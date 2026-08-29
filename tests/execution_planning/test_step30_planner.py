from __future__ import annotations

from design_execution_planning import (
    ExecutionPlanner,
    ExecutionPlanningRequest,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
    compute_routing_snapshot_hash,
)


def _request(transaction):
    changeset, boundary = transaction
    ref = HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    routes = tuple(
        RuntimeEntityRoute(target, ref)
        for operation in (changeset.root_operation, *changeset.derived_operations)
        for target in operation.targets
    )
    evidence = RuntimeRoutingEvidence("RRS-PLAN", routes, compute_routing_snapshot_hash(routes))
    return ExecutionPlanningRequest(changeset, boundary, evidence)


def _units(plan):
    return tuple(unit for slice_ in plan.execution_slices for unit in slice_.execution_units)


def test_every_source_operation_appears_exactly_once(step30_transaction) -> None:
    changeset, _ = step30_transaction
    plan = ExecutionPlanner().plan(_request(step30_transaction))
    source_ids = [unit.source_operation_id for unit in _units(plan)]
    expected = [
        changeset.root_operation.operation_id,
        *(operation.operation_id for operation in changeset.derived_operations),
    ]
    assert sorted(source_ids) == sorted(expected)
    assert len(source_ids) == len(set(source_ids))


def test_unit_is_lossless_projection_and_carries_all_preconditions(step30_transaction) -> None:
    changeset, _ = step30_transaction
    plan = ExecutionPlanner().plan(_request(step30_transaction))
    by_source = {unit.source_operation_id: unit for unit in _units(plan)}
    for operation in (changeset.root_operation, *changeset.derived_operations):
        unit = by_source[operation.operation_id]
        assert unit.canonical_operation == operation.canonical_operation
        assert unit.canonical_operation_version == operation.canonical_operation_version
        assert unit.canonical_definition_fingerprint == operation.canonical_definition_fingerprint
        assert unit.targets == operation.targets
        assert dict(unit.arguments) == dict(operation.arguments)
        assert unit.expected_effects == operation.expected_effects
        assert unit.preconditions == changeset.preconditions
        assert unit.execution_unit_id == f"EU-{unit.execution_unit_hash[:12]}"
