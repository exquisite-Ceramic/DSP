from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from design_execution_planning import plan_materialized_execution
from design_gateway_authorization import (
    ApprovalAdmission,
    ApprovalConsumptionRequestV2,
    ExecutionGrantRequestV2,
    GatewayAuthorizationServiceV2,
    InMemoryGatewayAuthorizationStoreV2,
    compute_admission_fingerprint,
)
from design_provider_binding import resolve_provider_bindings_v2

from tests.execution_planning._support import build_phase_i_execution_inputs
from tests.materialization_planning._support import build_case
from tests.provider_binding._support import snapshot


def approval_request_v2(case=None) -> ApprovalConsumptionRequestV2:
    case = case or build_case()
    draft = ApprovalAdmission(
        admission_id="ADM-PHASE-I-V2",
        changeset_hash=case.changeset.changeset_hash,
        approved_scope_hash=case.boundary_v2.scope_hash,
        semantic_environment_ref=case.changeset.semantic_environment_ref,
        approver="user:phase-i-approver",
        policy_snapshot_hash="a" * 64,
        policy_allowed_operations=("set_wall_thickness.v1",),
        approved_at="2026-09-06T09:00:00Z",
        expires_at="2026-09-06T17:00:00Z",
        admission_fingerprint="0" * 64,
    )
    admission = replace(
        draft,
        admission_fingerprint=compute_admission_fingerprint(draft),
    )
    return ApprovalConsumptionRequestV2(
        admission=admission,
        canonical_changeset=case.changeset,
        approval_scope_boundary=case.boundary_v2,
        consumed_at="2026-09-06T10:00:00Z",
    )


def native_identity(host_type: str) -> tuple[str, str]:
    if host_type == "autocad":
        return "ACAD-HANDLE-001", "AcDbPolyline"
    return "REVIT-UNIQUE-ID-001", "Wall"


def authorization_case(host_type: str = "autocad"):
    case, materialization_plan, _, execution_request = build_phase_i_execution_inputs()
    execution_plan = plan_materialized_execution(execution_request)
    execution_slice = next(
        item
        for item in execution_plan.execution_slices
        if item.host_runtime_ref.host_type == host_type
    )
    native_id, native_kind = native_identity(host_type)
    provider_snapshot = snapshot(
        execution_slice,
        native_id=native_id,
        native_kind=native_kind,
    )
    binding_set = resolve_provider_bindings_v2(execution_slice, provider_snapshot)
    store = InMemoryGatewayAuthorizationStoreV2()
    service = GatewayAuthorizationServiceV2(store)
    approval = service.consume_approval(approval_request_v2(case))
    request = ExecutionGrantRequestV2(
        approval_id=approval.approval_id,
        execution_plan=execution_plan,
        execution_slice=execution_slice,
        provider_binding_set=binding_set,
        materialization_plan=materialization_plan,
        topology_snapshot=case.topology,
        approval_scope_boundary=case.boundary_v2,
        issued_at="2026-09-06T11:00:00Z",
    )
    return SimpleNamespace(
        case=case,
        materialization_plan=materialization_plan,
        execution_plan=execution_plan,
        execution_slice=execution_slice,
        binding_set=binding_set,
        store=store,
        service=service,
        approval=approval,
        request=request,
    )
