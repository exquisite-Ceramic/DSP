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
from datetime import UTC, datetime
from pathlib import Path

import design_product_front_door as front_door
import psycopg
import pytest
from design_changeset import canonical_hash
from design_orchestrator import PendingInteractionKind, WorkflowPhase, WorkflowResumeCommand
from design_orchestrator.checkpoint_postgres import create_postgres_checkpointer
from design_orchestrator.langgraph_checkpoint_reader import (
    LangGraphWorkflowCheckpointReader,
)
from design_orchestrator.workflow_services import WorkflowStateError
from design_product_runtime import (
    ProductFlowStatus,
    ProductTaskQueryState,
    ProductTaskRequest,
    create_postgres_product_task_request_store,
)
from revit_sidecar import RevitCurrentContextProbe


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


_REFERENCE_DOCUMENT_ID = "/DSP/fixtures/Task9Reference.rvt"


class _RecordingTransport(StatefulRevitTransport):
    """只给 external Revit fake 增加 test telemetry，并统一 Front Door saved-document identity。"""

    def __init__(self, telemetry_path):
        super().__init__()
        self._telemetry_path = Path(telemetry_path)

    def request(self, command):
        result = super().request(command)
        # Product Runtime fixture 原本使用抽象 DOC-TASK9；跨 Front Door 验收必须让
        # context/readiness evidence 与 frozen absolute saved-document path 精确一致。
        if command.operation in {
            "context.current_selection",
            "check_wall_thickness_readiness",
        }:
            result["payload"]["document_id"] = _REFERENCE_DOCUMENT_ID
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
                "document_id": _REFERENCE_DOCUMENT_ID,
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
saga_store = PostgresExecutionSagaStoreV2(dsn)
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
                    "document_id": "/DSP/fixtures/Task9Reference.rvt",
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


def _accept_command(proposal) -> WorkflowResumeCommand:
    """从真实 operation-proposal pause 构造 exact accept command。"""

    pending = proposal.checkpoint.pending_interaction
    assert pending is not None
    return WorkflowResumeCommand(
        resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        pause_id=pending.pause_id,
    )


class _PolicySource:
    """返回固定 configured policy，并记录完整 ProductFlow 是否真正进入 policy boundary。"""

    def __init__(self, policy) -> None:
        self._policy = policy
        self.calls = 0

    def load(self):
        """返回测试指定 policy authority。"""

        self.calls += 1
        return self._policy


class _ForbiddenPolicySource:
    """错误 owner graph 必须在读取 configured policy 之前 fail closed。"""

    def __init__(self) -> None:
        self.calls = 0

    def load(self):
        """任何 policy 读取都代表 lineage gate 顺序错误。"""

        self.calls += 1
        raise AssertionError("wrong owner graph must fail before policy authorization")


class _PolicyClock:
    """为 Task 9 configured-policy acceptance 提供固定 UTC issuance 时间。"""

    def now(self) -> datetime:
        """返回 deterministic timezone-aware UTC。"""

        return datetime(2026, 9, 24, 9, 0, tzinfo=UTC)


class _WrongChangeSetOwner:
    """模拟误接到平行业务图的 ChangeSet owner；返回与 exact StableRef 不同的 hash。"""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def get(self, changeset_id: str):
        """记录 lookup，并返回明确不属于当前 workflow lineage 的对象。"""

        self.calls.append(changeset_id)

        class _WrongChangeSet:
            changeset_hash = "f" * 64

        return _WrongChangeSet()


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


def test_configured_policy_denies_after_proposal_before_host_mutation() -> None:
    """human accept 后 configured policy 拒绝 exact operation 时：

    完整 ProductFlow 必须在 Host 写入之前 fail closed。
    """

    helpers = _load_product_runtime_acceptance_helpers()
    dsn = _postgres_dsn()
    case = helpers._build_reference_case(
        dsn,
        "task-front-door-policy-deny",
        reset_schema=True,
    )
    admission_store = front_door.PostgresConfiguredPolicyAdmissionStore(dsn)
    try:
        proposal = case.flow.submit(case.request)
        assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        owner_ports = case.runtime._services._external_owners
        deny_policy = front_door.ConfiguredProductApprovalPolicy.from_mapping(
            {
                "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
                "policy_id": "task9-deny-set-wall-thickness",
                "principal": "user:task9-policy-test",
                "project_ids": ["project-task9"],
                "allowed_canonical_operations": ["inspect_wall.v1"],
                "admission_ttl_seconds": 900,
            }
        )
        policy_source = _PolicySource(deny_policy)
        owner_ports._approval_admission = front_door.ConfiguredPolicyApprovalAdmissionPort(
            changeset_store=owner_ports._changeset_store,
            approval_scope_store=owner_ports._approval_scope_store,
            admission_store=admission_store,
            policy_source=policy_source,
            clock=_PolicyClock(),
            id_factory=lambda: "ADM-TASK9-MUST-NOT-ISSUE",
        )

        with pytest.raises(WorkflowStateError) as captured:
            case.flow.resume(case.task_id, _accept_command(proposal))

        assert captured.value.code == "WORKFLOW_SERVICE_FAILURE"
        assert policy_source.calls == 1
        assert case.host.execute_count == 0
        assert "set_wall_thickness" not in case.host.command_operations()
    finally:
        admission_store.close()
        helpers._close_case(case)


