# Real Product Vertical — Revit Wall Thickness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Every production-code task is TDD RED → GREEN → focused verification → exact-head verification → commit. Do not collapse gates.

**Status:** Revised written implementation plan — pending re-review  
**Date:** 2026-09-25  
**Plan source base:** `design/revit-wall-thickness-product-vertical@b2b7e131415322e8704045f298952eb434356922`  
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

This follows the existing `platform/interaction` source-only precedent. Revit-native reading and command construction remain under `hosts/revit`. Generic orchestrator/reconciliation code must not import Revit modules. Product Runtime is the application/composition layer allowed to consume platform public contracts and Revit sidecar public adapters together.

## Source Census Decisions Frozen by This Plan

1. `PostgresWorkflowArtifactStore` does not own ProductTask requests. ProductTask request identity is `task_id`, with create-once semantics in an independent `product_task.request` owner table.
2. `orchestrator_checkpoint` stores workflow navigation/refs only; it does not store the mutable ProductTask request body.
3. `WorkflowServices.bind_parameters(...)` and `SemanticReconstructionPort.load_parameter_binding_inputs(...)` gain explicit `task_id`; no new checkpoint field is needed because graph state already owns task id.
4. Existing `SET_WALL_THICKNESS_V1` remains authoritative: target comes from CONTEXT, thickness from INTENT, canonical effect is `PROPERTIES`.
5. Independent READ reuses `RevitWallSnapshotReader`; no duplicate Wall/WallType read logic.
6. `DesignFactAdapter` remains the only Revit snapshot → normalized fact boundary.
7. Semantic Runtime snapshot registry remains in-memory for this capability; no owner-wide PostgreSQL migration is introduced.
8. EXECUTE `expected_revision` is the exact PlanningSnapshot `base_host_revision`, frozen inside existing hash-bound `ProviderBindingV2.native_binding_metadata`; no duplicate revision field is added to ExecutionSlice, Grant, Saga or HostDispatchContext.
9. `WorkflowPhase.COMPLETED` is not product success. Only authoritative Saga `SUCCEEDED` maps to product `SUCCEEDED`.
10. Independent evidence failure after known Host commit leaves durable truth `HOST_COMMITTED + RECONCILING + verification_hash=None` and returns recovery-required semantics; no new Saga state/transition and no fake bundle.

## Global Constraints

- Product request is user INTENT authority, never model/Host truth authority.
- Request must not carry selected semantic/native identity, current thickness, classification, WallType, Host revision, joins/inserts/openings.
- Same `task_id` + same body is idempotent; same `task_id` + different body is a stable conflict.
- Request-write / workflow-start crash window must be recoverable from a fresh store/runtime.
- Before ParameterBinder, request may be reloaded only by exact `task_id`; after bound-operation authority exists, downstream recovery uses frozen artifacts/refs and must not reinterpret the original request.
- `WorkflowStartRequest.request_data` contains request locator/hash only.
- No `current request`, `latest request`, reverse lookup, thread-local or singleton request state.
- `CanonicalWorkflowOwnerPorts` stays generic; Revit-specific product rules live in Product Runtime / Host adapters.
- Product runtime cannot bypass resolver/binder/ChangeSet/approval/planning/binding/grant to mutate Host state.
- Independent READ must prove exact host, document, Wall.UniqueId and `ActualDelta.revision_after == read.revision_before == read.revision_after`.
- A newer revision is not accepted even when the measured value still equals 300 mm.
- Mutation response `width_after_mm` is never a Step33 evidence fallback.
- Evidence acquisition failure never synthesizes a `VerificationEvidenceBundle`; it remains nonterminal/recoverable truth.
- Existing `SemanticVerifier` remains the only semantic PASS/FAIL authority.
- Live width tolerance remains Phase H `pytest.approx(value, abs=1e-6)`.
- Offline product acceptance may fake only external Host transport behavior and human/presentation boundary. Impact, Scope, ChangeSet, Planning, Binding, Gateway, Saga, Reconciliation and SemanticVerifier use production owners.
- No NLP/Agent/MCP, multi-entity, CREATE/DELETE/OFFSET, cross-host, multi-document, compensation, V1 retirement, support-matrix or generic-product-framework expansion.
- New Python production code includes complete Chinese comments/docstrings and follows current repository style.
- Each Task gets an independent commit; the next Task starts only from the previous Task's exact GREEN HEAD.

