"""Phase I 物化流水线的 provider-neutral 架构与 V1 兼容性守卫。"""

from __future__ import annotations

import ast
from dataclasses import fields
from pathlib import Path

import pytest
from design_approval_scope import validate_approval_scope_boundary
from design_changeset import validate_changeset_integrity
from design_execution_coordination import CoordinationResult, CoordinationStatus
from design_execution_planning import (
    ExecutionPlanningRequestV2,
    validate_execution_plan_integrity,
)
from design_execution_reconciliation import InMemoryExecutionSagaStore

from tests.execution_coordination.conftest import _build_three_slice_transaction
from tests.execution_reconciliation.test_saga_v2_definition import _definition

ROOT = Path(__file__).resolve().parents[2]
STEP30 = ROOT / "platform/execution_planning/src/design_execution_planning/v2.py"
STEP31 = ROOT / "platform/provider_binding/src/design_provider_binding/v2.py"
STEP37 = (
    ROOT
    / "platform/execution_coordination/src/design_execution_coordination/materialized_coordinator.py"
)
PROVIDER_NEUTRAL_ROOTS = (
    ROOT / "platform/materialization_topology/src",
    ROOT / "platform/materialization_planning/src",
    ROOT / "platform/convergence/src",
)
WORKFLOW_REQUIREMENTS = {
    ".github/workflows/step28-approval-scope.yml": (
        "platform/materialization_topology/**",
        "tests/materialization_topology/**",
    ),
    ".github/workflows/step29-immutable-changeset.yml": (
        "platform/approval_scope/**",
        "tests/approval_scope/**",
        "platform/materialization_topology/**",
        "tests/materialization_topology/**",
    ),
    ".github/workflows/step30-execution-partitioning.yml": (
        "platform/approval_scope/**",
        "tests/approval_scope/**",
        "platform/changeset/**",
        "tests/changeset/**",
        "platform/materialization_topology/**",
        "tests/materialization_topology/**",
        "platform/materialization_planning/**",
        "tests/materialization_planning/**",
    ),
    ".github/workflows/step31-provider-binding.yml": (
        "platform/execution_planning/**",
        "tests/execution_planning/**",
        "platform/materialization_planning/**",
        "tests/materialization_planning/**",
    ),
    ".github/workflows/step32-gateway-authorization.yml": (
        "platform/provider_binding/**",
        "tests/provider_binding/**",
        "platform/materialization_topology/**",
        "tests/materialization_topology/**",
        "platform/materialization_planning/**",
        "tests/materialization_planning/**",
    ),
    ".github/workflows/step33-execution-reconciliation.yml": (
        "platform/approval_scope/**",
        "tests/approval_scope/**",
        "platform/changeset/**",
        "tests/changeset/**",
        "platform/gateway_authorization/**",
        "tests/gateway_authorization/**",
        "platform/materialization_planning/**",
        "tests/materialization_planning/**",
    ),
    ".github/workflows/step37-cross-host-saga-failure-injection.yml": (
        "platform/approval_scope/**",
        "tests/approval_scope/**",
        "platform/materialization_planning/**",
        "tests/materialization_planning/**",
        "platform/convergence/**",
        "tests/convergence/**",
    ),
}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _call_names(path: Path) -> set[str]:
    tree = ast.parse(_source(path))
    result: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        if isinstance(target, ast.Name):
            result.add(target.id)
        elif isinstance(target, ast.Attribute):
            result.add(target.attr)
    return result


def test_step30_has_no_availability_discovery_surface() -> None:
    assert "availability" not in _source(STEP30).casefold()
    assert "availability" not in {field.name for field in fields(ExecutionPlanningRequestV2)}


def test_step31_cannot_construct_new_materialization_intents_or_plans() -> None:
    calls = _call_names(STEP31)
    assert "MaterializationIntent" not in calls
    assert "MaterializationPlan" not in calls


def test_materialized_step37_does_not_clone_canonical_operations_or_materializations() -> None:
    calls = _call_names(STEP37)
    assert calls.isdisjoint(
        {
            "CanonicalChangeOperation",
            "CanonicalChangeSet",
            "MaterializationIntent",
            "MaterializationPlan",
        }
    )


def test_materialized_step37_has_no_parallel_2pc_compensation_or_failure_injection_path() -> None:
    source = _source(STEP37).casefold()
    forbidden = (
        "asyncio",
        "concurrent.futures",
        "threadpoolexecutor",
        "processpoolexecutor",
        "create_task(",
        "gather(",
        "distributed_lock",
        "distributed lock",
        "two_phase_commit",
        "two phase commit",
        "2pc",
        "xa transaction",
        "compensation",
        "inverse_command",
        "inverse command",
        "failure_injection",
        "debug_fail",
        "force_failure",
    )
    for marker in forbidden:
        assert marker not in source


def test_topology_planning_and_convergence_core_have_no_host_native_vocabulary() -> None:
    source = "\n".join(
        _source(path)
        for root in PROVIDER_NEUTRAL_ROOTS
        for path in sorted(root.rglob("*.py"))
    )
    forbidden = (
        "AutoCAD",
        "LWPOLYLINE",
        "ConstantWidth",
        "Handle",
        "Autodesk.Revit",
        "ElementId",
        "UniqueId",
        "WallType",
        "304.8",
    )
    for marker in forbidden:
        assert marker not in source


def test_v1_step28_step30_and_coordination_contracts_remain_usable() -> None:
    transaction = _build_three_slice_transaction()
    validate_approval_scope_boundary(transaction.approval_scope_boundary)
    validate_changeset_integrity(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
    )
    validate_execution_plan_integrity(transaction.execution_plan)

    assert tuple(item.value for item in CoordinationStatus) == (
        "SUCCEEDED",
        "FAILED",
        "PARTIALLY_COMMITTED",
        "RECOVERY_REQUIRED",
    )
    assert {field.name for field in fields(CoordinationResult)} == {
        "saga_id",
        "saga_revision",
        "status",
        "active_slice_hash",
        "failure_ref",
    }


def test_v1_step33_store_remains_v1_typed() -> None:
    _, definition_v2 = _definition()
    with pytest.raises(TypeError):
        InMemoryExecutionSagaStore().create_saga(definition_v2)


def test_legacy_step28_to_step37_workflows_watch_direct_v2_dependencies_only() -> None:
    for relative_path, required_paths in WORKFLOW_REQUIREMENTS.items():
        source = _source(ROOT / relative_path)
        for required_path in required_paths:
            quoted = f'- "{required_path}"'
            assert source.count(quoted) == 2, (
                f"{relative_path} must watch {required_path} in both push and pull_request"
            )
        assert "self-hosted" not in source
        assert "DSP_PHASE_I_LIVE" not in source
        assert "DSP_REVIT_LIVE" not in source
