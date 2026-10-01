# MCP / Agent Front Door controlled live acceptance

本 runbook 是 `2026-09-28-mcp-agent-front-door.md` Task 10 的真实环境验收入口。

它明确区分两类证据：

1. `tests/integration/test_mcp_agent_front_door_live_support.py` 只做非交互 readiness/support；它不创建 ProductTask、不调用模型、不调用 MCP 业务工具、不替用户接受 HITL，也不能替代 mandatory controlled live acceptance。
2. mandatory acceptance 必须在真实 Windows/Revit 环境中，由真实模型解释自然语言，经真实 loopback Streamable HTTP MCP、显式人类决定、configured policy、真实 Revit mutation 与独立 READ/reconciliation 完成一条 exact lineage。

在 positive 与 negative controlled live 都完成之前，Task 10 状态只能是 `LIVE-PENDING`，不能标记 `CLOSED`/`COMPLETED`。

## 1. 安全边界与前置条件

只在专用、可丢弃的 acceptance 环境执行。不要复用生产 PostgreSQL、生产 SQLite 或真实项目文件。

- 使用独立 PostgreSQL database/DSN；negative 与 positive case 最好各自使用 fresh database，避免历史 Admission replay 影响结论。
- 使用专门保存的 Revit fixture，并在运行前手工选中 candidate 配置声明的唯一 Wall。
- Product Front Door 只能监听 `127.0.0.1`、`localhost` 或 `::1`；本 runbook 使用 `127.0.0.1:8010`。
- 不把 API key、token、DSN、模型 credential、连接串或其他秘密写入 evidence 文件、截图、PR comment 或 commit。
- 允许记录用户可见的测试 utterance、model provider/model label、opaque id、hash、Revit document/Host identity 与非秘密验证结果。
- 模型只负责把自然语言解释成窄 `AgentProposal`；模型不得得到 MCP endpoint/catalog，也不得直接执行 human resume/approval。
- human decision 必须来自 owner-derived `OPERATION_PROPOSAL` pending interaction，并由 deterministic client 调用 `resume_operation_proposal`。

## 2. 必需环境变量

在 **Windows PowerShell** 中设置以下变量。`DSP_AGENT_INTERPRETER_COMMAND` 在本 runbook 中采用 JSON argv array，目的是与 `SubprocessAgentInterpreter(shell=False)` 保持一致，不引入 shell 字符串解释。

```powershell
$env:DSP_FRONT_DOOR_LIVE="1"
$env:DSP_AGENT_INTERPRETER_COMMAND='["python","C:\\dsp-live\\real_model_interpreter.py"]'
$env:DSP_AGENT_MODEL_NAME="provider/model-version"
$env:DSP_FRONT_DOOR_CANDIDATES_FILE="C:\dsp-live\revit-candidates.json"
$env:DSP_FRONT_DOOR_POLICY_FILE="C:\dsp-live\approval-policy.json"
$env:DSP_FRONT_DOOR_STATE_DB="C:\dsp-live\front-door-state.sqlite3"
$env:DSP_FRONT_DOOR_HOST="127.0.0.1"
$env:DSP_FRONT_DOOR_PORT="8010"
$env:DSP_REVIT_VERSION="2026"
$env:DSP_REVIT_TFM="net8.0-windows"
$env:DSP_REVIT_API_DIR="C:\Program Files\Autodesk\Revit 2026"
$env:DSP_REVIT_PIPE="<running Revit AgentHost pipe name>"
$env:DSP_REVIT_FIXTURE="C:\dsp-live\fixtures\FrontDoorAcceptance.rvt"
$env:DSP_TEST_POSTGRES_DSN="postgresql://<acceptance-user>:<secret>@localhost:5432/<acceptance-db>"
```

`DSP_AGENT_MODEL_NAME` 是证据标签，不是 credential。真实 model command 自己从本机安全 credential source 取凭据；不要把凭据放进 argv 或 stdout。

### 2.1 Candidate 配置

候选文件必须满足现有 `DSP_REVIT_CANDIDATES_V1` exact schema，例如：

```json
{
  "version": "DSP_REVIT_CANDIDATES_V1",
  "candidates": [
    {
      "candidate_key": "revit-live-wall-001",
      "project_id": "project-live-front-door",
      "transport_locator": "<same value as DSP_REVIT_PIPE>",
      "document_id": "C:\\dsp-live\\fixtures\\FrontDoorAcceptance.rvt",
      "semantic_target_id": "WALL-LIVE-001",
      "native_target_unique_id": "<selected Revit Wall.UniqueId>"
    }
  ]
}
```

