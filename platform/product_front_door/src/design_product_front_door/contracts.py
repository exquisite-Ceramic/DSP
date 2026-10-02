"""Product Front Door 的 immutable candidate / session authority 契约。"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Protocol

from design_changeset import canonical_hash

_SHA256_HEX_LENGTH = 64
_HOST_KIND_REVIT = "REVIT"


def _non_blank(value: object, *, code: str, field_name: str) -> str:
    """把 authority 字段规范化为去除首尾空白的非空字符串。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{code}: {field_name} must be a non-blank string")
    return value.strip()


def _sha256_hex(value: object, *, code: str, field_name: str) -> str:
    """只接受 canonical_hash 产生的 64 位小写十六进制 SHA-256。"""

    normalized = _non_blank(value, code=code, field_name=field_name)
    if len(normalized) != _SHA256_HEX_LENGTH or any(
        character not in "0123456789abcdef" for character in normalized
    ):
        raise ValueError(f"{code}: {field_name} must be a lowercase SHA-256 hex digest")
    return normalized


def _absolute_document_id(value: object) -> str:
    """按 Windows/POSIX 路径语义验证 saved-document identity，而不是按 CI Host OS 猜测。"""

    normalized = _non_blank(
        value,
        code="FRONT_DOOR_DOCUMENT_ID_INVALID",
        field_name="document_id",
    )
    if not (
        PureWindowsPath(normalized).is_absolute()
        or PurePosixPath(normalized).is_absolute()
    ):
        raise ValueError(
            "FRONT_DOOR_DOCUMENT_ID_INVALID: document_id must be an absolute saved-document path"
        )
    return normalized


def configured_revit_candidate_hash_body(
    *,
    candidate_key: str,
    project_id: str,
    transport_locator: str,
    document_id: str,
    semantic_target_id: str,
    native_target_unique_id: str,
) -> dict[str, str]:
    """返回 candidate_hash 的唯一规范 body；transport locator 仅是连接定位信息。"""

    return {
        "candidate_key": candidate_key,
        "project_id": project_id,
        "transport_locator": transport_locator,
        "document_id": document_id,
        "semantic_target_id": semantic_target_id,
        "native_target_unique_id": native_target_unique_id,
    }


def session_binding_hash_body(
    *,
    session_ref: str,
    project_id: str,
    host_kind: str,
    candidate_key: str,
    candidate_hash: str,
    transport_locator: str,
    host_instance_id: str,
    document_id: str,
) -> dict[str, str]:
    """返回 binding_hash 的唯一 authority body；document_title 明确不参与身份哈希。"""

    return {
        "session_ref": session_ref,
        "project_id": project_id,
        "host_kind": host_kind,
        "candidate_key": candidate_key,
        "candidate_hash": candidate_hash,
        "transport_locator": transport_locator,
        "host_instance_id": host_instance_id,
        "document_id": document_id,
    }


@dataclass(frozen=True, slots=True)
class ConfiguredRevitCandidate:
    """确定性的本机 Revit 候选配置；locator 永远不充当 Host 身份证明。"""

    candidate_key: str
    project_id: str
    transport_locator: str
    document_id: str
    semantic_target_id: str
    native_target_unique_id: str
    candidate_hash: str

    def __post_init__(self) -> None:
        """规范化全部 authority 字段，并验证 supplied hash 与完整 body 精确一致。"""

        candidate_key = _non_blank(
            self.candidate_key,
            code="FRONT_DOOR_CANDIDATE_CONFIG_INVALID",
            field_name="candidate_key",
        )
        project_id = _non_blank(
            self.project_id,
            code="FRONT_DOOR_CANDIDATE_CONFIG_INVALID",
            field_name="project_id",
        )
        transport_locator = _non_blank(
            self.transport_locator,
            code="FRONT_DOOR_CANDIDATE_CONFIG_INVALID",
            field_name="transport_locator",
        )
        document_id = _absolute_document_id(self.document_id)
        semantic_target_id = _non_blank(
            self.semantic_target_id,
            code="FRONT_DOOR_CANDIDATE_CONFIG_INVALID",
            field_name="semantic_target_id",
        )
        native_target_unique_id = _non_blank(
            self.native_target_unique_id,
            code="FRONT_DOOR_CANDIDATE_CONFIG_INVALID",
            field_name="native_target_unique_id",
        )
        candidate_hash = _sha256_hex(
            self.candidate_hash,
            code="FRONT_DOOR_CANDIDATE_HASH_INVALID",
            field_name="candidate_hash",
        )

        normalized_body = configured_revit_candidate_hash_body(
            candidate_key=candidate_key,
            project_id=project_id,
            transport_locator=transport_locator,
            document_id=document_id,
            semantic_target_id=semantic_target_id,
            native_target_unique_id=native_target_unique_id,
        )
        expected_hash = canonical_hash(normalized_body)
        if candidate_hash != expected_hash:
            raise ValueError(
                "FRONT_DOOR_CANDIDATE_HASH_INVALID: candidate_hash does not match authority body"
            )

        object.__setattr__(self, "candidate_key", candidate_key)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "transport_locator", transport_locator)
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "semantic_target_id", semantic_target_id)
        object.__setattr__(self, "native_target_unique_id", native_target_unique_id)
        object.__setattr__(self, "candidate_hash", candidate_hash)


