"""Task 8.3/8.4：canonical workflow 对真实 execution-owner truth 的路由契约。"""

from __future__ import annotations

from design_orchestrator.recovery import decide_apply_resume
from design_orchestrator.workflow_contracts import WorkflowCheckpointView, WorkflowPhase
from design_orchestrator.workflow_services import ExecutionOwnerView, ExecutionSagaView

from tests.execution_coordination.test_task8_execution_recovery_projection import (
    build_reconciled_nonterminal_case,
)


def test_reconciled_nonterminal_saga_routes_to_recover_or_wait_not_redispatch() -> None:
    """无 active Host recovery 不等于 Saga 完成；CONVERGENCE_PENDING 必须继续等待 owner。"""
    from design_execution_coordination import project_execution_recovery

    stored, reconciled = build_reconciled_nonterminal_case()
    slice_hash = stored.definition.ordered_slice_hashes[0]
    projection = project_execution_recovery(stored, slice_hash, reconciled)
    assert projection.disposition is None

    owner_view = ExecutionOwnerView(
        saga=ExecutionSagaView(
            saga_id=stored.definition.saga_id,
            saga_revision=stored.saga_revision,
            status=stored.status.value,
            active_slice_hash=None,
        ),
        active_dispatch_recovery=None,
    )
    checkpoint = WorkflowCheckpointView(
        task_id="task-task8-reconciled-nonterminal",
        phase=WorkflowPhase.APPLY_WAIT,
        saga_id=stored.definition.saga_id,
    )

    decision = decide_apply_resume(checkpoint=checkpoint, execution=owner_view)

    assert decision.route == "RECOVER_OR_WAIT"
    assert decision.route != "MAY_DISPATCH"
    assert decision.route != "TERMINAL_EXECUTION_STATE"
    # decide_apply_resume 是纯 owner-read 分类器，没有 begin_execution/Host mutation 依赖；
    # 只要 route 不是 MAY_DISPATCH，现有 graph refresh 分支就不会进入 apply_or_recover。
    assert decision.refreshed_saga_revision == stored.saga_revision
