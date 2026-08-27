from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any

import pytest
from jsonschema import Draft202012Validator

from design_orchestrator.operation_resolver import (
    CapabilityConflictError,
    OperationPolicy,
    OperationResolver,
    ResolutionContext,
    TaskConstraints,
)


@dataclass(frozen=True, slots=True)
class Profile:
    provider_server: str
    provider_tool: str
    canonical_operation: str = "move.v1"
    category: str = "MODEL_OPERATION"
    entity_constraints: tuple[str, ...] = ("LINE", "ARC")
    execution_freshness: tuple[dict[str, Any], ...] = (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    effects: tuple[str, ...] = ("PLACEMENT", "GEOMETRY")
    risk: str | None = "LOW"
    preview_supported: bool = False
    rollback_supported: bool = False
    verification_contract: dict[str, Any] = field(
        default_factory=lambda: {"mode": "HOST_READ_BACK"}
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "targets": {"type": "array", "items": {"type": "string"}},
                "displacement": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
            },
            "required": ["targets", "displacement"],
        }
    )
    output_schema: dict[str, Any] | None = None


def context(
    *providers: str,
    entity_kinds: tuple[str, ...] = ("LINE",),
    policy: OperationPolicy | None = None,
    task: TaskConstraints | None = None,
) -> ResolutionContext:
    return ResolutionContext(
        host_provider_servers=frozenset(providers),
        entity_kinds=frozenset(entity_kinds),
        policy=policy or OperationPolicy(),
        task=task or TaskConstraints(),
    )


def profile_for(
    canonical_operation: str,
    *,
    provider_server: str = "autocad.local",
    provider_tool: str | None = None,
    **overrides: Any,
) -> Profile:
    return Profile(
        provider_server=provider_server,
        provider_tool=provider_tool or canonical_operation.replace(".v1", ""),
        canonical_operation=canonical_operation,
        **overrides,
    )


def test_two_move_providers_aggregate_to_one_canonical_operation() -> None:
    profiles = (
        Profile("autocad.local", "cad.move"),
        Profile("vendor.optimized", "vendor.move"),
    )

    result = OperationResolver().resolve(
        profiles,
        context("autocad.local", "vendor.optimized"),
    )

    assert [item.canonical_operation for item in result.resolved_operations] == ["move.v1"]
    assert len(result.resolved_operations[0].candidate_provider_ids) == 2
    assert len(result.provider_candidates) == 2


def test_host_filter_removes_unavailable_implementation_not_canonical_operation() -> None:
    profiles = (
        Profile("autocad.local", "cad.move"),
        Profile("vendor.optimized", "vendor.move"),
    )

    result = OperationResolver().resolve(profiles, context("autocad.local"))

    assert [item.canonical_operation for item in result.resolved_operations] == ["move.v1"]
    assert {item.provider_server for item in result.provider_candidates.values()} == {
        "autocad.local"
    }


def test_entity_filter_keeps_provider_that_supports_all_current_entity_kinds() -> None:
    profiles = (
        Profile("autocad.local", "cad.move", entity_constraints=("LINE",)),
        Profile("vendor.optimized", "vendor.move", entity_constraints=("ARC",)),
    )

    result = OperationResolver().resolve(
        profiles,
        context("autocad.local", "vendor.optimized", entity_kinds=("ARC",)),
    )

    assert [item.canonical_operation for item in result.resolved_operations] == ["move.v1"]
    assert {item.provider_server for item in result.provider_candidates.values()} == {
        "vendor.optimized"
    }


def test_entity_filter_removes_operation_when_no_provider_supports_selection() -> None:
    profiles = (
        Profile("autocad.local", "cad.move", entity_constraints=("LINE",)),
        Profile("vendor.optimized", "vendor.move", entity_constraints=("ARC",)),
    )

    result = OperationResolver().resolve(
        profiles,
        context("autocad.local", "vendor.optimized", entity_kinds=("LWPOLYLINE",)),
    )

    assert result.resolved_operations == ()
    assert result.provider_candidates == {}


def test_policy_deny_removes_canonical_operation_and_provider_candidates() -> None:
    result = OperationResolver().resolve(
        (Profile("autocad.local", "cad.move"),),
        context(
            "autocad.local",
            policy=OperationPolicy(decisions={"move.v1": "DENY"}),
        ),
    )

    assert result.resolved_operations == ()
    assert result.provider_candidates == {}


def test_policy_approval_required_keeps_operation_with_decision() -> None:
    result = OperationResolver().resolve(
        (Profile("autocad.local", "cad.move"),),
        context(
            "autocad.local",
            policy=OperationPolicy(decisions={"move.v1": "APPROVAL_REQUIRED"}),
        ),
    )

    assert len(result.resolved_operations) == 1
    assert result.resolved_operations[0].policy_decision == "APPROVAL_REQUIRED"


