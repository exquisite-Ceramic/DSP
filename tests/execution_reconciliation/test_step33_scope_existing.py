"""Step33 deterministic MODIFY/DELETE scope comparison behavior."""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_approval_scope import (
    ApprovalScopeDefinition,
    CanonicalAspect,
    DeletionRule,
    EntityPredicate,
    EntitySelector,
    ExecutionSliceScopeRule,
    ExistingEntityRule,
    PredicateField,
    PredicateOperator,
    PredicateTerm,
    bind_changeset,
    compute_scope_body_hash,
)
from design_execution_planning import (
    ApprovedExecutionScopeRef,
    HostRuntimeRef,
    compute_execution_slice_hash,
)
from host_contracts import HostEntityRef

import design_execution_reconciliation as reconciliation


def _assert_error(code: str, operation, *, upstream_code: str | None = None) -> None:
    with pytest.raises(reconciliation.ReconciliationError) as exc:
        operation()
    assert exc.value.code == code
    assert exc.value.upstream_code == upstream_code


def _request(authority, delta, boundary, execution_slice):
    return reconciliation.ScopeComparisonRequest(
        admitted_execution_authority=authority,
        actual_delta=delta,
        approval_scope_boundary=boundary,
        execution_slice=execution_slice,
    )


def _compare(authority, delta, boundary, execution_slice):
    return reconciliation.ScopeComparator().compare(
        _request(authority, delta, boundary, execution_slice)
    )


