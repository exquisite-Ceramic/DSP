"""Immutable provider/native binding contracts for Phase G Step31."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from types import MappingProxyType
from typing import Any

from design_execution_planning import ExecutionSlice, ExecutionUnit, HostRuntimeRef

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ProviderBindingError(ValueError):
    """Stable Step31 domain error carrying a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _text(code, "code")


class EligibilityState(str, Enum):
    SATISFIED = "SATISFIED"
    UNSATISFIED = "UNSATISFIED"
    UNKNOWN = "UNKNOWN"


class NativeConstraintOperator(str, Enum):
    EQ = "EQ"
    IN = "IN"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _digest(value: object, field_name: str) -> str:
    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must be lowercase SHA-256 hex")
    return normalized


def _version(value: object, field_name: str) -> str:
    normalized = _text(value, field_name)
    if _VERSION_RE.fullmatch(normalized) is None:
        raise ValueError(f"{field_name} must use MAJOR.MINOR.PATCH")
    return normalized


def _enum(value: object, enum_type: type[Enum], field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


def _readonly_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return MappingProxyType(deepcopy(dict(value)))


def _typed_tuple(values, typ: type, field_name: str, *, required: bool = False):
    normalized = tuple(values)
    if any(not isinstance(value, typ) for value in normalized):
        raise TypeError(f"{field_name} contains invalid values")
    if required and not normalized:
        raise ValueError(f"{field_name} requires at least one value")
    return normalized


def _texts(values, field_name: str, *, required: bool = False) -> tuple[str, ...]:
    normalized = tuple(sorted({_text(value, field_name) for value in values}))
    if required and not normalized:
        raise ValueError(f"{field_name} requires at least one value")
    return normalized


def _utc_timestamp(value: object, field_name: str) -> str:
    normalized = _text(value, field_name)
    raw = f"{normalized[:-1]}+00:00" if normalized.endswith("Z") else normalized
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an RFC3339 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timedelta(0):
        raise ValueError(f"{field_name} must be UTC")
    canonical = parsed.isoformat()
    if canonical.endswith("+00:00"):
        canonical = f"{canonical[:-6]}Z"
    return canonical


@dataclass(frozen=True, slots=True)
class NativeConstraint:
    field: str
    operator: NativeConstraintOperator | str
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        field = _text(self.field, "field")
        if field != "native_kind":
            raise ValueError("Step31 v1 only supports native_kind constraints")
        operator = _enum(self.operator, NativeConstraintOperator, "operator")
        values = _texts(self.values, "constraint value", required=True)
        if operator is NativeConstraintOperator.EQ and len(values) != 1:
            raise ValueError("EQ requires exactly one value")
        object.__setattr__(self, "field", field)
        object.__setattr__(self, "operator", operator)
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class NativeTargetBindingEvidence:
    semantic_id: str
    host_type: str
    document_ref: str
    native_id: str
    native_kind: str
    host_binding_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("semantic_id", "host_type", "document_ref", "native_id", "native_kind"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(
            self,
            "host_binding_fingerprint",
            _digest(self.host_binding_fingerprint, "host_binding_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class ProviderExecutionCandidate:
    provider_server: str
    provider_tool: str
    provider_version: str
    canonical_operation: str
    compatible_operation_versions: tuple[str, ...]
    input_adapter_version: str
    provider_native_constraints: tuple[NativeConstraint, ...]
    provider_input_schema: Mapping[str, Any]
    verification_contract: Mapping[str, Any]
    rollback_contract: Mapping[str, Any]
    trust_state: EligibilityState | str
    compatibility_state: EligibilityState | str
    health_state: EligibilityState | str
    license_state: EligibilityState | str
    certification_state: EligibilityState | str
    policy_priority: int
    candidate_fingerprint: str

    def __post_init__(self) -> None:
        for name in ("provider_server", "provider_tool", "canonical_operation"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "provider_version", _version(self.provider_version, "provider_version"))
        object.__setattr__(
            self,
            "compatible_operation_versions",
            tuple(
                sorted(
                    {
                        _version(value, "compatible_operation_version")
                        for value in self.compatible_operation_versions
                    }
                )
            ),
        )
        if not self.compatible_operation_versions:
            raise ValueError("compatible_operation_versions requires at least one value")
        object.__setattr__(
            self,
            "input_adapter_version",
            _version(self.input_adapter_version, "input_adapter_version"),
        )
        object.__setattr__(
            self,
            "provider_native_constraints",
            _typed_tuple(
                self.provider_native_constraints,
                NativeConstraint,
                "provider_native_constraints",
            ),
        )
        for name in ("provider_input_schema", "verification_contract", "rollback_contract"):
            object.__setattr__(self, name, _readonly_mapping(getattr(self, name), name))
        for name in (
            "trust_state",
            "compatibility_state",
            "health_state",
            "license_state",
            "certification_state",
        ):
            object.__setattr__(
                self,
                name,
                _enum(getattr(self, name), EligibilityState, name),
            )
        if isinstance(self.policy_priority, bool) or not isinstance(self.policy_priority, int):
            raise TypeError("policy_priority must be an integer")
        if self.policy_priority < 0:
            raise ValueError("policy_priority must be >= 0")
        object.__setattr__(
            self,
            "candidate_fingerprint",
            _digest(self.candidate_fingerprint, "candidate_fingerprint"),
        )


@dataclass(frozen=True, slots=True)
class ProviderExecutionSnapshot:
    snapshot_id: str
    execution_slice_id: str
    execution_slice_hash: str
    host_runtime_ref: HostRuntimeRef
    native_target_bindings: tuple[NativeTargetBindingEvidence, ...]
    provider_candidates: tuple[ProviderExecutionCandidate, ...]
    valid_until: str
    snapshot_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "snapshot_id", _text(self.snapshot_id, "snapshot_id"))
        object.__setattr__(
            self,
            "execution_slice_id",
            _text(self.execution_slice_id, "execution_slice_id"),
        )
        object.__setattr__(
            self,
            "execution_slice_hash",
            _digest(self.execution_slice_hash, "execution_slice_hash"),
        )
        if not isinstance(self.host_runtime_ref, HostRuntimeRef):
            raise TypeError("host_runtime_ref must be HostRuntimeRef")
        object.__setattr__(
            self,
            "native_target_bindings",
            _typed_tuple(
                self.native_target_bindings,
                NativeTargetBindingEvidence,
                "native_target_bindings",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "provider_candidates",
            _typed_tuple(
                self.provider_candidates,
                ProviderExecutionCandidate,
                "provider_candidates",
                required=True,
            ),
        )
        object.__setattr__(self, "valid_until", _utc_timestamp(self.valid_until, "valid_until"))
        object.__setattr__(self, "snapshot_hash", _digest(self.snapshot_hash, "snapshot_hash"))


@dataclass(frozen=True, slots=True)
class ProviderPreconditionBinding:
    source_precondition_fingerprint: str
    provider_precondition: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "source_precondition_fingerprint",
            _digest(self.source_precondition_fingerprint, "source_precondition_fingerprint"),
        )
        object.__setattr__(
            self,
            "provider_precondition",
            _readonly_mapping(self.provider_precondition, "provider_precondition"),
        )


@dataclass(frozen=True, slots=True)
class ProviderBindingMaterial:
    native_targets: tuple[NativeTargetBindingEvidence, ...]
    provider_arguments: Mapping[str, Any]
    provider_preconditions: tuple[ProviderPreconditionBinding, ...]
    native_binding_metadata: Mapping[str, Any]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "native_targets",
            _typed_tuple(
                self.native_targets,
                NativeTargetBindingEvidence,
                "native_targets",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "provider_arguments",
            _readonly_mapping(self.provider_arguments, "provider_arguments"),
        )
        object.__setattr__(
            self,
            "provider_preconditions",
            _typed_tuple(
                self.provider_preconditions,
                ProviderPreconditionBinding,
                "provider_preconditions",
            ),
        )
        object.__setattr__(
            self,
            "native_binding_metadata",
            _readonly_mapping(self.native_binding_metadata, "native_binding_metadata"),
        )


@dataclass(frozen=True, slots=True)
class ProviderBinding:
    binding_id: str
    execution_unit_id: str
    execution_unit_hash: str
    execution_slice_id: str
    execution_slice_hash: str
    canonical_operation: str
    provider_server: str
    provider_tool: str
    provider_version: str
    selected_candidate_fingerprint: str
    host_instance_id: str
    document_ref: str
    input_adapter_version: str
    native_targets: tuple[NativeTargetBindingEvidence, ...]
    provider_arguments: Mapping[str, Any]
    provider_preconditions: tuple[ProviderPreconditionBinding, ...]
    native_binding_metadata: Mapping[str, Any]
    verification_contract: Mapping[str, Any]
    rollback_contract: Mapping[str, Any]
    binding_expires_at: str
    binding_hash: str

    def __post_init__(self) -> None:
        for name in (
            "binding_id",
            "execution_unit_id",
            "execution_slice_id",
            "canonical_operation",
            "provider_server",
            "provider_tool",
            "host_instance_id",
            "document_ref",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "execution_unit_hash",
            "execution_slice_hash",
            "selected_candidate_fingerprint",
            "binding_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(self, "provider_version", _version(self.provider_version, "provider_version"))
        object.__setattr__(
            self,
            "input_adapter_version",
            _version(self.input_adapter_version, "input_adapter_version"),
        )
        object.__setattr__(
            self,
            "native_targets",
            _typed_tuple(
                self.native_targets,
                NativeTargetBindingEvidence,
                "native_targets",
                required=True,
            ),
        )
        object.__setattr__(
            self,
            "provider_arguments",
            _readonly_mapping(self.provider_arguments, "provider_arguments"),
        )
        object.__setattr__(
            self,
            "provider_preconditions",
            _typed_tuple(
                self.provider_preconditions,
                ProviderPreconditionBinding,
                "provider_preconditions",
            ),
        )
        for name in (
            "native_binding_metadata",
            "verification_contract",
            "rollback_contract",
        ):
            object.__setattr__(self, name, _readonly_mapping(getattr(self, name), name))
        object.__setattr__(
            self,
            "binding_expires_at",
            _utc_timestamp(self.binding_expires_at, "binding_expires_at"),
        )


@dataclass(frozen=True, slots=True)
class ProviderBindingSet:
    binding_set_id: str
    execution_slice_id: str
    execution_slice_hash: str
    provider_execution_snapshot_id: str
    provider_execution_snapshot_hash: str
    bindings: tuple[ProviderBinding, ...]
    binding_set_hash: str

    def __post_init__(self) -> None:
        for name in (
            "binding_set_id",
            "execution_slice_id",
            "provider_execution_snapshot_id",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        for name in (
            "execution_slice_hash",
            "provider_execution_snapshot_hash",
            "binding_set_hash",
        ):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        object.__setattr__(
            self,
            "bindings",
            _typed_tuple(self.bindings, ProviderBinding, "bindings", required=True),
        )


@dataclass(frozen=True, slots=True)
class ProviderBindingRequest:
    execution_slice: ExecutionSlice
    provider_execution_snapshot: ProviderExecutionSnapshot
    admission_time: str

    def __post_init__(self) -> None:
        if not isinstance(self.execution_slice, ExecutionSlice):
            raise TypeError("execution_slice must be ExecutionSlice")
        if not isinstance(self.provider_execution_snapshot, ProviderExecutionSnapshot):
            raise TypeError("provider_execution_snapshot must be ProviderExecutionSnapshot")
        object.__setattr__(
            self,
            "admission_time",
            _utc_timestamp(self.admission_time, "admission_time"),
        )


__all__ = [
    "EligibilityState",
    "NativeConstraint",
    "NativeConstraintOperator",
    "NativeTargetBindingEvidence",
    "ProviderBinding",
    "ProviderBindingError",
    "ProviderBindingMaterial",
    "ProviderBindingRequest",
    "ProviderBindingSet",
    "ProviderExecutionCandidate",
    "ProviderExecutionSnapshot",
    "ProviderPreconditionBinding",
]
