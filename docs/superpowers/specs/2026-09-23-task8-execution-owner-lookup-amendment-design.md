# Task 8 Execution Owner Lookup Amendment Design

**Status:** Proposed — in-chat design approved; written-spec review pending  
**Date:** 2026-09-23  
**Exact discovery base:** `feat/capability-real-owner-e2e-workflow@01c72938ce92c7df773a5c04ca28ca88f697b358`  
**Baseline design:** `docs/superpowers/specs/2026-09-20-real-owner-e2e-workflow-design.md`  
**Baseline plan:** `docs/superpowers/plans/2026-09-20-real-owner-e2e-workflow.md`  
**Workflow authority:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`  
**Persistence authority:** `docs/adr/ADR-008-durable-state-persistence-ownership.md`  
**Delivery/recovery authority:** `docs/adr/ADR-009-cross-owner-delivery-crash-recovery.md`

## 1. Purpose

Task 7 已在 exact HEAD `01c72938ce92c7df773a5c04ca28ca88f697b358` 完成并通过 exact-head gate。进入 Task 8 只读 contract archaeology 后，发现 baseline Task 8 的“request/wiring only”假设缺少三个公开能力：

1. Gateway V2 admitted grant 只冻结 `binding_set_hash`，Provider Binding V2 store 只公开 `get(binding_set_id)`；
2. durable Host dispatch intent 虽已持久化，但没有 public store protocol，也没有按 exact `saga_id + execution_slice_hash` 的 recovery lookup；
3. `begin_execution()` 若发现 unknown outcome / `RECOVERY_REQUIRED`，现有 graph async 分支不会同时持久化 `saga_id`，恢复时 `decide_apply_resume()` 会因为 checkpoint 没有 durable Saga identity 而返回 `MAY_DISPATCH`。

这三个缺口都属于 baseline Design §8.2 已冻结的条件：当 real-owner composition 缺少 owner public API 时，应 `FAIL DESIGN / expose missing owner API`，不得在 `CanonicalWorkflowOwnerPorts` 中发明反向索引、私有 lineage map 或恢复状态机。

本 Amendment 只补齐 Task 8 所需的最小 owner lookup 与 workflow navigation seam，不重写既有 Saga/Reconciliation/Provider Binding/Gateway 语义。

---

## 2. Repository facts that trigger this amendment

### 2.1 Provider Binding V2 cannot resolve an admitted hash

`InMemoryProviderBindingSetV2Store` 当前只提供：

```python
put(binding_set)
get(binding_set_id)
```

而 `AdmittedExecutionAuthorityV2` / `ExecutionGrantV2` 在 execution boundary 冻结的是：

```text
binding_set_hash
```

`CanonicalWorkflowOwnerPorts` 不得自行实现：

```python
binding_set_id = f"PBSV2-{binding_set_hash[:12]}"
```

来绕过 owner lookup。该 identity rule 属于 Provider Binding owner。

### 2.2 Dispatch intent recovery truth lacks an exact public lookup

`PostgresHostDispatchIntentStore` 已持久化：

```text
PREPARED
DISPATCHED
OUTCOME_UNKNOWN
HOST_COMMITTED
SAFE_TO_RETRY
RECONCILED
```

并且数据库 owner key 已包含唯一的：

```text
(saga_id, execution_slice_hash)
```

但当前 public surface 只有按 `dispatch_intent_id` 的 `get()`；`_select_by_slice()` 仍是 concrete PostgreSQL adapter 的私有实现。package root 也没有公开统一的 `HostDispatchIntentStore` contract。

因此 workflow composition 无法通过 public owner API 从 active Saga Slice 解析 exact Host-effect recovery truth。

### 2.3 Current async apply path loses Saga identity

现有 graph：

```text
refresh_execution_owner
  -> MAY_DISPATCH
  -> apply_or_recover