def test_wrong_changeset_owner_graph_fails_before_policy_or_host_mutation() -> None:
    """configured-policy 误接平行 ChangeSet owner 时：

    必须在 policy issuance 与 Host 写入之前 fail closed。
    """

    helpers = _load_product_runtime_acceptance_helpers()
    dsn = _postgres_dsn()
    case = helpers._build_reference_case(
        dsn,
        "task-front-door-wrong-owner-graph",
        reset_schema=True,
    )
    admission_store = front_door.PostgresConfiguredPolicyAdmissionStore(dsn)
    try:
        proposal = case.flow.submit(case.request)
        assert proposal.workflow_phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        owner_ports = case.runtime._services._external_owners
        wrong_changesets = _WrongChangeSetOwner()
        forbidden_policy = _ForbiddenPolicySource()
        owner_ports._approval_admission = front_door.ConfiguredPolicyApprovalAdmissionPort(
            changeset_store=wrong_changesets,
            approval_scope_store=owner_ports._approval_scope_store,
            admission_store=admission_store,
            policy_source=forbidden_policy,
            clock=_PolicyClock(),
            id_factory=lambda: "ADM-TASK9-MUST-NOT-ISSUE",
        )

        with pytest.raises(WorkflowStateError) as captured:
            case.flow.resume(case.task_id, _accept_command(proposal))

        assert captured.value.code == "WORKFLOW_SERVICE_FAILURE"
        assert len(wrong_changesets.calls) == 1
        assert forbidden_policy.calls == 0
        assert case.host.execute_count == 0
        assert "set_wall_thickness" not in case.host.command_operations()
    finally:
        admission_store.close()
        helpers._close_case(case)


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
async def test_reference_client_uses_fake_agent_human_with_real_mcp_product_path(
    tmp_path,
) -> None:
    """offline positive path 串联：

    deterministic Agent/HumanDecision、真实 MCP transport 与 production owners。
    """

    helpers = _load_product_runtime_acceptance_helpers()
    dsn = _postgres_dsn()
    helpers._reset_product_acceptance_schemas(dsn)
    database_path = tmp_path / "reference-client.sqlite3"
    telemetry_path = tmp_path / "reference-client-host.jsonl"
    error_path = tmp_path / "reference-client-server-error.txt"
    candidate_source = front_door.ConfiguredRevitCandidateCatalog.from_mapping(
        {
            "version": "DSP_REVIT_CANDIDATES_V1",
            "candidates": [
                {
                    "candidate_key": "revit-task9-reference",
                    "project_id": "project-task9",
                    "transport_locator": "task9-reference-transport",
                    "document_id": "/DSP/fixtures/Task9Reference.rvt",
                    "semantic_target_id": "WALL-001",
                    "native_target_unique_id": "REVIT-UNIQUE-ID-TASK9",
                }
            ],
        }
    )

    class _DeterministicAgent:
        """只把固定自然语言解释成冻结的窄 proposal，不拥有业务 identity。"""

        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def interpret(self, *, client_submission_ref: str, utterance: str):
            """记录 correlation/utterance，并返回固定 300mm proposal。"""

            self.calls.append((client_submission_ref, utterance))
            return front_door.AgentProposal(
                candidate_key="revit-task9-reference",
                thickness_value=300.0,
                thickness_unit="mm",
            )

    class _ClientContextTransport:
        """仅模拟 reference client freeze 前的外部 Revit context READ。"""

        def __init__(self) -> None:
            self._delegate = helpers.StatefulRevitTransport()

        def request(self, command):
            """复用既有 Revit fake，并把 saved-document identity 对齐 candidate。"""

            result = self._delegate.request(command)
            if command.operation == "context.current_selection":
                result["payload"]["document_id"] = "/DSP/fixtures/Task9Reference.rvt"
            return result

    class _AcceptHumanDecision:
        """只对 owner-derived operation proposal 返回显式 accept。"""

        def __init__(self) -> None:
            self.pending: list[object] = []

        def decide(self, pending):
            """记录真实 pending，并返回其中允许的 accept resume kind。"""

            self.pending.append(pending)
            assert "OPERATION_PROPOSAL_ACCEPTED" in pending.allowed_resume_kinds
            return "OPERATION_PROPOSAL_ACCEPTED"

    store = front_door.SqliteFrontDoorStateStore(str(database_path))
    agent = _DeterministicAgent()
    human = _AcceptHumanDecision()
    client_transport = _ClientContextTransport()
    controller = front_door.SubmissionController(
        state_store=store,
        agent_interpreter=agent,
        candidate_source=candidate_source,
        context_probe_factory=lambda locator: RevitCurrentContextProbe(client_transport),
        session_ref_factory=lambda: "revit-session-product-e2e",
        task_id_factory=lambda: "task-front-door-reference-client-real-mcp",
    )
    try:
        with _real_mcp_server(
            _REFERENCE_PRODUCT_SERVER,
            dsn,
            str(database_path),
            str(telemetry_path),
            str(error_path),
        ) as endpoint_url:
            reference_client = front_door.ReferenceClient(
                state_store=store,
                submission_controller=controller,
                mcp_client=front_door.ProductFrontDoorMcpClient(endpoint_url),
                human_decision_port=human,
            )
            result = await reference_client.run_submission(
                client_submission_ref="submission-task9-reference-client",
                utterance="把当前选中的墙体厚度改成 300mm",
            )

        assert result.state is ProductTaskQueryState.WORKFLOW
        assert result.flow is not None
        assert result.flow.status is ProductFlowStatus.SUCCEEDED
        assert result.flow.workflow_phase is WorkflowPhase.COMPLETED
        assert agent.calls == [
            (
                "submission-task9-reference-client",
                "把当前选中的墙体厚度改成 300mm",
            )
        ]
        assert len(human.pending) == 1
        assert _telemetry_operations(telemetry_path).count("set_wall_thickness") == 1
        assert not error_path.exists()
    finally:
        store.close()


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

    # 第二个 context manager 启动全新的 Python/MCP server 进程；
    # 只复用 SQLite/PostgreSQL durable facts。
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


