"""ADR-010 Task 7 的 workflow resume 决策层。

这里仅把已经重新查询得到的 execution-owner read model 分类成 workflow 路由；它不拥有
Execution Saga 或 Host dispatch recovery 的状态转移，也绝不从 checkpoint 节点位置推断
外部副作用是否已经发生。
"""

from __future__ import annotations

from dataclasses import dataclass

from design_orchestrator.workflow_contracts import WorkflowCheckpointView
from design_orchestrator.workflow_services import (
    ExecutionOwnerView,
    HostDispatchRecoveryState,
    WorkflowStateError,
)


@dataclass(frozen=True, slots=True)
class ResumeDecision:
    """基于最新 execution-owner truth 得出的纯 workflow 路由结果。"""

    route: str
    refreshed_saga_revision: int | None
    reason: str


def decide_apply_resume(
    *,
    checkpoint: WorkflowCheckpointView,
    execution: ExecutionOwnerView | None,
) -> ResumeDecision:
    """在 apply 前根据 authoritative execution truth 决定恢复路径。

    checkpoint 只提供稳定的 ``saga_id`` 与导航上下文；一旦已经存在 durable Saga identity，
    调用方必须把该 Saga 的最新 owner view 传入。Host dispatch recovery 的优先级高于 Saga
    状态，因此 ``OUTCOME_UNKNOWN``、``RECOVERY_REQUIRED`` 和 ``SAFE_TO_RETRY`` 都不会被
    Workflow Orchestrator 解释成“可以创建一个新 Host command”。
    """

    if not isinstance(checkpoint, WorkflowCheckpointView):
        raise ValueError("checkpoint must be a WorkflowCheckpointView")

    if checkpoint.saga_id is None:
        if execution is not None:
            raise WorkflowStateError(
                "WORKFLOW_EXECUTION_OWNER_STATE_UNEXPECTED",
                "execution owner view was supplied before saga identity existed",
            )
        return ResumeDecision(
            route="MAY_DISPATCH",
            refreshed_saga_revision=None,
            reason="no durable saga exists yet",
        )

    if execution is None:
        raise WorkflowStateError(
            "WORKFLOW_EXECUTION_OWNER_STATE_MISSING",
            checkpoint.saga_id,
        )
    if execution.saga.saga_id != checkpoint.saga_id:
        raise WorkflowStateError(
            "WORKFLOW_EXECUTION_OWNER_STATE_MISMATCH",
            f"checkpoint={checkpoint.saga_id}, owner={execution.saga.saga_id}",
        )

    revision = execution.saga.saga_revision
    recovery = execution.active_dispatch_recovery
    if recovery is not None:
        if recovery.state in {
            HostDispatchRecoveryState.OUTCOME_UNKNOWN,
            HostDispatchRecoveryState.RECOVERY_REQUIRED,
            HostDispatchRecoveryState.SAFE_TO_RETRY,
        }:
            return ResumeDecision(
                route="RECOVER_OR_WAIT",
                refreshed_saga_revision=revision,
                reason=f"active dispatch recovery: {recovery.state.value}",
            )
        raise WorkflowStateError(
            "WORKFLOW_EXECUTION_RECOVERY_STATE_UNKNOWN",
            str(recovery.state),
        )

    status = execution.saga.status
    if status == "READY":
        return ResumeDecision(
            route="MAY_DISPATCH",
            refreshed_saga_revision=revision,
            reason="refreshed saga is READY and no dispatch recovery is active",
        )
    if status in {"EXECUTING", "PENDING", "CONVERGENCE_PENDING"}:
        return ResumeDecision(
            route="RECOVER_OR_WAIT",
            refreshed_saga_revision=revision,
            reason=f"refreshed saga is already active: {status}",
        )
    if status in {"SUCCEEDED", "DIVERGED", "PARTIALLY_COMMITTED", "FAILED"}:
        return ResumeDecision(
            route="TERMINAL_EXECUTION_STATE",
            refreshed_saga_revision=revision,
            reason=f"refreshed saga is terminal: {status}",
        )
    raise WorkflowStateError("WORKFLOW_SAGA_STATUS_UNKNOWN", status)


__all__ = ["ResumeDecision", "decide_apply_resume"]
