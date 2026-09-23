# Capability Phase — Real-Owner E2E Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every production-code task is TDD RED → GREEN → focused verification → exact-head verification → commit. Do not collapse gates.

**Status:** Baseline implementation in progress — Amendment A written-plan review pending  
**Date:** 2026-09-20  
**Amendment A date:** 2026-09-23  
**Original base:** `main@f5ffd4633fbb28c2a54bbc4417df805fac9c2d6c`  
**Amendment base:** `feat/capability-real-owner-e2e-workflow@1cce9ce7cbb6afef3feabb464118b952b1ecb114`  
**Spec:** `docs/superpowers/specs/2026-09-20-real-owner-e2e-workflow-design.md` §21 Amendment A  
**Workflow authority:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`  
**Persistence authority:** `docs/adr/ADR-008-durable-state-persistence-ownership.md`  
**Delivery authority:** `docs/adr/ADR-009-cross-owner-delivery-crash-recovery.md`

## Goal

完成 real-owner workflow reference composition，但在继续 Task 7 Step 3 之前，先修复 Task 6 rereview 暴露的 operation freshness → Impact exact-lineage 缺口：successful freshness 必须显式携带 exact `operation_ref + planning_snapshot_ref + snapshot_set_ref`，Impact 必须只消费这组 refs，并在调用真实 Impact owner 前验证三者属于同一次合法 operation freshness 结果。

本 Amendment 不推翻已经完成的 composition 主干，也不回滚 Task 7 Step 1/2。它只重开 Task 6 的 freshness→Impact boundary，并把 checkpoint/recovery evidence 收紧到真实 LangGraph checkpointer 持久化的 graph state。

## Architecture

Baseline 调用栈仍是：

```text
LangGraphWorkflowRuntime
  → DefaultWorkflowServices
    → CanonicalWorkflowOwnerPorts
      → authoritative owner public APIs
```

Amendment A 只允许修改两个 workflow-facing seam：

```text
ensure_operation_freshness(operation_ref)
  -> OperationFreshnessResult | AsyncOperationRef

analyze_impact(
  operation_ref,
  planning_snapshot_ref,
  snapshot_set_ref,
)
  -> StableRef
