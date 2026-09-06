from __future__ import annotations

from dataclasses import replace

import pytest
from design_approval_scope import CanonicalAspect
from design_changeset import canonical_hash
from design_execution_reconciliation import (
    ActualChange,
    ActualChangeKind,
    ActualDelta,
    ExecutionReconciliationServiceV2,
    InMemoryExecutionSagaStoreV2,
    ReconciliationError,
    ScopeComparisonStatus,
    VerificationContractEvidence,
    VerificationEvidenceBundle,
    VerificationStatus,
    VerificationSubjectEvidence,
    compute_actual_change_hash,
    compute_actual_delta_hash,
    compute_verification_evidence_bundle_hash,
)
from design_orchestrator.canonical_operations import SET_WALL_THICKNESS_V1
from semantic_runtime import (
    Coverage,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotKind,
)

from tests.execution_reconciliation.test_saga_v2_definition import _phase_i_context


def _signed_delta(ctx, index: int = 0) -> ActualDelta:
    execution_slice = ctx.execution_plan.execution_slices[index]
    authority = ctx.authorities[index]
    unit = execution_slice.execution_units[0]
    change_draft = ActualChange(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id="WALL-001",
        canonical_kind="ifc:IfcWall",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
        source_execution_unit_hash=unit.execution_unit_hash,
        actual_change_hash="0" * 64,
    )
    change = replace(
        change_draft,
        actual_change_hash=compute_actual_change_hash(change_draft),
    )
    delta_draft = ActualDelta(
        actual_delta_id=f"AD-V2-{execution_slice.host_runtime_ref.host_type}",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=10,
        revision_after=11,
        changes=(change,),
        actual_delta_hash="0" * 64,
    )
    return replace(
        delta_draft,
        actual_delta_hash=compute_actual_delta_hash(delta_draft),
    )


def _signed_bundle(ctx, delta: ActualDelta, index: int = 0) -> VerificationEvidenceBundle:
    execution_slice = ctx.execution_plan.execution_slices[index]
    environment = SemanticEnvironmentRef(
        ctx.case.changeset.semantic_environment_ref.environment_id,
        ctx.case.changeset.semantic_environment_ref.content_hash,
    )
    marker = execution_slice.host_runtime_ref.host_type
    projection = SemanticProjectionRef(
        projection_id=f"PROJ-V2-{marker}",
        projection_hash=canonical_hash({"v2": "projection", "host": marker}),
        semantic_model_version="ifc43+phase-i",
        provider_set_hash=canonical_hash({"v2": "providers", "host": marker}),
        mapping_profile_set_hash=canonical_hash({"v2": "mappings", "host": marker}),
        normalized_fact_batch_hash=canonical_hash({"v2": "facts", "host": marker}),
    )
    snapshot = SemanticSnapshot(
        snapshot_id=f"PS-V2-{marker}",
        kind=SnapshotKind.PLANNING,
        project_id=ctx.case.changeset.project_id,
        freshness_contract_id=f"FC-V2-{marker}",
        freshness_contract_hash=canonical_hash({"v2": "freshness", "host": marker}),
        document_ref=delta.document_ref,
        base_host_revision=str(delta.revision_after),
        coverage=Coverage(delta.document_ref, ("WALL-001",)),
        projection_ref=projection,
        semantic_environment_ref=environment,
        aspect_guarantees=(),
        hash=canonical_hash({"v2": "snapshot", "delta": delta.actual_delta_hash}),
    )
    subject = VerificationSubjectEvidence(
        semantic_id="WALL-001",
        canonical_kind="ifc:IfcWall",
        properties={"dsp:WallThickness": {"value": 300.0, "unit": "mm"}},
        placement=None,
        geometry_evidence=None,
        relationships=(),
        constraints=(),
        classification=("ifc:IfcWall",),
        evidence_aspects=(CanonicalAspect.PROPERTIES,),
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.hash,
        projection_ref=projection,
    )
    contract = SET_WALL_THICKNESS_V1.verification_contract
    draft = VerificationEvidenceBundle(
        evidence_bundle_id=f"VEB-V2-{marker}",
        changeset_hash=ctx.case.changeset.changeset_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        actual_delta_hash=delta.actual_delta_hash,
        semantic_environment_ref=environment,
        post_execution_snapshot_ref=snapshot,
        post_execution_projection_ref=projection,
        base_host_revision=str(delta.revision_after),
        baseline_snapshot_ref=None,
        baseline_projection_ref=None,
        contract_evidence=(
            VerificationContractEvidence(
                contract_ref=canonical_hash(contract),
                contract_body=contract,
            ),
        ),
        subject_evidence=(subject,),
        baseline_subject_evidence=(),
        evidence_bundle_hash="0" * 64,
    )
    return replace(
        draft,
        evidence_bundle_hash=compute_verification_evidence_bundle_hash(draft),
    )


def _service() -> ExecutionReconciliationServiceV2:
    return ExecutionReconciliationServiceV2(store=InMemoryExecutionSagaStoreV2())


def test_v2_scope_comparison_reuses_provider_neutral_semantics_after_lineage_validation() -> None:
    ctx = _phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    delta = _signed_delta(ctx)

    result = _service().compare_scope(
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
    ctx = _phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    delta = _signed_delta(ctx)
    bundle = _signed_bundle(ctx, delta)

    result = _service().verify_semantics(
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
    ctx = _phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = replace(
        ctx.authorities[0],
        materialization_id=ctx.authorities[1].materialization_id,
    )
    delta = _signed_delta(ctx)

    with pytest.raises(ReconciliationError) as exc:
        _service().compare_scope(
            canonical_changeset=ctx.case.changeset,
            approval_scope_boundary=ctx.case.boundary_v2,
            execution_slice=execution_slice,
            authority=authority,
            actual_delta=delta,
        )
    assert exc.value.code == "RECONCILIATION_LINEAGE_MISMATCH"


def test_v2_binding_substitution_fails_before_semantic_verification() -> None:
    ctx = _phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    original_delta = _signed_delta(ctx)
    tampered_delta = replace(original_delta, binding_set_hash="f" * 64)
    delta = replace(
        tampered_delta,
        actual_delta_hash=compute_actual_delta_hash(tampered_delta),
    )
    bundle = _signed_bundle(ctx, original_delta)

    with pytest.raises(ReconciliationError) as exc:
        _service().verify_semantics(
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
