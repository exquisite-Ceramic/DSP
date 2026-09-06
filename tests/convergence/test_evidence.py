from __future__ import annotations

from dataclasses import fields, replace

import pytest
from design_convergence import (
    CanonicalFieldEvidence,
    ConvergenceEvidenceSet,
    ConvergenceVerificationError,
    MaterializationCanonicalEvidence,
    build_convergence_evidence_set,
    build_materialization_canonical_evidence,
    compute_convergence_evidence_set_hash,
    compute_materialization_canonical_evidence_hash,
)
from design_execution_reconciliation import (
    ExecutionReconciliationServiceV2,
    InMemoryExecutionSagaStoreV2,
    compute_semantic_verification_hash,
)

from tests.execution_reconciliation.test_saga_v2_definition import _phase_i_context
from tests.execution_reconciliation.test_step33_v2_local_reconciliation import (
    _signed_bundle,
    _signed_delta,
)


def _local_evidence(index: int = 0) -> tuple[object, MaterializationCanonicalEvidence]:
    ctx = _phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[index]
    authority = ctx.authorities[index]
    delta = _signed_delta(ctx, index)
    bundle = _signed_bundle(ctx, delta, index)
    verification = ExecutionReconciliationServiceV2(
        store=InMemoryExecutionSagaStoreV2()
    ).verify_semantics(
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
        execution_slice=execution_slice,
        authority=authority,
        actual_delta=delta,
        validation_tasks=ctx.case.changeset.validation_tasks,
        verification_evidence_bundle=bundle,
        verified_at=f"2026-09-06T13:0{index}:00Z",
    )
    evidence = build_materialization_canonical_evidence(
        materialization_id=execution_slice.materialization_id,
        execution_slice=execution_slice,
        actual_delta=delta,
        verification_result=verification,
        verification_evidence_bundle=bundle,
        convergence_profile=ctx.case.profile,
    )
    return ctx, evidence


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ConvergenceVerificationError) as exc:
        operation()
    assert exc.value.code == code


def test_materialization_evidence_has_exact_frozen_lineage_fields() -> None:
    assert {field.name for field in fields(MaterializationCanonicalEvidence)} == {
        "materialization_id",
        "semantic_id",
        "execution_slice_hash",
        "actual_delta_hash",
        "verification_hash",
        "semantic_environment_ref",
        "post_execution_projection_ref",
        "canonical_kind",
        "verified_fields",
        "evidence_hash",
    }


def test_convergence_evidence_set_has_exact_frozen_lineage_fields() -> None:
    assert {field.name for field in fields(ConvergenceEvidenceSet)} == {
        "materialization_plan_hash",
        "required_set_hash",
        "convergence_profile_hash",
        "semantic_environment_ref",
        "evidence_items",
        "evidence_set_hash",
    }


def test_verified_wall_projection_builds_one_exact_mm_field() -> None:
    ctx, evidence = _local_evidence(0)
    execution_slice = ctx.execution_plan.execution_slices[0]

    assert evidence.materialization_id == execution_slice.materialization_id
    assert evidence.semantic_id == "WALL-001"
    assert evidence.execution_slice_hash == execution_slice.execution_slice_hash
    assert evidence.canonical_kind == "ifc:IfcWall"
    assert evidence.semantic_environment_ref == ctx.case.changeset.semantic_environment_ref
    assert len(evidence.verified_fields) == 1
    field = evidence.verified_fields[0]
    assert isinstance(field, CanonicalFieldEvidence)
    assert field.path == "properties.dsp:WallThickness"
    assert field.value == 300.0
    assert field.unit == "mm"
    assert evidence.evidence_hash == compute_materialization_canonical_evidence_hash(evidence)


