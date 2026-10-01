"""Product Front Door 的 loopback-only MCP 2.x 客户端。"""

from __future__ import annotations

import json
from collections.abc import Mapping
from urllib.parse import urlsplit

from design_orchestrator import (
    AsyncOperationKind,
    AsyncOperationRef,
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
)
from design_product_runtime import (
    ProductFlowStatus,
    ProductFlowView,
    ProductTaskQueryState,
    ProductTaskQueryView,
    ProductTaskRequest,
)
from mcp.client import Client
from mcp.types import TextContent

_SUBMIT_TOOL = "product.wall_thickness.submit"
_GET_TOOL = "product.wall_thickness.get"
_RESUME_TOOL = "product.wall_thickness.resume_operation_proposal"
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})
_RESUME_KINDS = frozenset(
    {
        "OPERATION_PROPOSAL_ACCEPTED",
        "OPERATION_PROPOSAL_REJECTED",
    }
)


def _require_mapping(value: object, field_name: str) -> Mapping[str, object]:
    """要求 MCP structured content 的指定节点是字符串键 JSON object。"""

    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        raise TypeError(f"{field_name} must be a string-keyed object")
    return value


def _plain_json(value: object) -> object:
    """把冻结 Mapping/tuple 递归转成 MCP SDK 可直接编码的 JSON 值。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _plain_json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain_json(item) for item in value]
    raise TypeError(f"unsupported MCP argument value: {type(value).__name__}")


def _decode_stable_ref(value: object, field_name: str) -> StableRef | None:
    """恢复 workflow 的 stable ref；None 保持 None，不推断任何 owner locator。"""

    if value is None:
        return None
    body = _require_mapping(value, field_name)
    return StableRef(
        ref_id=body.get("ref_id"),
        content_hash=body.get("content_hash"),
    )


def _decode_async_ref(value: object, field_name: str) -> AsyncOperationRef | None:
    """恢复外部 async owner 引用，不在客户端解释 operation 状态。"""

    if value is None:
        return None
    body = _require_mapping(value, field_name)
    return AsyncOperationRef(
        kind=AsyncOperationKind(body.get("kind")),
        owner=body.get("owner"),
        operation_id=body.get("operation_id"),
    )


def _decode_pending(value: object) -> PendingInteractionView | None:
    """恢复 owner-derived HITL 视图；resume 权限仍由 allowed_resume_kinds 决定。"""

    if value is None:
        return None
    body = _require_mapping(value, "pending_interaction")
    raw_allowed = body.get("allowed_resume_kinds")
    if not isinstance(raw_allowed, list) or any(
        not isinstance(item, str) for item in raw_allowed
    ):
        raise TypeError("pending_interaction.allowed_resume_kinds must be a string array")
    subject_ref = _decode_stable_ref(
        body.get("subject_ref"),
        "pending_interaction.subject_ref",
    )
    if subject_ref is None:
        raise ValueError("pending_interaction.subject_ref is required")
    return PendingInteractionView(
        pause_id=body.get("pause_id"),
        kind=PendingInteractionKind(body.get("kind")),
        subject_ref=subject_ref,
        allowed_resume_kinds=tuple(raw_allowed),
    )


def _decode_checkpoint(value: object) -> WorkflowCheckpointView:
    """从 MCP JSON 恢复 framework-neutral checkpoint，不触碰可执行 workflow runtime。"""

    body = _require_mapping(value, "flow.checkpoint")
    return WorkflowCheckpointView(
        task_id=body.get("task_id"),
        phase=WorkflowPhase(body.get("phase")),
        context_snapshot_ref=_decode_stable_ref(
            body.get("context_snapshot_ref"),
            "context_snapshot_ref",
        ),
        operation_ref=_decode_stable_ref(body.get("operation_ref"), "operation_ref"),
        interaction_ref=_decode_async_ref(body.get("interaction_ref"), "interaction_ref"),
        changeset_ref=_decode_stable_ref(body.get("changeset_ref"), "changeset_ref"),
        approval_ref=_decode_stable_ref(body.get("approval_ref"), "approval_ref"),
        execution_plan_ref=_decode_stable_ref(
            body.get("execution_plan_ref"),
            "execution_plan_ref",
        ),
        saga_id=body.get("saga_id"),
        async_operation_ref=_decode_async_ref(
            body.get("async_operation_ref"),
            "async_operation_ref",
        ),
        error_code=body.get("error_code"),
        pending_interaction=_decode_pending(body.get("pending_interaction")),
    )


def _decode_query_view(value: object) -> ProductTaskQueryView | None:
    """恢复 ProductTaskQueryView；null 精确表示 exact task not found。"""

    if value is None:
        return None
    body = _require_mapping(value, "ProductTaskQueryView")
    state = ProductTaskQueryState(body.get("state"))
    raw_flow = body.get("flow")
    flow = None
    if raw_flow is not None:
        flow_body = _require_mapping(raw_flow, "flow")
        flow = ProductFlowView(
            status=ProductFlowStatus(flow_body.get("status")),
            checkpoint=_decode_checkpoint(flow_body.get("checkpoint")),
        )
    return ProductTaskQueryView(
        task_id=body.get("task_id"),
        request_hash=body.get("request_hash"),
        state=state,
        flow=flow,
    )


def _result_payload(result) -> object:
    """优先读取 structured content；null 等非对象结果从单一文本 JSON 恢复。"""

    if result.is_error:
        messages = [
            block.text
            for block in result.content
            if isinstance(block, TextContent)
        ]
        detail = " | ".join(messages) if messages else "unknown MCP tool error"
        raise RuntimeError(f"Product Front Door MCP tool failed: {detail}")

    if result.structured_content is not None:
        return result.structured_content
    text_blocks = [
        block.text
        for block in result.content
        if isinstance(block, TextContent)
    ]
    if len(text_blocks) != 1:
        raise ValueError("Product Front Door MCP result must contain one JSON text block")
    try:
        return json.loads(text_blocks[0])
    except json.JSONDecodeError as exc:
        raise ValueError("Product Front Door MCP result text is not valid JSON") from exc


class ProductFrontDoorMcpClient:
    """只通过配置的 loopback Streamable HTTP URL 调用 Product Front Door。"""

    def __init__(self, endpoint_url: str) -> None:
        """冻结并验证本地 endpoint；v1 不允许静默扩张到 remote trust boundary。"""

        if not isinstance(endpoint_url, str) or not endpoint_url.strip():
            raise ValueError("endpoint_url must be a non-blank loopback URL")
        normalized = endpoint_url.strip()
        parsed = urlsplit(normalized)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname is None
            or parsed.hostname.lower() not in _LOOPBACK_HOSTS
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("Product Front Door MCP endpoint must be a loopback URL")
        try:
            port = parsed.port
        except ValueError as exc:
            raise ValueError("Product Front Door MCP endpoint must use a valid loopback port") from exc
        if port is not None and not 1 <= port <= 65535:
            raise ValueError("Product Front Door MCP endpoint must use a valid loopback port")
        self.endpoint_url = normalized

    async def _call(self, tool_name: str, arguments: dict[str, object]) -> object:
        """每次调用都通过真实 SDK session negotiation/list/call，不保留第二份 transport state。"""

        async with Client(self.endpoint_url) as client:
            catalog = await client.list_tools()
            if tool_name not in {tool.name for tool in catalog.tools}:
                raise RuntimeError(f"Product Front Door MCP tool is unavailable: {tool_name}")
            result = await client.call_tool(tool_name, arguments)
        return _result_payload(result)

    async def submit(self, request: ProductTaskRequest) -> ProductTaskQueryView:
        """发送完整 frozen request；客户端不分配或重算 task/session identity。"""

        if not isinstance(request, ProductTaskRequest):
            raise TypeError("request must be a ProductTaskRequest")
        payload = {
            "task_id": request.task_id,
            "project_id": request.project_id,
            "host_kind": request.host_kind,
            "session_ref": request.session_ref,
            "requested_action": request.requested_action,
            "intent_arguments": _plain_json(request.intent_arguments),
            "request_hash": request.request_hash,
        }
        view = _decode_query_view(await self._call(_SUBMIT_TOOL, payload))
        if view is None:
            raise ValueError("Product Front Door submit returned null task view")
        return view

    async def get(self, task_id: str) -> ProductTaskQueryView | None:
        """只按 exact task_id 查询；不提供 listing、latest 或 session fallback。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-blank string")
        return _decode_query_view(
            await self._call(_GET_TOOL, {"task_id": task_id})
        )

    async def resume_operation_proposal(
        self,
        *,
        task_id: str,
        pause_id: str,
        resume_kind: str,
    ) -> ProductTaskQueryView:
        """发送 exact operation-proposal human resume；不接受 arbitrary approval payload。"""

        if not isinstance(task_id, str) or not task_id.strip():
            raise ValueError("task_id must be a non-blank string")
        if not isinstance(pause_id, str) or not pause_id.strip():
            raise ValueError("pause_id must be a non-blank string")
        if resume_kind not in _RESUME_KINDS:
            raise ValueError("resume_kind must be an Operation Proposal human decision")
        view = _decode_query_view(
            await self._call(
                _RESUME_TOOL,
                {
                    "task_id": task_id,
                    "pause_id": pause_id,
                    "resume_kind": resume_kind,
                },
            )
        )
        if view is None:
            raise ValueError("Product Front Door resume returned null task view")
        return view


__all__ = ["ProductFrontDoorMcpClient"]
