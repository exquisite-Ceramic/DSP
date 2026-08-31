from __future__ import annotations

import pytest

from design_interaction import (
    InteractionError,
    InteractionSession,
    InteractionState,
    InteractionType,
)
from design_orchestrator.canonical_operations import (
    CanonicalOperationDefinition,
    MOVE_V1,
    SlotBindingClass,
)
from design_orchestrator.interactive_binding import (
    InteractionBindingContext,
    InteractionRequired,
    InteractiveParameterResolver,
    OperationInteractionRecipe,
    SlotInteractionRecipe,
)
from design_orchestrator.parameter_binder import (
    BindingResolverKind,
    BoundOperationProposal,
    MOVE_V1_BINDING_RECIPE,
    OperationBindingRecipe,
    OperationProposal,
    ParameterBindingContext,
    SlotBindingRecipe,
)


POINT_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 3,
    "maxItems": 3,
}

POINT_OPERATION = CanonicalOperationDefinition(
    canonical_operation="point.place.v1",
    version="1.0.0",
    title="Place point",
    description="Place a canonical point selected by the user.",
    category="MODEL_OPERATION",
    input_schema={
        "type": "object",
        "properties": {
            "targets": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "point": POINT_SCHEMA,
        },
        "required": ["targets", "point"],
        "additionalProperties": False,
    },
    slot_binding_policy={
        "targets": SlotBindingClass.CONTEXT,
        "point": SlotBindingClass.INTENT,
    },
    effects=("PLACEMENT",),
    verification_contract={"type": "HOST_READ_BACK"},
)

POINT_BINDING_RECIPE = OperationBindingRecipe(
    canonical_operation="point.place.v1",
    slots=(
        SlotBindingRecipe(
            slot="targets",
            resolver_kind=BindingResolverKind.CONTEXT_SELECTION,
        ),
    ),
)

POINT_INTERACTION_RECIPE = OperationInteractionRecipe(
    canonical_operation="point.place.v1",
    slots=(
        SlotInteractionRecipe(
            slot="point",
            interaction_type=InteractionType.PICK_POINT,
            input_constraints={"prompt": "Pick a placement point"},
            result_schema=POINT_SCHEMA,
        ),
    ),
)


def _parameter_context() -> ParameterBindingContext:
    return ParameterBindingContext(
        context_snapshot_id="CS-26",
        context_snapshot_hash="hash-26",
        document_ref="drawing-01",
        semantic_environment_ref="env-26",
        selection=("S-001",),
    )


def _interaction_context(**overrides) -> InteractionBindingContext:
    values = {"task_id": "task-26", "host_instance_id": "acad-01"}
    values.update(overrides)
    return InteractionBindingContext(**values)


def _completed_session(**overrides) -> InteractionSession:
    values = {
        "interaction_id": "IS-001",
        "task_id": "task-26",
        "host_instance_id": "acad-01",
        "document_id": "drawing-01",
        "interaction_type": InteractionType.PICK_POINT,
        "input_constraints": {"prompt": "Pick a placement point"},
        "result_schema": POINT_SCHEMA,
        "state": InteractionState.COMPLETED,
        "result": [10.0, 20.0, 0.0],
        "created_at": "2026-08-29T08:00:00Z",
        "expires_at": "2026-08-29T08:05:00Z",
    }
    values.update(overrides)
    return InteractionSession(**values)


def _resolver() -> InteractiveParameterResolver:
    return InteractiveParameterResolver(
        definitions=(POINT_OPERATION,),
        binding_recipes=(POINT_BINDING_RECIPE,),
        interaction_recipes=(POINT_INTERACTION_RECIPE,),
    )


def test_missing_required_interactive_intent_returns_interaction_required() -> None:
    result = _resolver().resolve(
        OperationProposal("point.place.v1", {}),
        _parameter_context(),
        _interaction_context(),
    )

    assert isinstance(result, InteractionRequired)
    assert result.canonical_operation == "point.place.v1"
    assert result.slot == "point"
    assert result.interaction_type is InteractionType.PICK_POINT
    assert result.input_constraints == {"prompt": "Pick a placement point"}
    assert result.result_schema == POINT_SCHEMA
    assert result.context_snapshot_ref.context_snapshot_id == "CS-26"


def test_explicit_intent_value_bypasses_interaction() -> None:
    result = _resolver().resolve(
        OperationProposal("point.place.v1", {"point": [1.0, 2.0, 3.0]}),
        _parameter_context(),
        _interaction_context(),
    )

    assert isinstance(result, BoundOperationProposal)
    assert result.arguments == {"targets": ["S-001"], "point": [1.0, 2.0, 3.0]}
    assert result.binding_evidence["point"].source == "OperationProposal.intent_arguments"
    assert result.binding_evidence["point"].source_ref is None


