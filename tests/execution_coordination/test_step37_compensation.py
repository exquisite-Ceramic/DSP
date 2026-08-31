import pytest
from design_approval_scope import CanonicalAspect
from design_execution_coordination import (
    AuthorityFailure,
    CoordinationError,
    CoordinationStatus,
    ExecutionSagaCoordinator,
    HostCommitted,
)
from design_execution_reconciliation import (
    CompensationExecutionRef,
    ExecutionReconciliationService,
    ExecutionSagaStatus,
    InMemoryExecutionSagaStore,
    ReconciliationError,
)

_DESIRED_RECOVERY_EFFECTS = (
    {
        "canonical_operation": "semantic.assertions.v1",
        "targets": ["WALL-001"],
        "arguments": {
            "assertions": {"properties.thickness": 300.0},
        },
    },
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
        return "2026-08-31T13:20:00Z"


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


def _drive_second_slice_scope_breach(
    transaction,
    build_authority_for_slice,
    build_delta_for_slice,
    build_verification_bundle,
):
    reconciliation = ExecutionReconciliationService(
        store=InMemoryExecutionSagaStore()
    )
    stored, ordered = _ordered_slices(reconciliation, transaction)
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
                        committed_at="2026-08-31T13:21:00Z",
                    )
                }
            ),
            second.host_runtime_ref: RecordingHostPort(
                {
                    second.execution_slice_hash: HostCommitted(
                        actual_delta=second_delta,
                        committed_at="2026-08-31T13:22:00Z",
                    )
                }
            ),
        }
    )
    evidence_port = RecordingEvidencePort(build_verification_bundle)
    coordinator = _coordinator(
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
    assert result.status is CoordinationStatus.PARTIALLY_COMMITTED
    final = reconciliation.get_saga(stored.definition.saga_id)
    assert final is not None
    assert final.status is ExecutionSagaStatus.PARTIALLY_COMMITTED
    assert third.host_runtime_ref not in registry.resolutions
    return (
        coordinator,
        reconciliation,
        final,
        ordered,
        (first_delta, second_delta),
        authority_port,
        registry,
        evidence_port,
    )


def test_compensation_proposal_uses_only_durable_step33_evidence(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_delta_for_slice,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    (
        coordinator,
        _,
        final,
        ordered,
        deltas,
        authority_port,
        registry,
        evidence_port,
    ) = _drive_second_slice_scope_breach(
        transaction,
        build_authority_for_slice,
        build_delta_for_slice,
        build_verification_bundle,
    )
    first, second, _ = ordered
    first_delta, second_delta = deltas
    calls_before = (
        tuple(authority_port.calls),
        tuple(registry.resolutions),
        tuple(evidence_port.calls),
    )

    proposal = coordinator.create_compensation_proposal(
        source_saga_id=final.definition.saga_id,
        failed_slice_hash=second.execution_slice_hash,
        desired_recovery_effects=_DESIRED_RECOVERY_EFFECTS,
    )

    failed_state = final.slice_states[1]
    assert proposal.source_saga_id == final.definition.saga_id
    assert proposal.source_changeset_hash == transaction.canonical_changeset.changeset_hash
    assert proposal.failed_slice_hash == second.execution_slice_hash
    assert proposal.committed_slice_hashes == (
        first.execution_slice_hash,
        second.execution_slice_hash,
    )
    assert proposal.actual_delta_refs == (
        first_delta.actual_delta_hash,
        second_delta.actual_delta_hash,
    )
    assert proposal.verification_failure_refs == ()
    assert proposal.scope_breach_refs == (failed_state.scope_comparison_hash,)
    assert len(proposal.desired_recovery_effects) == 1
    recovery_effect = proposal.desired_recovery_effects[0]
    assert recovery_effect["canonical_operation"] == "semantic.assertions.v1"
    assert tuple(recovery_effect["targets"]) == ("WALL-001",)
    assert (
        recovery_effect["arguments"]["assertions"]["properties.thickness"]
        == 300.0
    )
    assert calls_before == (
        tuple(authority_port.calls),
        tuple(registry.resolutions),
        tuple(evidence_port.calls),
    )


def test_failed_saga_cannot_fabricate_compensation(
    step37_three_slice_transaction,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    reconciliation = ExecutionReconciliationService(
        store=InMemoryExecutionSagaStore()
    )
    stored, ordered = _ordered_slices(reconciliation, transaction)
    first = ordered[0]
    authority_port = RecordingAuthorityPort(
        {
            first.execution_slice_hash: AuthorityFailure(
                failure_ref="AUTH-FAIL-NO-COMP",
                failed_at="2026-08-31T13:23:00Z",
            )
        }
    )
    registry = RecordingHostRegistry({})
    evidence_port = RecordingEvidencePort(build_verification_bundle)
    coordinator = _coordinator(
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
    assert result.status is CoordinationStatus.FAILED

    with pytest.raises(ReconciliationError) as excinfo:
        coordinator.create_compensation_proposal(
            source_saga_id=stored.definition.saga_id,
            failed_slice_hash=first.execution_slice_hash,
            desired_recovery_effects=_DESIRED_RECOVERY_EFFECTS,
        )
    assert excinfo.value.code == "COMPENSATION_CONFLICT"
    assert registry.resolutions == []
    assert evidence_port.calls == []


def test_compensation_failed_remains_step33_truth_and_is_not_forward_executable(
    step37_three_slice_transaction,
    build_authority_for_slice,
    build_delta_for_slice,
    build_verification_bundle,
):
    transaction = step37_three_slice_transaction
    (
        coordinator,
        reconciliation,
        final,
        ordered,
        _,
        authority_port,
        registry,
        evidence_port,
    ) = _drive_second_slice_scope_breach(
        transaction,
        build_authority_for_slice,
        build_delta_for_slice,
        build_verification_bundle,
    )
    failed_slice = ordered[1]
    proposal = coordinator.create_compensation_proposal(
        source_saga_id=final.definition.saga_id,
        failed_slice_hash=failed_slice.execution_slice_hash,
        desired_recovery_effects=_DESIRED_RECOVERY_EFFECTS,
    )
    stored = reconciliation.begin_compensation(
        final.definition.saga_id,
        proposal,
        expected_revision=final.saga_revision,
    )
    stored = reconciliation.record_compensation_result(
        final.definition.saga_id,
        CompensationExecutionRef(
            compensation_proposal_hash=proposal.proposal_hash,
            compensating_changeset_hash="f" * 64,
            succeeded=False,
            completed_at="2026-08-31T12:30:00Z",
        ),
        expected_revision=stored.saga_revision,
    )
    assert stored.status is ExecutionSagaStatus.COMPENSATION_FAILED

    calls_before = (
        tuple(authority_port.calls),
        tuple(registry.resolutions),
        tuple(evidence_port.calls),
    )
    with pytest.raises(CoordinationError) as excinfo:
        coordinator.execute(
            transaction.canonical_changeset,
            transaction.approval_scope_boundary,
            transaction.execution_plan,
        )
    assert excinfo.value.code == "SAGA_NOT_FORWARD_EXECUTABLE"
    assert calls_before == (
        tuple(authority_port.calls),
        tuple(registry.resolutions),
        tuple(evidence_port.calls),
    )
    assert not hasattr(coordinator, "execute_inverse")
    assert not hasattr(coordinator, "execute_compensation")
