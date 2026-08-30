from __future__ import annotations

import pytest
from design_approval_scope import (
    ApprovalScopePlanner,
    ApprovalScopePlanRequest,
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
    ChangeSetBuilder,
    ChangeSetBuildRequest,
    DerivedOperationMaterialization,
    compute_bound_operation_evidence_fingerprint,
    compute_bound_operation_fingerprint,
    compute_contract_definition_fingerprint,
    compute_proposed_change_hash,
)
from design_execution_planning import (
    ExecutionPlanningRequest,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
    compute_routing_snapshot_hash,
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


def build_step30_transaction(selection: tuple[str, ...] = ("WALL-001",)):
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    bound = binder.bind(
        OperationProposal("move.v1", {"displacement": [100.0, 0.0, 0.0]}),
        ParameterBindingContext(
            context_snapshot_id="CS-STEP30",
            context_snapshot_hash="context-hash-step30",
            document_ref="DOC-1",
            semantic_environment_ref="ENV-1",
            selection=selection,
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
                    source_semantic_id=selection[0],
                    target_semantic_id="ANNOTATION-002",
                    strength=DependencyStrength.SOFT,
                    propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
                    propagation_action=PropagationAction.RECOMPUTE,
                    rule_ref="RULE-ANN",
                ),
            ),
            intent_boundary=IntentBoundary(
                direct_targets=selection,
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
    direct_rule_ids = tuple(direct_existing_rule_id(target) for target in selection)
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
                direct_targets=selection,
                allowed_canonical_effects=("PLACEMENT", "GEOMETRY"),
                allowed_derived_rule_refs=("RULE-ANN",),
            ),
            direct_entity_effects=tuple(
                DirectEntityEffect(
                    target,
                    (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
                )
                for target in selection
            ),
            scope_effect_recipes=(recipe,),
            execution_slice_scope_rules=(
                ExecutionSliceScopeRule(
                    "SLICE-SCOPE-1",
                    "DOC-1",
                    tuple(sorted((*direct_rule_ids, derived_rule_id))),
                ),
            ),
        )
    )
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
        task_id="TASK-30",
        bound_operation_evidence=bound_evidence,
        impact_analysis=impact,
        approval_scope_definition=scope,
        canonical_operation_contracts=(contract,),
        derived_materializations=(materialization,),
    )
    changeset = ChangeSetBuilder().build(request)
    boundary = bind_changeset(scope, changeset.changeset_hash, "SCOPE-30")
    return changeset, boundary


@pytest.fixture
def step30_transaction():
    return build_step30_transaction()


@pytest.fixture
def step30_multitarget_transaction():
    return build_step30_transaction(("WALL-001", "WALL-002"))


def routing_for_transaction(
    transaction,
    *,
    root_ref: HostRuntimeRef | None = None,
    derived_ref: HostRuntimeRef | None = None,
) -> RuntimeRoutingEvidence:
    changeset, _ = transaction
    root_ref = root_ref or HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    derived_ref = derived_ref or root_ref
    routes = [RuntimeEntityRoute(target, root_ref) for target in changeset.root_operation.targets]
    for operation in changeset.derived_operations:
        routes.extend(RuntimeEntityRoute(target, derived_ref) for target in operation.targets)
    route_tuple = tuple(routes)
    return RuntimeRoutingEvidence(
        "RRS-30",
        route_tuple,
        compute_routing_snapshot_hash(route_tuple),
    )


def valid_request(transaction, routing: RuntimeRoutingEvidence | None = None):
    changeset, boundary = transaction
    return ExecutionPlanningRequest(
        changeset,
        boundary,
        routing or routing_for_transaction(transaction),
    )
