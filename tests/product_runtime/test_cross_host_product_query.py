"""Task 15：Cross-Host Product Vertical fully-durable offline query matrix。"""

from __future__ import annotations

import os

import psycopg
import pytest
from design_execution_reconciliation import (
    ExecutionReconciliationServiceV2,
    SagaConvergenceOutcome,
)
from design_execution_reconciliation.postgres import (
    apply_execution_saga_migrations,
    connect_postgres,
)
from design_execution_reconciliation.postgres_dispatch_intent import (
    PostgresHostDispatchIntentStore,
)
from design_execution_reconciliation.postgres_evidence import (
    PostgresReconciliationEvidenceStore,
)
from design_execution_reconciliation.postgres_saga_store_v2 import (
    PostgresExecutionSagaStoreV2,
)
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.langgraph_checkpoint_reader import (
    LangGraphWorkflowCheckpointReader,
)
from design_orchestrator.langgraph_runtime import _runtime_config
from design_orchestrator.langgraph_state import (
    CHECKPOINT_CONTRACT_VERSION,
    WorkflowGraphState,
)
from design_orchestrator.proposal_decision_postgres import (
    PostgresProposalDecisionStore,
)
from design_orchestrator.workflow_contracts import StableRef, WorkflowPhase
from design_product_front_door import SessionBindingMemberV2, SessionBindingV2
from design_product_runtime import (
    ProductTaskQueryService,
    ProductTaskRequestV2,
    create_postgres_product_task_request_store,
)
from langgraph.graph import END, START, StateGraph

from tests.product_runtime.conftest import build_cross_host_task15_lineage
from tests.product_runtime.test_cross_host_product_recovery import (
    _complete_first_slice,
)

_SESSION_REF = "session-cross-host-query-task15"


