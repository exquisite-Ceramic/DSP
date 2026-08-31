"""Live Step36 proof that a real AutoCAD OFFSET creation reconciles within scope."""

from __future__ import annotations

import os
import uuid
from collections.abc import Mapping
from dataclasses import replace

import pytest
from autocad_live_host import live_autocad_host_adapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from design_approval_scope import (
    ApprovalScopePlanner,
    ApprovalScopePlanRequest,
    CanonicalEffectEvidence,
    CanonicalExistenceEffect,
    CreationRule,
    EntitySelector,
    ExecutionSliceScopeRule,
    bind_changeset,
    creation_rule_id,
)
from design_changeset import ChangeSetBuilder, ChangeSetBuildRequest
from design_execution_planning import (
    ExecutionPlanner,
    ExecutionPlanningRequest,
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
from design_impact import (
    ImpactAnalysisRequest,
    ImpactAnalyzer,
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
from test_step36_live_autocad_offset_create import (
    _DISTANCE_MM,
    _assert_mm_fixture,
    _bounds,
    _layer,
    _native_kind,
    _selected_source,
    _side_point,
)
from test_step36_offset_creation_authority import (
    Step36CreationAuthorityFixture,
    _admit_execution_authority,
    _bound_evidence,
    _creation_contract,
    _intent_boundary,
    _operation_contract,
)

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AGENT_HOST_TEST") != "1",
        reason="requires live AutoCAD host (AGENT_HOST_TEST=1)",
    ),
]


def _bound_offset(document_ref: str):
    binder = ParameterBinder((OFFSET_V1,), (OFFSET_V1_BINDING_RECIPE,))
    return binder.bind(
        OperationProposal(
            canonical_operation=OFFSET_V1.canonical_operation,
            intent_arguments={
                "distance": {"value": _DISTANCE_MM, "unit": "mm"},
                "side_point": {
                    "x": 5000.0,
                    "y": 2000.0,
                    "z": 0.0,
                    "unit": "mm",
                },
            },
        ),
        ParameterBindingContext(
            context_snapshot_id="CS-STEP36-LIVE-SCOPE",
            context_snapshot_hash="context-hash-step36-live-scope",
            document_ref=document_ref,
            semantic_environment_ref="ENV-STEP36-LIVE-SCOPE",
            selection=("WALL-001",),
        ),
    )


def _provider_binding_set(
    execution_slice,
    *,
    source_handle: str,
    source_native_kind: str,
) -> ProviderBindingSet:
    assert len(execution_slice.execution_units) == 1
    unit = execution_slice.execution_units[0]
    assert unit.targets == ("WALL-001",)

    target_draft = NativeTargetBindingEvidence(
        semantic_id="WALL-001",
        host_type=execution_slice.host_runtime_ref.host_type,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        native_id=source_handle,
        native_kind=source_native_kind,
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
        native_binding_metadata={"fixture": "step36-live-offset-source"},
        verification_contract=dict(OFFSET_V1.verification_contract),
        rollback_contract={"type": "NONE"},
        binding_expires_at="2026-08-31T12:00:00Z",
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
        provider_execution_snapshot_id="PXS-STEP36-LIVE-SCOPE",
        provider_execution_snapshot_hash="d" * 64,
        bindings=(binding,),
        binding_set_hash=binding_set_hash,
    )


def _build_live_authority(
    *,
    host_type: str,
    host_instance_id: str,
    document_ref: str,
    source_handle: str,
    source_native_kind: str,
) -> Step36CreationAuthorityFixture:
    bound = _bound_offset(document_ref)
    environment = SemanticEnvironmentBinding(
        "ENV-STEP36-LIVE-SCOPE",
        "env-hash-step36-live-scope",
    )
    planning = PlanningSnapshotBinding(
        "PS-STEP36-LIVE-SCOPE",
        "planning-hash-step36-live-scope",
        document_ref,
        environment,
    )
    snapshot_set = SnapshotSetBinding(
        "SS-STEP36-LIVE-SCOPE",
        "snapshot-set-hash-step36-live-scope",
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
        rule_id="REQUEST-OFFSET-LIVE",
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
                    "SLICE-SCOPE-STEP36-LIVE",
                    document_ref,
                    creation_rule_ids=(admitted_rule_id,),
                ),
            ),
        )
    )
    assert len(scope.creation_rules) == 1
    creation_rule = scope.creation_rules[0]
    changeset = ChangeSetBuilder().build(
        ChangeSetBuildRequest(
            task_id="TASK-STEP36-LIVE-SCOPE",
            bound_operation_evidence=_bound_evidence(bound),
            impact_analysis=impact,
            approval_scope_definition=scope,
            canonical_operation_contracts=(_operation_contract(),),
        )
    )
    boundary = bind_changeset(scope, changeset.changeset_hash, "SCOPE-STEP36-LIVE")
    runtime = HostRuntimeRef(host_type, host_instance_id, document_ref)
    routes = (RuntimeEntityRoute("WALL-001", runtime),)
    routing = RuntimeRoutingEvidence(
        "RRS-STEP36-LIVE-SCOPE",
        routes,
        compute_routing_snapshot_hash(routes),
    )
    plan = ExecutionPlanner().plan(
        ExecutionPlanningRequest(changeset, boundary, routing)
    )
    assert len(plan.execution_slices) == 1
    execution_slice = plan.execution_slices[0]
    binding_set = _provider_binding_set(
        execution_slice,
        source_handle=source_handle,
        source_native_kind=source_native_kind,
    )
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


