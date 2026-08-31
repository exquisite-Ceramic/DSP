import pytest
from design_approval_scope import CanonicalAspect
from design_execution_coordination import (
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
    ReconciliationError,
    ScopeComparisonRequest,
    SliceReconciliationStatus,
)


class NoCallAuthorityPort:
    def __init__(self):
        self.calls = []

    def admit(self, execution_slice):
        self.calls.append(execution_slice.execution_slice_hash)
        raise AssertionError("preflight guard must not call authority port")


class NoCallHostRegistry:
    def __init__(self):
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        raise AssertionError("preflight guard must not resolve a Host")


class NoCallEvidencePort:
    def __init__(self):
        self.calls = []

    def build_bundle(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("preflight guard must not request evidence")


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


class ConflictOnRecordHostCommit:
    def __init__(self, delegate):
        self.delegate = delegate
        self.conflicts = 0

    def __getattr__(self, name):
        return getattr(self.delegate, name)

    def record_host_commit(self, *args, **kwargs):
        self.conflicts += 1
        raise ReconciliationError("SAGA_CONFLICT", "injected CAS conflict")


class FixedClock:
    def now(self):
        return "2026-08-31T12:40:00Z"


def _build_coordinator(reconciliation):
    authority_port = NoCallAuthorityPort()
    host_registry = NoCallHostRegistry()
    evidence_port = NoCallEvidencePort()
    coordinator = ExecutionSagaCoordinator(
        reconciliation=reconciliation,
        authority_port=authority_port,
        host_registry=host_registry,
        evidence_port=evidence_port,
        clock=FixedClock(),
    )
    return coordinator, authority_port, host_registry, evidence_port


def _recording_coordinator(
    reconciliation,
    authority_port,
    host_registry,
    evidence_port,
):
    return ExecutionSagaCoordinator(
        reconciliation=reconciliation,
        authority_port=authority_port,
        host_registry=host_registry,
        evidence_port=evidence_port,
        clock=FixedClock(),
    )


def _slice_for_hash(transaction, slice_hash):
    return next(
        item
        for item in transaction.execution_plan.execution_slices
        if item.execution_slice_hash == slice_hash
    )


def _ordered_slices(reconciliation, transaction):
    stored = reconciliation.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    return stored, tuple(
        _slice_for_hash(transaction, value)
        for value in stored.definition.ordered_slice_hashes
    )


def test_active_slice_at_entry_requires_recovery_without_host_replay(
    step37_three_slice_transaction,
    build_authority_for_slice,
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
    first_slice = _slice_for_hash(transaction, first_hash)
    stored = reconciliation.reserve_slice_admission(
        stored.definition.saga_id,
        first_hash,
        expected_revision=stored.saga_revision,
        reserved_at="2026-08-31T12:35:00Z",
    )
    authority = build_authority_for_slice(transaction, first_slice)
    stored = reconciliation.confirm_slice_admitted(
        stored.definition.saga_id,
        authority,
        expected_revision=stored.saga_revision,
    )

    coordinator, authority_port, host_registry, evidence_port = _build_coordinator(
        reconciliation
    )
    result = coordinator.execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert result.status is CoordinationStatus.RECOVERY_REQUIRED
    assert result.active_slice_hash == first_hash
    assert result.saga_revision == stored.saga_revision
    assert result.failure_ref is None
    assert authority_port.calls == []
    assert host_registry.resolutions == []
    assert evidence_port.calls == []


def test_failed_saga_projects_stored_truth_without_external_replay(
    step37_three_slice_transaction,
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
    stored = reconciliation.reserve_slice_admission(
        stored.definition.saga_id,
        first_hash,
        expected_revision=stored.saga_revision,
        reserved_at="2026-08-31T12:41:00Z",
    )
    stored = reconciliation.fail_slice_before_commit(
        stored.definition.saga_id,
        first_hash,
        expected_revision=stored.saga_revision,
        failed_at="2026-08-31T12:42:00Z",
    )

    coordinator, authority_port, host_registry, evidence_port = _build_coordinator(
        reconciliation
    )
    result = coordinator.execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert result.status is CoordinationStatus.FAILED
    assert result.saga_revision == stored.saga_revision
    assert result.active_slice_hash is None
    assert authority_port.calls == []
    assert host_registry.resolutions == []
    assert evidence_port.calls == []


def test_partially_committed_saga_projects_stored_truth_without_external_replay(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_delta_for_slice,
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
    first_slice = _slice_for_hash(transaction, first_hash)
    stored = reconciliation.reserve_slice_admission(
        stored.definition.saga_id,
        first_hash,
        expected_revision=stored.saga_revision,
        reserved_at="2026-08-31T12:43:00Z",
    )
    authority = build_authority_for_slice(transaction, first_slice)
    stored = reconciliation.confirm_slice_admitted(
        stored.definition.saga_id,
        authority,
        expected_revision=stored.saga_revision,
    )
    delta = build_delta_for_slice(
        first_slice,
        authority,
        aspect=CanonicalAspect.GEOMETRY,
    )
    stored = reconciliation.record_host_commit(
        stored.definition.saga_id,
        delta,
        expected_revision=stored.saga_revision,
        committed_at="2026-08-31T12:44:00Z",
    )
    stored = reconciliation.begin_reconciliation(
        stored.definition.saga_id,
        first_hash,
        expected_revision=stored.saga_revision,
    )
    scope_result = reconciliation.compare_scope(
        ScopeComparisonRequest(
            admitted_execution_authority=authority,
            actual_delta=delta,
            approval_scope_boundary=transaction.approval_scope_boundary,
            execution_slice=first_slice,
        )
    )
    stored = reconciliation.record_scope_result(
        stored.definition.saga_id,
        scope_result,
        expected_revision=stored.saga_revision,
    )

    coordinator, authority_port, host_registry, evidence_port = _build_coordinator(
        reconciliation
    )
    result = coordinator.execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert result.status is CoordinationStatus.PARTIALLY_COMMITTED
    assert result.saga_revision == stored.saga_revision
    assert result.active_slice_hash is None
    assert authority_port.calls == []
    assert host_registry.resolutions == []
    assert evidence_port.calls == []


def test_unknown_commit_requires_recovery_and_restart_never_replays_host(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_delta_for_slice,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    reconciliation = ExecutionReconciliationService(
        store=InMemoryExecutionSagaStore()
    )
    stored, ordered = _ordered_slices(reconciliation, transaction)
    first, second, third = ordered
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
                committed_at="2026-08-31T12:02:00Z",
            )
        }
    )
    second_host = RecordingHostPort(
        {
            second.execution_slice_hash: HostFailed(
                phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
                failure_ref="HOST-ACK-LOST-STEP37",
                failed_at="2026-08-31T12:03:00Z",
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
    coordinator = _recording_coordinator(
        reconciliation,
        authority_port,
        registry,
        evidence_port,
    )

    result = coordinator.execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    final = reconciliation.get_saga(stored.definition.saga_id)
    assert final is not None
    assert final.status is ExecutionSagaStatus.EXECUTING
    assert result.status is CoordinationStatus.RECOVERY_REQUIRED
    assert result.active_slice_hash == second.execution_slice_hash
    assert result.failure_ref == "HOST-ACK-LOST-STEP37"
    assert final.slice_states[0].status is SliceReconciliationStatus.SUCCEEDED
    assert final.slice_states[1].status is SliceReconciliationStatus.ADMITTED
    assert final.slice_states[1].actual_delta_hash is None
    assert final.slice_states[2].status is SliceReconciliationStatus.NOT_STARTED
    assert authority_port.calls == [
        first.execution_slice_hash,
        second.execution_slice_hash,
    ]
    assert first_host.calls == [first.execution_slice_hash]
    assert second_host.calls == [second.execution_slice_hash]
    assert third.host_runtime_ref not in registry.resolutions

    restarted = coordinator.execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert restarted.status is CoordinationStatus.RECOVERY_REQUIRED
    assert restarted.active_slice_hash == second.execution_slice_hash
    assert authority_port.calls == [
        first.execution_slice_hash,
        second.execution_slice_hash,
    ]
    assert second_host.calls == [second.execution_slice_hash]
    assert third.host_runtime_ref not in registry.resolutions


def test_post_host_cas_conflict_stops_without_replaying_mutation(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_delta_for_slice,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    reconciliation = ExecutionReconciliationService(
        store=InMemoryExecutionSagaStore()
    )
    stored, ordered = _ordered_slices(reconciliation, transaction)
    first = ordered[0]
    authority = build_authority_for_slice(transaction, first)
    delta = build_delta_for_slice(first, authority)
    authority_port = RecordingAuthorityPort({first.execution_slice_hash: authority})
    first_host = RecordingHostPort(
        {
            first.execution_slice_hash: HostCommitted(
                actual_delta=delta,
                committed_at="2026-08-31T12:05:00Z",
            )
        }
    )
    registry = RecordingHostRegistry({first.host_runtime_ref: first_host})
    evidence_port = RecordingEvidencePort(build_verification_bundle)
    conflict_service = ConflictOnRecordHostCommit(reconciliation)
    conflicted = _recording_coordinator(
        conflict_service,
        authority_port,
        registry,
        evidence_port,
    )

    with pytest.raises(ReconciliationError) as excinfo:
        conflicted.execute(
            transaction.canonical_changeset,
            transaction.approval_scope_boundary,
            transaction.execution_plan,
        )
    assert excinfo.value.code == "SAGA_CONFLICT"
    assert conflict_service.conflicts == 1
    assert first_host.calls == [first.execution_slice_hash]

    after_conflict = reconciliation.get_saga(stored.definition.saga_id)
    assert after_conflict is not None
    assert after_conflict.status is ExecutionSagaStatus.EXECUTING
    assert after_conflict.slice_states[0].status is SliceReconciliationStatus.ADMITTED
    assert after_conflict.slice_states[0].actual_delta_hash is None

    restarted = _recording_coordinator(
        reconciliation,
        authority_port,
        registry,
        evidence_port,
    ).execute(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )

    assert restarted.status is CoordinationStatus.RECOVERY_REQUIRED
    assert restarted.active_slice_hash == first.execution_slice_hash
    assert authority_port.calls == [first.execution_slice_hash]
    assert first_host.calls == [first.execution_slice_hash]
    assert registry.resolutions == [first.host_runtime_ref]
    assert evidence_port.calls == []
