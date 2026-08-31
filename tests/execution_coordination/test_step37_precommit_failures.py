from design_execution_coordination import (
    AuthorityFailure,
    CoordinationStatus,
    ExecutionSagaCoordinator,
    HostCommitted,
    HostFailed,
    HostFailurePhase,
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
        self.calls.append(
            (execution_slice.execution_slice_hash, authority.host_instance_id)
        )
        return self.outcomes[execution_slice.execution_slice_hash]


class RecordingHostRegistry:
    def __init__(self, ports):
        self.ports = dict(ports)
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        return self.ports[runtime_ref]


class RecordingEvidencePort:
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
        return self.bundle_builder(
            execution_slice=execution_slice,
            actual_delta=actual_delta,
            canonical_changeset=canonical_changeset,
        )


class FixedClock:
    def now(self):
        return "2026-08-31T12:59:00Z"


def _ordered_slices(reconciliation, transaction):
    stored = reconciliation.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    slice_by_hash = {
        item.execution_slice_hash: item
        for item in transaction.execution_plan.execution_slices
    }
    return stored, tuple(
        slice_by_hash[value] for value in stored.definition.ordered_slice_hashes
    )


def _coordinator(reconciliation, authority_port, registry, evidence_port):
    return ExecutionSagaCoordinator(
        reconciliation=reconciliation,
        authority_port=authority_port,
        host_registry=registry,
        evidence_port=evidence_port,
        clock=FixedClock(),
    )


def test_first_slice_authority_failure_is_durable_precommit_failure(
    step37_three_slice_transaction,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    reconciliation = ExecutionReconciliationService(
        store=InMemoryExecutionSagaStore()
    )
    stored, ordered_slices = _ordered_slices(reconciliation, transaction)
    first = ordered_slices[0]
    authority_port = RecordingAuthorityPort(
        {
            first.execution_slice_hash: AuthorityFailure(
                failure_ref="AUTH-DENIED-STEP37",
                failed_at="2026-08-31T12:01:00Z",
            )
        }
    )
    registry = RecordingHostRegistry({})
    evidence_port = RecordingEvidencePort(build_verification_bundle)

    result = _coordinator(
        reconciliation,
        authority_port,
        registry,
        evidence_port,
    ).execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert result.status is CoordinationStatus.FAILED
    assert result.failure_ref == "AUTH-DENIED-STEP37"
    final = reconciliation.get_saga(stored.definition.saga_id)
    assert final is not None
    assert final.status is ExecutionSagaStatus.FAILED
    assert final.slice_states[0].status is SliceReconciliationStatus.FAILED_BEFORE_COMMIT
    assert final.slice_states[0].actual_delta_hash is None
    assert all(
        state.status is SliceReconciliationStatus.BLOCKED
        for state in final.slice_states[1:]
    )
    assert authority_port.calls == [first.execution_slice_hash]
    assert registry.resolutions == []
    assert evidence_port.calls == []


def test_first_slice_host_before_commit_failure_records_no_delta(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    reconciliation = ExecutionReconciliationService(
        store=InMemoryExecutionSagaStore()
    )
    stored, ordered_slices = _ordered_slices(reconciliation, transaction)
    first = ordered_slices[0]
    authority = build_authority_for_slice(transaction, first)
    authority_port = RecordingAuthorityPort({first.execution_slice_hash: authority})
    first_host = RecordingHostPort(
        {
            first.execution_slice_hash: HostFailed(
                phase=HostFailurePhase.BEFORE_COMMIT,
                failure_ref="HOST-PRECOMMIT-STEP37",
                failed_at="2026-08-31T12:02:00Z",
            )
        }
    )
    registry = RecordingHostRegistry({first.host_runtime_ref: first_host})
    evidence_port = RecordingEvidencePort(build_verification_bundle)

    result = _coordinator(
        reconciliation,
        authority_port,
        registry,
        evidence_port,
    ).execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert result.status is CoordinationStatus.FAILED
    assert result.failure_ref == "HOST-PRECOMMIT-STEP37"
    final = reconciliation.get_saga(stored.definition.saga_id)
    assert final is not None
    assert final.status is ExecutionSagaStatus.FAILED
    assert final.slice_states[0].status is SliceReconciliationStatus.FAILED_BEFORE_COMMIT
    assert final.slice_states[0].actual_delta_hash is None
    assert first_host.calls == [
        (first.execution_slice_hash, first.host_runtime_ref.host_instance_id)
    ]
    assert evidence_port.calls == []


def test_second_slice_precommit_failure_preserves_first_commit_and_blocks_third(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_delta_for_slice,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    reconciliation = ExecutionReconciliationService(
        store=InMemoryExecutionSagaStore()
    )
    stored, ordered_slices = _ordered_slices(reconciliation, transaction)
    first, second, third = ordered_slices
    first_authority = build_authority_for_slice(transaction, first)
    second_authority = build_authority_for_slice(transaction, second)
    first_delta = build_delta_for_slice(first, first_authority)

    authority_port = RecordingAuthorityPort(
        {
            first.execution_slice_hash: first_authority,
            second.execution_slice_hash: second_authority,
        }
    )
    first_host = RecordingHostPort(
        {
            first.execution_slice_hash: HostCommitted(
                actual_delta=first_delta,
                committed_at="2026-08-31T12:03:00Z",
            )
        }
    )
    second_host = RecordingHostPort(
        {
            second.execution_slice_hash: HostFailed(
                phase=HostFailurePhase.BEFORE_COMMIT,
                failure_ref="HOST-PRECOMMIT-SECOND-STEP37",
                failed_at="2026-08-31T12:04:00Z",
            )
        }
    )
    registry = RecordingHostRegistry(
        {
            first.host_runtime_ref: first_host,
            second.host_runtime_ref: second_host,
        }
    )
    evidence_port = RecordingEvidencePort(build_verification_bundle)

    result = _coordinator(
        reconciliation,
        authority_port,
        registry,
        evidence_port,
    ).execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert result.status is CoordinationStatus.PARTIALLY_COMMITTED
    assert result.failure_ref == "HOST-PRECOMMIT-SECOND-STEP37"
    final = reconciliation.get_saga(stored.definition.saga_id)
    assert final is not None
    assert final.status is ExecutionSagaStatus.PARTIALLY_COMMITTED
    assert final.slice_states[0].status is SliceReconciliationStatus.SUCCEEDED
    assert final.slice_states[0].actual_delta_hash == first_delta.actual_delta_hash
    assert final.slice_states[1].status is SliceReconciliationStatus.FAILED_BEFORE_COMMIT
    assert final.slice_states[1].actual_delta_hash is None
    assert final.slice_states[2].status is SliceReconciliationStatus.BLOCKED
    assert authority_port.calls == [
        first.execution_slice_hash,
        second.execution_slice_hash,
    ]
    assert registry.resolutions == [first.host_runtime_ref, second.host_runtime_ref]
    assert third.host_runtime_ref not in registry.resolutions
    assert evidence_port.calls == [first.execution_slice_hash]