def test_completed_interaction_resumes_binding_and_rewrites_evidence() -> None:
    session = _completed_session()

    result = _resolver().resolve(
        OperationProposal("point.place.v1", {}),
        _parameter_context(),
        _interaction_context(),
        interaction_sessions={"point": session},
    )

    assert isinstance(result, BoundOperationProposal)
    assert result.arguments == {"targets": ["S-001"], "point": [10.0, 20.0, 0.0]}
    assert result.binding_evidence["point"].binding_class is SlotBindingClass.INTENT
    assert result.binding_evidence["point"].source == "InteractionSession"
    assert result.binding_evidence["point"].source_ref == "IS-001"


@pytest.mark.parametrize(
    "session",
    [
        _completed_session(task_id="other-task"),
        _completed_session(host_instance_id="revit-01"),
        _completed_session(document_id="drawing-02"),
        _completed_session(interaction_type=InteractionType.PICK_DIRECTION),
    ],
)
def test_completed_session_must_match_task_host_document_and_type(
    session: InteractionSession,
) -> None:
    with pytest.raises(InteractionError) as exc:
        _resolver().resolve(
            OperationProposal("point.place.v1", {}),
            _parameter_context(),
            _interaction_context(),
            interaction_sessions={"point": session},
        )

    assert exc.value.code == "INTERACTION_CONTEXT_MISMATCH"


def test_non_completed_session_cannot_supply_canonical_value() -> None:
    session = InteractionSession(
        interaction_id="IS-PENDING",
        task_id="task-26",
        host_instance_id="acad-01",
        document_id="drawing-01",
        interaction_type=InteractionType.PICK_POINT,
        input_constraints={},
        result_schema=POINT_SCHEMA,
        state=InteractionState.PENDING,
        created_at="2026-08-29T08:00:00Z",
        expires_at="2026-08-29T08:05:00Z",
    )

    with pytest.raises(InteractionError) as exc:
        _resolver().resolve(
            OperationProposal("point.place.v1", {}),
            _parameter_context(),
            _interaction_context(),
            interaction_sessions={"point": session},
        )

    assert exc.value.code == "INTERACTION_CONTEXT_MISMATCH"


def test_interaction_recipe_is_only_allowed_for_required_intent_slots() -> None:
    optional_operation = CanonicalOperationDefinition(
        canonical_operation="optional.point.v1",
        version="1.0.0",
        title="Optional point",
        description="Synthetic optional slot fixture.",
        category="MODEL_OPERATION",
        input_schema={
            "type": "object",
            "properties": {"point": POINT_SCHEMA},
            "required": [],
            "additionalProperties": False,
        },
        slot_binding_policy={"point": SlotBindingClass.INTENT},
        effects=("PLACEMENT",),
        verification_contract={"type": "HOST_READ_BACK"},
    )

    with pytest.raises(ValueError, match="required INTENT"):
        InteractiveParameterResolver(
            definitions=(optional_operation,),
            binding_recipes=(),
            interaction_recipes=(
                OperationInteractionRecipe(
                    canonical_operation="optional.point.v1",
                    slots=(
                        SlotInteractionRecipe(
                            slot="point",
                            interaction_type=InteractionType.PICK_POINT,
                            result_schema=POINT_SCHEMA,
                        ),
                    ),
                ),
            ),
        )


def test_interaction_recipe_cannot_target_provider_slot() -> None:
    provider_operation = CanonicalOperationDefinition(
        canonical_operation="provider.fixture.v1",
        version="1.0.0",
        title="Provider fixture",
        description="Synthetic provider slot fixture.",
        category="MODEL_OPERATION",
        input_schema={
            "type": "object",
            "properties": {"native_ref": {"type": "string"}},
            "required": ["native_ref"],
            "additionalProperties": False,
        },
        slot_binding_policy={"native_ref": SlotBindingClass.PROVIDER},
        effects=("PROPERTIES",),
        verification_contract={"type": "HOST_READ_BACK"},
    )

    with pytest.raises(ValueError, match="required INTENT"):
        InteractiveParameterResolver(
            definitions=(provider_operation,),
            binding_recipes=(),
            interaction_recipes=(
                OperationInteractionRecipe(
                    canonical_operation="provider.fixture.v1",
                    slots=(
                        SlotInteractionRecipe(
                            slot="native_ref",
                            interaction_type=InteractionType.SELECT_ENTITIES,
                            result_schema={"type": "string"},
                        ),
                    ),
                ),
            ),
        )


def test_move_v1_still_binds_without_interaction() -> None:
    resolver = InteractiveParameterResolver(
        definitions=(MOVE_V1,),
        binding_recipes=(MOVE_V1_BINDING_RECIPE,),
        interaction_recipes=(),
    )

    result = resolver.resolve(
        OperationProposal("move.v1", {"displacement": [100.0, 0.0, 0.0]}),
        _parameter_context(),
        _interaction_context(),
    )

    assert isinstance(result, BoundOperationProposal)
    assert result.arguments == {
        "targets": ["S-001"],
        "displacement": [100.0, 0.0, 0.0],
    }
