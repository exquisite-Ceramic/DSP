"""Task 5：canonical owner 对 Gateway replay-safe approval seam 的接线回归。"""

from __future__ import annotations

from dataclasses import replace

from design_gateway_authorization import (
    ApprovalAdmission,
    GatewayAuthorizationServiceV2,
    InMemoryGatewayAuthorizationStoreV2,
    compute_admission_fingerprint,
)
from design_orchestrator.workflow_contracts import StableRef

from tests.orchestrator.test_canonical_owner_ports import (
    _Task7ApprovalAdmission,
    _Task7Clock,
    _task6_real_impact_case,
)


def test_canonical_owner_request_approval_replays_existing_gateway_approval() -> None:
    """同一 ChangeSet 的 approval retry 必须返回既有 Gateway truth，而不是再次 strict consume。"""

    gateway_store = InMemoryGatewayAuthorizationStoreV2()
    gateway = GatewayAuthorizationServiceV2(gateway_store)
    admission_port = _Task7ApprovalAdmission()
    (
        adapter,
        bound_ref,
        impact_ref,
        _,
        _,
        approval_scope_store,
        changeset_store,
        _,
    ) = _task6_real_impact_case(
        overrides={
            "gateway_authorization": gateway,
            "gateway_authorization_store": gateway_store,
            "coordination_clock": _Task7Clock(),
            "approval_admission": admission_port,
        }
    )
    changeset_ref = adapter.build_changeset("task-5-replay", bound_ref, impact_ref)
    changeset = changeset_store.get(changeset_ref.ref_id)
    boundary = approval_scope_store.get_boundary(f"SCOPE-{changeset.changeset_id}")

    draft = ApprovalAdmission(
        admission_id="ADM-TASK5-REPLAY",
        changeset_hash=changeset.changeset_hash,
        approved_scope_hash=boundary.scope_hash,
        semantic_environment_ref=changeset.semantic_environment_ref,
        approver="local:operator",
        policy_snapshot_hash="5" * 64,
        policy_allowed_operations=(changeset.root_operation.canonical_operation,),
        approved_at="2026-09-06T09:00:00Z",
        expires_at="2026-09-06T17:00:00Z",
        admission_fingerprint="0" * 64,
    )
    admission_port.admission = replace(
        draft,
        admission_fingerprint=compute_admission_fingerprint(draft),
    )

    first = adapter.request_approval(changeset_ref)
    replayed = adapter.request_approval(changeset_ref)

    assert isinstance(first, StableRef)
    assert replayed == first
    assert admission_port.calls == [changeset_ref, changeset_ref]
