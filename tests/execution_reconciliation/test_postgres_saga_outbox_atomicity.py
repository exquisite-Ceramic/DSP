from __future__ import annotations

import os

import pytest

from design_execution_reconciliation import build_saga_transition_event

from tests.execution_reconciliation.saga_store_v2_contract import (
    build_saga_v2_contract_fixture,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DSP_TEST_POSTGRES_DSN"),
    reason="DSP_TEST_POSTGRES_DSN is required",
)


def _postgres_api():
    """只在专用 PostgreSQL lane 中加载数据库基础设施。"""
    from design_execution_reconciliation.postgres import (
        apply_execution_saga_migrations,
        connect_postgres,
    )

    return apply_execution_saga_migrations, connect_postgres


def _store_type():
    """延迟加载 durable adapter，避免离线回归被 PostgreSQL 细节污染。"""
    from design_execution_reconciliation.postgres_saga_store_v2 import (
        PostgresExecutionSagaStoreV2,
    )

    return PostgresExecutionSagaStoreV2


def _clean_owner_tables(conn) -> None:
    """显式清理同一 owner 的依赖表，保持 FK 约束本身不变。"""
    with conn.transaction():
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
    """返回干净 PostgreSQL owner 上的 store、定义与初始 durable Saga。"""
    dsn = os.environ["DSP_TEST_POSTGRES_DSN"]
    apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        apply_migrations(conn)
        _clean_owner_tables(conn)
    finally:
        conn.close()

    _ctx, definition = build_saga_v2_contract_fixture()
    store = _store_type()(dsn)
    before = store.create_saga(definition)

    # 本 case 只观察后续 revision transition；即使 create 后续也产生 owner event，
    # 这里都先清空 outbox，避免把两个独立语义混在同一个断言里。
    conn = connect_postgres(dsn)
    try:
        with conn.transaction():
            conn.execute("TRUNCATE TABLE execution_saga.outbox")
    finally:
        conn.close()
    return store, definition, before


def test_saga_transition_commits_exactly_one_outbox_event() -> None:
    """成功的 Saga CAS transition 必须在同一 owner 中留下一个确定性 outbox event。"""
    dsn = os.environ["DSP_TEST_POSTGRES_DSN"]
    _apply_migrations, connect_postgres = _postgres_api()
    store, definition, before = _prepare_saga()
    try:
        first_hash = definition.ordered_slice_hashes[0]
        after = store.reserve_slice_admission(
            definition.saga_id,
            first_hash,
            expected_revision=before.saga_revision,
            reserved_at="2026-09-18T11:40:00Z",
        )

        conn = connect_postgres(dsn)
        try:
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
                ORDER BY occurred_at, event_id
                """
            ).fetchall()
        finally:
            conn.close()

        assert len(rows) == 1
        row = rows[0]
        expected = build_saga_transition_event(
            before,
            after,
            occurred_at=str(row[5]),
        )
        assert row[0] == expected.event_id
        assert row[1] == expected.event_fingerprint
        assert row[2] == expected.event_type
        assert row[3] == expected.aggregate_ref
        assert row[4] == expected.aggregate_revision
        assert row[6] == expected.payload

        replayed = store.reserve_slice_admission(
            definition.saga_id,
            first_hash,
            expected_revision=before.saga_revision,
            reserved_at="2026-09-18T11:40:00Z",
        )
        assert replayed == after

        conn = connect_postgres(dsn)
        try:
            count = conn.execute(
                "SELECT count(*) FROM execution_saga.outbox"
            ).fetchone()[0]
        finally:
            conn.close()
        assert count == 1
    finally:
        store.close()


def test_outbox_insert_failure_rolls_back_saga_transition() -> None:
    """outbox INSERT 失败时，前面的 Saga UPDATE 也必须由本地 ACID 整体回滚。"""
    dsn = os.environ["DSP_TEST_POSTGRES_DSN"]
    _apply_migrations, connect_postgres = _postgres_api()
    store, definition, before = _prepare_saga()

    trigger_conn = connect_postgres(dsn)
    try:
        trigger_conn.execute(
            """
            CREATE OR REPLACE FUNCTION execution_saga.test_fail_outbox_insert()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                RAISE EXCEPTION 'forced outbox failure';
            END;
            $$
            """
        )
        trigger_conn.execute(
            """
            CREATE TRIGGER test_fail_outbox_insert
            BEFORE INSERT ON execution_saga.outbox
            FOR EACH ROW
            EXECUTE FUNCTION execution_saga.test_fail_outbox_insert()
            """
        )
        trigger_conn.commit()
    finally:
        trigger_conn.close()

    try:
        first_hash = definition.ordered_slice_hashes[0]
        with pytest.raises(Exception, match="forced outbox failure"):
            store.reserve_slice_admission(
                definition.saga_id,
                first_hash,
                expected_revision=before.saga_revision,
                reserved_at="2026-09-18T11:41:00Z",
            )
    finally:
        cleanup_conn = connect_postgres(dsn)
        try:
            cleanup_conn.execute(
                "DROP TRIGGER IF EXISTS test_fail_outbox_insert ON execution_saga.outbox"
            )
            cleanup_conn.execute(
                "DROP FUNCTION IF EXISTS execution_saga.test_fail_outbox_insert()"
            )
            cleanup_conn.commit()
        finally:
            cleanup_conn.close()

    try:
        assert store.get_saga(definition.saga_id) == before
        verify_conn = connect_postgres(dsn)
        try:
            count = verify_conn.execute(
                "SELECT count(*) FROM execution_saga.outbox"
            ).fetchone()[0]
        finally:
            verify_conn.close()
        assert count == 0
    finally:
        store.close()
