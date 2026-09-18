from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from uuid import UUID

import pytest
from design_execution_reconciliation import OwnerEvent, compute_event_fingerprint

pytestmark = pytest.mark.skipif(
    not os.environ.get("DSP_TEST_POSTGRES_DSN"),
    reason="DSP_TEST_POSTGRES_DSN is required",
)


def _postgres_api():
    """只在专用 PostgreSQL lane 中加载持久化基础设施。"""
    from design_execution_reconciliation.postgres import (
        apply_execution_saga_migrations,
        connect_postgres,
    )

    return apply_execution_saga_migrations, connect_postgres


def _outbox_api():
    """延迟加载 Task 4 API，使普通离线 collection 不依赖未实现的 dispatcher。"""
    from design_execution_reconciliation.outbox_dispatcher import PostgresOutboxDispatcher
    from design_execution_reconciliation.postgres_outbox import (
        PostgresOutboxStore,
        insert_outbox_event,
    )

    return PostgresOutboxDispatcher, PostgresOutboxStore, insert_outbox_event


def _event(index: int = 1) -> OwnerEvent:
    """构造一个稳定、最小的 execution_saga owner event。"""
    event_id = UUID(f"00000000-0000-5000-8000-{index:012d}")
    payload = {
        "saga_id": f"saga-{index}",
        "saga_revision": index,
        "saga_status": "EXECUTING",
        "saga_definition_hash": f"{index:064x}"[-64:],
    }
    fingerprint = compute_event_fingerprint(
        producer_owner="execution_saga",
        event_type="SagaTransitioned",
        aggregate_ref=f"saga-{index}",
        aggregate_revision=index,
        payload=payload,
    )
    return OwnerEvent(
        event_id=event_id,
        event_fingerprint=fingerprint,
        event_type="SagaTransitioned",
        producer_owner="execution_saga",
        aggregate_ref=f"saga-{index}",
        aggregate_revision=index,
        occurred_at=f"2026-09-18T12:00:{index:02d}Z",
        payload=payload,
    )


def _reset_and_insert(*events: OwnerEvent) -> None:
    """为每个 case 建立干净 outbox，并通过 production insert helper 写入事件。"""
    dsn = os.environ["DSP_TEST_POSTGRES_DSN"]
    apply_migrations, connect_postgres = _postgres_api()
    _dispatcher_type, _store_type, insert_outbox_event = _outbox_api()
    conn = connect_postgres(dsn)
    try:
        apply_migrations(conn)
        with conn.transaction():
            conn.execute("TRUNCATE TABLE execution_saga.outbox")
            for event in events:
                insert_outbox_event(conn, event)
    finally:
        conn.close()


class _RecordingSink:
    """线程安全记录收到的不可变 delivery identity。"""

    def __init__(self) -> None:
        self.received: list[tuple[UUID, str]] = []
        self._lock = Lock()

    def send(self, event: OwnerEvent) -> None:
        with self._lock:
            self.received.append((event.event_id, event.event_fingerprint))


class _FailOnceSink(_RecordingSink):
    """第一次发送失败，第二次开始按正常 sink 记录。"""

    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    def send(self, event: OwnerEvent) -> None:
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("synthetic sink failure")
        super().send(event)


def _outbox_row(event_id: UUID):
    """读取 claim/publish 观察字段，测试不依赖 production 对象私有状态。"""
    _apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(os.environ["DSP_TEST_POSTGRES_DSN"])
    try:
        return conn.execute(
            """
            SELECT attempt_count, claimed_until, published_at
            FROM execution_saga.outbox
            WHERE event_id = %s
            """,
            (event_id,),
        ).fetchone()
    finally:
        conn.close()


