"""Cross-Host Product Vertical Task 1：V2 ProductTaskRequest 的显式版本契约。"""

from __future__ import annotations

from importlib import import_module

import pytest


def _contracts():
    """延迟读取 V2 contract，使 RED 明确落在能力缺失而非测试收集错误。"""

    module = import_module("design_product_runtime.contracts")
    request_type = getattr(module, "ProductTaskRequestV2", None)
    error_type = getattr(module, "ProductTaskRequestError", None)
    assert request_type is not None, "ProductTaskRequestV2 尚未实现"
    assert error_type is not None
    return module, request_type, error_type


def _create_v2(**overrides):
    """通过公开 create API 构造最小合法 V2 request。"""

    _, request_type, _ = _contracts()
    values = {
        "task_id": "TASK-CROSS-HOST-300",
        "project_id": "PROJECT-1",
        "initiating_host_kind": "REVIT",
        "session_ref": "SESSION-CROSS-HOST-1",
        "session_binding_hash": "a" * 64,
        "requested_action": "SET_BOUND_WALL_THICKNESS",
        "intent_arguments": {"thickness": {"value": 300.0, "unit": "mm"}},
    }
    values.update(overrides)
    return request_type.create(**values)


def test_v2_request_is_explicitly_versioned_and_hashes_complete_authority_body() -> None:
    """V2 identity 必须显式包含 version 与 exact session binding hash。"""

    module, _, _ = _contracts()
    request = _create_v2()

    assert request.version == "V2"
    assert request.initiating_host_kind == "REVIT"
    assert request.requested_action == "SET_BOUND_WALL_THICKNESS"
    assert len(request.request_hash) == 64
    assert module.product_task_request_v2_payload(request) == {
        "version": "V2",
        "project_id": "PROJECT-1",
        "initiating_host_kind": "REVIT",
        "session_ref": "SESSION-CROSS-HOST-1",
        "session_binding_hash": "a" * 64,
        "requested_action": "SET_BOUND_WALL_THICKNESS",
        "intent_arguments": {"thickness": {"value": 300.0, "unit": "mm"}},
    }

    changed_binding = _create_v2(session_binding_hash="b" * 64)
    assert changed_binding.request_hash != request.request_hash


def test_v2_request_rejects_wrong_initiator_action_and_binding_hash() -> None:
    """本 vertical 只允许 Revit 发起、bound-wall action 和规范 binding hash。"""

    _, _, error_type = _contracts()

    with pytest.raises(error_type) as wrong_host:
        _create_v2(initiating_host_kind="AUTOCAD")
    with pytest.raises(error_type) as wrong_action:
        _create_v2(requested_action="SET_SELECTED_WALL_THICKNESS")
    with pytest.raises(error_type) as bad_hash:
        _create_v2(session_binding_hash="not-a-hash")

    assert wrong_host.value.code == "PRODUCT_TASK_REQUEST_INVALID"
    assert wrong_action.value.code == "PRODUCT_TASK_REQUEST_INVALID"
    assert bad_hash.value.code == "PRODUCT_TASK_REQUEST_INVALID"


@pytest.mark.parametrize(
    "intent_arguments",
    [
        {"thickness": {"value": 0.0, "unit": "mm"}},
        {"thickness": {"value": -1.0, "unit": "mm"}},
        {"thickness": {"value": 300.0, "unit": "cm"}},
        {"thickness": {"value": 300.0, "unit": "mm"}, "host_revision": 7},
    ],
)
def test_v2_request_keeps_same_normalized_thickness_only_intent_boundary(
    intent_arguments: dict[str, object],
) -> None:
    """V2 扩大执行范围，但不能把 Host/model truth 扩进 request intent。"""

    _, _, error_type = _contracts()

    with pytest.raises(error_type) as captured:
        _create_v2(intent_arguments=intent_arguments)

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INVALID"


def test_v2_direct_construction_rejects_request_hash_mismatch() -> None:
    """supplied V2 hash 必须重新校验完整 versioned authority body。"""

    _, request_type, error_type = _contracts()

    with pytest.raises(error_type) as captured:
        request_type(
            version="V2",
            task_id="TASK-CROSS-HOST-300",
            project_id="PROJECT-1",
            initiating_host_kind="REVIT",
            session_ref="SESSION-CROSS-HOST-1",
            session_binding_hash="a" * 64,
            requested_action="SET_BOUND_WALL_THICKNESS",
            intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
            request_hash="0" * 64,
        )

    assert captured.value.code == "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"
