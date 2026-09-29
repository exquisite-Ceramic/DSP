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


def test_host_outcome_unknown_never_duplicate_execute(
    revit_wall_thickness_product_case,
) -> None:
    """未知 Host 结果进入 durable recovery 后，重复完成信号不得触发第二次 mutation。"""

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

    # v1 不宣称 ContextSnapshot 形成后的任意 server-process rebuild。这里验证真正需要的
    # recovery invariant：同一 live composition 收到后续完成信号时，只读取既有 Saga/intent
    # owner truth，不能把“未知是否已提交”降格成安全未提交并重新发送 mutation。
    waiting_again = case.flow.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="ASYNC_OPERATION_COMPLETED",
            payload={"operation_id": waiting.saga_id},
        ),
    )

    assert waiting_again.status is ProductFlowStatus.RECOVERY_REQUIRED
    assert waiting_again.workflow_phase is WorkflowPhase.APPLY_WAIT
    assert waiting_again.saga_id == waiting.saga_id
    assert case.host.execute_count == 1

    reloaded = case.saga_store.get_saga(waiting.saga_id)
    assert reloaded is not None
    reloaded_intent = case.dispatch_store.get_for_saga_slice(
        waiting.saga_id,
        slice_hash,
    )
    assert reloaded_intent is not None
    assert reloaded_intent.dispatch_intent_id == dispatch_intent_id
    assert reloaded_intent.status.value == "OUTCOME_UNKNOWN"


def test_transport_response_loss_after_host_commit_never_duplicate_execute(
    revit_wall_thickness_product_case,
) -> None:
    """真实 mutation 已完成但 response 丢失时，durable unknown outcome 必须禁止重发。"""

    task_id = "task-product-response-lost-after-commit"
    case = revit_wall_thickness_product_case(task_id)
    proposal = _submit_to_proposal(case)
    execute = case.host._execute_wall_thickness

    def commit_then_disconnect(command):
        """先执行真实 stateful mutation，再模拟 Named Pipe response 在返回前断连。"""

        response = execute(command)
        assert response["status"] == "OK"
        raise ConnectionError("response lost after Revit commit")

    case.host._execute_wall_thickness = commit_then_disconnect

    waiting = case.flow.resume(task_id, _accept_command(proposal))

    assert waiting.status is ProductFlowStatus.RECOVERY_REQUIRED
    assert waiting.workflow_phase is WorkflowPhase.APPLY_WAIT
    assert waiting.saga_id is not None
    assert case.host.execute_count == 1
    assert case.host.current_thickness_mm == 300.0
    assert case.host.current_revision == 43

    stored = case.saga_store.get_saga(waiting.saga_id)
    assert stored is not None
    slice_hash = stored.definition.ordered_slice_hashes[0]
    intent = case.dispatch_store.get_for_saga_slice(waiting.saga_id, slice_hash)
    assert intent is not None
    assert intent.status.value == "OUTCOME_UNKNOWN"
    dispatch_intent_id = intent.dispatch_intent_id

    waiting_again = case.flow.resume(
        task_id,
        WorkflowResumeCommand(
            resume_kind="ASYNC_OPERATION_COMPLETED",
            payload={"operation_id": waiting.saga_id},
        ),
    )

    assert waiting_again.status is ProductFlowStatus.RECOVERY_REQUIRED
    assert waiting_again.workflow_phase is WorkflowPhase.APPLY_WAIT
    assert waiting_again.saga_id == waiting.saga_id
    assert case.host.execute_count == 1
    assert case.host.current_thickness_mm == 300.0
    assert case.host.current_revision == 43

    reloaded_intent = case.dispatch_store.get_for_saga_slice(
        waiting.saga_id,
        slice_hash,
    )
    assert reloaded_intent is not None
    assert reloaded_intent.dispatch_intent_id == dispatch_intent_id
    assert reloaded_intent.status.value == "OUTCOME_UNKNOWN"


def test_host_success_from_other_commit_start_revision_requires_recovery(
    revit_wall_thickness_product_case,
) -> None:
    """
    Host 若从非授权 revision 提交，不能当正常成功；
    已发生的 commit 仍必须按 unknown outcome 保守恢复。
    """

    task_id = "task-product-commit-revision-mismatch"
    case = revit_wall_thickness_product_case(task_id)
    proposal = _submit_to_proposal(case)

    def commit_from_other_revision(command):
        """模拟 Host 实际从 90 提交到 91，同时返回完整且可独立 READ 的成功证据。"""

        case.host.execute_count += 1
        requested_mm = float(command.arguments["thickness"]["value"])
        case.host.current_thickness_mm = requested_mm
        case.host.current_revision = 91
        return {
            "command_id": command.command_id,
            "status": "OK",
            "revision_after": 91,
            "payload": {
                "wall_unique_id": command.target_native_refs[0].native_id,
                "wall_type_unique_id": "REVIT-WALLTYPE-TASK9",
                "editable_layer_index": 1,
                "width_before_internal": 0.5,
                "width_after_internal": requested_mm / 304.8,
                "width_after_mm": requested_mm,
                "requested_width_mm": requested_mm,
                "transaction_attempt_count": 1,
            },
            "verification": {
                "identity_invariant_proven": True,
                "location_invariant_proven": True,
                "relationship_invariant_proven": True,
                "document_change_observed": True,
                "revision_before": 90,
                "revision_after": 91,
                "location_signature_before": "Line|0|0|0|10|0|0",
                "location_signature_after": "Line|0|0|0|10|0|0",
                "relationship_signature_before": "isolated",
                "relationship_signature_after": "isolated",
            },
            "replayed": False,
        }

    case.host._execute_wall_thickness = commit_from_other_revision

    waiting = case.flow.resume(task_id, _accept_command(proposal))

    assert waiting.status is ProductFlowStatus.RECOVERY_REQUIRED
    assert waiting.workflow_phase is WorkflowPhase.APPLY_WAIT
    assert waiting.saga_id is not None
    assert case.host.execute_count == 1
    assert case.host.current_thickness_mm == 300.0
    assert case.host.current_revision == 91

    stored = case.saga_store.get_saga(waiting.saga_id)
    assert stored is not None
    slice_hash = stored.definition.ordered_slice_hashes[0]
    intent = case.dispatch_store.get_for_saga_slice(waiting.saga_id, slice_hash)
    assert intent is not None
    assert intent.status.value == "OUTCOME_UNKNOWN"


def test_operation_proposal_get_and_resume_reuse_same_reference_composition(
    revit_wall_thickness_product_case,
) -> None:
    """proposal pause 后 get 不触碰 Host，human resume 继续复用同一 in-memory snapshot owner。"""

    task_id = "task-product-same-composition-proposal"
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
    assert context_reads_before >= 1

    restored = case.flow.get(task_id)

    assert restored is not None
    assert restored.status is ProductFlowStatus.WAITING
    assert restored.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert restored.checkpoint.context_snapshot_ref == context_ref
    assert restored.checkpoint.operation_ref == operation_ref
    assert restored.checkpoint.pending_interaction == pending
    persisted_request = case.request_store.get(task_id)
    assert persisted_request is not None
    assert persisted_request.request_hash == request_hash
    assert persisted_request == case.request
    assert case.host.execute_count == 0
    assert (
        case.host.command_operations().count("context.current_selection")
        == context_reads_before
    )

    completed = case.flow.resume(task_id, _accept_command(restored))

    assert completed.status is ProductFlowStatus.SUCCEEDED
    assert completed.workflow_phase is WorkflowPhase.COMPLETED
    assert case.host.execute_count == 1
    assert case.request_store.get(task_id).request_hash == request_hash