不要在 JSON 中自带 `candidate_hash`；`ConfiguredRevitCandidateCatalog` 会从规范 authority body 计算 canonical hash。

### 2.2 Positive policy

positive case 的配置必须授权 exact project 与当前 vertical 的 canonical operation：

```json
{
  "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
  "policy_id": "policy-front-door-live-positive-v1",
  "principal": "local-live-acceptance",
  "project_ids": ["project-live-front-door"],
  "allowed_canonical_operations": ["set_wall_thickness.v1"],
  "admission_ttl_seconds": 900
}
```

### 2.3 Negative policy

negative case 必须使用**新 task/ChangeSet 且没有既有 durable admission**。推荐使用 fresh acceptance database，然后将 policy 改为一个仍然结构合法、但不授权该 operation 的配置，例如：

```json
{
  "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
  "policy_id": "policy-front-door-live-deny-v1",
  "principal": "local-live-acceptance",
  "project_ids": ["project-live-front-door"],
  "allowed_canonical_operations": ["some.other.operation.v1"],
  "admission_ttl_seconds": 900
}
```

negative case 不能通过篡改旧 Admission 或复用已授权 lineage 来制造“拒绝”。

## 3. 先启动 Revit fixture

1. 启动冻结版本的 Revit 与 AgentHost。
2. 打开 `DSP_REVIT_FIXTURE` 指向的已保存 fixture。
3. 手工选中且只选中 candidates 文件中 `native_target_unique_id` 对应的一个 `Wall`。
4. 确认 `DSP_REVIT_PIPE` 指向当前运行的真实 AgentHost named pipe。
5. 不要先手工修改目标墙厚；先保留 baseline，供 negative/positive 独立 READ 比较。

## 4. 启动 Product Front Door server

仓库当前没有单独的 server CLI；因此 controlled live 用下面的最小 bootstrap 组合现有 production/reference owners。将代码保存到 acceptance 工作目录（不要提交 credential）中的 `run_front_door_live_server.py`，从仓库根目录运行。

