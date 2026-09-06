"""DSP 物化拓扑的不可变平台契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class MaterializationTopologyError(ValueError):
    """物化拓扑契约或完整性校验失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _required_text(code, "code")


class MaterializationRequirement(str, Enum):
    """Phase I 支持的物化要求。"""

    REQUIRED = "REQUIRED"


def _required_text(value: str, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _required_digest(value: str, field_name: str) -> str:
    normalized = _required_text(value, field_name)
    if re.fullmatch(r"[0-9a-f]{64}", normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase 64-hex SHA-256 digest")
    return normalized


def _host_type(value: str) -> str:
    normalized = _required_text(value, "required_host_type")
    if normalized != normalized.lower() or re.fullmatch(r"[a-z][a-z0-9_-]*", normalized) is None:
        raise ValueError("required_host_type must be a lowercase Host type token")
    return normalized


@dataclass(frozen=True, slots=True)
class MaterializationSlot:
    """一个语义目标在一个必需 Host 文档中的物化义务。"""

    materialization_slot_id: str
    semantic_target_ref: str
    required_host_type: str
    document_ref: str
    requirement: MaterializationRequirement

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "materialization_slot_id",
            _required_text(self.materialization_slot_id, "materialization_slot_id"),
        )
        object.__setattr__(
            self,
            "semantic_target_ref",
            _required_text(self.semantic_target_ref, "semantic_target_ref"),
        )
        object.__setattr__(self, "required_host_type", _host_type(self.required_host_type))
        object.__setattr__(
            self,
            "document_ref",
            _required_text(self.document_ref, "document_ref"),
        )
        if not isinstance(self.requirement, MaterializationRequirement):
            try:
                requirement = MaterializationRequirement(str(self.requirement))
            except ValueError as exc:
                raise ValueError("invalid materialization requirement") from exc
            object.__setattr__(self, "requirement", requirement)


@dataclass(frozen=True, slots=True)
class MaterializationTopologySnapshot:
    """某个拓扑命名空间与修订号下的不可变 REQUIRED 槽快照。"""

    topology_environment_id: str
    topology_revision: int
    slots: tuple[MaterializationSlot, ...]
    topology_snapshot_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "topology_environment_id",
            _required_text(self.topology_environment_id, "topology_environment_id"),
        )
        if (
            not isinstance(self.topology_revision, int)
            or isinstance(self.topology_revision, bool)
            or self.topology_revision < 0
        ):
            raise ValueError("topology_revision must be a non-negative integer")

        normalized_slots = tuple(self.slots)
        if not normalized_slots:
            raise ValueError("slots requires at least one materialization slot")
        if any(not isinstance(slot, MaterializationSlot) for slot in normalized_slots):
            raise TypeError("slots must contain only MaterializationSlot values")

        identities: set[tuple[str, str, str]] = set()
        for slot in normalized_slots:
            identity = (
                slot.semantic_target_ref,
                slot.required_host_type,
                slot.document_ref,
            )
            if identity in identities:
                raise ValueError(
                    "duplicate materialization slot for semantic target, Host type, and document"
                )
            identities.add(identity)

        object.__setattr__(self, "slots", normalized_slots)
        object.__setattr__(
            self,
            "topology_snapshot_hash",
            _required_digest(self.topology_snapshot_hash, "topology_snapshot_hash"),
        )
