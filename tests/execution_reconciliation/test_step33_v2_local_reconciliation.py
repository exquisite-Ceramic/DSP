from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_reconciliation import (
    ReconciliationError,
    ScopeComparisonStatus,
    VerificationStatus,
    compute_actual_delta_hash,
)

from tests.execution_reconciliation._support import (
    phase_i_context,
    service,
    signed_bundle,
    signed_delta,
)

_service = service
_signed_bundle = signed_bundle
_signed_delta = signed_delta


def test_v2_scope_comparison_reuses_provider_neutral_semantics_after_lineage_validation() -> None:
    ctx = phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    delta = signed_delta(ctx)

    result = service().compare_scope(
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
        execution_slice=execution_slice,
        authority=authority,
        actual_delta=delta,
    )

    assert result.status is ScopeComparisonStatus.WITHIN_SCOPE
    assert result.execution_slice_hash == execution_slice.execution_slice_hash
    assert result.actual_delta_hash == delta.actual_delta_hash
    assert result.approved_scope_hash == ctx.case.boundary_v2.scope_hash
    assert len(result.matched_changes) == 1
    assert result.violations == ()


def test_v2_semantic_verification_accepts_exact_wall_thickness_evidence() -> None:
    ctx = phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    delta = signed_delta(ctx)
    bundle = signed_bundle(ctx, delta)

    result = service().verify_semantics(
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
        execution_slice=execution_slice,
        authority=authority,
        actual_delta=delta,
        validation_tasks=ctx.case.changeset.validation_tasks,
        verification_evidence_bundle=bundle,
        verified_at="2026-09-06T12:30:00Z",
    )

    assert result.status is VerificationStatus.PASSED
    assert result.execution_slice_hash == execution_slice.execution_slice_hash
    assert result.actual_delta_hash == delta.actual_delta_hash
    assert tuple(item.status for item in result.task_results) == (
        VerificationStatus.PASSED,
    )


def test_v2_materialization_substitution_fails_before_scope_evaluation() -> None:
    ctx = phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = replace(
        ctx.authorities[0],
        materialization_id=ctx.authorities[1].materialization_id,
    )
    delta = signed_delta(ctx)

    with pytest.raises(ReconciliationError) as exc:
        service().compare_scope(
            canonical_changeset=ctx.case.changeset,
            approval_scope_boundary=ctx.case.boundary_v2,
            execution_slice=execution_slice,
            authority=authority,
            actual_delta=delta,
        )
    assert exc.value.code == "RECONCILIATION_LINEAGE_MISMATCH"


def test_v2_binding_substitution_fails_before_semantic_verification() -> None:
    ctx = phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    original_delta = signed_delta(ctx)
    tampered_delta = replace(original_delta, binding_set_hash="f" * 64)
    delta = replace(
        tampered_delta,
        actual_delta_hash=compute_actual_delta_hash(tampered_delta),
    )
    bundle = signed_bundle(ctx, original_delta)

    with pytest.raises(ReconciliationError) as exc:
        service().verify_semantics(
            canonical_changeset=ctx.case.changeset,
            approval_scope_boundary=ctx.case.boundary_v2,
            execution_slice=execution_slice,
            authority=authority,
            actual_delta=delta,
            validation_tasks=ctx.case.changeset.validation_tasks,
            verification_evidence_bundle=bundle,
            verified_at="2026-09-06T12:30:00Z",
        )
    assert exc.value.code == "RECONCILIATION_LINEAGE_MISMATCH"
