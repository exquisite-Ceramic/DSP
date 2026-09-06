from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from autocad_sidecar.execution.readiness import AutoCadWallThicknessReadinessPort
from design_execution_coordination import (
    ReadinessError,
    ReadinessStatus,
    compute_readiness_receipt_hash,
)
from design_execution_planning import plan_materialized_execution
from design_fact_contracts import FactKind, NormalizedDesignFactBatch
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


class _ForbiddenRetry:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, _attempt):
        self.calls += 1
        raise AssertionError("readiness must not enter mutation retry")


class _ForbiddenIdempotency:
    def __init__(self) -> None:
        self.calls = 0

    async def complete(self, _key, _result):
        self.calls += 1
        raise AssertionError("readiness must not complete mutation idempotency")


class FakeDispatcher:
    def __init__(self, batch: NormalizedDesignFactBatch) -> None:
        self.batch = batch
        self.extract_calls: list[tuple[str, ...]] = []
        self.mutation_calls = 0
        self._retry = _ForbiddenRetry()
        self._idempotency = _ForbiddenIdempotency()

    async def extract_design_facts(self, handles: list[str]):
        self.extract_calls.append(tuple(handles))
        return self.batch

    async def set_wall_thickness(self, *_args, **_kwargs):
        self.mutation_calls += 1
        raise AssertionError("readiness must not mutate AutoCAD")


