from __future__ import annotations

import os

import pytest
from design_execution_reconciliation import ReconciliationError

from tests.execution_reconciliation.saga_store_v2_contract import (
    build_saga_v2_contract_fixture,
)

pytestmark = pytest.mark.skipif(
    not os.environ.get("DSP_TEST_POSTGRES_DSN"),
    reason="DSP_TEST_POSTGRES_DSN is required",
)

_PREPARED_AT = "2026-09-18T13:00:00Z"


def _postgres_dsn() -> str:
    """只允许在显式配置的真实 PostgreSQL contract lane 中运行。"""
    return os.environ["DSP_TEST_POSTGRES_DSN"].strip()


def _postgres_api():
    """延迟加载数据库帮助器，避免普通离线 collection 强依赖 PostgreSQL。"""
    from design_execution_reconciliation.postgres import (
        apply_execution_saga_migrations,
        connect_postgres,
    )

    return apply_execution_saga_migrations, connect_postgres


def _dispatch_api():
    """延迟加载 Task 6 production API，使 RED 精确暴露缺失的实现模块。"""
    from design_execution_reconciliation.dispatch_intent import (
        HostDispatchStatus,
        build_host_dispatch_intent,
    )
    from design_execution_reconciliation.postgres_dispatch_intent import (
        PostgresHostDispatchIntentStore,
    )

    return HostDispatchStatus, build_host_dispatch_intent, PostgresHostDispatchIntentStore


def _saga_store_type():
    """复用真实 Saga PostgreSQL adapter 创建 host_dispatch_intent 的 FK 父记录。"""
    from design_execution_reconciliation.postgres_saga_store_v2 import (
        PostgresExecutionSagaStoreV2,
    )

    return PostgresExecutionSagaStoreV2


def _truncate_owner_state(conn) -> None:
    """按 FK 依赖顺序清空 owner-local durable state，不使用跨边界 CASCADE。"""
    conn.execute(
        """
        TRUNCATE TABLE
            execution_saga.host_dispatch_observation,
            execution_saga.host_dispatch_intent,
            execution_saga.inbox_receipt,
            execution_saga.outbox,
            execution_saga.saga_v2
        """
    )


def _prepare_database() -> tuple[str, object, object]:
    """应用 migration、清空状态并创建一个真实 Saga，供 intent FK 与 lineage 使用。"""
    dsn = _postgres_dsn()
    apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        apply_migrations(conn)
        with conn.transaction():
            _truncate_owner_state(conn)
    finally:
        conn.close()

    ctx, definition = build_saga_v2_contract_fixture()
    saga_store = _saga_store_type()(dsn)
    try:
        saga_store.create_saga(definition)
    finally:
        saga_store.close()
    return dsn, ctx, definition


def _intent(ctx, definition, *, index: int = 0, **overrides):
    """从真实 admitted authority + ExecutionSliceV2 构造精确 post-admission candidate。"""
    _status, build_intent, _store_type = _dispatch_api()
    execution_slice = ctx.execution_plan.execution_slices[index]
    authority = ctx.authorities[index]
    values = {
        "saga_id": definition.saga_id,
        "execution_slice_hash": execution_slice.execution_slice_hash,
        "grant_hash": authority.grant_hash,
        "binding_set_hash": authority.binding_set_hash,
        "host_instance_id": authority.host_instance_id,
        "document_ref": execution_slice.host_runtime_ref.document_ref,
        "expected_host_revision": "41",
        "prepared_at": _PREPARED_AT,
    }
    values.update(overrides)
    return build_intent(**values)


def _row_count_for_slice(dsn: str, saga_id: str, execution_slice_hash: str) -> int:
    """直接读取持久行数，证明 lineage conflict 不会偷偷插入第二条 executable intent。"""
    _apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        return conn.execute(
            """
            SELECT count(*)
            FROM execution_saga.host_dispatch_intent
            WHERE saga_id = %s AND execution_slice_hash = %s
            """,
            (saga_id, execution_slice_hash),
        ).fetchone()[0]
    finally:
        conn.close()


def _observation_kinds(dsn: str, dispatch_intent_id) -> tuple[str, ...]:
    """按 revision 对应的写入顺序读取 append-only recovery observation。"""
    _apply_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        rows = conn.execute(
            """
            SELECT observation_kind
            FROM execution_saga.host_dispatch_observation
            WHERE dispatch_intent_id = %s
            ORDER BY observed_at, observation_id
            """,
            (dispatch_intent_id,),
        ).fetchall()
        return tuple(row[0] for row in rows)
    finally:
        conn.close()


