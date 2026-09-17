from __future__ import annotations

import os
from collections import defaultdict

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DSP_TEST_POSTGRES_DSN"),
    reason="DSP_TEST_POSTGRES_DSN is required",
)


def _postgres_api():
    """只在专用 PostgreSQL lane 中加载数据库基础设施，避免离线 collection 泄漏。"""
    from design_execution_reconciliation.postgres import (
        apply_execution_saga_migrations,
        connect_postgres,
    )

    return apply_execution_saga_migrations, connect_postgres


def test_delivery_recovery_tables_are_execution_saga_owned() -> None:
    """ADR-009 的 delivery / Host-effect journal 必须全部位于 execution_saga owner。"""
    apply_execution_saga_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(os.environ["DSP_TEST_POSTGRES_DSN"])
    try:
        conn.execute("DROP SCHEMA IF EXISTS execution_saga CASCADE")
        conn.commit()
        apply_execution_saga_migrations(conn)

        rows = conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'execution_saga'
            """
        ).fetchall()
        names = {row[0] for row in rows}

        assert {
            "outbox",
            "inbox_receipt",
            "host_dispatch_intent",
            "host_dispatch_observation",
        } <= names
    finally:
        conn.close()


def test_delivery_event_fingerprints_are_required() -> None:
    """outbox / inbox 都必须持久化不可空 fingerprint，才能区分合法 replay 与冲突。"""
    apply_execution_saga_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(os.environ["DSP_TEST_POSTGRES_DSN"])
    try:
        apply_execution_saga_migrations(conn)
        rows = conn.execute(
            """
            SELECT table_name, column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = 'execution_saga'
              AND table_name IN ('outbox', 'inbox_receipt')
              AND column_name = 'event_fingerprint'
            ORDER BY table_name
            """
        ).fetchall()

        assert rows == [
            ("inbox_receipt", "event_fingerprint", "NO"),
            ("outbox", "event_fingerprint", "NO"),
        ]
    finally:
        conn.close()


def test_host_dispatch_intent_preserves_single_slice_lineage_constraints() -> None:
    """同一 Saga/Slice 只能有一个 post-admission dispatch lineage。"""
    apply_execution_saga_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(os.environ["DSP_TEST_POSTGRES_DSN"])
    try:
        apply_execution_saga_migrations(conn)
        rows = conn.execute(
            """
            SELECT tc.constraint_name, kcu.column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
              ON tc.constraint_catalog = kcu.constraint_catalog
             AND tc.constraint_schema = kcu.constraint_schema
             AND tc.constraint_name = kcu.constraint_name
            WHERE tc.table_schema = 'execution_saga'
              AND tc.table_name = 'host_dispatch_intent'
              AND tc.constraint_type = 'UNIQUE'
            ORDER BY tc.constraint_name, kcu.ordinal_position
            """
        ).fetchall()

        unique_columns: dict[str, set[str]] = defaultdict(set)
        for constraint_name, column_name in rows:
            unique_columns[constraint_name].add(column_name)

        assert {"saga_id", "execution_slice_hash"} in unique_columns.values()
        assert {"document_ref", "idempotency_key"} in unique_columns.values()
    finally:
        conn.close()
