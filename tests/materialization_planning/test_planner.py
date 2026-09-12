from __future__ import annotations

from dataclasses import fields, replace

import pytest
from design_materialization_planning import (
    MaterializationPlanner,
    MaterializationPlanningError,
    MaterializationPlanningRequest,
)
from design_materialization_topology import MaterializationSlot

from tests.materialization_planning._support import build_case, slot, topology


def _request(case, **overrides):
    values = {
        "canonical_changeset": case.changeset,
        "approval_scope_boundary": case.boundary_v2,
        "topology_snapshot": case.topology,
        "convergence_profile": case.profile,
    }
    values.update(overrides)
    return MaterializationPlanningRequest(**values)


def _assert_code(code: str, operation) -> None:
    with pytest.raises(MaterializationPlanningError) as exc:
        operation()
    assert exc.value.code == code


def test_wall_operation_fans_out_to_two_required_materialization_intents(phase_i_case):
    plan = MaterializationPlanner().plan(_request(phase_i_case))

    assert len(plan.intents) == 2
    assert tuple(intent.required_host_type for intent in plan.intents) == ("autocad", "revit")
    assert tuple(intent.materialization_slot_id for intent in plan.intents) == (
        "MS-AUTOCAD",
        "MS-REVIT",
    )
    assert {intent.source_operation_id for intent in plan.intents} == {
        phase_i_case.changeset.root_operation.operation_id
    }
    assert len({intent.source_operation_hash for intent in plan.intents}) == 1
    assert all(intent.semantic_targets == ("WALL-001",) for intent in plan.intents)
    assert all(intent.expected_effects == ("PROPERTIES",) for intent in plan.intents)
    assert all(len(intent.intent_hash) == 64 for intent in plan.intents)
    assert plan.changeset_hash == phase_i_case.changeset.changeset_hash
    assert plan.approved_scope_hash == phase_i_case.boundary_v2.scope_hash
    assert plan.topology_snapshot_hash == phase_i_case.topology.topology_snapshot_hash
    assert plan.convergence_profile_hash == phase_i_case.profile.profile_hash
    assert len(plan.required_set_hash) == 64
    assert len(plan.materialization_plan_hash) == 64


def test_request_has_no_runtime_availability_input_and_required_set_cannot_shrink(phase_i_case):
    assert {field.name for field in fields(MaterializationPlanningRequest)} == {
        "canonical_changeset",
        "approval_scope_boundary",
        "topology_snapshot",
        "convergence_profile",
    }
    plan = MaterializationPlanner().plan(_request(phase_i_case))
    assert {intent.required_host_type for intent in plan.intents} == {"autocad", "revit"}


def test_v1_boundary_is_rejected_before_materialization_planning(phase_i_case):
    with pytest.raises(TypeError):
        MaterializationPlanner().plan(
            _request(
                phase_i_case,
                approval_scope_boundary=phase_i_case.boundary_v1,
            )
        )


def test_topology_hash_lineage_and_integrity_fail_closed(phase_i_case):
    _assert_code(
        "MATERIALIZATION_TOPOLOGY_MISMATCH",
        lambda: MaterializationPlanner().plan(
            _request(
                phase_i_case,
                topology_snapshot=replace(
                    phase_i_case.topology,
                    topology_snapshot_hash="f" * 64,
                ),
            )
        ),
    )


def test_extra_topology_target_not_present_in_changeset_fails_closed():
    case = build_case(
        topology_slots=(
            slot("MS-AUTOCAD", "WALL-001", "autocad", "DOC-AUTOCAD"),
            slot("MS-REVIT", "WALL-001", "revit", "DOC-REVIT"),
            slot("MS-EXTRA", "WALL-999", "autocad", "DOC-EXTRA"),
        )
    )
    _assert_code(
        "MATERIALIZATION_TARGET_NOT_IN_CHANGESET",
        lambda: MaterializationPlanner().plan(_request(case)),
    )


def test_missing_required_slot_is_rejected_before_multi_target_cardinality():
    case = build_case(
        targets=("WALL-001", "WALL-002"),
        topology_slots=(
            slot("MS-AUTOCAD", "WALL-001", "autocad", "DOC-AUTOCAD"),
            slot("MS-REVIT", "WALL-001", "revit", "DOC-REVIT"),
        ),
    )
    _assert_code(
        "MATERIALIZATION_REQUIRED_SLOT_MISSING",
        lambda: MaterializationPlanner().plan(_request(case)),
    )


def test_phase_i_rejects_multi_target_materialization_cardinality():
    case = build_case(
        targets=("WALL-001", "WALL-002"),
        topology_slots=(
            slot("MS-A1", "WALL-001", "autocad", "DOC-A1"),
            slot("MS-R1", "WALL-001", "revit", "DOC-R1"),
            slot("MS-A2", "WALL-002", "autocad", "DOC-A2"),
            slot("MS-R2", "WALL-002", "revit", "DOC-R2"),
        ),
    )
    _assert_code(
        "UNSUPPORTED_MATERIALIZATION_CARDINALITY",
        lambda: MaterializationPlanner().plan(_request(case)),
    )


def test_profile_hash_substitution_is_rejected(phase_i_case):
    _assert_code(
        "CONVERGENCE_PROFILE_INTEGRITY_INVALID",
        lambda: MaterializationPlanner().plan(
            _request(
                phase_i_case,
                convergence_profile=replace(
                    phase_i_case.profile,
                    profile_hash="f" * 64,
                ),
            )
        ),
    )


def test_duplicate_required_slot_identity_is_rejected_by_topology_owner():
    duplicate: tuple[MaterializationSlot, ...] = (
        slot("MS-1", "WALL-001", "autocad", "DOC-A"),
        slot("MS-2", "WALL-001", "autocad", "DOC-A"),
    )
    with pytest.raises(ValueError, match="duplicate materialization slot"):
        topology(duplicate)
