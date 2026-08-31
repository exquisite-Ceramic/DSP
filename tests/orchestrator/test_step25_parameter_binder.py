from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from design_orchestrator.canonical_operations import (
    CanonicalOperationDefinition,
    MVP_CANONICAL_OPERATIONS,
    SlotBindingClass,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    BindingError,
    BindingResolverKind,
    OperationBindingRecipe,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
    SlotBindingRecipe,
)


def _context(
    *,
    selection: tuple[str, ...] = ("S-001", "S-002"),
    context_values: dict[str, object] | None = None,
) -> ParameterBindingContext:
    return ParameterBindingContext(
        context_snapshot_id="CS-step25",
        context_snapshot_hash="snapshot-hash-step25",
        document_ref="drawing-001",
        semantic_environment_ref="semantic-env@step25",
        selection=selection,
        context_values={} if context_values is None else context_values,
    )


def _definition(
    *,
    canonical_operation: str,
    properties: dict[str, dict[str, object]],
    required: list[str],
    slot_binding_policy: dict[str, SlotBindingClass],
    operation_freshness_requirements: tuple[dict[str, object], ...] = (),
) -> CanonicalOperationDefinition:
    return CanonicalOperationDefinition(
        canonical_operation=canonical_operation,
        version="1.0.0",
        title=canonical_operation,
        description=f"Synthetic contract for {canonical_operation}",
        category="MODEL_OPERATION",
        input_schema={
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
        slot_binding_policy=slot_binding_policy,
        verification_contract={"type": "HOST_READ_BACK"},
        operation_freshness_requirements=operation_freshness_requirements,
        effects=("PROPERTIES",),
    )


def test_move_binds_context_targets_and_intent_displacement() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)

    bound = binder.bind(
        OperationProposal("move.v1", {"displacement": [100, 0, 0]}),
        _context(),
    )

    assert bound.operation.canonical_operation == "move.v1"
    assert bound.operation.version == "1.0.0"
    assert dict(bound.arguments) == {
        "targets": ["S-001", "S-002"],
        "displacement": [100, 0, 0],
    }
    assert bound.context_snapshot_ref.context_snapshot_id == "CS-step25"
    assert bound.context_snapshot_ref.context_snapshot_hash == "snapshot-hash-step25"
    assert bound.context_snapshot_ref.document_ref == "drawing-001"
    assert bound.semantic_environment_ref == "semantic-env@step25"
    assert bound.binding_evidence["targets"].binding_class is SlotBindingClass.CONTEXT
    assert bound.binding_evidence["targets"].source == "ContextSnapshot.selection"
    assert bound.binding_evidence["displacement"].binding_class is SlotBindingClass.INTENT
    assert (
        bound.binding_evidence["displacement"].source
        == "OperationProposal.intent_arguments"
    )


def test_unknown_operation_fails_closed() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)

    with pytest.raises(BindingError, match="unknown canonical operation"):
        binder.bind(OperationProposal("unknown.v1", {}), _context())


def test_unknown_proposal_slot_fails_closed() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)

    with pytest.raises(BindingError, match="unknown canonical slot"):
        binder.bind(
            OperationProposal(
                "move.v1",
                {"displacement": [100, 0, 0], "mystery": 1},
            ),
            _context(),
        )


def test_llm_cannot_supply_context_slot() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)

    with pytest.raises(BindingError, match="INTENT"):
        binder.bind(
            OperationProposal(
                "move.v1",
                {
                    "targets": ["S-user-smuggled"],
                    "displacement": [100, 0, 0],
                },
            ),
            _context(),
        )


def test_missing_required_intent_slot_fails_closed() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)

    with pytest.raises(BindingError, match="required INTENT slot"):
        binder.bind(OperationProposal("move.v1", {}), _context())


def test_empty_required_context_selection_fails_closed() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)

    with pytest.raises(BindingError, match="required CONTEXT slot"):
        binder.bind(
            OperationProposal("move.v1", {"displacement": [100, 0, 0]}),
            _context(selection=()),
        )


