from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("DSP_TEST_POSTGRES_DSN"),
    reason="DSP_TEST_POSTGRES_DSN is required",
)


def test_execution_saga_migrations_are_owner_scoped_and_idempotent() -> None:
    # 只有专用 PostgreSQL lane 才加载 psycopg 基础设施；普通 Phase I
    # 离线回归不安装数据库驱动，也不应在 collection 阶段触发该依赖。
    from design_execution_reconciliation.postgres import (
        apply_execution_saga_migrations,
        connect_postgres,
    )

    conn = connect_postgres(os.environ["DSP_TEST_POSTGRES_DSN"])
    try:
        conn.execute("DROP SCHEMA IF EXISTS execution_saga CASCADE")
        conn.commit()

        apply_execution_saga_migrations(conn)
        apply_execution_saga_migrations(conn)

        rows = conn.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_schema IN (
                'execution_saga',
                'semantic_runtime',
                'gateway',
                'changeset'
            )
            ORDER BY table_schema, table_name
            """
        ).fetchall()
        tables = {(row[0], row[1]) for row in rows}

        assert ("execution_saga", "schema_migrations") in tables
        assert ("execution_saga", "saga_v2") in tables
        assert not any(
            schema in {"semantic_runtime", "gateway", "changeset"}
            for schema, _ in tables
        )

        versions = conn.execute(
            """
            SELECT version
            FROM execution_saga.schema_migrations
            ORDER BY version
            """
        ).fetchall()
        assert versions == [("0001_execution_saga_v2.sql",)]
    finally:
        conn.close()
