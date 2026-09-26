from __future__ import annotations

import pytest
from design_execution_reconciliation import ExecutionSagaStatusV2
from design_orchestrator import WorkflowPhase, WorkflowResumeCommand
from design_orchestrator.langgraph_runtime import LangGraphWorkflowRuntime
from design_orchestrator.workflow_services import WorkflowStateError
from design_product_runtime import (
    ProductFlowStatus,
    WallThicknessProductFlow,
)


class _SimulatedProcessLoss(RuntimeError):
    """只表示测试注入的进程丢失；不写任何 owner 状态，也不承担恢复语义。"""


def _submit_to_proposal(case):
    """把真实 ProductFlow 推进到 operation proposal HITL，并返回 durable pause。"""

    proposal = case.flow.submit(case.request)
    assert proposal.status is ProductFlowStatus.WAITING
    assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert proposal.checkpoint.pending_interaction is not None
    assert case.host.execute_count == 0
    return proposal


def _accept_command(proposal) -> WorkflowResumeCommand:
    """从当前 durable pause 构造 exact human accept command。"""

    assert proposal.checkpoint.pending_interaction is not None
    return WorkflowResumeCommand(
        resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        pause_id=proposal.checkpoint.pending_interaction.pause_id,
    )


def test_host_outcome_unknown_rebuild_waits_without_duplicate_execute(
    revit_wall_thickness_product_case,
) -> None:
    """场景 10/19：Host outcome unknown 必须持久化恢复身份，重建后不能再次 mutation。"""

    task_id = "task-product-host-outcome-unknown"
    case = revit_wall_thickness_product_case(task_id)
    proposal = _submit_to_proposal(case)

    def unknown_outcome(command):
        """模拟请求已经越过 Host dispatch 边界，但响应只证明 commit state unknown。"""

        case.host.execute_count += 1
        return {
            "command_id": command.command_id,
            "status": "ERROR",
            "revision_after": case.host.current_revision,
            "error": {
                "code": "REVIT_COMMIT_STATE_UNKNOWN",
                "commit_state": "COMMIT_STATE_UNKNOWN",
            },
        }

    # 只替换允许的外部 Host transport 行为；Saga/dispatch/recovery owners 全部保持 production。
    case.host._execute_wall_thickness = unknown_outcome

    waiting = case.flow.resume(task_id, _accept_command(proposal))

    assert waiting.status is ProductFlowStatus.RECOVERY_REQUIRED
    assert waiting.workflow_phase is WorkflowPhase.APPLY_WAIT
    assert waiting.saga_id is not None
    assert waiting.checkpoint.async_operation_ref is not None
    assert waiting.checkpoint.async_operation_ref.operation_id == waiting.saga_id
    assert case.host.execute_count == 1

    stored = case.saga_store.get_saga(waiting.saga_id)
    assert stored is not None
    slice_hash = stored.definition.ordered_slice_hashes[0]
    intent = case.dispatch_store.get_for_saga_slice(waiting.saga_id, slice_hash)
    assert intent is not None
    assert intent.status.value == "OUTCOME_UNKNOWN"
    dispatch_intent_id = intent.dispatch_intent_id

    # 模拟整个产品进程重建：request/checkpoint/artifact/Saga/dispatch 都重新打开 PG connection，
    # Host 外部状态与 authoritative snapshot owner truth 按既有 fixture 契约保留。
    rebuilt = revit_wall_thickness_product_case.rebuild(case, task_id)
    waiting_after_restart = rebuilt.flow.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="ASYNC_OPERATION_COMPLETED",
            payload={"operation_id": waiting.saga_id},
        ),
    )

    assert waiting_after_restart.status is ProductFlowStatus.RECOVERY_REQUIRED
    assert waiting_after_restart.workflow_phase is WorkflowPhase.APPLY_WAIT
    assert waiting_after_restart.saga_id == waiting.saga_id
    assert rebuilt.host.execute_count == 1

    reloaded = rebuilt.saga_store.get_saga(waiting.saga_id)
    assert reloaded is not None
    reloaded_intent = rebuilt.dispatch_store.get_for_saga_slice(
        waiting.saga_id,
        slice_hash,
    )
    assert reloaded_intent is not None
    assert reloaded_intent.dispatch_intent_id == dispatch_intent_id
    assert reloaded_intent.status.value == "OUTCOME_UNKNOWN"


