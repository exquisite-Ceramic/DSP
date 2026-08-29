from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Iterable

import pytest
from jsonschema import Draft202012Validator

from autocad_sidecar.capability.profile import parse_design_capability
from autocad_sidecar.mcp_server import build_tool_definitions
from design_orchestrator.canonical_operations import (
    CanonicalOperationDefinition,
    MOVE_V1,
)
from design_orchestrator.operation_resolver import (
    CapabilityConflictError,
    OperationPolicy,
    OperationResolver,
    ResolutionContext,
    TaskConstraints,
)


PROVIDER_MOVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "handles": {"type": "array", "items": {"type": "string"}},
        "dx": {"type": "number"},
        "dy": {"type": "number"},
        "dz": {"type": "number"},
        "idempotency_key": {"type": ["string", "null"]},
        "revision": {"type": ["integer", "null"]},
    },
    "required": ["handles", "dx", "dy"],
}

GENERIC_CANONICAL_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "targets": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        }
    },
    "required": ["targets"],
    "additionalProperties": False,
}


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
        default_factory=lambda: {"type": "HOST_READ_BACK"}
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: json.loads(json.dumps(PROVIDER_MOVE_SCHEMA))
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


def definition_for(canonical_operation: str) -> CanonicalOperationDefinition:
    if canonical_operation == "move.v1":
        return MOVE_V1
    return CanonicalOperationDefinition(
        canonical_operation=canonical_operation,
        category="MODEL_OPERATION",
        input_schema=json.loads(json.dumps(GENERIC_CANONICAL_SCHEMA)),
        verification_contract={"type": "HOST_READ_BACK"},
    )


def resolver_for(profiles: Iterable[Profile]) -> OperationResolver:
    profile_tuple = tuple(profiles)
    definitions = tuple(
        definition_for(canonical_operation)
        for canonical_operation in sorted(
            {profile.canonical_operation for profile in profile_tuple}
        )
    )
    return OperationResolver(definitions)


