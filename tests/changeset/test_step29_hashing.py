from __future__ import annotations

import importlib
import importlib.util
from dataclasses import replace
from pathlib import Path

from design_approval_scope import bind_topology_snapshot_v2
from design_changeset import ChangeSetBuilder


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


def _load_builder_fixture():
    fixture_path = Path(__file__).with_name("test_step29_builder.py")
    spec = importlib.util.spec_from_file_location("_step29_builder_v2_fixture", fixture_path)
    assert spec is not None and spec.loader is not None
    fixture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fixture)
    return fixture


def test_topology_bound_v2_scope_uses_existing_changeset_hash_pipeline() -> None:
    fixture = _load_builder_fixture()
    request = fixture._request()
    scope_v2 = bind_topology_snapshot_v2(
        request.approval_scope_definition,
        topology_snapshot_hash="a" * 64,
    )
    changeset = ChangeSetBuilder().build(
        replace(request, approval_scope_definition=scope_v2)
    )
    assert changeset.approval_scope_definition_ref.scope_body_hash == scope_v2.scope_body_hash
