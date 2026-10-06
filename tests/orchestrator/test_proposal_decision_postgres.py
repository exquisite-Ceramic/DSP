"""Cross-Host Product Vertical Task 5：proposal decision PostgreSQL owner 契约。"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from importlib import import_module
from threading import Barrier

import psycopg
import pytest
from design_orchestrator.workflow_contracts import StableRef


@pytest.fixture
def product_task_postgres_dsn() -> str:
    """只在显式 PostgreSQL lane 执行 proposal decision owner acceptance。"""

    import os

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _api():
    """延迟加载 Task 5 新 owner，使 RED 精确落在 capability 缺失。"""

    contract = import_module("design_orchestrator.proposal_decision")
    postgres = import_module("design_orchestrator.proposal_decision_postgres")
    return (
        contract.HumanDecisionState,
        contract.ProposalContinuationState,
        postgres.create_postgres_proposal_decision_store,
    )


def _reset_schema(dsn: str) -> None:
    """每个测试从 fresh proposal-decision owner 开始，不复用前例状态。"""

    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS orchestrator_proposal CASCADE")


def _subject() -> StableRef:
    """返回一个 exact proposal subject identity。"""

    return StableRef("proposal-subject-task5", "a" * 64)


def test_gate_a_stale_wins_then_late_accept_cannot_advance(
    product_task_postgres_dsn: str,
) -> None:
    """Gate-A stale 一旦获胜，迟到 ACCEPT 只能重读同一 authoritative winner。"""

    human_state, continuation_state, factory = _api()
    _reset_schema(product_task_postgres_dsn)
    store = factory(product_task_postgres_dsn)
    try:
        stale = store.invalidate_gate_a(
            "task-task5-stale-first",
            "pause-task5",
            _subject(),
            "REVIT_REVISION_CHANGED",
        )
        late_accept = store.claim_accept(
            "task-task5-stale-first",
            "pause-task5",
            _subject(),
        )
    finally:
        store.close()

    assert stale == late_accept
    assert stale.human_decision is human_state.AWAITING
    assert stale.continuation is continuation_state.STALE_GATE_A
    assert stale.revision == 1
    assert stale.reason == "REVIT_REVISION_CHANGED"


def test_accept_wins_then_late_gate_a_invalidation_cannot_erase_accept(
    product_task_postgres_dsn: str,
) -> None:
    """ACCEPT 先获胜时，迟到 Gate-A invalidation 不得改写 human history。"""

    human_state, continuation_state, factory = _api()
    _reset_schema(product_task_postgres_dsn)
    store = factory(product_task_postgres_dsn)
    try:
        accepted = store.claim_accept(
            "task-task5-accept-first",
            "pause-task5",
            _subject(),
        )
        late_stale = store.invalidate_gate_a(
            "task-task5-accept-first",
            "pause-task5",
            _subject(),
            "AUTOCAD_REVISION_CHANGED",
        )
    finally:
        store.close()

    assert accepted == late_stale
    assert accepted.human_decision is human_state.ACCEPTED
    assert accepted.continuation is continuation_state.CONTINUABLE
    assert accepted.revision == 1
    assert accepted.reason is None


def test_reject_is_human_history_and_is_not_stale(
    product_task_postgres_dsn: str,
) -> None:
    """明确 REJECT 是 durable human decision，不能被建模成 stale。"""

    human_state, continuation_state, factory = _api()
    _reset_schema(product_task_postgres_dsn)
    store = factory(product_task_postgres_dsn)
    try:
        rejected = store.claim_reject(
            "task-task5-reject",
            "pause-task5",
            _subject(),
        )
        stale_attempt = store.invalidate_gate_a(
            "task-task5-reject",
            "pause-task5",
            _subject(),
            "MODEL_DRIFTED_AFTER_REJECT",
        )
    finally:
        store.close()

    assert rejected == stale_attempt
    assert rejected.human_decision is human_state.REJECTED
    assert rejected.continuation is continuation_state.CONTINUABLE
    assert rejected.reason is None


def test_gate_b_preserves_accepted_history_while_stopping_continuation(
    product_task_postgres_dsn: str,
) -> None:
    """Gate B 可使旧 task 不可继续，但不能把历史 ACCEPT 改回未决定。"""

    human_state, continuation_state, factory = _api()
    _reset_schema(product_task_postgres_dsn)
    store = factory(product_task_postgres_dsn)
    try:
        accepted = store.claim_accept(
            "task-task5-gate-b",
            "pause-task5",
            _subject(),
        )
        gate_b = store.invalidate_gate_b(
            "task-task5-gate-b",
            "pause-task5",
            _subject(),
            "PLANNING_CONTINUITY_MISMATCH",
        )
    finally:
        store.close()

    assert accepted.human_decision is human_state.ACCEPTED
    assert gate_b.human_decision is human_state.ACCEPTED
    assert gate_b.continuation is continuation_state.STALE_GATE_B
    assert gate_b.revision == accepted.revision + 1
    assert gate_b.reason == "PLANNING_CONTINUITY_MISMATCH"


def test_concurrent_accept_and_stale_have_one_authoritative_winner(
    product_task_postgres_dsn: str,
) -> None:
    """两个进程级 writer 竞争同一 expected state 时只能发布一个兼容 winner。"""

    human_state, continuation_state, factory = _api()
    _reset_schema(product_task_postgres_dsn)
    barrier = Barrier(2)

    def _attempt(kind: str):
        store = factory(product_task_postgres_dsn)
        try:
            barrier.wait(timeout=10)
            if kind == "accept":
                return store.claim_accept(
                    "task-task5-race",
                    "pause-task5",
                    _subject(),
                )
            return store.invalidate_gate_a(
                "task-task5-race",
                "pause-task5",
                _subject(),
                "CONCURRENT_DRIFT",
            )
        finally:
            store.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        accepted_future = executor.submit(_attempt, "accept")
        stale_future = executor.submit(_attempt, "stale")
        first = accepted_future.result(timeout=20)
        second = stale_future.result(timeout=20)

    verifier = factory(product_task_postgres_dsn)
    try:
        winner = verifier.get(
            "task-task5-race",
            "pause-task5",
            _subject(),
        )
    finally:
        verifier.close()

    assert winner is not None
    assert first == winner
    assert second == winner
    assert winner.revision == 1
    assert (
        winner.human_decision is human_state.ACCEPTED
        and winner.continuation is continuation_state.CONTINUABLE
    ) or (
        winner.human_decision is human_state.AWAITING
        and winner.continuation is continuation_state.STALE_GATE_A
    )


def test_same_task_pause_with_different_subject_is_not_same_authority(
    product_task_postgres_dsn: str,
) -> None:
    """同 task/pause 不能把另一个 proposal subject 当作可重放 decision。"""

    _, _, factory = _api()
    _reset_schema(product_task_postgres_dsn)
    store = factory(product_task_postgres_dsn)
    try:
        store.claim_accept("task-task5-subject", "pause-task5", _subject())
        with pytest.raises(ValueError, match="PROPOSAL_DECISION_SUBJECT_MISMATCH"):
            store.claim_accept(
                "task-task5-subject",
                "pause-task5",
                StableRef("other-subject", "b" * 64),
            )
    finally:
        store.close()
