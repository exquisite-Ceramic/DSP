"""Cross-Host Product Vertical 的受审稳定配置；瞬态 runtime/transport 不属于长期 policy identity。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Protocol

from design_changeset import canonical_hash

_SHA256_HEX_LENGTH = 64
_REQUIRED_ROLES = {
    "REVIT": "INITIATOR",
    "AUTOCAD": "BOUND_REQUIRED",
}


def _non_blank(value: object, field_name: str) -> str:
    """把受审配置 locator 规范化为非空字符串。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"FRONT_DOOR_CROSS_HOST_CONFIG_INVALID: {field_name} must be non-blank"
        )
    return value.strip()


def _sha256(value: object, field_name: str) -> str:
    """只接受 canonical SHA-256 identity。"""

    normalized = _non_blank(value, field_name)
    if len(normalized) != _SHA256_HEX_LENGTH or any(
        char not in "0123456789abcdef" for char in normalized
    ):
        raise ValueError(
            f"FRONT_DOOR_CROSS_HOST_CONFIG_INVALID: "
            f"{field_name} must be lowercase SHA-256"
        )
    return normalized


def _absolute_document(value: object) -> str:
    """以 Windows/POSIX 双语义验证受审 saved-document identity。"""

    normalized = _non_blank(value, "document_id")
    if not (
        PureWindowsPath(normalized).is_absolute()
        or PurePosixPath(normalized).is_absolute()
    ):
        raise ValueError(
            "FRONT_DOOR_CROSS_HOST_CONFIG_INVALID: document_id must be absolute"
        )
    return normalized


@dataclass(frozen=True, slots=True)
class ConfiguredCrossHostMemberTarget:
    """一个受审 Host materialization target；transport locator 只用于本次连接。"""

    host_kind: str
    role: str
    configured_reference_id: str
    configured_reference_hash: str
    transport_locator: str
    document_id: str
    native_target_id: str

    def __post_init__(self) -> None:
        """验证稳定 target 字段，同时保留 transport 作为非 hash 的连接 locator。"""

        object.__setattr__(self, "host_kind", _non_blank(self.host_kind, "host_kind"))
        object.__setattr__(self, "role", _non_blank(self.role, "role"))
        object.__setattr__(
            self,
            "configured_reference_id",
            _non_blank(self.configured_reference_id, "configured_reference_id"),
        )
        object.__setattr__(
            self,
            "configured_reference_hash",
            _sha256(self.configured_reference_hash, "configured_reference_hash"),
        )
        object.__setattr__(
            self,
            "transport_locator",
            _non_blank(self.transport_locator, "transport_locator"),
        )
        object.__setattr__(self, "document_id", _absolute_document(self.document_id))
        object.__setattr__(
            self,
            "native_target_id",
            _non_blank(self.native_target_id, "native_target_id"),
        )


def _canonical_members(
    members: Sequence[ConfiguredCrossHostMemberTarget],
) -> tuple[ConfiguredCrossHostMemberTarget, ConfiguredCrossHostMemberTarget]:
    """要求 exact Revit+AutoCAD reviewed membership，并按 Host kind 排序。"""

    if isinstance(members, (str, bytes)) or not isinstance(members, Sequence):
        raise TypeError(
            "FRONT_DOOR_CROSS_HOST_CONFIG_INVALID: members must be a sequence"
        )
    normalized = tuple(members)
    if len(normalized) != 2 or any(
        not isinstance(member, ConfiguredCrossHostMemberTarget)
        for member in normalized
    ):
        raise ValueError(
            "FRONT_DOOR_CROSS_HOST_CONFIG_INVALID: exactly two members are required"
        )
    by_kind = {member.host_kind: member for member in normalized}
    if len(by_kind) != 2 or set(by_kind) != {"AUTOCAD", "REVIT"}:
        raise ValueError(
            "FRONT_DOOR_CROSS_HOST_CONFIG_INVALID: members must be AUTOCAD and REVIT"
        )
    for host_kind, role in _REQUIRED_ROLES.items():
        if by_kind[host_kind].role != role:
            raise ValueError(
                "FRONT_DOOR_CROSS_HOST_CONFIG_INVALID: "
                f"{host_kind} role must be {role}"
            )
    return by_kind["AUTOCAD"], by_kind["REVIT"]


def _stable_member_body(member: ConfiguredCrossHostMemberTarget) -> dict[str, str]:
    """返回长期配置 identity；明确排除 transient transport locator。"""

    return {
        "host_kind": member.host_kind,
        "role": member.role,
        "configured_reference_id": member.configured_reference_id,
        "configured_reference_hash": member.configured_reference_hash,
        "document_id": member.document_id,
        "native_target_id": member.native_target_id,
    }


def reviewed_cross_host_configuration_hash_body(
    *,
    candidate_key: str,
    project_id: str,
    semantic_target_id: str,
    semantic_environment_id: str,
    semantic_environment_hash: str,
    topology_environment_id: str,
    topology_revision: int,
    topology_snapshot_hash: str,
    members: Sequence[ConfiguredCrossHostMemberTarget],
) -> dict[str, object]:
    """返回 V2 stable policy/reviewed configuration body；runtime endpoint 不参与。"""

    ordered = _canonical_members(members)
    return {
        "candidate_key": candidate_key,
        "project_id": project_id,
        "semantic_target_id": semantic_target_id,
        "semantic_environment_id": semantic_environment_id,
        "semantic_environment_hash": semantic_environment_hash,
        "topology_environment_id": topology_environment_id,
        "topology_revision": topology_revision,
        "topology_snapshot_hash": topology_snapshot_hash,
        "members": [_stable_member_body(member) for member in ordered],
    }