```

`OperationFreshnessResult` 是 Workflow Orchestrator 自己拥有的 navigation envelope，不是新的 authoritative artifact。它只包含三个 owner-issued `StableRef`。LangGraph private state 允许保存这三个 refs 的 JSON-compatible 编码，但不能保存 `SemanticSnapshot`、`SnapshotSet`、freshness contract body 或 Impact owner object。

Task 6 repair 完成前，Task 7 Step 3 及后续 product implementation 保持暂停。

## Tech Stack

Python 3.11 / 3.14、LangGraph 1.2.x、`langgraph-checkpoint-postgres` 3.x、PostgreSQL 17、pytest、Ruff、GitHub Actions；保持现有 .NET 10 / Revit Core repository regression。版本以 exact-head lockfile/CI 为准，本 Amendment 不做依赖升级。

---

## Current Execution Checkpoint

Amendment A 从以下 exact branch 状态继续：

```text
feature branch: feat/capability-real-owner-e2e-workflow
amendment base: 1cce9ce7cbb6afef3feabb464118b952b1ecb114
```

当前代码事实：

```text
CanonicalWorkflowOwnerPorts 已存在
Task 6 real freshness / Impact / ChangeSet 主干已接入，但 freshness→Impact lineage 有 P1 ambiguity
Task 7 Step 1 approval 已接入
Task 7 Step 2 planning 已接入
Task 7 当前 fail-closed boundary 已推进到 check_revision_barrier()
Task 7 Step 3 尚未开始
```

已保留的 Task 7 Step 2 产品基线为 `a6b31a82ee975330a103081c5714a2c2d0c14fa7`；测试边界迁移基线为 `c0c7b45d828910af2242d232e5817bef188b9c38`。Amendment A 的两个设计提交位于其后，仅修改设计文档。

### Execution rule

- Baseline Tasks 1–5 不重跑、不回滚；只有 Task 6 repair 触发的真实 regression 才允许最小兼容修改。
- 原 Task 6 标记为 **REOPENED**，不是重新实现整个 Task 6。
- Task 7 Step 1/2 作为 retained capability；repair 必须证明它们没有回退。
- Task 7 Step 3 只有在 Task 6 repair exact-head GREEN 后才能恢复。
- Tasks 8–10 保持原顺序，在 Task 7 完成后继续。

---

## Amendment A Supersession Rules

本节显式覆盖原 Plan 中已经不再成立的表述；其余 baseline Plan/Design 约束继续有效。

1. 原 Architecture / Global Constraints 中“`WorkflowServices`、`DefaultWorkflowServices`、`ExternalOwnerPorts` shape 完全不变”被收窄为：**只有 `ensure_operation_freshness` 与 `analyze_impact` 两个 seam 可按 §21.4 修改；其它 method signatures 继续冻结。**
2. 原 Task 4 “实现 exact existing `ExternalOwnerPorts` signature”是当时的历史实现要求；Task 6R 必须把 structural conformance test 迁移到 Amendment A 的新两个签名，其它方法不得变化。
3. 原 Task 6 中“planning SnapshotSet → Impact”若通过 freshness-contract reverse lookup 或 member reverse lookup 实现，现被 §21.6/§21.9 明确禁止。success path 必须使用 exact refs。
4. 原“fresh process / rebuilt adapter”表述必须拆开：同一 in-memory owner stores 上重建 adapter 只证明没有 adapter-private lineage；跨进程恢复仍受 Design §12 的 owner resolvability 条件约束。
5. graph topology 的节点顺序不变，但 `ensure_operation_freshness` 可以在一次 node update 中新增 `planning_snapshot_ref`、`snapshot_set_ref` private navigation fields。

---

## Global Constraints

- `Workflow Orchestrator` 仍是 workflow progression/checkpoint/HITL/wait-reentry logical owner；LangGraph 只是 reference runtime。
- `OperationFreshnessResult` 只能位于 framework-neutral workflow contract 层，不能成为 Semantic Runtime owner、store 或第二份 truth。
- 三个 freshness refs 是一个不可拆分的 success tuple，必须由同一次 `ensure_operation_freshness` graph node update 写入。
- async freshness wait/re-entry 必须清除旧 `planning_snapshot_ref` / `snapshot_set_ref`，禁止 stale pair 与新结果拼接。
- `CanonicalWorkflowOwnerPorts.analyze_impact(...)` 必须先解析并验证 exact refs，再调用真实 `ImpactAnalyzer`。
- production/reference success path 禁止调用 `get_snapshot_for_freshness_contract()`、`get_snapshot_set_for_member()` 或等价 latest/current/reverse lookup。
- adapter 禁止维护 `operation_ref -> snapshot`、`snapshot -> set`、`impact -> task` 等 process-local lineage truth map。
- authoritative owner output 必须由 owner-local repository/registry/service 解析；checkpoint 只持有 stable refs/navigation。
- 新增 Python 代码必须有完整中文注释/文档字符串，并满足当前 Ruff/typing 风格。
- 不新增 owner-wide PostgreSQL migration，不把 rebuilt-adapter test 描述成 cross-process durability proof。
- `_ScenarioOwners` 只保留 fast orchestration regression；real-owner path 不得 import/construct/delegate 到它。
- V1 consumer surfaces 禁止重新进入 production/reference adapter。
- 不实现 MCP/Agent front door、real AutoCAD/Revit acceptance、automatic compensation、V1 retirement、new outbox/inbox/replay architecture 或 support-matrix expansion。

---

## File Structure Freeze for Amendment A

| File | Responsibility in this repair |
| --- | --- |
| `platform/orchestrator/src/design_orchestrator/workflow_contracts.py` | 定义 non-authoritative `OperationFreshnessResult` typed navigation envelope |
| `platform/orchestrator/src/design_orchestrator/workflow_services.py` | 只迁移两个 approved workflow-facing signatures |
| `platform/orchestrator/src/design_orchestrator/default_workflow_services.py` | 只代理两个 approved signatures，不增加 domain logic |
| `platform/orchestrator/src/design_orchestrator/langgraph_state.py` | 增加 private `planning_snapshot_ref` / `snapshot_set_ref` StableRef fields；不扩 authoritative body |
| `platform/orchestrator/src/design_orchestrator/langgraph_graph.py` | successful freshness 原子写三 refs；async path 清 stale pair；Impact exact three-ref call |
| `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py` | 返回 exact freshness refs；exact owner resolution + frozen lineage validation；删除该 success path reverse lookup |
| `platform/semantic_runtime/src/semantic_runtime/snapshot_registry.py` | 继续提供 exact `get_snapshot(id)` / `get_snapshot_set(id)`；不为本 repair 新增 mutable current binding |
| `tests/orchestrator/test_default_workflow_services.py` | 两个 seam 的 delegation/shape regression |
| `tests/orchestrator/test_langgraph_graph.py` | atomic state update、stale-pair negative、actual LangGraph saver round-trip、refs-only assertions |
| `tests/orchestrator/test_canonical_owner_ports.py` | interleaved two-revision、四类 mismatch、rebuilt-adapter no-private-state proof、Task 7 Step 1/2 compatibility |
| `tests/architecture/test_real_owner_workflow_boundaries.py` | 禁止 production adapter 使用 reverse-lookup success path / hidden lineage / V1/private surfaces |

`WorkflowCheckpointView` 公共字段不因本 Amendment 自动扩张。只有在真实 runtime recovery test 证明 private graph state 无法通过 LangGraph saver 恢复这两个 refs 时，才允许停下并回到 Design/Plan；不得为了测试便利把它们无条件提升为新的 public checkpoint contract。

---

## Review Focus

1. **Interleaved revisions:** `freshness@42 → freshness@43 → Impact@42 → Impact@43` 时，后一次 freshness 不能污染前一个 workflow 的 exact refs。
2. **Cross-ref integrity:** 三个 ref 各自合法但关系错误时，必须在 `ImpactAnalyzer.analyze()` 前 fail closed，且 Impact call count 为 0。
3. **Async stale pair:** wait/re-entry 期间旧 planning/snapshot-set refs 不能残留并与新 operation freshness success 混用。
4. **Checkpoint evidence:** recovery proof 必须从 LangGraph checkpointer 实际持久化后读回的 `StateSnapshot.values` 恢复 refs，不能只复用测试局部变量。
5. **Recovery claim boundary:** rebuilt adapter + same in-memory stores 只能证明 no-private-state；fresh-process durability 只有 owner stores 真正跨进程可解析时才能声称。

每一项都在 Task 6R 对应 RED/GREEN 中有直接测试，不留给最终 E2E 才发现。

---

# Amendment A Execution Tasks

### Task 6R.1: Freeze the new workflow contract and graph-state atomicity

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_contracts.py`
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/default_workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_state.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify: `tests/orchestrator/test_default_workflow_services.py`
- Modify: `tests/orchestrator/test_langgraph_graph.py`

