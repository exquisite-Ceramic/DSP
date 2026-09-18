"""ADR-010 Task 7：resume 必须先重查完整 execution-owner authoritative truth。

本文件故意把 recovery 决策与 LangGraph 路由都作为外部可观察行为验证。测试中的 fake
execution owner 只记录调用，不复制 Saga/ADR-009 的业务状态机。
"""

from __future__ import annotations

import importlib

from design_orchestrator.langgraph_graph import build_workflow_graph
from design_orchestrator.workflow_contracts import StableRef, WorkflowCheckpointView, WorkflowPhase
from design_orchestrator.workflow_services import (
    ExecutionOwnerView,
    ExecutionSagaView,
    HostDispatchRecoveryState,
    HostDispatchRecoveryView,
)
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

_SLICE_HASH = "a" * 64


def _checkpoint(
    *,
    phase: WorkflowPhase = WorkflowPhase.APPLY_WAIT,
    saga_id: str | None = "saga-1",
) -> WorkflowCheckpointView:
    """构造只包含稳定引用的 checkpoint，模拟 crash/restart 后的旧导航事实。"""

    return WorkflowCheckpointView(
        task_id="task-resume-1",
        phase=phase,
        changeset_ref=StableRef("changeset-stale", "b" * 64),
        approval_ref=StableRef("approval-stale", "c" * 64),
        execution_plan_ref=StableRef("plan-1", "d" * 64),
        saga_id=saga_id,
    )


def _execution(
    status: str,
    *,
    revision: int = 7,
    recovery: HostDispatchRecoveryState | None = None,
) -> ExecutionOwnerView:
    """组合独立 Saga truth 与 Host-dispatch recovery truth。"""

    recovery_view = None
    if recovery is not None:
        recovery_view = HostDispatchRecoveryView(
            dispatch_intent_id="dispatch-intent-1",
            execution_slice_hash=_SLICE_HASH,
            state=recovery,
        )
    return ExecutionOwnerView(
        saga=ExecutionSagaView(
            saga_id="saga-1",
            saga_revision=revision,
            status=status,
            active_slice_hash=_SLICE_HASH,
        ),
        active_dispatch_recovery=recovery_view,
    )


def _decide(*, checkpoint: WorkflowCheckpointView, execution: ExecutionOwnerView | None):
    """延迟导入 Task 7 recovery 模块，使 RED 表现为测试失败而不是 collection error。"""

    module = importlib.import_module("design_orchestrator.recovery")
    return module.decide_apply_resume(checkpoint=checkpoint, execution=execution)


def test_ready_without_dispatch_recovery_may_dispatch() -> None:
    """A：只有 refreshed Saga READY 且无 recovery 时才能允许新 dispatch。"""

    decision = _decide(checkpoint=_checkpoint(), execution=_execution("READY"))

    assert decision.route == "MAY_DISPATCH"
    assert decision.refreshed_saga_revision == 7
    assert decision.reason


def test_executing_without_dispatch_recovery_must_recover_or_wait() -> None:
    """B：Saga 已 EXECUTING 时 checkpoint 位置不能授权第二次 begin_execution。"""

    decision = _decide(checkpoint=_checkpoint(), execution=_execution("EXECUTING"))

    assert decision.route == "RECOVER_OR_WAIT"
    assert decision.refreshed_saga_revision == 7


def test_partially_committed_is_terminal_execution_state() -> None:
    """C：PARTIALLY_COMMITTED 必须进入 terminal/reconcile，而不是再次 dispatch。"""

    decision = _decide(
        checkpoint=_checkpoint(),
        execution=_execution("PARTIALLY_COMMITTED"),
    )

    assert decision.route == "TERMINAL_EXECUTION_STATE"
    assert decision.refreshed_saga_revision == 7


def test_pre_apply_checkpoint_cannot_override_already_succeeded_saga() -> None:
    """D：即使 checkpoint 仍在 pre-Apply，SUCCEEDED authoritative truth 仍优先。"""

    decision = _decide(
        checkpoint=_checkpoint(phase=WorkflowPhase.EXECUTION_GRANT),
        execution=_execution("SUCCEEDED", revision=11),
    )

    assert decision.route == "TERMINAL_EXECUTION_STATE"
    assert decision.refreshed_saga_revision == 11


def test_active_outcome_unknown_always_precedes_saga_status() -> None:
    """F：OUTCOME_UNKNOWN 留在 dispatch-recovery projection，并强制 RECOVER_OR_WAIT。"""

    decision = _decide(
        checkpoint=_checkpoint(),
        execution=_execution(
            "EXECUTING",
            recovery=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
        ),
    )

    assert decision.route == "RECOVER_OR_WAIT"
    assert decision.refreshed_saga_revision == 7


