"""Cross-Host Product Vertical Task 10：cross-host exact registry composition。"""

from __future__ import annotations

import pytest
from design_execution_planning import HostRuntimeRef


class _Readiness:
    """最小 readiness port shape。"""

    def check(self, execution_slice, authority, binding_set):
        """本测试不执行领域逻辑，只验证端口装配。"""

        raise AssertionError("readiness must not be called during composition")


class _Execution:
    """最小 execution port shape。"""

    def execute(self, execution_slice, authority, binding_set, dispatch_context):
        """本测试不执行 Host mutation，只验证端口装配。"""

        raise AssertionError("execution must not be called during composition")


def _runtime(host_type: str, instance: str, document: str) -> HostRuntimeRef:
    """构造 exact HostRuntimeRef。"""

    return HostRuntimeRef(host_type, instance, document)


def test_cross_host_reference_composition_builds_two_exact_registries() -> None:
    """readiness/execution registries 必须共享同一双 Host exact runtime key set。"""

    from design_product_runtime.cross_host_reference_composition import (
        CrossHostRuntimePortBinding,
        build_cross_host_runtime_registries,
    )

    autocad = _runtime("autocad", "AUTOCAD-01", "DOC-A")
    revit = _runtime("revit", "REVIT-01", "DOC-R")
    acad_readiness = _Readiness()
    revit_readiness = _Readiness()
    acad_execution = _Execution()
    revit_execution = _Execution()

    registries = build_cross_host_runtime_registries(
        (
            CrossHostRuntimePortBinding(
                runtime_ref=autocad,
                readiness_port=acad_readiness,
                execution_port=acad_execution,
            ),
            CrossHostRuntimePortBinding(
                runtime_ref=revit,
                readiness_port=revit_readiness,
                execution_port=revit_execution,
            ),
        )
    )

    assert registries.readiness.resolve(autocad) is acad_readiness
    assert registries.readiness.resolve(revit) is revit_readiness
    assert registries.execution.resolve(autocad) is acad_execution
    assert registries.execution.resolve(revit) is revit_execution

    with pytest.raises(
        ValueError,
        match="PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED",
    ):
        registries.execution.resolve(
            _runtime("revit", "REVIT-01", "ANOTHER-DOC")
        )


def test_cross_host_reference_composition_requires_autocad_and_revit() -> None:
    """本 capability 的 reference composition 必须精确覆盖 AutoCAD+Revit。"""

    from design_product_runtime.cross_host_reference_composition import (
        CrossHostRuntimePortBinding,
        build_cross_host_runtime_registries,
    )

    with pytest.raises(
        ValueError,
        match="CROSS_HOST_RUNTIME_SET_INVALID",
    ):
        build_cross_host_runtime_registries(
            (
                CrossHostRuntimePortBinding(
                    runtime_ref=_runtime("revit", "REVIT-01", "DOC-R1"),
                    readiness_port=_Readiness(),
                    execution_port=_Execution(),
                ),
                CrossHostRuntimePortBinding(
                    runtime_ref=_runtime("revit", "REVIT-02", "DOC-R2"),
                    readiness_port=_Readiness(),
                    execution_port=_Execution(),
                ),
            )
        )
