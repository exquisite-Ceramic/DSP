"""ProductTask 首次 workflow start 的 PostgreSQL 行锁 gate。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

_OWNER_SCHEMA = "product_task"
_TABLE = "start_gate"


class PostgresProductTaskStartGate:
    """用 owner-local PostgreSQL 行锁串行化同一 task 的首次 workflow start。"""

    def __init__(self, dsn: str) -> None:
        """创建独立连接；不同 gate 实例之间只通过 PostgreSQL 锁协调。"""

        if not isinstance(dsn, str) or not dsn.strip():
            raise ValueError("dsn must not be blank")
        normalized_dsn = dsn.strip()

        # bootstrap 只负责 owner schema/table 存在，不持有任何业务临界区。
        with psycopg.connect(normalized_dsn, autocommit=True) as admin:
            admin.execute(f"CREATE SCHEMA IF NOT EXISTS {_OWNER_SCHEMA}")
            admin.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_OWNER_SCHEMA}.{_TABLE} (
                    task_id TEXT PRIMARY KEY,
                    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
                )
                """
            )

        self._connection = psycopg.connect(
            normalized_dsn,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        try:
            self._connection.execute(f"SET search_path TO {_OWNER_SCHEMA}")
        except Exception:
            self._connection.close()
            raise

    @contextmanager
    def serialize(self, task_id: str) -> Iterator[None]:
        """锁住 exact task 行，直到调用方退出完整 checkpoint→possible-start 临界区。

        首次 task 尚无 gate row 时，``INSERT ... ON CONFLICT`` 本身也受 PostgreSQL 唯一键
        冲突协调；随后 ``SELECT ... FOR UPDATE`` 把已存在/刚创建的同一行锁定到事务结束。
        连接使用 autocommit 仅用于普通 setup；这里的 ``transaction()`` 显式开启真正事务，
        因而异常退出会 rollback 并自动释放锁，不需要进程内 mutex 或恢复标记。
        """

        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-blank string")
        normalized_task_id = task_id.strip()
        if self._connection.closed:
            raise RuntimeError("start gate is closed")

        with self._connection.transaction():
            self._connection.execute(
                """
                INSERT INTO start_gate (task_id)
                VALUES (%s)
                ON CONFLICT (task_id) DO NOTHING
                """,
                (normalized_task_id,),
            )
            row = self._connection.execute(
                """
                SELECT task_id
                FROM start_gate
                WHERE task_id = %s
                FOR UPDATE
                """,
                (normalized_task_id,),
            ).fetchone()
            if row is None or row.get("task_id") != normalized_task_id:
                raise RuntimeError("start gate row could not be locked")
            yield

    def close(self) -> None:
        """幂等关闭 gate 自己持有的 PostgreSQL 连接。"""

        if not self._connection.closed:
            self._connection.close()


__all__ = ["PostgresProductTaskStartGate"]