def test_restart_at_operation_proposal_restores_exact_request_and_refs(
    revit_wall_thickness_product_case,
) -> None:
    """场景 17/19：proposal HITL 重启后恢复 exact request/refs，不重算上下文且只执行一次。"""

    task_id = "task-product-restart-at-proposal"
    case = revit_wall_thickness_product_case(task_id)
    proposal = _submit_to_proposal(case)
    context_ref = proposal.checkpoint.context_snapshot_ref
    operation_ref = proposal.checkpoint.operation_ref
    pending = proposal.checkpoint.pending_interaction
    assert context_ref is not None
    assert operation_ref is not None
    assert pending is not None
    request_hash = case.request.request_hash
    context_reads_before = case.host.command_operations().count("context.current_selection")
    assert context_reads_before == 1

    rebuilt = revit_wall_thickness_product_case.rebuild(case, task_id)
    restored = rebuilt.flow.get(task_id)

    assert restored is not None
    assert restored.status is ProductFlowStatus.WAITING
    assert restored.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert restored.checkpoint.context_snapshot_ref == context_ref
    assert restored.checkpoint.operation_ref == operation_ref
    assert restored.checkpoint.pending_interaction == pending
    persisted_request = rebuilt.request_store.get(task_id)
    assert persisted_request is not None
    assert persisted_request.request_hash == request_hash
    assert persisted_request == rebuilt.request
    assert rebuilt.host.execute_count == 0

    completed = rebuilt.flow.resume(task_id, _accept_command(restored))

    assert completed.status is ProductFlowStatus.SUCCEEDED
    assert completed.workflow_phase is WorkflowPhase.COMPLETED
    assert rebuilt.host.execute_count == 1
    assert rebuilt.host.command_operations().count("context.current_selection") == 1
    assert rebuilt.request_store.get(task_id).request_hash == request_hash


def test_restart_after_durable_dispatch_uses_owner_truth_without_duplicate_execute(
    revit_wall_thickness_product_case,
) -> None:
    """场景 18/19：真实执行已 durable、graph update 丢失后，新 runtime 只复用 owner truth。"""

    task_id = "task-product-restart-after-dispatch"
    case = revit_wall_thickness_product_case(task_id)
    proposal = _submit_to_proposal(case)
    services = case.runtime._services
    begin_execution = services.begin_execution
    durable_saga_id: list[str] = []

    def lose_process_after_begin(execution_plan_ref, grant_ref):
        """先让 production begin_execution 完整持久化，再在 LangGraph state update 前中断。"""

        result = begin_execution(execution_plan_ref, grant_ref)
        assert isinstance(result, str)
        stored = case.saga_store.get_saga(result)
        assert stored is not None
        assert stored.status is ExecutionSagaStatusV2.SUCCEEDED
        durable_saga_id.append(result)
        raise _SimulatedProcessLoss(result)

    services.begin_execution = lose_process_after_begin
    try:
        with pytest.raises(WorkflowStateError) as captured:
            case.flow.resume(task_id, _accept_command(proposal))
    finally:
        # 新 runtime 必须重新走 production service，不能继续携带 failure injection wrapper。
        services.begin_execution = begin_execution

    assert captured.value.code == "WORKFLOW_SERVICE_FAILURE"
    assert isinstance(captured.value.__cause__, _SimulatedProcessLoss)
    assert len(durable_saga_id) == 1
    saga_id = durable_saga_id[0]
    assert case.host.execute_count == 1

    after_loss = case.runtime.get_checkpoint(task_id)
    assert after_loss is not None
    assert after_loss.phase is WorkflowPhase.APPLY_WAIT
    assert after_loss.saga_id is None

    stored = case.saga_store.get_saga(saga_id)
    assert stored is not None
    assert stored.status is ExecutionSagaStatusV2.SUCCEEDED
    slice_hash = stored.definition.ordered_slice_hashes[0]
    intent = case.dispatch_store.get_for_saga_slice(saga_id, slice_hash)
    assert intent is not None
    dispatch_intent_id = intent.dispatch_intent_id

    # 创建全新的 LangGraph runtime + ProductFlow facade，但继续通过同一组真实 owner ports
    # 读取已经 durable 的 PostgreSQL Saga/dispatch truth。前驱 Task10 已独立证明 fresh-PG-
    # connection rebuild；本场景额外证明新的产品入口不会把 graph APPLY_WAIT 误判成再次执行许可。
    fresh_runtime = LangGraphWorkflowRuntime(
        services=services,
        checkpointer=case.checkpointer,
    )
    fresh_flow = WallThicknessProductFlow(
        request_store=case.request_store,
        workflow_runtime=fresh_runtime,
        saga_store=case.saga_store,
    )
    completed = fresh_flow.resume(task_id)

    assert completed.status is ProductFlowStatus.SUCCEEDED
    assert completed.workflow_phase is WorkflowPhase.COMPLETED
    assert completed.saga_id == saga_id
    assert case.host.execute_count == 1

    final_intent = case.dispatch_store.get_for_saga_slice(saga_id, slice_hash)
    assert final_intent is not None
    assert final_intent.dispatch_intent_id == dispatch_intent_id