**Consumes:** existing `StableRef`, `AsyncOperationRef`, existing LangGraph private state codec.

**Produces:**

```python
@dataclass(frozen=True, slots=True)
class OperationFreshnessResult:
    """成功 operation freshness 的 workflow-local exact navigation refs。"""

    operation_ref: StableRef
    planning_snapshot_ref: StableRef
    snapshot_set_ref: StableRef
```

Approved method signatures:

```python
def ensure_operation_freshness(
    self,
    operation_ref: StableRef,
) -> OperationFreshnessResult | AsyncOperationRef:
    raise NotImplementedError


def analyze_impact(
    self,
    operation_ref: StableRef,
    planning_snapshot_ref: StableRef,
    snapshot_set_ref: StableRef,
) -> StableRef:
    raise NotImplementedError
```

`OperationFreshnessResult.__post_init__` only enforces that all three members are `StableRef`; it must not resolve owners or duplicate lineage semantics.

- [ ] **Step 1: Add contract/delegation RED tests**

In `tests/orchestrator/test_default_workflow_services.py`, import the new type and freeze the exact delegation shape. The fake external owner should return:

```python
OperationFreshnessResult(
    operation_ref=StableRef("operation-1", "a" * 64),
    planning_snapshot_ref=StableRef("PS-42", "b" * 64),
    snapshot_set_ref=StableRef("PSS-42", "c" * 64),
)
```

Assert `DefaultWorkflowServices.ensure_operation_freshness(...)` returns the same typed value and `analyze_impact(...)` forwards all three refs in order.

- [ ] **Step 2: Add graph atomic-success RED**

In `tests/orchestrator/test_langgraph_graph.py`, add a narrow service fixture that reaches `ensure_operation_freshness`, returns one `OperationFreshnessResult`, and captures the arguments received by `analyze_impact`.

Assert the persisted state visible from the compiled graph/checkpointer contains all three refs from the same result:

```python
assert snapshot.values["operation_ref"] == {
    "ref_id": "operation-42",
    "content_hash": "a" * 64,
}
assert snapshot.values["planning_snapshot_ref"] == {
    "ref_id": "PS-42",
    "content_hash": "b" * 64,
}
assert snapshot.values["snapshot_set_ref"] == {
    "ref_id": "PSS-42",
    "content_hash": "c" * 64,
}
```

and captured Impact arguments equal the exact tuple. Do not assert only Python-local return values.

- [ ] **Step 3: Add async stale-pair RED**

Seed graph state with an old pair, then make `ensure_operation_freshness()` return an `AsyncOperationRef`. The resulting checkpoint must contain:

```python
assert snapshot.values.get("planning_snapshot_ref") is None
assert snapshot.values.get("snapshot_set_ref") is None
assert snapshot.values["async_operation_ref"]["operation_id"] == "reconstruct-43"
```

Resume/poll with a new successful result and assert the new pair is written together before Impact receives it. A partial tuple must not reach `analyze_impact`.

- [ ] **Step 4: Run RED and record the expected failures**

```bash
uv run pytest \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_langgraph_graph.py -q
```

Expected before implementation: import/signature/state assertions fail because `OperationFreshnessResult` and the two private state refs are absent.

- [ ] **Step 5: Implement the minimal contract/seam/state changes**

In `workflow_contracts.py`, add/export `OperationFreshnessResult` immediately after `StableRef` so it remains a framework-neutral navigation type.

In `workflow_services.py` and `default_workflow_services.py`, change only the two approved signatures/imports. `DefaultWorkflowServices` must remain a delegator; no snapshot resolution or lineage validation belongs there.

In `langgraph_state.py`, add only:

```python
planning_snapshot_ref: dict[str, object] | None
snapshot_set_ref: dict[str, object] | None
```

to `WorkflowGraphState` private fields.

In `langgraph_graph.py`, successful freshness must return one update containing all three refs:

```python
return {
    "operation_ref": _encode_stable_ref(result.operation_ref),
    "planning_snapshot_ref": _encode_stable_ref(result.planning_snapshot_ref),
    "snapshot_set_ref": _encode_stable_ref(result.snapshot_set_ref),
    "async_operation_ref": None,
    "resume_node": None,
    "phase": WorkflowPhase.ANALYZE_IMPACT.value,
}
```

The async branch must preserve the existing `_set_async_wait()` behavior and clear stale pair fields in the same node update:

```python
return {
    **_set_async_wait(
        result,
        resume_node="ensure_operation_freshness",
        phase=WorkflowPhase.ENSURE_OPERATION_FRESHNESS,
    ),
    "planning_snapshot_ref": None,
    "snapshot_set_ref": None,
}
```

`analyze_impact` must `_require_stable_ref(...)` all three refs and call the new service signature. Do not make the graph inspect snapshot bodies or compare lineage.

- [ ] **Step 6: Run GREEN**

```bash
uv run pytest \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_langgraph_graph.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/workflow_contracts.py \
  platform/orchestrator/src/design_orchestrator/workflow_services.py \
  platform/orchestrator/src/design_orchestrator/default_workflow_services.py \
  platform/orchestrator/src/design_orchestrator/langgraph_state.py \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_langgraph_graph.py
```

- [ ] **Step 7: Commit Task 6R.1**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/workflow_contracts.py \
  platform/orchestrator/src/design_orchestrator/workflow_services.py \
  platform/orchestrator/src/design_orchestrator/default_workflow_services.py \
  platform/orchestrator/src/design_orchestrator/langgraph_state.py \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_langgraph_graph.py
