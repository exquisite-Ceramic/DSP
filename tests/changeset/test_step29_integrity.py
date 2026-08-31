from __future__ import annotations

import importlib.util
from dataclasses import replace
from pathlib import Path

import pytest
from design_approval_scope import bind_changeset
from design_changeset import (
    ChangeSetBuilder,
    ChangeSetError,
    validate_changeset_integrity,
)


def _load_fixture(filename: str, module_name: str):
    fixture_path = Path(__file__).with_name(filename)
    spec = importlib.util.spec_from_file_location(module_name, fixture_path)
    assert spec is not None and spec.loader is not None
    fixtures = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixtures)
    return fixtures


def _transaction():
    fixtures = _load_fixture(
        "test_step29_derived_builder.py",
        "_step29_derived_builder_fixture",
    )
    request = fixtures._request()
    changeset = ChangeSetBuilder().build(request)
    boundary = bind_changeset(
        request.approval_scope_definition,
        changeset.changeset_hash,
        "SCOPE-29-INTEGRITY",
    )
    return changeset, boundary


def _creation_transaction():
    fixtures = _load_fixture(
        "test_step36_creation_builder.py",
        "_step36_creation_builder_fixture",
    )
    request = fixtures._request()
    changeset = ChangeSetBuilder().build(request)
    boundary = bind_changeset(
        request.approval_scope_definition,
        changeset.changeset_hash,
        "SCOPE-29-CREATION-INTEGRITY",
    )
    return changeset, boundary


def _assert_invalid(changeset, boundary) -> None:
    with pytest.raises(ChangeSetError) as exc:
        validate_changeset_integrity(changeset, boundary)
    assert exc.value.code == "CHANGESET_INTEGRITY_INVALID"


def test_real_root_and_derived_changeset_passes_integrity():
    changeset, boundary = _transaction()
    validate_changeset_integrity(changeset, boundary)


def test_real_creation_changeset_passes_integrity():
    changeset, boundary = _creation_transaction()
    validate_changeset_integrity(changeset, boundary)


def test_root_operation_body_tamper_fails():
    changeset, boundary = _transaction()
    root = replace(
        changeset.root_operation,
        arguments={
            "targets": ["WALL-001"],
            "displacement": [999.0, 0.0, 0.0],
        },
    )
    _assert_invalid(replace(changeset, root_operation=root), boundary)


def test_derived_operation_body_tamper_fails():
    changeset, boundary = _transaction()
    derived = replace(
        changeset.derived_operations[0],
        arguments={
            "targets": ["ANNOTATION-002"],
            "displacement": [1.0, 0.0, 0.0],
        },
    )
    _assert_invalid(replace(changeset, derived_operations=(derived,)), boundary)


def test_scope_rule_reference_tamper_fails():
    changeset, boundary = _transaction()
    root = replace(changeset.root_operation, scope_rule_ids=("ER-UNKNOWN",))
    _assert_invalid(replace(changeset, root_operation=root), boundary)


def test_dependency_semantics_tamper_fails():
    changeset, boundary = _transaction()
    dependency = replace(changeset.change_dependencies[0], reason_ref="tampered-reason")
    _assert_invalid(replace(changeset, change_dependencies=(dependency,)), boundary)


def test_precondition_tamper_fails():
    changeset, boundary = _transaction()
    precondition = replace(changeset.preconditions[0], evidence_ref="f" * 64)
    tampered = replace(
        changeset,
        preconditions=(precondition, *changeset.preconditions[1:]),
    )
    _assert_invalid(tampered, boundary)


def test_semantic_impact_tamper_fails():
    changeset, boundary = _transaction()
    impact = replace(changeset.semantic_impacts[0], propagation_action="BLOCK")
    tampered = replace(
        changeset,
        semantic_impacts=(impact, *changeset.semantic_impacts[1:]),
    )
    _assert_invalid(tampered, boundary)


def test_validation_task_tamper_fails():
    changeset, boundary = _transaction()
    task = replace(changeset.validation_tasks[0], contract_ref="e" * 64)
    tampered = replace(
        changeset,
        validation_tasks=(task, *changeset.validation_tasks[1:]),
    )
    _assert_invalid(tampered, boundary)


def test_final_changeset_hash_tamper_fails():
    changeset, boundary = _transaction()
    _assert_invalid(replace(changeset, changeset_hash="d" * 64), boundary)
