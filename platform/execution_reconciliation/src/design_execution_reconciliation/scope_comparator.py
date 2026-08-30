"""Deterministic Step33 comparison of actual Host effects to approved Slice scope."""

from __future__ import annotations

from dataclasses import dataclass, replace

from design_approval_scope import (
    ApprovalScopeError,
    EntitySelector,
    PredicateField,
    PredicateOperator,
    validate_approval_scope_boundary,
)
from design_execution_planning import (
    ExecutionPlanningError,
    validate_execution_slice_integrity,
)

from .contracts import (
    ActualChange,
    ActualChangeKind,
    ReconciliationError,
    ScopeComparisonRequest,
    ScopeComparisonResult,
    ScopeComparisonStatus,
    ScopeMatch,
    ScopeViolation,
)
from .hashing import compute_scope_comparison_hash, validate_actual_delta_integrity


@dataclass(frozen=True, slots=True)
class _SelectorContext:
    semantic_id: str | None
    canonical_kind: str | None
    source_entity: str | None
    derivation_rule: str | None


def _context(change: ActualChange) -> _SelectorContext:
    return _SelectorContext(
        semantic_id=change.semantic_id,
        canonical_kind=change.canonical_kind,
        source_entity=change.source_semantic_id,
        derivation_rule=change.derivation_rule,
    )


def _selector_value(context: _SelectorContext, field: PredicateField) -> str | None:
    return {
        PredicateField.SEMANTIC_ID: context.semantic_id,
        PredicateField.CANONICAL_KIND: context.canonical_kind,
        PredicateField.SOURCE_ENTITY: context.source_entity,
        PredicateField.DERIVATION_RULE: context.derivation_rule,
    }[field]


def _selector_matches(selector: EntitySelector, context: _SelectorContext) -> bool:
    if selector.entities:
        return context.semantic_id is not None and context.semantic_id in selector.entities

    predicate = selector.predicate
    if predicate is None:
        return False
    for term in predicate.all_of:
        value = _selector_value(context, term.field)
        if value is None:
            return False
        if term.operator is PredicateOperator.EQ:
            if value != term.values[0]:
                return False
        elif term.operator is PredicateOperator.IN:
            if value not in term.values:
                return False
        else:  # pragma: no cover - Step28 enum is closed, retain fail-closed behavior.
            return False
    return True


def _lineage_error(message: str) -> None:
    raise ReconciliationError("RECONCILIATION_LINEAGE_MISMATCH", message)


def _validate_lineage(request: ScopeComparisonRequest) -> None:
    authority = request.admitted_execution_authority
    delta = request.actual_delta
    boundary = request.approval_scope_boundary
    execution_slice = request.execution_slice

    exact_delta_joins = (
        ("grant_hash", authority.grant_hash, delta.grant_hash),
        ("binding_set_hash", authority.binding_set_hash, delta.binding_set_hash),
        (
            "execution_slice_hash",
            authority.execution_slice_hash,
            delta.execution_slice_hash,
        ),
        ("changeset_hash", authority.changeset_hash, delta.changeset_hash),
        (
            "approved_scope_hash",
            authority.approved_scope_hash,
            delta.approved_scope_hash,
        ),
        ("host_instance_id", authority.host_instance_id, delta.host_instance_id),
    )
    for field_name, expected, actual in exact_delta_joins:
        if expected != actual:
            _lineage_error(f"Step32 authority and ActualDelta {field_name} differ")

    if execution_slice.execution_slice_hash != authority.execution_slice_hash:
        _lineage_error("ExecutionSlice does not match admitted execution authority")
    if execution_slice.changeset_hash != authority.changeset_hash:
        _lineage_error("ExecutionSlice ChangeSet does not match admitted authority")
    if boundary.changeset_hash != authority.changeset_hash:
        _lineage_error("ApprovalScopeBoundary ChangeSet does not match admitted authority")
    if boundary.scope_hash != authority.approved_scope_hash:
        _lineage_error("ApprovalScopeBoundary does not match admitted approved scope")
    if execution_slice.approved_scope_ref.scope_hash != authority.approved_scope_hash:
        _lineage_error("ExecutionSlice approved scope does not match admitted authority")
    if execution_slice.host_runtime_ref.host_instance_id != authority.host_instance_id:
        _lineage_error("ExecutionSlice Host instance does not match admitted authority")


def _validate_boundary(request: ScopeComparisonRequest) -> None:
    try:
        validate_approval_scope_boundary(request.approval_scope_boundary)
    except ApprovalScopeError as exc:
        raise ReconciliationError(
            "SCOPE_COMPARISON_INVALID",
            "Step28 ApprovalScopeBoundary integrity validation failed",
            upstream_code=exc.code,
        ) from exc


def _validate_slice(request: ScopeComparisonRequest) -> None:
    try:
        validate_execution_slice_integrity(request.execution_slice)
    except ExecutionPlanningError as exc:
        raise ReconciliationError(
            "SCOPE_COMPARISON_INVALID",
            "Step30 ExecutionSlice integrity validation failed",
            upstream_code=exc.code,
        ) from exc


def _validate_host_and_provenance(request: ScopeComparisonRequest) -> None:
    delta = request.actual_delta
    execution_slice = request.execution_slice
    if execution_slice.host_runtime_ref.document_ref != delta.document_ref:
        _lineage_error("ExecutionSlice document does not match ActualDelta document")

    unit_hashes = {
        unit.execution_unit_hash for unit in execution_slice.execution_units
    }
    for change in delta.changes:
        source_hash = change.source_execution_unit_hash
        if source_hash is not None and source_hash not in unit_hashes:
            _lineage_error(
                "ActualChange source_execution_unit_hash is not a member of the admitted Slice"
            )


