"""Owner-side integrity reconstruction for immutable Step29 ChangeSets."""

from __future__ import annotations

from collections.abc import Mapping

from design_approval_scope import ApprovalScopeBoundary

from .contracts import CanonicalChangeOperation, CanonicalChangeSet, ChangeSetError
from .hashing import (
    compute_changeset_hash,
    compute_operation_semantic_hash,
    compute_scope_rule_fingerprint,
)


def _invalid(message: str) -> None:
    raise ChangeSetError("CHANGESET_INTEGRITY_INVALID", message)


def _rules_by_id(boundary: ApprovalScopeBoundary) -> dict[str, object]:
    rules: dict[str, object] = {}
    for rule in (
        *boundary.existing_entity_rules,
        *boundary.creation_rules,
        *boundary.deletion_rules,
    ):
        if rule.rule_id in rules:
            _invalid(f"duplicate Step28 scope rule id: {rule.rule_id}")
        rules[rule.rule_id] = rule
    return rules


def _operation_hash(
    operation: CanonicalChangeOperation,
    rules_by_id: Mapping[str, object],
) -> str:
    try:
        fingerprints = tuple(
            sorted(
                compute_scope_rule_fingerprint(rules_by_id[rule_id])
                for rule_id in operation.scope_rule_ids
            )
        )
    except KeyError as exc:
        _invalid(f"unresolved Step28 scope rule: {exc.args[0]}")

    operation_hash = compute_operation_semantic_hash(
        origin=operation.origin,
        canonical_operation=operation.canonical_operation,
        canonical_operation_version=operation.canonical_operation_version,
        canonical_definition_fingerprint=operation.canonical_definition_fingerprint,
        targets=operation.targets,
        arguments=operation.arguments,
        expected_effects=operation.expected_effects,
        scope_rule_fingerprints=fingerprints,
        source_evidence=operation.source_evidence,
        expected_existence_effects=operation.expected_existence_effects,
    )
    if operation.operation_id != f"COP-{operation_hash[:12]}":
        _invalid("operation id does not match semantic operation hash")
    return operation_hash


def _validation_task_payloads(changeset: CanonicalChangeSet) -> list[dict[str, object]]:
    return [
        {
            "kind": task.kind.value,
            "subject_semantic_ids": list(task.subject_semantic_ids),
            "canonical_operation_ref": task.canonical_operation_ref,
            "dependency_ref": task.dependency_ref,
            "contract_ref": task.contract_ref,
        }
        for task in changeset.validation_tasks
    ]


def validate_changeset_integrity(
    changeset: CanonicalChangeSet,
    approval_scope_boundary: ApprovalScopeBoundary,
) -> None:
    """Reconstruct the exact Step29 semantic body against one final Step28 Boundary."""
    if not isinstance(changeset, CanonicalChangeSet):
        raise TypeError("changeset must be CanonicalChangeSet")
    if not isinstance(approval_scope_boundary, ApprovalScopeBoundary):
        raise TypeError("approval_scope_boundary must be ApprovalScopeBoundary")

    if changeset.changeset_hash != approval_scope_boundary.changeset_hash:
        _invalid("ChangeSet hash does not match final Step28 Boundary")
    if (
        changeset.approval_scope_definition_ref.scope_body_hash
        != approval_scope_boundary.scope_body_hash
    ):
        _invalid("ChangeSet scope body does not match final Step28 Boundary")

    operations = (changeset.root_operation, *changeset.derived_operations)
    operation_ids = tuple(operation.operation_id for operation in operations)
    if len(set(operation_ids)) != len(operation_ids):
        _invalid("canonical operation ids must be unique")

    rules = _rules_by_id(approval_scope_boundary)
    operation_hashes = {
        operation.operation_id: _operation_hash(operation, rules)
        for operation in operations
    }
    root_hash = operation_hashes[changeset.root_operation.operation_id]
    derived_hashes = tuple(
        operation_hashes[operation.operation_id]
        for operation in changeset.derived_operations
    )

    dependency_payloads: list[dict[str, str]] = []
    for dependency in changeset.change_dependencies:
        predecessor_hash = operation_hashes.get(dependency.predecessor_operation_id)
        successor_hash = operation_hashes.get(dependency.successor_operation_id)
        if predecessor_hash is None or successor_hash is None:
            _invalid("change dependency references an unknown canonical operation")
        dependency_payloads.append(
            {
                "predecessor_operation_hash": predecessor_hash,
                "successor_operation_hash": successor_hash,
                "reason_ref": dependency.reason_ref,
            }
        )

    semantic_body = {
        "task_id": changeset.task_id,
        "project_id": changeset.project_id,
        "planning_snapshot_ref": changeset.planning_snapshot_ref,
        "snapshot_set_ref": changeset.snapshot_set_ref,
        "semantic_environment_ref": changeset.semantic_environment_ref,
        "impact_analysis_fingerprint": changeset.impact_analysis_fingerprint,
        "bound_operation_fingerprint": changeset.bound_operation_fingerprint,
        "scope_body_hash": approval_scope_boundary.scope_body_hash,
        "root_operation": root_hash,
        "derived_operations": list(derived_hashes),
        "change_dependencies": dependency_payloads,
        "preconditions": changeset.preconditions,
        "affected_entities": list(changeset.affected_entities),
        "semantic_impacts": changeset.semantic_impacts,
        "validation_tasks": _validation_task_payloads(changeset),
    }
    expected = compute_changeset_hash(semantic_body)
    if expected != changeset.changeset_hash:
        _invalid("ChangeSet hash does not match reconstructed semantic body")


__all__ = ["validate_changeset_integrity"]
