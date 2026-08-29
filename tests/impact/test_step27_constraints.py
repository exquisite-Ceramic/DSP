from __future__ import annotations

import pytest

from design_impact import (
    ConstraintEvaluationSpec,
    ConstraintOperator,
    ConstraintOutcome,
    ConstraintRule,
    ConstraintStrength,
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
    evaluate_constraint,
)
from design_orchestrator.parameter_binder import (
    BoundOperationProposal,
    CanonicalOperationRef,
    ContextSnapshotRef,
    PlanningRequirements,
)


def _bound_move():
    return BoundOperationProposal(
        operation=CanonicalOperationRef("move.v1", "1.0.0"),
        arguments={"targets": ["WALL-001"], "displacement": [100.0, 0.0, 0.0]},
        binding_evidence={},
        context_snapshot_ref=ContextSnapshotRef("CS-1", "ctx-hash", "DOC-1"),
        planning_requirements=PlanningRequirements(),
        semantic_environment_ref="ENV-1",
    )


def _bindings():
    environment = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding("PS-1", "ps-hash", "DOC-1", environment)
    snapshot_set = SnapshotSetBinding("PSS-1", "pss-hash", ("PS-1",), environment)
    return environment, planning, snapshot_set


def _edge(
    *,
    dependency_id: str,
    target: str,
    strength=DependencyStrength.SOFT,
    owner=PropagationOwner.SEMANTIC_RUNTIME,
    action=PropagationAction.RECOMPUTE,
    rule_ref: str | None = None,
):
    return DependencyEdge(
        dependency_id=dependency_id,
        source_semantic_id="WALL-001",
        target_semantic_id=target,
        strength=strength,
        propagation_owner=owner,
        propagation_action=action,
        rule_ref=rule_ref,
    )


def _request(
    *,
    edges=(),
    rules=(),
    observed_facts=None,
    allowed_rules=(),
):
    environment, planning, snapshot_set = _bindings()
    return ImpactAnalysisRequest(
        bound_operation=_bound_move(),
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        dependency_edges=tuple(edges),
        constraint_rules=tuple(rules),
        observed_facts=observed_facts or {},
        intent_boundary=IntentBoundary(
            direct_targets=("WALL-001",),
            allowed_canonical_effects=("PLACEMENT", "GEOMETRY"),
            allowed_derived_rule_refs=tuple(allowed_rules),
        ),
    )


def _constraint(
    *,
    constraint_id="CON-1",
    entity="OPENING-001",
    strength=ConstraintStrength.HARD,
    fact_key="clear_width_mm",
    operator=ConstraintOperator.GE,
    expected=900,
):
    return ConstraintRule(
        constraint_id=constraint_id,
        applies_to=(entity,),
        strength=strength,
        evaluation_spec=ConstraintEvaluationSpec(
            fact_key=fact_key,
            operator=operator,
            expected_value=expected,
        ),
    )


@pytest.mark.parametrize(
    ("operator", "actual", "expected", "outcome"),
    [
        (ConstraintOperator.EQ, 5, 5, ConstraintOutcome.PASS),
        (ConstraintOperator.NE, 5, 4, ConstraintOutcome.PASS),
        (ConstraintOperator.GT, 5, 4, ConstraintOutcome.PASS),
        (ConstraintOperator.GE, 5, 5, ConstraintOutcome.PASS),
        (ConstraintOperator.LT, 4, 5, ConstraintOutcome.PASS),
        (ConstraintOperator.LE, 5, 5, ConstraintOutcome.PASS),
        (ConstraintOperator.IN, "A", ("A", "B"), ConstraintOutcome.PASS),
        (ConstraintOperator.GE, 4, 5, ConstraintOutcome.FAIL),
    ],
)
def test_structured_constraint_operators_are_deterministic(
    operator, actual, expected, outcome
) -> None:
    rule = _constraint(operator=operator, expected=expected, fact_key="value")
    result, entities = evaluate_constraint(
        rule,
        observed_facts={"OPENING-001": {"value": actual}},
    )

    assert result is outcome
    assert entities == ("OPENING-001",)


