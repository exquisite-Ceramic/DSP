"""Deterministic Step31 snapshot validation and provider candidate selection."""

from __future__ import annotations

from datetime import datetime

import jsonschema
from design_execution_planning import ExecutionSlice, ExecutionUnit

from .adapters import native_constraints_satisfied
from .contracts import (
    EligibilityState,
    NativeTargetBindingEvidence,
    ProviderBindingError,
    ProviderBindingRequest,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshot,
)
from .hashing import (
    compute_candidate_fingerprint,
    compute_host_binding_fingerprint,
    compute_provider_snapshot_hash,
)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _native_bindings_by_semantic_id(
    execution_slice: ExecutionSlice,
    snapshot: ProviderExecutionSnapshot,
) -> dict[str, NativeTargetBindingEvidence]:
    runtime_ref = execution_slice.host_runtime_ref
    bindings: dict[str, NativeTargetBindingEvidence] = {}

    for row in snapshot.native_target_bindings:
        if (
            row.host_type != runtime_ref.host_type
            or row.document_ref != runtime_ref.document_ref
        ):
            raise ProviderBindingError(
                "PROVIDER_SLICE_MISMATCH",
                "native binding Host/document does not match execution slice",
            )
        if compute_host_binding_fingerprint(row) != row.host_binding_fingerprint:
            raise ProviderBindingError(
                "PROVIDER_NATIVE_BINDING_CONFLICT",
                "native binding fingerprint does not match native identity",
            )
        if row.semantic_id in bindings:
            raise ProviderBindingError(
                "PROVIDER_NATIVE_BINDING_CONFLICT",
                f"duplicate native binding for semantic target {row.semantic_id}",
            )
        bindings[row.semantic_id] = row

    required = {
        target
        for unit in execution_slice.execution_units
        for target in unit.targets
    }
    supplied = set(bindings)
    missing = required - supplied
    if missing:
        raise ProviderBindingError(
            "PROVIDER_NATIVE_BINDING_UNRESOLVED",
            f"native bindings unresolved for {sorted(missing)}",
        )
    extraneous = supplied - required
    if extraneous:
        raise ProviderBindingError(
            "PROVIDER_NATIVE_BINDING_EXTRANEOUS",
            f"extraneous native bindings for {sorted(extraneous)}",
        )
    return bindings


def _validate_candidate_schema(candidate: ProviderExecutionCandidate) -> None:
    schema = dict(candidate.provider_input_schema)
    validator_cls = jsonschema.validators.validator_for(schema)
    try:
        validator_cls.check_schema(schema)
    except jsonschema.SchemaError as exc:
        raise ProviderBindingError(
            "PROVIDER_CANDIDATE_INVALID",
            "provider input schema is invalid",
        ) from exc


def _validate_candidates(
    execution_slice: ExecutionSlice,
    snapshot: ProviderExecutionSnapshot,
) -> tuple[ProviderExecutionCandidate, ...]:
    valid_operations = {
        unit.canonical_operation for unit in execution_slice.execution_units
    }
    candidates = tuple(snapshot.provider_candidates)
    for candidate in candidates:
        if candidate.canonical_operation not in valid_operations:
            raise ProviderBindingError(
                "PROVIDER_CANDIDATE_INVALID",
                "provider candidate operation is unrelated to execution slice",
            )
        _validate_candidate_schema(candidate)
        if compute_candidate_fingerprint(candidate) != candidate.candidate_fingerprint:
            raise ProviderBindingError(
                "PROVIDER_CANDIDATE_INVALID",
                "provider candidate fingerprint mismatch",
            )
    return candidates


def _validate_request_and_snapshot(
    request: ProviderBindingRequest,
) -> tuple[
    dict[str, NativeTargetBindingEvidence],
    tuple[ProviderExecutionCandidate, ...],
]:
    execution_slice = request.execution_slice
    snapshot = request.provider_execution_snapshot

    if (
        snapshot.execution_slice_id != execution_slice.execution_slice_id
        or snapshot.execution_slice_hash != execution_slice.execution_slice_hash
        or snapshot.host_runtime_ref != execution_slice.host_runtime_ref
    ):
        raise ProviderBindingError(
            "PROVIDER_SLICE_MISMATCH",
            "provider execution snapshot does not bind the exact execution slice",
        )

    native_by_semantic_id = _native_bindings_by_semantic_id(execution_slice, snapshot)
    candidates = _validate_candidates(execution_slice, snapshot)

    if compute_provider_snapshot_hash(snapshot) != snapshot.snapshot_hash:
        raise ProviderBindingError(
            "PROVIDER_SNAPSHOT_HASH_MISMATCH",
            "provider execution snapshot hash mismatch",
        )

    if _parse_utc(request.admission_time) >= _parse_utc(snapshot.valid_until):
        raise ProviderBindingError(
            "PROVIDER_SNAPSHOT_EXPIRED",
            "provider execution snapshot is expired",
        )

    return native_by_semantic_id, candidates


def _candidate_is_eligible(
    candidate: ProviderExecutionCandidate,
    unit: ExecutionUnit,
    unit_native_targets: tuple[NativeTargetBindingEvidence, ...],
) -> bool:
    return (
        candidate.canonical_operation == unit.canonical_operation
        and unit.canonical_operation_version
        in candidate.compatible_operation_versions
        and native_constraints_satisfied(
            candidate.provider_native_constraints,
            unit_native_targets,
        )
        and candidate.trust_state is EligibilityState.SATISFIED
        and candidate.compatibility_state is EligibilityState.SATISFIED
        and candidate.health_state is EligibilityState.SATISFIED
        and candidate.license_state is EligibilityState.SATISFIED
        and candidate.certification_state is EligibilityState.SATISFIED
    )


def _candidate_rank(
    candidate: ProviderExecutionCandidate,
) -> tuple[int, str, str, str]:
    return (
        candidate.policy_priority,
        candidate.provider_server,
        candidate.provider_tool,
        candidate.provider_version,
    )


def _select_candidate(
    unit: ExecutionUnit,
    unit_native_targets: tuple[NativeTargetBindingEvidence, ...],
    candidates: tuple[ProviderExecutionCandidate, ...],
) -> ProviderExecutionCandidate:
    eligible = tuple(
        candidate
        for candidate in candidates
        if _candidate_is_eligible(candidate, unit, unit_native_targets)
    )
    if not eligible:
        raise ProviderBindingError(
            "PROVIDER_CANDIDATE_UNAVAILABLE",
            f"no eligible provider candidate for {unit.execution_unit_id}",
        )

    ranked = tuple(sorted(eligible, key=_candidate_rank))
    winning_rank = _candidate_rank(ranked[0])
    winners = tuple(
        candidate for candidate in ranked if _candidate_rank(candidate) == winning_rank
    )
    if len(winners) != 1:
        raise ProviderBindingError(
            "PROVIDER_CANDIDATE_AMBIGUOUS",
            f"ambiguous provider candidate rank for {unit.execution_unit_id}",
        )
    return winners[0]


__all__ = [
    "_candidate_is_eligible",
    "_candidate_rank",
    "_native_bindings_by_semantic_id",
    "_select_candidate",
    "_validate_candidates",
    "_validate_request_and_snapshot",
]
