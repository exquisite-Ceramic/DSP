from __future__ import annotations

from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    SliceReconciliationStatusV2,
)
from design_orchestrator import WorkflowPhase, WorkflowResumeCommand
from design_product_runtime import ProductFlowStatus


def test_product_flow_happy_path_commits_once_and_succeeds_from_authoritative_saga(
    revit_wall_thickness_product_case,
) -> None:
    """场景 1/19：产品入口只写一次 300mm，并由独立 READ + terminal Saga 决定成功。"""

    case = revit_wall_thickness_product_case("task-product-e2e-happy")

    proposal = case.flow.submit(case.request)

    assert proposal.status is ProductFlowStatus.WAITING
    assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert proposal.checkpoint.pending_interaction is not None
    assert case.host.execute_count == 0

    completed = case.flow.resume(
        case.task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            pause_id=proposal.checkpoint.pending_interaction.pause_id,
        ),
    )

    assert completed.status is ProductFlowStatus.SUCCEEDED
    assert completed.workflow_phase is WorkflowPhase.COMPLETED
    assert completed.saga_id is not None
    assert case.host.execute_count == 1
    assert case.host.current_thickness_mm == 300.0
    assert case.host.current_revision == 43

    operations = case.host.command_operations()
    execute_indexes = [
        index
        for index, operation in enumerate(operations)
        if operation == "set_wall_thickness"
    ]
    assert len(execute_indexes) == 1
    execute_index = execute_indexes[0]
    assert any(
        operation == "read_wall_thickness_snapshot"
        and index > execute_index
        and case.host.command_revisions[index] == 43
        for index, operation in enumerate(operations)
    )

    saga = case.saga_store.get_saga(completed.saga_id)
    assert saga is not None
    assert saga.status is ExecutionSagaStatusV2.SUCCEEDED
    assert len(saga.slice_states) == 1
    slice_state = saga.slice_states[0]
    assert slice_state.status is SliceReconciliationStatusV2.SUCCEEDED
    assert slice_state.actual_delta_hash is not None
    assert slice_state.scope_comparison_hash is not None
    assert slice_state.verification_hash is not None
    assert saga.convergence_result_hash is not None

    reread = case.flow.get(case.task_id)
    assert reread is not None
    assert reread.status is ProductFlowStatus.SUCCEEDED
    assert reread.saga_id == completed.saga_id
