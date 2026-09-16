# DSP Workflow Orchestrator / LangGraph Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement ADR-010 by introducing a framework-neutral `Workflow Orchestrator` boundary with LangGraph as the v0.6 reference runtime, durable PostgreSQL checkpointing, explicit HITL/AsyncOperationRef pause-resume, and recovery that re-queries authoritative owners instead of inferring external side effects from checkpoint position.

**Architecture:** `Workflow Orchestrator` remains the logical owner; LangGraph is an infrastructure/runtime implementation behind `WorkflowOrchestratorPort`. Workflow checkpoints contain navigation state, user/HITL continuation data, and stable refs only. Deterministic modules such as `OperationResolver`, `ParameterBinder`, ChangeSet/Gateway/Execution Saga services retain their business rules. Execution Saga remains the execution/reconciliation truth, while Host dispatch recovery state remains a separate execution-owner truth from ADR-009. Runtime resume therefore reloads an `ExecutionOwnerView` that composes Saga state with any active Host-dispatch recovery projection before deciding whether to continue, wait, replan, or enter recovery. PostgreSQL checkpoint tables live only in `orchestrator_checkpoint` and are never read by other owners.

**Tech Stack:** Python 3.11 canonical / Python 3.14 compatibility, `uv`, pytest, LangGraph `>=1.2.11,<2`, `langgraph-checkpoint-postgres>=3.1.2,<4`, psycopg 3, PostgreSQL 17 reference CI service.

**Spec:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`

**Depends on:** `docs/superpowers/plans/2026-09-16-durable-persistence-substrate.md` and `docs/superpowers/plans/2026-09-16-cross-owner-delivery-crash-recovery.md`. Runtime implementation starts from merged architecture review and completed dependency plans.

## Global Constraints

- `Workflow Orchestrator` is the authoritative logical owner for workflow progression/checkpoint/HITL/retry coordination.
- LangGraph types, checkpoint row shapes, graph node objects, and PostgresSaver internals must not enter DSP canonical/public domain contracts.
- Workflow checkpoints store stable refs and workflow-local data only; they do not become a second source of truth for D5, ChangeSet, ApprovalRecord, ExecutionGrant, ProviderBinding, Execution Saga, Host dispatch recovery, ActualDelta, or Host state.
- Execution Saga remains the authoritative Saga execution/reconciliation state machine; ADR-009 Host dispatch intent/recovery state remains a separate execution-owner projection and is not forced into `ExecutionSagaStatusV2`.
- Resume must re-query the complete authoritative execution-owner projection before any external side effect is retried.
- `OUTCOME_UNKNOWN` / dispatch recovery is always `RECOVER_OR_WAIT` from the Workflow Orchestrator’s perspective; it never causes a fresh `begin_execution()` or a new command identity.
- `AsyncOperationRef` is the stable wait/resume boundary for reconstruction, interaction, and long-running execution; hidden process/session memory is forbidden.
- Temporal is not introduced by this plan.
- Existing deterministic modules keep their business rules. LangGraph only sequences calls, waits, resumes, and routes exceptions/results.
- PostgreSQL `orchestrator_checkpoint` is physically isolated by schema/search path and credential boundary; no cross-owner table reads or writes.
- Every new non-trivial runtime/recovery module must use Chinese comments/docstrings for ownership and recovery invariants.
- Every task ends with targeted tests and a reviewable commit.

---

### Task 1: Make `platform/orchestrator` a package-managed runtime owner and lock LangGraph

**Files:**
- Create: `platform/orchestrator/pyproject.toml`
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Modify: `tests/architecture/test_modernization_workspace.py`
- Create: `tests/architecture/test_workflow_runtime_boundary.py`

**Interfaces:**
- Distribution name: `design-orchestrator`
- Python package: `design_orchestrator`
- Runtime dependencies: `jsonschema>=4.20`, `langgraph>=1.2.11,<2`, `langgraph-checkpoint-postgres>=3.1.2,<4`

- [ ] **Step 1: Write the RED architecture tests**

```python
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]
ORCHESTRATOR = ROOT / "platform" / "orchestrator"


def test_orchestrator_is_a_workspace_distribution() -> None:
    root = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    assert "platform/orchestrator" in root["tool"]["uv"]["workspace"]["members"]
    package = tomllib.loads((ORCHESTRATOR / "pyproject.toml").read_text(encoding="utf-8"))
    assert package["project"]["name"] == "design-orchestrator"


def test_langgraph_is_owned_by_orchestrator_package() -> None:
    package = tomllib.loads((ORCHESTRATOR / "pyproject.toml").read_text(encoding="utf-8"))
    deps = tuple(package["project"]["dependencies"])
    assert any(item.startswith("langgraph>=1.2.11") for item in deps)
    assert any(item.startswith("langgraph-checkpoint-postgres>=3.1.2") for item in deps)


