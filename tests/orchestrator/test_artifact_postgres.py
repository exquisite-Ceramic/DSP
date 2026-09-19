"""Workflow Orchestrator durable artifact owner 的 PostgreSQL RED/GREEN 验证。"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from importlib import import_module
from typing import Any
from uuid import UUID

import pytest
from design_orchestrator.canonical_operations import MOVE_V1
from design_orchestrator.operation_resolver import (
    OperationResolver,
    ResolutionContext,
    ResolutionResult,
    SemanticEligibilityContext,
)
from design_orchestrator.workflow_artifacts import (
    WORKFLOW_ARTIFACT_CODEC_VERSION,
    WorkflowArtifactUnavailableError,
    workflow_artifact_content_hash,
)
from design_orchestrator.workflow_contracts import StableRef

# 该文件只属于真实 PostgreSQL 验证 lane。旧的非 PostgreSQL workflow 不安装 psycopg，
# 因此必须在加载 PostgreSQL adapter 前做模块级 skip，避免可选依赖污染无关测试收集。
psycopg = pytest.importorskip(
    "psycopg",
    reason="psycopg is required for PostgreSQL artifact tests",
)
create_postgres_artifact_store = import_module(
    "design_orchestrator.artifact_postgres"
).create_postgres_artifact_store

_OWNER_SCHEMA = "orchestrator_artifact"
_DSN = os.getenv("DSP_TEST_POSTGRES_DSN")

pytestmark = pytest.mark.skipif(
    not _DSN,
    reason="DSP_TEST_POSTGRES_DSN is required",
)


@dataclass(frozen=True, slots=True)
class _Profile:
    """构造可进入真实 OperationResolver 的最小 capability profile。"""

    provider_server: str = "autocad.local"
    provider_tool: str = "cad.move"
    canonical_operation: str = "move.v1"
    category: str = "MODEL_OPERATION"
    entity_constraints: tuple[str, ...] = ("LINE", "ARC")
    execution_freshness: tuple[dict[str, Any], ...] = (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    effects: tuple[str, ...] = ("PLACEMENT", "GEOMETRY")
    existence_effects: tuple[str, ...] = ()
    risk: str | None = "LOW"
    preview_supported: bool = False
    rollback_supported: bool = False
    idempotent: bool = True
    verification_contract: dict[str, Any] = field(
        default_factory=lambda: {"type": "HOST_READ_BACK"}
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "handles": {"type": "array", "items": {"type": "string"}},
                "dx": {"type": "number"},
                "dy": {"type": "number"},
            },
            "required": ["handles", "dx", "dy"],
        }
    )
    output_schema: dict[str, Any] | None = None
    description: str | None = "PostgreSQL artifact fixture"


def _dsn() -> str:
    """返回真实 PostgreSQL DSN；CI PostgreSQL lane 会提供该环境变量。"""

    assert _DSN is not None
    return _DSN


def _reset_owner_schema() -> None:
    """每个测试从空 artifact owner schema 开始，避免跨用例污染。"""

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {_OWNER_SCHEMA} CASCADE")


def _resolution() -> ResolutionResult:
    """通过真实 resolver 生成 durable artifact。"""

    return OperationResolver((MOVE_V1,)).resolve(
        (_Profile(),),
        ResolutionContext(
            host_provider_servers=frozenset({"autocad.local"}),
            semantic_context=SemanticEligibilityContext(
                context_snapshot_id="CS-artifact-postgres",
                context_snapshot_hash="snapshot-artifact-postgres",
                document_ref="drawing-artifact-postgres",
                semantic_environment_ref="semantic-env@artifact-postgres",
                entities=(),
            ),
        ),
    )


def _put_resolution() -> tuple[object, StableRef, ResolutionResult]:
    """写入一个真实 resolution artifact，并返回 store、引用和原始对象。"""

    resolution = _resolution()
    store = create_postgres_artifact_store(_dsn())
    ref = store.put(
        kind="operation_resolution",
        value=resolution,
        content_hash=workflow_artifact_content_hash(resolution),
    )
    return store, ref, resolution


def _artifact_tables() -> set[tuple[str, str]]:
    """读取 workflow_artifact 同名表实际归属，禁止污染其他 owner schema。"""

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        rows = conn.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_name = 'workflow_artifact'
            ORDER BY table_schema, table_name
            """
        ).fetchall()
    return {(str(schema), str(table)) for schema, table in rows}


def _tamper(sql: str, *params: object) -> None:
    """仅供 corruption tests 直接破坏 owner row，验证 get() 的 fail-closed 行为。"""

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        conn.execute(f"SET search_path TO {_OWNER_SCHEMA}")
        conn.execute(sql, params)


