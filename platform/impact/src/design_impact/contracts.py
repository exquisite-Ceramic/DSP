"""Provider-neutral value contracts for deterministic Step27 impact analysis."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Any

from design_orchestrator.canonical_operations import CanonicalExistenceEffect


class ImpactError(ValueError):
    """Stable Step27 domain error carrying a machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _required_text(code, field_name="code")


class DependencyStrength(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    ADVISORY = "ADVISORY"


class PropagationOwner(str, Enum):
    HOST_NATIVE = "HOST_NATIVE"
    SEMANTIC_RUNTIME = "SEMANTIC_RUNTIME"
    AGENT = "AGENT"


class PropagationAction(str, Enum):
    AUTO_MUTATE = "AUTO_MUTATE"
    RECOMPUTE = "RECOMPUTE"
    REVALIDATE = "REVALIDATE"
    MARK_DIRTY = "MARK_DIRTY"
    REPLAN = "REPLAN"
    BLOCK = "BLOCK"


class ConstraintStrength(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"
    ADVISORY = "ADVISORY"


class ConstraintOperator(str, Enum):
    EQ = "EQ"
    NE = "NE"
    GT = "GT"
    GE = "GE"
    LT = "LT"
    LE = "LE"
    IN = "IN"


class ConstraintOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _enum(value: Any, enum_type: type[Enum], *, field_name: str):
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(str(value))
    except ValueError as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


def _tuple_text(
    values,
    *,
    field_name: str,
    unique: bool = False,
    sorted_values: bool = False,
) -> tuple[str, ...]:
    normalized = tuple(_required_text(item, field_name=field_name) for item in values)
    if unique and len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} values must be unique")
    if sorted_values:
        normalized = tuple(sorted(normalized))
    return normalized


def _optional_text(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    return _required_text(value, field_name=field_name)


def _readonly_mapping(value: Mapping[str, Any], *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return MappingProxyType(deepcopy(dict(value)))


@dataclass(frozen=True, slots=True)
class SemanticEnvironmentBinding:
    environment_id: str
    content_hash: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "environment_id",
            _required_text(self.environment_id, field_name="environment_id"),
        )
        object.__setattr__(
            self,
            "content_hash",
            _required_text(self.content_hash, field_name="content_hash"),
        )


@dataclass(frozen=True, slots=True)
class PlanningSnapshotBinding:
    snapshot_id: str
    snapshot_hash: str
    document_ref: str
    semantic_environment: SemanticEnvironmentBinding

    def __post_init__(self) -> None:
        for field_name in ("snapshot_id", "snapshot_hash", "document_ref"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        if not isinstance(self.semantic_environment, SemanticEnvironmentBinding):
            raise TypeError("semantic_environment must be SemanticEnvironmentBinding")


@dataclass(frozen=True, slots=True)
class SnapshotSetBinding:
    snapshot_set_id: str
    snapshot_set_hash: str
    member_snapshot_ids: tuple[str, ...]
    semantic_environment: SemanticEnvironmentBinding

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "snapshot_set_id",
            _required_text(self.snapshot_set_id, field_name="snapshot_set_id"),
        )
        object.__setattr__(
            self,
            "snapshot_set_hash",
            _required_text(self.snapshot_set_hash, field_name="snapshot_set_hash"),
        )
        members = _tuple_text(
            self.member_snapshot_ids,
            field_name="member_snapshot_ids",
            unique=True,
            sorted_values=True,
        )
        if not members:
            raise ValueError("member_snapshot_ids requires at least one snapshot")
        object.__setattr__(self, "member_snapshot_ids", members)
        if not isinstance(self.semantic_environment, SemanticEnvironmentBinding):
            raise TypeError("semantic_environment must be SemanticEnvironmentBinding")


@dataclass(frozen=True, slots=True)
class RelationshipEvidence:
    relationship_id: str
    source_semantic_id: str
    target_semantic_id: str
    relationship_type: str
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "relationship_id",
            "source_semantic_id",
            "target_semantic_id",
            "relationship_type",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "evidence_refs",
            _tuple_text(self.evidence_refs, field_name="evidence_refs"),
        )


@dataclass(frozen=True, slots=True)
class DependencyEdge:
    dependency_id: str
    source_semantic_id: str
    target_semantic_id: str
    strength: DependencyStrength
    propagation_owner: PropagationOwner
    propagation_action: PropagationAction
    rule_ref: str | None = None
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("dependency_id", "source_semantic_id", "target_semantic_id"):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "strength",
            _enum(self.strength, DependencyStrength, field_name="strength"),
        )
        object.__setattr__(
            self,
            "propagation_owner",
            _enum(
                self.propagation_owner,
                PropagationOwner,
                field_name="propagation_owner",
            ),
        )
        object.__setattr__(
            self,
            "propagation_action",
            _enum(
                self.propagation_action,
                PropagationAction,
                field_name="propagation_action",
            ),
        )
        object.__setattr__(
            self,
            "rule_ref",
            _optional_text(self.rule_ref, field_name="rule_ref"),
        )
        object.__setattr__(
            self,
            "evidence_refs",
            _tuple_text(self.evidence_refs, field_name="evidence_refs"),
        )


