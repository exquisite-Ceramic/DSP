"""Public-API-only Step33 reconciliation fixtures."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from design_approval_scope import (
    ApprovalScopeBoundary,
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
    CanonicalChangeSet,
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
    ExecutionPlan,
    ExecutionPlanner,
    ExecutionPlanningRequest,
    ExecutionSlice,
    HostRuntimeRef,
    RuntimeEntityRoute,
    RuntimeRoutingEvidence,
    compute_routing_snapshot_hash,
)
from design_execution_reconciliation import (
    ActualChange,
    ActualDelta,
    compute_actual_change_hash,
    compute_actual_delta_hash,
)
from design_gateway_authorization import (
    AdmittedExecutionAuthority,
    ApprovalAdmission,
    ApprovalConsumptionRequest,
    ExecutionGrantRequest,
    GatewayAuthorizationService,
    InMemoryGatewayAuthorizationStore,
    compute_admission_fingerprint,
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
from design_orchestrator.canonical_operations import (
    MOVE_V1,
    MVP_CANONICAL_OPERATIONS,
    SlotBindingClass,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    BoundOperationProposal,
    CanonicalOperationRef,
    ContextSnapshotRef,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
    PlanningRequirements,
    SlotBindingEvidence,
)
from design_provider_binding import (
    NativeTargetBindingEvidence,
    ProviderBinding,
    ProviderBindingSet,
    compute_binding_hash,
    compute_binding_set_hash,
    compute_host_binding_fingerprint,
)

_SEMANTIC_ASSERTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "targets": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "assertions": {"type": "object"},
    },
    "required": ["targets", "assertions"],
    "additionalProperties": False,
}
_SEMANTIC_ASSERTIONS_EFFECTS = (CanonicalAspect.PROPERTIES,)
_SEMANTIC_ASSERTIONS_VERIFICATION = {
    "type": "SEMANTIC_ASSERTIONS_V1",
    "version": "1.0.0",
    "assertions": [
        {
            "subjects": {"from_argument": "targets"},
            "path": "properties.thickness",
            "operator": "EQUALS_LITERAL",
            "value": 300.0,
        }
    ],
}
_SEMANTIC_ASSERTIONS_FINGERPRINT = compute_contract_definition_fingerprint(
    canonical_operation="semantic.assertions.v1",
    canonical_operation_version="1.0.0",
    argument_schema=_SEMANTIC_ASSERTIONS_SCHEMA,
    effects=_SEMANTIC_ASSERTIONS_EFFECTS,
    verification_contract=_SEMANTIC_ASSERTIONS_VERIFICATION,
)
SEMANTIC_ASSERTIONS_V1 = CanonicalOperationContractEvidence(
    canonical_operation="semantic.assertions.v1",
    canonical_operation_version="1.0.0",
    argument_schema=_SEMANTIC_ASSERTIONS_SCHEMA,
    effects=_SEMANTIC_ASSERTIONS_EFFECTS,
    verification_contract=_SEMANTIC_ASSERTIONS_VERIFICATION,
    definition_fingerprint=_SEMANTIC_ASSERTIONS_FINGERPRINT,
)


@dataclass(frozen=True, slots=True)
class Step33Transaction:
    canonical_changeset: CanonicalChangeSet
    approval_scope_boundary: ApprovalScopeBoundary
    execution_plan: ExecutionPlan
    execution_slice: ExecutionSlice | None = None


def _bound_evidence(bound: BoundOperationProposal) -> BoundOperationEvidence:
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
    material_fingerprint = compute_bound_operation_fingerprint(
        bound.operation.canonical_operation,
        bound.operation.version,
        arguments,
    )
    evidence_fingerprint = compute_bound_operation_evidence_fingerprint(
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
        bound_operation_fingerprint=material_fingerprint,
        bound_operation_evidence_fingerprint=evidence_fingerprint,
    )


def _contract_from_definition(definition) -> CanonicalOperationContractEvidence:
    fingerprint = compute_contract_definition_fingerprint(
        canonical_operation=definition.canonical_operation,
        canonical_operation_version=definition.version,
        argument_schema=definition.input_schema,
        effects=definition.effects,
        verification_contract=definition.verification_contract,
    )
    return CanonicalOperationContractEvidence(
        canonical_operation=definition.canonical_operation,
        canonical_operation_version=definition.version,
        argument_schema=definition.input_schema,
        effects=definition.effects,
        verification_contract=definition.verification_contract,
        definition_fingerprint=fingerprint,
    )


def _single_bound_operation() -> BoundOperationProposal:
    return BoundOperationProposal(
        operation=CanonicalOperationRef("semantic.assertions.v1", "1.0.0"),
        arguments={
            "targets": ["WALL-001"],
            "assertions": {"properties.thickness": 300.0},
        },
        binding_evidence={
            "targets": SlotBindingEvidence(
                slot="targets",
                binding_class=SlotBindingClass.CONTEXT,
                source="Step33Fixture.selection",
                source_ref="CS-STEP33-SINGLE",
            ),
            "assertions": SlotBindingEvidence(
                slot="assertions",
                binding_class=SlotBindingClass.INTENT,
                source="Step33Fixture.intent",
            ),
        },
        context_snapshot_ref=ContextSnapshotRef(
            "CS-STEP33-SINGLE",
            "context-hash-step33-single",
            "DOC-1",
        ),
        planning_requirements=PlanningRequirements(),
        semantic_environment_ref="ENV-STEP33",
    )


def _build_single_slice_transaction() -> Step33Transaction:
    bound = _single_bound_operation()
    environment = SemanticEnvironmentBinding("ENV-STEP33", "env-hash-step33")
    planning = PlanningSnapshotBinding(
        "PS-STEP33-SINGLE",
        "ps-hash-step33-single",
        "DOC-1",
        environment,
    )
    snapshot_set = SnapshotSetBinding(
        "PSS-STEP33-SINGLE",
        "pss-hash-step33-single",
        (planning.snapshot_id,),
        environment,
    )
    intent = IntentBoundary(
        direct_targets=("WALL-001",),
        allowed_canonical_effects=(CanonicalAspect.PROPERTIES.value,),
    )
    impact = ImpactAnalyzer().analyze(
        ImpactAnalysisRequest(
            bound_operation=bound,
            planning_snapshot_ref=planning,
            snapshot_set_ref=snapshot_set,
            semantic_environment_ref=environment,
            intent_boundary=intent,
        )
    )
    rule_id = direct_existing_rule_id("WALL-001")
    scope = ApprovalScopePlanner().plan(
        ApprovalScopePlanRequest(
            canonical_effect_evidence=CanonicalEffectEvidence(
                "semantic.assertions.v1",
                "1.0.0",
                (CanonicalAspect.PROPERTIES,),
            ),
            impact_analysis=impact,
            intent_boundary=intent,
            direct_entity_effects=(
                DirectEntityEffect(
                    "WALL-001",
                    (CanonicalAspect.PROPERTIES,),
                ),
            ),
            execution_slice_scope_rules=(
                ExecutionSliceScopeRule(
                    "SLICE-SCOPE-STEP33-SINGLE",
                    "DOC-1",
                    existing_rule_ids=(rule_id,),
                ),
            ),
        )
    )
    changeset = ChangeSetBuilder().build(
        ChangeSetBuildRequest(
            task_id="TASK-STEP33-SINGLE",
            bound_operation_evidence=_bound_evidence(bound),
            impact_analysis=impact,
            approval_scope_definition=scope,
            canonical_operation_contracts=(SEMANTIC_ASSERTIONS_V1,),
        )
    )
    boundary = bind_changeset(scope, changeset.changeset_hash, "SCOPE-STEP33-SINGLE")
    runtime = HostRuntimeRef("TEST_HOST", "HOST-STEP33-A", "DOC-1")
    routes = (RuntimeEntityRoute("WALL-001", runtime),)
    routing = RuntimeRoutingEvidence(
        "RRS-STEP33-SINGLE",
        routes,
        compute_routing_snapshot_hash(routes),
    )
    plan = ExecutionPlanner().plan(
        ExecutionPlanningRequest(changeset, boundary, routing)
    )
    assert len(plan.execution_slices) == 1
    return Step33Transaction(
        canonical_changeset=changeset,
        approval_scope_boundary=boundary,
        execution_plan=plan,
        execution_slice=plan.execution_slices[0],
    )


def _build_move_two_slice_transaction() -> Step33Transaction:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    context = ParameterBindingContext(
        context_snapshot_id="CS-STEP33-SAGA",
        context_snapshot_hash="context-hash-step33-saga",
        document_ref="DOC-1",
        semantic_environment_ref="ENV-STEP33-SAGA",
        selection=("WALL-001",),
        context_values={},
    )
    bound = binder.bind(
        OperationProposal("move.v1", {"displacement": [100.0, 0.0, 0.0]}),
        context,
    )
    environment = SemanticEnvironmentBinding(
        "ENV-STEP33-SAGA",
        "env-hash-step33-saga",
    )
    planning = PlanningSnapshotBinding(
        "PS-STEP33-SAGA",
        "ps-hash-step33-saga",
        "DOC-1",
        environment,
    )
    snapshot_set = SnapshotSetBinding(
        "PSS-STEP33-SAGA",
        "pss-hash-step33-saga",
        (planning.snapshot_id,),
        environment,
    )
    edge = DependencyEdge(
        dependency_id="DEP-STEP33-ANN",
        source_semantic_id="WALL-001",
        target_semantic_id="ANNOTATION-002",
        strength=DependencyStrength.SOFT,
        propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
        propagation_action=PropagationAction.RECOMPUTE,
        rule_ref="RULE-STEP33-ANN",
    )
    intent = IntentBoundary(
        direct_targets=("WALL-001",),
        allowed_canonical_effects=(
            CanonicalAspect.PLACEMENT.value,
            CanonicalAspect.GEOMETRY.value,
        ),
        allowed_derived_rule_refs=("RULE-STEP33-ANN",),
    )
    impact = ImpactAnalyzer().analyze(
        ImpactAnalysisRequest(
            bound_operation=bound,
            planning_snapshot_ref=planning,
            snapshot_set_ref=snapshot_set,
            semantic_environment_ref=environment,
            dependency_edges=(edge,),
            intent_boundary=intent,
        )
    )
    bundle = impact.propagation_bundles[0]
    recipe = ScopeEffectRecipe(
        recipe_id="REC-STEP33-ANN",
        dependency_ref=edge.dependency_id,
        allowed_aspects=(CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
        rule_ref=edge.rule_ref,
        propagation_bundle_id=bundle.bundle_id,
    )
    direct_rule_id = direct_existing_rule_id("WALL-001")
    derived_rule_id = recipe_existing_rule_id(recipe, "ANNOTATION-002")
    scope = ApprovalScopePlanner().plan(
        ApprovalScopePlanRequest(
            canonical_effect_evidence=CanonicalEffectEvidence(
                MOVE_V1.canonical_operation,
                MOVE_V1.version,
                (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
            ),
            impact_analysis=impact,
            intent_boundary=intent,
            direct_entity_effects=(
                DirectEntityEffect(
                    "WALL-001",
                    (CanonicalAspect.PLACEMENT, CanonicalAspect.GEOMETRY),
                ),
            ),
            scope_effect_recipes=(recipe,),
            execution_slice_scope_rules=(
                ExecutionSliceScopeRule(
                    "SLICE-SCOPE-STEP33-SAGA",
                    "DOC-1",
                    existing_rule_ids=(direct_rule_id, derived_rule_id),
                ),
            ),
        )
    )
    materialization = DerivedOperationMaterialization(
        propagation_bundle_id=bundle.bundle_id,
        proposed_change_hash=compute_proposed_change_hash(bundle.proposed_changes[0]),
        canonical_operation=MOVE_V1.canonical_operation,
        canonical_operation_version=MOVE_V1.version,
        targets=("ANNOTATION-002",),
        arguments={
            "targets": ["ANNOTATION-002"],
            "displacement": [0.0, 0.0, 0.0],
        },
        scope_rule_ids=(derived_rule_id,),
    )
    changeset = ChangeSetBuilder().build(
        ChangeSetBuildRequest(
            task_id="TASK-STEP33-SAGA",
            bound_operation_evidence=_bound_evidence(bound),
            impact_analysis=impact,
            approval_scope_definition=scope,
            canonical_operation_contracts=(_contract_from_definition(MOVE_V1),),
            derived_materializations=(materialization,),
        )
    )
    boundary = bind_changeset(scope, changeset.changeset_hash, "SCOPE-STEP33-SAGA")
    runtime_a = HostRuntimeRef("TEST_HOST", "HOST-STEP33-A", "DOC-1")
    runtime_b = HostRuntimeRef("TEST_HOST", "HOST-STEP33-B", "DOC-1")
    routes = (
        RuntimeEntityRoute("WALL-001", runtime_a),
        RuntimeEntityRoute("ANNOTATION-002", runtime_b),
    )
    routing = RuntimeRoutingEvidence(
        "RRS-STEP33-SAGA",
        routes,
        compute_routing_snapshot_hash(routes),
    )
    plan = ExecutionPlanner().plan(
        ExecutionPlanningRequest(changeset, boundary, routing)
    )
    assert len(plan.execution_slices) == 2
    return Step33Transaction(
        canonical_changeset=changeset,
        approval_scope_boundary=boundary,
        execution_plan=plan,
    )


def _native_target(
    execution_slice: ExecutionSlice,
    semantic_id: str,
    index: int,
) -> NativeTargetBindingEvidence:
    draft = NativeTargetBindingEvidence(
        semantic_id=semantic_id,
        host_type=execution_slice.host_runtime_ref.host_type,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        native_id=f"NATIVE-{index:02d}-{semantic_id}",
        native_kind="TEST_ENTITY",
        host_binding_fingerprint="0" * 64,
    )
    return replace(
        draft,
        host_binding_fingerprint=compute_host_binding_fingerprint(draft),
    )


def _build_binding_set(execution_slice: ExecutionSlice) -> ProviderBindingSet:
    bindings: list[ProviderBinding] = []
    target_index = 0
    for unit in execution_slice.execution_units:
        native_targets = []
        for semantic_id in unit.targets:
            target_index += 1
            native_targets.append(_native_target(execution_slice, semantic_id, target_index))
        draft = ProviderBinding(
            binding_id="PB-DRAFT",
            execution_unit_id=unit.execution_unit_id,
            execution_unit_hash=unit.execution_unit_hash,
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            canonical_operation=unit.canonical_operation,
            provider_server="step33.fixture.provider",
            provider_tool="execute",
            provider_version="1.0.0",
            selected_candidate_fingerprint="c" * 64,
            host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
            document_ref=execution_slice.host_runtime_ref.document_ref,
            input_adapter_version="1.0.0",
            native_targets=tuple(native_targets),
            provider_arguments=dict(unit.arguments),
            provider_preconditions=(),
            native_binding_metadata={"fixture": "step33"},
            verification_contract=dict(_SEMANTIC_ASSERTIONS_VERIFICATION),
            rollback_contract={"type": "NONE"},
            binding_expires_at="2026-08-30T09:00:00Z",
            binding_hash="0" * 64,
        )
        binding_hash = compute_binding_hash(
            execution_unit_hash=draft.execution_unit_hash,
            execution_slice_hash=draft.execution_slice_hash,
            canonical_operation=draft.canonical_operation,
            provider_server=draft.provider_server,
            provider_tool=draft.provider_tool,
            provider_version=draft.provider_version,
            selected_candidate_fingerprint=draft.selected_candidate_fingerprint,
            host_instance_id=draft.host_instance_id,
            document_ref=draft.document_ref,
            input_adapter_version=draft.input_adapter_version,
            native_targets=draft.native_targets,
            provider_arguments=draft.provider_arguments,
            provider_preconditions=draft.provider_preconditions,
            native_binding_metadata=draft.native_binding_metadata,
            verification_contract=draft.verification_contract,
            rollback_contract=draft.rollback_contract,
            binding_expires_at=draft.binding_expires_at,
        )
        bindings.append(
            replace(
                draft,
                binding_id=f"PB-{binding_hash[:12]}",
                binding_hash=binding_hash,
            )
        )
    binding_tuple = tuple(bindings)
    binding_set_hash = compute_binding_set_hash(
        execution_slice_hash=execution_slice.execution_slice_hash,
        binding_hashes=(binding.binding_hash for binding in binding_tuple),
    )
    return ProviderBindingSet(
        binding_set_id=f"PBS-{binding_set_hash[:12]}",
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        provider_execution_snapshot_id="PXS-STEP33-FIXTURE",
        provider_execution_snapshot_hash="d" * 64,
        bindings=binding_tuple,
        binding_set_hash=binding_set_hash,
    )


def _admit_authority(
    transaction: Step33Transaction,
    binding_set: ProviderBindingSet,
) -> AdmittedExecutionAuthority:
    execution_slice = transaction.execution_slice
    assert execution_slice is not None
    changeset = transaction.canonical_changeset
    boundary = transaction.approval_scope_boundary
    draft = ApprovalAdmission(
        admission_id="ADM-STEP33-FIXTURE",
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        semantic_environment_ref=changeset.semantic_environment_ref,
        approver="user:step33-fixture",
        policy_snapshot_hash="e" * 64,
        policy_allowed_operations=(changeset.root_operation.canonical_operation,),
        approved_at="2026-08-30T07:00:00Z",
        expires_at="2026-08-30T09:00:00Z",
        admission_fingerprint="0" * 64,
    )
    admission = replace(
        draft,
        admission_fingerprint=compute_admission_fingerprint(draft),
    )
    store = InMemoryGatewayAuthorizationStore()
    service = GatewayAuthorizationService(store)
    approval = service.consume_approval(
        ApprovalConsumptionRequest(
            admission=admission,
            canonical_changeset=changeset,
            approval_scope_boundary=boundary,
            consumed_at="2026-08-30T07:30:00Z",
        )
    )
    grant = service.issue_execution_grant(
        ExecutionGrantRequest(
            approval_id=approval.approval_id,
            execution_slice=execution_slice,
            provider_binding_set=binding_set,
            issued_at="2026-08-30T07:40:00Z",
        )
    )
    return service.admit_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:45:00Z",
    )


@pytest.fixture
def step33_single_slice_transaction() -> Step33Transaction:
    return _build_single_slice_transaction()


@pytest.fixture
def step33_two_slice_transaction() -> Step33Transaction:
    return _build_move_two_slice_transaction()


@pytest.fixture
def step33_binding_set(
    step33_single_slice_transaction: Step33Transaction,
) -> ProviderBindingSet:
    execution_slice = step33_single_slice_transaction.execution_slice
    assert execution_slice is not None
    return _build_binding_set(execution_slice)


@pytest.fixture
def step33_admitted_authority(
    step33_single_slice_transaction: Step33Transaction,
    step33_binding_set: ProviderBindingSet,
) -> AdmittedExecutionAuthority:
    return _admit_authority(step33_single_slice_transaction, step33_binding_set)


@pytest.fixture
def step33_signed_actual_change():
    def build(**values) -> ActualChange:
        draft = ActualChange(actual_change_hash="0" * 64, **values)
        return replace(
            draft,
            actual_change_hash=compute_actual_change_hash(draft),
        )

    return build


@pytest.fixture
def step33_signed_actual_delta(
    step33_single_slice_transaction: Step33Transaction,
    step33_admitted_authority: AdmittedExecutionAuthority,
):
    def build(*changes: ActualChange, **overrides) -> ActualDelta:
        execution_slice = step33_single_slice_transaction.execution_slice
        assert execution_slice is not None
        values = {
            "actual_delta_id": "AD-STEP33-FIXTURE",
            "grant_hash": step33_admitted_authority.grant_hash,
            "binding_set_hash": step33_admitted_authority.binding_set_hash,
            "execution_slice_hash": step33_admitted_authority.execution_slice_hash,
            "changeset_hash": step33_admitted_authority.changeset_hash,
            "approved_scope_hash": step33_admitted_authority.approved_scope_hash,
            "host_instance_id": step33_admitted_authority.host_instance_id,
            "document_ref": execution_slice.host_runtime_ref.document_ref,
            "revision_before": 10,
            "revision_after": 11,
            "changes": tuple(changes),
            "actual_delta_hash": "0" * 64,
        }
        values.update(overrides)
        draft = ActualDelta(**values)
        return replace(
            draft,
            actual_delta_hash=compute_actual_delta_hash(draft),
        )

    return build