def _resolve_slice_scope(request: ScopeComparisonRequest):
    boundary = request.approval_scope_boundary
    execution_slice = request.execution_slice
    scope_rule_id = execution_slice.approved_scope_ref.execution_slice_scope_rule_id
    candidates = tuple(
        rule
        for rule in boundary.execution_slice_scopes
        if rule.slice_scope_rule_id == scope_rule_id
        and rule.document_ref == execution_slice.host_runtime_ref.document_ref
    )
    if len(candidates) != 1:
        raise ReconciliationError(
            "SCOPE_COMPARISON_INVALID",
            "exact Step28 ExecutionSliceScopeRule cannot be resolved",
        )
    return candidates[0]


def _rule_index(rules) -> dict[str, object]:
    result: dict[str, object] = {}
    for rule in rules:
        if rule.rule_id in result:
            raise ReconciliationError(
                "SCOPE_COMPARISON_INVALID",
                f"duplicate Step28 rule id: {rule.rule_id}",
            )
        result[rule.rule_id] = rule
    return result


def _authorized_rules(rule_ids: tuple[str, ...], rules_by_id: dict[str, object]):
    try:
        return tuple(rules_by_id[rule_id] for rule_id in sorted(rule_ids))
    except KeyError as exc:
        raise ReconciliationError(
            "SCOPE_COMPARISON_INVALID",
            f"Slice scope references unresolved Step28 rule: {exc.args[0]}",
        ) from exc


def _compare_modify(
    change: ActualChange,
    rules,
) -> tuple[list[ScopeMatch], list[ScopeViolation]]:
    context = _context(change)
    matching = tuple(rule for rule in rules if _selector_matches(rule.selector, context))
    if not matching:
        return [], [ScopeViolation("ENTITY_OUTSIDE_SCOPE", change.actual_change_hash)]

    matches = [
        ScopeMatch(change.actual_change_hash, rule.rule_id)
        for rule in sorted(matching, key=lambda item: item.rule_id)
    ]
    allowed_aspects = {
        aspect
        for rule in matching
        for aspect in rule.allowed_aspects
    }
    if not set(change.changed_aspects).issubset(allowed_aspects):
        return matches, [ScopeViolation("ASPECT_OUTSIDE_SCOPE", change.actual_change_hash)]
    return matches, []


def _compare_delete(
    change: ActualChange,
    rules,
) -> tuple[list[ScopeMatch], list[ScopeViolation]]:
    context = _context(change)
    matching = tuple(rule for rule in rules if _selector_matches(rule.selector, context))
    if not matching:
        return [], [ScopeViolation("DELETION_FORBIDDEN", change.actual_change_hash)]
    return (
        [
            ScopeMatch(change.actual_change_hash, rule.rule_id)
            for rule in sorted(matching, key=lambda item: item.rule_id)
        ],
        [],
    )


def _compare_create_fail_closed(
    change: ActualChange,
) -> tuple[list[ScopeMatch], list[ScopeViolation]]:
    return [], [ScopeViolation("CREATION_OPERATION_FORBIDDEN", change.actual_change_hash)]


class ScopeComparator:
    """Compare normalized actual side effects to exact Step28/Step30 authority."""

    def compare(self, request: ScopeComparisonRequest) -> ScopeComparisonResult:
        if not isinstance(request, ScopeComparisonRequest):
            raise ReconciliationError(
                "SCOPE_COMPARISON_INVALID",
                "request must be ScopeComparisonRequest",
            )

        validate_actual_delta_integrity(request.actual_delta)
        _validate_lineage(request)
        _validate_boundary(request)
        _validate_slice(request)
        _validate_host_and_provenance(request)
        slice_scope = _resolve_slice_scope(request)

        boundary = request.approval_scope_boundary
        existing_by_id = _rule_index(boundary.existing_entity_rules)
        deletion_by_id = _rule_index(boundary.deletion_rules)
        existing_rules = _authorized_rules(
            slice_scope.existing_rule_ids,
            existing_by_id,
        )
        deletion_rules = _authorized_rules(
            slice_scope.deletion_rule_ids,
            deletion_by_id,
        )

        matches: list[ScopeMatch] = []
        violations: list[ScopeViolation] = []
        for change in sorted(
            request.actual_delta.changes,
            key=lambda item: item.actual_change_hash,
        ):
            if change.change_kind is ActualChangeKind.MODIFY:
                change_matches, change_violations = _compare_modify(
                    change,
                    existing_rules,
                )
            elif change.change_kind is ActualChangeKind.DELETE:
                change_matches, change_violations = _compare_delete(
                    change,
                    deletion_rules,
                )
            else:
                change_matches, change_violations = _compare_create_fail_closed(change)
            matches.extend(change_matches)
            violations.extend(change_violations)

        status = (
            ScopeComparisonStatus.SCOPE_BREACH
            if violations
            else ScopeComparisonStatus.WITHIN_SCOPE
        )
        draft = ScopeComparisonResult(
            status=status,
            actual_delta_hash=request.actual_delta.actual_delta_hash,
            approved_scope_hash=boundary.scope_hash,
            execution_slice_hash=request.execution_slice.execution_slice_hash,
            matched_changes=tuple(matches),
            violations=tuple(violations),
            comparison_hash="0" * 64,
        )
        return replace(
            draft,
            comparison_hash=compute_scope_comparison_hash(draft),
        )


__all__ = ["ScopeComparator"]
