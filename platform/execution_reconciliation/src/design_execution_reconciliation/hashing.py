"""Canonical Step33 hashing for normalized side effects and verification evidence."""

from __future__ import annotations

from design_changeset import canonical_hash
from semantic_runtime import SemanticProjectionRef, SemanticSnapshot

from .contracts import (
    ActualChange,
    ActualDelta,
    ReconciliationError,
    ScopeComparisonResult,
    SemanticVerificationResult,
    ValidationTaskResult,
    VerificationEvidenceBundle,
    VerificationSubjectEvidence,
)
from .saga_contracts import ExecutionSagaDefinition


def _instance_payload(change: ActualChange) -> dict[str, object] | None:
    if change.semantic_id is not None:
        return {
            "kind": "SEMANTIC_ID",
            "semantic_id": change.semantic_id,
        }
    if change.host_entity_ref is not None:
        return {
            "kind": "HOST_ENTITY",
            "document_id": change.host_entity_ref.document_id,
            "native_id": change.host_entity_ref.native_id,
        }
    return None


def _projection_payload(ref: SemanticProjectionRef | None) -> object:
    return None if ref is None else ref.payload()


def _snapshot_ref_payload(snapshot: SemanticSnapshot | None) -> object:
    if snapshot is None:
        return None
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_hash": snapshot.hash,
        "document_ref": snapshot.document_ref,
        "base_host_revision": snapshot.base_host_revision,
        "projection_ref": snapshot.projection_ref.payload(),
        "semantic_environment_ref": snapshot.semantic_environment_ref.payload(),
    }


def _subject_payload(subject: VerificationSubjectEvidence) -> dict[str, object]:
    return {
        "semantic_id": subject.semantic_id,
        "canonical_kind": subject.canonical_kind,
        "properties": subject.properties,
        "placement": subject.placement,
        "geometry_evidence": subject.geometry_evidence,
        "relationships": list(subject.relationships),
        "constraints": list(subject.constraints),
        "classification": list(subject.classification),
        "evidence_aspects": [aspect.value for aspect in subject.evidence_aspects],
        "snapshot_id": subject.snapshot_id,
        "snapshot_hash": subject.snapshot_hash,
        "projection_ref": subject.projection_ref.payload(),
    }


def compute_actual_change_hash(change: ActualChange) -> str:
    """Hash provider-neutral change semantics and stable instance identity."""
    if not isinstance(change, ActualChange):
        raise TypeError("change must be ActualChange")
    return canonical_hash(
        {
            "change_kind": change.change_kind.value,
            "instance": _instance_payload(change),
            "canonical_kind": change.canonical_kind,
            "changed_aspects": [aspect.value for aspect in change.changed_aspects],
            "canonical_operation": change.canonical_operation,
            "source_execution_unit_hash": change.source_execution_unit_hash,
            "source_semantic_id": change.source_semantic_id,
            "source_canonical_kind": change.source_canonical_kind,
            "derivation_rule": change.derivation_rule,
        }
    )


def compute_actual_delta_hash(delta: ActualDelta) -> str:
    """Hash exact Step32 lineage, Host revision, and normalized side effects."""
    if not isinstance(delta, ActualDelta):
        raise TypeError("delta must be ActualDelta")
    return canonical_hash(
        {
            "grant_hash": delta.grant_hash,
            "binding_set_hash": delta.binding_set_hash,
            "execution_slice_hash": delta.execution_slice_hash,
            "changeset_hash": delta.changeset_hash,
            "approved_scope_hash": delta.approved_scope_hash,
            "host_instance_id": delta.host_instance_id,
            "document_ref": delta.document_ref,
            "revision_before": delta.revision_before,
            "revision_after": delta.revision_after,
            "actual_change_hashes": sorted(
                change.actual_change_hash for change in delta.changes
            ),
        }
    )


