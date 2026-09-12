from __future__ import annotations

from dataclasses import replace

import pytest
from design_materialization_planning import MaterializationPlan, MaterializationPlanningError


def test_plan_contract_rejects_duplicate_materialization_or_slot_identity(phase_i_case):
    from design_materialization_planning import MaterializationPlanner, MaterializationPlanningRequest

    plan = MaterializationPlanner().plan(
        MaterializationPlanningRequest(
            phase_i_case.changeset,
            phase_i_case.boundary_v2,
            phase_i_case.topology,
            phase_i_case.profile,
        )
    )
    first, second = plan.intents

    with pytest.raises(ValueError, match="materialization_id"):
        replace(plan, intents=(first, replace(second, materialization_id=first.materialization_id)))

    with pytest.raises(ValueError, match="materialization_slot_id"):
        replace(
            plan,
            intents=(first, replace(second, materialization_slot_id=first.materialization_slot_id)),
        )


def test_materialization_plan_is_immutable(phase_i_case):
    from design_materialization_planning import MaterializationPlanner, MaterializationPlanningRequest

    plan = MaterializationPlanner().plan(
        MaterializationPlanningRequest(
            phase_i_case.changeset,
            phase_i_case.boundary_v2,
            phase_i_case.topology,
            phase_i_case.profile,
        )
    )
    assert MaterializationPlan.__dataclass_params__.frozen is True
    with pytest.raises((AttributeError, TypeError)):
        plan.required_set_hash = "f" * 64


def test_materialization_planning_error_exposes_stable_code():
    error = MaterializationPlanningError("EXAMPLE", "example")
    assert error.code == "EXAMPLE"