def test_existing_domain_modules_do_not_import_langgraph() -> None:
    for name in (
        "canonical_operations.py",
        "operation_resolver.py",
        "parameter_binder.py",
        "interactive_binding.py",
    ):
        text = (ORCHESTRATOR / "src" / "design_orchestrator" / name).read_text(
            encoding="utf-8"
        )
        assert "langgraph" not in text
```

- [ ] **Step 2: Verify RED**

```bash
uv run python -m pytest tests/architecture/test_workflow_runtime_boundary.py -q
```

Expected: FAIL because `platform/orchestrator` currently has no package-local `pyproject.toml` and is not a workspace member.

- [ ] **Step 3: Add package metadata and dependencies**

Create `platform/orchestrator/pyproject.toml`:

```toml
[project]
name = "design-orchestrator"
version = "0.1.0"
description = "Framework-neutral DSP Workflow Orchestrator with LangGraph v0.6 reference runtime."
requires-python = ">=3.11"
dependencies = [
    "jsonschema>=4.20",
    "langgraph>=1.2.11,<2",
    "langgraph-checkpoint-postgres>=3.1.2,<4",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Add `platform/orchestrator` to the root uv workspace and run:

```bash
uv lock
uv sync --locked --all-packages
```

- [ ] **Step 4: Update the historical modernization workspace test without rewriting M0 history**

Preserve `_m0_package_managed_members()` as the historical baseline, then add the architecture-approved delta explicitly:

```python
ARCHITECTURE_APPROVED_WORKSPACE_ADDITIONS = {"platform/orchestrator"}

expected_members = (
    _m0_package_managed_members()
    | ARCHITECTURE_APPROVED_WORKSPACE_ADDITIONS
)
assert actual_members == expected_members

forbidden_members = {
    "platform/approval_scope",
    "platform/impact",
    "platform/interaction",
}
assert actual_members.isdisjoint(forbidden_members)
```

Do not edit the frozen M0 dependency inventory to pretend `platform/orchestrator` had a manifest earlier.

- [ ] **Step 5: Run GREEN and commit**

```bash
uv run python -m pytest \
  tests/architecture/test_workflow_runtime_boundary.py \
  tests/architecture/test_modernization_workspace.py -q

git add platform/orchestrator/pyproject.toml pyproject.toml uv.lock \
  tests/architecture/test_workflow_runtime_boundary.py \
  tests/architecture/test_modernization_workspace.py
git commit -m "build: package workflow orchestrator runtime"
```

---

### Task 2: Freeze framework-neutral workflow contracts and checkpoint-safe state

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/workflow_contracts.py`
- Create: `platform/orchestrator/src/design_orchestrator/workflow_port.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Create: `tests/orchestrator/test_workflow_contracts.py`

**Interfaces:**

```python
class AsyncOperationKind(str, Enum):
    INTERACTION_SESSION = "INTERACTION_SESSION"
    RECONSTRUCTION_JOB = "RECONSTRUCTION_JOB"
    EXECUTION_JOB = "EXECUTION_JOB"
    OTHER = "OTHER"


@dataclass(frozen=True, slots=True)
class AsyncOperationRef:
    kind: AsyncOperationKind
    owner: str
    operation_id: str


@dataclass(frozen=True, slots=True)
class StableRef:
    ref_id: str
    content_hash: str | None = None


class WorkflowPhase(str, Enum):
    RESOLVE_INTENT = "RESOLVE_INTENT"
    RESOLVE_HOST_CONTEXT = "RESOLVE_HOST_CONTEXT"
    ENSURE_CONTEXT_FRESHNESS = "ENSURE_CONTEXT_FRESHNESS"
    RESOLVE_OPERATIONS = "RESOLVE_OPERATIONS"
    AWAIT_OPERATION_PROPOSAL = "AWAIT_OPERATION_PROPOSAL"
    PARAMETER_BINDING = "PARAMETER_BINDING"
    ENSURE_OPERATION_FRESHNESS = "ENSURE_OPERATION_FRESHNESS"
    ANALYZE_IMPACT = "ANALYZE_IMPACT"
    BUILD_CHANGESET = "BUILD_CHANGESET"
    PREVIEW = "PREVIEW"
    POLICY_APPROVAL = "POLICY_APPROVAL"
    EXECUTION_PLANNING = "EXECUTION_PLANNING"
    REVISION_BARRIER = "REVISION_BARRIER"
    PROVIDER_BINDING = "PROVIDER_BINDING"
    EXECUTION_GRANT = "EXECUTION_GRANT"
    APPLY_WAIT = "APPLY_WAIT"
    VERIFY_RECONCILE = "VERIFY_RECONCILE"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


@dataclass(frozen=True, slots=True)
class WorkflowCheckpointView:
    task_id: str
    phase: WorkflowPhase
    context_snapshot_ref: StableRef | None = None
    operation_ref: StableRef | None = None
    interaction_ref: AsyncOperationRef | None = None
    changeset_ref: StableRef | None = None
    approval_ref: StableRef | None = None
    execution_plan_ref: StableRef | None = None
    saga_id: str | None = None
    async_operation_ref: AsyncOperationRef | None = None
    error_code: str | None = None
```

`WorkflowOrchestratorPort` exposes `start`, `resume`, and `get_checkpoint` using these framework-neutral types only.

- [ ] **Step 1: Write RED serialization-boundary tests**

Assert construction rejects blank identifiers and that `WorkflowCheckpointView` contains no LangGraph object/type. Add this architecture assertion:

```python
import inspect
from design_orchestrator import workflow_contracts, workflow_port


def test_public_workflow_contracts_do_not_expose_langgraph_types() -> None:
    source = inspect.getsource(workflow_contracts) + inspect.getsource(workflow_port)
    assert "langgraph." not in source
    assert "StateGraph" not in source
    assert "PostgresSaver" not in source
```

- [ ] **Step 2: Verify RED**

```bash
uv run python -m pytest tests/orchestrator/test_workflow_contracts.py -q
```

- [ ] **Step 3: Implement normalized immutable refs and checkpoint view**

Use validation helpers that trim required text, validate optional SHA-256 hashes when supplied, normalize enums, and copy mappings/tuples before storing them.

- [ ] **Step 4: Define the port**

```python
class WorkflowOrchestratorPort(Protocol):
    def start(self, request: WorkflowStartRequest) -> WorkflowCheckpointView: ...
    def resume(
        self,
        task_id: str,
        command: WorkflowResumeCommand | None = None,
    ) -> WorkflowCheckpointView: ...
    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None: ...
```

`WorkflowStartRequest` contains workflow-local request data plus initial stable Host/context refs; `WorkflowResumeCommand` carries user/HITL continuation data only.

- [ ] **Step 5: Run GREEN and commit**

```bash
uv run python -m pytest tests/orchestrator/test_workflow_contracts.py -q
git add platform/orchestrator/src/design_orchestrator/workflow_contracts.py \
  platform/orchestrator/src/design_orchestrator/workflow_port.py \
  platform/orchestrator/src/design_orchestrator/__init__.py \
  tests/orchestrator/test_workflow_contracts.py
git commit -m "feat: define framework neutral workflow owner contracts"
```

---

### Task 3: Define deterministic workflow service ports and complete execution-owner refresh boundary

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/workflow_services.py`
- Create: `tests/orchestrator/test_workflow_services.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class OwnerStateView:
    ref: StableRef
    status: str


@dataclass(frozen=True, slots=True)
class ExecutionSagaView:
    saga_id: str
    saga_revision: int
    status: str
    active_slice_hash: str | None


class HostDispatchRecoveryState(str, Enum):
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SAFE_TO_RETRY = "SAFE_TO_RETRY"


@dataclass(frozen=True, slots=True)
class HostDispatchRecoveryView:
    dispatch_intent_id: str
    execution_slice_hash: str
    state: HostDispatchRecoveryState


@dataclass(frozen=True, slots=True)
class ExecutionOwnerView:
    saga: ExecutionSagaView
    active_dispatch_recovery: HostDispatchRecoveryView | None = None


class WorkflowServices(Protocol):
    def resolve_host_context(self, task_id: str) -> StableRef: ...
    def ensure_context_freshness(self, snapshot_ref: StableRef) -> StableRef | AsyncOperationRef: ...
    def resolve_operations(self, snapshot_ref: StableRef) -> StableRef: ...
    def bind_parameters(self, operation_ref: StableRef) -> StableRef | AsyncOperationRef: ...
    def ensure_operation_freshness(self, operation_ref: StableRef) -> StableRef | AsyncOperationRef: ...
    def analyze_impact(self, operation_ref: StableRef) -> StableRef: ...
    def build_changeset(self, impact_ref: StableRef) -> StableRef: ...
    def preview(self, changeset_ref: StableRef) -> StableRef: ...
    def request_approval(self, changeset_ref: StableRef) -> StableRef | AsyncOperationRef: ...
    def plan_execution(self, changeset_ref: StableRef, approval_ref: StableRef) -> StableRef: ...
    def check_revision_barrier(self, execution_plan_ref: StableRef) -> None: ...
    def bind_providers(self, execution_plan_ref: StableRef) -> StableRef: ...
    def issue_execution_grant(self, execution_plan_ref: StableRef) -> StableRef: ...
    def begin_execution(self, execution_plan_ref: StableRef, grant_ref: StableRef) -> str | AsyncOperationRef: ...
    def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView: ...
    def verify_reconcile(self, saga_id: str) -> ExecutionOwnerView: ...
```

`ExecutionOwnerView` is a read model/projection owned by the execution boundary. It does not merge ownership: `ExecutionSagaView` remains the Saga truth projection, while `HostDispatchRecoveryView` projects ADR-009 Host-effect recovery truth. In particular, `OUTCOME_UNKNOWN` is **not** added to `ExecutionSagaStatusV2`.

- [ ] **Step 1: Write RED structural tests**

Verify that the protocol methods exchange only primitive values, `StableRef`, `AsyncOperationRef`, or framework-neutral views. In particular, no method accepts or returns LangGraph state objects, `StoredExecutionSagaV2`, or `HostDispatchIntent` domain objects directly.

- [ ] **Step 2: Add explicit owner-refresh semantics**

Create a pure helper:

```python
def classify_execution_resume(view: ExecutionOwnerView) -> str:
    recovery = view.active_dispatch_recovery
    if recovery is not None:
        if recovery.state in {
            HostDispatchRecoveryState.OUTCOME_UNKNOWN,
            HostDispatchRecoveryState.RECOVERY_REQUIRED,
            HostDispatchRecoveryState.SAFE_TO_RETRY,
        }:
            return "RECOVER_OR_WAIT"
        raise WorkflowStateError(
            "WORKFLOW_EXECUTION_RECOVERY_STATE_UNKNOWN",
            str(recovery.state),
        )

    saga = view.saga
    if saga.status in {"SUCCEEDED", "DIVERGED", "PARTIALLY_COMMITTED", "FAILED"}:
        return "TERMINAL"
    if saga.status in {"EXECUTING", "CONVERGENCE_PENDING"}:
        return "RECOVER_OR_WAIT"
    if saga.status == "READY":
        return "MAY_DISPATCH"
    raise WorkflowStateError("WORKFLOW_SAGA_STATUS_UNKNOWN", saga.status)
```

The ordering is normative: active Host-dispatch recovery is classified before the Saga status. A Saga can still be `EXECUTING` while the Host effect is specifically `OUTCOME_UNKNOWN`; the workflow must preserve that distinction rather than inventing a new Saga enum value.

- [ ] **Step 3: Add tests proving checkpoint position and Saga enum alone are not complete execution truth**

Cover at least:

```python
executing = ExecutionOwnerView(
    saga=ExecutionSagaView(
        saga_id="saga-1",
        saga_revision=4,
        status="EXECUTING",
        active_slice_hash="a" * 64,
    )
)
assert classify_execution_resume(executing) == "RECOVER_OR_WAIT"

unknown = ExecutionOwnerView(
    saga=executing.saga,
    active_dispatch_recovery=HostDispatchRecoveryView(
        dispatch_intent_id="intent-1",
        execution_slice_hash="a" * 64,
        state=HostDispatchRecoveryState.OUTCOME_UNKNOWN,
    ),
)
assert classify_execution_resume(unknown) == "RECOVER_OR_WAIT"
```

Also construct the views while a synthetic workflow phase says `APPLY_WAIT`; classification must still come from refreshed execution-owner truth, not checkpoint position.

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run python -m pytest tests/orchestrator/test_workflow_services.py -q
git add platform/orchestrator/src/design_orchestrator/workflow_services.py \
  tests/orchestrator/test_workflow_services.py
git commit -m "feat: define orchestrator deterministic service boundary"
```

---

### Task 4: Implement the LangGraph state adapter and graph topology

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/langgraph_state.py`
- Create: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Create: `tests/orchestrator/test_langgraph_graph.py`

**Private runtime state:** a `TypedDict` containing JSON-compatible workflow-local fields and stable-ref dictionaries only.

- [ ] **Step 1: Write RED state-shape test**

```python
FORBIDDEN_KEYS = {
    "changeset_object",
    "approval_record_object",
    "execution_saga_object",
    "dispatch_intent_object",
    "semantic_projection_object",
    "actual_delta_object",
}


def test_langgraph_state_contains_only_workflow_local_values(sample_graph_state) -> None:
    assert FORBIDDEN_KEYS.isdisjoint(sample_graph_state)
    assert isinstance(sample_graph_state["task_id"], str)
    assert isinstance(sample_graph_state["phase"], str)
```

- [ ] **Step 2: Implement conversion functions**

```python
def checkpoint_view_to_graph_state(view: WorkflowCheckpointView) -> dict[str, object]: ...
def graph_state_to_checkpoint_view(state: Mapping[str, object]) -> WorkflowCheckpointView: ...
```

Encode `StableRef`/`AsyncOperationRef` as explicit dictionaries; do not pickle domain objects.

- [ ] **Step 3: Build the graph with deterministic node functions**

Use `StateGraph` and keep each node thin. The main path is:

```text
START
→ resolve_host_context
→ ensure_context_freshness
→ resolve_operations
→ await_operation_proposal
→ parameter_binding
→ ensure_operation_freshness
→ analyze_impact
→ build_changeset
→ preview
→ policy_approval
→ execution_planning
→ revision_barrier
→ provider_binding
→ execution_grant
→ apply_or_recover
→ verify_reconcile
→ END
```

Every node calls exactly one `WorkflowServices` method or performs workflow-local routing. No node reimplements OperationResolver/ParameterBinder/Gateway/Saga/dispatch-recovery rules.

- [ ] **Step 4: Implement pause routing for `AsyncOperationRef`**

If a service returns `AsyncOperationRef`, write it to graph state and route to an `await_async_operation` node that calls LangGraph `interrupt()` with a framework-private payload derived from the ref. Resume only after `WorkflowResumeCommand` is supplied or the runtime is explicitly reinvoked after authoritative state changes.

- [ ] **Step 5: Implement HITL proposal/approval interrupts**

`await_operation_proposal` interrupts with the stable operation-space ref; `policy_approval` interrupts only when the approval owner reports a pending human decision. The interrupt payload must contain refs/labels, never the authoritative full ChangeSet or ApprovalRecord object.

- [ ] **Step 6: Run GREEN and commit**

```bash
uv run python -m pytest tests/orchestrator/test_langgraph_graph.py -q
git add platform/orchestrator/src/design_orchestrator/langgraph_state.py \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py
git commit -m "feat: add langgraph workflow topology"
```

---

### Task 5: Implement `LangGraphWorkflowRuntime` behind `WorkflowOrchestratorPort`

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/langgraph_runtime.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Create: `tests/orchestrator/test_langgraph_runtime.py`

**Interfaces:**

```python
class LangGraphWorkflowRuntime(WorkflowOrchestratorPort):
    def __init__(self, *, services: WorkflowServices, checkpointer) -> None: ...
    def start(self, request: WorkflowStartRequest) -> WorkflowCheckpointView: ...
    def resume(self, task_id: str, command: WorkflowResumeCommand | None = None) -> WorkflowCheckpointView: ...
    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None: ...
```

- [ ] **Step 1: Write RED start/resume tests using LangGraph `InMemorySaver`**

Test that `start()` compiles the graph with `thread_id == task_id`, reaches the first expected interrupt, and `get_checkpoint()` returns a framework-neutral view.

- [ ] **Step 2: Implement runtime config isolation**

Use LangGraph config internally:

```python
config = {"configurable": {"thread_id": task_id, "checkpoint_ns": "dsp.workflow.v0_6"}}
```

Do not expose this dict through `WorkflowOrchestratorPort`.

- [ ] **Step 3: Implement resume with `Command(resume=...)` only for explicit HITL payloads**

When `WorkflowResumeCommand` is present, convert it to the runtime-private resume payload. For poll/recheck resumes, invoke the graph without fabricating user input.

- [ ] **Step 4: Normalize runtime exceptions**

LangGraph exceptions must be translated to stable `WorkflowStateError` codes such as:

```text
WORKFLOW_NOT_FOUND
WORKFLOW_RESUME_INVALID
WORKFLOW_CHECKPOINT_INVALID
WORKFLOW_SERVICE_FAILURE
```

Keep the original exception as `__cause__`; do not leak framework class names into domain/public results.

- [ ] **Step 5: Run GREEN and commit**

```bash
uv run python -m pytest tests/orchestrator/test_langgraph_runtime.py -q
git add platform/orchestrator/src/design_orchestrator/langgraph_runtime.py \
  platform/orchestrator/src/design_orchestrator/__init__.py \
  tests/orchestrator/test_langgraph_runtime.py
git commit -m "feat: add langgraph workflow runtime adapter"
```

---

### Task 6: Add owner-scoped PostgreSQL checkpoint persistence

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/checkpoint_postgres.py`
- Create: `tests/orchestrator/test_postgres_checkpoint.py`
- Create: `.github/workflows/workflow-orchestrator.yml`

**Interfaces:**
- Schema: `orchestrator_checkpoint`
- Test DSN: `DSP_TEST_POSTGRES_DSN`
- Factory:

```python
def create_postgres_checkpointer(dsn: str): ...
```

- [ ] **Step 1: Write the RED ownership test**

The test must create the schema, initialize the checkpointer, query `information_schema.tables`, and assert all LangGraph checkpoint tables created by this factory live in `orchestrator_checkpoint`, not `public`, `execution_saga`, `gateway`, or `semantic_runtime`.

- [ ] **Step 2: Implement schema bootstrap and scoped connection**

Use psycopg to create the schema, then establish the LangGraph checkpointer connection with `search_path` restricted to `orchestrator_checkpoint`. Call `PostgresSaver.setup()` only through this factory.

The implementation shape should be equivalent to:

```python
def create_postgres_checkpointer(dsn: str):
    admin = psycopg.connect(dsn, autocommit=True)
    admin.execute("CREATE SCHEMA IF NOT EXISTS orchestrator_checkpoint")
    admin.close()

    scoped_dsn = add_search_path(dsn, "orchestrator_checkpoint")
    saver = PostgresSaver.from_conn_string(scoped_dsn)
    saver.setup()
    return saver
```

If the library factory is a context manager in the locked version, wrap it in an owner class that manages enter/exit explicitly; do not return a prematurely closed saver.

- [ ] **Step 3: Write restart-resume integration test**

Start a workflow, stop after an interrupt, dispose the runtime/checkpointer, create a new runtime using the same PostgreSQL database, then:

```python
checkpoint = runtime_b.get_checkpoint(task_id)
assert checkpoint is not None
assert checkpoint.task_id == task_id
resumed = runtime_b.resume(task_id, command)
assert resumed.phase != checkpoint.phase
```

- [ ] **Step 4: Add CI workflow**

Use a `postgres:17` service and run:

```bash
DSP_TEST_POSTGRES_DSN='postgresql://postgres:postgres@localhost:5432/dsp_test' \
  uv run python -m pytest \
  tests/orchestrator/test_postgres_checkpoint.py \
  tests/orchestrator/test_workflow_resume_authoritative_truth.py -q
```

- [ ] **Step 5: Run GREEN and commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest tests/orchestrator/test_postgres_checkpoint.py -q

git add platform/orchestrator/src/design_orchestrator/checkpoint_postgres.py \
  tests/orchestrator/test_postgres_checkpoint.py \
  .github/workflows/workflow-orchestrator.yml
git commit -m "feat: add orchestrator postgres checkpoint owner"
```

---

### Task 7: Make resume re-query complete execution-owner truth before execution decisions

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Create: `platform/orchestrator/src/design_orchestrator/recovery.py`
- Create: `tests/orchestrator/test_workflow_resume_authoritative_truth.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ResumeDecision:
    route: str
    refreshed_saga_revision: int | None
    reason: str


def decide_apply_resume(
    *,
    checkpoint: WorkflowCheckpointView,
    execution: ExecutionOwnerView | None,
) -> ResumeDecision: ...
```

- [ ] **Step 1: Write RED crash/restart cases**

Cover all of these:

```text
A. checkpoint phase says APPLY_WAIT, ExecutionOwnerView(Saga READY, no dispatch recovery)
   -> MAY_DISPATCH
B. checkpoint phase says APPLY_WAIT, Saga EXECUTING, no dispatch recovery
   -> RECOVER_OR_WAIT, never call begin_execution
C. checkpoint phase says APPLY_WAIT, Saga PARTIALLY_COMMITTED
   -> TERMINAL_EXECUTION_STATE
D. checkpoint says pre-Apply, but Saga already SUCCEEDED
   -> skip dispatch and route Verify/Reconcile/Complete
E. checkpoint has stale approval/change refs
   -> refresh owner facts before planning/apply
F. Saga EXECUTING + active dispatch recovery OUTCOME_UNKNOWN
   -> RECOVER_OR_WAIT, never call begin_execution
G. Saga READY + active dispatch recovery RECOVERY_REQUIRED/SAFE_TO_RETRY
   -> RECOVER_OR_WAIT; Workflow Orchestrator does not create a new command identity
```

Record fake-service calls and assert B/D/F/G never invoke a second Host dispatch through `begin_execution`.

- [ ] **Step 2: Implement pure recovery decision logic**

The function must derive execution routing from the refreshed `ExecutionOwnerView`, not from graph node history. Checkpoint phase is used only to know which owner refs need refreshing.

Decision order:

```text
active_dispatch_recovery present
→ RECOVER_OR_WAIT

else classify Saga status
→ READY                  => MAY_DISPATCH
→ EXECUTING/PENDING      => RECOVER_OR_WAIT
→ terminal               => terminal/reconcile route
```

`OUTCOME_UNKNOWN` stays in the dispatch-recovery projection. Do not add it to Saga status strings or synthesize a fake terminal Saga state.

- [ ] **Step 3: Insert an authoritative refresh node before `apply_or_recover`**

The node must:

```text
load saga_id from workflow state
→ services.get_execution_owner_state(saga_id)
→ inspect active Host dispatch recovery first
→ classify refreshed Saga status second
→ MAY_DISPATCH only when no recovery is active and Saga is READY
→ RECOVER_OR_WAIT for active/unknown execution or dispatch recovery
→ skip/reconcile for terminal execution states
```

If no `saga_id` exists yet, it may call `begin_execution`; once a Saga ID is durable, subsequent resumes use that ID and the execution owner’s stable read model.

- [ ] **Step 4: Prove cross-plan ADR-009 integration**

Build the fake execution owner view from two independent authoritative sources: Saga state plus Host dispatch recovery state. Add an `OUTCOME_UNKNOWN` case whose `dispatch_intent_id` and Slice hash remain stable across repeated workflow resumes.

Assert:

```text
workflow route = RECOVER_OR_WAIT
begin_execution call count does not increase
no new dispatch_intent_id is created
no new idempotency identity is manufactured
```

The Workflow Orchestrator may ask the execution owner to continue recovery through its stable service API, but it does not directly mutate the dispatch intent or decide that the Host is safe to retry.

- [ ] **Step 5: Run GREEN and commit**

```bash
uv run python -m pytest tests/orchestrator/test_workflow_resume_authoritative_truth.py -q
git add platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  platform/orchestrator/src/design_orchestrator/recovery.py \
  tests/orchestrator/test_workflow_resume_authoritative_truth.py
git commit -m "feat: recover workflow from authoritative owner truth"
```

---

### Task 8: Wire real deterministic OperationResolver and ParameterBinder adapters

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/default_workflow_services.py`
- Create: `tests/orchestrator/test_default_workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`

**Interfaces:**

```python
class WorkflowArtifactStore(Protocol):
    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef: ...
    def get(self, ref: StableRef) -> object: ...


class DefaultWorkflowServices:
    def __init__(
        self,
        *,
        operation_resolver: OperationResolver,
        parameter_binder: ParameterBinder,
        artifact_store: WorkflowArtifactStore,
        external_owners: ExternalOwnerPorts,
    ) -> None: ...
```

The artifact store owns only workflow-local deterministic intermediate artifacts that do not already have another authoritative owner. External domain objects remain with their existing services and are referenced by stable refs.

- [ ] **Step 1: Write RED OperationResolver adapter test**

Use the existing `OperationResolver.resolve(profiles, ResolutionContext)` API. The adapter must persist a workflow-local operation-space artifact and return a `StableRef`; the LangGraph checkpoint must not store the full `ResolutionResult` or provider candidate objects.

- [ ] **Step 2: Write RED ParameterBinder adapter test**

Use the existing `ParameterBinder.bind(OperationProposal, ParameterBindingContext)` API. The adapter must persist the deterministic `BoundOperationProposal` as an artifact/ref or hand it immediately to the next authoritative domain service; checkpoint stores only the resulting `StableRef`.

- [ ] **Step 3: Implement exact adapters without duplicating domain rules**

The service must literally call:

```python
resolution = self._operation_resolver.resolve(profiles, resolution_context)
bound = self._parameter_binder.bind(proposal, binding_context)
```

It must not copy eligibility, slot-binding, schema validation, provider candidate, or freshness algorithms into workflow node code.

The execution adapter is responsible only for composing the framework-neutral `ExecutionOwnerView` from the execution boundary’s stable Saga projection plus ADR-009 dispatch-recovery projection. It must not copy Saga or dispatch transition logic into the Orchestrator.

- [ ] **Step 4: Add negative architecture assertions**

Search `langgraph_graph.py` and `langgraph_runtime.py` and assert they do not contain copied domain identifiers such as `_supports_canonical_entities`, `_validate_recipe_match`, `compute_*_hash` implementations, Gateway/Saga transition enums, or HostDispatchStatus transition logic beyond routing through framework-neutral views.

- [ ] **Step 5: Run GREEN and commit**

```bash
uv run python -m pytest \
  tests/orchestrator/test_default_workflow_services.py \
  tests/orchestrator/test_operation_resolver.py \
  tests/orchestrator/test_step25_parameter_binder.py -q

git add platform/orchestrator/src/design_orchestrator/default_workflow_services.py \
  platform/orchestrator/src/design_orchestrator/__init__.py \
  tests/orchestrator/test_default_workflow_services.py
git commit -m "feat: wire deterministic services into workflow owner"
```

---

### Task 9: Prove HITL, AsyncOperationRef, restart, and execution-owner separation end-to-end

**Files:**
- Create: `tests/orchestrator/test_workflow_end_to_end.py`
- Create: `docs/runbooks/workflow-orchestrator-recovery.md`
- Modify: `.github/workflows/workflow-orchestrator.yml`

**Interfaces:** no new public interfaces; this task closes acceptance evidence.

- [ ] **Step 1: Build one deterministic test workflow fixture**

Use fake external owner ports but the real LangGraph runtime, real `OperationResolver`, real `ParameterBinder`, and PostgreSQL checkpointer. The fixture must exercise:

```text
start
→ resolve operation
→ HITL proposal interrupt
→ resume
→ parameter binding
→ AsyncOperationRef wait
→ resume after authoritative owner completion
→ ChangeSet/approval refs
→ execution Saga ref
→ restart runtime process boundary
→ refresh complete ExecutionOwnerView
→ verify/reconcile
→ completed
```

Include a second branch where restart observes `Saga EXECUTING + HostDispatchRecoveryView(OUTCOME_UNKNOWN)` and remains in recovery without a second execution start.

- [ ] **Step 2: Assert checkpoint payload ownership**

Inspect the saved checkpoint through LangGraph’s supported saver API and assert it contains IDs/refs/workflow-local data but not serialized full authoritative objects. Explicitly reject keys/values that represent `CanonicalChangeSet`, `ApprovalRecord`, `StoredExecutionSagaV2`, `HostDispatchIntent`, `ActualDelta`, or SemanticProjection payloads.

- [ ] **Step 3: Assert no duplicate execution after restart**

Make the fake execution owner report `EXECUTING`, `SUCCEEDED`, or `OUTCOME_UNKNOWN` recovery after runtime restart even though the checkpoint was written before the original caller observed completion. Assert `begin_execution` call count remains `1` in every case where an execution Saga already exists.

- [ ] **Step 4: Write the runbook**

Document:

```text
Workflow checkpoint answers “where is the task navigation?”
Execution Saga answers “what happened in Saga execution?”
Host dispatch recovery answers “is the current Host effect outcome known?”
ExecutionOwnerView composes those execution-side projections without merging their ownership.
On resume, reload authoritative refs before retry/replan.
OUTCOME_UNKNOWN is not a Saga terminal status and never authorizes a fresh begin_execution.
Do not edit checkpoint rows manually to force business success.
Do not infer Host non-commit from an Apply-adjacent checkpoint.
Temporal is not part of the v0.6 recovery procedure.
```

Include PostgreSQL schema ownership and the supported operator procedure for a stuck `AsyncOperationRef` or `OUTCOME_UNKNOWN` dispatch recovery.

- [ ] **Step 5: Run targeted and full regression**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest tests/orchestrator -q

uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
uv run ruff check --select E,F,I platform hosts/autocad/sidecar tests

dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj -f net8.0
```

Expected: all canonical repository regressions remain GREEN, with no new Ruff diagnostics.

- [ ] **Step 6: Commit**

```bash
git add tests/orchestrator \
  docs/runbooks/workflow-orchestrator-recovery.md \
  .github/workflows/workflow-orchestrator.yml
git commit -m "test: prove workflow orchestrator recovery invariants"
```

---

## Self-Review Checklist

Before declaring this implementation complete, verify every ADR-010 invariant:

- [ ] `WorkflowOrchestratorPort` is framework-neutral.
- [ ] LangGraph is the only v0.6 business workflow runtime introduced.
- [ ] No Temporal dependency or second workflow history exists.
- [ ] Checkpoints hold workflow-local state and stable refs only.
- [ ] OperationResolver/ParameterBinder and other deterministic services retain their domain algorithms.
- [ ] Execution Saga state is never copied into checkpoint as a second source of truth.
- [ ] Host dispatch recovery state is never forced into `ExecutionSagaStatusV2` or copied into checkpoint as a second source of truth.
- [ ] `ExecutionOwnerView` keeps Saga truth and Host-dispatch recovery truth distinguishable while giving the Orchestrator one stable authoritative read boundary.
- [ ] Resume re-queries complete execution-owner truth before external side-effect decisions.
- [ ] `OUTCOME_UNKNOWN` / `RECOVERY_REQUIRED` / `SAFE_TO_RETRY` routes to `RECOVER_OR_WAIT` and never manufactures a fresh command identity.
- [ ] `AsyncOperationRef` is persisted explicitly and survives runtime restart.
- [ ] HITL resume uses explicit continuation data rather than hidden process memory.
- [ ] PostgreSQL checkpoint tables live only under `orchestrator_checkpoint`.
- [ ] Other owners never read/write checkpoint tables directly.
- [ ] Framework-specific exceptions/types are normalized before leaving the runtime adapter.
- [ ] Full repository regression and Revit Core regression remain green.