def session_binding_member_v2_hash_body(
    member: "SessionBindingMemberV2",
) -> dict[str, str]:
    """把一个 V2 Host member 投影为 binding_hash 的稳定规范 body。"""

    return {
        "host_kind": member.host_kind,
        "role": member.role,
        "configured_reference_id": member.configured_reference_id,
        "configured_reference_hash": member.configured_reference_hash,
        "transport_locator": member.transport_locator,
        "host_instance_id": member.host_instance_id,
        "document_id": member.document_id,
        "native_target_id": member.native_target_id,
        "host_binding_fingerprint": member.host_binding_fingerprint,
    }


@dataclass(frozen=True, slots=True)
class SessionBindingMemberV2:
    """V2 session 中一个 REQUIRED Host 的 exact runtime/document/target 冻结成员。"""

    host_kind: str
    role: str
    configured_reference_id: str
    configured_reference_hash: str
    transport_locator: str
    host_instance_id: str
    document_id: str
    native_target_id: str
    host_binding_fingerprint: str

    def __post_init__(self) -> None:
        """规范化 member authority；Host 集合与角色约束由 SessionBindingV2 统一判断。"""

        object.__setattr__(
            self,
            "host_kind",
            _non_blank(
                self.host_kind,
                code="FRONT_DOOR_BINDING_V2_INVALID",
                field_name="host_kind",
            ),
        )
        object.__setattr__(
            self,
            "role",
            _non_blank(
                self.role,
                code="FRONT_DOOR_BINDING_V2_INVALID",
                field_name="role",
            ),
        )
        object.__setattr__(
            self,
            "configured_reference_id",
            _non_blank(
                self.configured_reference_id,
                code="FRONT_DOOR_BINDING_V2_INVALID",
                field_name="configured_reference_id",
            ),
        )
        object.__setattr__(
            self,
            "configured_reference_hash",
            _sha256_hex(
                self.configured_reference_hash,
                code="FRONT_DOOR_BINDING_V2_INVALID",
                field_name="configured_reference_hash",
            ),
        )
        object.__setattr__(
            self,
            "transport_locator",
            _non_blank(
                self.transport_locator,
                code="FRONT_DOOR_BINDING_V2_INVALID",
                field_name="transport_locator",
            ),
        )
        object.__setattr__(
            self,
            "host_instance_id",
            _non_blank(
                self.host_instance_id,
                code="FRONT_DOOR_BINDING_V2_INVALID",
                field_name="host_instance_id",
            ),
        )
        object.__setattr__(self, "document_id", _absolute_document_id(self.document_id))
        object.__setattr__(
            self,
            "native_target_id",
            _non_blank(
                self.native_target_id,
                code="FRONT_DOOR_BINDING_V2_INVALID",
                field_name="native_target_id",
            ),
        )
        object.__setattr__(
            self,
            "host_binding_fingerprint",
            _sha256_hex(
                self.host_binding_fingerprint,
                code="FRONT_DOOR_BINDING_V2_INVALID",
                field_name="host_binding_fingerprint",
            ),
        )


