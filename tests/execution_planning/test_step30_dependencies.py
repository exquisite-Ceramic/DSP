from __future__ import annotations

from dataclasses import replace

import pytest
from design_changeset import ChangeDependency
from design_execution_planning import (
    ExecutionPlanner,
    ExecutionPlanningError,
    ExecutionPlanningRequest,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
    compute_routing_snapshot_hash,
)


def _request(transaction, *, split_hosts: bool = False):
    changeset, boundary = transaction
    root_ref = HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    derived_ref = HostRuntimeRef("REVIT", "RVT-02", "DOC-1") if split_hosts else root_ref
    routes = [
        RuntimeEntityRoute(target, root_ref)
        for target in changeset.root_operation.targets
    ]
    for operation in changeset.derived_operations:
        routes.extend(RuntimeEntityRoute(target, derived_ref) for target in operation.targets)
    route_tuple = tuple(routes)
    evidence = RuntimeRoutingEvidence(
        "RRS-DEPS",
        route_tuple,
        compute_routing_snapshot_hash(route_tuple),
    )
    return ExecutionPlanningRequest(changeset, boundary, evidence)


def _unit_by_source(plan):
    return {
        unit.source_operation_id: unit.execution_unit_id
        for slice_ in plan.execution_slices
        for unit in slice_.execution_units
    }


def test_dependencies_project_one_to_one(step30_transaction) -> None:
    changeset, _ = step30_transaction
    plan = ExecutionPlanner().plan(_request(step30_transaction))
    unit_by_source = _unit_by_source(plan)
    expected = {
        (
            unit_by_source[dependency.predecessor_operation_id],
            unit_by_source[dependency.successor_operation_id],
            dependency.reason_ref,
        )
        for dependency in changeset.change_dependencies
    }
    actual = {
        (
            dependency.predecessor_execution_unit_id,
            dependency.successor_execution_unit_id,
            dependency.reason_ref,
        )
        for dependency in plan.execution_dependencies
    }
    assert actual == expected


def test_cross_slice_dependency_is_preserved(step30_transaction) -> None:
    plan = ExecutionPlanner().plan(_request(step30_transaction, split_hosts=True))
    assert len(plan.execution_slices) == 2
    assert len(plan.execution_dependencies) == 1
    predecessor = plan.execution_dependencies[0].predecessor_execution_unit_id
    successor = plan.execution_dependencies[0].successor_execution_unit_id
    slice_by_unit = {
        unit.execution_unit_id: slice_.execution_slice_id
        for slice_ in plan.execution_slices
        for unit in slice_.execution_units
    }
    assert slice_by_unit[predecessor] != slice_by_unit[successor]


def test_unknown_dependency_endpoint_fails_closed(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    original = changeset.change_dependencies[0]
    invalid = ChangeDependency(
        "COP-UNKNOWN",
        original.successor_operation_id,
        original.reason_ref,
    )
    bad_changeset = replace(changeset, change_dependencies=(invalid,))
    request = _request((bad_changeset, boundary))
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(request)
    assert exc.value.code == "EXECUTION_DEPENDENCY_INVALID"