## Ruff Gate Policy

The repository already contains historical Ruff diagnostics. This plan therefore distinguishes **new-only absolute Ruff** from **legacy-directory no-new-diagnostics Ruff**.

1. Files/directories created entirely by this capability and absent from the implementation base may use normal `uv run ruff check <new paths>` and must be clean.
2. Any Task touching a pre-existing directory such as `platform/orchestrator`, `tests/orchestrator`, `platform/execution_coordination`, `tests/execution_coordination`, `hosts/revit/sidecar`, `tests/integration` must use the same no-new-diagnostics semantics as `.github/workflows/repository-regression.yml`:
   - resolve a real baseline commit (`git merge-base HEAD origin/main` for local task work; GitHub Actions uses `.github/scripts/resolve-ruff-baseline.sh`);
   - use the **HEAD Ruff binary** for both baseline and head;
   - emit JSON diagnostics for the same scoped paths on baseline and head, allowing Ruff itself to return non-zero on both sides;
   - compare diagnostics as a multiset of `(normalized filename, code, message)`;
   - Task is GREEN only when `head - base == 0` new diagnostics.
3. Existing diagnostics are not Task scope and are not to be mass-cleaned merely to make an absolute directory command return zero.
4. Final GitHub Actions repository-regression Ruff delta on the final SHA is authoritative.

No Task below may replace this with an absolute Ruff gate over a legacy directory.

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

- [ ] **Step 1: Add request/hash RED** — reject blank identity, non-positive/non-finite thickness, non-mm unit, extra model-truth fields and hash mismatch; 300/350 hash differently.
- [ ] **Step 2: Run RED** — `uv run pytest tests/product_runtime/test_product_task_request.py -q -vv`.
- [ ] **Step 3: Implement immutable contract + canonical hash** over exactly `task_id, project_id, host_kind, session_ref, requested_action, intent_arguments`.
- [ ] **Step 4: Add PostgreSQL create-once RED** using owner schema/table `product_task.request`; prove same-body replay, different-body conflict, fresh-store read and corrupted-row integrity failure.
- [ ] **Step 5: Implement store + dedicated ProductTask PG fixture** in `tests/product_runtime/conftest.py`; do not borrow orchestrator owner fixture state.
- [ ] **Step 6: Prove request-written / no-checkpoint crash window** with store close/reopen before constructing any workflow.
- [ ] **Step 7: GREEN**:

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_product_task_request.py \
  tests/product_runtime/test_product_task_request_postgres.py -q -vv
uv run ruff check platform/product_runtime tests/product_runtime
```

- [ ] **Step 8: Commit** `feat: persist immutable product task requests`.

---

## Task 2: Carry `task_id` explicitly to ParameterBinder input assembly and migrate the full seam

**Production files:**
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/default_workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`

**Known test/fixture consumers that must migrate in this Task:**
- `tests/orchestrator/test_default_workflow_services.py`
- `tests/orchestrator/test_langgraph_graph.py`
- `tests/orchestrator/test_canonical_owner_ports.py`
- `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- `tests/orchestrator/test_task9_parameter_binding_lineage.py`
- `tests/orchestrator/test_task9_real_owner_acceptance.py`
- `tests/orchestrator/test_task10_durable_recovery.py`
- `tests/orchestrator/test_workflow_end_to_end.py`
- `tests/orchestrator/test_workflow_resume_authoritative_truth.py`
- `tests/orchestrator/test_hitl_resume_observability.py`
- `tests/orchestrator/test_langgraph_runtime.py`
- `tests/orchestrator/test_legacy_hitl_migration.py`
- `tests/orchestrator/test_legacy_hitl_resume_observability.py`
- `tests/orchestrator/test_postgres_checkpoint.py`
- `tests/orchestrator/test_task6_review_regressions.py`
- `tests/orchestrator/test_task9_parameter_binding_context_validation.py`
- `tests/orchestrator/test_v2_hitl_artifact_validation.py`

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

- [ ] **Step 1: Freeze the consumer census before RED.** Run:

```bash
git grep -n -E 'def bind_parameters\(|def load_parameter_binding_inputs\(' \
  -- platform/orchestrator tests/orchestrator
