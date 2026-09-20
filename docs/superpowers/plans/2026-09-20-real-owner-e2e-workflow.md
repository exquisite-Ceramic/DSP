# Capability Phase — Real-Owner E2E Workflow Implementation Plan

**Status:** Proposed — written-plan review pending  
**Date:** 2026-09-20  
**Base:** `main@f5ffd4633fbb28c2a54bbc4417df805fac9c2d6c`  
**Design:** `docs/superpowers/specs/2026-09-20-real-owner-e2e-workflow-design.md`  
**Workflow authority:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`  
**Persistence authority:** `docs/adr/ADR-008-durable-state-persistence-ownership.md`  
**Delivery authority:** `docs/adr/ADR-009-cross-owner-delivery-crash-recovery.md`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Every production-code task is TDD RED → GREEN → exact-head verification → commit. Do not collapse gates.

## Goal

把已经通过 HITL pause/resume 的 LangGraph workflow 从 test-side `_ScenarioOwners` composition 提升为可复用的 production/reference **real-owner composition**：

```text
LangGraphWorkflowRuntime
  → DefaultWorkflowServices
    → CanonicalWorkflowOwnerPorts
      → real Semantic Runtime freshness / revision authority
      → real Impact
      → real Approval Scope V2
      → real ChangeSet V2
      → real Materialization Planning / Topology
      → real Execution Planning V2
      → real Gateway V2
      → real Provider Binding V2
      → real Execution Saga V2 / coordination
      → real Reconciliation V2 / convergence
