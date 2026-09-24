# Task 9 Parameter Binding Context Lineage Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 Task 9 real-owner E2E 暴露的参数绑定 lineage 断点：把 graph 已持久化的 exact `context_snapshot_ref` 显式传入 ParameterBinder read-model 边界，使 `BoundOperationProposal.context_snapshot_ref` 必须来自 authoritative ContextSnapshot，而不是 operation-space artifact identity 或 process-local cache。

**Architecture:** 设计不变，仍遵守 ADR-010 的 refs-only checkpoint 与 owner-local truth。只迁移 `WorkflowServices.bind_parameters`、`ExternalOwnerPorts.load_parameter_binding_inputs` 与 `SemanticReconstructionPort.load_parameter_binding_inputs` 的参数形状；LangGraph `parameter_binding` 节点从现有 state 读取 `operation_ref + context_snapshot_ref` 并同时转发。`CanonicalWorkflowOwnerPorts` 只做显式 ref forwarding，不新增 map、reverse lookup、snapshot recomputation 或新 owner。

**Tech Stack:** Python 3.11/3.14, LangGraph 1.2.x, pytest, Ruff, PostgreSQL 17 acceptance.

**Spec:** `docs/superpowers/specs/2026-09-20-real-owner-e2e-workflow-design.md`

## Global Constraints

- 不重开或修改 approved Design；本 amendment 只修 implementation seam。
- ContextSnapshot authoritative identity 必须来自 workflow 已持久化的 `StableRef`，不得从 operation-space artifact 推断。
- 禁止在 `CanonicalWorkflowOwnerPorts`、boundary double 或 service adapter 中新增 process-local lineage map/cache。
- 禁止通过 snapshot registry reverse lookup 找“最近/匹配的” ContextSnapshot。
- 禁止重新执行 FreshnessResolver 或重算 snapshot identity 来补丢失 lineage。
- Graph topology、HITL correlation、operation freshness、Impact、ChangeSet 与 execution owner 语义保持不变。
- 先观察 focused RED，再写最小 GREEN；Task 9A PostgreSQL acceptance 必须在修复后重新执行。

## Review Focus

- 同一 operation-space ref 与不同 ContextSnapshot ref 组合时，binder 必须使用调用方显式给出的 ContextSnapshot ref。
- async/restart 后 `context_snapshot_ref` 必须来自 saver state，而不是进程内对象。
- legacy `_ScenarioOwners` 只做签名迁移，不改变其 fast-regression 语义。
- 缺失 `context_snapshot_ref` 必须在 graph `_require_stable_ref` 处 fail closed。
- `CanonicalWorkflowOwnerPorts` 不得新增 snapshot registry selector、私有 dict 或 hidden lineage state。

---

### Task 1: Freeze exact ContextSnapshot forwarding with focused RED

**Files:**
- Modify: `tests/orchestrator/test_langgraph_graph.py`
- Modify: `tests/orchestrator/test_default_workflow_services.py`

**Interfaces:**
- Consumes current `WorkflowGraphState.context_snapshot_ref` and operation-space `operation_ref`.
- Proves future signature `bind_parameters(operation_ref: StableRef, context_snapshot_ref: StableRef)` and owner read-model call `load_parameter_binding_inputs(operation_space_ref, context_snapshot_ref)`.

- [ ] **Step 1: Add graph RED**

Add a service double that records both refs and assert the `parameter_binding` node forwards the exact persisted ContextSnapshot ref alongside the operation-space ref.

- [ ] **Step 2: Add service RED**

Assert `DefaultWorkflowServices.bind_parameters(operation_space_ref, context_snapshot_ref)` calls the external owner with the same two refs and does not derive or replace the context ref.

- [ ] **Step 3: Run RED**

```bash
uv run pytest \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_default_workflow_services.py \
  -k "parameter_binding and context" -q
```

Expected: fail because current graph/service signatures forward only `operation_ref`.

- [ ] **Step 4: Commit RED**

```bash
git add \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_default_workflow_services.py
git commit -m "test: require explicit parameter binding context lineage"
```

---