def test_constraint_is_not_applicable_when_no_rule_entity_is_present() -> None:
    result, entities = evaluate_constraint(
        _constraint(),
        observed_facts={"OTHER-001": {"clear_width_mm": 100}},
    )

    assert result is ConstraintOutcome.NOT_APPLICABLE
    assert entities == ()


def test_missing_required_fact_fails_closed() -> None:
    with pytest.raises(ImpactError) as exc:
        evaluate_constraint(
            _constraint(),
            observed_facts={"OPENING-001": {}},
        )

    assert exc.value.code == "CONSTRAINT_INVALID"


def test_invalid_ordered_comparison_fails_closed() -> None:
    with pytest.raises(ImpactError) as exc:
        evaluate_constraint(
            _constraint(operator=ConstraintOperator.GE, expected=900),
            observed_facts={"OPENING-001": {"clear_width_mm": "wide"}},
        )

    assert exc.value.code == "CONSTRAINT_INVALID"


def test_hard_constraint_failure_creates_blocking_exception() -> None:
    edge = _edge(
        dependency_id="DEP-OPENING",
        target="OPENING-001",
        owner=PropagationOwner.HOST_NATIVE,
        action=PropagationAction.REVALIDATE,
        rule_ref="RULE-OPENING",
    )
    result = ImpactAnalyzer().analyze(
        _request(
            edges=(edge,),
            rules=(_constraint(strength=ConstraintStrength.HARD),),
            observed_facts={"OPENING-001": {"clear_width_mm": 850}},
            allowed_rules=("RULE-OPENING",),
        )
    )

    assert any(
        item.reason_code == "HARD_CONSTRAINT_FAILED" and item.blocking
        for item in result.exceptions
    )


def test_soft_and_advisory_constraint_failures_are_non_blocking_exceptions() -> None:
    edge = _edge(
        dependency_id="DEP-OPENING",
        target="OPENING-001",
        owner=PropagationOwner.HOST_NATIVE,
        action=PropagationAction.REVALIDATE,
        rule_ref="RULE-OPENING",
    )
    soft = _constraint(constraint_id="CON-SOFT", strength=ConstraintStrength.SOFT)
    advisory = _constraint(
        constraint_id="CON-ADVISORY",
        strength=ConstraintStrength.ADVISORY,
    )
    result = ImpactAnalyzer().analyze(
        _request(
            edges=(edge,),
            rules=(soft, advisory),
            observed_facts={"OPENING-001": {"clear_width_mm": 850}},
            allowed_rules=("RULE-OPENING",),
        )
    )

    reasons = {item.reason_code: item for item in result.exceptions}
    assert reasons["CONSTRAINT_REVIEW_REQUIRED"].blocking is False
    assert reasons["ADVISORY_CONSTRAINT"].blocking is False


def test_semantic_runtime_recompute_edges_group_into_one_bundle() -> None:
    edges = (
        _edge(
            dependency_id="DEP-ANN-1",
            target="ANNOTATION-001",
            rule_ref="RULE-ANN",
        ),
        _edge(
            dependency_id="DEP-ANN-2",
            target="ANNOTATION-002",
            rule_ref="RULE-ANN",
        ),
    )
    result = ImpactAnalyzer().analyze(
        _request(edges=edges, allowed_rules=("RULE-ANN",))
    )

    assert len(result.propagation_bundles) == 1
    bundle = result.propagation_bundles[0]
    assert bundle.rule_ref == "RULE-ANN"
    assert bundle.affected_entities == ("ANNOTATION-001", "ANNOTATION-002")
    assert bundle.propagation_owner is PropagationOwner.SEMANTIC_RUNTIME
    assert bundle.propagation_action is PropagationAction.RECOMPUTE
    assert bundle.deterministic is True
    assert tuple(item["affected_semantic_id"] for item in bundle.proposed_changes) == (
        "ANNOTATION-001",
        "ANNOTATION-002",
    )


