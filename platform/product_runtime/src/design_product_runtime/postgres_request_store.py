"""ProductTask request 的 PostgreSQL authoritative owner。"""

from __future__ import annotations

from collections.abc import Mapping

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .accepted_input import AcceptedProductTaskInputV2
from .contracts import (
    ProductTaskRequest,
    ProductTaskRequestError,
    ProductTaskRequestV2,
    product_task_request_payload,
    product_task_request_v2_payload,
)

_OWNER_SCHEMA = "product_task"
_TABLE = "request"
_CONFLICT = "PRODUCT_TASK_REQUEST_CONFLICT"
_INTEGRITY_INVALID = "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"
_VERSION_MISMATCH = "PRODUCT_TASK_REQUEST_VERSION_MISMATCH"
_V1 = "V1"
_V2 = "V2"


class PostgresProductTaskRequestStore:
    """按 task_id create-once 持久化 V1/V2 immutable ProductTask input。"""

    def __init__(self, connection: psycopg.Connection[dict[str, object]]) -> None:
        """接管一个已经锁定 owner search_path 的 PostgreSQL 连接。"""

        self._connection = connection

    def create(self, request: ProductTaskRequest) -> ProductTaskRequest:
        """首次创建 V1 request；同 body replay 幂等，不同 version/body fail closed。"""

        if not isinstance(request, ProductTaskRequest):
            raise TypeError("request must be a ProductTaskRequest")

        inserted = self._connection.execute(
            """
            INSERT INTO request (
                task_id,
                request_version,
                request_hash,
                payload,
                session_binding_hash,
                session_binding_payload
            )
            VALUES (%s, %s, %s, %s, NULL, NULL)
            ON CONFLICT (task_id) DO NOTHING
            RETURNING task_id
            """,
            (
                request.task_id,
                _V1,
                request.request_hash,
                Jsonb(product_task_request_payload(request)),
            ),
        ).fetchone()
        if inserted is not None:
            return request

        row = self._load_row(request.task_id)
        if row is None:
            raise ProductTaskRequestError(
                _INTEGRITY_INVALID,
                "ProductTask insert conflict did not resolve to a durable row",
            )
        if row["request_version"] != _V1:
            raise ProductTaskRequestError(
                _CONFLICT,
                "task_id already owns a different ProductTask request version",
            )
        existing = self._decode_v1(row)
        if existing == request:
            return existing
        raise ProductTaskRequestError(
            _CONFLICT,
            "task_id already owns a different immutable ProductTask request",
        )

    def create_v2(
        self,
        request: ProductTaskRequestV2,
        *,
        session_binding_hash: str,
        session_binding_payload: Mapping[str, object],
    ) -> AcceptedProductTaskInputV2:
        """原子发布 V2 request 与完整 binding body；同 task 只允许一个 immutable winner。"""

        accepted = AcceptedProductTaskInputV2(
            request,
            session_binding_hash,
            session_binding_payload,
        )
        inserted = self._connection.execute(
            """
            INSERT INTO request (
                task_id,
                request_version,
                request_hash,
                payload,
                session_binding_hash,
                session_binding_payload
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (task_id) DO NOTHING
            RETURNING task_id
            """,
            (
                request.task_id,
                _V2,
                request.request_hash,
                Jsonb(product_task_request_v2_payload(request)),
                accepted.session_binding_hash,
                Jsonb(dict(accepted.session_binding_payload)),
            ),
        ).fetchone()
        if inserted is not None:
            return accepted

        row = self._load_row(request.task_id)
        if row is None:
            raise ProductTaskRequestError(
                _INTEGRITY_INVALID,
                "ProductTask V2 insert conflict did not resolve to a durable row",
            )
        if row["request_version"] != _V2:
            raise ProductTaskRequestError(
                _CONFLICT,
                "task_id already owns a different ProductTask request version",
            )
        existing = self._decode_v2(row)
        if existing == accepted:
            return existing
        raise ProductTaskRequestError(
            _CONFLICT,
            "task_id already owns a different immutable ProductTask V2 input",
        )

    def get(self, task_id: str) -> ProductTaskRequest | None:
        """按 exact task_id 读取 V1 request；V2 必须通过显式 get_v2 分流。"""

        normalized = self._validate_task_id(task_id)
        row = self._load_row(normalized)
        if row is None:
            return None
        if row["request_version"] != _V1:
            raise ProductTaskRequestError(
                _VERSION_MISMATCH,
                "task_id belongs to ProductTask request version V2",
            )
        return self._decode_v1(row)

    def get_v2(self, task_id: str) -> AcceptedProductTaskInputV2 | None:
        """按 exact task_id 读取 V2 accepted input，并重新验证 request/binding 完整性。"""

        normalized = self._validate_task_id(task_id)
        row = self._load_row(normalized)
        if row is None:
            return None
        if row["request_version"] != _V2:
            raise ProductTaskRequestError(
                _VERSION_MISMATCH,
                "task_id belongs to ProductTask request version V1",
            )
        return self._decode_v2(row)

    @staticmethod
    def _validate_task_id(task_id: str) -> str:
        """规范 exact task locator；读取 API 不接受 blank 或隐式 latest。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ProductTaskRequestError(
                "PRODUCT_TASK_REQUEST_INVALID",
                "task_id must be a non-blank string",
            )
        return task_id.strip()

    def _load_row(self, task_id: str) -> Mapping[str, object] | None:
        """只按 exact task_id 读取唯一 owner row。"""

        return self._connection.execute(
            """
            SELECT
                task_id,
                request_version,
                request_hash,
                payload,
                session_binding_hash,
                session_binding_payload
            FROM request
            WHERE task_id = %s
            """,
            (task_id,),
        ).fetchone()

    def _decode_v1(self, row: Mapping[str, object]) -> ProductTaskRequest:
        """把 durable V1 row 重建为 contract，并把任何结构损坏归一为 integrity failure。"""

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
                raise ValueError("stored payload keys do not match ProductTask V1 contract")
            if (
                row.get("session_binding_hash") is not None
                or row.get("session_binding_payload") is not None
            ):
                raise ValueError("V1 row must not contain V2 binding columns")

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
                "stored ProductTask V1 request failed integrity validation",
            ) from exc

    def _decode_v2(self, row: Mapping[str, object]) -> AcceptedProductTaskInputV2:
        """把 durable V2 row 重建为 accepted input，并重新验证两份 hash lineage。"""

        try:
            stored_task_id = row["task_id"]
            stored_hash = row["request_hash"]
            payload = row["payload"]
            binding_hash = row["session_binding_hash"]
            binding_payload = row["session_binding_payload"]
            if not isinstance(stored_task_id, str):
                raise TypeError("stored task_id is not a string")
            if not isinstance(stored_hash, str):
                raise TypeError("stored request_hash is not a string")
            if not isinstance(payload, Mapping):
                raise TypeError("stored V2 payload is not a JSON object")
            if set(payload) != {
                "version",
                "project_id",
                "initiating_host_kind",
                "session_ref",
                "session_binding_hash",
                "requested_action",
                "intent_arguments",
            }:
                raise ValueError("stored payload keys do not match ProductTask V2 contract")
            if not isinstance(binding_hash, str):
                raise TypeError("stored session_binding_hash is not a string")
            if not isinstance(binding_payload, Mapping):
                raise TypeError("stored session_binding_payload is not a JSON object")

            request = ProductTaskRequestV2(
                version=payload["version"],
                task_id=stored_task_id,
                project_id=payload["project_id"],
                initiating_host_kind=payload["initiating_host_kind"],
                session_ref=payload["session_ref"],
                session_binding_hash=payload["session_binding_hash"],
                requested_action=payload["requested_action"],
                intent_arguments=payload["intent_arguments"],
                request_hash=stored_hash,
            )
            return AcceptedProductTaskInputV2(
                request,
                binding_hash,
                binding_payload,
            )
        except (KeyError, TypeError, ValueError, ProductTaskRequestError) as exc:
            if isinstance(exc, ProductTaskRequestError) and exc.code == _INTEGRITY_INVALID:
                raise
            raise ProductTaskRequestError(
                _INTEGRITY_INVALID,
                "stored ProductTask V2 accepted input failed integrity validation",
            ) from exc

    def close(self) -> None:
        """幂等关闭 owner 持有的 PostgreSQL 连接。"""

        if not self._connection.closed:
            self._connection.close()


def create_postgres_product_task_request_store(
    dsn: str,
) -> PostgresProductTaskRequestStore:
    """bootstrap/upgrade 独立 owner schema，并返回显式可关闭的 request store。"""

    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("dsn must not be blank")
    normalized_dsn = dsn.strip()

    with psycopg.connect(normalized_dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA IF NOT EXISTS {_OWNER_SCHEMA}")
        admin.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_OWNER_SCHEMA}.{_TABLE} (
                task_id TEXT PRIMARY KEY,
                request_version TEXT NOT NULL DEFAULT 'V1',
                request_hash CHAR(64) NOT NULL,
                payload JSONB NOT NULL,
                session_binding_hash TEXT,
                session_binding_payload JSONB,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        # 历史 V1 数据库只有 request_hash/payload；ADD COLUMN IF NOT EXISTS
        # 让 upgrade 保留原 row，并通过 DEFAULT 'V1' 明确其 frozen version。
        admin.execute(
            f"""
            ALTER TABLE {_OWNER_SCHEMA}.{_TABLE}
            ADD COLUMN IF NOT EXISTS request_version TEXT NOT NULL DEFAULT 'V1'
            """
        )
        admin.execute(
            f"""
            ALTER TABLE {_OWNER_SCHEMA}.{_TABLE}
            ADD COLUMN IF NOT EXISTS session_binding_hash TEXT
            """
        )
        admin.execute(
            f"""
            ALTER TABLE {_OWNER_SCHEMA}.{_TABLE}
            ADD COLUMN IF NOT EXISTS session_binding_payload JSONB
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
