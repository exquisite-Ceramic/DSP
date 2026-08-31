"""Public-API-only fixtures for Step37 cross-host Saga coordination."""

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
    canonical_hash,
    compute_bound_operation_evidence_fingerprint,
    compute_bound_operation_fingerprint,
    compute_contract_definition_fingerprint,
    compute_proposed_change_hash,
)
from design_execution_coordination import HostCommitted
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
    ActualChangeKind,
    ActualDelta,
    VerificationContractEvidence,
    VerificationEvidenceBundle,
    VerificationSubjectEvidence,
    compute_actual_change_hash,
    compute_actual_delta_hash,
    compute_verification_evidence_bundle_hash,
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
from design_orchestrator.canonical_operations import SlotBindingClass
from design_orchestrator.parameter_binder import (
    BoundOperationProposal,
    CanonicalOperationRef,
    ContextSnapshotRef,
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
from semantic_runtime import (
    Coverage,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotKind,
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
class Step37Transaction:
    canonical_changeset: CanonicalChangeSet
    approval_scope_boundary: ApprovalScopeBoundary
    execution_plan: ExecutionPlan


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


def _build_three_slice_transaction() -> Step37Transaction:
    bound = BoundOperationProposal(
        operation=CanonicalOperationRef("semantic.assertions.v1", "1.0.0"),
        arguments={
            "targets": ["WALL-001"],
            "assertions": {"properties.thickness": 300.0},
        },
        binding_evidence={
            "targets": SlotBindingEvidence(
                slot="targets",
                binding_class=SlotBindingClass.CONTEXT,
                source="Step37Fixture.selection",
                source_ref="CS-STEP37",
            ),
            "assertions": SlotBindingEvidence(
                slot="assertions",
                binding_class=SlotBindingClass.INTENT,
                source="Step37Fixture.intent",
            ),
        },
        context_snapshot_ref=ContextSnapshotRef(
            "CS-STEP37",
            "context-hash-step37",
            "DOC-STEP37",
        ),
        planning_requirements=PlanningRequirements(),
        semantic_environment_ref="ENV-STEP37",
    )
    environment = SemanticEnvironmentBinding("ENV-STEP37", "env-hash-step37")
    planning = PlanningSnapshotBinding(
        "PS-STEP37",
        "ps-hash-step37",
        "DOC-STEP37",
        environment,
    )
    snapshot_set = SnapshotSetBinding(
        "PSS-STEP37",
        "pss-hash-step37",
        (planning.snapshot_id,),
        environment,
    )
    edges = (
        DependencyEdge(
            dependency_id="DEP-STEP37-B",
            source_semantic_id="WALL-001",
            target_semantic_id="ANNOTATION-002",
            strength=DependencyStrength.SOFT,
            propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
            propagation_action=PropagationAction.RECOMPUTE,
            rule_ref="RULE-STEP37-B",
        ),
        DependencyEdge(
            dependency_id="DEP-STEP37-C",
            source_semantic_id="WALL-001",
            target_semantic_id="TAG-003",
            strength=DependencyStrength.SOFT,
            propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
            propagation_action=PropagationAction.RECOMPUTE,
            rule_ref="RULE-STEP37-C",
        ),
    )
    intent = IntentBoundary(
        direct_targets=("WALL-001",),
        allowed_canonical_effects=(CanonicalAspect.PROPERTIES.value,),
        allowed_derived_rule_refs=("RULE-STEP37-B", "RULE-STEP37-C"),
    )
    impact = ImpactAnalyzer().analyze(
        ImpactAnalysisRequest(
            bound_operation=bound,
            planning_snapshot_ref=planning,
            snapshot_set_ref=snapshot_set,
            semantic_environment_ref=environment,
            intent_boundary=intent,
            dependency_edges=edges,
        )
    )
    assert len(impact.propagation_bundles) == 2

    edge_by_rule = {edge.rule_ref: edge for edge in edges}
    recipes = []
    derived_rule_ids = []
    materializations = []
    for index, bundle in enumerate(impact.propagation_bundles, start=1):
        edge = edge_by_rule[bundle.rule_ref]
        target = bundle.affected_entities[0]
        recipe = ScopeEffectRecipe(
            recipe_id=f"REC-STEP37-{index}",
            dependency_ref=edge.dependency_id,
            allowed_aspects=(CanonicalAspect.PROPERTIES,),
            rule_ref=edge.rule_ref,
            propagation_bundle_id=bundle.bundle_id,
        )
        rule_id = recipe_existing_rule_id(recipe, target)
        recipes.append(recipe)
        derived_rule_ids.append(rule_id)
        materializations.append(
            DerivedOperationMaterialization(
                propagation_bundle_id=bundle.bundle_id,
                proposed_change_hash=compute_proposed_change_hash(
                    bundle.proposed_changes[0]
                ),
                canonical_operation="semantic.assertions.v1",
                canonical_operation_version="1.0.0",
                targets=(target,),
                arguments={
                    "targets": [target],
                    "assertions": {"properties.thickness": 300.0},
                },
                scope_rule_ids=(rule_id,),
            )
        )

    direct_rule_id = direct_existing_rule_id("WALL-001")
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
            scope_effect_recipes=tuple(recipes),
            execution_slice_scope_rules=(
                ExecutionSliceScopeRule(
                    "SLICE-SCOPE-STEP37",
                    "DOC-STEP37",
                    existing_rule_ids=(direct_rule_id, *derived_rule_ids),
                ),
            ),
        )
    )
    changeset = ChangeSetBuilder().build(
        ChangeSetBuildRequest(
            task_id="TASK-STEP37",
            bound_operation_evidence=_bound_evidence(bound),
            impact_analysis=impact,
            approval_scope_definition=scope,
            canonical_operation_contracts=(SEMANTIC_ASSERTIONS_V1,),
            derived_materializations=tuple(materializations),
        )
    )
    boundary = bind_changeset(scope, changeset.changeset_hash, "SCOPE-STEP37")
    routes = (
        RuntimeEntityRoute(
            "WALL-001",
            HostRuntimeRef("TEST_HOST", "HOST-STEP37-A", "DOC-STEP37"),
        ),
        RuntimeEntityRoute(
            "ANNOTATION-002",
            HostRuntimeRef("TEST_HOST", "HOST-STEP37-B", "DOC-STEP37"),
        ),
        RuntimeEntityRoute(
            "TAG-003",
            HostRuntimeRef("TEST_HOST", "HOST-STEP37-C", "DOC-STEP37"),
        ),
    )
    routing = RuntimeRoutingEvidence(
        "RRS-STEP37",
        routes,
        compute_routing_snapshot_hash(routes),
    )
    plan = ExecutionPlanner().plan(
        ExecutionPlanningRequest(changeset, boundary, routing)
    )
    assert len(plan.execution_slices) == 3
    return Step37Transaction(changeset, boundary, plan)


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
    bindings = []
    target_index = 0
    for unit in execution_slice.execution_units:
        native_targets = []
        for semantic_id in unit.targets:
            target_index += 1
            native_targets.append(
                _native_target(execution_slice, semantic_id, target_index)
            )
        draft = ProviderBinding(
            binding_id="PB-DRAFT",
            execution_unit_id=unit.execution_unit_id,
            execution_unit_hash=unit.execution_unit_hash,
            execution_slice_id=execution_slice.execution_slice_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            canonical_operation=unit.canonical_operation,
            provider_server="step37.fixture.provider",
            provider_tool="execute",
            provider_version="1.0.0",
            selected_candidate_fingerprint="c" * 64,
            host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
            document_ref=execution_slice.host_runtime_ref.document_ref,
            input_adapter_version="1.0.0",
            native_targets=tuple(native_targets),
            provider_arguments=dict(unit.arguments),
            provider_preconditions=(),
            native_binding_metadata={"fixture": "step37"},
            verification_contract=dict(_SEMANTIC_ASSERTIONS_VERIFICATION),
            rollback_contract={"type": "NONE"},
            binding_expires_at="2026-08-31T15:00:00Z",
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
        provider_execution_snapshot_id="PXS-STEP37",
        provider_execution_snapshot_hash="d" * 64,
        bindings=binding_tuple,
        binding_set_hash=binding_set_hash,
    )


