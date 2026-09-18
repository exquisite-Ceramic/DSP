from __future__ import annotations

from design_execution_reconciliation.dispatch_intent import (
    HostDispatchStatus,
    build_host_dispatch_intent,
)

_BASE_LINEAGE = {
    "saga_id": "SAGA-DISPATCH-001",
    "execution_slice_hash": "a" * 64,
    "grant_hash": "b" * 64,
    "binding_set_hash": "c" * 64,
    "host_instance_id": "autocad:instance-1",
    "document_ref": "doc:dispatch-1",
    "expected_host_revision": "41",
}


def _build_intent(**overrides):
    """构造 Task 6 纯领域 dispatch intent，便于只改变单个 lineage 因子。"""
    values = {**_BASE_LINEAGE, **overrides}
    return build_host_dispatch_intent(**values)


def test_dispatch_identity_is_deterministic_and_ignores_wall_clock() -> None:
    """同一不可变执行 lineage 在不同准备时间下必须复用完全相同的逻辑命令身份。"""
    first = _build_intent(prepared_at="2026-09-18T13:00:00Z")
    replay = _build_intent(prepared_at="2026-09-18T13:05:00Z")

    assert first.dispatch_intent_id == replay.dispatch_intent_id
    assert first.idempotency_key == replay.idempotency_key
    assert first.status is HostDispatchStatus.PREPARED
    assert first.intent_revision == 0
    assert replay.status is HostDispatchStatus.PREPARED
    assert replay.intent_revision == 0


def test_different_admitted_lineage_produces_different_candidate_identity() -> None:
    """grant 或 binding 改变时必须形成可检测的不同候选身份，而不能静默复用旧命令。"""
    baseline = _build_intent(prepared_at="2026-09-18T13:00:00Z")
    different_grant = _build_intent(
        grant_hash="d" * 64,
        prepared_at="2026-09-18T13:00:00Z",
    )
    different_binding = _build_intent(
        binding_set_hash="e" * 64,
        prepared_at="2026-09-18T13:00:00Z",
    )

    baseline_identity = (baseline.dispatch_intent_id, baseline.idempotency_key)
    assert (
        different_grant.dispatch_intent_id,
        different_grant.idempotency_key,
    ) != baseline_identity
    assert (
        different_binding.dispatch_intent_id,
        different_binding.idempotency_key,
    ) != baseline_identity
