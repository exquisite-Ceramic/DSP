"""Offline Step36 proof that CREATE authority survives Steps 27 through 33."""

from __future__ import annotations

from dataclasses import dataclass, replace

import pytest
from design_approval_scope import (
    ApprovalScopeBoundary,
    ApprovalScopePlanner,
    ApprovalScopePlanRequest,
    CanonicalCreationContract,
    CanonicalEffectEvidence,
    CanonicalExistenceEffect,
    CreationRule,
    EntitySelector,
    ExecutionSliceScopeRule,
    bind_changeset,
    creation_rule_id,
)
from design_changeset import (
    BoundOperationEvidence,
    CanonicalChangeSet,
    CanonicalOperationContractEvidence,
    ChangeSetBuilder,
    ChangeSetBuildRequest,
    compute_bound_operation_evidence_fingerprint,
    compute_bound_operation_fingerprint,
    compute_contract_definition_fingerprint,
)
from design_execution_planning import (
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
    ScopeComparator,
    ScopeComparisonRequest,
    ScopeComparisonStatus,
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
    ImpactAnalysisRequest,
    ImpactAnalyzer,
    IntentBoundary,
    PlanningSnapshotBinding,
    SemanticEnvironmentBinding,
    SnapshotSetBinding,
)
from design_orchestrator.canonical_operations import OFFSET_V1
from design_orchestrator.parameter_binder import (
    OFFSET_V1_BINDING_RECIPE,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)
from design_provider_binding import (
    NativeTargetBindingEvidence,
    ProviderBinding,
    ProviderBindingSet,
    compute_binding_hash,
    compute_binding_set_hash,
    compute_host_binding_fingerprint,
)
from host_contracts import HostEntityRef


@dataclass(frozen=True, slots=True)
class Step36CreationAuthorityFixture:
    creation_rule: CreationRule
    canonical_changeset: CanonicalChangeSet
    approval_scope_boundary: ApprovalScopeBoundary
    execution_slice: ExecutionSlice
    provider_binding_set: ProviderBindingSet
    admitted_execution_authority: AdmittedExecutionAuthority


def _creation_contract() -> CanonicalCreationContract:
    return CanonicalCreationContract(
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )


def _intent_boundary() -> IntentBoundary:
    return IntentBoundary(
        direct_targets=("WALL-001",),
        allowed_canonical_effects=(),
        allowed_derived_rule_refs=(),
        allowed_existence_effects=(CanonicalExistenceEffect.CREATE.value,),
    )


def _bound_offset():
    binder = ParameterBinder((OFFSET_V1,), (OFFSET_V1_BINDING_RECIPE,))
    return binder.bind(
        OperationProposal(
            canonical_operation=OFFSET_V1.canonical_operation,
            intent_arguments={
                "distance": {"value": 300.0, "unit": "mm"},
                "side_point": {
                    "x": 5000.0,
                    "y": 2000.0,
                    "z": 0.0,
                    "unit": "mm",
                },
            },
        ),
        ParameterBindingContext(
            context_snapshot_id="CS-STEP36-OFFLINE",
            context_snapshot_hash="context-hash-step36-offline",
            document_ref="DOC-A",
            semantic_environment_ref="ENV-STEP36",
            selection=("WALL-001",),
        ),
    )


