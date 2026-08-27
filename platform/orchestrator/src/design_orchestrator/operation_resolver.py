"""D4 canonical Operation Resolver.

The resolver deliberately consumes provider profiles structurally so this
platform component does not depend on any concrete Host sidecar package.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
from typing import Any, Protocol


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
class ResolutionContext:
    """Facts required by the D4 hard filters.

    Policy and Task fields are added in the next TDD slice. Keeping this type
    small here makes the Host → Entity behavior independently testable.
    """

    host_provider_servers: frozenset[str]
    entity_kinds: frozenset[str]


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
    resolved_operations: tuple[ResolvedOperation, ...]
    provider_candidates: dict[str, CapabilityProfile]


class OperationResolver:
    """Aggregate provider claims, then apply Host and Entity hard filters."""

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

        resolved: list[ResolvedOperation] = []
        candidate_map: dict[str, CapabilityProfile] = {}

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

            operation, operation_candidates = self._build_resolved_operation(
                canonical_operation,
                entity_filtered,
            )
            resolved.append(operation)
            candidate_map.update(operation_candidates)

        return ResolutionResult(
            resolved_operations=tuple(
                sorted(resolved, key=lambda item: item.canonical_operation)
            ),
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
                policy_decision="ALLOW",
                risk=self._aggregate_risk(profiles),
                task_score=0.0,
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

        highest = max(normalized, key=self._RISK_ORDER.__getitem__)
        return highest

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