def _canonical_v2_members(
    members: Sequence[SessionBindingMemberV2],
) -> tuple[SessionBindingMemberV2, SessionBindingMemberV2]:
    """要求 exact AutoCAD+Revit REQUIRED 成员，并按 Host kind 冻结稳定排序。"""

    if isinstance(members, (str, bytes)) or not isinstance(members, Sequence):
        raise TypeError("FRONT_DOOR_BINDING_V2_INVALID: members must be a sequence")
    normalized = tuple(members)
    if len(normalized) != 2 or any(
        not isinstance(member, SessionBindingMemberV2) for member in normalized
    ):
        raise ValueError(
            "FRONT_DOOR_BINDING_V2_INVALID: binding requires exactly two Host members"
        )
    by_kind = {member.host_kind: member for member in normalized}
    if len(by_kind) != 2 or set(by_kind) != {"AUTOCAD", "REVIT"}:
        raise ValueError(
            "FRONT_DOOR_BINDING_V2_INVALID: members must be exact AUTOCAD and REVIT"
        )
    if by_kind["REVIT"].role != "INITIATOR":
        raise ValueError(
            "FRONT_DOOR_BINDING_V2_INVALID: REVIT member role must be INITIATOR"
        )
    if by_kind["AUTOCAD"].role != "BOUND_REQUIRED":
        raise ValueError(
            "FRONT_DOOR_BINDING_V2_INVALID: AUTOCAD member role must be BOUND_REQUIRED"
        )
    return by_kind["AUTOCAD"], by_kind["REVIT"]


def session_binding_v2_hash_body(
    *,
    session_ref: str,
    project_id: str,
    semantic_target_id: str,
    semantic_environment_id: str,
    semantic_environment_hash: str,
    topology_environment_id: str,
    topology_revision: int,
    topology_snapshot_hash: str,
    initiating_host_kind: str,
    members: Sequence[SessionBindingMemberV2],
) -> dict[str, object]:
    """返回 SessionBindingV2 的唯一规范 hash body；members 始终使用确定性 Host 排序。"""

    ordered_members = _canonical_v2_members(members)
    return {
        "session_ref": session_ref,
        "project_id": project_id,
        "semantic_target_id": semantic_target_id,
        "semantic_environment_id": semantic_environment_id,
        "semantic_environment_hash": semantic_environment_hash,
        "topology_environment_id": topology_environment_id,
        "topology_revision": topology_revision,
        "topology_snapshot_hash": topology_snapshot_hash,
        "initiating_host_kind": initiating_host_kind,
        "members": [
            session_binding_member_v2_hash_body(member)
            for member in ordered_members
        ],
    }


