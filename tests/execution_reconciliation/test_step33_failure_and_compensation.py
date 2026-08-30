"""Task10 RED: partial failures, atomic blocking, and governed compensation."""

from __future__ import annotations

from dataclasses import fields, replace

import design_execution_reconciliation as reconciliation
import pytest
from design_gateway_authorization import AdmittedExecutionAuthority


def _definition(transaction):
    return reconciliation.ExecutionSagaBuilder().build(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )


def _slice(transaction, slice_hash):
    return next(
        item
        for item in transaction.execution_plan.execution_slices
        if item.execution_slice_hash == slice_hash
    )


def _state(stored, slice_hash):
    return next(
        item
        for item in stored.slice_states
        if item.execution_slice_hash == slice_hash
    )


def _assignment(definition, slice_hash):
    return next(
        item.validation_task_ids
        for item in definition.slice_validation_assignments
        if item.execution_slice_hash == slice_hash
    )


def _authority(transaction, slice_hash, marker="1"):
    execution_slice = _slice(transaction, slice_hash)
    return AdmittedExecutionAuthority(
        approval_hash=marker * 64,
        grant_hash=("a" if marker != "a" else "b") * 64,
        changeset_hash=transaction.canonical_changeset.changeset_hash,
        approved_scope_hash=transaction.approval_scope_boundary.scope_hash,
        execution_slice_hash=slice_hash,
        binding_set_hash=("c" if marker != "c" else "d") * 64,
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
        admitted_at="2026-08-30T10:05:00Z",
    )


def _delta(transaction, authority, marker="1"):
    execution_slice = _slice(transaction, authority.execution_slice_hash)
    draft = reconciliation.ActualDelta(
        actual_delta_id=f"AD-TASK10-{marker}",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=authority.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=20,
        revision_after=21,
        changes=(),
        actual_delta_hash="0" * 64,
    )
    return replace(
        draft,
        actual_delta_hash=reconciliation.compute_actual_delta_hash(draft),
    )


def _scope(transaction, slice_hash, delta_hash, status):
    violations = ()
    if status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH:
        violations = (
            reconciliation.ScopeViolation(
                code="TASK10_SCOPE_BREACH",
                actual_change_hash="f" * 64,
            ),
        )
    draft = reconciliation.ScopeComparisonResult(
        status=status,
        actual_delta_hash=delta_hash,
        approved_scope_hash=transaction.approval_scope_boundary.scope_hash,
        execution_slice_hash=slice_hash,
        matched_changes=(),
        violations=violations,
        comparison_hash="0" * 64,
    )
    return replace(
        draft,
        comparison_hash=reconciliation.compute_scope_comparison_hash(draft),
    )


def _verification(transaction, definition, slice_hash, delta_hash, status):
    task_results = []
    for task_id in _assignment(definition, slice_hash):
        draft = reconciliation.ValidationTaskResult(
            validation_task_id=task_id,
            status=status,
            observations=("task10 deterministic outcome",),
            failure_codes=() if status is reconciliation.VerificationStatus.PASSED else ("TASK10_VERIFY",),
            task_result_hash="0" * 64,
        )
        task_results.append(
            replace(
                draft,
                task_result_hash=reconciliation.compute_validation_task_result_hash(draft),
            )
        )
    draft_result = reconciliation.SemanticVerificationResult(
        verification_id=f"VR-TASK10-{status.value}",
        changeset_hash=transaction.canonical_changeset.changeset_hash,
        execution_slice_hash=slice_hash,
        actual_delta_hash=delta_hash,
        evidence_bundle_hash="e" * 64,
        task_results=tuple(task_results),
        status=status,
        verification_hash="0" * 64,
    )
    return replace(
        draft_result,
        verification_hash=reconciliation.compute_semantic_verification_hash(draft_result),
    )


def _reserve(store, stored, slice_hash, when="2026-08-30T10:00:00Z"):
    return store.reserve_slice_admission(
        stored.definition.saga_id,
        slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at=when,
    )


def _admit(store, stored, transaction, slice_hash, marker="1"):
    authority = _authority(transaction, slice_hash, marker)
    return (
        store.confirm_slice_admitted(
            stored.definition.saga_id,
            authority,
            expected_revision=stored.saga_revision,
        ),
        authority,
    )


