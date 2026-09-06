"""Phase I Step33 V2 的本地 reconciliation 与 convergence 状态。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .saga_contracts_v2 import ExecutionSagaDefinitionV2

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ExecutionSagaStatusV2(str, Enum):
    READY = "READY"
    EXECUTING = "EXECUTING"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    CONVERGENCE_PENDING = "CONVERGENCE_PENDING"
    SUCCEEDED = "SUCCEEDED"
    DIVERGED = "DIVERGED"
    FAILED = "FAILED"


class SagaConvergenceOutcome(str, Enum):
    CONVERGED = "CONVERGED"
    DIVERGED = "DIVERGED"


class SliceReconciliationStatusV2(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ADMISSION_RESERVED = "ADMISSION_RESERVED"
    ADMITTED = "ADMITTED"
    HOST_COMMITTED = "HOST_COMMITTED"
    RECONCILING = "RECONCILING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_BEFORE_COMMIT = "FAILED_BEFORE_COMMIT"
    VERIFY_FAILED = "VERIFY_FAILED"
    SCOPE_BREACH = "SCOPE_BREACH"
    BLOCKED = "BLOCKED"


def _text(value: object, field_name: str) -> str:
    """规范化不可为空的文本字段。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: object | None, field_name: str) -> str | None:
    """规范化可空文本字段。"""
    return None if value is None else _text(value, field_name)


def _digest(value: object, field_name: str) -> str:
    """规范化 SHA-256 小写十六进制摘要。"""
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _optional_digest(value: object | None, field_name: str) -> str | None:
    """规范化可空 SHA-256 摘要。"""
    return None if value is None else _digest(value, field_name)


def _enum(value: object, enum_type: type[Enum], field_name: str):
    """把枚举输入规范化为指定的闭世界枚举。"""
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class SliceReconciliationStateV2:
    """一个 REQUIRED materialization Slice 的持久本地 reconciliation 状态。"""

    execution_slice_hash: str
    sequence_index: int
    materialization_plan_hash: str
    status: SliceReconciliationStatusV2 | str = SliceReconciliationStatusV2.NOT_STARTED
    materialization_id: str | None = None
    approval_hash: str | None = None
    grant_hash: str | None = None
    binding_set_hash: str | None = None
    admitted_host_instance_id: str | None = None
    actual_delta_hash: str | None = None
    scope_comparison_hash: str | None = None
    verification_hash: str | None = None
    reserved_at: str | None = None
    admitted_at: str | None = None
    committed_at: str | None = None
    reconciled_at: str | None = None
    failed_at: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "execution_slice_hash",
            _digest(self.execution_slice_hash, "execution_slice_hash"),
        )
        object.__setattr__(
            self,
            "materialization_plan_hash",
            _digest(self.materialization_plan_hash, "materialization_plan_hash"),
        )
        if not isinstance(self.sequence_index, int) or isinstance(self.sequence_index, bool):
            raise TypeError("sequence_index must be an integer")
        if self.sequence_index < 0:
            raise ValueError("sequence_index must be non-negative")
        object.__setattr__(
            self,
            "status",
            _enum(self.status, SliceReconciliationStatusV2, "slice reconciliation status"),
        )
        object.__setattr__(
            self,
            "materialization_id",
            _optional_text(self.materialization_id, "materialization_id"),
        )
        for field_name in (
            "approval_hash",
            "grant_hash",
            "binding_set_hash",
            "actual_delta_hash",
            "scope_comparison_hash",
            "verification_hash",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_digest(getattr(self, field_name), field_name),
            )
        object.__setattr__(
            self,
            "admitted_host_instance_id",
            _optional_text(self.admitted_host_instance_id, "admitted_host_instance_id"),
        )
        for field_name in (
            "reserved_at",
            "admitted_at",
            "committed_at",
            "reconciled_at",
            "failed_at",
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class StoredExecutionSagaV2:
    """独立于 V1 store 的不可变 Saga V2 持久快照。"""

    definition: ExecutionSagaDefinitionV2
    saga_revision: int
    status: ExecutionSagaStatusV2 | str
    slice_states: tuple[SliceReconciliationStateV2, ...]
    convergence_outcome: SagaConvergenceOutcome | str | None = None
    convergence_result_hash: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ExecutionSagaDefinitionV2):
            raise TypeError("definition must be ExecutionSagaDefinitionV2")
        if not isinstance(self.saga_revision, int) or isinstance(self.saga_revision, bool):
            raise TypeError("saga_revision must be an integer")
        if self.saga_revision < 0:
            raise ValueError("saga_revision must be non-negative")
        object.__setattr__(
            self,
            "status",
            _enum(self.status, ExecutionSagaStatusV2, "execution saga status"),
        )
        states = tuple(self.slice_states)
        if any(not isinstance(item, SliceReconciliationStateV2) for item in states):
            raise TypeError("slice_states contains invalid values")
        if len(states) != len(self.definition.ordered_slice_hashes):
            raise ValueError("slice_states must cover every Saga V2 Slice")
        if tuple(item.sequence_index for item in states) != tuple(range(len(states))):
            raise ValueError("slice_states must use contiguous canonical sequence indexes")
        if tuple(item.execution_slice_hash for item in states) != self.definition.ordered_slice_hashes:
            raise ValueError("slice_states must follow immutable Saga V2 Slice order")
        if any(
            item.materialization_plan_hash != self.definition.materialization_plan_hash
            for item in states
        ):
            raise ValueError("slice_states must bind the Saga V2 materialization plan")
        object.__setattr__(self, "slice_states", states)

        outcome = self.convergence_outcome
        if outcome is not None:
            outcome = _enum(outcome, SagaConvergenceOutcome, "convergence outcome")
        object.__setattr__(self, "convergence_outcome", outcome)
        object.__setattr__(
            self,
            "convergence_result_hash",
            _optional_digest(self.convergence_result_hash, "convergence_result_hash"),
        )
        if (outcome is None) != (self.convergence_result_hash is None):
            raise ValueError(
                "convergence_outcome and convergence_result_hash must be recorded together"
            )


__all__ = [
    "ExecutionSagaStatusV2",
    "SagaConvergenceOutcome",
    "SliceReconciliationStateV2",
    "SliceReconciliationStatusV2",
    "StoredExecutionSagaV2",
]
