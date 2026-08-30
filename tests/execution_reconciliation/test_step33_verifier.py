"""Task7 RED tests for deterministic snapshot-bound semantic verification."""

from __future__ import annotations

from dataclasses import replace

import design_execution_reconciliation as reconciliation
import pytest
from design_approval_scope import (
    ApprovalScopeDefinition,
    CanonicalAspect,
    bind_changeset,
)
from design_changeset import (
    ValidationTask,
    ValidationTaskKind,
    canonical_hash,
    compute_changeset_hash,
    compute_operation_semantic_hash,
    compute_scope_rule_fingerprint,
)
from semantic_runtime import (
    Coverage,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotKind,
)


def _contract(*assertions, contract_type: str = "SEMANTIC_ASSERTIONS_V1") -> dict:
    body = {"type": contract_type}
    if contract_type == "SEMANTIC_ASSERTIONS_V1":
        body["version"] = "1.0.0"
        body["assertions"] = list(assertions)
    return body


def _verification_task(changeset, contract_body: dict) -> ValidationTask:
    root = changeset.root_operation
    operation_ref = f"{root.canonical_operation}@{root.canonical_operation_version}"
    contract_ref = canonical_hash(contract_body)
    semantic = {
        "kind": ValidationTaskKind.CANONICAL_OPERATION.value,
        "subject_semantic_ids": list(root.targets),
        "canonical_operation_ref": operation_ref,
        "contract_ref": contract_ref,
    }
    task_hash = canonical_hash(semantic)
    return ValidationTask(
        validation_task_id=f"VT-{task_hash[:12]}",
        kind=ValidationTaskKind.CANONICAL_OPERATION,
        subject_semantic_ids=root.targets,
        canonical_operation_ref=operation_ref,
        contract_ref=contract_ref,
    )


def _rebound_changeset_and_boundary(transaction, contract_body: dict, *, arguments=None):
    original = transaction.canonical_changeset
    old_boundary = transaction.approval_scope_boundary
    root = original.root_operation
    if arguments is not None:
        root = replace(root, arguments=arguments)
    rules = {rule.rule_id: rule for rule in old_boundary.existing_entity_rules}
    root_hash = compute_operation_semantic_hash(
        origin=root.origin,
        canonical_operation=root.canonical_operation,
        canonical_operation_version=root.canonical_operation_version,
        canonical_definition_fingerprint=root.canonical_definition_fingerprint,
        targets=root.targets,
        arguments=root.arguments,
        expected_effects=root.expected_effects,
        scope_rule_fingerprints=tuple(
            sorted(compute_scope_rule_fingerprint(rules[rule_id]) for rule_id in root.scope_rule_ids)
        ),
        source_evidence=root.source_evidence,
    )
    root = replace(root, operation_id=f"COP-{root_hash[:12]}")
    draft = replace(original, root_operation=root)
    task = _verification_task(draft, contract_body)
    semantic_body = {
        "task_id": draft.task_id,
        "project_id": draft.project_id,
        "planning_snapshot_ref": draft.planning_snapshot_ref,
        "snapshot_set_ref": draft.snapshot_set_ref,
        "semantic_environment_ref": draft.semantic_environment_ref,
        "impact_analysis_fingerprint": draft.impact_analysis_fingerprint,
        "bound_operation_fingerprint": draft.bound_operation_fingerprint,
        "scope_body_hash": old_boundary.scope_body_hash,
        "root_operation": root_hash,
        "derived_operations": [],
        "change_dependencies": [],
        "preconditions": draft.preconditions,
        "affected_entities": list(draft.affected_entities),
        "semantic_impacts": draft.semantic_impacts,
        "validation_tasks": [
            {
                "kind": task.kind.value,
                "subject_semantic_ids": list(task.subject_semantic_ids),
                "canonical_operation_ref": task.canonical_operation_ref,
                "dependency_ref": task.dependency_ref,
                "contract_ref": task.contract_ref,
            }
        ],
    }
    changeset_hash = compute_changeset_hash(semantic_body)
    changeset = replace(
        draft,
        changeset_id=f"CS-{changeset_hash[:12]}",
        validation_tasks=(task,),
        changeset_hash=changeset_hash,
    )
    definition = ApprovalScopeDefinition(
        scope_definition_id=old_boundary.scope_definition_id,
        impact_analysis_fingerprint=old_boundary.impact_analysis_fingerprint,
        canonical_effect_evidence=old_boundary.canonical_effect_evidence,
        intent_boundary=old_boundary.intent_boundary,
        planning_snapshot_ref=old_boundary.planning_snapshot_ref,
        snapshot_set_ref=old_boundary.snapshot_set_ref,
        semantic_environment_ref=old_boundary.semantic_environment_ref,
        existing_entity_rules=old_boundary.existing_entity_rules,
        creation_rules=old_boundary.creation_rules,
        deletion_rules=old_boundary.deletion_rules,
        propagation_bundle_ids=old_boundary.propagation_bundle_ids,
        execution_slice_scope_rules=old_boundary.execution_slice_scopes,
        scope_body_hash=old_boundary.scope_body_hash,
    )
    boundary = bind_changeset(definition, changeset_hash, old_boundary.scope_id)
    return changeset, boundary


