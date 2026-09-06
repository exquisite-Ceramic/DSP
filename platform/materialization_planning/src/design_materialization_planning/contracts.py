"""Phase I 物化计划的不可变 provider-neutral 契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_HASH_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_HOST_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")


class MaterializationPlanningError(ValueError):
    """带稳定错误码的物化计划失败。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _required_text(code, "code")


def _required_text(value: object, field_name: str) -> str:
    """规范化一个必填文本字段。"""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} is required")
    return value.strip()


def _required_digest(value: object, field_name: str) -> str:
    """验证一个小写 SHA-256 十六进制摘要。"""
    normalized = _required_text(value, field_name)
    if _HASH_PATTERN.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be a lowercase 64-hex SHA-256 digest")
    return normalized


def _required_host_type(value: object) -> str:
    """规范化 provider-neutral Host 类型 token。"""
    normalized = _required_text(value, "required_host_type")
    if _HOST_PATTERN.fullmatch(normalized) is None:
        raise ValueError("required_host_type must be a lowercase Host type token")
    return normalized


def _required_texts(values: object, field_name: str) -> tuple[str, ...]:
    """规范化非空且无重复的文本元组。"""
    try:
        raw = tuple(values)  # type: ignore[arg-type]
    except TypeError as exc:
        raise TypeError(f"{field_name} must be a sequence") from exc
    if not raw:
        raise ValueError(f"{field_name} requires at least one value")
    normalized = tuple(_required_text(value, field_name) for value in raw)
    if len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} values must be unique")
    return normalized


@dataclass(frozen=True, slots=True)
class MaterializationIntent:
    """把一个 canonical operation 投影到一个 REQUIRED Host 槽的不可变义务。"""

    materialization_id: str
    source_operation_id: str
    source_operation_hash: str
    semantic_targets: tuple[str, ...]
    materialization_slot_id: str
    required_host_type: str
    expected_effects: tuple[str, ...]
    intent_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "materialization_id",
            _required_text(self.materialization_id, "materialization_id"),
        )
        object.__setattr__(
            self,
            "source_operation_id",
            _required_text(self.source_operation_id, "source_operation_id"),
        )
        object.__setattr__(
            self,
            "source_operation_hash",
            _required_digest(self.source_operation_hash, "source_operation_hash"),
        )
        object.__setattr__(
            self,
            "semantic_targets",
            _required_texts(self.semantic_targets, "semantic_targets"),
        )
        object.__setattr__(
            self,
            "materialization_slot_id",
            _required_text(self.materialization_slot_id, "materialization_slot_id"),
        )
        object.__setattr__(
            self,
            "required_host_type",
            _required_host_type(self.required_host_type),
        )
        object.__setattr__(
            self,
            "expected_effects",
            _required_texts(self.expected_effects, "expected_effects"),
        )
        object.__setattr__(
            self,
            "intent_hash",
            _required_digest(self.intent_hash, "intent_hash"),
        )


@dataclass(frozen=True, slots=True)
class MaterializationPlan:
    """绑定审批、ChangeSet、拓扑与 convergence profile 的不可变物化计划。"""

    changeset_hash: str
    approved_scope_hash: str
    topology_snapshot_hash: str
    intents: tuple[MaterializationIntent, ...]
    required_set_hash: str
    convergence_profile_hash: str
    materialization_plan_hash: str

    def __post_init__(self) -> None:
        normalized_intents = tuple(self.intents)
        if not normalized_intents:
            raise ValueError("intents requires at least one MaterializationIntent")
        if any(not isinstance(intent, MaterializationIntent) for intent in normalized_intents):
            raise TypeError("intents must contain only MaterializationIntent values")

        materialization_ids = tuple(intent.materialization_id for intent in normalized_intents)
        if len(set(materialization_ids)) != len(materialization_ids):
            raise ValueError("materialization_id values must be unique within one plan")
        slot_ids = tuple(intent.materialization_slot_id for intent in normalized_intents)
        if len(set(slot_ids)) != len(slot_ids):
            raise ValueError("materialization_slot_id values must be unique within one plan")

        object.__setattr__(self, "intents", normalized_intents)
        for field_name in (
            "changeset_hash",
            "approved_scope_hash",
            "topology_snapshot_hash",
            "required_set_hash",
            "convergence_profile_hash",
            "materialization_plan_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_digest(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class MaterializationPlanningRequest:
    """MaterializationPlanner 的四项冻结输入。"""

    canonical_changeset: Any
    approval_scope_boundary: Any
    topology_snapshot: Any
    convergence_profile: Any


__all__ = [
    "MaterializationIntent",
    "MaterializationPlan",
    "MaterializationPlanningError",
    "MaterializationPlanningRequest",
]