git commit -m "feat: carry exact operation freshness refs"
```

---

### Task 6R.2: Replace reverse lookup with exact owner resolution and frozen lineage validation

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Modify: `tests/orchestrator/test_canonical_owner_ports.py`
- Modify: `tests/architecture/test_real_owner_workflow_boundaries.py`
- Do not modify `platform/semantic_runtime/src/semantic_runtime/snapshot_registry.py` unless an exact-id lookup defect is proven; current `get_snapshot(id)` / `get_snapshot_set(id)` are the approved path.

**Consumes:** Task 6R.1 `OperationFreshnessResult`; Semantic Runtime `SemanticSnapshot`, `SnapshotSet`, `build_operation_contract`; existing workflow artifact store and `_operation_freshness_contract(...)` helper.

**Produces:** exact freshness refs and fail-closed pre-Impact relation validation with no reverse-lookup success path.

- [ ] **Step 1: Write the interleaved two-revision RED**

Extend `tests/orchestrator/test_canonical_owner_ports.py` with one real FreshnessResolver/ImpactAnalyzer fixture that deliberately keeps both immutable histories:

```text
same bound operation / same operation freshness contract
freshness@42 -> PS-42 / PSS-42
freshness@43 -> PS-43 / PSS-43
Impact@42
Impact@43
```

The fixture must vary Host revision/reconstruction result without deleting PS-42/PSS-42. Store both `OperationFreshnessResult` values and invoke Impact later in the interleaved order.

Assert the Impact request capture sees:

```text
Impact@42 -> planning PS-42 and set PSS-42
Impact@43 -> planning PS-43 and set PSS-43
```

and no `SNAPSHOT_CONTRACT_REFERENCE_AMBIGUOUS` is raised.

- [ ] **Step 2: Verify the interleaved RED**

```bash
uv run pytest \
  tests/orchestrator/test_canonical_owner_ports.py \
  -k "interleaved and freshness and impact" -q
```

Expected on the pre-repair implementation: FAIL because successful freshness still returns `operation_ref` and Impact reverse-resolves by reusable contract identity.

- [ ] **Step 3: Add four pre-Impact mismatch RED cases**

Add a counting/capturing Impact analyzer and prove `analyze()` call count remains `0` for each case:

```text
A. ref/hash mismatch
   exact owner object exists, but StableRef.content_hash is changed

B. SnapshotSet membership mismatch
   planning_snapshot_ref points to PS-42 while snapshot_set_ref points to a valid PSS that does not contain PS-42

C. document/environment mismatch
   exact refs resolve, but selected planning/set belongs to a different valid document or SemanticEnvironment than the current bound operation/context

D. freshness-contract ↔ bound-operation mismatch
   exact refs resolve to a valid planning snapshot created for another bound operation contract
```

Each test must assert failure occurs before real Impact analyzer invocation. Do not satisfy the test by catching a later Impact validation error.

- [ ] **Step 4: Implement successful freshness return shape**

In `CanonicalWorkflowOwnerPorts.ensure_operation_freshness(...)`, after existing real `FreshnessResolver` success and owner registry writes, return:

```python
return OperationFreshnessResult(
    operation_ref=operation_ref,
    planning_snapshot_ref=StableRef(resolved.snapshot_id, resolved.hash),
    snapshot_set_ref=StableRef(snapshot_set.snapshot_set_id, snapshot_set.hash),
)
```

The async path remains `AsyncOperationRef` and must not synthesize snapshot refs.

- [ ] **Step 5: Implement exact-id resolution only**

Change `CanonicalWorkflowOwnerPorts.analyze_impact(...)` to resolve:

```python
bound = self._bound_operation(operation_ref)
planning = self._snapshot_registry.get_snapshot(planning_snapshot_ref.ref_id)
snapshot_set = self._snapshot_registry.get_snapshot_set(snapshot_set_ref.ref_id)
contract, context_snapshot = self._operation_freshness_contract(bound)
```

Immediately verify supplied hashes against authoritative objects with existing `_ref_hash_matches(...)`. Remove this success path's calls to:

```text
get_snapshot_for_freshness_contract
get_snapshot_set_for_member
```

The registry methods themselves may remain for other consumers; this task does not delete public history/query APIs merely to satisfy the adapter.

- [ ] **Step 6: Implement the four frozen relation checks before Impact**

Use existing public object fields/canonical contract construction; do not add a new policy engine. The pre-Impact guard must establish at least:

```python
if planning.snapshot_id != planning_snapshot_ref.ref_id:
    raise ValueError("planning snapshot ref does not match authoritative identity")
if snapshot_set.snapshot_set_id != snapshot_set_ref.ref_id:
    raise ValueError("snapshot-set ref does not match authoritative identity")

matching_members = [
    member
    for member in snapshot_set.members
    if member.snapshot_id == planning.snapshot_id and member.hash == planning.hash
]
if len(matching_members) != 1:
    raise ValueError("snapshot set does not contain the exact planning snapshot")

if planning.document_ref != contract.coverage.document_ref:
    raise ValueError("planning snapshot document does not match bound operation")
if planning.project_id != contract.project_id:
    raise ValueError("planning snapshot project does not match bound operation")
if planning.semantic_environment_ref != snapshot_set.semantic_environment_ref:
    raise ValueError("planning snapshot environment does not match snapshot set")
