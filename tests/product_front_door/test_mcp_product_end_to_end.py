"""Task 9：真实 loopback MCP 跨 Front Door / durable owner 的产品验收。"""

from __future__ import annotations

import importlib.util
import json
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
from design_changeset import canonical_hash
from design_orchestrator import WorkflowPhase, WorkflowResumeCommand
from design_orchestrator.workflow_services import WorkflowStateError
from design_product_runtime import (
    ProductFlowStatus,
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


def _load_product_runtime_acceptance_helpers():
    """复用现有 Product Runtime acceptance composition，不复制第二套 runtime fixture。"""

    helper_path = (
        Path(__file__).resolve().parents[1] / "product_runtime" / "conftest.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_task9_product_runtime_acceptance_helpers",
        helper_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


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


_REFERENCE_PRODUCT_SERVER = r'''
import json
import sys
from pathlib import Path

from design_execution_reconciliation.postgres import (
    apply_execution_saga_migrations,
    connect_postgres,
)
from design_execution_reconciliation.postgres_saga_store_v2 import (
    PostgresExecutionSagaStoreV2,
)
from design_orchestrator import LangGraphWorkflowCheckpointReader
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_product_front_door import (
    ConfiguredRevitCandidateCatalog,
    SqliteSessionBindingReader,
    run_streamable_http,
)
from design_product_front_door.composition_pool import ExactSessionCompositionPool
from design_product_front_door.service import ProductFrontDoorService
from design_product_runtime import (
    ProductTaskQueryService,
    RevitWallThicknessCompositionConfig,
    build_revit_wall_thickness_reference_composition,
    create_postgres_product_task_request_store,
)
from revit_sidecar import RevitCurrentContextProbe
from tests.product_runtime.conftest import (
    StatefulRevitTransport,
    _ConfiguredPolicyAdmissionFactory,
)


class _RecordingTransport(StatefulRevitTransport):
    """只给 external Revit fake 增加 test telemetry，不改变其 Host 行为。"""

    def __init__(self, telemetry_path):
        super().__init__()
        self._telemetry_path = Path(telemetry_path)

    def request(self, command):
        result = super().request(command)
        with self._telemetry_path.open("a", encoding="utf-8") as stream:
            stream.write(
                json.dumps(
                    {
                        "operation": command.operation,
                        "execute_count": self.execute_count,
                        "revision": self.current_revision,
                        "thickness_mm": self.current_thickness_mm,
                    },
                    sort_keys=True,
                )
                + "\n"
            )
        return result


class _RecordingService:
    """只记录 server 侧 domain error，MCP 对客户端仍使用 SDK 默认错误净化。"""

    def __init__(self, delegate, error_path):
        self._delegate = delegate
        self._error_path = Path(error_path)

    def _record(self, callback, *args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except Exception as exc:
            self._error_path.write_text(str(exc), encoding="utf-8")
            raise

    def submit(self, request):
        return self._record(self._delegate.submit, request)

    def get(self, task_id):
        return self._record(self._delegate.get, task_id)

    def resume_operation_proposal(self, *, task_id, pause_id, resume_kind):
        return self._record(
            self._delegate.resume_operation_proposal,
            task_id=task_id,
            pause_id=pause_id,
            resume_kind=resume_kind,
        )


port = int(sys.argv[1])
dsn = sys.argv[2]
sqlite_path = sys.argv[3]
telemetry_path = sys.argv[4]
error_path = sys.argv[5]

candidate_source = ConfiguredRevitCandidateCatalog.from_mapping(
    {
        "version": "DSP_REVIT_CANDIDATES_V1",
        "candidates": [
            {
                "candidate_key": "revit-task9-reference",
                "project_id": "project-task9",
                "transport_locator": "task9-reference-transport",
                "document_id": "DOC-TASK9",
                "semantic_target_id": "WALL-001",
                "native_target_unique_id": "REVIT-UNIQUE-ID-TASK9",
            }
        ],
    }
)
session_reader = SqliteSessionBindingReader(sqlite_path)
transport = _RecordingTransport(telemetry_path)


def transport_factory(locator):
    assert locator == "task9-reference-transport"
    return transport


approval_factory = _ConfiguredPolicyAdmissionFactory(
    dsn,
    admission_prefix="ADM-TASK9-MCP",
)


def composition_factory(*, binding, candidate):
    return build_revit_wall_thickness_reference_composition(
        config=RevitWallThicknessCompositionConfig(
            dsn=dsn,
            session_ref=binding.session_ref,
            document_id=binding.document_id,
            host_instance_id=binding.host_instance_id,
            semantic_target_id=candidate.semantic_target_id,
            native_target_unique_id=candidate.native_target_unique_id,
        ),
        transport=transport,
        approval_admission_factory=approval_factory,
    )


apply_connection = connect_postgres(dsn)
apply_execution_saga_migrations(apply_connection)
apply_connection.close()
request_store = create_postgres_product_task_request_store(dsn)
checkpointer = create_postgres_checkpointer(dsn)
saga_connection = connect_postgres(dsn)
saga_store = PostgresExecutionSagaStoreV2(saga_connection)
query = ProductTaskQueryService(
    request_store=request_store,
    checkpoint_reader=LangGraphWorkflowCheckpointReader(checkpointer=checkpointer),
    saga_store=saga_store,
)
service = ProductFrontDoorService(
    session_binding_reader=session_reader,
    candidate_source=candidate_source,
    context_probe=RevitCurrentContextProbe,
    transport_factory=transport_factory,
    query_service=query,
    composition_pool=ExactSessionCompositionPool(factory=composition_factory),
)
run_streamable_http(
    _RecordingService(service, error_path),
    host="127.0.0.1",
    port=port,
)
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


def _freeze_reference_submission(database_path: Path, request: ProductTaskRequest) -> None:
    """把 production-shaped request/session binding 原子冻结进 SQLite，供独立 MCP server 读取。"""

    candidate_source = front_door.ConfiguredRevitCandidateCatalog.from_mapping(
        {
            "version": "DSP_REVIT_CANDIDATES_V1",
            "candidates": [
                {
                    "candidate_key": "revit-task9-reference",
                    "project_id": "project-task9",
                    "transport_locator": "task9-reference-transport",
                    "document_id": "DOC-TASK9",
                    "semantic_target_id": "WALL-001",
                    "native_target_unique_id": "REVIT-UNIQUE-ID-TASK9",
                }
            ],
        }
    )
    candidate = candidate_source.get("revit-task9-reference")
    assert candidate is not None
    binding_body = front_door.session_binding_hash_body(
        session_ref=request.session_ref,
        project_id=request.project_id,
        host_kind=request.host_kind,
        candidate_key=candidate.candidate_key,
        candidate_hash=candidate.candidate_hash,
        transport_locator=candidate.transport_locator,
        host_instance_id="REVIT-TASK9",
        document_id=candidate.document_id,
    )
    binding = front_door.SessionBinding(
        **binding_body,
        document_title="Product E2E Fixture",
        binding_hash=canonical_hash(binding_body),
    )
    proposal = front_door.NormalizedFreezeProposal(
        project_id=request.project_id,
        host_kind=request.host_kind,
        requested_action=request.requested_action,
        intent_arguments=request.intent_arguments,
        candidate_key=candidate.candidate_key,
        candidate_hash=candidate.candidate_hash,
    )
    store = front_door.SqliteFrontDoorStateStore(str(database_path))
    try:
        correlation = f"submission:{request.task_id}"
        store.create_submission(correlation, "把当前选中墙体厚度改成 300mm")
        frozen = store.freeze_submission(
            client_submission_ref=correlation,
            proposal=proposal,
            binding=binding,
            request=request,
        )
        assert frozen.request == request
        assert frozen.session_binding == binding
    finally:
        store.close()


def _telemetry_operations(path: Path) -> tuple[str, ...]:
    """读取子进程写出的 Host operation 顺序；空文件精确表示没有 Host I/O。"""

    if not path.exists():
        return ()
    return tuple(
        json.loads(line)["operation"]
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )


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

    assert telemetry.read_text(encoding="utf-8").startswith(
        "FRONT_DOOR_CANDIDATE_DRIFT:"
    )


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


def test_context_snapshot_pause_composition_rebuild_fails_closed_without_host_mutation() -> None:
    """ContextSnapshot 形成后重建 composition 只能恢复 durable pause，resume 必须 fail closed。"""

    helpers = _load_product_runtime_acceptance_helpers()
    dsn = _postgres_dsn()
    task_id = "task-front-door-context-restart"
    first = helpers._build_reference_case(
        dsn,
        task_id,
        reset_schema=True,
    )
    host = first.host
    request = first.request
    try:
        proposal = first.flow.submit(request)
        assert proposal.status is ProductFlowStatus.WAITING
        assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        pending = proposal.checkpoint.pending_interaction
        assert pending is not None
        context_ref = proposal.checkpoint.context_snapshot_ref
        assert context_ref is not None
        snapshot = first.snapshot_registry.get_snapshot(context_ref.ref_id)
        assert snapshot.hash == context_ref.content_hash
        assert host.execute_count == 0
        command = WorkflowResumeCommand(
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            pause_id=pending.pause_id,
        )
    finally:
        helpers._close_case(first)

    # 新 composition 复用 PostgreSQL durable owners 与同一 Host，但天然创建新的内存
    # SnapshotRegistry；Task 9 只验证当前 v1 fail-closed，不伪造跨进程 snapshot recovery。
    rebuilt = helpers._build_reference_case(
        dsn,
        task_id,
        reset_schema=False,
        host=host,
        request=request,
    )
    try:
        restored = rebuilt.flow.get(task_id)
        assert restored is not None
        assert restored.status is ProductFlowStatus.WAITING
        assert restored.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        assert restored.checkpoint.context_snapshot_ref == context_ref
        assert host.execute_count == 0

        with pytest.raises(WorkflowStateError) as captured:
            rebuilt.flow.resume(task_id, command)

        assert captured.value.code == "WORKFLOW_SERVICE_FAILURE"
        assert host.execute_count == 0
    finally:
        helpers._close_case(rebuilt)


@pytest.mark.asyncio
async def test_real_mcp_reference_flow_replays_submit_then_resumes_same_server(
    tmp_path,
) -> None:
    """真实 MCP 正向流必须复用 exact-session composition，并把重送 submit 收敛到同一 pause。"""

    helpers = _load_product_runtime_acceptance_helpers()
    dsn = _postgres_dsn()
    helpers._reset_product_acceptance_schemas(dsn)
    request = helpers._request("task-front-door-real-mcp-positive")
    database_path = tmp_path / "front-door.sqlite3"
    telemetry_path = tmp_path / "host-telemetry.jsonl"
    error_path = tmp_path / "server-error.txt"
    _freeze_reference_submission(database_path, request)

    with _real_mcp_server(
        _REFERENCE_PRODUCT_SERVER,
        dsn,
        str(database_path),
        str(telemetry_path),
        str(error_path),
    ) as endpoint_url:
        client = front_door.ProductFrontDoorMcpClient(endpoint_url)
        first = await client.submit(request)
        assert first.state is ProductTaskQueryState.WORKFLOW
        assert first.flow is not None
        assert first.flow.status is ProductFlowStatus.WAITING
        assert first.flow.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        pending = first.flow.checkpoint.pending_interaction
        assert pending is not None
        assert "set_wall_thickness" not in _telemetry_operations(telemetry_path)

        # 模拟 submit response loss：客户端只用同一个 frozen request 重送，不能生成新 task/session。
        replayed = await client.submit(request)
        assert replayed.task_id == first.task_id
        assert replayed.request_hash == first.request_hash
        assert replayed.flow is not None
        assert replayed.flow.checkpoint.pending_interaction == pending
        assert "set_wall_thickness" not in _telemetry_operations(telemetry_path)

        completed = await client.resume_operation_proposal(
            task_id=request.task_id,
            pause_id=pending.pause_id,
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        )
        assert completed.state is ProductTaskQueryState.WORKFLOW
        assert completed.flow is not None
        assert completed.flow.status is ProductFlowStatus.SUCCEEDED
        assert completed.flow.workflow_phase is WorkflowPhase.COMPLETED

    operations = _telemetry_operations(telemetry_path)
    assert operations.count("set_wall_thickness") == 1
    assert not error_path.exists()


@pytest.mark.asyncio
async def test_real_mcp_server_restart_keeps_get_but_resume_fails_closed(
    tmp_path,
) -> None:
    """pause 后真实 server 进程重启：durable GET 仍可读，但丢失内存 snapshot 后 resume 必须拒绝。"""

    helpers = _load_product_runtime_acceptance_helpers()
    dsn = _postgres_dsn()
    helpers._reset_product_acceptance_schemas(dsn)
    request = helpers._request("task-front-door-real-mcp-restart")
    database_path = tmp_path / "front-door.sqlite3"
    telemetry_path = tmp_path / "host-telemetry.jsonl"
    first_error = tmp_path / "first-server-error.txt"
    second_error = tmp_path / "second-server-error.txt"
    _freeze_reference_submission(database_path, request)

    with _real_mcp_server(
        _REFERENCE_PRODUCT_SERVER,
        dsn,
        str(database_path),
        str(telemetry_path),
        str(first_error),
    ) as endpoint_url:
        first_client = front_door.ProductFrontDoorMcpClient(endpoint_url)
        paused = await first_client.submit(request)
        assert paused.flow is not None
        assert paused.flow.status is ProductFlowStatus.WAITING
        pending = paused.flow.checkpoint.pending_interaction
        assert pending is not None
        context_ref = paused.flow.checkpoint.context_snapshot_ref
        assert context_ref is not None

    assert "set_wall_thickness" not in _telemetry_operations(telemetry_path)

    # 第二个 context manager 启动全新的 Python/MCP server 进程；只复用 SQLite/PostgreSQL durable facts。
    with _real_mcp_server(
        _REFERENCE_PRODUCT_SERVER,
        dsn,
        str(database_path),
        str(telemetry_path),
        str(second_error),
    ) as endpoint_url:
        rebuilt_client = front_door.ProductFrontDoorMcpClient(endpoint_url)
        restored = await rebuilt_client.get(request.task_id)
        assert restored is not None
        assert restored.flow is not None
        assert restored.flow.status is ProductFlowStatus.WAITING
        assert restored.flow.checkpoint.context_snapshot_ref == context_ref

        with pytest.raises(RuntimeError, match="Product Front Door MCP tool failed"):
            await rebuilt_client.resume_operation_proposal(
                task_id=request.task_id,
                pause_id=pending.pause_id,
                resume_kind="OPERATION_PROPOSAL_ACCEPTED",
            )

    assert second_error.read_text(encoding="utf-8").startswith(
        "WORKFLOW_SERVICE_FAILURE:"
    )
    assert "set_wall_thickness" not in _telemetry_operations(telemetry_path)
