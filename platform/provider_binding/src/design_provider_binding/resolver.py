"""Deterministic Step31 snapshot validation, provider selection, and binding."""

from __future__ import annotations

from datetime import datetime

import jsonschema
from design_execution_planning import ExecutionSlice, ExecutionUnit

from .adapters import ProviderBindingAdapterRegistry, native_constraints_satisfied
from .contracts import (
    EligibilityState,
    NativeTargetBindingEvidence,
    ProviderBinding,
    ProviderBindingError,
    ProviderBindingMaterial,
    ProviderBindingRequest,
    ProviderBindingSet,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshot,
)
from .hashing import (
    compute_binding_hash,
    compute_binding_set_hash,
    compute_candidate_fingerprint,
    compute_host_binding_fingerprint,
    compute_precondition_fingerprint,
    compute_provider_snapshot_hash,
    validate_provider_binding,
    validate_provider_binding_set,
)


def _parse_utc(value: str) -> datetime:
    return datetime.fromisoformat(value)


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


def _validate_material_native_targets(
    unit: ExecutionUnit,
    material: ProviderBindingMaterial,
    native_by_semantic_id: dict[str, NativeTargetBindingEvidence],
) -> None:
    returned = tuple(material.native_targets)
    returned_ids = tuple(item.semantic_id for item in returned)
    if (
        len(returned) != len(unit.targets)
        or len(set(returned_ids)) != len(returned_ids)
        or set(returned_ids) != set(unit.targets)
        or any(item != native_by_semantic_id.get(item.semantic_id) for item in returned)
    ):
        raise ProviderBindingError(
            "PROVIDER_NATIVE_TARGET_MISMATCH",
            "adapter native targets do not match frozen native evidence",
        )


def _validate_material_preconditions(
    unit: ExecutionUnit,
    material: ProviderBindingMaterial,
) -> None:
    source_fingerprints = {
        compute_precondition_fingerprint(item) for item in unit.preconditions
    }
    seen: set[str] = set()
    for item in material.provider_preconditions:
        if (
            item.source_precondition_fingerprint not in source_fingerprints
            or item.source_precondition_fingerprint in seen
        ):
            raise ProviderBindingError(
                "PROVIDER_BINDING_ADAPTATION_FAILED",
                "provider precondition source reference is invalid",
            )
        seen.add(item.source_precondition_fingerprint)


def _validate_provider_arguments(
    selected: ProviderExecutionCandidate,
    material: ProviderBindingMaterial,
) -> None:
    schema = dict(selected.provider_input_schema)
    validator_cls = jsonschema.validators.validator_for(schema)
    validator = validator_cls(schema)
    try:
        validator.validate(dict(material.provider_arguments))
    except jsonschema.ValidationError as exc:
        raise ProviderBindingError(
            "PROVIDER_INPUT_SCHEMA_INVALID",
            "provider arguments do not satisfy provider input schema",
        ) from exc


def _materialize_binding(
    *,
    execution_slice: ExecutionSlice,
    snapshot: ProviderExecutionSnapshot,
    unit: ExecutionUnit,
    selected: ProviderExecutionCandidate,
    material: ProviderBindingMaterial,
) -> ProviderBinding:
    binding_hash = compute_binding_hash(
        execution_unit_hash=unit.execution_unit_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        canonical_operation=unit.canonical_operation,
        provider_server=selected.provider_server,
        provider_tool=selected.provider_tool,
        provider_version=selected.provider_version,
        selected_candidate_fingerprint=selected.candidate_fingerprint,
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        input_adapter_version=selected.input_adapter_version,
        native_targets=material.native_targets,
        provider_arguments=material.provider_arguments,
        provider_preconditions=material.provider_preconditions,
        native_binding_metadata=material.native_binding_metadata,
        verification_contract=selected.verification_contract,
        rollback_contract=selected.rollback_contract,
        binding_expires_at=snapshot.valid_until,
    )
    binding = ProviderBinding(
        f"PB-{binding_hash[:12]}",
        unit.execution_unit_id,
        unit.execution_unit_hash,
        execution_slice.execution_slice_id,
        execution_slice.execution_slice_hash,
        unit.canonical_operation,
        selected.provider_server,
        selected.provider_tool,
        selected.provider_version,
        selected.candidate_fingerprint,
        execution_slice.host_runtime_ref.host_instance_id,
        execution_slice.host_runtime_ref.document_ref,
        selected.input_adapter_version,
        material.native_targets,
        material.provider_arguments,
        material.provider_preconditions,
        material.native_binding_metadata,
        selected.verification_contract,
        selected.rollback_contract,
        snapshot.valid_until,
        binding_hash,
    )
    validate_provider_binding(binding)
    return binding


