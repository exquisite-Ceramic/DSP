"""Execution Saga V2 persistence backend 的显式运行时选择边界。"""

from __future__ import annotations

from .saga_store_v2 import InMemoryExecutionSagaStoreV2


def create_execution_saga_store_v2(
    *,
    backend: str,
    postgres_dsn: str | None = None,
):
    """按显式 backend 名称创建 Saga V2 store；未知 backend 一律 fail closed。"""
    if not isinstance(backend, str):
        raise TypeError("backend must be a string")
    normalized = backend.strip().lower()
    if normalized == "memory":
        return InMemoryExecutionSagaStoreV2()
    raise ValueError(f"unsupported execution saga store backend: {backend!r}")


__all__ = ["create_execution_saga_store_v2"]
