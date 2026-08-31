from design_approval_scope import CanonicalAspect
from design_execution_coordination import (
    CoordinationStatus,
    ExecutionSagaCoordinator,
)
from design_execution_reconciliation import (
    ExecutionReconciliationService,
    InMemoryExecutionSagaStore,
    ScopeComparisonRequest,
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


def _slice_for_hash(transaction, slice_hash):
    return next(
        item
        for item in transaction.execution_plan.execution_slices
        if item.execution_slice_hash == slice_hash
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