def test_prepare_replays_same_lineage_and_rejects_second_post_admission_lineage() -> None:
    """同一 Saga/Slice 只能存在一个 admitted Host dispatch lineage。"""
    dsn, ctx, definition = _prepare_database()
    _status, _builder, store_type = _dispatch_api()
    store = store_type(dsn)
    first_candidate = _intent(ctx, definition)
    try:
        first = store.prepare(first_candidate)
        replay = store.prepare(
            _intent(
                ctx,
                definition,
                # replay 时间可以不同，但 immutable execution lineage 不变。
                prepared_at="2026-09-18T13:05:00Z",
            )
        )
        assert replay == first

        conflicting = _intent(ctx, definition, grant_hash="f" * 64)
        with pytest.raises(ReconciliationError) as exc:
            store.prepare(conflicting)
        assert exc.value.code == "DISPATCH_INTENT_CONFLICT"
        assert store.get(first.dispatch_intent_id) == first
    finally:
        store.close()

    assert _row_count_for_slice(
        dsn,
        definition.saga_id,
        first_candidate.execution_slice_hash,
    ) == 1


def test_restart_durability_and_stale_writer_cas_allow_only_one_transition() -> None:
    """进程重启后 identity/revision 必须可恢复，同 revision 的两个 writer 只能一个成功。"""
    dsn, ctx, definition = _prepare_database()
    _status, _builder, store_type = _dispatch_api()
    intent = _intent(ctx, definition)

    store_a = store_type(dsn)
    try:
        prepared = store_a.prepare(intent)
    finally:
        store_a.close()

    store_b = store_type(dsn)
    store_c = store_type(dsn)
    try:
        observed_b = store_b.get(prepared.dispatch_intent_id)
        observed_c = store_c.get(prepared.dispatch_intent_id)
        assert observed_b == observed_c == prepared

        winner = store_b.mark_dispatched(
            prepared.dispatch_intent_id,
            expected_revision=prepared.intent_revision,
            observed_at="2026-09-18T13:10:00Z",
        )
        assert winner.intent_revision == prepared.intent_revision + 1

        with pytest.raises(ReconciliationError) as exc:
            store_c.mark_outcome_unknown(
                prepared.dispatch_intent_id,
                expected_revision=observed_c.intent_revision,
                failure_ref="transport:timeout",
                observed_at="2026-09-18T13:10:01Z",
            )
        assert exc.value.code == "DISPATCH_INTENT_CONFLICT"
        assert store_c.get(prepared.dispatch_intent_id) == winner
    finally:
        store_b.close()
        store_c.close()


def test_recovery_state_changes_append_observation_and_increment_revision_once() -> None:
    """每次 CAS 状态改变与 observation 必须在同一个 owner-local transaction 内落库。"""
    dsn, ctx, definition = _prepare_database()
    status_type, _builder, store_type = _dispatch_api()
    store = store_type(dsn)
    try:
        primary = store.prepare(_intent(ctx, definition, index=0))
        assert primary.status is status_type.PREPARED

        primary = store.mark_dispatched(
            primary.dispatch_intent_id,
            expected_revision=primary.intent_revision,
            observed_at="2026-09-18T13:20:00Z",
        )
        primary = store.mark_outcome_unknown(
            primary.dispatch_intent_id,
            expected_revision=primary.intent_revision,
            failure_ref="transport:response-lost",
            observed_at="2026-09-18T13:21:00Z",
        )
        primary = store.mark_host_committed(
            primary.dispatch_intent_id,
            expected_revision=primary.intent_revision,
            evidence_hash="1" * 64,
            observed_at="2026-09-18T13:22:00Z",
        )
        primary = store.mark_reconciled(
            primary.dispatch_intent_id,
            expected_revision=primary.intent_revision,
            evidence_hash="2" * 64,
            observed_at="2026-09-18T13:23:00Z",
        )
        assert primary.status is status_type.RECONCILED
        assert primary.intent_revision == 4

        retryable = store.prepare(_intent(ctx, definition, index=1))
        retryable = store.mark_dispatched(
            retryable.dispatch_intent_id,
            expected_revision=retryable.intent_revision,
            observed_at="2026-09-18T13:30:00Z",
        )
        retryable = store.mark_outcome_unknown(
            retryable.dispatch_intent_id,
            expected_revision=retryable.intent_revision,
            failure_ref="transport:timeout",
            observed_at="2026-09-18T13:31:00Z",
        )
        retryable = store.mark_safe_to_retry(
            retryable.dispatch_intent_id,
            expected_revision=retryable.intent_revision,
            evidence_ref="host:proved-not-committed",
            observed_at="2026-09-18T13:32:00Z",
        )
        assert retryable.status is status_type.SAFE_TO_RETRY
        assert retryable.intent_revision == 3
    finally:
        store.close()

    assert _observation_kinds(dsn, primary.dispatch_intent_id) == (
        "DISPATCHED",
        "OUTCOME_UNKNOWN",
        "HOST_COMMITTED",
        "RECONCILED",
    )
    assert _observation_kinds(dsn, retryable.dispatch_intent_id) == (
        "DISPATCHED",
        "OUTCOME_UNKNOWN",
        "SAFE_TO_RETRY",
    )