```python
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

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
    ConfiguredPolicyApprovalAdmissionPort,
    ConfiguredProductApprovalPolicy,
    ConfiguredRevitCandidateCatalog,
    PostgresConfiguredPolicyAdmissionStore,
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
from revit_sidecar import NamedPipeTransport, RevitCurrentContextProbe


class JsonPolicySource:
    """每次 issuance 都从 configured local policy 文件读取当前 authority。"""

    def __init__(self, path: str) -> None:
        self._path = Path(path)

    def load(self):
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        return ConfiguredProductApprovalPolicy.from_mapping(payload)


class UtcClock:
    """为 Admission issuance 提供 timezone-aware UTC。"""

    def now(self):
        return datetime.now(UTC)


class EvidenceAdmissionFactory:
    """只从 reference composition 传入的同一 ChangeSet/Scope stores 读取并记录证据。"""

    def __init__(self, *, dsn: str, policy_path: str, evidence_path: str) -> None:
        self._store = PostgresConfiguredPolicyAdmissionStore(dsn)
        self._policy_source = JsonPolicySource(policy_path)
        self._clock = UtcClock()
        self._evidence_path = Path(evidence_path)

    def build(self, *, changeset_store, approval_scope_store):
        delegate = ConfiguredPolicyApprovalAdmissionPort(
            changeset_store=changeset_store,
            approval_scope_store=approval_scope_store,
            admission_store=self._store,
            policy_source=self._policy_source,
            clock=self._clock,
            id_factory=lambda: f"ADM-LIVE-{uuid4()}",
        )
        evidence_path = self._evidence_path
        policy_source = self._policy_source

        class RecordingAdmissionPort:
            """记录 same-owner lineage；不创建或替代任何业务 authority。"""

            def request_approval(self, changeset_ref):
                changeset = changeset_store.get(changeset_ref.ref_id)
                boundary = approval_scope_store.get_boundary(
                    f"SCOPE-{changeset.changeset_id}"
                )
                admission = delegate.request_approval(changeset_ref)
                policy = policy_source.load()
                record = {
                    "kind": "configured_policy_admission",
                    "changeset_id": changeset.changeset_id,
                    "changeset_hash": changeset.changeset_hash,
                    "approval_scope_id": boundary.scope_id,
                    "approval_scope_hash": boundary.scope_hash,
                    "policy_id": policy.policy_id,
                    "principal": policy.principal,
                    "policy_snapshot_hash": policy.policy_snapshot_hash,
                    "admission_id": admission.admission_id,
                    "admission_fingerprint": admission.admission_fingerprint,
                    "approved_at": admission.approved_at,
                    "expires_at": admission.expires_at,
                }
                with evidence_path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                return admission

        return RecordingAdmissionPort()

    def close(self) -> None:
        self._store.close()


def main() -> None:
    dsn = os.environ["DSP_TEST_POSTGRES_DSN"]
    state_db = os.environ["DSP_FRONT_DOOR_STATE_DB"]
    host = os.environ["DSP_FRONT_DOOR_HOST"]
    port = int(os.environ["DSP_FRONT_DOOR_PORT"])
    policy_path = os.environ["DSP_FRONT_DOOR_POLICY_FILE"]
    evidence_path = os.environ.get(
        "DSP_FRONT_DOOR_EVIDENCE_FILE",
        str(Path(state_db).with_suffix(".evidence.jsonl")),
    )

    candidates_payload = json.loads(
        Path(os.environ["DSP_FRONT_DOOR_CANDIDATES_FILE"]).read_text(encoding="utf-8")
    )
    candidate_source = ConfiguredRevitCandidateCatalog.from_mapping(candidates_payload)
    session_reader = SqliteSessionBindingReader(state_db)

    def transport_factory(locator: str):
        return NamedPipeTransport(pipe_name=locator)

    approval_factory = EvidenceAdmissionFactory(
        dsn=dsn,
        policy_path=policy_path,
        evidence_path=evidence_path,
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
            transport=transport_factory(binding.transport_locator),
            approval_admission_factory=approval_factory,
        )

    migration_connection = connect_postgres(dsn)
    apply_execution_saga_migrations(migration_connection)
    migration_connection.close()

    request_store = create_postgres_product_task_request_store(dsn)
    checkpointer = create_postgres_checkpointer(dsn)
    saga_store = PostgresExecutionSagaStoreV2(dsn)
    pool = ExactSessionCompositionPool(factory=composition_factory)
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
        composition_pool=pool,
    )

    try:
        run_streamable_http(service, host=host, port=port)
    finally:
        pool.close()
        saga_store.close()
        checkpointer.close()
        request_store.close()
        session_reader.close()
        approval_factory.close()


if __name__ == "__main__":
    main()
```

启动：

```powershell
$env:DSP_FRONT_DOOR_EVIDENCE_FILE="C:\dsp-live\front-door-evidence.jsonl"
uv run python C:\dsp-live\run_front_door_live_server.py
```

server 必须持续运行到当前 controlled case 完成；不要在 operation-proposal pause 与 human resume 之间重启 server，因为 v1 的 process-local SnapshotRegistry 不承诺该窗口的跨进程恢复。

## 5. 运行 support-only readiness

另开 PowerShell，确认上面的 server 已监听，然后执行：

```powershell
uv run python -m pytest tests/integration/test_mcp_agent_front_door_live_support.py -q -vv
```

期望：两个 support tests 都 `PASSED`。这只证明环境、真实 Revit current context、PostgreSQL 与 MCP tool catalog 已就绪；**不能据此宣布 Task 10 live acceptance GREEN**。

## 6. 启动 reference client

将下面代码保存为 acceptance 工作目录中的 `run_front_door_live_client.py`。它使用现有 `SubmissionController`、真实 `SubprocessAgentInterpreter`、真实 MCP client 与显式 console HumanDecisionPort。

