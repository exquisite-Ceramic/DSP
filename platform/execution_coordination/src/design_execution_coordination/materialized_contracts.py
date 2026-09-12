"""Phase I materialized Step37 的独立协调结果契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _text(value: object, field_name: str) -> str:
    """规范化必填文本字段。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: object | None, field_name: str) -> str | None:
    """规范化可空文本字段。"""
    return None if value is None else _text(value, field_name)


def _optional_digest(value: object | None, field_name: str) -> str | None:
    """规范化可空 SHA-256 摘要字段。"""
    if value is None:
        return None
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _revision(value: object, field_name: str) -> int:
    """规范化非负 Saga revision。"""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


class MaterializedCoordinationStatus(str, Enum):
    """Phase I materialized Step37 的闭集协调状态。"""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    READINESS_FAILED = "READINESS_FAILED"
    DIVERGED = "DIVERGED"


@dataclass(frozen=True, slots=True)
class MaterializedCoordinationResult:
    """独立于 V1 CoordinationResult 的 materialized 协调结果。"""

    saga_id: str
    saga_revision: int
    status: MaterializedCoordinationStatus | str
    active_slice_hash: str | None
    failure_ref: str | None
    convergence_result_hash: str | None

    def __post_init__(self) -> None:
        object.__setattr__(self, "saga_id", _text(self.saga_id, "saga_id"))
        object.__setattr__(
            self,
            "saga_revision",
            _revision(self.saga_revision, "saga_revision"),
        )
        status = (
            self.status
            if isinstance(self.status, MaterializedCoordinationStatus)
            else MaterializedCoordinationStatus(str(self.status))
        )
        object.__setattr__(self, "status", status)
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
        object.__setattr__(
            self,
            "convergence_result_hash",
            _optional_digest(
                self.convergence_result_hash,
                "convergence_result_hash",
            ),
        )


__all__ = [
    "MaterializedCoordinationResult",
    "MaterializedCoordinationStatus",
]