if planning.semantic_environment_ref != context_snapshot.semantic_environment_ref:
    raise ValueError("planning snapshot environment does not match bound-operation context")

if planning.freshness_contract_id != contract.contract_id:
    raise ValueError("planning snapshot freshness contract does not match bound operation")
if planning.freshness_contract_hash != contract.hash:
    raise ValueError("planning snapshot freshness contract hash does not match bound operation")
```

Before these relation checks, call `_ref_hash_matches(...)` for both exact semantic refs. Reuse existing owner/public validation exceptions where one already expresses the invariant; otherwise use a narrow adapter integrity failure translated by the existing workflow error boundary. Do not compare revisions and choose a winner.

- [ ] **Step 7: Add architecture RED/GREEN for the old reverse path**

In `tests/architecture/test_real_owner_workflow_boundaries.py`, inspect the production adapter and fail if `CanonicalWorkflowOwnerPorts.analyze_impact` references either old reverse-query API:

```text
get_snapshot_for_freshness_contract
get_snapshot_set_for_member
```

Retain existing guards against adapter-local lineage dictionaries, V1 symbols, test helpers and owner-private modules.

- [ ] **Step 8: Run focused GREEN**

```bash
uv run pytest \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
```

- [ ] **Step 9: Commit Task 6R.2**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
git commit -m "fix: preserve exact freshness impact lineage"
```

---

### Task 6R.3: Prove persisted checkpoint round-trip and rebuilt-adapter no-private-state recovery

**Files:**
- Modify: `tests/orchestrator/test_langgraph_graph.py`
- Modify: `tests/orchestrator/test_canonical_owner_ports.py`
- Modify production checkpoint code only if the RED demonstrates an actual serialization defect; no public checkpoint expansion by default.

**Consumes:** Task 6R.1 private graph refs and Task 6R.2 exact adapter path.

**Produces:** evidence that exact lineage survives the real LangGraph checkpointer/serializer boundary and that a new adapter can consume restored refs without old adapter memory.

- [ ] **Step 1: Write actual checkpointer round-trip RED**

Use a compiled graph with `langgraph.checkpoint.memory.InMemorySaver`, because this test is about LangGraph state persistence/serialization rather than cross-process durability.

Drive the graph through successful operation freshness and to a safe persisted boundary. Read the state back through supported `graph.get_state(config)` from the injected saver; do not use service fixture local variables as the source of recovered refs.

Assert `StateSnapshot.values` contains JSON-compatible mappings for all three refs and no authoritative bodies. Then perform the existing checkpoint-safe JSON representation round-trip on those persisted values and rebuild `StableRef` values from the restored mappings.

Required recovered values:

```text
operation_ref
planning_snapshot_ref
snapshot_set_ref
```

This test may say “saver-backed serialized state round-trip”; it must not say “cross-process durability”.

- [ ] **Step 2: Prove stale/partial persisted tuple is rejected before Impact**

Construct saver-backed graph-state cases with one freshness ref missing or with an old pair beside a newer operation ref. Continue the compiled graph and assert it cannot call `analyze_impact`; `_require_stable_ref`/workflow validation must fail closed.

- [ ] **Step 3: Rebuilt-adapter RED/GREEN using restored refs**

In `tests/orchestrator/test_canonical_owner_ports.py`:

```text
adapter A
  -> real freshness success
  -> owner stores contain exact PS/PSS
  -> refs are persisted through saver-backed graph state
  -> discard adapter A
adapter B(new instance, same owner stores)
  -> consume StableRefs restored from persisted state
  -> assemble/call Impact for the same exact PS/PSS
```

Do not pass `OperationFreshnessResult` or snapshot objects directly from adapter A to adapter B through Python locals. The only bridge is persisted/deserialized ref data plus authoritative owner stores.

Name/docstring this test as **rebuilt-adapter/no-private-state**, not “cross-process recovery”.

- [ ] **Step 4: Run GREEN**

```bash
uv run pytest \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_canonical_owner_ports.py -q
uv run ruff check \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_canonical_owner_ports.py
```

- [ ] **Step 5: Commit Task 6R.3**

```bash
git add \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_canonical_owner_ports.py
git commit -m "test: prove persisted freshness lineage recovery"
```

If this task proves `WorkflowCheckpointView` must expose the private refs for runtime correctness rather than test convenience, stop before changing it and return to Design/Plan amendment. The approved default is private LangGraph state persistence.

---

### Task 6R.4: Close Task 6 repair with compatibility, architecture, and exact-head evidence

**Files:**
- Modify only tests/product files required by failures caused by the two approved seam changes.
- Do not advance `check_revision_barrier()` implementation in this task.

- [ ] **Step 1: Migrate fast scenario/service doubles to the new two-method shape**

Search exact branch consumers:

```bash
rg -n "ensure_operation_freshness\(|analyze_impact\(" platform tests
```

Every impacted fake/service implementation must return/pass `OperationFreshnessResult` consistently. Preserve `_ScenarioOwners` purpose; do not replace it with real-owner composition.

- [ ] **Step 2: Prove Task 7 Step 1/2 compatibility**

Run `tests/orchestrator/test_canonical_owner_ports.py` and assert the current post-planning fail-closed regression still fails at `check_revision_barrier`, not at approval/planning or freshness/Impact.

The retained boundary is:

```text
approval           -> real
execution planning -> real
check_revision_barrier -> CANONICAL_OWNER_PORT_NOT_WIRED until Task 7 Step 3
```

- [ ] **Step 3: Run focused Task 6 owner regressions**

