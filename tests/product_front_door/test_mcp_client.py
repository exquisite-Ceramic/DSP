"""Task 8：真实 loopback Streamable HTTP MCP client 契约测试。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import design_product_front_door as front_door
import pytest
from design_product_runtime import ProductTaskQueryState, ProductTaskRequest
from mcp import Client

_FROZEN_TOOLS = {
    "product.wall_thickness.submit",
    "product.wall_thickness.get",
    "product.wall_thickness.resume_operation_proposal",
}


def _client_type():
    """延迟取得 Task 8 public client；缺失时形成明确、可诊断的 TDD RED。"""

    client_type = getattr(front_door, "ProductFrontDoorMcpClient", None)
    assert client_type is not None, "ProductFrontDoorMcpClient 尚未实现"
    return client_type


def _request() -> ProductTaskRequest:
    """构造完整 immutable ProductTask；client 不得补写或重算业务 identity。"""

    return ProductTaskRequest.create(
        task_id="task-mcp-client-001",
        project_id="project-001",
        host_kind="REVIT",
        session_ref="session-mcp-client-001",
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


def _reserve_loopback_port() -> int:
    """只向内核申请一个临时 loopback 端口；真正 server 随后重新绑定该端口。"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(port: int, process: subprocess.Popen[str]) -> None:
    """等待真实 HTTP listener 建立；子进程提前退出时立即报告 stderr。"""

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"Product Front Door MCP server 提前退出：{stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("Product Front Door MCP server 未在期限内监听 loopback 端口")


_SERVER_SCRIPT = r'''
import sys

from design_orchestrator import (
    PendingInteractionKind,
    PendingInteractionView,
    StableRef,
    WorkflowCheckpointView,
    WorkflowPhase,
)
from design_product_front_door import run_streamable_http
from design_product_runtime import (
    ProductFlowStatus,
    ProductFlowView,
    ProductTaskQueryState,
    ProductTaskQueryView,
)


class _Service:
    """只为真实 MCP transport 测试提供 deterministic service owner 投影。"""

    def __init__(self):
        self.request = None
        self.resumed = False

    def _pending(self):
        checkpoint = WorkflowCheckpointView(
            task_id=self.request.task_id,
            phase=WorkflowPhase.AWAIT_OPERATION_PROPOSAL,
            pending_interaction=PendingInteractionView(
                pause_id="pause-mcp-client-001",
                kind=PendingInteractionKind.OPERATION_PROPOSAL,
                subject_ref=StableRef(ref_id="operation-mcp-client-001", content_hash="0" * 64),
                allowed_resume_kinds=(
                    "OPERATION_PROPOSAL_ACCEPTED",
                    "OPERATION_PROPOSAL_REJECTED",
                ),
            ),
        )
        return ProductTaskQueryView(
            task_id=self.request.task_id,
            request_hash=self.request.request_hash,
            state=ProductTaskQueryState.WORKFLOW,
            flow=ProductFlowView(status=ProductFlowStatus.WAITING, checkpoint=checkpoint),
        )

    def _terminal(self):
        checkpoint = WorkflowCheckpointView(
            task_id=self.request.task_id,
            phase=WorkflowPhase.COMPLETED,
        )
        return ProductTaskQueryView(
            task_id=self.request.task_id,
            request_hash=self.request.request_hash,
            state=ProductTaskQueryState.WORKFLOW,
            flow=ProductFlowView(status=ProductFlowStatus.SUCCEEDED, checkpoint=checkpoint),
        )

    def submit(self, request):
        self.request = request
        return self._pending()

    def get(self, task_id):
        if self.request is None or task_id != self.request.task_id:
            return None
        return self._terminal() if self.resumed else self._pending()

    def resume_operation_proposal(self, *, task_id, pause_id, resume_kind):
        assert self.request is not None
        assert task_id == self.request.task_id
        assert pause_id == "pause-mcp-client-001"
        assert resume_kind == "OPERATION_PROPOSAL_ACCEPTED"
        self.resumed = True
        return self._terminal()


run_streamable_http(_Service(), host="127.0.0.1", port=int(sys.argv[1]))
'''


@contextmanager
def _real_mcp_server():
    """在独立 Python 进程运行真实 Product Front Door Streamable HTTP server。"""

    port = _reserve_loopback_port()
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    # pytest 的 pythonpath 注入不会自动传播给子进程；这里原样传递当前解释器搜索路径。
    env["PYTHONPATH"] = os.pathsep.join(str(item) for item in sys.path)
    process = subprocess.Popen(
        [sys.executable, "-c", _SERVER_SCRIPT, str(port)],
        cwd=repo_root,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        _wait_for_server(port, process)
        yield f"http://127.0.0.1:{port}/mcp"
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.asyncio
async def test_real_loopback_client_negotiates_lists_and_calls_all_frozen_tools() -> None:
    """真实 URL 必须经过 MCP SDK negotiation/list/call，不能退化为 Python direct call。"""

    client_type = _client_type()
    request = _request()

    with _real_mcp_server() as endpoint_url:
        async with Client(endpoint_url) as sdk_client:
            catalog = await sdk_client.list_tools()
            assert {tool.name for tool in catalog.tools} == _FROZEN_TOOLS

        client = client_type(endpoint_url)
        submitted = await client.submit(request)
        assert submitted.task_id == request.task_id
        assert submitted.request_hash == request.request_hash
        assert submitted.state is ProductTaskQueryState.WORKFLOW
        assert submitted.flow is not None
        assert submitted.flow.checkpoint.pending_interaction is not None
        assert submitted.flow.checkpoint.pending_interaction.pause_id == "pause-mcp-client-001"

        resumed = await client.resume_operation_proposal(
            task_id=request.task_id,
            pause_id="pause-mcp-client-001",
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        )
        assert resumed.task_id == request.task_id
        assert resumed.flow is not None
        assert resumed.flow.status.value == "SUCCEEDED"

        queried = await client.get(request.task_id)
        assert queried is not None
        assert queried.task_id == request.task_id
        assert queried.request_hash == request.request_hash
        assert queried.flow is not None
        assert queried.flow.status.value == "SUCCEEDED"


@pytest.mark.parametrize(
    "endpoint_url",
    [
        "http://0.0.0.0:8010/mcp",
        "http://192.168.1.20:8010/mcp",
        "https://example.com/mcp",
    ],
)
def test_mcp_client_rejects_non_loopback_endpoint(endpoint_url: str) -> None:
    """v1 client trust boundary只允许显式 loopback URL，不静默连接 remote endpoint。"""

    client_type = _client_type()
    with pytest.raises(ValueError, match="loopback"):
        client_type(endpoint_url)
