from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from design_orchestrator.operation_resolver import OperationResolver, ResolutionContext


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


def context(*providers: str, entity_kinds: tuple[str, ...] = ("LINE",)) -> ResolutionContext:
    return ResolutionContext(
        host_provider_servers=frozenset(providers),
        entity_kinds=frozenset(entity_kinds),
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