def _projection(label: str) -> SemanticProjectionRef:
    return SemanticProjectionRef(
        projection_id=f"PROJ-{label}",
        projection_hash=canonical_hash({"projection": label}),
        semantic_model_version="ifc43+metro-v32",
        provider_set_hash=canonical_hash({"providers": label}),
        mapping_profile_set_hash=canonical_hash({"mappings": label}),
        normalized_fact_batch_hash=canonical_hash({"facts": label}),
    )


def _subject(snapshot, projection, *, thickness=0.3, x=15.0):
    return reconciliation.VerificationSubjectEvidence(
        semantic_id="WALL-001",
        canonical_kind="ifc:IfcWall",
        properties={"thickness": thickness},
        placement={"x": x},
        geometry_evidence=None,
        relationships=({"type": "HOSTED_BY", "target": "STOREY-001"},),
        constraints=(),
        classification=("ifc:IfcWall", "metro:Wall"),
        evidence_aspects=(
            CanonicalAspect.CLASSIFICATION,
            CanonicalAspect.PLACEMENT,
            CanonicalAspect.PROPERTIES,
            CanonicalAspect.RELATIONSHIPS,
        ),
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.hash,
        projection_ref=projection,
    )


def _signed_bundle(changeset, authority, delta, contract_body, *, subject=None):
    environment = SemanticEnvironmentRef(
        changeset.semantic_environment_ref.environment_id,
        changeset.semantic_environment_ref.content_hash,
    )
    projection = _projection("POST")
    snapshot = SemanticSnapshot(
        snapshot_id="PS-STEP33-POST",
        kind=SnapshotKind.PLANNING,
        project_id=changeset.project_id,
        freshness_contract_id="FC-STEP33-POST",
        freshness_contract_hash=canonical_hash({"freshness": "post"}),
        document_ref=delta.document_ref,
        base_host_revision=str(delta.revision_after),
        coverage=Coverage(delta.document_ref, ("WALL-001",)),
        projection_ref=projection,
        semantic_environment_ref=environment,
        aspect_guarantees=(),
        hash=canonical_hash({"snapshot": "step33-post"}),
    )
    evidence = subject or _subject(snapshot, projection)
    draft = reconciliation.VerificationEvidenceBundle(
        evidence_bundle_id="VEB-STEP33-VERIFIER",
        changeset_hash=changeset.changeset_hash,
        execution_slice_hash=authority.execution_slice_hash,
        actual_delta_hash=delta.actual_delta_hash,
        semantic_environment_ref=environment,
        post_execution_snapshot_ref=snapshot,
        post_execution_projection_ref=projection,
        base_host_revision=str(delta.revision_after),
        baseline_snapshot_ref=None,
        baseline_projection_ref=None,
        contract_evidence=(
            reconciliation.VerificationContractEvidence(
                canonical_hash(contract_body),
                contract_body,
            ),
        ),
        subject_evidence=(evidence,),
        baseline_subject_evidence=(),
        evidence_bundle_hash="0" * 64,
    )
    return replace(
        draft,
        evidence_bundle_hash=reconciliation.compute_verification_evidence_bundle_hash(draft),
    )


