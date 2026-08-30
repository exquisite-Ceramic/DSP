"""Integrity reconstruction for immutable Step30 execution slices and plans."""

from __future__ import annotations

from .contracts import (
    ExecutionPlan,
    ExecutionPlanningError,
    ExecutionSlice,
    ExecutionUnit,
)
from .hashing import (
    compute_execution_plan_hash,
    compute_execution_slice_hash,
    compute_execution_unit_hash,
)


def _invalid(code: str, message: str) -> None:
    raise ExecutionPlanningError(code, message)


def _validate_execution_unit(unit: ExecutionUnit, changeset_hash: str) -> None:
    if not isinstance(unit, ExecutionUnit):
        _invalid(
            "EXECUTION_UNIT_INTEGRITY_INVALID",
            "execution slice contains a non-ExecutionUnit value",
        )

    expected_hash = compute_execution_unit_hash(
        changeset_hash=changeset_hash,
        source_operation_hash=unit.source_operation_hash,
        canonical_operation=unit.canonical_operation,
        canonical_operation_version=unit.canonical_operation_version,
        canonical_definition_fingerprint=unit.canonical_definition_fingerprint,
        targets=unit.targets,
        arguments=unit.arguments,
        preconditions=unit.preconditions,
        expected_effects=unit.expected_effects,
    )
    if unit.execution_unit_hash != expected_hash:
        _invalid(
            "EXECUTION_UNIT_INTEGRITY_INVALID",
            "execution unit body does not match its committed hash",
        )
    if unit.execution_unit_id != f"EU-{expected_hash[:12]}":
        _invalid(
            "EXECUTION_UNIT_INTEGRITY_INVALID",
            "execution unit id does not match its semantic hash",
        )


def validate_execution_slice_integrity(execution_slice: ExecutionSlice) -> None:
    """Reconstruct and verify one final Step30 execution slice fail-closed."""
    if not isinstance(execution_slice, ExecutionSlice):
        raise TypeError("execution_slice must be ExecutionSlice")

    for unit in execution_slice.execution_units:
        _validate_execution_unit(unit, execution_slice.changeset_hash)

    expected_hash = compute_execution_slice_hash(
        changeset_hash=execution_slice.changeset_hash,
        scope_hash=execution_slice.approved_scope_ref.scope_hash,
        execution_slice_scope_rule_id=(
            execution_slice.approved_scope_ref.execution_slice_scope_rule_id
        ),
        host_runtime_ref=execution_slice.host_runtime_ref,
        execution_unit_hashes=(
            unit.execution_unit_hash for unit in execution_slice.execution_units
        ),
    )
    if execution_slice.execution_slice_hash != expected_hash:
        _invalid(
            "EXECUTION_SLICE_INTEGRITY_INVALID",
            "execution slice body does not match its committed hash",
        )
    if execution_slice.execution_slice_id != f"XS-{expected_hash[:12]}":
        _invalid(
            "EXECUTION_SLICE_INTEGRITY_INVALID",
            "execution slice id does not match its semantic hash",
        )


def validate_execution_plan_integrity(execution_plan: ExecutionPlan) -> None:
    """Reconstruct one immutable Step30 ExecutionPlan fail-closed."""
    if not isinstance(execution_plan, ExecutionPlan):
        raise TypeError("execution_plan must be ExecutionPlan")

    unit_by_id: dict[str, ExecutionUnit] = {}
    for execution_slice in execution_plan.execution_slices:
        validate_execution_slice_integrity(execution_slice)
        if execution_slice.changeset_hash != execution_plan.changeset_hash:
            _invalid(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "execution slice changeset does not match execution plan",
            )
        if (
            execution_slice.approved_scope_ref.scope_hash
            != execution_plan.approval_scope_ref.scope_hash
        ):
            _invalid(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "execution slice scope does not match execution plan",
            )
        for unit in execution_slice.execution_units:
            if unit.execution_unit_id in unit_by_id:
                _invalid(
                    "EXECUTION_PLAN_INTEGRITY_INVALID",
                    "duplicate execution unit id across execution slices",
                )
            unit_by_id[unit.execution_unit_id] = unit

    dependency_semantics: list[tuple[str, str, str]] = []
    for dependency in execution_plan.execution_dependencies:
        predecessor = unit_by_id.get(dependency.predecessor_execution_unit_id)
        successor = unit_by_id.get(dependency.successor_execution_unit_id)
        if predecessor is None or successor is None:
            _invalid(
                "EXECUTION_PLAN_INTEGRITY_INVALID",
                "execution dependency endpoint is not a member of the execution plan",
            )
        dependency_semantics.append(
            (
                predecessor.execution_unit_hash,
                successor.execution_unit_hash,
                dependency.reason_ref,
            )
        )

    expected_hash = compute_execution_plan_hash(
        changeset_hash=execution_plan.changeset_hash,
        scope_hash=execution_plan.approval_scope_ref.scope_hash,
        routing_snapshot_hash=execution_plan.routing_snapshot_hash,
        execution_slice_hashes=(
            execution_slice.execution_slice_hash
            for execution_slice in execution_plan.execution_slices
        ),
        execution_dependencies=dependency_semantics,
    )
    if execution_plan.execution_plan_hash != expected_hash:
        _invalid(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "execution plan body does not match its committed hash",
        )
    if execution_plan.execution_plan_id != f"XP-{expected_hash[:12]}":
        _invalid(
            "EXECUTION_PLAN_INTEGRITY_INVALID",
            "execution plan id does not match its semantic hash",
        )


__all__ = [
    "validate_execution_plan_integrity",
    "validate_execution_slice_integrity",
]