def _admission(case):
    provisional = ApprovalAdmission(
        admission_id="ADM-AUTOCAD-READINESS",
        changeset_hash=case.changeset.changeset_hash,
        approved_scope_hash=case.boundary_v2.scope_hash,
        semantic_environment_ref=case.changeset.semantic_environment_ref,
        approver="user:autocad-readiness",
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


def _autocad_inputs(*, native_kind: str = "LWPOLYLINE"):
    case, materialization_plan, _, execution_request = _phase_i_inputs()
    execution_plan = plan_materialized_execution(execution_request)
    execution_slice = next(
        item
        for item in execution_plan.execution_slices
        if item.host_runtime_ref.host_type == "autocad"
    )
    binding_set = resolve_provider_bindings_v2(
        execution_slice,
        _snapshot(
            execution_slice,
            native_id="ACAD-HANDLE-001",
            native_kind=native_kind,
        ),
    )
    service = GatewayAuthorizationServiceV2(InMemoryGatewayAuthorizationStoreV2())
    approval = service.consume_approval(
        ApprovalConsumptionRequestV2(
            admission=_admission(case),
            canonical_changeset=case.changeset,
            approval_scope_boundary=case.boundary_v2,
            consumed_at="2026-09-06T10:00:00Z",
        )
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
    return SimpleNamespace(
        execution_slice=execution_slice,
        binding_set=binding_set,
        authority=authority,
    )


def _batch(
    ctx,
    *,
    host_instance_id: str | None = None,
    document_ref: str | None = None,
    native_id: str = "ACAD-HANDLE-001",
    native_kind: str = "LWPOLYLINE",
    width_mm: float | None = 200.0,
    revision: int = 21,
) -> NormalizedDesignFactBatch:
    properties = (
        {}
        if width_mm is None
        else {"constantWidth": {"value": width_mm, "unit": "mm"}}
    )
    return DesignFactAdapter().normalize_snapshot(
        {
            "hostInstanceId": (
                host_instance_id
                or ctx.execution_slice.host_runtime_ref.host_instance_id
            ),
            "documentId": document_ref or ctx.execution_slice.host_runtime_ref.document_ref,
            "revision": revision,
            "entities": [
                {
                    "nativeId": native_id,
                    "nativeKind": native_kind,
                    "layer": "A-WALL",
                    "properties": properties,
                }
            ],
        }
    )


def _property_fact(batch: NormalizedDesignFactBatch):
    return next(item for item in batch.facts if item.fact_kind is FactKind.PROPERTY)


def _replace_fact(batch, original, **changes):
    return NormalizedDesignFactBatch(
        tuple(replace(item, **changes) if item is original else item for item in batch.facts)
    )


def test_ready_receipt_uses_exact_normalized_wall_fact_and_never_mutates() -> None:
    ctx = _autocad_inputs()
    dispatcher = FakeDispatcher(_batch(ctx, revision=21, width_mm=200.0))
    receipt = AutoCadWallThicknessReadinessPort(dispatcher).check(
        ctx.execution_slice,
        ctx.authority,
        ctx.binding_set,
    )

    target = ctx.binding_set.bindings[0].native_targets[0]
    assert target.native_id == "ACAD-HANDLE-001"
    assert target.native_kind == "LWPOLYLINE"
    assert receipt.status is ReadinessStatus.READY
    assert receipt.failure_code is None
    assert receipt.observed_revision == 21
    assert receipt.materialization_id == ctx.execution_slice.materialization_id
    assert receipt.materialization_plan_hash == ctx.execution_slice.materialization_plan_hash
    assert receipt.execution_slice_hash == ctx.execution_slice.execution_slice_hash
    assert receipt.binding_set_hash == ctx.binding_set.binding_set_hash
    assert receipt.grant_hash == ctx.authority.grant_hash
    assert receipt.host_runtime_ref == ctx.execution_slice.host_runtime_ref
    assert receipt.receipt_hash == compute_readiness_receipt_hash(receipt)
    assert dispatcher.extract_calls == [("ACAD-HANDLE-001",)]
    assert dispatcher.mutation_calls == 0
    assert dispatcher._retry.calls == 0
    assert dispatcher._idempotency.calls == 0


@pytest.mark.parametrize(
    ("batch_builder", "expected_code"),
    (
        (
            lambda ctx: _batch(ctx, host_instance_id="ACAD-OTHER"),
            "AUTOCAD_READINESS_HOST_MISMATCH",
        ),
        (
            lambda ctx: _batch(ctx, document_ref="DOC-OTHER"),
            "AUTOCAD_READINESS_DOCUMENT_MISMATCH",
        ),
        (
            lambda ctx: _batch(ctx, native_id="ACAD-HANDLE-OTHER"),
            "AUTOCAD_READINESS_TARGET_MISMATCH",
        ),
        (
            lambda ctx: _batch(ctx, native_kind="LINE"),
            "AUTOCAD_READINESS_NATIVE_KIND_MISMATCH",
        ),
        (
            lambda ctx: _batch(ctx, width_mm=None),
            "AUTOCAD_READINESS_WIDTH_MISSING",
        ),
    ),
)
def test_invalid_normalized_wall_evidence_returns_not_ready(
    batch_builder,
    expected_code,
) -> None:
    ctx = _autocad_inputs()
    dispatcher = FakeDispatcher(batch_builder(ctx))
    receipt = AutoCadWallThicknessReadinessPort(dispatcher).check(
        ctx.execution_slice,
        ctx.authority,
        ctx.binding_set,
    )
    assert receipt.status is ReadinessStatus.NOT_READY
    assert receipt.failure_code == expected_code
    assert dispatcher.mutation_calls == 0
    assert dispatcher._retry.calls == 0
    assert dispatcher._idempotency.calls == 0


def test_width_unit_revision_and_positive_value_are_revalidated() -> None:
    ctx = _autocad_inputs()
    base = _batch(ctx)
    width = _property_fact(base)

    wrong_unit = _replace_fact(base, width, unit="cm")
    receipt = AutoCadWallThicknessReadinessPort(FakeDispatcher(wrong_unit)).check(
        ctx.execution_slice,
        ctx.authority,
        ctx.binding_set,
    )
    assert receipt.status is ReadinessStatus.NOT_READY
    assert receipt.failure_code == "AUTOCAD_READINESS_WIDTH_UNIT_MISMATCH"

    non_positive = _replace_fact(base, width, value=0.0)
    receipt = AutoCadWallThicknessReadinessPort(FakeDispatcher(non_positive)).check(
        ctx.execution_slice,
        ctx.authority,
        ctx.binding_set,
    )
    assert receipt.status is ReadinessStatus.NOT_READY
    assert receipt.failure_code == "AUTOCAD_READINESS_WIDTH_INVALID"

    identity = next(item for item in base.facts if item.fact_kind is FactKind.IDENTITY)
    mixed_revision = _replace_fact(base, identity, source_revision=22)
    receipt = AutoCadWallThicknessReadinessPort(FakeDispatcher(mixed_revision)).check(
        ctx.execution_slice,
        ctx.authority,
        ctx.binding_set,
    )
    assert receipt.status is ReadinessStatus.NOT_READY
    assert receipt.failure_code == "AUTOCAD_READINESS_REVISION_MISMATCH"


def test_non_lwpolyline_binding_is_not_ready_with_real_observed_revision() -> None:
    ctx = _autocad_inputs(native_kind="AcDbPolyline")
    dispatcher = FakeDispatcher(_batch(ctx, native_kind="AcDbPolyline", revision=21))
    receipt = AutoCadWallThicknessReadinessPort(dispatcher).check(
        ctx.execution_slice,
        ctx.authority,
        ctx.binding_set,
    )
    assert receipt.status is ReadinessStatus.NOT_READY
    assert receipt.failure_code == "AUTOCAD_READINESS_NATIVE_KIND_UNSUPPORTED"
    assert receipt.observed_revision == 21
    assert dispatcher.extract_calls == [("ACAD-HANDLE-001",)]


def test_lineage_substitution_fails_closed_before_fact_extraction() -> None:
    ctx = _autocad_inputs()
    dispatcher = FakeDispatcher(_batch(ctx))
    substituted = replace(ctx.authority, host_instance_id="ACAD-OTHER")
    with pytest.raises(ReadinessError) as exc:
        AutoCadWallThicknessReadinessPort(dispatcher).check(
            ctx.execution_slice,
            substituted,
            ctx.binding_set,
        )
    assert exc.value.code == "READINESS_LINEAGE_MISMATCH"
    assert dispatcher.extract_calls == []
