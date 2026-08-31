from __future__ import annotations

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from design_orchestrator.canonical_operations import (
    CanonicalOperationDefinition,
    MOVE_V1,
    SlotBindingClass,
)


def make_definition(**overrides) -> CanonicalOperationDefinition:
    values = {
        "canonical_operation": "test.op.v1",
        "version": "1.0.0",
        "title": "Test operation",
        "description": "A Host-independent test operation.",
        "category": "MODEL_OPERATION",
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "number"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        "slot_binding_policy": {"value": SlotBindingClass.INTENT},
        "verification_contract": {"type": "NONE"},
        "effects": ("PROPERTIES",),
    }
    values.update(overrides)
    return CanonicalOperationDefinition(**values)


def test_move_v1_exposes_complete_step23_contract() -> None:
    assert MOVE_V1.canonical_operation == "move.v1"
    assert MOVE_V1.version == "1.0.0"
    assert MOVE_V1.title == "Move entities"
    assert MOVE_V1.description
    assert MOVE_V1.category == "MODEL_OPERATION"
    assert MOVE_V1.slot_binding_policy["targets"] is SlotBindingClass.CONTEXT
    assert MOVE_V1.slot_binding_policy["displacement"] is SlotBindingClass.INTENT
    assert MOVE_V1.canonical_entity_constraints == ()
    assert MOVE_V1.context_freshness_requirements == ()
    assert MOVE_V1.coverage_requirements == ()
    assert MOVE_V1.assurance_requirements == ()
    assert MOVE_V1.operation_freshness_requirements == (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    assert MOVE_V1.effects == ("PLACEMENT", "GEOMETRY")
    assert MOVE_V1.verification_contract == {"type": "HOST_READ_BACK"}


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("canonical_operation", " "),
        ("version", ""),
        ("title", " "),
        ("description", ""),
    ],
)
def test_required_text_fields_fail_closed(field_name: str, value: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_definition(**{field_name: value})


@pytest.mark.parametrize("version", ["1", "1.0", "v1.0.0", "1.0.x"])
def test_contract_version_requires_numeric_major_minor_patch(version: str) -> None:
    with pytest.raises(ValueError, match="version"):
        make_definition(version=version)


def test_missing_slot_policy_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing slot binding policy"):
        make_definition(slot_binding_policy={})


def test_unknown_policy_slot_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown canonical slot"):
        make_definition(
            slot_binding_policy={
                "value": SlotBindingClass.INTENT,
                "ghost": SlotBindingClass.CONTEXT,
            }
        )


def test_unknown_binding_class_fails_closed() -> None:
    with pytest.raises(ValueError):
        make_definition(slot_binding_policy={"value": "MAGIC"})


def test_input_schema_properties_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="properties"):
        make_definition(input_schema={"type": "object", "properties": []})


def test_required_must_reference_known_properties() -> None:
    with pytest.raises(ValueError, match="required"):
        make_definition(
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "number"}},
                "required": ["missing"],
                "additionalProperties": False,
            }
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "context_freshness_requirements",
        "operation_freshness_requirements",
        "coverage_requirements",
        "assurance_requirements",
    ],
)
def test_requirement_entries_must_be_objects(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_definition(**{field_name: ("not-an-object",)})


def test_move_intent_schema_exposes_only_displacement() -> None:
    projected = MOVE_V1.intent_input_schema()

    assert projected["type"] == "object"
    assert list(projected["properties"]) == ["displacement"]
    assert projected["required"] == ["displacement"]
    assert projected["additionalProperties"] is False
    assert "targets" not in projected["properties"]

    Draft202012Validator.check_schema(projected)
    Draft202012Validator(projected).validate({"displacement": [1, 2, 3]})


def test_definition_defensively_copies_structured_inputs() -> None:
    input_schema = {
        "type": "object",
        "properties": {"value": {"type": "number", "maximum": 10}},
        "required": ["value"],
        "additionalProperties": False,
    }
    policy = {"value": SlotBindingClass.INTENT}
    freshness = [{"aspect": "PROPERTIES", "required_state": "FRESH"}]
    effects = [{"aspect": "PROPERTIES"}]

    definition = make_definition(
        input_schema=input_schema,
        slot_binding_policy=policy,
        operation_freshness_requirements=tuple(freshness),
        effects=tuple(effects),
    )

    input_schema["properties"]["value"]["maximum"] = 999
    policy["value"] = SlotBindingClass.CONTEXT
    freshness[0]["required_state"] = "STALE"
    effects[0]["aspect"] = "GEOMETRY"

    assert definition.input_schema["properties"]["value"]["maximum"] == 10
    assert definition.slot_binding_policy["value"] is SlotBindingClass.INTENT
    assert definition.operation_freshness_requirements[0]["required_state"] == "FRESH"
    assert definition.effects[0]["aspect"] == "PROPERTIES"


def test_intent_projection_is_independent_from_canonical_schema() -> None:
    canonical_before = deepcopy(MOVE_V1.input_schema)
    first = MOVE_V1.intent_input_schema()
    first["properties"]["displacement"]["maxItems"] = 99
    first["required"].clear()

    second = MOVE_V1.intent_input_schema()

    assert second["properties"]["displacement"]["maxItems"] == 3
    assert second["required"] == ["displacement"]
    assert MOVE_V1.input_schema == canonical_before
