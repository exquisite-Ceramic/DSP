from __future__ import annotations

from dataclasses import fields

from design_execution_planning import (
    ExecutionPlanningRequestV2,
    HostRuntimeRef,
    MaterializationRoutingEvidence,
    MaterializationRuntimeRoute,
    compute_materialization_routing_hash,
    plan_materialized_execution,
    validate_execution_plan_v2,
)
from design_materialization_planning import (
    MaterializationPlanner,
    MaterializationPlanningRequest,
)

from tests.materialization_planning.conftest import build_case


def _phase_i_inputs():
    case = build_case()
    materialization_plan = MaterializationPlanner().plan(
        MaterializationPlanningRequest(
            canonical_changeset=case.changeset,
            approval_scope_boundary=case.boundary_v2,
            topology_snapshot=case.topology,
            convergence_profile=case.profile,
        )
    )
    slot_by_id = {
        slot.materialization_slot_id: slot
        for slot in case.topology.slots
    }
    routes = tuple(
        MaterializationRuntimeRoute(
            materialization_id=intent.materialization_id,
            host_runtime_ref=HostRuntimeRef(
                host_type=intent.required_host_type,
                host_instance_id=f"{intent.required_host_type.upper()}-01",
                document_ref=slot_by_id[intent.materialization_slot_id].document_ref,
            ),
        )
        for intent in materialization_plan.intents
    )
    routing = MaterializationRoutingEvidence(
        routing_snapshot_id="MRS-PHASE-I",
        routes=routes,
        routing_snapshot_hash=compute_materialization_routing_hash(routes),
    )
    request = ExecutionPlanningRequestV2(
        canonical_changeset=case.changeset,
        approval_scope_boundary=case.boundary_v2,
        materialization_plan=materialization_plan,
        topology_snapshot=case.topology,
        runtime_routing_evidence=routing,
    )
    return case, materialization_plan, routing, request


def test_v2_request_has_exact_frozen_inputs() -> None:
    assert {field.name for field in fields(ExecutionPlanningRequestV2)} == {
        "canonical_changeset",
        "approval_scope_boundary",
        "materialization_plan",
        "topology_snapshot",
        "runtime_routing_evidence",
    }


def test_one_materialization_intent_projects_to_one_unit_and_one_slice() -> None:
    case, materialization_plan, routing, request = _phase_i_inputs()

    execution_plan = plan_materialized_execution(request)

    assert len(execution_plan.execution_slices) == len(materialization_plan.intents) == 2
    assert tuple(
        execution_slice.host_runtime_ref.host_type
        for execution_slice in execution_plan.execution_slices
    ) == ("autocad", "revit")
    assert tuple(
        execution_slice.materialization_id
        for execution_slice in execution_plan.execution_slices
    ) == tuple(intent.materialization_id for intent in materialization_plan.intents)
    assert all(
        len(execution_slice.execution_units) == 1
        for execution_slice in execution_plan.execution_slices
    )
    assert all(
        execution_slice.execution_units[0].materialization_id
        == execution_slice.materialization_id
        for execution_slice in execution_plan.execution_slices
    )
    assert all(
        execution_slice.materialization_plan_hash
        == materialization_plan.materialization_plan_hash
        for execution_slice in execution_plan.execution_slices
    )
    assert execution_plan.materialization_plan_hash == materialization_plan.materialization_plan_hash
    assert execution_plan.required_set_hash == materialization_plan.required_set_hash
    assert execution_plan.topology_snapshot_hash == case.topology.topology_snapshot_hash
    assert execution_plan.routing_snapshot_hash == routing.routing_snapshot_hash
    assert execution_plan.ordering_policy == "stable_host_type_then_slot.v1"
    validate_execution_plan_v2(execution_plan, case.topology, case.boundary_v2)


def test_wall_materializations_bind_their_own_document_scoped_rules() -> None:
    case, _, _, request = _phase_i_inputs()
    execution_plan = plan_materialized_execution(request)
    expected_by_document = {
        rule.document_ref: rule.slice_scope_rule_id
        for rule in case.boundary_v2.execution_slice_scopes
    }

    assert {
        execution_slice.host_runtime_ref.document_ref:
        execution_slice.approved_scope_ref.execution_slice_scope_rule_id
        for execution_slice in execution_plan.execution_slices
    } == expected_by_document