```bash
uv run pytest \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_langgraph_runtime.py \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  tests/architecture/test_canonical_v2_boundaries.py \
  -q

uv run pytest \
  tests/semantic_runtime \
  tests/impact \
  tests/approval_scope \
  tests/changeset \
  -q
```

If an owner test package was renamed on the implementation HEAD, stop and update this Plan with the concrete replacement path before claiming the corresponding owner regression; do not silently omit it.

- [ ] **Step 4: Run Ruff with no new diagnostics**

```bash
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/workflow_contracts.py \
  platform/orchestrator/src/design_orchestrator/workflow_services.py \
  platform/orchestrator/src/design_orchestrator/default_workflow_services.py \
  platform/orchestrator/src/design_orchestrator/langgraph_state.py \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
```

Use repository no-new-diagnostics policy if baseline diagnostics exist; do not make unrelated exception/refactor changes to manufacture a clean global Ruff run.

- [ ] **Step 5: Exact-head CI gate**

Push the exact Task 6 repair HEAD and require all repository gates triggered for that SHA to finish with no failure/in-progress, including at least:

```text
Python 3.11 canonical
Python 3.14
Step36 / canonical architecture regression
Workflow Orchestrator relevant persistence lane if triggered
Revit Core
.NET 10
```

Do not use an earlier SHA’s GREEN as evidence for the repair HEAD.

- [ ] **Step 6: Close Task 6 repair only after evidence**

Record:

```text
interleaved two-revision GREEN
four mismatch negatives GREEN and Impact call count 0
atomic/stale-pair GREEN
saver-backed checkpoint round-trip GREEN
rebuilt-adapter no-private-state GREEN
no reverse-lookup architecture guard GREEN
Task 7 Step 1/2 compatibility GREEN
exact-head CI GREEN
```

Only then mark Task 6 repair CLOSED and resume Task 7 Step 3.

---

# Remaining Baseline Tasks After Task 6R

### Task 7 Step 3–5: Revision barrier → Provider Binding V2 → grant

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Modify: `tests/orchestrator/test_canonical_owner_ports.py`

**Precondition:** Task 6R.4 exact-head gate is CLOSED. Task 7 Step 1/2 implementation remains in place.

**Required real calls:**

```text
RevisionBarrier.check
resolve_provider_bindings_v2
GatewayAuthorizationServiceV2.issue_execution_grant
GatewayAuthorizationServiceV2.admit_execution_grant
```

- [ ] **Step 1: Write revision-ordering RED**

Resolve `ExecutionPlanV2` by exact plan ref, follow its authoritative ChangeSet/SnapshotSet lineage, and supply the exact `SnapshotSet` to `RevisionBarrier.check(...)`. With one current Host revision changed, assert failure occurs before provider execution snapshot/binding I/O. Same revisions must reach the next boundary.

Do not compare revisions in the adapter; adapter only resolves the owner input and invokes `RevisionBarrier`.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/orchestrator/test_canonical_owner_ports.py -k "revision_barrier" -q
```

Expected at Task 6R close: fail-closed `CANONICAL_OWNER_PORT_NOT_WIRED` at `check_revision_barrier`.

- [ ] **Step 3: Implement real revision-barrier request assembly**

Use existing typed owner stores/registries and the real Semantic Runtime `RevisionBarrier`; do not create adapter-private `plan -> snapshot_set` lineage maps. If `ExecutionPlanV2`/ChangeSet public contracts do not contain enough authoritative lineage to resolve the SnapshotSet, stop and return to Design/Plan rather than guessing.

- [ ] **Step 4: Write Provider Binding/grant RED**

Boundary-supplied `ProviderExecutionSnapshotV2` enters real `resolve_provider_bindings_v2()`. Real Gateway V2 then issues/admit execution grant. Assert exact slice/materialization/ChangeSet/scope hashes are preserved and provider mismatch prevents Host execution.

- [ ] **Step 5: Implement minimum wiring and run GREEN**

```bash
uv run pytest tests/orchestrator/test_canonical_owner_ports.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_ports.py
```

- [ ] **Step 6: Commit**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_ports.py
git commit -m "feat: wire real revision binding and grant owners"
```

---

### Task 8: Wire real Saga V2 / materialized coordination / reconciliation

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Create: `tests/orchestrator/test_canonical_owner_execution.py`

**Required real services:**

```text
ExecutionReconciliationServiceV2
MaterializedExecutionSagaCoordinator
CrossHostConvergenceVerifier
ExecutionSagaStoreV2 public factory/contract
existing durable dispatch-intent/recovery surface where required
```

Allowed deterministic doubles are limited to Host readiness observation, Host execute/read-back, verification/convergence evidence IO, and clock. They may return public contracts but cannot implement Saga/reconciliation semantics.

- [ ] **Step 1: Write successful execution RED**

Use real coordinator/reconciliation/convergence and a counting Host port. Assert terminal owner truth is `SUCCEEDED`, and workflow projection maps it without reimplementing terminal classification.

- [ ] **Step 2: Write DIVERGED RED**

Inject divergent canonical evidence through the evidence boundary. Assert real convergence/Saga records `DIVERGED`; adapter only projects terminal state. Assert no compensation call exists.

- [ ] **Step 3: Write unknown-outcome RED**

Exercise the current public Saga/recovery semantics. Timeout/unknown cannot be mapped to “not committed” and cannot authorize blind redispatch.

- [ ] **Step 4: Implement request/wiring only and run GREEN**

