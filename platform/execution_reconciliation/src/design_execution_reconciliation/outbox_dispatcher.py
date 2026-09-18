"""Execution Saga owner 的 at-least-once outbox dispatcher。"""

from __future__ import annotations

from typing import Protocol

from .delivery import OwnerEvent
from .postgres_outbox import PostgresOutboxStore


class OutboxSink(Protocol):
    """跨 owner delivery transport 的最小发送端口。"""

    def send(self, event: OwnerEvent) -> None:
        """发送一个不可变 owner event；transport 可以重复投递同一逻辑事件。"""
        ...


class PostgresOutboxDispatcher:
    """claim 后在数据库事务外发送，并按结果 release/ack 的 dispatcher。"""

    def __init__(self, store: PostgresOutboxStore, sink: OutboxSink) -> None:
        if not isinstance(store, PostgresOutboxStore):
            raise TypeError("store must be PostgresOutboxStore")
        if sink is None or not callable(getattr(sink, "send", None)):
            raise TypeError("sink must provide send(event)")
        self._store = store
        self._sink = sink

    def dispatch_batch(self, *, limit: int = 100) -> int:
        """发送一批 claimed events，并返回本轮成功 ack 的事件数。

        claim transaction 已在 ``claim_batch`` 返回前提交。这里的 ``send`` 因此不在
        PostgreSQL transaction 内。若进程在 send 成功后、ack 前崩溃，lease 到期后
        同一 ``event_id`` + ``event_fingerprint`` 会再次发送，这是预期的 at-least-once
        行为，而不是 exactly-once transport 失败。
        """
        claimed = self._store.claim_batch(limit=limit)
        published = 0
        for event in claimed:
            try:
                self._sink.send(event)
            except Exception:  # noqa: BLE001
                # 这里是任意 transport sink 的故障隔离边界。普通 Exception 都必须
                # 转换为“保持 unpublished + 立即释放 lease”，否则未知 transport
                # 异常会把事件无谓锁住到 lease 到期，削弱计划冻结的 retry 语义。
                self._store.release_claim(event.event_id)
                continue
            self._store.mark_published(event.event_id)
            published += 1
        return published


__all__ = ["OutboxSink", "PostgresOutboxDispatcher"]
