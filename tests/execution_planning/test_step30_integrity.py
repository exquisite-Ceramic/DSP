"""Step30 execution-slice integrity reconstruction tests."""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_execution_planning import (
    ExecutionPlanner,
    ExecutionPlanningError,
    ExecutionPlanningRequest,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
    compute_routing_snapshot_hash,
    validate_execution_slice_integrity,
)


def _real_execution_slice(transaction):
    changeset, boundary = transaction
    runtime = HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    routes = [
        RuntimeEntityRoute(target, runtime)
        for target in changeset.root_operation.targets
    ]
    for operation in changeset.derived_operations:
        routes.extend(RuntimeEntityRoute(target, runtime) for target in operation.targets)
    route_tuple = tuple(routes)
    routing = RuntimeRoutingEvidence(
        "RRS-INTEGRITY",
        route_tuple,
        compute_routing_snapshot_hash(route_tuple),
    )
    plan = ExecutionPlanner().plan(
        ExecutionPlanningRequest(changeset, boundary, routing)
    )
    assert len(plan.execution_slices) == 1
    assert len(plan.execution_slices[0].execution_units) == 2
    return plan.execution_slices[0]


def test_real_execution_slice_passes_integrity(step30_transaction) -> None:
    validate_execution_slice_integrity(_real_execution_slice(step30_transaction))


def test_execution_unit_body_tamper_is_detected(step30_transaction) -> None:
    execution_slice = _real_execution_slice(step30_transaction)
    unit = execution_slice.execution_units[0]
    bad = replace(unit, arguments={**dict(unit.arguments), "tampered": True})
    tampered = replace(
        execution_slice,
        execution_units=(bad, *execution_slice.execution_units[1:]),
    )

    with pytest.raises(ExecutionPlanningError) as exc:
        validate_execution_slice_integrity(tampered)
    assert exc.value.code == "EXECUTION_UNIT_INTEGRITY_INVALID"


def test_execution_slice_host_instance_tamper_is_detected(step30_transaction) -> None:
    execution_slice = _real_execution_slice(step30_transaction)
    tampered = replace(
        execution_slice,
        host_runtime_ref=replace(
            execution_slice.host_runtime_ref,
            host_instance_id="RVT-OTHER",
        ),
    )

    with pytest.raises(ExecutionPlanningError) as exc:
        validate_execution_slice_integrity(tampered)
    assert exc.value.code == "EXECUTION_SLICE_INTEGRITY_INVALID"


def test_execution_slice_scope_hash_tamper_is_detected(step30_transaction) -> None:
    execution_slice = _real_execution_slice(step30_transaction)
    tampered = replace(
        execution_slice,
        approved_scope_ref=replace(
            execution_slice.approved_scope_ref,
            scope_hash="f" * 64,
        ),
    )

    with pytest.raises(ExecutionPlanningError) as exc:
        validate_execution_slice_integrity(tampered)
    assert exc.value.code == "EXECUTION_SLICE_INTEGRITY_INVALID"


def test_execution_slice_unit_list_tamper_is_detected(step30_transaction) -> None:
    execution_slice = _real_execution_slice(step30_transaction)
    tampered = replace(
        execution_slice,
        execution_units=(execution_slice.execution_units[0],),
    )

    with pytest.raises(ExecutionPlanningError) as exc:
        validate_execution_slice_integrity(tampered)
    assert exc.value.code == "EXECUTION_SLICE_INTEGRITY_INVALID"
