from __future__ import annotations

from design_execution_reconciliation import InMemoryExecutionSagaStoreV2


def test_factory_selects_memory_backend_only_when_explicitly_requested() -> None:
    """runtime backend 选择必须是显式输入，不能由环境变量或隐式默认值决定。"""
    from design_execution_reconciliation.saga_store_factory import (
        create_execution_saga_store_v2,
    )

    store = create_execution_saga_store_v2(backend="memory")

    assert isinstance(store, InMemoryExecutionSagaStoreV2)
