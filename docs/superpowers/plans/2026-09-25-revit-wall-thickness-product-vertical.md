# Real Product Vertical — Revit Wall Thickness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every production-code task is TDD RED → GREEN → focused verification → exact-head verification → commit. Do not collapse gates.

**Status:** Written implementation plan — pending review  
**Date:** 2026-09-25  
**Plan base:** `design/revit-wall-thickness-product-vertical@b2b7e131415322e8704045f298952eb434356922`  
**Main baseline used for source census:** `main@1c753e949ada7a2c06ce856a57fa3ced407251e9`  
**Spec:** `docs/superpowers/specs/2026-09-25-revit-wall-thickness-product-vertical-design.md`  
**Workflow authority:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`  
**Persistence authority:** `docs/adr/ADR-008-durable-state-persistence-ownership.md`  
**Delivery/recovery authority:** `docs/adr/ADR-009-cross-owner-delivery-crash-recovery.md`

## Goal

交付第一个真实产品 vertical：把一份 durable、结构化的“当前 Revit 选择墙厚改为 300 mm”产品请求，沿现有 authoritative workflow 完整推进到 semantic context、canonical `set_wall_thickness.v1`、Impact/Scope/ChangeSet、preview/approval、Execution Planning/Provider Binding/Gateway admission、真实 Revit mutation、独立 post-commit READ、Step33 semantic verification、convergence 与 Saga terminal，并让产品层只投影 owner truth。

本计划不建立第二套 wall-thickness workflow，也不重新实现 Impact、Approval Scope、ChangeSet、Gateway、Saga 或 SemanticVerifier。新增内容只用于关闭产品 ingress、Revit I/O composition、request lineage 和 mandatory independent evidence 的缺口。

## Architecture

冻结后的生产调用链：

```text
WallThicknessProductFlow                         [new thin application facade]
  -> ProductTaskRequestStore                     [new durable request owner]
  -> LangGraphWorkflowRuntime                    [existing]
      -> DefaultWorkflowServices                 [existing; narrow task_id seam amendment]
          -> CanonicalWorkflowOwnerPorts         [existing; generic owner composition]
              -> RevitWallThicknessSemanticBoundary      [new application composition]
              -> existing Impact / Scope / ChangeSet owners
              -> existing Planning / Binding / Gateway owners
              -> MaterializedExecutionSagaCoordinator    [existing]
                  -> Revit readiness READ                [existing + revision-lineage tighten]
                  -> Revit EXECUTE set_wall_thickness    [new real execution port composition]
                  -> ActualDelta                         [existing Revit result adapter]
                  -> ScopeComparator                     [existing]
                  -> independent Revit READ
                     read_wall_thickness_snapshot        [new narrow Host read]
                     -> DesignFactAdapter                [existing]
                     -> SemanticService                  [existing]
                     -> VerificationEvidenceBundle
                  -> Step33 SemanticVerifier            [existing]
                  -> convergence / Saga terminal         [existing]
  -> ProductFlowView                            [projection only; no second success truth]
