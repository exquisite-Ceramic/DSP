"""Execution Saga owner 的私有跨 owner delivery 事件契约。"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from uuid import UUID, uuid5

from design_changeset import canonical_hash

from .saga_state_v2 import StoredExecutionSagaV2

_EVENT_NAMESPACE = UUID("61d30c68-1980-5d8a-aeda-b9160e0c8f37")
_PRODUCER_OWNER = "execution_saga"
_SAGA_TRANSITION_EVENT = "SagaTransitioned"


@dataclass(frozen=True, slots=True)
class OwnerEvent:
    """owner-local outbox 中持久化的最小、稳定事件 envelope。"""

    event_id: UUID
    event_fingerprint: str
    event_type: str
    producer_owner: str
    aggregate_ref: str
    aggregate_revision: int | None
    occurred_at: str
    payload: Mapping[str, object]


def compute_event_fingerprint(
    *,
    producer_owner: str,
    event_type: str,
    aggregate_ref: str,
    aggregate_revision: int | None,
    payload: Mapping[str, object],
) -> str:
    """对事件的不可变业务内容计算 canonical fingerprint。

    ``occurred_at`` 只是审计时间，不参与 retry identity；因此同一个逻辑事件在
    重试和恢复期间不会因为时钟变化而得到新的 fingerprint。
    """
    return canonical_hash(
        {
            "producer_owner": producer_owner,
            "event_type": event_type,
            "aggregate_ref": aggregate_ref,
            "aggregate_revision": aggregate_revision,
            "payload": dict(payload),
        }
    )


def _event_id(event_type: str, aggregate_ref: str, revision: int) -> UUID:
    """用 owner + event type + aggregate + revision 生成稳定 UUIDv5。"""
    return uuid5(
        _EVENT_NAMESPACE,
        f"{_PRODUCER_OWNER}:{event_type}:{aggregate_ref}:{revision}",
    )


def build_saga_transition_event(
    before: StoredExecutionSagaV2 | None,
    after: StoredExecutionSagaV2,
    *,
    occurred_at: str,
) -> OwnerEvent:
    """把一个已持久化 Saga revision 投影为最小跨 owner 通知事件。

    事件只携带稳定引用、revision、状态和定义哈希；完整 Saga snapshot 继续由
    Execution Saga owner 持有，消费者需要更多事实时应按 ``aggregate_ref`` 回查。
    """
    if before is not None and not isinstance(before, StoredExecutionSagaV2):
        raise TypeError("before must be StoredExecutionSagaV2 or None")
    if not isinstance(after, StoredExecutionSagaV2):
        raise TypeError("after must be StoredExecutionSagaV2")
    if before is not None and before.definition.saga_id != after.definition.saga_id:
        raise ValueError("before and after must belong to the same Saga")
    if not isinstance(occurred_at, str) or not occurred_at.strip():
        raise ValueError("occurred_at is required")

    payload: dict[str, object] = {
        "saga_id": after.definition.saga_id,
        "saga_revision": after.saga_revision,
        "saga_status": after.status.value,
        "saga_definition_hash": after.definition.saga_definition_hash,
    }
    fingerprint = compute_event_fingerprint(
        producer_owner=_PRODUCER_OWNER,
        event_type=_SAGA_TRANSITION_EVENT,
        aggregate_ref=after.definition.saga_id,
        aggregate_revision=after.saga_revision,
        payload=payload,
    )
    return OwnerEvent(
        event_id=_event_id(
            _SAGA_TRANSITION_EVENT,
            after.definition.saga_id,
            after.saga_revision,
        ),
        event_fingerprint=fingerprint,
        event_type=_SAGA_TRANSITION_EVENT,
        producer_owner=_PRODUCER_OWNER,
        aggregate_ref=after.definition.saga_id,
        aggregate_revision=after.saga_revision,
        occurred_at=occurred_at.strip(),
        payload=payload,
    )


__all__ = [
    "OwnerEvent",
    "build_saga_transition_event",
    "compute_event_fingerprint",
]