_V2_QUERY_VIEW_SERVER = r'''
import sys

from design_product_front_door import run_streamable_http
from design_product_runtime import (
    ProductMaterializationQueryViewV2,
    ProductProposalStateV2,
    ProductTaskQueryState,
    ProductTaskQueryViewV2,
    ProductTaskV2Status,
)


class _Service:
    def get(self, task_id):
        assert task_id == "task-v2-wire"
        materialization = ProductMaterializationQueryViewV2(
            host_kind="AUTOCAD",
            host_instance_id="AUTOCAD-WIRE",
            document_id="/DSP/wire.dwg",
            native_target_id="HANDLE-1",
            semantic_target_id="WALL-001",
            materialization_id="MAT-A",
            execution_slice_hash="a" * 64,
            status="SUCCEEDED",
            expected_revision=10,
            committed_revision=11,
            observed_revision=11,
            verified_thickness_mm=300.0,
            actual_delta_hash="b" * 64,
            verification_hash="c" * 64,
            evidence_bundle_hash="d" * 64,
            convergence_result_hash="e" * 64,
            recovery_disposition=None,
            evidence_unavailable_reason=None,
        )
        return ProductTaskQueryViewV2(
            version="V2",
            task_id=task_id,
            request_hash="f" * 64,
            state=ProductTaskQueryState.WORKFLOW,
            status=ProductTaskV2Status.SUCCEEDED,
            proposal_state=ProductProposalStateV2.ACCEPTED,
            saga_id="SAGA-WIRE",
            convergence_result_hash="e" * 64,
            materializations=(materialization,),
        )

    def submit(self, request):
        raise AssertionError("wire GET acceptance must not submit")

    def resume_operation_proposal(self, **kwargs):
        raise AssertionError("wire GET acceptance must not resume")


run_streamable_http(_Service(), host="127.0.0.1", port=int(sys.argv[1]))
'''


@pytest.mark.asyncio
async def test_v2_mcp_get_decodes_explicit_version_without_changing_v1_shape() -> None:
    """真实 MCP client 依 version 解码 V2；GET 不需要 Host 或 client-side binding config。"""

    _load_product_runtime_acceptance_helpers()
    with _real_mcp_server(_V2_QUERY_VIEW_SERVER) as endpoint:
        client = front_door.ProductFrontDoorMcpClient(endpoint)
        view = await client.get("task-v2-wire")

    assert view is not None
    assert view.version == "V2"
    assert view.status.value == "SUCCEEDED"
    assert view.materializations[0].verified_thickness_mm == 300.0
    assert view.materializations[0].host_kind == "AUTOCAD"


