from dataclasses import replace

from design_execution_coordination import (
    CoordinationStatus,
    ExecutionSagaCoordinator,
    HostCommitted,
)
from design_execution_reconciliation import (
    ExecutionReconciliationService,
    ExecutionSagaStatus,
    InMemoryExecutionSagaStore,
    SliceReconciliationStatus,
)


class RecordingAuthorityPort:
    def __init__(self, authorities):
        self.authorities = dict(authorities)
        self.calls = []

    def admit(self, execution_slice):
        self.calls.append(execution_slice.execution_slice_hash)
        return self.authorities[execution_slice.execution_slice_hash]


class RecordingHostPort:
    def __init__(self, outcome):
        self.outcome = outcome
        self.calls = []

    def execute(self, execution_slice, authority):
        self.calls.append(
            (execution_slice.execution_slice_hash, authority.host_instance_id)
        )
        return self.outcome


class ExactHostRegistry:
    def __init__(self, ports):
        self.ports = dict(ports)
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        return self.ports[runtime_ref]


class SignedEvidencePort:
    def __init__(self, bundle_builder):
        self.bundle_builder = bundle_builder
        self.calls = []

    def build_bundle(
        self,
        *,
        execution_slice,
        actual_delta,
        canonical_changeset,
        approval_scope_boundary,
    ):
        self.calls.append(execution_slice.execution_slice_hash)
        assert approval_scope_boundary.scope_hash == actual_delta.approved_scope_hash
        return self.bundle_builder(
            execution_slice=execution_slice,
            actual_delta=actual_delta,
            canonical_changeset=canonical_changeset,
        )


class FixedClock:
    def __init__(self):
        self.calls = 0

    def now(self):
        self.calls += 1
        return "2026-08-31T12:50:00Z"


def test_three_host_slices_execute_in_step33_order_and_succeed(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_delta_for_slice,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    reconciliation = ExecutionReconciliationService(
        store=InMemoryExecutionSagaStore()
    )
    stored = reconciliation.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    slice_by_hash = {
        item.execution_slice_hash: item
        for item in transaction.execution_plan.execution_slices
    }
    ordered_hashes = stored.definition.ordered_slice_hashes
    ordered_slices = tuple(slice_by_hash[value] for value in ordered_hashes)

    authorities = {
        slice_.execution_slice_hash: build_authority_for_slice(transaction, slice_)
        for slice_ in ordered_slices
    }
    ports = {}
    for slice_ in ordered_slices:
        authority = authorities[slice_.execution_slice_hash]
        delta = build_delta_for_slice(slice_, authority)
        ports[slice_.host_runtime_ref] = RecordingHostPort(
            HostCommitted(
                actual_delta=delta,
                committed_at="2026-08-31T12:51:00Z",
            )
        )

    authority_port = RecordingAuthorityPort(authorities)
    registry = ExactHostRegistry(ports)
    evidence_port = SignedEvidencePort(build_verification_bundle)
    coordinator = ExecutionSagaCoordinator(
        reconciliation=reconciliation,
        authority_port=authority_port,
        host_registry=registry,
        evidence_port=evidence_port,
        clock=FixedClock(),
    )

    result = coordinator.execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert result.status is CoordinationStatus.SUCCEEDED
    assert result.active_slice_hash is None
    final = reconciliation.get_saga(result.saga_id)
    assert final is not None
    assert final.status is ExecutionSagaStatus.SUCCEEDED
    assert all(
        state.status is SliceReconciliationStatus.SUCCEEDED
        for state in final.slice_states
    )
    assert authority_port.calls == list(ordered_hashes)
    assert registry.resolutions == [slice_.host_runtime_ref for slice_ in ordered_slices]
    assert evidence_port.calls == list(ordered_hashes)
    for slice_ in ordered_slices:
        port = ports[slice_.host_runtime_ref]
        assert port.calls == [
            (
                slice_.execution_slice_hash,
                slice_.host_runtime_ref.host_instance_id,
            )
        ]


def test_authority_host_mismatch_fails_before_host_routing(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    reconciliation = ExecutionReconciliationService(
        store=InMemoryExecutionSagaStore()
    )
    stored = reconciliation.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    first_hash = stored.definition.ordered_slice_hashes[0]
    first_slice = next(
        item
        for item in transaction.execution_plan.execution_slices
        if item.execution_slice_hash == first_hash
    )
    real_authority = build_authority_for_slice(transaction, first_slice)
    wrong_authority = replace(
        real_authority,
        host_instance_id="HOST-STEP37-WRONG",
    )

    authority_port = RecordingAuthorityPort({first_hash: wrong_authority})
    registry = ExactHostRegistry({})
    evidence_port = SignedEvidencePort(build_verification_bundle)
    coordinator = ExecutionSagaCoordinator(
        reconciliation=reconciliation,
        authority_port=authority_port,
        host_registry=registry,
        evidence_port=evidence_port,
        clock=FixedClock(),
    )

    result = coordinator.execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert result.status is CoordinationStatus.FAILED
    assert result.failure_ref == "COORDINATION_AUTHORITY_MISMATCH"
    final = reconciliation.get_saga(result.saga_id)
    assert final is not None
    assert final.status is ExecutionSagaStatus.FAILED
    assert final.slice_states[0].status is SliceReconciliationStatus.FAILED_BEFORE_COMMIT
    assert final.slice_states[0].actual_delta_hash is None
    assert all(
        state.status is SliceReconciliationStatus.BLOCKED
        for state in final.slice_states[1:]
    )
    assert authority_port.calls == [first_hash]
    assert registry.resolutions == []
    assert evidence_port.calls == []
