"""Deterministic semantic hashing for Step31 provider binding."""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from enum import Enum
from typing import Any

from design_changeset import ChangePrecondition, canonical_hash

from .contracts import (
    NativeConstraint,
    NativeTargetBindingEvidence,
    ProviderBinding,
    ProviderBindingError,
    ProviderBindingSet,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshot,
    ProviderPreconditionBinding,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


def _full_digest(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _DIGEST_RE.fullmatch(value) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return value


def _state_value(value: object) -> str:
    return value.value if isinstance(value, Enum) else str(value)


def _constraint_payload(constraint: NativeConstraint) -> dict[str, object]:
    return {
        "field": constraint.field,
        "operator": constraint.operator.value,
        "values": list(constraint.values),
    }


def _candidate_semantic_payload(candidate: ProviderExecutionCandidate) -> dict[str, object]:
    constraints = sorted(
        (_constraint_payload(item) for item in candidate.provider_native_constraints),
        key=lambda item: canonical_hash(item),
    )
    return {
        "provider_server": candidate.provider_server,
        "provider_tool": candidate.provider_tool,
        "provider_version": candidate.provider_version,
        "canonical_operation": candidate.canonical_operation,
        "compatible_operation_versions": sorted(candidate.compatible_operation_versions),
        "input_adapter_version": candidate.input_adapter_version,
        "provider_native_constraints": constraints,
        "provider_input_schema": candidate.provider_input_schema,
        "verification_contract": candidate.verification_contract,
        "rollback_contract": candidate.rollback_contract,
        "trust_state": _state_value(candidate.trust_state),
        "compatibility_state": _state_value(candidate.compatibility_state),
        "health_state": _state_value(candidate.health_state),
        "license_state": _state_value(candidate.license_state),
        "certification_state": _state_value(candidate.certification_state),
        "policy_priority": candidate.policy_priority,
    }


def _candidate_snapshot_payload(candidate: ProviderExecutionCandidate) -> dict[str, object]:
    return {
        **_candidate_semantic_payload(candidate),
        "candidate_fingerprint": candidate.candidate_fingerprint,
    }


def _native_target_payload(value: NativeTargetBindingEvidence) -> dict[str, str]:
    return {
        "semantic_id": value.semantic_id,
        "host_type": value.host_type,
        "document_ref": value.document_ref,
        "native_id": value.native_id,
        "native_kind": value.native_kind,
        "host_binding_fingerprint": value.host_binding_fingerprint,
    }


def _native_target_sort_key(value: dict[str, str]) -> tuple[str, str, str, str, str, str]:
    return (
        value["semantic_id"],
        value["host_type"],
        value["document_ref"],
        value["native_id"],
        value["native_kind"],
        value["host_binding_fingerprint"],
    )


def _provider_precondition_payload(value: ProviderPreconditionBinding) -> dict[str, object]:
    return {
        "source_precondition_fingerprint": value.source_precondition_fingerprint,
        "provider_precondition": value.provider_precondition,
    }


def compute_host_binding_fingerprint(value: NativeTargetBindingEvidence) -> str:
    return canonical_hash(
        {
            "semantic_id": value.semantic_id,
            "host_type": value.host_type,
            "document_ref": value.document_ref,
            "native_id": value.native_id,
            "native_kind": value.native_kind,
        }
    )


def compute_candidate_fingerprint(candidate: ProviderExecutionCandidate) -> str:
    return canonical_hash(_candidate_semantic_payload(candidate))


def compute_provider_snapshot_hash(snapshot: ProviderExecutionSnapshot) -> str:
    native_payloads = sorted(
        (_native_target_payload(item) for item in snapshot.native_target_bindings),
        key=_native_target_sort_key,
    )
    candidate_payloads = sorted(
        (_candidate_snapshot_payload(item) for item in snapshot.provider_candidates),
        key=lambda item: canonical_hash(item),
    )
    return canonical_hash(
        {
            "execution_slice_hash": snapshot.execution_slice_hash,
            "host_runtime_ref": {
                "host_type": snapshot.host_runtime_ref.host_type,
                "host_instance_id": snapshot.host_runtime_ref.host_instance_id,
                "document_ref": snapshot.host_runtime_ref.document_ref,
            },
            "native_target_bindings": native_payloads,
            "provider_candidates": candidate_payloads,
            "valid_until": snapshot.valid_until,
        }
    )


def compute_precondition_fingerprint(precondition: ChangePrecondition) -> str:
    return canonical_hash(
        {
            "kind": precondition.kind.value,
            "subject_ref": precondition.subject_ref,
            "evidence_ref": precondition.evidence_ref,
        }
    )


def compute_binding_hash(
    *,
    execution_unit_hash: str,
    execution_slice_hash: str,
    canonical_operation: str,
    provider_server: str,
    provider_tool: str,
    provider_version: str,
    selected_candidate_fingerprint: str,
    host_instance_id: str,
    document_ref: str,
    input_adapter_version: str,
    native_targets: Iterable[NativeTargetBindingEvidence],
    provider_arguments: Mapping[str, Any],
    provider_preconditions: Iterable[ProviderPreconditionBinding],
    native_binding_metadata: Mapping[str, Any],
    verification_contract: Mapping[str, Any],
    rollback_contract: Mapping[str, Any],
    binding_expires_at: str,
) -> str:
    _full_digest(execution_unit_hash, "execution_unit_hash")
    _full_digest(execution_slice_hash, "execution_slice_hash")
    _full_digest(selected_candidate_fingerprint, "selected_candidate_fingerprint")
    return canonical_hash(
        {
            "execution_unit_hash": execution_unit_hash,
            "execution_slice_hash": execution_slice_hash,
            "canonical_operation": canonical_operation,
            "provider_server": provider_server,
            "provider_tool": provider_tool,
            "provider_version": provider_version,
            "selected_candidate_fingerprint": selected_candidate_fingerprint,
            "host_instance_id": host_instance_id,
            "document_ref": document_ref,
            "input_adapter_version": input_adapter_version,
            "native_targets": sorted(
                (_native_target_payload(item) for item in native_targets),
                key=_native_target_sort_key,
            ),
            "provider_arguments": provider_arguments,
            "provider_preconditions": sorted(
                (_provider_precondition_payload(item) for item in provider_preconditions),
                key=lambda item: (
                    item["source_precondition_fingerprint"],
                    canonical_hash(item["provider_precondition"]),
                ),
            ),
            "native_binding_metadata": native_binding_metadata,
            "verification_contract": verification_contract,
            "rollback_contract": rollback_contract,
            "binding_expires_at": binding_expires_at,
        }
    )


def compute_binding_set_hash(
    *,
    execution_slice_hash: str,
    binding_hashes: Iterable[str],
) -> str:
    slice_hash = _full_digest(execution_slice_hash, "execution_slice_hash")
    hashes = tuple(_full_digest(value, "binding_hash") for value in binding_hashes)
    return canonical_hash(
        {
            "execution_slice_hash": slice_hash,
            "binding_hashes": sorted(hashes),
        }
    )


def validate_provider_binding(binding: ProviderBinding) -> None:
    expected = compute_binding_hash(
        execution_unit_hash=binding.execution_unit_hash,
        execution_slice_hash=binding.execution_slice_hash,
        canonical_operation=binding.canonical_operation,
        provider_server=binding.provider_server,
        provider_tool=binding.provider_tool,
        provider_version=binding.provider_version,
        selected_candidate_fingerprint=binding.selected_candidate_fingerprint,
        host_instance_id=binding.host_instance_id,
        document_ref=binding.document_ref,
        input_adapter_version=binding.input_adapter_version,
        native_targets=binding.native_targets,
        provider_arguments=binding.provider_arguments,
        provider_preconditions=binding.provider_preconditions,
        native_binding_metadata=binding.native_binding_metadata,
        verification_contract=binding.verification_contract,
        rollback_contract=binding.rollback_contract,
        binding_expires_at=binding.binding_expires_at,
    )
    if binding.binding_hash != expected or binding.binding_id != f"PB-{expected[:12]}":
        raise ProviderBindingError(
            "PROVIDER_BINDING_HASH_MISMATCH",
            "provider binding hash/id mismatch",
        )


def validate_provider_binding_set_hash(binding_set: ProviderBindingSet) -> None:
    expected = compute_binding_set_hash(
        execution_slice_hash=binding_set.execution_slice_hash,
        binding_hashes=(binding.binding_hash for binding in binding_set.bindings),
    )
    if (
        binding_set.binding_set_hash != expected
        or binding_set.binding_set_id != f"PBS-{expected[:12]}"
    ):
        raise ProviderBindingError(
            "PROVIDER_BINDING_SET_INVALID",
            "provider binding set hash/id mismatch",
        )


__all__ = [
    "compute_binding_hash",
    "compute_binding_set_hash",
    "compute_candidate_fingerprint",
    "compute_host_binding_fingerprint",
    "compute_precondition_fingerprint",
    "compute_provider_snapshot_hash",
    "validate_provider_binding",
    "validate_provider_binding_set_hash",
]
