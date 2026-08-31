"""Immutable provider-neutral execution-partitioning contracts for Step30."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from design_approval_scope import (
    ApprovalScopeBoundary,
    CanonicalAspect,
    CanonicalExistenceEffect,
)
from design_changeset import CanonicalChangeSet, ChangePrecondition

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ExecutionPlanningError(ValueError):
    """Stable Step30 domain error carrying a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _text(code, "code")


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


def _texts(values, field_name: str, *, required: bool = False) -> tuple[str, ...]:
    normalized = tuple(sorted({_text(value, field_name) for value in values}))
    if required and not normalized:
        raise ValueError(f"{field_name} requires at least one value")
    return normalized


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


def _aspects(values) -> tuple[CanonicalAspect, ...]:
    return tuple(
        sorted(
            {
                value if isinstance(value, CanonicalAspect) else CanonicalAspect(str(value))
                for value in values
            },
            key=lambda item: item.value,
        )
    )


def _existence_effects(values) -> tuple[CanonicalExistenceEffect, ...]:
    return tuple(
        sorted(
            {
                value
                if isinstance(value, CanonicalExistenceEffect)
                else CanonicalExistenceEffect(str(value))
                for value in values
            },
            key=lambda item: item.value,
        )
    )


@dataclass(frozen=True, slots=True)
class HostRuntimeRef:
    host_type: str
    host_instance_id: str
    document_ref: str

    def __post_init__(self) -> None:
        for name in ("host_type", "host_instance_id", "document_ref"):
            object.__setattr__(self, name, _text(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class RuntimeEntityRoute:
    semantic_id: str
    host_runtime_ref: HostRuntimeRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantic_id", _text(self.semantic_id, "semantic_id"))
        if not isinstance(self.host_runtime_ref, HostRuntimeRef):
            raise TypeError("host_runtime_ref must be HostRuntimeRef")


@dataclass(frozen=True, slots=True)
class RuntimeRoutingEvidence:
    routing_snapshot_id: str
    routes: tuple[RuntimeEntityRoute, ...]
    routing_snapshot_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "routing_snapshot_id", _text(self.routing_snapshot_id, "routing_snapshot_id"))
        object.__setattr__(
            self,
            "routes",
            _typed_tuple(self.routes, RuntimeEntityRoute, "routes"),
        )
        object.__setattr__(
            self,
            "routing_snapshot_hash",
            _digest(self.routing_snapshot_hash, "routing_snapshot_hash"),
        )


@dataclass(frozen=True, slots=True)
class ApprovalScopeRef:
    scope_id: str
    scope_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", _text(self.scope_id, "scope_id"))
        object.__setattr__(self, "scope_hash", _digest(self.scope_hash, "scope_hash"))


@dataclass(frozen=True, slots=True)
class ApprovedExecutionScopeRef:
    scope_id: str
    scope_hash: str
    execution_slice_scope_rule_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", _text(self.scope_id, "scope_id"))
        object.__setattr__(self, "scope_hash", _digest(self.scope_hash, "scope_hash"))
        object.__setattr__(
            self,
            "execution_slice_scope_rule_id",
            _text(self.execution_slice_scope_rule_id, "execution_slice_scope_rule_id"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionUnit:
    execution_unit_id: str
    source_operation_id: str
    source_operation_hash: str
    canonical_operation: str
    canonical_operation_version: str
    canonical_definition_fingerprint: str
    targets: tuple[str, ...]
    arguments: Mapping[str, Any]
    preconditions: tuple[ChangePrecondition, ...]
    expected_effects: tuple[CanonicalAspect | str, ...]
    execution_unit_hash: str
    expected_existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_unit_id", _text(self.execution_unit_id, "execution_unit_id"))
        object.__setattr__(self, "source_operation_id", _text(self.source_operation_id, "source_operation_id"))
        object.__setattr__(
            self,
            "source_operation_hash",
            _digest(self.source_operation_hash, "source_operation_hash"),
        )
        object.__setattr__(self, "canonical_operation", _text(self.canonical_operation, "canonical_operation"))
        object.__setattr__(
            self,
            "canonical_operation_version",
            _version(self.canonical_operation_version, "canonical_operation_version"),
        )
        object.__setattr__(
            self,
            "canonical_definition_fingerprint",
            _digest(self.canonical_definition_fingerprint, "canonical_definition_fingerprint"),
        )
        object.__setattr__(self, "targets", _texts(self.targets, "target", required=True))
        object.__setattr__(self, "arguments", _readonly_mapping(self.arguments, "arguments"))
        object.__setattr__(
            self,
            "preconditions",
            _typed_tuple(self.preconditions, ChangePrecondition, "preconditions"),
        )
        expected_effects = _aspects(self.expected_effects)
        expected_existence_effects = _existence_effects(self.expected_existence_effects)
        if not expected_effects and not expected_existence_effects:
            raise ValueError("execution unit requires expected effect authority")
        object.__setattr__(self, "expected_effects", expected_effects)
        object.__setattr__(
            self,
            "expected_existence_effects",
            expected_existence_effects,
        )
        object.__setattr__(
            self,
            "execution_unit_hash",
            _digest(self.execution_unit_hash, "execution_unit_hash"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionSlice:
    execution_slice_id: str
    changeset_id: str
    changeset_hash: str
    host_runtime_ref: HostRuntimeRef
    approved_scope_ref: ApprovedExecutionScopeRef
    execution_units: tuple[ExecutionUnit, ...]
    execution_slice_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_slice_id", _text(self.execution_slice_id, "execution_slice_id"))
        object.__setattr__(self, "changeset_id", _text(self.changeset_id, "changeset_id"))
        object.__setattr__(self, "changeset_hash", _digest(self.changeset_hash, "changeset_hash"))
        if not isinstance(self.host_runtime_ref, HostRuntimeRef):
            raise TypeError("host_runtime_ref must be HostRuntimeRef")
        if not isinstance(self.approved_scope_ref, ApprovedExecutionScopeRef):
            raise TypeError("approved_scope_ref must be ApprovedExecutionScopeRef")
        object.__setattr__(
            self,
            "execution_units",
            _typed_tuple(self.execution_units, ExecutionUnit, "execution_units", required=True),
        )
        object.__setattr__(
            self,
            "execution_slice_hash",
            _digest(self.execution_slice_hash, "execution_slice_hash"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionDependency:
    predecessor_execution_unit_id: str
    successor_execution_unit_id: str
    reason_ref: str

    def __post_init__(self) -> None:
        for name in (
            "predecessor_execution_unit_id",
            "successor_execution_unit_id",
            "reason_ref",
        ):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.predecessor_execution_unit_id == self.successor_execution_unit_id:
            raise ValueError("execution dependency cannot self-reference")


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    execution_plan_id: str
    changeset_id: str
    changeset_hash: str
    approval_scope_ref: ApprovalScopeRef
    routing_snapshot_id: str
    routing_snapshot_hash: str
    execution_slices: tuple[ExecutionSlice, ...]
    execution_dependencies: tuple[ExecutionDependency, ...]
    execution_plan_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "execution_plan_id", _text(self.execution_plan_id, "execution_plan_id"))
        object.__setattr__(self, "changeset_id", _text(self.changeset_id, "changeset_id"))
        object.__setattr__(self, "changeset_hash", _digest(self.changeset_hash, "changeset_hash"))
        if not isinstance(self.approval_scope_ref, ApprovalScopeRef):
            raise TypeError("approval_scope_ref must be ApprovalScopeRef")
        object.__setattr__(self, "routing_snapshot_id", _text(self.routing_snapshot_id, "routing_snapshot_id"))
        object.__setattr__(
            self,
            "routing_snapshot_hash",
            _digest(self.routing_snapshot_hash, "routing_snapshot_hash"),
        )
        object.__setattr__(
            self,
            "execution_slices",
            _typed_tuple(self.execution_slices, ExecutionSlice, "execution_slices", required=True),
        )
        object.__setattr__(
            self,
            "execution_dependencies",
            _typed_tuple(
                self.execution_dependencies,
                ExecutionDependency,
                "execution_dependencies",
            ),
        )
        object.__setattr__(
            self,
            "execution_plan_hash",
            _digest(self.execution_plan_hash, "execution_plan_hash"),
        )


@dataclass(frozen=True, slots=True)
class ExecutionPlanningRequest:
    canonical_changeset: CanonicalChangeSet
    approval_scope_boundary: ApprovalScopeBoundary
    runtime_routing_evidence: RuntimeRoutingEvidence

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_changeset, CanonicalChangeSet):
            raise TypeError("canonical_changeset must be CanonicalChangeSet")
        if not isinstance(self.approval_scope_boundary, ApprovalScopeBoundary):
            raise TypeError("approval_scope_boundary must be ApprovalScopeBoundary")
        if not isinstance(self.runtime_routing_evidence, RuntimeRoutingEvidence):
            raise TypeError("runtime_routing_evidence must be RuntimeRoutingEvidence")