def validate_actual_delta_integrity(delta: ActualDelta) -> None:
    """Reconstruct one ActualDelta commitment fail-closed."""
    if not isinstance(delta, ActualDelta):
        raise ReconciliationError(
            "ACTUAL_DELTA_INPUT_INVALID",
            "delta must be ActualDelta",
        )

    for change in delta.changes:
        expected_change_hash = compute_actual_change_hash(change)
        if change.actual_change_hash != expected_change_hash:
            raise ReconciliationError(
                "ACTUAL_DELTA_INTEGRITY_INVALID",
                "actual change body does not match its committed hash",
            )
        if (
            change.host_entity_ref is not None
            and change.host_entity_ref.document_id != delta.document_ref
        ):
            raise ReconciliationError(
                "ACTUAL_DELTA_INPUT_INVALID",
                "Host entity provenance document does not match ActualDelta document",
            )

    expected_delta_hash = compute_actual_delta_hash(delta)
    if delta.actual_delta_hash != expected_delta_hash:
        raise ReconciliationError(
            "ACTUAL_DELTA_INTEGRITY_INVALID",
            "ActualDelta body does not match its committed hash",
        )


def compute_scope_comparison_hash(result: ScopeComparisonResult) -> str:
    """Hash one deterministic scope-comparison decision and its audit detail."""
    if not isinstance(result, ScopeComparisonResult):
        raise TypeError("result must be ScopeComparisonResult")
    return canonical_hash(
        {
            "status": result.status.value,
            "actual_delta_hash": result.actual_delta_hash,
            "approved_scope_hash": result.approved_scope_hash,
            "execution_slice_hash": result.execution_slice_hash,
            "matched_changes": [
                {
                    "actual_change_hash": match.actual_change_hash,
                    "rule_id": match.rule_id,
                }
                for match in sorted(
                    result.matched_changes,
                    key=lambda item: (item.actual_change_hash, item.rule_id),
                )
            ],
            "violations": [
                {
                    "code": violation.code,
                    "actual_change_hash": violation.actual_change_hash,
                    "rule_id": violation.rule_id,
                }
                for violation in sorted(
                    result.violations,
                    key=lambda item: (
                        item.actual_change_hash,
                        item.code,
                        item.rule_id or "",
                    ),
                )
            ],
        }
    )


def compute_verification_evidence_bundle_hash(
    bundle: VerificationEvidenceBundle,
) -> str:
    """Hash one complete snapshot-bound provider-neutral verification evidence body."""
    if not isinstance(bundle, VerificationEvidenceBundle):
        raise TypeError("bundle must be VerificationEvidenceBundle")
    return canonical_hash(
        {
            "changeset_hash": bundle.changeset_hash,
            "execution_slice_hash": bundle.execution_slice_hash,
            "actual_delta_hash": bundle.actual_delta_hash,
            "semantic_environment_ref": bundle.semantic_environment_ref.payload(),
            "post_execution_snapshot_ref": _snapshot_ref_payload(
                bundle.post_execution_snapshot_ref
            ),
            "post_execution_projection_ref": _projection_payload(
                bundle.post_execution_projection_ref
            ),
            "base_host_revision": bundle.base_host_revision,
            "baseline_snapshot_ref": _snapshot_ref_payload(bundle.baseline_snapshot_ref),
            "baseline_projection_ref": _projection_payload(
                bundle.baseline_projection_ref
            ),
            "contract_evidence": [
                {
                    "contract_ref": item.contract_ref,
                    "contract_body": item.contract_body,
                }
                for item in bundle.contract_evidence
            ],
            "subject_evidence": [
                _subject_payload(item) for item in bundle.subject_evidence
            ],
            "baseline_subject_evidence": [
                _subject_payload(item) for item in bundle.baseline_subject_evidence
            ],
        }
    )


def _validate_subject_uniqueness(
    subjects: tuple[VerificationSubjectEvidence, ...],
    field_name: str,
) -> None:
    seen: set[tuple[str, str, str]] = set()
    for subject in subjects:
        key = (subject.snapshot_id, subject.snapshot_hash, subject.semantic_id)
        if key in seen:
            raise ReconciliationError(
                "VERIFY_INPUT_INVALID",
                f"{field_name} contains duplicate snapshot-bound semantic evidence",
            )
        seen.add(key)


