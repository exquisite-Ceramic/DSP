"""Grant lineage locking, provider-switch, and issuance idempotency for Step32."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest
from conftest import build_real_binding_set
from design_gateway_authorization import (
    GatewayAuthorizationError,
    GatewayAuthorizationService,
    GrantLifecycle,
    GrantState,
    InMemoryGatewayAuthorizationStore,
    StoredGrant,
    compute_grant_hash,
)


def _rehash_grant(grant, **changes):
    draft = replace(
        grant,
        grant_id="EG-PENDING",
        grant_hash="0" * 64,
        **changes,
    )
    grant_hash = compute_grant_hash(
        approval_hash=draft.approval_hash,
        changeset_hash=draft.changeset_hash,
        approved_scope_hash=draft.approved_scope_hash,
        execution_slice_hash=draft.execution_slice_hash,
        binding_set_hash=draft.binding_set_hash,
        host_instance_id=draft.host_instance_id,
        allowed_operations=draft.allowed_operations,
        issued_at=draft.issued_at,
        expires_at=draft.expires_at,
    )
    return replace(
        draft,
        grant_id=f"EG-{grant_hash[:12]}",
        grant_hash=grant_hash,
    )


def _seed_lifecycle(store, grant, lifecycle):
    lineage = (grant.approval_hash, grant.execution_slice_hash)
    with store._lock:
        store._grants[grant.grant_hash] = StoredGrant(grant, lifecycle)
        store._lineages[lineage] = [grant.grant_hash]


def _initial_grant(gateway_cross_step):
    store, _approval, execution_slice, _binding_set, request = gateway_cross_step
    service = GatewayAuthorizationService(store)
    grant = service.issue_execution_grant(request)
    return store, service, execution_slice, request, grant


def _alternate_request(execution_slice, request, *, issued_at="2026-08-30T07:50:00Z"):
    binding_set = build_real_binding_set(
        execution_slice,
        valid_until="2026-08-30T09:30:00Z",
    )
    assert binding_set.binding_set_hash != request.provider_binding_set.binding_set_hash
    return replace(
        request,
        provider_binding_set=binding_set,
        issued_at=issued_at,
    )


def _assert_error(code, callable_):
    with pytest.raises(GatewayAuthorizationError) as exc:
        callable_()
    assert exc.value.code == code


def test_active_same_binding_retry_returns_original_grant_unchanged(gateway_cross_step):
    _store, service, _slice, request, original = _initial_grant(gateway_cross_step)
    retried = service.issue_execution_grant(
        replace(request, issued_at="2026-08-30T07:50:00Z")
    )
    assert retried == original
    assert retried.grant_hash == original.grant_hash
    assert retried.issued_at == original.issued_at
    assert retried.expires_at == original.expires_at


def test_active_different_binding_supersedes_old_grant(gateway_cross_step):
    store, service, execution_slice, request, original = _initial_grant(gateway_cross_step)
    replacement = service.issue_execution_grant(
        _alternate_request(execution_slice, request)
    )

    assert replacement.grant_hash != original.grant_hash
    old = store.get_grant(original.grant_hash)
    new = store.get_grant(replacement.grant_hash)
    assert old is not None and new is not None
    assert old.lifecycle.state is GrantState.REVOKED
    assert old.lifecycle.superseded_by_grant_id == replacement.grant_id
    assert new.lifecycle.state is GrantState.ACTIVE


def test_admitted_same_binding_returns_original_grant(gateway_cross_step):
    store, service, _slice, request, original = _initial_grant(gateway_cross_step)
    _seed_lifecycle(
        store,
        original,
        GrantLifecycle(GrantState.ADMITTED, admitted_at="2026-08-30T07:45:00Z"),
    )

    retried = service.issue_execution_grant(
        replace(request, issued_at="2026-08-30T07:50:00Z")
    )
    assert retried == original


def test_admitted_different_binding_is_rejected(gateway_cross_step):
    store, service, execution_slice, request, original = _initial_grant(gateway_cross_step)
    _seed_lifecycle(
        store,
        original,
        GrantLifecycle(GrantState.ADMITTED, admitted_at="2026-08-30T07:45:00Z"),
    )
    alternate = _alternate_request(execution_slice, request)

    _assert_error(
        "EXECUTION_GRANT_ALREADY_ADMITTED",
        lambda: service.issue_execution_grant(alternate),
    )


def test_revoked_same_binding_is_rejected(gateway_cross_step):
    store, service, _slice, request, original = _initial_grant(gateway_cross_step)
    _seed_lifecycle(
        store,
        original,
        GrantLifecycle(
            GrantState.REVOKED,
            revoked_at="2026-08-30T07:45:00Z",
            revocation_reason="operator cancellation",
        ),
    )

    _assert_error(
        "EXECUTION_GRANT_REVOKED",
        lambda: service.issue_execution_grant(
            replace(request, issued_at="2026-08-30T07:50:00Z")
        ),
    )


def test_revoked_different_binding_allows_new_grant(gateway_cross_step):
    store, service, execution_slice, request, original = _initial_grant(gateway_cross_step)
    _seed_lifecycle(
        store,
        original,
        GrantLifecycle(
            GrantState.REVOKED,
            revoked_at="2026-08-30T07:45:00Z",
            revocation_reason="operator cancellation",
        ),
    )

    replacement = service.issue_execution_grant(
        _alternate_request(execution_slice, request)
    )
    assert replacement.grant_hash != original.grant_hash
    assert store.get_grant(replacement.grant_hash).lifecycle.state is GrantState.ACTIVE


def test_expired_same_binding_is_rejected(gateway_cross_step):
    store, _service, _slice, _request, original = _initial_grant(gateway_cross_step)
    candidate = _rehash_grant(
        original,
        issued_at="2026-08-30T08:31:00Z",
    )

    _assert_error(
        "EXECUTION_GRANT_EXPIRED",
        lambda: store.issue_or_get_grant(candidate),
    )


def test_expired_grant_allows_fresh_different_binding(gateway_cross_step):
    store, service, execution_slice, request, original = _initial_grant(gateway_cross_step)
    replacement = service.issue_execution_grant(
        _alternate_request(
            execution_slice,
            request,
            issued_at="2026-08-30T08:31:00Z",
        )
    )

    assert replacement.grant_hash != original.grant_hash
    old = store.get_grant(original.grant_hash)
    new = store.get_grant(replacement.grant_hash)
    assert old is not None and new is not None
    assert old.lifecycle.state is GrantState.EXPIRED
    assert new.lifecycle.state is GrantState.ACTIVE


def test_same_lineage_same_binding_concurrency_creates_one_grant_hash(gateway_cross_step):
    _old_store, _service, _slice, _request, candidate = _initial_grant(gateway_cross_step)
    store = InMemoryGatewayAuthorizationStore()

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: store.issue_or_get_grant(candidate), range(32)))

    assert {item.grant_hash for item in results} == {candidate.grant_hash}
    lineage = (candidate.approval_hash, candidate.execution_slice_hash)
    assert store._lineages[lineage] == [candidate.grant_hash]
    stored = store.get_grant(candidate.grant_hash)
    assert stored is not None
    assert stored.lifecycle.state is GrantState.ACTIVE
