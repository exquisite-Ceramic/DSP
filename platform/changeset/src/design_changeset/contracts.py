"""Provider-neutral immutable value contracts for Phase G Step29."""

from __future__ import annotations

import re
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

from design_approval_scope import (
    CanonicalAspect,
    CanonicalCreationContract,
    CanonicalExistenceEffect,
)

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


class ChangeSetError(ValueError):
    """Stable Step29 domain error carrying a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _text(code, "code")


class OperationOrigin(str, Enum):
    ROOT = "ROOT"
    DERIVED = "DERIVED"


class OperationSourceKind(str, Enum):
    ROOT_BOUND_OPERATION = "ROOT_BOUND_OPERATION"
    DERIVED_PROPAGATION = "DERIVED_PROPAGATION"


class PreconditionKind(str, Enum):
    OPERATION_FRESHNESS = "OPERATION_FRESHNESS"
    COVERAGE = "COVERAGE"
    ASSURANCE = "ASSURANCE"


class ValidationTaskKind(str, Enum):
    CANONICAL_OPERATION = "CANONICAL_OPERATION"
    DEPENDENCY_VERIFICATION = "DEPENDENCY_VERIFICATION"


def _text(value: object, field_name: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _optional_text(value: str | None, field_name: str) -> str | None:
    return None if value is None else _text(value, field_name)


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


def _texts(values, field_name: str, *, required: bool = False) -> tuple[str, ...]:
    normalized = tuple(sorted({_text(value, field_name) for value in values}))
    if required and not normalized:
        raise ValueError(f"{field_name} requires at least one value")
    return normalized


def _aspects(values, *, required: bool = False) -> tuple[CanonicalAspect, ...]:
    result = tuple(
        sorted(
            {
                value if isinstance(value, CanonicalAspect) else CanonicalAspect(str(value))
                for value in values
            },
            key=lambda item: item.value,
        )
    )
    if required and not result:
        raise ValueError("effects requires at least one canonical aspect")
    return result


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


def _readonly_mapping(value: Mapping[str, Any], field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return MappingProxyType(deepcopy(dict(value)))


def _require_type(value: object, typ: type, field_name: str) -> None:
    if not isinstance(value, typ):
        raise TypeError(f"{field_name} must be {typ.__name__}")


@dataclass(frozen=True, slots=True)
class CanonicalOperationContractEvidence:
    canonical_operation: str
    canonical_operation_version: str
    argument_schema: Mapping[str, Any]
    effects: tuple[CanonicalAspect | str, ...]
    verification_contract: Mapping[str, Any]
    definition_fingerprint: str
    existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()
    creation_contract: CanonicalCreationContract | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_operation", _text(self.canonical_operation, "canonical_operation"))
        object.__setattr__(self, "canonical_operation_version", _version(self.canonical_operation_version, "canonical_operation_version"))
        object.__setattr__(self, "argument_schema", _readonly_mapping(self.argument_schema, "argument_schema"))
        effects = _aspects(self.effects)
        existence_effects = _existence_effects(self.existence_effects)
        if not effects and not existence_effects:
            raise ValueError("canonical operation contract requires effect authority")
        creation_contract = self.creation_contract
        if creation_contract is not None:
            _require_type(creation_contract, CanonicalCreationContract, "creation_contract")
        if CanonicalExistenceEffect.CREATE in existence_effects:
            if creation_contract is None:
                raise ValueError("CREATE existence authority requires creation_contract")
        elif creation_contract is not None:
            raise ValueError("creation_contract requires CREATE existence authority")
        object.__setattr__(self, "effects", effects)
        object.__setattr__(self, "existence_effects", existence_effects)
        object.__setattr__(self, "creation_contract", creation_contract)
        object.__setattr__(self, "verification_contract", _readonly_mapping(self.verification_contract, "verification_contract"))
        object.__setattr__(self, "definition_fingerprint", _digest(self.definition_fingerprint, "definition_fingerprint"))


@dataclass(frozen=True, slots=True)
class BoundOperationEvidence:
    canonical_operation: str
    canonical_operation_version: str
    arguments: Mapping[str, Any]
    context_snapshot_id: str
    context_snapshot_hash: str
    document_ref: str
    semantic_environment_id: str
    planning_requirements: Mapping[str, Any]
    binding_evidence: Mapping[str, Any]
    bound_operation_fingerprint: str
    bound_operation_evidence_fingerprint: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_operation", _text(self.canonical_operation, "canonical_operation"))
        object.__setattr__(self, "canonical_operation_version", _version(self.canonical_operation_version, "canonical_operation_version"))
        for name in ("context_snapshot_id", "context_snapshot_hash", "document_ref", "semantic_environment_id"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        object.__setattr__(self, "arguments", _readonly_mapping(self.arguments, "arguments"))
        object.__setattr__(self, "planning_requirements", _readonly_mapping(self.planning_requirements, "planning_requirements"))
        object.__setattr__(self, "binding_evidence", _readonly_mapping(self.binding_evidence, "binding_evidence"))
        object.__setattr__(self, "bound_operation_fingerprint", _digest(self.bound_operation_fingerprint, "bound_operation_fingerprint"))
        object.__setattr__(self, "bound_operation_evidence_fingerprint", _digest(self.bound_operation_evidence_fingerprint, "bound_operation_evidence_fingerprint"))


@dataclass(frozen=True, slots=True)
class ApprovalScopeDefinitionRef:
    scope_definition_id: str
    scope_body_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_definition_id", _text(self.scope_definition_id, "scope_definition_id"))
        object.__setattr__(self, "scope_body_hash", _digest(self.scope_body_hash, "scope_body_hash"))


@dataclass(frozen=True, slots=True)
class OperationSourceEvidence:
    source_kind: OperationSourceKind
    source_fingerprint: str
    propagation_bundle_id: str | None = None
    proposed_change_hash: str | None = None

    def __post_init__(self) -> None:
        source_kind = _enum(self.source_kind, OperationSourceKind, "source_kind")
        object.__setattr__(self, "source_kind", source_kind)
        object.__setattr__(self, "source_fingerprint", _digest(self.source_fingerprint, "source_fingerprint"))
        object.__setattr__(self, "propagation_bundle_id", _optional_text(self.propagation_bundle_id, "propagation_bundle_id"))
        if self.proposed_change_hash is not None:
            object.__setattr__(self, "proposed_change_hash", _digest(self.proposed_change_hash, "proposed_change_hash"))
        if source_kind is OperationSourceKind.ROOT_BOUND_OPERATION:
            if self.propagation_bundle_id is not None or self.proposed_change_hash is not None:
                raise ValueError("root source evidence cannot reference propagation evidence")
        elif self.propagation_bundle_id is None or self.proposed_change_hash is None:
            raise ValueError("derived source evidence requires bundle and proposed-change refs")


@dataclass(frozen=True, slots=True)
class CanonicalChangeOperation:
    operation_id: str
    origin: OperationOrigin
    canonical_operation: str
    canonical_operation_version: str
    canonical_definition_fingerprint: str
    targets: tuple[str, ...]
    arguments: Mapping[str, Any]
    expected_effects: tuple[CanonicalAspect | str, ...]
    scope_rule_ids: tuple[str, ...]
    source_evidence: OperationSourceEvidence
    expected_existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "operation_id", _text(self.operation_id, "operation_id"))
        object.__setattr__(self, "origin", _enum(self.origin, OperationOrigin, "origin"))
        object.__setattr__(self, "canonical_operation", _text(self.canonical_operation, "canonical_operation"))
        object.__setattr__(self, "canonical_operation_version", _version(self.canonical_operation_version, "canonical_operation_version"))
        object.__setattr__(self, "canonical_definition_fingerprint", _digest(self.canonical_definition_fingerprint, "canonical_definition_fingerprint"))
        object.__setattr__(self, "targets", _texts(self.targets, "target", required=True))
        object.__setattr__(self, "arguments", _readonly_mapping(self.arguments, "arguments"))
        expected_effects = _aspects(self.expected_effects)
        expected_existence_effects = _existence_effects(self.expected_existence_effects)
        if not expected_effects and not expected_existence_effects:
            raise ValueError("change operation requires expected effect authority")
        object.__setattr__(self, "expected_effects", expected_effects)
        object.__setattr__(self, "expected_existence_effects", expected_existence_effects)
        object.__setattr__(self, "scope_rule_ids", _texts(self.scope_rule_ids, "scope_rule_id", required=True))
        _require_type(self.source_evidence, OperationSourceEvidence, "source_evidence")


@dataclass(frozen=True, slots=True)
class DerivedOperationMaterialization:
    propagation_bundle_id: str
    proposed_change_hash: str
    canonical_operation: str
    canonical_operation_version: str
    targets: tuple[str, ...]
    arguments: Mapping[str, Any]
    scope_rule_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "propagation_bundle_id", _text(self.propagation_bundle_id, "propagation_bundle_id"))
        object.__setattr__(self, "proposed_change_hash", _digest(self.proposed_change_hash, "proposed_change_hash"))
        object.__setattr__(self, "canonical_operation", _text(self.canonical_operation, "canonical_operation"))
        object.__setattr__(self, "canonical_operation_version", _version(self.canonical_operation_version, "canonical_operation_version"))
        object.__setattr__(self, "targets", _texts(self.targets, "target", required=True))
        object.__setattr__(self, "arguments", _readonly_mapping(self.arguments, "arguments"))
        object.__setattr__(self, "scope_rule_ids", _texts(self.scope_rule_ids, "scope_rule_id", required=True))


@dataclass(frozen=True, slots=True)
class ChangeDependency:
    predecessor_operation_id: str
    successor_operation_id: str
    reason_ref: str

    def __post_init__(self) -> None:
        for name in ("predecessor_operation_id", "successor_operation_id", "reason_ref"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if self.predecessor_operation_id == self.successor_operation_id:
            raise ValueError("change dependency cannot self-reference")


@dataclass(frozen=True, slots=True)
class ChangePrecondition:
    kind: PreconditionKind
    subject_ref: str
    evidence_ref: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", _enum(self.kind, PreconditionKind, "precondition kind"))
        object.__setattr__(self, "subject_ref", _text(self.subject_ref, "subject_ref"))
        object.__setattr__(self, "evidence_ref", _digest(self.evidence_ref, "evidence_ref"))


@dataclass(frozen=True, slots=True)
class SemanticImpactEvidence:
    source_semantic_id: str
    affected_semantic_id: str
    dependency_ref: str
    propagation_owner: str
    propagation_action: str
    requires_verification: bool

    def __post_init__(self) -> None:
        for name in ("source_semantic_id", "affected_semantic_id", "dependency_ref", "propagation_owner", "propagation_action"):
            object.__setattr__(self, name, _text(getattr(self, name), name))
        if not isinstance(self.requires_verification, bool):
            raise TypeError("requires_verification must be bool")


@dataclass(frozen=True, slots=True)
class ValidationTask:
    validation_task_id: str
    kind: ValidationTaskKind
    subject_semantic_ids: tuple[str, ...]
    contract_ref: str
    canonical_operation_ref: str | None = None
    dependency_ref: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "validation_task_id", _text(self.validation_task_id, "validation_task_id"))
        object.__setattr__(self, "kind", _enum(self.kind, ValidationTaskKind, "validation task kind"))
        object.__setattr__(self, "subject_semantic_ids", _texts(self.subject_semantic_ids, "subject_semantic_id", required=True))
        object.__setattr__(self, "contract_ref", _digest(self.contract_ref, "contract_ref"))
        object.__setattr__(self, "canonical_operation_ref", _optional_text(self.canonical_operation_ref, "canonical_operation_ref"))
        object.__setattr__(self, "dependency_ref", _optional_text(self.dependency_ref, "dependency_ref"))


@dataclass(frozen=True, slots=True)
class CanonicalChangeSet:
    changeset_id: str
    task_id: str
    project_id: str | None
    planning_snapshot_ref: Any
    snapshot_set_ref: Any
    semantic_environment_ref: Any
    impact_analysis_fingerprint: str
    bound_operation_fingerprint: str
    approval_scope_definition_ref: ApprovalScopeDefinitionRef
    root_operation: CanonicalChangeOperation
    derived_operations: tuple[CanonicalChangeOperation, ...]
    change_dependencies: tuple[ChangeDependency, ...]
    preconditions: tuple[ChangePrecondition, ...]
    affected_entities: tuple[str, ...]
    semantic_impacts: tuple[SemanticImpactEvidence, ...]
    validation_tasks: tuple[ValidationTask, ...]
    changeset_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "changeset_id", _text(self.changeset_id, "changeset_id"))
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        object.__setattr__(self, "project_id", _optional_text(self.project_id, "project_id"))
        object.__setattr__(self, "impact_analysis_fingerprint", _text(self.impact_analysis_fingerprint, "impact_analysis_fingerprint"))
        object.__setattr__(self, "bound_operation_fingerprint", _digest(self.bound_operation_fingerprint, "bound_operation_fingerprint"))
        _require_type(self.approval_scope_definition_ref, ApprovalScopeDefinitionRef, "approval_scope_definition_ref")
        _require_type(self.root_operation, CanonicalChangeOperation, "root_operation")
        for name, typ in (
            ("derived_operations", CanonicalChangeOperation),
            ("change_dependencies", ChangeDependency),
            ("preconditions", ChangePrecondition),
            ("semantic_impacts", SemanticImpactEvidence),
            ("validation_tasks", ValidationTask),
        ):
            values = tuple(getattr(self, name))
            if any(not isinstance(value, typ) for value in values):
                raise TypeError(f"{name} contains invalid values")
            object.__setattr__(self, name, values)
        object.__setattr__(self, "affected_entities", _texts(self.affected_entities, "affected_entity", required=True))
        object.__setattr__(self, "changeset_hash", _digest(self.changeset_hash, "changeset_hash"))


@dataclass(frozen=True, slots=True)
class ChangeSetBuildRequest:
    task_id: str
    bound_operation_evidence: BoundOperationEvidence
    impact_analysis: Any
    approval_scope_definition: Any
    canonical_operation_contracts: tuple[CanonicalOperationContractEvidence, ...]
    derived_materializations: tuple[DerivedOperationMaterialization, ...] = ()
    project_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_id", _text(self.task_id, "task_id"))
        object.__setattr__(self, "project_id", _optional_text(self.project_id, "project_id"))
        _require_type(self.bound_operation_evidence, BoundOperationEvidence, "bound_operation_evidence")
        contracts = tuple(self.canonical_operation_contracts)
        if not contracts or any(not isinstance(item, CanonicalOperationContractEvidence) for item in contracts):
            raise TypeError("canonical_operation_contracts requires contract evidence values")
        keys = [(item.canonical_operation, item.canonical_operation_version) for item in contracts]
        if len(set(keys)) != len(keys):
            raise ValueError("canonical operation contract keys must be unique")
        object.__setattr__(self, "canonical_operation_contracts", contracts)
        derived = tuple(self.derived_materializations)
        if any(not isinstance(item, DerivedOperationMaterialization) for item in derived):
            raise TypeError("derived_materializations contains invalid values")
        object.__setattr__(self, "derived_materializations", derived)


__all__ = [
    "ApprovalScopeDefinitionRef",
    "BoundOperationEvidence",
    "CanonicalChangeOperation",
    "CanonicalChangeSet",
    "CanonicalOperationContractEvidence",
    "ChangeDependency",
    "ChangePrecondition",
    "ChangeSetBuildRequest",
    "ChangeSetError",
    "DerivedOperationMaterialization",
    "OperationOrigin",
    "OperationSourceEvidence",
    "OperationSourceKind",
    "PreconditionKind",
    "SemanticImpactEvidence",
    "ValidationTask",
    "ValidationTaskKind",
]
