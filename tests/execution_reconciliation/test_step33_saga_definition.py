"""Task8 RED: immutable Saga definition, Slice DAG/order, and task assignment."""

from __future__ import annotations

from dataclasses import replace

import design_execution_reconciliation as reconciliation
import pytest
from design_changeset import ValidationTaskKind
from design_execution_planning import (
    ExecutionDependency,
    ExecutionPlanner,
    ExecutionPlanningRequest,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
    compute_execution_plan_hash,
    compute_routing_snapshot_hash,
)


def _builder():
    return reconciliation.ExecutionSagaBuilder()


def _build(transaction, *, plan=None):
    return _builder().build(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan if plan is None else plan,
    )


def _unit_index(plan):
    return {
        unit.execution_unit_id: unit
        for slice_ in plan.execution_slices
        for unit in slice_.execution_units
    }


def _slice_by_unit(plan):
    return {
        unit.execution_unit_id: slice_.execution_slice_hash
        for slice_ in plan.execution_slices
        for unit in slice_.execution_units
    }


def _slice_by_operation(plan):
    result = {}
    for slice_ in plan.execution_slices:
        for unit in slice_.execution_units:
            result.setdefault(unit.source_operation_id, []).append(
                slice_.execution_slice_hash
            )
    return result


def _rehash_plan(plan, *, slices=None, dependencies=None):
    execution_slices = plan.execution_slices if slices is None else tuple(slices)
    execution_dependencies = (
        plan.execution_dependencies if dependencies is None else tuple(dependencies)
    )
    unit_by_id = {
        unit.execution_unit_id: unit
        for slice_ in execution_slices
        for unit in slice_.execution_units
    }
    dependency_semantics = tuple(
        (
            unit_by_id[item.predecessor_execution_unit_id].execution_unit_hash,
            unit_by_id[item.successor_execution_unit_id].execution_unit_hash,
            item.reason_ref,
        )
        for item in execution_dependencies
    )
    plan_hash = compute_execution_plan_hash(
        changeset_hash=plan.changeset_hash,
        scope_hash=plan.approval_scope_ref.scope_hash,
        routing_snapshot_hash=plan.routing_snapshot_hash,
        execution_slice_hashes=(item.execution_slice_hash for item in execution_slices),
        execution_dependencies=dependency_semantics,
    )
    return replace(
        plan,
        execution_plan_id=f"XP-{plan_hash[:12]}",
        execution_slices=execution_slices,
        execution_dependencies=execution_dependencies,
        execution_plan_hash=plan_hash,
    )


def _single_host_plan(transaction):
    changeset = transaction.canonical_changeset
    boundary = transaction.approval_scope_boundary
    runtime = HostRuntimeRef("TEST_HOST", "HOST-STEP33-SAME", "DOC-1")
    routes = tuple(
        RuntimeEntityRoute(target, runtime)
        for operation in (changeset.root_operation, *changeset.derived_operations)
        for target in operation.targets
    )
    routing = RuntimeRoutingEvidence(
        "RRS-STEP33-SAME",
        routes,
        compute_routing_snapshot_hash(routes),
    )
    return ExecutionPlanner().plan(
        ExecutionPlanningRequest(changeset, boundary, routing)
    )


def _assignment_index(definition):
    result = {}
    for assignment in definition.slice_validation_assignments:
        for task_id in assignment.validation_task_ids:
            assert task_id not in result
            result[task_id] = assignment.execution_slice_hash
    return result


def _expected_task_slice(transaction, task):
    changeset = transaction.canonical_changeset
    plan = transaction.execution_plan
    operations = (changeset.root_operation, *changeset.derived_operations)
    slice_by_operation = _slice_by_operation(plan)

    if task.kind is ValidationTaskKind.CANONICAL_OPERATION:
        matches = tuple(
            operation
            for operation in operations
            if f"{operation.canonical_operation}@{operation.canonical_operation_version}"
            == task.canonical_operation_ref
            and operation.targets == task.subject_semantic_ids
        )
        assert len(matches) == 1
        slices = slice_by_operation[matches[0].operation_id]
        assert len(slices) == 1
        return slices[0]

    assert task.kind is ValidationTaskKind.DEPENDENCY_VERIFICATION
    impacts = tuple(
        impact
        for impact in changeset.semantic_impacts
        if impact.dependency_ref == task.dependency_ref
        and (impact.affected_semantic_id,) == task.subject_semantic_ids
    )
    assert len(impacts) == 1
    impact = impacts[0]
    affected_ops = tuple(
        operation
        for operation in operations
        if impact.affected_semantic_id in operation.targets
    )
    if len(affected_ops) == 1:
        owner = affected_ops[0]
    else:
        source_ops = tuple(
            operation
            for operation in operations
            if impact.source_semantic_id in operation.targets
        )
        assert len(source_ops) == 1
        owner = source_ops[0]
    slices = slice_by_operation[owner.operation_id]
    assert len(slices) == 1
    return slices[0]