def test_two_move_providers_aggregate_to_one_canonical_operation() -> None:
    profiles = (
        Profile("autocad.local", "cad.move"),
        Profile("vendor.optimized", "vendor.move"),
    )

    result = resolver_for(profiles).resolve(
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

    result = resolver_for(profiles).resolve(profiles, context("autocad.local"))

    assert [item.canonical_operation for item in result.resolved_operations] == ["move.v1"]
    assert {item.provider_server for item in result.provider_candidates.values()} == {
        "autocad.local"
    }


def test_entity_filter_keeps_provider_that_supports_all_current_entity_kinds() -> None:
    profiles = (
        Profile("autocad.local", "cad.move", entity_constraints=("LINE",)),
        Profile("vendor.optimized", "vendor.move", entity_constraints=("ARC",)),
    )

    result = resolver_for(profiles).resolve(
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

    result = resolver_for(profiles).resolve(
        profiles,
        context("autocad.local", "vendor.optimized", entity_kinds=("LWPOLYLINE",)),
    )

    assert result.resolved_operations == ()
    assert result.provider_candidates == {}


def test_policy_deny_removes_canonical_operation_and_provider_candidates() -> None:
    profiles = (Profile("autocad.local", "cad.move"),)
    result = resolver_for(profiles).resolve(
        profiles,
        context(
            "autocad.local",
            policy=OperationPolicy(decisions={"move.v1": "DENY"}),
        ),
    )

    assert result.resolved_operations == ()
    assert result.provider_candidates == {}


def test_policy_approval_required_keeps_operation_with_decision() -> None:
    profiles = (Profile("autocad.local", "cad.move"),)
    result = resolver_for(profiles).resolve(
        profiles,
        context(
            "autocad.local",
            policy=OperationPolicy(decisions={"move.v1": "APPROVAL_REQUIRED"}),
        ),
    )

    assert len(result.resolved_operations) == 1
    assert result.resolved_operations[0].policy_decision == "APPROVAL_REQUIRED"


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

    result = resolver_for(profiles).resolve(
        profiles,
        context("autocad.local", task=task),
    )

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

    result = resolver_for(profiles).resolve(
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


def test_different_provider_input_schemas_share_one_canonical_schema() -> None:
    profiles = (
        Profile("autocad.local", "cad.move", input_schema=PROVIDER_MOVE_SCHEMA),
        Profile(
            "vendor.optimized",
            "vendor.move",
            input_schema={
                "type": "object",
                "properties": {
                    "entity_ids": {"type": "array", "items": {"type": "integer"}},
                    "vector": {"type": "array", "items": {"type": "number"}},
                },
                "required": ["entity_ids", "vector"],
            },
        ),
    )

    result = resolver_for(profiles).resolve(
        profiles,
        context("autocad.local", "vendor.optimized"),
    )

    assert len(result.resolved_operations) == 1
    assert result.resolved_operations[0].input_schema == MOVE_V1.input_schema
    assert {profile.provider_tool for profile in result.provider_candidates.values()} == {
        "cad.move",
        "vendor.move",
    }


def test_duplicate_canonical_definitions_fail_closed() -> None:
    duplicate = CanonicalOperationDefinition(
        canonical_operation="move.v1",
        category="MODEL_OPERATION",
        input_schema={"type": "object", "properties": {}},
        verification_contract={"type": "NONE"},
    )

    with pytest.raises(CapabilityConflictError, match="duplicate canonical operation"):
        OperationResolver((MOVE_V1, duplicate))


def test_provider_without_platform_canonical_definition_is_not_exposed() -> None:
    profile = profile_for("vendor.unknown.v1")

    result = OperationResolver((MOVE_V1,)).resolve(
        (profile,),
        context("autocad.local"),
    )

    assert result.resolved_operations == ()
    assert result.provider_candidates == {}


def test_real_autocad_move_provider_never_leaks_host_arguments_to_llm() -> None:
    tools = {tool["name"]: tool for tool in build_tool_definitions()}
    profile = parse_design_capability(
        tools["cad.move"],
        provider_server="autocad.local",
    )

    result = OperationResolver((MOVE_V1,)).resolve(
        (profile,),
        context("autocad.local"),
    )

    assert "handles" in profile.input_schema["properties"]
    assert "idempotency_key" in profile.input_schema["properties"]
    assert result.resolved_operations[0].input_schema == MOVE_V1.input_schema

    action_space = result.llm_action_space()
    schema = result.structured_output_schema()
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(
        {
            "operations": [
                {
                    "canonical_operation": "move.v1",
                    "arguments": {
                        "targets": ["semantic-1"],
                        "displacement": [500, 0, 0],
                    },
                }
            ]
        }
    )

    serialized = json.dumps(
        {"action_space": action_space, "schema": schema},
        sort_keys=True,
    )
    for required in ("move.v1", "targets", "displacement"):
        assert required in serialized
    for forbidden in (
        "provider_server",
        "provider_tool",
        "candidate_provider_ids",
        "autocad.local",
        "cad.move",
        "handles",
        "dx",
        "dy",
        "dz",
        "idempotency_key",
        "revision",
    ):
        assert forbidden not in serialized


def test_llm_action_space_and_structured_schema_never_expose_provider_identity() -> None:
    profiles = (
        Profile("autocad.local", "cad.move"),
        Profile("vendor.optimized", "vendor.move"),
    )
    result = resolver_for(profiles).resolve(
        profiles,
        context("autocad.local", "vendor.optimized"),
    )

    action_space = result.llm_action_space()
    schema = result.structured_output_schema()
    Draft202012Validator.check_schema(schema)

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
    profiles = (Profile("autocad.local", "cad.move"),)
    result = resolver_for(profiles).resolve(
        profiles,
        context("unavailable.host"),
    )

    schema = result.structured_output_schema()
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    validator.validate({"operations": []})
    assert list(validator.iter_errors({"operations": [{"canonical_operation": "move.v1"}]}))


def test_canonical_operation_owns_task_freshness_not_provider_union() -> None:
    placement = {"aspect": "PLACEMENT", "required_state": "FRESH"}
    exact_geometry = {
        "aspect": "GEOMETRY",
        "required_state": "FRESH",
        "geometry_level": "EXACT",
    }
    profiles = (
        Profile(
            "autocad.local",
            "cad.move",
            execution_freshness=(placement,),
        ),
        Profile(
            "vendor.optimized",
            "vendor.move",
            execution_freshness=(placement, exact_geometry),
        ),
    )

    result = OperationResolver((MOVE_V1,)).resolve(
        profiles,
        context("autocad.local", "vendor.optimized"),
    )
    resolved = result.resolved_operations[0]
    expected = (placement,)

    assert resolved.operation_freshness_requirements == expected
    assert result.llm_action_space()[0]["operation_freshness_requirements"] == list(expected)

    vendor = next(
        profile
        for profile in result.provider_candidates.values()
        if profile.provider_server == "vendor.optimized"
    )
    assert vendor.execution_freshness == (placement, exact_geometry)


def test_effects_do_not_implicitly_create_task_freshness_requirements() -> None:
    result = OperationResolver((MOVE_V1,)).resolve(
        (Profile("autocad.local", "cad.move"),),
        context("autocad.local"),
    )
    resolved = result.resolved_operations[0]

    assert resolved.operation_freshness_requirements == (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    assert set(resolved.effects) == {"PLACEMENT", "GEOMETRY"}
