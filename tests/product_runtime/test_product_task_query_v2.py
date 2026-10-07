"""Task 14：ProductTaskQueryViewV2 只从 durable owner truth 投影。"""

from __future__ import annotations

from dataclasses import replace

import design_product_runtime as product_runtime
import pytest
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    HostDispatchStatus,
    SliceReconciliationStatusV2,
)
from design_orchestrator import StableRef, WorkflowCheckpointView, WorkflowPhase
from design_orchestrator.proposal_decision import (
    HumanDecisionState,
    ProposalContinuationState,
    ProposalDecisionRecord,
)
from design_product_runtime import AcceptedProductTaskInputV2, ProductTaskRequestV2

from tests.execution_coordination._materialized_support import (
    execute,
    materialized_fixture,
)


def _v2_types():
    """延迟取得 Task 14 新契约，使 RED 形成明确 capability failure。"""

    view_type = getattr(product_runtime, "ProductTaskQueryViewV2", None)
    materialization_type = getattr(
        product_runtime,
        "ProductMaterializationQueryViewV2",
        None,
    )
    status_type = getattr(product_runtime, "ProductTaskV2Status", None)
    proposal_type = getattr(product_runtime, "ProductProposalStateV2", None)
    assert view_type is not None, "ProductTaskQueryViewV2 尚未实现"
    assert materialization_type is not None, (
        "ProductMaterializationQueryViewV2 尚未实现"
    )
    assert status_type is not None, "ProductTaskV2Status 尚未实现"
    assert proposal_type is not None, "ProductProposalStateV2 尚未实现"
    return view_type, materialization_type, status_type, proposal_type


def _accepted(ctx, *, thickness_mm: float = 999.0) -> AcceptedProductTaskInputV2:
    """从真实双 Slice runtime/binding lineage 生成 server-owned V2 input。"""

    members = []
    for execution_slice, binding_set in zip(
        ctx.execution_plan.execution_slices,
        ctx.binding_sets,
        strict=True,
    ):
        target = binding_set.bindings[0].native_targets[0]
        runtime = execution_slice.host_runtime_ref
        members.append(
            {
                "host_kind": runtime.host_type.upper(),
                "role": (
                    "INITIATOR"
                    if runtime.host_type == "revit"
                    else "BOUND_REQUIRED"
                ),
                "configured_reference_id": f"cfg-{runtime.host_type}",
                "configured_reference_hash": (
                    "a" * 64 if runtime.host_type == "autocad" else "b" * 64
                ),
                "transport_locator": f"{runtime.host_type}-offline",
                "host_instance_id": runtime.host_instance_id,
                "document_id": runtime.document_ref,
                "native_target_id": target.native_id,
                "host_binding_fingerprint": target.host_binding_fingerprint,
            }
        )
    binding_hash = "c" * 64
    request = ProductTaskRequestV2.create(
        task_id="task-query-v2",
        project_id=ctx.case.changeset.project_id,
        initiating_host_kind="REVIT",
        session_ref="session-query-v2",
        session_binding_hash=binding_hash,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={
            "thickness": {"value": thickness_mm, "unit": "mm"}
        },
    )
    return AcceptedProductTaskInputV2(
        request,
        binding_hash,
        {
            "session_ref": request.session_ref,
            "project_id": request.project_id,
            "semantic_target_id": "WALL-001",
            "semantic_environment_id": (
                ctx.case.changeset.semantic_environment_ref.environment_id
            ),
            "semantic_environment_hash": (
                ctx.case.changeset.semantic_environment_ref.content_hash
            ),
            "topology_environment_id": "topology-query-v2",
            "topology_revision": 1,
            "topology_snapshot_hash": ctx.case.topology.topology_snapshot_hash,
            "initiating_host_kind": "REVIT",
            "members": members,
            "binding_hash": binding_hash,
        },
    )


class _RequestStore:
    """只暴露 V2 accepted-input owner；V1 lookup 被触碰即失败。"""

    def __init__(self, accepted) -> None:
        self.accepted = accepted

    def get_v2(self, task_id):
        assert task_id == self.accepted.request.task_id
        return self.accepted

    def get(self, task_id):
        raise AssertionError(f"V2 query must not use V1 request reader: {task_id}")


class _CheckpointReader:
    def __init__(self, checkpoint) -> None:
        self.checkpoint = checkpoint

    def get_checkpoint(self, task_id):
        assert task_id == self.checkpoint.task_id
        return self.checkpoint


class _DecisionReader:
    def __init__(self, record=None) -> None:
        self.record = record
        self.calls = []

    def get_for_task(self, task_id):
        self.calls.append(task_id)
        return self.record