def _to_reconciling(store, stored, transaction, slice_hash, marker="1"):
    if _state(stored, slice_hash).status is reconciliation.SliceReconciliationStatus.NOT_STARTED:
        stored = _reserve(store, stored, slice_hash)
    stored, authority = _admit(store, stored, transaction, slice_hash, marker)
    delta = _delta(transaction, authority, marker)
    stored = store.record_host_commit(
        stored.definition.saga_id,
        delta,
        expected_revision=stored.saga_revision,
        committed_at="2026-08-30T10:10:00Z",
    )
    stored = store.begin_reconciliation(
        stored.definition.saga_id,
        slice_hash,
        expected_revision=stored.saga_revision,
    )
    return stored, delta


def _succeed(store, stored, transaction, slice_hash, marker="1"):
    stored, delta = _to_reconciling(store, stored, transaction, slice_hash, marker)
    scope = _scope(
        transaction,
        slice_hash,
        delta.actual_delta_hash,
        reconciliation.ScopeComparisonStatus.WITHIN_SCOPE,
    )
    stored = store.record_scope_result(
        stored.definition.saga_id,
        scope,
        expected_revision=stored.saga_revision,
    )
    verification = _verification(
        transaction,
        stored.definition,
        slice_hash,
        delta.actual_delta_hash,
        reconciliation.VerificationStatus.PASSED,
    )
    return store.record_verification_result(
        stored.definition.saga_id,
        verification,
        expected_revision=stored.saga_revision,
        reconciled_at="2026-08-30T10:20:00Z",
    )


def _scope_breached_saga(transaction):
    definition = _definition(transaction)
    failed_slice = definition.ordered_slice_hashes[0]
    store = reconciliation.InMemoryExecutionSagaStore()
    stored = store.create_saga(definition)
    stored, delta = _to_reconciling(store, stored, transaction, failed_slice)
    breach = _scope(
        transaction,
        failed_slice,
        delta.actual_delta_hash,
        reconciliation.ScopeComparisonStatus.SCOPE_BREACH,
    )
    stored = store.record_scope_result(
        definition.saga_id,
        breach,
        expected_revision=stored.saga_revision,
    )
    return store, stored, failed_slice, delta, breach


def _proposal(store, stored, failed_slice):
    request = reconciliation.CompensationProposalRequest(
        source_saga_id=stored.definition.saga_id,
        failed_slice_hash=failed_slice,
        desired_recovery_effects=(
            {
                "semantic_id": "WALL-001",
                "canonical_aspect": "PROPERTIES",
                "desired": {"properties.thickness": 300.0},
            },
        ),
    )
    return reconciliation.ExecutionSagaPlanner(store).create_compensation_proposal(request)


def test_first_precommit_failure_is_terminal_failed_and_blocks_remaining(
    step33_two_slice_transaction,
) -> None:
    transaction = step33_two_slice_transaction
    definition = _definition(transaction)
    first, second = definition.ordered_slice_hashes
    store = reconciliation.InMemoryExecutionSagaStore()
    stored = store.create_saga(definition)
    stored = _reserve(store, stored, first)
    stored, _ = _admit(store, stored, transaction, first)

    failed = store.fail_slice_before_commit(
        definition.saga_id,
        first,
        expected_revision=stored.saga_revision,
        failed_at="2026-08-30T10:07:00Z",
    )

    assert failed.status is reconciliation.ExecutionSagaStatus.FAILED
    assert _state(failed, first).status is reconciliation.SliceReconciliationStatus.FAILED_BEFORE_COMMIT
    assert _state(failed, first).actual_delta_hash is None
    assert _state(failed, second).status is reconciliation.SliceReconciliationStatus.BLOCKED
    replay = store.fail_slice_before_commit(
        definition.saga_id,
        first,
        expected_revision=stored.saga_revision,
        failed_at="2026-08-30T10:07:00Z",
    )
    assert replay == failed


def test_later_precommit_failure_after_success_is_partially_committed(
    step33_two_slice_transaction,
) -> None:
    transaction = step33_two_slice_transaction
    definition = _definition(transaction)
    first, second = definition.ordered_slice_hashes
    store = reconciliation.InMemoryExecutionSagaStore()
    stored = store.create_saga(definition)
    stored = _succeed(store, stored, transaction, first)
    stored = _reserve(store, stored, second, "2026-08-30T10:30:00Z")
    stored, _ = _admit(store, stored, transaction, second, "2")

    failed = store.fail_slice_before_commit(
        definition.saga_id,
        second,
        expected_revision=stored.saga_revision,
        failed_at="2026-08-30T10:35:00Z",
    )

    assert failed.status is reconciliation.ExecutionSagaStatus.PARTIALLY_COMMITTED
    assert _state(failed, first).status is reconciliation.SliceReconciliationStatus.SUCCEEDED
    assert _state(failed, first).actual_delta_hash is not None
    assert _state(failed, second).status is reconciliation.SliceReconciliationStatus.FAILED_BEFORE_COMMIT
    assert _state(failed, second).actual_delta_hash is None