```python
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from uuid import uuid4

from design_product_front_door import (
    ConfiguredRevitCandidateCatalog,
    ProductFrontDoorMcpClient,
    ReferenceClient,
    SqliteFrontDoorStateStore,
    SubmissionController,
    SubprocessAgentInterpreter,
    run_reference_cli,
)
from revit_sidecar import NamedPipeTransport, RevitCurrentContextProbe


class ConsoleHumanDecision:
    """只把 owner-derived pending 呈现给人，并要求显式选择允许的 resume kind。"""

    def decide(self, pending):
        print(f"pause_id={pending.pause_id}")
        print(f"subject_ref={pending.subject_ref.ref_id}")
        print(f"subject_hash={pending.subject_ref.content_hash}")
        print("allowed_resume_kinds=" + ",".join(pending.allowed_resume_kinds))
        while True:
            value = input("输入 ACCEPT 或 REJECT: ").strip().upper()
            mapping = {
                "ACCEPT": "OPERATION_PROPOSAL_ACCEPTED",
                "REJECT": "OPERATION_PROPOSAL_REJECTED",
            }
            decision = mapping.get(value)
            if decision in pending.allowed_resume_kinds:
                return decision
            print("输入无效；必须显式选择当前 owner pending 允许的决定。")


def main() -> None:
    state = SqliteFrontDoorStateStore(os.environ["DSP_FRONT_DOOR_STATE_DB"])
    candidates = ConfiguredRevitCandidateCatalog.from_mapping(
        json.loads(
            Path(os.environ["DSP_FRONT_DOOR_CANDIDATES_FILE"]).read_text(
                encoding="utf-8"
            )
        )
    )
    command = json.loads(os.environ["DSP_AGENT_INTERPRETER_COMMAND"])
    if not isinstance(command, list) or not command or not all(
        isinstance(item, str) and item.strip() for item in command
    ):
        raise ValueError("DSP_AGENT_INTERPRETER_COMMAND must be a JSON argv array")

    interpreter = SubprocessAgentInterpreter(command=command)

    def context_probe_factory(locator: str):
        return RevitCurrentContextProbe(NamedPipeTransport(pipe_name=locator))

    controller = SubmissionController(
        state_store=state,
        agent_interpreter=interpreter,
        candidate_source=candidates,
        context_probe_factory=context_probe_factory,
        session_ref_factory=lambda: f"session-live-{uuid4()}",
        task_id_factory=lambda: f"task-live-{uuid4()}",
    )
    endpoint = (
        f"http://{os.environ['DSP_FRONT_DOOR_HOST']}:"
        f"{os.environ['DSP_FRONT_DOOR_PORT']}/mcp"
    )
    client = ReferenceClient(
        state_store=state,
        submission_controller=controller,
        mcp_client=ProductFrontDoorMcpClient(endpoint),
        human_decision_port=ConsoleHumanDecision(),
    )
    try:
        print(f"model_label={os.environ['DSP_AGENT_MODEL_NAME']}")
        asyncio.run(run_reference_cli(reference_client=client, argv=sys.argv[1:]))
    finally:
        state.close()


if __name__ == "__main__":
    main()
```

### 模型 command 契约

真实 model wrapper 从 stdin 读取：

```json
{"client_submission_ref":"...","utterance":"..."}
```

stdout 必须只有一个符合现有窄 schema 的 JSON object。positive/negative acceptance 的正常 proposal 形状是：

```json
{
  "kind": "PROPOSAL",
  "candidate_key": "revit-live-wall-001",
  "thickness": {"value": 300.0, "unit": "mm"}
}
```

模型 wrapper 可以把非秘密 invocation evidence 追加写入独立 JSONL，例如 `client_submission_ref`、`DSP_AGENT_MODEL_NAME`、时间戳与 provider request id；stdout 不能夹带日志，也不能记录 credential。

## 7. Baseline independent READ

在每个 controlled case 开始前，先取得 current Revit context/revision，再通过仓库现有 `RevitWallThicknessSnapshotReadPort` 做独立 READ。下面是最小模板：

```python
import os
from uuid import uuid4

from revit_sidecar import (
    NamedPipeTransport,
    RevitCurrentContextProbe,
    RevitWallThicknessSnapshotReadPort,
)

transport = NamedPipeTransport(pipe_name=os.environ["DSP_REVIT_PIPE"])
probe = RevitCurrentContextProbe(transport)
context = probe.discover(
    command_id=f"CMD-T10-BASELINE-{uuid4().hex}",
    document_id=os.environ["DSP_REVIT_FIXTURE"],
)
assert len(context.selected_elements) == 1
wall = context.selected_elements[0]
evidence = RevitWallThicknessSnapshotReadPort(transport).read(
    command_id=f"CMD-T10-BASELINE-READ-{uuid4().hex}",
    document_id=context.document_id,
    host_instance_id=context.host_instance_id,
    wall_unique_id=wall.unique_id,
    expected_revision=context.revision,
)
print(evidence)
```

记录 baseline revision 与 `wall_thickness_mm`。这次 READ 本身不构成 positive acceptance，只是给 negative no-mutation 与 positive effect verification 提供独立基线。

## 8. Negative controlled live case

目标：显式证明 **human 可以接受 operation proposal，但 configured policy 拒绝时没有 Host mutation**。

