"""Task 15：Cross-Host Product Vertical real-owner stale matrix。"""

from __future__ import annotations

import os
from dataclasses import replace

import psycopg
import pytest
from design_execution_reconciliation.postgres import (
    apply_execution_saga_migrations,
    connect_postgres,
)
from design_execution_reconciliation.postgres_saga_store_v2 import (
    PostgresExecutionSagaStoreV2,
)
from design_orchestrator.artifact_postgres import create_postgres_artifact_store
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.interaction_artifacts import (
    CrossHostOperationProposalSubjectV2,
    CrossHostProposalObservationV2,
)
from design_orchestrator.langgraph_checkpoint_reader import (
    LangGraphWorkflowCheckpointReader,
)
from design_orchestrator.langgraph_runtime import _runtime_config
from design_orchestrator.langgraph_state import (
    CHECKPOINT_CONTRACT_VERSION,
    WorkflowGraphState,
    encode_pending_interaction,
)
from design_orchestrator.proposal_decision import (
    HumanDecisionState,
    ProposalContinuationState,
)
from design_orchestrator.proposal_decision_postgres import (
    PostgresProposalDecisionStore,
)
from design_orchestrator.workflow_artifacts import workflow_artifact_content_hash
from design_orchestrator.workflow_contracts import (
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowPhase,
)
from design_product_front_door.service import ProductFrontDoorService
from design_product_runtime import (
    PostgresProductTaskResumeConsumeGate,
    ProductTaskQueryService,
    ProductTaskRequestV2,
    ProductTaskV2Status,
    create_postgres_product_task_request_store,
)
from langgraph.graph import END, START, StateGraph

from tests.product_runtime.conftest import build_cross_host_task15_lineage
from tests.product_runtime.test_cross_host_product_query import (
    _binding,
    _binding_payload,
)

_PAUSE_ID = "pause-cross-host-task15-stale"