```

Every implementation/fake at the Task 2 starting HEAD must either be in the list above or be added to this Task before production signatures change. Do not leave a discovered consumer for Task 11.

- [ ] **Step 2: Add delegation/graph RED.** Existing `state["task_id"]` must reach `DefaultWorkflowServices` and `ExternalOwnerPorts`; no new graph/checkpoint field.
- [ ] **Step 3: Add canonical adapter RED.** Adapter forwards exact task id and retains exact `ParameterBindingContext.context_snapshot_id/hash` validation against authoritative `context_snapshot_ref`.
- [ ] **Step 4: Implement the narrow seam.** Graph call is exactly task id + operation ref + context ref; ParameterBinder itself does not change.
- [ ] **Step 5: Migrate every census consumer in the same Task.** No optional task id, `*args`, default task, singleton/current-task compatibility shim. Legacy HITL/restart/observability fixtures receive and assert their existing task id where relevant.
- [ ] **Step 6: Run seam-focused GREEN including the previously omitted files:**

```bash
uv run pytest \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/orchestrator/test_hitl_resume_observability.py \
  tests/orchestrator/test_langgraph_runtime.py \
  tests/orchestrator/test_legacy_hitl_migration.py \
  tests/orchestrator/test_legacy_hitl_resume_observability.py \
  tests/orchestrator/test_postgres_checkpoint.py \
  tests/orchestrator/test_task6_review_regressions.py \
  tests/orchestrator/test_task9_parameter_binding_context_validation.py \
  tests/orchestrator/test_v2_hitl_artifact_validation.py -q
uv run pytest tests/orchestrator -q
```

Then run the **Ruff no-new-diagnostics gate** from the policy above for `platform/orchestrator tests/orchestrator`; raw historical diagnostics do not fail the Task unless the multiset delta is positive.

- [ ] **Step 7: Commit** `feat: bind workflow parameters to explicit task lineage`.

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

**Wire contract:** READ `read_wall_thickness_snapshot`, exactly one Wall UniqueId, empty arguments/preconditions, `idempotency_key=null`.

- [ ] **Step 1:** RED proves READ-only routing and delegation to existing `RevitWallSnapshotReader`.
- [ ] **Step 2:** Introduce one process-lifetime `RevitRuntimeIdentity` shared by context and snapshot READ.
- [ ] **Step 3:** Implement read window: supplied `revisionBefore`, native snapshot read, final `readCurrentRevision()`, success only when equal; otherwise `REVIT_SNAPSHOT_REVISION_CHANGED`; never open Transaction.
- [ ] **Step 4:** Wire router + PluginEntry without changing readiness/mutation names.
- [ ] **Step 5: GREEN**:

```bash
uv run pytest tests/revit/test_revit_wall_thickness_snapshot_read.py tests/revit/test_revit_architecture.py -q -vv
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj -f net8.0
```

- [ ] **Step 6: Commit** `feat: add independent Revit wall snapshot read`.

---

## Task 4: Add strict Python Revit context and snapshot read ports

**Files:**
- Create: `hosts/revit/sidecar/src/revit_sidecar/context.py`
- Create: `hosts/revit/sidecar/src/revit_sidecar/snapshot_read.py`
- Modify: `hosts/revit/sidecar/src/revit_sidecar/__init__.py`
- Create: `hosts/revit/sidecar/tests/test_context.py`
- Create: `hosts/revit/sidecar/tests/test_snapshot_read.py`

- [ ] **Step 1:** RED requires exact document/host identity, selected UniqueId/native kind and top-level Host revision from `context.current_selection`.
- [ ] **Step 2:** RED freezes snapshot command `mode=READ`, `operation=read_wall_thickness_snapshot`, one Wall target, no idempotency key.
- [ ] **Step 3:** `read(..., expected_revision=N)` requires document/host/native id exact and `revision_before == revision_after == N`.
- [ ] **Step 4:** Implement transport evidence validation only; no semantic mapping logic.
- [ ] **Step 5: GREEN**:

```bash
uv run pytest hosts/revit/sidecar/tests/test_context.py hosts/revit/sidecar/tests/test_snapshot_read.py -q -vv
```

Run the Ruff **no-new-diagnostics gate** for pre-existing `hosts/revit/sidecar`; additionally require the two newly created modules/tests themselves to have no Ruff diagnostics.

- [ ] **Step 6: Commit** `feat: validate Revit context and wall snapshot reads`.

---

## Task 5: Replace the test semantic boundary with real request-aware Revit semantics

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/revit_semantics.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Create: `tests/product_runtime/test_revit_semantics.py`
- Create: `tests/product_runtime/test_request_binding_interleaving.py`

- [ ] **Step 1:** RED `resolve_host_context(task_id)` loads exact request, reads current Revit selection, requires one element, resolves existing semantic identity via `IdentityRegistry.by_host`, requires Wall native kind, returns content-hashed exact context observation.
- [ ] **Step 2:** Fresh boundary instance can rebuild `load_context_inputs(context_ref)` only by exact Host re-read + observation hash match; changed selection/document/revision fails closed.
- [ ] **Step 3:** Real reconstruction path is `IdentityRegistry -> exact HostBinding -> snapshot READ -> DesignFactAdapter -> SemanticService -> ReconstructionResult`; do not invent `ifc:IfcWall`.
- [ ] **Step 4:** Real operation-resolution inputs build `SemanticEligibilityContext`; OperationResolver still resolves canonical action space.
- [ ] **Step 5:** Task-aware binding inputs load request by exact task id, put thickness in `OperationProposal`, and keep targets only in `ParameterBindingContext.selection`.
- [ ] **Step 6:** Add request-store unavailable/hash-mismatch RED through this real semantic boundary: fail closed before binding; no current/latest fallback.
- [ ] **Step 7:** Mandatory 300/350 interleaving recovery: pause both tasks before binder, rebuild request store + semantic boundary + runtime/adapters, resume B then A; each gets its own immutable value and exact context lineage.
- [ ] **Step 8: GREEN**:

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_revit_semantics.py \
  tests/product_runtime/test_request_binding_interleaving.py -q -vv
uv run ruff check platform/product_runtime tests/product_runtime
```