def _dsn() -> str:
    """只在显式 PostgreSQL lane 中执行完全离线 owner restart acceptance。"""

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _reset_and_migrate(dsn: str) -> None:
    """清理本 case 使用的所有 durable owner schemas，并应用 Saga migrations。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        for schema in (
            "product_task",
            "orchestrator_checkpoint",
            "orchestrator_proposal",
            "execution_saga",
        ):
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    connection = connect_postgres(dsn)
    try:
        apply_execution_saga_migrations(connection)
    finally:
        connection.close()


def _binding(ctx) -> SessionBindingV2:
    """从真实 Step31 binding/runtime lineage 构造 exact accepted binding。"""

    members = []
    for execution_slice, binding_set in zip(
        ctx.execution_plan.execution_slices,
        ctx.binding_sets,
        strict=True,
    ):
        target = binding_set.bindings[0].native_targets[0]
        runtime = execution_slice.host_runtime_ref
        members.append(
            SessionBindingMemberV2(
                host_kind=runtime.host_type.upper(),
                role=(
                    "INITIATOR"
                    if runtime.host_type == "revit"
                    else "BOUND_REQUIRED"
                ),
                configured_reference_id=f"task15-query-{runtime.host_type}",
                configured_reference_hash=(
                    "a" * 64
                    if runtime.host_type == "autocad"
                    else "b" * 64
                ),
                transport_locator=f"{runtime.host_type}://task15-query",
                host_instance_id=runtime.host_instance_id,
                document_id=runtime.document_ref,
                native_target_id=target.native_id,
                host_binding_fingerprint=target.host_binding_fingerprint,
            )
        )
    return SessionBindingV2.create(
        session_ref=_SESSION_REF,
        project_id=ctx.project_id,
        semantic_target_id="WALL-001",
        semantic_environment_id=ctx.semantic_environment_id,
        semantic_environment_hash=ctx.semantic_environment_hash,
        topology_environment_id=ctx.case.topology.topology_environment_id,
        topology_revision=ctx.case.topology.topology_revision,
        topology_snapshot_hash=ctx.case.topology.topology_snapshot_hash,
        initiating_host_kind="REVIT",
        members=tuple(members),
    )


def _binding_payload(binding: SessionBindingV2) -> dict[str, object]:
    """生成 ProductTask owner 持久化的完整 immutable binding JSON。"""

    return {
        "session_ref": binding.session_ref,
        "project_id": binding.project_id,
        "semantic_target_id": binding.semantic_target_id,
        "semantic_environment_id": binding.semantic_environment_id,
        "semantic_environment_hash": binding.semantic_environment_hash,
        "topology_environment_id": binding.topology_environment_id,
        "topology_revision": binding.topology_revision,
        "topology_snapshot_hash": binding.topology_snapshot_hash,
        "initiating_host_kind": binding.initiating_host_kind,
        "members": [
            {
                "host_kind": member.host_kind,
                "role": member.role,
                "configured_reference_id": member.configured_reference_id,
                "configured_reference_hash": member.configured_reference_hash,
                "transport_locator": member.transport_locator,
                "host_instance_id": member.host_instance_id,
                "document_id": member.document_id,
                "native_target_id": member.native_target_id,
                "host_binding_fingerprint": member.host_binding_fingerprint,
            }
            for member in binding.members
        ],
        "binding_hash": binding.binding_hash,
    }


def _persist_completed_checkpoint(
    saver,
    *,
    task_id: str,
    saga_id: str,
) -> None:
    """通过真实 LangGraph PostgreSQL saver 写入带 exact Saga identity 的终态导航。"""

    builder = StateGraph(WorkflowGraphState)

    def persist(state: WorkflowGraphState) -> dict[str, object]:
        """节点不产生领域事实，只要求 LangGraph 持久化传入的合法导航状态。"""

        del state
        return {}

    builder.add_node("persist", persist)
    builder.add_edge(START, "persist")
    builder.add_edge("persist", END)
    graph = builder.compile(checkpointer=saver)
    graph.invoke(
        {
            "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
            "task_id": task_id,
            "phase": WorkflowPhase.COMPLETED.value,
            "saga_id": saga_id,
        },
        _runtime_config(task_id),
    )


def test_v2_get_survives_full_owner_restart_and_projects_two_measured_300_reads() -> None:
    """所有可查询 owners 重开后仍返回 exact-task SUCCEEDED，而不触发任何 Host seam。"""

    dsn = _dsn()
    _reset_and_migrate(dsn)
    ctx = build_cross_host_task15_lineage()

    saga_store = PostgresExecutionSagaStoreV2(dsn)
    dispatch_store = PostgresHostDispatchIntentStore(dsn)
    evidence_store = PostgresReconciliationEvidenceStore(dsn)
    request_store = create_postgres_product_task_request_store(dsn)
    decision_store = PostgresProposalDecisionStore(dsn)
    saver = create_postgres_checkpointer(dsn)
    try:
        reconciliation = ExecutionReconciliationServiceV2(
            store=saga_store,
            evidence_store=evidence_store,
        )
        stored = reconciliation.create_saga(
            ctx.case.changeset,
            ctx.case.boundary_v2,
            ctx.materialization_plan,
            ctx.execution_plan,
        )
        for index in range(2):
            stored = _complete_first_slice(
                ctx=ctx,
                service=reconciliation,
                dispatches=dispatch_store,
                stored=stored,
                index=index,
            )
        stored = reconciliation.record_convergence_outcome(
            stored.definition.saga_id,
            SagaConvergenceOutcome.CONVERGED,
            "c" * 64,
            expected_revision=stored.saga_revision,
        )

        binding = _binding(ctx)
        request = ProductTaskRequestV2.create(
            task_id=ctx.case.changeset.task_id,
            project_id=ctx.project_id,
            initiating_host_kind="REVIT",
            session_ref=_SESSION_REF,
            session_binding_hash=binding.binding_hash,
            requested_action="SET_BOUND_WALL_THICKNESS",
            intent_arguments={"thickness": {"value": 999.0, "unit": "mm"}},
        )
        request_store.create_v2(
            request,
            session_binding_hash=binding.binding_hash,
            session_binding_payload=_binding_payload(binding),
        )
        decision_store.claim_accept(
            request.task_id,
            "pause-task15-query",
            StableRef("subject-task15-query", "d" * 64),
        )
        _persist_completed_checkpoint(
            saver,
            task_id=request.task_id,
            saga_id=stored.definition.saga_id,
        )
        saga_id = stored.definition.saga_id
        task_id = request.task_id
    finally:
        saver.close()
        decision_store.close()
        request_store.close()
        evidence_store.close()
        dispatch_store.close()
        saga_store.close()

    # 全部 owner 新建连接，模拟 server/composition 重启且 Hosts 完全不可用。
    reopened_requests = create_postgres_product_task_request_store(dsn)
    reopened_saga = PostgresExecutionSagaStoreV2(dsn)
    reopened_dispatch = PostgresHostDispatchIntentStore(dsn)
    reopened_evidence = PostgresReconciliationEvidenceStore(dsn)
    reopened_decisions = PostgresProposalDecisionStore(dsn)
    reopened_saver = create_postgres_checkpointer(dsn)
    try:
        query = ProductTaskQueryService(
            request_store=reopened_requests,
            checkpoint_reader=LangGraphWorkflowCheckpointReader(
                checkpointer=reopened_saver
            ),
            saga_store=reopened_saga,
            proposal_decision_reader=reopened_decisions,
            dispatch_intent_reader=reopened_dispatch,
            evidence_reader=reopened_evidence,
        )
        view = query.get(task_id)
    finally:
        reopened_saver.close()
        reopened_decisions.close()
        reopened_evidence.close()
        reopened_dispatch.close()
        reopened_saga.close()
        reopened_requests.close()

    assert view is not None
    assert view.version == "V2"
    assert view.status.value == "SUCCEEDED"
    assert view.proposal_state is not None
    assert view.proposal_state.value == "ACCEPTED"
    assert view.saga_id == saga_id
    assert len(view.materializations) == 2
    assert {
        item.host_kind for item in view.materializations
    } == {"AUTOCAD", "REVIT"}
    assert {
        item.verified_thickness_mm for item in view.materializations
    } == {300.0}
    assert all(item.actual_delta_hash for item in view.materializations)
    assert all(item.verification_hash for item in view.materializations)
    assert all(item.evidence_bundle_hash for item in view.materializations)