_CROSS_HOST_PRODUCT_SERVER = r'''
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from design_execution_reconciliation.postgres import (
    apply_execution_saga_migrations,
    connect_postgres,
)
from design_materialization_topology import (
    MaterializationRequirement,
    MaterializationSlot,
    MaterializationTopologySnapshot,
    compute_topology_snapshot_hash,
)
from design_product_front_door import (
    ConfiguredPolicyApprovalAdmissionPortV2,
    ConfiguredProductApprovalPolicyV2,
    PostgresConfiguredPolicyAdmissionStore,
    SqliteSessionBindingReader,
    run_streamable_http,
)
from design_product_front_door.service import ProductFrontDoorService
from design_product_runtime import build_cross_host_product_reference_runtime
from host_contracts import HostCommandResult


port = int(sys.argv[1])
dsn = sys.argv[2]
sqlite_path = sys.argv[3]
config_path = Path(sys.argv[4])
telemetry_path = Path(sys.argv[5])
error_path = Path(sys.argv[6])
config = json.loads(config_path.read_text(encoding="utf-8"))


def _record(operation, *, host, revision, thickness, execute_count):
    with telemetry_path.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps(
                {
                    "operation": operation,
                    "host": host,
                    "revision": revision,
                    "thickness_mm": thickness,
                    "execute_count": execute_count,
                },
                sort_keys=True,
            )
            + "\n"
        )


class _AutoCadDispatcher:
    def __init__(self):
        self.revision = config["autocad_revision"]
        self.width_mm = 200.0
        self.execute_count = 0

    async def extract_design_facts(self, handles):
        assert tuple(handles) == (config["autocad_native_id"],)
        _record(
            "autocad.read",
            host="AUTOCAD",
            revision=self.revision,
            thickness=self.width_mm,
            execute_count=self.execute_count,
        )
        return DesignFactAdapter().normalize_snapshot(
            {
                "hostInstanceId": config["autocad_host_instance_id"],
                "documentId": config["autocad_document"],
                "revision": self.revision,
                "entities": [
                    {
                        "nativeId": config["autocad_native_id"],
                        "nativeKind": "LWPOLYLINE",
                        "layer": "A-WALL",
                        "properties": {
                            "constantWidth": {
                                "value": self.width_mm,
                                "unit": "mm",
                            }
                        },
                    }
                ],
            }
        )

    async def set_wall_thickness(
        self,
        handles,
        thickness_mm,
        *,
        idempotency_key,
        revision,
    ):
        assert tuple(handles) == (config["autocad_native_id"],)
        assert idempotency_key
        assert revision == self.revision
        before = self.width_mm
        self.execute_count += 1
        self.width_mm = float(thickness_mm)
        self.revision += 1
        _record(
            "autocad.execute",
            host="AUTOCAD",
            revision=self.revision,
            thickness=self.width_mm,
            execute_count=self.execute_count,
        )
        return HostCommandResult(
            command_id=f"AUTOCAD-COMMIT-{self.execute_count}",
            status="OK",
            payload={
                "updated": 1,
                "beforeWidths": {config["autocad_native_id"]: before},
                "widths": {config["autocad_native_id"]: self.width_mm},
                "unit": "mm",
            },
            revision_after=self.revision,
        )


class _RevitTransport:
    def __init__(self):
        self.revision = config["revit_revision"]
        self.width_mm = 200.0
        self.execute_count = 0

    def request(self, command):
        assert command.document_id == config["revit_document"]
        target = (
            command.target_native_refs[0].native_id
            if command.target_native_refs
            else config["revit_native_id"]
        )
        assert target == config["revit_native_id"]
        if command.operation == "context.current_selection":
            _record(
                "revit.context",
                host="REVIT",
                revision=self.revision,
                thickness=self.width_mm,
                execute_count=self.execute_count,
            )
            return {
                "status": "OK",
                "revision_after": self.revision,
                "payload": {
                    "document_id": config["revit_document"],
                    "document_title": "CrossHostTask155.rvt",
                    "host_instance_id": config["revit_host_instance_id"],
                    "selected_elements": [
                        {
                            "unique_id": config["revit_native_id"],
                            "native_kind": "Wall",
                        }
                    ],
                },
            }
        if command.operation == "read_wall_thickness_snapshot":
            _record(
                "revit.read",
                host="REVIT",
                revision=self.revision,
                thickness=self.width_mm,
                execute_count=self.execute_count,
            )
            return {
                "status": "OK",
                "revision_after": self.revision,
                "payload": {
                    "document_id": config["revit_document"],
                    "host_instance_id": config["revit_host_instance_id"],
                    "wall_unique_id": config["revit_native_id"],
                    "wall_type_unique_id": "REVIT-WALL-TYPE-TASK155",
                    "native_kind": "Wall",
                    "builtin_category": "OST_Walls",
                    "wall_thickness_mm": self.width_mm,
                    "location_signature": "TASK155-LOCATION",
                    "relationship_signature": "TASK155-RELATIONSHIP",
                    "revision_before": self.revision,
                    "revision_after": self.revision,
                },
            }
        if command.operation == "check_wall_thickness_readiness":
            _record(
                "revit.readiness",
                host="REVIT",
                revision=self.revision,
                thickness=self.width_mm,
                execute_count=self.execute_count,
            )
            return {
                "status": "OK",
                "revision_after": self.revision,
                "payload": {
                    "document_id": config["revit_document"],
                    "wall_unique_id": config["revit_native_id"],
                    "current_width": {"value": self.width_mm, "unit": "mm"},
                    "isolation_ready": True,
                    "plan_ready": True,
                },
            }
        if command.operation == "set_wall_thickness":
            expected = command.preconditions[0]["revision"]
            assert expected == self.revision
            before_revision = self.revision
            self.execute_count += 1
            self.width_mm = float(command.arguments["thickness"]["value"])
            self.revision += 1
            _record(
                "revit.execute",
                host="REVIT",
                revision=self.revision,
                thickness=self.width_mm,
                execute_count=self.execute_count,
            )
            return {
                "command_id": command.command_id,
                "status": "OK",
                "revision_after": self.revision,
                "payload": {
                    "wall_unique_id": config["revit_native_id"],
                    "wall_type_unique_id": "REVIT-WALL-TYPE-TASK155",
                    "editable_layer_index": 1,
                    "width_before_internal": 200.0 / 304.8,
                    "width_after_internal": self.width_mm / 304.8,
                    "width_after_mm": self.width_mm,
                    "requested_width_mm": self.width_mm,
                    "transaction_attempt_count": 1,
                },
                "verification": {
                    "identity_invariant_proven": True,
                    "location_invariant_proven": True,
                    "relationship_invariant_proven": True,
                    "document_change_observed": True,
                    "revision_before": before_revision,
                    "revision_after": self.revision,
                    "location_signature_before": "TASK155-LOCATION",
                    "location_signature_after": "TASK155-LOCATION",
                    "relationship_signature_before": "TASK155-RELATIONSHIP",
                    "relationship_signature_after": "TASK155-RELATIONSHIP",
                    "normalized_wider_effects": [],
                },
                "replayed": False,
            }
        raise AssertionError(f"unexpected Revit operation: {command.operation}")


class _PolicySource:
    def __init__(self, policy):
        self._policy = policy

    def load(self):
        return self._policy


class _PolicyClock:
    def now(self):
        return datetime.now(UTC)


class _AdmissionFactory:
    def __init__(self):
        self._stores = []
        self._sequence = 0

    def build(self, *, changeset_store, approval_scope_store, accepted_input_reader):
        store = PostgresConfiguredPolicyAdmissionStore(dsn)
        self._stores.append(store)
        policy = ConfiguredProductApprovalPolicyV2.from_mapping(
            {
                "version": "DSP_PRODUCT_APPROVAL_POLICY_V2",
                "policy_id": "task155-real-mcp",
                "principal": "local:task155-real-mcp",
                "project_ids": [config["project_id"]],
                "allowed_canonical_operations": ["set_wall_thickness.v1"],
                "reviewed_configuration_hash": config["reviewed_configuration_hash"],
                "semantic_target_ids": [config["semantic_target_id"]],
                "allowed_topology_snapshot_hashes": [config["topology_snapshot_hash"]],
                "required_host_roles": {
                    "AUTOCAD": "BOUND_REQUIRED",
                    "REVIT": "INITIATOR",
                },
                "admission_ttl_seconds": 3600,
            }
        )
        self._sequence += 1
        return ConfiguredPolicyApprovalAdmissionPortV2(
            changeset_store=changeset_store,
            approval_scope_store=approval_scope_store,
            admission_store=store,
            accepted_input_reader=accepted_input_reader,
            policy_source=_PolicySource(policy),
            clock=_PolicyClock(),
            id_factory=lambda: f"ADM-TASK155-{self._sequence}",
        )

    def close(self):
        for store in reversed(self._stores):
            store.close()


class _ReviewedValidator:
    def validate(self, binding):
        assert binding.project_id == config["project_id"]
        assert binding.semantic_target_id == config["semantic_target_id"]
        assert binding.semantic_environment_id == config["semantic_environment_id"]
        assert binding.semantic_environment_hash == config["semantic_environment_hash"]
        assert binding.topology_environment_id == config["topology_environment_id"]
        assert binding.topology_revision == config["topology_revision"]
        assert binding.topology_snapshot_hash == config["topology_snapshot_hash"]
        expected = {
            "AUTOCAD": (
                config["autocad_document"],
                config["autocad_native_id"],
                config["autocad_host_instance_id"],
            ),
            "REVIT": (
                config["revit_document"],
                config["revit_native_id"],
                config["revit_host_instance_id"],
            ),
        }
        for member in binding.members:
            assert (
                member.document_id,
                member.native_target_id,
                member.host_instance_id,
            ) == expected[member.host_kind]


class _Forbidden:
    def __getattr__(self, name):
        raise AssertionError(f"V2 path touched forbidden V1 seam: {name}")

    def __call__(self, *args, **kwargs):
        raise AssertionError(f"V2 path touched forbidden V1 callable: {args=} {kwargs=}")


class _RecordingService:
    def __init__(self, delegate):
        self._delegate = delegate

    def _record(self, callback, *args, **kwargs):
        try:
            return callback(*args, **kwargs)
        except Exception as exc:
            error_path.write_text(str(exc), encoding="utf-8")
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


draft_topology = MaterializationTopologySnapshot(
    topology_environment_id=config["topology_environment_id"],
    topology_revision=config["topology_revision"],
    slots=(
        MaterializationSlot(
            materialization_slot_id="SLOT-AUTOCAD-TASK155",
            semantic_target_ref=config["semantic_target_id"],
            required_host_type="autocad",
            document_ref=config["autocad_document"],
            requirement=MaterializationRequirement.REQUIRED,
        ),
        MaterializationSlot(
            materialization_slot_id="SLOT-REVIT-TASK155",
            semantic_target_ref=config["semantic_target_id"],
            required_host_type="revit",
            document_ref=config["revit_document"],
            requirement=MaterializationRequirement.REQUIRED,
        ),
    ),
    topology_snapshot_hash="0" * 64,
)
topology = MaterializationTopologySnapshot(
    topology_environment_id=draft_topology.topology_environment_id,
    topology_revision=draft_topology.topology_revision,
    slots=draft_topology.slots,
    topology_snapshot_hash=compute_topology_snapshot_hash(draft_topology),
)
assert topology.topology_snapshot_hash == config["topology_snapshot_hash"]

apply_connection = connect_postgres(dsn)
apply_execution_saga_migrations(apply_connection)
apply_connection.close()

autocad = _AutoCadDispatcher()
revit = _RevitTransport()


def autocad_factory(locator):
    assert locator == config["autocad_locator"]
    return autocad


def revit_factory(locator):
    assert locator == config["revit_locator"]
    return revit


admission_factory = _AdmissionFactory()
runtime = build_cross_host_product_reference_runtime(
    dsn=dsn,
    topology_snapshot=topology,
    autocad_dispatcher_factory=autocad_factory,
    revit_transport_factory=revit_factory,
    approval_admission_factory=admission_factory,
)
session_reader = SqliteSessionBindingReader(sqlite_path)
forbidden = _Forbidden()
service = ProductFrontDoorService(
    session_binding_reader=session_reader,
    candidate_source=forbidden,
    context_probe=forbidden,
    transport_factory=forbidden,
    query_service=runtime.query_service,
    composition_pool=forbidden,
    reviewed_configuration_validator=_ReviewedValidator(),
    accepted_input_store=runtime.request_store,
    proposal_decision_store=runtime.proposal_decision_store,
    decision_consume_gate=runtime.decision_consume_gate,
    interaction_subject_reader=runtime.artifact_store,
    cross_host_observation_reader=runtime.observation_reader,
    v2_flow_resolver=runtime.flow_resolver,
)
run_streamable_http(
    _RecordingService(service),
    host="127.0.0.1",
    port=port,
)
'''