def _synthetic_boundary_and_slice(
    transaction,
    *,
    existing_rules=None,
    deletion_rules=(),
    slice_existing_rule_ids=None,
    slice_deletion_rule_ids=(),
):
    boundary = transaction.approval_scope_boundary
    execution_slice = transaction.execution_slice
    assert execution_slice is not None

    existing = (
        boundary.existing_entity_rules
        if existing_rules is None
        else tuple(existing_rules)
    )
    existing_ids = (
        tuple(rule.rule_id for rule in existing)
        if slice_existing_rule_ids is None
        else tuple(slice_existing_rule_ids)
    )
    slice_scope = ExecutionSliceScopeRule(
        execution_slice.approved_scope_ref.execution_slice_scope_rule_id,
        execution_slice.host_runtime_ref.document_ref,
        existing_rule_ids=existing_ids,
        deletion_rule_ids=tuple(slice_deletion_rule_ids),
    )
    body_hash = compute_scope_body_hash(
        impact_analysis_fingerprint=boundary.impact_analysis_fingerprint,
        canonical_effect_evidence=boundary.canonical_effect_evidence,
        intent_boundary=boundary.intent_boundary,
        planning_snapshot_ref=boundary.planning_snapshot_ref,
        snapshot_set_ref=boundary.snapshot_set_ref,
        semantic_environment_ref=boundary.semantic_environment_ref,
        existing_entity_rules=existing,
        creation_rules=boundary.creation_rules,
        deletion_rules=tuple(deletion_rules),
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
        existing_entity_rules=existing,
        creation_rules=boundary.creation_rules,
        deletion_rules=tuple(deletion_rules),
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


def _delta_for_scope(
    signed_delta,
    authority,
    boundary,
    execution_slice,
    *changes,
    **overrides,
):
    values = {
        "grant_hash": authority.grant_hash,
        "binding_set_hash": authority.binding_set_hash,
        "execution_slice_hash": execution_slice.execution_slice_hash,
        "changeset_hash": execution_slice.changeset_hash,
        "approved_scope_hash": boundary.scope_hash,
        "host_instance_id": execution_slice.host_runtime_ref.host_instance_id,
        "document_ref": execution_slice.host_runtime_ref.document_ref,
    }
    values.update(overrides)
    return signed_delta(*changes, **values)


def _violation_codes(result) -> tuple[str, ...]:
    return tuple(violation.code for violation in result.violations)


def _matched_rule_ids(result) -> tuple[str, ...]:
    return tuple(match.rule_id for match in result.matched_changes)


def test_bad_actual_delta_hash_wins_before_lineage_mismatch(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    delta = step33_signed_actual_delta(change)
    bad_delta = replace(delta, actual_delta_hash="f" * 64)
    bad_authority = replace(step33_admitted_authority, grant_hash="e" * 64)

    _assert_error(
        "ACTUAL_DELTA_INTEGRITY_INVALID",
        lambda: _compare(bad_authority, bad_delta, boundary, execution_slice),
    )


def test_valid_delta_authority_mismatch_fails_lineage_before_scope_integrity(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    delta = step33_signed_actual_delta(change)
    bad_authority = replace(step33_admitted_authority, binding_set_hash="e" * 64)
    bad_boundary = replace(boundary, scope_body_hash="f" * 64)

    _assert_error(
        "RECONCILIATION_LINEAGE_MISMATCH",
        lambda: _compare(bad_authority, delta, bad_boundary, execution_slice),
    )


def test_bad_boundary_is_wrapped_after_lineage_validation(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    delta = step33_signed_actual_delta(change)
    bad_boundary = replace(boundary, scope_body_hash="f" * 64)

    _assert_error(
        "SCOPE_COMPARISON_INVALID",
        lambda: _compare(
            step33_admitted_authority,
            delta,
            bad_boundary,
            execution_slice,
        ),
        upstream_code="SCOPE_INTEGRITY_INVALID",
    )


def test_bad_execution_slice_is_wrapped_after_boundary_integrity(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    delta = step33_signed_actual_delta(change)
    bad_runtime = HostRuntimeRef(
        execution_slice.host_runtime_ref.host_type,
        execution_slice.host_runtime_ref.host_instance_id,
        "DOC-TAMPERED",
    )
    bad_slice = replace(execution_slice, host_runtime_ref=bad_runtime)

    _assert_error(
        "SCOPE_COMPARISON_INVALID",
        lambda: _compare(step33_admitted_authority, delta, boundary, bad_slice),
        upstream_code="EXECUTION_SLICE_INTEGRITY_INVALID",
    )


@pytest.mark.parametrize(
    ("authority_field", "delta_field"),
    (
        ("grant_hash", "grant_hash"),
        ("binding_set_hash", "binding_set_hash"),
        ("execution_slice_hash", "execution_slice_hash"),
        ("changeset_hash", "changeset_hash"),
        ("approved_scope_hash", "approved_scope_hash"),
        ("host_instance_id", "host_instance_id"),
    ),
)
def test_authority_delta_join_is_exact(
    authority_field,
    delta_field,
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    override = "OTHER-HOST" if delta_field == "host_instance_id" else "e" * 64
    delta = step33_signed_actual_delta(change, **{delta_field: override})

    _assert_error(
        "RECONCILIATION_LINEAGE_MISMATCH",
        lambda: _compare(step33_admitted_authority, delta, boundary, execution_slice),
    )
    assert getattr(step33_admitted_authority, authority_field) != getattr(
        delta,
        delta_field,
    )


def test_slice_document_must_equal_actual_delta_document(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    delta = step33_signed_actual_delta(change, document_ref="DOC-OTHER")

    _assert_error(
        "RECONCILIATION_LINEAGE_MISMATCH",
        lambda: _compare(step33_admitted_authority, delta, boundary, execution_slice),
    )


def test_source_execution_unit_hash_must_belong_to_exact_slice(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
        source_execution_unit_hash="f" * 64,
    )
    delta = step33_signed_actual_delta(change)

    _assert_error(
        "RECONCILIATION_LINEAGE_MISMATCH",
        lambda: _compare(step33_admitted_authority, delta, boundary, execution_slice),
    )


def test_modify_explicit_existing_rule_with_allowed_aspect_is_within_scope(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
        source_execution_unit_hash=execution_slice.execution_units[0].execution_unit_hash,
    )
    delta = step33_signed_actual_delta(change)

    result = _compare(step33_admitted_authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    assert _matched_rule_ids(result) == (boundary.existing_entity_rules[0].rule_id,)
    assert result.violations == ()
    assert result.actual_delta_hash == delta.actual_delta_hash
    assert result.approved_scope_hash == boundary.scope_hash
    assert result.execution_slice_hash == execution_slice.execution_slice_hash
    assert len(result.comparison_hash) == 64


def test_modify_unions_aspects_across_slice_authorized_rules_deterministically(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    rules = (
        ExistingEntityRule(
            "ER-GEOMETRY",
            EntitySelector(entities=("WALL-001",)),
            (CanonicalAspect.GEOMETRY,),
        ),
        ExistingEntityRule(
            "ER-PROPERTIES",
            EntitySelector(entities=("WALL-001",)),
            (CanonicalAspect.PROPERTIES,),
        ),
    )
    boundary, execution_slice = _synthetic_boundary_and_slice(
        step33_single_slice_transaction,
        existing_rules=rules,
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES, CanonicalAspect.GEOMETRY),
    )
    delta = _delta_for_scope(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    assert _matched_rule_ids(result) == ("ER-GEOMETRY", "ER-PROPERTIES")
    assert result.violations == ()


def test_modify_entity_outside_slice_rules_is_scope_breach(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="DOOR-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
    )
    delta = step33_signed_actual_delta(change)

    result = _compare(step33_admitted_authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH
    assert _violation_codes(result) == ("ENTITY_OUTSIDE_SCOPE",)
    assert result.matched_changes == ()


def test_modify_unauthorized_aspect_is_scope_breach(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.GEOMETRY,),
    )
    delta = step33_signed_actual_delta(change)

    result = _compare(step33_admitted_authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH
    assert _violation_codes(result) == ("ASPECT_OUTSIDE_SCOPE",)


def test_modify_predicate_selector_uses_only_semantic_actual_change_context(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    predicate = EntityPredicate(
        all_of=(
            PredicateTerm(
                PredicateField.SEMANTIC_ID,
                PredicateOperator.EQ,
                ("WALL-001",),
            ),
            PredicateTerm(
                PredicateField.CANONICAL_KIND,
                PredicateOperator.IN,
                ("ifc:IfcWall", "ifc:IfcWallStandardCase"),
            ),
            PredicateTerm(
                PredicateField.SOURCE_ENTITY,
                PredicateOperator.EQ,
                ("SOURCE-001",),
            ),
            PredicateTerm(
                PredicateField.DERIVATION_RULE,
                PredicateOperator.EQ,
                ("RULE-PROP",),
            ),
        )
    )
    rule = ExistingEntityRule(
        "ER-PREDICATE",
        EntitySelector(predicate=predicate),
        (CanonicalAspect.PROPERTIES,),
    )
    boundary, execution_slice = _synthetic_boundary_and_slice(
        step33_single_slice_transaction,
        existing_rules=(rule,),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        canonical_kind="ifc:IfcWall",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
        source_semantic_id="SOURCE-001",
        derivation_rule="RULE-PROP",
        host_entity_ref=HostEntityRef("DOC-1", "42", "NATIVE-NOISE"),
    )
    delta = _delta_for_scope(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    assert _matched_rule_ids(result) == ("ER-PREDICATE",)


def test_host_native_metadata_cannot_change_modify_comparison(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    first_change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
        host_entity_ref=HostEntityRef("DOC-1", "42", "LINE"),
    )
    second_change = step33_signed_actual_change(
        change_kind="MODIFY",
        semantic_id="WALL-001",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
        host_entity_ref=HostEntityRef("DOC-1", "99", "ARC"),
    )
    first_delta = step33_signed_actual_delta(first_change)
    second_delta = step33_signed_actual_delta(second_change)

    first = _compare(
        step33_admitted_authority,
        first_delta,
        boundary,
        execution_slice,
    )
    second = _compare(
        step33_admitted_authority,
        second_delta,
        boundary,
        execution_slice,
    )

    assert first_change.actual_change_hash == second_change.actual_change_hash
    assert first_delta.actual_delta_hash == second_delta.actual_delta_hash
    assert first.status is second.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    assert first.matched_changes == second.matched_changes
    assert first.comparison_hash == second.comparison_hash


def test_delete_matching_slice_authorized_rule_is_within_scope(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    deletion_rule = DeletionRule(
        "DR-WALL",
        EntitySelector(entities=("WALL-001",)),
    )
    boundary, execution_slice = _synthetic_boundary_and_slice(
        step33_single_slice_transaction,
        deletion_rules=(deletion_rule,),
        slice_deletion_rule_ids=(deletion_rule.rule_id,),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = step33_signed_actual_change(
        change_kind="DELETE",
        semantic_id="WALL-001",
    )
    delta = _delta_for_scope(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE
    assert _matched_rule_ids(result)[-1] == "DR-WALL"
    assert result.violations == ()


def test_delete_boundary_only_rule_cannot_authorize_current_slice(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    deletion_rule = DeletionRule(
        "DR-WALL",
        EntitySelector(entities=("WALL-001",)),
    )
    boundary, execution_slice = _synthetic_boundary_and_slice(
        step33_single_slice_transaction,
        deletion_rules=(deletion_rule,),
        slice_deletion_rule_ids=(),
    )
    authority = _relineage(step33_admitted_authority, boundary, execution_slice)
    change = step33_signed_actual_change(
        change_kind="DELETE",
        semantic_id="WALL-001",
    )
    delta = _delta_for_scope(
        step33_signed_actual_delta,
        authority,
        boundary,
        execution_slice,
        change,
    )

    result = _compare(authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH
    assert _violation_codes(result) == ("DELETION_FORBIDDEN",)


def test_delete_without_any_rule_is_scope_breach(
    step33_single_slice_transaction,
    step33_admitted_authority,
    step33_signed_actual_change,
    step33_signed_actual_delta,
) -> None:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    boundary = step33_single_slice_transaction.approval_scope_boundary
    change = step33_signed_actual_change(
        change_kind="DELETE",
        semantic_id="WALL-001",
    )
    delta = step33_signed_actual_delta(change)

    result = _compare(step33_admitted_authority, delta, boundary, execution_slice)

    assert result.status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH
    assert _violation_codes(result) == ("DELETION_FORBIDDEN",)