1. 使用 fresh acceptance PostgreSQL database/DSN，或确认该 exact ChangeSet/scope 从未有 durable Admission。
2. 把 `DSP_FRONT_DOOR_POLICY_FILE` 指向第 2.3 节的合法 deny policy。
3. 清空/换用新的 `DSP_FRONT_DOOR_STATE_DB`，保证产生新的 `client_submission_ref`、session 与 ProductTask。
4. 重启 Product Front Door server，使新的 policy/state/DSN 成为本 case 的唯一 configured environment。
5. 重做第 5 节 support readiness。
6. 记录 baseline independent READ。
7. 运行真实模型：

```powershell
uv run python C:\dsp-live\run_front_door_live_client.py "把当前选中墙体厚度改成 300mm"
```

8. 记录 CLI 在模型/网络工作前打印的 `client_submission_ref`。
9. 检查模型产出的 constrained proposal 与 candidate/thickness 是否符合预期。
10. 当 owner-derived `OPERATION_PROPOSAL` 出现时，人工输入 `ACCEPT`。
11. 期望 configured policy 在 Admission issuance 处 fail closed，任务不得产生真实 `set_wall_thickness` EXECUTE。
12. 再执行一次 independent READ：revision 与墙厚必须证明没有该 ProductTask 导致的 mutation。
13. 确认没有新的 `configured_policy_admission` evidence row；如果已有同 lineage Admission，则本次 negative case 无效，必须换 fresh DB/new lineage 重做。

**Negative GREEN 条件：**真实模型 + 真实 MCP + 显式 human accept 已发生；policy 明确拒绝；Host mutation count = 0；独立 READ 证明墙厚没有因该任务改变。

## 9. Positive controlled live case

目标：一条 exact lineage 完成真实 mutation 与独立验证。

1. 使用 fresh acceptance database/DSN；将 policy 切换为第 2.2 节 positive policy。
2. 使用新的 SQLite state DB 或明确新的 `client_submission_ref`。
3. 在 Revit 中确认仍只选中 configured candidate 的目标 Wall。
4. 重启 server，并再次运行 support readiness。
5. 记录 baseline independent READ。
6. 执行：

```powershell
uv run python C:\dsp-live\run_front_door_live_client.py "把当前选中墙体厚度改成 300mm"
```

7. 记录 `client_submission_ref` 与 `DSP_AGENT_MODEL_NAME`。
8. 检查 constrained model proposal：candidate key 必须是配置中的 exact key，厚度必须是 `300.0 mm`。
9. owner-derived `OPERATION_PROPOSAL` 出现后，人工输入 `ACCEPT`；记录 pause id、subject ref/hash 与决定。
10. 等 reference client 完成 same-task final `get()`；期望最终用户呈现为 `SUCCEEDED task_id=...`。
11. 立即用第 7 节的独立 READ 再读目标 Wall；使用 fresh context revision 作为 `expected_revision`，记录 `wall_thickness_mm == 300.0`。
12. 保存 server evidence JSONL 中来自 same ChangeSet/Scope stores 的 configured-policy Admission 记录。

**Positive GREEN 条件：**真实 model、real Streamable HTTP MCP、explicit human accept、configured policy Admission、Gateway authorization、真实 Revit effect、independent read/reconciliation 与 final same-task GET 全部属于同一 lineage。

## 10. 记录 exact lineage evidence

不得只保存“测试通过”截图。至少记录下表中的非秘密字段：

| 阶段 | 必需 evidence |
| --- | --- |
| repository | exact `git rev-parse HEAD` |
| user/model | natural-language utterance、`client_submission_ref`、`DSP_AGENT_MODEL_NAME`、非秘密 model invocation id/时间 |
| proposal/freeze | `proposal_hash`、candidate key、candidate hash |
| session | `session_ref`、binding hash、real `host_instance_id`、document id |
| ProductTask | task id、request hash |
| MCP/HITL | real MCP submit 已发生、operation-proposal pause id、subject ref/hash、explicit human decision |
| policy owners | ChangeSet id/hash、ApprovalScope id/hash，必须来自 configured policy 实际读取的同一 stores |
| configured policy | policy id、principal、policy snapshot hash |
| Admission | admission id、fingerprint、approved_at、expires_at |
| Gateway | final checkpoint `approval_ref.ref_id` + `approval_ref.content_hash`，即 Gateway ApprovalRecord stable ref/hash |
| Revit effect | real Host runtime/document/target、执行前后 revision、mutation operation evidence |
| verification | independent snapshot READ、measured thickness、Saga/reconciliation verification hashes |
| final query | exact same task 的 MCP `get()` state/status |