def test_scope_breach_after_commit_is_partial_and_atomically_blocks_remaining(
    step33_two_slice_transaction,
) -> None:
    transaction = step33_two_slice_transaction
    store, stored, failed_slice, delta, breach = _scope_breached_saga(transaction)
    remaining = stored.definition.ordered_slice_hashes[1]

    assert stored.status is reconciliation.ExecutionSagaStatus.PARTIALLY_COMMITTED
    failed_state = _state(stored, failed_slice)
    assert failed_state.status is reconciliation.SliceReconciliationStatus.SCOPE_BREACH
    assert failed_state.actual_delta_hash == delta.actual_delta_hash
    assert failed_state.scope_comparison_hash == breach.comparison_hash
    assert _state(stored, remaining).status is reconciliation.SliceReconciliationStatus.BLOCKED

    passed = _verification(
        transaction,
        stored.definition,
        failed_slice,
        delta.actual_delta_hash,
        reconciliation.VerificationStatus.PASSED,
    )
    with pytest.raises(reconciliation.ReconciliationError) as exc:
        store.record_verification_result(
            stored.definition.saga_id,
            passed,
            expected_revision=stored.saga_revision,
            reconciled_at="2026-08-30T10:20:00Z",
        )
    assert exc.value.code == "SAGA_CONFLICT"


@pytest.mark.parametrize(
    "status",
    (
        reconciliation.VerificationStatus.FAILED,
        reconciliation.VerificationStatus.EVIDENCE_INSUFFICIENT,
    ),
)
def test_nonpassing_verification_after_commit_is_partial_and_blocks(
    step33_two_slice_transaction,
    status,
) -> None:
    transaction = step33_two_slice_transaction
    definition = _definition(transaction)
    failed_slice, remaining = definition.ordered_slice_hashes
    store = reconciliation.InMemoryExecutionSagaStore()
    stored = store.create_saga(definition)
    stored, delta = _to_reconciling(store, stored, transaction, failed_slice)
    scope = _scope(
        transaction,
        failed_slice,
        delta.actual_delta_hash,
        reconciliation.ScopeComparisonStatus.WITHIN_SCOPE,
    )
    stored = store.record_scope_result(
        definition.saga_id,
        scope,
        expected_revision=stored.saga_revision,
    )
    verification = _verification(
        transaction,
        definition,
        failed_slice,
        delta.actual_delta_hash,
        status,
    )

    failed = store.record_verification_result(
        definition.saga_id,
        verification,
        expected_revision=stored.saga_revision,
        reconciled_at="2026-08-30T10:20:00Z",
    )

    assert failed.status is reconciliation.ExecutionSagaStatus.PARTIALLY_COMMITTED
    failed_state = _state(failed, failed_slice)
    assert failed_state.status is reconciliation.SliceReconciliationStatus.VERIFY_FAILED
    assert failed_state.verification_hash == verification.verification_hash
    assert _state(failed, remaining).status is reconciliation.SliceReconciliationStatus.BLOCKED


