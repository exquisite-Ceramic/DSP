from __future__ import annotations

from design_approval_scope import (
    ApprovalScopePlanRequest,
    ApprovalScopePlanner,
    CanonicalAspect,
    CanonicalEffectEvidence,
    DirectEntityEffect,
    ExecutionSliceScopeRule,
    ScopeEffectRecipe,
    bind_changeset,
    direct_existing_rule_id,
    recipe_existing_rule_id,
)
from design_changeset import (
    BoundOperationEvidence,
    CanonicalOperationContractEvidence,
    ChangeSetBuildRequest,
    ChangeSetBuilder,
    DerivedOperationMaterialization,
    ValidationTaskKind,
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


def _request_and_scope():
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    bound = binder.bind(
        OperationProposal("move.v1", {"displacement": [100.0, 0.0, 0.0]}),
        ParameterBindingContext(
            context_snapshot_id="CS-STEP29-FINAL",
            context_snapshot_hash="context-hash-step29-final",
            document_ref="DOC-1",
            semantic_environment_ref="ENV-1",
            selection=("WALL-001",),
            context_values={},
        ),
    )
    environment = SemanticEnvironmentBinding("ENV-1", "env-hash")
    planning = PlanningSnapshotBinding("PS-1", "ps-hash", "DOC-1", environment)
    snapshot_set = SnapshotSetBinding("PSS-1", "pss-hash", ("PS-1",), environment)
    impact = ImpactAnalyzer().analyze(
        ImpactAnalysisRequest(
            bound_operation=bound,
            planning_snapshot_ref=planning,
            snapshot_set_ref=snapshot_set,
            semantic_environment_ref=environment,
            dependency_edges=(
                DependencyEdge(
                    dependency_id="DEP-ANN",
                    source_semantic_id="WALL-001",
                    target_semantic_id="ANNOTATION-002",
                    strength=DependencyStrength.SOFT,
                    propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
                    propagation_action=PropagationAction.RECOMPUTE,
                    rule_ref="RULE-ANN",
                ),
            ),
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

    planning_requirements = {
        "operation_freshness_requirements": (
            bound.planning_requirements.operation_freshness_requirements
        ),
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
    bound_evidence = BoundOperationEvidence(
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
    contract_fp = compute_contract_definition_fingerprint(
        canonical_operation=MOVE_V1.canonical_operation,
        canonical_operation_version=MOVE_V1.version,
        argument_schema=MOVE_V1.input_schema,
        effects=MOVE_V1.effects,
        verification_contract=MOVE_V1.verification_contract,
    )
    contract = CanonicalOperationContractEvidence(
        canonical_operation=MOVE_V1.canonical_operation,
        canonical_operation_version=MOVE_V1.version,
        argument_schema=MOVE_V1.input_schema,
        effects=MOVE_V1.effects,
        verification_contract=MOVE_V1.verification_contract,
        definition_fingerprint=contract_fp,
    )
    materialization = DerivedOperationMaterialization(
        propagation_bundle_id=bundle.bundle_id,
        proposed_change_hash=compute_proposed_change_hash(bundle.proposed_changes[0]),
        canonical_operation="move.v1",
        canonical_operation_version="1.0.0",
        targets=("ANNOTATION-002",),
        arguments={
            "targets": ["ANNOTATION-002"],
            "displacement": [0.0, 0.0, 0.0],
        },
        scope_rule_ids=(derived_rule_id,),
    )
    request = ChangeSetBuildRequest(
        task_id="TASK-29-FINAL",
        bound_operation_evidence=bound_evidence,
        impact_analysis=impact,
        approval_scope_definition=scope,
        canonical_operation_contracts=(contract,),
        derived_materializations=(materialization,),
    )
    return request, scope


def test_every_materialized_canonical_operation_gets_verification_obligation() -> None:
    request, _ = _request_and_scope()
    result = ChangeSetBuilder().build(request)
    canonical_tasks = tuple(
        task
        for task in result.validation_tasks
        if task.kind is ValidationTaskKind.CANONICAL_OPERATION
    )
    assert {task.subject_semantic_ids for task in canonical_tasks} == {
        ("WALL-001",),
        ("ANNOTATION-002",),
    }


def test_generated_changeset_hash_binds_through_existing_step28_binder() -> None:
    request, scope = _request_and_scope()
    result = ChangeSetBuilder().build(request)
    boundary = bind_changeset(scope, result.changeset_hash, "SCOPE-FINAL")

    assert boundary.changeset_hash == result.changeset_hash
    assert boundary.scope_body_hash == scope.scope_body_hash
    assert boundary.existing_entity_rules == scope.existing_entity_rules
    assert boundary.creation_rules == scope.creation_rules
    assert boundary.deletion_rules == scope.deletion_rules
    assert boundary.propagation_bundle_ids == scope.propagation_bundle_ids
