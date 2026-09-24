"""Task 10 review：补齐 execution recovery 合法中断窗口与外部恢复回读证据。"""

from __future__ import annotations

import pytest
from design_execution_coordination import project_execution_recovery
from design_execution_reconciliation import (
    ExecutionReconciliationServiceV2,
    InMemoryExecutionSagaStoreV2,
    InMemoryHostDispatchIntentStore,
)
from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
from design_orchestrator.recovery import decide_apply_resume
from design_orchestrator.workflow_contracts import WorkflowCheckpointView, WorkflowPhase

from tests.execution_coordination.test_task8_execution_recovery_projection import (
    _single_slice_fixture,
)


def _execution_owner_reader(
    *,
    saga_store: InMemoryExecutionSagaStoreV2,
    dispatch_store: InMemoryHostDispatchIntentStore,
) -> CanonicalWorkflowOwnerPorts:
    """只组合本回归会读取的真实 execution owner 依赖，其余 seam 不参与测试。"""

    unused = object()
    return CanonicalWorkflowOwnerPorts(
        snapshot_registry=unused,
        freshness_resolver=unused,
        workflow_artifact_store=unused,
        host_revision_observation=unused,
        canonical_operations=(),
        impact_analyzer=unused,
        impact_store=unused,
        approval_scope_planner=unused,
        approval_scope_store=unused,
        changeset_builder=unused,
        changeset_store=unused,
        materialization_planner=unused,
        materialization_plan_store=unused,
        topology_registry=unused,
        topology_environment_id=unused,
        topology_revision=unused,
        execution_plan_store=unused,
        revision_barrier=unused,
        gateway_authorization=unused,
        gateway_authorization_store=unused,
        coordination_clock=unused,
        provider_binding_store=unused,
        dispatch_intent_store=dispatch_store,
        execution_recovery_projection=project_execution_recovery,
        saga_store=saga_store,
        execution_coordinator=unused,
        reconciliation_service=unused,
        convergence_verifier=unused,
        semantic_reconstruction=unused,
        preview_port=unused,
        approval_admission=unused,
        materialization_routing=unused,
        provider_execution_snapshot=unused,
    )


@pytest.mark.parametrize(
    "confirm_admission",
    (False, True),
    ids=("ADMISSION_RESERVED", "ADMITTED"),
)
def test_pre_dispatch_crash_window_without_intent_routes_to_safe_wait(
    confirm_admission: bool,
) -> None:
    """真实 owner 的 pre-dispatch crash window 必须进入 RECOVER_OR_WAIT，而不是查询异常。"""

    ctx, initial, _intent = _single_slice_fixture()
    saga_store = InMemoryExecutionSagaStoreV2()
    stored = saga_store.create_saga(initial.definition)
    reconciliation = ExecutionReconciliationServiceV2(store=saga_store)
    slice_hash = stored.definition.ordered_slice_hashes[0]

    stored = reconciliation.reserve_slice_admission(
        stored.definition.saga_id,
        slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at="2026-09-24T14:30:00Z",
    )
    if confirm_admission:
        stored = reconciliation.confirm_slice_admitted(
            stored.definition.saga_id,
            ctx.authorities[0],
            expected_revision=stored.saga_revision,
        )

    dispatch_store = InMemoryHostDispatchIntentStore()
    assert (
        dispatch_store.get_for_saga_slice(stored.definition.saga_id, slice_hash)
        is None
    )

    adapter = _execution_owner_reader(
        saga_store=saga_store,
        dispatch_store=dispatch_store,
    )
    view = adapter.get_execution_owner_state(stored.definition.saga_id)
    checkpoint = WorkflowCheckpointView(
        task_id=f"task-review-{'admitted' if confirm_admission else 'reserved'}",
        phase=WorkflowPhase.APPLY_WAIT,
        saga_id=stored.definition.saga_id,
    )

    decision = decide_apply_resume(checkpoint=checkpoint, execution=view)

    assert decision.route == "RECOVER_OR_WAIT"
    assert dispatch_store.get_for_saga_slice(stored.definition.saga_id, slice_hash) is None