def _created_change(
    fixture: Step36CreationAuthorityFixture,
    *,
    document_ref: str,
    native_id: str,
    native_type: str,
) -> ActualChange:
    unit = fixture.execution_slice.execution_units[0]
    draft = ActualChange(
        change_kind=ActualChangeKind.CREATE,
        actual_change_hash="0" * 64,
        canonical_kind="ifc:IfcWall",
        canonical_operation=OFFSET_V1.canonical_operation,
        source_execution_unit_hash=unit.execution_unit_hash,
        source_semantic_id="WALL-001",
        source_canonical_kind="ifc:IfcWall",
        derivation_rule="RULE-OFFSET-WALL",
        host_entity_ref=HostEntityRef(
            document_id=document_ref,
            native_id=native_id,
            native_type=native_type,
        ),
    )
    return replace(
        draft,
        actual_change_hash=compute_actual_change_hash(draft),
    )


def _actual_delta(
    fixture: Step36CreationAuthorityFixture,
    *,
    revision_before: int,
    revision_after: int,
    changes: tuple[ActualChange, ...],
) -> ActualDelta:
    authority = fixture.admitted_execution_authority
    draft = ActualDelta(
        actual_delta_id="AD-STEP36-LIVE-SCOPE",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=authority.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=fixture.execution_slice.host_runtime_ref.document_ref,
        revision_before=revision_before,
        revision_after=revision_after,
        changes=changes,
        actual_delta_hash="0" * 64,
    )
    return replace(
        draft,
        actual_delta_hash=compute_actual_delta_hash(draft),
    )


def _compare(fixture: Step36CreationAuthorityFixture, delta: ActualDelta):
    return ScopeComparator().compare(
        ScopeComparisonRequest(
            admitted_execution_authority=fixture.admitted_execution_authority,
            actual_delta=delta,
            approval_scope_boundary=fixture.approval_scope_boundary,
            execution_slice=fixture.execution_slice,
        )
    )


@pytest.mark.asyncio
async def test_live_created_offset_ref_reconciles_within_creation_scope() -> None:
    host = live_autocad_host_adapter()

    try:
        dispatcher = CommandDispatcher(host)
        source_handle, revision_before, source_before = await _selected_source(dispatcher)
        _assert_mm_fixture(source_before)
        source_bounds = _bounds(source_before)
        source_native_kind = _native_kind(source_before)
        assert source_before.facts
        host_refs = {
            (
                fact.host_ref.host_type,
                fact.host_ref.host_instance_id,
                fact.host_ref.document_id,
            )
            for fact in source_before.facts
        }
        assert len(host_refs) == 1
        host_type, host_instance_id, document_ref = host_refs.pop()

        fixture = _build_live_authority(
            host_type=host_type,
            host_instance_id=host_instance_id,
            document_ref=document_ref,
            source_handle=source_handle,
            source_native_kind=source_native_kind,
        )
        binding = fixture.provider_binding_set.bindings[0]
        assert len(binding.native_targets) == 1
        assert binding.native_targets[0].semantic_id == "WALL-001"
        assert binding.native_targets[0].native_id == source_handle
        assert binding.native_targets[0].document_ref == document_ref

        result = await dispatcher.offset(
            [source_handle],
            {"value": _DISTANCE_MM, "unit": "mm"},
            _side_point(source_bounds),
            idempotency_key=f"step36-live-scope-{uuid.uuid4()}",
            revision=revision_before,
        )
        assert result.ok, result.error
        assert result.revision_after == revision_before + 1
        created_ref = (result.payload or {}).get("createdEntityRef")
        assert isinstance(created_ref, Mapping)
        created_handle = str(created_ref.get("native_id") or "")
        created_type = str(created_ref.get("native_type") or "")
        assert created_handle
        assert created_handle != source_handle
        assert created_type

        source_after = await dispatcher.extract_design_facts([source_handle])
        created_after = await dispatcher.extract_design_facts([created_handle])
    finally:
        await host.close()

    assert _bounds(source_after) == source_bounds
    assert _layer(created_after) == "A-WALL"

    change = _created_change(
        fixture,
        document_ref=document_ref,
        native_id=created_handle,
        native_type=created_type,
    )
    delta = _actual_delta(
        fixture,
        revision_before=revision_before,
        revision_after=revision_before + 1,
        changes=(change,),
    )

    assert change.canonical_operation == "offset.v1"
    assert change.canonical_kind == "ifc:IfcWall"
    assert change.source_semantic_id == "WALL-001"
    assert change.source_canonical_kind == "ifc:IfcWall"
    assert change.derivation_rule == "RULE-OFFSET-WALL"
    assert change.host_entity_ref.native_id == created_handle
    assert "LWPOLYLINE" not in repr(delta)
    assert "GetOffsetCurves" not in repr(delta)

    result = _compare(fixture, delta)
    assert result.status is ScopeComparisonStatus.WITHIN_SCOPE
    assert result.violations == ()
    assert result.matched_changes[0].rule_id == fixture.creation_rule.rule_id

    synthetic_second = _created_change(
        fixture,
        document_ref=document_ref,
        native_id=f"{created_handle}-SYNTHETIC-SECOND",
        native_type=created_type,
    )
    breach_delta = _actual_delta(
        fixture,
        revision_before=revision_before,
        revision_after=revision_before + 1,
        changes=(change, synthetic_second),
    )
    breach = _compare(fixture, breach_delta)
    assert breach.status is ScopeComparisonStatus.SCOPE_BREACH
    assert [violation.code for violation in breach.violations] == [
        "CREATION_COUNT_EXCEEDED"
    ]
