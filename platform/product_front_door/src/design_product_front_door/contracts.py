"""Product Front Door 的 immutable candidate / session authority 契约。"""

from __future__ import annotations

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
            raise ValueError("FRONT_DOOR_BINDING_INVALID: document_title must be a string")
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
    "configured_revit_candidate_hash_body",
    "session_binding_hash_body",
]