def _bound_evidence(bound) -> BoundOperationEvidence:
    requirements = bound.planning_requirements
    planning_requirements = {
        "operation_freshness_requirements": requirements.operation_freshness_requirements,
        "coverage_requirements": requirements.coverage_requirements,
        "assurance_requirements": requirements.assurance_requirements,
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


def _operation_contract() -> CanonicalOperationContractEvidence:
    creation_contract = _creation_contract()
    fingerprint = compute_contract_definition_fingerprint(
        canonical_operation=OFFSET_V1.canonical_operation,
        canonical_operation_version=OFFSET_V1.version,
        argument_schema=OFFSET_V1.input_schema,
        effects=OFFSET_V1.effects,
        verification_contract=OFFSET_V1.verification_contract,
        existence_effects=(CanonicalExistenceEffect.CREATE,),
        creation_contract=creation_contract,
    )
    return CanonicalOperationContractEvidence(
        canonical_operation=OFFSET_V1.canonical_operation,
        canonical_operation_version=OFFSET_V1.version,
        argument_schema=OFFSET_V1.input_schema,
        effects=OFFSET_V1.effects,
        verification_contract=OFFSET_V1.verification_contract,
        definition_fingerprint=fingerprint,
        existence_effects=(CanonicalExistenceEffect.CREATE,),
        creation_contract=creation_contract,
    )


def _provider_binding_set(execution_slice: ExecutionSlice) -> ProviderBindingSet:
    assert len(execution_slice.execution_units) == 1
    unit = execution_slice.execution_units[0]
    assert unit.targets == ("WALL-001",)

    target_draft = NativeTargetBindingEvidence(
        semantic_id="WALL-001",
        host_type=execution_slice.host_runtime_ref.host_type,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        native_id="2C6",
        native_kind="LWPOLYLINE",
        host_binding_fingerprint="0" * 64,
    )
    native_target = replace(
        target_draft,
        host_binding_fingerprint=compute_host_binding_fingerprint(target_draft),
    )
    binding_draft = ProviderBinding(
        binding_id="PB-DRAFT",
        execution_unit_id=unit.execution_unit_id,
        execution_unit_hash=unit.execution_unit_hash,
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        canonical_operation=unit.canonical_operation,
        provider_server="step36.offset.provider",
        provider_tool="offset",
        provider_version="1.0.0",
        selected_candidate_fingerprint="c" * 64,
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        input_adapter_version="1.0.0",
        native_targets=(native_target,),
        provider_arguments=dict(unit.arguments),
        provider_preconditions=(),
        native_binding_metadata={"fixture": "step36-offset-source"},
        verification_contract=dict(OFFSET_V1.verification_contract),
        rollback_contract={"type": "NONE"},
        binding_expires_at="2026-08-31T08:00:00Z",
        binding_hash="0" * 64,
    )
    binding_hash = compute_binding_hash(
        execution_unit_hash=binding_draft.execution_unit_hash,
        execution_slice_hash=binding_draft.execution_slice_hash,
        canonical_operation=binding_draft.canonical_operation,
        provider_server=binding_draft.provider_server,
        provider_tool=binding_draft.provider_tool,
        provider_version=binding_draft.provider_version,
        selected_candidate_fingerprint=binding_draft.selected_candidate_fingerprint,
        host_instance_id=binding_draft.host_instance_id,
        document_ref=binding_draft.document_ref,
        input_adapter_version=binding_draft.input_adapter_version,
        native_targets=binding_draft.native_targets,
        provider_arguments=binding_draft.provider_arguments,
        provider_preconditions=binding_draft.provider_preconditions,
        native_binding_metadata=binding_draft.native_binding_metadata,
        verification_contract=binding_draft.verification_contract,
        rollback_contract=binding_draft.rollback_contract,
        binding_expires_at=binding_draft.binding_expires_at,
    )
    binding = replace(
        binding_draft,
        binding_id=f"PB-{binding_hash[:12]}",
        binding_hash=binding_hash,
    )
    binding_set_hash = compute_binding_set_hash(
        execution_slice_hash=execution_slice.execution_slice_hash,
        binding_hashes=(binding.binding_hash,),
    )
    return ProviderBindingSet(
        binding_set_id=f"PBS-{binding_set_hash[:12]}",
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        provider_execution_snapshot_id="PXS-STEP36-OFFLINE",
        provider_execution_snapshot_hash="d" * 64,
        bindings=(binding,),
        binding_set_hash=binding_set_hash,
    )


def _admit_execution_authority(
    changeset: CanonicalChangeSet,
    boundary: ApprovalScopeBoundary,
    execution_slice: ExecutionSlice,
    binding_set: ProviderBindingSet,
) -> AdmittedExecutionAuthority:
    admission_draft = ApprovalAdmission(
        admission_id="ADM-STEP36-OFFLINE",
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        semantic_environment_ref=changeset.semantic_environment_ref,
        approver="user:step36-offline",
        policy_snapshot_hash="e" * 64,
        policy_allowed_operations=(OFFSET_V1.canonical_operation,),
        approved_at="2026-08-31T06:00:00Z",
        expires_at="2026-08-31T08:00:00Z",
        admission_fingerprint="0" * 64,
    )
    admission = replace(
        admission_draft,
        admission_fingerprint=compute_admission_fingerprint(admission_draft),
    )
    service = GatewayAuthorizationService(InMemoryGatewayAuthorizationStore())
    approval = service.consume_approval(
        ApprovalConsumptionRequest(
            admission=admission,
            canonical_changeset=changeset,
            approval_scope_boundary=boundary,
            consumed_at="2026-08-31T06:30:00Z",
        )
    )
    grant = service.issue_execution_grant(
        ExecutionGrantRequest(
            approval_id=approval.approval_id,
            execution_slice=execution_slice,
            provider_binding_set=binding_set,
            issued_at="2026-08-31T07:00:00Z",
        )
    )
    return service.admit_execution_grant(
        grant.grant_hash,
        "2026-08-31T07:05:00Z",
    )


def _build_fixture() -> Step36CreationAuthorityFixture:
    bound = _bound_offset()
    environment = SemanticEnvironmentBinding("ENV-STEP36", "env-hash-step36")
    planning = PlanningSnapshotBinding(
        "PS-STEP36-OFFLINE",
        "planning-hash-step36-offline",
        "DOC-A",
        environment,
    )
    snapshot_set = SnapshotSetBinding(
        "SS-STEP36-OFFLINE",
        "snapshot-set-hash-step36-offline",
        (planning.snapshot_id,),
        environment,
    )
    intent = _intent_boundary()
    impact = ImpactAnalyzer().analyze(
        ImpactAnalysisRequest(
            bound_operation=bound,
            planning_snapshot_ref=planning,
            snapshot_set_ref=snapshot_set,
            semantic_environment_ref=environment,
            intent_boundary=intent,
        )
    )
    requested_creation_rule = CreationRule(
        rule_id="REQUEST-OFFSET",
        canonical_operation=OFFSET_V1.canonical_operation,
        source_selector=EntitySelector(entities=("WALL-001",)),
        entity_kinds=("ifc:IfcWall",),
        max_count=1,
        required_derivation="RULE-OFFSET-WALL",
    )
    admitted_rule_id = creation_rule_id(requested_creation_rule)
    scope = ApprovalScopePlanner().plan(
        ApprovalScopePlanRequest(
            canonical_effect_evidence=CanonicalEffectEvidence(
                canonical_operation=OFFSET_V1.canonical_operation,
                canonical_operation_version=OFFSET_V1.version,
                allowed_aspects=(),
                allowed_existence_effects=(CanonicalExistenceEffect.CREATE,),
                creation_contract=_creation_contract(),
            ),
            impact_analysis=impact,
            intent_boundary=intent,
            requested_creation_rules=(requested_creation_rule,),
            execution_slice_scope_rules=(
                ExecutionSliceScopeRule(
                    "SLICE-SCOPE-STEP36-OFFLINE",
                    "DOC-A",
                    creation_rule_ids=(admitted_rule_id,),
                ),
            ),
        )
    )
    assert len(scope.creation_rules) == 1
    creation_rule = scope.creation_rules[0]
    changeset = ChangeSetBuilder().build(
        ChangeSetBuildRequest(
            task_id="TASK-STEP36-OFFLINE",
            bound_operation_evidence=_bound_evidence(bound),
            impact_analysis=impact,
            approval_scope_definition=scope,
            canonical_operation_contracts=(_operation_contract(),),
        )
    )
    boundary = bind_changeset(scope, changeset.changeset_hash, "SCOPE-STEP36-OFFLINE")
    runtime = HostRuntimeRef("AUTOCAD", "AUTOCAD-STEP36-A", "DOC-A")
    routes = (RuntimeEntityRoute("WALL-001", runtime),)
    routing = RuntimeRoutingEvidence(
        "RRS-STEP36-OFFLINE",
        routes,
        compute_routing_snapshot_hash(routes),
    )
    plan = ExecutionPlanner().plan(
        ExecutionPlanningRequest(changeset, boundary, routing)
    )
    assert len(plan.execution_slices) == 1
    execution_slice = plan.execution_slices[0]
    binding_set = _provider_binding_set(execution_slice)
    authority = _admit_execution_authority(
        changeset,
        boundary,
        execution_slice,
        binding_set,
    )
    return Step36CreationAuthorityFixture(
        creation_rule=creation_rule,
        canonical_changeset=changeset,
        approval_scope_boundary=boundary,
        execution_slice=execution_slice,
        provider_binding_set=binding_set,
        admitted_execution_authority=authority,
    )


@pytest.fixture(scope="module")
def step36_creation_authority() -> Step36CreationAuthorityFixture:
    return _build_fixture()


def _create_change(
    fixture: Step36CreationAuthorityFixture,
    native_id: str,
    *,
    canonical_kind: str = "ifc:IfcWall",
    source_semantic_id: str = "WALL-001",
    derivation_rule: str = "RULE-OFFSET-WALL",
) -> ActualChange:
    unit = fixture.execution_slice.execution_units[0]
    draft = ActualChange(
        change_kind=ActualChangeKind.CREATE,
        actual_change_hash="0" * 64,
        canonical_kind=canonical_kind,
        canonical_operation=OFFSET_V1.canonical_operation,
        source_execution_unit_hash=unit.execution_unit_hash,
        source_semantic_id=source_semantic_id,
        source_canonical_kind="ifc:IfcWall",
        derivation_rule=derivation_rule,
        host_entity_ref=HostEntityRef(
            document_id="DOC-A",
            native_id=native_id,
            native_type="Polyline",
        ),
    )
    return replace(
        draft,
        actual_change_hash=compute_actual_change_hash(draft),
    )


def _delta(
    fixture: Step36CreationAuthorityFixture,
    changes: tuple[ActualChange, ...],
) -> ActualDelta:
    authority = fixture.admitted_execution_authority
    execution_slice = fixture.execution_slice
    draft = ActualDelta(
        actual_delta_id="AD-STEP36-OFFLINE",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=authority.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=7,
        revision_after=8,
        changes=changes,
        actual_delta_hash="0" * 64,
    )
    return replace(
        draft,
        actual_delta_hash=compute_actual_delta_hash(draft),
    )


def _compare(
    fixture: Step36CreationAuthorityFixture,
    *changes: ActualChange,
):
    return ScopeComparator().compare(
        ScopeComparisonRequest(
            admitted_execution_authority=fixture.admitted_execution_authority,
            actual_delta=_delta(fixture, tuple(changes)),
            approval_scope_boundary=fixture.approval_scope_boundary,
            execution_slice=fixture.execution_slice,
        )
    )


def test_one_created_wall_is_within_creation_scope(
    step36_creation_authority: Step36CreationAuthorityFixture,
) -> None:
    result = _compare(
        step36_creation_authority,
        _create_change(step36_creation_authority, "C01"),
    )

    assert result.status is ScopeComparisonStatus.WITHIN_SCOPE
    assert result.violations == ()
    assert result.matched_changes[0].rule_id == step36_creation_authority.creation_rule.rule_id


def test_two_created_host_entities_exceed_creation_capacity(
    step36_creation_authority: Step36CreationAuthorityFixture,
) -> None:
    result = _compare(
        step36_creation_authority,
        _create_change(step36_creation_authority, "C01"),
        _create_change(step36_creation_authority, "C02"),
    )

    assert result.status is ScopeComparisonStatus.SCOPE_BREACH
    assert [violation.code for violation in result.violations] == [
        "CREATION_COUNT_EXCEEDED"
    ]


@pytest.mark.parametrize(
    ("change_overrides", "expected_code"),
    [
        ({"canonical_kind": "ifc:IfcDoor"}, "CREATION_KIND_FORBIDDEN"),
        ({"source_semantic_id": "WALL-OTHER"}, "CREATION_SOURCE_FORBIDDEN"),
        ({"derivation_rule": "RULE-OTHER"}, "CREATION_DERIVATION_MISMATCH"),
    ],
)
def test_creation_rule_dimensions_fail_closed(
    step36_creation_authority: Step36CreationAuthorityFixture,
    change_overrides: dict[str, str],
    expected_code: str,
) -> None:
    result = _compare(
        step36_creation_authority,
        _create_change(
            step36_creation_authority,
            "C01",
            **change_overrides,
        ),
    )

    assert result.status is ScopeComparisonStatus.SCOPE_BREACH
    assert [violation.code for violation in result.violations] == [expected_code]
