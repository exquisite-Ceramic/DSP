"""Canonical Step33 hashing for authoritative normalized Host side effects."""

from __future__ import annotations

from design_changeset import canonical_hash

from .contracts import (
    ActualChange,
    ActualDelta,
    ReconciliationError,
    ScopeComparisonResult,
)


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


__all__ = [
    "compute_actual_change_hash",
    "compute_actual_delta_hash",
    "compute_scope_comparison_hash",
    "validate_actual_delta_integrity",
]
