from __future__ import annotations

from dataclasses import replace

import pytest
from design_approval_scope import (
    CanonicalExistenceEffect,
    CreationRule,
    EntitySelector,
    ExecutionSliceScopeRule,
)
from design_changeset import (
    compute_operation_semantic_hash,
    compute_scope_rule_fingerprint,
)
from design_execution_planning import ExecutionPlanningError
from design_execution_planning.planner import (
    _select_slice_scope,
    _source_operation_hash,
    _validate_scope_binding,
)


def _creation_rule(rule_id: str, canonical_operation: str = "move.v1") -> CreationRule:
    return CreationRule(
        rule_id=rule_id,
        canonical_operation=canonical_operation,
        source_selector=EntitySelector(entities=("WALL-001",)),
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )


def test_scope_must_bind_exact_changeset(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    bad_boundary = replace(boundary, changeset_hash="0" * 64)
    with pytest.raises(ExecutionPlanningError) as exc:
        _validate_scope_binding(changeset, bad_boundary)
    assert exc.value.code == "EXECUTION_SCOPE_MISMATCH"


def test_unknown_operation_scope_rule_fails_closed(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    bad_root = replace(changeset.root_operation, scope_rule_ids=("UNKNOWN-RULE",))
    bad_changeset = replace(changeset, root_operation=bad_root)
    with pytest.raises(ExecutionPlanningError) as exc:
        _validate_scope_binding(bad_changeset, boundary)
    assert exc.value.code == "EXECUTION_SCOPE_MISMATCH"


def test_creation_rule_is_valid_operation_scope_authority(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    creation = _creation_rule("CREATE-WALL")
    root = replace(changeset.root_operation, scope_rule_ids=(creation.rule_id,))
    scoped_changeset = replace(changeset, root_operation=root)
    scoped_boundary = replace(boundary, creation_rules=(creation,))

    rules = _validate_scope_binding(scoped_changeset, scoped_boundary)

    assert rules[creation.rule_id] == creation


def test_duplicate_rule_id_across_existing_and_creation_fails_closed(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    duplicate = _creation_rule(boundary.existing_entity_rules[0].rule_id)
    ambiguous = replace(boundary, creation_rules=(duplicate,))

    with pytest.raises(ExecutionPlanningError) as exc:
        _validate_scope_binding(changeset, ambiguous)

    assert exc.value.code == "EXECUTION_SCOPE_MISMATCH"


def test_tampered_operation_fails_source_hash_reverification(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    rules = _validate_scope_binding(changeset, boundary)
    bad_root = replace(
        changeset.root_operation,
        arguments={"targets": ["WALL-001"], "displacement": [999.0, 0.0, 0.0]},
    )
    with pytest.raises(ExecutionPlanningError) as exc:
        _source_operation_hash(bad_root, rules)
    assert exc.value.code == "EXECUTION_OPERATION_MISMATCH"


def test_creation_source_hash_binds_existence_authority(step30_transaction) -> None:
    changeset, _ = step30_transaction
    creation = _creation_rule("CREATE-WALL")
    root = replace(
        changeset.root_operation,
        expected_effects=(),
        expected_existence_effects=(CanonicalExistenceEffect.CREATE,),
        scope_rule_ids=(creation.rule_id,),
    )
    expected = compute_operation_semantic_hash(
        origin=root.origin,
        canonical_operation=root.canonical_operation,
        canonical_operation_version=root.canonical_operation_version,
        canonical_definition_fingerprint=root.canonical_definition_fingerprint,
        targets=root.targets,
        arguments=root.arguments,
        expected_effects=root.expected_effects,
        scope_rule_fingerprints=(compute_scope_rule_fingerprint(creation),),
        source_evidence=root.source_evidence,
        expected_existence_effects=root.expected_existence_effects,
    )
    root = replace(root, operation_id=f"COP-{expected[:12]}")

    assert _source_operation_hash(root, {creation.rule_id: creation}) == expected


def test_unique_least_authority_scope_is_selected(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    root = changeset.root_operation
    exact = ExecutionSliceScopeRule("SLICE-EXACT", "DOC-1", root.scope_rule_ids)
    wider = ExecutionSliceScopeRule(
        "SLICE-WIDER",
        "DOC-1",
        tuple(sorted(set(root.scope_rule_ids) | {"UNRELATED"})),
    )
    scoped = replace(boundary, execution_slice_scopes=(wider, exact))
    selected = _select_slice_scope(root, "DOC-1", scoped)
    assert selected.slice_scope_rule_id == "SLICE-EXACT"


def test_creation_rule_can_cover_execution_slice(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    root = replace(changeset.root_operation, scope_rule_ids=("CREATE-WALL",))
    creation_scope = ExecutionSliceScopeRule(
        "SLICE-CREATE",
        "DOC-1",
        creation_rule_ids=("CREATE-WALL",),
    )
    scoped = replace(boundary, execution_slice_scopes=(creation_scope,))

    selected = _select_slice_scope(root, "DOC-1", scoped)

    assert selected.slice_scope_rule_id == "SLICE-CREATE"


def test_uncovered_scope_fails_closed(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    scoped = replace(
        boundary,
        execution_slice_scopes=(ExecutionSliceScopeRule("OTHER", "DOC-1", ("OTHER-RULE",)),),
    )
    with pytest.raises(ExecutionPlanningError) as exc:
        _select_slice_scope(changeset.root_operation, "DOC-1", scoped)
    assert exc.value.code == "EXECUTION_SLICE_SCOPE_UNCOVERED"


def test_equal_minimum_different_authority_is_ambiguous(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    root = changeset.root_operation
    first = ExecutionSliceScopeRule(
        "SLICE-A",
        "DOC-1",
        root.scope_rule_ids,
        creation_rule_ids=("CREATE-A",),
    )
    second = ExecutionSliceScopeRule(
        "SLICE-B",
        "DOC-1",
        root.scope_rule_ids,
        deletion_rule_ids=("DELETE-B",),
    )
    scoped = replace(boundary, execution_slice_scopes=(first, second))
    with pytest.raises(ExecutionPlanningError) as exc:
        _select_slice_scope(root, "DOC-1", scoped)
    assert exc.value.code == "EXECUTION_SLICE_SCOPE_AMBIGUOUS"


def test_semantically_duplicate_scope_uses_lexicographically_smallest_id(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    root = changeset.root_operation
    later = ExecutionSliceScopeRule("SLICE-Z", "DOC-1", root.scope_rule_ids)
    earlier = ExecutionSliceScopeRule("SLICE-A", "DOC-1", root.scope_rule_ids)
    scoped = replace(boundary, execution_slice_scopes=(later, earlier))
    selected = _select_slice_scope(root, "DOC-1", scoped)
    assert selected.slice_scope_rule_id == "SLICE-A"
