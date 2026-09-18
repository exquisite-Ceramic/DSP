"""Host dispatch durable intent 的不可变领域契约与稳定身份构造器。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from uuid import UUID, uuid5

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")

# 两个固定 namespace 分离“durable intent 主键”与“Host command 幂等键”的身份域。
# namespace 本身一旦发布就不能改变，否则重启后会为同一逻辑命令生成新身份。
_DISPATCH_NAMESPACE = UUID("e0bdb3eb-6c43-5c2a-beb6-e55eb9f252d3")
_IDEMPOTENCY_NAMESPACE = UUID("691eb245-0ea4-50a4-9671-3dd5abf22c79")


class HostDispatchStatus(str, Enum):
    """Execution Saga owner 持久化的 Host dispatch/recovery 状态。"""

    PREPARED = "PREPARED"
    DISPATCHED = "DISPATCHED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    HOST_COMMITTED = "HOST_COMMITTED"
    SAFE_TO_RETRY = "SAFE_TO_RETRY"
    RECONCILED = "RECONCILED"


def _text(value: object, field_name: str) -> str:
    """规范化不能为空的文本字段。"""
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: object | None, field_name: str) -> str | None:
    """规范化可选文本；None 表示调用方没有可冻结的 Host revision precondition。"""
    return None if value is None else _text(value, field_name)


def _digest(value: object, field_name: str) -> str:
    """只接受仓库统一使用的小写 SHA-256 hex lineage。"""
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _revision(value: object) -> int:
    """校验 durable intent 自己的单调 CAS revision。"""
    if not isinstance(value, int) or isinstance(value, bool):
        raise TypeError("intent_revision must be an integer")
    if value < 0:
        raise ValueError("intent_revision must be non-negative")
    return value


@dataclass(frozen=True, slots=True)
class HostDispatchIntent:
    """一个已冻结 admitted lineage 的唯一逻辑 Host command intent。"""

    dispatch_intent_id: UUID
    saga_id: str
    execution_slice_hash: str
    grant_hash: str
    binding_set_hash: str
    host_instance_id: str
    document_ref: str
    idempotency_key: UUID
    expected_host_revision: str | None
    status: HostDispatchStatus
    intent_revision: int
    prepared_at: str

    def __post_init__(self) -> None:
        if not isinstance(self.dispatch_intent_id, UUID):
            raise TypeError("dispatch_intent_id must be UUID")
        if not isinstance(self.idempotency_key, UUID):
            raise TypeError("idempotency_key must be UUID")

        object.__setattr__(self, "saga_id", _text(self.saga_id, "saga_id"))
        for name in ("execution_slice_hash", "grant_hash", "binding_set_hash"):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "host_instance_id",
            _text(self.host_instance_id, "host_instance_id"),
        )
        object.__setattr__(self, "document_ref", _text(self.document_ref, "document_ref"))
        object.__setattr__(
            self,
            "expected_host_revision",
            _optional_text(self.expected_host_revision, "expected_host_revision"),
        )
        if not isinstance(self.status, HostDispatchStatus):
            try:
                object.__setattr__(self, "status", HostDispatchStatus(str(self.status)))
            except ValueError as exc:
                raise ValueError(f"invalid dispatch status: {self.status!r}") from exc
        object.__setattr__(self, "intent_revision", _revision(self.intent_revision))
        object.__setattr__(self, "prepared_at", _text(self.prepared_at, "prepared_at"))


def build_host_dispatch_intent(
    *,
    saga_id: str,
    execution_slice_hash: str,
    grant_hash: str,
    binding_set_hash: str,
    host_instance_id: str,
    document_ref: str,
    expected_host_revision: str | None,
    prepared_at: str,
) -> HostDispatchIntent:
    """从 immutable execution lineage 构造确定性的 PREPARED intent。

    ``prepared_at`` 只承担审计时间，不参与 ``dispatch_intent_id`` 或
    ``idempotency_key``。因此 Window E 崩溃恢复后重新构造同一 admitted lineage
    时，不会因为 wall clock 改变而制造第二个逻辑 Host command。
    """
    normalized_saga_id = _text(saga_id, "saga_id")
    normalized_slice_hash = _digest(execution_slice_hash, "execution_slice_hash")
    normalized_grant_hash = _digest(grant_hash, "grant_hash")
    normalized_binding_hash = _digest(binding_set_hash, "binding_set_hash")
    normalized_host = _text(host_instance_id, "host_instance_id")
    normalized_document = _text(document_ref, "document_ref")
    normalized_revision = _optional_text(expected_host_revision, "expected_host_revision")
    normalized_prepared_at = _text(prepared_at, "prepared_at")

    intent_name = (
        f"{normalized_saga_id}:{normalized_slice_hash}:{normalized_grant_hash}:"
        f"{normalized_binding_hash}:{normalized_host}:{normalized_document}"
    )
    return HostDispatchIntent(
        dispatch_intent_id=uuid5(_DISPATCH_NAMESPACE, intent_name),
        saga_id=normalized_saga_id,
        execution_slice_hash=normalized_slice_hash,
        grant_hash=normalized_grant_hash,
        binding_set_hash=normalized_binding_hash,
        host_instance_id=normalized_host,
        document_ref=normalized_document,
        idempotency_key=uuid5(_IDEMPOTENCY_NAMESPACE, intent_name),
        expected_host_revision=normalized_revision,
        status=HostDispatchStatus.PREPARED,
        intent_revision=0,
        prepared_at=normalized_prepared_at,
    )


__all__ = [
    "HostDispatchIntent",
    "HostDispatchStatus",
    "build_host_dispatch_intent",
]
