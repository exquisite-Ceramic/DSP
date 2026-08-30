"""Deterministic immutable Saga definition builder for Step33."""

from __future__ import annotations

import heapq
from collections import defaultdict

from design_approval_scope import (
    ApprovalScopeBoundary,
    ApprovalScopeError,
    ExistingEntityRule,
    validate_approval_scope_boundary,
)
from design_changeset import (
    CanonicalChangeOperation,
    CanonicalChangeSet,
    ChangeSetError,
    ValidationTask,
    ValidationTaskKind,
    compute_operation_semantic_hash,
    compute_scope_rule_fingerprint,
    validate_changeset_integrity,
)
from design_execution_planning import (
    ExecutionPlan,
    ExecutionPlanningError,
    ExecutionSlice,
    ExecutionUnit,
    validate_execution_plan_integrity,
)
from semantic_runtime import SemanticEnvironmentRef

from .contracts import ReconciliationError
from .hashing import compute_execution_saga_definition_hash
from .saga_contracts import (
    ExecutionSagaDefinition,
    SliceDependency,
    SliceValidationAssignment,
)


def _invalid(message: str, *, upstream_code: str | None = None) -> None:
    raise ReconciliationError(
        "SAGA_INTEGRITY_INVALID",
        message,
        upstream_code=upstream_code,
    )


def _validate_upstream(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundary,
    execution_plan: ExecutionPlan,
) -> None:
    try:
        validate_approval_scope_boundary(boundary)
    except ApprovalScopeError as exc:
        _invalid("Step28 ApprovalScopeBoundary integrity failed", upstream_code=exc.code)
    except (TypeError, ValueError) as exc:
        _invalid(
            "Step28 ApprovalScopeBoundary validation failed",
            upstream_code=type(exc).__name__,
        )

    try:
        validate_changeset_integrity(changeset, boundary)
    except ChangeSetError as exc:
        _invalid("Step29 CanonicalChangeSet integrity failed", upstream_code=exc.code)
    except (TypeError, ValueError) as exc:
        _invalid(
            "Step29 CanonicalChangeSet validation failed",
            upstream_code=type(exc).__name__,
        )

    try:
        validate_execution_plan_integrity(execution_plan)
    except ExecutionPlanningError as exc:
        _invalid("Step30 ExecutionPlan integrity failed", upstream_code=exc.code)
    except (TypeError, ValueError) as exc:
        _invalid(
            "Step30 ExecutionPlan validation failed",
            upstream_code=type(exc).__name__,
        )


def _operations(changeset: CanonicalChangeSet) -> tuple[CanonicalChangeOperation, ...]:
    return (changeset.root_operation, *changeset.derived_operations)


def _scope_rules(boundary: ApprovalScopeBoundary) -> dict[str, ExistingEntityRule]:
    rules: dict[str, ExistingEntityRule] = {}
    for rule in boundary.existing_entity_rules:
        if rule.rule_id in rules:
            _invalid("Step28 Boundary contains duplicate existing entity rule ids")
        rules[rule.rule_id] = rule
    return rules


def _operation_hashes(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundary,
) -> dict[str, str]:
    rules = _scope_rules(boundary)
    result: dict[str, str] = {}
    for operation in _operations(changeset):
        try:
            fingerprints = tuple(
                sorted(
                    compute_scope_rule_fingerprint(rules[rule_id])
                    for rule_id in operation.scope_rule_ids
                )
            )
        except KeyError as exc:
            _invalid(f"Step29 operation references unresolved scope rule {exc.args[0]}")
        operation_hash = compute_operation_semantic_hash(
            origin=operation.origin,
            canonical_operation=operation.canonical_operation,
            canonical_operation_version=operation.canonical_operation_version,
            canonical_definition_fingerprint=operation.canonical_definition_fingerprint,
            targets=operation.targets,
            arguments=operation.arguments,
            expected_effects=operation.expected_effects,
            scope_rule_fingerprints=fingerprints,
            source_evidence=operation.source_evidence,
        )
        if operation.operation_id != f"COP-{operation_hash[:12]}":
            _invalid("Step29 operation id does not match its semantic hash")
        if operation.operation_id in result:
            _invalid("Step29 operation ids are not unique")
        result[operation.operation_id] = operation_hash
    return result


