"""Immutable provider-neutral contracts for Step28 approval scope."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re
from typing import Any


class ApprovalScopeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _text(code, "code")


class CanonicalAspect(str, Enum):
    IDENTITY = "IDENTITY"
    PROPERTIES = "PROPERTIES"
    PLACEMENT = "PLACEMENT"
    GEOMETRY = "GEOMETRY"
    SPATIAL = "SPATIAL"
    CONNECTIVITY = "CONNECTIVITY"
    RELATIONSHIPS = "RELATIONSHIPS"
    CONSTRAINTS = "CONSTRAINTS"
    CLASSIFICATION = "CLASSIFICATION"


class PredicateField(str, Enum):
    SEMANTIC_ID = "SEMANTIC_ID"
    CANONICAL_KIND = "CANONICAL_KIND"
    SOURCE_ENTITY = "SOURCE_ENTITY"
    DERIVATION_RULE = "DERIVATION_RULE"


class PredicateOperator(str, Enum):
    EQ = "EQ"
    IN = "IN"


def _text(value: str, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} is required")
    return value.strip()


def _optional(value: str | None, name: str) -> str | None:
    return None if value is None else _text(value, name)


def _digest(value: str, name: str) -> str:
    value = _text(value, name)
    if re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise ValueError(f"{name} must be a lowercase 64-hex SHA-256 digest")
    return value


def _enum(value: Any, enum_type: type[Enum], name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {name}: {value!r}") from exc


def _texts(values, name: str, *, required: bool = False) -> tuple[str, ...]:
    result = tuple(sorted({_text(value, name) for value in values}))
    if required and not result:
        raise ValueError(f"{name} requires at least one value")
    return result


def _aspects(values, *, required: bool = False) -> tuple[CanonicalAspect, ...]:
    result = tuple(
        sorted(
            {_enum(v, CanonicalAspect, "canonical aspect") for v in values},
            key=lambda v: v.value,
        )
    )
    if required and not result:
        raise ValueError("allowed_aspects requires at least one canonical aspect")
    return result


@dataclass(frozen=True, slots=True)
class PredicateTerm:
    field: PredicateField
    operator: PredicateOperator
    values: tuple[str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "field", _enum(self.field, PredicateField, "predicate field"))
        object.__setattr__(self, "operator", _enum(self.operator, PredicateOperator, "predicate operator"))
        values = _texts(self.values, "predicate value", required=True)
        if self.operator is PredicateOperator.EQ and len(values) != 1:
            raise ValueError("EQ requires exactly one predicate value")
        object.__setattr__(self, "values", values)


@dataclass(frozen=True, slots=True)
class EntityPredicate:
    all_of: tuple[PredicateTerm, ...]

    def __post_init__(self) -> None:
        terms = tuple(self.all_of)
        if not terms or any(not isinstance(term, PredicateTerm) for term in terms):
            raise ValueError("all_of requires PredicateTerm values")
        unique = {(t.field.value, t.operator.value, t.values): t for t in terms}
        object.__setattr__(self, "all_of", tuple(unique[key] for key in sorted(unique)))


@dataclass(frozen=True, slots=True)
class EntitySelector:
    entities: tuple[str, ...] = ()
    predicate: EntityPredicate | None = None

    def __post_init__(self) -> None:
        entities = _texts(self.entities, "entity")
        if bool(entities) == (self.predicate is not None):
            raise ValueError("selector requires exactly one of entities or predicate")
        if self.predicate is not None and not isinstance(self.predicate, EntityPredicate):
            raise TypeError("predicate must be EntityPredicate")
        object.__setattr__(self, "entities", entities)


@dataclass(frozen=True, slots=True)
class CanonicalEffectEvidence:
    canonical_operation: str
    canonical_operation_version: str
    allowed_aspects: tuple[CanonicalAspect | str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_operation", _text(self.canonical_operation, "canonical_operation"))
        version = _text(self.canonical_operation_version, "canonical_operation_version")
        if re.fullmatch(r"\d+\.\d+\.\d+", version) is None:
            raise ValueError("canonical_operation_version must use MAJOR.MINOR.PATCH")
        object.__setattr__(self, "canonical_operation_version", version)
        object.__setattr__(self, "allowed_aspects", _aspects(self.allowed_aspects, required=True))


@dataclass(frozen=True, slots=True)
class DirectEntityEffect:
    semantic_id: str
    allowed_aspects: tuple[CanonicalAspect | str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "semantic_id", _text(self.semantic_id, "semantic_id"))
        object.__setattr__(self, "allowed_aspects", _aspects(self.allowed_aspects, required=True))


@dataclass(frozen=True, slots=True)
class ScopeEffectRecipe:
    recipe_id: str
    dependency_ref: str
    allowed_aspects: tuple[CanonicalAspect | str, ...]
    rule_ref: str | None = None
    propagation_bundle_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "recipe_id", _text(self.recipe_id, "recipe_id"))
        object.__setattr__(self, "dependency_ref", _text(self.dependency_ref, "dependency_ref"))
        object.__setattr__(self, "allowed_aspects", _aspects(self.allowed_aspects, required=True))
        object.__setattr__(self, "rule_ref", _optional(self.rule_ref, "rule_ref"))
        object.__setattr__(self, "propagation_bundle_id", _optional(self.propagation_bundle_id, "propagation_bundle_id"))


@dataclass(frozen=True, slots=True)
class ExistingEntityRule:
    rule_id: str
    selector: EntitySelector
    allowed_aspects: tuple[CanonicalAspect | str, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _text(self.rule_id, "rule_id"))
        if not isinstance(self.selector, EntitySelector):
            raise TypeError("selector must be EntitySelector")
        object.__setattr__(self, "allowed_aspects", _aspects(self.allowed_aspects, required=True))


@dataclass(frozen=True, slots=True)
class CreationRule:
    rule_id: str
    canonical_operation: str
    source_selector: EntitySelector
    entity_kinds: tuple[str, ...]
    max_count: int | None = None
    required_derivation: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _text(self.rule_id, "rule_id"))
        object.__setattr__(self, "canonical_operation", _text(self.canonical_operation, "canonical_operation"))
        if not isinstance(self.source_selector, EntitySelector):
            raise TypeError("source_selector must be EntitySelector")
        object.__setattr__(self, "entity_kinds", _texts(self.entity_kinds, "entity_kind", required=True))
        if self.max_count is not None and (
            not isinstance(self.max_count, int)
            or isinstance(self.max_count, bool)
            or self.max_count <= 0
        ):
            raise ValueError("max_count must be a positive integer")
        object.__setattr__(self, "required_derivation", _optional(self.required_derivation, "required_derivation"))


@dataclass(frozen=True, slots=True)
class DeletionRule:
    rule_id: str
    selector: EntitySelector

    def __post_init__(self) -> None:
        object.__setattr__(self, "rule_id", _text(self.rule_id, "rule_id"))
        if not isinstance(self.selector, EntitySelector):
            raise TypeError("selector must be EntitySelector")


@dataclass(frozen=True, slots=True)
class ExecutionSliceScopeRule:
    slice_scope_rule_id: str
    document_ref: str
    existing_rule_ids: tuple[str, ...] = ()
    creation_rule_ids: tuple[str, ...] = ()
    deletion_rule_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "slice_scope_rule_id", _text(self.slice_scope_rule_id, "slice_scope_rule_id"))
        object.__setattr__(self, "document_ref", _text(self.document_ref, "document_ref"))
        for name in ("existing_rule_ids", "creation_rule_ids", "deletion_rule_ids"):
            object.__setattr__(self, name, _texts(getattr(self, name), name))


@dataclass(frozen=True, slots=True)
class ApprovalScopePlanRequest:
    canonical_effect_evidence: CanonicalEffectEvidence
    impact_analysis: Any
    intent_boundary: Any
    direct_entity_effects: tuple[DirectEntityEffect, ...] = ()
    scope_effect_recipes: tuple[ScopeEffectRecipe, ...] = ()
    requested_creation_rules: tuple[CreationRule, ...] = ()
    requested_deletion_rules: tuple[DeletionRule, ...] = ()
    execution_slice_scope_rules: tuple[ExecutionSliceScopeRule, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.canonical_effect_evidence, CanonicalEffectEvidence):
            raise TypeError("canonical_effect_evidence must be CanonicalEffectEvidence")
        typed_fields = (
            ("direct_entity_effects", DirectEntityEffect),
            ("scope_effect_recipes", ScopeEffectRecipe),
            ("requested_creation_rules", CreationRule),
            ("requested_deletion_rules", DeletionRule),
            ("execution_slice_scope_rules", ExecutionSliceScopeRule),
        )
        for name, typ in typed_fields:
            values = tuple(getattr(self, name))
            if any(not isinstance(value, typ) for value in values):
                raise TypeError(f"{name} contains invalid values")
            object.__setattr__(self, name, values)


@dataclass(frozen=True, slots=True)
class ApprovalScopeDefinition:
    scope_definition_id: str
    impact_analysis_fingerprint: str
    canonical_effect_evidence: CanonicalEffectEvidence
    planning_snapshot_ref: Any
    snapshot_set_ref: Any
    semantic_environment_ref: Any
    existing_entity_rules: tuple[ExistingEntityRule, ...]
    creation_rules: tuple[CreationRule, ...]
    deletion_rules: tuple[DeletionRule, ...]
    propagation_bundle_ids: tuple[str, ...]
    execution_slice_scope_rules: tuple[ExecutionSliceScopeRule, ...]
    scope_body_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_definition_id", _text(self.scope_definition_id, "scope_definition_id"))
        object.__setattr__(self, "impact_analysis_fingerprint", _text(self.impact_analysis_fingerprint, "impact_analysis_fingerprint"))
        object.__setattr__(self, "scope_body_hash", _digest(self.scope_body_hash, "scope_body_hash"))
        for name in ("existing_entity_rules", "creation_rules", "deletion_rules", "execution_slice_scope_rules"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "propagation_bundle_ids", _texts(self.propagation_bundle_ids, "propagation_bundle_id"))


@dataclass(frozen=True, slots=True)
class ApprovalScopeBoundary:
    scope_id: str
    changeset_hash: str
    scope_body_hash: str
    existing_entity_rules: tuple[ExistingEntityRule, ...]
    creation_rules: tuple[CreationRule, ...]
    deletion_rules: tuple[DeletionRule, ...]
    propagation_bundle_ids: tuple[str, ...]
    execution_slice_scopes: tuple[ExecutionSliceScopeRule, ...]
    scope_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "scope_id", _text(self.scope_id, "scope_id"))
        for name in ("changeset_hash", "scope_body_hash", "scope_hash"):
            object.__setattr__(self, name, _digest(getattr(self, name), name))
        for name in ("existing_entity_rules", "creation_rules", "deletion_rules", "execution_slice_scopes"):
            object.__setattr__(self, name, tuple(getattr(self, name)))
        object.__setattr__(self, "propagation_bundle_ids", _texts(self.propagation_bundle_ids, "propagation_bundle_id"))
