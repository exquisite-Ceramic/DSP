from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_reconciliation import (
    ActualDelta,
    ExecutionSagaBuilderV2,
    ExecutionSagaStatusV2,
    InMemoryExecutionSagaStoreV2,
    ReconciliationError,
    SagaConvergenceOutcome,
    ScopeComparisonResult,
    ScopeComparisonStatus,
    SemanticVerificationResult,
    ValidationTaskResult,
    VerificationStatus,
    compute_actual_delta_hash,
    compute_scope_comparison_hash,
    compute_semantic_verification_hash,
    compute_validation_task_result_hash,
)

from tests.execution_reconciliation.test_saga_v2_definition import _phase_i_context


def _created_store():
    ctx = _phase_i_context()
    definition = ExecutionSagaBuilderV2().build(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
    )
    store = InMemoryExecutionSagaStoreV2()
    stored = store.create_saga(definition)
    return ctx, store, stored


def _signed_delta(execution_slice, authority, marker: int) -> ActualDelta:
    draft = ActualDelta(
        actual_delta_id=f"AD-V2-{marker}",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=marker,
        revision_after=marker + 1,
        changes=(),
        actual_delta_hash="0" * 64,
    )
    return replace(draft, actual_delta_hash=compute_actual_delta_hash(draft))


def _signed_scope_result(execution_slice, delta) -> ScopeComparisonResult:
    draft = ScopeComparisonResult(
        status=ScopeComparisonStatus.WITHIN_SCOPE,
        actual_delta_hash=delta.actual_delta_hash,
        approved_scope_hash=delta.approved_scope_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        matched_changes=(),
        violations=(),
        comparison_hash="0" * 64,
    )
    return replace(draft, comparison_hash=compute_scope_comparison_hash(draft))


def _signed_verification_result(stored, execution_slice, delta) -> SemanticVerificationResult:
    assignment = next(
        item
        for item in stored.definition.slice_validation_assignments
        if item.execution_slice_hash == execution_slice.execution_slice_hash
    )
    task_results = []
    for task_id in assignment.validation_task_ids:
        draft_task = ValidationTaskResult(
            validation_task_id=task_id,
            status=VerificationStatus.PASSED,
            observations=(),
            failure_codes=(),
            task_result_hash="0" * 64,
        )
        task_results.append(
            replace(
                draft_task,
                task_result_hash=compute_validation_task_result_hash(draft_task),
            )
        )
    draft = SemanticVerificationResult(
        verification_id="SVR-V2-DRAFT",
        changeset_hash=stored.definition.changeset_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        actual_delta_hash=delta.actual_delta_hash,
        evidence_bundle_hash=("a" if execution_slice.host_runtime_ref.host_type == "autocad" else "b") * 64,
        task_results=tuple(task_results),
        status=VerificationStatus.PASSED,
        verification_hash="0" * 64,
    )
    verification_hash = compute_semantic_verification_hash(draft)
    return replace(
        draft,
        verification_id=f"SVR-{verification_hash[:12]}",
        verification_hash=verification_hash,
    )


def _drive_local_success(ctx, store, stored, index: int):
    execution_slice = ctx.execution_plan.execution_slices[index]
    authority = ctx.authorities[index]
    stored = store.reserve_slice_admission(
        stored.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=stored.saga_revision,
        reserved_at=f"2026-09-06T12:0{index}:00Z",
    )
    stored = store.confirm_slice_admitted(
        stored.definition.saga_id,
        authority,
        expected_revision=stored.saga_revision,
    )
    delta = _signed_delta(execution_slice, authority, index + 1)
    stored = store.record_host_commit(
        stored.definition.saga_id,
        delta,
        expected_revision=stored.saga_revision,
        committed_at=f"2026-09-06T12:1{index}:00Z",
    )
    stored = store.begin_reconciliation(
        stored.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=stored.saga_revision,
    )
    scope_result = _signed_scope_result(execution_slice, delta)
    stored = store.record_scope_result(
        stored.definition.saga_id,
        scope_result,
        expected_revision=stored.saga_revision,
    )
    verification_result = _signed_verification_result(stored, execution_slice, delta)
    stored = store.record_verification_result(
        stored.definition.saga_id,
        verification_result,
        expected_revision=stored.saga_revision,
        reconciled_at=f"2026-09-06T12:2{index}:00Z",
    )
    return stored


def test_all_required_local_success_transitions_to_convergence_pending() -> None:
    ctx, store, stored = _created_store()

    stored = _drive_local_success(ctx, store, stored, 0)
    assert stored.status is ExecutionSagaStatusV2.EXECUTING

    stored = _drive_local_success(ctx, store, stored, 1)
    assert stored.status is ExecutionSagaStatusV2.CONVERGENCE_PENDING


def test_diverged_is_impossible_before_all_required_slices_succeed() -> None:
    ctx, store, stored = _created_store()
    stored = _drive_local_success(ctx, store, stored, 0)

    with pytest.raises(ReconciliationError) as exc:
        store.record_convergence_outcome(
            stored.definition.saga_id,
            SagaConvergenceOutcome.DIVERGED,
            "d" * 64,
            expected_revision=stored.saga_revision,
        )
    assert exc.value.code == "SAGA_CONFLICT"
    assert store.get_saga(stored.definition.saga_id) == stored


def test_converged_outcome_moves_pending_saga_to_succeeded() -> None:
    ctx, store, stored = _created_store()
    stored = _drive_local_success(ctx, store, stored, 0)
    stored = _drive_local_success(ctx, store, stored, 1)

    stored = store.record_convergence_outcome(
        stored.definition.saga_id,
        SagaConvergenceOutcome.CONVERGED,
        "c" * 64,
        expected_revision=stored.saga_revision,
    )

    assert stored.status is ExecutionSagaStatusV2.SUCCEEDED
    assert stored.convergence_outcome is SagaConvergenceOutcome.CONVERGED
    assert stored.convergence_result_hash == "c" * 64


def test_diverged_outcome_moves_pending_saga_to_diverged() -> None:
    ctx, store, stored = _created_store()
    stored = _drive_local_success(ctx, store, stored, 0)
    stored = _drive_local_success(ctx, store, stored, 1)

    stored = store.record_convergence_outcome(
        stored.definition.saga_id,
        SagaConvergenceOutcome.DIVERGED,
        "d" * 64,
        expected_revision=stored.saga_revision,
    )

    assert stored.status is ExecutionSagaStatusV2.DIVERGED
    assert stored.convergence_outcome is SagaConvergenceOutcome.DIVERGED
    assert stored.convergence_result_hash == "d" * 64
