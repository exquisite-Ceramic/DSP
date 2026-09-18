from __future__ import annotations

import pytest
from design_execution_reconciliation import ReconciliationError

from tests.execution_coordination._materialized_support import (
    execute,
    materialized_fixture,
)


class FailingPrepareStore:
    """模拟同一 Saga/Slice 已存在不同 admitted lineage 的 durable conflict。"""

    def __init__(self, events: list[tuple[str, object]]) -> None:
        self.events = events
        self.prepare_calls = []

    def prepare(self, intent):
        """记录 candidate 后以稳定冲突码拒绝，不允许 coordinator 继续 Host I/O。"""
        self.prepare_calls.append(intent)
        self.events.append(("prepare_dispatch_intent", intent))
        raise ReconciliationError(
            "DISPATCH_INTENT_CONFLICT",
            "fixture already contains a different admitted dispatch lineage",
        )

    def get(self, dispatch_intent_id):
        """满足 Task 7 constructor contract；本测试不会进入恢复读取。"""
        return None

    def mark_dispatched(self, *args, **kwargs):
        """prepare 失败后绝不应调用。"""
        raise AssertionError("mark_dispatched must not run after prepare conflict")

    def mark_outcome_unknown(self, *args, **kwargs):
        """prepare 失败后绝不应调用。"""
        raise AssertionError("mark_outcome_unknown must not run after prepare conflict")

    def mark_host_committed(self, *args, **kwargs):
        """prepare 失败后绝不应调用。"""
        raise AssertionError("mark_host_committed must not run after prepare conflict")

    def mark_safe_to_retry(self, *args, **kwargs):
        """prepare 失败后绝不应调用。"""
        raise AssertionError("mark_safe_to_retry must not run after prepare conflict")

    def mark_reconciled(self, *args, **kwargs):
        """满足 Task 7 constructor contract；Task 8 才消费 recovery reconcile。"""
        raise AssertionError("mark_reconciled is outside this test")


def _filtered_first_slice_events(fixture):
    """只抽取 Task 7 冻结的六个关键边界事件，忽略后续 Step33/convergence 细节。"""
    first_hash = fixture.ctx.execution_plan.execution_slices[0].execution_slice_hash
    names = {
        "reserve_slice_admission",
        "confirm_slice_admitted",
        "prepare_dispatch_intent",
        "mark_dispatched",
        "host.execute",
        "record_host_commit",
    }
    return tuple(
        name
        for name, payload in fixture.events
        if name in names
        and getattr(payload, "execution_slice_hash", payload) == first_hash
    )


def test_dispatch_intent_is_persisted_after_admission_and_before_host_io() -> None:
    """每个 Slice 必须先冻结 exact admitted lineage，再把同一稳定幂等键交给 Host。"""
    fixture = materialized_fixture(record_events=True)

    result = execute(fixture)

    assert result.status.value == "SUCCEEDED"
    assert _filtered_first_slice_events(fixture) == (
        "reserve_slice_admission",
        "confirm_slice_admitted",
        "prepare_dispatch_intent",
        "mark_dispatched",
        "host.execute",
        "record_host_commit",
    )

    for execution_slice in fixture.ctx.execution_plan.execution_slices:
        intent = fixture.dispatch_intents.prepared_by_slice[
            execution_slice.execution_slice_hash
        ]
        authority = next(
            item
            for item in fixture.ctx.authorities
            if item.execution_slice_hash == execution_slice.execution_slice_hash
        )
        binding_set = next(
            item
            for item in fixture.ctx.binding_sets
            if item.execution_slice_hash == execution_slice.execution_slice_hash
        )
        host_call = fixture.host_registry.ports[
            execution_slice.host_runtime_ref.host_type
        ].calls[0]
        dispatch_context = host_call[3]

        assert intent.grant_hash == authority.grant_hash
        assert intent.binding_set_hash == binding_set.binding_set_hash
        assert intent.host_instance_id == authority.host_instance_id
        assert intent.document_ref == execution_slice.host_runtime_ref.document_ref
        assert dispatch_context.dispatch_intent_id == str(intent.dispatch_intent_id)
        assert dispatch_context.idempotency_key == str(intent.idempotency_key)
        assert dispatch_context.saga_id == fixture.result_saga_id
        assert dispatch_context.execution_slice_hash == execution_slice.execution_slice_hash


def test_prepare_conflict_fails_closed_before_host_io() -> None:
    """post-admission lineage 冲突必须停在 durable intent 边界，不能触发任何 Host mutation。"""
    events: list[tuple[str, object]] = []
    conflict_store = FailingPrepareStore(events)
    fixture = materialized_fixture(
        dispatch_intents=conflict_store,
        events=events,
    )

    with pytest.raises(ReconciliationError) as exc:
        execute(fixture)

    assert exc.value.code == "DISPATCH_INTENT_CONFLICT"
    assert len(conflict_store.prepare_calls) == 1
    candidate = conflict_store.prepare_calls[0]
    first_slice = fixture.ctx.execution_plan.execution_slices[0]
    first_authority = fixture.ctx.authorities[0]
    first_binding = fixture.ctx.binding_sets[0]
    assert candidate.execution_slice_hash == first_slice.execution_slice_hash
    assert candidate.grant_hash == first_authority.grant_hash
    assert candidate.binding_set_hash == first_binding.binding_set_hash
    assert all(port.calls == [] for port in fixture.host_registry.ports.values())
