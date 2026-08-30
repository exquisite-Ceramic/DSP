"""Step33 deterministic CREATE scope matching and capacity allocation tests."""

from __future__ import annotations

from dataclasses import replace

import design_execution_reconciliation as reconciliation
import pytest
from design_approval_scope import (
    ApprovalScopeDefinition,
    CreationRule,
    EntityPredicate,
    EntitySelector,
    ExecutionSliceScopeRule,
    PredicateField,
    PredicateOperator,
    PredicateTerm,
    bind_changeset,
    compute_scope_body_hash,
)
from design_execution_planning import (
    ApprovedExecutionScopeRef,
    compute_execution_slice_hash,
)


def _synthetic_creation_boundary_and_slice(
    transaction,
    creation_rules: tuple[CreationRule, ...],
    *,
    slice_creation_rule_ids: tuple[str, ...] | None = None,
):
    boundary = transaction.approval_scope_boundary
    execution_slice = transaction.execution_slice
    assert execution_slice is not None
    current_scope = next(
        rule
        for rule in boundary.execution_slice_scopes
        if rule.slice_scope_rule_id
        == execution_slice.approved_scope_ref.execution_slice_scope_rule_id
    )
    creation_ids = (
        tuple(rule.rule_id for rule in creation_rules)
        if slice_creation_rule_ids is None
        else slice_creation_rule_ids
    )
    slice_scope = ExecutionSliceScopeRule(
        current_scope.slice_scope_rule_id,
        current_scope.document_ref,
        existing_rule_ids=current_scope.existing_rule_ids,
        creation_rule_ids=creation_ids,
        deletion_rule_ids=current_scope.deletion_rule_ids,
    )
    body_hash = compute_scope_body_hash(
        impact_analysis_fingerprint=boundary.impact_analysis_fingerprint,
        canonical_effect_evidence=boundary.canonical_effect_evidence,
        intent_boundary=boundary.intent_boundary,
        planning_snapshot_ref=boundary.planning_snapshot_ref,
        snapshot_set_ref=boundary.snapshot_set_ref,
        semantic_environment_ref=boundary.semantic_environment_ref,
        existing_entity_rules=boundary.existing_entity_rules,
        creation_rules=creation_rules,
        deletion_rules=boundary.deletion_rules,
        propagation_bundle_ids=boundary.propagation_bundle_ids,
        execution_slice_scope_rules=(slice_scope,),
    )
    definition = ApprovalScopeDefinition(
        scope_definition_id=boundary.scope_definition_id,
        impact_analysis_fingerprint=boundary.impact_analysis_fingerprint,
        canonical_effect_evidence=boundary.canonical_effect_evidence,
        intent_boundary=boundary.intent_boundary,
        planning_snapshot_ref=boundary.planning_snapshot_ref,
        snapshot_set_ref=boundary.snapshot_set_ref,
        semantic_environment_ref=boundary.semantic_environment_ref,
        existing_entity_rules=boundary.existing_entity_rules,
        creation_rules=creation_rules,
        deletion_rules=boundary.deletion_rules,
        propagation_bundle_ids=boundary.propagation_bundle_ids,
        execution_slice_scope_rules=(slice_scope,),
        scope_body_hash=body_hash,
    )
    synthetic_boundary = bind_changeset(
        definition,
        boundary.changeset_hash,
        boundary.scope_id,
    )
    approved_scope_ref = ApprovedExecutionScopeRef(
        synthetic_boundary.scope_id,
        synthetic_boundary.scope_hash,
        slice_scope.slice_scope_rule_id,
    )
    slice_hash = compute_execution_slice_hash(
        changeset_hash=execution_slice.changeset_hash,
        scope_hash=synthetic_boundary.scope_hash,
        execution_slice_scope_rule_id=slice_scope.slice_scope_rule_id,
        host_runtime_ref=execution_slice.host_runtime_ref,
        execution_unit_hashes=(
            unit.execution_unit_hash for unit in execution_slice.execution_units
        ),
    )
    synthetic_slice = replace(
        execution_slice,
        execution_slice_id=f"XS-{slice_hash[:12]}",
        approved_scope_ref=approved_scope_ref,
        execution_slice_hash=slice_hash,
    )
    return synthetic_boundary, synthetic_slice


