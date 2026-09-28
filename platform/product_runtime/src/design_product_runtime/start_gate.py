"""ProductTask 首次 workflow start 临界区的最小串行化端口。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import AbstractContextManager
from typing import Protocol


class ProductTaskStartGate(Protocol):
    """只串行化同一 task 的 checkpoint-missing → possible-start 临界区。"""

    def serialize(self, task_id: str) -> AbstractContextManager[None]:
        """返回覆盖整个首次启动临界区的上下文管理器。"""

        ...


class ProductTaskStartGateContextFactory(Protocol):
    """仅用于静态描述 contextmanager decorator 所产生的兼容调用形状。"""

    def __call__(self, task_id: str) -> Iterator[None]:
        """生成一次串行化上下文。"""

        ...


__all__ = ["ProductTaskStartGate"]
