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
        """保存连接参数；每次 gate 临界区必须使用独立 PostgreSQL connection。"""

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

        # 同一个 exact-session composition 会跨 MCP worker threads 复用 gate 实例。
        # 因此不能在实例上共享 psycopg connection；共享 connection 会让并发
        # transaction() 落进同一数据库事务/保存点，FOR UPDATE 无法互相阻塞。
        self._dsn = normalized_dsn
        self._closed = False

    @contextmanager
    def serialize(self, task_id: str) -> Iterator[None]:
        """锁住 exact task 行，直到调用方退出完整 checkpoint→possible-start 临界区。

        首次 task 尚无 gate row 时，``INSERT ... ON CONFLICT`` 本身也受 PostgreSQL 唯一键
        冲突协调；随后 ``SELECT ... FOR UPDATE`` 把已存在/刚创建的同一行锁定到事务结束。
        每次调用都取得独立 connection/transaction，因此同一 gate 实例的并发线程与不同
        进程一样，必须通过 PostgreSQL 行锁竞争，不能退化成同一事务里的嵌套保存点。
        异常退出会 rollback 并自动释放锁，不需要进程内 mutex 或恢复标记。
        """

        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-blank string")
        normalized_task_id = task_id.strip()
        if self._closed:
            raise RuntimeError("start gate is closed")

        with psycopg.connect(
            self._dsn,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        ) as connection:
            connection.execute(f"SET search_path TO {_OWNER_SCHEMA}")
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO start_gate (task_id)
                    VALUES (%s)
                    ON CONFLICT (task_id) DO NOTHING
                    """,
                    (normalized_task_id,),
                )
                row = connection.execute(
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
        """幂等关闭 gate 生命周期；活动临界区各自拥有并关闭自己的 connection。"""

        self._closed = True


class PostgresProductTaskResumeConsumeGate(PostgresProductTaskStartGate):
    """复用同一 ProductTask start_gate 行锁机制串行化 human decision 消费。

    该类型只建立独立语义端口；存储仍是 product_task.start_gate，不创建第二张锁表、
    lease、advisory lock、进程 mutex 或 distributed-lock authority。
    """


__all__ = [
    "PostgresProductTaskResumeConsumeGate",
    "PostgresProductTaskStartGate",
]
