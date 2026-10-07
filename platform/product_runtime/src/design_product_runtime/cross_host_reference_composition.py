"""Cross-Host Product Vertical 的 exact runtime registry composition seam。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from design_execution_planning import HostRuntimeRef

from .runtime_registry import ExactHostRuntimeRegistry

_REQUIRED_HOST_TYPES = frozenset({"autocad", "revit"})


@dataclass(frozen=True, slots=True)
class CrossHostRuntimePortBinding:
    """一个 exact runtime 同时绑定 readiness 与 execution production port。"""

    runtime_ref: HostRuntimeRef
    readiness_port: object
    execution_port: object

    def __post_init__(self) -> None:
        """只接受当前 vertical 可实际调用的端口 shape。"""

        if not isinstance(self.runtime_ref, HostRuntimeRef):
            raise TypeError("runtime_ref must be HostRuntimeRef")
        if not callable(getattr(self.readiness_port, "check", None)):
            raise TypeError("readiness_port must provide check")
        if not callable(getattr(self.execution_port, "execute", None)):
            raise TypeError("execution_port must provide execute")


@dataclass(frozen=True, slots=True)
class CrossHostRuntimeRegistries:
    """供现有 readiness barrier 与 materialized coordinator 注入的两个 registry。"""

    readiness: ExactHostRuntimeRegistry
    execution: ExactHostRuntimeRegistry


def build_cross_host_runtime_registries(
    bindings: Iterable[CrossHostRuntimePortBinding],
) -> CrossHostRuntimeRegistries:
    """构造 exact AutoCAD+Revit registries；构建阶段绝不触发 Host I/O。"""

    values = tuple(bindings)
    if len(values) != 2 or any(
        not isinstance(item, CrossHostRuntimePortBinding) for item in values
    ):
        raise ValueError(
            "CROSS_HOST_RUNTIME_SET_INVALID: exactly two runtime bindings are required"
        )
    host_types = {item.runtime_ref.host_type for item in values}
    if host_types != _REQUIRED_HOST_TYPES:
        raise ValueError(
            "CROSS_HOST_RUNTIME_SET_INVALID: required Host set is AutoCAD + Revit"
        )

    readiness = ExactHostRuntimeRegistry(
        (item.runtime_ref, item.readiness_port) for item in values
    )
    execution = ExactHostRuntimeRegistry(
        (item.runtime_ref, item.execution_port) for item in values
    )
    return CrossHostRuntimeRegistries(
        readiness=readiness,
        execution=execution,
    )


__all__ = [
    "CrossHostRuntimePortBinding",
    "CrossHostRuntimeRegistries",
    "build_cross_host_runtime_registries",
]