```bash
uv run pytest tests/orchestrator/test_canonical_owner_execution.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_execution.py
```

- [ ] **Step 5: Commit**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_execution.py
git commit -m "feat: wire real workflow execution owners"
```

---

### Task 9: Add real-owner LangGraph E2E acceptance A–D/F/G

**Files:**
- Create: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Modify: `tests/architecture/test_real_owner_workflow_boundaries.py`
- Do not delete/rewrite `tests/orchestrator/test_workflow_end_to_end.py::_ScenarioOwners`

**Acceptance composition:**

```text
real LangGraphWorkflowRuntime
real PostgreSQL checkpointer
real PostgreSQL WorkflowArtifactStore
real OperationResolver / ParameterBinder
real FreshnessResolver / RevisionBarrier
real Impact / Approval Scope / ChangeSet
real Materialization / Execution Planning
real Gateway V2 / Provider Binding V2
real Saga / Coordination / Reconciliation / Convergence
+ explicit deterministic environment/presentation boundaries only
```

- [ ] **Step 1: Happy-path RED A**

Drive one canonical operation through HITL to terminal `WorkflowPhase.COMPLETED`. Final refs/saga id must resolve through real owner services/stores.

- [ ] **Step 2: HITL RED B**

Verify proposal pause, exact `pause_id`, stale resume rejection, and ACCEPT continuing into real-owner path without weakening predecessor HITL contract.

- [ ] **Step 3: Async RED C**

Force semantic reconstruction async wait using existing `AsyncOperationRef`. On resume, assert the Amendment A freshness tuple is newly persisted atomically and downstream Impact consumes that exact pair.

- [ ] **Step 4: Missing-ref RED D**

Remove one authoritative owner-local object after checkpoint, then resume. Assert fail closed and zero downstream owner/Host calls; do not reconstruct truth from checkpoint.

- [ ] **Step 5: Refs-only checkpoint RED F**

Inspect deserialized checkpoint through supported saver API. Assert no full authoritative domain body is persisted. Forbidden types include at least:

```text
SemanticSnapshot / SnapshotSet body
ImpactAnalysis
ApprovalScopeDefinitionV2 / ApprovalScopeBoundaryV2
CanonicalChangeSet
ApprovalRecord
ExecutionPlanV2
ProviderBindingSetV2
ExecutionGrantV2
StoredExecutionSagaV2
ActualDelta
```

StableRef mappings for `planning_snapshot_ref` / `snapshot_set_ref` are explicitly allowed.

- [ ] **Step 6: Architecture RED/GREEN G**

Run the real-owner boundary guard; the E2E module must neither import nor construct `_ScenarioOwners`, V1 surfaces, or owner-private implementation modules.

- [ ] **Step 7: Run GREEN and commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/orchestrator/test_real_owner_workflow_end_to_end.py -q
uv run pytest tests/architecture/test_real_owner_workflow_boundaries.py -q
uv run ruff check \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py

git add \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
git commit -m "test: add real-owner workflow acceptance"
```

---

### Task 10: Prove durable Saga recovery and close exact-head CI H

**Files:**
- Modify: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Inspect before any CI edit: `.github/workflows/workflow-orchestrator.yml`
- Inspect before any CI edit: `.github/workflows/durable-persistence.yml`
- Inspect before any CI edit: `.github/workflows/phase-i-real-cross-host-materialization-saga.yml`
- Inspect before any CI edit: `.github/workflows/step37-cross-host-saga-failure-injection.yml`
- Inspect before any CI edit: `.github/workflows/repository-regression.yml`
- Modify only the concrete existing workflow file whose current collection is proven not to schedule the required acceptance; if existing lanes already collect it, make no workflow change.
- No lifecycle closeout in this task.

- [ ] **Step 1: No-double-Host recovery RED E**

Use real PostgreSQL Saga/dispatch-intent persistence and a counting Host port:

```text
first runtime reaches durable dispatch/commit evidence
→ cross an existing supported runtime/process recovery point
→ create fresh workflow runtime/checkpointer/artifact store + fresh Saga service/store connection
→ resume/recover same saga
→ authoritative evidence says Host already committed/reconcilable
→ Host execute call count remains exactly 1
→ reconcile to terminal result
```

Unlike Task 6R.3, this is the place where a real durability/cross-runtime claim is made. Do not share an in-memory Saga object across runtimes.

- [ ] **Step 2: Preserve fast scenario regression**

Run existing `tests/orchestrator/test_workflow_end_to_end.py`; `_ScenarioOwners` remains legal only there.

- [ ] **Step 3: PostgreSQL capability gate**

Before editing CI, inspect the five workflow files listed above and record which exact job currently owns Workflow Orchestrator PostgreSQL and durable Saga/dispatch-intent coverage.

Run:

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/orchestrator/test_artifact_postgres.py \
  -q
