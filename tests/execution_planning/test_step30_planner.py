from __future__ import annotations

from dataclasses import replace

from design_approval_scope import CanonicalExistenceEffect
from design_execution_planning import (
    ExecutionPlanner,
    ExecutionPlanningRequest,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
    compute_execution_plan_hash,
    compute_routing_snapshot_hash,
)
from design_execution_planning.planner import _build_unit


def _request(transaction, *, root_ref=None, derived_ref=None, reverse_routes=False):
    changeset, boundary = transaction
    root_ref = root_ref or HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    derived_ref = derived_ref or root_ref
    routes = [
        RuntimeEntityRoute(target, root_ref)
        for target in changeset.root_operation.targets
    ]
    for operation in changeset.derived_operations:
        routes.extend(RuntimeEntityRoute(target, derived_ref) for target in operation.targets)
    if reverse_routes:
        routes.reverse()
    route_tuple = tuple(routes)
    evidence = RuntimeRoutingEvidence(
        "RRS-PLAN",
        route_tuple,
        compute_routing_snapshot_hash(route_tuple),
    )
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


def test_creation_operation_projects_source_only_existence_authority(step30_transaction) -> None:
    changeset, _ = step30_transaction
    operation = replace(
        changeset.root_operation,
        expected_effects=(),
        expected_existence_effects=(CanonicalExistenceEffect.CREATE,),
    )

    unit = _build_unit(changeset, operation, "b" * 64)

    assert unit.targets == operation.targets
    assert unit.expected_effects == ()
    assert unit.expected_existence_effects == (CanonicalExistenceEffect.CREATE,)


def test_same_runtime_and_scope_key_groups_units_into_one_slice(step30_transaction) -> None:
    plan = ExecutionPlanner().plan(_request(step30_transaction))
    assert len(plan.execution_slices) == 1
    assert len(plan.execution_slices[0].execution_units) == 2
    assert plan.execution_slices[0].execution_slice_id == (
        f"XS-{plan.execution_slices[0].execution_slice_hash[:12]}"
    )


def test_different_host_instances_create_different_slices(step30_transaction) -> None:
    plan = ExecutionPlanner().plan(
        _request(
            step30_transaction,
            root_ref=HostRuntimeRef("REVIT", "RVT-01", "DOC-1"),
            derived_ref=HostRuntimeRef("REVIT", "RVT-02", "DOC-1"),
        )
    )
    assert len(plan.execution_slices) == 2
    assert {slice_.host_runtime_ref.host_instance_id for slice_ in plan.execution_slices} == {
        "RVT-01",
        "RVT-02",
    }


def test_route_input_order_does_not_change_plan_identity(step30_transaction) -> None:
    forward = ExecutionPlanner().plan(_request(step30_transaction))
    reversed_plan = ExecutionPlanner().plan(
        _request(step30_transaction, reverse_routes=True)
    )
    assert forward.execution_plan_hash == reversed_plan.execution_plan_hash
    assert forward.execution_plan_id == reversed_plan.execution_plan_id
    assert tuple(slice_.execution_slice_hash for slice_ in forward.execution_slices) == tuple(
        slice_.execution_slice_hash for slice_ in reversed_plan.execution_slices
    )


def test_plan_hash_binds_full_execution_unit_hashes(step30_transaction) -> None:
    changeset, boundary = step30_transaction
    request = _request(step30_transaction)
    plan = ExecutionPlanner().plan(request)
    unit_by_id = {unit.execution_unit_id: unit for unit in _units(plan)}
    dependency_semantics = tuple(
        (
            unit_by_id[dependency.predecessor_execution_unit_id].execution_unit_hash,
            unit_by_id[dependency.successor_execution_unit_id].execution_unit_hash,
            dependency.reason_ref,
        )
        for dependency in plan.execution_dependencies
    )
    expected_hash = compute_execution_plan_hash(
        changeset_hash=changeset.changeset_hash,
        scope_hash=boundary.scope_hash,
        routing_snapshot_hash=request.runtime_routing_evidence.routing_snapshot_hash,
        execution_slice_hashes=(slice_.execution_slice_hash for slice_ in plan.execution_slices),
        execution_dependencies=dependency_semantics,
    )
    assert plan.execution_plan_hash == expected_hash
