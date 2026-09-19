"""ADR-010 orchestrator 的 PostgreSQL checkpoint owner adapter。

LangGraph checkpoint 表只允许存在于 ``orchestrator_checkpoint`` schema。本模块负责 schema
bootstrap、连接级 ``search_path`` 隔离和 saver 生命周期；调用方不会直接管理 LangGraph
``PostgresSaver.from_conn_string`` 的 context-manager 细节。
"""

from __future__ import annotations

from types import TracebackType

import psycopg
from langgraph.checkpoint.postgres import PostgresSaver
from psycopg.rows import dict_row

_OWNER_SCHEMA = "orchestrator_checkpoint"


class OwnedPostgresSaver(PostgresSaver):
    """持有自身 psycopg 连接生命周期的 orchestrator checkpoint saver。

    锁定版 ``PostgresSaver.from_conn_string`` 返回 context manager；若直接把其中的 saver 返回，
    离开 ``with`` 后连接会立即关闭。这个 owner adapter 显式持有 live connection，并提供
    ``close()``/context-manager 语义，保证 runtime restart 测试与生产进程都能确定地释放资源。
    """

    def __init__(self, connection: psycopg.Connection[dict[str, object]]) -> None:
        super().__init__(connection)
        self._owned_connection = connection

    def close(self) -> None:
        """幂等关闭 owner 持有的 PostgreSQL 连接。"""

        if not self._owned_connection.closed:
            self._owned_connection.close()

    def __enter__(self) -> OwnedPostgresSaver:
        """允许测试与应用使用 ``with`` 显式限定 saver 生命周期。"""

        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """离开 owner scope 时关闭连接，不吞掉调用方异常。"""

        del exc_type, exc, traceback
        self.close()
        return False


def create_postgres_checkpointer(dsn: str) -> OwnedPostgresSaver:
    """创建 schema 隔离且可显式关闭的 LangGraph PostgreSQL checkpointer。

    bootstrap 使用独立 autocommit 管理连接；真正交给 LangGraph 的连接同样启用 autocommit，
    并使用 ``dict_row``（这是 PostgresSaver 读取 checkpoint 行的要求）。在调用 ``setup()``
    前先把连接级 ``search_path`` 限制为 orchestrator owner schema，因此库创建的所有未限定名
    checkpoint 表都会落在 ``orchestrator_checkpoint``，不会污染 ``public`` 或其他 owner。
    """

    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("dsn must not be blank")
    normalized_dsn = dsn.strip()

    # Schema bootstrap 与 saver 数据连接分离，避免把 setup 之前的管理操作混入 owner session。
    with psycopg.connect(normalized_dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA IF NOT EXISTS {_OWNER_SCHEMA}")

    connection = psycopg.connect(
        normalized_dsn,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    try:
        # owner schema 是固定常量，不接受用户输入；连接后续只在这个 search_path 下工作。
        connection.execute(f"SET search_path TO {_OWNER_SCHEMA}")
        saver = OwnedPostgresSaver(connection)
        saver.setup()
    except Exception:
        connection.close()
        raise
    return saver


__all__ = ["OwnedPostgresSaver", "create_postgres_checkpointer"]