def test_store_reopens_artifact_after_process_owned_connection_restart() -> None:
    """关闭 store A 后，store B 必须从 PostgreSQL 恢复同一 deterministic artifact。"""

    _reset_owner_schema()
    store_a, ref, resolution = _put_resolution()
    assert UUID(ref.ref_id)
    store_a.close()

    store_b = create_postgres_artifact_store(_dsn())
    try:
        restored = store_b.get(ref)
    finally:
        store_b.close()

    assert isinstance(restored, ResolutionResult)
    assert restored.resolved_operations == resolution.resolved_operations
    assert workflow_artifact_content_hash(restored) == ref.content_hash


def test_artifact_table_exists_only_in_orchestrator_artifact_schema() -> None:
    """Artifact table 只能由 orchestrator_artifact owner schema 持有。"""

    _reset_owner_schema()
    store = create_postgres_artifact_store(_dsn())
    try:
        tables = _artifact_tables()
    finally:
        store.close()

    assert tables == {(_OWNER_SCHEMA, "workflow_artifact")}
    assert {
        "public",
        "orchestrator_checkpoint",
        "execution_saga",
        "gateway",
        "semantic_runtime",
    }.isdisjoint({schema for schema, _ in tables})


def test_duplicate_semantic_put_returns_same_stable_ref() -> None:
    """相同 kind + canonical content hash 必须幂等返回同一 opaque artifact ref。"""

    _reset_owner_schema()
    resolution = _resolution()
    content_hash = workflow_artifact_content_hash(resolution)
    store = create_postgres_artifact_store(_dsn())
    try:
        first = store.put(
            kind="operation_resolution",
            value=resolution,
            content_hash=content_hash,
        )
        second = store.put(
            kind="operation_resolution",
            value=resolution,
            content_hash=content_hash,
        )
    finally:
        store.close()

    assert first == second


def test_put_rejects_mismatched_hash_before_touching_closed_connection() -> None:
    """调用方 supplied hash 错误必须在任何 SQL 前 fail closed。"""

    _reset_owner_schema()
    store = create_postgres_artifact_store(_dsn())
    store.close()

    with pytest.raises(ValueError, match="content_hash"):
        store.put(
            kind="operation_resolution",
            value=_resolution(),
            content_hash="0" * 64,
        )


def test_get_rejects_payload_tamper() -> None:
    """JSONB payload 被改写后不得返回伪造 artifact。"""

    _reset_owner_schema()
    store, ref, _ = _put_resolution()
    store.close()
    _tamper(
        "UPDATE workflow_artifact SET payload = %s::jsonb WHERE artifact_id = %s",
        '{"resolved_operations": [], "provider_candidates": {}}',
        ref.ref_id,
    )

    reopened = create_postgres_artifact_store(_dsn())
    try:
        with pytest.raises(WorkflowArtifactUnavailableError):
            reopened.get(ref)
    finally:
        reopened.close()


def test_get_rejects_unknown_codec_version() -> None:
    """数据库中的未知 codec version 必须归一化为 artifact unavailable。"""

    _reset_owner_schema()
    store, ref, _ = _put_resolution()
    store.close()
    _tamper(
        "UPDATE workflow_artifact SET codec_version = %s WHERE artifact_id = %s",
        WORKFLOW_ARTIFACT_CODEC_VERSION + 1,
        ref.ref_id,
    )

    reopened = create_postgres_artifact_store(_dsn())
    try:
        with pytest.raises(WorkflowArtifactUnavailableError):
            reopened.get(ref)
    finally:
        reopened.close()


def test_get_rejects_wrong_ref_hash_and_missing_row() -> None:
    """引用 hash 不匹配或 row 不存在都必须 fail closed。"""

    _reset_owner_schema()
    store, ref, _ = _put_resolution()
    try:
        with pytest.raises(WorkflowArtifactUnavailableError):
            store.get(StableRef(ref.ref_id, "f" * 64))
        with pytest.raises(WorkflowArtifactUnavailableError):
            store.get(StableRef("00000000-0000-0000-0000-000000000000", ref.content_hash))
    finally:
        store.close()


def test_get_requires_ref_content_hash_and_close_is_idempotent() -> None:
    """完整性引用必须携带 hash；owner connection close 可安全重复调用。"""

    _reset_owner_schema()
    store, ref, _ = _put_resolution()
    try:
        with pytest.raises(WorkflowArtifactUnavailableError):
            store.get(StableRef(ref.ref_id))
    finally:
        store.close()
        store.close()