```

只有真实的 environment / IO / presentation boundary 可以保留窄、确定性的 test ports。完成标准不是“把 scenario fake 写得更像 production”，而是 `CanonicalWorkflowOwnerPorts` 真正调用 repository owner public APIs，workflow checkpoint 继续只保存 refs/navigation，owner ref 无法解析时 fail closed，并用真实 durable Saga 路径证明 recovery 不会重复 Host execution。

## Architecture

`WorkflowServices`、`DefaultWorkflowServices` 与现有 LangGraph topology 保持不变。新 adapter 实现现有 `ExternalOwnerPorts` structural protocol；Operation Resolver 与 Parameter Binder 继续由 `DefaultWorkflowServices` 直接拥有，不再包装一层。

`CanonicalWorkflowOwnerPorts` 只做：

```text
request assembly
StableRef ↔ owner-local identity/hash conversion
owner-local object resolution
read-model projection
cross-owner dependency wiring
workflow-facing error translation
```

它不得实现：approval policy、ChangeSet semantics、revision comparison policy、provider selection policy、grant authorization、Saga transition、unknown-outcome、reconciliation、DIVERGED、compensation 或 Host commit truth。

Owner object body 不得复制进 workflow checkpoint，也不得进入 adapter-owned generic truth cache。若某个 owner 当前缺少可解析的 reference surface，本计划只允许增加 **owner-local typed repository/registry surface**；不允许在 orchestrator 内建立一个跨 owner `dict[str, object]` 作为第二 truth。

## Tech Stack

Python 3.11 / 3.14、LangGraph 1.2.x、`langgraph-checkpoint-postgres` 3.x、PostgreSQL 17、pytest、Ruff、GitHub Actions；保持现有 .NET 10 / Revit Core repository regression。版本以实施时 lockfile / exact-head CI 为准，本计划不借 capability phase 做依赖升级。

---

## Global Constraints

- `Workflow Orchestrator` 仍是 workflow progression / checkpoint / HITL / wait-reentry logical owner；LangGraph 只是 reference runtime。
- `CanonicalWorkflowOwnerPorts` **MUST implement the existing `ExternalOwnerPorts` shape**；不得修改 graph node ownership 来适配 adapter。
- `DefaultWorkflowServices` 继续直接使用真实 `OperationResolver` 与 `ParameterBinder`。
- workflow checkpoint 只保存 stable refs、navigation、pending interaction / async operation metadata；禁止保存完整 `ImpactAnalysis`、Approval Scope、`CanonicalChangeSet`、`ApprovalRecord`、`ExecutionPlanV2`、`ProviderBindingSetV2`、`ExecutionGrantV2`、Saga state、ActualDelta。
- authoritative owner output 必须由 owner-local repository/registry/service 解析；adapter 只能持有依赖引用，不能变成 owner store。
- 不要求本阶段把所有 owner 迁 PostgreSQL。process-local owner ref 在 fresh process 无法解析时必须 fail closed；不得从 checkpoint 重建 truth。
- Existing durable Workflow Orchestrator checkpoint/artifact PostgreSQL path 与 Execution Saga PostgreSQL path 必须用于 acceptance。
- Preview 仍是 presentation boundary；test preview port 可以是 deterministic double，但不能产出第二份 ChangeSet truth。
- Human/policy admission、semantic reconstruction IO、current Host revision observation、provider runtime snapshot、Host readiness/execute/read-back 与 presentation preview 是允许的 narrow boundary ports；这些 doubles 不得重写 domain semantics。
- `_ScenarioOwners` 保留在 fast orchestration regression；real-owner acceptance 不能 import、construct、subclass 或 delegate 到它。
- V1 consumer surfaces 禁止重新进入 production/reference adapter。
- owner-private modules（例如 `*_v2.py`、`postgres_*`、`saga_transitions_v2.py` 等实现文件）不是 adapter dependency contract；adapter 只依赖 approved package public exports。
- 不新增 outbox/inbox owner，不重做 replay protocol，不扩张 ADR-009 owner-wide crash matrix。
- `DIVERGED` 只作为 terminal observable truth；本阶段不做自动 compensation，CV2-008 保持 blocked。
- 不实现 MCP/Agent front door，不执行 real AutoCAD/Revit acceptance，不把本 capability 宣称为完整 semantic product scenario。
- 所有新增 Python 代码必须保留完整中文注释/文档字符串，并遵守当前 Ruff/typing 风格。

---

## Exact-Head Census Freeze

本 Plan 的 owner/public-API census 基于：

```text
main@f5ffd4633fbb28c2a54bbc4417df805fac9c2d6c
```

以下表格是 implementation dependency freeze。实施 Task 1 必须把它变成 machine-readable census；若 exact implementation branch 的 main baseline 已变化，先做 compare，任何 surface contradiction 都停止实现并回到 Plan amendment。

| Area | Approved public surface / fact | Decision |
| --- | --- | --- |
| Orchestrator service seam | `design_orchestrator.default_workflow_services.ExternalOwnerPorts` | `CanonicalWorkflowOwnerPorts` 实现现有 seam；不改 graph contract |
| Orchestrator deterministic services | `OperationResolver`, `ParameterBinder`, `DefaultWorkflowServices` | 继续真实使用；不重复包装 |
| Semantic freshness | `semantic_runtime.FreshnessResolver`, `build_context_contract`, `build_operation_contract`, `SemanticSnapshot`, `SnapshotSet` | real-owner path 使用真实 freshness semantics；reconstructor 是 environment boundary |
| Revision authority | `SemanticSnapshot.base_host_revision`; `FreshnessResolver.resolve(... expected_host_revision=...)`; `RevisionChangedError` | 不新增 canonical revision 字段；在 Semantic Runtime owner 暴露 revision-barrier public API，current revision observation 为窄环境 port |
| Impact | `design_impact.ImpactAnalyzer`, `ImpactAnalysisRequest`, `ImpactAnalysis` | 使用 package public surface |
| Approval Scope | `ApprovalScopePlanner`, `ApprovalScopePlanRequest`, `ApprovalScopeDefinitionV2`, `ApprovalScopeBoundaryV2`, `bind_changeset_v2`, `bind_topology_snapshot_v2`, V2 validators | ChangeSet V2 的真实支撑 authority；不是新 graph node |
| ChangeSet | package-root canonical `ChangeSetBuilder`, `ChangeSetBuildRequest`, `CanonicalChangeSet`, `validate_changeset_integrity_v2` | 不 import `builder_v2.py` |
| Materialization Topology | `MaterializationTopologyRegistry`, `MaterializationTopologySnapshot`, public hash/validator | registry 是 real owner surface；topology revision != Host document revision |
| Materialization Planning | `MaterializationPlanner`, `MaterializationPlanningRequest`, `MaterializationPlan` | real deterministic owner |
| Execution Planning | `ExecutionPlanningRequestV2`, `ExecutionPlanV2`, `ExecutionSliceV2`, `MaterializationRoutingEvidence`, `plan_materialized_execution`, V2 validator | package root 同时有 legacy/V2，guard 做 symbol whitelist |
| Gateway | `GatewayAuthorizationServiceV2`, `ApprovalConsumptionRequestV2`, `ExecutionGrantRequestV2`, `ExecutionGrantV2`, `AdmittedExecutionAuthorityV2`, V2 store contracts | package root 同时有 V1/V2，adapter 只允许 V2 symbols |
| Provider Binding | `ProviderExecutionSnapshotV2`, `ProviderBindingSetV2`, `resolve_provider_bindings_v2`, V2 validators | provider runtime snapshot 是 environment/provider boundary；selection semantics 仍由 owner function |
| Reconciliation / Saga | `ExecutionReconciliationServiceV2`, `ExecutionSagaStoreV2`, `create_execution_saga_store_v2`, `ExecutionSagaStatusV2`, V2 public contracts | PostgreSQL store 通过 public factory / injected store；adapter 禁止 import `postgres_*` internals |
| Coordination | `MaterializedExecutionSagaCoordinator`, public readiness/Host/evidence ports | real coordinator；Host/readiness/evidence 可 deterministic boundary double |
| Convergence | `CrossHostConvergenceVerifier`, `ConvergenceComparisonProfile`, public evidence builders | real convergence semantics |
| Scenario fake | `tests/orchestrator/test_workflow_end_to_end.py::_ScenarioOwners` | fast regression only；real-owner path machine-forbidden |
| Architecture precedent | `tests/architecture/test_canonical_v2_boundaries.py` AST `module:symbol` checks | 新 guard 复用同一 machine-enforced style |
| Existing durable workflow | PostgreSQL checkpointer + PostgreSQL `WorkflowArtifactStore` | real-owner E2E 必须使用 |
| Existing durable Saga | Execution Saga V2 PostgreSQL + durable dispatch-intent recovery | no-double-Host acceptance 必须使用 |

### Missing public/reference surfaces frozen by census

Exact HEAD 还缺以下可直接供 production/reference composition 使用的 surface：

1. Semantic Runtime 没有独立公开的 `RevisionBarrier` service；现有 authority 足够（`SemanticSnapshot.base_host_revision`），因此补 public API，不补新领域字段。
2. Impact / Approval Scope / ChangeSet / Materialization Planning / Execution Planning / Provider Binding 主要暴露纯 deterministic builder/value API，没有统一的 owner-local ref resolution surface；workflow 却跨 node 只传 `StableRef`。因此需要最小 typed repository/registry contract，且 store 归各自 owner，不归 orchestrator。
3. `platform/orchestrator/pyproject.toml` 没有声明这些 source-tree owners 为 distribution dependency；root repository test 通过 `pythonpath` 暴露它们。实施必须增加 import smoke / packaging evidence，但不得顺带把整个 repository 做 packaging modernization。只有 exact smoke 证明 reference composition 无法被正常导入时，才允许最小 capability prerequisite packaging change。

---

## Execution Topology

当前 branch `architecture/real-owner-e2e-workflow-plan` 是 **artifact-only planning branch**。在 written-plan review 通过前，不得写 production implementation。

批准后的流程冻结为：

```text
freeze approved Implementation Plan
→ docs/architecture PR: architecture/real-owner-e2e-workflow-plan -> main
→ merge exact approved plan head
→ verify merged-main SHA
→ create feat/capability-real-owner-e2e-workflow from merged main
→ Tasks 1–10, each RED → GREEN → exact-head evidence → commit
→ implementation PR -> main
→ exact-head CI + review
→ merge exact implementation head
→ merged-main observation
→ docs-only lifecycle closeout
→ mark real E2E workflow COMPLETED
→ successor semantic -> plan -> approve -> execute -> reconcile remains NOT STARTED until its own gate
```

如果 Task 1 exact census、Task 2 revision authority、或任意后续 RED evidence 证明 approved Design Spec 的 owner assumption 错误：

```text
STOP implementation
→ document contradiction
→ return to Design/Plan amendment
```

不得在 implementation PR 中偷偷改变 ownership。

---

## Review Focus

1. **ExternalOwnerPorts preserved:** adapter 实现现有 seam，不通过扩展 graph protocol 绕开真实 owner wiring。
2. **Revision authority:** barrier 必须比较 `SemanticSnapshot.base_host_revision` 与 authoritative current revision observation；不得把 topology revision、checkpoint phase 或 provider timestamp 当 Host revision。
3. **StableRef resolution:** owner-local typed repositories 保存/读取 owner truth；adapter 不持有 generic object cache。
4. **Canonical/V2 only:** package root 同时暴露 V1/V2 的 package 必须 symbol-whitelist；不得只做 `module.startswith(...)` 粗粒度放行。
5. **No fake laundering:** `_ScenarioOwners` 与 tests support 不得被 production adapter import；允许的 test double 必须位于真正的 IO/environment/presentation seam。
6. **Real durable recovery:** Orchestrator checkpoint/artifact 与 Execution Saga/dispatch recovery 用真实 PostgreSQL；fresh process 对非 durable owner ref 无法解析时 fail closed。
7. **No duplicate Host call:** unknown-outcome/recovery acceptance 证明 durable evidence 已足够时不会再次执行 Host。
8. **No scope creep:** 不引入 compensation executor、MCP front door、real Host acceptance、owner-wide database migration 或 ADR-009 redesign。

---

### Task 1: Freeze machine-readable real-owner census and public-surface allowlist

**Files:**
- Create: `docs/superpowers/reviews/2026-09-20-real-owner-e2e-workflow-census.md`
- Create: `tests/architecture/test_real_owner_e2e_census.py`

**Purpose:** 把本 Plan 的 exact-head census 变成 machine-enforced implementation input，避免后续 task 用猜测的 module/symbol。

- [ ] **Step 1: Write RED census coverage test**

要求 census 至少覆盖：

```text
orchestrator_seam
semantic_freshness
revision_authority
impact
approval_scope_v2
changeset_v2
materialization_topology
materialization_planning
execution_planning_v2
gateway_v2
provider_binding_v2
saga_v2
coordination
reconciliation_v2
convergence
owner_ref_surfaces
scenario_fake_boundary
import_time_dependencies
```

Test 解析表格并拒绝 `TODO/TBD/UNKNOWN`。

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/architecture/test_real_owner_e2e_census.py -q
```

