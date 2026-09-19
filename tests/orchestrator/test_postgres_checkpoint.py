"""ADR-010 orchestrator PostgreSQL checkpoint owner 的 RED/GREEN 验证。

这里使用真实 PostgreSQL，验证两件事：LangGraph checkpoint 表只能由 orchestrator 自己的
schema 持有；进程级 runtime/checkpointer 重建后，workflow 仍能从同一个 durable checkpoint
恢复，而不是依赖内存对象存活。
"""

from __future__ import annotations

import os

import psycopg
import pytest
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.langgraph_runtime import LangGraphWorkflowRuntime
from design_orchestrator.workflow_contracts import (
    AsyncOperationKind,
    AsyncOperationRef,
    StableRef,
    WorkflowPhase,
    WorkflowResumeCommand,
    WorkflowStartRequest,
)
from design_orchestrator.workflow_services import ExecutionOwnerView, ExecutionSagaView

_OWNER_SCHEMA = "orchestrator_checkpoint"
_DSN = os.getenv("DSP_TEST_POSTGRES_DSN")

pytestmark = pytest.mark.skipif(
    not _DSN,
    reason="DSP_TEST_POSTGRES_DSN is required",
)


class _RestartServices:
    """把 workflow 推进到 proposal interrupt，并在恢复后制造第二个 durable interrupt。"""

    def resolve_host_context(self, task_id: str) -> StableRef:
        return StableRef(f"snapshot-{task_id}", "a" * 64)

    def ensure_context_freshness(self, snapshot_ref: StableRef) -> StableRef:
        return snapshot_ref

    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef:
        return StableRef("operation-postgres", "b" * 64)

    def bind_parameters(self, operation_ref: StableRef) -> AsyncOperationRef:
        return AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="interaction-postgres",
        )

    def ensure_operation_freshness(self, operation_ref: StableRef) -> StableRef:
        return operation_ref

    def analyze_impact(self, operation_ref: StableRef) -> StableRef:
        return StableRef("impact-postgres", "c" * 64)

    def build_changeset(self, impact_ref: StableRef) -> StableRef:
        return StableRef("changeset-postgres", "d" * 64)

    def preview(self, changeset_ref: StableRef) -> StableRef:
        return StableRef("preview-postgres", "e" * 64)

    def request_approval(self, changeset_ref: StableRef) -> StableRef:
        return StableRef("approval-postgres", "f" * 64)

    def plan_execution(
        self,
        changeset_ref: StableRef,
        approval_ref: StableRef,
    ) -> StableRef:
        return StableRef("plan-postgres", "1" * 64)

    def check_revision_barrier(self, execution_plan_ref: StableRef) -> None:
        return None

    def bind_providers(self, execution_plan_ref: StableRef) -> StableRef:
        return StableRef("binding-postgres", "2" * 64)

    def issue_execution_grant(self, execution_plan_ref: StableRef) -> StableRef:
        return StableRef("grant-postgres", "3" * 64)

    def begin_execution(
        self,
        execution_plan_ref: StableRef,
        grant_ref: StableRef,
    ) -> str:
        return "saga-postgres"

    def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView:
        return ExecutionOwnerView(
            saga=ExecutionSagaView(
                saga_id=saga_id,
                saga_revision=0,
                status="READY",
                active_slice_hash=None,
            )
        )

    def verify_reconcile(self, saga_id: str) -> ExecutionOwnerView:
        return ExecutionOwnerView(
            saga=ExecutionSagaView(
                saga_id=saga_id,
                saga_revision=1,
                status="SUCCEEDED",
                active_slice_hash=None,
            )
        )


def _dsn() -> str:
    """返回真实 PostgreSQL DSN；skip marker 已确保 CI lane 中一定存在。"""

    assert _DSN is not None
    return _DSN


def _reset_owner_schema() -> None:
    """每个测试从空 orchestrator owner schema 开始，避免前一用例污染表归属证据。"""

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {_OWNER_SCHEMA} CASCADE")


def _checkpoint_tables() -> set[tuple[str, str]]:
    """读取数据库中所有 LangGraph checkpoint 命名表及其实际 schema。"""

    with psycopg.connect(_dsn(), autocommit=True) as conn:
        rows = conn.execute(
            """
            SELECT table_schema, table_name
            FROM information_schema.tables
            WHERE table_name LIKE 'checkpoint%'
            ORDER BY table_schema, table_name
            """
        ).fetchall()
    return {(str(schema), str(table)) for schema, table in rows}


def _start_request() -> WorkflowStartRequest:
    """构造可跨 runtime 重建复用的稳定启动请求。"""

    return WorkflowStartRequest(
        task_id="task-postgres-restart",
        request_data={"intent": "durable restart proof"},
        initial_host_ref=StableRef("host-postgres", "4" * 64),
        initial_context_ref=None,
    )


def test_factory_creates_all_checkpoint_tables_in_orchestrator_owner_schema() -> None:
    """PostgresSaver.setup() 创建的表不得落入 public 或其他 authoritative owner schema。"""

    _reset_owner_schema()
    checkpointer = create_postgres_checkpointer(_dsn())
    try:
        tables = _checkpoint_tables()
    finally:
        checkpointer.close()

    assert tables
    assert {schema for schema, _ in tables} == {_OWNER_SCHEMA}
    assert {
        "checkpoint_migrations",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
    }.issubset({table for _, table in tables})
    assert {
        "public",
        "execution_saga",
        "gateway",
        "semantic_runtime",
    }.isdisjoint({schema for schema, _ in tables})


def test_restart_reopens_same_checkpoint_and_resumes_after_interrupt() -> None:
    """关闭第一个 saver 后，新 runtime 必须恢复同一 durable pause identity 后再继续 task。"""

    _reset_owner_schema()
    services = _RestartServices()

    saver_a = create_postgres_checkpointer(_dsn())
    runtime_a = LangGraphWorkflowRuntime(services=services, checkpointer=saver_a)
    checkpoint_before = runtime_a.start(_start_request())
    assert checkpoint_before.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert checkpoint_before.pending_interaction is not None
    saver_a.close()

    saver_b = create_postgres_checkpointer(_dsn())
    try:
        runtime_b = LangGraphWorkflowRuntime(services=services, checkpointer=saver_b)
        reopened = runtime_b.get_checkpoint("task-postgres-restart")
        assert reopened == checkpoint_before
        assert reopened is not None
        assert reopened.pending_interaction is not None

        # 重启后的 ACCEPT 必须携带数据库中恢复出的同一个 pause_id；
        # 这证明 durable checkpoint 保存的是可相关联的人机等待，而不是进程内临时状态。
        resumed = runtime_b.resume(
            "task-postgres-restart",
            WorkflowResumeCommand(
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
                payload={},
                pause_id=reopened.pending_interaction.pause_id,
            ),
        )
        assert resumed.phase is WorkflowPhase.PARAMETER_BINDING
        assert resumed.phase is not checkpoint_before.phase
        assert resumed.pending_interaction is None
        assert resumed.async_operation_ref == AsyncOperationRef(
            kind=AsyncOperationKind.INTERACTION_SESSION,
            owner="interaction",
            operation_id="interaction-postgres",
        )
    finally:
        saver_b.close()