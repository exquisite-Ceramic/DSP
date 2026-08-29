from __future__ import annotations

import importlib
from dataclasses import FrozenInstanceError

import pytest


def test_runtime_ref_is_frozen() -> None:
    module = importlib.import_module("design_execution_planning")
    ref = module.HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    with pytest.raises(FrozenInstanceError):
        ref.document_ref = "DOC-2"


def test_unit_has_no_reverse_slice_reference() -> None:
    module = importlib.import_module("design_execution_planning")
    assert "execution_slice_id" not in module.ExecutionUnit.__dataclass_fields__


def test_request_cannot_choose_provider_or_slice_scope() -> None:
    module = importlib.import_module("design_execution_planning")
    fields = set(module.ExecutionPlanningRequest.__dataclass_fields__)
    assert {"provider_id", "provider_tool", "execution_slice_scope_rule_id"}.isdisjoint(fields)


def test_runtime_routes_normalize_to_tuple_without_losing_duplicates() -> None:
    module = importlib.import_module("design_execution_planning")
    route = module.RuntimeEntityRoute(
        "WALL-001",
        module.HostRuntimeRef("REVIT", "RVT-01", "DOC-1"),
    )
    evidence = module.RuntimeRoutingEvidence("RRS-1", [route, route], "a" * 64)
    assert evidence.routes == (route, route)


def test_execution_unit_arguments_are_defensively_read_only() -> None:
    module = importlib.import_module("design_execution_planning")
    source = {"targets": ["WALL-001"], "displacement": [100.0, 0.0, 0.0]}
    unit = module.ExecutionUnit(
        execution_unit_id="EU-123",
        source_operation_id="COP-123",
        source_operation_hash="a" * 64,
        canonical_operation="move.v1",
        canonical_operation_version="1.0.0",
        canonical_definition_fingerprint="b" * 64,
        targets=("WALL-001",),
        arguments=source,
        preconditions=(),
        expected_effects=("PLACEMENT", "GEOMETRY"),
        execution_unit_hash="c" * 64,
    )
    source["targets"].append("WALL-002")
    assert unit.arguments["targets"] == ["WALL-001"]
    with pytest.raises(TypeError):
        unit.arguments["new"] = True


def test_hash_contracts_require_lowercase_sha256() -> None:
    module = importlib.import_module("design_execution_planning")
    with pytest.raises(ValueError):
        module.RuntimeRoutingEvidence("RRS-1", (), "NOT-A-DIGEST")