def test_ready_with_recovery_required_or_safe_to_retry_never_authorizes_dispatch() -> None:
    """G：execution owner 即使判 SAFE_TO_RETRY，workflow 也不能自行制造新 Host command identity。"""

    for state in (
        HostDispatchRecoveryState.RECOVERY_REQUIRED,
        HostDispatchRecoveryState.SAFE_TO_RETRY,
    ):
        decision = _decide(
            checkpoint=_checkpoint(),
            execution=_execution("READY", recovery=state),
        )
        assert decision.route == "RECOVER_OR_WAIT"


class _ResumeServices:
    """记录 refresh、dispatch 与 reconcile 次序的最小 WorkflowServices fake。"""

    def __init__(self, execution: ExecutionOwnerView) -> None:
        self.execution = execution
        self.calls: list[str] = []
        self.begin_count = 0
        self.dispatch_intent_ids: list[str] = []

    # Task 7 图测试从 execution_grant 之后恢复；此前方法只为 protocol 完整性提供哨兵。
    def __getattr__(self, name: str):
        raise AssertionError(f"unexpected workflow service call: {name}")

    def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView:
        """记录每次 authoritative refresh，并保留当前 recovery identity 供断言。"""

        self.calls.append(f"refresh:{saga_id}")
        recovery = self.execution.active_dispatch_recovery
        if recovery is not None:
            self.dispatch_intent_ids.append(recovery.dispatch_intent_id)
        return self.execution

    def begin_execution(self, execution_plan_ref: StableRef, grant_ref: StableRef) -> str:
        """模拟唯一允许的新 dispatch，并记录它是否发生在 refresh 之后。"""

        self.calls.append("begin_execution")
        self.begin_count += 1
        return "saga-new"

    def verify_reconcile(self, saga_id: str) -> ExecutionOwnerView:
        """记录 terminal/reconcile 路由；测试不在这里复制真实 Saga 逻辑。"""

        self.calls.append(f"verify:{saga_id}")
        return self.execution


def _seed_after_execution_grant(*, services: _ResumeServices, saga_id: str = "saga-1"):
    """把 compiled graph 的 durable state 定位到 execution_grant 之后，模拟进程重启。"""

    saver = InMemorySaver()
    graph = build_workflow_graph(services).compile(checkpointer=saver)
    config = {"configurable": {"thread_id": "task-resume-graph", "checkpoint_ns": ""}}
    graph.update_state(
        config,
        {
            "task_id": "task-resume-graph",
            "phase": WorkflowPhase.APPLY_WAIT.value,
            "changeset_ref": {"ref_id": "stale-changeset", "content_hash": "e" * 64},
            "approval_ref": {"ref_id": "stale-approval", "content_hash": "f" * 64},
            "execution_plan_ref": {"ref_id": "plan-1", "content_hash": "1" * 64},
            "grant_ref": {"ref_id": "grant-1", "content_hash": "2" * 64},
            "saga_id": saga_id,
        },
        as_node="execution_grant",
    )
    return graph, config


def test_graph_refreshes_ready_owner_before_dispatch() -> None:
    """A/E：即使 checkpoint 已到 apply 边界，也必须先 refresh READY truth，再允许 dispatch。"""

    services = _ResumeServices(_execution("READY", revision=9))
    graph, config = _seed_after_execution_grant(services=services)

    graph.invoke(None, config)

    assert services.begin_count == 1
    assert services.calls[:2] == ["refresh:saga-1", "begin_execution"]
    assert services.calls[2] == "verify:saga-new"


def test_graph_refreshes_owner_before_skipping_dispatch_for_succeeded_saga() -> None:
    """D/E：旧 approval/change refs 不能覆盖 SUCCEEDED owner truth，且 refresh 必须先发生。"""

    services = _ResumeServices(_execution("SUCCEEDED", revision=12))
    graph, config = _seed_after_execution_grant(services=services)

    graph.invoke(None, config)

    assert services.begin_count == 0
    assert services.calls[:2] == ["refresh:saga-1", "verify:saga-1"]


def test_graph_outcome_unknown_keeps_stable_dispatch_identity_across_resumes() -> None:
    """F：重复 workflow resume 只刷新同一 recovery identity，不触发第二次 Host dispatch。"""

    services = _ResumeServices(
        _execution(
            "EXECUTING",
            recovery=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
        )
    )
    graph, config = _seed_after_execution_grant(services=services)

    # 第一次恢复读取 owner truth 后进入 EXECUTION_JOB interrupt；此时不得触发 begin_execution。
    graph.invoke(None, config)
    # LangGraph 的 interrupt 必须由一个真实、非空的 resume payload 消费；空 dict 会被视为
    # 未提供 resume value。业务节点不读取该 payload，它只作为“外部等待已经被唤醒”的信号。
    graph.invoke(Command(resume={"status": "wake"}), config)

    assert services.begin_count == 0
    assert services.dispatch_intent_ids == ["dispatch-intent-1", "dispatch-intent-1"]
    assert services.calls == ["refresh:saga-1", "refresh:saga-1"]