```

Product/Application composition 代码放在新的 source-only application package：

```text
platform/product_runtime/src/design_product_runtime/
```

它沿用 `platform/interaction` 的 source-only precedent；本 capability 不新增 installable domain distribution，也不借机重排 workspace package ownership。根 `pyproject.toml` 只把该 `src` 加入 test/runtime `pythonpath`。

Revit-native 读取与命令构造继续留在 `hosts/revit`；generic workflow/reconciliation 不 import Revit package。Product Runtime 是允许同时依赖平台 public contracts 与 Revit sidecar public adapters 的 application/composition 层。

## Tech Stack

Python 3.11 / 3.14、LangGraph 1.2.x、PostgreSQL 17、psycopg 3.x、pytest、Ruff、现有 Semantic Runtime/Semantic Service/Enterprise Mapping provider、Revit C# plugin + named pipe sidecar、现有 Step28–33 / Phase I V2 owners。版本以 exact-head lockfile/CI 为准，本计划不升级依赖。

---

## Source Census Decisions Frozen by This Plan

1. `PostgresWorkflowArtifactStore` **不**作为 ProductTask request store：它按 `(kind, content_hash)` 去重并拥有 workflow-local deterministic artifact；ProductTask request 必须按 `task_id` create-once。
2. `orchestrator_checkpoint` **不**存 request body；checkpoint 继续只保存 workflow navigation/ref state。
3. ProductTask request 使用独立 owner-local PostgreSQL schema `product_task`，table `request`；复用现有 psycopg/schema-isolation pattern，而不是复用错误 owner 的表。
4. `WorkflowServices.bind_parameters(...)` 与 `SemanticReconstructionPort.load_parameter_binding_inputs(...)` 需要窄 amendment：显式携带 `task_id`；不新增 checkpoint 字段。
5. `SET_WALL_THICKNESS_V1` 已存在且正确：`targets` 来自 CONTEXT，`thickness` 来自 INTENT，canonical effect 为 `PROPERTIES`。
6. 现有 `RevitWallSnapshotReader` 是新 independent READ 的唯一 native wall snapshot reader；不得复制 Wall/WallType read logic。
7. `RevitRequestExecutorRouter` 当前没有 `read_wall_thickness_snapshot`，因此该 READ 是真实新增能力。
8. `DesignFactAdapter` 已支持 `document_id / host_instance_id / source_revision / native_id / native_kind / builtin_category / wall_thickness_mm`，继续作为 Revit snapshot → NormalizedDesignFact 的唯一边界。
9. Semantic Runtime snapshot registry 当前只有 `InMemorySnapshotRegistry`；本计划不做 owner-wide PostgreSQL snapshot migration。
10. Revit EXECUTE 需要 `expected_revision`，而当前 coordinator 的 dispatch intent 不携带该值。计划不扩 `ExecutionSliceV2`、Saga 或 `HostDispatchContext`；exact planning `base_host_revision` 通过既有、会进入 binding hash 的 `ProviderBindingV2.native_binding_metadata` 冻结并传给 Revit execution port。
11. `WorkflowPhase.COMPLETED` 不是产品成功依据；只有 authoritative Saga `SUCCEEDED` 可投影为产品成功。
12. independent READ/evidence 失败发生在 known Host commit 之后时，不伪造 `VerificationEvidenceBundle`。durable truth 保持 `dispatch=HOST_COMMITTED`、slice=`RECONCILING`、verification hash absent，并由 coordinator 返回 `RECOVERY_REQUIRED`；不新增 Saga transition。

---

## Global Constraints

- Product request 是用户 INTENT authority，不是 model/Host fact authority。
- request 不得携带或覆盖 selected semantic/native identity、current thickness、classification、WallType、Host revision、join/insert/opening truth。
- 同一 `task_id` + 同 request body replay 必须幂等；同一 `task_id` + 不同 body 必须稳定 conflict。
- request 写入后、workflow start 前进程丢失必须可由 fresh store/runtime 继续；不得要求 process-local cache。
- ParameterBinder 前可通过 exact `task_id` 重载 request；ParameterBinder 成功后 downstream recovery 只使用已冻结 artifacts/refs，不重新解释 request。
- `WorkflowStartRequest.request_data` 最多保存 request locator/hash，不保存第二份 mutable request body。
- 不新增“current request”“latest request”“current selection cache”或 thread-local/singleton request state。
- `CanonicalWorkflowOwnerPorts` 保持 generic；Revit-specific product规则不进入该类。
- product runtime 不直接生成 Host mutation；必须经过 OperationResolver、ParameterBinder、ChangeSet、approval、planning、binding、grant。
- provider snapshot 中的 `expected_host_revision` 必须来自 exact ChangeSet → SnapshotSet → PlanningSnapshot lineage；不得由 execution port 临时采样。
- independent READ 必须验证 exact host instance、document、native Wall.UniqueId 和 `ActualDelta.revision_after == read.revision_before == read.revision_after`。
- newer revision 即使仍为 300 mm 也不是合法 verification evidence。
- mutation response `width_after_mm` 不得成为 product vertical Step33 evidence fallback。
- READ failure/revision mismatch 后禁止重新 dispatch mutation 获取“干净证据”。
- evidence acquisition failure 不允许构造 synthetic/fake `VerificationEvidenceBundle`；无证据就保持 recovery/nonterminal truth。
- 现有 `SemanticVerifier` 继续唯一决定 semantic assertion PASS/FAIL；product facade 不维护第二份 verification status。
- live wall width tolerance 沿用 Phase H：`pytest.approx(value, abs=1e-6)`；不得另造更宽容产品 tolerance。
- real-owner offline acceptance 只允许 fake external Host transport / human presentation boundary；Impact、Scope、ChangeSet、Planning、Binding、Gateway、Saga、Reconciliation、SemanticVerifier 必须是真实 production owners。
- 不扩 NLP/Agent/MCP、multi-entity、CREATE/DELETE/OFFSET、cross-host、multi-document、compensation、V1 retirement、support matrix 或 generic product framework。
- 新增 Python production 代码必须有完整中文注释/文档字符串，并满足当前 Ruff 规范。
- 每个 Task 完成后提交独立 commit；下一 Task 只基于上一 Task exact GREEN HEAD 开始。

---

## File Structure Freeze

| File | Responsibility |
| --- | --- |
| `platform/product_runtime/src/design_product_runtime/contracts.py` | ProductTask request/hash/error 与 product outcome projection contracts |
| `platform/product_runtime/src/design_product_runtime/postgres_request_store.py` | `product_task.request` create-once durable owner |
| `platform/product_runtime/src/design_product_runtime/revit_semantics.py` | real Revit context/semantic reconstruction + request-aware binding inputs |
| `platform/product_runtime/src/design_product_runtime/revit_execution.py` | routing/provider-snapshot/registry application composition；不实现 domain owners |
| `platform/product_runtime/src/design_product_runtime/revit_evidence.py` | independent READ → facts/claims → Step33 evidence bundle |
| `platform/product_runtime/src/design_product_runtime/wall_thickness_flow.py` | thin request/start/resume/outcome facade |
| `platform/orchestrator/src/design_orchestrator/workflow_services.py` | task-aware `bind_parameters` framework-neutral seam |
| `platform/orchestrator/src/design_orchestrator/default_workflow_services.py` | task_id delegation + existing operation-space validation |
| `platform/orchestrator/src/design_orchestrator/langgraph_graph.py` | parameter-binding node forwards existing `state.task_id` |
| `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py` | forwards task_id into semantic boundary；继续校验 exact context ref |
| `hosts/revit/plugin/Revit.AgentHost/Native/Context/RevitRuntimeIdentity.cs` | one process-lifetime Revit host instance identity shared by READ surfaces |
| `hosts/revit/plugin/Revit.AgentHost/Native/Walls/RevitWallThicknessSnapshotRead.cs` | dedicated read-only `read_wall_thickness_snapshot`, reusing `RevitWallSnapshotReader` |
| `hosts/revit/plugin/Revit.AgentHost/Native/ExternalEvents/RevitRequestExecutorRouter.cs` | route the new READ operation only |
| `hosts/revit/plugin/Revit.AgentHost/Native/PluginEntry.cs` | wire the new native reader |
| `hosts/revit/sidecar/src/revit_sidecar/context.py` | parse `context.current_selection`, expose current revision |
| `hosts/revit/sidecar/src/revit_sidecar/snapshot_read.py` | build/validate dedicated wall snapshot READ command/result |
| `hosts/revit/sidecar/src/revit_sidecar/execution.py` | admitted binding → EXECUTE command → existing result adapter |
| `hosts/revit/sidecar/src/revit_sidecar/readiness.py` | require readiness revision == binding-frozen expected revision |
| `platform/execution_coordination/src/design_execution_coordination/contracts.py` | generic `VerificationEvidenceUnavailable` fail-closed surface |
| `platform/execution_coordination/src/design_execution_coordination/ports.py` | ConvergenceEvidencePort receives exact authority/binding lineage |
| `platform/execution_coordination/src/design_execution_coordination/materialized_coordinator.py` | known-commit evidence failure → durable `RECOVERY_REQUIRED`, no fake verification |
| `platform/execution_coordination/src/design_execution_coordination/recovery.py` | same exact binding/authority arguments when rebuilding evidence after recovered commit |
| `tests/product_runtime/**` | request, semantic, composition, facade and PostgreSQL product E2E proofs |
| `tests/revit/**` | native source/architecture contract proofs for new READ |
| `hosts/revit/sidecar/tests/**` | context/snapshot/execution/readiness adapter tests |
| `tests/integration/test_revit_wall_thickness_product_live.py` | mandatory live happy-path product acceptance |
| `.github/workflows/revit-wall-thickness-product-vertical.yml` | product offline gate; live test remains externally enabled |
| `docs/runbooks/revit-wall-thickness-product-vertical.md` | live setup, evidence capture, happy/negative recording |

---

## Review Focus

1. **Request durability:** exact task create/replay/conflict semantics plus “request committed, no workflow checkpoint yet” recovery.
2. **300/350 cross-talk:** two tasks on same Host/context interleaved around ParameterBinder and resumed after rebuilding store/runtime/adapters.
3. **No model truth in request:** selection/identity/revision/current width all originate from Host + semantic owners.
4. **Revision authority:** execution uses binding-hashed planning revision, readiness proves that same revision, Host command receives it unchanged.
5. **Independent evidence:** Step33 evidence originates from a second READ command, never mutation response body.
6. **Known commit evidence failure:** owner remains `HOST_COMMITTED + RECONCILING`, product does not say success, second mutation count stays zero.
7. **Terminal truth:** workflow `COMPLETED` plus Saga `FAILED/PARTIALLY_COMMITTED/DIVERGED` must not become product success.
8. **Live acceptance split:** live happy path is mandatory closure evidence; live negative is recorded separately when the controlled Revit fixture supports the necessary selection/state setup.

---

# Implementation Tasks

## Task 1: Add immutable ProductTask request contract and PostgreSQL owner

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Create: `platform/product_runtime/src/design_product_runtime/contracts.py`
- Create: `platform/product_runtime/src/design_product_runtime/postgres_request_store.py`
- Modify: `pyproject.toml`
- Create: `tests/product_runtime/test_product_task_request.py`
- Create: `tests/product_runtime/test_product_task_request_postgres.py`

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class ProductTaskRequest:
    task_id: str
    project_id: str
    host_kind: str
    session_ref: str
    requested_action: str
    intent_arguments: Mapping[str, object]
    request_hash: str


class ProductTaskRequestError(ValueError):
    code: str


class PostgresProductTaskRequestStore:
    def create(self, request: ProductTaskRequest) -> ProductTaskRequest: ...
    def get(self, task_id: str) -> ProductTaskRequest | None: ...
    def close(self) -> None: ...
```

Frozen request values for this vertical:

```python
host_kind = "REVIT"
requested_action = "SET_SELECTED_WALL_THICKNESS"
intent_arguments = {"thickness": {"value": 300.0, "unit": "mm"}}
```

- [ ] **Step 1: Add deterministic request/hash RED tests**

Assert normalization rejects blank IDs, non-positive/non-finite thickness, non-`mm` units, model-truth fields outside the frozen schema, and hash mismatch. Assert 300 and 350 requests have different hashes.

- [ ] **Step 2: Run focused RED**

```bash
uv run pytest tests/product_runtime/test_product_task_request.py -q -vv
```

Expected: import/module failures for the new contract.

- [ ] **Step 3: Implement the immutable contract and canonical request hash**

Use canonical JSON hashing over exactly:

```text
task_id, project_id, host_kind, session_ref,
requested_action, intent_arguments
```

Do not include timestamps, selected entity, Host revision, WallType or native IDs.

- [ ] **Step 4: Add PostgreSQL create-once RED**

Use schema/table:

```sql
CREATE SCHEMA IF NOT EXISTS product_task;
CREATE TABLE IF NOT EXISTS product_task.request (
    task_id TEXT PRIMARY KEY,
    request_hash CHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Tests must prove:

```text
create(A@300) -> row
create(A@300) -> exact replay, same logical request
create(A@350) -> PRODUCT_TASK_REQUEST_CONFLICT
get(A) after store.close() + fresh store -> exact 300 request
```

- [ ] **Step 5: Implement owner-local PostgreSQL store**

Follow the explicit connection lifecycle/search-path discipline used by existing PostgreSQL owner adapters. Validate payload/hash again on read; corrupted row must fail closed with `PRODUCT_TASK_REQUEST_INTEGRITY_INVALID`.

- [ ] **Step 6: Prove the pre-workflow crash window**

Commit a request, close the request store before creating any LangGraph checkpoint, reopen a fresh store and prove exact request recovery. This test must not instantiate a workflow merely to pass.

- [ ] **Step 7: Run Task 1 GREEN**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_product_task_request.py \
  tests/product_runtime/test_product_task_request_postgres.py -q -vv
uv run ruff check platform/product_runtime tests/product_runtime
```

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml platform/product_runtime tests/product_runtime
git commit -m "feat: persist immutable product task requests"
```

---

## Task 2: Carry `task_id` explicitly to ParameterBinder input assembly

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/default_workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Modify: `tests/orchestrator/test_default_workflow_services.py`
- Modify: `tests/orchestrator/test_langgraph_graph.py`
- Modify: `tests/orchestrator/test_canonical_owner_ports.py`
- Modify: affected real-owner orchestration fixtures/tests

**Approved signatures:**

```python
class WorkflowServices(Protocol):
    def bind_parameters(
        self,
        task_id: str,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> StableRef | AsyncOperationRef: ...


class ExternalOwnerPorts(Protocol):
    def load_parameter_binding_inputs(
        self,
        task_id: str,
        operation_space_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> ParameterBindingInputs: ...
```

- [ ] **Step 1: Add delegation/graph RED tests**

Assert the graph forwards its existing `state["task_id"]`; assert `DefaultWorkflowServices` forwards all three values in order; assert no new state/checkpoint field is introduced.

- [ ] **Step 2: Add canonical adapter lineage RED**

`CanonicalWorkflowOwnerPorts` must forward exact `task_id`, then retain its current check that returned `ParameterBindingContext.context_snapshot_id/hash` equals authoritative `context_snapshot_ref`.

- [ ] **Step 3: Run RED**

```bash
uv run pytest \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_canonical_owner_ports.py -q -vv
```

- [ ] **Step 4: Implement the narrow seam amendment**

The `parameter_binding` graph node becomes structurally equivalent to:

```python
result = services.bind_parameters(
    cast(str, state["task_id"]),
    _require_stable_ref(state, "operation_ref"),
    _require_stable_ref(state, "context_snapshot_ref"),
)
```

Do not alter ParameterBinder itself and do not add a request field to LangGraph state.

- [ ] **Step 5: Migrate all test consumers without reintroducing a default task/global request**

Every fake must accept task_id explicitly even if it ignores it. No `*args`, optional task ID, singleton or “current task” compatibility shim is permitted.

- [ ] **Step 6: Run Task 2 GREEN and architecture regression**

```bash
uv run pytest tests/orchestrator -q
uv run ruff check platform/orchestrator tests/orchestrator
```

- [ ] **Step 7: Commit**

```bash
git add platform/orchestrator tests/orchestrator
git commit -m "feat: bind workflow parameters to explicit task lineage"
```

---

## Task 3: Add the dedicated Revit post-commit wall snapshot READ

**Files:**
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/Context/RevitRuntimeIdentity.cs`
- Modify: `hosts/revit/plugin/Revit.AgentHost/Native/Context/RevitContextIdentityReader.cs`
- Create: `hosts/revit/plugin/Revit.AgentHost/Native/Walls/RevitWallThicknessSnapshotRead.cs`
- Modify: `hosts/revit/plugin/Revit.AgentHost/Native/ExternalEvents/RevitRequestExecutorRouter.cs`
- Modify: `hosts/revit/plugin/Revit.AgentHost/Native/PluginEntry.cs`
- Create/Modify: `tests/revit/test_revit_wall_thickness_snapshot_read.py`
- Modify: `tests/revit/test_revit_architecture.py` if needed for source-boundary assertions

**Wire contract:**

```text
mode      = READ
operation = read_wall_thickness_snapshot
target_native_refs = exactly one Wall UniqueId
arguments = {}
preconditions = []
idempotency_key = null
```

Success payload must include:

```text
document_id
host_instance_id
wall_unique_id
wall_type_unique_id
native_kind = Wall
builtin_category = OST_Walls
wall_thickness_mm
location_signature
relationship_signature
revision_before
revision_after
```

- [ ] **Step 1: Add source/contract RED tests**

Freeze that the router does not route this READ today, then assert the new path is READ-only, rejects multiple/non-Wall targets, and calls existing `RevitWallSnapshotReader` rather than duplicating its WallType/CompoundStructure logic.

- [ ] **Step 2: Introduce one process-lifetime `RevitRuntimeIdentity`**

Move the current `revit-{Guid...}` process identity behind a shared static class and make `RevitContextIdentityReader` use it unchanged semantically.

- [ ] **Step 3: Implement `RevitWallThicknessSnapshotRead`**

Read revision before native snapshot, call `RevitWallSnapshotReader.Read(...)`, read revision after, and only return `OK` if both revisions are equal. A changed read window returns stable `REVIT_SNAPSHOT_REVISION_CHANGED`; it never opens a Transaction.

- [ ] **Step 4: Wire router and PluginEntry**

Do not modify mutation behavior or readiness operation names.

- [ ] **Step 5: Run Revit-free proof**

```bash
uv run pytest tests/revit/test_revit_wall_thickness_snapshot_read.py tests/revit/test_revit_architecture.py -q -vv
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

The native plugin itself remains covered by controlled live Revit acceptance because Autodesk assemblies are not part of generic Linux CI.

- [ ] **Step 6: Commit**

```bash
git add hosts/revit/plugin tests/revit
git commit -m "feat: add independent Revit wall snapshot read"
```

---

## Task 4: Add strict Python Revit context and snapshot read ports

**Files:**
- Create: `hosts/revit/sidecar/src/revit_sidecar/context.py`
- Create: `hosts/revit/sidecar/src/revit_sidecar/snapshot_read.py`
- Modify: `hosts/revit/sidecar/src/revit_sidecar/__init__.py`
- Create: `hosts/revit/sidecar/tests/test_context.py`
- Create: `hosts/revit/sidecar/tests/test_snapshot_read.py`

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class RevitContextEvidence:
    document_id: str
    host_instance_id: str
    selected_elements: tuple[RevitSelectedElement, ...]
    revision: int


@dataclass(frozen=True, slots=True)
class RevitWallSnapshotEvidence:
    document_id: str
    host_instance_id: str
    wall_unique_id: str
    native_kind: str
    builtin_category: str
    wall_thickness_mm: float
    location_signature: str
    relationship_signature: str
    revision_before: int
    revision_after: int
```

- [ ] **Step 1: Add context parser RED**

Assert exact document/host identity, selected `UniqueId`, native kind and top-level Host revision are required. Malformed, blank or wrong-document results fail closed.

- [ ] **Step 2: Add dedicated snapshot command/result RED**

The Python port must construct a `HostCommand` with `mode="READ"`, `operation="read_wall_thickness_snapshot"`, one Wall target, empty args/preconditions and `idempotency_key=None`.

- [ ] **Step 3: Freeze exact verification-window checks**

`read(..., expected_revision=N)` succeeds only when:

```python
result.revision_before == N
result.revision_after == N
result.document_id == expected_document
result.host_instance_id == expected_host_instance
result.wall_unique_id == expected_unique_id
```

Use the existing Phase H wall-width tolerance only when comparing measured millimetres to a target:

```python
assert result.wall_thickness_mm == pytest.approx(expected_mm, abs=1e-6)
```

- [ ] **Step 4: Implement ports with no semantic mapping logic**

These adapters validate transport evidence only. Canonical classification/property projection remains in Task 5/7 via existing semantic owners.

- [ ] **Step 5: Run Task 4 GREEN**

```bash
uv run pytest hosts/revit/sidecar/tests/test_context.py hosts/revit/sidecar/tests/test_snapshot_read.py -q -vv
uv run ruff check hosts/revit/sidecar/src/revit_sidecar hosts/revit/sidecar/tests
```

- [ ] **Step 6: Commit**

```bash
git add hosts/revit/sidecar
git commit -m "feat: validate Revit context and wall snapshot reads"
```

---

## Task 5: Replace the test semantic boundary with real request-aware Revit semantics

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/revit_semantics.py`
- Create: `tests/product_runtime/test_revit_semantics.py`
- Create: `tests/product_runtime/test_request_binding_interleaving.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`

**Consumes:**
- `ProductTaskRequestStore`
- `RevitContextPort`
- `RevitWallSnapshotPort`
- existing `IdentityRegistry`
- existing `DesignFactAdapter`
- existing `SemanticService`
- existing `SemanticSnapshot` / `FreshnessResolver` contracts
- existing `SET_WALL_THICKNESS_V1`

**Produces:** `RevitWallThicknessSemanticBoundary`, implementing the current `SemanticReconstructionPort` methods including task-aware binding input assembly.

- [ ] **Step 1: Add context acquisition RED**

`resolve_host_context(task_id)` must:

```text
load exact ProductTask request
READ current Revit context
require exactly one selected element
resolve selected Host identity through IdentityRegistry.by_host(...)
require native kind Wall
return a content-hashed StableRef for that exact task/context observation
```

The request itself must not contain the selected entity.

- [ ] **Step 2: Add no-private-cache RED**

`load_context_inputs(context_ref)` must be able to rebuild from a fresh boundary instance. It may re-read Host context and must require the new observation hash to match the supplied context ref; changed selection/document/revision fails closed instead of looking up “latest context”.

- [ ] **Step 3: Add real semantic reconstruction RED**

For each freshness contract root semantic id:

```text
IdentityRegistry semantic id -> exact Revit HostBinding
RevitWallSnapshotPort READ at expected_host_revision
DesignFactAdapter.normalize_snapshot(...)
SemanticService.project_facts(...)
-> canonical classification/property evidence
-> ReconstructionResult
```

Require enough guarantees for the requested freshness contract; do not invent classification if providers do not emit `ifc:IfcWall`.

- [ ] **Step 4: Add real operation-resolution input RED**

`load_operation_resolution_inputs(context_snapshot_ref)` must build `SemanticEligibilityContext` from the exact snapshot/evidence path and expose a production `RevitWallThicknessCapabilityProfile` for canonical `set_wall_thickness.v1`. The product layer does not directly select the canonical operation; `OperationResolver` still resolves the action space.

- [ ] **Step 5: Add request-aware ParameterBindingInputs RED**

Approved shape:

```python
def load_parameter_binding_inputs(
    self,
    task_id: str,
    operation_space_ref: StableRef,
    context_snapshot_ref: StableRef,
) -> ParameterBindingInputs:
    request = request_store.get(task_id)
    # exact request + exact context only
    proposal = OperationProposal(
        "set_wall_thickness.v1",
        {"thickness": request.intent_arguments["thickness"]},
    )
    ...
```

`targets` must still come from `ParameterBindingContext.selection`, never from the request.

- [ ] **Step 6: Implement with exact snapshot/request validation**

No process-local `task_id -> request`, `snapshot -> claims` or “current request” cache is allowed. Any repeated Host read must be exact-revision validated.

- [ ] **Step 7: Add the mandatory 300/350 interleaving recovery proof**

```text
A: 300 mm, same Host/context
B: 350 mm, same Host/context
start A -> pause before ParameterBinder
start B -> pause before ParameterBinder
close/rebuild request store + product semantic boundaries + runtimes/adapters
resume B
resume A
```

Assert B bound operation contains exactly 350 mm and A contains exactly 300 mm. Also assert both exact context refs remain matched and no request cross-talk occurs.

- [ ] **Step 8: Run Task 5 GREEN**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_revit_semantics.py \
  tests/product_runtime/test_request_binding_interleaving.py -q -vv
uv run ruff check platform/product_runtime tests/product_runtime
```

- [ ] **Step 9: Commit**

```bash
git add platform/product_runtime tests/product_runtime
git commit -m "feat: compose product requests with Revit semantic context"
```

---

## Task 6: Compose real routing, provider binding revision lineage, readiness and Revit mutation

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/revit_execution.py`
- Create: `hosts/revit/sidecar/src/revit_sidecar/execution.py`
- Modify: `hosts/revit/sidecar/src/revit_sidecar/readiness.py`
- Modify: `hosts/revit/sidecar/src/revit_sidecar/__init__.py`
- Create: `tests/product_runtime/test_revit_execution_composition.py`
- Create: `hosts/revit/sidecar/tests/test_execution.py`
- Modify: `hosts/revit/sidecar/tests/test_readiness.py`

**Revision carrier:** use existing `ProviderBindingV2.native_binding_metadata`, which already participates in provider binding hashing.

Expected metadata:

```python
{
    "identity_source": "semantic-runtime-host-binding",
    "expected_host_revision": 42,
}
```

- [ ] **Step 1: Add routing/provider snapshot RED**

Production application composition must resolve:

```text
ExecutionSliceV2.changeset_id
-> exact CanonicalChangeSet
-> exact snapshot_set_ref
-> exact SnapshotSet
-> member whose document_ref == execution_slice.host_runtime_ref.document_ref
-> base_host_revision
```

Require one exact member; convert its revision to a non-negative integer; freeze it into `native_binding_metadata` before `resolve_provider_bindings_v2` runs.

- [ ] **Step 2: Prove metadata is hash-bound**

A test must show changing only `expected_host_revision` changes provider snapshot/binding hashes. Do not add a duplicate revision field to ExecutionSlice, Grant or Saga.

- [ ] **Step 3: Tighten readiness RED**

`RevitWallThicknessReadinessPort` must require its observed Host revision to equal binding metadata `expected_host_revision`; mismatch returns NOT_READY/fail-closed before mutation.

- [ ] **Step 4: Add real execution-port RED**

`RevitWallThicknessExecutionPort.execute(...)` must:

```text
validate exact execution_slice / authority / binding_set joins
require exactly one admitted Wall native target
read canonical thickness in mm from binding/provider arguments
read expected revision from hash-bound native_binding_metadata
build RevitHostAdapter.build_set_wall_thickness_command(...)
use dispatch_context.idempotency_key unchanged
send via NamedPipeTransport
adapt via existing RevitExecutionResultAdapter
```

No random command id/idempotency identity is generated inside the port. Command id may be deterministic from `dispatch_intent_id`.

- [ ] **Step 5: Assert layer naming/unit contract**

Tests must freeze:

```text
canonical       set_wall_thickness.v1
provider_tool   revit.set_wall_thickness
Host operation  set_wall_thickness
transport unit  mm
```

- [ ] **Step 6: Implement registry/routing boundaries**

The product application layer may compose a one-Revit-host registry and materialization routing evidence from authoritative environment configuration/Host context. Controlled tests/live fixtures preseed `IdentityRegistry` and `MaterializationTopologyRegistry`; the ProductTask request never supplies semantic/native target identity.

- [ ] **Step 7: Run Task 6 GREEN**

```bash
uv run pytest \
  tests/product_runtime/test_revit_execution_composition.py \
  hosts/revit/sidecar/tests/test_execution.py \
  hosts/revit/sidecar/tests/test_readiness.py -q -vv
uv run ruff check platform/product_runtime hosts/revit/sidecar
```

- [ ] **Step 8: Commit**

```bash
git add platform/product_runtime hosts/revit/sidecar tests/product_runtime
git commit -m "feat: execute admitted wall thickness changes through Revit"
```

---

## Task 7: Put independent READ evidence inside Step33 and preserve known-commit recovery truth

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/revit_evidence.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/contracts.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/ports.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/materialized_coordinator.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/recovery.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Create: `tests/product_runtime/test_revit_verification_evidence.py`
- Modify/Create: focused execution-coordination tests for evidence-unavailable state

**Approved generic coordination error:**

```python
class VerificationEvidenceUnavailable(CoordinationError):
    """Host 已知提交后无法取得可归属本次 commit 的 mandatory verification evidence。"""
```

This exception is not a Saga state and must never be recorded as `BEFORE_COMMIT`.

**Approved `ConvergenceEvidencePort.build_bundle` lineage:**

```python
def build_bundle(
    self,
    *,
    execution_slice: ExecutionSliceV2,
    authority: AdmittedExecutionAuthorityV2,
    binding_set: ProviderBindingSetV2,
    actual_delta: ActualDelta,
    canonical_changeset: CanonicalChangeSet,
    approval_scope_boundary: ApprovalScopeBoundaryV2,
) -> VerificationEvidenceBundle: ...
```

- [ ] **Step 1: Add exact independent-READ RED**

`RevitWallThicknessEvidencePort` resolves the exact admitted native target from `binding_set`, then calls the dedicated snapshot READ with:

```text
host_instance_id = execution_slice.host_runtime_ref.host_instance_id
document         = ActualDelta.document_ref
Wall.UniqueId    = binding.native_targets[0].native_id
expected_revision = ActualDelta.revision_after
```

- [ ] **Step 2: Add correlation negative RED**

Reject and raise stable evidence-unavailable codes for:

```text
host instance mismatch
document mismatch
Wall.UniqueId mismatch
READ revision_before != ActualDelta.revision_after
READ revision_after  != ActualDelta.revision_after
READ revision_before != READ revision_after
```

Do not accept a newer revision even if measured thickness is still the requested value.

- [ ] **Step 3: Add semantic evidence RED**

Only after correlation passes:

```text
RevitWallSnapshotEvidence
-> DesignFactAdapter.normalize_snapshot
-> SemanticService.project_facts
-> exact canonical `ifc:IfcWall` + `dsp:WallThickness`
-> SemanticSnapshot / VerificationSubjectEvidence
-> VerificationEvidenceBundle
```

The bundle must reference the exact ChangeSet, execution slice and ActualDelta hashes. It must not read `width_after_mm` from mutation response.

- [ ] **Step 4: Add coordinator known-commit failure RED**

Inject `VerificationEvidenceUnavailable` after scope result. Assert durable truth is:

```text
dispatch intent status = HOST_COMMITTED
Saga slice status      = RECONCILING
scope comparison hash  = persisted
verification hash      = None
Saga terminal          = false
Host execute call count = 1
```

Coordinator must return `MaterializedCoordinationStatus.RECOVERY_REQUIRED` with the existing saga id rather than propagating a bare service exception or synthesizing a verification result.

- [ ] **Step 5: Implement the narrow coordinator handling**

Catch only the explicit evidence-unavailable type around `build_bundle`. Do not swallow integrity errors, programming errors, ScopeComparator failures or SemanticVerifier results.

- [ ] **Step 6: Amend recovery build_bundle call with exact binding lineage**

`UnknownOutcomeRecovery` already receives `binding_set`; thread it into its post-commit evidence call. No mutation method is added to the recovery probe.

- [ ] **Step 7: Prove semantic mismatch reaches the existing terminal path**

A valid independent snapshot at the exact committed revision but with wall thickness != requested value must produce a real `SemanticVerificationResult` FAILED and the existing Saga V2 partially-committed/verify-failed outcome. This is different from evidence-unavailable and must not remain RECONCILING.

- [ ] **Step 8: Run Task 7 GREEN**

```bash
uv run pytest \
  tests/product_runtime/test_revit_verification_evidence.py \
  tests/execution_coordination -q
uv run pytest tests/execution_reconciliation -q
uv run ruff check platform/product_runtime platform/execution_coordination tests
```

Use the repository’s actual execution-coordination test path if the focused directory is named differently; do not replace a missing path with a skipped command.

- [ ] **Step 9: Commit**

```bash
git add platform/product_runtime platform/execution_coordination tests
git commit -m "feat: verify Revit commits from independent read evidence"
```

---

## Task 8: Add the thin `WallThicknessProductFlow` facade and authoritative outcome projection

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/wall_thickness_flow.py`
- Modify: `platform/product_runtime/src/design_product_runtime/contracts.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Create: `tests/product_runtime/test_wall_thickness_flow.py`

**Product facade contract:**

```python
class ProductFlowStatus(str, Enum):
    WAITING = "WAITING"
    CANCELLED = "CANCELLED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    DIVERGED = "DIVERGED"


class WallThicknessProductFlow:
    def submit(self, request: ProductTaskRequest) -> ProductFlowView: ...
    def resume(
        self,
        task_id: str,
        command: WorkflowResumeCommand | None = None,
    ) -> ProductFlowView: ...
```

- [ ] **Step 1: Add write-before-start recovery RED**

`submit()` order is normative:

```text
request_store.create(request)
-> check runtime checkpoint for task_id
-> no checkpoint: runtime.start(WorkflowStartRequest(...))
-> existing checkpoint: resume/render existing workflow; never create a second task
```

Inject a crash after request create and before `runtime.start`; fresh facade must start the exact same persisted request later.

- [ ] **Step 2: Freeze `request_data` locator-only shape**

```python
request_data = {
    "product_request_task_id": request.task_id,
    "product_request_hash": request.request_hash,
}
```

No intent body is copied into checkpoint metadata.

- [ ] **Step 3: Add outcome projection RED**

Rules:

```text
pending interaction / async op -> WAITING
active execution recovery      -> RECOVERY_REQUIRED
Saga SUCCEEDED                 -> SUCCEEDED
Saga FAILED                    -> FAILED
Saga PARTIALLY_COMMITTED       -> PARTIALLY_COMMITTED
Saga DIVERGED                  -> DIVERGED
```

`WorkflowPhase.COMPLETED` by itself is never success. A COMPLETED workflow with missing/unresolved saga owner truth must fail closed.

- [ ] **Step 4: Add known-commit READ-failure presentation RED**

When Task 7 leaves the owner at `HOST_COMMITTED + RECONCILING` and the graph is waiting on the durable saga id, facade status is `RECOVERY_REQUIRED`; it must not display `SUCCEEDED` merely because Host mutation was known committed.

- [ ] **Step 5: Implement facade as pure composition/projection**

No Impact/Scope/approval/execution/verification rules belong here. The facade only persists the request, drives runtime start/resume, and reads public workflow/execution-owner projections.

- [ ] **Step 6: Run Task 8 GREEN**

```bash
uv run pytest tests/product_runtime/test_wall_thickness_flow.py -q -vv
uv run ruff check platform/product_runtime tests/product_runtime
```

- [ ] **Step 7: Commit**

```bash
git add platform/product_runtime tests/product_runtime
git commit -m "feat: add wall thickness product flow facade"
```

---

## Task 9: Prove the full offline product vertical with real owners and durable recovery

**Files:**
- Create: `tests/product_runtime/test_revit_wall_thickness_product_e2e.py`
- Modify: `tests/product_runtime/conftest.py` or root test fixtures as appropriate
- Modify: `tests/orchestrator/conftest.py` only if collection/PG fixture registration must include the new test module

**Required real components:**

```text
PostgresProductTaskRequestStore
LangGraph Postgres checkpointer
PostgresWorkflowArtifactStore
real OperationResolver + ParameterBinder
real FreshnessResolver / Semantic owners
real ImpactAnalyzer
real ApprovalScopePlanner
real ChangeSetBuilder
real MaterializationPlanner
real Execution Planner V2
real Provider Binding V2
real Gateway V2
PostgreSQL Saga V2 + HostDispatchIntent stores
real ScopeComparator + SemanticVerifier
real convergence verifier
real WallThicknessProductFlow
```

Allowed doubles:

```text
Host transport server behavior
human/presentation approval UI boundary
clock where deterministic owner contracts already permit an injected clock
```

- [ ] **Step 1: Build one stateful fake Revit transport, not fake owners**

It must implement the same wire operations:

```text
context.current_selection
check_wall_thickness_readiness
set_wall_thickness
read_wall_thickness_snapshot
```

Its document revision increments exactly once on successful mutation and independent READ observes the post-commit state separately.

- [ ] **Step 2: Prove happy path**

Submit 300 mm request, drive existing HITL/async boundaries, and assert:

```text
bound operation thickness = 300 mm
approved scope = selected wall + PROPERTIES only
EXECUTE call count = 1
independent READ call count >= 1 after commit
ActualDelta revision_after == independent READ revision
Step33 verification = PASSED
Saga = SUCCEEDED
ProductFlowStatus = SUCCEEDED
```

- [ ] **Step 3: Prove request conflict and pre-start crash recovery**

Same task/different thickness conflicts before workflow mutation. Request-only durable row survives fresh process and starts exactly one workflow later.

- [ ] **Step 4: Re-run mandatory 300/350 interleaving at full-flow level**

At minimum assert both final ChangeSets preserve their own thickness and request hashes; no artifact/request cross-talk is allowed.

- [ ] **Step 5: Prove independent READ value mismatch**

Mutation response says 300 mm, exact-revision independent READ says 299 mm. Expected:

```text
no second EXECUTE
real SemanticVerifier != PASSED
Saga != SUCCEEDED
ProductFlowStatus != SUCCEEDED
```

- [ ] **Step 6: Prove independent READ revision mismatch**

Inject one unrelated document revision between commit and READ. Expected durable truth:

```text
EXECUTE count = 1
dispatch = HOST_COMMITTED
slice = RECONCILING
verification hash = None
workflow/product = RECOVERY_REQUIRED
```

Resume/rebuild runtime and prove it still does not issue a second mutation.

- [ ] **Step 7: Prove identity/document mismatch fail closed**

Return wrong host instance, document or Wall.UniqueId from independent READ; all must refuse evidence and never reach product success.

- [ ] **Step 8: Run PostgreSQL 17 product gate**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_revit_wall_thickness_product_e2e.py -q -vv
```

- [ ] **Step 9: Run focused predecessors/regressions**

```bash
uv run pytest \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/orchestrator/test_task10_durable_recovery.py \
  tests/integration/test_phase_h_revit_wall_thickness_reconciliation.py -q
```

- [ ] **Step 10: Commit**

```bash
git add tests/product_runtime tests/orchestrator/conftest.py
git commit -m "test: prove Revit wall thickness product vertical offline"
```

---

## Task 10: Add mandatory live Revit product acceptance and separate conditional negatives

**Files:**
- Create: `tests/integration/test_revit_wall_thickness_product_live.py`
- Create: `docs/runbooks/revit-wall-thickness-product-vertical.md`
- Modify: controlled fixture manifest/runbook references only if the existing fixture format needs product-specific metadata

- [ ] **Step 1: Reuse the reviewed Phase H isolated-wall fixture**

Verify `.rvt` SHA-256 and `isolated_wall_unique_id` exactly as current Phase H live acceptance does. Seed environment-owned IdentityRegistry/TopologyRegistry for that fixture wall; do not put its identity into ProductTask request.

- [ ] **Step 2: Drive the actual product flow**

Use real named pipe transport and real product composition. Submit 300 mm and drive existing pauses to execution. The test must observe a dedicated `read_wall_thickness_snapshot` after the EXECUTE response; it may not construct Step33 evidence from mutation payload.

- [ ] **Step 3: Freeze mandatory happy-path assertions**

```text
request persisted with exact hash
selected identity resolves to exact isolated wall
EXECUTE uses expected revision from binding metadata
commit increments revision
independent READ host/document/Wall.UniqueId exact match
read revision_before == read revision_after == commit revision
read wall_thickness_mm == approx(300.0, abs=1e-6)
Step33 PASSED
Saga SUCCEEDED
ProductFlowStatus SUCCEEDED
```

- [ ] **Step 4: Record conditional live negatives separately**

If the controlled live environment can deterministically select/configure the Phase H shared-type/insert/join fixtures, run those product-level negatives and record them. If selection automation is not available, record `NOT_RUN_ENVIRONMENT_LIMITATION` in the live evidence report; this does not waive the mandatory offline negative proofs from Task 9 or the mandatory live happy path.

- [ ] **Step 5: Document reset/repeatability**

Runbook must state how the fixture is restored between runs, how Revit version/TFM/API path/pipe are recorded, and which output fields prove the independent READ rather than mutation response echo.

- [ ] **Step 6: Run live acceptance on the controlled Windows/Revit machine**

```powershell
$env:DSP_REVIT_LIVE = "1"
python -m pytest tests/integration/test_revit_wall_thickness_product_live.py -q -vv -s
```

Capture exact HEAD, fixture hash, Revit version, revision before/after, independent READ revision, measured width, Saga status and product status.

- [ ] **Step 7: Commit tests/runbook**

```bash
git add tests/integration/test_revit_wall_thickness_product_live.py docs/runbooks/revit-wall-thickness-product-vertical.md
git commit -m "test: add live Revit product vertical acceptance"
```

---

## Task 11: Add CI gate, full regression, scope audit and capability closeout

**Files:**
- Create: `.github/workflows/revit-wall-thickness-product-vertical.yml`
- Modify: `README.md`
- Modify: docs capability/status ledger used by the repository, if one exists at implementation HEAD

- [ ] **Step 1: Add dedicated offline CI workflow**

The workflow must install the real orchestrator/PostgreSQL/product test dependencies and run at least:

```text
ProductTask deterministic + PostgreSQL tests
Task-aware binder/orchestrator tests
Revit sidecar context/snapshot/execution/readiness tests
product semantic/evidence/facade tests
PostgreSQL full product E2E
Ruff on all changed Python paths
Revit Core .NET tests
```

The live Revit test remains opt-in/external and must be collected with `DSP_REVIT_LIVE=0` in generic CI to prove it does not accidentally require Revit.

- [ ] **Step 2: Run exact-head focused suites**

Run the precise Task 1–10 commands again on the same HEAD; do not rely on earlier commit logs.

- [ ] **Step 3: Run repository regressions required by current main policy**

At minimum execute the repository’s canonical Python 3.11 lane, Python 3.14 lane where configured, Revit Core, .NET and strict Ruff/architecture gates. Use the exact commands from current CI/workflow definitions rather than copying stale historical commands from this plan.

- [ ] **Step 4: Perform scope audit**

Confirm no implementation added:

```text
NLP/Agent/MCP front door
new canonical operation family
new Saga transition/state
checkpoint request body
latest/reverse-lookup request recovery
mutation-response verification fallback
WallType duplicate/reassign behavior
multi-host/multi-document scope
semantic snapshot PostgreSQL migration
```

- [ ] **Step 5: Update README only after evidence is GREEN**

README may state the product vertical is implemented only after exact-head offline product E2E and mandatory live happy path both have recorded evidence. Do not mark capability complete from unit tests alone.

- [ ] **Step 6: Fresh exact-head CI evidence**

Record branch HEAD and required workflow run URLs/statuses. Any new RED invalidates closeout until the same exact HEAD is green.

- [ ] **Step 7: Commit closeout docs/CI**

```bash
git add .github/workflows/revit-wall-thickness-product-vertical.yml README.md docs
git commit -m "ci: gate Revit wall thickness product vertical"
```

- [ ] **Step 8: PR/merged-main lifecycle**

After review, merge through normal repository policy. Re-run/observe the required merged-main workflows on the merge commit before marking the capability `CLOSED`. Branch GREEN is not merged-main closure.

---

## Acceptance Matrix

| Proof | Required evidence |
| --- | --- |
| Request create-once | same body replay; different body conflict |
| Pre-start crash | request survives with no workflow checkpoint and starts later |
| Binder lineage | explicit `task_id + operation_ref + context_snapshot_ref` |
| Cross-talk | 300/350 interleave after fresh stores/runtime/adapters |
| Semantic selection | exactly one selected Host element -> existing semantic identity -> `ifc:IfcWall` |
| Planning | real Impact/Scope/ChangeSet/Planning/Binding/Gateway owners |
| Revision | planning snapshot revision frozen in binding hash; readiness and EXECUTE use exact value |
| Mutation | real `set_wall_thickness`, mm transport, one logical dispatch identity |
| Independent read | dedicated READ after commit; exact host/doc/entity/revision |
| Semantic result | real Step33 verifies `dsp:WallThickness == requested thickness` |
| Evidence unavailable | `HOST_COMMITTED + RECONCILING`, no fake bundle, no second mutation, product recovery state |
| Value mismatch | valid exact-revision evidence reaches real SemanticVerifier and does not succeed |
| Product outcome | only Saga `SUCCEEDED` maps to product `SUCCEEDED` |
| Offline E2E | PostgreSQL request/checkpoint/artifact/Saga/dispatch + real owners |
| Live E2E | controlled real Revit happy path with separate independent READ |
| Live negative | separate evidence when environment supports deterministic setup; otherwise explicitly recorded not-run |
| Closeout | exact-head CI + mandatory live happy path + merged-main observation |

---

## Stop-and-Amend Triggers

Implementation must stop and return to Design/Written-Spec review rather than improvising if any of the following proves necessary:

1. independent READ failure cannot be represented truthfully as existing known-commit nonterminal recovery without adding a new Saga transition/state;
2. correct execution requires adding Host/native identity or revision authority to ProductTask request;
3. exact post-commit evidence requires accepting a newer Host revision or mutation response fallback;
4. product recovery requires rereading/reinterpreting the original request after bound operation/ChangeSet authority has been frozen;
5. real routing requires changing the materialization topology ownership model rather than consuming existing environment-owned topology;
6. implementation requires a generic NLP/Agent/MCP ingress or support-matrix expansion to make this single vertical work.

None of these conditions is currently supported by the source census at `b2b7e131...`; if one appears during TDD, it is new architectural evidence, not license to widen this plan.
