"""Product Front Door MCP server 的最小 tool-catalog 与 fail-closed contract。"""

from __future__ import annotations

import pytest
from design_product_front_door.mcp_server import (
    ProductFrontDoorMcpServer,
    build_mcp_server,
)
from design_product_runtime import ProductTaskRequest
from mcp import Client

_FROZEN_TOOL_NAMES = {
    "product.wall_thickness.submit",
    "product.wall_thickness.get",
    "product.wall_thickness.resume_operation_proposal",
}
_FROZEN_TOOL_PROPERTIES = {
    "product.wall_thickness.submit": {
        "task_id",
        "project_id",
        "host_kind",
        "session_ref",
        "requested_action",
        "intent_arguments",
        "request_hash",
    },
    "product.wall_thickness.get": {"task_id"},
    "product.wall_thickness.resume_operation_proposal": {
        "task_id",
        "pause_id",
        "resume_kind",
    },
}


class _RecordingService:
    """记录 MCP adapter 是否越过冻结 tool surface 调用了应用 service。"""

    def __init__(self) -> None:
        """初始化调用记录；测试不构造任何 Host、Gateway 或 durable owner。"""

        self.calls: list[tuple[str, object]] = []

    def submit(self, request: ProductTaskRequest) -> None:
        """记录完整 frozen ProductTask 委托。"""

        self.calls.append(("submit", request))

    def get(self, task_id: str) -> None:
        """记录 exact task 查询；返回 None 表示 durable query 没有该 task。"""

        self.calls.append(("get", task_id))

    def resume_operation_proposal(
        self,
        *,
        task_id: str,
        pause_id: str,
        resume_kind: str,
    ) -> None:
        """记录 exact Operation Proposal human-resume 委托。"""

        self.calls.append(("resume", (task_id, pause_id, resume_kind)))