def _dsn() -> str:
    """只在显式 PostgreSQL lane 中执行真实 stale-owner acceptance。"""

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _reset(dsn: str) -> None:
    """清理 Gate A 用到的 durable owners，并应用 execution-saga migrations。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        for schema in (
            "product_task",
            "orchestrator_checkpoint",
            "orchestrator_artifact",
            "orchestrator_proposal",
            "execution_saga",
        ):
            conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    connection = connect_postgres(dsn)
    try:
        apply_execution_saga_migrations(connection)
    finally:
        connection.close()


def _observations(ctx, binding) -> tuple[CrossHostProposalObservationV2, ...]:
    """从 exact Step31 binding/runtime lineage构造用户实际看到的双 Host 状态。"""

    by_host = {item.host_kind: item for item in binding.members}
    values = []
    for execution_slice, binding_set in zip(
        ctx.execution_plan.execution_slices,
        ctx.binding_sets,
        strict=True,
    ):
        runtime = execution_slice.host_runtime_ref
        host_kind = runtime.host_type.upper()
        member = by_host[host_kind]
        native_target = binding_set.bindings[0].native_targets[0]
        expected_revision = binding_set.bindings[0].native_binding_metadata[
            "expected_revision"
        ]
        values.append(
            CrossHostProposalObservationV2(
                host_kind=host_kind,
                host_instance_id=runtime.host_instance_id,
                document_id=runtime.document_ref,
                native_target_id=native_target.native_id,
                semantic_target_id=member.host_binding_fingerprint
                and binding.semantic_target_id,
                host_revision=expected_revision,
                normalized_thickness_mm=200.0,
                observed_at=(
                    "2026-10-07T06:45:00Z"
                    if host_kind == "AUTOCAD"
                    else "2026-10-07T06:45:01Z"
                ),
                command_id=f"proposal-task15-{runtime.host_type}",
            )
        )
    return tuple(values)


def _persist_pending_checkpoint(saver, *, task_id: str, subject_ref: StableRef) -> None:
    """通过真实 LangGraph saver 写入 V2 Operation Proposal navigation state。"""

    pending = PendingInteractionView(
        pause_id=_PAUSE_ID,
        kind=PendingInteractionKind.OPERATION_PROPOSAL,
        subject_ref=subject_ref,
        allowed_resume_kinds=(
            "OPERATION_PROPOSAL_ACCEPTED",
            "OPERATION_PROPOSAL_REJECTED",
        ),
    )
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
            "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
            "proposal_subject_ref": {
                "ref_id": subject_ref.ref_id,
                "content_hash": subject_ref.content_hash,
            },
            "pending_interaction": encode_pending_interaction(pending),
        },
        _runtime_config(task_id),
    )


class _FreshObservationReader:
    """唯一允许的外部 Host double；只模拟 Gate A fresh READ。"""

    def __init__(
        self,
        accepted: tuple[CrossHostProposalObservationV2, ...],
        *,
        drift_host: str,
    ) -> None:
        self._values = {item.host_kind: item for item in accepted}
        self._drift_host = drift_host
        self.calls: list[str] = []

    def read(self, *, binding, member, command_id: str):
        """metadata 可重采；指定 Host revision 漂移形成稳定状态变化。"""

        assert member in binding.members
        assert command_id
        self.calls.append(member.host_kind)
        value = self._values[member.host_kind]
        fresh = replace(
            value,
            observed_at="2026-10-07T06:46:00Z",
            command_id=f"gate-a-task15-{member.host_kind.lower()}",
        )
        if member.host_kind == self._drift_host:
            fresh = replace(fresh, host_revision=fresh.host_revision + 1)
        return fresh


class _Forbidden:
    """Gate A stale 后任何 flow/composition/Host mutation 访问都视为正确性失败。"""

    def __getattr__(self, name: str):
        raise AssertionError(f"stale path touched forbidden dependency: {name}")

    def __call__(self, *args, **kwargs):
        raise AssertionError(f"stale path called forbidden dependency: {args=} {kwargs=}")


def test_gate_a_drift_uses_durable_v2_checkpoint_and_never_consumes_old_accept() -> None:
    """真实 V2 query/checkpoint 下，漂移必须发布 STALE_GATE_A 并在 flow.resume 前终止。"""

    dsn = _dsn()
    _reset(dsn)
    ctx = build_cross_host_task15_lineage()
    binding = _binding(ctx)
    request = ProductTaskRequestV2.create(
        task_id=ctx.case.changeset.task_id,
        project_id=ctx.project_id,
        initiating_host_kind="REVIT",
        session_ref=binding.session_ref,
        session_binding_hash=binding.binding_hash,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )
    accepted_observations = _observations(ctx, binding)
    subject = CrossHostOperationProposalSubjectV2(
        request_hash=request.request_hash,
        session_binding_hash=binding.binding_hash,
        topology_snapshot_hash=binding.topology_snapshot_hash,
        semantic_target_id=binding.semantic_target_id,
        semantic_environment_id=binding.semantic_environment_id,
        semantic_environment_hash=binding.semantic_environment_hash,
        canonical_operation="set_wall_thickness.v1",
        canonical_arguments={
            "thickness": {"value": 300.0, "unit": "mm"},
            "targets": [binding.semantic_target_id],
        },
        observations=accepted_observations,
    )

    requests = create_postgres_product_task_request_store(dsn)
    decisions = PostgresProposalDecisionStore(dsn)
    artifacts = create_postgres_artifact_store(dsn)
    saver = create_postgres_checkpointer(dsn)
    saga_store = PostgresExecutionSagaStoreV2(dsn)
    gate = PostgresProductTaskResumeConsumeGate(dsn)
    try:
        requests.create_v2(
            request,
            session_binding_hash=binding.binding_hash,
            session_binding_payload=_binding_payload(binding),
        )
        subject_ref = artifacts.put(
            kind="cross_host_operation_proposal_subject_v2",
            value=subject,
            content_hash=workflow_artifact_content_hash(subject),
        )
        _persist_pending_checkpoint(
            saver,
            task_id=request.task_id,
            subject_ref=subject_ref,
        )
        query = ProductTaskQueryService(
            request_store=requests,
            checkpoint_reader=LangGraphWorkflowCheckpointReader(
                checkpointer=saver
            ),
            saga_store=saga_store,
            proposal_decision_reader=decisions,
        )
        host_reads = _FreshObservationReader(
            accepted_observations,
            drift_host="REVIT",
        )
        service = ProductFrontDoorService(
            session_binding_reader=_Forbidden(),
            candidate_source=_Forbidden(),
            context_probe=_Forbidden(),
            transport_factory=_Forbidden(),
            query_service=query,
            composition_pool=_Forbidden(),
            proposal_decision_store=decisions,
            decision_consume_gate=gate,
            interaction_subject_reader=artifacts,
            cross_host_observation_reader=host_reads,
            v2_flow_resolver=_Forbidden(),
        )

        with pytest.raises(ValueError, match="FRONT_DOOR_PROPOSAL_STALE"):
            service.resume_operation_proposal(
                task_id=request.task_id,
                pause_id=_PAUSE_ID,
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            )

        record = decisions.get(request.task_id, _PAUSE_ID, subject_ref)
        assert record is not None
        assert record.human_decision is HumanDecisionState.AWAITING
        assert record.continuation is ProposalContinuationState.STALE_GATE_A
        assert host_reads.calls == ["AUTOCAD", "REVIT"]

        view = service.get(request.task_id)
        assert view is not None
        assert view.status is ProductTaskV2Status.STALE
        assert view.proposal_state is not None
        assert view.proposal_state.value == "STALE_GATE_A"
    finally:
        gate.close()
        saga_store.close()
        saver.close()
        artifacts.close()
        decisions.close()
        requests.close()



def test_gate_b_decision_adapter_preserves_postgres_accept_history() -> None:
    """subject-based continuation seam 必须只投影现有 owner，不复制 pause/state。"""

    from design_product_runtime.cross_host_reference_composition import (
        ProposalDecisionContinuationAdapter,
    )

    dsn = _dsn()
    _reset(dsn)
    decisions = PostgresProposalDecisionStore(dsn)
    subject_ref = StableRef("subject-task15-gate-b", "e" * 64)
    try:
        accepted = decisions.claim_accept(
            "task-task15-gate-b",
            "pause-task15-gate-b",
            subject_ref,
        )
        adapter = ProposalDecisionContinuationAdapter(decisions)

        assert adapter.get_by_subject(
            "task-task15-gate-b",
            subject_ref,
        ) == accepted

        stale = adapter.invalidate_gate_b_by_subject(
            "task-task15-gate-b",
            subject_ref,
            "REVIT_PLANNING_CONTINUITY_DRIFT",
        )
        assert stale.human_decision is HumanDecisionState.ACCEPTED
        assert stale.continuation is ProposalContinuationState.STALE_GATE_B
        assert stale.revision == accepted.revision + 1
        assert decisions.get(
            "task-task15-gate-b",
            "pause-task15-gate-b",
            subject_ref,
        ) == stale
    finally:
        decisions.close()


class _PlanningPort:
    """focused composition double；只证明 exact runtime/document 路由，不模拟语义 owner。"""

    def __init__(self, runtime_ref, revision: str) -> None:
        self.runtime_ref = runtime_ref
        self.revision = revision
        self.reconstruction_calls = []

    def current_revision(self, document_ref: str) -> str:
        """只接受自身 exact document。"""

        assert document_ref == self.runtime_ref.document_ref
        return self.revision

    def reconstruct_member(self, **kwargs):
        """记录 exact member route；focused test 不进入 semantic reconstruction。"""

        self.reconstruction_calls.append(kwargs)
        return ("member", self.runtime_ref.host_type)


def test_cross_host_planning_composition_uses_exact_runtime_and_document_routes() -> None:
    """planning composition 不得按 host type latest/fuzzy fallback。"""

    from design_execution_planning import HostRuntimeRef
    from design_product_runtime.cross_host_reference_composition import (
        build_cross_host_planning_composition,
    )

    autocad_runtime = HostRuntimeRef("autocad", "AUTOCAD-GATE-B", r"C:\DSP\a.dwg")
    revit_runtime = HostRuntimeRef("revit", "REVIT-GATE-B", r"C:\DSP\r.rvt")
    autocad = _PlanningPort(autocad_runtime, "17")
    revit = _PlanningPort(revit_runtime, "41")
    composition = build_cross_host_planning_composition(
        (
            (autocad_runtime, autocad),
            (revit_runtime, revit),
        )
    )

    assert composition.revision_observation.current_revision(
        autocad_runtime.document_ref
    ) == "17"
    assert composition.revision_observation.current_revision(
        revit_runtime.document_ref
    ) == "41"

    observation = CrossHostProposalObservationV2(
        host_kind="REVIT",
        host_instance_id=revit_runtime.host_instance_id,
        document_id=revit_runtime.document_ref,
        native_target_id="REVIT-WALL-GATE-B",
        semantic_target_id="WALL-001",
        host_revision=41,
        normalized_thickness_mm=200.0,
        observed_at="2026-10-07T07:10:00Z",
        command_id="proposal-revit-gate-b",
    )
    result = composition.member_reconstruction.reconstruct_member(
        task_id="task-gate-b",
        host_kind="REVIT",
        contract=object(),
        accepted_observation=observation,
        expected_host_revision="41",
        semantic_environment_ref=object(),
    )
    assert result == ("member", "revit")
    assert len(revit.reconstruction_calls) == 1
    assert autocad.reconstruction_calls == []

    with pytest.raises(
        ValueError,
        match="PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED",
    ):
        composition.revision_observation.current_revision(r"C:\DSP\other.rvt")
