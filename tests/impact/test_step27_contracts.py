from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from design_impact import (
    ConstraintEvaluationSpec,
    ConstraintOperator,
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


def test_frozen_dependency_vocabularies_reject_unknown_values() -> None:
    with pytest.raises(ValueError):
        DependencyStrength("CRITICAL")
    with pytest.raises(ValueError):
        PropagationOwner("PROVIDER")
    with pytest.raises(ValueError):
        PropagationAction("EXECUTE")
    with pytest.raises(ValueError):
        ConstraintStrength("MANDATORY")
    with pytest.raises(ValueError):
        ConstraintOperator("MATCHES")
    with pytest.raises(ValueError):
        ConstraintOutcome("UNKNOWN")


def test_relationship_is_not_dependency_type() -> None:
    relationship = RelationshipEvidence(
        relationship_id="REL-1",
        source_semantic_id="WALL-001",
        target_semantic_id="OPENING-001",
        relationship_type="HAS_OPENING",
    )
    assert not isinstance(relationship, DependencyEdge)


def test_dependency_contract_normalizes_immutable_evidence() -> None:
    source = ["METRO-RULE-1", "IFC-REL-1"]
    edge = DependencyEdge(
        dependency_id="DEP-1",
        source_semantic_id="WALL-001",
        target_semantic_id="OPENING-001",
        strength=DependencyStrength.HARD,
        propagation_owner=PropagationOwner.HOST_NATIVE,
        propagation_action=PropagationAction.REVALIDATE,
        rule_ref="RULE-OPENING",
        evidence_refs=source,
    )
    source.append("LATE-MUTATION")

    assert edge.evidence_refs == ("METRO-RULE-1", "IFC-REL-1")
    with pytest.raises(FrozenInstanceError):
        edge.dependency_id = "DEP-2"  # type: ignore[misc]


def test_snapshot_bindings_require_unique_member_ids_and_matching_types() -> None:
    environment = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding(
        snapshot_id="PS-1",
        snapshot_hash="ps-hash",
        document_ref="DOC-1",
        semantic_environment=environment,
    )
    snapshot_set = SnapshotSetBinding(
        snapshot_set_id="PSS-1",
        snapshot_set_hash="pss-hash",
        member_snapshot_ids=("PS-2", "PS-1"),
        semantic_environment=environment,
    )

    assert planning.semantic_environment == environment
    assert snapshot_set.member_snapshot_ids == ("PS-1", "PS-2")

    with pytest.raises(ValueError):
        SnapshotSetBinding(
            snapshot_set_id="PSS-1",
            snapshot_set_hash="pss-hash",
            member_snapshot_ids=("PS-1", "PS-1"),
            semantic_environment=environment,
        )


def test_intent_boundary_is_normalized_and_unique() -> None:
    boundary = IntentBoundary(
        direct_targets=("WALL-002", "WALL-001"),
        allowed_canonical_effects=("GEOMETRY", "PLACEMENT"),
        allowed_derived_rule_refs=("RULE-B", "RULE-A"),
    )

    assert boundary.direct_targets == ("WALL-001", "WALL-002")
    assert boundary.allowed_canonical_effects == ("GEOMETRY", "PLACEMENT")
    assert boundary.allowed_derived_rule_refs == ("RULE-A", "RULE-B")


def test_constraint_rule_uses_structured_evaluation_spec() -> None:
    rule = ConstraintRule(
        constraint_id="CON-1",
        applies_to=("OPENING-001",),
        strength=ConstraintStrength.HARD,
        evaluation_spec=ConstraintEvaluationSpec(
            fact_key="clear_width_mm",
            operator=ConstraintOperator.GE,
            expected_value=900,
        ),
        evidence_refs=("metro:IDS-1",),
    )

    assert rule.evaluation_spec.fact_key == "clear_width_mm"
    assert rule.evaluation_spec.operator is ConstraintOperator.GE
    assert rule.evidence_refs == ("metro:IDS-1",)


def test_propagation_bundle_defensively_copies_canonical_proposals() -> None:
    proposal = {
        "affected_semantic_id": "ANNOTATION-002",
        "action": "RECOMPUTE",
        "rule_ref": "RULE-ANN",
    }
    bundle = PropagationBundle(
        bundle_id="PB-1",
        rule_ref="RULE-ANN",
        strength=DependencyStrength.SOFT,
        propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
        propagation_action=PropagationAction.RECOMPUTE,
        source_entities=("WALL-001",),
        affected_entities=("ANNOTATION-002",),
        deterministic=True,
        proposed_changes=(proposal,),
    )
    proposal["action"] = "MUTATED"

    assert bundle.proposed_changes[0]["action"] == "RECOMPUTE"


def test_public_output_contract_is_provider_neutral() -> None:
    environment = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding("PS-1", "ps-hash", "DOC-1", environment)
    snapshot_set = SnapshotSetBinding("PSS-1", "pss-hash", ("PS-1",), environment)
    predicted = PredictedImpact(
        source_semantic_id="WALL-001",
        affected_semantic_id="OPENING-001",
        strength=DependencyStrength.HARD,
        propagation_owner=PropagationOwner.HOST_NATIVE,
        propagation_action=PropagationAction.REVALIDATE,
        dependency_ref="DEP-1",
        evidence_refs=(),
        requires_verification=True,
    )
    exception = ImpactException(
        exception_id="IX-1",
        reason_code="REPLAN_REQUIRED",
        source_entities=("WALL-001",),
        affected_entities=("MEP-008",),
        strength="SOFT",
        propagation_owner="AGENT",
        requested_action="REPLAN",
        blocking=False,
    )
    result = ImpactAnalysis(
        analysis_id="IA-123",
        canonical_operation="move.v1",
        direct_targets=("WALL-001",),
        planning_snapshot_ref=planning,
        snapshot_set_ref=snapshot_set,
        semantic_environment_ref=environment,
        predicted_impacts=(predicted,),
        propagation_bundles=(),
        exceptions=(exception,),
        analysis_fingerprint="fingerprint",
    )

    assert result.canonical_operation == "move.v1"
    assert not hasattr(result, "provider_tool")
    assert not hasattr(result, "host_command")
    assert not hasattr(result, "changeset_id")


def test_blank_ids_fail_closed() -> None:
    with pytest.raises(ValueError):
        RelationshipEvidence("", "WALL-001", "OPENING-001", "HAS_OPENING")
    with pytest.raises(ValueError):
        SemanticEnvironmentBinding("ENV-1", "")


def test_impact_error_carries_machine_readable_code() -> None:
    error = ImpactError("DEPENDENCY_INVALID", "duplicate dependency")
    assert error.code == "DEPENDENCY_INVALID"
    assert str(error) == "duplicate dependency"
