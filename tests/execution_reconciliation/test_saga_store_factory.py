from __future__ import annotations

import pytest
from design_execution_reconciliation import InMemoryExecutionSagaStoreV2


def _factory():
    """延迟导入 factory，确保测试只验证运行时选择语义。"""
    from design_execution_reconciliation.saga_store_factory import (
        create_execution_saga_store_v2,
    )

    return create_execution_saga_store_v2


def test_factory_selects_memory_backend_only_when_explicitly_requested() -> None:
    """memory backend 必须由显式 backend 参数选择。"""
    store = _factory()(backend="memory")

    assert isinstance(store, InMemoryExecutionSagaStoreV2)


def test_factory_requires_explicit_dsn_for_postgres_backend() -> None:
    """postgres 是受支持 backend，但没有显式 DSN 时必须 fail closed。"""
    with pytest.raises(ValueError, match="postgres_dsn is required"):
        _factory()(backend="postgres")


def test_factory_rejects_unknown_backend() -> None:
    """未知 backend 不能退回 memory 或其他隐式默认值。"""
    with pytest.raises(ValueError, match="unsupported execution saga store backend"):
        _factory()(backend="sqlite")


def test_factory_does_not_infer_backend_from_environment(monkeypatch) -> None:
    """即使环境里存在 PostgreSQL DSN，显式 memory 选择也不得被偷偷覆盖。"""
    monkeypatch.setenv(
        "DSP_TEST_POSTGRES_DSN",
        "postgresql://should-not-be-used.invalid/dsp",
    )

    store = _factory()(backend="memory")

    assert isinstance(store, InMemoryExecutionSagaStoreV2)
