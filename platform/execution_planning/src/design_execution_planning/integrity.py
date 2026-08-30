"""Integrity reconstruction for immutable Step30 execution slices."""

from __future__ import annotations

from .contracts import (
    ExecutionPlanningError,
    ExecutionSlice,
    ExecutionUnit,
)
from .hashing import (
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


__all__ = ["validate_execution_slice_integrity"]