def _aspect_values(values) -> tuple[str, ...]:
    return tuple(sorted(getattr(item, "value", str(item)) for item in values))


def _validate_unit_against_operation(
    unit: ExecutionUnit,
    operation: CanonicalChangeOperation,
    expected_operation_hash: str,
    changeset: CanonicalChangeSet,
) -> None:
    if unit.source_operation_hash != expected_operation_hash:
        _invalid("ExecutionUnit source_operation_hash does not join its Step29 operation")
    if (
        unit.canonical_operation != operation.canonical_operation
        or unit.canonical_operation_version != operation.canonical_operation_version
        or unit.canonical_definition_fingerprint
        != operation.canonical_definition_fingerprint
        or unit.targets != operation.targets
        or dict(unit.arguments) != dict(operation.arguments)
        or unit.preconditions != changeset.preconditions
        or _aspect_values(unit.expected_effects) != _aspect_values(operation.expected_effects)
    ):
        _invalid("ExecutionUnit semantic body does not exactly project its Step29 operation")


def _validate_lineage(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundary,
    execution_plan: ExecutionPlan,
) -> tuple[dict[str, ExecutionSlice], dict[str, str]]:
    if not (
        changeset.changeset_hash
        == boundary.changeset_hash
        == execution_plan.changeset_hash
    ):
        _invalid("Step28→29→30 ChangeSet hash lineage does not join exactly")
    if execution_plan.changeset_id != changeset.changeset_id:
        _invalid("ExecutionPlan changeset_id does not match the Step29 ChangeSet")
    if (
        execution_plan.approval_scope_ref.scope_id != boundary.scope_id
        or execution_plan.approval_scope_ref.scope_hash != boundary.scope_hash
    ):
        _invalid("ExecutionPlan approved scope does not match the exact Step28 Boundary")
    if changeset.semantic_environment_ref != boundary.semantic_environment_ref:
        _invalid("Step29 and Step28 semantic environments differ")
    if (
        boundary.planning_snapshot_ref.semantic_environment
        != boundary.semantic_environment_ref
        or boundary.snapshot_set_ref.semantic_environment
        != boundary.semantic_environment_ref
    ):
        _invalid("Step28 planning state does not share one semantic environment")

    operation_by_id = {operation.operation_id: operation for operation in _operations(changeset)}
    operation_hash_by_id = _operation_hashes(changeset, boundary)
    slice_by_hash: dict[str, ExecutionSlice] = {}
    slice_by_unit_id: dict[str, str] = {}
    slices_by_operation_id: dict[str, list[str]] = defaultdict(list)
    known_slice_scope_ids = {
        rule.slice_scope_rule_id: rule for rule in boundary.execution_slice_scopes
    }

    for execution_slice in execution_plan.execution_slices:
        slice_hash = execution_slice.execution_slice_hash
        if slice_hash in slice_by_hash:
            _invalid("ExecutionPlan contains duplicate Slice hashes")
        slice_by_hash[slice_hash] = execution_slice
        if (
            execution_slice.changeset_id != changeset.changeset_id
            or execution_slice.changeset_hash != changeset.changeset_hash
        ):
            _invalid("ExecutionSlice does not join the exact Step29 ChangeSet")
        if (
            execution_slice.approved_scope_ref.scope_id != boundary.scope_id
            or execution_slice.approved_scope_ref.scope_hash != boundary.scope_hash
        ):
            _invalid("ExecutionSlice does not join the exact Step28 Boundary")
        scope_rule = known_slice_scope_ids.get(
            execution_slice.approved_scope_ref.execution_slice_scope_rule_id
        )
        if scope_rule is None:
            _invalid("ExecutionSlice references an unknown Step28 slice scope rule")
        if scope_rule.document_ref != execution_slice.host_runtime_ref.document_ref:
            _invalid("ExecutionSlice document does not match its Step28 slice scope rule")

        for unit in execution_slice.execution_units:
            if unit.execution_unit_id in slice_by_unit_id:
                _invalid("ExecutionUnit appears in more than one Slice")
            slice_by_unit_id[unit.execution_unit_id] = slice_hash
            operation = operation_by_id.get(unit.source_operation_id)
            if operation is None:
                _invalid("ExecutionUnit source_operation_id is not a Step29 operation")
            _validate_unit_against_operation(
                unit,
                operation,
                operation_hash_by_id[operation.operation_id],
                changeset,
            )
            slices_by_operation_id[operation.operation_id].append(slice_hash)

    if set(slices_by_operation_id) != set(operation_by_id):
        _invalid("ExecutionPlan does not project every Step29 operation exactly once")
    for operation_id, slice_hashes in slices_by_operation_id.items():
        if len(slice_hashes) != 1:
            _invalid(
                f"Step29 operation {operation_id} resolves to multiple ExecutionSlices"
            )

    return slice_by_hash, {
        operation_id: slice_hashes[0]
        for operation_id, slice_hashes in slices_by_operation_id.items()
    }