Expected: FAIL because census document is absent.

- [ ] **Step 3: Re-run exact implementation-branch census**

Use exact commands equivalent to:

```bash
rg -n "class ExternalOwnerPorts|class DefaultWorkflowServices|class WorkflowServices" platform/orchestrator
rg -n "FreshnessResolver|SemanticSnapshot|base_host_revision|RevisionChangedError" platform/semantic_runtime
rg -n "ImpactAnalyzer|ApprovalScopePlanner|ChangeSetBuilder|plan_materialized_execution" platform
rg -n "GatewayAuthorizationServiceV2|resolve_provider_bindings_v2" platform
rg -n "ExecutionReconciliationServiceV2|MaterializedExecutionSagaCoordinator" platform
rg -n "_ScenarioOwners" tests platform
rg -n "postgres_|saga_transitions_v2|builder_v2|/v2.py" platform/orchestrator platform/*/src
```

Census 每个 owner 记录：approved package-root exports、legacy symbols to forbid、private implementation modules、current store/ref surface、import-time optional dependency。

- [ ] **Step 4: Freeze machine-readable allowlist**

Census 必须包含 `module:symbol` 形式 allowlist；Gateway / Execution Planning / Provider Binding / Reconciliation 不能只写 module name，因为 package root 同时公开 legacy 与 V2。