def _cross_host_mcp_fixture(tmp_path):
    """用真实 client controller 冻结 V2 winner，并生成独立 server 的 reviewed config。"""

    import design_product_runtime as product_runtime
    from design_materialization_topology import (
        MaterializationRequirement,
        MaterializationSlot,
        MaterializationTopologySnapshot,
        compute_topology_snapshot_hash,
    )

    build_runtime = getattr(
        product_runtime,
        "build_cross_host_product_reference_runtime",
        None,
    )
    assert build_runtime is not None, (
        "build_cross_host_product_reference_runtime 尚未实现"
    )

    dsn = _postgres_dsn()
    with psycopg.connect(dsn, autocommit=True) as connection:
        for schema in (
            "product_task",
            "orchestrator_checkpoint",
            "orchestrator_artifact",
            "orchestrator_proposal",
            "execution_saga",
            "product_policy",
        ):
            connection.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")

    semantic_service, semantic_environment = (
        product_runtime.revit_reference_composition._semantic_environment()
    )
    del semantic_service
    project_id = "project-task155-real-mcp"
    semantic_target_id = "WALL-TASK155"
    topology_environment_id = "TOPOLOGY-TASK155"
    topology_revision = 1
    autocad_document = "/DSP/fixtures/CrossHostTask155.dwg"
    revit_document = "/DSP/fixtures/CrossHostTask155.rvt"
    draft = MaterializationTopologySnapshot(
        topology_environment_id=topology_environment_id,
        topology_revision=topology_revision,
        slots=(
            MaterializationSlot(
                materialization_slot_id="SLOT-AUTOCAD-TASK155",
                semantic_target_ref=semantic_target_id,
                required_host_type="autocad",
                document_ref=autocad_document,
                requirement=MaterializationRequirement.REQUIRED,
            ),
            MaterializationSlot(
                materialization_slot_id="SLOT-REVIT-TASK155",
                semantic_target_ref=semantic_target_id,
                required_host_type="revit",
                document_ref=revit_document,
                requirement=MaterializationRequirement.REQUIRED,
            ),
        ),
        topology_snapshot_hash="0" * 64,
    )
    topology = MaterializationTopologySnapshot(
        topology_environment_id=draft.topology_environment_id,
        topology_revision=draft.topology_revision,
        slots=draft.slots,
        topology_snapshot_hash=compute_topology_snapshot_hash(draft),
    )
    member_type = front_door.ConfiguredCrossHostMemberTarget
    target = front_door.ConfiguredCrossHostWallThicknessTarget.create(
        candidate_key="cross-host-task155",
        project_id=project_id,
        semantic_target_id=semantic_target_id,
        semantic_environment_id=semantic_environment.environment_id,
        semantic_environment_hash=semantic_environment.content_hash,
        topology_environment_id=topology_environment_id,
        topology_revision=topology_revision,
        topology_snapshot_hash=topology.topology_snapshot_hash,
        members=(
            member_type(
                host_kind="AUTOCAD",
                role="BOUND_REQUIRED",
                configured_reference_id="SLOT-AUTOCAD-TASK155",
                configured_reference_hash="a" * 64,
                transport_locator="autocad-task155",
                document_id=autocad_document,
                native_target_id="ACAD-WALL-TASK155",
            ),
            member_type(
                host_kind="REVIT",
                role="INITIATOR",
                configured_reference_id="SLOT-REVIT-TASK155",
                configured_reference_hash="b" * 64,
                transport_locator="revit-task155",
                document_id=revit_document,
                native_target_id="REVIT-WALL-TASK155",
            ),
        ),
    )

    class _Interpreter:
        def interpret(self, *, client_submission_ref, utterance):
            assert client_submission_ref
            assert utterance
            return front_door.AgentProposal(
                candidate_key=target.candidate_key,
                thickness_value=300.0,
                thickness_unit="mm",
            )

    class _TargetSource:
        def get(self, key):
            return target if key == target.candidate_key else None

    class _Probe:
        def __init__(self, host_kind):
            self.host_kind = host_kind

        def discover(self, *, command_id, document_id):
            assert command_id
            member = target.member(self.host_kind)
            assert document_id == member.document_id
            return type(
                "Observation",
                (),
                {
                    "document_id": member.document_id,
                    "host_instance_id": (
                        "AUTOCAD-TASK155"
                        if self.host_kind == "AUTOCAD"
                        else "REVIT-TASK155"
                    ),
                    "native_target_id": member.native_target_id,
                    "host_binding_fingerprint": (
                        "c" * 64 if self.host_kind == "AUTOCAD" else "d" * 64
                    ),
                },
            )()

    class _ProbeFactory:
        def __call__(self, host_kind, locator):
            assert locator == target.member(host_kind).transport_locator
            return _Probe(host_kind)

    class _Forbidden:
        def get(self, *args, **kwargs):
            """满足 V1 candidate-source 构造 shape；若 V2 真调用则立即失败。"""

            raise AssertionError(
                f"V2 client path touched V1 get seam: {args=} {kwargs=}"
            )

        def __getattr__(self, name):
            raise AssertionError(f"V2 client path touched V1 seam: {name}")

        def __call__(self, *args, **kwargs):
            raise AssertionError(f"V2 client path touched V1 callable: {args=} {kwargs=}")

    sqlite_path = tmp_path / "cross-host-front-door.sqlite3"
    state = front_door.SqliteFrontDoorStateStore(str(sqlite_path))
    try:
        controller = front_door.SubmissionController(
            state_store=state,
            agent_interpreter=_Interpreter(),
            candidate_source=_Forbidden(),
            context_probe_factory=_Forbidden(),
            session_ref_factory=lambda: "session-task155-real-mcp",
            task_id_factory=lambda: "task-task155-real-mcp",
            cross_host_target_source=_TargetSource(),
            cross_host_probe_factory=_ProbeFactory(),
        )
        frozen = controller.prepare_cross_host_submission(
            client_submission_ref="submission-task155-real-mcp",
            utterance="把两端墙厚同步改成 300mm",
        )
    finally:
        state.close()

    config = {
        "project_id": project_id,
        "semantic_target_id": semantic_target_id,
        "semantic_environment_id": semantic_environment.environment_id,
        "semantic_environment_hash": semantic_environment.content_hash,
        "topology_environment_id": topology_environment_id,
        "topology_revision": topology_revision,
        "topology_snapshot_hash": topology.topology_snapshot_hash,
        "reviewed_configuration_hash": target.reviewed_configuration_hash,
        "autocad_locator": target.member("AUTOCAD").transport_locator,
        "autocad_document": autocad_document,
        "autocad_native_id": target.member("AUTOCAD").native_target_id,
        "autocad_host_instance_id": "AUTOCAD-TASK155",
        "autocad_revision": 11,
        "revit_locator": target.member("REVIT").transport_locator,
        "revit_document": revit_document,
        "revit_native_id": target.member("REVIT").native_target_id,
        "revit_host_instance_id": "REVIT-TASK155",
        "revit_revision": 12,
    }
    config_path = tmp_path / "cross-host-config.json"
    config_path.write_text(json.dumps(config, sort_keys=True), encoding="utf-8")
    telemetry = tmp_path / "cross-host-telemetry.jsonl"
    error_path = tmp_path / "cross-host-server-error.txt"
    return (
        dsn,
        sqlite_path,
        config_path,
        telemetry,
        error_path,
        frozen,
    )


