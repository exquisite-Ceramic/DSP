from __future__ import annotations

import os
import uuid
from dataclasses import replace

import pytest

import design_execution_reconciliation as reconciliation
import test_step34_autocad_wall_thickness_reconciliation as fixture
from autocad_live_host import live_autocad_host_adapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from design_fact_contracts import FactKind

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AGENT_HOST_TEST") != "1",
        reason="requires live AutoCAD host (AGENT_HOST_TEST=1)",
    ),
]


def _build_live_transaction(
    document_ref: str,
    host_instance_id: str,
) -> fixture.Step34Transaction:
    binder = fixture.ParameterBinder(
        fixture.MVP_CANONICAL_OPERATIONS,
        fixture.MVP_BINDING_RECIPES,
    )
    bound = binder.bind(
        fixture.OperationProposal(
            "set_wall_thickness.v1",
            {"thickness": {"value": 300.0, "unit": "mm"}},
        ),
        fixture.ParameterBindingContext(
            context_snapshot_id="CS-STEP34-LIVE",
            context_snapshot_hash="context-hash-step34-live",
            document_ref=document_ref,
            semantic_environment_ref="ENV-STEP34-LIVE",
            selection=("WALL-001",),
            context_values={},
        ),
    )
    environment = fixture.SemanticEnvironmentBinding(
        "ENV-STEP34-LIVE",
        "env-hash-step34-live",
    )
    planning = fixture.PlanningSnapshotBinding(
        "PS-STEP34-LIVE",
        "ps-hash-step34-live",
        document_ref,
        environment,
    )
    snapshot_set = fixture.SnapshotSetBinding(
        "PSS-STEP34-LIVE",
        "pss-hash-step34-live",
        (planning.snapshot_id,),
        environment,
    )
    intent = fixture.IntentBoundary(
        direct_targets=("WALL-001",),
        allowed_canonical_effects=(fixture.CanonicalAspect.PROPERTIES.value,),
    )
    impact = fixture.ImpactAnalyzer().analyze(
        fixture.ImpactAnalysisRequest(
            bound_operation=bound,
            planning_snapshot_ref=planning,
            snapshot_set_ref=snapshot_set,
            semantic_environment_ref=environment,
            intent_boundary=intent,
        )
    )
    rule_id = fixture.direct_existing_rule_id("WALL-001")
    scope = fixture.ApprovalScopePlanner().plan(
        fixture.ApprovalScopePlanRequest(
            canonical_effect_evidence=fixture.CanonicalEffectEvidence(
                fixture.SET_WALL_THICKNESS_V1.canonical_operation,
                fixture.SET_WALL_THICKNESS_V1.version,
                (fixture.CanonicalAspect.PROPERTIES,),
            ),
            impact_analysis=impact,
            intent_boundary=intent,
            direct_entity_effects=(
                fixture.DirectEntityEffect(
                    "WALL-001",
                    (fixture.CanonicalAspect.PROPERTIES,),
                ),
            ),
            execution_slice_scope_rules=(
                fixture.ExecutionSliceScopeRule(
                    "SLICE-SCOPE-STEP34-LIVE",
                    document_ref,
                    existing_rule_ids=(rule_id,),
                ),
            ),
        )
    )
    changeset = fixture.ChangeSetBuilder().build(
        fixture.ChangeSetBuildRequest(
            task_id="TASK-STEP34-LIVE",
            bound_operation_evidence=fixture._bound_evidence(bound),
            impact_analysis=impact,
            approval_scope_definition=scope,
            canonical_operation_contracts=(fixture._contract_from_definition(),),
        )
    )
    boundary = fixture.bind_changeset(
        scope,
        changeset.changeset_hash,
        "SCOPE-STEP34-LIVE",
    )
    runtime = fixture.HostRuntimeRef(
        "autocad",
        host_instance_id,
        document_ref,
    )
    routes = (fixture.RuntimeEntityRoute("WALL-001", runtime),)
    routing = fixture.RuntimeRoutingEvidence(
        "RRS-STEP34-LIVE",
        routes,
        fixture.compute_routing_snapshot_hash(routes),
    )
    plan = fixture.ExecutionPlanner().plan(
        fixture.ExecutionPlanningRequest(changeset, boundary, routing)
    )
    assert len(plan.execution_slices) == 1
    return fixture.Step34Transaction(
        changeset,
        boundary,
        plan,
        plan.execution_slices[0],
    )


