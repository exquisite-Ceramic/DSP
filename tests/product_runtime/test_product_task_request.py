"""Real Product Vertical Task 1：immutable ProductTask request contract 的 TDD RED/GREEN。"""

from __future__ import annotations

import math
from importlib import import_module

import pytest


def _contracts():
    """延迟加载尚未实现的 product runtime contract，并把“能力缺失”表现为测试失败。"""

    try:
        module = import_module("design_product_runtime.contracts")
    except ModuleNotFoundError as exc:
        if exc.name in {"design_product_runtime", "design_product_runtime.contracts"}:
            pytest.fail("design_product_runtime.contracts is not implemented")
        raise
    return module.ProductTaskRequest, module.ProductTaskRequestError


def _create_request(
    *,
    task_id: str = "TASK-WALL-300",
    project_id: str = "PROJECT-1",
    host_kind: str = "REVIT",
    session_ref: str = "SESSION-1",
    requested_action: str = "SET_SELECTED_WALL_THICKNESS",
    intent_arguments: dict[str, object] | None = None,
):
    """通过公开 create API 构造冻结 vertical 的最小产品请求。"""

    ProductTaskRequest, _ = _contracts()
    if intent_arguments is None:
        intent_arguments = {"thickness": {"value": 300.0, "unit": "mm"}}
    return ProductTaskRequest.create(
        task_id=task_id,
        project_id=project_id,
        host_kind=host_kind,
        session_ref=session_ref,
        requested_action=requested_action,
        intent_arguments=intent_arguments,
    )


def test_request_hash_is_deterministic_and_300_differs_from_350() -> None:
    """同一 immutable body 必须得到同一 hash，不同 thickness 必须改变 identity。"""

    first = _create_request()
    replay = _create_request()
    other = _create_request(
        task_id="TASK-WALL-350",
        intent_arguments={"thickness": {"value": 350.0, "unit": "mm"}},
    )

    assert first == replay
    assert len(first.request_hash) == 64
    assert first.request_hash != other.request_hash


def test_request_deep_copies_and_freezes_intent_arguments() -> None:
    """调用方后续修改原始 dict 不得改变 durable request body 或其 hash。"""

    arguments: dict[str, object] = {
        "thickness": {"value": 300.0, "unit": "mm"},
    }
    request = _create_request(intent_arguments=arguments)
    original_hash = request.request_hash

    thickness = arguments["thickness"]
    assert isinstance(thickness, dict)
    thickness["value"] = 350.0

    assert request.intent_arguments["thickness"]["value"] == 300.0
    assert request.request_hash == original_hash
    with pytest.raises(TypeError):
        request.intent_arguments["thickness"]["value"] = 325.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_id", ""),
        ("project_id", "   "),
        ("host_kind", ""),
        ("session_ref", "\t"),
        ("requested_action", ""),
    ],
)
def test_blank_request_identity_is_rejected(field: str, value: str) -> None:
    """所有 lineage locator 都必须是非空字符串。"""

    _, ProductTaskRequestError = _contracts()
    kwargs = {field: value}

    with pytest.raises(ProductTaskRequestError) as captured:
        _create_request(**kwargs)

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INVALID"


def test_vertical_rejects_wrong_host_or_action() -> None:
    """Task 1 contract 只表达本次冻结的 Revit wall-thickness vertical。"""

    _, ProductTaskRequestError = _contracts()

    with pytest.raises(ProductTaskRequestError) as wrong_host:
        _create_request(host_kind="AUTOCAD")
    with pytest.raises(ProductTaskRequestError) as wrong_action:
        _create_request(requested_action="MOVE")

    assert wrong_host.value.code == "PRODUCT_TASK_REQUEST_INVALID"
    assert wrong_action.value.code == "PRODUCT_TASK_REQUEST_INVALID"


@pytest.mark.parametrize(
    "value",
    [0, -1, True, math.nan, math.inf, -math.inf, "300"],
)
def test_invalid_thickness_is_rejected(value: object) -> None:
    """Thickness 必须是有限正数，bool/string 不能借 Python 数值兼容性混入。"""

    _, ProductTaskRequestError = _contracts()

    with pytest.raises(ProductTaskRequestError) as captured:
        _create_request(intent_arguments={"thickness": {"value": value, "unit": "mm"}})

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INVALID"


def test_non_mm_unit_is_rejected() -> None:
    """Product ingress 只接受 canonical intent transport 的 mm。"""

    _, ProductTaskRequestError = _contracts()

    with pytest.raises(ProductTaskRequestError) as captured:
        _create_request(intent_arguments={"thickness": {"value": 300.0, "unit": "cm"}})

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INVALID"


@pytest.mark.parametrize(
    "intent_arguments",
    [
        {
            "thickness": {"value": 300.0, "unit": "mm"},
            "selected_native_id": "REVIT-WALL-1",
        },
        {
            "thickness": {"value": 300.0, "unit": "mm"},
            "host_revision": 42,
        },
        {
            "thickness": {
                "value": 300.0,
                "unit": "mm",
                "current_thickness_mm": 200.0,
            }
        },
    ],
)
def test_model_truth_fields_are_rejected_from_request_body(
    intent_arguments: dict[str, object],
) -> None:
    """选择、revision、current state 等 Host/model truth 不能进入 ProductTask request。"""

    _, ProductTaskRequestError = _contracts()

    with pytest.raises(ProductTaskRequestError) as captured:
        _create_request(intent_arguments=intent_arguments)

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INVALID"


def test_direct_construction_rejects_request_hash_mismatch() -> None:
    """即使字段结构合法，supplied hash 与 canonical body 不一致也必须 fail closed。"""

    ProductTaskRequest, ProductTaskRequestError = _contracts()

    with pytest.raises(ProductTaskRequestError) as captured:
        ProductTaskRequest(
            task_id="TASK-WALL-300",
            project_id="PROJECT-1",
            host_kind="REVIT",
            session_ref="SESSION-1",
            requested_action="SET_SELECTED_WALL_THICKNESS",
            intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
            request_hash="0" * 64,
        )

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"