def test_pending_event_is_sent_and_marked_published() -> None:
    """A: pending -> send 成功 -> published_at 持久化。"""
    event = _event(1)
    _reset_and_insert(event)
    dispatcher_type, store_type, _insert = _outbox_api()
    store = store_type(os.environ["DSP_TEST_POSTGRES_DSN"])
    sink = _RecordingSink()
    try:
        dispatcher = dispatcher_type(store, sink)
        assert dispatcher.dispatch_batch(limit=10) == 1
        assert sink.received == [(event.event_id, event.event_fingerprint)]
        attempt_count, claimed_until, published_at = _outbox_row(event.event_id)
        assert attempt_count == 1
        assert claimed_until is None
        assert published_at is not None
        assert dispatcher.dispatch_batch(limit=10) == 0
    finally:
        store.close()


def test_send_failure_releases_claim_and_retries_same_event() -> None:
    """B: sink 失败后事件保持 unpublished，下一批次重试同一 identity。"""
    event = _event(2)
    _reset_and_insert(event)
    dispatcher_type, store_type, _insert = _outbox_api()
    store = store_type(os.environ["DSP_TEST_POSTGRES_DSN"])
    sink = _FailOnceSink()
    try:
        dispatcher = dispatcher_type(store, sink)
        assert dispatcher.dispatch_batch(limit=10) == 0
        attempt_count, claimed_until, published_at = _outbox_row(event.event_id)
        assert attempt_count == 1
        assert claimed_until is None
        assert published_at is None

        assert dispatcher.dispatch_batch(limit=10) == 1
        assert sink.received == [(event.event_id, event.event_fingerprint)]
        attempt_count, claimed_until, published_at = _outbox_row(event.event_id)
        assert attempt_count == 2
        assert claimed_until is None
        assert published_at is not None
    finally:
        store.close()


def test_crash_after_send_before_publish_causes_expected_duplicate_delivery() -> None:
    """C: send 后 crash、lease 过期后允许同一不可变事件再次发送。"""
    event = _event(3)
    _reset_and_insert(event)
    dispatcher_type, store_type, _insert = _outbox_api()
    dsn = os.environ["DSP_TEST_POSTGRES_DSN"]
    first_store = store_type(dsn)
    sink = _RecordingSink()
    try:
        claimed = first_store.claim_batch(limit=1)
        assert claimed == (event,)
        sink.send(claimed[0])
        # 模拟进程在 send 成功后、mark_published 前消失；数据库中只剩 active lease。
    finally:
        first_store.close()

    _apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        with conn.transaction():
            conn.execute(
                """
                UPDATE execution_saga.outbox
                SET claimed_until = now() - interval '1 second'
                WHERE event_id = %s
                """,
                (event.event_id,),
            )
    finally:
        conn.close()

    second_store = store_type(dsn)
    try:
        dispatcher = dispatcher_type(second_store, sink)
        assert dispatcher.dispatch_batch(limit=1) == 1
    finally:
        second_store.close()

    assert sink.received == [
        (event.event_id, event.event_fingerprint),
        (event.event_id, event.event_fingerprint),
    ]
    attempt_count, claimed_until, published_at = _outbox_row(event.event_id)
    assert attempt_count == 2
    assert claimed_until is None
    assert published_at is not None


def test_two_claimers_never_own_the_same_active_lease() -> None:
    """D: 两个 dispatcher store 同时 claim 时，一个 event 只能被一个 active lease 拿到。"""
    event = _event(4)
    _reset_and_insert(event)
    _dispatcher_type, store_type, _insert = _outbox_api()
    dsn = os.environ["DSP_TEST_POSTGRES_DSN"]
    barrier = Barrier(2)

    def claim_once():
        store = store_type(dsn)
        try:
            barrier.wait(timeout=5)
            return store.claim_batch(limit=1)
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(claim_once)
        second = executor.submit(claim_once)
        results = (first.result(timeout=10), second.result(timeout=10))

    flattened = [claimed for batch in results for claimed in batch]
    assert flattened == [event]
    attempt_count, claimed_until, published_at = _outbox_row(event.event_id)
    assert attempt_count == 1
    assert claimed_until is not None
    assert published_at is None