@dataclass(frozen=True, slots=True)
class SessionBindingV2:
    """一次 create-once 的双 Host runtime/document/semantic/topology authority 绑定。"""

    session_ref: str
    project_id: str
    semantic_target_id: str
    semantic_environment_id: str
    semantic_environment_hash: str
    topology_environment_id: str
    topology_revision: int
    topology_snapshot_hash: str
    initiating_host_kind: str
    members: tuple[SessionBindingMemberV2, SessionBindingMemberV2]
    binding_hash: str

    def __post_init__(self) -> None:
        """验证 exact 双 Host membership、拓扑 lineage 与 supplied binding hash。"""

        session_ref = _non_blank(
            self.session_ref,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="session_ref",
        )
        project_id = _non_blank(
            self.project_id,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="project_id",
        )
        semantic_target_id = _non_blank(
            self.semantic_target_id,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="semantic_target_id",
        )
        semantic_environment_id = _non_blank(
            self.semantic_environment_id,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="semantic_environment_id",
        )
        semantic_environment_hash = _sha256_hex(
            self.semantic_environment_hash,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="semantic_environment_hash",
        )
        topology_environment_id = _non_blank(
            self.topology_environment_id,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="topology_environment_id",
        )
        if (
            isinstance(self.topology_revision, bool)
            or not isinstance(self.topology_revision, int)
            or self.topology_revision < 0
        ):
            raise ValueError(
                "FRONT_DOOR_BINDING_V2_INVALID: topology_revision must be a non-negative integer"
            )
        topology_snapshot_hash = _sha256_hex(
            self.topology_snapshot_hash,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="topology_snapshot_hash",
        )
        initiating_host_kind = _non_blank(
            self.initiating_host_kind,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="initiating_host_kind",
        )
        if initiating_host_kind != "REVIT":
            raise ValueError(
                "FRONT_DOOR_BINDING_V2_INVALID: initiating_host_kind must be REVIT"
            )
        members = _canonical_v2_members(self.members)
        binding_hash = _sha256_hex(
            self.binding_hash,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="binding_hash",
        )
        expected_hash = canonical_hash(
            session_binding_v2_hash_body(
                session_ref=session_ref,
                project_id=project_id,
                semantic_target_id=semantic_target_id,
                semantic_environment_id=semantic_environment_id,
                semantic_environment_hash=semantic_environment_hash,
                topology_environment_id=topology_environment_id,
                topology_revision=self.topology_revision,
                topology_snapshot_hash=topology_snapshot_hash,
                initiating_host_kind=initiating_host_kind,
                members=members,
            )
        )
        if binding_hash != expected_hash:
            raise ValueError(
                "FRONT_DOOR_BINDING_V2_INVALID: binding_hash does not match authority body"
            )

        object.__setattr__(self, "session_ref", session_ref)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "semantic_target_id", semantic_target_id)
        object.__setattr__(self, "semantic_environment_id", semantic_environment_id)
        object.__setattr__(self, "semantic_environment_hash", semantic_environment_hash)
        object.__setattr__(self, "topology_environment_id", topology_environment_id)
        object.__setattr__(self, "topology_snapshot_hash", topology_snapshot_hash)
        object.__setattr__(self, "initiating_host_kind", initiating_host_kind)
        object.__setattr__(self, "members", members)
        object.__setattr__(self, "binding_hash", binding_hash)

    def member(self, host_kind: str) -> SessionBindingMemberV2:
        """按 exact Host kind 返回冻结成员；禁止 latest/fuzzy fallback。"""

        normalized = _non_blank(
            host_kind,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="host_kind",
        )
        for member in self.members:
            if member.host_kind == normalized:
                return member
        raise KeyError(f"SessionBindingV2 member not found: {normalized}")

    @classmethod
    def create(
        cls,
        *,
        session_ref: str,
        project_id: str,
        semantic_target_id: str,
        semantic_environment_id: str,
        semantic_environment_hash: str,
        topology_environment_id: str,
        topology_revision: int,
        topology_snapshot_hash: str,
        initiating_host_kind: str,
        members: Sequence[SessionBindingMemberV2],
    ) -> "SessionBindingV2":
        """规范化 exact 两 Host binding 并计算不可变 authority hash。"""

        canonical_session_ref = _non_blank(
            session_ref,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="session_ref",
        )
        canonical_project_id = _non_blank(
            project_id,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="project_id",
        )
        canonical_semantic_target_id = _non_blank(
            semantic_target_id,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="semantic_target_id",
        )
        canonical_semantic_environment_id = _non_blank(
            semantic_environment_id,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="semantic_environment_id",
        )
        canonical_semantic_environment_hash = _sha256_hex(
            semantic_environment_hash,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="semantic_environment_hash",
        )
        canonical_topology_environment_id = _non_blank(
            topology_environment_id,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="topology_environment_id",
        )
        if (
            isinstance(topology_revision, bool)
            or not isinstance(topology_revision, int)
            or topology_revision < 0
        ):
            raise ValueError(
                "FRONT_DOOR_BINDING_V2_INVALID: topology_revision must be a non-negative integer"
            )
        canonical_topology_snapshot_hash = _sha256_hex(
            topology_snapshot_hash,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="topology_snapshot_hash",
        )
        canonical_initiator = _non_blank(
            initiating_host_kind,
            code="FRONT_DOOR_BINDING_V2_INVALID",
            field_name="initiating_host_kind",
        )
        if canonical_initiator != "REVIT":
            raise ValueError(
                "FRONT_DOOR_BINDING_V2_INVALID: initiating_host_kind must be REVIT"
            )
        canonical_members = _canonical_v2_members(members)
        body = session_binding_v2_hash_body(
            session_ref=canonical_session_ref,
            project_id=canonical_project_id,
            semantic_target_id=canonical_semantic_target_id,
            semantic_environment_id=canonical_semantic_environment_id,
            semantic_environment_hash=canonical_semantic_environment_hash,
            topology_environment_id=canonical_topology_environment_id,
            topology_revision=topology_revision,
            topology_snapshot_hash=canonical_topology_snapshot_hash,
            initiating_host_kind=canonical_initiator,
            members=canonical_members,
        )
        return cls(
            session_ref=canonical_session_ref,
            project_id=canonical_project_id,
            semantic_target_id=canonical_semantic_target_id,
            semantic_environment_id=canonical_semantic_environment_id,
            semantic_environment_hash=canonical_semantic_environment_hash,
            topology_environment_id=canonical_topology_environment_id,
            topology_revision=topology_revision,
            topology_snapshot_hash=canonical_topology_snapshot_hash,
            initiating_host_kind=canonical_initiator,
            members=canonical_members,
            binding_hash=canonical_hash(body),
        )


