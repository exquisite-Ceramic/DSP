from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from design_execution_coordination import (
    CrossHostReadinessBarrier,
    HostReadinessReceipt,
    ReadinessBarrierStatus,
    ReadinessError,
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
from tests.execution_planning.test_step30_materialization_v2 import _phase_i_inputs
from tests.provider_binding.test_step31_materialization_v2 import _snapshot


def _admission(case):
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


def _phase_i_readiness_inputs():
    case, materialization_plan, _, execution_request = _phase_i_inputs()
    execution_plan = plan_materialized_execution(execution_request)
    store = InMemoryGatewayAuthorizationStoreV2()
    service = GatewayAuthorizationServiceV2(store)
    approval = service.consume_approval(
        ApprovalConsumptionRequestV2(
            admission=_admission(case),
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
            _snapshot(
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


def _barrier(statuses=None, *, corrupt_host: str | None = None, corrupt=None):
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


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ReadinessError) as exc:
        operation()
    assert exc.value.code == code


def test_all_required_ready_returns_one_exact_receipt_per_materialization() -> None:
    ctx = _phase_i_readiness_inputs()
    barrier, registry, ports = _barrier()
    result = barrier.check_all(
        ctx.materialization_plan,
        ctx.execution_plan,
        ctx.binding_sets,
        ctx.authorities,
    )

    assert result.status is ReadinessBarrierStatus.READY
    assert result.failure_ref is None
    assert len(result.receipts) == len(ctx.materialization_plan.intents) == 2
    assert tuple(item.host_runtime_ref.host_type for item in result.receipts) == (
        "autocad",
        "revit",
    )
    assert {item.materialization_id for item in result.receipts} == {
        item.materialization_id for item in ctx.materialization_plan.intents
    }
    assert len(registry.resolutions) == 2
    assert all(len(port.calls) == 1 for port in ports.values())


def test_any_not_ready_returns_not_ready_after_observing_all_required_hosts() -> None:
    ctx = _phase_i_readiness_inputs()
    barrier, _, ports = _barrier(
        {
            "autocad": ReadinessStatus.NOT_READY,
            "revit": ReadinessStatus.READY,
        }
    )
    result = barrier.check_all(
        ctx.materialization_plan,
        ctx.execution_plan,
        ctx.binding_sets,
        ctx.authorities,
    )

    assert result.status is ReadinessBarrierStatus.NOT_READY
    assert result.failure_ref == "AUTOCAD_NOT_READY"
    assert len(result.receipts) == 2
    assert all(len(port.calls) == 1 for port in ports.values())


@pytest.mark.parametrize("collection", ("binding", "authority"))
def test_missing_or_extra_required_binding_or_authority_fails_closed(collection) -> None:
    ctx = _phase_i_readiness_inputs()
    barrier, _, _ = _barrier()
    bindings = ctx.binding_sets
    authorities = ctx.authorities
    if collection == "binding":
        _assert_code(
            "READINESS_LINEAGE_MISMATCH",
            lambda: barrier.check_all(
                ctx.materialization_plan,
                ctx.execution_plan,
                bindings[:1],
                authorities,
            ),
        )
        _assert_code(
            "READINESS_LINEAGE_MISMATCH",
            lambda: barrier.check_all(
                ctx.materialization_plan,
                ctx.execution_plan,
                (*bindings, bindings[0]),
                authorities,
            ),
        )
    else:
        _assert_code(
            "READINESS_LINEAGE_MISMATCH",
            lambda: barrier.check_all(
                ctx.materialization_plan,
                ctx.execution_plan,
                bindings,
                authorities[:1],
            ),
        )
        _assert_code(
            "READINESS_LINEAGE_MISMATCH",
            lambda: barrier.check_all(
                ctx.materialization_plan,
                ctx.execution_plan,
                bindings,
                (*authorities, authorities[0]),
            ),
        )


@pytest.mark.parametrize("corrupt", ("materialization", "binding", "runtime"))
def test_receipt_lineage_mismatch_fails_closed(corrupt) -> None:
    ctx = _phase_i_readiness_inputs()
    barrier, _, _ = _barrier(corrupt_host="revit", corrupt=corrupt)
    _assert_code(
        "READINESS_LINEAGE_MISMATCH",
        lambda: barrier.check_all(
            ctx.materialization_plan,
            ctx.execution_plan,
            ctx.binding_sets,
            ctx.authorities,
        ),
    )


def test_authority_or_binding_substitution_fails_before_any_readiness_check() -> None:
    ctx = _phase_i_readiness_inputs()
    barrier, _, ports = _barrier()
    substituted = replace(
        ctx.authorities[1],
        binding_set_hash=ctx.binding_sets[0].binding_set_hash,
    )
    _assert_code(
        "READINESS_LINEAGE_MISMATCH",
        lambda: barrier.check_all(
            ctx.materialization_plan,
            ctx.execution_plan,
            ctx.binding_sets,
            (ctx.authorities[0], substituted),
        ),
    )
    assert all(port.calls == [] for port in ports.values())