```

`apply_or_recover` 调用：

```python
begin_execution(execution_plan_ref, grant_ref)
```

返回 `str` 时会保存 `saga_id`；返回 `AsyncOperationRef` 时只写 async wait，不写 `saga_id`。

这对普通外部异步 operation 没问题，但对 execution unknown-outcome 不安全：真实 coordinator 已经创建 durable Saga 并写入 dispatch recovery truth，此时若 checkpoint 不保存 Saga identity，恢复后的 `refresh_execution_owner` 无法查询 owner state，`decide_apply_resume()` 会把“checkpoint 没有 saga_id”解释为尚未创建 durable Saga，并返回 `MAY_DISPATCH`。

因此 Task 8 必须允许 execution async result 把 owner-issued Saga identity 作为 workflow navigation 与 wait 原子持久化。

---

## 3. Goals

本 Amendment 必须实现：

1. Provider Binding owner 可以按 exact `binding_set_hash` 解析其 immutable V2 artifact；
2. Execution Reconciliation owner 暴露统一的 Host dispatch intent store contract，并能按 exact Saga/Slice 查询 recovery truth；
3. in-memory/reference 与 PostgreSQL dispatch-intent stores 实现同一 public contract，focused Task 8 不再需要 test-side authoritative dispatch store fake；
4. `CanonicalWorkflowOwnerPorts.begin_execution()` 可以完全从 authoritative public APIs 重建 coordinator 输入；
5. unknown outcome 返回 workflow wait 时，`saga_id` 与 async navigation 原子进入 graph state；
6. resume 必须先重新查询 `ExecutionOwnerView`，Host dispatch recovery 优先于 Saga 状态，禁止 blind redispatch；
7. success 与 DIVERGED 继续由真实 Saga/Reconciliation/Convergence owner 产生，adapter 只做 request assembly 和 read-model projection。

---

## 4. Non-goals

本 Amendment 不实现：

- 新的 Saga transition；
- 新的 reconciliation 或 convergence evaluator；
- automatic compensation；
- 新的 outbox/inbox/replay protocol；
- owner-wide PostgreSQL migration；
- Provider Binding owner-wide durability redesign；
- real AutoCAD/Revit acceptance；
- MCP/Agent front door；
- V1 retirement；
- 新 workflow topology；
- 把 full owner objects 放进 checkpoint；
- 用 adapter-private dict/cache 保存 grant→binding、saga→dispatch 或 plan→owner body lineage。

---

## 5. Decision

### 5.1 Provider Binding: add exact hash lookup at the owner boundary

扩展现有 V2 reference store：

```python
def get_by_hash(self, binding_set_hash: str) -> ProviderBindingSetV2:
    ...
```

冻结语义：

- 输入必须是合法 lowercase SHA-256；
- lookup 属于 Provider Binding owner；
- 返回前继续执行 owner-local id/hash integrity validation；
- unresolved hash 使用现有 Provider Binding reference-not-found error vocabulary；
- 不提供 latest/current/reverse-by-materialization 查询；
- 不要求本阶段新增 Provider Binding PostgreSQL backend。

owner 可以在自己的 store 内维护 hash index，或在 owner 内部使用当前 content-addressed identity 规则；调用方不得复制该规则。

### 5.2 Execution Reconciliation: publish a Host dispatch intent store contract

新增 package-root public protocol，最小形状为：

```python
class HostDispatchIntentStore(Protocol):
    def prepare(self, intent: HostDispatchIntent) -> HostDispatchIntent: ...
    def get(self, dispatch_intent_id: UUID) -> HostDispatchIntent | None: ...
    def get_for_saga_slice(
        self,
        saga_id: str,
        execution_slice_hash: str,
    ) -> HostDispatchIntent | None: ...
    def mark_dispatched(...): ...
    def mark_outcome_unknown(...): ...
    def mark_host_committed(...): ...
    def mark_safe_to_retry(...): ...
    def mark_reconciled(...): ...
```

新增 owner-owned `InMemoryHostDispatchIntentStore` reference implementation，并让现有 `PostgresHostDispatchIntentStore` 实现同一 contract。

`get_for_saga_slice()` 必须是 exact lookup：

```text
saga_id + execution_slice_hash -> 0 or 1 HostDispatchIntent
```

它不得“选最新”。PostgreSQL 已有唯一 owner key 时应直接按该 key 查询；in-memory reference implementation 必须冻结同一唯一性。

如果实现中需要共享 transition/integrity checks，应在 Execution Reconciliation owner 内提取共享 pure helper；不得让 in-memory 与 PostgreSQL 两套实现各自演化一份不同的 transition semantics。

### 5.3 Canonical composition explicitly receives the dispatch-intent owner

`CanonicalWorkflowOwnerPorts` constructor 增加：

```text
dispatch_intent_store
```

该依赖只用于 authoritative recovery read；reference/production composition 必须把与 `MaterializedExecutionSagaCoordinator` 相同的 logical dispatch-intent owner 显式传给 adapter。composition tests 应构造并复用同一个 injected store；adapter 不得自行创建第二个 store。本 Amendment 不要求增加运行时对象同一性 introspection。

adapter 不读取具体 PostgreSQL internals，也不调用 `_select_by_slice()` 等 private API。

### 5.4 `begin_execution()` reconstructs inputs only through public owner APIs

`begin_execution(execution_plan_ref, grant_ref)` 的允许职责固定为：

1. exact resolve `ExecutionPlanV2` 并验证 plan ref hash；
2. 要求 `grant_ref.content_hash` 非空，用该 exact hash 查询 Gateway V2 immutable grant，并校验 `grant_id`/hash 与 exact execution Slice lineage；
3. 通过 Gateway public admission API 获得同一 grant 的 admitted authority；该调用必须保持现有 idempotent admission semantics，不在 adapter 复制 lifecycle 规则；
4. 用 authority 的 `binding_set_hash` 调用 Provider Binding owner `get_by_hash()`；
5. 从 plan/ChangeSet/Approval Scope/Materialization owner stores 解析 exact artifacts；
6. 通过 `design_convergence` public builder 按已有 owner contract 确定性重建 convergence profile，并验证其 hash 等于 materialization/execution plan 冻结的 profile hash；
7. 把真实 artifacts 交给现有 `MaterializedExecutionSagaCoordinator.execute(...)`。

adapter 不缓存这些 body，也不创建第二份 lineage registry。

当前 workflow contract 仍只发布一个 `provider_binding_ref` / `grant_ref`，Task 7 已冻结“恰好一个 `ExecutionSliceV2`”边界；本 Amendment 不扩展 multi-slice workflow contract。

### 5.5 Materialized coordinator result mapping

`CanonicalWorkflowOwnerPorts.begin_execution()` 只投影 coordinator 已有结果，不重新分类 Saga：

```text
SUCCEEDED / DIVERGED / FAILED / PARTIALLY_COMMITTED
  -> return durable saga_id

