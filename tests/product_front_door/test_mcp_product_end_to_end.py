"""Task 9：真实 loopback MCP 跨 Front Door / durable owner 的产品验收。"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import design_product_front_door as front_door
import psycopg
import pytest
from design_product_runtime import (
    ProductTaskQueryState,
    ProductTaskRequest,
    create_postgres_product_task_request_store,
)


def _reserve_loopback_port() -> int:
    """向内核申请临时 loopback 端口；随后由真实 MCP server 子进程重新绑定。"""

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_server(port: int, process: subprocess.Popen[str]) -> None:
    """等待真实 HTTP listener；子进程提前退出时把 stderr 带回 acceptance。"""

    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        if process.poll() is not None:
            stderr = process.stderr.read() if process.stderr is not None else ""
            raise AssertionError(f"Task 9 MCP server 提前退出：{stderr}")
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.05)
    raise AssertionError("Task 9 MCP server 未在期限内监听 loopback 端口")


@contextmanager
def _real_mcp_server(script: str, *arguments: str):
    """在独立 Python 进程运行 production Streamable HTTP server。"""

    port = _reserve_loopback_port()
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    # pytest 的 workspace pythonpath 不会自动传播给 ``python -c`` 子进程，因此显式透传。
    env["PYTHONPATH"] = os.pathsep.join(str(item) for item in sys.path)
    process = subprocess.Popen(
        [sys.executable, "-c", script, str(port), *arguments],
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


def _request(
    task_id: str,
    *,
    project_id: str = "project-task9-mcp",
    session_ref: str = "session-task9-mcp",
) -> ProductTaskRequest:
    """构造完整 immutable ProductTask；MCP client 不得补写 authority。"""

    return ProductTaskRequest.create(
        task_id=task_id,
        project_id=project_id,
        host_kind="REVIT",
        session_ref=session_ref,
        requested_action="SET_SELECTED_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300.0, "unit": "mm"}},
    )


_CANDIDATE_DRIFT_SERVER = r'''
import sys
from pathlib import Path

from design_changeset import canonical_hash
from design_product_front_door import (
    ConfiguredRevitCandidate,
    SessionBinding,
    configured_revit_candidate_hash_body,
    run_streamable_http,
    session_binding_hash_body,
)
from design_product_front_door.service import ProductFrontDoorService


class _SessionReader:
    def __init__(self, binding):
        self._binding = binding

    def resolve_session(self, session_ref):
        assert session_ref == self._binding.session_ref
        return self._binding


class _CandidateSource:
    def __init__(self, candidate):
        self._candidate = candidate

    def get(self, candidate_key):
        assert candidate_key == self._candidate.candidate_key
        return self._candidate


class _Forbidden:
    def __getattr__(self, name):
        raise AssertionError(f"candidate drift must fail before forbidden seam: {name}")

    def __call__(self, *args, **kwargs):
        raise AssertionError(
            f"candidate drift must fail before Host access: {args=} {kwargs=}"
        )


class _RecordingService:
    """仅把 server 侧真实错误写入 test telemetry；MCP 仍保持默认错误净化。"""

    def __init__(self, delegate, telemetry_path):
        self._delegate = delegate
        self._telemetry_path = Path(telemetry_path)

    def submit(self, request):
        try:
            return self._delegate.submit(request)
        except Exception as exc:
            self._telemetry_path.write_text(str(exc), encoding="utf-8")
            raise

    def get(self, task_id):
        return self._delegate.get(task_id)

    def resume_operation_proposal(self, *, task_id, pause_id, resume_kind):
        return self._delegate.resume_operation_proposal(
            task_id=task_id,
            pause_id=pause_id,
            resume_kind=resume_kind,
        )


frozen_body = configured_revit_candidate_hash_body(
    candidate_key="revit-task9-mcp",
    project_id="project-task9-mcp",
    transport_locator="revit-task9-mcp-pipe",
    document_id=r"C:\\DSP\\Task9Mcp.rvt",
    semantic_target_id="WALL-TASK9-MCP",
    native_target_unique_id="WALL-NATIVE-FROZEN",
)
frozen_candidate = ConfiguredRevitCandidate(
    **frozen_body,
    candidate_hash=canonical_hash(frozen_body),
)
binding_body = session_binding_hash_body(
    session_ref="session-task9-mcp",
    project_id=frozen_candidate.project_id,
    host_kind="REVIT",
    candidate_key=frozen_candidate.candidate_key,
    candidate_hash=frozen_candidate.candidate_hash,
    transport_locator=frozen_candidate.transport_locator,
    host_instance_id="REVIT-TASK9-MCP",
    document_id=frozen_candidate.document_id,
)
binding = SessionBinding(
    **binding_body,
    document_title="Task9Mcp.rvt",
    binding_hash=canonical_hash(binding_body),
)

# 同一个 candidate_key 在 freeze 后被编辑：target identity 变化，因此 canonical hash 变化。
current_body = configured_revit_candidate_hash_body(
    candidate_key=frozen_candidate.candidate_key,
    project_id=frozen_candidate.project_id,
    transport_locator=frozen_candidate.transport_locator,
    document_id=frozen_candidate.document_id,
    semantic_target_id=frozen_candidate.semantic_target_id,
    native_target_unique_id="WALL-NATIVE-DRIFTED",
)
current_candidate = ConfiguredRevitCandidate(
    **current_body,
    candidate_hash=canonical_hash(current_body),
)
forbidden = _Forbidden()
service = ProductFrontDoorService(
    session_binding_reader=_SessionReader(binding),
    candidate_source=_CandidateSource(current_candidate),
    context_probe=forbidden,
    transport_factory=forbidden,
    query_service=forbidden,
    composition_pool=forbidden,
)
run_streamable_http(
    _RecordingService(service, sys.argv[2]),
    host="127.0.0.1",
    port=int(sys.argv[1]),
)
'''


_DURABLE_GET_SERVER = r'''
import sys

from design_orchestrator import LangGraphWorkflowCheckpointReader
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_product_front_door import run_streamable_http
from design_product_front_door.service import ProductFrontDoorService
from design_product_runtime import (
    ProductTaskQueryService,
    create_postgres_product_task_request_store,
)


class _NoSagaStore:
    def get_saga(self, saga_id):
        raise AssertionError(f"request-only GET must not read Saga owner: {saga_id}")


class _HostUnavailable:
    def __getattr__(self, name):
        raise AssertionError(f"host-independent GET touched unavailable seam: {name}")

    def __call__(self, *args, **kwargs):
        raise AssertionError(
            f"host-independent GET attempted Host access: {args=} {kwargs=}"
        )


port = int(sys.argv[1])
dsn = sys.argv[2]
request_store = create_postgres_product_task_request_store(dsn)
checkpointer = create_postgres_checkpointer(dsn)
query = ProductTaskQueryService(
    request_store=request_store,
    checkpoint_reader=LangGraphWorkflowCheckpointReader(checkpointer=checkpointer),
    saga_store=_NoSagaStore(),
)
unavailable = _HostUnavailable()
service = ProductFrontDoorService(
    session_binding_reader=unavailable,
    candidate_source=unavailable,
    context_probe=unavailable,
    transport_factory=unavailable,
    query_service=query,
    composition_pool=unavailable,
)
run_streamable_http(service, host="127.0.0.1", port=port)
'''


def _postgres_dsn() -> str:
    """Task 9 durable MCP acceptance 只在显式 PostgreSQL 17 lane 运行。"""

    dsn = os.getenv("DSP_TEST_POSTGRES_DSN", "").strip()
    if not dsn:
        pytest.skip("DSP_TEST_POSTGRES_DSN is required")
    return dsn


def _reset_query_schemas(dsn: str) -> None:
    """从 fresh ProductTask/checkpoint owner schemas 开始，避免跨测试 lineage 污染。"""

    with psycopg.connect(dsn, autocommit=True) as connection:
        connection.execute("DROP SCHEMA IF EXISTS product_task CASCADE")
        connection.execute("DROP SCHEMA IF EXISTS orchestrator_checkpoint CASCADE")


@pytest.mark.asyncio
async def test_real_mcp_submit_candidate_drift_fails_before_host_or_workflow(
    tmp_path,
) -> None:
    """freeze 后 same-key candidate 漂移时，真实 MCP submit 必须在 Host/flow 前 fail closed。"""

    request = _request("task-task9-candidate-drift")
    telemetry = tmp_path / "candidate-drift.txt"
    with _real_mcp_server(_CANDIDATE_DRIFT_SERVER, str(telemetry)) as endpoint_url:
        client = front_door.ProductFrontDoorMcpClient(endpoint_url)
        with pytest.raises(RuntimeError, match="Product Front Door MCP tool failed"):
            await client.submit(request)

    assert telemetry.read_text(encoding="utf-8") == "FRONT_DOOR_CANDIDATE_DRIFT"


@pytest.mark.asyncio
async def test_real_mcp_get_reads_postgres_when_host_is_unavailable() -> None:
    """task create 已 durable commit 后，即使 Host seams 全不可用，GET 仍只读 owner truth。"""

    dsn = _postgres_dsn()
    _reset_query_schemas(dsn)
    request = _request("task-task9-host-unavailable")

    # 先由独立 caller durable-create ProductTask，再关闭连接，模拟 server 进程之外的已提交事实。
    request_store = create_postgres_product_task_request_store(dsn)
    try:
        request_store.create(request)
    finally:
        request_store.close()

    with _real_mcp_server(_DURABLE_GET_SERVER, dsn) as endpoint_url:
        client = front_door.ProductFrontDoorMcpClient(endpoint_url)
        view = await client.get(request.task_id)

    assert view is not None
    assert view.task_id == request.task_id
    assert view.request_hash == request.request_hash
    assert view.state is ProductTaskQueryState.ACCEPTED_PRE_WORKFLOW
    assert view.flow is None
