"""Step37 execution coordination 的不可变 provider-neutral 公共契约。

Task 7 在该边界补充 durable Host dispatch identity；这里只表达逻辑命令身份与
Host outcome 事实，不引入任何 Host-native payload 或 recovery 决策。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from design_execution_reconciliation import ActualDelta

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _text(value: object, field_name: str) -> str:
    """规范化不能为空的 provider-neutral 文本字段。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: object | None, field_name: str) -> str | None:
    """规范化允许缺省的文本字段。"""
    return None if value is None else _text(value, field_name)


def _digest(value: object, field_name: str) -> str:
    """校验仓库统一使用的小写 SHA-256 十六进制摘要。"""
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _optional_digest(value: object | None, field_name: str) -> str | None:
    """规范化可选 SHA-256 摘要。"""
    return None if value is None else _digest(value, field_name)


def _revision(value: object, field_name: str) -> int:
    """校验单调 revision；bool 不视为合法整数 revision。"""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _enum(value: object, enum_type: type[Enum], field_name: str):
    """把字符串或枚举值规范化为指定稳定枚举。"""
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
    """旧 Step37 coordination surface 的稳定终态集合。"""

    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class HostFailurePhase(str, Enum):
    """Host failure 是否已经越过提交边界的最小事实分类。"""

    BEFORE_COMMIT = "BEFORE_COMMIT"
    COMMIT_STATE_UNKNOWN = "COMMIT_STATE_UNKNOWN"


@dataclass(frozen=True, slots=True)
class HostDispatchContext:
    """在 durable dispatch intent 与 Host execution port 之间传递稳定逻辑命令身份。

    该对象只携带 provider-neutral identity，不携带 Host-native payload。Host 写操作必须
    使用这里的 ``idempotency_key``，从而让进程重启或网络重试仍命中同一个逻辑命令。
    """

    dispatch_intent_id: str
    idempotency_key: str
    saga_id: str
    execution_slice_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dispatch_intent_id",
            _text(self.dispatch_intent_id, "dispatch_intent_id"),
        )
        object.__setattr__(
            self,
            "idempotency_key",
            _text(self.idempotency_key, "idempotency_key"),
        )
        object.__setattr__(self, "saga_id", _text(self.saga_id, "saga_id"))
        object.__setattr__(
            self,
            "execution_slice_hash",
            _digest(self.execution_slice_hash, "execution_slice_hash"),
        )


@dataclass(frozen=True, slots=True)
class CoordinationResult:
    """旧 Step37 coordinator 对外暴露的稳定结果。"""

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
    """Gateway authority 获取失败的稳定 provider-neutral 事实。"""

    failure_ref: str
    failed_at: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "failure_ref", _text(self.failure_ref, "failure_ref"))
        object.__setattr__(self, "failed_at", _text(self.failed_at, "failed_at"))


@dataclass(frozen=True, slots=True)
class HostCommitted:
    """Host 明确返回已提交且带规范 ActualDelta 的结果。"""

    actual_delta: ActualDelta
    committed_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.actual_delta, ActualDelta):
            raise TypeError("actual_delta must be ActualDelta")
        object.__setattr__(self, "committed_at", _text(self.committed_at, "committed_at"))


@dataclass(frozen=True, slots=True)
class HostFailed:
    """Host 失败结果；phase 明确区分安全未提交与提交状态未知。"""

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
    "HostDispatchContext",
    "HostExecutionResult",
    "HostFailed",
    "HostFailurePhase",
]
