"""Task9 RED: CAS Saga persistence, sequential admission, and successful reconciliation."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import design_execution_reconciliation as reconciliation
import pytest
from design_gateway_authorization import (
    ApprovalAdmission,
    ApprovalConsumptionRequest,
    ExecutionGrantRequest,
    GatewayAuthorizationService,
    InMemoryGatewayAuthorizationStore,
    compute_admission_fingerprint,
)


def _definition(transaction):
    return reconciliation.ExecutionSagaBuilder().build(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )


def _store():
    return reconciliation.InMemoryExecutionSagaStore()


def _slice(transaction, slice_hash):
    return next(
        item
        for item in transaction.execution_plan.execution_slices
        if item.execution_slice_hash == slice_hash
    )


def _slice_state(stored, slice_hash):
    return next(
        item
        for item in stored.slice_states
        if item.execution_slice_hash == slice_hash
    )


def _assignment(definition, slice_hash):
    return next(
        item
        for item in definition.slice_validation_assignments
        if item.execution_slice_hash == slice_hash
    )


def _manual_authority(transaction, slice_hash, *, marker="1"):
    execution_slice = _slice(transaction, slice_hash)
    return reconciliation.AdmittedExecutionAuthority(
        approval_hash=marker * 64,
        grant_hash=("a" if marker != "a" else "b") * 64,
        changeset_hash=transaction.canonical_changeset.changeset_hash,
        approved_scope_hash=transaction.approval_scope_boundary.scope_hash,
        execution_slice_hash=slice_hash,
        binding_set_hash=("c" if marker != "c" else "d") * 64,
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
        admitted_at="2026-08-30T08:05:00Z",
    )


def _actual_delta(transaction, authority, *, suffix="A"):
    execution_slice = _slice(transaction, authority.execution_slice_hash)
    draft = reconciliation.ActualDelta(
        actual_delta_id=f"AD-TASK9-{suffix}",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=authority.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=10,
        revision_after=11,
        changes=(),
        actual_delta_hash="0" * 64,
    )
    return replace(
        draft,
        actual_delta_hash=reconciliation.compute_actual_delta_hash(draft),
    )


def _within_scope(transaction, slice_hash, actual_delta_hash):
    draft = reconciliation.ScopeComparisonResult(
        status=reconciliation.ScopeComparisonStatus.WITHIN_SCOPE,
        actual_delta_hash=actual_delta_hash,
        approved_scope_hash=transaction.approval_scope_boundary.scope_hash,
        execution_slice_hash=slice_hash,
        matched_changes=(),
        violations=(),
        comparison_hash="0" * 64,
    )
    return replace(
        draft,
        comparison_hash=reconciliation.compute_scope_comparison_hash(draft),
    )


def _verification(
    transaction,
    definition,
    slice_hash,
    actual_delta_hash,
    *,
    task_ids=None,
    status=None,
    suffix="A",
):
    assigned = _assignment(definition, slice_hash).validation_task_ids
    selected = assigned if task_ids is None else tuple(task_ids)
    final_status = status or reconciliation.VerificationStatus.PASSED
    task_results = []
    for task_id in selected:
        draft = reconciliation.ValidationTaskResult(
            validation_task_id=task_id,
            status=final_status,
            observations=("task9 deterministic verification",),
            failure_codes=() if final_status is reconciliation.VerificationStatus.PASSED else ("TASK9_FAIL",),
            task_result_hash="0" * 64,
        )
        task_results.append(
            replace(
                draft,
                task_result_hash=reconciliation.compute_validation_task_result_hash(draft),
            )
        )
    draft_result = reconciliation.SemanticVerificationResult(
        verification_id=f"VR-TASK9-{suffix}",
        changeset_hash=transaction.canonical_changeset.changeset_hash,
        execution_slice_hash=slice_hash,
        actual_delta_hash=actual_delta_hash,
        evidence_bundle_hash="e" * 64,
        task_results=tuple(task_results),
        status=final_status,
        verification_hash="0" * 64,
    )
    return replace(
        draft_result,
        verification_hash=reconciliation.compute_semantic_verification_hash(draft_result),
    )


def _reserve(store, stored, slice_hash, *, reserved_at="2026-08-30T08:00:00Z"):
    return store.reserve_slice_admission(
        stored.definition.saga_id,
        slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at=reserved_at,
    )


def _drive_to_reconciling(store, stored, transaction, slice_hash):
    if _slice_state(stored, slice_hash).status is reconciliation.SliceReconciliationStatus.NOT_STARTED:
        stored = _reserve(store, stored, slice_hash)
    authority = _manual_authority(transaction, slice_hash)
    stored = store.confirm_slice_admitted(
        stored.definition.saga_id,
        authority,
        expected_revision=stored.saga_revision,
    )
    delta = _actual_delta(transaction, authority, suffix=slice_hash[:6])
    stored = store.record_host_commit(
        stored.definition.saga_id,
        delta,
        expected_revision=stored.saga_revision,
        committed_at="2026-08-30T08:10:00Z",
    )
    stored = store.begin_reconciliation(
        stored.definition.saga_id,
        slice_hash,
        expected_revision=stored.saga_revision,
    )
    return stored, delta


def _drive_success(store, stored, transaction, slice_hash):
    stored, delta = _drive_to_reconciling(store, stored, transaction, slice_hash)
    scope = _within_scope(transaction, slice_hash, delta.actual_delta_hash)
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
        suffix=slice_hash[:6],
    )
    stored = store.record_verification_result(
        stored.definition.saga_id,
        verification,
        expected_revision=stored.saga_revision,
        reconciled_at="2026-08-30T08:20:00Z",
    )
    return stored


def test_create_replay_and_initial_state(step33_two_slice_transaction) -> None:
    definition = _definition(step33_two_slice_transaction)
    store = _store()

    created = store.create_saga(definition)

    assert created.definition == definition
    assert created.saga_revision == 0
    assert created.status is reconciliation.ExecutionSagaStatus.READY
    assert tuple(state.sequence_index for state in created.slice_states) == tuple(
        range(len(definition.ordered_slice_hashes))
    )
    assert tuple(state.execution_slice_hash for state in created.slice_states) == (
        definition.ordered_slice_hashes
    )
    assert all(
        state.status is reconciliation.SliceReconciliationStatus.NOT_STARTED
        for state in created.slice_states
    )
    assert store.create_saga(definition) == created
    assert store.get_saga(definition.saga_id) == created

    conflicting = replace(definition, execution_plan_hash="f" * 64)
    with pytest.raises(reconciliation.ReconciliationError) as exc:
        store.create_saga(conflicting)
    assert exc.value.code == "SAGA_CONFLICT"


def test_reservation_is_globally_sequential_cas_and_idempotent(
    step33_two_slice_transaction,
) -> None:
    definition = _definition(step33_two_slice_transaction)
    first, second = definition.ordered_slice_hashes
    store = _store()
    created = store.create_saga(definition)

    with pytest.raises(reconciliation.ReconciliationError) as wrong_order:
        store.reserve_slice_admission(
            definition.saga_id,
            second,
            expected_revision=0,
            reserved_at="2026-08-30T08:00:00Z",
        )
    assert wrong_order.value.code == "SAGA_CONFLICT"

    reserved = _reserve(store, created, first)
    assert reserved.saga_revision == 1
    assert reserved.status is reconciliation.ExecutionSagaStatus.EXECUTING
    assert _slice_state(reserved, first).status is reconciliation.SliceReconciliationStatus.ADMISSION_RESERVED

    replay = store.reserve_slice_admission(
        definition.saga_id,
        first,
        expected_revision=0,
        reserved_at="2026-08-30T08:00:00Z",
    )
    assert replay == reserved

    with pytest.raises(reconciliation.ReconciliationError) as stale:
        store.reserve_slice_admission(
            definition.saga_id,
            first,
            expected_revision=0,
            reserved_at="2026-08-30T08:00:01Z",
        )
    assert stale.value.code == "SAGA_CONFLICT"

    with pytest.raises(reconciliation.ReconciliationError) as active:
        store.reserve_slice_admission(
            definition.saga_id,
            second,
            expected_revision=reserved.saga_revision,
            reserved_at="2026-08-30T08:01:00Z",
        )
    assert active.value.code == "SAGA_CONFLICT"


def test_32_concurrent_reservations_produce_one_logical_reservation(
    step33_two_slice_transaction,
) -> None:
    definition = _definition(step33_two_slice_transaction)
    first = definition.ordered_slice_hashes[0]
    store = _store()
    store.create_saga(definition)

    def reserve_once():
        return store.reserve_slice_admission(
            definition.saga_id,
            first,
            expected_revision=0,
            reserved_at="2026-08-30T08:00:00Z",
        )

    with ThreadPoolExecutor(max_workers=32) as executor:
        results = tuple(executor.map(lambda _: reserve_once(), range(32)))

    assert {item.saga_revision for item in results} == {1}
    assert len({item.slice_states for item in results}) == 1
    stored = store.get_saga(definition.saga_id)
    assert stored is not None
    assert stored.saga_revision == 1
    assert _slice_state(stored, first).status is reconciliation.SliceReconciliationStatus.ADMISSION_RESERVED


def test_dependency_predecessor_must_succeed_before_next_reservation(
    step33_two_slice_transaction,
) -> None:
    transaction = step33_two_slice_transaction
    definition = _definition(transaction)
    first, second = definition.ordered_slice_hashes
    store = _store()
    stored = store.create_saga(definition)

    stored = _drive_success(store, stored, transaction, first)
    assert _slice_state(stored, first).status is reconciliation.SliceReconciliationStatus.SUCCEEDED
    assert stored.status is reconciliation.ExecutionSagaStatus.EXECUTING

    reserved_second = _reserve(
        store,
        stored,
        second,
        reserved_at="2026-08-30T08:30:00Z",
    )
    assert _slice_state(reserved_second, second).status is reconciliation.SliceReconciliationStatus.ADMISSION_RESERVED


def test_step32_admission_retry_recovers_lost_step33_confirmation(
    step33_single_slice_transaction,
    step33_binding_set,
) -> None:
    transaction = step33_single_slice_transaction
    definition = _definition(transaction)
    slice_hash = definition.ordered_slice_hashes[0]
    saga_store = _store()
    saga = saga_store.create_saga(definition)
    reserved = _reserve(saga_store, saga, slice_hash)

    changeset = transaction.canonical_changeset
    boundary = transaction.approval_scope_boundary
    draft = ApprovalAdmission(
        admission_id="ADM-TASK9-RECOVERY",
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        semantic_environment_ref=changeset.semantic_environment_ref,
        approver="user:task9",
        policy_snapshot_hash="9" * 64,
        policy_allowed_operations=tuple(
            sorted(
                {
                    changeset.root_operation.canonical_operation,
                    *(item.canonical_operation for item in changeset.derived_operations),
                }
            )
        ),
        approved_at="2026-08-30T07:00:00Z",
        expires_at="2026-08-30T09:00:00Z",
        admission_fingerprint="0" * 64,
    )
    admission = replace(
        draft,
        admission_fingerprint=compute_admission_fingerprint(draft),
    )
    gateway_store = InMemoryGatewayAuthorizationStore()
    gateway = GatewayAuthorizationService(gateway_store)
    approval = gateway.consume_approval(
        ApprovalConsumptionRequest(
            admission=admission,
            canonical_changeset=changeset,
            approval_scope_boundary=boundary,
            consumed_at="2026-08-30T07:30:00Z",
        )
    )
    execution_slice = _slice(transaction, slice_hash)
    grant = gateway.issue_execution_grant(
        ExecutionGrantRequest(
            approval_id=approval.approval_id,
            execution_slice=execution_slice,
            provider_binding_set=step33_binding_set,
            issued_at="2026-08-30T07:40:00Z",
        )
    )

    first_admission = gateway.admit_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:45:00Z",
    )
    retried_admission = gateway.admit_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:45:00Z",
    )
    assert retried_admission == first_admission
    assert retried_admission.admitted_at == first_admission.admitted_at

    confirmed = saga_store.confirm_slice_admitted(
        definition.saga_id,
        retried_admission,
        expected_revision=reserved.saga_revision,
    )
    recovered = saga_store.confirm_slice_admitted(
        definition.saga_id,
        retried_admission,
        expected_revision=reserved.saga_revision,
    )
    assert recovered == confirmed
    assert _slice_state(confirmed, slice_hash).grant_hash == grant.grant_hash

    with pytest.raises(reconciliation.ReconciliationError) as conflict:
        saga_store.confirm_slice_admitted(
            definition.saga_id,
            replace(retried_admission, host_instance_id="HOST-DIFFERENT"),
            expected_revision=reserved.saga_revision,
        )
    assert conflict.value.code == "SAGA_CONFLICT"


def test_successful_reconciliation_requires_scope_then_complete_task_coverage(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_delta,
) -> None:
    transaction = step33_single_slice_transaction
    definition = _definition(transaction)
    slice_hash = definition.ordered_slice_hashes[0]
    store = _store()
    stored = store.create_saga(definition)
    stored = _reserve(store, stored, slice_hash)
    stored = store.confirm_slice_admitted(
        definition.saga_id,
        step33_admitted_authority,
        expected_revision=stored.saga_revision,
    )
    delta = step33_signed_actual_delta()
    stored = store.record_host_commit(
        definition.saga_id,
        delta,
        expected_revision=stored.saga_revision,
        committed_at="2026-08-30T08:10:00Z",
    )
    assert _slice_state(stored, slice_hash).status is reconciliation.SliceReconciliationStatus.HOST_COMMITTED
    stored = store.begin_reconciliation(
        definition.saga_id,
        slice_hash,
        expected_revision=stored.saga_revision,
    )
    assert _slice_state(stored, slice_hash).status is reconciliation.SliceReconciliationStatus.RECONCILING

    verification = _verification(
        transaction,
        definition,
        slice_hash,
        delta.actual_delta_hash,
    )
    with pytest.raises(reconciliation.ReconciliationError) as no_scope:
        store.record_verification_result(
            definition.saga_id,
            verification,
            expected_revision=stored.saga_revision,
            reconciled_at="2026-08-30T08:20:00Z",
        )
    assert no_scope.value.code == "SAGA_CONFLICT"

    scope = _within_scope(transaction, slice_hash, delta.actual_delta_hash)
    stored = store.record_scope_result(
        definition.saga_id,
        scope,
        expected_revision=stored.saga_revision,
    )

    missing = _verification(
        transaction,
        definition,
        slice_hash,
        delta.actual_delta_hash,
        task_ids=(),
        suffix="MISSING",
    )
    with pytest.raises(reconciliation.ReconciliationError) as omitted:
        store.record_verification_result(
            definition.saga_id,
            missing,
            expected_revision=stored.saga_revision,
            reconciled_at="2026-08-30T08:20:00Z",
        )
    assert omitted.value.code == "SAGA_INTEGRITY_INVALID"

    mismatched_delta = replace(
        verification,
        actual_delta_hash="f" * 64,
        verification_hash="0" * 64,
    )
    mismatched_delta = replace(
        mismatched_delta,
        verification_hash=reconciliation.compute_semantic_verification_hash(mismatched_delta),
    )
    with pytest.raises(reconciliation.ReconciliationError) as mismatch:
        store.record_verification_result(
            definition.saga_id,
            mismatched_delta,
            expected_revision=stored.saga_revision,
            reconciled_at="2026-08-30T08:20:00Z",
        )
    assert mismatch.value.code == "SAGA_INTEGRITY_INVALID"

    failed = _verification(
        transaction,
        definition,
        slice_hash,
        delta.actual_delta_hash,
        status=reconciliation.VerificationStatus.FAILED,
        suffix="FAILED",
    )
    with pytest.raises(reconciliation.ReconciliationError):
        store.record_verification_result(
            definition.saga_id,
            failed,
            expected_revision=stored.saga_revision,
            reconciled_at="2026-08-30T08:20:00Z",
        )
    assert store.get_saga(definition.saga_id).status is not reconciliation.ExecutionSagaStatus.SUCCEEDED

    succeeded = store.record_verification_result(
        definition.saga_id,
        verification,
        expected_revision=stored.saga_revision,
        reconciled_at="2026-08-30T08:20:00Z",
    )
    state = _slice_state(succeeded, slice_hash)
    assert state.status is reconciliation.SliceReconciliationStatus.SUCCEEDED
    assert state.actual_delta_hash == delta.actual_delta_hash
    assert state.scope_comparison_hash == scope.comparison_hash
    assert state.verification_hash == verification.verification_hash
    assert state.reconciled_at == "2026-08-30T08:20:00Z"
    assert succeeded.status is reconciliation.ExecutionSagaStatus.SUCCEEDED


def test_verification_cannot_use_task_assigned_to_another_slice(
    step33_two_slice_transaction,
) -> None:
    transaction = step33_two_slice_transaction
    definition = _definition(transaction)
    nonempty = tuple(
        assignment
        for assignment in definition.slice_validation_assignments
        if assignment.validation_task_ids
    )
    assert len(nonempty) >= 2
    target_assignment, other_assignment = nonempty[:2]
    target_slice = target_assignment.execution_slice_hash
    store = _store()
    stored = store.create_saga(definition)
    stored, delta = _drive_to_reconciling(store, stored, transaction, target_slice)
    scope = _within_scope(transaction, target_slice, delta.actual_delta_hash)
    stored = store.record_scope_result(
        definition.saga_id,
        scope,
        expected_revision=stored.saga_revision,
    )
    wrong = _verification(
        transaction,
        definition,
        target_slice,
        delta.actual_delta_hash,
        task_ids=(other_assignment.validation_task_ids[0],),
        suffix="OTHER-SLICE",
    )

    with pytest.raises(reconciliation.ReconciliationError) as exc:
        store.record_verification_result(
            definition.saga_id,
            wrong,
            expected_revision=stored.saga_revision,
            reconciled_at="2026-08-30T08:20:00Z",
        )
    assert exc.value.code == "SAGA_INTEGRITY_INVALID"
