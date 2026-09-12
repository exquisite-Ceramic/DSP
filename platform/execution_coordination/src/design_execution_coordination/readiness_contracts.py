"""Phase I provider-neutral readiness 的不可变公共契约。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from design_changeset import canonical_hash
from design_execution_planning import HostRuntimeRef

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _text(value: object, field_name: str) -> str:
    """把必填文本规范化为非空字符串。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: object | None, field_name: str) -> str | None:
    """规范化可选文本。"""
    return None if value is None else _text(value, field_name)


def _digest(value: object, field_name: str) -> str:
    """校验 lowercase SHA-256 十六进制摘要。"""
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _revision(value: object, field_name: str) -> int:
    """校验非负 Host revision。"""
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _enum(value: object, enum_type: type[Enum], field_name: str):
    """把字符串或枚举值收敛到指定 closed-world 枚举。"""
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


class ReadinessError(ValueError):
    """携带稳定机器错误码的 Phase I readiness 领域错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _text(code, "code")


class ReadinessStatus(str, Enum):
    """单个 REQUIRED materialization 的只读 readiness 结果。"""

    READY = "READY"
    NOT_READY = "NOT_READY"


class ReadinessBarrierStatus(str, Enum):
    """全部 REQUIRED materialization 的闭世界 barrier 结果。"""

    READY = "READY"
    NOT_READY = "NOT_READY"


@dataclass(frozen=True, slots=True)
class HostReadinessReceipt:
    """绑定 exact materialization execution authority 的不可变 readiness 回执。"""

    materialization_id: str
    materialization_plan_hash: str
    execution_slice_hash: str
    binding_set_hash: str
    grant_hash: str
    host_runtime_ref: HostRuntimeRef
    observed_revision: int
    status: ReadinessStatus | str
    failure_code: str | None
    receipt_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "materialization_id",
            _text(self.materialization_id, "materialization_id"),
        )
        for name in (
            "materialization_plan_hash",
            "execution_slice_hash",
            "binding_set_hash",
            "grant_hash",
            "receipt_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        if not isinstance(self.host_runtime_ref, HostRuntimeRef):
            raise TypeError("host_runtime_ref must be HostRuntimeRef")
        object.__setattr__(
            self,
            "observed_revision",
            _revision(self.observed_revision, "observed_revision"),
        )
        object.__setattr__(
            self,
            "status",
            _enum(self.status, ReadinessStatus, "readiness status"),
        )
        object.__setattr__(
            self,
            "failure_code",
            _optional_text(self.failure_code, "failure_code"),
        )
        if self.status is ReadinessStatus.READY and self.failure_code is not None:
            raise ValueError("READY receipt cannot carry failure_code")
        if self.status is ReadinessStatus.NOT_READY and self.failure_code is None:
            raise ValueError("NOT_READY receipt requires failure_code")


@dataclass(frozen=True, slots=True)
class ReadinessBarrierResult:
    """只表达 readiness barrier，不复用或扩展 V1 coordination 状态。"""

    status: ReadinessBarrierStatus | str
    receipts: tuple[HostReadinessReceipt, ...]
    failure_ref: str | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "status",
            _enum(self.status, ReadinessBarrierStatus, "readiness barrier status"),
        )
        receipts = tuple(self.receipts)
        if any(not isinstance(item, HostReadinessReceipt) for item in receipts):
            raise TypeError("receipts must contain HostReadinessReceipt values")
        object.__setattr__(self, "receipts", receipts)
        object.__setattr__(
            self,
            "failure_ref",
            _optional_text(self.failure_ref, "failure_ref"),
        )
        if self.status is ReadinessBarrierStatus.READY and self.failure_ref is not None:
            raise ValueError("READY barrier cannot carry failure_ref")
        if self.status is ReadinessBarrierStatus.NOT_READY and self.failure_ref is None:
            raise ValueError("NOT_READY barrier requires failure_ref")


def compute_readiness_receipt_hash(receipt: HostReadinessReceipt) -> str:
    """计算覆盖全部 readiness lineage 与观察结果的不可变内容哈希。"""
    if not isinstance(receipt, HostReadinessReceipt):
        raise TypeError("receipt must be HostReadinessReceipt")
    return canonical_hash(
        {
            "version": "HOST_READINESS_RECEIPT_V1",
            "materialization_id": receipt.materialization_id,
            "materialization_plan_hash": receipt.materialization_plan_hash,
            "execution_slice_hash": receipt.execution_slice_hash,
            "binding_set_hash": receipt.binding_set_hash,
            "grant_hash": receipt.grant_hash,
            "host_runtime_ref": {
                "host_type": receipt.host_runtime_ref.host_type,
                "host_instance_id": receipt.host_runtime_ref.host_instance_id,
                "document_ref": receipt.host_runtime_ref.document_ref,
            },
            "observed_revision": receipt.observed_revision,
            "status": receipt.status.value,
            "failure_code": receipt.failure_code,
        }
    )


__all__ = [
    "HostReadinessReceipt",
    "ReadinessBarrierResult",
    "ReadinessBarrierStatus",
    "ReadinessError",
    "ReadinessStatus",
    "compute_readiness_receipt_hash",
]
