"""Phase H: provider-neutral Revit wall-thickness reconciliation parity proof."""

from __future__ import annotations

from dataclasses import dataclass, replace

import design_execution_reconciliation as reconciliation
from design_approval_scope import (
    ApprovalScopeBoundary,
    ApprovalScopePlanner,
    ApprovalScopePlanRequest,
    CanonicalAspect,
    CanonicalEffectEvidence,
    DirectEntityEffect,
    ExecutionSliceScopeRule,
    bind_changeset,
    direct_existing_rule_id,
)
from design_changeset import (
    BoundOperationEvidence,
    CanonicalChangeSet,
    CanonicalOperationContractEvidence,
    ChangeSetBuilder,
    ChangeSetBuildRequest,
    canonical_hash,
    compute_bound_operation_evidence_fingerprint,
    compute_bound_operation_fingerprint,
    compute_contract_definition_fingerprint,
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
from design_orchestrator.canonical_operations import (
    MVP_CANONICAL_OPERATIONS,
    SET_WALL_THICKNESS_V1,
)
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    BoundOperationProposal,
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
from revit_sidecar.execution_result_adapter import RevitExecutionResultAdapter
from semantic_runtime import (
    Coverage,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotKind,
)


@dataclass(frozen=True, slots=True)
class PhaseHTransaction:
    canonical_changeset: CanonicalChangeSet
    approval_scope_boundary: ApprovalScopeBoundary
    execution_plan: ExecutionPlan
    execution_slice: ExecutionSlice


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


def _contract_from_definition() -> CanonicalOperationContractEvidence:
    definition = SET_WALL_THICKNESS_V1
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


def _build_transaction() -> PhaseHTransaction:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    bound = binder.bind(
        OperationProposal(
            "set_wall_thickness.v1",
            {"thickness": {"value": 300.0, "unit": "mm"}},
        ),
        ParameterBindingContext(
            context_snapshot_id="CS-PHASE-H",
            context_snapshot_hash="context-hash-phase-h",
            document_ref="DOC-REVIT",
            semantic_environment_ref="ENV-PHASE-H",
            selection=("WALL-001",),
            context_values={},
        ),
    )
    environment = SemanticEnvironmentBinding("ENV-PHASE-H", "env-hash-phase-h")
    planning = PlanningSnapshotBinding(
        "PS-PHASE-H",
        "ps-hash-phase-h",
        "DOC-REVIT",
        environment,
    )
    snapshot_set = SnapshotSetBinding(
        "PSS-PHASE-H",
        "pss-hash-phase-h",
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
                SET_WALL_THICKNESS_V1.canonical_operation,
                SET_WALL_THICKNESS_V1.version,
                (CanonicalAspect.PROPERTIES,),
            ),
            impact_analysis=impact,
            intent_boundary=intent,
            direct_entity_effects=(
                DirectEntityEffect("WALL-001", (CanonicalAspect.PROPERTIES,)),
            ),
            execution_slice_scope_rules=(
                ExecutionSliceScopeRule(
                    "SLICE-SCOPE-PHASE-H",
                    "DOC-REVIT",
                    existing_rule_ids=(rule_id,),
                ),
            ),
        )
    )
    changeset = ChangeSetBuilder().build(
        ChangeSetBuildRequest(
            task_id="TASK-PHASE-H",
            bound_operation_evidence=_bound_evidence(bound),
            impact_analysis=impact,
            approval_scope_definition=scope,
            canonical_operation_contracts=(_contract_from_definition(),),
        )
    )
    boundary = bind_changeset(scope, changeset.changeset_hash, "SCOPE-PHASE-H")
    runtime = HostRuntimeRef("revit", "HOST-REVIT-A", "DOC-REVIT")
    routes = (RuntimeEntityRoute("WALL-001", runtime),)
    routing = RuntimeRoutingEvidence(
        "RRS-PHASE-H",
        routes,
        compute_routing_snapshot_hash(routes),
    )
    plan = ExecutionPlanner().plan(
        ExecutionPlanningRequest(changeset, boundary, routing)
    )
    assert len(plan.execution_slices) == 1
    return PhaseHTransaction(changeset, boundary, plan, plan.execution_slices[0])