def _build_live_binding_set(
    execution_slice: fixture.ExecutionSlice,
    native_id: str,
) -> fixture.ProviderBindingSet:
    unit = execution_slice.execution_units[0]
    native_draft = fixture.NativeTargetBindingEvidence(
        semantic_id="WALL-001",
        host_type="autocad",
        document_ref=execution_slice.host_runtime_ref.document_ref,
        native_id=native_id,
        native_kind="LWPOLYLINE",
        host_binding_fingerprint="0" * 64,
    )
    native = replace(
        native_draft,
        host_binding_fingerprint=fixture.compute_host_binding_fingerprint(native_draft),
    )
    draft = fixture.ProviderBinding(
        binding_id="PB-STEP34-LIVE-DRAFT",
        execution_unit_id=unit.execution_unit_id,
        execution_unit_hash=unit.execution_unit_hash,
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        canonical_operation=unit.canonical_operation,
        provider_server="autocad-local",
        provider_tool="cad.set_wall_thickness",
        provider_version="1.0.0",
        selected_candidate_fingerprint="c" * 64,
        host_instance_id=execution_slice.host_runtime_ref.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        input_adapter_version="1.0.0",
        native_targets=(native,),
        provider_arguments={"handles": [native_id], "thickness_mm": 300.0},
        provider_preconditions=(),
        native_binding_metadata={"step34": "live-wall-thickness"},
        verification_contract=fixture.SET_WALL_THICKNESS_V1.verification_contract,
        rollback_contract={"type": "NONE"},
        binding_expires_at="2026-08-30T23:00:00Z",
        binding_hash="0" * 64,
    )
    binding_hash = fixture.compute_binding_hash(
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
    binding_set_hash = fixture.compute_binding_set_hash(
        execution_slice_hash=execution_slice.execution_slice_hash,
        binding_hashes=(binding.binding_hash,),
    )
    return fixture.ProviderBindingSet(
        binding_set_id=f"PBS-{binding_set_hash[:12]}",
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        provider_execution_snapshot_id="PXS-STEP34-LIVE",
        provider_execution_snapshot_hash="d" * 64,
        bindings=(binding,),
        binding_set_hash=binding_set_hash,
    )


def _signed_live_delta(
    transaction: fixture.Step34Transaction,
    authority: fixture.AdmittedExecutionAuthority,
    *,
    revision_before: int,
    revision_after: int,
) -> reconciliation.ActualDelta:
    change = fixture._signed_change()
    draft = reconciliation.ActualDelta(
        actual_delta_id="AD-STEP34-LIVE",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=authority.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=transaction.execution_slice.host_runtime_ref.document_ref,
        revision_before=revision_before,
        revision_after=revision_after,
        changes=(change,),
        actual_delta_hash="0" * 64,
    )
    return replace(
        draft,
        actual_delta_hash=reconciliation.compute_actual_delta_hash(draft),
    )


@pytest.mark.asyncio
async def test_live_autocad_wall_thickness_reaches_step33_succeeded() -> None:
    host = live_autocad_host_adapter()
    try:
        dispatcher = CommandDispatcher(host)
        document = await dispatcher.current_document()
        assert document.ok, document.error
        revision_before = int((document.payload or {}).get("revision") or 0)

        selection = await dispatcher.current_selection()
        assert selection.ok, selection.error
        refs = (selection.payload or {}).get("entityRefs", [])
        assert len(refs) == 1, "select exactly one Step34 A-WALL LWPOLYLINE fixture"
        selected = refs[0]
        assert str(selected.get("native_type", "")).upper() in {"POLYLINE", "LWPOLYLINE"}
        native_id = str(selected["native_id"])

        pre = await dispatcher.extract_design_facts([native_id])
        layers = [
            fact
            for fact in pre.facts
            if fact.fact_kind is FactKind.CLASSIFICATION and fact.predicate == "layer"
        ]
        assert len(layers) == 1
        assert layers[0].value == "A-WALL"
        pre_widths = [
            fact
            for fact in pre.facts
            if fact.fact_kind is FactKind.PROPERTY and fact.predicate == "constant_width"
        ]
        assert len(pre_widths) == 1, "final Step34 acceptance requires INSUNITS=4"
        assert pre_widths[0].value == 200.0, "reset Global Width to 200 before final acceptance"
        assert pre_widths[0].unit == "mm"

        document_ref = pre_widths[0].host_ref.document_id
        host_instance_id = pre_widths[0].host_ref.host_instance_id
        transaction = _build_live_transaction(document_ref, host_instance_id)
        binding_set = _build_live_binding_set(transaction.execution_slice, native_id)
        authority = fixture._admit_authority(transaction, binding_set)

        result = await dispatcher.set_wall_thickness(
            [native_id],
            300.0,
            idempotency_key=f"step34-live-e2e-{uuid.uuid4()}",
            revision=revision_before,
        )
        assert result.ok, result.error
        assert result.verification is not None
        assert result.verification.get("ok") is True
        assert result.revision_after == revision_before + 1

        post = await dispatcher.extract_design_facts([native_id])
    finally:
        await host.close()

    post_widths = [
        fact
        for fact in post.facts
        if fact.fact_kind is FactKind.PROPERTY and fact.predicate == "constant_width"
    ]
    assert len(post_widths) == 1
    assert post_widths[0].value == 300.0
    assert post_widths[0].unit == "mm"
    assert post_widths[0].host_ref.document_id == document_ref
    assert post_widths[0].host_ref.host_instance_id == host_instance_id

    delta = _signed_live_delta(
        transaction,
        authority,
        revision_before=revision_before,
        revision_after=int(result.revision_after),
    )
    assert "LWPOLYLINE" not in repr(delta)
    assert native_id not in repr(delta)
    assert "ConstantWidth" not in repr(delta)

    service = fixture._service()
    saga, scope_result = fixture._drive_to_scope(
        service,
        transaction,
        authority,
        delta,
    )
    assert scope_result.status is reconciliation.ScopeComparisonStatus.WITHIN_SCOPE

    verification = service.verify_semantics(
        saga.definition.saga_id,
        transaction.execution_slice.execution_slice_hash,
        fixture._verification_request(
            transaction,
            authority,
            delta,
            saga,
            width_mm=float(post_widths[0].value),
        ),
    )
    final = service.record_verification_result(
        saga.definition.saga_id,
        verification,
        expected_revision=saga.saga_revision,
        reconciled_at="2026-08-30T21:03:00Z",
    )

    assert verification.status is reconciliation.VerificationStatus.PASSED
    assert final.status is reconciliation.ExecutionSagaStatus.SUCCEEDED
    state = fixture._slice_state(final, transaction.execution_slice.execution_slice_hash)
    assert state.status is reconciliation.SliceReconciliationStatus.SUCCEEDED
