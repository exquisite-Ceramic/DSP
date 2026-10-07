"""Task 13：V2 reconciliation evidence body 的 PostgreSQL durability contract。"""

from __future__ import annotations

import os
from dataclasses import replace

import pytest
from design_execution_reconciliation import ReconciliationError

from tests.execution_reconciliation._support import (
    phase_i_context,
    service,
    signed_bundle,
    signed_delta,
)


def _dsn() -> str:
    """只在显式 PostgreSQL lane 执行 durable evidence owner 验证。"""

    dsn = os.environ.get("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _postgres_api():
    """延迟加载 Task 13 PostgreSQL adapter，使 RED 精确落在 capability 缺失。"""

    from design_execution_reconciliation.postgres import (
        apply_execution_saga_migrations,
        connect_postgres,
    )
    from design_execution_reconciliation.postgres_evidence import (
        PostgresReconciliationEvidenceStore,
    )

    return apply_execution_saga_migrations, connect_postgres, PostgresReconciliationEvidenceStore


def _clean_evidence_rows() -> None:
    """若 migration 已存在则清空 Task 13 evidence 表；RED 阶段允许表尚不存在。"""

    apply_migrations, connect_postgres, _ = _postgres_api()
    conn = connect_postgres(_dsn())
    try:
        apply_migrations(conn)
        with conn.transaction():
            table = conn.execute(
                "SELECT to_regclass('execution_saga.reconciliation_evidence')"
            ).fetchone()
            if table is not None and table[0] is not None:
                conn.execute("TRUNCATE TABLE execution_saga.reconciliation_evidence")
    finally:
        conn.close()


@pytest.fixture(autouse=True)
def _fresh_evidence_owner():
    """每个 case 使用空 owner state，避免 content-addressed replay 互相污染。"""

    _clean_evidence_rows()
    yield
    _clean_evidence_rows()


def _bodies():
    """用真实 Step33 evaluator 生成三种完整、hash-valid 的 evidence body。"""

    ctx = phase_i_context()
    execution_slice = ctx.execution_plan.execution_slices[0]
    authority = ctx.authorities[0]
    delta = signed_delta(ctx)
    bundle = signed_bundle(ctx, delta)
    verification = service().verify_semantics(
        canonical_changeset=ctx.case.changeset,
        approval_scope_boundary=ctx.case.boundary_v2,
        execution_slice=execution_slice,
        authority=authority,
        actual_delta=delta,
        validation_tasks=ctx.case.changeset.validation_tasks,
        verification_evidence_bundle=bundle,
        verified_at="2026-10-07T03:50:00Z",
    )
    return delta, bundle, verification


def test_all_v2_evidence_bodies_survive_store_restart() -> None:
    """ActualDelta、bundle、verification result 必须按 committed hash 重启可读。"""

    _, _, store_type = _postgres_api()
    delta, bundle, verification = _bodies()

    store_a = store_type(_dsn())
    try:
        assert store_a.put_actual_delta(delta) == delta.actual_delta_hash
        assert (
            store_a.put_verification_bundle(bundle)
            == bundle.evidence_bundle_hash
        )
        assert (
            store_a.put_verification_result(verification)
            == verification.verification_hash
        )
    finally:
        store_a.close()

    store_b = store_type(_dsn())
    try:
        assert store_b.get_actual_delta(delta.actual_delta_hash) == delta
        assert (
            store_b.get_verification_bundle(bundle.evidence_bundle_hash)
            == bundle
        )
        assert (
            store_b.get_verification_result(verification.verification_hash)
            == verification
        )
    finally:
        store_b.close()


def test_same_hash_same_body_replay_is_idempotent() -> None:
    """content-addressed owner 对 exact replay 不产生第二份可变 truth。"""

    _, _, store_type = _postgres_api()
    delta, bundle, verification = _bodies()
    store = store_type(_dsn())
    try:
        assert store.put_actual_delta(delta) == delta.actual_delta_hash
        assert store.put_actual_delta(delta) == delta.actual_delta_hash
        assert store.put_verification_bundle(bundle) == bundle.evidence_bundle_hash
        assert store.put_verification_bundle(bundle) == bundle.evidence_bundle_hash
        assert (
            store.put_verification_result(verification)
            == verification.verification_hash
        )
        assert (
            store.put_verification_result(verification)
            == verification.verification_hash
        )
    finally:
        store.close()


def test_same_committed_hash_with_different_body_is_corruption() -> None:
    """相同 hash 不允许对应不同 body；不能静默覆盖 durable evidence。"""

    _, _, store_type = _postgres_api()
    delta, _, _ = _bodies()
    store = store_type(_dsn())
    try:
        store.put_actual_delta(delta)
        tampered = replace(delta, revision_after=delta.revision_after + 1)
        with pytest.raises(ReconciliationError) as exc:
            store.put_actual_delta(tampered)
        assert exc.value.code in {
            "ACTUAL_DELTA_INTEGRITY_INVALID",
            "RECONCILIATION_EVIDENCE_CORRUPT",
        }
        assert store.get_actual_delta(delta.actual_delta_hash) == delta
    finally:
        store.close()
