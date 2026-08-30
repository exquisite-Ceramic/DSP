"""Deterministic ApprovalAdmission consumption pipeline for Step32."""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_gateway_authorization import (
    GatewayAuthorizationError,
    GatewayAuthorizationService,
    compute_admission_fingerprint,
    compute_approval_hash,
)


def _resign(admission, **changes):
    draft = replace(admission, admission_fingerprint="0" * 64, **changes)
    return replace(draft, admission_fingerprint=compute_admission_fingerprint(draft))


def _assert_error(code, request, store, *, upstream_code=None):
    service = GatewayAuthorizationService(store)
    with pytest.raises(GatewayAuthorizationError) as exc:
        service.consume_approval(request)
    assert exc.value.code == code
    if upstream_code is not None:
        assert exc.value.upstream_code == upstream_code
    assert store.calls == []


def test_admission_fingerprint_mismatch_precedes_all_other_validation(
    valid_approval_request,
    spy_store,
) -> None:
    admission = replace(
        valid_approval_request.admission,
        admission_fingerprint="f" * 64,
        expires_at="2026-08-30T07:00:00Z",
    )
    request = replace(valid_approval_request, admission=admission)
    _assert_error("APPROVAL_INTEGRITY_INVALID", request, spy_store)


def test_expired_admission_is_rejected_before_upstream_integrity(
    valid_approval_request,
    spy_store,
) -> None:
    admission = _resign(
        valid_approval_request.admission,
        expires_at="2026-08-30T07:30:00Z",
    )
    boundary = replace(valid_approval_request.approval_scope_boundary, scope_hash="f" * 64)
    request = replace(
        valid_approval_request,
        admission=admission,
        approval_scope_boundary=boundary,
    )
    _assert_error("APPROVAL_ADMISSION_EXPIRED", request, spy_store)


def test_step28_integrity_failure_is_mapped_with_upstream_code(
    valid_approval_request,
    spy_store,
) -> None:
    boundary = replace(valid_approval_request.approval_scope_boundary, scope_hash="f" * 64)
    request = replace(valid_approval_request, approval_scope_boundary=boundary)
    _assert_error(
        "APPROVAL_INTEGRITY_INVALID",
        request,
        spy_store,
        upstream_code="SCOPE_INTEGRITY_INVALID",
    )


def test_step29_integrity_failure_is_mapped_with_upstream_code(
    valid_approval_request,
    spy_store,
) -> None:
    changeset = valid_approval_request.canonical_changeset
    root = replace(
        changeset.root_operation,
        arguments={**dict(changeset.root_operation.arguments), "tampered": True},
    )
    request = replace(
        valid_approval_request,
        canonical_changeset=replace(changeset, root_operation=root),
    )
    _assert_error(
        "APPROVAL_INTEGRITY_INVALID",
        request,
        spy_store,
        upstream_code="CHANGESET_INTEGRITY_INVALID",
    )


def test_scope_body_join_mismatch_is_owner_integrity_failure(
    valid_approval_request,
    spy_store,
) -> None:
    changeset = valid_approval_request.canonical_changeset
    scope_ref = replace(
        changeset.approval_scope_definition_ref,
        scope_body_hash="e" * 64,
    )
    request = replace(
        valid_approval_request,
        canonical_changeset=replace(
            changeset,
            approval_scope_definition_ref=scope_ref,
        ),
    )
    _assert_error(
        "APPROVAL_INTEGRITY_INVALID",
        request,
        spy_store,
        upstream_code="CHANGESET_INTEGRITY_INVALID",
    )


def test_three_way_changeset_hash_mismatch_is_rejected(
    valid_approval_request,
    spy_store,
) -> None:
    admission = _resign(valid_approval_request.admission, changeset_hash="e" * 64)
    request = replace(valid_approval_request, admission=admission)
    _assert_error("APPROVAL_SCOPE_MISMATCH", request, spy_store)


def test_approved_scope_hash_mismatch_is_rejected(
    valid_approval_request,
    spy_store,
) -> None:
    admission = _resign(valid_approval_request.admission, approved_scope_hash="e" * 64)
    request = replace(valid_approval_request, admission=admission)
    _assert_error("APPROVAL_SCOPE_MISMATCH", request, spy_store)


def test_semantic_environment_mismatch_is_rejected(
    valid_approval_request,
    spy_store,
) -> None:
    admission = _resign(valid_approval_request.admission, semantic_environment_ref="ENV-OTHER")
    request = replace(valid_approval_request, admission=admission)
    _assert_error("SEMANTIC_ENVIRONMENT_MISMATCH", request, spy_store)


def test_operation_outside_policy_is_rejected(
    valid_approval_request,
    spy_store,
) -> None:
    admission = _resign(
        valid_approval_request.admission,
        policy_allowed_operations=("copy.v1",),
    )
    request = replace(valid_approval_request, admission=admission)
    _assert_error("APPROVAL_OPERATION_FORBIDDEN", request, spy_store)


def test_valid_approval_persists_exact_least_privilege_authority(
    valid_approval_request,
    spy_store,
) -> None:
    record = GatewayAuthorizationService(spy_store).consume_approval(valid_approval_request)
    changeset = valid_approval_request.canonical_changeset
    expected_operations = {
        changeset.root_operation.canonical_operation,
        *(operation.canonical_operation for operation in changeset.derived_operations),
    }
    assert set(record.allowed_operations) == expected_operations
    assert set(record.allowed_operations) <= set(
        valid_approval_request.admission.policy_allowed_operations
    )
    assert record.approved_at == valid_approval_request.admission.approved_at
    assert record.consumed_at == valid_approval_request.consumed_at
    assert record.approval_id == f"AR-{record.approval_hash[:12]}"
    assert record.approval_hash == compute_approval_hash(
        admission_fingerprint=record.admission_fingerprint,
        changeset_hash=record.changeset_hash,
        approved_scope_hash=record.approved_scope_hash,
        semantic_environment_ref=record.semantic_environment_ref,
        approver=record.approver,
        policy_snapshot_hash=record.policy_snapshot_hash,
        allowed_operations=record.allowed_operations,
        approved_at=record.approved_at,
    )
    assert len(spy_store.calls) == 1
    assert spy_store.calls[0][2] == record