def test_two_slice_plan_projects_cross_slice_dag_and_all_tasks_once(
    step33_two_slice_transaction,
) -> None:
    transaction = step33_two_slice_transaction
    definition = _build(transaction)
    plan = transaction.execution_plan

    assert definition.changeset_hash == transaction.canonical_changeset.changeset_hash
    assert definition.approved_scope_hash == transaction.approval_scope_boundary.scope_hash
    assert definition.execution_plan_hash == plan.execution_plan_hash
    assert set(definition.ordered_slice_hashes) == {
        slice_.execution_slice_hash for slice_ in plan.execution_slices
    }
    assert definition.saga_id == f"SG-{definition.saga_definition_hash[:12]}"

    unit_by_id = _unit_index(plan)
    slice_by_unit = _slice_by_unit(plan)
    expected_edges = {}
    for dependency in plan.execution_dependencies:
        predecessor = slice_by_unit[dependency.predecessor_execution_unit_id]
        successor = slice_by_unit[dependency.successor_execution_unit_id]
        if predecessor == successor:
            continue
        expected_edges.setdefault((predecessor, successor), set()).add(
            dependency.reason_ref
        )
    actual_edges = {
        (edge.predecessor_slice_hash, edge.successor_slice_hash): set(edge.reason_refs)
        for edge in definition.slice_dependencies
    }
    assert actual_edges == expected_edges
    assert all(
        unit_by_id[item.predecessor_execution_unit_id].execution_unit_hash
        for item in plan.execution_dependencies
    )

    assignment_by_task = _assignment_index(definition)
    assert set(assignment_by_task) == {
        task.validation_task_id
        for task in transaction.canonical_changeset.validation_tasks
    }
    for task in transaction.canonical_changeset.validation_tasks:
        assert assignment_by_task[task.validation_task_id] == _expected_task_slice(
            transaction,
            task,
        )


def test_same_slice_unit_dependency_does_not_create_self_edge(
    step33_two_slice_transaction,
) -> None:
    plan = _single_host_plan(step33_two_slice_transaction)
    assert len(plan.execution_slices) == 1
    assert plan.execution_dependencies

    definition = _build(step33_two_slice_transaction, plan=plan)

    assert definition.slice_dependencies == ()
    assert definition.ordered_slice_hashes == (
        plan.execution_slices[0].execution_slice_hash,
    )


def test_definition_is_stable_under_valid_plan_tuple_reordering(
    step33_two_slice_transaction,
) -> None:
    plan = step33_two_slice_transaction.execution_plan
    reversed_plan = _rehash_plan(
        plan,
        slices=tuple(reversed(plan.execution_slices)),
        dependencies=tuple(reversed(plan.execution_dependencies)),
    )
    assert reversed_plan.execution_plan_hash == plan.execution_plan_hash

    first = _build(step33_two_slice_transaction, plan=plan)
    second = _build(step33_two_slice_transaction, plan=reversed_plan)

    assert second.ordered_slice_hashes == first.ordered_slice_hashes
    assert second.slice_dependencies == first.slice_dependencies
    assert second.slice_validation_assignments == first.slice_validation_assignments
    assert second.saga_definition_hash == first.saga_definition_hash
    assert second.saga_id == first.saga_id


def test_independent_roots_use_slice_hash_as_topological_tiebreaker(
    step33_two_slice_transaction,
) -> None:
    plan = _rehash_plan(
        step33_two_slice_transaction.execution_plan,
        dependencies=(),
    )

    definition = _build(step33_two_slice_transaction, plan=plan)

    assert definition.slice_dependencies == ()
    assert definition.ordered_slice_hashes == tuple(
        sorted(slice_.execution_slice_hash for slice_ in plan.execution_slices)
    )


def test_projected_slice_cycle_fails_closed_even_when_step30_plan_is_hash_valid(
    step33_two_slice_transaction,
) -> None:
    plan = step33_two_slice_transaction.execution_plan
    assert len(plan.execution_slices) == 2
    assert len(plan.execution_dependencies) == 1
    existing = plan.execution_dependencies[0]
    reverse = ExecutionDependency(
        existing.successor_execution_unit_id,
        existing.predecessor_execution_unit_id,
        "TASK8-CYCLE",
    )
    cyclic = _rehash_plan(plan, dependencies=(*plan.execution_dependencies, reverse))

    with pytest.raises(reconciliation.ReconciliationError) as exc:
        _build(step33_two_slice_transaction, plan=cyclic)

    assert exc.value.code == "SAGA_INTEGRITY_INVALID"


