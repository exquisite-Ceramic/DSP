from __future__ import annotations

from design_orchestrator import WorkflowPhase, WorkflowResumeCommand
from design_product_runtime import ProductFlowStatus


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


def test_host_outcome_unknown_and_restart_after_dispatch_never_duplicate_execute(
    revit_wall_thickness_product_case,
) -> None:
    """场景 10/18：未知 Host 结果在 dispatch 后重启，owner truth 必须阻止第二次 mutation。"""

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

    # 场景 18 的 restart 发生在 durable dispatch 之后：request/checkpoint/artifact/Saga/dispatch
    # 全部重新打开 PostgreSQL connection。恢复只能读取同一 Saga/intent owner truth，不能把
    # “未知是否已提交”误解释成安全未提交并重新发送 set_wall_thickness。
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
    """场景 17/19：proposal HITL 重启后恢复 exact request/refs，不在恢复读取时重算 context。"""

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

    # proposal 形成前已有两次合法 current-selection READ：初始 capture 与 freshness exact re-read。
    # 这里冻结实际计数，只要求 process rebuild + get() 本身不产生第三次 context recompute。
    context_reads_before = case.host.command_operations().count("context.current_selection")
    assert context_reads_before >= 1

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
    assert (
        rebuilt.host.command_operations().count("context.current_selection")
        == context_reads_before
    )

    completed = rebuilt.flow.resume(task_id, _accept_command(restored))

    assert completed.status is ProductFlowStatus.SUCCEEDED
    assert completed.workflow_phase is WorkflowPhase.COMPLETED
    assert rebuilt.host.execute_count == 1
    assert rebuilt.request_store.get(task_id).request_hash == request_hash
