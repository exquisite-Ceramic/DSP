"""Immutable provider-neutral contracts for Step37 execution coordination."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from design_execution_reconciliation import ActualDelta

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


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


def _revision(value: object, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _enum(value: object, enum_type: type[Enum], field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


class CoordinationError(ValueError):
    """Stable Step37 domain error carrying a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _text(code, "code")


class CoordinationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class HostFailurePhase(str, Enum):
    BEFORE_COMMIT = "BEFORE_COMMIT"
    COMMIT_STATE_UNKNOWN = "COMMIT_STATE_UNKNOWN"


@dataclass(frozen=True, slots=True)
class CoordinationResult:
    saga_id: str
    saga_revision: int
    status: CoordinationStatus | str
    active_slice_hash: str | None
    failure_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "saga_id", _text(self.saga_id, "saga_id"))
        object.__setattr__(
            self,
            "saga_revision",
            _revision(self.saga_revision, "saga_revision"),
        )
        object.__setattr__(
            self,
            "status",
            _enum(self.status, CoordinationStatus, "coordination status"),
        )
        object.__setattr__(
            self,
            "active_slice_hash",
            _optional_digest(self.active_slice_hash, "active_slice_hash"),
        )
        object.__setattr__(
            self,
            "failure_ref",
            _optional_text(self.failure_ref, "failure_ref"),
        )


@dataclass(frozen=True, slots=True)
class AuthorityFailure:
    failure_ref: str
    failed_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_ref", _text(self.failure_ref, "failure_ref"))
        object.__setattr__(self, "failed_at", _text(self.failed_at, "failed_at"))


@dataclass(frozen=True, slots=True)
class HostCommitted:
    actual_delta: ActualDelta
    committed_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.actual_delta, ActualDelta):
            raise TypeError("actual_delta must be ActualDelta")
        object.__setattr__(self, "committed_at", _text(self.committed_at, "committed_at"))


@dataclass(frozen=True, slots=True)
class HostFailed:
    phase: HostFailurePhase | str
    failure_ref: str
    failed_at: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "phase",
            _enum(self.phase, HostFailurePhase, "Host failure phase"),
        )
        object.__setattr__(self, "failure_ref", _text(self.failure_ref, "failure_ref"))
        object.__setattr__(self, "failed_at", _text(self.failed_at, "failed_at"))


HostExecutionResult = HostCommitted | HostFailed


__all__ = [
    "AuthorityFailure",
    "CoordinationError",
    "CoordinationResult",
    "CoordinationStatus",
    "HostCommitted",
    "HostExecutionResult",
    "HostFailed",
    "HostFailurePhase",
]
