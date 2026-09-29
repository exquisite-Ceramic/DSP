"""Product Front Door 的 configured local approval policy authority。"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from design_changeset import canonical_hash

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
            raise _config_error("top-level keys do not match DSP_PRODUCT_APPROVAL_POLICY_V1")
        if payload.get("version") != _POLICY_VERSION:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_VERSION_INVALID: unsupported policy config version"
            )

        policy_id = _non_blank(payload.get("policy_id"), "policy_id")
        principal = _non_blank(payload.get("principal"), "principal")
        project_ids = _normalized_unique_strings(payload.get("project_ids"), "project_ids")
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

        normalized_project_id = project_id.strip() if isinstance(project_id, str) else ""
        if not normalized_project_id or normalized_project_id not in self.project_ids:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: project is not authorized by configured policy"
            )

        try:
            raw_operations = tuple(required_canonical_operations)
        except TypeError as exc:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: required canonical operations are invalid"
            ) from exc
        if not raw_operations:
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: required canonical operation set is empty"
            )

        normalized_operations: list[str] = []
        for operation in raw_operations:
            if not isinstance(operation, str) or not operation.strip():
                raise ValueError(
                    "FRONT_DOOR_APPROVAL_POLICY_DENIED: required canonical operation is invalid"
                )
            normalized_operations.append(operation.strip())
        if len(set(normalized_operations)) != len(normalized_operations):
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: required canonical operations contain duplicates"
            )

        allowed = set(self.allowed_canonical_operations)
        if any(operation not in allowed for operation in normalized_operations):
            raise ValueError(
                "FRONT_DOOR_APPROVAL_POLICY_DENIED: configured policy does not authorize the complete canonical operation set"
            )


__all__ = ["ConfiguredProductApprovalPolicy"]
