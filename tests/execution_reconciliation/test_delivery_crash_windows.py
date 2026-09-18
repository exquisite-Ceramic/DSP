"""Task 9：集中证明 ADR-009 delivery crash windows A-D2。"""

from __future__ import annotations

import os
from dataclasses import replace
from uuid import UUID

import pytest
from design_execution_reconciliation import OwnerEvent, compute_event_fingerprint

from tests.execution_reconciliation.saga_store_v2_contract import (
    build_saga_v2_contract_fixture,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DSP_TEST_POSTGRES_DSN"),
    reason="DSP_TEST_POSTGRES_DSN is required",
)

_NOW = "2026-09-18T15:00:00Z"


def _postgres_api():
    """只在显式 PostgreSQL lane 中加载数据库基础设施。"""
    from design_execution_reconciliation.postgres import (
        apply_execution_saga_migrations,
        connect_postgres,
    )

    return apply_execution_saga_migrations, connect_postgres


def _saga_store_type():
    """延迟加载 Saga PostgreSQL adapter，保持普通离线 collection 可用。"""
    from design_execution_reconciliation.postgres_saga_store_v2 import (
        PostgresExecutionSagaStoreV2,
    )

    return PostgresExecutionSagaStoreV2


def _outbox_store_type():
    """延迟加载 durable outbox store。"""
    from design_execution_reconciliation.postgres_outbox import PostgresOutboxStore

    return PostgresOutboxStore


def _inbox_api():
    """延迟加载 transactional inbox API。"""
    from design_execution_reconciliation.postgres_inbox import (
        DeliveryError,
        PostgresInbox,
    )

    return DeliveryError, PostgresInbox


def _truncate_owner_state(conn) -> None:
    """按 owner-local FK 依赖顺序清空 Task 9 使用的 durable state。"""
    conn.execute(
        """
        TRUNCATE TABLE
            execution_saga.host_dispatch_observation,
            execution_saga.host_dispatch_intent,
            execution_saga.inbox_receipt,
            execution_saga.outbox,
            execution_saga.saga_v2
        """
    )


def _prepare_saga():
    """创建干净 Saga，并移除 create_saga 自身产生的 outbox event。"""
    dsn = os.environ["DSP_TEST_POSTGRES_DSN"]
    apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        apply_migrations(conn)
        with conn.transaction():
            _truncate_owner_state(conn)
    finally:
        conn.close()

    _ctx, definition = build_saga_v2_contract_fixture()
    store = _saga_store_type()(dsn)
    before = store.create_saga(definition)

    conn = connect_postgres(dsn)
    try:
        with conn.transaction():
            conn.execute("TRUNCATE TABLE execution_saga.outbox")
    finally:
        conn.close()
    return dsn, store, definition, before


def _outbox_count(dsn: str) -> int:
    """直接读取 owner-local outbox 行数。"""
    _apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        return conn.execute("SELECT count(*) FROM execution_saga.outbox").fetchone()[0]
    finally:
        conn.close()


def _event() -> OwnerEvent:
    """构造一个稳定 immutable delivery identity，供 C/D/D2 共用。"""
    payload = {
        "saga_id": "saga-crash-window",
        "saga_revision": 9,
        "saga_status": "EXECUTING",
        "saga_definition_hash": "b" * 64,
    }
    fingerprint = compute_event_fingerprint(
        producer_owner="execution_saga",
        event_type="SagaTransitioned",
        aggregate_ref="saga-crash-window",
        aggregate_revision=9,
        payload=payload,
    )
    return OwnerEvent(
        event_id=UUID("20000000-0000-5000-8000-000000000001"),
        event_fingerprint=fingerprint,
        event_type="SagaTransitioned",
        producer_owner="execution_saga",
        aggregate_ref="saga-crash-window",
        aggregate_revision=9,
        occurred_at="2026-09-18T14:59:59Z",
        payload=payload,
    )