def _project_slice_dependencies(
    execution_plan: ExecutionPlan,
    slice_by_hash: dict[str, ExecutionSlice],
) -> tuple[SliceDependency, ...]:
    slice_by_unit_id = {
        unit.execution_unit_id: execution_slice.execution_slice_hash
        for execution_slice in slice_by_hash.values()
        for unit in execution_slice.execution_units
    }
    reasons_by_edge: dict[tuple[str, str], set[str]] = defaultdict(set)
    for dependency in execution_plan.execution_dependencies:
        try:
            predecessor = slice_by_unit_id[dependency.predecessor_execution_unit_id]
            successor = slice_by_unit_id[dependency.successor_execution_unit_id]
        except KeyError as exc:
            _invalid(f"ExecutionDependency endpoint is unresolved: {exc.args[0]}")
        if predecessor == successor:
            continue
        reasons_by_edge[(predecessor, successor)].add(dependency.reason_ref)
    return tuple(
        SliceDependency(predecessor, successor, tuple(sorted(reasons)))
        for (predecessor, successor), reasons in sorted(reasons_by_edge.items())
    )


def _topological_order(
    slice_hashes: tuple[str, ...],
    dependencies: tuple[SliceDependency, ...],
) -> tuple[str, ...]:
    indegree = {slice_hash: 0 for slice_hash in slice_hashes}
    successors: dict[str, set[str]] = {slice_hash: set() for slice_hash in slice_hashes}
    for dependency in dependencies:
        if (
            dependency.predecessor_slice_hash not in indegree
            or dependency.successor_slice_hash not in indegree
        ):
            _invalid("Slice dependency references a Slice outside the ExecutionPlan")
        if dependency.successor_slice_hash not in successors[dependency.predecessor_slice_hash]:
            successors[dependency.predecessor_slice_hash].add(dependency.successor_slice_hash)
            indegree[dependency.successor_slice_hash] += 1

    eligible = [slice_hash for slice_hash, degree in indegree.items() if degree == 0]
    heapq.heapify(eligible)
    ordered: list[str] = []
    while eligible:
        current = heapq.heappop(eligible)
        ordered.append(current)
        for successor in sorted(successors[current]):
            indegree[successor] -= 1
            if indegree[successor] == 0:
                heapq.heappush(eligible, successor)

    if len(ordered) != len(slice_hashes):
        _invalid("projected ExecutionSlice dependency graph contains a cycle")
    return tuple(ordered)


def _canonical_task_operation(
    task: ValidationTask,
    operations: tuple[CanonicalChangeOperation, ...],
) -> CanonicalChangeOperation:
    matches = tuple(
        operation
        for operation in operations
        if f"{operation.canonical_operation}@{operation.canonical_operation_version}"
        == task.canonical_operation_ref
        and operation.targets == task.subject_semantic_ids
    )
    if len(matches) != 1:
        _invalid("canonical ValidationTask does not resolve to exactly one Step29 operation")
    return matches[0]


def _dependency_task_operation(
    task: ValidationTask,
    changeset: CanonicalChangeSet,
    operations: tuple[CanonicalChangeOperation, ...],
) -> CanonicalChangeOperation:
    impacts = tuple(
        impact
        for impact in changeset.semantic_impacts
        if impact.dependency_ref == task.dependency_ref
        and task.subject_semantic_ids == (impact.affected_semantic_id,)
    )
    if len(impacts) != 1:
        _invalid("dependency ValidationTask does not resolve to exactly one semantic impact")
    impact = impacts[0]

    affected_operations = tuple(
        operation
        for operation in operations
        if impact.affected_semantic_id in operation.targets
    )
    if len(affected_operations) == 1:
        return affected_operations[0]

    source_operations = tuple(
        operation
        for operation in operations
        if impact.source_semantic_id in operation.targets
    )
    if len(source_operations) != 1:
        _invalid("dependency ValidationTask owner operation is unresolved or ambiguous")
    return source_operations[0]