def test_compensation_proposal_is_provider_neutral_and_derived_from_durable_evidence(
    step33_two_slice_transaction,
) -> None:
    store, stored, failed_slice, delta, breach = _scope_breached_saga(
        step33_two_slice_transaction
    )

    proposal = _proposal(store, stored, failed_slice)

    assert {field.name for field in fields(reconciliation.CompensationProposal)} == {
        "compensation_proposal_id",
        "source_saga_id",
        "source_changeset_hash",
        "failed_slice_hash",
        "committed_slice_hashes",
        "actual_delta_refs",
        "verification_failure_refs",
        "scope_breach_refs",
        "desired_recovery_effects",
        "proposal_hash",
    }
    assert proposal.source_saga_id == stored.definition.saga_id
    assert proposal.source_changeset_hash == stored.definition.changeset_hash
    assert proposal.failed_slice_hash == failed_slice
    assert proposal.committed_slice_hashes == (failed_slice,)
    assert proposal.actual_delta_refs == (delta.actual_delta_hash,)
    assert proposal.scope_breach_refs == (breach.comparison_hash,)
    assert proposal.verification_failure_refs == ()
    assert proposal.compensation_proposal_id == f"CP-{proposal.proposal_hash[:12]}"
    assert reconciliation.compute_compensation_proposal_hash(proposal) == proposal.proposal_hash
    assert "grant" not in {field.name for field in fields(reconciliation.CompensationProposal)}
    assert "host" not in {field.name for field in fields(reconciliation.CompensationProposal)}

    with pytest.raises(reconciliation.ReconciliationError) as exc:
        reconciliation.ExecutionSagaPlanner(store).create_compensation_proposal(
            reconciliation.CompensationProposalRequest(
                source_saga_id=stored.definition.saga_id,
                failed_slice_hash=stored.definition.ordered_slice_hashes[1],
                desired_recovery_effects=proposal.desired_recovery_effects,
            )
        )
    assert exc.value.code == "COMPENSATION_CONFLICT"


def test_compensation_success_is_auditable_and_never_relabels_source_saga_succeeded(
    step33_two_slice_transaction,
) -> None:
    store, stored, failed_slice, _delta_value, _breach = _scope_breached_saga(
        step33_two_slice_transaction
    )
    proposal = _proposal(store, stored, failed_slice)

    compensating = store.begin_compensation(
        stored.definition.saga_id,
        proposal,
        expected_revision=stored.saga_revision,
    )
    assert compensating.status is reconciliation.ExecutionSagaStatus.COMPENSATING
    assert compensating.compensation_proposal_hash == proposal.proposal_hash
    assert store.begin_compensation(
        stored.definition.saga_id,
        proposal,
        expected_revision=stored.saga_revision,
    ) == compensating

    ref = reconciliation.CompensationExecutionRef(
        compensation_proposal_hash=proposal.proposal_hash,
        compensating_changeset_hash="7" * 64,
        succeeded=True,
        completed_at="2026-08-30T11:00:00Z",
    )
    compensated = store.record_compensation_result(
        stored.definition.saga_id,
        ref,
        expected_revision=compensating.saga_revision,
    )

    assert compensated.status is reconciliation.ExecutionSagaStatus.COMPENSATED
    assert compensated.status is not reconciliation.ExecutionSagaStatus.SUCCEEDED
    assert compensated.compensating_changeset_hash == ref.compensating_changeset_hash
    assert compensated.compensation_succeeded is True
    assert compensated.compensation_completed_at == ref.completed_at
    assert _state(compensated, failed_slice).status is reconciliation.SliceReconciliationStatus.SCOPE_BREACH
    assert store.record_compensation_result(
        stored.definition.saga_id,
        ref,
        expected_revision=compensating.saga_revision,
    ) == compensated

    with pytest.raises(reconciliation.ReconciliationError) as conflict:
        store.record_compensation_result(
            stored.definition.saga_id,
            replace(ref, compensating_changeset_hash="8" * 64),
            expected_revision=compensating.saga_revision,
        )
    assert conflict.value.code == "COMPENSATION_CONFLICT"


def test_compensation_failure_is_terminal_without_automatic_recovery_loop(
    step33_two_slice_transaction,
) -> None:
    store, stored, failed_slice, _delta_value, _breach = _scope_breached_saga(
        step33_two_slice_transaction
    )
    proposal = _proposal(store, stored, failed_slice)
    compensating = store.begin_compensation(
        stored.definition.saga_id,
        proposal,
        expected_revision=stored.saga_revision,
    )
    ref = reconciliation.CompensationExecutionRef(
        compensation_proposal_hash=proposal.proposal_hash,
        compensating_changeset_hash="6" * 64,
        succeeded=False,
        completed_at="2026-08-30T11:05:00Z",
    )

    failed = store.record_compensation_result(
        stored.definition.saga_id,
        ref,
        expected_revision=compensating.saga_revision,
    )

    assert failed.status is reconciliation.ExecutionSagaStatus.COMPENSATION_FAILED
    assert failed.compensation_succeeded is False
    with pytest.raises(reconciliation.ReconciliationError) as retry:
        store.begin_compensation(
            stored.definition.saga_id,
            replace(proposal, proposal_hash="9" * 64),
            expected_revision=failed.saga_revision,
        )
    assert retry.value.code == "COMPENSATION_CONFLICT"