- [ ] **Step 5: GREEN + commit**

```bash
uv run pytest tests/architecture/test_real_owner_e2e_census.py -q
uv run ruff check tests/architecture/test_real_owner_e2e_census.py

git add docs/superpowers/reviews/2026-09-20-real-owner-e2e-workflow-census.md \
  tests/architecture/test_real_owner_e2e_census.py
git commit -m "docs: freeze real-owner workflow census"
```

**Stop gate:** any contradiction with the approved Design Spec stops before Task 2.

---

### Task 2: Expose Semantic Runtime revision-barrier authority without inventing revision truth

**Files:**
- Create: `platform/semantic_runtime/src/semantic_runtime/revision_barrier.py`
- Modify: `platform/semantic_runtime/src/semantic_runtime/__init__.py`
- Create: `tests/semantic_runtime/test_revision_barrier.py`

**Interfaces:**

```python
class HostRevisionObservationPort(Protocol):
    def current_revision(self, document_ref: str) -> str: ...


class RevisionBarrier:
    def __init__(self, revisions: HostRevisionObservationPort) -> None: ...
    def check(self, snapshot_set: SnapshotSet) -> None: ...
```

The owner must reuse existing `RevisionChangedError` / stable `REVISION_CONFLICT` mapping policy at the workflow boundary. The authoritative expected value is each `SemanticSnapshot.base_host_revision` in the exact planning `SnapshotSet`.

- [ ] **Step 1: RED tests**

Cover:

```text
same document revision       -> pass
one changed revision         -> RevisionChangedError
missing/empty observation    -> fail closed
multiple documents           -> every planning snapshot checked
context snapshot substituted -> reject; SnapshotSet contains planning snapshots only
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/semantic_runtime/test_revision_barrier.py -q
```

- [ ] **Step 3: Implement owner service**

Rules:

```text
expected revision = SemanticSnapshot.base_host_revision
current revision  = HostRevisionObservationPort.current_revision(document_ref)
expected != current -> RevisionChangedError
```

Do not read topology revision. Do not infer revision from checkpoint or provider snapshot. Do not import AutoCAD/Revit code.

- [ ] **Step 4: Public export + GREEN**

```bash
uv run pytest tests/semantic_runtime/test_revision_barrier.py -q
uv run ruff check \
  platform/semantic_runtime/src/semantic_runtime/revision_barrier.py \
  tests/semantic_runtime/test_revision_barrier.py

git add platform/semantic_runtime/src/semantic_runtime/revision_barrier.py \
  platform/semantic_runtime/src/semantic_runtime/__init__.py \
  tests/semantic_runtime/test_revision_barrier.py
git commit -m "feat: expose semantic revision barrier"
```

---

### Task 3: Add owner-local immutable reference repositories required by workflow StableRefs

**Files:**
- Create: `platform/semantic_runtime/src/semantic_runtime/snapshot_registry.py`
- Create: `platform/impact/src/design_impact/store.py`
- Create: `platform/approval_scope/src/design_approval_scope/store.py`
- Create: `platform/changeset/src/design_changeset/store.py`
- Create: `platform/materialization_planning/src/design_materialization_planning/store.py`
- Create: `platform/execution_planning/src/design_execution_planning/store_v2.py`
- Create: `platform/provider_binding/src/design_provider_binding/store_v2.py`
- Modify corresponding package `__init__.py` files
- Create: `tests/orchestrator/test_real_owner_reference_resolution.py`

