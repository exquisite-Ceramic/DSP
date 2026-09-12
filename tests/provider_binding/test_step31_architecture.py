from __future__ import annotations

import ast
from dataclasses import fields, is_dataclass
from pathlib import Path

from design_provider_binding import (
    ProviderBinding,
    ProviderBindingMaterial,
    ProviderBindingRequest,
    ProviderBindingSetV2,
    ProviderBindingV2,
    ProviderExecutionSnapshotV2,
)

ROOT = Path(__file__).resolve().parents[2]
PRODUCTION_ROOT = ROOT / "platform/provider_binding/src/design_provider_binding"

FORBIDDEN_SYMBOLS = {
    "autocad_sidecar",
    "revit",
    "tekla",
    "host_contracts",
    "HostAdapter",
    "CommandDispatcher",
    "HostCommand",
    "ApprovalRecord",
    "ExecutionGrant",
    "ActualDelta",
    "send_command",
    "command_id",
    "idempotency_key",
}
FORBIDDEN_HOST_CONSTANTS = {"AUTOCAD", "REVIT", "TEKLA"}
FORBIDDEN_ENVELOPE_FIELDS = {
    "approval_id",
    "approval_record",
    "execution_grant",
    "grant_id",
    "actual_delta",
    "host_command",
    "command_id",
    "idempotency_key",
}


def _production_trees():
    for path in sorted(PRODUCTION_ROOT.glob("*.py")):
        yield path, ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _import_parts(node: ast.AST) -> set[str]:
    parts: set[str] = set()
    if isinstance(node, ast.Import):
        for alias in node.names:
            parts.update(alias.name.split("."))
    elif isinstance(node, ast.ImportFrom) and node.module:
        parts.update(node.module.split("."))
    return parts


def test_production_has_no_host_specific_or_step32_runtime_leakage():
    violations: list[str] = []
    for path, tree in _production_trees():
        for node in ast.walk(tree):
            imported = _import_parts(node)
            bad_imports = imported & FORBIDDEN_SYMBOLS
            for marker in sorted(bad_imports):
                violations.append(f"{path.name}: import {marker}")

            if isinstance(node, ast.Name) and node.id in FORBIDDEN_SYMBOLS:
                violations.append(f"{path.name}: name {node.id}")
            if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_SYMBOLS:
                violations.append(f"{path.name}: attribute {node.attr}")
            if (
                isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value in FORBIDDEN_HOST_CONSTANTS
            ):
                violations.append(f"{path.name}: host constant {node.value}")

    assert violations == []


def test_provider_binding_contracts_exclude_governance_and_command_envelopes():
    binding_fields = {field.name for field in fields(ProviderBinding)}
    request_fields = {field.name for field in fields(ProviderBindingRequest)}

    assert binding_fields.isdisjoint(FORBIDDEN_ENVELOPE_FIELDS)
    assert request_fields.isdisjoint(FORBIDDEN_ENVELOPE_FIELDS)
    assert request_fields == {
        "execution_slice",
        "provider_execution_snapshot",
        "admission_time",
    }


def test_adapter_material_cannot_supply_canonical_or_provider_identity():
    assert {field.name for field in fields(ProviderBindingMaterial)} == {
        "native_targets",
        "provider_arguments",
        "provider_preconditions",
        "native_binding_metadata",
    }


def test_v2_value_contracts_are_frozen_and_authority_free():
    for value in (
        ProviderExecutionSnapshotV2,
        ProviderBindingV2,
        ProviderBindingSetV2,
    ):
        assert is_dataclass(value)
        assert value.__dataclass_params__.frozen is True
        assert {
            field.name for field in fields(value)
        }.isdisjoint(FORBIDDEN_ENVELOPE_FIELDS)


def test_v2_never_constructs_fake_v1_execution_slice_or_unit():
    path = PRODUCTION_ROOT / "v2.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "ExecutionSlice" not in constructed
    assert "ExecutionUnit" not in constructed
