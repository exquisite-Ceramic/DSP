"""HostDispatchIntentStore 的跨后端可复用行为契约。

这些断言只依赖公开 store API 与不可变领域对象，不读取内存字典或 SQL。任何后端都必须
在同一组 legal Saga/Slice lineage 上表现一致。
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from design_execution_reconciliation import (
    HostDispatchIntent,
    HostDispatchStatus,
    ReconciliationError,
    build_host_dispatch_intent,
)

IntentFactory = Callable[..., HostDispatchIntent]
ContractAssertion = Callable[[object, IntentFactory], None]

_PREPARED_AT = "2026-09-24T08:00:00Z"


def build_dispatch_intent_contract_factory(ctx, definition) -> IntentFactory:
    """把 shared assertions 绑定到真实 Saga 定义与对应的 admitted lineage。"""

    def _factory(
        *,
        index: int = 0,
        grant_hash: str | None = None,
        binding_set_hash: str | None = None,
    ) -> HostDispatchIntent:
        execution_slice = ctx.execution_plan.execution_slices[index]
        authority = ctx.authorities[index]
        return build_host_dispatch_intent(
            saga_id=definition.saga_id,
            execution_slice_hash=execution_slice.execution_slice_hash,
            grant_hash=authority.grant_hash if grant_hash is None else grant_hash,
            binding_set_hash=(
                authority.binding_set_hash
                if binding_set_hash is None
                else binding_set_hash
            ),
            host_instance_id=authority.host_instance_id,
            document_ref=execution_slice.host_runtime_ref.document_ref,
            expected_host_revision="41",
            prepared_at=_PREPARED_AT,
        )

    return _factory


def assert_lookup_and_replay_contract(store, intent_factory: IntentFactory) -> None:
    """prepare replay、id lookup 与 exact Saga/Slice lookup 必须指向同一 durable truth。"""
    candidate = intent_factory(index=0)
    prepared = store.prepare(candidate)

    assert prepared == candidate
    assert store.prepare(intent_factory(index=0)) == prepared
    assert store.get(prepared.dispatch_intent_id) == prepared
    assert (
        store.get_for_saga_slice(prepared.saga_id, prepared.execution_slice_hash)
        == prepared
    )

    dispatched = store.mark_dispatched(
        prepared.dispatch_intent_id,
        expected_revision=prepared.intent_revision,
        observed_at="2026-09-24T08:01:00Z",
    )
    assert dispatched.status is HostDispatchStatus.DISPATCHED
    assert store.get(prepared.dispatch_intent_id) == dispatched
    assert (
        store.get_for_saga_slice(prepared.saga_id, prepared.execution_slice_hash)
        == dispatched
    )


def assert_unknown_contract(store, intent_factory: IntentFactory) -> None:
    """DISPATCHED -> OUTCOME_UNKNOWN 必须保留 exact identity 并单调推进 revision。"""
    prepared = store.prepare(intent_factory(index=0))
    dispatched = store.mark_dispatched(
        prepared.dispatch_intent_id,
        expected_revision=prepared.intent_revision,
        observed_at="2026-09-24T08:10:00Z",
    )
    unknown = store.mark_outcome_unknown(
        dispatched.dispatch_intent_id,
        expected_revision=dispatched.intent_revision,
        failure_ref="transport:response-lost",
        observed_at="2026-09-24T08:11:00Z",
    )

    assert unknown.status is HostDispatchStatus.OUTCOME_UNKNOWN
    assert unknown.intent_revision == 2
    assert store.get(unknown.dispatch_intent_id) == unknown


def assert_committed_reconciled_contract(store, intent_factory: IntentFactory) -> None:
    """HOST_COMMITTED 与 RECONCILED 必须在同一 intent identity 上继续 CAS revision。"""
    prepared = store.prepare(intent_factory(index=0))
    dispatched = store.mark_dispatched(
        prepared.dispatch_intent_id,
        expected_revision=prepared.intent_revision,
        observed_at="2026-09-24T08:20:00Z",
    )
    committed = store.mark_host_committed(
        dispatched.dispatch_intent_id,
        expected_revision=dispatched.intent_revision,
        evidence_hash="1" * 64,
        observed_at="2026-09-24T08:21:00Z",
    )
    reconciled = store.mark_reconciled(
        committed.dispatch_intent_id,
        expected_revision=committed.intent_revision,
        evidence_hash="2" * 64,
        observed_at="2026-09-24T08:22:00Z",
    )

    assert committed.status is HostDispatchStatus.HOST_COMMITTED
    assert reconciled.status is HostDispatchStatus.RECONCILED
    assert reconciled.intent_revision == 3
    assert store.get(reconciled.dispatch_intent_id) == reconciled


def assert_safe_retry_contract(store, intent_factory: IntentFactory) -> None:
    """已有未提交证据时，DISPATCHED intent 可被 owner 标记为 SAFE_TO_RETRY。"""
    prepared = store.prepare(intent_factory(index=0))
    dispatched = store.mark_dispatched(
        prepared.dispatch_intent_id,
        expected_revision=prepared.intent_revision,
        observed_at="2026-09-24T08:30:00Z",
    )
    retryable = store.mark_safe_to_retry(
        dispatched.dispatch_intent_id,
        expected_revision=dispatched.intent_revision,
        evidence_ref="host:proved-not-committed",
        observed_at="2026-09-24T08:31:00Z",
    )

    assert retryable.status is HostDispatchStatus.SAFE_TO_RETRY
    assert retryable.intent_revision == 2
    assert store.get(retryable.dispatch_intent_id) == retryable


def assert_lineage_conflict_contract(store, intent_factory: IntentFactory) -> None:
    """同一 Saga/Slice 的 grant 或 binding 改变必须 fail closed，不能生成第二条 intent。"""
    prepared = store.prepare(intent_factory(index=0))

    for conflicting in (
        intent_factory(index=0, grant_hash="f" * 64),
        intent_factory(index=0, binding_set_hash="e" * 64),
    ):
        with pytest.raises(ReconciliationError) as exc:
            store.prepare(conflicting)
        assert exc.value.code == "DISPATCH_INTENT_CONFLICT"

    assert store.get(prepared.dispatch_intent_id) == prepared
    assert (
        store.get_for_saga_slice(prepared.saga_id, prepared.execution_slice_hash)
        == prepared
    )


def assert_cas_conflict_contract(store, intent_factory: IntentFactory) -> None:
    """stale expected_revision 不能覆盖已经提交的新 revision。"""
    prepared = store.prepare(intent_factory(index=0))
    dispatched = store.mark_dispatched(
        prepared.dispatch_intent_id,
        expected_revision=prepared.intent_revision,
        observed_at="2026-09-24T08:40:00Z",
    )

    with pytest.raises(ReconciliationError) as exc:
        store.mark_outcome_unknown(
            dispatched.dispatch_intent_id,
            expected_revision=prepared.intent_revision,
            failure_ref="transport:stale-writer",
            observed_at="2026-09-24T08:41:00Z",
        )
    assert exc.value.code == "DISPATCH_INTENT_CONFLICT"
    assert store.get(dispatched.dispatch_intent_id) == dispatched


__all__ = [
    "ContractAssertion",
    "IntentFactory",
    "assert_cas_conflict_contract",
    "assert_committed_reconciled_contract",
    "assert_lineage_conflict_contract",
    "assert_lookup_and_replay_contract",
    "assert_safe_retry_contract",
    "assert_unknown_contract",
    "build_dispatch_intent_contract_factory",
]
