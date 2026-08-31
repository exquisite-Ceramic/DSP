from design_execution_coordination import (
    CoordinationStatus,
    ExecutionSagaCoordinator,
)
from design_execution_reconciliation import (
    ExecutionReconciliationService,
    InMemoryExecutionSagaStore,
)


class NoCallAuthorityPort:
    def __init__(self):
        self.calls = []

    def admit(self, execution_slice):
        self.calls.append(execution_slice.execution_slice_hash)
        raise AssertionError("active-Slice guard must not call authority port")


class NoCallHostRegistry:
    def __init__(self):
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        raise AssertionError("active-Slice guard must not resolve a Host")


class NoCallEvidencePort:
    def __init__(self):
        self.calls = []

    def build_bundle(self, **kwargs):
        self.calls.append(kwargs)
        raise AssertionError("active-Slice guard must not request evidence")


class FixedClock:
    def now(self):
        return "2026-08-31T12:40:00Z"


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
    first_slice = next(
        item
        for item in transaction.execution_plan.execution_slices
        if item.execution_slice_hash == first_hash
    )
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