def _build_authority_for_slice(
    transaction: Step37Transaction,
    execution_slice: ExecutionSlice,
) -> AdmittedExecutionAuthority:
    changeset = transaction.canonical_changeset
    boundary = transaction.approval_scope_boundary
    binding_set = _build_binding_set(execution_slice)
    draft = ApprovalAdmission(
        admission_id=f"ADM-{execution_slice.execution_slice_id}",
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        semantic_environment_ref=changeset.semantic_environment_ref,
        approver="user:step37-fixture",
        policy_snapshot_hash="e" * 64,
        policy_allowed_operations=("semantic.assertions.v1",),
        approved_at="2026-08-31T12:00:00Z",
        expires_at="2026-08-31T15:00:00Z",
        admission_fingerprint="0" * 64,
    )
    admission = replace(
        draft,
        admission_fingerprint=compute_admission_fingerprint(draft),
    )
    service = GatewayAuthorizationService(InMemoryGatewayAuthorizationStore())
    approval = service.consume_approval(
        ApprovalConsumptionRequest(
            admission=admission,
            canonical_changeset=changeset,
            approval_scope_boundary=boundary,
            consumed_at="2026-08-31T12:05:00Z",
        )
    )
    grant = service.issue_execution_grant(
        ExecutionGrantRequest(
            approval_id=approval.approval_id,
            execution_slice=execution_slice,
            provider_binding_set=binding_set,
            issued_at="2026-08-31T12:10:00Z",
        )
    )
    return service.admit_execution_grant(
        grant.grant_hash,
        "2026-08-31T12:15:00Z",
    )


