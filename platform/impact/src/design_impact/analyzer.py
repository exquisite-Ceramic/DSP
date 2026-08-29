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
    ConstraintOutcome,
    ConstraintRule,
    ConstraintStrength,
    DependencyEdge,
    DependencyStrength,
    ImpactAnalysis,
    ImpactError,
    ImpactException,
    IntentBoundary,
    PlanningSnapshotBinding,
    PredictedImpact,
    PropagationAction,
    PropagationBundle,
    PropagationOwner,
    RelationshipEvidence,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from .rules import evaluate_constraint


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


def _stable_exception(
    *,
    reason_code: str,
    source_entities: tuple[str, ...],
    affected_entities: tuple[str, ...],
    strength: str,
    propagation_owner: str,
    requested_action: str,
    blocking: bool,
    evidence_refs: tuple[str, ...] = (),
    identity_ref: str | None = None,
) -> ImpactException:
    source_entities = tuple(sorted(set(source_entities)))
    affected_entities = tuple(sorted(set(affected_entities)))
    evidence_refs = tuple(sorted(set(evidence_refs)))
    payload = {
        "reason_code": reason_code,
        "source_entities": source_entities,
        "affected_entities": affected_entities,
        "strength": strength,
        "propagation_owner": propagation_owner,
        "requested_action": requested_action,
        "blocking": blocking,
        "evidence_refs": evidence_refs,
        "identity_ref": identity_ref,
    }
    return ImpactException(
        exception_id=f"IX-{_canonical_hash(payload)[:12]}",
        reason_code=reason_code,
        source_entities=source_entities,
        affected_entities=affected_entities,
        strength=strength,
        propagation_owner=propagation_owner,
        requested_action=requested_action,
        blocking=blocking,
        evidence_refs=evidence_refs,
    )


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
        bundles, dependency_exceptions = self._classify_propagation(
            direct_targets=direct_targets,
            reachable_edges=reachable_edges,
            intent_boundary=request.intent_boundary,
        )
        constraint_exceptions = self._constraint_exceptions(
            request=request,
            direct_targets=direct_targets,
            predicted=predicted,
        )
        exceptions = self._normalize_exceptions(
            (*dependency_exceptions, *constraint_exceptions)
        )
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
            propagation_bundles=bundles,
            exceptions=exceptions,
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

        constraint_ids = [item.constraint_id for item in request.constraint_rules]
        if len(set(constraint_ids)) != len(constraint_ids):
            raise ImpactError(
                "CONSTRAINT_INVALID",
                "constraint ids must be unique within one analysis request",
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
    def _classify_propagation(
        *,
        direct_targets: tuple[str, ...],
        reachable_edges: tuple[DependencyEdge, ...],
        intent_boundary: IntentBoundary,
    ) -> tuple[tuple[PropagationBundle, ...], tuple[ImpactException, ...]]:
        allowed_rules = set(intent_boundary.allowed_derived_rule_refs)
        direct_target_set = set(direct_targets)
        safe_actions = {
            PropagationAction.AUTO_MUTATE,
            PropagationAction.RECOMPUTE,
            PropagationAction.REVALIDATE,
            PropagationAction.MARK_DIRTY,
        }
        groups: dict[
            tuple[DependencyStrength, PropagationOwner, PropagationAction, str],
            list[DependencyEdge],
        ] = {}
        exceptions: list[ImpactException] = []

        for edge in reachable_edges:
            scope_allowed = (
                edge.target_semantic_id in direct_target_set
                or (edge.rule_ref is not None and edge.rule_ref in allowed_rules)
            )
            if not scope_allowed:
                exceptions.append(
                    _stable_exception(
                        reason_code="INTENT_SCOPE_EXPANSION",
                        source_entities=(edge.source_semantic_id,),
                        affected_entities=(edge.target_semantic_id,),
                        strength=edge.strength.value,
                        propagation_owner=edge.propagation_owner.value,
                        requested_action=PropagationAction.REPLAN.value,
                        blocking=True,
                        evidence_refs=edge.evidence_refs,
                        identity_ref=edge.dependency_id,
                    )
                )

            if edge.propagation_action is PropagationAction.BLOCK:
                exceptions.append(
                    _stable_exception(
                        reason_code="PROPAGATION_BLOCKED",
                        source_entities=(edge.source_semantic_id,),
                        affected_entities=(edge.target_semantic_id,),
                        strength=edge.strength.value,
                        propagation_owner=edge.propagation_owner.value,
                        requested_action=PropagationAction.BLOCK.value,
                        blocking=True,
                        evidence_refs=edge.evidence_refs,
                        identity_ref=edge.dependency_id,
                    )
                )
                continue

            if (
                edge.propagation_owner is PropagationOwner.AGENT
                or edge.propagation_action is PropagationAction.REPLAN
            ):
                exceptions.append(
                    _stable_exception(
                        reason_code="REPLAN_REQUIRED",
                        source_entities=(edge.source_semantic_id,),
                        affected_entities=(edge.target_semantic_id,),
                        strength=edge.strength.value,
                        propagation_owner=edge.propagation_owner.value,
                        requested_action=PropagationAction.REPLAN.value,
                        blocking=True,
                        evidence_refs=edge.evidence_refs,
                        identity_ref=edge.dependency_id,
                    )
                )
                continue

            if (
                not scope_allowed
                or edge.propagation_owner is not PropagationOwner.SEMANTIC_RUNTIME
                or edge.propagation_action not in safe_actions
                or edge.rule_ref is None
            ):
                continue

            key = (
                edge.strength,
                edge.propagation_owner,
                edge.propagation_action,
                edge.rule_ref,
            )
            groups.setdefault(key, []).append(edge)

        bundles: list[PropagationBundle] = []
        for key in sorted(
            groups,
            key=lambda item: (item[0].value, item[1].value, item[2].value, item[3]),
        ):
            strength, owner, action, rule_ref = key
            edges = groups[key]
            source_entities = tuple(sorted({item.source_semantic_id for item in edges}))
            affected_entities = tuple(sorted({item.target_semantic_id for item in edges}))
            proposed_changes = tuple(
                {
                    "affected_semantic_id": semantic_id,
                    "action": action.value,
                    "rule_ref": rule_ref,
                }
                for semantic_id in affected_entities
            )
            bundle_payload = {
                "strength": strength.value,
                "propagation_owner": owner.value,
                "propagation_action": action.value,
                "rule_ref": rule_ref,
                "source_entities": source_entities,
                "affected_entities": affected_entities,
                "proposed_changes": proposed_changes,
            }
            bundles.append(
                PropagationBundle(
                    bundle_id=f"PB-{_canonical_hash(bundle_payload)[:12]}",
                    rule_ref=rule_ref,
                    strength=strength,
                    propagation_owner=owner,
                    propagation_action=action,
                    source_entities=source_entities,
                    affected_entities=affected_entities,
                    deterministic=True,
                    proposed_changes=proposed_changes,
                )
            )

        return tuple(bundles), tuple(exceptions)

    @staticmethod
    def _constraint_exceptions(
        *,
        request: ImpactAnalysisRequest,
        direct_targets: tuple[str, ...],
        predicted: tuple[PredictedImpact, ...],
    ) -> tuple[ImpactException, ...]:
        current_entities = set(direct_targets)
        current_entities.update(item.affected_semantic_id for item in predicted)
        exceptions: list[ImpactException] = []

        for rule in sorted(request.constraint_rules, key=lambda item: item.constraint_id):
            applicable = tuple(sorted(current_entities.intersection(rule.applies_to)))
            if not applicable:
                continue
            missing_entities = tuple(
                semantic_id
                for semantic_id in applicable
                if semantic_id not in request.observed_facts
            )
            if missing_entities:
                raise ImpactError(
                    "CONSTRAINT_INVALID",
                    "required observed facts are missing for applicable constraint entities",
                )

            facts = {semantic_id: request.observed_facts[semantic_id] for semantic_id in applicable}
            outcome, evaluated_entities = evaluate_constraint(rule, observed_facts=facts)
            if outcome is not ConstraintOutcome.FAIL:
                continue

            if rule.strength is ConstraintStrength.HARD:
                reason_code = "HARD_CONSTRAINT_FAILED"
                owner = PropagationOwner.SEMANTIC_RUNTIME.value
                action = PropagationAction.BLOCK.value
                blocking = True
            elif rule.strength is ConstraintStrength.SOFT:
                reason_code = "CONSTRAINT_REVIEW_REQUIRED"
                owner = PropagationOwner.AGENT.value
                action = PropagationAction.REPLAN.value
                blocking = False
            else:
                reason_code = "ADVISORY_CONSTRAINT"
                owner = PropagationOwner.SEMANTIC_RUNTIME.value
                action = PropagationAction.REVALIDATE.value
                blocking = False

            exceptions.append(
                _stable_exception(
                    reason_code=reason_code,
                    source_entities=direct_targets,
                    affected_entities=evaluated_entities,
                    strength=rule.strength.value,
                    propagation_owner=owner,
                    requested_action=action,
                    blocking=blocking,
                    evidence_refs=(*rule.evidence_refs, rule.constraint_id),
                    identity_ref=rule.constraint_id,
                )
            )

        return tuple(exceptions)

    @staticmethod
    def _normalize_exceptions(
        exceptions: tuple[ImpactException, ...],
    ) -> tuple[ImpactException, ...]:
        unique = {item.exception_id: item for item in exceptions}
        return tuple(
            sorted(
                unique.values(),
                key=lambda item: (
                    item.reason_code,
                    item.affected_entities,
                    item.source_entities,
                    item.exception_id,
                ),
            )
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
            "observed_facts": _jsonable(request.observed_facts),
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
