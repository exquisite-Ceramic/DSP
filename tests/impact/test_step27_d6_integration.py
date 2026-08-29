from __future__ import annotations

import pytest

from design_impact import (
    DependencyEdge,
    DependencyStrength,
    ImpactAnalysisRequest,
    ImpactAnalyzer,
    ImpactError,
    IntentBoundary,
    PlanningSnapshotBinding,
    PropagationAction,
    PropagationOwner,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from design_orchestrator.canonical_operations import MVP_CANONICAL_OPERATIONS
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)


def _bound_move(
    *,
    displacement=(100.0, 0.0, 0.0),
    selection=("WALL-001",),
    semantic_environment_ref="ENV-1",
):
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    context = ParameterBindingContext(
        context_snapshot_id="CS-STEP27",
        context_snapshot_hash="context-hash-step27",
        document_ref="DOC-1",
        semantic_environment_ref=semantic_environment_ref,
        selection=selection,
        context_values={},
    )
    return binder.bind(
        OperationProposal("move.v1", {"displacement": list(displacement)}),
        context,
    )


def _edges():
    return (
        DependencyEdge(
            dependency_id="DEP-B",
            source_semantic_id="WALL-001",
            target_semantic_id="ANNOTATION-002",
            strength=DependencyStrength.SOFT,
            propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
            propagation_action=PropagationAction.RECOMPUTE,
            rule_ref="RULE-ANN",
        ),
        DependencyEdge(
            dependency_id="DEP-A",
            source_semantic_id="WALL-001",
            target_semantic_id="OPENING-001",
            strength=DependencyStrength.HARD,
            propagation_owner=PropagationOwner.HOST_NATIVE,
            propagation_action=PropagationAction.REVALIDATE,
            rule_ref="RULE-OPENING",
        ),
    )


def _request(
    *,
    bound=None,
    snapshot_hash="ps-hash",
    snapshot_set_hash="pss-hash",
    env_hash="env-hash",
    edges=None,
):
    bound = bound or _bound_move()
    environment = SemanticEnvironmentBinding("ENV-1", env_hash)
    planning = PlanningSnapshotBinding("PS-1", snapshot_hash, "DOC-1", environment)
    snapshot_set = SnapshotSetBinding(
        "PSS-1",
        snapshot_set_hash,
        ("PS-1",),
        environment,
    )
    targets = tuple(bound.arguments["targets"])
    return ImpactAnalysisRequest(
        bound_operation=bound,
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        dependency_edges=_edges() if edges is None else tuple(edges),
        intent_boundary=IntentBoundary(
            direct_targets=targets,
            allowed_canonical_effects=("PLACEMENT", "GEOMETRY"),
            allowed_derived_rule_refs=("RULE-ANN", "RULE-OPENING"),
        ),
    )


def test_real_step25_bound_operation_flows_into_step27() -> None:
    bound = _bound_move()
    result = ImpactAnalyzer().analyze(_request(bound=bound))

    assert bound.operation.canonical_operation == "move.v1"
    assert dict(bound.arguments) == {
        "targets": ["WALL-001"],
        "displacement": [100.0, 0.0, 0.0],
    }
    assert result.canonical_operation == "move.v1"
    assert result.direct_targets == ("WALL-001",)
    assert result.analysis_id == f"IA-{result.analysis_fingerprint[:12]}"


def test_dependency_input_order_does_not_change_analysis_fingerprint() -> None:
    forward = ImpactAnalyzer().analyze(_request(edges=_edges()))
    reverse = ImpactAnalyzer().analyze(_request(edges=tuple(reversed(_edges()))))

    assert forward.analysis_fingerprint == reverse.analysis_fingerprint


def test_unreachable_dependency_evidence_changes_analysis_fingerprint() -> None:
    baseline = ImpactAnalyzer().analyze(_request(edges=_edges()))
    unreachable = DependencyEdge(
        dependency_id="DEP-UNREACHABLE",
        source_semantic_id="UNRELATED-001",
        target_semantic_id="UNRELATED-002",
        strength=DependencyStrength.ADVISORY,
        propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
        propagation_action=PropagationAction.MARK_DIRTY,
        rule_ref="RULE-UNREACHABLE",
    )
    changed = ImpactAnalyzer().analyze(_request(edges=(*_edges(), unreachable)))

    assert changed.predicted_impacts == baseline.predicted_impacts
    assert changed.analysis_fingerprint != baseline.analysis_fingerprint


def test_material_displacement_changes_analysis_fingerprint() -> None:
    baseline = ImpactAnalyzer().analyze(_request(bound=_bound_move()))
    changed = ImpactAnalyzer().analyze(
        _request(bound=_bound_move(displacement=(101.0, 0.0, 0.0)))
    )

    assert baseline.analysis_fingerprint != changed.analysis_fingerprint


def test_direct_target_changes_analysis_fingerprint() -> None:
    baseline = ImpactAnalyzer().analyze(_request(bound=_bound_move()))
    changed_bound = _bound_move(selection=("WALL-002",))
    changed = ImpactAnalyzer().analyze(_request(bound=changed_bound, edges=()))

    assert baseline.analysis_fingerprint != changed.analysis_fingerprint
    assert changed.direct_targets == ("WALL-002",)


def test_planning_snapshot_hash_changes_analysis_fingerprint() -> None:
    baseline = ImpactAnalyzer().analyze(_request())
    changed = ImpactAnalyzer().analyze(_request(snapshot_hash="ps-hash-2"))

    assert baseline.analysis_fingerprint != changed.analysis_fingerprint


def test_snapshot_set_hash_changes_analysis_fingerprint() -> None:
    baseline = ImpactAnalyzer().analyze(_request())
    changed = ImpactAnalyzer().analyze(_request(snapshot_set_hash="pss-hash-2"))

    assert baseline.analysis_fingerprint != changed.analysis_fingerprint


def test_semantic_environment_hash_changes_analysis_fingerprint() -> None:
    baseline = ImpactAnalyzer().analyze(_request())
    changed = ImpactAnalyzer().analyze(_request(env_hash="env-hash-2"))

    assert baseline.analysis_fingerprint != changed.analysis_fingerprint


def test_d6_semantic_environment_must_match_impact_environment() -> None:
    bound = _bound_move(semantic_environment_ref="ENV-OTHER")

    with pytest.raises(ImpactError) as exc:
        ImpactAnalyzer().analyze(_request(bound=bound))

    assert exc.value.code == "SEMANTIC_ENVIRONMENT_MISMATCH"


def test_step27_output_has_no_execution_provider_metadata() -> None:
    result = ImpactAnalyzer().analyze(_request())

    assert not hasattr(result, "provider_tool")
    assert not hasattr(result, "native_id")
    assert not hasattr(result, "execution_grant")
    for bundle in result.propagation_bundles:
        for proposed in bundle.proposed_changes:
            assert "provider_tool" not in proposed
            assert "native_id" not in proposed
