"""Cross-Host Product Vertical Task 10：exact Host runtime registry 契约。"""

from __future__ import annotations

import pytest
from design_execution_planning import HostRuntimeRef


class _Port:
    """用于证明 registry 只返回 exact key 所绑定的端口。"""

    def __init__(self, name: str) -> None:
        self.name = name


def _runtime(host_type: str, instance: str, document: str) -> HostRuntimeRef:
    """构造稳定 runtime identity。"""

    return HostRuntimeRef(
        host_type=host_type,
        host_instance_id=instance,
        document_ref=document,
    )


def test_registry_rejects_same_host_type_with_wrong_instance_or_document() -> None:
    """host_type 相同也不能弱化 exact runtime/document identity。"""

    from design_product_runtime.runtime_registry import ExactHostRuntimeRegistry

    autocad = _runtime("autocad", "AUTOCAD-01", "DOC-A")
    revit = _runtime("revit", "REVIT-01", "DOC-R")
    autocad_port = _Port("autocad")
    revit_port = _Port("revit")
    registry = ExactHostRuntimeRegistry(
        (
            (autocad, autocad_port),
            (revit, revit_port),
        )
    )

    assert registry.resolve(autocad) is autocad_port
    assert registry.resolve(revit) is revit_port

    with pytest.raises(
        ValueError,
        match="PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED",
    ):
        registry.resolve(_runtime("autocad", "AUTOCAD-OTHER", "DOC-A"))

    with pytest.raises(
        ValueError,
        match="PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED",
    ):
        registry.resolve(_runtime("autocad", "AUTOCAD-01", "DOC-OTHER"))


def test_registry_rejects_duplicate_exact_runtime_key() -> None:
    """同一个 exact runtime key 不能被两个端口覆盖。"""

    from design_product_runtime.runtime_registry import ExactHostRuntimeRegistry

    runtime = _runtime("revit", "REVIT-01", "DOC-R")
    with pytest.raises(ValueError, match="PRODUCT_RUNTIME_HOST_RUNTIME_CONFLICT"):
        ExactHostRuntimeRegistry(
            (
                (runtime, _Port("first")),
                (runtime, _Port("second")),
            )
        )