def test_context_value_recipe_is_explicit_and_deterministic() -> None:
    definition = _definition(
        canonical_operation="level.tag.v1",
        properties={
            "target": {"type": "string"},
            "level": {"type": "string"},
        },
        required=["target", "level"],
        slot_binding_policy={
            "target": SlotBindingClass.INTENT,
            "level": SlotBindingClass.CONTEXT,
        },
    )
    recipe = OperationBindingRecipe(
        "level.tag.v1",
        (
            SlotBindingRecipe(
                "level",
                BindingResolverKind.CONTEXT_VALUE,
                source_key="active_level",
            ),
        ),
    )
    binder = ParameterBinder((definition,), (recipe,))

    bound = binder.bind(
        OperationProposal("level.tag.v1", {"target": "S-001"}),
        _context(context_values={"active_level": "L2"}),
    )

    assert dict(bound.arguments) == {"target": "S-001", "level": "L2"}
    assert bound.binding_evidence["level"].source == "ContextSnapshot.context_values"
    assert bound.binding_evidence["level"].source_ref == "active_level"


def test_context_slot_without_recipe_fails_during_binder_construction() -> None:
    definition = _definition(
        canonical_operation="context.required.v1",
        properties={"target": {"type": "string"}},
        required=["target"],
        slot_binding_policy={"target": SlotBindingClass.CONTEXT},
    )

    with pytest.raises(BindingError, match="missing deterministic recipe"):
        ParameterBinder((definition,), ())


def test_canonical_default_recipe_binds_literal_and_records_evidence() -> None:
    definition = _definition(
        canonical_operation="offset.v1",
        properties={
            "distance": {"type": "number"},
            "unit": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}},
                "required": ["symbol"],
                "additionalProperties": False,
            },
        },
        required=["distance", "unit"],
        slot_binding_policy={
            "distance": SlotBindingClass.INTENT,
            "unit": SlotBindingClass.CANONICAL_DEFAULT,
        },
    )
    default_container = {"symbol": "mm"}
    recipe = OperationBindingRecipe(
        "offset.v1",
        (
            SlotBindingRecipe(
                "unit",
                BindingResolverKind.CANONICAL_DEFAULT,
                default_value=default_container,
            ),
        ),
    )
    binder = ParameterBinder((definition,), (recipe,))
    default_container["symbol"] = "changed-after-construction"

    bound = binder.bind(OperationProposal("offset.v1", {"distance": 300}), _context())

    assert bound.arguments["unit"] == {"symbol": "mm"}
    assert bound.binding_evidence["unit"].source == "CanonicalDefault"


def test_canonical_default_without_recipe_fails_closed() -> None:
    definition = _definition(
        canonical_operation="default.required.v1",
        properties={"unit": {"type": "string"}},
        required=["unit"],
        slot_binding_policy={"unit": SlotBindingClass.CANONICAL_DEFAULT},
    )

    with pytest.raises(BindingError, match="missing deterministic recipe"):
        ParameterBinder((definition,), ())


def test_derived_resolver_binds_after_non_derived_arguments() -> None:
    definition = _definition(
        canonical_operation="vector.length.v1",
        properties={
            "vector": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 2,
                "maxItems": 2,
            },
            "length": {"type": "number"},
        },
        required=["vector", "length"],
        slot_binding_policy={
            "vector": SlotBindingClass.INTENT,
            "length": SlotBindingClass.DERIVED,
        },
    )
    recipe = OperationBindingRecipe(
        "vector.length.v1",
        (
            SlotBindingRecipe(
                "length",
                BindingResolverKind.DERIVED,
                source_key="vector_length",
            ),
        ),
    )

    def vector_length(_definition, _proposal, _context, arguments):
        vector = arguments["vector"]
        return (vector[0] ** 2 + vector[1] ** 2) ** 0.5

    binder = ParameterBinder(
        (definition,),
        (recipe,),
        derived_resolvers={"vector_length": vector_length},
    )

    bound = binder.bind(
        OperationProposal("vector.length.v1", {"vector": [3, 4]}),
        _context(),
    )

    assert bound.arguments["length"] == 5
    assert bound.binding_evidence["length"].source == "DerivedResolver:vector_length"