@pytest.mark.asyncio
async def test_real_mcp_v2_submit_reaches_durable_cross_host_proposal_pause(
    tmp_path,
) -> None:
    """真实 MCP submit 必须从 accepted input 启动 LangGraph，并停在双 Host proposal pause。"""

    dsn, sqlite_path, config_path, telemetry, error_path, frozen = (
        _cross_host_mcp_fixture(tmp_path)
    )
    with _real_mcp_server(
        _CROSS_HOST_PRODUCT_SERVER,
        dsn,
        str(sqlite_path),
        str(config_path),
        str(telemetry),
        str(error_path),
    ) as endpoint_url:
        client = front_door.ProductFrontDoorMcpClient(endpoint_url)
        view = await client.submit(frozen.request)

        assert view.version == "V2"
        assert view.task_id == frozen.request.task_id
        assert view.state is ProductTaskQueryState.WORKFLOW
        assert view.status.value == "WAITING"
        durable = await client.get(frozen.request.task_id)
        assert durable == view
        checkpoint_reader = create_postgres_checkpointer(dsn)
        try:
            checkpoint = LangGraphWorkflowCheckpointReader(
                checkpointer=checkpoint_reader
            ).get_checkpoint(frozen.request.task_id)
        finally:
            checkpoint_reader.close()
        assert checkpoint is not None
        assert checkpoint.phase is WorkflowPhase.AWAIT_OPERATION_PROPOSAL
        pending = checkpoint.pending_interaction
        assert pending is not None
        assert pending.kind is PendingInteractionKind.OPERATION_PROPOSAL
        assert pending.subject_ref != checkpoint.operation_ref

    operations = _telemetry_operations(telemetry)
    assert "autocad.execute" not in operations
    assert "revit.execute" not in operations
    assert not error_path.exists()