def _relineage(authority, boundary, execution_slice):
    return replace(
        authority,
        approved_scope_hash=boundary.scope_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
    )


def _signed_scope_delta(
    signed_delta,
    authority,
    boundary,
    execution_slice,
    *changes,
):
    return signed_delta(
        *changes,
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        changeset_hash=execution_slice.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
    )


def _compare(authority, delta, boundary, execution_slice):
    request = reconciliation.ScopeComparisonRequest(
        admitted_execution_authority=authority,
        actual_delta=delta,
        approval_scope_boundary=boundary,
        execution_slice=execution_slice,
    )
    return reconciliation.ScopeComparator().compare(request)


def _violation_codes(result) -> tuple[str, ...]:
    return tuple(violation.code for violation in result.violations)


def _rule(
    rule_id: str = "CR-COPY",
    *,
    canonical_operation: str = "copy.v1",
    source_selector: EntitySelector | None = None,
    entity_kinds: tuple[str, ...] = ("ifc:IfcWall",),
    max_count: int | None = None,
    required_derivation: str | None = "RULE-COPY",
) -> CreationRule:
    return CreationRule(
        rule_id=rule_id,
        canonical_operation=canonical_operation,
        source_selector=source_selector
        or EntitySelector(entities=("WALL-001",)),
        entity_kinds=entity_kinds,
        max_count=max_count,
        required_derivation=required_derivation,
    )


def _create_change(signed_change, semantic_id: str = "NEW-001", **overrides):
    values = {
        "change_kind": "CREATE",
        "semantic_id": semantic_id,
        "canonical_kind": "ifc:IfcWall",
        "canonical_operation": "copy.v1",
        "source_semantic_id": "WALL-001",
        "source_canonical_kind": "ifc:IfcWall",
        "derivation_rule": "RULE-COPY",
    }
    values.update(overrides)
    return signed_change(**values)


