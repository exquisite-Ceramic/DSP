from __future__ import annotations

from dataclasses import replace

import pytest
from design_approval_scope import (
    ApprovalScopePlanner,
    ApprovalScopePlanRequest,
    CanonicalAspect,
    CanonicalEffectEvidence,
    DirectEntityEffect,
    ExecutionSliceScopeRule,
    ScopeEffectRecipe,
    direct_existing_rule_id,
    recipe_existing_rule_id,
)
from design_changeset import (
    BoundOperationEvidence,
    CanonicalOperationContractEvidence,
    ChangeSetBuilder,
    ChangeSetBuildRequest,
    ChangeSetError,
    DerivedOperationMaterialization,
    OperationOrigin,
    compute_bound_operation_evidence_fingerprint,
    compute_bound_operation_fingerprint,
    compute_contract_definition_fingerprint,
    compute_proposed_change_hash,
)
from design_impact import (
    DependencyEdge,
    DependencyStrength,
    ImpactAnalysisRequest,
    ImpactAnalyzer,
    IntentBoundary,
    PlanningSnapshotBinding,
    PropagationAction,
    PropagationOwner,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from design_orchestrator.canonical_operations import MOVE_V1, MVP_CANONICAL_OPERATIONS
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)


def _bound_move():
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    context = ParameterBindingContext(
        context_snapshot_id="CS-STEP29-DERIVED",
        context_snapshot_hash="context-hash-step29-derived",
        document_ref="DOC-1",
        semantic_environment_ref="ENV-1",
        selection=("WALL-001",),
        context_values={},
    )
    return binder.bind(
        OperationProposal("move.v1", {"displacement": [100.0, 0.0, 0.0]}),
        context,
    )