def test_unregistered_derived_resolver_fails_closed() -> None:
    definition = _definition(
        canonical_operation="derived.required.v1",
        properties={"value": {"type": "number"}},
        required=["value"],
        slot_binding_policy={"value": SlotBindingClass.DERIVED},
    )
    recipe = OperationBindingRecipe(
        "derived.required.v1",
        (
            SlotBindingRecipe(
                "value",
                BindingResolverKind.DERIVED,
                source_key="missing_resolver",
            ),
        ),
    )

    with pytest.raises(BindingError, match="unregistered DERIVED resolver"):
        ParameterBinder((definition,), (recipe,))


def test_provider_slot_is_deferred_and_cannot_be_supplied_by_llm() -> None:
    definition = _definition(
        canonical_operation="provider.defer.v1",
        properties={
            "intent": {"type": "number"},
            "runtime_value": {"type": "string"},
        },
        required=["intent", "runtime_value"],
        slot_binding_policy={
            "intent": SlotBindingClass.INTENT,
            "runtime_value": SlotBindingClass.PROVIDER,
        },
    )
    binder = ParameterBinder((definition,), ())

    bound = binder.bind(
        OperationProposal("provider.defer.v1", {"intent": 7}),
        _context(),
    )
    assert dict(bound.arguments) == {"intent": 7}
    assert "runtime_value" not in bound.binding_evidence

    with pytest.raises(BindingError, match="INTENT"):
        binder.bind(
            OperationProposal(
                "provider.defer.v1",
                {"intent": 7, "runtime_value": "forbidden"},
            ),
            _context(),
        )


def test_recipe_binding_class_mismatch_fails_during_binder_construction() -> None:
    definition = _definition(
        canonical_operation="recipe.mismatch.v1",
        properties={"target": {"type": "string"}},
        required=["target"],
        slot_binding_policy={"target": SlotBindingClass.CONTEXT},
    )
    recipe = OperationBindingRecipe(
        "recipe.mismatch.v1",
        (
            SlotBindingRecipe(
                "target",
                BindingResolverKind.CANONICAL_DEFAULT,
                default_value="S-001",
            ),
        ),
    )

    with pytest.raises(BindingError, match="does not match"):
        ParameterBinder((definition,), (recipe,))


def test_canonical_schema_validation_rejects_malformed_intent_value() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)

    with pytest.raises(BindingError, match="canonical input schema"):
        binder.bind(
            OperationProposal("move.v1", {"displacement": [100, 0]}),
            _context(),
        )


def test_planning_requirements_come_from_canonical_definition_only() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)

    bound = binder.bind(
        OperationProposal("move.v1", {"displacement": [100, 0, 0]}),
        _context(),
    )

    assert bound.planning_requirements.operation_freshness_requirements == (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    assert bound.planning_requirements.coverage_requirements == ()
    assert bound.planning_requirements.assurance_requirements == ()


def test_inputs_and_bound_output_are_defensive_copies() -> None:
    intent = {"displacement": [100, 0, 0]}
    context_values = {"note": {"value": 1}}
    proposal = OperationProposal("move.v1", intent)
    context = _context(context_values=context_values)
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)

    intent["displacement"][0] = 999
    context_values["note"]["value"] = 999
    bound = binder.bind(proposal, context)

    assert bound.arguments["displacement"] == [100, 0, 0]
    with pytest.raises(TypeError):
        bound.arguments["new"] = 1
    with pytest.raises(FrozenInstanceError):
        bound.operation.version = "2.0.0"
