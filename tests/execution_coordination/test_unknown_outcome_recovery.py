"""Task 8：用 durable evidence 驱动未知 Host outcome 恢复。"""

from __future__ import annotations

import pytest

from design_execution_coordination import (
    CoordinationError,
    HostCommitted,
    HostFailed,
    HostFailurePhase,
    MaterializedCoordinationStatus,
    UnknownOutcomeRecovery,
)
from design_execution_reconciliation import (
    HostDispatchStatus,
    SliceReconciliationStatusV2,
)

from tests.execution_coordination._materialized_support import (
    execute,
    materialized_fixture,
)
from tests.execution_reconciliation._support import signed_delta


class _Probe:
    """只读 Host outcome probe；测试明确区分 probe 与 mutation dispatch。"""

    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    def resolve(self, execution_slice, dispatch_context):
        """记录稳定 dispatch identity，并返回冻结的 Host recovery evidence。"""
        self.calls.append((execution_slice, dispatch_context))
        return self.result


def _unknown_case():
    """先制造一次真实 Task 7 OUTCOME_UNKNOWN，再返回恢复所需 durable lineage。"""
    failure = HostFailed(
        phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
        failure_ref="HOST_RESPONSE_LOST",
        failed_at="2026-09-06T14:01:30Z",
    )
    fixture = materialized_fixture(host_failures={"autocad": failure})
    first = fixture.ctx.execution_plan.execution_slices[0]
    result = execute(fixture)
    assert result.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED

    stored_saga = fixture.reconciliation.get_saga(result.saga_id)
    assert stored_saga is not None
    intent = fixture.dispatch_intents.prepared_by_slice[first.execution_slice_hash]
    assert intent.status is HostDispatchStatus.OUTCOME_UNKNOWN

    authority = next(
        item
        for item in fixture.ctx.authorities
        if item.materialization_id == first.materialization_id
    )
    binding_set = next(
        item
        for item in fixture.ctx.binding_sets
        if item.materialization_id == first.materialization_id
    )
    return fixture, stored_saga, first, authority, binding_set, intent


def _recovery(fixture, probe):
    """按计划接口组合 recovery service；所有语义判断仍委托既有 Step33 V2。"""
    return UnknownOutcomeRecovery(
        reconciliation=fixture.reconciliation,
        dispatch_intents=fixture.dispatch_intents,
        outcome_probe=probe,
        evidence_port=fixture.evidence_port,
        canonical_changeset=fixture.ctx.case.changeset,
        approval_scope_boundary=fixture.ctx.case.boundary_v2,
        clock=fixture.clock,
    )


def _recover(service, stored_saga, execution_slice, authority, binding_set, intent):
    """统一调用计划冻结的 recover keyword-only surface。"""
    return service.recover(
        stored_saga=stored_saga,
        execution_slice=execution_slice,
        authority=authority,
        binding_set=binding_set,
        dispatch_intent=intent,
    )


def test_recovery_without_durable_intent_fails_closed_before_host_probe():
    """调用方持有 intent 对象不等于 durable truth；store 缺失时 probe 也不得发生。"""
    fixture, stored, execution_slice, authority, binding_set, intent = _unknown_case()
    fixture.dispatch_intents.by_id.pop(intent.dispatch_intent_id)
    probe = _Probe(
        HostFailed(
            phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
            failure_ref="SHOULD_NOT_BE_OBSERVED",
            failed_at="2026-09-06T14:02:00Z",
        )
    )

    with pytest.raises(CoordinationError) as exc_info:
        _recover(
            _recovery(fixture, probe),
            stored,
            execution_slice,
            authority,
            binding_set,
            intent,
        )

    assert exc_info.value.code == "DISPATCH_INTENT_MISSING"
    assert probe.calls == []