- [ ] **Step 9: Commit** `feat: compose product requests with Revit semantic context`.

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

- [ ] **Step 1:** Resolve exact `ExecutionSliceV2 -> ChangeSet -> SnapshotSet -> PlanningSnapshot(document)` and freeze non-negative `base_host_revision` into `ProviderBindingMaterial.native_binding_metadata` before V2 binding resolution.
- [ ] **Step 2:** Prove changing only expected revision changes provider snapshot/binding hashes.
- [ ] **Step 3:** Readiness observed revision must equal the hash-bound expected revision before mutation.
- [ ] **Step 4:** Execution port validates slice/authority/binding joins, one admitted Wall target, canonical mm thickness and expected revision; reuses durable dispatch idempotency key; uses existing Host adapter/result adapter.
- [ ] **Step 5:** Freeze names: canonical `set_wall_thickness.v1`, provider `revit.set_wall_thickness`, Host `set_wall_thickness`, transport `mm`.
- [ ] **Step 6:** Compose environment-owned runtime/identity/topology; request never supplies target identity.
- [ ] **Step 7: GREEN**:

```bash
uv run pytest \
  tests/product_runtime/test_revit_execution_composition.py \
  hosts/revit/sidecar/tests/test_execution.py \
  hosts/revit/sidecar/tests/test_readiness.py -q -vv
uv run ruff check platform/product_runtime tests/product_runtime
```

Run Ruff no-new-diagnostics for the pre-existing sidecar directory.

- [ ] **Step 8: Commit** `feat: execute admitted wall thickness changes through Revit`.

---

## Task 7: Put independent READ evidence inside Step33, migrate the full evidence seam, and preserve known-commit recovery truth