@dataclass(frozen=True, slots=True)
class ConfiguredCrossHostWallThicknessTarget:
    """Revit-entry 双 Host vertical 的 exact reviewed target 配置。"""

    candidate_key: str
    project_id: str
    semantic_target_id: str
    semantic_environment_id: str
    semantic_environment_hash: str
    topology_environment_id: str
    topology_revision: int
    topology_snapshot_hash: str
    members: tuple[
        ConfiguredCrossHostMemberTarget,
        ConfiguredCrossHostMemberTarget,
    ]
    reviewed_configuration_hash: str

    def __post_init__(self) -> None:
        """验证完整 stable body；transport 变化不得改变 reviewed hash。"""

        candidate_key = _non_blank(self.candidate_key, "candidate_key")
        project_id = _non_blank(self.project_id, "project_id")
        semantic_target_id = _non_blank(self.semantic_target_id, "semantic_target_id")
        semantic_environment_id = _non_blank(
            self.semantic_environment_id,
            "semantic_environment_id",
        )
        semantic_environment_hash = _sha256(
            self.semantic_environment_hash,
            "semantic_environment_hash",
        )
        topology_environment_id = _non_blank(
            self.topology_environment_id,
            "topology_environment_id",
        )
        if (
            isinstance(self.topology_revision, bool)
            or not isinstance(self.topology_revision, int)
            or self.topology_revision < 0
        ):
            raise ValueError(
                "FRONT_DOOR_CROSS_HOST_CONFIG_INVALID: "
                "topology_revision must be a non-negative integer"
            )
        topology_snapshot_hash = _sha256(
            self.topology_snapshot_hash,
            "topology_snapshot_hash",
        )
        members = _canonical_members(self.members)
        reviewed_hash = _sha256(
            self.reviewed_configuration_hash,
            "reviewed_configuration_hash",
        )
        expected_hash = canonical_hash(
            reviewed_cross_host_configuration_hash_body(
                candidate_key=candidate_key,
                project_id=project_id,
                semantic_target_id=semantic_target_id,
                semantic_environment_id=semantic_environment_id,
                semantic_environment_hash=semantic_environment_hash,
                topology_environment_id=topology_environment_id,
                topology_revision=self.topology_revision,
                topology_snapshot_hash=topology_snapshot_hash,
                members=members,
            )
        )
        if reviewed_hash != expected_hash:
            raise ValueError(
                "FRONT_DOOR_CROSS_HOST_CONFIG_INVALID: "
                "reviewed_configuration_hash does not match stable body"
            )

        object.__setattr__(self, "candidate_key", candidate_key)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "semantic_target_id", semantic_target_id)
        object.__setattr__(self, "semantic_environment_id", semantic_environment_id)
        object.__setattr__(self, "semantic_environment_hash", semantic_environment_hash)
        object.__setattr__(self, "topology_environment_id", topology_environment_id)
        object.__setattr__(self, "topology_snapshot_hash", topology_snapshot_hash)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "reviewed_configuration_hash", reviewed_hash)

    @classmethod
    def create(
        cls,
        *,
        candidate_key: str,
        project_id: str,
        semantic_target_id: str,
        semantic_environment_id: str,
        semantic_environment_hash: str,
        topology_environment_id: str,
        topology_revision: int,
        topology_snapshot_hash: str,
        members: Sequence[ConfiguredCrossHostMemberTarget],
    ) -> "ConfiguredCrossHostWallThicknessTarget":
        """根据稳定 reviewed body 计算 identity；transport locator 只随对象携带。"""

        ordered = _canonical_members(members)
        body = reviewed_cross_host_configuration_hash_body(
            candidate_key=_non_blank(candidate_key, "candidate_key"),
            project_id=_non_blank(project_id, "project_id"),
            semantic_target_id=_non_blank(semantic_target_id, "semantic_target_id"),
            semantic_environment_id=_non_blank(
                semantic_environment_id,
                "semantic_environment_id",
            ),
            semantic_environment_hash=_sha256(
                semantic_environment_hash,
                "semantic_environment_hash",
            ),
            topology_environment_id=_non_blank(
                topology_environment_id,
                "topology_environment_id",
            ),
            topology_revision=topology_revision,
            topology_snapshot_hash=_sha256(
                topology_snapshot_hash,
                "topology_snapshot_hash",
            ),
            members=ordered,
        )
        return cls(
            candidate_key=body["candidate_key"],
            project_id=body["project_id"],
            semantic_target_id=body["semantic_target_id"],
            semantic_environment_id=body["semantic_environment_id"],
            semantic_environment_hash=body["semantic_environment_hash"],
            topology_environment_id=body["topology_environment_id"],
            topology_revision=body["topology_revision"],
            topology_snapshot_hash=body["topology_snapshot_hash"],
            members=ordered,
            reviewed_configuration_hash=canonical_hash(body),
        )

    def member(self, host_kind: str) -> ConfiguredCrossHostMemberTarget:
        """按 exact Host kind 返回 reviewed member；不提供 fuzzy/latest fallback。"""

        normalized = _non_blank(host_kind, "host_kind")
        for member in self.members:
            if member.host_kind == normalized:
                return member
        raise KeyError(f"reviewed cross-host member not found: {normalized}")


class ConfiguredCrossHostWallThicknessTargetSource(Protocol):
    """按 deterministic candidate_key 返回 exact cross-Host reviewed target。"""

    def get(
        self,
        candidate_key: str,
    ) -> ConfiguredCrossHostWallThicknessTarget | None:
        """未知 key 返回 None；禁止 latest/fuzzy fallback。"""

        ...


__all__ = [
    "ConfiguredCrossHostMemberTarget",
    "ConfiguredCrossHostWallThicknessTarget",
    "ConfiguredCrossHostWallThicknessTargetSource",
    "reviewed_cross_host_configuration_hash_body",
]
