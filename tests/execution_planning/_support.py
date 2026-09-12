from design_execution_planning import (
    ExecutionPlanningRequestV2,
    HostRuntimeRef,
    MaterializationRoutingEvidence,
    MaterializationRuntimeRoute,
    compute_materialization_routing_hash,
)
from design_materialization_planning import (
    MaterializationPlanner,
    MaterializationPlanningRequest,
)

from tests.materialization_planning._support import build_case


def build_phase_i_execution_inputs():
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