**Production definition/call sites:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/contracts.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/ports.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/materialized_coordinator.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/recovery.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/__init__.py`

**New product evidence implementation:**
- Create: `platform/product_runtime/src/design_product_runtime/revit_evidence.py`
- Create: `tests/product_runtime/test_revit_verification_evidence.py`
- Create: `tests/execution_coordination/test_verification_evidence_unavailable.py`

**Existing V2 `build_bundle` implementations that must migrate in this Task:**
- Modify: `tests/execution_coordination/_materialized_support.py`
- Modify: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Modify: `tests/integration/phase_i_live_host.py`

**Approved evidence port signature:**

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

- [ ] **Step 1: Freeze the evidence seam census before RED.** Run:

```bash
git grep -n 'def build_bundle' -- platform tests
```

Every V2 `ConvergenceEvidencePort` implementation at the Task 7 starting HEAD must be migrated in this Task. Any additional discovered implementation is added now, not deferred to final regression.

- [ ] **Step 2: Add independent READ RED.** Product evidence port gets exact target from admitted binding and reads exact host/document/Wall.UniqueId at `ActualDelta.revision_after`.
- [ ] **Step 3: Add correlation negatives.** Reject host/document/entity mismatch, read-before/read-after mismatch, and any read revision different from ActualDelta revision; newer state is not accepted.
- [ ] **Step 4: Add semantic evidence RED.** Correlated snapshot only: `DesignFactAdapter -> SemanticService -> exact wall/thickness evidence -> VerificationEvidenceBundle`, bound to exact ChangeSet/execution/ActualDelta hashes, never mutation-response width.
- [ ] **Step 5: Add known-commit evidence-unavailable RED.** After scope result, explicit `VerificationEvidenceUnavailable` leaves `dispatch=HOST_COMMITTED`, slice `RECONCILING`, persisted scope hash, no verification hash, Saga nonterminal, Host execute count 1; coordinator returns `RECOVERY_REQUIRED` with same saga id.
- [ ] **Step 6: Implement narrow coordinator handling** around evidence build only; integrity/programming/scope/SemanticVerifier failures are not swallowed.
- [ ] **Step 7: Thread authority + binding set into recovery evidence call**; recovery probe remains read-only.
- [ ] **Step 8: Migrate the three existing implementations.** `_materialized_support.py`, real-owner E2E and `phase_i_live_host.py` all accept `authority` and `binding_set`; their existing assertions remain and add exact-lineage assertions where available. This migration is part of Task 7 GREEN, not Task 11 cleanup.
- [ ] **Step 9: Prove exact-revision value mismatch uses the existing semantic-failure terminal path**, not RECONCILING.
- [ ] **Step 10: GREEN including seam compatibility:**

```bash
uv run pytest tests/product_runtime/test_revit_verification_evidence.py -q -vv
uv run pytest tests/execution_coordination -q
uv run pytest tests/execution_reconciliation -q
uv run pytest tests/orchestrator/test_real_owner_workflow_end_to_end.py -q
DSP_PHASE_I_LIVE=0 uv run pytest tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py --collect-only -q
```

Run absolute Ruff only for new `platform/product_runtime` / `tests/product_runtime` files. Run Ruff no-new-diagnostics for `platform/execution_coordination`, `tests/execution_coordination`, `tests/orchestrator` and `tests/integration` touched by the seam migration.

- [ ] **Step 11: Commit** `feat: verify Revit commits from independent read evidence`.

---

## Task 8: Add thin `WallThicknessProductFlow` and authoritative outcome projection

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/wall_thickness_flow.py`
- Modify: `platform/product_runtime/src/design_product_runtime/contracts.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Create: `tests/product_runtime/test_wall_thickness_flow.py`

- [ ] **Step 1:** `submit()` writes request first, then checks checkpoint, starts only when absent; crash after request write / before start is recoverable.
- [ ] **Step 2:** `request_data` contains only `product_request_task_id` + `product_request_hash`.
- [ ] **Step 3:** Product projection rules: pending wait → WAITING; active execution recovery → RECOVERY_REQUIRED; Saga terminal statuses map one-to-one. `WorkflowPhase.COMPLETED` alone never means success.
- [ ] **Step 4:** `HOST_COMMITTED + RECONCILING` projects RECOVERY_REQUIRED.
- [ ] **Step 5:** Implement facade as pure persistence/runtime-driving/projection composition.
- [ ] **Step 6: GREEN**:

```bash
uv run pytest tests/product_runtime/test_wall_thickness_flow.py -q -vv
uv run ruff check platform/product_runtime tests/product_runtime
```

- [ ] **Step 7: Commit** `feat: add wall thickness product flow facade`.

---

## Task 9: Prove the complete Design §18 mandatory offline acceptance through ProductFlow composition

**Files:**
- Modify: `tests/product_runtime/conftest.py`
- Create: `tests/product_runtime/test_revit_wall_thickness_product_e2e.py`
- Create: `tests/product_runtime/test_revit_wall_thickness_product_ingress_failures.py`
- Create: `tests/product_runtime/test_revit_wall_thickness_product_authorization_failures.py`
- Create: `tests/product_runtime/test_revit_wall_thickness_product_recovery.py`
- Create: `tests/product_runtime/test_revit_wall_thickness_product_verification_failures.py`

**Required real components:** PostgreSQL ProductTask store, LangGraph PostgreSQL checkpointer, PostgreSQL workflow artifact store, real OperationResolver/ParameterBinder/Freshness/Impact/Scope/ChangeSet/Materialization/Execution Planning/Provider Binding/Gateway, PostgreSQL Saga V2 + HostDispatchIntent stores, real ScopeComparator/SemanticVerifier/convergence, real `WallThicknessProductFlow`.

Allowed doubles: external Host transport behavior, human/presentation interaction boundary, supported deterministic clocks/failure injection. Predecessor owner tests do **not** satisfy this Task unless the assertion actually enters through `WallThicknessProductFlow` with the new product composition.

### Task 9 scenario-to-test freeze

| Mandatory Design §18 scenario | Test landing | Required mutation/success assertion |
| --- | --- | --- |
| happy path one wall → 300 | `test_revit_wall_thickness_product_e2e.py` | exactly 1 EXECUTE; separate READ; Saga/product SUCCEEDED |
| operation proposal reject | `...product_ingress_failures.py` | 0 EXECUTE; product CANCELLED |
| stale context | `...product_ingress_failures.py` | 0 stale EXECUTE; reacquire/freshness path required before any later mutation |
| parameter/context lineage mismatch | `...product_ingress_failures.py` | 0 EXECUTE; fail closed; product not success |
| 300/350 interleaved requests after rebuild | `...product_e2e.py` | each task binds own request; no cross-talk; at most its own admitted mutation |
| request store unavailable/hash mismatch before binding | `...product_ingress_failures.py` | 0 EXECUTE; no latest/current fallback; product not success |
| approval/grant mismatch | `...product_authorization_failures.py` | 0 EXECUTE; fail before Host mutation |
| grant revoked | `...product_authorization_failures.py` | 0 EXECUTE; product not success |
| grant expired | `...product_authorization_failures.py` | 0 EXECUTE; product not success |
| Host outcome unknown | `...product_recovery.py` | one logical dispatch identity; no duplicate EXECUTE; RECOVERY_REQUIRED/wait |
| ActualDelta extra entity | `...product_verification_failures.py` | mutation may be committed once; Step33/product not success |
| ActualDelta extra aspect | `...product_verification_failures.py` | mutation may be committed once; Step33/product not success |
| mutation says 300, independent READ says other value | `...product_verification_failures.py` | exactly 1 EXECUTE; real SemanticVerifier non-PASS; product not success |
| independent READ wrong host/document/entity | `...product_verification_failures.py` | no second EXECUTE; evidence rejected; product not success |
| independent READ revision newer than commit | `...product_verification_failures.py` | no second EXECUTE; evidence rejected; RECOVERY_REQUIRED/non-success |
| revision changes during independent READ | `...product_verification_failures.py` | no second EXECUTE; evidence rejected; RECOVERY_REQUIRED/non-success |
| restart at operation proposal HITL | `...product_recovery.py` | 0 EXECUTE before accept; fresh runtime restores exact request + refs; no recompute/cross-talk |
| restart after dispatch | `...product_recovery.py` | owner truth chooses route; no duplicate EXECUTE |
| exact final semantic thickness 300 at committed revision | `...product_e2e.py` | independent exact-revision Step33 proof PASS + Saga/product SUCCEEDED |

- [ ] **Step 1: Build one stateful fake Revit transport, not fake owners.** It implements `context.current_selection`, readiness, mutation and independent snapshot read; successful mutation increments document revision exactly once.
- [ ] **Step 2: Implement happy path + exact final semantic proof** in `test_revit_wall_thickness_product_e2e.py`.
- [ ] **Step 3: Implement ingress/HITL/context/request failures** and assert no stale/unauthorized Host mutation.
- [ ] **Step 4: Implement authorization failures** for approval/grant mismatch plus revoked/expired grant; all must stop before dispatch.
- [ ] **Step 5: Implement Host outcome-unknown + both restart windows**; no duplicate logical dispatch after rebuild.
- [ ] **Step 6: Implement scope and independent-evidence failures** for extra entity/aspect, wrong value, wrong identity, newer revision, read-window revision change; all must deny product success and never redispatch merely to obtain cleaner evidence.
- [ ] **Step 7: Re-run full-flow 300/350 interleave** after fresh request store/runtime/adapters and assert final BoundOperation/ChangeSet values and request hashes stay task-local.
- [ ] **Step 8: Run the mandatory PostgreSQL offline matrix as one gate:**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_revit_wall_thickness_product_e2e.py \
  tests/product_runtime/test_revit_wall_thickness_product_ingress_failures.py \
  tests/product_runtime/test_revit_wall_thickness_product_authorization_failures.py \
  tests/product_runtime/test_revit_wall_thickness_product_recovery.py \
  tests/product_runtime/test_revit_wall_thickness_product_verification_failures.py -q -vv
```

