"""Task 9：集中证明 ADR-009 Host-effect crash windows E-G。"""

from __future__ import annotations

import pytest
from design_execution_coordination import (
    HostFailed,
    HostFailurePhase,
    MaterializedCoordinationStatus,
    UnknownOutcomeRecovery,
)
from design_execution_reconciliation import (
    ExecutionSagaStatusV2,
    HostDispatchStatus,
    ReconciliationError,
    SliceReconciliationStatusV2,
    build_host_dispatch_intent,
)

from tests.execution_coordination._materialized_support import (
    InMemoryDispatchIntentStore,
    execute,
    materialized_fixture,
)
from tests.execution_coordination._support import phase_i_readiness_inputs


class _Probe:
    """只读 Host outcome probe；用于模拟进程重启后的 evidence lookup。"""

    def __init__(self, result) -> None:
        self.result = result
        self.calls = []

    def resolve(self, execution_slice, dispatch_context):
        """记录恢复时使用的 stable dispatch identity，不执行任何 mutation。"""
        self.calls.append((execution_slice, dispatch_context))
        return self.result


def _first_slice_inputs(fixture):
    """返回首个 Slice 的 exact admitted authority 与 binding lineage。"""
    execution_slice = fixture.ctx.execution_plan.execution_slices[0]
    authority = next(
        item
        for item in fixture.ctx.authorities
        if item.execution_slice_hash == execution_slice.execution_slice_hash
    )
    binding_set = next(
        item
        for item in fixture.ctx.binding_sets
        if item.execution_slice_hash == execution_slice.execution_slice_hash
    )
    return execution_slice, authority, binding_set


def _event_names_for_slice(fixture, execution_slice_hash: str) -> tuple[str, ...]:
    """只抽取首 Slice 的 durable-intent/Host 边界事件，忽略后续 reconciliation 细节。"""
    names = {
        "reserve_slice_admission",
        "confirm_slice_admitted",
        "prepare_dispatch_intent",
        "mark_dispatched",
        "host.execute",
        "mark_outcome_unknown",
    }
    return tuple(
        name
        for name, payload in fixture.events
        if name in names
        and getattr(payload, "execution_slice_hash", payload) == execution_slice_hash
    )


def test_e_f_restart_uses_same_intent_identity_and_unknown_never_blind_retries() -> None:
    """E/F：intent 先于 Host I/O 持久化；响应丢失后只能按同一 identity probe，不能盲重试。"""
    failure = HostFailed(
        phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
        failure_ref="HOST_RESPONSE_LOST",
        failed_at="2026-09-18T15:10:00Z",
    )
    fixture = materialized_fixture(
        host_failures={"autocad": failure},
        record_events=True,
    )
    execution_slice, authority, binding_set = _first_slice_inputs(fixture)

    result = execute(fixture)

    assert result.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED
    assert _event_names_for_slice(fixture, execution_slice.execution_slice_hash) == (
        "reserve_slice_admission",
        "confirm_slice_admitted",
        "prepare_dispatch_intent",
        "mark_dispatched",
        "host.execute",
        "mark_outcome_unknown",
    )

    durable_intent = fixture.dispatch_intents.prepared_by_slice[
        execution_slice.execution_slice_hash
    ]
    assert durable_intent.status is HostDispatchStatus.OUTCOME_UNKNOWN
    original_host_call = fixture.host_registry.ports["autocad"].calls[0]
    original_context = original_host_call[3]
    assert original_context.dispatch_intent_id == str(durable_intent.dispatch_intent_id)
    assert original_context.idempotency_key == str(durable_intent.idempotency_key)
    assert len(fixture.host_registry.ports["autocad"].calls) == 1

    stored_saga = fixture.reconciliation.get_saga(result.saga_id)
    assert stored_saga is not None
    probe = _Probe(
        HostFailed(
            phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
            failure_ref="READBACK_STILL_AMBIGUOUS",
            failed_at="2026-09-18T15:11:00Z",
        )
    )

    # 用一个全新的 recovery service 代表平台进程重启；durable store 与 identity 不变。
    recovery = UnknownOutcomeRecovery(
        reconciliation=fixture.reconciliation,
        dispatch_intents=fixture.dispatch_intents,
        outcome_probe=probe,
        evidence_port=fixture.evidence_port,
        canonical_changeset=fixture.ctx.case.changeset,
        approval_scope_boundary=fixture.ctx.case.boundary_v2,
        clock=fixture.clock,
    )
    recovered = recovery.recover(
        stored_saga=stored_saga,
        execution_slice=execution_slice,
        authority=authority,
        binding_set=binding_set,
        dispatch_intent=durable_intent,
    )

    assert recovered.status is MaterializedCoordinationStatus.RECOVERY_REQUIRED
    assert recovered.failure_ref == "READBACK_STILL_AMBIGUOUS"
    after_recovery = fixture.dispatch_intents.get(durable_intent.dispatch_intent_id)
    assert after_recovery == durable_intent
    assert len(probe.calls) == 1
    recovery_context = probe.calls[0][1]
    assert recovery_context.dispatch_intent_id == original_context.dispatch_intent_id
    assert recovery_context.idempotency_key == original_context.idempotency_key
    assert len(fixture.host_registry.ports["autocad"].calls) == 1


def test_e2_conflicting_admitted_lineage_never_creates_second_host_call() -> None:
    """E2：同一 Saga/Slice 的第二个 admitted grant/binding candidate 必须在 Host I/O 前冲突。"""
    ctx = phase_i_readiness_inputs()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    store = InMemoryDispatchIntentStore()

    conflicting = build_host_dispatch_intent(
        saga_id=ctx.saga_definition.saga_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        grant_hash="f" * 64,
        binding_set_hash=authority.binding_set_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        expected_host_revision=None,
        prepared_at="2026-09-18T15:20:00Z",
    )
    store.prepare(conflicting)
    fixture = materialized_fixture(dispatch_intents=store)

    with pytest.raises(ReconciliationError) as exc_info:
        execute(fixture)

    assert exc_info.value.code == "DISPATCH_INTENT_CONFLICT"
    assert store.prepared_by_slice[execution_slice.execution_slice_hash] == conflicting
    assert len(store.prepared_by_slice) == 1
    assert all(port.calls == [] for port in fixture.host_registry.ports.values())


def test_g_later_slice_failure_preserves_existing_partial_commit_semantics() -> None:
    """G：前一 Slice 已提交而后一 Slice BEFORE_COMMIT 失败时，Saga 仍由既有 partial semantics 收口。"""
    failure = HostFailed(
        phase=HostFailurePhase.BEFORE_COMMIT,
        failure_ref="REVIT_REVISION_CONFLICT",
        failed_at="2026-09-18T15:30:00Z",
    )
    fixture = materialized_fixture(host_failures={"revit": failure})

    result = execute(fixture)

    assert result.status is MaterializedCoordinationStatus.PARTIALLY_COMMITTED
    assert result.failure_ref == "REVIT_REVISION_CONFLICT"
    assert fixture.convergence_verifier.calls == []
    assert len(fixture.host_registry.ports["autocad"].calls) == 1
    assert len(fixture.host_registry.ports["revit"].calls) == 1

    stored = fixture.reconciliation.get_saga(result.saga_id)
    assert stored is not None
    assert stored.status is ExecutionSagaStatusV2.PARTIALLY_COMMITTED
    assert stored.slice_states[0].status is SliceReconciliationStatusV2.SUCCEEDED
    assert stored.slice_states[1].status is SliceReconciliationStatusV2.FAILED_BEFORE_COMMIT
    assert stored.slice_states[1].actual_delta_hash is None