def _parts():
    bound = _bound_move()
    environment = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding("PS-1", "ps-hash", "DOC-1", environment)
    snapshot_set = SnapshotSetBinding("PSS-1", "pss-hash", ("PS-1",), environment)
    edge = DependencyEdge(
        dependency_id="DEP-ANN",
        source_semantic_id="WALL-001",
        target_semantic_id="ANNOTATION-002",
        strength=DependencyStrength.SOFT,
        propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
        propagation_action=PropagationAction.RECOMPUTE,
        rule_ref="RULE-ANN",
    )
    impact = ImpactAnalyzer().analyze(
        ImpactAnalysisRequest(
            bound_operation=bound,
            planning_snapshot_ref=planning,
            snapshot_set_ref=snapshot_set,
            semantic_environment_ref=environment,
            dependency_edges=(edge,),
            intent_boundary=IntentBoundary(
                direct_targets=("WALL-001",),
                allowed_canonical_effects=("PLACEMENT", "GEOMETRY"),
                allowed_derived_rule_refs=("RULE-ANN",),
            ),
        )
    )
    bundle = impact.propagation_bundles[0]
    recipe = ScopeEffectRecipe(
        recipe_id="REC-ANN",
        dependency_ref="DEP-ANN",
        allowed_aspects=(CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
        rule_ref="RULE-ANN",
        propagation_bundle_id=bundle.bundle_id,
    )
    direct_rule_id = direct_existing_rule_id("WALL-001")
    derived_rule_id = recipe_existing_rule_id(recipe, "ANNOTATION-002")
    scope = ApprovalScopePlanner().plan(
        ApprovalScopePlanRequest(
            canonical_effect_evidence=CanonicalEffectEvidence(
                "move.v1",
                "1.0.0",
                (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
            ),
            impact_analysis=impact,
            intent_boundary=IntentBoundary(
                direct_targets=("WALL-001",),
                allowed_canonical_effects=("PLACEMENT", "GEOMETRY"),
                allowed_derived_rule_refs=("RULE-ANN",),
            ),
            direct_entity_effects=(
                DirectEntityEffect(
                    "WALL-001",
                    (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
                ),
            ),
            scope_effect_recipes=(recipe,),
            execution_slice_scope_rules=(
                ExecutionSliceScopeRule(
                    "SLICE-SCOPE-1",
                    "DOC-1",
                    (direct_rule_id, derived_rule_id),
                ),
            ),
        )
    )
    return bound, impact, scope, bundle, derived_rule_id


def _contract() -> CanonicalOperationContractEvidence:
    fingerprint = compute_contract_definition_fingerprint(
        canonical_operation=MOVE_V1.canonical_operation,
        canonical_operation_version=MOVE_V1.version,
        argument_schema=MOVE_V1.input_schema,
        effects=MOVE_V1.effects,
        verification_contract=MOVE_V1.verification_contract,
    )
    return CanonicalOperationContractEvidence(
        canonical_operation=MOVE_V1.canonical_operation,
        canonical_operation_version=MOVE_V1.version,
        argument_schema=MOVE_V1.input_schema,
        effects=MOVE_V1.effects,
        verification_contract=MOVE_V1.verification_contract,
        definition_fingerprint=fingerprint,
    )


def _bound_evidence(bound) -> BoundOperationEvidence:
    planning_requirements = {
        "operation_freshness_requirements": bound.planning_requirements.operation_freshness_requirements,
        "coverage_requirements": bound.planning_requirements.coverage_requirements,
        "assurance_requirements": bound.planning_requirements.assurance_requirements,
    }
    binding_evidence = {
        slot: {
            "binding_class": evidence.binding_class.value,
            "source": evidence.source,
            "source_ref": evidence.source_ref,
        }
        for slot, evidence in bound.binding_evidence.items()
    }
    arguments = dict(bound.arguments)
    material_fp = compute_bound_operation_fingerprint(
        bound.operation.canonical_operation,
        bound.operation.version,
        arguments,
    )
    evidence_fp = compute_bound_operation_evidence_fingerprint(
        canonical_operation=bound.operation.canonical_operation,
        canonical_operation_version=bound.operation.version,
        arguments=arguments,
        context_snapshot_id=bound.context_snapshot_ref.context_snapshot_id,
        context_snapshot_hash=bound.context_snapshot_ref.context_snapshot_hash,
        document_ref=bound.context_snapshot_ref.document_ref,
        semantic_environment_id=bound.semantic_environment_ref,
        planning_requirements=planning_requirements,
        binding_evidence=binding_evidence,
    )
    return BoundOperationEvidence(
        canonical_operation=bound.operation.canonical_operation,
        canonical_operation_version=bound.operation.version,
        arguments=arguments,
        context_snapshot_id=bound.context_snapshot_ref.context_snapshot_id,
        context_snapshot_hash=bound.context_snapshot_ref.context_snapshot_hash,
        document_ref=bound.context_snapshot_ref.document_ref,
        semantic_environment_id=bound.semantic_environment_ref,
        planning_requirements=planning_requirements,
        binding_evidence=binding_evidence,
        bound_operation_fingerprint=material_fp,
        bound_operation_evidence_fingerprint=evidence_fp,
    )


def _materialization(bundle, derived_rule_id) -> DerivedOperationMaterialization:
    proposal_hash = compute_proposed_change_hash(bundle.proposed_changes[0])
    return DerivedOperationMaterialization(
        propagation_bundle_id=bundle.bundle_id,
        proposed_change_hash=proposal_hash,
        canonical_operation="move.v1",
        canonical_operation_version="1.0.0",
        targets=("ANNOTATION-002",),
        arguments={
            "targets": ["ANNOTATION-002"],
            "displacement": [0.0, 0.0, 0.0],
        },
        scope_rule_ids=(derived_rule_id,),
    )


def _request(*, materializations=None) -> ChangeSetBuildRequest:
    bound, impact, scope, bundle, derived_rule_id = _parts()
    if materializations is None:
        materializations = (_materialization(bundle, derived_rule_id),)
    return ChangeSetBuildRequest(
        task_id="TASK-29-DERIVED",
        bound_operation_evidence=_bound_evidence(bound),
        impact_analysis=impact,
        approval_scope_definition=scope,
        canonical_operation_contracts=(_contract(),),
        derived_materializations=materializations,
    )


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ChangeSetError) as exc:
        operation()
    assert exc.value.code == code


def test_admitted_proposal_materializes_exactly_one_derived_operation_and_edge() -> None:
    result = ChangeSetBuilder().build(_request())

    assert len(result.derived_operations) == 1
    derived = result.derived_operations[0]
    assert derived.origin is OperationOrigin.DERIVED
    assert derived.targets == ("ANNOTATION-002",)
    assert derived.expected_effects == (
        CanonicalAspect.GEOMETRY,
        CanonicalAspect.PLACEMENT,
    )
    assert len(result.change_dependencies) == 1
    edge = result.change_dependencies[0]
    assert edge.predecessor_operation_id == result.root_operation.operation_id
    assert edge.successor_operation_id == derived.operation_id


def test_unknown_propagation_bundle_is_rejected_with_stable_code() -> None:
    request = _request()
    materialization = replace(
        request.derived_materializations[0],
        propagation_bundle_id="PB-UNKNOWN",
    )
    _assert_code(
        "CHANGESET_DERIVED_BUNDLE_UNKNOWN",
        lambda: ChangeSetBuilder().build(replace(request, derived_materializations=(materialization,))),
    )


def test_unknown_proposed_change_hash_is_rejected_with_stable_code() -> None:
    request = _request()
    materialization = replace(
        request.derived_materializations[0],
        proposed_change_hash="f" * 64,
    )
    _assert_code(
        "CHANGESET_DERIVED_PROPOSAL_UNKNOWN",
        lambda: ChangeSetBuilder().build(replace(request, derived_materializations=(materialization,))),
    )


def test_proposed_change_cannot_be_materialized_twice() -> None:
    request = _request()
    materialization = request.derived_materializations[0]
    _assert_code(
        "CHANGESET_DERIVED_PROPOSAL_DUPLICATE",
        lambda: ChangeSetBuilder().build(
            replace(request, derived_materializations=(materialization, materialization))
        ),
    )


def test_admitted_deterministic_proposal_cannot_be_silently_dropped() -> None:
    _assert_code(
        "CHANGESET_DERIVED_MATERIALIZATION_MISSING",
        lambda: ChangeSetBuilder().build(_request(materializations=())),
    )
