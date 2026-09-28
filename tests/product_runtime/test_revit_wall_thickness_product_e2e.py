from __future__ import annotations

from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    SliceReconciliationStatusV2,
)
from design_orchestrator import WorkflowPhase, WorkflowResumeCommand
from design_orchestrator.parameter_binder import BoundOperationProposal
from design_product_runtime import ProductFlowStatus, ProductTaskRequest


def _accept_command(proposal) -> WorkflowResumeCommand:
    """从持久化 proposal pause 构造 exact human-accept resume command。"""

    assert proposal.checkpoint.pending_interaction is not None
    return WorkflowResumeCommand(
        resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        pause_id=proposal.checkpoint.pending_interaction.pause_id,
    )


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

    completed = case.flow.resume(case.task_id, _accept_command(proposal))

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


def test_300_350_interleaving_survives_full_product_composition_rebuild(
    revit_wall_thickness_product_case,
) -> None:
    """场景 5/19：A=300/B=350 在 binder 前暂停，重建后 B→A 全流恢复不得串 request lineage。"""

    task_a = "task-product-interleave-A"
    task_b = "task-product-interleave-B"
    initial = revit_wall_thickness_product_case(task_a)
    request_a = initial.request
    request_b = ProductTaskRequest.create(
        task_id=task_b,
        project_id=request_a.project_id,
        host_kind=request_a.host_kind,
        session_ref=request_a.session_ref,
        requested_action=request_a.requested_action,
        intent_arguments={"thickness": {"value": 350.0, "unit": "mm"}},
    )

    pause_a = initial.flow.submit(request_a)
    pause_b = initial.flow.submit(request_b)

    assert pause_a.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert pause_b.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert pause_a.checkpoint.context_snapshot_ref is not None
    assert pause_b.checkpoint.context_snapshot_ref is not None
    assert pause_a.checkpoint.operation_ref is not None
    assert pause_b.checkpoint.operation_ref is not None
    assert request_a.request_hash != request_b.request_hash
    assert initial.host.execute_count == 0

    # 模拟进程重建：旧 PG connections/runtime/adapters 全部关闭并重新创建；恢复唯一允许
    # 依赖的是 durable request/checkpoint/artifact 与 authoritative ContextSnapshot owner truth。
    rebuilt = revit_wall_thickness_product_case.rebuild(initial, task_a)
    assert rebuilt.request_store.get(task_a) == request_a
    assert rebuilt.request_store.get(task_b) == request_b

    completed_b = rebuilt.flow.resume(task_b, _accept_command(pause_b))

    assert completed_b.status is ProductFlowStatus.SUCCEEDED
    assert completed_b.workflow_phase is WorkflowPhase.COMPLETED
    assert rebuilt.host.execute_count == 1
    assert rebuilt.host.current_thickness_mm == 350.0
    assert rebuilt.host.current_revision == 43
    assert completed_b.checkpoint.operation_ref is not None
    assert completed_b.checkpoint.changeset_ref is not None

    bound_b = rebuilt.artifact_store.get(completed_b.checkpoint.operation_ref)
    assert isinstance(bound_b, BoundOperationProposal)
    assert bound_b.arguments["thickness"] == {"value": 350.0, "unit": "mm"}
    assert bound_b.context_snapshot_ref.context_snapshot_id == (
        pause_b.checkpoint.context_snapshot_ref.ref_id
    )
    assert bound_b.context_snapshot_ref.context_snapshot_hash == (
        pause_b.checkpoint.context_snapshot_ref.content_hash
    )
    changeset_b = rebuilt.changeset_store.get(completed_b.checkpoint.changeset_ref.ref_id)
    assert changeset_b.root_operation.arguments["thickness"] == {
        "value": 350.0,
        "unit": "mm",
    }

    completed_a = rebuilt.flow.resume(task_a, _accept_command(pause_a))

    assert completed_a.status is ProductFlowStatus.SUCCEEDED
    assert completed_a.workflow_phase is WorkflowPhase.COMPLETED
    assert rebuilt.host.execute_count == 2
    assert rebuilt.host.current_thickness_mm == 300.0
    assert rebuilt.host.current_revision == 44
    assert completed_a.checkpoint.operation_ref is not None
    assert completed_a.checkpoint.changeset_ref is not None

    bound_a = rebuilt.artifact_store.get(completed_a.checkpoint.operation_ref)
    assert isinstance(bound_a, BoundOperationProposal)
    assert bound_a.arguments["thickness"] == {"value": 300.0, "unit": "mm"}
    assert bound_a.context_snapshot_ref.context_snapshot_id == (
        pause_a.checkpoint.context_snapshot_ref.ref_id
    )
    assert bound_a.context_snapshot_ref.context_snapshot_hash == (
        pause_a.checkpoint.context_snapshot_ref.content_hash
    )
    changeset_a = rebuilt.changeset_store.get(completed_a.checkpoint.changeset_ref.ref_id)
    assert changeset_a.root_operation.arguments["thickness"] == {
        "value": 300.0,
        "unit": "mm",
    }

    assert completed_b.checkpoint.operation_ref != completed_a.checkpoint.operation_ref
    assert changeset_b.changeset_hash != changeset_a.changeset_hash
    assert rebuilt.request_store.get(task_b).request_hash == request_b.request_hash
    assert rebuilt.request_store.get(task_a).request_hash == request_a.request_hash

    execute_commands = [
        command
        for command in rebuilt.host.commands
        if command.operation == "set_wall_thickness"
    ]
    assert [command.arguments["thickness"]["value"] for command in execute_commands] == [
        350.0,
        300.0,
    ]
    assert [command.preconditions for command in execute_commands] == [
        [{"revision": 42}],
        [{"revision": 43}],
    ]
