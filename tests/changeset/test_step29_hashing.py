from __future__ import annotations

import importlib


def test_canonical_hash_is_mapping_order_independent() -> None:
    hashing = importlib.import_module("design_changeset.hashing")
    first = {"b": [2, 1], "a": {"y": 2, "x": 1}}
    second = {"a": {"x": 1, "y": 2}, "b": [2, 1]}
    assert hashing.canonical_hash(first) == hashing.canonical_hash(second)


def test_bound_operation_fingerprint_changes_with_material_arguments() -> None:
    hashing = importlib.import_module("design_changeset.hashing")
    first = hashing.compute_bound_operation_fingerprint(
        "move.v1",
        "1.0.0",
        {"targets": ["WALL-001"], "displacement": [100.0, 0.0, 0.0]},
    )
    second = hashing.compute_bound_operation_fingerprint(
        "move.v1",
        "1.0.0",
        {"targets": ["WALL-001"], "displacement": [101.0, 0.0, 0.0]},
    )
    assert first != second


def test_proposed_change_hash_is_mapping_order_independent() -> None:
    hashing = importlib.import_module("design_changeset.hashing")
    first = {
        "affected_semantic_id": "ANNOTATION-001",
        "action": "RECOMPUTE",
        "rule_ref": "RULE-ANN",
    }
    second = {
        "rule_ref": "RULE-ANN",
        "action": "RECOMPUTE",
        "affected_semantic_id": "ANNOTATION-001",
    }
    assert hashing.compute_proposed_change_hash(first) == hashing.compute_proposed_change_hash(second)


def test_canonical_contract_fingerprint_changes_with_effect_authority() -> None:
    hashing = importlib.import_module("design_changeset.hashing")
    base = hashing.compute_contract_definition_fingerprint(
        canonical_operation="move.v1",
        canonical_operation_version="1.0.0",
        argument_schema={"type": "object"},
        effects=("PLACEMENT", "GEOMETRY"),
        verification_contract={"type": "HOST_READ_BACK"},
    )
    changed = hashing.compute_contract_definition_fingerprint(
        canonical_operation="move.v1",
        canonical_operation_version="1.0.0",
        argument_schema={"type": "object"},
        effects=("PLACEMENT",),
        verification_contract={"type": "HOST_READ_BACK"},
    )
    assert base != changed


def test_operation_semantic_hash_has_no_construction_id_parameter() -> None:
    hashing = importlib.import_module("design_changeset.hashing")
    parameters = hashing.compute_operation_semantic_hash.__code__.co_varnames[
        : hashing.compute_operation_semantic_hash.__code__.co_argcount
    ]
    assert "operation_id" not in parameters
    assert "scope_rule_ids" not in parameters