def _build_binding_set(execution_slice: ExecutionSlice) -> ProviderBindingSet:
    unit = execution_slice.execution_units[0]
    native_draft = NativeTargetBindingEvidence(
        semantic_id="WALL-001",
        host_type="revit",
        document_ref="DOC-REVIT",
        native_id="wall-unique-id",
        native_kind="Wall",
        host_binding_fingerprint="0" * 64,
    )
    native = replace(
        native_draft,
        host_binding_fingerprint=compute_host_binding_fingerprint(native_draft),
    )
    draft = ProviderBinding(
        binding_id="PB-PHASE-H-DRAFT",
        execution_unit_id=unit.execution_unit_id,
        execution_unit_hash=unit.execution_unit_hash,
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        canonical_operation=unit.canonical_operation,
        provider_server="revit-local",
        provider_tool="revit.set_wall_thickness",
        provider_version="1.0.0",
        selected_candidate_fingerprint="c" * 64,
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        input_adapter_version="1.0.0",
        native_targets=(native,),
        provider_arguments={
            "wall_unique_id": "wall-unique-id",
            "thickness": {"value": 300.0, "unit": "mm"},
        },
        provider_preconditions=({"revision": 10},),
        native_binding_metadata={"phase_h": "revit-wall-thickness"},
        verification_contract=SET_WALL_THICKNESS_V1.verification_contract,
        rollback_contract={"type": "NONE"},
        binding_expires_at="2026-09-01T23:00:00Z",
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
    binding = replace(
        draft,
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
        provider_execution_snapshot_id="PXS-PHASE-H",
        provider_execution_snapshot_hash="d" * 64,
        bindings=(binding,),
        binding_set_hash=binding_set_hash,
    )


def _admit_authority(
    transaction: PhaseHTransaction,
    binding_set: ProviderBindingSet,
) -> AdmittedExecutionAuthority:
    changeset = transaction.canonical_changeset
    boundary = transaction.approval_scope_boundary
    draft = ApprovalAdmission(
        admission_id="ADM-PHASE-H",
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        semantic_environment_ref=changeset.semantic_environment_ref,
        approver="user:phase-h-fixture",
        policy_snapshot_hash="e" * 64,
        policy_allowed_operations=(SET_WALL_THICKNESS_V1.canonical_operation,),
        approved_at="2026-09-01T20:00:00Z",
        expires_at="2026-09-01T23:00:00Z",
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
            consumed_at="2026-09-01T20:10:00Z",
        )
    )
    grant = service.issue_execution_grant(
        ExecutionGrantRequest(
            approval_id=approval.approval_id,
            execution_slice=transaction.execution_slice,
            provider_binding_set=binding_set,
            issued_at="2026-09-01T20:20:00Z",
        )
    )
    return service.admit_execution_grant(
        grant.grant_hash,
        "2026-09-01T20:30:00Z",
    )


def _host_result(*, wider_effects: list[dict] | None = None) -> dict:
    verification = {
        "identity_invariant_proven": True,
        "location_invariant_proven": True,
        "relationship_invariant_proven": True,
        "document_change_observed": True,
        "revision_before": 10,
        "revision_after": 11,
        "location_signature_before": "Line|0|0|0|10|0|0",
        "location_signature_after": "Line|0|0|0|10|0|0",
        "relationship_signature_before": "isolated",
        "relationship_signature_after": "isolated",
    }
    if wider_effects is not None:
        verification["normalized_wider_effects"] = wider_effects
    return {
        "command_id": "CMD-REVIT-PHASE-H",
        "status": "OK",
        "revision_after": 11,
        "payload": {
            "wall_unique_id": "wall-unique-id",
            "wall_type_unique_id": "wall-type-unique-id",
            "editable_layer_index": 1,
            "width_before_internal": 0.5,
            "width_after_internal": 0.984251968503937,
            "width_after_mm": 300.0,
            "requested_width_mm": 300.0,
            "transaction_attempt_count": 1,
        },
        "verification": verification,
        "replayed": False,
    }


