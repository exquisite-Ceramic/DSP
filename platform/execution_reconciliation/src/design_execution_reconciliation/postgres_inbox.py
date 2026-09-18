"""Execution Saga owner 的 PostgreSQL transactional inbox。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

import psycopg

from .delivery import OwnerEvent
from .postgres import connect_postgres

_ResultT = TypeVar("_ResultT", bound=str | None)


class DeliveryError(RuntimeError):
    """表示跨 owner delivery 在 durable consumption 边界上的结构化失败。"""

    def __init__(self, code: str, message: str) -> None:
        """保存稳定错误码，并保留人类可读的诊断信息。"""
        super().__init__(message)
        self.code = code


class PostgresInbox:
    """把 consumer durable mutation 与 inbox receipt 放进同一事务。"""

    def __init__(self, dsn: str) -> None:
        """创建 inbox 持有的 PostgreSQL 连接。"""
        self._conn = connect_postgres(dsn)

    def close(self) -> None:
        """关闭 inbox 自己持有的 PostgreSQL 连接。"""
        self._conn.close()

    def consume(
        self,
        event: OwnerEvent,
        *,
        apply: Callable[[psycopg.Connection[Any], OwnerEvent], _ResultT],
        processed_at: str,
    ) -> _ResultT:
        """原子消费一个 immutable owner event，并保证重复投递 replay-safe。

        先在同一事务内尝试插入 receipt 占位行。PostgreSQL 的唯一键冲突会让
        并发消费者在 ``event_id`` 上自然串行化：只有成功插入占位行的事务能够
        执行业务 ``apply``；其他事务在首个事务提交后只读取既有结果。

        如果 ``apply`` 抛出异常，业务写入、占位 receipt 和最终结果会由同一个
        PostgreSQL transaction 一起回滚，因此后续 retry 可以重新取得消费权。
        """
        if not isinstance(event, OwnerEvent):
            raise TypeError("event must be OwnerEvent")
        if not callable(apply):
            raise TypeError("apply must be callable")
        if not isinstance(processed_at, str) or not processed_at.strip():
            raise ValueError("processed_at is required")

        with self._conn.transaction():
            inserted = self._conn.execute(
                """
                INSERT INTO execution_saga.inbox_receipt (
                    event_id,
                    event_fingerprint,
                    producer_owner,
                    event_type,
                    source_ref,
                    source_revision,
                    processed_at,
                    result_ref
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, NULL)
                ON CONFLICT (event_id) DO NOTHING
                RETURNING event_id
                """,
                (
                    event.event_id,
                    event.event_fingerprint,
                    event.producer_owner,
                    event.event_type,
                    event.aggregate_ref,
                    event.aggregate_revision,
                    processed_at.strip(),
                ),
            ).fetchone()

            if inserted is None:
                existing = self._conn.execute(
                    """
                    SELECT event_fingerprint, result_ref
                    FROM execution_saga.inbox_receipt
                    WHERE event_id = %s
                    """,
                    (event.event_id,),
                ).fetchone()
                if existing is None:
                    raise RuntimeError("inbox receipt disappeared after event_id conflict")
                if existing[0] != event.event_fingerprint:
                    raise DeliveryError(
                        "DELIVERY_EVENT_CONFLICT",
                        "event_id already exists with a different immutable fingerprint",
                    )
                return existing[1]

            result = apply(self._conn, event)
            if result is not None and not isinstance(result, str):
                raise TypeError("apply result must be str or None")

            self._conn.execute(
                """
                UPDATE execution_saga.inbox_receipt
                SET result_ref = %s
                WHERE event_id = %s
                """,
                (result, event.event_id),
            )
            return result


__all__ = ["DeliveryError", "PostgresInbox"]