def test_committed_recovery_reuses_durable_evidence_and_does_not_repeat_host_dispatch():
    """同一 logical command 被证明已提交后，只继续 Step33，不再次执行 Host mutation。"""
    fixture, stored, execution_slice, authority, binding_set, intent = _unknown_case()
    original_host_calls = len(fixture.host_registry.ports["autocad"].calls)
    recovered_delta = signed_delta(fixture.ctx, 0)
    probe = _Probe(
        HostCommitted(
            actual_delta=recovered_delta,
            committed_at="2026-09-06T14:01:00Z",
        )
    )
    service = _recovery(fixture, probe)

    result = _recover(
        service,
        stored,
        execution_slice,
        authority,
        binding_set,
        intent,
    )

    durable_intent = fixture.dispatch_intents.get(intent.dispatch_intent_id)
    recovered_saga = fixture.reconciliation.get_saga(stored.definition.saga_id)
    assert durable_intent.status is HostDispatchStatus.RECONCILED
    assert recovered_saga is not None
    recovered_state = next(
        item
        for item in recovered_saga.slice_states
        if item.execution_slice_hash == execution_slice.execution_slice_hash
    )
    assert recovered_state.status is SliceReconciliationStatusV2.SUCCEEDED
    assert recovered_state.actual_delta_hash == recovered_delta.actual_delta_hash
    assert result.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED
    assert len(fixture.host_registry.ports["autocad"].calls) == original_host_calls
    assert len(probe.calls) == 1

    # 已完成本地 reconciliation 后重复 recovery 只投影 durable truth；probe 也不重复。
    replay = _recover(
        service,
        recovered_saga,
        execution_slice,
        authority,
        binding_set,
        durable_intent,
    )
    assert replay == result
    assert len(probe.calls) == 1
    assert len(fixture.host_registry.ports["autocad"].calls) == original_host_calls


def test_not_committed_recovery_marks_safe_to_retry_without_reissuing_mutation():
    """只有 Host 给出 BEFORE_COMMIT 正向证据时，unknown 才能降为 SAFE_TO_RETRY。"""
    fixture, stored, execution_slice, authority, binding_set, intent = _unknown_case()
    original_host_calls = len(fixture.host_registry.ports["autocad"].calls)
    probe = _Probe(
        HostFailed(
            phase=HostFailurePhase.BEFORE_COMMIT,
            failure_ref="COMMAND_NOT_COMMITTED",
            failed_at="2026-09-06T14:02:00Z",
        )
    )

    result = _recover(
        _recovery(fixture, probe),
        stored,
        execution_slice,
        authority,
        binding_set,
        intent,
    )

    durable_intent = fixture.dispatch_intents.get(intent.dispatch_intent_id)
    assert durable_intent.status is HostDispatchStatus.SAFE_TO_RETRY
    assert result.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED
    assert result.failure_ref == "COMMAND_NOT_COMMITTED"
    assert len(fixture.host_registry.ports["autocad"].calls) == original_host_calls
    assert len(probe.calls) == 1


def test_ambiguous_recovery_remains_unknown_and_never_guesses():
    """read-back 仍不充分时保持 OUTCOME_UNKNOWN，timeout/缺响应绝不能推导未提交。"""
    fixture, stored, execution_slice, authority, binding_set, intent = _unknown_case()
    original_host_calls = len(fixture.host_registry.ports["autocad"].calls)
    probe = _Probe(
        HostFailed(
            phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
            failure_ref="READBACK_AMBIGUOUS",
            failed_at="2026-09-06T14:02:00Z",
        )
    )

    result = _recover(
        _recovery(fixture, probe),
        stored,
        execution_slice,
        authority,
        binding_set,
        intent,
    )

    durable_intent = fixture.dispatch_intents.get(intent.dispatch_intent_id)
    assert durable_intent.status is HostDispatchStatus.OUTCOME_UNKNOWN
    assert durable_intent.intent_revision == intent.intent_revision
    assert result.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED
    assert result.failure_ref == "READBACK_AMBIGUOUS"
    assert len(fixture.host_registry.ports["autocad"].calls) == original_host_calls
    assert len(probe.calls) == 1


def test_host_committed_intent_replay_continues_reconcile_without_dispatch():
    """intent 已有 HOST_COMMITTED durable evidence 时，只允许 probe/read-back 后继续 Step33。"""
    fixture, stored, execution_slice, authority, binding_set, intent = _unknown_case()
    committed = fixture.dispatch_intents.mark_host_committed(
        intent.dispatch_intent_id,
        expected_revision=intent.intent_revision,
        evidence_hash=signed_delta(fixture.ctx, 0).actual_delta_hash,
        observed_at="2026-09-06T14:01:00Z",
    )
    original_host_calls = len(fixture.host_registry.ports["autocad"].calls)
    probe = _Probe(
        HostCommitted(
            actual_delta=signed_delta(fixture.ctx, 0),
            committed_at="2026-09-06T14:01:00Z",
        )
    )

    result = _recover(
        _recovery(fixture, probe),
        stored,
        execution_slice,
        authority,
        binding_set,
        committed,
    )

    durable_intent = fixture.dispatch_intents.get(intent.dispatch_intent_id)
    assert durable_intent.status is HostDispatchStatus.RECONCILED
    assert result.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED
    assert len(fixture.host_registry.ports["autocad"].calls) == original_host_calls
    assert len(probe.calls) == 1
