from __future__ import annotations

from dataclasses import is_dataclass
from pathlib import Path

import design_execution_planning
from design_execution_planning import (
    ApprovalScopeRef,
    ApprovedExecutionScopeRef,
    ExecutionDependency,
    ExecutionPlan,
    ExecutionPlanningRequest,
    ExecutionSlice,
    ExecutionUnit,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
)

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "platform" / "execution_planning" / "src" / "design_execution_planning"


def test_step30_has_no_host_provider_governance_or_runtime_leakage() -> None:
    forbidden = (
        "host_contracts",
        "HostCommand",
        "ProviderBinding",
        "provider_id",
        "provider_tool",
        "native_id",
        "ElementId",
        "Handle",
        "internal_unit",
        "binding_set_hash",
        "ApprovalRecord",
        "ExecutionGrant",
        "ActualDelta",
        "VerificationReport",
        "rollback",
        "Saga",
    )
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(PACKAGE.glob("*.py"))
    )
    for marker in forbidden:
        assert marker not in production


def test_step30_fields_keep_runtime_state_and_caller_authority_out() -> None:
    assert "execution_slice_id" not in ExecutionUnit.__dataclass_fields__
    assert "status" not in ExecutionSlice.__dataclass_fields__
    request_fields = set(ExecutionPlanningRequest.__dataclass_fields__)
    assert {
        "provider_id",
        "provider_tool",
        "execution_slice_scope_rule_id",
        "binding_set_hash",
        "approval_id",
        "execution_grant",
    }.isdisjoint(request_fields)


def test_public_value_contracts_are_frozen_dataclasses() -> None:
    for value in (
        HostRuntimeRef,
        RuntimeEntityRoute,
        RuntimeRoutingEvidence,
        ApprovalScopeRef,
        ApprovedExecutionScopeRef,
        ExecutionUnit,
        ExecutionSlice,
        ExecutionDependency,
        ExecutionPlan,
        ExecutionPlanningRequest,
    ):
        assert is_dataclass(value)
        assert value.__dataclass_params__.frozen is True


def test_public_api_is_explicit_unique_and_non_private() -> None:
    assert isinstance(design_execution_planning.__all__, list)
    assert len(design_execution_planning.__all__) == len(set(design_execution_planning.__all__))
    assert all(not name.startswith("_") for name in design_execution_planning.__all__)
