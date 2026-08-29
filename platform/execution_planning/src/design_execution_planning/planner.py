"""Fail-closed deterministic execution partitioning for Step30."""

from __future__ import annotations

from collections.abc import Mapping

from design_approval_scope import (
    ApprovalScopeBoundary,
    ExecutionSliceScopeRule,
    ExistingEntityRule,
)
from design_changeset import (
    CanonicalChangeOperation,
    CanonicalChangeSet,
    compute_operation_semantic_hash,
    compute_scope_rule_fingerprint,
)

from .contracts import (
    ApprovalScopeRef,
    ApprovedExecutionScopeRef,
    ExecutionDependency,
    ExecutionPlan,
    ExecutionPlanningError,
    ExecutionPlanningRequest,
    ExecutionSlice,
    ExecutionUnit,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
)
from .hashing import (
    compute_execution_plan_hash,
    compute_execution_slice_hash,
    compute_execution_unit_hash,
    compute_routing_snapshot_hash,
)


def _error(code: str, message: str):
    raise ExecutionPlanningError(code, message)


def _operations(changeset: CanonicalChangeSet) -> tuple[CanonicalChangeOperation, ...]:
    return (changeset.root_operation, *changeset.derived_operations)


def _validate_scope_binding(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundary,
) -> dict[str, ExistingEntityRule]:
    if changeset.changeset_hash != boundary.changeset_hash:
        _error("EXECUTION_SCOPE_MISMATCH", "approval scope does not bind this ChangeSet")
    if changeset.approval_scope_definition_ref.scope_body_hash != boundary.scope_body_hash:
        _error("EXECUTION_SCOPE_MISMATCH", "approval scope body differs from the ChangeSet scope reference")

    rules: dict[str, ExistingEntityRule] = {}
    for rule in boundary.existing_entity_rules:
        if rule.rule_id in rules:
            _error("EXECUTION_SCOPE_MISMATCH", "approval scope contains duplicate existing rule ids")
        rules[rule.rule_id] = rule

    for operation in _operations(changeset):
        if not operation.scope_rule_ids:
            _error("EXECUTION_SCOPE_MISMATCH", "canonical operation has no Step28 mutation authority")
        unknown = set(operation.scope_rule_ids) - set(rules)
        if unknown:
            _error(
                "EXECUTION_SCOPE_MISMATCH",
                f"canonical operation references unknown Step28 rules: {sorted(unknown)}",
            )
    return rules


