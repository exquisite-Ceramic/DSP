# Real Product Vertical — Revit Wall Thickness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Every production-code task is TDD RED → GREEN → focused verification → exact-head verification → commit. Do not collapse gates.

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

本计划不建立第二套 wall-thickness workflow，也不重新实现 Impact、Approval Scope、ChangeSet、Gateway、Saga 或 SemanticVerifier。新增内容只用于关闭产品 ingress、request lineage、Revit I/O composition 与 mandatory independent evidence 缺口。

## Architecture

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
                  -> Revit readiness READ                 [existing + revision-lineage tighten]
                  -> Revit EXECUTE set_wall_thickness     [new real execution port composition]
                  -> ActualDelta                          [existing result adapter]
                  -> ScopeComparator                      [existing]
                  -> independent Revit READ
                     read_wall_thickness_snapshot         [new narrow Host read]
                     -> DesignFactAdapter                 [existing]
                     -> SemanticService                   [existing]
                     -> VerificationEvidenceBundle
                  -> Step33 SemanticVerifier             [existing]
                  -> convergence / Saga terminal          [existing]
  -> ProductFlowView                              [projection only; no second success truth]
```

Product/application composition lives in the new source-only package:

```text
platform/product_runtime/src/design_product_runtime/
```

This follows the existing `platform/interaction` source-only precedent. The capability does not create a new domain owner distribution or reorder workspace ownership. Root `pyproject.toml` only adds the source path for repository tests/runtime composition.

Revit-native reading and command construction remain under `hosts/revit`. Generic orchestrator/reconciliation code must not import Revit modules. Product Runtime is the application/composition layer allowed to consume platform public contracts and Revit sidecar public adapters together.

## Tech Stack

Python 3.11 / 3.14、LangGraph 1.2.x、PostgreSQL 17、psycopg 3.x、pytest、Ruff、Semantic Runtime、Semantic Service、Enterprise Mapping provider、Revit C# plugin + named pipe sidecar、现有 Step28–33 / Phase I V2 owners。版本以 exact-head lockfile/CI 为准，本计划不升级依赖。

---

## Source Census Decisions Frozen by This Plan

1. `PostgresWorkflowArtifactStore` 不作为 ProductTask request store：它按 `(kind, content_hash)` 去重并拥有 workflow-local deterministic artifact；ProductTask request 必须按 `task_id` create-once。
2. `orchestrator_checkpoint` 不存 request body；checkpoint 继续只保存 workflow navigation/ref state。
3. ProductTask request 使用独立 owner-local PostgreSQL schema `product_task`、table `request`。
4. `WorkflowServices.bind_parameters(...)` 与 `SemanticReconstructionPort.load_parameter_binding_inputs(...)` 显式携带 `task_id`；不新增 checkpoint 字段。
5. 现有 `SET_WALL_THICKNESS_V1` 保持不变：`targets` 来自 CONTEXT，`thickness` 来自 INTENT，canonical effect 为 `PROPERTIES`。
6. 新 independent READ 复用现有 `RevitWallSnapshotReader`；禁止复制 Wall/WallType 读取逻辑。
7. `RevitRequestExecutorRouter` 当前没有 `read_wall_thickness_snapshot`，因此该 READ 是真实新增 Host 能力。
8. 现有 `DesignFactAdapter` 继续作为 Revit snapshot → NormalizedDesignFact 的唯一边界。
9. Semantic Runtime 当前只有 `InMemorySnapshotRegistry`；本 capability 不做 owner-wide PostgreSQL snapshot migration。
10. Revit EXECUTE 的 `expected_revision` 通过既有、参与 binding hash 的 `ProviderBindingV2.native_binding_metadata` 冻结；来源必须是 exact ChangeSet → SnapshotSet → PlanningSnapshot `base_host_revision`。不扩 `ExecutionSliceV2`、Saga 或 `HostDispatchContext`。
11. `WorkflowPhase.COMPLETED` 不是产品成功依据；只有 authoritative Saga `SUCCEEDED` 可映射产品 `SUCCEEDED`。
12. independent READ/evidence 失败发生在 known Host commit 之后时，不伪造 `VerificationEvidenceBundle`。durable truth 保持 `dispatch=HOST_COMMITTED`、slice=`RECONCILING`、verification hash absent，并返回 `RECOVERY_REQUIRED`；不新增 Saga transition/state。

---

## Global Constraints

- Product request 是用户 INTENT authority，不是 model/Host fact authority。
- request 不得携带 selected semantic/native identity、current thickness、classification、WallType、Host revision、join/insert/opening truth。
- 同一 `task_id` + 同 body replay 幂等；同一 `task_id` + 不同 body 稳定 conflict。
- request 写入后、workflow start 前中断必须可由 fresh store/runtime 继续。
- ParameterBinder 前可按 exact `task_id` 重载 request；ParameterBinder 成功后 downstream recovery 只使用已冻结 artifacts/refs，不重新解释 request。
- `WorkflowStartRequest.request_data` 只允许稳定 locator/hash，不复制 mutable request body。
- 禁止 `current request`、`latest request`、thread-local/singleton request state 与 request reverse lookup。
- `CanonicalWorkflowOwnerPorts` 保持 generic；Revit-specific product 规则不进入该类。
- product runtime 不直接绕过 resolver/binder/ChangeSet/approval/planning/binding/grant 生成 Host mutation。
- provider snapshot 的 `expected_host_revision` 必须来自 exact planning snapshot；execution port 不得临时采样 revision。
- independent READ 必须验证 exact host instance、document、native Wall.UniqueId 与 `ActualDelta.revision_after == read.revision_before == read.revision_after`。
- newer revision 即使仍为 300 mm，也不是本次 commit 的合法 verification evidence。
- mutation response `width_after_mm` 不得作为 product vertical Step33 evidence fallback。
- READ failure/revision mismatch 后禁止重新 dispatch mutation 获取“干净证据”。
- evidence acquisition failure 不允许 synthetic/fake `VerificationEvidenceBundle`。
- 现有 `SemanticVerifier` 继续唯一决定 semantic assertion PASS/FAIL；product facade 不维护第二份 verification status。
- live wall width tolerance 沿用 Phase H：`pytest.approx(value, abs=1e-6)`。
- offline product acceptance 只允许 fake external Host transport / human presentation boundary；Impact、Scope、ChangeSet、Planning、Binding、Gateway、Saga、Reconciliation、SemanticVerifier 必须使用 production owners。
- 不扩 NLP/Agent/MCP、multi-entity、CREATE/DELETE/OFFSET、cross-host、multi-document、compensation、V1 retirement、support matrix 或 generic product framework。
- 新增 Python production 代码必须有完整中文注释/文档字符串并满足当前 Ruff 规范。
- 每个 Task 独立提交；下一 Task 只基于上一 Task exact GREEN HEAD 开始。

---

## File Structure Freeze

| File | Responsibility |
| --- | --- |
| `platform/product_runtime/src/design_product_runtime/contracts.py` | ProductTask request/hash/error + product outcome contracts |
| `platform/product_runtime/src/design_product_runtime/postgres_request_store.py` | `product_task.request` create-once durable owner |
| `platform/product_runtime/src/design_product_runtime/revit_semantics.py` | real Revit context/semantic reconstruction + request-aware binding inputs |
| `platform/product_runtime/src/design_product_runtime/revit_execution.py` | routing/provider-snapshot/registry application composition |
| `platform/product_runtime/src/design_product_runtime/revit_evidence.py` | independent READ → facts/claims → Step33 evidence bundle |
| `platform/product_runtime/src/design_product_runtime/wall_thickness_flow.py` | thin request/start/resume/outcome facade |
| `platform/orchestrator/src/design_orchestrator/workflow_services.py` | task-aware binder seam |
| `platform/orchestrator/src/design_orchestrator/default_workflow_services.py` | task_id delegation + existing operation-space validation |
| `platform/orchestrator/src/design_orchestrator/langgraph_graph.py` | parameter-binding node forwards existing `state.task_id` |
| `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py` | forwards task_id into semantic boundary; retains exact context validation |
| `hosts/revit/plugin/Revit.AgentHost/Native/Context/RevitRuntimeIdentity.cs` | one process-lifetime Revit host instance identity shared by READ surfaces |
| `hosts/revit/plugin/Revit.AgentHost/Native/Walls/RevitWallThicknessSnapshotRead.cs` | dedicated read-only wall snapshot operation reusing `RevitWallSnapshotReader` |
| `hosts/revit/sidecar/src/revit_sidecar/context.py` | parse `context.current_selection`, expose current revision |
| `hosts/revit/sidecar/src/revit_sidecar/snapshot_read.py` | build/validate wall snapshot READ command/result |
| `hosts/revit/sidecar/src/revit_sidecar/execution.py` | admitted binding → EXECUTE command → existing result adapter |
| `hosts/revit/sidecar/src/revit_sidecar/readiness.py` | require readiness revision == binding-frozen expected revision |
| `platform/execution_coordination/src/design_execution_coordination/contracts.py` | generic evidence-unavailable error surface |
| `platform/execution_coordination/src/design_execution_coordination/ports.py` | evidence port receives exact authority/binding lineage |
| `platform/execution_coordination/src/design_execution_coordination/materialized_coordinator.py` | known-commit evidence failure → durable recovery-required result |
| `platform/execution_coordination/src/design_execution_coordination/recovery.py` | same exact lineage when rebuilding post-commit evidence |
| `tests/product_runtime/**` | request/semantic/composition/facade/PostgreSQL product proofs |
| `tests/integration/test_revit_wall_thickness_product_live.py` | mandatory live product acceptance |
| `.github/workflows/revit-wall-thickness-product-vertical.yml` | product offline CI gate |
| `docs/runbooks/revit-wall-thickness-product-vertical.md` | live setup/evidence recording |

---

## Review Focus

1. Request create/replay/conflict plus “request committed, no workflow checkpoint yet” recovery.
2. 300/350 two-task interleave after rebuilding stores/runtime/adapters; no request cross-talk.
3. Selected identity/revision/current width originate from Host + semantic owners, not ProductTask request.
4. Execution revision is binding-hashed planning revision and is proved again by readiness.
5. Step33 evidence originates from a second READ command, never mutation response body.
6. Known commit + unavailable evidence leaves `HOST_COMMITTED + RECONCILING`, no second mutation, product `RECOVERY_REQUIRED`.
7. Workflow `COMPLETED` plus Saga `FAILED/PARTIALLY_COMMITTED/DIVERGED` never becomes product success.
8. Live happy path is mandatory closure evidence; live negatives are recorded separately when the controlled fixture supports deterministic setup.

---

# Implementation Tasks

## Task 1: Add immutable ProductTask request contract and PostgreSQL owner

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Create: `platform/product_runtime/src/design_product_runtime/contracts.py`
- Create: `platform/product_runtime/src/design_product_runtime/postgres_request_store.py`
- Modify: `pyproject.toml`
- Create: `tests/product_runtime/conftest.py`
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

Frozen vertical input:

```python
host_kind = "REVIT"
requested_action = "SET_SELECTED_WALL_THICKNESS"
intent_arguments = {"thickness": {"value": 300.0, "unit": "mm"}}
```

- [ ] **Step 1: Add deterministic request/hash RED**

Reject blank identities, non-positive/non-finite thickness, non-`mm` unit, extra model-truth fields, and hash mismatch. Assert 300/350 bodies hash differently.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/product_runtime/test_product_task_request.py -q -vv
```

- [ ] **Step 3: Implement immutable contract + canonical hash**

Hash exactly `task_id, project_id, host_kind, session_ref, requested_action, intent_arguments`. Do not hash timestamps, selected entity, Host revision, WallType or native IDs.

- [ ] **Step 4: Add PostgreSQL create-once RED**

Schema/table:

```sql
CREATE SCHEMA IF NOT EXISTS product_task;
CREATE TABLE IF NOT EXISTS product_task.request (
    task_id TEXT PRIMARY KEY,
    request_hash CHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

Prove:

```text
create(A@300) -> row
create(A@300) -> exact idempotent replay
create(A@350) -> PRODUCT_TASK_REQUEST_CONFLICT
fresh store get(A) -> exact 300 request
```

- [ ] **Step 5: Implement store + dedicated product test fixture**

`tests/product_runtime/conftest.py` owns the ProductTask PostgreSQL fixture/cleanup and skips only PostgreSQL-dependent tests when `DSP_TEST_POSTGRES_DSN` is absent. Do not depend on `tests/orchestrator/conftest.py` for this new owner.

Validate payload/hash again on read; corrupted row raises `PRODUCT_TASK_REQUEST_INTEGRITY_INVALID`.

- [ ] **Step 6: Prove request-write / workflow-start crash window**

Commit request, close store before creating any LangGraph checkpoint, reopen fresh store, recover exact request. No workflow object is needed for this proof.

- [ ] **Step 7: Run GREEN**

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
- Modify: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Modify: `tests/orchestrator/test_task9_parameter_binding_lineage.py`
- Modify: `tests/orchestrator/test_task9_real_owner_acceptance.py`
- Modify: `tests/orchestrator/test_task10_durable_recovery.py`
- Modify: `tests/orchestrator/test_workflow_end_to_end.py`
- Modify: `tests/orchestrator/test_workflow_resume_authoritative_truth.py`

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

- [ ] **Step 1: Add delegation/graph RED**

Assert existing `state["task_id"]` reaches DefaultWorkflowServices and ExternalOwnerPorts. Assert no new graph/checkpoint field.

- [ ] **Step 2: Add canonical adapter RED**

`CanonicalWorkflowOwnerPorts` forwards exact task id and keeps current validation that returned `ParameterBindingContext.context_snapshot_id/hash` equals the authoritative context ref.

- [ ] **Step 3: Run RED**

```bash
uv run pytest \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_canonical_owner_ports.py -q -vv
```

- [ ] **Step 4: Implement narrow seam amendment**

```python
result = services.bind_parameters(
    cast(str, state["task_id"]),
    _require_stable_ref(state, "operation_ref"),
    _require_stable_ref(state, "context_snapshot_ref"),
)
```

Do not change ParameterBinder itself.

- [ ] **Step 5: Migrate all listed consumers**

Every fake/fixture accepts explicit task id. No optional task id, `*args`, singleton, default task, or current-request compatibility shim.

- [ ] **Step 6: Run GREEN**

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
- Create: `tests/revit/test_revit_wall_thickness_snapshot_read.py`
- Modify: `tests/revit/test_revit_architecture.py`

**Wire contract:**

```text
mode      = READ
operation = read_wall_thickness_snapshot
target_native_refs = exactly one Wall UniqueId
arguments = {}
preconditions = []
idempotency_key = null
```

Success payload contains exact `document_id`, shared process `host_instance_id`, Wall/WallType UniqueIds, `native_kind=Wall`, `builtin_category=OST_Walls`, `wall_thickness_mm`, location/relationship signatures, `revision_before`, `revision_after`.

- [ ] **Step 1: Add source/contract RED**

Assert new route is READ-only, one Wall target only, and delegates native reading to existing `RevitWallSnapshotReader` rather than duplicating CompoundStructure logic.

- [ ] **Step 2: Introduce shared `RevitRuntimeIdentity`**

Move current process-lifetime `revit-{Guid...}` identity behind one shared static source and update `RevitContextIdentityReader` to use it.

- [ ] **Step 3: Implement snapshot reader command**

`RevitRequestExecutorRouter.Execute(...)` already supplies `revisionBefore` and `readCurrentRevision`. Pass both into `RevitWallThicknessSnapshotRead`; use `RevitWallSnapshotReader.Read(...)`, then require final revision equals `revisionBefore`. Revision change returns stable `REVIT_SNAPSHOT_REVISION_CHANGED`. Never open a Revit Transaction.

- [ ] **Step 4: Wire router + PluginEntry**

Keep existing readiness/mutation operation names unchanged.

- [ ] **Step 5: Run Revit-free proof**

```bash
uv run pytest \
  tests/revit/test_revit_wall_thickness_snapshot_read.py \
  tests/revit/test_revit_architecture.py -q -vv
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj -f net8.0
```

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

**Produces:** `RevitContextEvidence`, `RevitSelectedElement`, `RevitWallSnapshotEvidence`, plus read-only transport adapters.

- [ ] **Step 1: Add context parser RED**

Require exact document/host identity, selected UniqueId/native kind, and top-level Host revision from `context.current_selection` response. Reject malformed/blank/wrong-document results.

- [ ] **Step 2: Add snapshot command/result RED**

Build `HostCommand(mode="READ", operation="read_wall_thickness_snapshot", one Wall target, empty arguments/preconditions, idempotency_key=None)`.

- [ ] **Step 3: Freeze verification-window checks**

`read(..., expected_revision=N)` succeeds only when document/host/native id match and `revision_before == revision_after == N`. Wall thickness target comparisons use `pytest.approx(expected_mm, abs=1e-6)`.

- [ ] **Step 4: Implement ports without semantic mapping logic**

These adapters validate transport evidence only.

- [ ] **Step 5: Run GREEN**

```bash
uv run pytest \
  hosts/revit/sidecar/tests/test_context.py \
  hosts/revit/sidecar/tests/test_snapshot_read.py -q -vv
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
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Create: `tests/product_runtime/test_revit_semantics.py`
- Create: `tests/product_runtime/test_request_binding_interleaving.py`

**Consumes:** ProductTask request store, Revit context/snapshot ports, `IdentityRegistry`, `DesignFactAdapter`, `SemanticService`, Semantic Runtime snapshot/freshness contracts, existing `SET_WALL_THICKNESS_V1`.

- [ ] **Step 1: Add context acquisition RED**

`resolve_host_context(task_id)` loads exact request, reads current Revit context, requires exactly one selected element, resolves existing semantic identity via `IdentityRegistry.by_host(...)`, requires Wall native kind, and returns a content-hashed ref for that exact task/context observation. Request body never supplies selected entity.

- [ ] **Step 2: Add no-private-cache RED**

A fresh boundary instance must resolve `load_context_inputs(context_ref)` by re-reading Host context and verifying the observation hash equals the supplied ref. Changed selection/document/revision fails closed; no latest lookup.

- [ ] **Step 3: Add semantic reconstruction RED**

For each freshness root semantic id:

```text
IdentityRegistry -> exact Revit HostBinding
snapshot READ at expected_host_revision
DesignFactAdapter.normalize_snapshot
SemanticService.project_facts
-> canonical classification/property evidence
-> ReconstructionResult
```

Do not invent `ifc:IfcWall` when provider projection does not prove it.

- [ ] **Step 4: Add operation-resolution input RED**

Build exact `SemanticEligibilityContext` and a production wall-thickness capability profile; `OperationResolver` still selects canonical action space.

- [ ] **Step 5: Add request-aware binding input RED**

```python
def load_parameter_binding_inputs(
    self,
    task_id: str,
    operation_space_ref: StableRef,
    context_snapshot_ref: StableRef,
) -> ParameterBindingInputs:
    request = request_store.get(task_id)
    proposal = OperationProposal(
        "set_wall_thickness.v1",
        {"thickness": request.intent_arguments["thickness"]},
    )
    ...
```

`targets` still come only from `ParameterBindingContext.selection`.

- [ ] **Step 6: Implement exact request/context validation**

No process-local task/request or snapshot/claim authority cache.

- [ ] **Step 7: Add mandatory 300/350 interleaving recovery proof**

```text
A=300, B=350, same Host/context
start A -> pause before binder
start B -> pause before binder
close/rebuild request stores + semantic boundaries + runtimes/adapters
resume B
resume A
```

Assert B binds 350 only, A binds 300 only, and both retain their own exact context/operation lineage.

- [ ] **Step 8: Run GREEN**

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

## Task 6: Compose real routing, hash-bound revision lineage, readiness and Revit mutation

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/revit_execution.py`
- Create: `hosts/revit/sidecar/src/revit_sidecar/execution.py`
- Modify: `hosts/revit/sidecar/src/revit_sidecar/readiness.py`
- Modify: `hosts/revit/sidecar/src/revit_sidecar/__init__.py`
- Create: `tests/product_runtime/test_revit_execution_composition.py`
- Create: `hosts/revit/sidecar/tests/test_execution.py`
- Modify: `hosts/revit/sidecar/tests/test_readiness.py`

**Frozen revision carrier:** existing `ProviderBindingV2.native_binding_metadata`, e.g.:

```python
{
    "identity_source": "semantic-runtime-host-binding",
    "expected_host_revision": 42,
}
```

- [ ] **Step 1: Add provider snapshot RED**

Resolve `ExecutionSliceV2.changeset_id -> CanonicalChangeSet -> exact snapshot_set_ref -> exact SnapshotSet -> member for execution document -> base_host_revision`. Require one member, non-negative integer revision, then freeze it into binding metadata before `resolve_provider_bindings_v2`.

- [ ] **Step 2: Prove revision is hash-bound**

Changing only `expected_host_revision` must change provider snapshot/binding hashes. Do not add a revision field to ExecutionSlice, Grant or Saga.

- [ ] **Step 3: Tighten readiness RED**

Observed readiness revision must equal binding metadata expected revision; mismatch is NOT_READY before mutation.

- [ ] **Step 4: Add real execution-port RED**

`RevitWallThicknessExecutionPort.execute(...)` validates slice/authority/binding joins, one admitted Wall target, canonical mm thickness, hash-bound expected revision, builds existing Revit set-wall-thickness command, reuses `dispatch_context.idempotency_key`, sends named-pipe request, then adapts via existing `RevitExecutionResultAdapter`. Command id is deterministic from durable dispatch identity; no random logical command identity.

- [ ] **Step 5: Freeze naming/unit layers**

```text
canonical       set_wall_thickness.v1
provider_tool   revit.set_wall_thickness
Host operation  set_wall_thickness
transport unit  mm
```

- [ ] **Step 6: Implement routing/registry composition**

Application composition uses environment-owned Host/runtime/identity/topology configuration. Tests/live fixtures preseed `IdentityRegistry` and `MaterializationTopologyRegistry`; ProductTask request never supplies native/semantic target identity.

- [ ] **Step 7: Run GREEN**

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
- Create: `tests/execution_coordination/test_verification_evidence_unavailable.py`

**Approved generic surface:**

```python
class VerificationEvidenceUnavailable(CoordinationError):
    """Host 已知提交后无法取得可归属本次 commit 的 mandatory verification evidence。"""
```

This is not a Saga state.

**Approved evidence port lineage:**

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

- [ ] **Step 1: Add independent READ RED**

Evidence port resolves exact admitted target from binding set and reads `host_instance_id=execution runtime`, `document=ActualDelta.document_ref`, `Wall.UniqueId=binding native target`, `expected_revision=ActualDelta.revision_after`.

- [ ] **Step 2: Add correlation negative RED**

Reject host/document/Wall.UniqueId mismatch, read-before/read-after mismatch, or any revision different from ActualDelta revision. Newer state is not accepted.

- [ ] **Step 3: Add semantic evidence RED**

Only correlated snapshot goes through `DesignFactAdapter -> SemanticService -> exact ifc:IfcWall + dsp:WallThickness -> SemanticSnapshot/VerificationSubjectEvidence -> VerificationEvidenceBundle`. Bundle binds exact ChangeSet/execution/ActualDelta hashes. Never use mutation response width.

- [ ] **Step 4: Add known-commit evidence-failure RED**

After scope result, inject `VerificationEvidenceUnavailable` and assert:

```text
dispatch = HOST_COMMITTED
slice = RECONCILING
scope comparison hash persisted
verification hash = None
Saga nonterminal
Host execute count = 1
```

Coordinator returns `MaterializedCoordinationStatus.RECOVERY_REQUIRED` with existing saga id.

- [ ] **Step 5: Implement narrow coordinator handling**

Catch only explicit evidence-unavailable around `build_bundle`. Integrity/programming/scope/SemanticVerifier failures remain unchanged.

- [ ] **Step 6: Thread exact binding lineage through recovery evidence call**

`UnknownOutcomeRecovery` already receives `binding_set`; pass it and authority to `build_bundle`. Recovery probe remains read-only.

- [ ] **Step 7: Prove value mismatch uses existing terminal path**

Exact committed revision but wrong thickness must produce real `SemanticVerificationResult` FAILED and existing verify-failed/partially-committed Saga outcome, not RECONCILING.

- [ ] **Step 8: Run GREEN**

```bash
uv run pytest \
  tests/product_runtime/test_revit_verification_evidence.py \
  tests/execution_coordination -q
uv run pytest tests/execution_reconciliation -q
uv run ruff check \
  platform/product_runtime \
  platform/execution_coordination \
  tests/product_runtime \
  tests/execution_coordination
```

- [ ] **Step 9: Commit**

```bash
git add platform/product_runtime platform/execution_coordination tests/product_runtime tests/execution_coordination
git commit -m "feat: verify Revit commits from independent read evidence"
```

---

## Task 8: Add thin `WallThicknessProductFlow` and authoritative outcome projection

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/wall_thickness_flow.py`
- Modify: `platform/product_runtime/src/design_product_runtime/contracts.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Create: `tests/product_runtime/test_wall_thickness_flow.py`

**Product statuses:** `WAITING`, `CANCELLED`, `RECOVERY_REQUIRED`, `SUCCEEDED`, `FAILED`, `PARTIALLY_COMMITTED`, `DIVERGED`.

- [ ] **Step 1: Add write-before-start recovery RED**

`submit()` order is normative: request_store.create → inspect runtime checkpoint → no checkpoint means start → existing checkpoint means render/resume existing workflow. Inject crash after request create/before runtime.start; fresh facade later starts exactly the persisted request.

- [ ] **Step 2: Freeze locator-only request_data**

```python
request_data = {
    "product_request_task_id": request.task_id,
    "product_request_hash": request.request_hash,
}
```

- [ ] **Step 3: Add outcome projection RED**

Pending interaction/async = WAITING; active execution recovery = RECOVERY_REQUIRED; Saga statuses map one-to-one to product terminal statuses. `WorkflowPhase.COMPLETED` alone is never success. COMPLETED with unresolved/missing Saga fails closed.

- [ ] **Step 4: Add known-commit READ-failure presentation RED**

`HOST_COMMITTED + RECONCILING` projects `RECOVERY_REQUIRED`, never `SUCCEEDED`.

- [ ] **Step 5: Implement pure facade**

No Impact/Scope/approval/execution/verification rule duplication.

- [ ] **Step 6: Run GREEN**

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
- Modify: `tests/product_runtime/conftest.py`
- Create: `tests/product_runtime/test_revit_wall_thickness_product_e2e.py`

**Required real components:** PostgreSQL ProductTask store, LangGraph PostgreSQL checkpointer, PostgreSQL workflow artifact store, real OperationResolver/ParameterBinder/Freshness/Impact/Scope/ChangeSet/Materialization/Execution Planning/Provider Binding/Gateway, PostgreSQL Saga V2 + HostDispatchIntent stores, real ScopeComparator/SemanticVerifier/convergence, real ProductFlow facade.

Allowed doubles: external Host transport behavior, human/presentation approval boundary, deterministic injected clocks already supported by existing public contracts.

- [ ] **Step 1: Build one stateful fake Revit transport, not fake owners**

It implements exact wire operations `context.current_selection`, `check_wall_thickness_readiness`, `set_wall_thickness`, `read_wall_thickness_snapshot`. Successful mutation increments document revision exactly once; independent READ observes post-commit state separately.

- [ ] **Step 2: Prove happy path**

Assert bound thickness 300, scope selected wall + PROPERTIES only, one EXECUTE, separate post-commit READ, matching revision, Step33 PASSED, Saga SUCCEEDED, ProductFlow SUCCEEDED.

- [ ] **Step 3: Prove request conflict + pre-start crash recovery**

Same task/different thickness conflicts before workflow mutation; request-only durable row starts exactly one workflow after fresh process recovery.

- [ ] **Step 4: Re-run full-flow 300/350 interleave**

Assert final bound operation/ChangeSet of each task preserves its own value/request hash.

- [ ] **Step 5: Prove independent READ value mismatch**

Mutation response says 300, exact-revision READ says 299. Assert no second EXECUTE, SemanticVerifier non-PASS, Saga/product non-success.

- [ ] **Step 6: Prove independent READ revision mismatch**

Inject unrelated revision between commit/read. Assert one EXECUTE, dispatch HOST_COMMITTED, slice RECONCILING, verification hash absent, product RECOVERY_REQUIRED. Rebuild/resume and prove no second mutation.

- [ ] **Step 7: Prove identity/document mismatch**

Wrong host instance/document/Wall.UniqueId refuses evidence and never reaches success.

- [ ] **Step 8: Run PostgreSQL product gate**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_revit_wall_thickness_product_e2e.py -q -vv
```

- [ ] **Step 9: Run predecessor regressions**

```bash
uv run pytest \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/orchestrator/test_task10_durable_recovery.py \
  tests/integration/test_phase_h_revit_wall_thickness_reconciliation.py -q
```

- [ ] **Step 10: Commit**

```bash
git add tests/product_runtime
git commit -m "test: prove Revit wall thickness product vertical offline"
```

---

## Task 10: Add mandatory live Revit product acceptance and separate conditional negatives

**Files:**
- Create: `tests/integration/test_revit_wall_thickness_product_live.py`
- Create: `docs/runbooks/revit-wall-thickness-product-vertical.md`

- [ ] **Step 1: Reuse reviewed Phase H isolated-wall fixture**

Verify `.rvt` SHA-256 and `isolated_wall_unique_id` exactly as current Phase H live acceptance. Seed environment-owned IdentityRegistry/TopologyRegistry for the fixture; ProductTask request still contains no model identity.

- [ ] **Step 2: Drive actual product flow over real named pipe**

Submit 300 mm, drive existing pauses, observe dedicated `read_wall_thickness_snapshot` after EXECUTE. Never construct verification evidence from mutation payload.

- [ ] **Step 3: Freeze mandatory happy-path assertions**

```text
request hash durable
selected identity == isolated wall
EXECUTE expected revision == binding metadata revision
commit increments revision
independent READ host/document/Wall.UniqueId exact
read_before == read_after == commit revision
wall_thickness_mm == approx(300.0, abs=1e-6)
Step33 PASSED
Saga SUCCEEDED
ProductFlow SUCCEEDED
```

- [ ] **Step 4: Record live negatives separately**

When controlled setup can deterministically select/configure Phase H shared-type/insert/join fixtures, run product-level negatives and record them. When that environment cannot deterministically establish the negative fixture, record `NOT_RUN_ENVIRONMENT_LIMITATION`; Task 9 offline negatives remain mandatory and live happy path remains mandatory.

- [ ] **Step 5: Document reset/repeatability**

Runbook records fixture restore, fixture hash, Revit version, TFM/API path/pipe, exact HEAD, mutation revision, independent READ revision and measured width.

- [ ] **Step 6: Run live acceptance**

```powershell
$env:DSP_REVIT_LIVE = "1"
python -m pytest tests/integration/test_revit_wall_thickness_product_live.py -q -vv -s
```

- [ ] **Step 7: Commit**

```bash
git add tests/integration/test_revit_wall_thickness_product_live.py docs/runbooks/revit-wall-thickness-product-vertical.md
git commit -m "test: add live Revit product vertical acceptance"
```

---

## Task 11: Add CI gate, full regression, scope audit and capability closeout

**Files:**
- Create: `.github/workflows/revit-wall-thickness-product-vertical.yml`
- Modify: `README.md`

- [ ] **Step 1: Add dedicated offline CI workflow**

Install from committed lock and run ProductTask deterministic/PostgreSQL tests, task-aware binder/orchestrator tests, Revit sidecar context/snapshot/execution/readiness tests, product semantic/evidence/facade tests, PostgreSQL full product E2E, Ruff on changed Python paths, and Revit Core .NET tests. Generic CI collects live test with `DSP_REVIT_LIVE=0`.

- [ ] **Step 2: Re-run every Task 1–10 focused command on one exact HEAD**

Do not use earlier commit logs as closeout evidence.

- [ ] **Step 3: Run exact repository-regression local parity**

```bash
python -m pip install uv
uv sync --locked --all-packages
uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
uv run ruff check \
  platform/product_runtime \
  platform/orchestrator \
  platform/execution_coordination \
  hosts/revit/sidecar \
  tests/product_runtime \
  tests/orchestrator \
  tests/execution_coordination \
  tests/revit
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj -f net8.0
```

Then require the current `repository-regression.yml` GitHub Actions run to be GREEN on the same HEAD; that workflow supplies Python 3.11 canonical, Python 3.14 compatibility, repository Ruff-delta enforcement and .NET 10 host-neutral compatibility.

- [ ] **Step 4: Scope audit**

Confirm no NLP/Agent/MCP front door, new canonical operation family, new Saga transition/state, checkpoint request body, latest/reverse request recovery, mutation-response verification fallback, WallType duplicate/reassign, multi-host/multi-document expansion, or semantic snapshot PostgreSQL migration.

- [ ] **Step 5: Update README only after exact-head offline + mandatory live happy path are GREEN**

Unit tests alone cannot mark the product capability implemented.

- [ ] **Step 6: Record fresh exact-head CI evidence**

Record branch SHA and required workflow run URLs/statuses. Any later commit invalidates the evidence until rerun.

- [ ] **Step 7: Commit closeout docs/CI**

```bash
git add .github/workflows/revit-wall-thickness-product-vertical.yml README.md
git commit -m "ci: gate Revit wall thickness product vertical"
```

- [ ] **Step 8: PR / merged-main lifecycle**

Merge through repository policy. Observe required merged-main workflows on the merge commit before marking capability `CLOSED`.

---

## Acceptance Matrix

| Proof | Required evidence |
| --- | --- |
| Request create-once | same body replay; different body conflict |
| Pre-start crash | request survives without workflow checkpoint and starts later |
| Binder lineage | explicit `task_id + operation_ref + context_snapshot_ref` |
| Cross-talk | 300/350 interleave after fresh stores/runtime/adapters |
| Semantic selection | one selected Host element -> existing semantic identity -> `ifc:IfcWall` |
| Planning | real Impact/Scope/ChangeSet/Planning/Binding/Gateway owners |
| Revision | planning revision frozen in binding hash; readiness and EXECUTE use exact value |
| Mutation | real `set_wall_thickness`, mm transport, one logical dispatch identity |
| Independent read | dedicated READ after commit; exact host/doc/entity/revision |
| Semantic result | Step33 verifies `dsp:WallThickness == requested thickness` |
| Evidence unavailable | `HOST_COMMITTED + RECONCILING`, no fake bundle, no second mutation, product recovery state |
| Value mismatch | exact-revision evidence reaches real SemanticVerifier and does not succeed |
| Product outcome | only Saga `SUCCEEDED` maps to product `SUCCEEDED` |
| Offline E2E | PostgreSQL request/checkpoint/artifact/Saga/dispatch + real owners |
| Live E2E | controlled real Revit happy path with separate independent READ |
| Live negative | separate evidence when deterministic live setup is available; otherwise explicitly recorded not-run |
| Closeout | exact-head CI + mandatory live happy path + merged-main observation |

---

## Stop-and-Amend Triggers

Implementation must stop and return to Design/Written-Spec review rather than improvising if:

1. independent READ failure cannot be represented truthfully as existing known-commit nonterminal recovery without adding a new Saga transition/state;
2. correct execution requires putting Host/native identity or revision authority into ProductTask request;
3. exact post-commit evidence requires accepting newer Host revision or mutation-response fallback;
4. product recovery requires rereading/reinterpreting original request after bound operation/ChangeSet authority is frozen;
5. real routing requires changing materialization-topology ownership rather than consuming existing environment-owned topology;
6. the single vertical requires generic NLP/Agent/MCP ingress or support-matrix expansion.

None of these conditions is supported by the source census at `b2b7e131...`; if one appears during TDD it is new architectural evidence, not permission to widen this plan.