@pytest.mark.asyncio
async def test_real_mcp_v2_accept_consumes_same_pause_and_runs_existing_workflow(
    tmp_path,
) -> None:
    """ACCEPT 必须消费 submit 产生的 exact pause，并沿既有双 Slice workflow 收口成功。"""

    dsn, sqlite_path, config_path, telemetry, error_path, frozen = (
        _cross_host_mcp_fixture(tmp_path)
    )
    with _real_mcp_server(
        _CROSS_HOST_PRODUCT_SERVER,
        dsn,
        str(sqlite_path),
        str(config_path),
        str(telemetry),
        str(error_path),
    ) as endpoint_url:
        client = front_door.ProductFrontDoorMcpClient(endpoint_url)
        proposal = await client.submit(frozen.request)
        assert proposal.version == "V2"
        assert proposal.state is ProductTaskQueryState.WORKFLOW
        assert proposal.status.value == "WAITING"
        checkpointer = create_postgres_checkpointer(dsn)
        try:
            checkpoint = LangGraphWorkflowCheckpointReader(
                checkpointer=checkpointer
            ).get_checkpoint(frozen.request.task_id)
        finally:
            checkpointer.close()
        assert checkpoint is not None
        pending = checkpoint.pending_interaction
        assert pending is not None

        completed = await client.resume_operation_proposal(
            task_id=frozen.request.task_id,
            pause_id=pending.pause_id,
            resume_kind="OPERATION_PROPOSAL_ACCEPTED",
        )
        reread = await client.get(frozen.request.task_id)

        assert completed == reread
        assert completed.version == "V2"
        assert completed.status.value == "SUCCEEDED"
        assert completed.proposal_state.value == "ACCEPTED"
        assert completed.saga_id is not None
        assert len(completed.materializations) == 2
        assert {
            (item.host_kind, item.verified_thickness_mm)
            for item in completed.materializations
        } == {("AUTOCAD", 300.0), ("REVIT", 300.0)}

    operations = _telemetry_operations(telemetry)
    assert operations.count("autocad.execute") == 1
    assert operations.count("revit.execute") == 1
    assert not error_path.exists()
