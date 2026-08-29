from __future__ import annotations

from copy import deepcopy

import pytest

from design_impact import (
    DependencyEdge,
    DependencyStrength,
    ImpactAnalyzer,
    ImpactAnalysisRequest,
    ImpactError,
    IntentBoundary,
    PlanningSnapshotBinding,
    PropagationAction,
    PropagationOwner,
    RelationshipEvidence,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from design_orchestrator.parameter_binder import (
    BoundOperationProposal,
    CanonicalOperationRef,
    ContextSnapshotRef,
    PlanningRequirements,
)


def _bound_move(*, targets=("WALL-001",), displacement=(100.0, 0.0, 0.0)):
    return BoundOperationProposal(
        operation=CanonicalOperationRef("move.v1", "1.0.0"),
        arguments={"targets": list(targets), "displacement": list(displacement)},
        binding_evidence={},
        context_snapshot_ref=ContextSnapshotRef("CS-1", "ctx-hash", "DOC-1"),
        planning_requirements=PlanningRequirements(),
        semantic_environment_ref="ENV-1",
    )


def _bindings(*, env_hash="env-hash", snapshot_hash="ps-hash"):
    environment = SemanticEnvironmentBinding("ENV-1", env_hash)
    planning = PlanningSnapshotBinding("PS-1", snapshot_hash, "DOC-1", environment)
    snapshot_set = SnapshotSetBinding("PSS-1", "pss-hash", ("PS-1",), environment)
    return environment, planning, snapshot_set


def _edges():
    return (
        DependencyEdge(
            dependency_id="DEP-OPENING",
            source_semantic_id="WALL-001",
            target_semantic_id="OPENING-001",
            strength=DependencyStrength.HARD,
            propagation_owner=PropagationOwner.HOST_NATIVE,
            propagation_action=PropagationAction.REVALIDATE,
            rule_ref="RULE-OPENING",
            evidence_refs=("ifc:RelVoidsElement",),
        ),
        DependencyEdge(
            dependency_id="DEP-ANN",
            source_semantic_id="WALL-001",
            target_semantic_id="ANNOTATION-002",
            strength=DependencyStrength.SOFT,
            propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
            propagation_action=PropagationAction.RECOMPUTE,
            rule_ref="RULE-ANN",
        ),
        DependencyEdge(
            dependency_id="DEP-MEP",
            source_semantic_id="WALL-001",
            target_semantic_id="MEP-008",
            strength=DependencyStrength.SOFT,
            propagation_owner=PropagationOwner.AGENT,
            propagation_action=PropagationAction.REPLAN,
            rule_ref="RULE-MEP",
        ),
    )


def _request(*, edges=(), relationships=(), bound=None, environment=None, planning=None, snapshot_set=None):
    if environment is None or planning is None or snapshot_set is None:
        environment, planning, snapshot_set = _bindings()
    bound = bound or _bound_move()
    return ImpactAnalysisRequest(
        bound_operation=bound,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        dependency_edges=tuple(edges),
        relationship_evidence=tuple(relationships),
        intent_boundary=IntentBoundary(
            direct_targets=("WALL-001",),
            allowed_canonical_effects=("PLACEMENT", "GEOMETRY"),
            allowed_derived_rule_refs=("RULE-ANN", "RULE-MEP", "RULE-OPENING"),
        ),
    )


def test_relationship_evidence_alone_does_not_create_predicted_impact() -> None:
    result = ImpactAnalyzer().analyze(
        _request(
            relationships=(
                RelationshipEvidence(
                    relationship_id="REL-1",
                    source_semantic_id="WALL-001",
                    target_semantic_id="OPENING-001",
                    relationship_type="HAS_OPENING",
                ),
            )
        )
    )

    assert result.direct_targets == ("WALL-001",)
    assert result.predicted_impacts == ()


def test_explicit_dependencies_create_predicted_impacts() -> None:
    result = ImpactAnalyzer().analyze(_request(edges=_edges()))

    assert tuple(item.affected_semantic_id for item in result.predicted_impacts) == (
        "ANNOTATION-002",
        "MEP-008",
        "OPENING-001",
    )


def test_host_native_impact_requires_later_verification() -> None:
    result = ImpactAnalyzer().analyze(_request(edges=_edges()))
    impacts = {item.affected_semantic_id: item for item in result.predicted_impacts}

    assert impacts["OPENING-001"].requires_verification is True
    assert impacts["ANNOTATION-002"].requires_verification is False
    assert impacts["MEP-008"].requires_verification is False


def test_dependency_traversal_follows_explicit_directional_edges() -> None:
    nested = DependencyEdge(
        dependency_id="DEP-NESTED",
        source_semantic_id="OPENING-001",
        target_semantic_id="TAG-010",
        strength=DependencyStrength.ADVISORY,
        propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
        propagation_action=PropagationAction.MARK_DIRTY,
        rule_ref="RULE-TAG",
    )
    request = _request(edges=(*_edges(), nested))
    request = ImpactAnalysisRequest(
        bound_operation=request.bound_operation,
        planning_snapshot_ref=request.planning_snapshot_ref,
        snapshot_set_ref=request.snapshot_set_ref,
        semantic_environment_ref=request.semantic_environment_ref,
        dependency_edges=request.dependency_edges,
        relationship_evidence=request.relationship_evidence,
        intent_boundary=IntentBoundary(
            direct_targets=("WALL-001",),
            allowed_canonical_effects=("PLACEMENT", "GEOMETRY"),
            allowed_derived_rule_refs=("RULE-ANN", "RULE-MEP", "RULE-OPENING", "RULE-TAG"),
        ),
    )

    result = ImpactAnalyzer().analyze(request)

    assert "TAG-010" in {item.affected_semantic_id for item in result.predicted_impacts}


def test_edge_order_does_not_change_output_order_or_fingerprint() -> None:
    forward = ImpactAnalyzer().analyze(_request(edges=_edges()))
    reverse = ImpactAnalyzer().analyze(_request(edges=tuple(reversed(_edges()))))

    assert forward.predicted_impacts == reverse.predicted_impacts
    assert forward.analysis_fingerprint == reverse.analysis_fingerprint
    assert forward.analysis_id == reverse.analysis_id


def test_analyzer_does_not_mutate_bound_operation_arguments() -> None:
    bound = _bound_move()
    before = deepcopy(dict(bound.arguments))

    ImpactAnalyzer().analyze(_request(edges=_edges(), bound=bound))

    assert dict(bound.arguments) == before


def test_duplicate_dependency_ids_fail_closed() -> None:
    duplicate = DependencyEdge(
        dependency_id="DEP-OPENING",
        source_semantic_id="WALL-001",
        target_semantic_id="OTHER-001",
        strength=DependencyStrength.SOFT,
        propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
        propagation_action=PropagationAction.RECOMPUTE,
        rule_ref="RULE-OTHER",
    )

    with pytest.raises(ImpactError) as exc:
        ImpactAnalyzer().analyze(_request(edges=(*_edges(), duplicate)))

    assert exc.value.code == "DEPENDENCY_INVALID"


def test_snapshot_must_be_member_of_snapshot_set() -> None:
    environment, planning, _ = _bindings()
    snapshot_set = SnapshotSetBinding("PSS-1", "pss-hash", ("PS-OTHER",), environment)

    with pytest.raises(ImpactError) as exc:
        ImpactAnalyzer().analyze(
            _request(
                environment=environment,
                planning=planning,
                snapshot_set=snapshot_set,
            )
        )

    assert exc.value.code == "SNAPSHOT_MISMATCH"


def test_semantic_environment_must_match_all_planning_refs() -> None:
    request_environment = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning_environment = SemanticEnvironmentBinding("ENV-1", "other-hash")
    planning = PlanningSnapshotBinding("PS-1", "ps-hash", "DOC-1", planning_environment)
    snapshot_set = SnapshotSetBinding("PSS-1", "pss-hash", ("PS-1",), request_environment)

    with pytest.raises(ImpactError) as exc:
        ImpactAnalyzer().analyze(
            _request(
                environment=request_environment,
                planning=planning,
                snapshot_set=snapshot_set,
            )
        )

    assert exc.value.code == "SEMANTIC_ENVIRONMENT_MISMATCH"


def test_intent_boundary_direct_targets_must_match_bound_targets() -> None:
    environment, planning, snapshot_set = _bindings()
    request = ImpactAnalysisRequest(
        bound_operation=_bound_move(),
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        intent_boundary=IntentBoundary(direct_targets=("OTHER-001",)),
    )

    with pytest.raises(ImpactError) as exc:
        ImpactAnalyzer().analyze(request)

    assert exc.value.code == "IMPACT_INPUT_INVALID"
