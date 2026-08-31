"""D4 canonical Operation Resolver.

The resolver consumes provider profiles structurally so this platform component
stays independent from concrete Host sidecars and provider-specific MCP tools.
Provider execution schemas and native entity constraints remain internal;
LLM-facing schemas and applicability come only from platform-owned canonical
operation definitions plus a ContextSnapshot-bound semantic read model.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import json
from math import isfinite
from types import MappingProxyType
from typing import Any, Protocol

from design_orchestrator.canonical_operations import (
    CanonicalExistenceEffect,
    CanonicalOperationDefinition,
)


_POLICY_DECISIONS = frozenset({"ALLOW", "APPROVAL_REQUIRED", "DENY"})
_CANONICAL_TERM_PUNCTUATION = frozenset("._-")


def _required_text(value: str, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _canonical_term(value: str) -> str:
    term = _required_text(value, field_name="canonical classification")
    prefix, separator, local_name = term.partition(":")
    if (
        not separator
        or not prefix
        or not local_name
        or not prefix[0].isalpha()
        or not local_name[0].isalpha()
        or not all(
            character.isalnum() or character in _CANONICAL_TERM_PUNCTUATION
            for character in prefix
        )
        or not all(
            character.isalnum() or character in _CANONICAL_TERM_PUNCTUATION
            for character in local_name
        )
    ):
        raise ValueError(
            "canonical classification must be a namespace-qualified term "
            "such as 'ifc:IfcWall'"
        )
    return term


class CapabilityConflictError(ValueError):
    """Raised when platform canonical contracts are ambiguous or invalid."""


class CapabilityProfile(Protocol):
    provider_server: str
    provider_tool: str
    canonical_operation: str
    category: str
    entity_constraints: tuple[str, ...]
    execution_freshness: tuple[dict[str, Any], ...]
    effects: tuple[Any, ...]
    risk: str | None
    preview_supported: bool
    rollback_supported: bool
    verification_contract: dict[str, Any]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any] | None


@dataclass(frozen=True, slots=True)
class ClassificationGuarantee:
    """Provider-neutral statement that classification is safe for machine use."""

    machine_decision_supported: bool

    def __post_init__(self) -> None:
        if not isinstance(self.machine_decision_supported, bool):
            raise ValueError("machine_decision_supported must be a boolean")


@dataclass(frozen=True, slots=True)
class SemanticEligibilityEntity:
    """Canonical classifications for one semantic entity in a bound snapshot."""

    semantic_id: str
    canonical_classifications: tuple[str, ...] = ()
    classification_guarantee: ClassificationGuarantee | None = None

    def __post_init__(self) -> None:
        semantic_id = _required_text(self.semantic_id, field_name="semantic_id")
        classifications = tuple(
            sorted({_canonical_term(item) for item in self.canonical_classifications})
        )
        guarantee = self.classification_guarantee
        if guarantee is not None and not isinstance(guarantee, ClassificationGuarantee):
            raise TypeError(
                "classification_guarantee must be a ClassificationGuarantee or None"
            )
        object.__setattr__(self, "semantic_id", semantic_id)
        object.__setattr__(self, "canonical_classifications", classifications)


@dataclass(frozen=True, slots=True)
class SemanticEligibilityContext:
    """Small provider-neutral eligibility view bound to one ContextSnapshot."""

    context_snapshot_id: str
    context_snapshot_hash: str
    document_ref: str
    semantic_environment_ref: str
    entities: tuple[SemanticEligibilityEntity, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "context_snapshot_id",
            "context_snapshot_hash",
            "document_ref",
            "semantic_environment_ref",
        ):
            object.__setattr__(
                self,
                field_name,
                _required_text(getattr(self, field_name), field_name=field_name),
            )

        entities = tuple(self.entities)
        if any(not isinstance(item, SemanticEligibilityEntity) for item in entities):
            raise TypeError("entities must contain SemanticEligibilityEntity values")
        semantic_ids = [item.semantic_id for item in entities]
        if len(set(semantic_ids)) != len(semantic_ids):
            raise ValueError("semantic eligibility context requires unique semantic_id values")
        object.__setattr__(self, "entities", entities)


@dataclass(frozen=True, slots=True)
class OperationPolicy:
    """Canonical operation policy decisions for the current resolution step."""

    decisions: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        normalized = {
            str(operation): str(decision).upper()
            for operation, decision in self.decisions.items()
        }
        invalid = sorted(set(normalized.values()) - _POLICY_DECISIONS)
        if invalid:
            raise ValueError(f"invalid policy decision(s): {invalid}")
        object.__setattr__(self, "decisions", MappingProxyType(normalized))

    def decision_for(self, canonical_operation: str) -> str:
        return self.decisions.get(canonical_operation, "ALLOW")


@dataclass(frozen=True, slots=True)
class TaskConstraints:
    """Task relevance constraints applied after policy filtering."""

    allowed_operations: frozenset[str] | None = None
    scores: Mapping[str, float] = field(default_factory=dict)
    top_k: int = 10

    def __post_init__(self) -> None:
        if not isinstance(self.top_k, int) or isinstance(self.top_k, bool):
            raise ValueError("top_k must be an integer between 3 and 10")
        if not 3 <= self.top_k <= 10:
            raise ValueError("top_k must be between 3 and 10")

        allowed = (
            None
            if self.allowed_operations is None
            else frozenset(str(operation) for operation in self.allowed_operations)
        )
        normalized_scores: dict[str, float] = {}
        for operation, raw_score in self.scores.items():
            score = float(raw_score)
            if not isfinite(score):
                raise ValueError(f"task score for {operation!r} must be finite")
            normalized_scores[str(operation)] = score

        object.__setattr__(self, "allowed_operations", allowed)
        object.__setattr__(self, "scores", MappingProxyType(normalized_scores))

    def allows(self, canonical_operation: str) -> bool:
        return (
            self.allowed_operations is None
            or canonical_operation in self.allowed_operations
        )

    def score_for(self, canonical_operation: str) -> float:
        return self.scores.get(canonical_operation, 0.0)


@dataclass(frozen=True, slots=True)
class ResolutionContext:
    """Host, semantic snapshot, policy, and task facts for one resolution step."""

    host_provider_servers: frozenset[str]
    semantic_context: SemanticEligibilityContext
    policy: OperationPolicy = field(default_factory=OperationPolicy)
    task: TaskConstraints = field(default_factory=TaskConstraints)

    def __post_init__(self) -> None:
        if not isinstance(self.semantic_context, SemanticEligibilityContext):
            raise TypeError("semantic_context must be a SemanticEligibilityContext")


@dataclass(frozen=True, slots=True)
class ResolvedOperation:
    """Canonical operation view; candidate provider IDs are internal hints."""

    operation_id: str
    canonical_operation: str
    input_schema: dict[str, Any]
    canonical_entity_constraints: tuple[str, ...]
    context_freshness_requirements: tuple[dict[str, Any], ...]
    operation_freshness_requirements: tuple[dict[str, Any], ...]
    effects: tuple[Any, ...]
    existence_effects: tuple[CanonicalExistenceEffect, ...]
    policy_decision: str
    risk: str | None
    task_score: float
    preview_supported: bool
    rollback_supported: bool
    verification_contract: dict[str, Any]
    candidate_provider_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResolutionResult:
    """Resolution output with a separate internal provider-candidate map."""

    resolved_operations: tuple[ResolvedOperation, ...]
    provider_candidates: dict[str, CapabilityProfile]

    def llm_action_space(self) -> tuple[dict[str, object], ...]:
        """Return only canonical planning data; provider routing stays internal."""

        return tuple(
            {
                "operation_id": operation.operation_id,
                "canonical_operation": operation.canonical_operation,
                "input_schema": deepcopy(operation.input_schema),
                "canonical_entity_constraints": list(
                    operation.canonical_entity_constraints
                ),
                "context_freshness_requirements": deepcopy(
                    list(operation.context_freshness_requirements)
                ),
                "operation_freshness_requirements": deepcopy(
                    list(operation.operation_freshness_requirements)
                ),
                "effects": deepcopy(list(operation.effects)),
                "existence_effects": [
                    item.value for item in operation.existence_effects
                ],
                "policy_decision": operation.policy_decision,
                "risk": operation.risk,
                "task_score": operation.task_score,
                "preview_supported": operation.preview_supported,
                "rollback_supported": operation.rollback_supported,
                "verification_contract": deepcopy(operation.verification_contract),
            }
            for operation in self.resolved_operations
        )

    def structured_output_schema(self) -> dict[str, object]:
        """Build the constrained canonical-operation schema presented to the LLM."""

        operation_items: dict[str, object]
        if self.resolved_operations:
            one_of = [
                {
                    "type": "object",
                    "properties": {
                        "canonical_operation": {
                            "const": operation.canonical_operation,
                        },
                        "arguments": deepcopy(operation.input_schema),
                    },
                    "required": ["canonical_operation", "arguments"],
                    "additionalProperties": False,
                }
                for operation in self.resolved_operations
            ]
            operation_items = {
                "type": "array",
                "minItems": 1,
                "items": {"oneOf": one_of},
            }
        else:
            operation_items = {
                "type": "array",
                "maxItems": 0,
                "items": False,
            }

        return {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "type": "object",
            "properties": {"operations": operation_items},
            "required": ["operations"],
            "additionalProperties": False,
        }


@dataclass(frozen=True, slots=True)
class _EligibleGroup:
    definition: CanonicalOperationDefinition
    profiles: tuple[CapabilityProfile, ...]
    policy_decision: str
    task_score: float


class OperationResolver:
    """Aggregate first, then filter Host → Canonical Entity → Policy → Task.

    Canonical definitions are platform-owned. Provider MCP schemas and native
    entity constraints are retained only in ``provider_candidates`` for later
    execution-time ProviderBinding/adaptation.
    """

    _RISK_ORDER = {
        "NONE": 0,
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "CRITICAL": 4,
    }

    def __init__(
        self,
        canonical_operations: Iterable[CanonicalOperationDefinition],
    ) -> None:
        definitions: dict[str, CanonicalOperationDefinition] = {}
        for definition in canonical_operations:
            if definition.canonical_operation in definitions:
                raise CapabilityConflictError(
                    "duplicate canonical operation definition: "
                    f"{definition.canonical_operation}"
                )
            definitions[definition.canonical_operation] = definition
        self._definitions = MappingProxyType(definitions)

    def resolve(
        self,
        profiles: Iterable[CapabilityProfile],
        context: ResolutionContext,
    ) -> ResolutionResult:
        groups = self._aggregate_by_canonical_operation(profiles)
        task_candidates: list[_EligibleGroup] = []

        for canonical_operation, aggregated_profiles in groups:
            definition = self._definitions.get(canonical_operation)
            if definition is None:
                # Unknown provider claims never expand the LLM action space.
                continue

            contract_filtered = tuple(
                profile
                for profile in aggregated_profiles
                if self._matches_canonical_contract(profile, definition)
            )
            if not contract_filtered:
                continue

            host_filtered = tuple(
                profile
                for profile in contract_filtered
                if profile.provider_server in context.host_provider_servers
            )
            if not host_filtered:
                continue

            if not self._supports_canonical_entities(
                definition,
                context.semantic_context,
            ):
                continue

            policy_decision = context.policy.decision_for(canonical_operation)
            if policy_decision == "DENY":
                continue

            if not context.task.allows(canonical_operation):
                continue

            task_candidates.append(
                _EligibleGroup(
                    definition=definition,
                    profiles=host_filtered,
                    policy_decision=policy_decision,
                    task_score=context.task.score_for(canonical_operation),
                )
            )

        ranked_groups = sorted(
            task_candidates,
            key=lambda group: (
                -group.task_score,
                group.definition.canonical_operation,
            ),
        )[: context.task.top_k]

        resolved: list[ResolvedOperation] = []
        candidate_map: dict[str, CapabilityProfile] = {}
        for group in ranked_groups:
            operation, operation_candidates = self._build_resolved_operation(
                group.definition,
                group.profiles,
                policy_decision=group.policy_decision,
                task_score=group.task_score,
            )
            resolved.append(operation)
            candidate_map.update(operation_candidates)

        return ResolutionResult(
            resolved_operations=tuple(resolved),
            provider_candidates=candidate_map,
        )

    @staticmethod
    def _aggregate_by_canonical_operation(
        profiles: Iterable[CapabilityProfile],
    ) -> tuple[tuple[str, tuple[CapabilityProfile, ...]], ...]:
        grouped: dict[str, list[CapabilityProfile]] = defaultdict(list)
        for profile in sorted(
            profiles,
            key=lambda item: (
                item.canonical_operation,
                item.provider_server,
                item.provider_tool,
            ),
        ):
            grouped[profile.canonical_operation].append(profile)

        return tuple(
            (canonical_operation, tuple(grouped[canonical_operation]))
            for canonical_operation in sorted(grouped)
        )

    @staticmethod
    def _matches_canonical_contract(
        profile: CapabilityProfile,
        definition: CanonicalOperationDefinition,
    ) -> bool:
        # Provider execution input/output schemas are intentionally not compared
        # here. They may differ and are adapted only after late ProviderBinding.
        return (
            profile.category == definition.category
            and profile.verification_contract == definition.verification_contract
        )

    @staticmethod
    def _supports_canonical_entities(
        definition: CanonicalOperationDefinition,
        semantic_context: SemanticEligibilityContext,
    ) -> bool:
        constraints = frozenset(definition.canonical_entity_constraints)
        if not constraints:
            # Progressive invariant: unconstrained actions must not force
            # CLASSIFICATION reconstruction or evidence.
            return True
        if not semantic_context.entities:
            return False

        for entity in semantic_context.entities:
            guarantee = entity.classification_guarantee
            if (
                not entity.canonical_classifications
                or guarantee is None
                or not guarantee.machine_decision_supported
                or constraints.isdisjoint(entity.canonical_classifications)
            ):
                return False
        return True

    def _build_resolved_operation(
        self,
        definition: CanonicalOperationDefinition,
        profiles: tuple[CapabilityProfile, ...],
        *,
        policy_decision: str,
        task_score: float,
    ) -> tuple[ResolvedOperation, dict[str, CapabilityProfile]]:
        candidate_map: dict[str, CapabilityProfile] = {}
        candidate_ids: list[str] = []
        for profile in profiles:
            candidate_id = self._candidate_id(profile)
            candidate_ids.append(candidate_id)
            candidate_map[candidate_id] = profile

        return (
            ResolvedOperation(
                operation_id=self._operation_id(definition.canonical_operation),
                canonical_operation=definition.canonical_operation,
                input_schema=deepcopy(definition.input_schema),
                canonical_entity_constraints=tuple(
                    definition.canonical_entity_constraints
                ),
                context_freshness_requirements=deepcopy(
                    definition.context_freshness_requirements
                ),
                operation_freshness_requirements=deepcopy(
                    definition.operation_freshness_requirements
                ),
                effects=self._aggregate_effects(profiles),
                existence_effects=tuple(definition.existence_effects),
                policy_decision=policy_decision,
                risk=self._aggregate_risk(profiles),
                task_score=task_score,
                preview_supported=all(profile.preview_supported for profile in profiles),
                rollback_supported=all(profile.rollback_supported for profile in profiles),
                verification_contract=deepcopy(definition.verification_contract),
                candidate_provider_ids=tuple(candidate_ids),
            ),
            candidate_map,
        )

    @classmethod
    def _aggregate_effects(
        cls,
        profiles: tuple[CapabilityProfile, ...],
    ) -> tuple[Any, ...]:
        by_key: dict[str, Any] = {}
        for profile in profiles:
            for effect in profile.effects:
                copied = deepcopy(effect)
                by_key[cls._stable_json(copied)] = copied
        return tuple(by_key[key] for key in sorted(by_key))

    def _aggregate_risk(
        self,
        profiles: tuple[CapabilityProfile, ...],
    ) -> str | None:
        risks = [profile.risk for profile in profiles if profile.risk is not None]
        if not risks:
            return None

        normalized = [risk.upper() for risk in risks]
        unknown = sorted({risk for risk in normalized if risk not in self._RISK_ORDER})
        if unknown:
            if len(set(normalized)) == 1:
                return risks[0]
            raise CapabilityConflictError(
                f"cannot conservatively aggregate unknown risk values: {unknown}"
            )

        return max(normalized, key=self._RISK_ORDER.__getitem__)

    @staticmethod
    def _operation_id(canonical_operation: str) -> str:
        digest = sha256(canonical_operation.encode("utf-8")).hexdigest()[:16]
        return f"ro_{digest}"

    @staticmethod
    def _candidate_id(profile: CapabilityProfile) -> str:
        raw = (
            f"{profile.provider_server}\0{profile.provider_tool}\0"
            f"{profile.canonical_operation}"
        )
        digest = sha256(raw.encode("utf-8")).hexdigest()[:16]
        return f"pc_{digest}"

    @staticmethod
    def _stable_json(value: Any) -> str:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        )
