"""ProductTask request 的 PostgreSQL authoritative owner。"""

from __future__ import annotations

from collections.abc import Mapping

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .contracts import (
    ProductTaskRequest,
    ProductTaskRequestError,
    product_task_request_payload,
)

_OWNER_SCHEMA = "product_task"
_TABLE = "request"
_CONFLICT = "PRODUCT_TASK_REQUEST_CONFLICT"
_INTEGRITY_INVALID = "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"


class PostgresProductTaskRequestStore:
    """按 ``task_id`` create-once 持久化 immutable ProductTask request。"""

    def __init__(self, connection: psycopg.Connection[dict[str, object]]) -> None:
        """接管一个已经锁定 owner ``search_path`` 的 PostgreSQL 连接。"""

        self._connection = connection

    def create(self, request: ProductTaskRequest) -> ProductTaskRequest:
        """首次创建 request；同 body replay 幂等，不同 body 对同 task fail closed。"""

        if not isinstance(request, ProductTaskRequest):
            raise TypeError("request must be a ProductTaskRequest")

        inserted = self._connection.execute(
            """
            INSERT INTO request (task_id, request_hash, payload)
            VALUES (%s, %s, %s)
            ON CONFLICT (task_id) DO NOTHING
            RETURNING task_id
            """,
            (
                request.task_id,
                request.request_hash,
                Jsonb(product_task_request_payload(request)),
            ),
        ).fetchone()
        if inserted is not None:
            return request

        existing = self._load(request.task_id)
        if existing is None:
            raise ProductTaskRequestError(
                _INTEGRITY_INVALID,
                "ProductTask insert conflict did not resolve to a durable row",
            )
        if existing == request:
            return existing
        raise ProductTaskRequestError(
            _CONFLICT,
            "task_id already owns a different immutable ProductTask request",
        )

    def get(self, task_id: str) -> ProductTaskRequest | None:
        """按 exact ``task_id`` 读取 request，并重新验证 payload/hash 完整性。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ProductTaskRequestError(
                "PRODUCT_TASK_REQUEST_INVALID",
                "task_id must be a non-blank string",
            )
        return self._load(task_id)

    def _load(self, task_id: str) -> ProductTaskRequest | None:
        """读取 owner row，并把任何 durable-row 结构损坏归一为 integrity failure。"""

        row = self._connection.execute(
            """
            SELECT task_id, request_hash, payload
            FROM request
            WHERE task_id = %s
            """,
            (task_id,),
        ).fetchone()
        if row is None:
            return None

        try:
            stored_task_id = row["task_id"]
            stored_hash = row["request_hash"]
            payload = row["payload"]
            if not isinstance(stored_task_id, str):
                raise TypeError("stored task_id is not a string")
            if not isinstance(stored_hash, str):
                raise TypeError("stored request_hash is not a string")
            if not isinstance(payload, Mapping):
                raise TypeError("stored payload is not a JSON object")
            if set(payload) != {
                "project_id",
                "host_kind",
                "session_ref",
                "requested_action",
                "intent_arguments",
            }:
                raise ValueError("stored payload keys do not match ProductTask contract")

            return ProductTaskRequest(
                task_id=stored_task_id,
                project_id=payload["project_id"],
                host_kind=payload["host_kind"],
                session_ref=payload["session_ref"],
                requested_action=payload["requested_action"],
                intent_arguments=payload["intent_arguments"],
                request_hash=stored_hash,
            )
        except (KeyError, TypeError, ValueError, ProductTaskRequestError) as exc:
            if isinstance(exc, ProductTaskRequestError) and exc.code == _INTEGRITY_INVALID:
                raise
            raise ProductTaskRequestError(
                _INTEGRITY_INVALID,
                "stored ProductTask request failed integrity validation",
            ) from exc

    def close(self) -> None:
        """幂等关闭 owner 持有的 PostgreSQL 连接。"""

        if not self._connection.closed:
            self._connection.close()


def create_postgres_product_task_request_store(
    dsn: str,
) -> PostgresProductTaskRequestStore:
    """bootstrap 独立 owner schema，并返回显式可关闭的 ProductTask request store。"""

    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("dsn must not be blank")
    normalized_dsn = dsn.strip()

    with psycopg.connect(normalized_dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA IF NOT EXISTS {_OWNER_SCHEMA}")
        admin.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_OWNER_SCHEMA}.{_TABLE} (
                task_id TEXT PRIMARY KEY,
                request_hash CHAR(64) NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )

    connection = psycopg.connect(
        normalized_dsn,
        autocommit=True,
        prepare_threshold=0,
        row_factory=dict_row,
    )
    try:
        connection.execute(f"SET search_path TO {_OWNER_SCHEMA}")
    except Exception:
        connection.close()
        raise
    return PostgresProductTaskRequestStore(connection)


__all__ = [
    "PostgresProductTaskRequestStore",
    "create_postgres_product_task_request_store",
]
