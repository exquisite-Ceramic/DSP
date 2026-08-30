from __future__ import annotations

from design_orchestrator.canonical_operations import (
    MVP_CANONICAL_OPERATIONS,
    SET_WALL_THICKNESS_V1,
    SlotBindingClass,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)


def test_set_wall_thickness_v1_is_provider_neutral_and_semantically_verified() -> None:
    op = SET_WALL_THICKNESS_V1

    assert op.canonical_operation == "set_wall_thickness.v1"
    assert op.version == "1.0.0"
    assert op.category == "MODEL_OPERATION"
    assert op.slot_binding_policy["targets"] is SlotBindingClass.CONTEXT
    assert op.slot_binding_policy["thickness"] is SlotBindingClass.INTENT
    assert op.canonical_entity_constraints == ("ifc:IfcWall",)
    assert op.operation_freshness_requirements == (
        {"aspect": "PROPERTIES", "required_state": "FRESH"},
    )
    assert op.effects == ("PROPERTIES",)
    assert op.verification_contract == {
        "type": "SEMANTIC_ASSERTIONS_V1",
        "version": "1.0.0",
        "assertions": [
            {
                "subjects": {"from_argument": "targets"},
                "path": "properties.dsp:WallThickness",
                "operator": "EQUALS_ARGUMENT",
                "argument": "thickness",
            }
        ],
    }

    serialized = repr(op.input_schema) + repr(op.canonical_entity_constraints)
    assert "LWPOLYLINE" not in serialized
    assert "ConstantWidth" not in serialized


def test_set_wall_thickness_v1_binds_semantic_targets_from_context() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    context = ParameterBindingContext(
        context_snapshot_id="CS-STEP34",
        context_snapshot_hash="context-hash-step34",
        document_ref="DOC-STEP34",
        semantic_environment_ref="ENV-STEP34",
        selection=("WALL-001",),
        context_values={},
    )

    bound = binder.bind(
        OperationProposal(
            "set_wall_thickness.v1",
            {"thickness": {"value": 300.0, "unit": "mm"}},
        ),
        context,
    )

    assert dict(bound.arguments) == {
        "targets": ["WALL-001"],
        "thickness": {"value": 300.0, "unit": "mm"},
    }
    assert bound.binding_evidence["targets"].binding_class is SlotBindingClass.CONTEXT
    assert bound.binding_evidence["thickness"].binding_class is SlotBindingClass.INTENT
    assert "LWPOLYLINE" not in repr(bound.arguments)
    assert "ConstantWidth" not in repr(bound.arguments)