def _source_operation_hash(
    operation: CanonicalChangeOperation,
    rules_by_id: Mapping[str, ExistingEntityRule],
) -> str:
    try:
        fingerprints = tuple(
            sorted(
                compute_scope_rule_fingerprint(rules_by_id[rule_id])
                for rule_id in operation.scope_rule_ids
            )
        )
    except KeyError as exc:
        _error("EXECUTION_SCOPE_MISMATCH", f"operation scope rule is unresolved: {exc.args[0]}")

    source_hash = compute_operation_semantic_hash(
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
    if operation.operation_id != f"COP-{source_hash[:12]}":
        _error(
            "EXECUTION_OPERATION_MISMATCH",
            "canonical operation no longer matches its Step29 semantic identity",
        )
    return source_hash


def _slice_body(rule: ExecutionSliceScopeRule) -> tuple[object, ...]:
    return (
        rule.document_ref,
        tuple(sorted(rule.existing_rule_ids)),
        tuple(sorted(rule.creation_rule_ids)),
        tuple(sorted(rule.deletion_rule_ids)),
    )


def _select_slice_scope(
    operation: CanonicalChangeOperation,
    document_ref: str,
    boundary: ApprovalScopeBoundary,
) -> ExecutionSliceScopeRule:
    required = set(operation.scope_rule_ids)
    candidates: list[tuple[int, tuple[object, ...], ExecutionSliceScopeRule]] = []
    for candidate in boundary.execution_slice_scopes:
        if candidate.document_ref != document_ref:
            continue
        if not required.issubset(candidate.existing_rule_ids):
            continue
        authority = (
            set(candidate.existing_rule_ids)
            | set(candidate.creation_rule_ids)
            | set(candidate.deletion_rule_ids)
        )
        surplus = authority - required
        candidates.append((len(surplus), _slice_body(candidate), candidate))

    if not candidates:
        _error(
            "EXECUTION_SLICE_SCOPE_UNCOVERED",
            "no approved execution slice scope covers this canonical operation",
        )

    minimum = min(item[0] for item in candidates)
    tied = [item for item in candidates if item[0] == minimum]
    bodies = {item[1] for item in tied}
    if len(bodies) != 1:
        _error(
            "EXECUTION_SLICE_SCOPE_AMBIGUOUS",
            "multiple least-authority execution slice scopes have different authority",
        )

    return min((item[2] for item in tied), key=lambda item: item.slice_scope_rule_id)


def _normalize_routes(
    evidence: RuntimeRoutingEvidence,
    required_targets: set[str],
) -> dict[str, HostRuntimeRef]:
    index: dict[str, HostRuntimeRef] = {}
    normalized_routes: list[RuntimeEntityRoute] = []
    for route in evidence.routes:
        previous = index.get(route.semantic_id)
        if previous is not None and previous != route.host_runtime_ref:
            _error(
                "EXECUTION_ROUTE_CONFLICT",
                f"semantic target {route.semantic_id} has conflicting runtime routes",
            )
        if previous is None:
            index[route.semantic_id] = route.host_runtime_ref
            normalized_routes.append(route)

    recomputed = compute_routing_snapshot_hash(tuple(normalized_routes))
    if recomputed != evidence.routing_snapshot_hash:
        _error(
            "EXECUTION_ROUTE_HASH_MISMATCH",
            "runtime routing evidence hash does not match normalized route semantics",
        )

    actual_targets = set(index)
    missing = required_targets - actual_targets
    if missing:
        _error(
            "EXECUTION_ROUTE_UNRESOLVED",
            f"runtime routing is missing required targets: {sorted(missing)}",
        )
    extra = actual_targets - required_targets
    if extra:
        _error(
            "EXECUTION_ROUTE_EXTRANEOUS",
            f"runtime routing contains unrelated targets: {sorted(extra)}",
        )
    return index


def _operation_runtime_ref(
    operation: CanonicalChangeOperation,
    route_index: Mapping[str, HostRuntimeRef],
) -> HostRuntimeRef:
    try:
        refs = {route_index[target] for target in operation.targets}
    except KeyError as exc:
        _error("EXECUTION_ROUTE_UNRESOLVED", f"runtime route is missing: {exc.args[0]}")
    if len(refs) != 1:
        _error(
            "EXECUTION_OPERATION_NOT_PARTITIONABLE",
            "one canonical operation cannot span Host runtime boundaries",
        )
    return next(iter(refs))


def _build_unit(
    changeset: CanonicalChangeSet,
    operation: CanonicalChangeOperation,
    source_operation_hash: str,
) -> ExecutionUnit:
    unit_hash = compute_execution_unit_hash(
        changeset_hash=changeset.changeset_hash,
        source_operation_hash=source_operation_hash,
        canonical_operation=operation.canonical_operation,
        canonical_operation_version=operation.canonical_operation_version,
        canonical_definition_fingerprint=operation.canonical_definition_fingerprint,
        targets=operation.targets,
        arguments=operation.arguments,
        preconditions=changeset.preconditions,
        expected_effects=operation.expected_effects,
    )
    return ExecutionUnit(
        execution_unit_id=f"EU-{unit_hash[:12]}",
        source_operation_id=operation.operation_id,
        source_operation_hash=source_operation_hash,
        canonical_operation=operation.canonical_operation,
        canonical_operation_version=operation.canonical_operation_version,
        canonical_definition_fingerprint=operation.canonical_definition_fingerprint,
        targets=operation.targets,
        arguments=operation.arguments,
        preconditions=changeset.preconditions,
        expected_effects=operation.expected_effects,
        execution_unit_hash=unit_hash,
    )


def _slice_key(
    runtime_ref: HostRuntimeRef,
    scope_rule: ExecutionSliceScopeRule,
) -> tuple[str, str, str, str]:
    return (
        runtime_ref.host_type,
        runtime_ref.host_instance_id,
        runtime_ref.document_ref,
        scope_rule.slice_scope_rule_id,
    )


def _build_slices(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundary,
    planned_units: tuple[tuple[HostRuntimeRef, ExecutionSliceScopeRule, ExecutionUnit], ...],
) -> tuple[ExecutionSlice, ...]:
    grouped: dict[
        tuple[str, str, str, str],
        tuple[HostRuntimeRef, ExecutionSliceScopeRule, list[ExecutionUnit]],
    ] = {}
    for runtime_ref, scope_rule, unit in planned_units:
        key = _slice_key(runtime_ref, scope_rule)
        if key not in grouped:
            grouped[key] = (runtime_ref, scope_rule, [])
        grouped[key][2].append(unit)

    slices: list[ExecutionSlice] = []
    for key in sorted(grouped):
        runtime_ref, scope_rule, units = grouped[key]
        ordered_units = tuple(sorted(units, key=lambda item: item.execution_unit_hash))
        unit_ids = [unit.execution_unit_id for unit in ordered_units]
        if len(set(unit_ids)) != len(unit_ids):
            _error(
                "EXECUTION_OPERATION_MISMATCH",
                "execution unit construction identity is ambiguous",
            )
        slice_hash = compute_execution_slice_hash(
            changeset_hash=changeset.changeset_hash,
            scope_hash=boundary.scope_hash,
            execution_slice_scope_rule_id=scope_rule.slice_scope_rule_id,
            host_runtime_ref=runtime_ref,
            execution_unit_hashes=(unit.execution_unit_hash for unit in ordered_units),
        )
        slices.append(
            ExecutionSlice(
                execution_slice_id=f"XS-{slice_hash[:12]}",
                changeset_id=changeset.changeset_id,
                changeset_hash=changeset.changeset_hash,
                host_runtime_ref=runtime_ref,
                approved_scope_ref=ApprovedExecutionScopeRef(
                    boundary.scope_id,
                    boundary.scope_hash,
                    scope_rule.slice_scope_rule_id,
                ),
                execution_units=ordered_units,
                execution_slice_hash=slice_hash,
            )
        )
    return tuple(sorted(slices, key=lambda item: item.execution_slice_hash))


def _project_dependencies(
    changeset: CanonicalChangeSet,
    unit_by_operation_id: Mapping[str, ExecutionUnit],
) -> tuple[ExecutionDependency, ...]:
    projected: list[ExecutionDependency] = []
    for dependency in changeset.change_dependencies:
        predecessor = unit_by_operation_id.get(dependency.predecessor_operation_id)
        successor = unit_by_operation_id.get(dependency.successor_operation_id)
        if predecessor is None or successor is None:
            _error(
                "EXECUTION_DEPENDENCY_INVALID",
                "Step29 dependency references an operation absent from the execution plan",
            )
        projected.append(
            ExecutionDependency(
                predecessor_execution_unit_id=predecessor.execution_unit_id,
                successor_execution_unit_id=successor.execution_unit_id,
                reason_ref=dependency.reason_ref,
            )
        )
    return tuple(
        sorted(
            projected,
            key=lambda item: (
                item.predecessor_execution_unit_id,
                item.successor_execution_unit_id,
                item.reason_ref,
            ),
        )
    )


class ExecutionPlanner:
    """Project the exact Step29 transaction onto approved runtime Host routes."""

    def plan(self, request: ExecutionPlanningRequest) -> ExecutionPlan:
        if not isinstance(request, ExecutionPlanningRequest):
            _error("EXECUTION_INPUT_INVALID", "request must be ExecutionPlanningRequest")

        changeset = request.canonical_changeset
        boundary = request.approval_scope_boundary
        rules = _validate_scope_binding(changeset, boundary)
        operations = _operations(changeset)
        source_hashes = {
            operation.operation_id: _source_operation_hash(operation, rules)
            for operation in operations
        }
        if len(source_hashes) != len(operations):
            _error("EXECUTION_OPERATION_MISMATCH", "Step29 operation ids must be unique")

        required_targets = {target for operation in operations for target in operation.targets}
        route_index = _normalize_routes(request.runtime_routing_evidence, required_targets)

        planned: list[tuple[HostRuntimeRef, ExecutionSliceScopeRule, ExecutionUnit]] = []
        unit_by_operation_id: dict[str, ExecutionUnit] = {}
        for operation in operations:
            runtime_ref = _operation_runtime_ref(operation, route_index)
            scope_rule = _select_slice_scope(operation, runtime_ref.document_ref, boundary)
            unit = _build_unit(changeset, operation, source_hashes[operation.operation_id])
            if operation.operation_id in unit_by_operation_id:
                _error("EXECUTION_OPERATION_MISMATCH", "one canonical operation cannot project twice")
            unit_by_operation_id[operation.operation_id] = unit
            planned.append((runtime_ref, scope_rule, unit))

        if len(unit_by_operation_id) != len(operations):
            _error("EXECUTION_OPERATION_MISMATCH", "every canonical operation must project exactly once")

        ordered_slices = _build_slices(changeset, boundary, tuple(planned))
        dependencies = _project_dependencies(changeset, unit_by_operation_id)
        plan_hash = compute_execution_plan_hash(
            changeset_hash=changeset.changeset_hash,
            scope_hash=boundary.scope_hash,
            routing_snapshot_hash=request.runtime_routing_evidence.routing_snapshot_hash,
            execution_slice_hashes=(item.execution_slice_hash for item in ordered_slices),
            execution_dependencies=dependencies,
        )
        return ExecutionPlan(
            execution_plan_id=f"XP-{plan_hash[:12]}",
            changeset_id=changeset.changeset_id,
            changeset_hash=changeset.changeset_hash,
            approval_scope_ref=ApprovalScopeRef(boundary.scope_id, boundary.scope_hash),
            routing_snapshot_id=request.runtime_routing_evidence.routing_snapshot_id,
            routing_snapshot_hash=request.runtime_routing_evidence.routing_snapshot_hash,
            execution_slices=ordered_slices,
            execution_dependencies=dependencies,
            execution_plan_hash=plan_hash,
        )


__all__ = [
    "ExecutionPlanner",
    "_build_slices",
    "_build_unit",
    "_normalize_routes",
    "_operation_runtime_ref",
    "_project_dependencies",
    "_select_slice_scope",
    "_source_operation_hash",
    "_validate_scope_binding",
]