def test_create_all_rule_dimensions_satisfied_is_within_scope(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    rule = _rule(max_count=1)
    boundary, execution_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule,),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = _create_change(step33_signed_actual_change)
    delta = _signed_scope_delta(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    assert result.violations == ()
    assert tuple(match.rule_id for match in result.matched_changes) == ("CR-COPY",)


def test_create_operation_mismatch_is_staged_operation_breach(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    rule = _rule(canonical_operation="array.v1")
    boundary, execution_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule,),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = _create_change(step33_signed_actual_change)
    delta = _signed_scope_delta(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH
    assert _violation_codes(result) == ("CREATION_OPERATION_FORBIDDEN",)


def test_create_kind_mismatch_is_staged_kind_breach(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    rule = _rule(entity_kinds=("ifc:IfcDoor",))
    boundary, execution_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule,),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = _create_change(step33_signed_actual_change)
    delta = _signed_scope_delta(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert _violation_codes(result) == ("CREATION_KIND_FORBIDDEN",)


def test_create_explicit_source_mismatch_is_staged_source_breach(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    rule = _rule(source_selector=EntitySelector(entities=("WALL-OTHER",)))
    boundary, execution_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule,),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = _create_change(step33_signed_actual_change)
    delta = _signed_scope_delta(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert _violation_codes(result) == ("CREATION_SOURCE_FORBIDDEN",)


def test_create_source_predicate_canonical_kind_uses_source_kind(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    selector = EntitySelector(
        predicate=EntityPredicate(
            all_of=(
                PredicateTerm(
                    PredicateField.CANONICAL_KIND,
                    PredicateOperator.EQ,
                    ("ifc:IfcWall",),
                ),
            )
        )
    )
    rule = _rule(
        source_selector=selector,
        entity_kinds=("ifc:IfcDoor",),
    )
    boundary, execution_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule,),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = _create_change(
        step33_signed_actual_change,
        canonical_kind="ifc:IfcDoor",
        source_canonical_kind="ifc:IfcWall",
    )
    delta = _signed_scope_delta(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    assert tuple(match.rule_id for match in result.matched_changes) == ("CR-COPY",)


def test_create_missing_required_source_semantic_evidence_fails_closed(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    rule = _rule()
    boundary, execution_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule,),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = _create_change(
        step33_signed_actual_change,
        source_semantic_id=None,
    )
    delta = _signed_scope_delta(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert _violation_codes(result) == ("CREATION_SOURCE_FORBIDDEN",)


def test_create_required_derivation_mismatch_is_staged_derivation_breach(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    rule = _rule(required_derivation="RULE-REQUIRED")
    boundary, execution_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule,),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = _create_change(step33_signed_actual_change, derivation_rule="RULE-OTHER")
    delta = _signed_scope_delta(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert _violation_codes(result) == ("CREATION_DERIVATION_MISMATCH",)


def test_creation_rule_absent_from_current_slice_cannot_authorize(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    rule = _rule()
    boundary, execution_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule,),
        slice_creation_rule_ids=(),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = _create_change(step33_signed_actual_change)
    delta = _signed_scope_delta(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH
    assert _violation_codes(result) == ("CREATION_OPERATION_FORBIDDEN",)
    assert result.matched_changes == ()


def test_creation_max_count_overflow_is_capacity_breach(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    rule = _rule(max_count=1)
    boundary, execution_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule,),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    first = _create_change(step33_signed_actual_change, "NEW-001")
    second = _create_change(step33_signed_actual_change, "NEW-002")
    delta = _signed_scope_delta(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        first,
        second,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH
    assert _violation_codes(result) == ("CREATION_COUNT_EXCEEDED",)


def test_overlapping_creation_rules_use_global_capacity_allocation(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    rule_a = _rule(
        "CR-A",
        source_selector=EntitySelector(
            predicate=EntityPredicate(
                all_of=(
                    PredicateTerm(
                        PredicateField.SEMANTIC_ID,
                        PredicateOperator.IN,
                        ("SRC-A-ONLY", "SRC-COMMON"),
                    ),
                )
            )
        ),
        max_count=1,
    )
    rule_b = _rule(
        "CR-B",
        source_selector=EntitySelector(
            predicate=EntityPredicate(
                all_of=(
                    PredicateTerm(
                        PredicateField.SEMANTIC_ID,
                        PredicateOperator.IN,
                        ("SRC-B-ONLY", "SRC-COMMON"),
                    ),
                )
            )
        ),
        max_count=2,
    )
    common = _create_change(
        step33_signed_actual_change,
        "NEW-001",
        source_semantic_id="SRC-COMMON",
    )
    only_a = _create_change(
        step33_signed_actual_change,
        "NEW-002",
        source_semantic_id="SRC-A-ONLY",
    )
    only_b = _create_change(
        step33_signed_actual_change,
        "NEW-003",
        source_semantic_id="SRC-B-ONLY",
    )

    boundary, execution_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule_a, rule_b),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    delta = _signed_scope_delta(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        common,
        only_a,
        only_b,
    )
    result = _compare(authority, delta, boundary, execution_slice)

    reversed_boundary, reversed_slice = _synthetic_creation_boundary_and_slice(
        step33_single_slice_transaction,
        (rule_b, rule_a),
        slice_creation_rule_ids=(rule_b.rule_id, rule_a.rule_id),
    )
    reversed_authority = _relineage(
        step33_admitted_authority,
        reversed_boundary,
        reversed_slice,
    )
    reversed_delta = _signed_scope_delta(
        step33_signed_actual_delta,
        reversed_authority,
        reversed_boundary,
        reversed_slice,
        only_b,
        only_a,
        common,
    )
    reversed_result = _compare(
        reversed_authority,
        reversed_delta,
        reversed_boundary,
        reversed_slice,
    )

    assert result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    assert reversed_result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    expected = {
        (common.actual_change_hash, "CR-B"),
        (only_a.actual_change_hash, "CR-A"),
        (only_b.actual_change_hash, "CR-B"),
    }
    assert {
        (match.actual_change_hash, match.rule_id) for match in result.matched_changes
    } == expected
    assert reversed_result.matched_changes == result.matched_changes
    assert reversed_result.comparison_hash == result.comparison_hash
