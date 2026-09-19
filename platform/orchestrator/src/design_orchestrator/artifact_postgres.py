"""Workflow Orchestrator deterministic artifact 的 PostgreSQL owner adapter。

完整 workflow-local artifact 只允许落在 ``orchestrator_artifact`` schema；checkpoint 继续只保存
navigation state 与 ``StableRef``。本模块负责 owner schema bootstrap、连接级 ``search_path``、
artifact codec/version 持久化和读取时完整性校验。
"""

from __future__ import annotations

from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from design_orchestrator.default_workflow_services import WorkflowArtifactStore
from design_orchestrator.workflow_artifacts import (
    WORKFLOW_ARTIFACT_CODEC_VERSION,
    WorkflowArtifactCodecError,
    WorkflowArtifactUnavailableError,
    decode_workflow_artifact,
    encode_workflow_artifact,
    workflow_artifact_content_hash,
)
from design_orchestrator.workflow_contracts import StableRef

_OWNER_SCHEMA = "orchestrator_artifact"
_TABLE = "workflow_artifact"


class PostgresWorkflowArtifactStore(WorkflowArtifactStore):
    """持有 owner-local PostgreSQL 连接的 durable ``WorkflowArtifactStore``。"""

    def __init__(self, connection: psycopg.Connection[dict[str, object]]) -> None:
        self._connection = connection

    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef:
        """校验 canonical hash 后幂等持久化 artifact，并返回 opaque stable ref。"""

        expected_hash = workflow_artifact_content_hash(value)
        if not isinstance(content_hash, str) or content_hash != expected_hash:
            raise ValueError("content_hash must equal workflow artifact canonical hash")

        payload = encode_workflow_artifact(kind=kind, value=value)
        artifact_id = str(uuid4())
        row = self._connection.execute(
            """
            INSERT INTO workflow_artifact (
                artifact_id,
                kind,
                codec_version,
                content_hash,
                payload
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (kind, content_hash) DO NOTHING
            RETURNING artifact_id, content_hash
            """,
            (
                artifact_id,
                kind,
                WORKFLOW_ARTIFACT_CODEC_VERSION,
                content_hash,
                Jsonb(payload),
            ),
        ).fetchone()
        if row is None:
            row = self._connection.execute(
                """
                SELECT artifact_id, content_hash
                FROM workflow_artifact
                WHERE kind = %s AND content_hash = %s
                """,
                (kind, content_hash),
            ).fetchone()
        if row is None:
            raise WorkflowArtifactUnavailableError(
                "workflow artifact insert did not produce a durable row"
            )
        return StableRef(
            ref_id=str(row["artifact_id"]),
            content_hash=str(row["content_hash"]),
        )

    def get(self, ref: StableRef) -> object:
        """按 opaque ref 读取 artifact，并逐层验证 ref、row、codec 与 canonical hash。"""

        if not isinstance(ref, StableRef):
            raise TypeError("ref must be a StableRef")
        if not isinstance(ref.content_hash, str) or not ref.content_hash:
            raise WorkflowArtifactUnavailableError(
                "workflow artifact ref requires content_hash"
            )

        row = self._connection.execute(
            """
            SELECT kind, codec_version, content_hash, payload
            FROM workflow_artifact
            WHERE artifact_id = %s
            """,
            (ref.ref_id,),
        ).fetchone()
        if row is None:
            raise WorkflowArtifactUnavailableError("workflow artifact row is unavailable")

        row_hash = str(row["content_hash"])
        if row_hash != ref.content_hash:
            raise WorkflowArtifactUnavailableError(
                "workflow artifact ref hash does not match durable row"
            )

        payload = row["payload"]
        if not isinstance(payload, dict):
            raise WorkflowArtifactUnavailableError(
                "workflow artifact payload is not a JSON object"
            )
        try:
            value = decode_workflow_artifact(
                kind=str(row["kind"]),
                codec_version=int(row["codec_version"]),
                payload=payload,
            )
            decoded_hash = workflow_artifact_content_hash(value)
        except (WorkflowArtifactCodecError, TypeError, ValueError) as exc:
            raise WorkflowArtifactUnavailableError(
                "workflow artifact codec or integrity validation failed"
            ) from exc

        if decoded_hash != row_hash:
            raise WorkflowArtifactUnavailableError(
                "workflow artifact canonical hash does not match durable row"
            )
        return value

    def close(self) -> None:
        """幂等关闭 owner 持有的数据连接。"""

        if not self._connection.closed:
            self._connection.close()


def create_postgres_artifact_store(dsn: str) -> PostgresWorkflowArtifactStore:
    """创建 schema 隔离、可显式关闭的 PostgreSQL workflow artifact store。"""

    if not isinstance(dsn, str) or not dsn.strip():
        raise ValueError("dsn must not be blank")
    normalized_dsn = dsn.strip()

    with psycopg.connect(normalized_dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA IF NOT EXISTS {_OWNER_SCHEMA}")
        admin.execute(
            f"""
            CREATE TABLE IF NOT EXISTS {_OWNER_SCHEMA}.{_TABLE} (
                artifact_id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                codec_version INTEGER NOT NULL,
                content_hash CHAR(64) NOT NULL,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                UNIQUE (kind, content_hash)
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
    return PostgresWorkflowArtifactStore(connection)


__all__ = ["PostgresWorkflowArtifactStore", "create_postgres_artifact_store"]
