from __future__ import annotations

from dataclasses import replace

import pytest
from design_gateway_authorization import (
    ApprovalAdmission,
    ApprovalConsumptionRequest,
    ApprovalConsumptionRequestV2,
    GatewayAuthorizationError,
    GatewayAuthorizationService,
    GatewayAuthorizationServiceV2,
    InMemoryGatewayAuthorizationStoreV2,
    compute_admission_fingerprint,
)
from tests.materialization_planning.conftest import build_case


def _approval_request_v2(case=None) -> ApprovalConsumptionRequestV2:
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


def _assert_error(code: str, operation, *, upstream_code: str | None = None) -> None:
    with pytest.raises(GatewayAuthorizationError) as exc:
        operation()
    assert exc.value.code == code
    if upstream_code is not None:
        assert exc.value.upstream_code == upstream_code


def test_v2_approval_consumes_exact_boundary_and_persists_existing_record_shape() -> None:
    request = _approval_request_v2()
    store = InMemoryGatewayAuthorizationStoreV2()
    record = GatewayAuthorizationServiceV2(store).consume_approval(request)

    assert record.changeset_hash == request.canonical_changeset.changeset_hash
    assert record.approved_scope_hash == request.approval_scope_boundary.scope_hash
    assert record.allowed_operations == ("set_wall_thickness.v1",)
    assert record.approval_id == f"AR-{record.approval_hash[:12]}"
    assert store.get_approval(record.approval_id).record == record


def test_v2_approval_preserves_one_time_admission_consumption() -> None:
    request = _approval_request_v2()
    service = GatewayAuthorizationServiceV2(InMemoryGatewayAuthorizationStoreV2())
    service.consume_approval(request)

    _assert_error(
        "APPROVAL_ADMISSION_ALREADY_CONSUMED",
        lambda: service.consume_approval(request),
    )


def test_v2_scope_or_changeset_integrity_failure_maps_owner_error() -> None:
    request = _approval_request_v2()
    service = GatewayAuthorizationServiceV2(InMemoryGatewayAuthorizationStoreV2())

    _assert_error(
        "APPROVAL_INTEGRITY_INVALID",
        lambda: service.consume_approval(
            replace(
                request,
                approval_scope_boundary=replace(
                    request.approval_scope_boundary,
                    scope_hash="f" * 64,
                ),
            )
        ),
        upstream_code="SCOPE_INTEGRITY_INVALID",
    )

    changeset = request.canonical_changeset
    root = replace(
        changeset.root_operation,
        arguments={**dict(changeset.root_operation.arguments), "tampered": True},
    )
    _assert_error(
        "APPROVAL_INTEGRITY_INVALID",
        lambda: service.consume_approval(
            replace(request, canonical_changeset=replace(changeset, root_operation=root))
        ),
        upstream_code="CHANGESET_INTEGRITY_INVALID",
    )


def test_v2_approval_requires_exact_three_way_changeset_and_scope_join() -> None:
    request = _approval_request_v2()
    service = GatewayAuthorizationServiceV2(InMemoryGatewayAuthorizationStoreV2())
    admission = replace(
        request.admission,
        approved_scope_hash="e" * 64,
        admission_fingerprint="0" * 64,
    )
    admission = replace(
        admission,
        admission_fingerprint=compute_admission_fingerprint(admission),
    )

    _assert_error(
        "APPROVAL_SCOPE_MISMATCH",
        lambda: service.consume_approval(replace(request, admission=admission)),
    )


def test_v1_service_still_rejects_v2_boundary_object() -> None:
    request = _approval_request_v2()
    v1_request = ApprovalConsumptionRequest(
        admission=request.admission,
        canonical_changeset=request.canonical_changeset,
        approval_scope_boundary=request.approval_scope_boundary,
        consumed_at=request.consumed_at,
    )

    _assert_error(
        "APPROVAL_INPUT_INVALID",
        lambda: GatewayAuthorizationService(
            InMemoryGatewayAuthorizationStoreV2()
        ).consume_approval(v1_request),
    )