- [ ] **Step 9: Run predecessor regressions** for real-owner workflow, durable recovery and Phase H reconciliation, but treat them only as regression evidence, not substitutes for the table above.
- [ ] **Step 10: Ruff** — absolute clean for new Product Runtime/new product tests; any touched legacy test directories use no-new-diagnostics.
- [ ] **Step 11: Commit** `test: prove complete Revit wall thickness product acceptance offline`.

---

## Task 10: Add mandatory live Revit product acceptance and separate conditional negatives

**Files:**
- Create: `tests/integration/test_revit_wall_thickness_product_live.py`
- Create: `docs/runbooks/revit-wall-thickness-product-vertical.md`

- [ ] **Step 1:** Reuse reviewed Phase H isolated-wall fixture; verify `.rvt` SHA-256 and exact isolated wall identity; seed environment-owned registries, never request body.
- [ ] **Step 2:** Drive actual `WallThicknessProductFlow` over real named pipe and observe dedicated independent snapshot READ after mutation.
- [ ] **Step 3:** Mandatory happy-path assertions: request hash durable, selected identity exact, binding revision used by EXECUTE, one commit revision increment, independent READ host/doc/entity/revision exact, width 300 ± 1e-6, Step33 PASS, Saga/product SUCCEEDED.
- [ ] **Step 4:** Where controlled fixture/setup can deterministically create Design §18 live-negative conditions, run them. Otherwise record `NOT_RUN_ENVIRONMENT_LIMITATION`; this never waives Task 9 mandatory offline proof.
- [ ] **Step 5:** Runbook records reset procedure, fixture hash, Revit version, TFM/API path/pipe, exact HEAD, mutation and independent-read revisions and measured width.
- [ ] **Step 6: Live GREEN**:

