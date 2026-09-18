"""Execution Saga owner 的 PostgreSQL transactional outbox 适配器。"""

from __future__ import annotations

from uuid import UUID

from psycopg.types.json import Jsonb

from .contracts import ReconciliationError
from .delivery import OwnerEvent
from .postgres import connect_postgres


def _validate_limit(limit: int) -> int:
    """统一校验 batch limit，避免不同 outbox 入口出现不一致边界。"""
    if not isinstance(limit, int) or isinstance(limit, bool):
        raise TypeError("limit must be an integer")
    if limit <= 0:
        raise ValueError("limit must be positive")
    return limit


def _decode_event_row(row) -> OwnerEvent:
    """把 PostgreSQL outbox 行恢复为稳定的 owner event envelope。"""
    occurred_at = row[5]
    occurred_text = (
        occurred_at.isoformat().replace("+00:00", "Z")
        if hasattr(occurred_at, "isoformat")
        else str(occurred_at)
    )
    return OwnerEvent(
        event_id=row[0] if isinstance(row[0], UUID) else UUID(str(row[0])),
        event_fingerprint=row[1],
        event_type=row[2],
        producer_owner="execution_saga",
        aggregate_ref=row[3],
        aggregate_revision=row[4],
        occurred_at=occurred_text,
        payload=row[6],
    )


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
    normalized_limit = _validate_limit(limit)

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
        (normalized_limit,),
    ).fetchall()
    return tuple(_decode_event_row(row) for row in rows)


class PostgresOutboxStore:
    """为 dispatcher 提供短事务 claim/release/ack 的 owner-local adapter。

    该对象不持有 sink，也不发送任何网络消息。claim transaction 在事件返回给
    dispatcher 之前已经提交，因此外部 ``send`` 永远不会被包进 PostgreSQL 事务。
    """

    def __init__(self, dsn: str) -> None:
        self._conn = connect_postgres(dsn)

    def close(self) -> None:
        """关闭该 store 独占的数据库连接。"""
        self._conn.close()

    def claim_batch(self, *, limit: int = 100) -> tuple[OwnerEvent, ...]:
        """以 30 秒 lease claim 一批可发送事件，并在返回前提交 claim。

        ``FOR UPDATE SKIP LOCKED`` 防止多个 dispatcher 同时等待/持有同一行锁；
        ``claimed_until`` 又保证第一个 claim 提交后，其他 dispatcher 在 lease 有效期
        内仍会跳过该事件。lease 到期后允许再次 claim，这是 at-least-once 的关键。
        """
        normalized_limit = _validate_limit(limit)
        with self._conn.transaction():
            rows = self._conn.execute(
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
                  AND (claimed_until IS NULL OR claimed_until <= now())
                ORDER BY occurred_at, event_id
                FOR UPDATE SKIP LOCKED
                LIMIT %s
                """,
                (normalized_limit,),
            ).fetchall()
            if not rows:
                return ()

            event_ids = [row[0] for row in rows]
            self._conn.execute(
                """
                UPDATE execution_saga.outbox
                SET attempt_count = attempt_count + 1,
                    claimed_until = now() + interval '30 seconds'
                WHERE event_id = ANY(%s)
                """,
                (event_ids,),
            )
            return tuple(_decode_event_row(row) for row in rows)

    def release_claim(self, event_id: UUID) -> None:
        """发送失败后释放未发布事件的 lease，使下一 batch 可以立即重试。"""
        if not isinstance(event_id, UUID):
            raise TypeError("event_id must be UUID")
        with self._conn.transaction():
            self._conn.execute(
                """
                UPDATE execution_saga.outbox
                SET claimed_until = NULL
                WHERE event_id = %s
                  AND published_at IS NULL
                """,
                (event_id,),
            )

    def mark_published(self, event_id: UUID) -> None:
        """幂等确认 delivery；重复 ack 保留第一次 published_at。"""
        if not isinstance(event_id, UUID):
            raise TypeError("event_id must be UUID")
        with self._conn.transaction():
            self._conn.execute(
                """
                UPDATE execution_saga.outbox
                SET published_at = COALESCE(published_at, now()),
                    claimed_until = NULL
                WHERE event_id = %s
                """,
                (event_id,),
            )


__all__ = [
    "PostgresOutboxStore",
    "insert_outbox_event",
    "load_pending_outbox",
]
