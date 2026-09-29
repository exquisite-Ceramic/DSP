"""Task 5：Gateway V2 对已消费 configured-policy admission 的 same-owner replay 契约。"""

from __future__ import annotations

from dataclasses import replace

import pytest
from design_approval_scope import bind_changeset_v2, bind_topology_snapshot_v2
from design_changeset import validate_changeset_integrity_v2
from design_gateway_authorization import (
    ApprovalAdmission,
    ApprovalConsumptionRequestV2,
    GatewayAuthorizationError,
    GatewayAuthorizationServiceV2,
    InMemoryGatewayAuthorizationStoreV2,
    StoredApproval,
    compute_admission_fingerprint,
)

from tests.materialization_planning._support import build_case


def _case():
    """构造真实合法的 V2 ChangeSet/scope owner artifacts 与 configured-policy admission。"""

    case = build_case(project_id="project-id")
    scope_v2 = bind_topology_snapshot_v2(
        case.scope_v1,
        case.topology.topology_snapshot_hash,
    )
    boundary = bind_changeset_v2(
        scope_v2,
        case.changeset.changeset_hash,
        f"SCOPE-{case.changeset.changeset_id}",
    )
    validate_changeset_integrity_v2(case.changeset, boundary)
    draft = ApprovalAdmission(
        admission_id="ADM-REPLAY-001",
        changeset_hash=case.changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        semantic_environment_ref=case.changeset.semantic_environment_ref,
        approver="local:operator",
        policy_snapshot_hash="a" * 64,
        policy_allowed_operations=("set_wall_thickness.v1",),
        approved_at="2026-09-29T10:00:00Z",
        expires_at="2026-09-29T10:15:00Z",
        admission_fingerprint="0" * 64,
    )
    admission = replace(
        draft,
        admission_fingerprint=compute_admission_fingerprint(draft),
    )
    return case.changeset, boundary, admission


def _consume_or_get(service, request):
    """延迟取得 Task 5 新 Gateway seam，使尚未实现时形成明确 TDD RED。"""

    method = getattr(service, "consume_or_get_approval", None)
    assert callable(method), "GatewayAuthorizationServiceV2.consume_or_get_approval 尚未实现"
    return method(request)


def test_same_owner_retry_after_admission_expiry_returns_exact_existing_approval() -> None:
    """首次消费后即使 admission 已过期，同 id/fingerprint retry 仍返回原 ApprovalRecord。"""

    changeset, boundary, admission = _case()
    store = InMemoryGatewayAuthorizationStoreV2()
    service = GatewayAuthorizationServiceV2(store)
    first_request = ApprovalConsumptionRequestV2(
        admission=admission,
        canonical_changeset=changeset,
        approval_scope_boundary=boundary,
        consumed_at="2026-09-29T10:05:00Z",
    )
    retry_request = ApprovalConsumptionRequestV2(
        admission=admission,
        canonical_changeset=changeset,
        approval_scope_boundary=boundary,
        consumed_at="2026-09-29T11:00:00Z",
    )

    first = _consume_or_get(service, first_request)
    replayed = _consume_or_get(service, retry_request)

    assert replayed == first
    assert replayed.consumed_at == "2026-09-29T10:05:00Z"


def test_same_admission_id_with_different_fingerprint_still_conflicts() -> None:
    """same-owner replay 只能匹配 exact admission fingerprint，不能把 id 当成 authority。"""

    changeset, boundary, admission = _case()
    store = InMemoryGatewayAuthorizationStoreV2()
    service = GatewayAuthorizationServiceV2(store)
    first_request = ApprovalConsumptionRequestV2(
        admission=admission,
        canonical_changeset=changeset,
        approval_scope_boundary=boundary,
        consumed_at="2026-09-29T10:05:00Z",
    )
    _consume_or_get(service, first_request)

    changed_draft = replace(
        admission,
        approver="local:other-operator",
        admission_fingerprint="0" * 64,
    )
    changed = replace(
        changed_draft,
        admission_fingerprint=compute_admission_fingerprint(changed_draft),
    )
    conflicting_request = ApprovalConsumptionRequestV2(
        admission=changed,
        canonical_changeset=changeset,
        approval_scope_boundary=boundary,
        consumed_at="2026-09-29T10:06:00Z",
    )

    with pytest.raises(GatewayAuthorizationError) as exc_info:
        _consume_or_get(service, conflicting_request)

    assert exc_info.value.code == "APPROVAL_ADMISSION_CONFLICT"


def test_replay_rejects_corrupt_stored_approval_authority_hash() -> None:
    """read seam 读到已消费记录后必须重新验证 immutable approval hash，不能盲信 store row。"""

    changeset, boundary, admission = _case()
    store = InMemoryGatewayAuthorizationStoreV2()
    service = GatewayAuthorizationServiceV2(store)
    first_request = ApprovalConsumptionRequestV2(
        admission=admission,
        canonical_changeset=changeset,
        approval_scope_boundary=boundary,
        consumed_at="2026-09-29T10:05:00Z",
    )
    first = _consume_or_get(service, first_request)

    stored = store.get_approval(first.approval_id)
    assert stored is not None
    corrupt_record = replace(stored.record, approval_hash="f" * 64)
    store._approvals[first.approval_id] = StoredApproval(
        record=corrupt_record,
        lifecycle=stored.lifecycle,
    )
    retry_request = ApprovalConsumptionRequestV2(
        admission=admission,
        canonical_changeset=changeset,
        approval_scope_boundary=boundary,
        consumed_at="2026-09-29T10:06:00Z",
    )

    with pytest.raises(GatewayAuthorizationError) as exc_info:
        _consume_or_get(service, retry_request)

    assert exc_info.value.code == "APPROVAL_INTEGRITY_INVALID"