class _DispatchReader:
    """从 materialized fixture 的 durable-intent fake 暴露 exact Saga/Slice read。"""

    def __init__(self, intents, overrides=None) -> None:
        self.intents = intents
        self.overrides = dict(overrides or {})
        self.calls = []

    def get_for_saga_slice(self, saga_id, execution_slice_hash):
        self.calls.append((saga_id, execution_slice_hash))
        if execution_slice_hash in self.overrides:
            return self.overrides[execution_slice_hash]
        return self.intents.get(execution_slice_hash)


class _EvidenceReader:
    def __init__(self, service, *, missing_verification=False) -> None:
        self.service = service
        self.missing_verification = missing_verification
        self.calls = []

    def get_actual_delta(self, content_hash):
        self.calls.append(("delta", content_hash))
        return self.service.get_actual_delta(content_hash)

    def get_verification_result(self, content_hash):
        self.calls.append(("verification", content_hash))
        if self.missing_verification:
            return None
        return self.service.get_verification_result(content_hash)

    def get_verification_bundle(self, content_hash):
        self.calls.append(("bundle", content_hash))
        return self.service.get_verification_bundle(content_hash)


def _accepted_decision(task_id: str) -> ProposalDecisionRecord:
    return ProposalDecisionRecord(
        task_id=task_id,
        pause_id="pause-query-v2",
        subject_ref=StableRef("subject-query-v2", "d" * 64),
        human_decision=HumanDecisionState.ACCEPTED,
        continuation=ProposalContinuationState.CONTINUABLE,
        revision=1,
    )


def _service(
    fixture,
    *,
    checkpoint,
    accepted=None,
    decision=None,
    dispatch_overrides=None,
    missing_verification=False,
):
    """只注入 durable read owners；没有 Host/readiness/Gateway/execution seam。"""

    service_type = product_runtime.ProductTaskQueryService
    accepted = accepted or _accepted(fixture.ctx)
    return service_type(
        request_store=_RequestStore(accepted),
        checkpoint_reader=_CheckpointReader(checkpoint),
        saga_store=fixture.reconciliation.service,
        proposal_decision_reader=_DecisionReader(decision),
        dispatch_intent_reader=_DispatchReader(
            fixture.dispatch_intents.prepared_by_slice,
            dispatch_overrides,
        ),
        evidence_reader=_EvidenceReader(
            fixture.reconciliation.service,
            missing_verification=missing_verification,
        ),
    )


def _successful_case(*, request_thickness_mm: float = 999.0):
    """执行真实 in-memory materialized owner chain，随后只读其 durable truth。"""

    fixture = materialized_fixture()
    result = execute(fixture)
    accepted = _accepted(fixture.ctx, thickness_mm=request_thickness_mm)
    checkpoint = WorkflowCheckpointView(
        task_id=accepted.request.task_id,
        phase=WorkflowPhase.COMPLETED,
        saga_id=result.saga_id,
    )
    return fixture, accepted, checkpoint


def test_v2_get_projects_measured_300_from_durable_read_evidence_not_request_intent() -> None:
    """实测厚度只能沿 verification→bundle 读取，不能回显 request intent。"""

    _, _, status_type, proposal_type = _v2_types()
    fixture, accepted, checkpoint = _successful_case(
        request_thickness_mm=999.0
    )
    service = _service(
        fixture,
        checkpoint=checkpoint,
        accepted=accepted,
        decision=_accepted_decision(accepted.request.task_id),
    )

    view = service.get(accepted.request.task_id)

    assert view.version == "V2"
    assert view.status is status_type.SUCCEEDED
    assert view.proposal_state is proposal_type.ACCEPTED
    assert len(view.materializations) == 2
    assert {
        item.verified_thickness_mm for item in view.materializations
    } == {300.0}
    assert all(item.observed_revision == 11 for item in view.materializations)
    assert all(item.committed_revision == 11 for item in view.materializations)
    assert all(item.actual_delta_hash for item in view.materializations)
    assert all(item.verification_hash for item in view.materializations)
    assert all(item.evidence_bundle_hash for item in view.materializations)
    assert all(
        item.convergence_result_hash == view.convergence_result_hash
        for item in view.materializations
    )
    assert accepted.request.intent_arguments["thickness"]["value"] == 999.0


def test_v2_get_with_hosts_offline_calls_zero_mutating_or_live_seams() -> None:
    """ProductTaskQueryService 必须能只靠 durable read owners 完成 V2 GET。"""

    _v2_types()
    fixture, accepted, checkpoint = _successful_case()
    service = _service(
        fixture,
        checkpoint=checkpoint,
        accepted=accepted,
        decision=_accepted_decision(accepted.request.task_id),
    )

    class _Forbidden:
        def __getattr__(self, name):
            raise AssertionError(f"offline GET touched forbidden seam: {name}")

        def __call__(self, *args, **kwargs):
            raise AssertionError(
                f"offline GET attempted live side effect: {args=} {kwargs=}"
            )

    from design_product_front_door.service import ProductFrontDoorService

    forbidden = _Forbidden()
    front_door = ProductFrontDoorService(
        session_binding_reader=forbidden,
        candidate_source=forbidden,
        context_probe=forbidden,
        transport_factory=forbidden,
        query_service=service,
        composition_pool=forbidden,
        reviewed_configuration_validator=forbidden,
        accepted_input_store=forbidden,
        proposal_decision_store=None,
    )
    assert front_door.get(accepted.request.task_id).status.value == "SUCCEEDED"