def test_unresolved_or_ambiguous_source_operation_assignment_fails_closed(
    step33_two_slice_transaction,
) -> None:
    plan = step33_two_slice_transaction.execution_plan
    first_slice, second_slice = plan.execution_slices
    first_unit = first_slice.execution_units[0]
    second_unit = second_slice.execution_units[0]

    unresolved_slice = replace(
        first_slice,
        execution_units=(replace(first_unit, source_operation_id="COP-UNKNOWN"),),
    )
    unresolved_plan = _rehash_plan(
        plan,
        slices=(unresolved_slice, second_slice),
    )
    with pytest.raises(reconciliation.ReconciliationError) as unresolved_exc:
        _build(step33_two_slice_transaction, plan=unresolved_plan)
    assert unresolved_exc.value.code == "SAGA_INTEGRITY_INVALID"

    ambiguous_slice = replace(
        second_slice,
        execution_units=(
            replace(
                second_unit,
                source_operation_id=first_unit.source_operation_id,
            ),
        ),
    )
    ambiguous_plan = _rehash_plan(
        plan,
        slices=(first_slice, ambiguous_slice),
    )
    with pytest.raises(reconciliation.ReconciliationError) as ambiguous_exc:
        _build(step33_two_slice_transaction, plan=ambiguous_plan)
    assert ambiguous_exc.value.code == "SAGA_INTEGRITY_INVALID"


def test_invalid_upstream_artifacts_are_mapped_with_structured_upstream_code(
    step33_two_slice_transaction,
) -> None:
    transaction = step33_two_slice_transaction

    bad_boundary = replace(
        transaction.approval_scope_boundary,
        scope_hash="f" * 64,
    )
    with pytest.raises(reconciliation.ReconciliationError) as boundary_exc:
        _builder().build(
            transaction.canonical_changeset,
            bad_boundary,
            transaction.execution_plan,
        )
    assert boundary_exc.value.code == "SAGA_INTEGRITY_INVALID"
    assert boundary_exc.value.upstream_code is not None

    bad_changeset = replace(
        transaction.canonical_changeset,
        changeset_hash="e" * 64,
    )
    with pytest.raises(reconciliation.ReconciliationError) as changeset_exc:
        _builder().build(
            bad_changeset,
            transaction.approval_scope_boundary,
            transaction.execution_plan,
        )
    assert changeset_exc.value.code == "SAGA_INTEGRITY_INVALID"
    assert changeset_exc.value.upstream_code is not None

    bad_plan = replace(
        transaction.execution_plan,
        execution_plan_hash="d" * 64,
    )
    with pytest.raises(reconciliation.ReconciliationError) as plan_exc:
        _builder().build(
            transaction.canonical_changeset,
            transaction.approval_scope_boundary,
            bad_plan,
        )
    assert plan_exc.value.code == "SAGA_INTEGRITY_INVALID"
    assert plan_exc.value.upstream_code is not None


def test_valid_but_cross_transaction_lineage_mismatch_is_rejected(
    step33_single_slice_transaction,
    step33_two_slice_transaction,
) -> None:
    with pytest.raises(reconciliation.ReconciliationError) as exc:
        _builder().build(
            step33_single_slice_transaction.canonical_changeset,
            step33_single_slice_transaction.approval_scope_boundary,
            step33_two_slice_transaction.execution_plan,
        )

    assert exc.value.code == "SAGA_INTEGRITY_INVALID"


def test_assignment_material_is_part_of_saga_definition_hash(
    step33_two_slice_transaction,
) -> None:
    definition = _build(step33_two_slice_transaction)
    assert len(definition.slice_validation_assignments) == 2
    left, right = definition.slice_validation_assignments
    assert left.validation_task_ids

    moved_task = left.validation_task_ids[0]
    mutated_left = reconciliation.SliceValidationAssignment(
        left.execution_slice_hash,
        left.validation_task_ids[1:],
    )
    mutated_right = reconciliation.SliceValidationAssignment(
        right.execution_slice_hash,
        (*right.validation_task_ids, moved_task),
    )
    mutated = replace(
        definition,
        slice_validation_assignments=(mutated_left, mutated_right),
    )

    assert (
        reconciliation.compute_execution_saga_definition_hash(mutated)
        != definition.saga_definition_hash
    )
