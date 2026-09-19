"""ADR-010 deterministic workflow service boundary 的 RED 测试。

测试冻结两个关键事实：Workflow Orchestrator 只依赖 framework-neutral service views；
恢复执行时必须先看 ADR-009 Host-dispatch recovery truth，再解释 Execution Saga 状态。
"""

from __future__ import annotations

import inspect

import pytest
from design_orchestrator.workflow_contracts import WorkflowPhase
from design_orchestrator.workflow_services import (
    ExecutionOwnerView,
    ExecutionSagaView,
    HostDispatchRecoveryState,
    HostDispatchRecoveryView,
    WorkflowServices,
    WorkflowStateError,
    classify_execution_resume,
)


def _executing_saga() -> ExecutionSagaView:
    """构造一个仍处于执行期的 Saga read model。"""

    return ExecutionSagaView(
        saga_id="saga-1",
        saga_revision=4,
        status="EXECUTING",
        active_slice_hash="a" * 64,
    )


def test_workflow_services_expose_only_framework_neutral_boundary() -> None:
    """Service protocol 不得直接交换 runtime 或 execution-store 的领域实现对象。"""

    source = inspect.getsource(WorkflowServices)

    assert "langgraph" not in source.lower()
    assert "StoredExecutionSagaV2" not in source
    assert "HostDispatchIntent" not in source

    methods = {
        name
        for name, value in vars(WorkflowServices).items()
        if callable(value) and not name.startswith("_")
    }
    assert methods == {
        "resolve_host_context",
        "ensure_context_freshness",
        "resolve_operations",
        "ensure_operation_artifact",
        "bind_parameters",
        "ensure_operation_freshness",
        "analyze_impact",
        "build_changeset",
        "preview",
        "request_approval",
        "plan_execution",
        "check_revision_barrier",
        "bind_providers",
        "issue_execution_grant",
        "begin_execution",
        "get_execution_owner_state",
        "verify_reconcile",
    }


def test_execution_owner_views_normalize_stable_identity() -> None:
    """执行 owner projection 必须保存规范化身份、revision 与 canonical slice hash。"""

    saga = ExecutionSagaView(
        saga_id=" saga-1 ",
        saga_revision=0,
        status=" READY ",
        active_slice_hash=None,
    )
    recovery = HostDispatchRecoveryView(
        dispatch_intent_id=" intent-1 ",
        execution_slice_hash="b" * 64,
        state="OUTCOME_UNKNOWN",
    )

    assert saga.saga_id == "saga-1"
    assert saga.status == "READY"
    assert recovery.dispatch_intent_id == "intent-1"
    assert recovery.state is HostDispatchRecoveryState.OUTCOME_UNKNOWN

    with pytest.raises(ValueError):
        ExecutionSagaView("saga-1", -1, "READY", None)
    with pytest.raises(ValueError):
        HostDispatchRecoveryView("intent-1", "BAD-HASH", "OUTCOME_UNKNOWN")


def test_active_dispatch_recovery_is_classified_before_saga_status() -> None:
    """Host effect 未决时，workflow 不得仅凭 Saga status 决定重新 dispatch。"""

    ready_but_unknown = ExecutionOwnerView(
        saga=ExecutionSagaView("saga-1", 5, "READY", "a" * 64),
        active_dispatch_recovery=HostDispatchRecoveryView(
            dispatch_intent_id="intent-1",
            execution_slice_hash="a" * 64,
            state=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
        ),
    )

    assert classify_execution_resume(ready_but_unknown) == "RECOVER_OR_WAIT"


def test_execution_resume_classification_uses_authoritative_owner_truth() -> None:
    """Synthetic checkpoint phase 不能替代重新读取 execution-owner projection。"""

    checkpoint_phase = WorkflowPhase.APPLY_WAIT
    executing = ExecutionOwnerView(saga=_executing_saga())
    unknown = ExecutionOwnerView(
        saga=executing.saga,
        active_dispatch_recovery=HostDispatchRecoveryView(
            dispatch_intent_id="intent-1",
            execution_slice_hash="a" * 64,
            state=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
        ),
    )

    assert checkpoint_phase is WorkflowPhase.APPLY_WAIT
    assert classify_execution_resume(executing) == "RECOVER_OR_WAIT"
    assert classify_execution_resume(unknown) == "RECOVER_OR_WAIT"

    assert classify_execution_resume(
        ExecutionOwnerView(saga=ExecutionSagaView("saga-1", 2, "READY", None))
    ) == "MAY_DISPATCH"
    for terminal in ("SUCCEEDED", "DIVERGED", "PARTIALLY_COMMITTED", "FAILED"):
        assert classify_execution_resume(
            ExecutionOwnerView(saga=ExecutionSagaView("saga-1", 9, terminal, None))
        ) == "TERMINAL"


def test_unknown_saga_status_fails_closed_with_stable_error_code() -> None:
    """未知执行状态不能猜测继续路径，必须以稳定 workflow error code 失败。"""

    with pytest.raises(WorkflowStateError) as captured:
        classify_execution_resume(
            ExecutionOwnerView(
                saga=ExecutionSagaView("saga-1", 1, "FUTURE_STATUS", None)
            )
        )

    assert captured.value.code == "WORKFLOW_SAGA_STATUS_UNKNOWN"
    assert captured.value.detail == "FUTURE_STATUS"