def _signed_change(
    *,
    semantic_id: str,
    aspect: CanonicalAspect = CanonicalAspect.PROPERTIES,
) -> ActualChange:
    draft = ActualChange(
        change_kind=ActualChangeKind.MODIFY,
        actual_change_hash="0" * 64,
        semantic_id=semantic_id,
        changed_aspects=(aspect,),
    )
    return replace(
        draft,
        actual_change_hash=compute_actual_change_hash(draft),
    )


def _build_delta_for_slice(
    execution_slice: ExecutionSlice,
    authority: AdmittedExecutionAuthority,
    *,
    aspect: CanonicalAspect = CanonicalAspect.PROPERTIES,
) -> ActualDelta:
    changes = tuple(
        _signed_change(semantic_id=semantic_id, aspect=aspect)
        for unit in execution_slice.execution_units
        for semantic_id in unit.targets
    )
    draft = ActualDelta(
        actual_delta_id=f"AD-STEP37-{authority.host_instance_id}",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=authority.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=10,
        revision_after=11,
        changes=changes,
        actual_delta_hash="0" * 64,
    )
    return replace(
        draft,
        actual_delta_hash=compute_actual_delta_hash(draft),
    )


def _build_verification_bundle(
    *,
    execution_slice: ExecutionSlice,
    actual_delta: ActualDelta,
    canonical_changeset: CanonicalChangeSet,
    property_value: float = 300.0,
) -> VerificationEvidenceBundle:
    target = execution_slice.execution_units[0].targets[0]
    environment = SemanticEnvironmentRef(
        canonical_changeset.semantic_environment_ref.environment_id,
        canonical_changeset.semantic_environment_ref.content_hash,
    )
    projection = SemanticProjectionRef(
        projection_id=f"PROJ-STEP37-{actual_delta.actual_delta_hash[:12]}",
        projection_hash=canonical_hash(
            {"step37": "projection", "delta": actual_delta.actual_delta_hash}
        ),
        semantic_model_version="step37-test",
        provider_set_hash=canonical_hash({"step37": "providers"}),
        mapping_profile_set_hash=canonical_hash({"step37": "mappings"}),
        normalized_fact_batch_hash=canonical_hash(
            {"step37": "facts", "delta": actual_delta.actual_delta_hash}
        ),
    )
    snapshot = SemanticSnapshot(
        snapshot_id=f"PS-STEP37-{actual_delta.actual_delta_hash[:12]}",
        kind=SnapshotKind.PLANNING,
        project_id=canonical_changeset.project_id,
        freshness_contract_id="FC-STEP37",
        freshness_contract_hash=canonical_hash({"step37": "freshness"}),
        document_ref=actual_delta.document_ref,
        base_host_revision=str(actual_delta.revision_after),
        coverage=Coverage(actual_delta.document_ref, (target,)),
        projection_ref=projection,
        semantic_environment_ref=environment,
        aspect_guarantees=(),
        hash=canonical_hash(
            {"step37": "snapshot", "delta": actual_delta.actual_delta_hash}
        ),
    )
    subject = VerificationSubjectEvidence(
        semantic_id=target,
        canonical_kind="ifc:IfcWall",
        properties={"thickness": property_value},
        placement=None,
        geometry_evidence=None,
        relationships=(),
        constraints=(),
        classification=("ifc:IfcWall",),
        evidence_aspects=(CanonicalAspect.PROPERTIES,),
        snapshot_id=snapshot.snapshot_id,
        snapshot_hash=snapshot.hash,
        projection_ref=projection,
    )
    draft = VerificationEvidenceBundle(
        evidence_bundle_id=f"VEB-STEP37-{actual_delta.actual_delta_hash[:12]}",
        changeset_hash=canonical_changeset.changeset_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        actual_delta_hash=actual_delta.actual_delta_hash,
        semantic_environment_ref=environment,
        post_execution_snapshot_ref=snapshot,
        post_execution_projection_ref=projection,
        base_host_revision=str(actual_delta.revision_after),
        baseline_snapshot_ref=None,
        baseline_projection_ref=None,
        contract_evidence=(
            VerificationContractEvidence(
                contract_ref=canonical_hash(_SEMANTIC_ASSERTIONS_VERIFICATION),
                contract_body=_SEMANTIC_ASSERTIONS_VERIFICATION,
            ),
        ),
        subject_evidence=(subject,),
        baseline_subject_evidence=(),
        evidence_bundle_hash="0" * 64,
    )
    return replace(
        draft,
        evidence_bundle_hash=compute_verification_evidence_bundle_hash(draft),
    )


