"""Execution Saga owner 的 PostgreSQL transactional outbox 适配器。"""

from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Jsonb

from .contracts import ReconciliationError
from .delivery import OwnerEvent


def insert_outbox_event(conn, event: OwnerEvent) -> None:
    """在调用方已开启的 owner-local transaction 内幂等写入一个事件。

    这里绝不提交事务，也不发送网络消息。相同 ``event_id`` 只有在 fingerprint 完全
    相同时才视为安全 replay；同 ID 不同内容说明 deterministic identity 被破坏，必须
    fail closed，不能覆盖已经持久化的事件事实。
    """
    if conn is None or not callable(getattr(conn, "execute", None)):
        raise TypeError("conn must be a psycopg connection")
    if not isinstance(event, OwnerEvent):
        raise TypeError("event must be OwnerEvent")

    cursor = conn.execute(
        """
        INSERT INTO execution_saga.outbox (
            event_id,
            event_fingerprint,
            event_type,
            aggregate_ref,
            aggregate_revision,
            occurred_at,
            payload
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (event_id) DO NOTHING
        """,
        (
            event.event_id,
            event.event_fingerprint,
            event.event_type,
            event.aggregate_ref,
            event.aggregate_revision,
            event.occurred_at,
            Jsonb(dict(event.payload)),
        ),
    )
    if cursor.rowcount == 1:
        return

    row = conn.execute(
        """
        SELECT event_fingerprint
        FROM execution_saga.outbox
        WHERE event_id = %s
        """,
        (event.event_id,),
    ).fetchone()
    if row is None or row[0] != event.event_fingerprint:
        raise ReconciliationError(
            "DELIVERY_EVENT_CONFLICT",
            "outbox event id is already bound to different immutable content",
        )


def load_pending_outbox(conn, *, limit: int) -> tuple[OwnerEvent, ...]:
    """按稳定顺序读取尚未发布的 outbox 事件，不改变 claim/publish 状态。"""
    if conn is None or not callable(getattr(conn, "execute", None)):
        raise TypeError("conn must be a psycopg connection")
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit must be an integer")
    if limit <= 0:
        raise ValueError("limit must be positive")

    rows = conn.execute(
        """
        SELECT event_id,
               event_fingerprint,
               event_type,
               aggregate_ref,
               aggregate_revision,
               occurred_at,
               payload
        FROM execution_saga.outbox
        WHERE published_at IS NULL
        ORDER BY occurred_at, event_id
        LIMIT %s
        """,
        (limit,),
    ).fetchall()

    events: list[OwnerEvent] = []
    for row in rows:
        occurred_at = row[5]
        occurred_text = (
            occurred_at.isoformat().replace("+00:00", "Z")
            if hasattr(occurred_at, "isoformat")
            else str(occurred_at)
        )
        events.append(
            OwnerEvent(
                event_id=row[0] if isinstance(row[0], UUID) else UUID(str(row[0])),
                event_fingerprint=row[1],
                event_type=row[2],
                producer_owner="execution_saga",
                aggregate_ref=row[3],
                aggregate_revision=row[4],
                occurred_at=occurred_text,
                payload=row[6],
            )
        )
    return tuple(events)


__all__ = ["insert_outbox_event", "load_pending_outbox"]
