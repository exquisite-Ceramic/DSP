"""Deterministic task-scoped dependency impact analysis for Step27."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from enum import Enum
from hashlib import sha256
import json
from types import MappingProxyType
from typing import Any

from design_orchestrator.parameter_binder import BoundOperationProposal

from .contracts import (
    ConstraintRule,
    DependencyEdge,
    ImpactAnalysis,
    ImpactError,
    IntentBoundary,
    PlanningSnapshotBinding,
    PredictedImpact,
    PropagationOwner,
    RelationshipEvidence,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)


def _freeze_observed_facts(
    value: Mapping[str, Mapping[str, object]],
) -> Mapping[str, Mapping[str, object]]:
    if not isinstance(value, Mapping):
        raise TypeError("observed_facts must be a mapping")
    frozen: dict[str, Mapping[str, object]] = {}
    for semantic_id, facts in value.items():
        if not isinstance(semantic_id, str) or not semantic_id.strip():
            raise ValueError("observed_facts keys must be non-empty semantic ids")
        if not isinstance(facts, Mapping):
            raise TypeError("observed_facts values must be mappings")
        frozen[semantic_id.strip()] = MappingProxyType(deepcopy(dict(facts)))
    return MappingProxyType(frozen)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): _jsonable(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return deepcopy(value)


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        _jsonable(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class ImpactAnalysisRequest:
    bound_operation: BoundOperationProposal
    planning_snapshot_ref: PlanningSnapshotBinding
    snapshot_set_ref: SnapshotSetBinding
    semantic_environment_ref: SemanticEnvironmentBinding
    intent_boundary: IntentBoundary
    dependency_edges: tuple[DependencyEdge, ...] = ()
    constraint_rules: tuple[ConstraintRule, ...] = ()
    relationship_evidence: tuple[RelationshipEvidence, ...] = ()
    observed_facts: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.bound_operation, BoundOperationProposal):
            raise TypeError("bound_operation must be BoundOperationProposal")
        if not isinstance(self.planning_snapshot_ref, PlanningSnapshotBinding):
            raise TypeError("planning_snapshot_ref must be PlanningSnapshotBinding")
        if not isinstance(self.snapshot_set_ref, SnapshotSetBinding):
            raise TypeError("snapshot_set_ref must be SnapshotSetBinding")
        if not isinstance(self.semantic_environment_ref, SemanticEnvironmentBinding):
            raise TypeError("semantic_environment_ref must be SemanticEnvironmentBinding")
        if not isinstance(self.intent_boundary, IntentBoundary):
            raise TypeError("intent_boundary must be IntentBoundary")

        dependencies = tuple(self.dependency_edges)
        constraints = tuple(self.constraint_rules)
        relationships = tuple(self.relationship_evidence)
        if any(not isinstance(item, DependencyEdge) for item in dependencies):
            raise TypeError("dependency_edges must contain DependencyEdge values")
        if any(not isinstance(item, ConstraintRule) for item in constraints):
            raise TypeError("constraint_rules must contain ConstraintRule values")
        if any(not isinstance(item, RelationshipEvidence) for item in relationships):
            raise TypeError("relationship_evidence must contain RelationshipEvidence values")

        object.__setattr__(self, "dependency_edges", dependencies)
        object.__setattr__(self, "constraint_rules", constraints)
        object.__setattr__(self, "relationship_evidence", relationships)
        object.__setattr__(self, "observed_facts", _freeze_observed_facts(self.observed_facts))


class ImpactAnalyzer:
    """Analyze explicit canonical dependencies against one pinned planning state."""

    def analyze(self, request: ImpactAnalysisRequest) -> ImpactAnalysis:
        if not isinstance(request, ImpactAnalysisRequest):
            raise TypeError("request must be ImpactAnalysisRequest")

        self._validate_bindings(request)
        direct_targets = self._direct_targets(request.bound_operation)
        if direct_targets != request.intent_boundary.direct_targets:
            raise ImpactError(
                "IMPACT_INPUT_INVALID",
                "intent boundary direct targets do not match bound operation targets",
            )

        reachable_edges = self._reachable_edges(direct_targets, request.dependency_edges)
        predicted = tuple(self._to_predicted(edge) for edge in reachable_edges)
        fingerprint = self._analysis_fingerprint(
            request=request,
            direct_targets=direct_targets,
            reachable_edges=reachable_edges,
        )

        return ImpactAnalysis(
            analysis_id=f"IA-{fingerprint[:12]}",
            canonical_operation=request.bound_operation.operation.canonical_operation,
            direct_targets=direct_targets,
            planning_snapshot_ref=request.planning_snapshot_ref,
            snapshot_set_ref=request.snapshot_set_ref,
            semantic_environment_ref=request.semantic_environment_ref,
            predicted_impacts=predicted,
            propagation_bundles=(),
            exceptions=(),
            analysis_fingerprint=fingerprint,
        )

    @staticmethod
    def _validate_bindings(request: ImpactAnalysisRequest) -> None:
        environment = request.semantic_environment_ref
        if (
            request.planning_snapshot_ref.semantic_environment != environment
            or request.snapshot_set_ref.semantic_environment != environment
        ):
            raise ImpactError(
                "SEMANTIC_ENVIRONMENT_MISMATCH",
                "planning state references do not share one semantic environment",
            )

        if request.planning_snapshot_ref.snapshot_id not in request.snapshot_set_ref.member_snapshot_ids:
            raise ImpactError(
                "SNAPSHOT_MISMATCH",
                "planning snapshot is not a member of the supplied snapshot set",
            )

        dependency_ids = [item.dependency_id for item in request.dependency_edges]
        if len(set(dependency_ids)) != len(dependency_ids):
            raise ImpactError(
                "DEPENDENCY_INVALID",
                "dependency ids must be unique within one analysis request",
            )

    @staticmethod
    def _direct_targets(bound_operation: BoundOperationProposal) -> tuple[str, ...]:
        raw_targets = bound_operation.arguments.get("targets")
        if (
            raw_targets is None
            or isinstance(raw_targets, (str, bytes, Mapping))
            or not isinstance(raw_targets, Iterable)
        ):
            raise ImpactError(
                "IMPACT_INPUT_INVALID",
                "bound operation requires iterable canonical targets",
            )

        normalized: list[str] = []
        for item in raw_targets:
            if not isinstance(item, str) or not item.strip():
                raise ImpactError(
                    "IMPACT_INPUT_INVALID",
                    "bound operation targets must be non-empty semantic ids",
                )
            normalized.append(item.strip())

        direct_targets = tuple(sorted(set(normalized)))
        if not direct_targets:
            raise ImpactError(
                "IMPACT_INPUT_INVALID",
                "bound operation requires at least one canonical target",
            )
        return direct_targets

    @staticmethod
    def _reachable_edges(
        direct_targets: tuple[str, ...],
        dependency_edges: tuple[DependencyEdge, ...],
    ) -> tuple[DependencyEdge, ...]:
        ordered_edges = tuple(
            sorted(
                dependency_edges,
                key=lambda item: (
                    item.source_semantic_id,
                    item.target_semantic_id,
                    item.dependency_id,
                ),
            )
        )
        reached_entities = set(direct_targets)
        selected_ids: set[str] = set()
        selected: list[DependencyEdge] = []

        changed = True
        while changed:
            changed = False
            for edge in ordered_edges:
                if edge.dependency_id in selected_ids:
                    continue
                if edge.source_semantic_id not in reached_entities:
                    continue
                selected_ids.add(edge.dependency_id)
                selected.append(edge)
                if edge.target_semantic_id not in reached_entities:
                    reached_entities.add(edge.target_semantic_id)
                changed = True

        return tuple(
            sorted(
                selected,
                key=lambda item: (
                    item.source_semantic_id,
                    item.target_semantic_id,
                    item.dependency_id,
                ),
            )
        )

    @staticmethod
    def _to_predicted(edge: DependencyEdge) -> PredictedImpact:
        return PredictedImpact(
            source_semantic_id=edge.source_semantic_id,
            affected_semantic_id=edge.target_semantic_id,
            strength=edge.strength,
            propagation_owner=edge.propagation_owner,
            propagation_action=edge.propagation_action,
            dependency_ref=edge.dependency_id,
            evidence_refs=edge.evidence_refs,
            requires_verification=edge.propagation_owner is PropagationOwner.HOST_NATIVE,
        )

    @staticmethod
    def _analysis_fingerprint(
        *,
        request: ImpactAnalysisRequest,
        direct_targets: tuple[str, ...],
        reachable_edges: tuple[DependencyEdge, ...],
    ) -> str:
        dependency_payload = [
            {
                "dependency_id": edge.dependency_id,
                "source_semantic_id": edge.source_semantic_id,
                "target_semantic_id": edge.target_semantic_id,
                "strength": edge.strength.value,
                "propagation_owner": edge.propagation_owner.value,
                "propagation_action": edge.propagation_action.value,
                "rule_ref": edge.rule_ref,
                "evidence_refs": sorted(edge.evidence_refs),
            }
            for edge in reachable_edges
        ]
        constraint_payload = [
            {
                "constraint_id": rule.constraint_id,
                "applies_to": list(rule.applies_to),
                "strength": rule.strength.value,
                "evaluation_spec": {
                    "fact_key": rule.evaluation_spec.fact_key,
                    "operator": rule.evaluation_spec.operator.value,
                    "expected_value": _jsonable(rule.evaluation_spec.expected_value),
                },
                "evidence_refs": sorted(rule.evidence_refs),
            }
            for rule in sorted(request.constraint_rules, key=lambda item: item.constraint_id)
        ]
        payload = {
            "operation": {
                "canonical_operation": request.bound_operation.operation.canonical_operation,
                "version": request.bound_operation.operation.version,
                "arguments": _jsonable(request.bound_operation.arguments),
            },
            "direct_targets": list(direct_targets),
            "planning_snapshot": {
                "snapshot_id": request.planning_snapshot_ref.snapshot_id,
                "snapshot_hash": request.planning_snapshot_ref.snapshot_hash,
                "document_ref": request.planning_snapshot_ref.document_ref,
            },
            "snapshot_set": {
                "snapshot_set_id": request.snapshot_set_ref.snapshot_set_id,
                "snapshot_set_hash": request.snapshot_set_ref.snapshot_set_hash,
                "member_snapshot_ids": list(request.snapshot_set_ref.member_snapshot_ids),
            },
            "semantic_environment": {
                "environment_id": request.semantic_environment_ref.environment_id,
                "content_hash": request.semantic_environment_ref.content_hash,
            },
            "dependency_edges": dependency_payload,
            "constraint_rules": constraint_payload,
            "intent_boundary": {
                "direct_targets": list(request.intent_boundary.direct_targets),
                "allowed_canonical_effects": list(
                    request.intent_boundary.allowed_canonical_effects
                ),
                "allowed_derived_rule_refs": list(
                    request.intent_boundary.allowed_derived_rule_refs
                ),
            },
        }
        return _canonical_hash(payload)


__all__ = ["ImpactAnalysisRequest", "ImpactAnalyzer"]