@dataclass(frozen=True, slots=True)
class ConstraintEvaluationSpec:
    fact_key: str
    operator: ConstraintOperator
    expected_value: object

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "fact_key",
            _required_text(self.fact_key, field_name="fact_key"),
        )
        object.__setattr__(
            self,
            "operator",
            _enum(self.operator, ConstraintOperator, field_name="operator"),
        )
        object.__setattr__(self, "expected_value", deepcopy(self.expected_value))


@dataclass(frozen=True, slots=True)
class ConstraintRule:
    constraint_id: str
    applies_to: tuple[str, ...]
    strength: ConstraintStrength
    evaluation_spec: ConstraintEvaluationSpec
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "constraint_id",
            _required_text(self.constraint_id, field_name="constraint_id"),
        )
        applies_to = _tuple_text(
            self.applies_to,
            field_name="applies_to",
            unique=True,
            sorted_values=True,
        )
        if not applies_to:
            raise ValueError("applies_to requires at least one semantic id")
        object.__setattr__(self, "applies_to", applies_to)
        object.__setattr__(
            self,
            "strength",
            _enum(self.strength, ConstraintStrength, field_name="strength"),
        )
        if not isinstance(self.evaluation_spec, ConstraintEvaluationSpec):
            raise TypeError("evaluation_spec must be ConstraintEvaluationSpec")
        object.__setattr__(
            self,
            "evidence_refs",
            _tuple_text(self.evidence_refs, field_name="evidence_refs"),
        )


@dataclass(frozen=True, slots=True)
class IntentBoundary:
    direct_targets: tuple[str, ...]
    allowed_canonical_effects: tuple[str, ...] = ()
    allowed_derived_rule_refs: tuple[str, ...] = ()
    allowed_existence_effects: tuple[CanonicalExistenceEffect | str, ...] = ()

    def __post_init__(self) -> None:
        direct_targets = _tuple_text(
            self.direct_targets,
            field_name="direct_targets",
            unique=True,
            sorted_values=True,
        )
        if not direct_targets:
            raise ValueError("direct_targets requires at least one semantic id")
        object.__setattr__(self, "direct_targets", direct_targets)
        object.__setattr__(
            self,
            "allowed_canonical_effects",
            _tuple_text(
                self.allowed_canonical_effects,
                field_name="allowed_canonical_effects",
                unique=True,
                sorted_values=True,
            ),
        )
        object.__setattr__(
            self,
            "allowed_derived_rule_refs",
            _tuple_text(
                self.allowed_derived_rule_refs,
                field_name="allowed_derived_rule_refs",
                unique=True,
                sorted_values=True,
            ),
        )
        existence_effects = tuple(
            sorted(
                {
                    value
                    if isinstance(value, CanonicalExistenceEffect)
                    else CanonicalExistenceEffect(str(value))
                    for value in self.allowed_existence_effects
                },
                key=lambda item: item.value,
            )
        )
        object.__setattr__(self, "allowed_existence_effects", existence_effects)


@dataclass(frozen=True, slots=True)
class PredictedImpact:
    source_semantic_id: str
    affected_semantic_id: str
    strength: DependencyStrength
    propagation_owner: PropagationOwner
    propagation_action: PropagationAction
    dependency_ref: str
    evidence_refs: tuple[str, ...]
    requires_verification: bool

    def __post_init__(self) -> None:
        for field_name in (
            "source_semantic_id",
            "affected_semantic_id",
            "dependency_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )
        object.__setattr__(
            self,
            "strength",
            _enum(self.strength, DependencyStrength, field_name="strength"),
        )
        object.__setattr__(
            self,
            "propagation_owner",
            _enum(
                self.propagation_owner,
                PropagationOwner,
                field_name="propagation_owner",
            ),
        )
        object.__setattr__(
            self,
            "propagation_action",
            _enum(
                self.propagation_action,
                PropagationAction,
                field_name="propagation_action",
            ),
        )
        object.__setattr__(
            self,
            "evidence_refs",
            _tuple_text(self.evidence_refs, field_name="evidence_refs"),
        )
        if not isinstance(self.requires_verification, bool):
            raise TypeError("requires_verification must be bool")


@dataclass(frozen=True, slots=True)
class PropagationBundle:
    bundle_id: str
    rule_ref: str
    strength: DependencyStrength
    propagation_owner: PropagationOwner
    propagation_action: PropagationAction
    source_entities: tuple[str, ...]
    affected_entities: tuple[str, ...]
    deterministic: bool
    proposed_changes: tuple[Mapping[str, object], ...]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "bundle_id",
            _required_text(self.bundle_id, field_name="bundle_id"),
        )
        object.__setattr__(
            self,
            "rule_ref",
            _required_text(self.rule_ref, field_name="rule_ref"),
        )
        object.__setattr__(
            self,
            "strength",
            _enum(self.strength, DependencyStrength, field_name="strength"),
        )
        object.__setattr__(
            self,
            "propagation_owner",
            _enum(
                self.propagation_owner,
                PropagationOwner,
                field_name="propagation_owner",
            ),
        )
        object.__setattr__(
            self,
            "propagation_action",
            _enum(
                self.propagation_action,
                PropagationAction,
                field_name="propagation_action",
            ),
        )
        object.__setattr__(
            self,
            "source_entities",
            _tuple_text(
                self.source_entities,
                field_name="source_entities",
                unique=True,
                sorted_values=True,
            ),
        )
        object.__setattr__(
            self,
            "affected_entities",
            _tuple_text(
                self.affected_entities,
                field_name="affected_entities",
                unique=True,
                sorted_values=True,
            ),
        )
        if not isinstance(self.deterministic, bool):
            raise TypeError("deterministic must be bool")
        copied = tuple(
            _readonly_mapping(item, field_name="proposed_changes entry")
            for item in self.proposed_changes
        )
        object.__setattr__(self, "proposed_changes", copied)


