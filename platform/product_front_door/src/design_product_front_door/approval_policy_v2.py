"""Cross-Host Product Vertical 的显式 V2 configured policy 与 durable admission port。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta

from design_changeset import canonical_hash
from design_gateway_authorization import (
    ApprovalAdmission,
    compute_admission_fingerprint,
)
from design_product_runtime.accepted_input import AcceptedProductTaskInputV2

from .approval_policy import (
    ConfiguredPolicyApprovalAdmissionPort,
    _config_error,
)
from .contracts import SessionBindingMemberV2, SessionBindingV2

_POLICY_VERSION = "DSP_PRODUCT_APPROVAL_POLICY_V2"
_POLICY_FIELDS = frozenset(
    {
        "version",
        "policy_id",
        "principal",
        "project_ids",
        "allowed_canonical_operations",
        "reviewed_configuration_hash",
        "semantic_target_ids",
        "allowed_topology_snapshot_hashes",
        "required_host_roles",
        "admission_ttl_seconds",
    }
)
_REQUIRED_HOST_ROLES = {
    "AUTOCAD": "BOUND_REQUIRED",
    "REVIT": "INITIATOR",
}
_HEX_DIGITS = frozenset("0123456789abcdef")


def _non_blank(value: object, field_name: str) -> str:
    """规范化 V2 policy 的稳定字符串字段。"""

    if not isinstance(value, str) or not value.strip():
        raise _config_error(f"{field_name} must be a non-blank string")
    return value.strip()


def _sha256(value: object, field_name: str) -> str:
    """只接受规范 lowercase SHA-256，避免 topology/config ref 模糊比较。"""

    normalized = _non_blank(value, field_name)
    if len(normalized) != 64 or any(char not in _HEX_DIGITS for char in normalized):
        raise _config_error(f"{field_name} must be lowercase SHA-256")
    return normalized


def _unique_strings(value: object, field_name: str) -> tuple[str, ...]:
    """把非空 JSON list 规范为排序唯一 tuple，并拒绝重复 authority。"""

    if not isinstance(value, list) or not value:
        raise _config_error(f"{field_name} must be a non-empty list")
    normalized = tuple(_non_blank(item, field_name) for item in value)
    if len(set(normalized)) != len(normalized):
        raise _config_error(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


def _unique_hashes(value: object, field_name: str) -> tuple[str, ...]:
    """把 topology allowlist 规范为排序唯一 hash tuple。"""

    if not isinstance(value, list) or not value:
        raise _config_error(f"{field_name} must be a non-empty list")
    normalized = tuple(_sha256(item, field_name) for item in value)
    if len(set(normalized)) != len(normalized):
        raise _config_error(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


def _host_roles(value: object) -> tuple[tuple[str, str], ...]:
    """规范化 required Host roles；本 vertical 只允许 exact AutoCAD+Revit。"""

    if not isinstance(value, Mapping):
        raise _config_error("required_host_roles must be a mapping")
    normalized = {
        _non_blank(host, "required_host_roles.host"): _non_blank(
            role,
            "required_host_roles.role",
        )
        for host, role in value.items()
    }
    if normalized != _REQUIRED_HOST_ROLES:
        raise _config_error(
            "required_host_roles must be exact AUTOCAD=BOUND_REQUIRED, REVIT=INITIATOR"
        )
    return tuple(sorted(normalized.items()))


def _policy_body(
    *,
    policy_id: str,
    principal: str,
    project_ids: tuple[str, ...],
    allowed_canonical_operations: tuple[str, ...],
    reviewed_configuration_hash: str,
    semantic_target_ids: tuple[str, ...],
    allowed_topology_snapshot_hashes: tuple[str, ...],
    required_host_roles: tuple[tuple[str, str], ...],
    admission_ttl_seconds: int,
) -> dict[str, object]:
    """返回 V2 policy snapshot 的唯一 canonical authority body。"""

    return {
        "version": _POLICY_VERSION,
        "policy_id": policy_id,
        "principal": principal,
        "project_ids": list(project_ids),
        "allowed_canonical_operations": list(allowed_canonical_operations),
        "reviewed_configuration_hash": reviewed_configuration_hash,
        "semantic_target_ids": list(semantic_target_ids),
        "allowed_topology_snapshot_hashes": list(
            allowed_topology_snapshot_hashes
        ),
        "required_host_roles": dict(required_host_roles),
        "admission_ttl_seconds": admission_ttl_seconds,
    }


@dataclass(frozen=True, slots=True)
class ConfiguredProductApprovalPolicyV2:
    """只授权稳定 cross-Host capability 维度的不可变 V2 policy snapshot。"""

    version: str
    policy_id: str
    principal: str
    project_ids: tuple[str, ...]
    allowed_canonical_operations: tuple[str, ...]
    reviewed_configuration_hash: str
    semantic_target_ids: tuple[str, ...]
    allowed_topology_snapshot_hashes: tuple[str, ...]
    required_host_roles: tuple[tuple[str, str], ...]
    admission_ttl_seconds: int
    policy_snapshot_hash: str

    @classmethod
    def from_mapping(cls, payload: object) -> "ConfiguredProductApprovalPolicyV2":
        """解析 strict V2 config；未知字段与 transient runtime 字段均 fail closed。"""

        if not isinstance(payload, Mapping):
            raise _config_error("policy config must be a mapping")
        if set(payload) != _POLICY_FIELDS:
            raise _config_error(
                "top-level keys do not match DSP_PRODUCT_APPROVAL_POLICY_V2"
            )
        if payload.get("version") != _POLICY_VERSION:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_VERSION_INVALID: "
                "unsupported policy config version"
            )

        policy_id = _non_blank(payload.get("policy_id"), "policy_id")
        principal = _non_blank(payload.get("principal"), "principal")
        project_ids = _unique_strings(payload.get("project_ids"), "project_ids")
        operations = _unique_strings(
            payload.get("allowed_canonical_operations"),
            "allowed_canonical_operations",
        )
        reviewed_hash = _sha256(
            payload.get("reviewed_configuration_hash"),
            "reviewed_configuration_hash",
        )
        semantic_targets = _unique_strings(
            payload.get("semantic_target_ids"),
            "semantic_target_ids",
        )
        topology_hashes = _unique_hashes(
            payload.get("allowed_topology_snapshot_hashes"),
            "allowed_topology_snapshot_hashes",
        )
        host_roles = _host_roles(payload.get("required_host_roles"))
        ttl = payload.get("admission_ttl_seconds")
        if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
            raise _config_error("admission_ttl_seconds must be a positive integer")

        body = _policy_body(
            policy_id=policy_id,
            principal=principal,
            project_ids=project_ids,
            allowed_canonical_operations=operations,
            reviewed_configuration_hash=reviewed_hash,
            semantic_target_ids=semantic_targets,
            allowed_topology_snapshot_hashes=topology_hashes,
            required_host_roles=host_roles,
            admission_ttl_seconds=ttl,
        )
        return cls(
            version=_POLICY_VERSION,
            policy_id=policy_id,
            principal=principal,
            project_ids=project_ids,
            allowed_canonical_operations=operations,
            reviewed_configuration_hash=reviewed_hash,
            semantic_target_ids=semantic_targets,
            allowed_topology_snapshot_hashes=topology_hashes,
            required_host_roles=host_roles,
            admission_ttl_seconds=ttl,
            policy_snapshot_hash=canonical_hash(body),
        )

    def snapshot_payload(self) -> dict[str, object]:
        """导出签发时必须 durability-preserve 的 canonical policy body。"""

        return _policy_body(
            policy_id=self.policy_id,
            principal=self.principal,
            project_ids=self.project_ids,
            allowed_canonical_operations=self.allowed_canonical_operations,
            reviewed_configuration_hash=self.reviewed_configuration_hash,
            semantic_target_ids=self.semantic_target_ids,
            allowed_topology_snapshot_hashes=self.allowed_topology_snapshot_hashes,
            required_host_roles=self.required_host_roles,
            admission_ttl_seconds=self.admission_ttl_seconds,
        )

    def authorize(
        self,
        *,
        project_id: str,
        required_canonical_operations: Iterable[str],
        semantic_target_id: str,
        topology_snapshot_hash: str,
        required_host_roles: Mapping[str, str],
    ) -> None:
        """验证完整 stable product authority；任何维度不匹配都默认拒绝。"""

        project = _non_blank(project_id, "project_id")
        if project not in self.project_ids:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: project is not authorized"
            )

        try:
            raw_operations = tuple(required_canonical_operations)
        except TypeError as exc:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: invalid operation set"
            ) from exc
        if not raw_operations:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: operation set is empty"
            )
        operations = tuple(
            _non_blank(item, "required_canonical_operations")
            for item in raw_operations
        )
        if len(set(operations)) != len(operations):
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: duplicate operations"
            )
        if not set(operations).issubset(self.allowed_canonical_operations):
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: operation is not authorized"
            )

        target = _non_blank(semantic_target_id, "semantic_target_id")
        if target not in self.semantic_target_ids:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: semantic target is not authorized"
            )

        topology_hash = _sha256(topology_snapshot_hash, "topology_snapshot_hash")
        if topology_hash not in self.allowed_topology_snapshot_hashes:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: topology is not authorized"
            )

        normalized_roles = tuple(
            sorted(
                (
                    _non_blank(host, "required_host_roles.host"),
                    _non_blank(role, "required_host_roles.role"),
                )
                for host, role in required_host_roles.items()
            )
        )
        if normalized_roles != self.required_host_roles:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: required Host roles mismatch"
            )


@dataclass(frozen=True, slots=True)
class _AcceptedPolicyContext:
    """从 ProductTask accepted input 投影出的 stable policy comparison dimensions。"""

    semantic_target_id: str
    topology_snapshot_hash: str
    required_host_roles: Mapping[str, str]


def _binding_from_accepted(accepted: AcceptedProductTaskInputV2) -> SessionBindingV2:
    """从 server-owned immutable binding body 重建 exact SessionBindingV2。"""

    payload = accepted.session_binding_payload
    raw_members = payload.get("members")
    if not isinstance(raw_members, list):
        raise ValueError(
            "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: accepted binding members invalid"
        )
    members = []
    for raw in raw_members:
        if not isinstance(raw, Mapping):
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: accepted binding member invalid"
            )
        members.append(
            SessionBindingMemberV2(
                host_kind=raw.get("host_kind"),
                role=raw.get("role"),
                configured_reference_id=raw.get("configured_reference_id"),
                configured_reference_hash=raw.get("configured_reference_hash"),
                transport_locator=raw.get("transport_locator"),
                host_instance_id=raw.get("host_instance_id"),
                document_id=raw.get("document_id"),
                native_target_id=raw.get("native_target_id"),
                host_binding_fingerprint=raw.get("host_binding_fingerprint"),
            )
        )
    return SessionBindingV2(
        session_ref=payload.get("session_ref"),
        project_id=payload.get("project_id"),
        semantic_target_id=payload.get("semantic_target_id"),
        semantic_environment_id=payload.get("semantic_environment_id"),
        semantic_environment_hash=payload.get("semantic_environment_hash"),
        topology_environment_id=payload.get("topology_environment_id"),
        topology_revision=payload.get("topology_revision"),
        topology_snapshot_hash=payload.get("topology_snapshot_hash"),
        initiating_host_kind=payload.get("initiating_host_kind"),
        members=tuple(members),
        binding_hash=payload.get("binding_hash"),
    )


class ConfiguredPolicyApprovalAdmissionPortV2(ConfiguredPolicyApprovalAdmissionPort):
    """用 V2 stable policy + accepted binding 签发现有 Gateway ApprovalAdmission。"""

    def __init__(
        self,
        *,
        changeset_store: object,
        approval_scope_store: object,
        admission_store: object,
        accepted_input_reader: object,
        policy_source: object,
        clock: object,
        id_factory: object,
    ) -> None:
        """复用 V1 lineage helpers，但显式增加 server-owned accepted-input authority。"""

        super().__init__(
            changeset_store=changeset_store,
            approval_scope_store=approval_scope_store,
            admission_store=admission_store,
            policy_source=policy_source,
            clock=clock,
            id_factory=id_factory,
        )
        if not callable(getattr(accepted_input_reader, "get_v2", None)):
            raise TypeError("accepted_input_reader must provide get_v2")
        for method_name in ("get_v2", "issue_or_get_v2"):
            if not callable(getattr(admission_store, method_name, None)):
                raise TypeError(
                    f"admission_store must provide {method_name} for V2"
                )
        self._accepted_input_reader = accepted_input_reader

    def request_approval(self, changeset_ref) -> ApprovalAdmission:
        """replay durable V2 snapshot，或验证 stable task context 后首次签发。"""

        changeset, boundary, required_operations = self._load_authoritative_lineage(
            changeset_ref
        )
        context = self._accepted_context(
            task_id=changeset.task_id,
            changeset=changeset,
            boundary=boundary,
        )

        existing_v2 = self._admission_store.get_v2(
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
        )
        if existing_v2 is not None:
            admission = existing_v2.admission
            self._validate_replayed_admission(
                admission,
                changeset=changeset,
                boundary=boundary,
                required_operations=required_operations,
            )
            policy = ConfiguredProductApprovalPolicyV2.from_mapping(
                existing_v2.policy_snapshot_payload
            )
            if policy.version != existing_v2.policy_version:
                raise ValueError(
                    "FRONT_DOOR_APPROVAL_ADMISSION_INTEGRITY_INVALID: "
                    "stored V2 policy version mismatch"
                )
            if policy.policy_snapshot_hash != admission.policy_snapshot_hash:
                raise ValueError(
                    "FRONT_DOOR_APPROVAL_ADMISSION_INTEGRITY_INVALID: "
                    "stored policy body hash mismatch"
                )
            self._authorize_context(
                policy,
                changeset=changeset,
                boundary=boundary,
                required_operations=required_operations,
                context=context,
            )
            return admission

        existing_any = self._admission_store.get(
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
        )
        if existing_any is not None:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_VERSION_INVALID: "
                "existing V1 admission cannot authorize V2"
            )

        policy = self._policy_source.load()
        if not isinstance(policy, ConfiguredProductApprovalPolicyV2):
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_VERSION_INVALID: "
                "V2 task requires ConfiguredProductApprovalPolicyV2"
            )
        self._authorize_context(
            policy,
            changeset=changeset,
            boundary=boundary,
            required_operations=required_operations,
            context=context,
        )

        approved_at = self._clock.now()
        approved_at_text = self._canonical_utc(approved_at)
        expires_at_text = self._canonical_utc(
            approved_at + timedelta(seconds=policy.admission_ttl_seconds)
        )
        admission_id = self._id_factory()
        if not isinstance(admission_id, str) or not admission_id.strip():
            raise ValueError(
                "FRONT_DOOR_APPROVAL_ADMISSION_INVALID: blank admission id"
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
        stored = self._admission_store.issue_or_get_v2(
            admission,
            policy_version=policy.version,
            policy_snapshot_payload=policy.snapshot_payload(),
        )
        return stored.admission

    def _accepted_context(
        self,
        *,
        task_id: str,
        changeset: object,
        boundary: object,
    ) -> _AcceptedPolicyContext:
        """从 exact task 的 immutable accepted binding 投影 stable policy dimensions。"""

        accepted = self._accepted_input_reader.get_v2(task_id)
        if not isinstance(accepted, AcceptedProductTaskInputV2):
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: V2 accepted input is missing"
            )
        binding = _binding_from_accepted(accepted)
        if accepted.request.project_id != changeset.project_id:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: project mismatch"
            )
        if binding.project_id != changeset.project_id:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: binding project mismatch"
            )
        if binding.topology_snapshot_hash != boundary.topology_snapshot_hash:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: topology mismatch"
            )
        if binding.semantic_target_id not in changeset.root_operation.targets:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_LINEAGE_INVALID: semantic target mismatch"
            )
        return _AcceptedPolicyContext(
            semantic_target_id=binding.semantic_target_id,
            topology_snapshot_hash=binding.topology_snapshot_hash,
            required_host_roles={
                member.host_kind: member.role for member in binding.members
            },
        )

    @staticmethod
    def _authorize_context(
        policy: ConfiguredProductApprovalPolicyV2,
        *,
        changeset: object,
        boundary: object,
        required_operations: tuple[str, ...],
        context: _AcceptedPolicyContext,
    ) -> None:
        """把 final ChangeSet/scope 与 accepted stable Host set 一起交给 policy。"""

        policy.authorize(
            project_id=changeset.project_id,
            required_canonical_operations=required_operations,
            semantic_target_id=context.semantic_target_id,
            topology_snapshot_hash=boundary.topology_snapshot_hash,
            required_host_roles=context.required_host_roles,
        )


__all__ = [
    "ConfiguredPolicyApprovalAdmissionPortV2",
    "ConfiguredProductApprovalPolicyV2",
]