### 10.1 从 SQLite 读取 freeze evidence

```python
import os
from design_product_front_door import SqliteFrontDoorStateStore

ref = "<client_submission_ref>"
store = SqliteFrontDoorStateStore(os.environ["DSP_FRONT_DOOR_STATE_DB"])
try:
    frozen = store.get_frozen_submission(ref)
    assert frozen is not None
    print("proposal_hash", frozen.proposal_hash)
    print("candidate_key", frozen.session_binding.candidate_key)
    print("candidate_hash", frozen.session_binding.candidate_hash)
    print("session_ref", frozen.session_binding.session_ref)
    print("binding_hash", frozen.session_binding.binding_hash)
    print("host_instance_id", frozen.session_binding.host_instance_id)
    print("document_id", frozen.session_binding.document_id)
    print("task_id", frozen.request.task_id)
    print("request_hash", frozen.request.request_hash)
finally:
    store.close()
```

### 10.2 final checkpoint/Gateway ref

通过 `ProductFrontDoorMcpClient.get(task_id)` 读取 final same-task view。记录 checkpoint 的 `changeset_ref`、`approval_ref`、`execution_plan_ref` 与 `saga_id`。不要从日志字符串猜测这些 id。

### 10.3 Admission/ChangeSet/Scope evidence

server bootstrap 的 `EvidenceAdmissionFactory` 只观察 `build_revit_wall_thickness_reference_composition()` 实际传入 configured policy 的**同一** `changeset_store` 和 `approval_scope_store`；它把 ChangeSet/Scope 与 durable Admission 的非秘密 identity/hash 追加到 `DSP_FRONT_DOOR_EVIDENCE_FILE`。不得用平行 test store 重建这些值。

### 10.4 Reconciliation evidence

final view 的 `saga_id` 是 execution owner locator。使用现有 `PostgresExecutionSagaStoreV2(DSP_TEST_POSTGRES_DSN).get_saga(saga_id)` 读取 same saga，记录 terminal status、slice `actual_delta_hash`、`scope_comparison_hash`、`verification_hash` 与 saga `convergence_result_hash`。只记录 hash/status，不打印 DSN。

## 11. Recovery / rerun 规则

- 若 client 在 freeze 后丢失 MCP response，使用原 `client_submission_ref` 恢复；不要创建新 utterance/task 来掩盖失败：

```powershell
uv run python C:\dsp-live\run_front_door_live_client.py --submission-ref <原 client_submission_ref>
```

- 若 client 在 freeze 前退出，同一 `client_submission_ref` 会从 durable `SubmissionRecord.utterance` 恢复；同 ref 提供不同 utterance 应冲突。
- 若 Product Front Door server 在 ContextSnapshot/operation-proposal pause 后重启，v1 不承诺 process-local SnapshotRegistry 可恢复该 live composition。此时必须记录现有 fail-closed 行为，不允许新增 `latest`/reverse lookup/process-local fallback 来伪造成功。
- negative case 若发现已有 Admission replay，判定本 case 环境无效，换 fresh database/new lineage 重跑。

## 12. Branch exact-head verification

controlled negative + positive live evidence 都 GREEN 后，先记录：

```powershell
git rev-parse HEAD
```

然后在**同一个 exact HEAD**上完成：

- canonical pytest mode
- alternate/compatibility pytest mode
- Product Front Door workflow
- Repository Regression
- Workflow Orchestrator PostgreSQL
- Durable Persistence
- Ruff：0 new diagnostics

live evidence capture 之后不得再偷偷修改 HEAD；如有任何 commit，必须重新执行与新 HEAD 对应的 live/CI gate，不能把旧 evidence 归到新 SHA。

## 13. Merge 与 lifecycle closeout

只有同时满足以下条件才允许进入 review/merge：

- Task 9 offline gates GREEN；
- Task 10 support/readiness GREEN；
- negative controlled live GREEN；
- positive controlled live GREEN；
- exact lineage evidence 完整且无秘密；
- exact-head branch verification 全 GREEN；
- branch HEAD 未漂移。

feature branch CI GREEN 本身不能把 capability 标记为 `COMPLETED`。

合并后必须观察 **merge SHA** 上的 required workflows。只有 merged-main observation 全 GREEN，才能做最小 lifecycle metadata closeout；如果 merged-main 任一 required workflow RED，lifecycle 保持 open。
