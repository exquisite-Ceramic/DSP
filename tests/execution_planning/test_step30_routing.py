from __future__ import annotations

import pytest
from design_execution_planning import (
    ExecutionPlanner,
    ExecutionPlanningError,
    ExecutionPlanningRequest,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
    compute_routing_snapshot_hash,
)


def _routes(changeset, root_ref=None, derived_ref=None):
    root_ref = root_ref or HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    derived_ref = derived_ref or root_ref
    result = [RuntimeEntityRoute(target, root_ref) for target in changeset.root_operation.targets]
    for operation in changeset.derived_operations:
        result.extend(RuntimeEntityRoute(target, derived_ref) for target in operation.targets)
    return tuple(result)


def _request(transaction, routes, *, supplied_hash=None):
    changeset, boundary = transaction
    evidence = RuntimeRoutingEvidence(
        "RRS-ROUTING",
        routes,
        supplied_hash or compute_routing_snapshot_hash(routes),
    )
    return ExecutionPlanningRequest(changeset, boundary, evidence)


def test_wrong_routing_hash_fails(step30_transaction) -> None:
    changeset, _ = step30_transaction
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(_request(step30_transaction, _routes(changeset), supplied_hash="0" * 64))
    assert exc.value.code == "EXECUTION_ROUTING_HASH_MISMATCH"


def test_missing_route_fails_closed(step30_transaction) -> None:
    changeset, _ = step30_transaction
    routes = _routes(changeset)[1:]
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(_request(step30_transaction, routes))
    assert exc.value.code == "EXECUTION_ROUTE_UNRESOLVED"


def test_conflicting_duplicate_route_fails_closed(step30_transaction) -> None:
    changeset, _ = step30_transaction
    routes = list(_routes(changeset))
    routes.append(
        RuntimeEntityRoute(
            routes[0].semantic_id,
            HostRuntimeRef("REVIT", "RVT-OTHER", "DOC-1"),
        )
    )
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(_request(step30_transaction, tuple(routes)))
    assert exc.value.code == "EXECUTION_ROUTE_CONFLICT"


def test_extraneous_route_fails_closed(step30_transaction) -> None:
    changeset, _ = step30_transaction
    routes = (*_routes(changeset), RuntimeEntityRoute("EXTRA", HostRuntimeRef("REVIT", "RVT-01", "DOC-1")))
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(_request(step30_transaction, routes))
    assert exc.value.code == "EXECUTION_ROUTE_EXTRANEOUS"


def test_identical_duplicate_route_normalizes_successfully(step30_transaction) -> None:
    changeset, _ = step30_transaction
    base = _routes(changeset)
    plan = ExecutionPlanner().plan(_request(step30_transaction, (*base, base[0])))
    assert plan.routing_snapshot_hash == compute_routing_snapshot_hash(base)


def test_one_canonical_operation_cannot_span_runtime_boundaries(step30_multitarget_transaction) -> None:
    changeset, _ = step30_multitarget_transaction
    first, second = changeset.root_operation.targets
    routes = (
        RuntimeEntityRoute(first, HostRuntimeRef("REVIT", "RVT-01", "DOC-1")),
        RuntimeEntityRoute(second, HostRuntimeRef("REVIT", "RVT-02", "DOC-1")),
        *(
            RuntimeEntityRoute(target, HostRuntimeRef("REVIT", "RVT-01", "DOC-1"))
            for operation in changeset.derived_operations
            for target in operation.targets
        ),
    )
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(_request(step30_multitarget_transaction, routes))
    assert exc.value.code == "EXECUTION_OPERATION_NOT_PARTITIONABLE"