### Task 2: Migrate the explicit ref seam with minimal GREEN

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/default_workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify only required test/service doubles that implement the migrated structural seam.

**Interfaces:**
- Produces `WorkflowServices.bind_parameters(operation_ref, context_snapshot_ref)`.
- Produces `ExternalOwnerPorts.load_parameter_binding_inputs(operation_space_ref, context_snapshot_ref)`.
- Produces `SemanticReconstructionPort.load_parameter_binding_inputs(operation_space_ref, context_snapshot_ref)`.

- [ ] **Step 1: Change protocol signatures only**

Add `context_snapshot_ref: StableRef` as the second positional argument on all three interfaces. Do not add optional defaults; missing lineage must fail closed.

- [ ] **Step 2: Forward graph state explicitly**

`parameter_binding()` must call:

```python
services.bind_parameters(
    _require_stable_ref(state, "operation_ref"),
    _require_stable_ref(state, "context_snapshot_ref"),
)
```

No topology or phase changes.

- [ ] **Step 3: Forward through default services and canonical adapter**

`DefaultWorkflowServices.bind_parameters()` passes both refs unchanged to `load_parameter_binding_inputs()`. `CanonicalWorkflowOwnerPorts.load_parameter_binding_inputs()` passes both refs unchanged to `SemanticReconstructionPort`; it must not inspect snapshot registry to discover lineage.

- [ ] **Step 4: Migrate structural doubles**

Update only test doubles/fixtures whose method signatures implement these seams. Existing deterministic test behavior may remain unchanged except where the new exact context ref should be asserted.

- [ ] **Step 5: Run focused GREEN**

```bash
uv run pytest \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/orchestrator/test_workflow_end_to_end.py \
  -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/workflow_services.py \
  platform/orchestrator/src/design_orchestrator/default_workflow_services.py \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator
```

- [ ] **Step 6: Commit GREEN**

```bash
git add platform/orchestrator/src/design_orchestrator tests/orchestrator
git commit -m "fix: carry parameter binding context lineage"
```

---

### Task 3: Re-prove Task 9A on the real PostgreSQL workflow

**Files:**
- Modify only if fixture signature migration is required: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Inspect: `.github/workflows/workflow-orchestrator.yml`

- [ ] **Step 1: Remove the Task 9 test-side lineage substitution**

The real-owner `_SemanticBoundary.load_parameter_binding_inputs()` must consume the passed `context_snapshot_ref` directly. It must not use `operation_space_ref.ref_id` as `ParameterBindingContext.context_snapshot_id`, maintain a cached latest context ref, or recompute SemanticSnapshot identity.

- [ ] **Step 2: Run exact Task 9A PostgreSQL acceptance**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest \
    tests/orchestrator/test_real_owner_workflow_end_to_end.py::test_real_owner_happy_path_reaches_completed_and_resolves_final_refs \
    -q
```

Expected after seam repair: the prior `SNAPSHOT_REFERENCE_NOT_FOUND` lineage failure is gone. Any new failure must be classified before further implementation.

- [ ] **Step 3: Static and scope verification**

```bash
uv run ruff check \
  platform/orchestrator/src/design_orchestrator \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py
git diff --check
```

Require no new owner-local map/reverse-selector pattern in `canonical_owner_ports.py` and no `_ScenarioOwners` import in the real-owner acceptance.

- [ ] **Step 4: Commit any fixture-only migration separately**

```bash
git add tests/orchestrator/test_real_owner_workflow_end_to_end.py
git commit -m "test: consume explicit context lineage in real owner e2e"
```

Then return to Task 9 B/C/D/F/G in `2026-09-23-task8-execution-owner-lookup-amendment.md`.

## Self-Review

- **Spec coverage:** This amendment implements the already-approved restart-safe exact-owner-ref requirement and changes no owner/domain semantics.
- **Placeholder scan:** No TBD/TODO or unspecified implementation steps remain.
- **Type consistency:** All three migrated signatures use the same required `StableRef` second argument.
- **Review Focus:** Focused tests cover graph forwarding, service forwarding, structural seam migration, restart-safe explicit identity, and prohibition on inferred/cached lineage.