@dataclass
class FixedClock:
    value: str = "2026-08-31T12:20:00Z"
    calls: int = 0

    def now(self) -> str:
        self.calls += 1
        return self.value


class DeterministicAuthorityPort:
    def __init__(self, outcomes):
        self.outcomes = dict(outcomes)
        self.calls = []

    def admit(self, execution_slice):
        self.calls.append(execution_slice.execution_slice_hash)
        return self.outcomes[execution_slice.execution_slice_hash]


class DeterministicHostPort:
    def __init__(self, outcomes):
        self.outcomes = dict(outcomes)
        self.calls = []

    def execute(self, execution_slice, authority):
        self.calls.append(
            (execution_slice.execution_slice_hash, authority.host_instance_id)
        )
        return self.outcomes[execution_slice.execution_slice_hash]


class DeterministicHostRegistry:
    def __init__(self, ports):
        self.ports = dict(ports)
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        return self.ports[runtime_ref]


class DeterministicEvidencePort:
    def __init__(self, property_values=None):
        self.property_values = dict(property_values or {})
        self.calls = []

    def build_bundle(
        self,
        *,
        execution_slice,
        actual_delta,
        canonical_changeset,
        approval_scope_boundary,
    ):
        self.calls.append(execution_slice.execution_slice_hash)
        assert approval_scope_boundary.scope_hash == actual_delta.approved_scope_hash
        return _build_verification_bundle(
            execution_slice=execution_slice,
            actual_delta=actual_delta,
            canonical_changeset=canonical_changeset,
            property_value=self.property_values.get(
                execution_slice.execution_slice_hash,
                300.0,
            ),
        )


@pytest.fixture
def step37_three_slice_transaction() -> Step37Transaction:
    return _build_three_slice_transaction()


@pytest.fixture
def build_authority_for_slice():
    return _build_authority_for_slice


@pytest.fixture
def build_delta_for_slice():
    return _build_delta_for_slice


@pytest.fixture
def build_verification_bundle():
    return _build_verification_bundle


@pytest.fixture
def build_success_host_outcome(build_delta_for_slice):
    def build(execution_slice, authority):
        return HostCommitted(
            actual_delta=build_delta_for_slice(execution_slice, authority),
            committed_at="2026-08-31T12:25:00Z",
        )

    return build
