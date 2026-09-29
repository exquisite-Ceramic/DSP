"""Product Front Door 的 configured local approval policy 与 admission composition。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from design_approval_scope import validate_approval_scope_boundary_v2
from design_changeset import canonical_hash, validate_changeset_integrity_v2
from design_gateway_authorization import ApprovalAdmission, compute_admission_fingerprint
from design_orchestrator.workflow_contracts import StableRef

_POLICY_VERSION = "DSP_PRODUCT_APPROVAL_POLICY_V1"
_POLICY_FIELDS = frozenset(
    {
        "version",
        "policy_id",
        "principal",
        "project_ids",
        "allowed_canonical_operations",
        "admission_ttl_seconds",
    }
)


def _config_error(message: str) -> ValueError:
    """返回稳定的 policy 配置错误，禁止缺失/畸形配置退化成 permissive fallback。"""

    return ValueError(f"FRONT_DOOR_APPROVAL_POLICY_CONFIG_INVALID: {message}")


def _non_blank(value: object, field_name: str) -> str:
    """规范化单个不可为空的字符串 authority 字段。"""

    if not isinstance(value, str) or not value.strip():
        raise _config_error(f"{field_name} must be a non-blank string")
    return value.strip()


def _normalized_unique_strings(value: object, field_name: str) -> tuple[str, ...]:
    """把 JSON array 规范化为排序后的唯一非空字符串 tuple，并拒绝重复 authority。"""

    if not isinstance(value, list) or not value:
        raise _config_error(f"{field_name} must be a non-empty list")

    normalized: list[str] = []
    for item in value:
        normalized.append(_non_blank(item, field_name))
    if len(set(normalized)) != len(normalized):
        raise _config_error(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


def _policy_hash_body(
    *,
    policy_id: str,
    principal: str,
    project_ids: tuple[str, ...],
    allowed_canonical_operations: tuple[str, ...],
    admission_ttl_seconds: int,
) -> dict[str, object]:
    """返回 `policy_snapshot_hash` 的唯一规范 authority body。"""

    return {
        "version": _POLICY_VERSION,
        "policy_id": policy_id,
        "principal": principal,
        "project_ids": list(project_ids),
        "allowed_canonical_operations": list(allowed_canonical_operations),
        "admission_ttl_seconds": admission_ttl_seconds,
    }


@dataclass(frozen=True, slots=True)
class ConfiguredProductApprovalPolicy:
    """本机 v1 configured-policy 的不可变、完整性受保护规范投影。"""

    version: str
    policy_id: str
    principal: str
    project_ids: tuple[str, ...]
    allowed_canonical_operations: tuple[str, ...]
    admission_ttl_seconds: int
    policy_snapshot_hash: str

    @classmethod
    def from_mapping(cls, payload: object) -> ConfiguredProductApprovalPolicy:
        """解析 exact v1 配置；任何缺失、未知或无效字段都默认拒绝新 admission issuance。"""

        if not isinstance(payload, Mapping):
            raise _config_error("policy config must be a mapping")
        if set(payload) != _POLICY_FIELDS:
            raise _config_error(
                "top-level keys do not match DSP_PRODUCT_APPROVAL_POLICY_V1"
            )
        if payload.get("version") != _POLICY_VERSION:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_VERSION_INVALID: "
                "unsupported policy config version"
            )

        policy_id = _non_blank(payload.get("policy_id"), "policy_id")
        principal = _non_blank(payload.get("principal"), "principal")
        project_ids = _normalized_unique_strings(
            payload.get("project_ids"),
            "project_ids",
        )
        allowed_operations = _normalized_unique_strings(
            payload.get("allowed_canonical_operations"),
            "allowed_canonical_operations",
        )
        ttl = payload.get("admission_ttl_seconds")
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
            raise _config_error("admission_ttl_seconds must be a positive integer")

        body = _policy_hash_body(
            policy_id=policy_id,
            principal=principal,
            project_ids=project_ids,
            allowed_canonical_operations=allowed_operations,
            admission_ttl_seconds=ttl,
        )
        return cls(
            version=_POLICY_VERSION,
            policy_id=policy_id,
            principal=principal,
            project_ids=project_ids,
            allowed_canonical_operations=allowed_operations,
            admission_ttl_seconds=ttl,
            policy_snapshot_hash=canonical_hash(body),
        )

    def authorize(
        self,
        *,
        project_id: str,
        required_canonical_operations: Iterable[str],
    ) -> None:
        """验证 project 与完整 canonical-operation 集合；任何不匹配都 fail closed。"""

        normalized_project_id = (
            project_id.strip() if isinstance(project_id, str) else ""
        )
        if not normalized_project_id or normalized_project_id not in self.project_ids:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: "
                "project is not authorized by configured policy"
            )

        try:
            raw_operations = tuple(required_canonical_operations)
        except TypeError as exc:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: "
                "required canonical operations are invalid"
            ) from exc
        if not raw_operations:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: "
                "required canonical operation set is empty"
            )

        normalized_operations: list[str] = []
        for operation in raw_operations:
            if not isinstance(operation, str) or not operation.strip():
                raise ValueError(
                    "FRONT_DOOR_APPROVAL_POLICY_DENIED: "
                    "required canonical operation is invalid"
                )
            normalized_operations.append(operation.strip())
        if len(set(normalized_operations)) != len(normalized_operations):
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: "
                "required canonical operations contain duplicates"
            )

        allowed = set(self.allowed_canonical_operations)
        if any(operation not in allowed for operation in normalized_operations):
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: configured policy does not "
                "authorize the complete canonical operation set"
            )


class ConfiguredPolicyApprovalAdmissionPort:
    """从 authoritative ChangeSet/scope 与 configured policy 签发 durable ApprovalAdmission。"""

    def __init__(
        self,
        *,
        changeset_store: object,
        approval_scope_store: object,
        admission_store: object,
        policy_source: object,
        clock: object,
        id_factory: object,
    ) -> None:
        """显式接收共享 owner stores；不得通过私有字段或并行 store graph 取业务真相。"""

        if not callable(getattr(changeset_store, "get", None)):
            raise TypeError("changeset_store must provide get")
        if not callable(getattr(approval_scope_store, "get_boundary", None)):
            raise TypeError("approval_scope_store must provide get_boundary")
        if any(
            not callable(getattr(admission_store, method_name, None))
            for method_name in ("get", "issue_or_get")
        ):
            raise TypeError("admission_store must provide get and issue_or_get")
        if not callable(getattr(policy_source, "load", None)):
            raise TypeError("policy_source must provide load")
        if not callable(getattr(clock, "now", None)):
            raise TypeError("clock must provide now")
        if not callable(id_factory):
            raise TypeError("id_factory must be callable")

        self._changeset_store = changeset_store
        self._approval_scope_store = approval_scope_store
        self._admission_store = admission_store
        self._policy_source = policy_source
        self._clock = clock
        self._id_factory = id_factory

    def request_approval(self, changeset_ref: StableRef) -> ApprovalAdmission:
        """按 exact final lineage replay 已签发 admission，或在 policy 授权后首次签发。"""

        changeset, boundary, required_operations = self._load_authoritative_lineage(
            changeset_ref
        )
        existing = self._admission_store.get(
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
        )
        if existing is not None:
            self._validate_replayed_admission(
                existing,
                changeset=changeset,
                boundary=boundary,
                required_operations=required_operations,
            )
            return existing

        policy = self._policy_source.load()
        if not isinstance(policy, ConfiguredProductApprovalPolicy):
            raise _config_error(
                "policy source did not return ConfiguredProductApprovalPolicy"
            )
        policy.authorize(
            project_id=changeset.project_id,
            required_canonical_operations=required_operations,
        )

        approved_at = self._clock.now()
        approved_at_text = self._canonical_utc(approved_at)
        expires_at_text = self._canonical_utc(
            approved_at + timedelta(seconds=policy.admission_ttl_seconds)
        )
        admission_id = self._id_factory()
        if not isinstance(admission_id, str) or not admission_id.strip():
            raise ValueError(
                "FRONT_DOOR_APPROVAL_ADMISSION_INVALID: "
                "id_factory returned a blank admission id"
            )

        draft = ApprovalAdmission(
            admission_id=admission_id.strip(),
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
            semantic_environment_ref=changeset.semantic_environment_ref,
            approver=policy.principal,
            policy_snapshot_hash=policy.policy_snapshot_hash,
            policy_allowed_operations=policy.allowed_canonical_operations,
            approved_at=approved_at_text,
            expires_at=expires_at_text,
            admission_fingerprint="0" * 64,
        )
        admission = replace(
            draft,
            admission_fingerprint=compute_admission_fingerprint(draft),
        )
        return self._admission_store.issue_or_get(admission)

    def _load_authoritative_lineage(
        self,
        changeset_ref: StableRef,
    ) -> tuple[object, object, tuple[str, ...]]:
        """从共享 owner stores 解析并校验 exact ChangeSet 与最终 ApprovalScope boundary。"""

        if not isinstance(changeset_ref, StableRef):
            raise TypeError("changeset_ref must be StableRef")
        if changeset_ref.content_hash is None:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: "
                "ChangeSet StableRef requires content hash"
            )

        changeset = self._changeset_store.get(changeset_ref.ref_id)
        if changeset.changeset_hash != changeset_ref.content_hash:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: ChangeSet StableRef hash mismatch"
            )
        boundary = self._approval_scope_store.get_boundary(
            f"SCOPE-{changeset.changeset_id}"
        )
        validate_approval_scope_boundary_v2(boundary)
        validate_changeset_integrity_v2(changeset, boundary)
        if boundary.changeset_hash != changeset.changeset_hash:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: "
                "final scope does not reference the ChangeSet"
            )

        required_operations = tuple(
            sorted(
                {
                    changeset.root_operation.canonical_operation,
                    *(
                        operation.canonical_operation
                        for operation in changeset.derived_operations
                    ),
                }
            )
        )
        if not required_operations:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: "
                "ChangeSet has no canonical operations"
            )
        return changeset, boundary, required_operations

    @staticmethod
    def _validate_replayed_admission(
        admission: ApprovalAdmission,
        *,
        changeset: object,
        boundary: object,
        required_operations: tuple[str, ...],
    ) -> None:
        """durable replay 不重读当前 policy，但重新证明 stored admission 属于该 owner lineage。"""

        if not isinstance(admission, ApprovalAdmission):
            raise TypeError("admission store returned an invalid approval admission")
        if compute_admission_fingerprint(admission) != admission.admission_fingerprint:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_ADMISSION_INTEGRITY_INVALID: "
                "replay fingerprint mismatch"
            )
        if admission.changeset_hash != changeset.changeset_hash:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: replay changeset hash mismatch"
            )
        if admission.approved_scope_hash != boundary.scope_hash:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: replay scope hash mismatch"
            )
        if admission.semantic_environment_ref != changeset.semantic_environment_ref:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: "
                "replay semantic environment mismatch"
            )
        if not set(required_operations).issubset(admission.policy_allowed_operations):
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: "
                "replay admission lacks operation authority"
            )

    @staticmethod
    def _canonical_utc(value: object) -> str:
        """把 injected clock 的 timezone-aware datetime 规范化成 Gateway 接受的 UTC Z 时间。"""

        if not isinstance(value, datetime) or value.tzinfo is None:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_CLOCK_INVALID: "
                "clock.now() must return timezone-aware datetime"
            )
        utc_value = value.astimezone(timezone.utc)
        return utc_value.isoformat().replace("+00:00", "Z")


__all__ = [
    "ConfiguredPolicyApprovalAdmissionPort",
    "ConfiguredProductApprovalPolicy",
]