```

Also run the exact current PostgreSQL checkpoint and durable Saga/dispatch-intent test files referenced by `workflow-orchestrator.yml`, `durable-persistence.yml`, `phase-i-real-cross-host-materialization-saga.yml`, and `step37-cross-host-saga-failure-injection.yml`. If the workflow references reveal different concrete test paths than the historical Plan, update this Plan before using those paths as closure evidence.

- [ ] **Step 4: Repository exact-head regressions**

Require the repository’s canonical exact-head CI jobs for the final SHA, including:

```text
Python 3.11 canonical pytest modes
Python 3.14 repository regression
Ruff: new diagnostics = 0
Workflow Orchestrator PostgreSQL
Durable Persistence / Execution Saga PostgreSQL
canonical V2 architecture guards
existing scenario orchestration regression
.NET 10
Revit Core
```

- [ ] **Step 5: Scope audit**

Compare final implementation branch against the approved amendment base and reject unrelated changes in:

```text
MCP front door
real AutoCAD/Revit acceptance
compensation executor
V1 retirement
new outbox/inbox protocol
owner-wide PostgreSQL migration
unrelated dependency upgrade
support-matrix expansion
```

- [ ] **Step 6: Final implementation commit / PR evidence**

If Task 10 requires source/test/CI changes, commit only the exact Task 10 files. Then push the exact implementation HEAD and require exact-head GREEN before merge.

---

## Acceptance Matrix

| Design acceptance | Plan evidence |
| --- | --- |
| Amendment A exact operation freshness lineage | Task 6R.1–6R.3 |
| Interleaved rev42/rev43 isolation | Task 6R.2 |
| Four pre-Impact mismatch categories | Task 6R.2 |
| Atomic success tuple + stale-pair prevention | Task 6R.1 / Task 6R.3 |
| Saver-backed serialized checkpoint recovery | Task 6R.3 |
| Rebuilt adapter does not depend on private lineage | Task 6R.3 |
| No reverse-lookup success path | Task 6R.2 architecture guard |
| Task 7 Step 1/2 retained | Task 6R.4 compatibility gate |
| A. happy path reaches `COMPLETED` | Task 9 |
| B. HITL pause/resume intact | Task 9 |
| C. async wait/re-entry | Task 6R.1 + Task 9 |
| D. missing authoritative ref fails closed | Task 9 |
| E. durable Saga recovery does not execute Host twice | Task 10 |
| F. checkpoint refs/navigation only | Task 6R.3 + Task 9 |
| G. no V1/scenario fake in production composition | Task 6R.2 + Task 9 architecture guard |
| H. PostgreSQL + repository regression green | Task 10 |

---

## Boundary-Double Register

The real-owner acceptance may use deterministic doubles only for these explicit boundaries:

| Boundary | Why permitted | Forbidden behavior |
| --- | --- | --- |
| Semantic reconstruction IO | external/Host-derived observation | cannot implement freshness policy; returns public reconstruction/read-model results only |
| Current Host revision observation | environment observation for RevisionBarrier | cannot decide pass/fail; returns revision only |
| Preview | presentation artifact | cannot modify ChangeSet/approval authority |
| Human/policy admission input | external decision evidence | cannot create ApprovalRecord/grant; Gateway V2 consumes it |
| Runtime routing | environment/runtime discovery | cannot implement planning semantics |
| Provider execution snapshot/native identity | provider environment evidence | cannot select provider; Provider Binding V2 does selection |
| Host readiness | external Host observation | cannot mutate Saga truth |
| Host execute/read-back | external mutation boundary | cannot classify reconciliation/DIVERGED |
| Verification/convergence evidence IO | environment evidence acquisition | cannot evaluate scope/semantic/convergence rules |
| Clock | deterministic audit time | cannot change identity/business outcome beyond public timestamp contract |

No other repository-internal authoritative owner may be replaced by a test fake in the real-owner E2E.

---

## Failure Semantics

Implementation must preserve these fail-closed boundaries:

```text
missing owner ref
  -> workflow-facing authoritative-ref unavailable error

StableRef id/hash mismatch
  -> fail before downstream owner call

snapshot/set membership mismatch
  -> fail before Impact

document/environment mismatch
  -> fail before Impact

freshness contract != current bound operation
  -> fail before Impact

partial/stale freshness tuple
  -> graph cannot enter Impact successfully

semantic revision changed
  -> RevisionChangedError / existing REVISION_CONFLICT mapping

Gateway V2 rejection
  -> preserve Gateway stable error semantics

provider snapshot/binding mismatch
  -> ProviderBindingError; no Host execution

Saga unknown outcome
  -> remain UNKNOWN/recovery; never assume not committed

DIVERGED
  -> terminal observable failure; no auto compensation

missing non-durable owner state after fresh process
  -> fail closed; do not claim durability from rebuilt-adapter test
```

Error translation in `CanonicalWorkflowOwnerPorts` may map owner errors to the existing workflow-facing vocabulary, but it cannot hide which frozen boundary failed or convert data-integrity failures into retryable success.

---

## Amendment A Final Plan Gate

This revised Plan becomes the implementation authority for the reopened Task 6 only after written-plan review approval.

Before approval:

```text
Task 6R production code changes FORBIDDEN
Task 7 Step 3 implementation FORBIDDEN
follow-on provider/grant expansion FORBIDDEN
```

After approval, execute strictly:

```text
Task 6R.1 contract + graph atomicity RED/GREEN
→ Task 6R.2 interleaved lineage + mismatch RED/GREEN
→ Task 6R.3 saver round-trip + rebuilt-adapter proof
→ Task 6R.4 focused regression + exact-head CI
→ Task 6 repair CLOSED
→ Task 7 Step 3–5
→ Task 8
→ Task 9
→ Task 10
→ implementation exact-head GREEN
→ merge
→ merged-main observation GREEN
→ docs-only lifecycle closeout
→ real E2E workflow COMPLETED
```

Any evidence that the approved exact refs cannot be reconstructed through existing owner public APIs is a **STOP / Design-Plan amendment** condition. Do not reintroduce latest/current lookup, delete immutable history, create hidden adapter maps, or silently broaden the public checkpoint contract to get a GREEN test.