def _request() -> ProductTaskRequest:
    """构造带 canonical request_hash 的完整 frozen ProductTask。"""

    return ProductTaskRequest.create(
        task_id="task-mcp-server-red",
        project_id="project-mcp-server",
        host_kind="REVIT",
        session_ref="session-product-authority",
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


def test_mcp_server_lists_only_frozen_product_tools() -> None:
    """adapter catalog 只能暴露冻结的三个产品工具，不能出现 generic approval/passthrough。"""

    service = _RecordingService()
    server = ProductFrontDoorMcpServer(service=service)

    tool_names = server.list_tools()

    assert len(tool_names) == 3
    assert set(tool_names) == _FROZEN_TOOL_NAMES
    assert all("approval" not in name for name in tool_names)
    assert all("admission" not in name for name in tool_names)
    assert all("gateway" not in name for name in tool_names)
    assert all("sidecar" not in name for name in tool_names)
    assert service.calls == []


@pytest.mark.asyncio
async def test_real_mcp_catalog_matches_frozen_product_surface_and_schema() -> None:
    """真实 MCPServer catalog 必须只注册三个工具，且 transport/session 字段不能进入业务 schema。"""

    service = _RecordingService()
    server = build_mcp_server(service)

    async with Client(server) as client:
        listed = await client.list_tools()

    tools = {tool.name: tool for tool in listed.tools}
    assert set(tools) == _FROZEN_TOOL_NAMES
    for name, tool in tools.items():
        assert set(tool.input_schema["properties"]) == _FROZEN_TOOL_PROPERTIES[name]
        assert set(tool.input_schema.get("required", [])) == _FROZEN_TOOL_PROPERTIES[name]
        assert "session_id" not in tool.input_schema["properties"]
        assert "approval" not in tool.input_schema["properties"]
        assert "admission" not in tool.input_schema["properties"]

    assert service.calls == []


def test_mcp_server_unknown_tool_fails_closed_without_touching_service() -> None:
    """未知 tool 必须在 adapter 边界直接拒绝，不能降级成 generic service/Host passthrough。"""

    service = _RecordingService()
    server = ProductFrontDoorMcpServer(service=service)

    with pytest.raises((KeyError, ValueError)):
        server.call_tool(
            tool_name="gateway.execute",
            payload={"task_id": "task-mcp-server-red"},
            session_id="mcp-session-red",
        )

    assert service.calls == []


def test_mcp_server_submit_decodes_complete_request_and_ignores_transport_session() -> None:
    """submit 只委托 payload 中的完整 ProductTask，transport session 不能替代业务 session_ref。"""

    request = _request()
    service = _RecordingService()
    server = ProductFrontDoorMcpServer(service=service)

    server.call_tool(
        tool_name="product.wall_thickness.submit",
        payload=_submit_payload(request),
        session_id="mcp-session-must-not-become-product-session",
    )

    assert service.calls == [("submit", request)]


def test_mcp_server_get_delegates_exact_task_id_only() -> None:
    """get tool 只把 strict DTO 解出的 exact task_id 委托给现有 service，不做 session fallback。"""

    service = _RecordingService()
    server = ProductFrontDoorMcpServer(service=service)

    server.call_tool(
        tool_name="product.wall_thickness.get",
        payload={"task_id": "task-mcp-server-red"},
        session_id="mcp-session-red",
    )

    assert service.calls == [("get", "task-mcp-server-red")]

    # 额外 locator/session 字段必须由 strict MCP DTO 在 service 调用前拒绝；
    # adapter 不能把 transport session 当成 ProductTask 的 session_ref fallback。
    with pytest.raises((TypeError, ValueError)):
        server.call_tool(
            tool_name="product.wall_thickness.get",
            payload={
                "task_id": "task-mcp-server-red",
                "session_ref": "must-not-enter-get-wire",
            },
            session_id="mcp-session-red",
        )

    assert service.calls == [("get", "task-mcp-server-red")]


def test_mcp_server_resume_delegates_only_exact_frozen_human_decision() -> None:
    """resume 只委托 exact task/pause/decision 三元组，不接收任意 approval payload。"""

    service = _RecordingService()
    server = ProductFrontDoorMcpServer(service=service)

    server.call_tool(
        tool_name="product.wall_thickness.resume_operation_proposal",
        payload={
            "task_id": "task-mcp-server-red",
            "pause_id": "pause-mcp-server-red",
            "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
        },
        session_id="mcp-session-red",
    )

    assert service.calls == [
        (
            "resume",
            (
                "task-mcp-server-red",
                "pause-mcp-server-red",
                "OPERATION_PROPOSAL_ACCEPTED",
            ),
        )
    ]

    with pytest.raises((TypeError, ValueError)):
        server.call_tool(
            tool_name="product.wall_thickness.resume_operation_proposal",
            payload={
                "task_id": "task-mcp-server-red",
                "pause_id": "pause-mcp-server-red",
                "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
                "approval": True,
            },
            session_id="mcp-session-red",
        )


def test_mcp_server_v2_submit_delegates_versioned_request_without_binding_body() -> None:
    """server adapter 必须按 version 解码 V2 request，transport/session 不补写 binding。"""

    request_type = getattr(__import__("design_product_runtime", fromlist=["ProductTaskRequestV2"]), "ProductTaskRequestV2")
    request = request_type.create(
        task_id="task-mcp-server-v2",
        project_id="project-mcp-server",
        initiating_host_kind="REVIT",
        session_ref="session-v2",
        session_binding_hash="a" * 64,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )
    service = _RecordingService()
    server = ProductFrontDoorMcpServer(service=service)
    payload = {
        "version": request.version,
        "task_id": request.task_id,
        "project_id": request.project_id,
        "initiating_host_kind": request.initiating_host_kind,
        "session_ref": request.session_ref,
        "session_binding_hash": request.session_binding_hash,
        "requested_action": request.requested_action,
        "intent_arguments": {"thickness": {"value": 300.0, "unit": "mm"}},
        "request_hash": request.request_hash,
    }

    server.call_tool(
        tool_name="product.wall_thickness.submit",
        payload=payload,
        session_id="transport-session-must-not-be-authority",
    )

    assert service.calls == [("submit", request)]
