"""Deterministic semantic hashing for Step30 execution planning."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from design_changeset import ChangePrecondition, canonical_hash

from .contracts import HostRuntimeRef, RuntimeEntityRoute


def _runtime_ref_payload(ref: HostRuntimeRef) -> dict[str, str]:
    return {
        "host_type": ref.host_type,
        "host_instance_id": ref.host_instance_id,
        "document_ref": ref.document_ref,
    }


def compute_routing_snapshot_hash(routes: Iterable[RuntimeEntityRoute]) -> str:
    unique: dict[tuple[str, str, str, str], dict[str, object]] = {}
    for route in routes:
        key = (
            route.semantic_id,
            route.host_runtime_ref.host_type,
            route.host_runtime_ref.host_instance_id,
            route.host_runtime_ref.document_ref,
        )
        unique[key] = {
            "semantic_id": route.semantic_id,
            "host_runtime_ref": _runtime_ref_payload(route.host_runtime_ref),
        }
    return canonical_hash([unique[key] for key in sorted(unique)])


def _precondition_payload(precondition: ChangePrecondition) -> dict[str, str]:
    return {
        "kind": precondition.kind.value,
        "subject_ref": precondition.subject_ref,
        "evidence_ref": precondition.evidence_ref,
    }


def compute_execution_unit_hash(
    *,
    changeset_hash: str,
    source_operation_hash: str,
    canonical_operation: str,
    canonical_operation_version: str,
    canonical_definition_fingerprint: str,
    targets: Iterable[str],
    arguments: Mapping[str, Any],
    preconditions: Iterable[ChangePrecondition],
    expected_effects: Iterable[object],
) -> str:
    return canonical_hash(
        {
            "changeset_hash": changeset_hash,
            "source_operation_hash": source_operation_hash,
            "canonical_operation": canonical_operation,
            "canonical_operation_version": canonical_operation_version,
            "canonical_definition_fingerprint": canonical_definition_fingerprint,
            "targets": sorted(set(targets)),
            "arguments": arguments,
            "preconditions": sorted(
                (_precondition_payload(item) for item in preconditions),
                key=lambda item: (item["kind"], item["subject_ref"], item["evidence_ref"]),
            ),
            "expected_effects": sorted(
                {
                    getattr(item, "value", str(item))
                    for item in expected_effects
                }
            ),
        }
    )


def compute_execution_slice_hash(
    *,
    changeset_hash: str,
    scope_hash: str,
    execution_slice_scope_rule_id: str,
    host_runtime_ref: HostRuntimeRef,
    execution_unit_hashes: Iterable[str],
) -> str:
    return canonical_hash(
        {
            "changeset_hash": changeset_hash,
            "scope_hash": scope_hash,
            "execution_slice_scope_rule_id": execution_slice_scope_rule_id,
            "host_runtime_ref": _runtime_ref_payload(host_runtime_ref),
            "execution_unit_hashes": sorted(set(execution_unit_hashes)),
        }
    )


def _dependency_payload(value: object) -> tuple[str, str, str]:
    if isinstance(value, tuple) and len(value) == 3:
        return (str(value[0]), str(value[1]), str(value[2]))
    return (
        str(value.predecessor_execution_unit_id),
        str(value.successor_execution_unit_id),
        str(value.reason_ref),
    )


def compute_execution_plan_hash(
    *,
    changeset_hash: str,
    scope_hash: str,
    routing_snapshot_hash: str,
    execution_slice_hashes: Iterable[str],
    execution_dependencies: Iterable[object],
) -> str:
    dependencies = sorted({_dependency_payload(item) for item in execution_dependencies})
    return canonical_hash(
        {
            "changeset_hash": changeset_hash,
            "scope_hash": scope_hash,
            "routing_snapshot_hash": routing_snapshot_hash,
            "execution_slice_hashes": sorted(set(execution_slice_hashes)),
            "execution_dependencies": [
                {
                    "predecessor_execution_unit_id": predecessor,
                    "successor_execution_unit_id": successor,
                    "reason_ref": reason_ref,
                }
                for predecessor, successor, reason_ref in dependencies
            ],
        }
    )


__all__ = [
    "compute_execution_plan_hash",
    "compute_execution_slice_hash",
    "compute_execution_unit_hash",
    "compute_routing_snapshot_hash",
]
