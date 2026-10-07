"""Task 13：evidence-body-first → Saga/dispatch-reference-second 顺序契约。"""

from __future__ import annotations

import pytest
from design_execution_coordination import MaterializedExecutionSagaCoordinator
from design_execution_reconciliation import SliceReconciliationStatusV2

from tests.execution_coordination._materialized_support import (
    TrackingReconciliation,
    execute,
    materialized_fixture,
)


class EvidenceTrackingReconciliation(TrackingReconciliation):
    """为 coordinator 顺序测试暴露 Task 13 evidence persistence seam。"""

    def __init__(self, events, *, crash_before_saga_commit: bool = False) -> None:
        super().__init__(events)
        self.crash_before_saga_commit = crash_before_saga_commit
        self.actual_deltas = {}
        self.bundles = {}
        self.verifications = {}
        self.last_saga_id = None

    def create_saga(self, *args, **kwargs):
        """记录真实 Saga id，测试不读取 backend 私有存储布局。"""

        stored = super().create_saga(*args, **kwargs)
        self.last_saga_id = stored.definition.saga_id
        return stored

    def persist_actual_delta(self, value):
        """模拟 owner body-first durable write。"""

        self.actual_deltas[value.actual_delta_hash] = value
        self.events.append(("persist_actual_delta", value.actual_delta_hash))
        return value.actual_delta_hash

    def persist_verification_bundle(self, value):
        """模拟 verification bundle 的 content-addressed durable write。"""

        self.bundles[value.evidence_bundle_hash] = value
        self.events.append(
            ("persist_verification_bundle", value.evidence_bundle_hash)
        )
        return value.evidence_bundle_hash

    def persist_verification_result(self, value):
        """模拟 semantic verification result 的 durable write。"""

        self.verifications[value.verification_hash] = value
        self.events.append(
            ("persist_verification_result", value.verification_hash)
        )
        return value.verification_hash

    def record_host_commit(self, saga_id, actual_delta, **kwargs):
        """可在 body durable 后、Saga reference 发布前模拟进程崩溃。"""

        if self.crash_before_saga_commit:
            self.events.append(("crash_before_saga_commit", actual_delta.actual_delta_hash))
            raise RuntimeError("SIMULATED_CRASH_AFTER_EVIDENCE_BODY")
        return super().record_host_commit(saga_id, actual_delta, **kwargs)

    def record_verification_result(self, saga_id, result, **kwargs):
        """记录 Saga verification hash 的发布时间。"""

        self.events.append(("record_verification_result", result.verification_hash))
        return self.service.record_verification_result(saga_id, result, **kwargs)


def _fixture_with_reconciliation(reconciliation):
    """复用真实 coordinator fixture，只替换 reconciliation facade。"""

    fixture = materialized_fixture(events=reconciliation.events)
    fixture.reconciliation = reconciliation
    fixture.coordinator = MaterializedExecutionSagaCoordinator(
        readiness_barrier=fixture.coordinator._readiness_barrier,
        reconciliation=reconciliation,
        host_registry=fixture.host_registry,
        dispatch_intents=fixture.dispatch_intents,
        evidence_port=fixture.evidence_port,
        convergence_verifier=fixture.convergence_verifier,
        clock=fixture.clock,
    )
    return fixture


def _event_index(events, name: str) -> int:
    """返回第一条指定事件的位置，缺失即让断言清晰失败。"""

    return next(index for index, item in enumerate(events) if item[0] == name)


def test_actual_delta_body_is_durable_before_dispatch_and_saga_commit_hash() -> None:
    """ActualDelta body 必须先于 dispatch evidence hash 与 Saga actual_delta_hash。"""

    events = []
    reconciliation = EvidenceTrackingReconciliation(events)
    fixture = _fixture_with_reconciliation(reconciliation)

    execute(fixture)

    assert _event_index(events, "persist_actual_delta") < _event_index(
        events,
        "mark_host_committed",
    )
    assert _event_index(events, "persist_actual_delta") < _event_index(
        events,
        "record_host_commit",
    )


def test_verification_bodies_are_durable_before_saga_verification_hash() -> None:
    """bundle/result body 都必须先 durable，Saga 才能发布 verification hash。"""

    events = []
    reconciliation = EvidenceTrackingReconciliation(events)
    fixture = _fixture_with_reconciliation(reconciliation)

    execute(fixture)

    assert _event_index(events, "persist_verification_bundle") < _event_index(
        events,
        "persist_verification_result",
    )
    assert _event_index(events, "persist_verification_result") < _event_index(
        events,
        "record_verification_result",
    )


def test_crash_after_body_before_saga_ref_leaves_safe_unreferenced_body() -> None:
    """body-first crash 允许孤立 immutable body，但 Saga 绝不能声称已记录 commit。"""

    events = []
    reconciliation = EvidenceTrackingReconciliation(
        events,
        crash_before_saga_commit=True,
    )
    fixture = _fixture_with_reconciliation(reconciliation)

    with pytest.raises(RuntimeError, match="SIMULATED_CRASH_AFTER_EVIDENCE_BODY"):
        execute(fixture)

    assert len(reconciliation.actual_deltas) == 1
    assert reconciliation.last_saga_id is not None
    stored = reconciliation.service.get_saga(reconciliation.last_saga_id)
    assert stored is not None
    committed_states = [
        state for state in stored.slice_states if state.actual_delta_hash is not None
    ]
    assert committed_states == []
    admitted_states = [
        state
        for state in stored.slice_states
        if state.status is SliceReconciliationStatusV2.ADMITTED
    ]
    assert len(admitted_states) == 1