**Purpose:** workflow node boundaries use `StableRef`, while these owners currently primarily expose deterministic value APIs. Add the minimum owner-owned lookup surface; do not add owner-wide PostgreSQL migration.

**Repository rule:** each store validates the object’s own stable identity/hash on `put()` and again on `get()` where a public validator/hash function exists. Same identity + same content is replay-safe; same identity + different content is conflict/fail closed.

Suggested owner-specific identity mapping:

```text
SemanticSnapshot      -> snapshot_id / hash
SnapshotSet           -> snapshot_set_id / hash
ImpactAnalysis        -> analysis_id / analysis_fingerprint
ApprovalScope V2      -> owner-defined id / scope hash
CanonicalChangeSet    -> changeset_id / changeset_hash
MaterializationPlan   -> owner-defined plan id/hash
ExecutionPlanV2       -> execution_plan_id / execution_plan_hash
ProviderBindingSetV2  -> binding_set_id / binding_set_hash
```

Do not make these packages depend on `design_orchestrator.StableRef`. Adapter converts owner identity/hash to `StableRef`.

- [ ] **Step 1: RED replay/conflict/not-found tests**

For each store category prove:

```text
put -> get exact object
same identity + same content -> idempotent
same identity + different hash/body -> owner-specific conflict
unknown identity -> owner-specific not-found
```

The test must also assert there is no single cross-owner `dict[str, object]` repository in orchestrator.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/orchestrator/test_real_owner_reference_resolution.py -q
```

- [ ] **Step 3: Implement minimal in-memory reference implementations**

These are current reference owner stores, not durable guarantees. Do not introduce SQL/migrations in this task.

- [ ] **Step 4: Public exports + GREEN**

```bash
uv run pytest tests/orchestrator/test_real_owner_reference_resolution.py -q
uv run ruff check \
  platform/semantic_runtime/src/semantic_runtime/snapshot_registry.py \
  platform/impact/src/design_impact/store.py \
  platform/approval_scope/src/design_approval_scope/store.py \
  platform/changeset/src/design_changeset/store.py \
  platform/materialization_planning/src/design_materialization_planning/store.py \
  platform/execution_planning/src/design_execution_planning/store_v2.py \
  platform/provider_binding/src/design_provider_binding/store_v2.py

git add platform tests/orchestrator/test_real_owner_reference_resolution.py
git commit -m "feat: add owner-local workflow reference stores"
```

**Scope guard:** adding PostgreSQL stores here requires a separate approved persistence change; it is not part of this capability.

---

### Task 4: Add `CanonicalWorkflowOwnerPorts` composition adapter skeleton

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Create: `tests/orchestrator/test_canonical_owner_ports.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py` only if a lazy public export is required

**Interfaces:** preserve the exact `ExternalOwnerPorts` structural methods. Add only narrow dependency protocols needed for environment/presentation seams, for example:

```python
class SemanticReconstructionPort(Protocol): ...
class PreviewPort(Protocol): ...
class ApprovalAdmissionPort(Protocol): ...
class MaterializationRoutingPort(Protocol): ...
class ProviderExecutionSnapshotPort(Protocol): ...
class HostRevisionObservationPort(Protocol): ...
```

Prefer reusing existing public coordination/readiness/Host/evidence protocols instead of duplicating them.

Constructor dependencies must be explicit owner services/stores/registries; no service locator and no `dict[str, object]` bag.

- [ ] **Step 1: RED structural conformance test**

Instantiate adapter with minimal deterministic dependencies and assert every `ExternalOwnerPorts` method is callable with the existing signature. Also assert `DefaultWorkflowServices(... external_owners=adapter ...)` constructs without changing `WorkflowServices`.

- [ ] **Step 2: RED import smoke**

Run a subprocess import that blocks optional database-driver import unless explicitly needed. Importing `design_orchestrator.canonical_owner_ports` must not eagerly construct PostgreSQL resources or import test modules.

```bash
uv run python -c "import design_orchestrator.canonical_owner_ports"
```

If exact packaging evidence proves a source-only owner cannot be imported in the supported repository/runtime layout, stop and make the smallest capability-prerequisite packaging change. Do not turn this into workspace modernization.

- [ ] **Step 3: Implement skeleton + error translation helpers**

At this task, methods may call narrowly injected ports/stores but must not yet contain domain rules. Keep package-root export lazy if exposing it would otherwise pull the full owner graph at `import design_orchestrator` time.

- [ ] **Step 4: GREEN + commit**

```bash
uv run pytest tests/orchestrator/test_canonical_owner_ports.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_ports.py

git add platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  platform/orchestrator/src/design_orchestrator/__init__.py \
  tests/orchestrator/test_canonical_owner_ports.py