```powershell
$env:DSP_REVIT_LIVE = "1"
python -m pytest tests/integration/test_revit_wall_thickness_product_live.py -q -vv -s
```

- [ ] **Step 7:** Run Ruff no-new-diagnostics for touched legacy `tests/integration` plus absolute clean on the new live test file.
- [ ] **Step 8: Commit** `test: add live Revit product vertical acceptance`.

---

## Task 11: Add CI gate and close out on the final immutable branch SHA

**Files:**
- Create: `.github/workflows/revit-wall-thickness-product-vertical.yml`
- Modify: `README.md`

This Task's ordering is normative. **No closeout evidence collected before the final commit may be used to close the capability. No repository commit is allowed after final-SHA evidence is recorded without restarting Steps 4–6.**

- [ ] **Step 1: Prepare the dedicated offline CI workflow in the working tree.** It installs from committed lock and runs ProductTask PG tests, Task 2 seam migration tests, sidecar context/snapshot/execution/readiness, product semantic/evidence/facade tests, full Task 9 PostgreSQL matrix, Revit Core .NET tests, live-test collection with `DSP_REVIT_LIVE=0`, and Ruff using repository no-new-diagnostics semantics for legacy paths.
- [ ] **Step 2: Scope audit the complete working tree** before final commit. Confirm no Agent/MCP/NLP, new canonical action, new Saga state/transition, request body checkpointing, latest/reverse request recovery, mutation-response evidence fallback, WallType duplicate/reassign, multi-host/multi-document expansion or semantic-snapshot PG migration.
- [ ] **Step 3: Update README in the same final closeout commit candidate** only after Task 9 offline matrix and Task 10 mandatory live happy path are GREEN. README may describe the capability candidate; branch closure still waits for final-SHA CI.
- [ ] **Step 4: Create the final branch commit, then push it.** This commit includes the workflow and README. Record `FINAL_SHA=$(git rev-parse HEAD)` after commit and verify remote branch points to the same SHA. No later branch mutation is allowed without invalidating all following evidence.
- [ ] **Step 5: Re-run local exact-head verification on `FINAL_SHA`.** Re-run every Task 1–10 focused command that is applicable to the local environment, the complete Task 9 PostgreSQL matrix, repository pytest importlib/local-parity lanes, Revit Core, and absolute Ruff for capability-new files. For legacy Ruff paths use the no-new-diagnostics procedure, not raw absolute directory success.
- [ ] **Step 6: Require GitHub Actions GREEN on the same `FINAL_SHA`.** The newly committed `revit-wall-thickness-product-vertical.yml` must actually run successfully after push. `repository-regression.yml` on the same SHA must also be GREEN and supplies canonical Python 3.11, Python 3.14 compatibility, repository Ruff delta and .NET 10 compatibility. Record workflow run IDs/URLs and final SHA in the PR conversation or CI artifact; do **not** commit that evidence back to the branch.
- [ ] **Step 7: Written closeout check.** Confirm final remote branch SHA still equals `FINAL_SHA`; if it moved, Steps 5–6 are stale and must be repeated.
- [ ] **Step 8: Review/merge through normal policy.** After merge, observe required workflows on the merge commit. Only merged-main GREEN may mark the capability `CLOSED`.

