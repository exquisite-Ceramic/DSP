from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest
from design_gateway_authorization import (
    GatewayAuthorizationError,
    GrantState,
    compute_admission_fingerprint,
)
from design_orchestrator import WorkflowPhase, WorkflowResumeCommand
from design_orchestrator.workflow_services import WorkflowStateError
from design_product_runtime import ProductFlowStatus


class _ApprovalScopeMismatchBoundary:
    """只在允许的 human/policy 输入边界注入错误 scope；Gateway owner 仍使用 production。"""

    def __init__(self, delegate) -> None:
        self._delegate = delegate

    def request_approval(self, changeset_ref):
        """保留真实 admission 其余字段，只改 approved_scope_hash 并重算其 owner fingerprint。"""

        admission = self._delegate.request_approval(changeset_ref)
        mismatched = replace(
            admission,
            approved_scope_hash="f" * 64,
            admission_fingerprint="0" * 64,
        )
        return replace(
            mismatched,
            admission_fingerprint=compute_admission_fingerprint(mismatched),
        )


class _GrantLifecycleInjectionClock:
    """在第二次 grant admission 前注入持久 lifecycle 状态，不替代 Gateway 校验逻辑。"""

    def __init__(self, gateway_store, state: GrantState) -> None:
        self._gateway_store = gateway_store
        self._state = state
        self.calls = 0

    def now(self) -> datetime:
        """第三次 coordination timestamp 正好位于 begin_execution 的再次 admission 之前。"""

        self.calls += 1
        if self.calls == 3:
            grants = self._gateway_store._grants_v2
            assert len(grants) == 1
            grant_hash, stored = next(iter(grants.items()))
            grants[grant_hash] = replace(stored, state=self._state)
        return datetime.fromisoformat("2026-09-24T10:00:00+00:00")


def _adapter(case):
    """仅供 acceptance failure injection 访问既有 production composition adapter。"""

    return case.runtime._services._external_owners


def _submit_to_proposal(case):
    """从真实 ProductFlow 推进到 operation proposal HITL，授权链尚未开始。"""

    proposal = case.flow.submit(case.request)
    assert proposal.status is ProductFlowStatus.WAITING
    assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
    assert proposal.checkpoint.pending_interaction is not None
    assert case.host.execute_count == 0
    return proposal


def _accept(case, proposal):
    """接受 exact durable proposal，让真实 approval/planning/grant 链继续运行。"""

    return case.flow.resume(
        case.task_id,
        WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            pause_id=proposal.checkpoint.pending_interaction.pause_id,
        ),
    )


def _assert_gateway_failure(captured, code: str) -> None:
    """校验 runtime 公共包装与真实 GatewayAuthorizationError 根因。"""

    assert captured.value.code == "WORKFLOW_SERVICE_FAILURE"
    cause = captured.value.__cause__
    assert isinstance(cause, GatewayAuthorizationError)
    assert cause.code == code


def _assert_no_dispatch(case) -> None:
    """授权失败必须停在 durable Saga/Host dispatch 之前。"""

    checkpoint = case.runtime.get_checkpoint(case.task_id)
    assert checkpoint is not None
    assert checkpoint.saga_id is None
    assert case.host.execute_count == 0
    assert "set_wall_thickness" not in case.host.command_operations()


def test_approval_scope_mismatch_fails_closed_before_host_dispatch(
    revit_wall_thickness_product_case,
) -> None:
    """场景 7/19：approval 与 authoritative scope 不一致时由真实 Gateway V2 fail closed。"""

    case = revit_wall_thickness_product_case("task-product-approval-scope-mismatch")
    proposal = _submit_to_proposal(case)
    adapter = _adapter(case)
    adapter._approval_admission = _ApprovalScopeMismatchBoundary(
        adapter._approval_admission
    )

    with pytest.raises(WorkflowStateError) as captured:
        _accept(case, proposal)

    _assert_gateway_failure(captured, "APPROVAL_SCOPE_MISMATCH")
    _assert_no_dispatch(case)


@pytest.mark.parametrize(
    ("grant_state", "expected_code"),
    (
        (GrantState.REVOKED, "EXECUTION_GRANT_REVOKED"),
        (GrantState.EXPIRED, "EXECUTION_GRANT_EXPIRED"),
    ),
)
def test_revoked_or_expired_grant_fails_closed_before_host_dispatch(
    revit_wall_thickness_product_case,
    grant_state: GrantState,
    expected_code: str,
) -> None:
    """场景 8-9/19：真实 Gateway 在再次 admission 时拒绝已撤销/过期 grant。"""

    case = revit_wall_thickness_product_case(
        f"task-product-grant-{grant_state.value.lower()}"
    )
    proposal = _submit_to_proposal(case)
    adapter = _adapter(case)
    clock = _GrantLifecycleInjectionClock(
        adapter._gateway_authorization_store,
        grant_state,
    )
    adapter._coordination_clock = clock

    with pytest.raises(WorkflowStateError) as captured:
        _accept(case, proposal)

    _assert_gateway_failure(captured, expected_code)
    assert clock.calls == 3
    _assert_no_dispatch(case)
