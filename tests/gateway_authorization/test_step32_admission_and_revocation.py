"""CAS admission, revocation ordering, and Step33 handoff for Step32."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import fields

import pytest
from design_gateway_authorization import (
    AdmittedExecutionAuthority,
    ApprovalState,
    GatewayAuthorizationError,
    GatewayAuthorizationService,
    GrantState,
)


def _issued(gateway_cross_step):
    store, approval, _slice, _binding_set, request = gateway_cross_step
    service = GatewayAuthorizationService(store)
    grant = service.issue_execution_grant(request)
    return store, approval, service, request, grant


def _assert_error(code, callable_):
    with pytest.raises(GatewayAuthorizationError) as exc:
        callable_()
    assert exc.value.code == code


def test_active_grant_admits_once_and_returns_exact_step33_handoff(gateway_cross_step):
    store, approval, service, _request, grant = _issued(gateway_cross_step)

    authority = service.admit_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:45:00Z",
    )

    assert isinstance(authority, AdmittedExecutionAuthority)
    assert {field.name for field in fields(AdmittedExecutionAuthority)} == {
        "approval_hash",
        "grant_hash",
        "changeset_hash",
        "approved_scope_hash",
        "execution_slice_hash",
        "binding_set_hash",
        "host_instance_id",
        "admitted_at",
    }
    assert authority.approval_hash == approval.approval_hash
    assert authority.grant_hash == grant.grant_hash
    assert authority.changeset_hash == grant.changeset_hash
    assert authority.approved_scope_hash == grant.approved_scope_hash
    assert authority.execution_slice_hash == grant.execution_slice_hash
    assert authority.binding_set_hash == grant.binding_set_hash
    assert authority.host_instance_id == grant.host_instance_id
    assert authority.admitted_at == "2026-08-30T07:45:00Z"

    stored = store.get_grant(grant.grant_hash)
    assert stored is not None
    assert stored.lifecycle.state is GrantState.ADMITTED
    assert stored.lifecycle.admitted_at == authority.admitted_at


def test_same_admitted_grant_retry_returns_original_logical_handoff(gateway_cross_step):
    _store, _approval, service, _request, grant = _issued(gateway_cross_step)
    original = service.admit_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:45:00Z",
    )
    retried = service.admit_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:55:00Z",
    )

    assert retried == original
    assert retried.admitted_at == "2026-08-30T07:45:00Z"


def test_admission_at_expiry_projects_expired_and_fails(gateway_cross_step):
    store, _approval, service, _request, grant = _issued(gateway_cross_step)

    _assert_error(
        "EXECUTION_GRANT_EXPIRED",
        lambda: service.admit_execution_grant(grant.grant_hash, grant.expires_at),
    )

    stored = store.get_grant(grant.grant_hash)
    assert stored is not None
    assert stored.lifecycle.state is GrantState.EXPIRED


def test_revoked_grant_cannot_be_admitted(gateway_cross_step):
    _store, _approval, service, _request, grant = _issued(gateway_cross_step)
    service.revoke_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:44:00Z",
        "operator cancellation",
    )

    _assert_error(
        "EXECUTION_GRANT_REVOKED",
        lambda: service.admit_execution_grant(
            grant.grant_hash,
            "2026-08-30T07:45:00Z",
        ),
    )


def test_parent_approval_revocation_has_admission_error_precedence(gateway_cross_step):
    _store, approval, service, _request, grant = _issued(gateway_cross_step)
    service.revoke_approval(
        approval.approval_id,
        "2026-08-30T07:44:00Z",
        "approval withdrawn",
    )

    _assert_error(
        "APPROVAL_REVOKED",
        lambda: service.admit_execution_grant(
            grant.grant_hash,
            "2026-08-30T07:45:00Z",
        ),
    )


def test_concurrent_admission_returns_one_logical_handoff(gateway_cross_step):
    store, _approval, service, _request, grant = _issued(gateway_cross_step)
    admitted_times = tuple(
        f"2026-08-30T07:{minute:02d}:00Z" for minute in range(45, 60)
    )
    admitted_times += tuple(
        f"2026-08-30T08:{minute:02d}:00Z" for minute in range(17)
    )

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(
            pool.map(
                lambda value: service.admit_execution_grant(grant.grant_hash, value),
                admitted_times,
            )
        )

    assert len(results) == 32
    assert len(set(results)) == 1
    assert results[0].admitted_at in admitted_times
    stored = store.get_grant(grant.grant_hash)
    assert stored is not None
    assert stored.lifecycle.state is GrantState.ADMITTED
    assert stored.lifecycle.admitted_at == results[0].admitted_at


def test_revoke_commit_first_makes_later_admit_fail(gateway_cross_step):
    _store, _approval, service, _request, grant = _issued(gateway_cross_step)
    service.revoke_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:44:00Z",
        "operator cancellation",
    )

    _assert_error(
        "EXECUTION_GRANT_REVOKED",
        lambda: service.admit_execution_grant(
            grant.grant_hash,
            "2026-08-30T07:45:00Z",
        ),
    )


def test_admit_commit_first_then_revoke_preserves_admitted_evidence(gateway_cross_step):
    store, _approval, service, _request, grant = _issued(gateway_cross_step)
    authority = service.admit_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:45:00Z",
    )
    revoked = service.revoke_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:46:00Z",
        "cancel remaining execution",
    )

    assert revoked.lifecycle.state is GrantState.REVOKED
    assert revoked.lifecycle.admitted_at == authority.admitted_at
    assert revoked.lifecycle.revoked_at == "2026-08-30T07:46:00Z"
    assert revoked.lifecycle.revocation_reason == "cancel remaining execution"
    stored = store.get_grant(grant.grant_hash)
    assert stored == revoked


def test_approval_revocation_cascades_active_child_and_blocks_future_authority(
    gateway_cross_step,
):
    store, approval, service, request, grant = _issued(gateway_cross_step)
    revoked_approval = service.revoke_approval(
        approval.approval_id,
        "2026-08-30T07:44:00Z",
        "approval withdrawn",
    )

    assert revoked_approval.lifecycle.state is ApprovalState.REVOKED
    assert revoked_approval.lifecycle.revoked_at == "2026-08-30T07:44:00Z"
    child = store.get_grant(grant.grant_hash)
    assert child is not None
    assert child.lifecycle.state is GrantState.REVOKED
    assert child.lifecycle.revoked_at == "2026-08-30T07:44:00Z"

    _assert_error(
        "APPROVAL_REVOKED",
        lambda: service.issue_execution_grant(request),
    )
    _assert_error(
        "APPROVAL_REVOKED",
        lambda: service.admit_execution_grant(
            grant.grant_hash,
            "2026-08-30T07:45:00Z",
        ),
    )


def test_approval_revocation_preserves_admitted_child_evidence(gateway_cross_step):
    store, approval, service, _request, grant = _issued(gateway_cross_step)
    authority = service.admit_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:45:00Z",
    )
    service.revoke_approval(
        approval.approval_id,
        "2026-08-30T07:46:00Z",
        "approval withdrawn",
    )

    child = store.get_grant(grant.grant_hash)
    assert child is not None
    assert child.lifecycle.state is GrantState.REVOKED
    assert child.lifecycle.admitted_at == authority.admitted_at
    assert child.lifecycle.revoked_at == "2026-08-30T07:46:00Z"
    assert child.lifecycle.revocation_reason == "approval withdrawn"


def test_identical_grant_revoke_is_idempotent_but_conflict_is_rejected(
    gateway_cross_step,
):
    _store, _approval, service, _request, grant = _issued(gateway_cross_step)
    first = service.revoke_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:44:00Z",
        "operator cancellation",
    )
    retried = service.revoke_execution_grant(
        grant.grant_hash,
        "2026-08-30T07:44:00Z",
        "operator cancellation",
    )
    assert retried == first

    _assert_error(
        "EXECUTION_GRANT_CONFLICT",
        lambda: service.revoke_execution_grant(
            grant.grant_hash,
            "2026-08-30T07:45:00Z",
            "different cancellation",
        ),
    )