---

## Acceptance Matrix

| Proof | Required evidence |
| --- | --- |
| Request create-once | same body replay; different body conflict |
| Pre-start crash | request survives without workflow checkpoint and starts later |
| Binder lineage | explicit `task_id + operation_ref + context_snapshot_ref` across every seam consumer |
| Cross-talk | 300/350 interleave after fresh stores/runtime/adapters |
| Proposal reject | ProductFlow CANCELLED, no execution |
| Stale context | no stale Host execution; reacquire/freshness path before mutation |
| Parameter/context mismatch | fail closed, no Host execution |
| Request unavailable/hash mismatch | fail closed, no latest/current fallback |
| Approval/grant mismatch | fail before Host execution |
| Grant revoked/expired | fail before dispatch |
| Host outcome unknown | recover/wait, no duplicate dispatch |
| Planning | real Impact/Scope/ChangeSet/Planning/Binding/Gateway owners |
| Revision | planning revision frozen in binding hash; readiness and EXECUTE use exact value |
| Scope extra entity/aspect | Step33/product no success |
| Mutation | real `set_wall_thickness`, mm transport, one logical dispatch identity |
| Independent read | dedicated READ after commit; exact host/doc/entity/revision |
| Wrong read value | real SemanticVerifier non-PASS, product no success |
| Wrong read identity | evidence rejected, no second mutation |
| Newer/read-window revision | evidence rejected; newer is not good enough |
| Restart at HITL | exact task request + refs restored; no recompute/cross-talk |
| Restart after dispatch | owner truth decides route; no duplicate dispatch |
| Semantic result | Step33 verifies `dsp:WallThickness == requested thickness` at committed revision |
| Evidence unavailable | `HOST_COMMITTED + RECONCILING`, no fake bundle, no second mutation, recovery status |
| Product outcome | only Saga `SUCCEEDED` maps to product `SUCCEEDED` |
| Offline E2E | every Design §18 required scenario crosses new ProductFlow composition |
| Live E2E | controlled real Revit happy path with separate independent READ |
| Live negative | separate evidence where deterministic setup exists; otherwise explicit environment limitation |
| Ruff | capability-new paths clean; legacy paths introduce zero new diagnostics |
| Closeout | final commit → push → same-SHA local/CI evidence → merge → merged-main observation |

## Stop-and-Amend Triggers

Implementation stops and returns to Design/Written-Spec review rather than improvising if:

1. independent READ failure cannot be represented truthfully as existing known-commit nonterminal recovery without adding a Saga state/transition;
2. correct execution requires putting Host/native identity or revision authority into ProductTask request;
3. exact post-commit evidence requires accepting newer Host revision or mutation-response fallback;
4. product recovery requires reinterpreting original request after bound operation/ChangeSet authority is frozen;
5. real routing requires changing materialization-topology ownership rather than consuming existing environment-owned topology;
6. the single vertical requires generic NLP/Agent/MCP ingress or support-matrix expansion.

None of these conditions is currently supported by the source census. If one appears during TDD it is new architectural evidence, not permission to widen this plan.