def test_policy_deny_prevents_irrelevant_conflicting_group_from_poisoning_resolution() -> None:
    conflict_a = profile_for(
        "curve.offset.v1",
        provider_server="autocad.local",
        provider_tool="cad.offset",
        input_schema={"type": "object", "properties": {"distance": {"type": "number"}}},
    )
    conflict_b = profile_for(
        "curve.offset.v1",
        provider_server="vendor.optimized",
        provider_tool="vendor.offset",
        input_schema={"type": "object", "properties": {"distance": {"type": "string"}}},
    )
    move = Profile("autocad.local", "cad.move")

    result = OperationResolver().resolve(
        (conflict_a, conflict_b, move),
        context(
            "autocad.local",
            "vendor.optimized",
            policy=OperationPolicy(decisions={"curve.offset.v1": "DENY"}),
        ),
    )

    assert [item.canonical_operation for item in result.resolved_operations] == ["move.v1"]


def test_task_allowlist_is_applied_after_policy() -> None:
    profiles = (
        profile_for("move.v1"),
        profile_for("curve.offset.v1"),
        profile_for("property.update.v1"),
    )
    task = TaskConstraints(
        allowed_operations=frozenset({"move.v1", "property.update.v1"}),
        scores={"move.v1": 0.7, "property.update.v1": 0.8},
    )

    result = OperationResolver().resolve(profiles, context("autocad.local", task=task))

    assert [item.canonical_operation for item in result.resolved_operations] == [
        "property.update.v1",
        "move.v1",
    ]


def test_task_ranking_uses_score_then_canonical_tie_break_and_top_k() -> None:
    operations = tuple(f"op.{index:02d}.v1" for index in range(11))
    profiles = tuple(profile_for(operation) for operation in operations)
    scores = {operation: float(index) for index, operation in enumerate(operations)}
    scores["op.08.v1"] = 10.0
    scores["op.09.v1"] = 10.0
    scores["op.10.v1"] = 9.0

    result = OperationResolver().resolve(
        profiles,
        context(
            "autocad.local",
            task=TaskConstraints(scores=scores, top_k=3),
        ),
    )

    assert [item.canonical_operation for item in result.resolved_operations] == [
        "op.08.v1",
        "op.09.v1",
        "op.10.v1",
    ]
    assert [item.task_score for item in result.resolved_operations] == [10.0, 10.0, 9.0]


@pytest.mark.parametrize("top_k", [2, 11])
def test_task_top_k_must_stay_within_three_to_ten(top_k: int) -> None:
    with pytest.raises(ValueError, match="top_k"):
        TaskConstraints(top_k=top_k)


def test_conflicting_surviving_provider_contracts_fail_closed() -> None:
    profiles = (
        Profile("autocad.local", "cad.move"),
        Profile(
            "vendor.optimized",
            "vendor.move",
            input_schema={"type": "object", "properties": {"distance": {"type": "number"}}},
        ),
    )

    with pytest.raises(CapabilityConflictError, match="input_schema"):
        OperationResolver().resolve(
            profiles,
            context("autocad.local", "vendor.optimized"),
        )


def test_llm_action_space_and_structured_schema_never_expose_provider_identity() -> None:
    profiles = (
        Profile("autocad.local", "cad.move"),
        Profile("vendor.optimized", "vendor.move"),
    )
    result = OperationResolver().resolve(
        profiles,
        context("autocad.local", "vendor.optimized"),
    )

    action_space = result.llm_action_space()
    schema = result.structured_output_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        {
            "operations": [
                {
                    "canonical_operation": "move.v1",
                    "arguments": {"targets": ["semantic-1"], "displacement": [500, 0, 0]},
                }
            ]
        }
    )

    serialized = json.dumps(
        {"action_space": action_space, "schema": schema},
        sort_keys=True,
    )
    assert "move.v1" in serialized
    for forbidden in (
        "provider_server",
        "provider_tool",
        "candidate_provider_ids",
        "autocad.local",
        "vendor.optimized",
        "cad.move",
        "vendor.move",
    ):
        assert forbidden not in serialized


def test_zero_operation_schema_is_valid_and_accepts_only_empty_operation_list() -> None:
    result = OperationResolver().resolve(
        (Profile("autocad.local", "cad.move"),),
        context("unavailable.host"),
    )

    schema = result.structured_output_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate({"operations": []})
    assert list(validator.iter_errors({"operations": [{"canonical_operation": "move.v1"}]}))
