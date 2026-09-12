from __future__ import annotations

from dataclasses import replace

import pytest
from design_approval_scope import ExecutionSliceScopeRule
from design_execution_planning import ExecutionPlanningError
from design_execution_planning.v2 import _resolve_exact_execution_slice_scope

from tests.materialization_planning.conftest import build_case


def _boundary_with(case, *rules):
    return replace(case.boundary_v2, execution_slice_scopes=tuple(rules))


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ExecutionPlanningError) as exc:
        operation()
    assert exc.value.code == code


def test_exact_document_and_exact_rule_sets_are_required() -> None:
    case = build_case()
    operation = case.changeset.root_operation
    required = operation.scope_rule_ids
    exact = ExecutionSliceScopeRule(
        "EXACT-AUTOCAD",
        "DOC-AUTOCAD",
        existing_rule_ids=required,
    )
    wider = ExecutionSliceScopeRule(
        "WIDER-AUTOCAD",
        "DOC-AUTOCAD",
        existing_rule_ids=(*required, "ER-EXTRA"),
    )
    wrong_document = ExecutionSliceScopeRule(
        "EXACT-OTHER",
        "DOC-OTHER",
        existing_rule_ids=required,
    )

    selected = _resolve_exact_execution_slice_scope(
        operation,
        "DOC-AUTOCAD",
        _boundary_with(case, wider, exact, wrong_document),
    )
    assert selected.slice_scope_rule_id == "EXACT-AUTOCAD"


@pytest.mark.parametrize(
    "candidate",
    (
        ExecutionSliceScopeRule(
            "WIDER",
            "DOC-AUTOCAD",
            existing_rule_ids=("ER-WALL-001", "ER-EXTRA"),
        ),
        ExecutionSliceScopeRule(
            "NARROW",
            "DOC-AUTOCAD",
            existing_rule_ids=(),
        ),
        ExecutionSliceScopeRule(
            "CREATION-SURPLUS",
            "DOC-AUTOCAD",
            existing_rule_ids=("ER-WALL-001",),
            creation_rule_ids=("CR-EXTRA",),
        ),
        ExecutionSliceScopeRule(
            "DELETION-SURPLUS",
            "DOC-AUTOCAD",
            existing_rule_ids=("ER-WALL-001",),
            deletion_rule_ids=("DR-EXTRA",),
        ),
        ExecutionSliceScopeRule(
            "OTHER-DOC",
            "DOC-OTHER",
            existing_rule_ids=("ER-WALL-001",),
        ),
    ),
)
def test_v2_never_falls_back_to_wider_narrower_or_other_document_scope(candidate) -> None:
    case = build_case()
    operation = case.changeset.root_operation

    _assert_code(
        "EXECUTION_SCOPE_UNCOVERED",
        lambda: _resolve_exact_execution_slice_scope(
            operation,
            "DOC-AUTOCAD",
            _boundary_with(case, candidate),
        ),
    )


def test_multiple_exact_scope_rules_are_ambiguous() -> None:
    case = build_case()
    operation = case.changeset.root_operation
    required = operation.scope_rule_ids
    first = ExecutionSliceScopeRule(
        "EXACT-1",
        "DOC-AUTOCAD",
        existing_rule_ids=required,
    )
    second = ExecutionSliceScopeRule(
        "EXACT-2",
        "DOC-AUTOCAD",
        existing_rule_ids=required,
    )

    _assert_code(
        "EXECUTION_SCOPE_AMBIGUOUS",
        lambda: _resolve_exact_execution_slice_scope(
            operation,
            "DOC-AUTOCAD",
            _boundary_with(case, first, second),
        ),
    )


def test_autocad_and_revit_resolve_only_their_own_document_rules() -> None:
    case = build_case()
    operation = case.changeset.root_operation

    autocad = _resolve_exact_execution_slice_scope(
        operation,
        "DOC-AUTOCAD",
        case.boundary_v2,
    )
    revit = _resolve_exact_execution_slice_scope(
        operation,
        "DOC-REVIT",
        case.boundary_v2,
    )

    assert autocad.document_ref == "DOC-AUTOCAD"
    assert revit.document_ref == "DOC-REVIT"
    assert autocad.slice_scope_rule_id != revit.slice_scope_rule_id
