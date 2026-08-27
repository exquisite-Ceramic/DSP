"""D4 canonical Operation Resolver.

The resolver consumes provider profiles structurally so this platform component
stays independent from concrete Host sidecars and provider-specific MCP tools.
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


_POLICY_DECISIONS = frozenset({"ALLOW", "APPROVAL_REQUIRED", "DENY"})


class CapabilityConflictError(ValueError):
    """Raised when provider claims disagree on one canonical contract."""


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
    """Host, entity, policy, and task facts for one resolution step."""

    host_provider_servers: frozenset[str]
    entity_kinds: frozenset[str]
    policy: OperationPolicy = field(default_factory=OperationPolicy)
    task: TaskConstraints = field(default_factory=TaskConstraints)


@dataclass(frozen=True, slots=True)
class ResolvedOperation:
    """Canonical operation view; candidate provider IDs are internal hints."""

    operation_id: str
    canonical_operation: str
    input_schema: dict[str, Any]
    entity_constraints: tuple[str, ...]
    context_freshness_requirements: tuple[dict[str, Any], ...]
    operation_freshness_requirements: tuple[dict[str, Any], ...]
    effects: tuple[Any, ...]
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
                "entity_constraints": list(operation.entity_constraints),
                "context_freshness_requirements": deepcopy(
                    list(operation.context_freshness_requirements)
                ),
                "operation_freshness_requirements": deepcopy(
                    list(operation.operation_freshness_requirements)
                ),
                "effects": deepcopy(list(operation.effects)),
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
    canonical_operation: str
    profiles: tuple[CapabilityProfile, ...]
    policy_decision: str
    task_score: float


class OperationResolver:
    """Aggregate first, then filter Host → Entity → Policy → Task."""

    _RISK_ORDER = {
        "NONE": 0,
        "LOW": 1,
        "MEDIUM": 2,
        "HIGH": 3,
        "CRITICAL": 4,
    }

    def resolve(
        self,
        profiles: Iterable[CapabilityProfile],
        context: ResolutionContext,
    ) -> ResolutionResult:
        groups = self._aggregate_by_canonical_operation(profiles)
        task_candidates: list[_EligibleGroup] = []

        for canonical_operation, aggregated_profiles in groups:
            host_filtered = tuple(
                profile
                for profile in aggregated_profiles
                if profile.provider_server in context.host_provider_servers
            )
            if not host_filtered:
                continue

            entity_filtered = tuple(
                profile
                for profile in host_filtered
                if self._supports_entities(profile, context.entity_kinds)
            )
            if not entity_filtered:
                continue

            policy_decision = context.policy.decision_for(canonical_operation)
            if policy_decision == "DENY":
                continue

            if not context.task.allows(canonical_operation):
                continue

            task_candidates.append(
                _EligibleGroup(
                    canonical_operation=canonical_operation,
                    profiles=entity_filtered,
                    policy_decision=policy_decision,
                    task_score=context.task.score_for(canonical_operation),
                )
            )

        ranked_groups = sorted(
            task_candidates,
            key=lambda group: (-group.task_score, group.canonical_operation),
        )[: context.task.top_k]

        resolved: list[ResolvedOperation] = []
        candidate_map: dict[str, CapabilityProfile] = {}
        for group in ranked_groups:
            operation, operation_candidates = self._build_resolved_operation(
                group.canonical_operation,
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
    def _supports_entities(
        profile: CapabilityProfile,
        entity_kinds: frozenset[str],
    ) -> bool:
        if not profile.entity_constraints or not entity_kinds:
            return True
        return entity_kinds.issubset(profile.entity_constraints)

    def _build_resolved_operation(
        self,
        canonical_operation: str,
        profiles: tuple[CapabilityProfile, ...],
        *,
        policy_decision: str,
        task_score: float,
    ) -> tuple[ResolvedOperation, dict[str, CapabilityProfile]]:
        self._require_consensus(profiles, "category")
        input_schema = self._require_consensus(profiles, "input_schema")
        self._require_consensus(profiles, "output_schema")
        verification_contract = self._require_consensus(
            profiles,
            "verification_contract",
        )

        candidate_map: dict[str, CapabilityProfile] = {}
        candidate_ids: list[str] = []
        for profile in profiles:
            candidate_id = self._candidate_id(profile)
            candidate_ids.append(candidate_id)
            candidate_map[candidate_id] = profile

        return (
            ResolvedOperation(
                operation_id=self._operation_id(canonical_operation),
                canonical_operation=canonical_operation,
                input_schema=deepcopy(input_schema),
                entity_constraints=self._aggregate_entity_constraints(profiles),
                context_freshness_requirements=(),
                operation_freshness_requirements=self._aggregate_mapping_items(
                    profile.execution_freshness for profile in profiles
                ),
                effects=self._aggregate_effects(profiles),
                policy_decision=policy_decision,
                risk=self._aggregate_risk(profiles),
                task_score=task_score,
                preview_supported=all(profile.preview_supported for profile in profiles),
                rollback_supported=all(profile.rollback_supported for profile in profiles),
                verification_contract=deepcopy(verification_contract),
                candidate_provider_ids=tuple(candidate_ids),
            ),
            candidate_map,
        )

    @staticmethod
    def _require_consensus(
        profiles: tuple[CapabilityProfile, ...],
        attribute: str,
    ) -> Any:
        first = getattr(profiles[0], attribute)
        if any(getattr(profile, attribute) != first for profile in profiles[1:]):
            raise CapabilityConflictError(
                f"providers disagree on {attribute} for {profiles[0].canonical_operation}"
            )
        return deepcopy(first)

    @staticmethod
    def _aggregate_entity_constraints(
        profiles: tuple[CapabilityProfile, ...],
    ) -> tuple[str, ...]:
        if any(not profile.entity_constraints for profile in profiles):
            return ()
        return tuple(
            sorted(
                {
                    entity_kind
                    for profile in profiles
                    for entity_kind in profile.entity_constraints
                }
            )
        )

    @classmethod
    def _aggregate_mapping_items(
        cls,
        groups: Iterable[Iterable[Mapping[str, Any]]],
    ) -> tuple[dict[str, Any], ...]:
        by_key: dict[str, dict[str, Any]] = {}
        for group in groups:
            for item in group:
                copied = deepcopy(dict(item))
                by_key[cls._stable_json(copied)] = copied
        return tuple(by_key[key] for key in sorted(by_key))

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
