"""Product Front Door MCP wire 的 strict decoding contract。"""

from __future__ import annotations

import pytest
from design_product_front_door.mcp_wire import (
    ProductTaskGetInput,
    ProductTaskResumeOperationProposalInput,
    ProductTaskSubmitInput,
    decode_get_input,
    decode_resume_operation_proposal_input,
    decode_submit_input,
)
from design_product_runtime import ProductTaskRequest, ProductTaskRequestError
from pydantic import ValidationError


def _request() -> ProductTaskRequest:
    """构造一个完整冻结、带 canonical request_hash 的 Revit ProductTask。"""

    return ProductTaskRequest.create(
        task_id="task-wire-001",
        project_id="project-wire",
        host_kind="REVIT",
        session_ref="session-wire",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 350.0, "unit": "mm"}},
    )


def _submit_payload(request: ProductTaskRequest) -> dict[str, object]:
    """按 frozen ProductTask 七字段 authority body 构造 MCP submit 参数。"""

    return {
        "task_id": request.task_id,
        "project_id": request.project_id,
        "host_kind": request.host_kind,
        "session_ref": request.session_ref,
        "requested_action": request.requested_action,
        "intent_arguments": {
            "thickness": {
                "value": request.intent_arguments["thickness"]["value"],
                "unit": request.intent_arguments["thickness"]["unit"],
            }
        },
        "request_hash": request.request_hash,
    }


def test_submit_requires_complete_frozen_product_task() -> None:
    """MCP submit 只解码完整 ProductTask，不替调用方补身份字段或重算 request hash。"""

    request = _request()
    decoded = decode_submit_input(
        ProductTaskSubmitInput.model_validate(_submit_payload(request))
    )

    assert decoded == request

    for missing_field in (
        "task_id",
        "project_id",
        "host_kind",
        "session_ref",
        "requested_action",
        "intent_arguments",
        "request_hash",
    ):
        incomplete = _submit_payload(request)
        incomplete.pop(missing_field)
        with pytest.raises(ValidationError):
            ProductTaskSubmitInput.model_validate(incomplete)


def test_submit_rejects_extra_fields_and_invalid_request_integrity() -> None:
    """wire 不接受客户端工具层夹带的新 authority，也不绕过 ProductTask 完整性校验。"""

    request = _request()
    with pytest.raises(ValidationError):
        ProductTaskSubmitInput.model_validate(
            {**_submit_payload(request), "candidate_key": "must-not-enter-wire"}
        )

    invalid_hash = ProductTaskSubmitInput.model_validate(
        {**_submit_payload(request), "request_hash": "0" * 64}
    )
    with pytest.raises(ProductTaskRequestError) as exc_info:
        decode_submit_input(invalid_hash)
    assert exc_info.value.code == "PRODUCT_TASK_REQUEST_INTEGRITY_INVALID"


def test_get_accepts_only_exact_task_id() -> None:
    """get 的 wire surface 只定位 exact task_id，不暴露 listing/search/session 参数。"""

    decoded = decode_get_input(
        ProductTaskGetInput.model_validate({"task_id": "task-wire-001"})
    )
    assert decoded == "task-wire-001"

    with pytest.raises(ValidationError):
        ProductTaskGetInput.model_validate(
            {"task_id": "task-wire-001", "session_ref": "session-wire"}
        )

    with pytest.raises((ValidationError, ValueError)):
        decode_get_input(ProductTaskGetInput.model_validate({"task_id": "   "}))


@pytest.mark.parametrize(
    "resume_kind",
    ["OPERATION_PROPOSAL_ACCEPTED", "OPERATION_PROPOSAL_REJECTED"],
)
def test_resume_accepts_only_frozen_operation_proposal_decisions(resume_kind: str) -> None:
    """human resume 只有 exact pause identity 与冻结 decision kind，不携带任意 payload。"""

    decoded = decode_resume_operation_proposal_input(
        ProductTaskResumeOperationProposalInput.model_validate(
            {
                "task_id": "task-wire-001",
                "pause_id": "pause-wire-001",
                "resume_kind": resume_kind,
            }
        )
    )

    assert decoded == ("task-wire-001", "pause-wire-001", resume_kind)

    with pytest.raises(ValidationError):
        ProductTaskResumeOperationProposalInput.model_validate(
            {
                "task_id": "task-wire-001",
                "pause_id": "pause-wire-001",
                "resume_kind": resume_kind,
                "payload": {"approved_by": "model"},
            }
        )


def test_resume_rejects_non_operation_proposal_kind() -> None:
    """async/poll/generic approval 不能借 Product Front Door 的 human-resume tool 进入 workflow。"""

    with pytest.raises(ValidationError):
        ProductTaskResumeOperationProposalInput.model_validate(
            {
                "task_id": "task-wire-001",
                "pause_id": "pause-wire-001",
                "resume_kind": "EXECUTION_APPROVED",
            }
        )


def _v2_request():
    """构造 explicit V2 submit request。"""

    request_type = getattr(__import__("design_product_runtime", fromlist=["ProductTaskRequestV2"]), "ProductTaskRequestV2")
    return request_type.create(
        task_id="task-wire-v2",
        project_id="project-wire",
        initiating_host_kind="REVIT",
        session_ref="session-wire-v2",
        session_binding_hash="a" * 64,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


def _v2_submit_payload(request) -> dict[str, object]:
    """V2 wire 只传 request，不重复传完整 SessionBinding body。"""

    return {
        "version": request.version,
        "task_id": request.task_id,
        "project_id": request.project_id,
        "initiating_host_kind": request.initiating_host_kind,
        "session_ref": request.session_ref,
        "session_binding_hash": request.session_binding_hash,
        "requested_action": request.requested_action,
        "intent_arguments": {
            "thickness": {
                "value": request.intent_arguments["thickness"]["value"],
                "unit": request.intent_arguments["thickness"]["unit"],
            }
        },
        "request_hash": request.request_hash,
    }


def test_missing_wire_version_decodes_as_v1_and_explicit_v2_decodes_as_v2() -> None:
    """同一 submit tool 必须保留 V1 payload，并用显式 version 分流 V2。"""

    module = __import__("design_product_front_door.mcp_wire", fromlist=["decode_submit_payload"])
    v1 = _request()
    assert module.decode_submit_payload(_submit_payload(v1)) == v1

    v2 = _v2_request()
    payload = _v2_submit_payload(v2)
    assert "session_binding" not in payload
    assert module.decode_submit_payload(payload) == v2


def test_unknown_wire_version_fails_closed() -> None:
    """未知版本不能降级为 V1 或猜测 request schema。"""

    module = __import__("design_product_front_door.mcp_wire", fromlist=["decode_submit_payload"])
    payload = _v2_submit_payload(_v2_request())
    payload["version"] = "V99"

    with pytest.raises(ValueError, match="unsupported ProductTask submit version"):
        module.decode_submit_payload(payload)