def test_builder_rejects_resigned_substituted_local_verification_lineage() -> None:
    ctx = _phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    delta = _signed_delta(ctx, 0)
    bundle = _signed_bundle(ctx, delta, 0)
    verification = ExecutionReconciliationServiceV2(
        store=InMemoryExecutionSagaStoreV2()
    ).verify_semantics(
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
        execution_slice=execution_slice,
        authority=authority,
        actual_delta=delta,
        validation_tasks=ctx.case.changeset.validation_tasks,
        verification_evidence_bundle=bundle,
        verified_at="2026-09-06T13:00:00Z",
    )

    substituted_draft = replace(
        verification,
        execution_slice_hash="f" * 64,
        verification_hash="0" * 64,
    )
    substituted = replace(
        substituted_draft,
        verification_hash=compute_semantic_verification_hash(substituted_draft),
    )
    _assert_code(
        "CONVERGENCE_EVIDENCE_LINEAGE_MISMATCH",
        lambda: build_materialization_canonical_evidence(
            materialization_id=execution_slice.materialization_id,
            execution_slice=execution_slice,
            actual_delta=delta,
            verification_result=substituted,
            verification_evidence_bundle=bundle,
            convergence_profile=ctx.case.profile,
        ),
    )


def test_evidence_set_binds_plan_required_set_profile_and_environment() -> None:
    ctx, first = _local_evidence(0)
    _, second = _local_evidence(1)

    evidence_set = build_convergence_evidence_set(
        plan=ctx.materialization_plan,
        profile=ctx.case.profile,
        evidence_items=(second, first),
    )

    assert isinstance(evidence_set, ConvergenceEvidenceSet)
    assert evidence_set.materialization_plan_hash == ctx.materialization_plan.materialization_plan_hash
    assert evidence_set.required_set_hash == ctx.materialization_plan.required_set_hash
    assert evidence_set.convergence_profile_hash == ctx.case.profile.profile_hash
    assert evidence_set.semantic_environment_ref == first.semantic_environment_ref
    assert tuple(item.materialization_id for item in evidence_set.evidence_items) == tuple(
        sorted((first.materialization_id, second.materialization_id))
    )
    assert evidence_set.evidence_set_hash == compute_convergence_evidence_set_hash(evidence_set)


def test_evidence_set_rejects_missing_duplicate_or_cross_environment_items() -> None:
    ctx, first = _local_evidence(0)
    _, second = _local_evidence(1)

    _assert_code(
        "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
        lambda: build_convergence_evidence_set(
            plan=ctx.materialization_plan,
            profile=ctx.case.profile,
            evidence_items=(first,),
        ),
    )
    _assert_code(
        "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
        lambda: build_convergence_evidence_set(
            plan=ctx.materialization_plan,
            profile=ctx.case.profile,
            evidence_items=(first, first),
        ),
    )
    changed_environment = replace(
        second.semantic_environment_ref,
        environment_id="ENV-OTHER",
    )
    changed = replace(
        second,
        semantic_environment_ref=changed_environment,
        evidence_hash="0" * 64,
    )
    changed = replace(
        changed,
        evidence_hash=compute_materialization_canonical_evidence_hash(changed),
    )
    _assert_code(
        "CONVERGENCE_EVIDENCE_ENVIRONMENT_MISMATCH",
        lambda: build_convergence_evidence_set(
            plan=ctx.materialization_plan,
            profile=ctx.case.profile,
            evidence_items=(first, changed),
        ),
    )


def test_evidence_set_rejects_semantic_target_substitution() -> None:
    ctx, first = _local_evidence(0)
    _, second = _local_evidence(1)
    changed = replace(
        first,
        semantic_id="WALL-OTHER",
        evidence_hash="0" * 64,
    )
    changed = replace(
        changed,
        evidence_hash=compute_materialization_canonical_evidence_hash(changed),
    )

    _assert_code(
        "CONVERGENCE_EVIDENCE_COVERAGE_MISMATCH",
        lambda: build_convergence_evidence_set(
            plan=ctx.materialization_plan,
            profile=ctx.case.profile,
            evidence_items=(changed, second),
        ),
    )