def _request(
    transaction,
    authority,
    signed_change,
    signed_delta,
    contract_body,
    *,
    arguments=None,
    subject=None,
    validation_tasks=None,
    bundle_mutator=None,
    delta_mutator=None,
):
    changeset, boundary = _rebound_changeset_and_boundary(
        transaction,
        contract_body,
        arguments=arguments,
    )
    authority = replace(
        authority,
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
    )
    change = signed_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        canonical_kind="ifc:IfcWall",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    delta = signed_delta(
        change,
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=authority.execution_slice_hash,
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref="DOC-1",
        revision_before=10,
        revision_after=11,
    )
    if delta_mutator is not None:
        delta = delta_mutator(delta)
    bundle = _signed_bundle(changeset, authority, delta, contract_body, subject=subject)
    if bundle_mutator is not None:
        bundle = bundle_mutator(bundle)
    tasks = changeset.validation_tasks if validation_tasks is None else validation_tasks(changeset)
    request = reconciliation.SemanticVerificationRequest(
        admitted_execution_authority=authority,
        approval_scope_boundary=boundary,
        canonical_changeset=changeset,
        actual_delta=delta,
        validation_tasks=tasks,
        verification_evidence_bundle=bundle,
        verified_at="2026-08-30T14:30:00Z",
    )
    return request


def _verify(request):
    return reconciliation.SemanticVerifier().verify(request)


def test_supported_provider_neutral_operator_vocabulary_passes(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {"subjects": {"from_argument": "targets"}, "path": "properties.thickness", "operator": "EXISTS"},
        {"subjects": {"from_argument": "targets"}, "path": "properties.absent", "operator": "NOT_EXISTS"},
        {"subjects": {"from_argument": "targets"}, "path": "properties.thickness", "operator": "EQUALS_LITERAL", "value": 0.3},
        {"subjects": {"from_argument": "targets"}, "path": "properties.thickness", "operator": "EQUALS_ARGUMENT", "argument": "thickness"},
        {"subjects": {"from_argument": "targets"}, "operator": "RELATIONSHIP_EXISTS", "relationship": {"type": "HOSTED_BY", "target": "STOREY-001"}},
        {"subjects": {"from_argument": "targets"}, "operator": "CLASSIFICATION_IS", "value": "ifc:IfcWall"},
    )
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        arguments={"targets": ["WALL-001"], "thickness": 0.3},
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.PASSED
    assert len(result.task_results) == 1
    assert result.task_results[0].status is reconciliation.VerificationStatus.PASSED
    assert result.task_results[0].failure_codes == ()


def test_wrong_value_is_failed_not_scope_breach(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {"subjects": {"from_argument": "targets"}, "path": "properties.thickness", "operator": "EQUALS_LITERAL", "value": 0.4}
    )
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.FAILED
    assert result.task_results[0].failure_codes == ("EXPECTED_VALUE_MISMATCH",)


def test_missing_required_path_is_evidence_insufficient(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {"subjects": {"from_argument": "targets"}, "path": "properties.height", "operator": "EXISTS"}
    )
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.EVIDENCE_INSUFFICIENT
    assert result.task_results[0].failure_codes == ("REQUIRED_FIELD_MISSING",)


def test_unsupported_contract_cannot_pass(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(contract_type="HOST_READ_BACK")
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
    )

    result = _verify(request)

    assert result.status is reconciliation.VerificationStatus.EVIDENCE_INSUFFICIENT
    assert result.task_results[0].failure_codes == ("VERIFY_CONTRACT_UNSUPPORTED",)