RECOVERY_REQUIRED
  -> return AsyncOperationRef(
         kind=EXECUTION_JOB,
         owner="execution",
         operation_id=saga_id,
     )

READINESS_FAILED with no durable Saga
  -> fail closed through a stable workflow-facing error;
     never persist "NOT_CREATED" as a real saga_id
```

`RECOVERY_REQUIRED` 绝不能转换成“未提交”或重新调用 Host。

### 5.6 Graph navigation repair: persist Saga identity with execution wait

不改变 graph topology，也不新增 domain decision。

只修改 `apply_or_recover` 的 execution-async navigation：当 `begin_execution()` 返回：

```python
AsyncOperationRef(
    kind=AsyncOperationKind.EXECUTION_JOB,
    owner="execution",
    operation_id=<durable saga_id>,
)
```

graph 必须在**同一次 node update** 中写入：

```text
saga_id = operation_id
async_operation_ref = encoded result
resume_node = refresh_execution_owner
phase = APPLY_WAIT
```

非 execution-kind async ref 不得被误当成 Saga identity。

恢复后仍走现有：

```text
await_async_operation
  -> refresh_execution_owner
  -> get_execution_owner_state(saga_id)
  -> decide_apply_resume(...)
```

因此 checkpoint 只持有 owner-issued id/navigation，不持有 HostDispatchIntent body。

### 5.7 `get_execution_owner_state()` composes, but does not own, recovery truth

adapter 从真实 Saga store/service 读取 `StoredExecutionSagaV2`，投影为 `ExecutionSagaView`。

若 Saga 有一个 active Slice，则使用：

```python
dispatch_intent_store.get_for_saga_slice(
    saga_id,
    active_slice_hash,
)
```

读取 Host-effect truth。若存在多个 active Slice 而当前 workflow contract 无法唯一表达，fail closed；不得选择任意一个。

workflow-facing recovery projection冻结为保守映射：

```text
OUTCOME_UNKNOWN -> OUTCOME_UNKNOWN
SAFE_TO_RETRY   -> SAFE_TO_RETRY
PREPARED        -> RECOVERY_REQUIRED
DISPATCHED      -> RECOVERY_REQUIRED
HOST_COMMITTED  -> RECOVERY_REQUIRED
RECONCILED      -> no active dispatch recovery
```

这只是 read-model projection：adapter 不执行 intent transition，不把 `SAFE_TO_RETRY` 自动解释成允许新 Host command；现有 `decide_apply_resume()` 仍将三种 workflow recovery state 全部路由到 `RECOVER_OR_WAIT`。

### 5.8 `verify_reconcile()` is a terminal-owner read, not a second reconciler

真实 `MaterializedExecutionSagaCoordinator` 已负责：

```text
Host commit
-> local scope reconciliation
-> semantic verification
-> cross-host convergence
-> Saga terminal transition
```

因此 Task 8 的 `verify_reconcile(saga_id)` 不得再次实现或运行第二套 reconciliation。它重新读取 `ExecutionOwnerView`：

- terminal Saga (`SUCCEEDED`, `DIVERGED`, `PARTIALLY_COMMITTED`, `FAILED`)：返回 read model；
- active dispatch recovery 或非 terminal Saga：fail closed / remain recovery，不得让 graph 标记完成；
- `DIVERGED` 是 terminal observable owner result；不得调用 compensation。

---

## 6. File responsibility freeze

预计 Amendment B / Task 8 implementation 只允许触碰下列责任面；implementation plan 可以在书面 review 后进一步缩小，但不能扩大语义：

| File | Responsibility |
| --- | --- |
| `platform/provider_binding/src/design_provider_binding/store_v2.py` | owner-local exact hash lookup |
| `platform/provider_binding/src/design_provider_binding/__init__.py` | export approved public V2 lookup surface as needed |
| `platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent_store.py` | public store protocol + owner-owned in-memory reference implementation |
| `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py` | implement exact Saga/Slice lookup on existing durable store |
| `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py` | package-root public exports |
| `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py` | request assembly + terminal/recovery read-model projection only |
| `platform/orchestrator/src/design_orchestrator/langgraph_graph.py` | atomically persist Saga id with execution async navigation |
| `tests/orchestrator/test_canonical_owner_execution.py` | real Saga/Reconciliation/Convergence success, DIVERGED, unknown outcome |
| `tests/orchestrator/test_langgraph_graph.py` | execution async result persists saga id and resumes through refresh |
| `tests/architecture/test_real_owner_workflow_boundaries.py` | no private owner imports/maps/V1/test-owner regressions |

No CI workflow change is authorized by this Amendment itself.

---

## 7. Required tests

### A. Provider Binding hash lookup

Prove:

```text
put(binding_set)
-> get_by_hash(binding_set.binding_set_hash)
-> exact same immutable artifact
```

Invalid or unresolved hash fails at the Provider Binding owner boundary; adapter never derives binding-set id.

### B. Dispatch store parity

Run the same contract cases against in-memory reference and PostgreSQL store where PostgreSQL is available:

```text
prepare replay-safe
same Saga/Slice different lineage conflict
exact get_for_saga_slice
DISPATCHED
OUTCOME_UNKNOWN
HOST_COMMITTED
SAFE_TO_RETRY
RECONCILED
CAS conflict
```

### C. Real success

Use real:

```text
ExecutionReconciliationServiceV2
MaterializedExecutionSagaCoordinator
ExecutionSagaStoreV2
HostDispatchIntentStore
CrossHostConvergenceVerifier
```

and only allowed Host/evidence/clock doubles.

Assert owner terminal truth is `SUCCEEDED`; Host execute count is exactly one.

### D. Real DIVERGED

Inject divergent canonical evidence only through the allowed evidence boundary. Assert real convergence owner and Saga record `DIVERGED`; no compensation call/surface is introduced.

### E. Unknown outcome / no blind redispatch

First call reaches durable Host dispatch intent then receives commit-state-unknown result:

```text
Host execute count == 1
Saga id exists
HostDispatchIntent == OUTCOME_UNKNOWN
begin_execution returns execution AsyncOperationRef carrying that saga id
```

Graph must atomically persist saga id + wait. After resume:

```text
refresh_execution_owner reads exact Saga/Slice dispatch truth
-> RECOVER_OR_WAIT
-> Host execute count remains 1
```

A repeated direct coordinator/adapter call for the same durable lineage must also return recovery without issuing a second Host command。

### F. Architecture

Machine-enforced guard must reject:

```text
adapter derivation of PBSV2 id from hash
adapter access to provider-binding private dicts
adapter access to PostgresHostDispatchIntentStore private selectors
adapter-local saga->dispatch / grant->binding maps
ScenarioOwners/test helpers in production composition
V1 execution surfaces
```

---

## 8. Acceptance criteria

Amendment B is implemented only when all are true:

1. Task 7 behavior remains GREEN；
2. no authoritative test fake is required for Provider Binding lookup or dispatch-intent persistence；
3. successful real coordinator path reaches Saga `SUCCEEDED`；
4. divergent evidence reaches real Saga `DIVERGED` without compensation；
5. unknown outcome persists `OUTCOME_UNKNOWN`, carries durable `saga_id` into workflow wait, and cannot redispatch blindly；
6. `ExecutionOwnerView` is built from real Saga + exact dispatch owner truth；
7. checkpoint still contains refs/navigation only, not owner bodies；
8. no owner-private API or adapter lineage cache is introduced；
9. focused tests/Ruff pass；
10. implementation closure later requires exact-head repository CI, but no implementation begins until this written spec and the follow-on written plan are reviewed。

---

## 9. Supersession and execution gate

This Amendment supersedes only the baseline Task 8 assumptions that:

```text
existing Provider Binding lookup is already sufficient for grant->binding reconstruction
existing durable dispatch-intent surface is already sufficient for Saga/Slice recovery lookup
existing apply_or_recover async navigation already preserves durable Saga identity
```

All other baseline Design, Amendment A, ADR-008/009/010 ownership rules remain in force.

Until this written spec is reviewed and approved:

```text
Task 8 production implementation FORBIDDEN
Task 9/10 implementation FORBIDDEN
baseline Task 7 code MUST NOT be rolled back
```

After written-spec approval, the next permitted action is to revise the implementation plan for Task 8/9/10 using the approved contracts above. Implementation may begin only after that written plan is reviewed and an execution method is selected.
