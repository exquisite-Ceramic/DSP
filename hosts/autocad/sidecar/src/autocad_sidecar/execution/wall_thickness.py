"""AutoCAD 墙厚产品 vertical 的同步 mutation wrapper。"""

from __future__ import annotations

import asyncio
import math


def _run(awaitable):
    """在同步 coordinator 边界执行 sidecar async API；禁止嵌套事件循环。"""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError(
        "AutoCAD wall-thickness synchronous mutation cannot run inside an active event loop"
    )


def _text(value: object, field_name: str) -> str:
    """规范化 Host-local identity 字段。"""

    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value.strip()


def _revision(value: object) -> int:
    """只接受真实非负 AutoCAD document revision。"""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("expected_revision must be a non-negative integer")
    return value


def _thickness(value: object) -> float:
    """只接受有限正 mm 墙厚。"""

    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value <= 0
    ):
        raise ValueError("thickness_mm must be a finite positive number")
    return float(value)


class AutoCadWallThicknessMutationPort:
    """只包装 public CommandDispatcher.set_wall_thickness，不持有产品 authority。"""

    def __init__(self, dispatcher) -> None:
        execute = getattr(dispatcher, "set_wall_thickness", None)
        if not callable(execute):
            raise TypeError("dispatcher must provide set_wall_thickness")
        self._dispatcher = dispatcher

    def execute(
        self,
        *,
        native_id: str,
        thickness_mm: float,
        idempotency_key: str,
        expected_revision: int,
    ):
        """发送一次 exact logical mutation；transport 异常原样上抛，禁止 wrapper 重试。"""

        native = _text(native_id, "native_id")
        key = _text(idempotency_key, "idempotency_key")
        revision = _revision(expected_revision)
        thickness = _thickness(thickness_mm)
        return _run(
            self._dispatcher.set_wall_thickness(
                [native],
                thickness,
                idempotency_key=key,
                revision=revision,
            )
        )


__all__ = ["AutoCadWallThicknessMutationPort"]
