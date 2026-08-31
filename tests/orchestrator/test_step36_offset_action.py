from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from design_orchestrator.canonical_operations import (
    CanonicalCreationContract,
    CanonicalExistenceEffect,
    CanonicalOperationDefinition,
    MVP_CANONICAL_OPERATIONS,
    OFFSET_V1,
    SlotBindingClass,
)
from design_orchestrator.operation_resolver import (
    ClassificationGuarantee,
    OperationResolver,
    ResolutionContext,
    SemanticEligibilityContext,
    SemanticEligibilityEntity,
)
from design_orchestrator.parameter_binder import (
    OFFSET_V1_BINDING_RECIPE,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)


@dataclass(frozen=True, slots=True)
class OffsetProfile:
    provider_server: str = "autocad.local"
    provider_tool: str = "cad.offset"
    canonical_operation: str = "offset.v1"
    category: str = "MODEL_OPERATION"
    entity_constraints: tuple[str, ...] = ("LWPOLYLINE",)
    execution_freshness: tuple[dict[str, Any], ...] = ()
    effects: tuple[Any, ...] = ()
    risk: str | None = "MEDIUM"
    preview_supported: bool = False
    rollback_supported: bool = False
    verification_contract: dict[str, Any] = field(default_factory=dict)
    input_schema: dict[str, Any] = field(
        default_factory=lambda: {
            "type": "object",
            "properties": {
                "handles": {"type": "array", "items": {"type": "string"}},
                "distance": {"type": "number"},
                "sidePoint": {"type": "object"},
            },
        }
    )
    output_schema: dict[str, Any] | None = None


def _offset_context() -> ResolutionContext:
    semantic_context = SemanticEligibilityContext(
        context_snapshot_id="CS-step36",
        context_snapshot_hash="hash-step36",
        document_ref="DOC-A",
        semantic_environment_ref="ENV-A",
        entities=(
            SemanticEligibilityEntity(
                semantic_id="WALL-001",
                canonical_classifications=("ifc:IfcWall",),
                classification_guarantee=ClassificationGuarantee(True),
            ),
        ),
    )
    return ResolutionContext(
        host_provider_servers=frozenset({"autocad.local"}),
        semantic_context=semantic_context,
    )


def test_offset_v1_has_closed_create_envelope_and_provider_neutral_intent() -> None:
    assert OFFSET_V1.canonical_operation == "offset.v1"
    assert OFFSET_V1.version == "1.0.0"
    assert OFFSET_V1.category == "MODEL_OPERATION"
    assert OFFSET_V1.effects == ()
    assert OFFSET_V1.existence_effects == (CanonicalExistenceEffect.CREATE,)
    assert OFFSET_V1.creation_contract == CanonicalCreationContract(
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )
    assert OFFSET_V1.slot_binding_policy["targets"] is SlotBindingClass.CONTEXT
    assert OFFSET_V1.slot_binding_policy["distance"] is SlotBindingClass.INTENT
    assert OFFSET_V1.slot_binding_policy["side_point"] is SlotBindingClass.INTENT
    assert OFFSET_V1.input_schema["properties"]["targets"]["maxItems"] == 1
    assert OFFSET_V1.canonical_entity_constraints == ("ifc:IfcWall",)
    assert OFFSET_V1.verification_contract == {}
    assert OFFSET_V1 in MVP_CANONICAL_OPERATIONS

    material = repr(OFFSET_V1.input_schema) + repr(OFFSET_V1.canonical_entity_constraints)
    assert "LWPOLYLINE" not in material
    assert "GetOffsetCurves" not in material
    assert "Handle" not in material


def test_model_operation_requires_aspect_or_existence_effect() -> None:
    with pytest.raises(ValueError, match="effect"):
        CanonicalOperationDefinition(
            canonical_operation="invalid.no-effect.v1",
            version="1.0.0",
            title="Invalid",
            description="No effect authority.",
            category="MODEL_OPERATION",
            input_schema={"type": "object", "properties": {}},
            slot_binding_policy={},
            verification_contract={},
        )


def test_create_requires_creation_contract() -> None:
    with pytest.raises(ValueError, match="creation_contract"):
        CanonicalOperationDefinition(
            canonical_operation="invalid.create.v1",
            version="1.0.0",
            title="Invalid create",
            description="CREATE without a closed envelope.",
            category="MODEL_OPERATION",
            input_schema={"type": "object", "properties": {}},
            slot_binding_policy={},
            verification_contract={},
            existence_effects=(CanonicalExistenceEffect.CREATE,),
        )


def test_resolver_exposes_platform_owned_create_semantics_not_native_constraints() -> None:
    result = OperationResolver((OFFSET_V1,)).resolve((OffsetProfile(),), _offset_context())

    assert len(result.resolved_operations) == 1
    resolved = result.resolved_operations[0]
    assert resolved.canonical_operation == "offset.v1"
    assert resolved.existence_effects == (CanonicalExistenceEffect.CREATE,)
    assert resolved.canonical_entity_constraints == ("ifc:IfcWall",)

    action = result.llm_action_space()[0]
    assert action["existence_effects"] == ["CREATE"]
    serialized = repr(action)
    assert "LWPOLYLINE" not in serialized
    assert "cad.offset" not in serialized


def test_parameter_binder_binds_only_source_target_for_offset() -> None:
    binder = ParameterBinder((OFFSET_V1,), (OFFSET_V1_BINDING_RECIPE,))
    bound = binder.bind(
        OperationProposal(
            canonical_operation="offset.v1",
            intent_arguments={
                "distance": {"value": 300.0, "unit": "mm"},
                "side_point": {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"},
            },
        ),
        ParameterBindingContext(
            context_snapshot_id="CS-step36",
            context_snapshot_hash="hash-step36",
            document_ref="DOC-A",
            semantic_environment_ref="ENV-A",
            selection=("WALL-001",),
        ),
    )

    assert dict(bound.arguments) == {
        "targets": ["WALL-001"],
        "distance": {"value": 300.0, "unit": "mm"},
        "side_point": {"x": 5000.0, "y": 2000.0, "z": 0.0, "unit": "mm"},
    }
    assert bound.binding_evidence["targets"].source == "ParameterBindingContext.selection"
