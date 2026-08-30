"""Immutable provider-neutral lifecycle state for Step33 execution Sagas."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from .saga_contracts import ExecutionSagaDefinition

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class ExecutionSagaStatus(str, Enum):
    READY = "READY"
    EXECUTING = "EXECUTING"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    SUCCEEDED = "SUCCEEDED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    FAILED = "FAILED"


class SliceReconciliationStatus(str, Enum):
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
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: object | None, field_name: str) -> str | None:
    return None if value is None else _text(value, field_name)


def _digest(value: object, field_name: str) -> str:
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _optional_digest(value: object | None, field_name: str) -> str | None:
    return None if value is None else _digest(value, field_name)


def _enum(value: object, enum_type: type[Enum], field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


@dataclass(frozen=True, slots=True)
class SliceReconciliationState:
    execution_slice_hash: str
    sequence_index: int
    status: SliceReconciliationStatus | str = SliceReconciliationStatus.NOT_STARTED
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

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "execution_slice_hash",
            _digest(self.execution_slice_hash, "execution_slice_hash"),
        )
        if not isinstance(self.sequence_index, int) or isinstance(self.sequence_index, bool):
            raise TypeError("sequence_index must be an integer")
        if self.sequence_index < 0:
            raise ValueError("sequence_index must be non-negative")
        object.__setattr__(
            self,
            "status",
            _enum(self.status, SliceReconciliationStatus, "slice reconciliation status"),
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
        ):
            object.__setattr__(
                self,
                field_name,
                _optional_text(getattr(self, field_name), field_name),
            )


@dataclass(frozen=True, slots=True)
class StoredExecutionSaga:
    definition: ExecutionSagaDefinition
    saga_revision: int
    status: ExecutionSagaStatus | str
    slice_states: tuple[SliceReconciliationState, ...]
    compensation_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.definition, ExecutionSagaDefinition):
            raise TypeError("definition must be ExecutionSagaDefinition")
        if not isinstance(self.saga_revision, int) or isinstance(self.saga_revision, bool):
            raise TypeError("saga_revision must be an integer")
        if self.saga_revision < 0:
            raise ValueError("saga_revision must be non-negative")
        object.__setattr__(
            self,
            "status",
            _enum(self.status, ExecutionSagaStatus, "execution saga status"),
        )
        states = tuple(self.slice_states)
        if any(not isinstance(item, SliceReconciliationState) for item in states):
            raise TypeError("slice_states contains invalid values")
        if len(states) != len(self.definition.ordered_slice_hashes):
            raise ValueError("slice_states must cover every Saga Slice")
        if tuple(item.sequence_index for item in states) != tuple(range(len(states))):
            raise ValueError("slice_states must use contiguous canonical sequence indexes")
        if tuple(item.execution_slice_hash for item in states) != self.definition.ordered_slice_hashes:
            raise ValueError("slice_states must follow the immutable Saga Slice order")
        object.__setattr__(self, "slice_states", states)
        refs = tuple(sorted({_text(item, "compensation_ref") for item in self.compensation_refs}))
        object.__setattr__(self, "compensation_refs", refs)


__all__ = [
    "ExecutionSagaStatus",
    "SliceReconciliationState",
    "SliceReconciliationStatus",
    "StoredExecutionSaga",
]
