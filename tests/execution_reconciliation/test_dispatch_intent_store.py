"""HostDispatchIntentStore 内存 reference backend 的公共 contract tests。"""

from __future__ import annotations

from tests.execution_reconciliation.dispatch_intent_store_contract import (
    ContractAssertion,
    assert_cas_conflict_contract,
    assert_committed_reconciled_contract,
    assert_lineage_conflict_contract,
    assert_lookup_and_replay_contract,
    assert_safe_retry_contract,
    assert_unknown_contract,
    build_dispatch_intent_contract_factory,
)
from tests.execution_reconciliation.saga_store_v2_contract import (
    build_saga_v2_contract_fixture,
)


def _run_contract(assertion: ContractAssertion) -> None:
    """每个 shared case 都创建全新的内存 owner，禁止跨 case 状态污染。"""
    # 延迟导入让 RED 发生在测试体内：当前仓库还没有发布这个 reference store。
    from design_execution_reconciliation import (
        HostDispatchIntentStore,
        InMemoryHostDispatchIntentStore,
    )

    assert HostDispatchIntentStore is not None
    ctx, definition = build_saga_v2_contract_fixture()
    store = InMemoryHostDispatchIntentStore()
    assertion(store, build_dispatch_intent_contract_factory(ctx, definition))


def test_in_memory_lookup_and_replay_contract() -> None:
    """内存 backend 必须支持 exact replay、id lookup 与 Saga/Slice lookup。"""
    _run_contract(assert_lookup_and_replay_contract)


def test_in_memory_unknown_contract() -> None:
    """内存 backend 必须持久表达 OUTCOME_UNKNOWN revision。"""
    _run_contract(assert_unknown_contract)


def test_in_memory_committed_reconciled_contract() -> None:
    """内存 backend 必须与 owner recovery 的 commit/reconcile 状态机保持一致。"""
    _run_contract(assert_committed_reconciled_contract)


def test_in_memory_safe_retry_contract() -> None:
    """内存 backend 必须支持显式 SAFE_TO_RETRY evidence 状态。"""
    _run_contract(assert_safe_retry_contract)


def test_in_memory_lineage_conflict_contract() -> None:
    """内存 backend 不得允许同 Saga/Slice 被第二套 admitted lineage 覆盖。"""
    _run_contract(assert_lineage_conflict_contract)


def test_in_memory_cas_conflict_contract() -> None:
    """内存 backend 必须拒绝 stale expected_revision。"""
    _run_contract(assert_cas_conflict_contract)
