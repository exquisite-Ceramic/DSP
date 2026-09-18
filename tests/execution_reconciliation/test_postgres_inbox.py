from __future__ import annotations

import os
from dataclasses import replace
from uuid import UUID

import pytest
from design_execution_reconciliation import OwnerEvent, compute_event_fingerprint

pytestmark = pytest.mark.skipif(
    not os.environ.get("DSP_TEST_POSTGRES_DSN"),
    reason="DSP_TEST_POSTGRES_DSN is required",
)

_NOW = "2026-09-18T12:30:00Z"


def _postgres_api():
    """只在专用 PostgreSQL lane 中加载数据库基础设施。"""
    from design_execution_reconciliation.postgres import (
        apply_execution_saga_migrations,
        connect_postgres,
    )

    return apply_execution_saga_migrations, connect_postgres


def _inbox_api():
    """延迟加载 Task 5 API，使普通离线 collection 不依赖 PostgreSQL inbox。"""
    from design_execution_reconciliation.postgres_inbox import (
        DeliveryError,
        PostgresInbox,
    )

    return DeliveryError, PostgresInbox


def _event() -> OwnerEvent:
    """构造一个稳定的跨 owner 输入事件。"""
    payload = {
        "saga_id": "saga-inbox-1",
        "saga_revision": 7,
        "saga_status": "EXECUTING",
        "saga_definition_hash": "a" * 64,
    }
    fingerprint = compute_event_fingerprint(
        producer_owner="execution_saga",
        event_type="SagaTransitioned",
        aggregate_ref="saga-inbox-1",
        aggregate_revision=7,
        payload=payload,
    )
    return OwnerEvent(
        event_id=UUID("10000000-0000-5000-8000-000000000001"),
        event_fingerprint=fingerprint,
        event_type="SagaTransitioned",
        producer_owner="execution_saga",
        aggregate_ref="saga-inbox-1",
        aggregate_revision=7,
        occurred_at="2026-09-18T12:29:59Z",
        payload=payload,
    )


def _prepare_database() -> str:
    """创建仅测试使用的 consumer projection table，并清空 inbox/projection。"""
    dsn = os.environ["DSP_TEST_POSTGRES_DSN"]
    apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        apply_migrations(conn)
        with conn.transaction():
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS execution_saga.test_projection (
                    projection_key text PRIMARY KEY,
                    event_id uuid NOT NULL,
                    event_fingerprint char(64) NOT NULL
                )
                """
            )
            conn.execute("TRUNCATE TABLE execution_saga.inbox_receipt")
            conn.execute("TRUNCATE TABLE execution_saga.test_projection")
    finally:
        conn.close()
    return dsn


def _counts(dsn: str) -> tuple[int, int]:
    """读取 inbox receipt 与测试 projection 的 durable 行数。"""
    _apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        receipt_count = conn.execute(
            "SELECT count(*) FROM execution_saga.inbox_receipt"
        ).fetchone()[0]
        projection_count = conn.execute(
            "SELECT count(*) FROM execution_saga.test_projection"
        ).fetchone()[0]
        return receipt_count, projection_count
    finally:
        conn.close()


def test_duplicate_same_fingerprint_replays_without_reapplying_effect() -> None:
    """同一不可变事件重复投递时，只执行一次 consumer durable mutation。"""
    dsn = _prepare_database()
    _delivery_error, inbox_type = _inbox_api()
    inbox = inbox_type(dsn)
    event = _event()
    calls = 0

    def apply(conn, incoming: OwnerEvent) -> str:
        nonlocal calls
        calls += 1
        conn.execute(
            """
            INSERT INTO execution_saga.test_projection (
                projection_key,
                event_id,
                event_fingerprint
            )
            VALUES (%s, %s, %s)
            """,
            ("projection:1", incoming.event_id, incoming.event_fingerprint),
        )
        return "projection:1"

    try:
        first = inbox.consume(event, apply=apply, processed_at=_NOW)
        second = inbox.consume(event, apply=apply, processed_at=_NOW)
    finally:
        inbox.close()

    assert first == second == "projection:1"
    assert calls == 1
    assert _counts(dsn) == (1, 1)


def test_same_event_id_with_different_fingerprint_is_conflict() -> None:
    """确定性 event_id 不能掩盖不同 immutable content；冲突必须 fail closed。"""
    dsn = _prepare_database()
    delivery_error, inbox_type = _inbox_api()
    inbox = inbox_type(dsn)
    event = _event()
    calls = 0

    def apply(conn, incoming: OwnerEvent) -> str:
        nonlocal calls
        calls += 1
        conn.execute(
            """
            INSERT INTO execution_saga.test_projection (
                projection_key,
                event_id,
                event_fingerprint
            )
            VALUES (%s, %s, %s)
            """,
            ("projection:1", incoming.event_id, incoming.event_fingerprint),
        )
        return "projection:1"

    try:
        assert inbox.consume(event, apply=apply, processed_at=_NOW) == "projection:1"

        conflicting_payload = {
            **event.payload,
            "saga_status": "SUCCEEDED",
        }
        conflicting_fingerprint = compute_event_fingerprint(
            producer_owner=event.producer_owner,
            event_type=event.event_type,
            aggregate_ref=event.aggregate_ref,
            aggregate_revision=event.aggregate_revision,
            payload=conflicting_payload,
        )
        conflicting_event = replace(
            event,
            event_fingerprint=conflicting_fingerprint,
            payload=conflicting_payload,
        )

        with pytest.raises(delivery_error) as exc:
            inbox.consume(conflicting_event, apply=apply, processed_at=_NOW)
        assert exc.value.code == "DELIVERY_EVENT_CONFLICT"
    finally:
        inbox.close()

    assert calls == 1
    assert _counts(dsn) == (1, 1)


def test_apply_failure_rolls_back_projection_and_inbox_receipt() -> None:
    """consumer mutation 失败时，业务写入与 inbox receipt 必须一起回滚。"""
    dsn = _prepare_database()
    _delivery_error, inbox_type = _inbox_api()
    inbox = inbox_type(dsn)
    event = _event()

    def apply(conn, incoming: OwnerEvent) -> str:
        conn.execute(
            """
            INSERT INTO execution_saga.test_projection (
                projection_key,
                event_id,
                event_fingerprint
            )
            VALUES (%s, %s, %s)
            """,
            ("projection:rollback", incoming.event_id, incoming.event_fingerprint),
        )
        raise RuntimeError("synthetic consumer failure")

    try:
        with pytest.raises(RuntimeError, match="synthetic consumer failure"):
            inbox.consume(event, apply=apply, processed_at=_NOW)
    finally:
        inbox.close()

    assert _counts(dsn) == (0, 0)