def _delta(
    authority: AdmittedExecutionAuthority,
    *,
    wider_effects: list[dict] | None = None,
) -> reconciliation.ActualDelta:
    result = RevitExecutionResultAdapter.adapt(
        admitted_authority=authority,
        document_ref="DOC-REVIT",
        approved_semantic_wall_id="WALL-001",
        host_result=_host_result(wider_effects=wider_effects),
        occurred_at="2026-09-01T21:01:00Z",
    )
    assert isinstance(result, HostCommitted)
    return result.actual_delta


def _slice_state(stored, slice_hash):
    return next(
        state
        for state in stored.slice_states
        if state.execution_slice_hash == slice_hash
    )


def _assigned_tasks(stored, transaction: PhaseHTransaction):
    slice_hash = transaction.execution_slice.execution_slice_hash
    assignment = next(
        item
        for item in stored.definition.slice_validation_assignments
        if item.execution_slice_hash == slice_hash
    )
    tasks_by_id = {
        task.validation_task_id: task
        for task in transaction.canonical_changeset.validation_tasks
    }
    return tuple(tasks_by_id[task_id] for task_id in assignment.validation_task_ids)


def _signed_bundle(
    transaction: PhaseHTransaction,
    authority: AdmittedExecutionAuthority,
    delta: reconciliation.ActualDelta,
    *,
    width_mm: float,
    include_subject: bool = True,
) -> reconciliation.VerificationEvidenceBundle:
    changeset = transaction.canonical_changeset
    environment = SemanticEnvironmentRef(
        changeset.semantic_environment_ref.environment_id,
        changeset.semantic_environment_ref.content_hash,
    )
    projection = SemanticProjectionRef(
        projection_id="PROJ-PHASE-H",
        projection_hash=canonical_hash(
            {"phase_h": "projection", "width_mm": width_mm}
        ),
        semantic_model_version="dsp-core+ifc43+enterprise-phase-h",
        provider_set_hash=canonical_hash({"phase_h": "providers"}),
        mapping_profile_set_hash=canonical_hash({"phase_h": "mappings"}),
        normalized_fact_batch_hash=canonical_hash(
            {"phase_h": "facts", "width_mm": width_mm}
        ),
    )
    snapshot = SemanticSnapshot(
        snapshot_id="PS-PHASE-H-POST",
        kind=SnapshotKind.PLANNING,
        project_id=changeset.project_id,
        freshness_contract_id="FC-PHASE-H-POST",
        freshness_contract_hash=canonical_hash({"phase_h": "freshness"}),
        document_ref=delta.document_ref,
        base_host_revision=str(delta.revision_after),
        coverage=Coverage(delta.document_ref, ("WALL-001",)),
        projection_ref=projection,
        semantic_environment_ref=environment,
        aspect_guarantees=(),
        hash=canonical_hash(
            {
                "phase_h": "snapshot",
                "delta": delta.actual_delta_hash,
                "width_mm": width_mm,
            }
        ),
    )
    subject = reconciliation.VerificationSubjectEvidence(
        semantic_id="WALL-001",
        canonical_kind="ifc:IfcWall",
        properties={
            "dsp:WallThickness": {
                "value": width_mm,
                "unit": "mm",
            }
        },
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
    contract = SET_WALL_THICKNESS_V1.verification_contract
    draft = reconciliation.VerificationEvidenceBundle(
        evidence_bundle_id="VEB-PHASE-H",
        changeset_hash=changeset.changeset_hash,
        execution_slice_hash=authority.execution_slice_hash,
        actual_delta_hash=delta.actual_delta_hash,
        semantic_environment_ref=environment,
        post_execution_snapshot_ref=snapshot,
        post_execution_projection_ref=projection,
        base_host_revision=str(delta.revision_after),
        baseline_snapshot_ref=None,
        baseline_projection_ref=None,
        contract_evidence=(
            reconciliation.VerificationContractEvidence(
                contract_ref=canonical_hash(contract),
                contract_body=contract,
            ),
        ),
        subject_evidence=(subject,) if include_subject else (),
        baseline_subject_evidence=(),
        evidence_bundle_hash="0" * 64,
    )
    return replace(
        draft,
        evidence_bundle_hash=reconciliation.compute_verification_evidence_bundle_hash(
            draft
        ),
    )


def _service() -> reconciliation.ExecutionReconciliationService:
    return reconciliation.ExecutionReconciliationService(
        store=reconciliation.InMemoryExecutionSagaStore(),
    )


def _drive_to_scope(
    service: reconciliation.ExecutionReconciliationService,
    transaction: PhaseHTransaction,
    authority: AdmittedExecutionAuthority,
    delta: reconciliation.ActualDelta,
):
    execution_slice = transaction.execution_slice
    saga = service.create_saga(
        transaction.canonical_changeset,
        transaction.approval_scope_boundary,
        transaction.execution_plan,
    )
    saga = service.reserve_slice_admission(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=saga.saga_revision,
        reserved_at="2026-09-01T21:00:00Z",
    )
    saga = service.confirm_slice_admitted(
        saga.definition.saga_id,
        authority,
        expected_revision=saga.saga_revision,
    )
    saga = service.record_host_commit(
        saga.definition.saga_id,
        delta,
        expected_revision=saga.saga_revision,
        committed_at="2026-09-01T21:01:00Z",
    )
    saga = service.begin_reconciliation(
        saga.definition.saga_id,
        execution_slice.execution_slice_hash,
        expected_revision=saga.saga_revision,
    )
    scope_result = service.compare_scope(
        reconciliation.ScopeComparisonRequest(
            admitted_execution_authority=authority,
            actual_delta=delta,
            approval_scope_boundary=transaction.approval_scope_boundary,
            execution_slice=execution_slice,
        )
    )
    saga = service.record_scope_result(
        saga.definition.saga_id,
        scope_result,
        expected_revision=saga.saga_revision,
    )
    return saga, scope_result


def _verification_request(
    transaction: PhaseHTransaction,
    authority: AdmittedExecutionAuthority,
    delta: reconciliation.ActualDelta,
    saga,
    *,
    width_mm: float,
    include_subject: bool = True,
) -> reconciliation.SemanticVerificationRequest:
    return reconciliation.SemanticVerificationRequest(
        admitted_execution_authority=authority,
        approval_scope_boundary=transaction.approval_scope_boundary,
        canonical_changeset=transaction.canonical_changeset,
        actual_delta=delta,
        validation_tasks=_assigned_tasks(saga, transaction),
        verification_evidence_bundle=_signed_bundle(
            transaction,
            authority,
            delta,
            width_mm=width_mm,
            include_subject=include_subject,
        ),
        verified_at="2026-09-01T21:02:00Z",
    )


def _fixture():
    transaction = _build_transaction()
    binding_set = _build_binding_set(transaction.execution_slice)
    authority = _admit_authority(transaction, binding_set)
    return transaction, binding_set, authority


def test_revit_wall_thickness_reaches_succeeded_through_provider_neutral_chain() -> None:
    transaction, binding_set, authority = _fixture()
    delta = _delta(authority)
    service = _service()

    native_target = binding_set.bindings[0].native_targets[0]
    assert transaction.execution_slice.host_runtime_ref == HostRuntimeRef(
        "revit", "HOST-REVIT-A", "DOC-REVIT"
    )
    assert native_target.native_kind == "Wall"
    assert native_target.native_id == "wall-unique-id"
    assert binding_set.bindings[0].provider_server == "revit-local"
    assert binding_set.bindings[0].provider_tool == "revit.set_wall_thickness"
    assert delta.changes[0].changed_aspects == (CanonicalAspect.PROPERTIES,)
    assert delta.changes[0].host_entity_ref is None
    assert "WallType" not in repr(delta)
    assert "CompoundStructure" not in repr(delta)

    saga, scope_result = _drive_to_scope(service, transaction, authority, delta)
    assert scope_result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE

    verification = service.verify_semantics(
        saga.definition.saga_id,
        transaction.execution_slice.execution_slice_hash,
        _verification_request(
            transaction,
            authority,
            delta,
            saga,
            width_mm=300.0,
        ),
    )
    final = service.record_verification_result(
        saga.definition.saga_id,
        verification,
        expected_revision=saga.saga_revision,
        reconciled_at="2026-09-01T21:03:00Z",
    )

    assert verification.status is reconciliation.VerificationStatus.PASSED
    assert final.status is reconciliation.ExecutionSagaStatus.SUCCEEDED
    state = _slice_state(final, transaction.execution_slice.execution_slice_hash)
    assert state.status is reconciliation.SliceReconciliationStatus.SUCCEEDED


def test_revit_wrong_reconstructed_width_becomes_verify_failed() -> None:
    transaction, _, authority = _fixture()
    delta = _delta(authority)
    service = _service()

    saga, scope_result = _drive_to_scope(service, transaction, authority, delta)
    assert scope_result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE

    verification = service.verify_semantics(
        saga.definition.saga_id,
        transaction.execution_slice.execution_slice_hash,
        _verification_request(
            transaction,
            authority,
            delta,
            saga,
            width_mm=299.0,
        ),
    )
    final = service.record_verification_result(
        saga.definition.saga_id,
        verification,
        expected_revision=saga.saga_revision,
        reconciled_at="2026-09-01T21:03:00Z",
    )

    assert verification.status is reconciliation.VerificationStatus.FAILED
    assert final.status is reconciliation.ExecutionSagaStatus.PARTIALLY_COMMITTED
    state = _slice_state(final, transaction.execution_slice.execution_slice_hash)
    assert state.status is reconciliation.SliceReconciliationStatus.VERIFY_FAILED
    assert final.status is not reconciliation.ExecutionSagaStatus.SUCCEEDED


def test_revit_truthful_extra_geometry_becomes_scope_breach() -> None:
    transaction, _, authority = _fixture()
    delta = _delta(
        authority,
        wider_effects=[
            {
                "semantic_id": "WALL-001",
                "canonical_kind": "ifc:IfcWall",
                "changed_aspects": ["GEOMETRY"],
            }
        ],
    )
    service = _service()

    saga, scope_result = _drive_to_scope(service, transaction, authority, delta)

    assert scope_result.status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH
    assert "ASPECT_OUTSIDE_SCOPE" in {item.code for item in scope_result.violations}
    assert saga.status is reconciliation.ExecutionSagaStatus.PARTIALLY_COMMITTED
    state = _slice_state(saga, transaction.execution_slice.execution_slice_hash)
    assert state.status is reconciliation.SliceReconciliationStatus.SCOPE_BREACH


def test_revit_truthful_other_entity_becomes_scope_breach() -> None:
    transaction, _, authority = _fixture()
    delta = _delta(
        authority,
        wider_effects=[
            {
                "semantic_id": "DOOR-001",
                "canonical_kind": "ifc:IfcDoor",
                "changed_aspects": ["RELATIONSHIPS"],
            }
        ],
    )
    service = _service()

    saga, scope_result = _drive_to_scope(service, transaction, authority, delta)

    assert scope_result.status is reconciliation.ScopeComparisonStatus.SCOPE_BREACH
    assert saga.status is reconciliation.ExecutionSagaStatus.PARTIALLY_COMMITTED
    state = _slice_state(saga, transaction.execution_slice.execution_slice_hash)
    assert state.status is reconciliation.SliceReconciliationStatus.SCOPE_BREACH


def test_revit_host_success_without_post_semantic_evidence_cannot_pass_verification() -> None:
    transaction, _, authority = _fixture()
    delta = _delta(authority)
    service = _service()

    saga, scope_result = _drive_to_scope(service, transaction, authority, delta)
    assert scope_result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE

    verification = service.verify_semantics(
        saga.definition.saga_id,
        transaction.execution_slice.execution_slice_hash,
        _verification_request(
            transaction,
            authority,
            delta,
            saga,
            width_mm=300.0,
            include_subject=False,
        ),
    )
    final = service.record_verification_result(
        saga.definition.saga_id,
        verification,
        expected_revision=saga.saga_revision,
        reconciled_at="2026-09-01T21:03:00Z",
    )

    assert verification.status is reconciliation.VerificationStatus.EVIDENCE_INSUFFICIENT
    assert verification.status is not reconciliation.VerificationStatus.PASSED
    assert final.status is reconciliation.ExecutionSagaStatus.PARTIALLY_COMMITTED
    state = _slice_state(final, transaction.execution_slice.execution_slice_hash)
    assert state.status is reconciliation.SliceReconciliationStatus.VERIFY_FAILED
    assert final.status is not reconciliation.ExecutionSagaStatus.SUCCEEDED
