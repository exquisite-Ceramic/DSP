from __future__ import annotations

import design_orchestrator.canonical_operations as canonical_operations
from design_orchestrator.canonical_operations import MOVE_V1


def test_move_v1_exposes_complete_step23_contract() -> None:
    assert MOVE_V1.canonical_operation == "move.v1"
    assert MOVE_V1.version == "1.0.0"
    assert MOVE_V1.title == "Move entities"
    assert MOVE_V1.description
    assert MOVE_V1.category == "MODEL_OPERATION"
    assert MOVE_V1.canonical_entity_constraints == ()
    assert MOVE_V1.coverage_requirements == ()
    assert MOVE_V1.assurance_requirements == ()
    assert MOVE_V1.operation_freshness_requirements == (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    assert MOVE_V1.effects == ("PLACEMENT", "GEOMETRY")
    assert MOVE_V1.verification_contract == {"type": "HOST_READ_BACK"}


def test_move_v1_declares_typed_slot_ownership() -> None:
    slot_binding_class = getattr(canonical_operations, "SlotBindingClass", None)
    assert slot_binding_class is not None
    assert MOVE_V1.slot_binding_policy["targets"] is slot_binding_class.CONTEXT
    assert MOVE_V1.slot_binding_policy["displacement"] is slot_binding_class.INTENT