def test_invented_or_mutated_validation_task_is_rejected(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {"subjects": {"from_argument": "targets"}, "path": "properties.thickness", "operator": "EXISTS"}
    )
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        validation_tasks=lambda changeset: (
            replace(changeset.validation_tasks[0], subject_semantic_ids=("WALL-OTHER",)),
        ),
    )

    with pytest.raises(reconciliation.ReconciliationError) as exc_info:
        _verify(request)

    assert exc_info.value.code == "VERIFY_INPUT_INVALID"


def test_actual_delta_intrinsic_failure_precedes_lineage_failure(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {"subjects": {"from_argument": "targets"}, "path": "properties.thickness", "operator": "EXISTS"}
    )
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        delta_mutator=lambda delta: replace(
            delta,
            grant_hash="f" * 64,
            actual_delta_hash="e" * 64,
        ),
    )

    with pytest.raises(reconciliation.ReconciliationError) as exc_info:
        _verify(request)

    assert exc_info.value.code == "ACTUAL_DELTA_INTEGRITY_INVALID"


def test_authority_actual_delta_lineage_mismatch_is_rejected(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {"subjects": {"from_argument": "targets"}, "path": "properties.thickness", "operator": "EXISTS"}
    )

    def different_grant(delta):
        draft = replace(delta, grant_hash="f" * 64, actual_delta_hash="0" * 64)
        return replace(
            draft,
            actual_delta_hash=reconciliation.compute_actual_delta_hash(draft),
        )

    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        delta_mutator=different_grant,
    )

    with pytest.raises(reconciliation.ReconciliationError) as exc_info:
        _verify(request)

    assert exc_info.value.code == "RECONCILIATION_LINEAGE_MISMATCH"


def test_bundle_exact_hash_joins_are_required(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {"subjects": {"from_argument": "targets"}, "path": "properties.thickness", "operator": "EXISTS"}
    )

    def mutate(bundle):
        draft = replace(bundle, execution_slice_hash="f" * 64, evidence_bundle_hash="0" * 64)
        return replace(
            draft,
            evidence_bundle_hash=reconciliation.compute_verification_evidence_bundle_hash(draft),
        )

    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
        bundle_mutator=mutate,
    )

    with pytest.raises(reconciliation.ReconciliationError) as exc_info:
        _verify(request)

    assert exc_info.value.code == "RECONCILIATION_LINEAGE_MISMATCH"


def test_verified_at_is_audit_only_not_part_of_verification_hash(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    contract = _contract(
        {"subjects": {"from_argument": "targets"}, "path": "properties.thickness", "operator": "EXISTS"}
    )
    request = _request(
        step33_single_slice_transaction,
        step33_admitted_authority,
        step33_signed_actual_change,
        step33_signed_actual_delta,
        contract,
    )

    first = _verify(request)
    second = _verify(replace(request, verified_at="2026-08-30T15:30:00Z"))

    assert second.verification_hash == first.verification_hash
    assert second.verification_id == first.verification_id


def test_step29_planning_snapshot_hash_is_not_assumed_sha256(
    step33_single_slice_transaction,
) -> None:
    planning = step33_single_slice_transaction.canonical_changeset.planning_snapshot_ref
    projection = _projection("BASELINE-COMPAT")

    evidence = reconciliation.VerificationSubjectEvidence(
        semantic_id="WALL-001",
        canonical_kind="ifc:IfcWall",
        properties={"thickness": 0.25},
        placement={"x": 10.0},
        geometry_evidence=None,
        relationships=(),
        constraints=(),
        classification=("ifc:IfcWall",),
        evidence_aspects=(CanonicalAspect.PROPERTIES,),
        snapshot_id=planning.snapshot_id,
        snapshot_hash=planning.snapshot_hash,
        projection_ref=projection,
    )

    assert evidence.snapshot_hash == planning.snapshot_hash