def validate_verification_evidence_bundle_integrity(
    bundle: VerificationEvidenceBundle,
) -> None:
    """Reconstruct intrinsic evidence identity without any cross-object joins."""
    if not isinstance(bundle, VerificationEvidenceBundle):
        raise ReconciliationError(
            "VERIFY_INPUT_INVALID",
            "bundle must be VerificationEvidenceBundle",
        )

    contract_bodies: dict[str, str] = {}
    for evidence in bundle.contract_evidence:
        body_hash = canonical_hash(evidence.contract_body)
        previous = contract_bodies.get(evidence.contract_ref)
        if body_hash != evidence.contract_ref or (
            previous is not None and previous != body_hash
        ):
            raise ReconciliationError(
                "VERIFY_CONTRACT_MISMATCH",
                "verification contract body does not match its content-addressed ref",
            )
        contract_bodies[evidence.contract_ref] = body_hash

    _validate_subject_uniqueness(bundle.subject_evidence, "subject_evidence")
    _validate_subject_uniqueness(
        bundle.baseline_subject_evidence,
        "baseline_subject_evidence",
    )

    expected_hash = compute_verification_evidence_bundle_hash(bundle)
    if bundle.evidence_bundle_hash != expected_hash:
        raise ReconciliationError(
            "VERIFY_INPUT_INVALID",
            "VerificationEvidenceBundle body does not match its committed hash",
        )


def compute_validation_task_result_hash(result: ValidationTaskResult) -> str:
    """Hash one deterministic ValidationTask evaluation result."""
    if not isinstance(result, ValidationTaskResult):
        raise TypeError("result must be ValidationTaskResult")
    return canonical_hash(
        {
            "validation_task_id": result.validation_task_id,
            "status": result.status.value,
            "observations": list(result.observations),
            "failure_codes": list(result.failure_codes),
        }
    )


def compute_semantic_verification_hash(result: SemanticVerificationResult) -> str:
    """Hash semantic verification meaning, excluding audit-only timestamps/ids."""
    if not isinstance(result, SemanticVerificationResult):
        raise TypeError("result must be SemanticVerificationResult")
    return canonical_hash(
        {
            "changeset_hash": result.changeset_hash,
            "execution_slice_hash": result.execution_slice_hash,
            "actual_delta_hash": result.actual_delta_hash,
            "evidence_bundle_hash": result.evidence_bundle_hash,
            "task_result_hashes": [
                item.task_result_hash
                for item in sorted(
                    result.task_results,
                    key=lambda item: item.validation_task_id,
                )
            ],
            "status": result.status.value,
        }
    )


def compute_execution_saga_definition_hash(definition: ExecutionSagaDefinition) -> str:
    """Hash immutable Saga meaning, including canonical order and task ownership."""
    if not isinstance(definition, ExecutionSagaDefinition):
        raise TypeError("definition must be ExecutionSagaDefinition")
    return canonical_hash(
        {
            "changeset_hash": definition.changeset_hash,
            "approved_scope_hash": definition.approved_scope_hash,
            "semantic_environment_ref": definition.semantic_environment_ref.payload(),
            "execution_plan_hash": definition.execution_plan_hash,
            "ordered_slice_hashes": list(definition.ordered_slice_hashes),
            "slice_dependencies": [
                {
                    "predecessor_slice_hash": item.predecessor_slice_hash,
                    "successor_slice_hash": item.successor_slice_hash,
                    "reason_refs": list(item.reason_refs),
                }
                for item in definition.slice_dependencies
            ],
            "slice_validation_assignments": [
                {
                    "execution_slice_hash": item.execution_slice_hash,
                    "validation_task_ids": list(item.validation_task_ids),
                }
                for item in definition.slice_validation_assignments
            ],
        }
    )


__all__ = [
    "compute_actual_change_hash",
    "compute_actual_delta_hash",
    "compute_execution_saga_definition_hash",
    "compute_scope_comparison_hash",
    "compute_semantic_verification_hash",
    "compute_validation_task_result_hash",
    "compute_verification_evidence_bundle_hash",
    "validate_actual_delta_integrity",
    "validate_verification_evidence_bundle_integrity",
]
