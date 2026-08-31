from __future__ import annotations

from dataclasses import dataclass, field, fields
import json
from typing import Any

import pytest

from design_orchestrator.canonical_operations import (
    CanonicalOperationDefinition,
    MOVE_V1,
    SlotBindingClass,
)
import design_orchestrator.operation_resolver as resolver_module
from design_orchestrator.operation_resolver import OperationResolver, ResolutionContext


@dataclass(frozen=True, slots=True)
class Profile:
    provider_server: str = "autocad.local"
    provider_tool: str = "cad.test"
    canonical_operation: str = "test.v1"
    category: str = "MODEL_OPERATION"
    entity_constraints: tuple[str, ...] = ("LINE", "LWPOLYLINE", "ARC")
    execution_freshness: tuple[dict[str, Any], ...] = ()
    effects: tuple[str, ...] = ()
    risk: str | None = "LOW"
    preview_supported: bool = False
    rollback_supported: bool = False
    verification_contract: dict[str, Any] = field(
        default_factory=lambda: {"type": "HOST_READ_BACK"}
    )
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {"handles": {"type": "array", "items": {"type": "string"}}},
            "required": ["handles"],
        }
    )
    output_schema: dict[str, Any] | None = None


def _api(name: str):
    value = getattr(resolver_module, name, None)
    if value is None:
        pytest.fail(f"Step24 API {name} is not implemented")
    return value


def _definition(
    *,
    canonical_operation: str = "test.v1",
    canonical_entity_constraints: tuple[str, ...] = (),
) -> CanonicalOperationDefinition:
    return CanonicalOperationDefinition(
        canonical_operation=canonical_operation,
        version="1.0.0",
        title="Step24 test operation",
        description="Canonical operation used to freeze Step24 eligibility behavior.",
        category="MODEL_OPERATION",
        input_schema={
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
        },
        slot_binding_policy={"targets": SlotBindingClass.CONTEXT},
        canonical_entity_constraints=canonical_entity_constraints,
        effects=("PROPERTIES",),
        verification_contract={"type": "HOST_READ_BACK"},
    )


def _semantic_context(
    *classifications: tuple[str, ...],
    machine_decision_supported: bool | None = True,
):
    ClassificationGuarantee = _api("ClassificationGuarantee")
    SemanticEligibilityEntity = _api("SemanticEligibilityEntity")
    SemanticEligibilityContext = _api("SemanticEligibilityContext")

    entities = tuple(
        SemanticEligibilityEntity(
            semantic_id=f"semantic-{index}",
            canonical_classifications=terms,
            classification_guarantee=(
                None
                if machine_decision_supported is None
                else ClassificationGuarantee(
                    machine_decision_supported=machine_decision_supported
                )
            ),
        )
        for index, terms in enumerate(classifications, start=1)
    )
    return SemanticEligibilityContext(
        context_snapshot_id="CS-step24",
        context_snapshot_hash="snapshot-hash-step24",
        document_ref="document-1",
        semantic_environment_ref="semantic-env@hash-step24",
        entities=entities,
    )


def _resolution_context(*providers: str, semantic_context=None) -> ResolutionContext:
    if semantic_context is None:
        semantic_context = _semantic_context((), machine_decision_supported=None)
    return ResolutionContext(
        host_provider_servers=frozenset(providers),
        semantic_context=semantic_context,
    )


def test_resolution_context_replaces_native_entity_kinds_with_semantic_context() -> None:
    names = {item.name for item in fields(ResolutionContext)}

    assert "semantic_context" in names
    assert "entity_kinds" not in names


def test_semantic_eligibility_context_is_snapshot_bound_and_rejects_native_terms() -> None:
    SemanticEligibilityEntity = _api("SemanticEligibilityEntity")

    with pytest.raises(ValueError, match="canonical classification"):
        SemanticEligibilityEntity(
            semantic_id="semantic-1",
            canonical_classifications=("LINE",),
            classification_guarantee=None,
        )

    context = _semantic_context(("ifc:IfcWall", "metro:StationWall"))
    assert context.context_snapshot_id == "CS-step24"
    assert context.context_snapshot_hash == "snapshot-hash-step24"
    assert context.document_ref == "document-1"
    assert context.semantic_environment_ref == "semantic-env@hash-step24"
    assert context.entities[0].canonical_classifications == (
        "ifc:IfcWall",
        "metro:StationWall",
    )


def test_empty_canonical_constraints_do_not_require_classification() -> None:
    profile = Profile(
        provider_tool="cad.move",
        canonical_operation="move.v1",
        entity_constraints=("ARC",),
    )
    semantic_context = _semantic_context((), machine_decision_supported=None)

    result = OperationResolver((MOVE_V1,)).resolve(
        (profile,),
        _resolution_context("autocad.local", semantic_context=semantic_context),
    )

    assert [item.canonical_operation for item in result.resolved_operations] == ["move.v1"]
    assert len(result.provider_candidates) == 1


def test_exact_canonical_term_match_controls_eligibility_not_provider_native_constraints() -> None:
    definition = _definition(canonical_entity_constraints=("ifc:IfcWall",))
    profile = Profile(entity_constraints=("LINE",))
    semantic_context = _semantic_context(("ifc:IfcWall",))

    result = OperationResolver((definition,)).resolve(
        (profile,),
        _resolution_context("autocad.local", semantic_context=semantic_context),
    )

    assert [item.canonical_operation for item in result.resolved_operations] == ["test.v1"]
    resolved = result.resolved_operations[0]
    assert resolved.canonical_entity_constraints == ("ifc:IfcWall",)
    assert result.provider_candidates[resolved.candidate_provider_ids[0]].entity_constraints == (
        "LINE",
    )

    serialized = json.dumps(result.llm_action_space(), sort_keys=True)
    assert "canonical_entity_constraints" in serialized
    assert "ifc:IfcWall" in serialized
    assert "LINE" not in serialized


def test_exact_term_v1_does_not_infer_ifc_inheritance() -> None:
    definition = _definition(canonical_entity_constraints=("ifc:IfcElement",))
    semantic_context = _semantic_context(("ifc:IfcWall",))

    result = OperationResolver((definition,)).resolve(
        (Profile(),),
        _resolution_context("autocad.local", semantic_context=semantic_context),
    )

    assert result.resolved_operations == ()
    assert result.provider_candidates == {}


@pytest.mark.parametrize(
    ("classifications", "machine_decision_supported"),
    [
        ((), True),
        (("ifc:IfcWall",), None),
        (("ifc:IfcWall",), False),
    ],
)
def test_nonempty_canonical_constraints_fail_closed_without_machine_usable_classification(
    classifications: tuple[str, ...],
    machine_decision_supported: bool | None,
) -> None:
    definition = _definition(canonical_entity_constraints=("ifc:IfcWall",))
    semantic_context = _semantic_context(
        classifications,
        machine_decision_supported=machine_decision_supported,
    )

    result = OperationResolver((definition,)).resolve(
        (Profile(),),
        _resolution_context("autocad.local", semantic_context=semantic_context),
    )

    assert result.resolved_operations == ()
    assert result.provider_candidates == {}


def test_every_context_entity_must_match_a_canonical_constraint() -> None:
    definition = _definition(
        canonical_entity_constraints=("ifc:IfcWall", "metro:StationWall")
    )
    semantic_context = _semantic_context(
        ("ifc:IfcWall",),
        ("ifc:IfcDoor",),
    )

    result = OperationResolver((definition,)).resolve(
        (Profile(),),
        _resolution_context("autocad.local", semantic_context=semantic_context),
    )

    assert result.resolved_operations == ()
    assert result.provider_candidates == {}