git commit -m "feat: add canonical workflow owner ports"
```

---

### Task 5: Add semantic public-surface architecture guard for the production/reference adapter

**Files:**
- Create: `tests/architecture/test_real_owner_workflow_boundaries.py`
- Modify: `tests/architecture/test_canonical_v2_boundaries.py` only if a shared helper is clearly reusable

**Purpose:** adapter and architecture guard remain separate, independently reviewable changes.

- [ ] **Step 1: RED forbidden-consumer tests**

Using AST import inspection, enforce:

```text
ALLOW: exact census-approved package-root canonical/V2 symbols
DENY: legacy V1 symbols
DENY: owner-private implementation modules
DENY: postgres_* implementation imports from adapter
DENY: tests.*, _ScenarioOwners, test support helpers
DENY: AutoCAD/Revit Host implementation modules
```

For package roots that export both V1 and V2, compare `module:symbol` rather than module prefix.

- [ ] **Step 2: Explicit `_ScenarioOwners` negative guard**

Guard the real-owner adapter and new real-owner E2E test so neither imports nor constructs `_ScenarioOwners`.

- [ ] **Step 3: Adapter ownership guard**

AST/source guard must reject obvious duplicated semantic implementations such as local functions/classes named as Gateway/ChangeSet/Saga transition evaluators. Keep this narrow: enforce dependency boundary, not brittle filename conventions.

- [ ] **Step 4: GREEN + commit**

```bash
uv run pytest \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  tests/architecture/test_canonical_v2_boundaries.py -q
uv run ruff check tests/architecture/test_real_owner_workflow_boundaries.py

git add tests/architecture/test_real_owner_workflow_boundaries.py \
  tests/architecture/test_canonical_v2_boundaries.py
git commit -m "test: guard real-owner workflow boundaries"
```

---

### Task 6: Wire real freshness → Impact → Approval Scope V2 → ChangeSet V2

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Modify: `tests/orchestrator/test_canonical_owner_ports.py`
- Add/modify only owner tests necessary for newly exposed stores

**Required real calls:**

```text
FreshnessResolver
ImpactAnalyzer.analyze
ApprovalScopePlanner.plan
Approval Scope V2 binding/validation
ChangeSetBuilder.build
validate_changeset_integrity_v2
```

- [ ] **Step 1: RED freshness tests**

`resolve_host_context()` / `ensure_context_freshness()` / `ensure_operation_freshness()` must use real freshness contract/resolver semantics with deterministic reconstruction boundary. Resulting `SemanticSnapshot` / `SnapshotSet` goes to Semantic Runtime owner registry; workflow receives refs/read model only.

Include one async reconstruction wait/re-entry path using existing `AsyncOperationRef` contract; do not create a new workflow async model.

- [ ] **Step 2: RED impact/scope/changeset lineage test**

From a real `BoundOperationProposal`, prove:

```text
planning SnapshotSet
→ real ImpactAnalysis
→ real ApprovalScopeDefinitionV2/BoundaryV2
→ real CanonicalChangeSet
```

StableRef content hash must equal owner hash/fingerprint. A stale/missing upstream owner ref must fail closed before the next owner runs.

- [ ] **Step 3: Implement request assembly only**

Adapter may translate bound-operation evidence into public owner request contracts. It must not reproduce impact propagation, scope admission, ChangeSet hashing, or validation algorithms.

- [ ] **Step 4: GREEN + commit**

```bash
uv run pytest tests/orchestrator/test_canonical_owner_ports.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_ports.py

git add platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_ports.py
git commit -m "feat: wire real semantic and changeset owners"
```

---

### Task 7: Wire real Gateway V2 → materialization/planning → revision barrier → Provider Binding V2 → grant

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Modify: `tests/orchestrator/test_canonical_owner_ports.py`

**Required real calls:**

```text
GatewayAuthorizationServiceV2.consume_approval
MaterializationPlanner.plan
MaterializationTopologyRegistry.get
plan_materialized_execution
RevisionBarrier.check
resolve_provider_bindings_v2
GatewayAuthorizationServiceV2.issue_execution_grant
GatewayAuthorizationServiceV2.admit_execution_grant
```

Human/policy decision is supplied by narrow `ApprovalAdmissionPort`; provider runtime/native snapshot and runtime routing are supplied through explicit boundary ports. The owner services still perform all policy/selection/authorization semantics.

- [ ] **Step 1: RED approval test**

A deterministic admission fixture enters `GatewayAuthorizationServiceV2.consume_approval`; workflow receives `approval_ref`. Test must prove adapter did not synthesize `ApprovalRecord` directly.

- [ ] **Step 2: RED planning test**

Real topology + materialization planning + `plan_materialized_execution()` produces `ExecutionPlanV2`; store it in owner-local stores and return `plan_ref`.

- [ ] **Step 3: RED revision ordering test**

Set current Host revision different from one planning snapshot. `check_revision_barrier(plan_ref)` must fail before provider snapshot resolution / provider binding calls. Same revision passes.

- [ ] **Step 4: RED binding/grant test**

Real `resolve_provider_bindings_v2()` consumes boundary-supplied `ProviderExecutionSnapshotV2`. Real Gateway issues/admit grant. Assert binding/grant lineage joins exact Slice/materialization/ChangeSet/scope hashes.

- [ ] **Step 5: GREEN + commit**

```bash
uv run pytest tests/orchestrator/test_canonical_owner_ports.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_ports.py

