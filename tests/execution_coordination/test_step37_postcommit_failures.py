from design_approval_scope import CanonicalAspect
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
    def __init__(self, outcomes):
        self.outcomes = dict(outcomes)
        self.calls = []

    def admit(self, execution_slice):
        self.calls.append(execution_slice.execution_slice_hash)
        return self.outcomes[execution_slice.execution_slice_hash]


class RecordingHostPort:
    def __init__(self, outcomes):
        self.outcomes = dict(outcomes)
        self.calls = []

    def execute(self, execution_slice, authority):
        self.calls.append(execution_slice.execution_slice_hash)
        return self.outcomes[execution_slice.execution_slice_hash]


class RecordingHostRegistry:
    def __init__(self, ports):
        self.ports = dict(ports)
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        return self.ports[runtime_ref]


class PropertyEvidencePort:
    def __init__(self, bundle_builder, values=None):
        self.bundle_builder = bundle_builder
        self.values = dict(values or {})
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
        return self.bundle_builder(
            execution_slice=execution_slice,
            actual_delta=actual_delta,
            canonical_changeset=canonical_changeset,
            property_value=self.values.get(
                execution_slice.execution_slice_hash,
                300.0,
            ),
        )


class FixedClock:
    def now(self):
        return "2026-08-31T13:10:00Z"


def _setup(transaction):
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
    ordered = tuple(
        slice_by_hash[value] for value in stored.definition.ordered_slice_hashes
    )
    return reconciliation, stored, ordered


def _execute(transaction, reconciliation, authority_port, registry, evidence_port):
    return ExecutionSagaCoordinator(
        reconciliation=reconciliation,
        authority_port=authority_port,
        host_registry=registry,
        evidence_port=evidence_port,
        clock=FixedClock(),
    ).execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )


def test_second_slice_scope_breach_preserves_delta_and_blocks_third(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_delta_for_slice,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    reconciliation, stored, ordered = _setup(transaction)
    first, second, third = ordered
    first_authority = build_authority_for_slice(transaction, first)
    second_authority = build_authority_for_slice(transaction, second)
    first_delta = build_delta_for_slice(first, first_authority)
    second_delta = build_delta_for_slice(
        second,
        second_authority,
        aspect=CanonicalAspect.GEOMETRY,
    )
    authority_port = RecordingAuthorityPort(
        {
            first.execution_slice_hash: first_authority,
            second.execution_slice_hash: second_authority,
        }
    )
    registry = RecordingHostRegistry(
        {
            first.host_runtime_ref: RecordingHostPort(
                {
                    first.execution_slice_hash: HostCommitted(
                        actual_delta=first_delta,
                        committed_at="2026-08-31T13:01:00Z",
                    )
                }
            ),
            second.host_runtime_ref: RecordingHostPort(
                {
                    second.execution_slice_hash: HostCommitted(
                        actual_delta=second_delta,
                        committed_at="2026-08-31T13:02:00Z",
                    )
                }
            ),
        }
    )
    evidence_port = PropertyEvidencePort(build_verification_bundle)

    result = _execute(
        transaction,
        reconciliation,
        authority_port,
        registry,
        evidence_port,
    )

    final = reconciliation.get_saga(stored.definition.saga_id)
    assert final is not None
    assert result.status is CoordinationStatus.PARTIALLY_COMMITTED
    assert final.status is ExecutionSagaStatus.PARTIALLY_COMMITTED
    assert final.slice_states[0].status is SliceReconciliationStatus.SUCCEEDED
    assert final.slice_states[1].status is SliceReconciliationStatus.SCOPE_BREACH
    assert final.slice_states[1].actual_delta_hash == second_delta.actual_delta_hash
    assert final.slice_states[1].scope_comparison_hash is not None
    assert result.failure_ref == final.slice_states[1].scope_comparison_hash
    assert final.slice_states[2].status is SliceReconciliationStatus.BLOCKED
    assert evidence_port.calls == [first.execution_slice_hash]
    assert registry.resolutions == [first.host_runtime_ref, second.host_runtime_ref]
    assert third.host_runtime_ref not in registry.resolutions


def test_second_slice_verification_failure_preserves_verification_and_blocks_third(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_delta_for_slice,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    reconciliation, stored, ordered = _setup(transaction)
    first, second, third = ordered
    first_authority = build_authority_for_slice(transaction, first)
    second_authority = build_authority_for_slice(transaction, second)
    first_delta = build_delta_for_slice(first, first_authority)
    second_delta = build_delta_for_slice(second, second_authority)
    authority_port = RecordingAuthorityPort(
        {
            first.execution_slice_hash: first_authority,
            second.execution_slice_hash: second_authority,
        }
    )
    registry = RecordingHostRegistry(
        {
            first.host_runtime_ref: RecordingHostPort(
                {
                    first.execution_slice_hash: HostCommitted(
                        actual_delta=first_delta,
                        committed_at="2026-08-31T13:03:00Z",
                    )
                }
            ),
            second.host_runtime_ref: RecordingHostPort(
                {
                    second.execution_slice_hash: HostCommitted(
                        actual_delta=second_delta,
                        committed_at="2026-08-31T13:04:00Z",
                    )
                }
            ),
        }
    )
    evidence_port = PropertyEvidencePort(
        build_verification_bundle,
        {second.execution_slice_hash: 301.0},
    )

    result = _execute(
        transaction,
        reconciliation,
        authority_port,
        registry,
        evidence_port,
    )

    final = reconciliation.get_saga(stored.definition.saga_id)
    assert final is not None
    assert result.status is CoordinationStatus.PARTIALLY_COMMITTED
    assert final.status is ExecutionSagaStatus.PARTIALLY_COMMITTED
    assert final.slice_states[0].status is SliceReconciliationStatus.SUCCEEDED
    assert final.slice_states[1].status is SliceReconciliationStatus.VERIFY_FAILED
    assert final.slice_states[1].actual_delta_hash == second_delta.actual_delta_hash
    assert final.slice_states[1].verification_hash is not None
    assert result.failure_ref == final.slice_states[1].verification_hash
    assert final.slice_states[2].status is SliceReconciliationStatus.BLOCKED
    assert evidence_port.calls == [
        first.execution_slice_hash,
        second.execution_slice_hash,
    ]
    assert registry.resolutions == [first.host_runtime_ref, second.host_runtime_ref]
    assert third.host_runtime_ref not in registry.resolutions
