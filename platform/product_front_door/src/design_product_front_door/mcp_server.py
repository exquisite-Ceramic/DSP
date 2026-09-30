"""Product Front Door 的固定 MCP tool catalog 与薄委托 adapter。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent

from .mcp_wire import (
    OperationProposalResumeKind,
    ProductTaskGetInput,
    ProductTaskResumeOperationProposalInput,
    ProductTaskSubmitInput,
    decode_get_input,
    decode_resume_operation_proposal_input,
    decode_submit_input,
)

_SUBMIT_TOOL = "product.wall_thickness.submit"
_GET_TOOL = "product.wall_thickness.get"
_RESUME_TOOL = "product.wall_thickness.resume_operation_proposal"
_FROZEN_TOOL_NAMES = (_SUBMIT_TOOL, _GET_TOOL, _RESUME_TOOL)


def _json_compatible(value: object) -> object:
    """把 owner-derived view 递归投影为 JSON 值，不创建新的业务状态。"""

    if isinstance(value, Enum):
        return _json_compatible(value.value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("MCP result mappings must use string keys")
            result[key] = _json_compatible(item)
        return result
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_compatible(getattr(value, field.name))
            for field in fields(value)
        }
    if isinstance(value, (tuple, list)):
        return [_json_compatible(item) for item in value]
    raise TypeError(f"MCP result contains unsupported value: {type(value).__name__}")


def _success_result(value: object) -> CallToolResult:
    """把 service 返回值编码成 MCP JSON 文本，并在对象结果时同步提供 structured content。"""

    payload = _json_compatible(value)
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    structured_content = payload if isinstance(payload, dict) else None
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=structured_content,
        is_error=False,
    )


class ProductFrontDoorMcpServer:
    """只把三个冻结逻辑工具映射到既有 ProductFrontDoorService。"""

    def __init__(self, *, service: object) -> None:
        """保存注入 service；MCP adapter 自身不拥有 task/session/approval 状态。"""

        if service is None:
            raise ValueError("service must not be None")
        self._service = service

    def list_tools(self) -> tuple[str, ...]:
        """返回固定 catalog；不存在 generic approval、Gateway 或 Host passthrough。"""

        return _FROZEN_TOOL_NAMES

    def call_tool(
        self,
        *,
        tool_name: str,
        payload: dict[str, object],
        session_id: str | None = None,
    ) -> object:
        """strict decode 后委托 service；transport session 永不参与 ProductTask authority。"""

        # MCP 2.x transport identity 不是 ProductTask session_ref；这里显式忽略该兼容参数。
        _ = session_id

        if tool_name == _SUBMIT_TOOL:
            request = decode_submit_input(ProductTaskSubmitInput.model_validate(payload))
            return self._service_method("submit")(request)

        if tool_name == _GET_TOOL:
            task_id = decode_get_input(ProductTaskGetInput.model_validate(payload))
            return self._service_method("get")(task_id)

        if tool_name == _RESUME_TOOL:
            task_id, pause_id, resume_kind = decode_resume_operation_proposal_input(
                ProductTaskResumeOperationProposalInput.model_validate(payload)
            )
            return self._service_method("resume_operation_proposal")(
                task_id=task_id,
                pause_id=pause_id,
                resume_kind=resume_kind,
            )

        raise KeyError(f"unknown Product Front Door MCP tool: {tool_name}")

    def _service_method(self, name: str):
        """只解析冻结 service 方法；缺失 seam 直接失败，不做动态 passthrough。"""

        method = getattr(self._service, name, None)
        if not callable(method):
            raise TypeError(f"service must provide callable {name}")
        return method


def build_mcp_server(service: object) -> MCPServer:
    """围绕注入的 Product Front Door service 构造仓库 MCP 2.x server。"""

    adapter = ProductFrontDoorMcpServer(service=service)
    server = MCPServer("DSP Product Front Door")

    @server.tool(name=_SUBMIT_TOOL)
    def submit(
        task_id: str,
        project_id: str,
        host_kind: str,
        session_ref: str,
        requested_action: str,
        intent_arguments: dict[str, object],
        request_hash: str,
    ) -> CallToolResult:
        """提交完整 frozen ProductTask；不补写任何 identity/authority。"""

        return _success_result(
            adapter.call_tool(
                tool_name=_SUBMIT_TOOL,
                payload={
                    "task_id": task_id,
                    "project_id": project_id,
                    "host_kind": host_kind,
                    "session_ref": session_ref,
                    "requested_action": requested_action,
                    "intent_arguments": intent_arguments,
                    "request_hash": request_hash,
                },
            )
        )

    @server.tool(name=_GET_TOOL)
    def get(task_id: str) -> CallToolResult:
        """只按 exact task_id 查询 durable ProductTask facts。"""

        return _success_result(
            adapter.call_tool(
                tool_name=_GET_TOOL,
                payload={"task_id": task_id},
            )
        )

    @server.tool(name=_RESUME_TOOL)
    def resume_operation_proposal(
        task_id: str,
        pause_id: str,
        resume_kind: OperationProposalResumeKind,
    ) -> CallToolResult:
        """恢复 exact Operation Proposal pause；不接收 arbitrary payload 或 approval evidence。"""

        return _success_result(
            adapter.call_tool(
                tool_name=_RESUME_TOOL,
                payload={
                    "task_id": task_id,
                    "pause_id": pause_id,
                    "resume_kind": resume_kind,
                },
            )
        )

    return server


__all__ = ["ProductFrontDoorMcpServer", "build_mcp_server"]
