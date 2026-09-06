from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_planning import (
    ExecutionPlanningError,
    HostRuntimeRef,
    MaterializationRoutingEvidence,
    compute_materialization_routing_hash,
    plan_materialized_execution,
    validate_execution_plan_v2,
)

from test_step30_materialization_v2 import _phase_i_inputs


def test_materialization_routing_hash_is_order_independent() -> None:
    _, _, routing, _ = _phase_i_inputs()
    assert compute_materialization_routing_hash(routing.routes) == (
        compute_materialization_routing_hash(tuple(reversed(routing.routes)))
    )


def test_runtime_change_changes_routing_and_execution_plan_hashes() -> None:
    case, _, routing, request = _phase_i_inputs()
    baseline = plan_materialized_execution(request)
    changed_routes = (
        replace(
            routing.routes[0],
            host_runtime_ref=HostRuntimeRef(
                routing.routes[0].host_runtime_ref.host_type,
                "AUTOCAD-02",
                routing.routes[0].host_runtime_ref.document_ref,
            ),
        ),
        *routing.routes[1:],
    )
    changed_routing = MaterializationRoutingEvidence(
        routing_snapshot_id="MRS-PHASE-I-2",
        routes=changed_routes,
        routing_snapshot_hash=compute_materialization_routing_hash(changed_routes),
    )
    changed = plan_materialized_execution(
        replace(request, runtime_routing_evidence=changed_routing)
    )

    assert changed.routing_snapshot_hash != baseline.routing_snapshot_hash
    assert changed.execution_plan_hash != baseline.execution_plan_hash
    validate_execution_plan_v2(changed, case.topology, case.boundary_v2)


def test_v2_slice_hashes_bind_distinct_materialization_lineage() -> None:
    _, materialization_plan, _, request = _phase_i_inputs()
    execution_plan = plan_materialized_execution(request)

    assert len({item.execution_slice_hash for item in execution_plan.execution_slices}) == 2
    assert {
        item.materialization_id
        for item in execution_plan.execution_slices
    } == {item.materialization_id for item in materialization_plan.intents}


def test_plan_integrity_rejects_required_set_hash_substitution() -> None:
    case, _, _, request = _phase_i_inputs()
    execution_plan = plan_materialized_execution(request)

    with pytest.raises(ExecutionPlanningError) as exc:
        validate_execution_plan_v2(
            replace(execution_plan, required_set_hash="f" * 64),
            case.topology,
            case.boundary_v2,
        )
    assert exc.value.code == "EXECUTION_PLAN_INTEGRITY_INVALID"
