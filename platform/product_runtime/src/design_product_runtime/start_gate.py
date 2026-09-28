"""ProductTask 首次 workflow start 临界区的最小串行化端口。"""

from __future__ import annotations

from contextlib import AbstractContextManager
from typing import Protocol


class ProductTaskStartGate(Protocol):
    """只串行化同一 task 的 checkpoint-missing → possible-start 临界区。"""

    def serialize(self, task_id: str) -> AbstractContextManager[None]:
        """返回覆盖整个首次启动临界区的上下文管理器。"""

        ...


__all__ = ["ProductTaskStartGate"]
