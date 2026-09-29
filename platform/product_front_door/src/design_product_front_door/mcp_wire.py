"""Product Front Door 的 strict MCP input DTO 与 domain decoding。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from design_product_runtime import ProductTaskRequest

OperationProposalResumeKind = Literal[
    "OPERATION_PROPOSAL_ACCEPTED",
    "OPERATION_PROPOSAL_REJECTED",
]


class ProductTaskSubmitInput(BaseModel):
    """完整 frozen ProductTask 的 MCP submit 输入；禁止边界层补写 authority。"""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    task_id: str
    project_id: str
    host_kind: str
    session_ref: str
    requested_action: str
    intent_arguments: dict[str, object]
    request_hash: str


class ProductTaskGetInput(BaseModel):
    """只按 exact task_id 查询的 MCP 输入。"""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    task_id: str


class ProductTaskResumeOperationProposalInput(BaseModel):
    """Operation Proposal human resume 的唯一 MCP 输入面。"""

    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    task_id: str
    pause_id: str
    resume_kind: OperationProposalResumeKind


def _require_nonblank(value: str, field_name: str) -> str:
    """只拒绝空白 locator，不替调用方改写 exact identity。"""

    if not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value


def decode_submit_input(value: ProductTaskSubmitInput) -> ProductTaskRequest:
    """把完整 MCP payload 解码为既有 ProductTask authority contract。"""

    return ProductTaskRequest(
        task_id=value.task_id,
        project_id=value.project_id,
        host_kind=value.host_kind,
        session_ref=value.session_ref,
        requested_action=value.requested_action,
        intent_arguments=value.intent_arguments,
        request_hash=value.request_hash,
    )


def decode_get_input(value: ProductTaskGetInput) -> str:
    """返回 exact task_id；不提供 listing、search 或 session fallback。"""

    return _require_nonblank(value.task_id, "task_id")


def decode_resume_operation_proposal_input(
    value: ProductTaskResumeOperationProposalInput,
) -> tuple[str, str, str]:
    """返回 service 需要的三项 frozen human-resume 参数，不构造 workflow command。"""

    task_id = _require_nonblank(value.task_id, "task_id")
    pause_id = _require_nonblank(value.pause_id, "pause_id")
    return task_id, pause_id, value.resume_kind


__all__ = [
    "OperationProposalResumeKind",
    "ProductTaskGetInput",
    "ProductTaskResumeOperationProposalInput",
    "ProductTaskSubmitInput",
    "decode_get_input",
    "decode_resume_operation_proposal_input",
    "decode_submit_input",
]