git add platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_ports.py
git commit -m "feat: wire real planning authorization and binding"
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

Allowed deterministic doubles:

```text
Host readiness observation
Host execution/read-back port
verification/convergence evidence IO port
clock
```

These doubles may return real public contracts but may not implement Saga/reconciliation semantics.

- [ ] **Step 1: RED successful materialized execution**

Use real coordinator + reconciliation + convergence and a counting Host port. Assert terminal owner truth is `SUCCEEDED`, and workflow maps it to completion without reimplementing terminal classification.

- [ ] **Step 2: RED DIVERGED test**

Inject divergent canonical evidence through the narrow evidence boundary. Assert real convergence/Saga path records `DIVERGED`; adapter only projects terminal state. Assert no compensation call exists.

- [ ] **Step 3: RED pre-commit failure / unknown outcome mapping**

Reuse current public Saga/recovery semantics. Adapter must not classify timeout as “not committed”.

- [ ] **Step 4: GREEN + commit**

```bash
uv run pytest tests/orchestrator/test_canonical_owner_execution.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_execution.py

git add platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_execution.py
git commit -m "feat: wire real workflow execution owners"
```

---

### Task 9: Add real-owner LangGraph E2E acceptance A–D/F/G

**Files:**
- Create: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Modify: `tests/architecture/test_real_owner_workflow_boundaries.py`
- Do **not** delete or rewrite `tests/orchestrator/test_workflow_end_to_end.py::_ScenarioOwners`

**Acceptance composition:**

```text
real LangGraphWorkflowRuntime
real PostgreSQL checkpointer
real PostgreSQL WorkflowArtifactStore
real OperationResolver
real ParameterBinder
real FreshnessResolver / RevisionBarrier
real Impact / Approval Scope / ChangeSet
real Materialization / Execution Planning
real Gateway V2
real Provider Binding V2
real Saga / Coordination / Reconciliation / Convergence
+ explicit deterministic environment/presentation boundary ports only
```

- [ ] **Step 1: RED happy path A**

Drive one canonical operation through HITL to terminal `WorkflowPhase.COMPLETED`. Assert final refs/saga id resolve through real owner services/stores.

- [ ] **Step 2: RED HITL B**

Verify proposal pause, exact `pause_id`, reject stale resume, ACCEPT continues through real owners. Do not weaken predecessor HITL contract.

- [ ] **Step 3: RED async wait/re-entry C**

Force semantic reconstruction async wait via existing `AsyncOperationRef`; completion resumes into real freshness/owner path.

- [ ] **Step 4: RED missing authoritative ref D**

Remove one owner-local object after checkpoint, then resume. Assert workflow fails closed with stable workflow-facing unavailable/error semantics and does not call downstream owner/Host.

- [ ] **Step 5: RED checkpoint refs-only F**

Inspect deserialized checkpoint through supported saver API. Assert no full authoritative owner body is persisted. Exact forbidden types include at least:

```text
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

- [ ] **Step 6: No V1 + no `_ScenarioOwners` G**

Run architecture guard and additionally assert real E2E module neither imports nor constructs `_ScenarioOwners`.

- [ ] **Step 7: GREEN + commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/orchestrator/test_real_owner_workflow_end_to_end.py -q
uv run pytest tests/architecture/test_real_owner_workflow_boundaries.py -q
uv run ruff check \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py

git add tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
git commit -m "test: add real-owner workflow acceptance"
```

---

### Task 10: Prove durable Saga recovery, preserve scenario regression, and close exact-head CI H

**Files:**
- Modify: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Modify: existing PostgreSQL workflow only if required to schedule this acceptance
- Modify: `.github/workflows/...` only if the existing PostgreSQL lane does not already collect the test
- No lifecycle closeout in this task

- [ ] **Step 1: RED no-double-Host recovery E**

Use real PostgreSQL Saga/dispatch-intent persistence and a counting Host port.

Required scenario:

```text
first runtime reaches durable dispatch/commit evidence
→ simulate process/runtime boundary at an existing supported recovery point
→ create fresh workflow runtime/checkpointer/artifact store + fresh Saga service/store connection
→ resume/recover same saga
→ authoritative evidence says Host already committed/reconcilable
→ Host execute call count remains exactly 1
→ reconcile to terminal result
```

Do not prove this by sharing an in-memory Saga object across runtimes.

- [ ] **Step 2: Preserve `_ScenarioOwners` fast regression**

