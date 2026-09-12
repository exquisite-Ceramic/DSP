from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from design_execution_coordination import (
    CrossHostReadinessBarrier,
    HostReadinessReceipt,
    ReadinessStatus,
    compute_readiness_receipt_hash,
)
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
from tests.provider_binding._support import snapshot


def admission(case):
    provisional = ApprovalAdmission(
        admission_id="ADM-READINESS",
        changeset_hash=case.changeset.changeset_hash,
        approved_scope_hash=case.boundary_v2.scope_hash,
        semantic_environment_ref=case.changeset.semantic_environment_ref,
        approver="user:readiness-approver",
        policy_snapshot_hash="a" * 64,
        policy_allowed_operations=("set_wall_thickness.v1",),
        approved_at="2026-09-06T09:00:00Z",
        expires_at="2026-09-06T17:00:00Z",
        admission_fingerprint="0" * 64,
    )
    return replace(
        provisional,
        admission_fingerprint=compute_admission_fingerprint(provisional),
    )


def phase_i_readiness_inputs():
    case, materialization_plan, _, execution_request = build_phase_i_execution_inputs()
    execution_plan = plan_materialized_execution(execution_request)
    store = InMemoryGatewayAuthorizationStoreV2()
    service = GatewayAuthorizationServiceV2(store)
    approval = service.consume_approval(
        ApprovalConsumptionRequestV2(
            admission=admission(case),
            canonical_changeset=case.changeset,
            approval_scope_boundary=case.boundary_v2,
            consumed_at="2026-09-06T10:00:00Z",
        )
    )
    binding_sets = []
    authorities = []
    for execution_slice in execution_plan.execution_slices:
        host_type = execution_slice.host_runtime_ref.host_type
        native_id, native_kind = (
            ("ACAD-HANDLE-001", "AcDbPolyline")
            if host_type == "autocad"
            else ("REVIT-UNIQUE-ID-001", "Wall")
        )
        binding_set = resolve_provider_bindings_v2(
            execution_slice,
            snapshot(
                execution_slice,
                native_id=native_id,
                native_kind=native_kind,
            ),
        )
        grant = service.issue_execution_grant(
            ExecutionGrantRequestV2(
                approval_id=approval.approval_id,
                execution_plan=execution_plan,
                execution_slice=execution_slice,
                provider_binding_set=binding_set,
                materialization_plan=materialization_plan,
                topology_snapshot=case.topology,
                approval_scope_boundary=case.boundary_v2,
                issued_at="2026-09-06T11:00:00Z",
            )
        )
        authority = service.admit_execution_grant(
            grant.grant_hash,
            "2026-09-06T11:05:00Z",
        )
        binding_sets.append(binding_set)
        authorities.append(authority)
    return SimpleNamespace(
        case=case,
        materialization_plan=materialization_plan,
        execution_plan=execution_plan,
        binding_sets=tuple(binding_sets),
        authorities=tuple(authorities),
    )


class FakeReadinessPort:
    def __init__(self, status: ReadinessStatus, *, corrupt: str | None = None) -> None:
        self.status = status
        self.corrupt = corrupt
        self.calls = []

    def check(self, execution_slice, authority, binding_set):
        self.calls.append((execution_slice, authority, binding_set))
        provisional = HostReadinessReceipt(
            materialization_id=execution_slice.materialization_id,
            materialization_plan_hash=execution_slice.materialization_plan_hash,
            execution_slice_hash=execution_slice.execution_slice_hash,
            binding_set_hash=binding_set.binding_set_hash,
            grant_hash=authority.grant_hash,
            host_runtime_ref=execution_slice.host_runtime_ref,
            observed_revision=11,
            status=self.status,
            failure_code=(
                None
                if self.status is ReadinessStatus.READY
                else f"{execution_slice.host_runtime_ref.host_type.upper()}_NOT_READY"
            ),
            receipt_hash="0" * 64,
        )
        receipt = replace(
            provisional,
            receipt_hash=compute_readiness_receipt_hash(provisional),
        )
        if self.corrupt == "materialization":
            return replace(receipt, materialization_id="MAT-CORRUPTED")
        if self.corrupt == "binding":
            return replace(receipt, binding_set_hash="f" * 64)
        if self.corrupt == "runtime":
            runtime = receipt.host_runtime_ref
            return replace(
                receipt,
                host_runtime_ref=replace(
                    runtime,
                    host_instance_id=f"{runtime.host_instance_id}-OTHER",
                ),
            )
        return receipt


class FakeReadinessRegistry:
    def __init__(self, ports) -> None:
        self.ports = dict(ports)
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        return self.ports[runtime_ref.host_type]


def barrier(statuses=None, *, corrupt_host: str | None = None, corrupt=None):
    statuses = statuses or {
        "autocad": ReadinessStatus.READY,
        "revit": ReadinessStatus.READY,
    }
    ports = {
        host_type: FakeReadinessPort(
            status,
            corrupt=corrupt if host_type == corrupt_host else None,
        )
        for host_type, status in statuses.items()
    }
    registry = FakeReadinessRegistry(ports)
    return CrossHostReadinessBarrier(registry), registry, ports