def test_auto_mutate_is_planning_only_canonical_bundle_metadata() -> None:
    edge = _edge(
        dependency_id="DEP-DERIVED",
        target="DERIVED-001",
        owner=PropagationOwner.SEMANTIC_RUNTIME,
        action=PropagationAction.AUTO_MUTATE,
        rule_ref="RULE-DERIVED",
    )
    result = ImpactAnalyzer().analyze(
        _request(edges=(edge,), allowed_rules=("RULE-DERIVED",))
    )

    bundle = result.propagation_bundles[0]
    proposal = dict(bundle.proposed_changes[0])
    assert proposal == {
        "affected_semantic_id": "DERIVED-001",
        "action": "AUTO_MUTATE",
        "rule_ref": "RULE-DERIVED",
    }
    assert "provider_tool" not in proposal
    assert "native_id" not in proposal


def test_host_native_dependency_does_not_create_platform_bundle() -> None:
    edge = _edge(
        dependency_id="DEP-OPENING",
        target="OPENING-001",
        strength=DependencyStrength.HARD,
        owner=PropagationOwner.HOST_NATIVE,
        action=PropagationAction.REVALIDATE,
        rule_ref="RULE-OPENING",
    )
    result = ImpactAnalyzer().analyze(
        _request(edges=(edge,), allowed_rules=("RULE-OPENING",))
    )

    assert result.predicted_impacts[0].requires_verification is True
    assert result.propagation_bundles == ()


def test_agent_or_replan_dependency_enters_exception_set() -> None:
    edge = _edge(
        dependency_id="DEP-MEP",
        target="MEP-008",
        owner=PropagationOwner.AGENT,
        action=PropagationAction.REPLAN,
        rule_ref="RULE-MEP",
    )
    result = ImpactAnalyzer().analyze(
        _request(edges=(edge,), allowed_rules=("RULE-MEP",))
    )

    assert result.propagation_bundles == ()
    assert any(item.reason_code == "REPLAN_REQUIRED" for item in result.exceptions)


def test_block_action_creates_blocking_exception() -> None:
    edge = _edge(
        dependency_id="DEP-BLOCK",
        target="SAFETY-001",
        strength=DependencyStrength.HARD,
        owner=PropagationOwner.SEMANTIC_RUNTIME,
        action=PropagationAction.BLOCK,
        rule_ref="RULE-SAFETY",
    )
    result = ImpactAnalyzer().analyze(
        _request(edges=(edge,), allowed_rules=("RULE-SAFETY",))
    )

    exception = next(item for item in result.exceptions if item.reason_code == "PROPAGATION_BLOCKED")
    assert exception.blocking is True
    assert result.propagation_bundles == ()


def test_unapproved_derived_rule_is_intent_scope_expansion() -> None:
    edge = _edge(
        dependency_id="DEP-ANN",
        target="ANNOTATION-002",
        rule_ref="RULE-ANN",
    )
    result = ImpactAnalyzer().analyze(_request(edges=(edge,), allowed_rules=()))

    assert result.propagation_bundles == ()
    assert any(
        item.reason_code == "INTENT_SCOPE_EXPANSION"
        and item.affected_entities == ("ANNOTATION-002",)
        for item in result.exceptions
    )


def test_bundle_identity_and_exception_identity_are_input_order_stable() -> None:
    edges = (
        _edge(dependency_id="DEP-A", target="ANN-A", rule_ref="RULE-ANN"),
        _edge(dependency_id="DEP-B", target="ANN-B", rule_ref="RULE-ANN"),
        _edge(
            dependency_id="DEP-MEP",
            target="MEP-008",
            owner=PropagationOwner.AGENT,
            action=PropagationAction.REPLAN,
            rule_ref="RULE-MEP",
        ),
    )
    forward = ImpactAnalyzer().analyze(
        _request(edges=edges, allowed_rules=("RULE-ANN", "RULE-MEP"))
    )
    reverse = ImpactAnalyzer().analyze(
        _request(edges=tuple(reversed(edges)), allowed_rules=("RULE-MEP", "RULE-ANN"))
    )

    assert forward.propagation_bundles == reverse.propagation_bundles
    assert forward.exceptions == reverse.exceptions