Run existing `tests/orchestrator/test_workflow_end_to_end.py` unchanged in purpose. `_ScenarioOwners` remains legal there.

- [ ] **Step 3: PostgreSQL capability gate**

Run at least:

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/orchestrator/test_postgres_checkpoint.py \
  tests/orchestrator/test_artifact_postgres.py \
  -q
```

And existing durable Saga / dispatch-intent PostgreSQL suites.

- [ ] **Step 4: Repository regressions**

Required final exact-head gates:

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

Use the repository’s current canonical CI commands/workflows; do not substitute a local subset for exact-head GitHub checks.

- [ ] **Step 5: Exact-head scope audit**

Compare implementation branch with its merged-plan base. Confirm only capability files/tests/necessary CI wiring changed; explicitly reject:

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

If Task 10 needed source/test changes, commit them separately:

```bash
git add <exact Task 10 files>
git commit -m "test: close real-owner workflow recovery"
```

Then push implementation branch, open implementation PR, and require exact-head GREEN before merge.

---

## Acceptance Matrix

| Design acceptance | Plan evidence |
| --- | --- |
| A. happy path reaches `COMPLETED` | Task 9 real-owner LangGraph happy path |
| B. HITL pause/resume intact | Task 9 exact `pause_id` / ACCEPT / stale replay |
| C. async wait/re-entry | Task 6 + Task 9 semantic reconstruction `AsyncOperationRef` |
| D. missing authoritative ref fails closed | Task 9 owner object removal + downstream zero-call assertion |
| E. durable Saga recovery does not execute Host twice | Task 10 PostgreSQL Saga/dispatch recovery + counting Host port |
| F. checkpoint refs/navigation only | Task 9 supported saver inspection + forbidden authoritative types |
| G. no V1 consumer reintroduced | Task 5 symbol-level architecture guard + Task 9 guard |
| H. PostgreSQL + repository regression green | Task 10 exact-head CI matrix |

---

## Boundary-Double Register

The real-owner acceptance may use deterministic doubles **only** for these explicit boundaries:

| Boundary | Why a double is permitted | Forbidden behavior |
| --- | --- | --- |
| Semantic reconstruction IO | external/Host-derived environment observation | cannot implement freshness policy; returns `ReconstructionResult` only |
| Current Host revision observation | environment observation for RevisionBarrier | cannot decide pass/fail; returns revision only |
| Preview | presentation artifact | cannot modify ChangeSet/approval authority |
| Human/policy admission input | external human/policy decision evidence | cannot create `ApprovalRecord`/grant; Gateway V2 must consume it |
| Runtime routing | environment/runtime discovery | cannot implement planning semantics |
| Provider execution snapshot/native identity input | runtime/provider environment evidence | cannot select provider; Provider Binding V2 does selection |
| Host readiness | external Host availability/revision evidence | cannot mutate Saga truth |
| Host execute/read-back | actual external mutation boundary | cannot classify reconciliation/DIVERGED |
| Verification/convergence evidence IO | environment evidence acquisition | cannot evaluate scope/semantic/convergence rule |
| Clock | deterministic audit time | cannot affect identity/business outcome beyond public timestamp contract |

No other repository-internal domain owner may be replaced by a test fake in `test_real_owner_workflow_end_to_end.py`.

---

## Failure Semantics

Implementation must preserve these fail-closed boundaries:

```text
missing owner ref                  -> workflow-facing authoritative-ref unavailable error
owner hash/id mismatch             -> owner integrity/conflict error; no downstream execution
semantic revision changed          -> RevisionChangedError -> workflow REVISION_CONFLICT mapping
Gateway V2 rejection               -> preserve Gateway stable error semantics
provider snapshot/binding mismatch -> ProviderBindingError; no Host execution
Saga unknown outcome               -> remain UNKNOWN/recovery path; never assume not committed
DIVERGED                           -> terminal observable failure; no auto compensation
checkpoint contains only refs      -> missing ref is not reconstructed from checkpoint body
```

Error translation in `CanonicalWorkflowOwnerPorts` may map an owner error to the existing workflow-facing error vocabulary, but must retain cause/code in a stable, testable way where current contracts allow it.

---

## Final Plan Gate

This document is the implementation authority only after written-plan review approval and merge to `main`.

Before that approval:

```text
production code changes      FORBIDDEN
implementation task execution FORBIDDEN
CI/support-matrix expansion    FORBIDDEN
```

After approval, implementation must execute Tasks 1–10 in order unless exact evidence triggers an explicit stop/amendment gate.

Capability lifecycle is not `COMPLETED` when implementation PR merely opens or turns green. Required closeout remains:

```text
implementation exact-head GREEN
→ merge
→ merged-main observation GREEN
→ docs-only lifecycle closeout
→ real E2E workflow COMPLETED
```

Only after that closeout may the next capability (`semantic -> plan -> approve -> execute -> reconcile`) enter its own Design Gate.