"""Fail-closed deterministic execution partitioning for Step30."""

from __future__ import annotations

from design_approval_scope import (
    ApprovalScopeBoundary,
    ExecutionSliceScopeRule,
    ExistingEntityRule,
)
from design_changeset import (
    CanonicalChangeOperation,
    CanonicalChangeSet,
    compute_operation_semantic_hash,
    compute_scope_rule_fingerprint,
)

from .contracts import ExecutionPlanningError


def _error(code: str, message: str):
    raise ExecutionPlanningError(code, message)


def _operations(changeset: CanonicalChangeSet) -> tuple[CanonicalChangeOperation, ...]:
    return (changeset.root_operation, *changeset.derived_operations)


def _validate_scope_binding(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundary,
) -> dict[str, ExistingEntityRule]:
    if changeset.changeset_hash != boundary.changeset_hash:
        _error("EXECUTION_SCOPE_MISMATCH", "approval scope does not bind this ChangeSet")
    if changeset.approval_scope_definition_ref.scope_body_hash != boundary.scope_body_hash:
        _error("EXECUTION_SCOPE_MISMATCH", "approval scope body differs from the ChangeSet scope reference")

    rules: dict[str, ExistingEntityRule] = {}
    for rule in boundary.existing_entity_rules:
        if rule.rule_id in rules:
            _error("EXECUTION_SCOPE_MISMATCH", "approval scope contains duplicate existing rule ids")
        rules[rule.rule_id] = rule

    for operation in _operations(changeset):
        if not operation.scope_rule_ids:
            _error("EXECUTION_SCOPE_MISMATCH", "canonical operation has no Step28 mutation authority")
        unknown = set(operation.scope_rule_ids) - set(rules)
        if unknown:
            _error(
                "EXECUTION_SCOPE_MISMATCH",
                f"canonical operation references unknown Step28 rules: {sorted(unknown)}",
            )
    return rules


def _source_operation_hash(
    operation: CanonicalChangeOperation,
    rules_by_id: dict[str, ExistingEntityRule],
) -> str:
    try:
        fingerprints = tuple(
            sorted(
                compute_scope_rule_fingerprint(rules_by_id[rule_id])
                for rule_id in operation.scope_rule_ids
            )
        )
    except KeyError as exc:
        _error("EXECUTION_SCOPE_MISMATCH", f"operation scope rule is unresolved: {exc.args[0]}")

    source_hash = compute_operation_semantic_hash(
        origin=operation.origin,
        canonical_operation=operation.canonical_operation,
        canonical_operation_version=operation.canonical_operation_version,
        canonical_definition_fingerprint=operation.canonical_definition_fingerprint,
        targets=operation.targets,
        arguments=operation.arguments,
        expected_effects=operation.expected_effects,
        scope_rule_fingerprints=fingerprints,
        source_evidence=operation.source_evidence,
    )
    if operation.operation_id != f"COP-{source_hash[:12]}":
        _error(
            "EXECUTION_OPERATION_MISMATCH",
            "canonical operation no longer matches its Step29 semantic identity",
        )
    return source_hash


def _slice_body(rule: ExecutionSliceScopeRule) -> tuple[object, ...]:
    return (
        rule.document_ref,
        tuple(sorted(rule.existing_rule_ids)),
        tuple(sorted(rule.creation_rule_ids)),
        tuple(sorted(rule.deletion_rule_ids)),
    )


def _select_slice_scope(
    operation: CanonicalChangeOperation,
    document_ref: str,
    boundary: ApprovalScopeBoundary,
) -> ExecutionSliceScopeRule:
    required = set(operation.scope_rule_ids)
    candidates: list[tuple[int, tuple[object, ...], ExecutionSliceScopeRule]] = []
    for candidate in boundary.execution_slice_scopes:
        if candidate.document_ref != document_ref:
            continue
        if not required.issubset(candidate.existing_rule_ids):
            continue
        authority = (
            set(candidate.existing_rule_ids)
            | set(candidate.creation_rule_ids)
            | set(candidate.deletion_rule_ids)
        )
        surplus = authority - required
        candidates.append((len(surplus), _slice_body(candidate), candidate))

    if not candidates:
        _error(
            "EXECUTION_SLICE_SCOPE_UNCOVERED",
            "no approved execution slice scope covers this canonical operation",
        )

    minimum = min(item[0] for item in candidates)
    tied = [item for item in candidates if item[0] == minimum]
    bodies = {item[1] for item in tied}
    if len(bodies) != 1:
        _error(
            "EXECUTION_SLICE_SCOPE_AMBIGUOUS",
            "multiple least-authority execution slice scopes have different authority",
        )

    return min((item[2] for item in tied), key=lambda item: item.slice_scope_rule_id)


__all__ = [
    "_select_slice_scope",
    "_source_operation_hash",
    "_validate_scope_binding",
]