def _validation_assignments(
    changeset: CanonicalChangeSet,
    operation_slice: dict[str, str],
    slice_hashes: tuple[str, ...],
) -> tuple[SliceValidationAssignment, ...]:
    operations = _operations(changeset)
    task_ids: set[str] = set()
    tasks_by_slice: dict[str, list[str]] = {slice_hash: [] for slice_hash in slice_hashes}

    for task in changeset.validation_tasks:
        if task.validation_task_id in task_ids:
            _invalid("ValidationTask ids are not unique")
        task_ids.add(task.validation_task_id)

        if task.kind is ValidationTaskKind.CANONICAL_OPERATION:
            operation = _canonical_task_operation(task, operations)
        elif task.kind is ValidationTaskKind.DEPENDENCY_VERIFICATION:
            operation = _dependency_task_operation(task, changeset, operations)
        else:
            _invalid(f"unsupported ValidationTask kind {task.kind!r}")

        slice_hash = operation_slice.get(operation.operation_id)
        if slice_hash is None:
            _invalid("ValidationTask owner operation has no ExecutionSlice")
        tasks_by_slice[slice_hash].append(task.validation_task_id)

    assignments = tuple(
        SliceValidationAssignment(slice_hash, tuple(sorted(tasks_by_slice[slice_hash])))
        for slice_hash in sorted(slice_hashes)
    )
    assigned_task_ids = {
        task_id for assignment in assignments for task_id in assignment.validation_task_ids
    }
    if assigned_task_ids != task_ids:
        _invalid("not every ValidationTask is assigned exactly once")
    return assignments


class ExecutionSagaBuilder:
    """Build one immutable Step33 Saga definition from validated Steps 28–30."""

    def build(
        self,
        changeset: CanonicalChangeSet,
        boundary: ApprovalScopeBoundary,
        execution_plan: ExecutionPlan,
    ) -> ExecutionSagaDefinition:
        _validate_upstream(changeset, boundary, execution_plan)
        slice_by_hash, operation_slice = _validate_lineage(
            changeset,
            boundary,
            execution_plan,
        )
        slice_hashes = tuple(slice_by_hash)
        dependencies = _project_slice_dependencies(execution_plan, slice_by_hash)
        ordered_slice_hashes = _topological_order(slice_hashes, dependencies)
        assignments = _validation_assignments(
            changeset,
            operation_slice,
            slice_hashes,
        )
        environment = changeset.semantic_environment_ref
        semantic_environment_ref = SemanticEnvironmentRef(
            environment.environment_id,
            environment.content_hash,
        )
        draft = ExecutionSagaDefinition(
            saga_id="SG-DRAFT",
            changeset_hash=changeset.changeset_hash,
            approved_scope_hash=boundary.scope_hash,
            semantic_environment_ref=semantic_environment_ref,
            execution_plan_hash=execution_plan.execution_plan_hash,
            ordered_slice_hashes=ordered_slice_hashes,
            slice_dependencies=dependencies,
            slice_validation_assignments=assignments,
            saga_definition_hash="0" * 64,
        )
        definition_hash = compute_execution_saga_definition_hash(draft)
        return ExecutionSagaDefinition(
            saga_id=f"SG-{definition_hash[:12]}",
            changeset_hash=draft.changeset_hash,
            approved_scope_hash=draft.approved_scope_hash,
            semantic_environment_ref=draft.semantic_environment_ref,
            execution_plan_hash=draft.execution_plan_hash,
            ordered_slice_hashes=draft.ordered_slice_hashes,
            slice_dependencies=draft.slice_dependencies,
            slice_validation_assignments=draft.slice_validation_assignments,
            saga_definition_hash=definition_hash,
        )


__all__ = ["ExecutionSagaBuilder"]
