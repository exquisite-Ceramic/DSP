from __future__ import annotations

import pytest
from design_gateway_authorization import GatewayAuthorizationError

from tests.gateway_authorization._support import authorization_case


def test_admitted_authority_preserves_exact_materialization_lineage() -> None:
    ctx = authorization_case("revit")
    grant = ctx.service.issue_execution_grant(ctx.request)
    authority = ctx.service.admit_execution_grant(
        grant.grant_hash,
        "2026-09-06T11:10:00Z",
    )

    assert authority.approval_hash == grant.approval_hash
    assert authority.grant_hash == grant.grant_hash
    assert authority.changeset_hash == grant.changeset_hash
    assert authority.approved_scope_hash == grant.approved_scope_hash
    assert authority.materialization_plan_hash == grant.materialization_plan_hash
    assert authority.materialization_id == grant.materialization_id
    assert authority.execution_slice_hash == grant.execution_slice_hash
    assert authority.binding_set_hash == grant.binding_set_hash
    assert authority.host_instance_id == grant.host_instance_id
    assert authority.admitted_at == "2026-09-06T11:10:00Z"


def test_repeated_admission_is_idempotent() -> None:
    ctx = authorization_case("autocad")
    grant = ctx.service.issue_execution_grant(ctx.request)
    first = ctx.service.admit_execution_grant(
        grant.grant_hash,
        "2026-09-06T11:10:00Z",
    )
    second = ctx.service.admit_execution_grant(
        grant.grant_hash,
        "2026-09-06T11:20:00Z",
    )

    assert second == first


def test_unknown_or_expired_grant_cannot_be_admitted() -> None:
    ctx = authorization_case("revit")
    with pytest.raises(GatewayAuthorizationError) as exc:
        ctx.service.admit_execution_grant("f" * 64, "2026-09-06T11:10:00Z")
    assert exc.value.code == "EXECUTION_GRANT_CONFLICT"

    grant = ctx.service.issue_execution_grant(ctx.request)
    with pytest.raises(GatewayAuthorizationError) as exc:
        ctx.service.admit_execution_grant(grant.grant_hash, grant.expires_at)
    assert exc.value.code == "EXECUTION_GRANT_EXPIRED"
