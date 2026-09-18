from __future__ import annotations

import os
from dataclasses import replace

import pytest
from design_execution_reconciliation import ReconciliationError

from tests.execution_reconciliation.saga_store_v2_contract import (
    SAGA_STORE_V2_CONTRACT_CASES,
    build_saga_v2_contract_fixture,
)


def _postgres_dsn() -> str:
    """只在显式提供测试 PostgreSQL 时运行 durable store 验证。"""
    dsn = os.environ.get("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _postgres_api():
    """在确认专用 PostgreSQL lane 后才加载 psycopg 基础设施。"""
    from design_execution_reconciliation.postgres import (
        apply_execution_saga_migrations,
        connect_postgres,
    )

    return apply_execution_saga_migrations, connect_postgres


def _store_type():
    """延迟导入 PostgreSQL adapter，避免普通离线回归在 collection 阶段加载 psycopg。"""
    from design_execution_reconciliation.postgres_saga_store_v2 import (
        PostgresExecutionSagaStoreV2,
    )

    return PostgresExecutionSagaStoreV2


def _truncate_execution_saga_owner_state(conn) -> None:
    """显式清空本 owner 的测试状态，不用 CASCADE 穿透未知依赖边界。"""
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


@pytest.fixture(autouse=True)
def _clean_execution_saga_table():
    """每个 PostgreSQL case 使用空 owner state，避免确定性 identity 相互污染。"""
    dsn = _postgres_dsn()
    apply_execution_saga_migrations, connect_postgres = _postgres_api()
    conn = connect_postgres(dsn)
    try:
        apply_execution_saga_migrations(conn)
        with conn.transaction():
            _truncate_execution_saga_owner_state(conn)
    finally:
        conn.close()
    yield
    conn = connect_postgres(dsn)
    try:
        with conn.transaction():
            _truncate_execution_saga_owner_state(conn)
    finally:
        conn.close()


@pytest.mark.parametrize(
    "contract_case",
    SAGA_STORE_V2_CONTRACT_CASES,
    ids=[name for name, _assertion in SAGA_STORE_V2_CONTRACT_CASES],
)
def test_postgres_store_v2_conforms_to_backend_contract(contract_case) -> None:
    """PostgreSQL backend 必须与内存 backend 共享完全相同的 Saga V2 领域语义。"""
    dsn = _postgres_dsn()
    _name, assertion = contract_case
    ctx, definition = build_saga_v2_contract_fixture()
    store = _store_type()(dsn)
    try:
        assertion(store, ctx, definition)
    finally:
        store.close()


def test_factory_selects_postgres_backend_with_explicit_dsn() -> None:
    """只有显式选择 postgres 且提供 DSN 时，公共 factory 才实例化 durable adapter。"""
    from design_execution_reconciliation import create_execution_saga_store_v2

    store_type = _store_type()
    store = create_execution_saga_store_v2(
        backend="postgres",
        postgres_dsn=_postgres_dsn(),
    )
    try:
        assert isinstance(store, store_type)
    finally:
        store.close()


def test_postgres_store_survives_restart_and_create_is_evidence_safe() -> None:
    dsn = _postgres_dsn()
    store_type = _store_type()
    _, definition = build_saga_v2_contract_fixture()

    store_a = store_type(dsn)
    try:
        stored = store_a.create_saga(definition)
        assert store_a.create_saga(definition) == stored
    finally:
        store_a.close()

    store_b = store_type(dsn)
    try:
        assert store_b.get_saga(definition.saga_id) == stored

        conflicting = replace(definition, changeset_hash="f" * 64)
        with pytest.raises(ReconciliationError) as exc:
            store_b.create_saga(conflicting)
        assert exc.value.code == "SAGA_CONFLICT"
    finally:
        store_b.close()


def test_postgres_store_enforces_revision_cas_across_independent_connections() -> None:
    dsn = _postgres_dsn()
    store_type = _store_type()
    _, definition = build_saga_v2_contract_fixture()

    store_a = store_type(dsn)
    store_b = store_type(dsn)
    try:
        initial = store_a.create_saga(definition)
        observed_by_b = store_b.get_saga(definition.saga_id)
        assert observed_by_b == initial

        first_hash = definition.ordered_slice_hashes[0]
        winner = store_a.reserve_slice_admission(
            definition.saga_id,
            first_hash,
            expected_revision=initial.saga_revision,
            reserved_at="2026-09-16T23:30:00Z",
        )
        assert winner.saga_revision == initial.saga_revision + 1

        with pytest.raises(ReconciliationError) as exc:
            store_b.reserve_slice_admission(
                definition.saga_id,
                first_hash,
                expected_revision=observed_by_b.saga_revision,
                reserved_at="2026-09-16T23:30:01Z",
            )
        assert exc.value.code == "SAGA_CONFLICT"
        assert store_b.get_saga(definition.saga_id) == winner
    finally:
        store_a.close()
        store_b.close()
