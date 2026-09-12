from __future__ import annotations

from dataclasses import replace

from design_approval_scope import CanonicalAspect
from design_changeset import canonical_hash
from design_execution_reconciliation import (
    ActualChange,
    ActualChangeKind,
    ActualDelta,
    ExecutionReconciliationServiceV2,
    ExecutionSagaBuilderV2,
    InMemoryExecutionSagaStoreV2,
    VerificationContractEvidence,
    VerificationEvidenceBundle,
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

from tests.execution_coordination._support import phase_i_readiness_inputs


def phase_i_context():
    return phase_i_readiness_inputs()


def definition():
    ctx = phase_i_context()
    saga_definition = ExecutionSagaBuilderV2().build(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
    )
    return ctx, saga_definition


def signed_delta(ctx, index: int = 0) -> ActualDelta:
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


def signed_bundle(ctx, delta: ActualDelta, index: int = 0) -> VerificationEvidenceBundle:
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


def service() -> ExecutionReconciliationServiceV2:
    return ExecutionReconciliationServiceV2(store=InMemoryExecutionSagaStoreV2())
