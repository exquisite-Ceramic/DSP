from __future__ import annotations

from uuid import UUID

from design_execution_reconciliation import InMemoryExecutionSagaStoreV2
from design_execution_reconciliation.delivery import (
    build_saga_transition_event,
    compute_event_fingerprint,
)

from tests.execution_reconciliation.saga_store_v2_contract import (
    build_saga_v2_contract_fixture,
)


def _ready_saga():
    """构造一个真实的 READY Saga V2 持久状态，避免测试伪造领域对象。"""
    _ctx, definition = build_saga_v2_contract_fixture()
    return InMemoryExecutionSagaStoreV2().create_saga(definition)


def test_saga_transition_event_is_deterministic() -> None:
    """同一 Saga revision 必须产生稳定 event id、fingerprint 与最小载荷。"""
    ready_saga = _ready_saga()

    first = build_saga_transition_event(
        None,
        ready_saga,
        occurred_at="2026-09-16T16:00:00Z",
    )
    second = build_saga_transition_event(
        None,
        ready_saga,
        occurred_at="2026-09-16T16:00:00Z",
    )

    assert first == second
    assert isinstance(first.event_id, UUID)
    assert len(first.event_fingerprint) == 64
    assert first.producer_owner == "execution_saga"
    assert first.aggregate_ref == ready_saga.definition.saga_id
    assert first.aggregate_revision == ready_saga.saga_revision
    assert set(first.payload) == {
        "saga_id",
        "saga_revision",
        "saga_status",
        "saga_definition_hash",
    }


def test_event_fingerprint_commits_immutable_event_content() -> None:
    """fingerprint 必须提交业务身份与载荷，而不能被审计时间影响。"""
    base = dict(
        producer_owner="execution_saga",
        event_type="SagaTransitioned",
        aggregate_ref="saga-1",
        aggregate_revision=3,
        payload={"saga_status": "EXECUTING"},
    )

    first = compute_event_fingerprint(**base)

    assert first == compute_event_fingerprint(**base)
    assert first != compute_event_fingerprint(
        **{**base, "payload": {"saga_status": "SUCCEEDED"}}
    )