@pytest.mark.parametrize(
    ("continuation", "expected"),
    (
        (ProposalContinuationState.STALE_GATE_A, "STALE_GATE_A"),
        (ProposalContinuationState.STALE_GATE_B, "STALE_GATE_B"),
    ),
)
def test_stale_gate_a_and_gate_b_project_stale_not_cancelled(
    continuation,
    expected,
) -> None:
    """stale 是 proposal owner truth，不得被 checkpoint FAILED/CANCELLED 改写成拒绝。"""

    _, _, status_type, proposal_type = _v2_types()
    fixture = materialized_fixture()
    accepted = _accepted(fixture.ctx)
    decision = ProposalDecisionRecord(
        task_id=accepted.request.task_id,
        pause_id="pause-stale",
        subject_ref=StableRef("subject-stale", "e" * 64),
        human_decision=(
            HumanDecisionState.AWAITING
            if continuation is ProposalContinuationState.STALE_GATE_A
            else HumanDecisionState.ACCEPTED
        ),
        continuation=continuation,
        revision=2 if continuation is ProposalContinuationState.STALE_GATE_B else 1,
        reason="OBSERVATION_CONTINUITY_LOST",
    )
    checkpoint = WorkflowCheckpointView(
        task_id=accepted.request.task_id,
        phase=WorkflowPhase.FAILED,
    )
    service = _service(
        fixture,
        checkpoint=checkpoint,
        accepted=accepted,
        decision=decision,
    )

    view = service.get(accepted.request.task_id)

    assert view.status is status_type.STALE
    assert view.status.value != "CANCELLED"
    assert view.proposal_state is proposal_type(expected)
    assert view.materializations == ()


def test_partial_commit_and_unresolved_dispatch_project_exact_owner_truth() -> None:
    """known commit + required dispatch unresolved 时优先 RECOVERY_REQUIRED。"""

    _, _, status_type, _ = _v2_types()
    fixture, accepted, checkpoint = _successful_case()
    stored = fixture.reconciliation.service.get_saga(checkpoint.saga_id)
    assert stored is not None
    second = stored.slice_states[1]
    partial = replace(
        stored,
        status=ExecutionSagaStatusV2.EXECUTING,
        slice_states=(
            stored.slice_states[0],
            replace(
                second,
                status=SliceReconciliationStatusV2.RECONCILING,
                actual_delta_hash=None,
                verification_hash=None,
                reconciled_at=None,
            ),
        ),
        convergence_outcome=None,
        convergence_result_hash=None,
    )

    class _SagaStore:
        def get_saga(self, saga_id):
            assert saga_id == partial.definition.saga_id
            return partial

    unresolved = replace(
        fixture.dispatch_intents.prepared_by_slice[
            second.execution_slice_hash
        ],
        status=HostDispatchStatus.OUTCOME_UNKNOWN,
    )
    service = product_runtime.ProductTaskQueryService(
        request_store=_RequestStore(accepted),
        checkpoint_reader=_CheckpointReader(checkpoint),
        saga_store=_SagaStore(),
        proposal_decision_reader=_DecisionReader(
            _accepted_decision(accepted.request.task_id)
        ),
        dispatch_intent_reader=_DispatchReader(
            fixture.dispatch_intents.prepared_by_slice,
            {second.execution_slice_hash: unresolved},
        ),
        evidence_reader=_EvidenceReader(fixture.reconciliation.service),
    )

    view = service.get(accepted.request.task_id)

    assert view.status is status_type.RECOVERY_REQUIRED
    assert view.materializations[0].actual_delta_hash is not None
    assert view.materializations[1].actual_delta_hash is None
    assert (
        view.materializations[1].recovery_disposition
        == "OUTCOME_UNKNOWN"
    )


def test_missing_published_evidence_body_is_integrity_failure_not_redispatch() -> None:
    """Saga 已发布 verification_hash 时缺 body 属于完整性错误，查询不能自动重执行。"""

    _v2_types()
    fixture, accepted, checkpoint = _successful_case()
    service = _service(
        fixture,
        checkpoint=checkpoint,
        accepted=accepted,
        decision=_accepted_decision(accepted.request.task_id),
        missing_verification=True,
    )

    with pytest.raises(product_runtime.ProductTaskQueryError) as captured:
        service.get(accepted.request.task_id)

    assert captured.value.code == "PRODUCT_TASK_EVIDENCE_INTEGRITY_INVALID"
