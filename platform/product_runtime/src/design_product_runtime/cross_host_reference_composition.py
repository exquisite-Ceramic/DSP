"""Cross-Host Product Vertical 的 exact runtime registry composition seam。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from design_execution_planning import HostRuntimeRef

from .autocad_execution import AutoCadWallThicknessExecutionPort
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


def build_autocad_wall_thickness_runtime_binding(
    runtime_ref: HostRuntimeRef,
    dispatcher,
    *,
    clock=None,
) -> CrossHostRuntimePortBinding:
    """把现有 AutoCAD public dispatcher 组合成 exact readiness/execution runtime binding。"""

    if not isinstance(runtime_ref, HostRuntimeRef):
        raise TypeError("runtime_ref must be HostRuntimeRef")
    if runtime_ref.host_type != "autocad":
        raise ValueError("AutoCAD runtime binding requires host_type='autocad'")

    from autocad_sidecar.execution.readiness import AutoCadWallThicknessReadinessPort
    from autocad_sidecar.execution.wall_thickness import AutoCadWallThicknessMutationPort

    mutation = AutoCadWallThicknessMutationPort(dispatcher)
    return CrossHostRuntimePortBinding(
        runtime_ref=runtime_ref,
        readiness_port=AutoCadWallThicknessReadinessPort(dispatcher),
        execution_port=AutoCadWallThicknessExecutionPort(
            mutation,
            clock=clock,
        ),
    )


class CrossHostVerificationEvidenceRouter:
    """按 exact HostRuntimeRef 路由已有 Host verification evidence adapters。

    该 router 只解决 composition dispatch；不拥有 evidence、admission、readiness 或
    execution authority，也不在构建时触发任何 Host I/O。
    """

    def __init__(
        self,
        entries: Iterable[tuple[HostRuntimeRef, object]],
    ) -> None:
        """冻结 exact runtime→evidence port 映射，并验证最小只读端口 shape。"""

        normalized = []
        for runtime_ref, port in tuple(entries):
            if not isinstance(runtime_ref, HostRuntimeRef):
                raise TypeError("runtime_ref must be HostRuntimeRef")
            if not callable(getattr(port, "build_bundle", None)):
                raise TypeError("evidence port must provide build_bundle")
            if not callable(getattr(port, "build_evidence", None)):
                raise TypeError("evidence port must provide build_evidence")
            normalized.append((runtime_ref, port))
        self._registry = ExactHostRuntimeRegistry(normalized)

    @staticmethod
    def _runtime_from_kwargs(kwargs: dict[str, object]) -> HostRuntimeRef:
        """只从 coordinator 已验证的 ExecutionSlice runtime identity 解析 route。"""

        execution_slice = kwargs.get("execution_slice")
        runtime_ref = getattr(execution_slice, "host_runtime_ref", None)
        if not isinstance(runtime_ref, HostRuntimeRef):
            raise TypeError(
                "execution_slice must expose a HostRuntimeRef host_runtime_ref"
            )
        return runtime_ref

    def build_bundle(self, **kwargs):
        """把独立 READ bundle 构造委托给 exact Host evidence adapter。"""

        port = self._registry.resolve(self._runtime_from_kwargs(kwargs))
        return port.build_bundle(**kwargs)

    def build_evidence(self, **kwargs):
        """把 convergence evidence 构造委托给同一 exact Host adapter。"""

        port = self._registry.resolve(self._runtime_from_kwargs(kwargs))
        return port.build_evidence(**kwargs)


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
    "CrossHostVerificationEvidenceRouter",
    "build_autocad_wall_thickness_runtime_binding",
    "build_cross_host_runtime_registries",
]