class ConfiguredRevitCandidateSource(Protocol):
    """按 deterministic candidate_key 解析精确 immutable candidate 的最小端口。"""

    def get(self, candidate_key: str) -> ConfiguredRevitCandidate | None:
        """返回 exact candidate；未知 key 返回 None，不做 latest/fuzzy fallback。"""

        ...


@dataclass(frozen=True, slots=True)
class SessionBinding:
    """一次 create-once 的 Revit runtime/document/candidate authority 绑定。"""

    session_ref: str
    project_id: str
    host_kind: str
    candidate_key: str
    candidate_hash: str
    transport_locator: str
    host_instance_id: str
    document_id: str
    document_title: str
    binding_hash: str

    def __post_init__(self) -> None:
        """验证 exact authority body；candidate_hash 必须被 binding_hash 显式冻结。"""

        session_ref = _non_blank(
            self.session_ref,
            code="FRONT_DOOR_BINDING_INVALID",
            field_name="session_ref",
        )
        project_id = _non_blank(
            self.project_id,
            code="FRONT_DOOR_BINDING_INVALID",
            field_name="project_id",
        )
        host_kind = _non_blank(
            self.host_kind,
            code="FRONT_DOOR_BINDING_INVALID",
            field_name="host_kind",
        )
        if host_kind != _HOST_KIND_REVIT:
            raise ValueError("FRONT_DOOR_BINDING_INVALID: host_kind must be REVIT")
        candidate_key = _non_blank(
            self.candidate_key,
            code="FRONT_DOOR_BINDING_INVALID",
            field_name="candidate_key",
        )
        candidate_hash = _sha256_hex(
            self.candidate_hash,
            code="FRONT_DOOR_BINDING_INVALID",
            field_name="candidate_hash",
        )
        transport_locator = _non_blank(
            self.transport_locator,
            code="FRONT_DOOR_BINDING_INVALID",
            field_name="transport_locator",
        )
        host_instance_id = _non_blank(
            self.host_instance_id,
            code="FRONT_DOOR_BINDING_INVALID",
            field_name="host_instance_id",
        )
        document_id = _absolute_document_id(self.document_id)
        if not isinstance(self.document_title, str):
            raise TypeError("FRONT_DOOR_BINDING_INVALID: document_title must be a string")
        binding_hash = _sha256_hex(
            self.binding_hash,
            code="FRONT_DOOR_BINDING_HASH_INVALID",
            field_name="binding_hash",
        )

        normalized_body = session_binding_hash_body(
            session_ref=session_ref,
            project_id=project_id,
            host_kind=host_kind,
            candidate_key=candidate_key,
            candidate_hash=candidate_hash,
            transport_locator=transport_locator,
            host_instance_id=host_instance_id,
            document_id=document_id,
        )
        expected_hash = canonical_hash(normalized_body)
        if binding_hash != expected_hash:
            raise ValueError(
                "FRONT_DOOR_BINDING_HASH_INVALID: binding_hash does not match authority body"
            )

        object.__setattr__(self, "session_ref", session_ref)
        object.__setattr__(self, "project_id", project_id)
        object.__setattr__(self, "host_kind", host_kind)
        object.__setattr__(self, "candidate_key", candidate_key)
        object.__setattr__(self, "candidate_hash", candidate_hash)
        object.__setattr__(self, "transport_locator", transport_locator)
        object.__setattr__(self, "host_instance_id", host_instance_id)
        object.__setattr__(self, "document_id", document_id)
        object.__setattr__(self, "binding_hash", binding_hash)


__all__ = [
    "ConfiguredRevitCandidate",
    "ConfiguredRevitCandidateSource",
    "SessionBinding",
    "SessionBindingMemberV2",
    "SessionBindingV2",
    "configured_revit_candidate_hash_body",
    "session_binding_hash_body",
    "session_binding_member_v2_hash_body",
    "session_binding_v2_hash_body",
]
