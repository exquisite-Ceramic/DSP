"""Execution Saga owner 的 PostgreSQL 基础设施帮助器。"""

from __future__ import annotations

from importlib import resources
from typing import Any

import psycopg

_MIGRATION_PACKAGE = "design_execution_reconciliation.migrations"


def connect_postgres(dsn: str) -> psycopg.Connection[Any]:
    """创建由调用方显式管理生命周期的 PostgreSQL 连接。"""
    if not isinstance(dsn, str):
        raise TypeError("dsn must be a string")
    normalized = dsn.strip()
    if not normalized:
        raise ValueError("dsn is required")
    return psycopg.connect(normalized)


def _migration_resources():
    """按稳定文件名顺序枚举 owner-local SQL migration。"""
    root = resources.files(_MIGRATION_PACKAGE)
    migrations = tuple(
        item
        for item in root.iterdir()
        if item.is_file()
        and item.name.endswith(".sql")
        and len(item.name) >= 5
        and item.name[:4].isdigit()
        and item.name[4] == "_"
    )
    return tuple(sorted(migrations, key=lambda item: item.name))


def _schema_migrations_exists(conn: psycopg.Connection[Any]) -> bool:
    """探测 migration ledger；首个 migration 执行前它可以不存在。"""
    row = conn.execute(
        "SELECT to_regclass('execution_saga.schema_migrations')"
    ).fetchone()
    return bool(row and row[0] is not None)


def _execute_simple_sql_script(conn: psycopg.Connection[Any], sql: str) -> None:
    """执行本包受控的简单 DDL 脚本，不接受外部 SQL 输入。"""
    for statement in sql.split(";"):
        normalized = statement.strip()
        if normalized:
            conn.execute(normalized)


def apply_execution_saga_migrations(conn: psycopg.Connection[Any]) -> None:
    """单调、幂等地应用 Execution Saga owner 自己的 packaged migrations。"""
    if conn is None or not callable(getattr(conn, "execute", None)):
        raise TypeError("conn must be a psycopg connection")

    for migration in _migration_resources():
        with conn.transaction():
            already_applied = False
            if _schema_migrations_exists(conn):
                already_applied = (
                    conn.execute(
                        """
                        SELECT 1
                        FROM execution_saga.schema_migrations
                        WHERE version = %s
                        """,
                        (migration.name,),
                    ).fetchone()
                    is not None
                )
            if already_applied:
                continue

            _execute_simple_sql_script(conn, migration.read_text(encoding="utf-8"))
            conn.execute(
                """
                INSERT INTO execution_saga.schema_migrations (version)
                VALUES (%s)
                ON CONFLICT (version) DO NOTHING
                """,
                (migration.name,),
            )


__all__ = ["apply_execution_saga_migrations", "connect_postgres"]