def _prepare_consumer_database() -> str:
    """建立只属于测试的 consumer projection，并清空 inbox/projection。"""
    dsn = os.environ["DSP_TEST_POSTGRES_DSN"]
    apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        apply_migrations(conn)
        with conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_saga.test_crash_projection (
                    projection_key text PRIMARY KEY,
                    event_id uuid NOT NULL,
                    event_fingerprint char(64) NOT NULL
                )
                """
            )
            conn.execute("TRUNCATE TABLE execution_saga.inbox_receipt")
            conn.execute("TRUNCATE TABLE execution_saga.test_crash_projection")
    finally:
        conn.close()
    return dsn


def _consumer_counts(dsn: str) -> tuple[int, int]:
    """返回 inbox receipt 与 durable consumer side effect 的行数。"""
    _apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        receipt_count = conn.execute(
            "SELECT count(*) FROM execution_saga.inbox_receipt"
        ).fetchone()[0]
        projection_count = conn.execute(
            "SELECT count(*) FROM execution_saga.test_crash_projection"
        ).fetchone()[0]
        return receipt_count, projection_count
    finally:
        conn.close()


def _insert_projection(conn, incoming: OwnerEvent, key: str) -> str:
    """使用 inbox 提供的同一连接写 consumer durable state。"""
    conn.execute(
        """
        INSERT INTO execution_saga.test_crash_projection (
            projection_key,
            event_id,
            event_fingerprint
        )
        VALUES (%s, %s, %s)
        """,
        (key, incoming.event_id, incoming.event_fingerprint),
    )
    return key


def test_a_rollback_before_local_commit_leaves_no_state_and_no_outbox_event() -> None:
    """A：Saga UPDATE 后、local commit 前失败时，state 与 outbox 必须一起回滚。"""
    dsn, store, definition, before = _prepare_saga()
    _apply_migrations, connect_postgres = _postgres_api()
    trigger_conn = connect_postgres(dsn)
    try:
        trigger_conn.execute(
            """
            CREATE OR REPLACE FUNCTION execution_saga.test_task9_fail_outbox_insert()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'task9 forced outbox failure';
            END;
            $$
            """
        )
        trigger_conn.execute(
            """
            CREATE TRIGGER test_task9_fail_outbox_insert
            BEFORE INSERT ON execution_saga.outbox
            FOR EACH ROW
            EXECUTE FUNCTION execution_saga.test_task9_fail_outbox_insert()
            """
        )
        trigger_conn.commit()
    finally:
        trigger_conn.close()

    try:
        first_hash = definition.ordered_slice_hashes[0]
        with pytest.raises(Exception, match="task9 forced outbox failure"):
            store.reserve_slice_admission(
                definition.saga_id,
                first_hash,
                expected_revision=before.saga_revision,
                reserved_at="2026-09-18T15:01:00Z",
            )
    finally:
        cleanup = connect_postgres(dsn)
        try:
            cleanup.execute(
                "DROP TRIGGER IF EXISTS test_task9_fail_outbox_insert "
                "ON execution_saga.outbox"
            )
            cleanup.execute(
                "DROP FUNCTION IF EXISTS execution_saga.test_task9_fail_outbox_insert()"
            )
            cleanup.commit()
        finally:
            cleanup.close()

    try:
        assert store.get_saga(definition.saga_id) == before
        assert _outbox_count(dsn) == 0
    finally:
        store.close()


def test_b_committed_state_and_outbox_survive_producer_restart() -> None:
    """B：local commit 已完成而 dispatcher 尚未运行时，pending event 必须跨重启存活。"""
    dsn, store, definition, before = _prepare_saga()
    first_hash = definition.ordered_slice_hashes[0]
    try:
        after = store.reserve_slice_admission(
            definition.saga_id,
            first_hash,
            expected_revision=before.saga_revision,
            reserved_at="2026-09-18T15:02:00Z",
        )
    finally:
        store.close()

    # 用全新的 outbox store 代表 producer/dispatcher 进程重启后的读取。
    outbox = _outbox_store_type()(dsn)
    try:
        claimed = outbox.claim_batch(limit=10)
    finally:
        outbox.close()

    assert len(claimed) == 1
    event = claimed[0]
    assert event.aggregate_ref == definition.saga_id
    assert event.aggregate_revision == after.saga_revision
    assert len(event.event_fingerprint) == 64


def test_c_redelivery_after_consumer_rollback_accepts_same_immutable_event() -> None:
    """C：delivery 已发生但 consumer commit 前崩溃，redelivery 必须接受同一 id+fingerprint。"""
    dsn = _prepare_consumer_database()
    _delivery_error, inbox_type = _inbox_api()
    event = _event()
    inbox = inbox_type(dsn)

    def crash_after_write(conn, incoming: OwnerEvent) -> str:
        _insert_projection(conn, incoming, "projection:c")
        raise RuntimeError("synthetic consumer crash before commit")

    try:
        with pytest.raises(RuntimeError, match="synthetic consumer crash before commit"):
            inbox.consume(event, apply=crash_after_write, processed_at=_NOW)
        assert _consumer_counts(dsn) == (0, 0)

        result = inbox.consume(
            event,
            apply=lambda conn, incoming: _insert_projection(
                conn,
                incoming,
                "projection:c",
            ),
            processed_at=_NOW,
        )
    finally:
        inbox.close()

    assert result == "projection:c"
    assert _consumer_counts(dsn) == (1, 1)


def test_d_consumer_commit_before_sender_ack_is_duplicate_safe() -> None:
    """D：consumer 已提交但 sender 未 ack 时，同一事件重投不得重复 durable side effect。"""
    dsn = _prepare_consumer_database()
    _delivery_error, inbox_type = _inbox_api()
    event = _event()
    inbox = inbox_type(dsn)
    calls = 0

    def apply(conn, incoming: OwnerEvent) -> str:
        nonlocal calls
        calls += 1
        return _insert_projection(conn, incoming, "projection:d")

    try:
        first = inbox.consume(event, apply=apply, processed_at=_NOW)
        second = inbox.consume(event, apply=apply, processed_at=_NOW)
    finally:
        inbox.close()

    assert first == second == "projection:d"
    assert calls == 1
    assert _consumer_counts(dsn) == (1, 1)


def test_d2_same_event_id_with_different_fingerprint_is_conflict() -> None:
    """D2：相同 event_id 携带不同 immutable content 必须冲突，不能当普通 duplicate。"""
    dsn = _prepare_consumer_database()
    delivery_error, inbox_type = _inbox_api()
    event = _event()
    inbox = inbox_type(dsn)
    calls = 0

    def apply(conn, incoming: OwnerEvent) -> str:
        nonlocal calls
        calls += 1
        return _insert_projection(conn, incoming, "projection:d2")

    try:
        assert inbox.consume(event, apply=apply, processed_at=_NOW) == "projection:d2"
        conflicting_payload = {**event.payload, "saga_status": "SUCCEEDED"}
        conflicting = replace(
            event,
            payload=conflicting_payload,
            event_fingerprint=compute_event_fingerprint(
                producer_owner=event.producer_owner,
                event_type=event.event_type,
                aggregate_ref=event.aggregate_ref,
                aggregate_revision=event.aggregate_revision,
                payload=conflicting_payload,
            ),
        )

        with pytest.raises(delivery_error) as exc_info:
            inbox.consume(conflicting, apply=apply, processed_at=_NOW)
        assert exc_info.value.code == "DELIVERY_EVENT_CONFLICT"
    finally:
        inbox.close()

    assert calls == 1
    assert _consumer_counts(dsn) == (1, 1)
