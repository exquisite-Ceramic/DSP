from __future__ import annotations

from dataclasses import fields, replace

import pytest
from design_execution_planning import HostRuntimeRef
from design_gateway_authorization import (
    ExecutionGrantRequestV2,
    GatewayAuthorizationError,
)

from tests.gateway_authorization._support import authorization_case


def _assert_error(code: str, operation, *, upstream_code: str | None = None) -> None:
    with pytest.raises(GatewayAuthorizationError) as exc:
        operation()
    assert exc.value.code == code
    if upstream_code is not None:
        assert exc.value.upstream_code == upstream_code


def test_v2_grant_request_carries_exact_owner_validation_evidence() -> None:
    assert {field.name for field in fields(ExecutionGrantRequestV2)} == {
        "approval_id",
        "execution_plan",
        "execution_slice",
        "provider_binding_set",
        "materialization_plan",
        "topology_snapshot",
        "approval_scope_boundary",
        "issued_at",
    }


def test_valid_grant_binds_exact_materialization_authority() -> None:
    ctx = authorization_case("autocad")
    grant = ctx.service.issue_execution_grant(ctx.request)

    assert grant.approval_id == ctx.approval.approval_id
    assert grant.approval_hash == ctx.approval.approval_hash
    assert grant.changeset_hash == ctx.execution_slice.changeset_hash
    assert grant.approved_scope_hash == ctx.execution_slice.approved_scope_ref.scope_hash
    assert grant.materialization_plan_hash == ctx.materialization_plan.materialization_plan_hash
    assert grant.materialization_id == ctx.execution_slice.materialization_id
    assert grant.execution_slice_id == ctx.execution_slice.execution_slice_id
    assert grant.execution_slice_hash == ctx.execution_slice.execution_slice_hash
    assert grant.binding_set_hash == ctx.binding_set.binding_set_hash
    assert grant.host_instance_id == ctx.execution_slice.host_runtime_ref.host_instance_id
    assert grant.allowed_operations == ("set_wall_thickness.v1",)
    assert grant.expires_at == ctx.binding_set.bindings[0].binding_expires_at
    assert grant.grant_id == f"EGV2-{grant.grant_hash[:12]}"


def test_autocad_and_revit_receive_distinct_materialization_grants() -> None:
    autocad = authorization_case("autocad")
    revit = authorization_case("revit")
    autocad_grant = autocad.service.issue_execution_grant(autocad.request)
    revit_grant = revit.service.issue_execution_grant(revit.request)

    assert autocad_grant.materialization_id != revit_grant.materialization_id
    assert autocad_grant.execution_slice_hash != revit_grant.execution_slice_hash
    assert autocad_grant.binding_set_hash != revit_grant.binding_set_hash
    assert autocad_grant.grant_hash != revit_grant.grant_hash


@pytest.mark.parametrize("mutation", ("plan", "materialization", "binding", "slice", "host"))
def test_materialization_plan_binding_slice_or_host_substitution_fails_closed(mutation) -> None:
    ctx = authorization_case("autocad")
    request = ctx.request

    if mutation == "plan":
        request = replace(
            request,
            materialization_plan=replace(
                request.materialization_plan,
                materialization_plan_hash="f" * 64,
            ),
        )
    elif mutation == "materialization":
        request = replace(
            request,
            execution_slice=replace(
                request.execution_slice,
                materialization_id="MAT-SUBSTITUTED",
            ),
        )
    elif mutation == "binding":
        request = replace(
            request,
            provider_binding_set=replace(
                request.provider_binding_set,
                binding_set_hash="f" * 64,
            ),
        )
    elif mutation == "slice":
        request = replace(
            request,
            execution_slice=replace(
                request.execution_slice,
                execution_slice_hash="f" * 64,
            ),
        )
    else:
        runtime = request.execution_slice.host_runtime_ref
        request = replace(
            request,
            execution_slice=replace(
                request.execution_slice,
                host_runtime_ref=HostRuntimeRef(
                    runtime.host_type,
                    f"{runtime.host_instance_id}-OTHER",
                    runtime.document_ref,
                ),
            ),
        )

    _assert_error(
        "MATERIALIZATION_AUTHORITY_MISMATCH",
        lambda: ctx.service.issue_execution_grant(request),
    )


def test_tampered_execution_plan_is_rejected_through_step30_owner_validator() -> None:
    ctx = authorization_case("autocad")
    bad_plan = replace(ctx.execution_plan, execution_plan_hash="f" * 64)

    _assert_error(
        "MATERIALIZATION_AUTHORITY_MISMATCH",
        lambda: ctx.service.issue_execution_grant(
            replace(ctx.request, execution_plan=bad_plan)
        ),
        upstream_code="EXECUTION_PLAN_INTEGRITY_INVALID",
    )


def test_same_active_lineage_and_binding_remains_idempotent() -> None:
    ctx = authorization_case("autocad")
    first = ctx.service.issue_execution_grant(ctx.request)
    second = ctx.service.issue_execution_grant(
        replace(ctx.request, issued_at="2026-09-06T11:05:00Z")
    )

    assert second == first