@dataclass(frozen=True, slots=True)
class ImpactException:
    exception_id: str
    reason_code: str
    source_entities: tuple[str, ...]
    affected_entities: tuple[str, ...]
    strength: str
    propagation_owner: str
    requested_action: str
    blocking: bool
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "exception_id",
            "reason_code",
            "strength",
            "propagation_owner",
            "requested_action",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(str(getattr(self, field_name)), field_name=field_name),
            )
        object.__setattr__(
            self,
            "source_entities",
            _tuple_text(
                self.source_entities,
                field_name="source_entities",
                unique=True,
                sorted_values=True,
            ),
        )
        object.__setattr__(
            self,
            "affected_entities",
            _tuple_text(
                self.affected_entities,
                field_name="affected_entities",
                unique=True,
                sorted_values=True,
            ),
        )
        object.__setattr__(
            self,
            "evidence_refs",
            _tuple_text(self.evidence_refs, field_name="evidence_refs"),
        )
        if not isinstance(self.blocking, bool):
            raise TypeError("blocking must be bool")


@dataclass(frozen=True, slots=True)
class ImpactAnalysis:
    analysis_id: str
    canonical_operation: str
    direct_targets: tuple[str, ...]
    planning_snapshot_ref: PlanningSnapshotBinding
    snapshot_set_ref: SnapshotSetBinding
    semantic_environment_ref: SemanticEnvironmentBinding
    predicted_impacts: tuple[PredictedImpact, ...] = ()
    propagation_bundles: tuple[PropagationBundle, ...] = ()
    exceptions: tuple[ImpactException, ...] = ()
    analysis_fingerprint: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "analysis_id",
            _required_text(self.analysis_id, field_name="analysis_id"),
        )
        object.__setattr__(
            self,
            "canonical_operation",
            _required_text(self.canonical_operation, field_name="canonical_operation"),
        )
        object.__setattr__(
            self,
            "direct_targets",
            _tuple_text(
                self.direct_targets,
                field_name="direct_targets",
                unique=True,
                sorted_values=True,
            ),
        )
        if not isinstance(self.planning_snapshot_ref, PlanningSnapshotBinding):
            raise TypeError("planning_snapshot_ref must be PlanningSnapshotBinding")
        if not isinstance(self.snapshot_set_ref, SnapshotSetBinding):
            raise TypeError("snapshot_set_ref must be SnapshotSetBinding")
        if not isinstance(self.semantic_environment_ref, SemanticEnvironmentBinding):
            raise TypeError("semantic_environment_ref must be SemanticEnvironmentBinding")

        predicted = tuple(self.predicted_impacts)
        bundles = tuple(self.propagation_bundles)
        exceptions = tuple(self.exceptions)
        if any(not isinstance(item, PredictedImpact) for item in predicted):
            raise TypeError("predicted_impacts must contain PredictedImpact values")
        if any(not isinstance(item, PropagationBundle) for item in bundles):
            raise TypeError("propagation_bundles must contain PropagationBundle values")
        if any(not isinstance(item, ImpactException) for item in exceptions):
            raise TypeError("exceptions must contain ImpactException values")
        object.__setattr__(self, "predicted_impacts", predicted)
        object.__setattr__(self, "propagation_bundles", bundles)
        object.__setattr__(self, "exceptions", exceptions)
        object.__setattr__(
            self,
            "analysis_fingerprint",
            _required_text(self.analysis_fingerprint, field_name="analysis_fingerprint"),
        )


__all__ = [
    "ConstraintEvaluationSpec",
    "ConstraintOperator",
    "ConstraintOutcome",
    "ConstraintRule",
    "ConstraintStrength",
    "DependencyEdge",
    "DependencyStrength",
    "ImpactAnalysis",
    "ImpactError",
    "ImpactException",
    "IntentBoundary",
    "PlanningSnapshotBinding",
    "PredictedImpact",
    "PropagationAction",
    "PropagationBundle",
    "PropagationOwner",
    "RelationshipEvidence",
    "SemanticEnvironmentBinding",
    "SnapshotSetBinding",
]