class ProviderResolver:
    """Pure deterministic late binder for one Step30 ExecutionSlice."""

    def __init__(self, adapter_registry: ProviderBindingAdapterRegistry) -> None:
        if not isinstance(adapter_registry, ProviderBindingAdapterRegistry):
            raise TypeError("adapter_registry must be ProviderBindingAdapterRegistry")
        self._adapter_registry = adapter_registry

    def resolve(self, request: ProviderBindingRequest) -> ProviderBindingSet:
        if not isinstance(request, ProviderBindingRequest):
            raise TypeError("request must be ProviderBindingRequest")

        execution_slice = request.execution_slice
        snapshot = request.provider_execution_snapshot
        native_by_semantic_id, candidates = _validate_request_and_snapshot(request)
        bindings: list[ProviderBinding] = []

        for unit in sorted(
            execution_slice.execution_units,
            key=lambda item: item.execution_unit_hash,
        ):
            unit_native_targets = tuple(
                native_by_semantic_id[target] for target in unit.targets
            )
            selected = _select_candidate(unit, unit_native_targets, candidates)
            adapter = self._adapter_registry.require(
                selected.provider_server,
                selected.input_adapter_version,
            )
            try:
                material = adapter.bind(
                    unit,
                    execution_slice.host_runtime_ref,
                    selected,
                    unit_native_targets,
                )
            except Exception as exc:
                raise ProviderBindingError(
                    "PROVIDER_BINDING_ADAPTATION_FAILED",
                    "selected provider adapter failed",
                ) from exc

            if not isinstance(material, ProviderBindingMaterial):
                raise ProviderBindingError(
                    "PROVIDER_BINDING_ADAPTATION_FAILED",
                    "selected provider adapter returned invalid binding material",
                )

            _validate_material_native_targets(unit, material, native_by_semantic_id)
            _validate_material_preconditions(unit, material)
            _validate_provider_arguments(selected, material)
            bindings.append(
                _materialize_binding(
                    execution_slice=execution_slice,
                    snapshot=snapshot,
                    unit=unit,
                    selected=selected,
                    material=material,
                )
            )

        normalized_bindings = tuple(
            sorted(bindings, key=lambda item: item.execution_unit_hash)
        )
        binding_set_hash = compute_binding_set_hash(
            execution_slice_hash=execution_slice.execution_slice_hash,
            binding_hashes=(item.binding_hash for item in normalized_bindings),
        )
        binding_set = ProviderBindingSet(
            f"PBS-{binding_set_hash[:12]}",
            execution_slice.execution_slice_id,
            execution_slice.execution_slice_hash,
            snapshot.snapshot_id,
            snapshot.snapshot_hash,
            normalized_bindings,
            binding_set_hash,
        )
        validate_provider_binding_set(binding_set, execution_slice)
        return binding_set


__all__ = [
    "ProviderResolver",
    "_candidate_is_eligible",
    "_candidate_rank",
    "_native_bindings_by_semantic_id",
    "_select_candidate",
    "_validate_candidates",
    "_validate_request_and_snapshot",
]
