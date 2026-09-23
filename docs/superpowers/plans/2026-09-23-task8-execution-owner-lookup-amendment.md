# Task 8 Execution Owner Lookup Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete Task 8 real execution-owner wiring without duplicating owner semantics: add exact Provider Binding hash lookup, publish durable dispatch-intent store parity, add execution-owner recovery projection, atomically persist Saga identity with execution wait, and prove safe-wait/no-blind-redispatch behavior before continuing the real-owner E2E.

**Architecture:** `CanonicalWorkflowOwnerPorts` remains a composition adapter. Provider Binding owns hash lookup, Execution Reconciliation owns dispatch-intent persistence, Execution Coordination owns Saga/dispatch recovery interpretation, and LangGraph owns only workflow navigation/checkpoint state. Task 8 is explicitly **safe-wait integration**, not autonomous unknown-outcome recovery scheduling or generic forward-resume/convergence.

**Tech Stack:** Python 3.11 / 3.14, LangGraph 1.2.x, `langgraph-checkpoint-postgres` 3.x, PostgreSQL 17, pytest, Ruff, GitHub Actions. No dependency upgrade is authorized.

**Spec:** `docs/superpowers/specs/2026-09-23-task8-execution-owner-lookup-amendment-design.md`

**Approved written-spec HEAD:** `41d763ada50ed50e9c3322d54e1879b170d5b3fe`

## Global Constraints

- Task 7 remains CLOSED and must not be rolled back.
- `CanonicalWorkflowOwnerPorts` may assemble requests and consume public read models; it must not own Provider Binding identity rules, dispatch transition rules, Saga/dispatch precedence, reconciliation, convergence, or retry policy.
- `get_by_hash(binding_set_hash)` must validate lowercase SHA-256 and must prove `returned.binding_set_hash == requested_binding_set_hash` before returning.
- A same-first-12-hex/different-full-hash case must fail closed; short content-addressed ids are never sufficient evidence of exact hash equality.
- `HostDispatchIntentStore.get_for_saga_slice(saga_id, execution_slice_hash)` is an exact owner lookup and must not filter by active/terminal Saga state or select a latest row.
- In-memory and PostgreSQL dispatch-intent stores must implement the same public contract and the same transition/integrity semantics.
- Formal Task 8 closure requires PostgreSQL contract cases to run **non-skipped** and pass on the exact closing SHA.
- Workflow recovery reads the exact Slice identity from the durable Saga definition. Current workflow scope remains exactly one `ExecutionSliceV2`; multi-slice expansion is out of scope.
- Saga/dispatch precedence belongs to Execution Coordination. `CanonicalWorkflowOwnerPorts` must not encode its own status matrix.
- `SUCCEEDED + Slice SUCCEEDED + HOST_COMMITTED` is terminal with no active workflow recovery.
- `FAILED + Slice FAILED_BEFORE_COMMIT + SAFE_TO_RETRY` is terminal with no active workflow recovery; the durable `SAFE_TO_RETRY` evidence remains queryable in the owner store.
- Terminal Saga plus incompatible unresolved `OUTCOME_UNKNOWN` must fail closed as owner-truth conflict.
- `UnknownOutcomeRecovery.recover(...)` remains the public external recovery entrypoint. Task 8 does not add a scheduler/worker and does not claim autonomous recovery to final convergence.
- `begin_execution()` returning an execution `AsyncOperationRef` must atomically persist its `operation_id` as `saga_id` together with async navigation/wait state.
- Checkpoints may contain ids/refs/navigation only; no `HostDispatchIntent`, `StoredExecutionSagaV2`, `ProviderBindingSetV2`, `ExecutionPlanV2`, `ActualDelta`, or other owner body may be persisted as workflow truth.
- Allowed deterministic doubles remain limited to external/environment boundaries: Host readiness, Host execute/read-back, Host outcome probe, verification/convergence evidence IO, routing/provider observation, preview/HITL evidence, and clock.
- No new compensation behavior, V1 revival, owner-private lookup, adapter-private lineage cache, outbox/inbox architecture, owner-wide PostgreSQL migration, real AutoCAD/Revit acceptance, MCP front door, or support-matrix expansion.
- New Python code must use complete Chinese comments/docstrings and satisfy repository Ruff conventions.

## Review Focus

1. **Hash-prefix collision:** a stored Provider Binding object whose first 12 hash chars match the request but whose full hash differs must never be returned.
2. **Terminal Saga with residual dispatch row:** a legal `HOST_COMMITTED` or `SAFE_TO_RETRY` row must not mechanically force `RECOVER_OR_WAIT` after the Saga/Slice has already reached a compatible terminal outcome.
3. **Unresolved terminal conflict:** terminal Saga plus incompatible `OUTCOME_UNKNOWN` must fail closed rather than silently pick Saga or dispatch truth.
4. **Unknown-outcome replay:** once a durable Saga id and `OUTCOME_UNKNOWN` intent exist, workflow resume/retry must never create a second Host mutation command identity.
5. **PostgreSQL parity:** an in-memory GREEN is insufficient; the exact `HostDispatchIntentStore` contract must execute against PostgreSQL 17 non-skipped on the exact closing SHA.

Each focus item is pinned by an explicit test below.

---

## Supersession of the baseline Task 8/9/10 plan

This plan supersedes only the Task 8/9/10 portions of `docs/superpowers/plans/2026-09-20-real-owner-e2e-workflow.md`.

The following historical statements are no longer implementation authority:

```text
Task 8 can use the existing dispatch-intent surface without a public store contract.
Task 8 may derive Provider Binding identity from the grant hash in the adapter.
Task 8 may classify recovery from active Slice + dispatch enum in the adapter.
Task 10 unknown-outcome acceptance must automatically recover/reconcile to terminal.
```

The corrected boundary is:

```text
Task 8 owner API/parity + canonical execution wiring + safe wait
→ Task 9 real-owner LangGraph E2E A–D/F/G plus unknown-outcome safe-wait acceptance
→ Task 10 durable PostgreSQL restart/no-double-Host proof + exact-head closure
```

Task 10 may prove that an external `UnknownOutcomeRecovery.recover(...)` invocation advances durable owner truth and that a fresh workflow runtime observes it. It must **not** claim the workflow autonomously schedules recovery or necessarily completes forward-resume/convergence after recovered commitment.

---

## File Structure Freeze

| File | Responsibility |
| --- | --- |
| `platform/provider_binding/src/design_provider_binding/store_v2.py` | Exact owner-local `get_by_hash()` with full-hash equality |
| `platform/provider_binding/src/design_provider_binding/__init__.py` | Export approved store/public surface as needed |
| `platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent_store.py` | Public `HostDispatchIntentStore` protocol + in-memory reference implementation |
| `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py` | Implement exact Saga/Slice lookup on durable store |
| `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py` | Export dispatch-intent protocol/reference store |
| `platform/execution_coordination/src/design_execution_coordination/recovery.py` | Owner-level Saga/dispatch read projection; preserve `UnknownOutcomeRecovery` behavior |
| `platform/execution_coordination/src/design_execution_coordination/__init__.py` | Export approved recovery projection types/function |
| `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py` | Reconstruct execution request from public owner APIs and consume owner recovery projection |
| `platform/orchestrator/src/design_orchestrator/langgraph_graph.py` | Persist execution Saga id and async wait atomically |
| `tests/provider_binding/test_task8_hash_lookup.py` | Exact-hash and collision-shaped Provider Binding lookup contract |
| `tests/execution_reconciliation/dispatch_intent_store_contract.py` | Shared backend-neutral dispatch store contract assertions |
| `tests/execution_reconciliation/test_dispatch_intent_store.py` | In-memory dispatch store contract |
| `tests/execution_reconciliation/test_postgres_dispatch_intent.py` | Existing PostgreSQL lane plus shared Task 8 parity contract |
| `tests/execution_coordination/test_task8_execution_recovery_projection.py` | Saga/dispatch precedence and conflict matrix owned by execution coordination |
| `tests/orchestrator/test_canonical_owner_execution.py` | Real coordinator success/DIVERGED/unknown safe-wait wiring |
| `tests/orchestrator/test_langgraph_graph.py` | Atomic Saga id + wait persistence and resume route |
| `tests/orchestrator/test_real_owner_workflow_end_to_end.py` | Real-owner LangGraph acceptance including safe-wait behavior |
| `tests/architecture/test_real_owner_workflow_boundaries.py` | No private owner lookup/status matrix/V1/test-authority regression |
| `.github/workflows/durable-persistence.yml` | **Inspect only by default**; existing PostgreSQL 17 job already collects `test_postgres_dispatch_intent.py` |

No CI workflow edit is planned. If the implementation changes test filenames such that the existing `execution-saga-postgres` job no longer executes the shared PostgreSQL contract, stop and amend this plan before editing CI.

---

### Task 8.1: Add exact Provider Binding hash lookup

**Files:**
- Modify: `platform/provider_binding/src/design_provider_binding/store_v2.py`
- Modify: `platform/provider_binding/src/design_provider_binding/__init__.py` only if package-root export is required by existing import conventions
- Create: `tests/provider_binding/test_task8_hash_lookup.py`

**Interfaces:**
- Consumes: existing `ProviderBindingSetV2`, `ProviderBindingError`, `_validate_reference()`.
- Produces:

```python
def get_by_hash(self, binding_set_hash: str) -> ProviderBindingSetV2:
    ...
```

with the invariant:

```python
returned.binding_set_hash == binding_set_hash
```

- [ ] **Step 1: Write exact-hash success RED**

Create `tests/provider_binding/test_task8_hash_lookup.py` using the existing Provider Binding test fixtures/builders. Store one real `ProviderBindingSetV2`, then assert:

```python
stored = store.put(binding_set)
resolved = store.get_by_hash(binding_set.binding_set_hash)
assert resolved == binding_set
assert resolved.binding_set_hash == binding_set.binding_set_hash
```

Do not assert implementation details such as `_items` contents.

- [ ] **Step 2: Write full-hash collision-shaped RED**

Use a monkeypatched/crafted store state only if needed to create two valid-looking full digests sharing the same first 12 hex chars. The observable assertion is:

```python
requested_hash = "a" * 12 + "1" * 52
stored_hash = "a" * 12 + "2" * 52
assert requested_hash[:12] == stored_hash[:12]
assert requested_hash != stored_hash

with pytest.raises(ProviderBindingError) as exc_info:
    store.get_by_hash(requested_hash)
assert exc_info.value.code in {
    "PROVIDER_BINDING_SET_REFERENCE_NOT_FOUND",
    "PROVIDER_BINDING_INTEGRITY_INVALID",
}
```

The test must prove that matching `PBSV2-<first12>` is not sufficient to return the stored artifact.

- [ ] **Step 3: Write invalid-hash RED**

Assert uppercase, short, non-hex, and blank inputs fail at the Provider Binding owner boundary before lookup.

```python
@pytest.mark.parametrize("value", ["", "A" * 64, "a" * 63, "g" * 64])
def test_get_by_hash_rejects_noncanonical_digest(value):
    with pytest.raises((ValueError, ProviderBindingError)):
        store.get_by_hash(value)
```

Use the repository's existing stable error vocabulary if the owner already centralizes digest validation; do not invent an adapter error.

- [ ] **Step 4: Run RED**

```bash
uv run pytest tests/provider_binding/test_task8_hash_lookup.py -q
```

Expected: fail because `InMemoryProviderBindingSetV2Store` has no `get_by_hash()`.

- [ ] **Step 5: Implement minimal owner lookup**

Implementation remains inside the owner. It may maintain a private full-hash index or derive the content-addressed id internally, but before returning it must execute both checks:

```python
_validate_reference(binding_set)
if binding_set.binding_set_hash != requested_hash:
    raise ProviderBindingError(...)
```

The adapter must not participate in this derivation.

- [ ] **Step 6: Run GREEN + owner regression**

```bash
uv run pytest tests/provider_binding/test_task8_hash_lookup.py tests/provider_binding -q
uv run ruff check \
  platform/provider_binding/src/design_provider_binding/store_v2.py \
  tests/provider_binding/test_task8_hash_lookup.py
```

- [ ] **Step 7: Commit Task 8.1**

```bash
git add \
  platform/provider_binding/src/design_provider_binding/store_v2.py \
  platform/provider_binding/src/design_provider_binding/__init__.py \
  tests/provider_binding/test_task8_hash_lookup.py
git commit -m "feat: add exact provider binding hash lookup"
```

If `__init__.py` is unchanged, omit it from `git add`.

---

### Task 8.2: Publish one HostDispatchIntentStore contract and prove in-memory/PostgreSQL parity

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent_store.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/dispatch_intent_store_contract.py`
- Create: `tests/execution_reconciliation/test_dispatch_intent_store.py`
- Modify: `tests/execution_reconciliation/test_postgres_dispatch_intent.py`

**Interfaces:**
- Consumes: existing `HostDispatchIntent`, `HostDispatchStatus`, existing PostgreSQL transition methods and durable uniqueness `(saga_id, execution_slice_hash)`.
- Produces:

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


class InMemoryHostDispatchIntentStore:
    ...
```

- [ ] **Step 1: Extract a backend-neutral contract harness RED**

Create `tests/execution_reconciliation/dispatch_intent_store_contract.py` with a function such as:

```python
def assert_dispatch_intent_store_contract(store, *, make_intent, clock):
    prepared = store.prepare(make_intent())
    assert store.prepare(make_intent()) == prepared
    assert store.get(prepared.dispatch_intent_id) == prepared
    assert store.get_for_saga_slice(
        prepared.saga_id,
        prepared.execution_slice_hash,
    ) == prepared
    ...
```

The same helper must exercise:

```text
prepare exact replay
same Saga/Slice with different lineage -> conflict
get(id)
exact get_for_saga_slice
DISPATCHED
OUTCOME_UNKNOWN
HOST_COMMITTED
SAFE_TO_RETRY
RECONCILED
CAS/revision conflict
```

Do not encode backend-specific SQL or private dictionaries in this helper.

- [ ] **Step 2: Add in-memory RED**

Create `tests/execution_reconciliation/test_dispatch_intent_store.py` and call the shared contract against `InMemoryHostDispatchIntentStore`.

Expected RED: public protocol/reference implementation does not exist.

- [ ] **Step 3: Add PostgreSQL exact-lookup RED to the existing CI-collected file**

Modify `tests/execution_reconciliation/test_postgres_dispatch_intent.py` to run the same shared contract against `PostgresHostDispatchIntentStore` under `DSP_TEST_POSTGRES_DSN`.

Also add an explicit terminal-independent lookup assertion:

```python
resolved = store.get_for_saga_slice(intent.saga_id, intent.execution_slice_hash)
assert resolved is not None
assert resolved.dispatch_intent_id == intent.dispatch_intent_id
```

The store API receives no Saga-active flag, so terminal state cannot suppress the row.

- [ ] **Step 4: Run RED**

```bash
uv run pytest tests/execution_reconciliation/test_dispatch_intent_store.py -q
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/execution_reconciliation/test_postgres_dispatch_intent.py -q
```

Expected: missing protocol/reference store and/or missing public `get_for_saga_slice()`.

- [ ] **Step 5: Implement shared public contract**

Create the public protocol and in-memory implementation. If transition validation is currently duplicated inside PostgreSQL methods, extract only the smallest owner-local pure helper needed so both backends enforce the same transition/CAS rules.

`get_for_saga_slice()` must implement:

```text
exact saga_id + exact execution_slice_hash
-> 0 or 1 row
```

It must never select latest/current and must never filter based on Saga status.

- [ ] **Step 6: Implement PostgreSQL public exact lookup**

`PostgresHostDispatchIntentStore.get_for_saga_slice()` may internally reuse its own existing private selector, but the private method remains an implementation detail. Callers import/use only the public contract.

- [ ] **Step 7: Run GREEN and parity regression**

```bash
uv run pytest \
  tests/execution_reconciliation/test_dispatch_intent_store.py \
  tests/execution_reconciliation/test_postgres_dispatch_intent.py \
  tests/execution_reconciliation/test_dispatch_intent.py \
  tests/execution_coordination/test_host_effect_crash_windows.py \
  tests/execution_coordination/test_unknown_outcome_recovery.py \
  -q

uv run ruff check \
  platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent_store.py \
  platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py \
  tests/execution_reconciliation/dispatch_intent_store_contract.py \
  tests/execution_reconciliation/test_dispatch_intent_store.py \
  tests/execution_reconciliation/test_postgres_dispatch_intent.py
```

- [ ] **Step 8: Commit Task 8.2**

```bash
git add \
  platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent_store.py \
  platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py \
  platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py \
  tests/execution_reconciliation/dispatch_intent_store_contract.py \
  tests/execution_reconciliation/test_dispatch_intent_store.py \
  tests/execution_reconciliation/test_postgres_dispatch_intent.py
git commit -m "feat: publish dispatch intent store contract"
```

---

### Task 8.3: Put Saga/dispatch recovery precedence in Execution Coordination

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/recovery.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Create: `tests/execution_coordination/test_task8_execution_recovery_projection.py`

**Interfaces:**
- Consumes: `StoredExecutionSagaV2`, `SliceReconciliationStateV2`, `HostDispatchIntent | None`, `HostDispatchStatus`.
- Produces an owner-neutral public projection surface. Freeze these exact names in this task:

```python
class ExecutionRecoveryDisposition(str, Enum):
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SAFE_TO_RETRY = "SAFE_TO_RETRY"


@dataclass(frozen=True, slots=True)
class ExecutionRecoveryProjection:
    disposition: ExecutionRecoveryDisposition | None


def project_execution_recovery(
    stored_saga: StoredExecutionSagaV2,
    execution_slice_hash: str,
    dispatch_intent: HostDispatchIntent | None,
) -> ExecutionRecoveryProjection:
    ...
```

`None` means no active unresolved Host-effect recovery. This type lives in Execution Coordination and must not import `design_orchestrator`.

- [ ] **Step 1: Write terminal-compatible REDs**

Add exact tests for the two review cases:

```text
Saga SUCCEEDED + Slice SUCCEEDED + dispatch HOST_COMMITTED
-> projection.disposition is None

Saga FAILED + Slice FAILED_BEFORE_COMMIT + dispatch SAFE_TO_RETRY
-> projection.disposition is None
-> durable intent remains SAFE_TO_RETRY
```

The second assertion reads the store separately; projection does not erase evidence.

- [ ] **Step 2: Write unresolved REDs**

For non-terminal Saga/Slice truth assert:

```text
OUTCOME_UNKNOWN -> OUTCOME_UNKNOWN
SAFE_TO_RETRY -> SAFE_TO_RETRY
PREPARED -> RECOVERY_REQUIRED
DISPATCHED -> RECOVERY_REQUIRED
HOST_COMMITTED -> RECOVERY_REQUIRED
RECONCILED -> None
```

Use real enums and real immutable contracts.

- [ ] **Step 3: Write conflict RED**

Construct a terminal Saga whose exact Slice is terminal but whose matching dispatch intent remains `OUTCOME_UNKNOWN`. Assert owner-level fail closed with the existing coordination error family/code; do not return `None` and do not pick a workflow route.

- [ ] **Step 4: Write exact-Slice RED**

Pass an execution slice hash not present in `stored_saga.definition.ordered_slice_hashes`. Assert owner integrity failure. Current workflow expects exactly one Slice later, but this owner helper still validates that the requested Slice is actually part of the Saga.

- [ ] **Step 5: Run RED**

```bash
uv run pytest tests/execution_coordination/test_task8_execution_recovery_projection.py -q
```

Expected: public projection types/function do not exist.

- [ ] **Step 6: Implement minimal projection by extracting existing semantics**

Reuse `_terminal_result`, `_project_result`, `UnknownOutcomeRecovery` semantics and current coordinator write ordering as the source of truth. The new helper must be read-only: it does not probe Host, mutate dispatch state, mutate Saga, run reconciliation, or call convergence.

Do not implement this matrix in `CanonicalWorkflowOwnerPorts`.

- [ ] **Step 7: Run GREEN + existing recovery regressions**

```bash
uv run pytest \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  tests/execution_coordination/test_unknown_outcome_recovery.py \
  tests/execution_coordination/test_phase_i_materialized_success.py \
  tests/execution_coordination/test_phase_i_materialized_divergence.py \
  tests/execution_coordination/test_phase_i_materialized_unknown_commit.py \
  -q

uv run ruff check \
  platform/execution_coordination/src/design_execution_coordination/recovery.py \
  tests/execution_coordination/test_task8_execution_recovery_projection.py
```

- [ ] **Step 8: Commit Task 8.3**

```bash
git add \
  platform/execution_coordination/src/design_execution_coordination/recovery.py \
  platform/execution_coordination/src/design_execution_coordination/__init__.py \
  tests/execution_coordination/test_task8_execution_recovery_projection.py
git commit -m "feat: expose execution recovery projection"
```

---

### Task 8.4: Wire real execution owners into CanonicalWorkflowOwnerPorts

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Create: `tests/orchestrator/test_canonical_owner_execution.py`
- Modify: `tests/architecture/test_real_owner_workflow_boundaries.py`

**Interfaces:**
- Consumes: Task 8.1 `provider_binding_store.get_by_hash()`, Task 8.2 `HostDispatchIntentStore`, Task 8.3 `project_execution_recovery()`, existing real `MaterializedExecutionSagaCoordinator`, `ExecutionReconciliationServiceV2`, `ExecutionSagaStoreV2`, Gateway V2 and convergence APIs.
- Produces working implementations of existing workflow-facing methods:

```python
def begin_execution(
    self,
    execution_plan_ref: StableRef,
    grant_ref: StableRef,
) -> str | AsyncOperationRef: ...


def get_execution_owner_state(self, saga_id: str) -> ExecutionOwnerView: ...


def verify_reconcile(self, saga_id: str) -> ExecutionOwnerView: ...
```

The constructor also receives a public `dispatch_intent_store` dependency. Do not add a private reverse index.

- [ ] **Step 1: Write real success RED**

Create `tests/orchestrator/test_canonical_owner_execution.py` using real:

```text
ExecutionReconciliationServiceV2
MaterializedExecutionSagaCoordinator
ExecutionSagaStoreV2
InMemoryHostDispatchIntentStore
CrossHostConvergenceVerifier
```

and only allowed Host/evidence/clock doubles.

Drive `begin_execution()` from exact execution-plan/grant refs and assert:

```python
saga_id = ports.begin_execution(execution_plan_ref, grant_ref)
assert isinstance(saga_id, str)
view = ports.get_execution_owner_state(saga_id)
assert view.saga.status == "SUCCEEDED"
assert view.active_dispatch_recovery is None
assert counting_host.execute_calls == 1
```

Also assert the matching durable dispatch row may still be `HOST_COMMITTED`; the adapter must consume Task 8.3 projection and still return terminal/no-active-recovery.

- [ ] **Step 2: Write DIVERGED RED**

Inject divergent canonical evidence only through the allowed evidence boundary. Assert:

```text
real convergence result = DIVERGED
real Saga status = DIVERGED
ExecutionOwnerView.saga.status = DIVERGED
active_dispatch_recovery = None
Host execute count = 1
no compensation call/surface
```

- [ ] **Step 3: Write unknown-outcome safe-wait RED**

Have the Host mutation boundary return `COMMIT_STATE_UNKNOWN`. Assert:

```text
durable Saga exists
durable dispatch intent = OUTCOME_UNKNOWN
begin_execution(...) -> AsyncOperationRef(kind=EXECUTION_JOB, owner="execution", operation_id=saga_id)
get_execution_owner_state(saga_id).active_dispatch_recovery.state = OUTCOME_UNKNOWN
Host execute count = 1
```

Call `begin_execution()` again for the same durable lineage and assert Host execute count remains `1`; existing coordinator replay/recovery semantics must prevent a second mutation command.

- [ ] **Step 4: Write Provider Binding hash-join negative**

Arrange a grant/authority whose `binding_set_hash` cannot be exactly resolved. Assert failure occurs before coordinator/Host execution. The test must not derive `PBSV2-<hash[:12]>` in the adapter fixture.

- [ ] **Step 5: Write architecture RED**

Extend `tests/architecture/test_real_owner_workflow_boundaries.py` to reject production adapter references to:

```text
provider binding `_items`
PostgresHostDispatchIntentStore private selectors such as `_select_by_slice`
manual `PBSV2-` hash-prefix derivation
adapter-local saga->dispatch or grant->binding dicts
adapter-local terminal/recovery status matrix
ScenarioOwners/test authority
V1 execution surfaces
```

- [ ] **Step 6: Run RED**

```bash
uv run pytest \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  -q
```

Expected: current `begin_execution()`, `get_execution_owner_state()`, and `verify_reconcile()` fail closed as not wired.

- [ ] **Step 7: Implement request assembly and projection consumption only**

`begin_execution()` must:

```text
resolve exact ExecutionPlanV2 by id/hash
resolve exact Gateway grant by grant_ref.content_hash
obtain admitted authority through Gateway public API
resolve binding set through provider_binding_store.get_by_hash(authority.binding_set_hash)
assert full binding hash equals authority.binding_set_hash
resolve exact ChangeSet / Approval Scope / MaterializationPlan
rebuild and hash-check convergence profile through public builder
call MaterializedExecutionSagaCoordinator.execute(...)
map only coordinator result shape to saga_id or execution AsyncOperationRef
```

`get_execution_owner_state()` must:

```text
load StoredExecutionSagaV2
require exactly one definition.ordered_slice_hashes entry for current workflow scope
read dispatch_intent_store.get_for_saga_slice(saga_id, exact_slice_hash)
call project_execution_recovery(...)
map the returned owner disposition to HostDispatchRecoveryView
```

`verify_reconcile()` must only re-read the same owner projection and require terminal/no-active-recovery. It must not run a second reconciler.

- [ ] **Step 8: Run GREEN**

```bash
uv run pytest \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  -q

uv run ruff check \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
```

- [ ] **Step 9: Commit Task 8.4**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
git commit -m "feat: wire real execution owner composition"
```

---

### Task 8.5: Atomically persist Saga identity with execution wait

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify: `tests/orchestrator/test_langgraph_graph.py`

**Interfaces:**
- Consumes: existing `AsyncOperationRef`, `AsyncOperationKind.EXECUTION_JOB`, existing `saga_id` graph state field.
- Produces: one atomic `apply_or_recover` node update that preserves durable Saga identity while entering `APPLY_WAIT`.

- [ ] **Step 1: Write execution-async atomic-state RED**

In `tests/orchestrator/test_langgraph_graph.py`, have `begin_execution()` return:

```python
AsyncOperationRef(
    kind=AsyncOperationKind.EXECUTION_JOB,
    owner="execution",
    operation_id="SAGA-123",
)
```

Assert one persisted node update contains:

```python
assert snapshot.values["saga_id"] == "SAGA-123"
assert snapshot.values["resume_node"] == "refresh_execution_owner"
assert snapshot.values["phase"] == WorkflowPhase.APPLY_WAIT.value
assert snapshot.values["async_operation_ref"]["operation_id"] == "SAGA-123"
```

- [ ] **Step 2: Write non-execution async negative**

Return an `AsyncOperationRef` of another allowed kind. Assert its `operation_id` is **not** copied into `saga_id`.

- [ ] **Step 3: Write resume/no-redispatch RED**

Resume from the saver-backed wait with durable `saga_id`. Make `get_execution_owner_state()` return active `OUTCOME_UNKNOWN` and assert:

```text
refresh_execution_owner -> RECOVER_OR_WAIT
begin_execution call count remains unchanged
Host/service mutation call count remains unchanged
```

The graph must re-read owner truth; it must not infer Host outcome from checkpoint position.

- [ ] **Step 4: Run RED**

```bash
uv run pytest tests/orchestrator/test_langgraph_graph.py -k "execution and saga" -q
```

Expected: current async branch stores wait navigation but does not persist Saga id.

- [ ] **Step 5: Implement minimal graph change**

Only for `EXECUTION_JOB` owned by `execution`, merge `saga_id=result.operation_id` into the same dict returned by `apply_or_recover`. Do not change graph topology or domain decision functions.

- [ ] **Step 6: Run GREEN + runtime regression**

```bash
uv run pytest \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_langgraph_runtime.py \
  -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py
```

- [ ] **Step 7: Commit Task 8.5**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py
git commit -m "fix: persist saga identity with execution wait"
```

---

### Task 8.6: Prove safe-wait boundary and close Task 8 on exact-head PostgreSQL evidence

**Files:**
- Modify tests only if a focused assertion is missing from Tasks 8.1–8.5.
- Inspect: `.github/workflows/durable-persistence.yml`
- Do not edit the workflow unless the exact current file no longer runs `tests/execution_reconciliation/test_postgres_dispatch_intent.py`.

**Interfaces:**
- Consumes: public `UnknownOutcomeRecovery.recover(...)`; Task 8 owner/store/wiring contracts.
- Produces: closure evidence only. It does not add autonomous recovery scheduling.

- [ ] **Step 1: Prove external recovery entrypoint remains mutation-safe**

Run the existing owner test plus the new projection tests:

```bash
uv run pytest \
  tests/execution_coordination/test_unknown_outcome_recovery.py \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  -q
```

Required evidence:

```text
UnknownOutcomeRecovery uses HostOutcomeProbe
UnknownOutcomeRecovery has no Host mutation port
OUTCOME_UNKNOWN can remain recovery when evidence is insufficient
SAFE_TO_RETRY / reconciled evidence can advance owner truth
```

Do not assert workflow-owned scheduling.

- [ ] **Step 2: Run full focused Task 8 suite**

```bash
uv run pytest \
  tests/provider_binding/test_task8_hash_lookup.py \
  tests/execution_reconciliation/test_dispatch_intent_store.py \
  tests/execution_reconciliation/test_postgres_dispatch_intent.py \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  tests/execution_coordination/test_unknown_outcome_recovery.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_langgraph_graph.py \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  -q
```

When running locally without PostgreSQL, a skip is permitted only for local development evidence. It does not close Task 8.

- [ ] **Step 3: Run owner regressions**

```bash
uv run pytest \
  tests/provider_binding \
  tests/execution_reconciliation \
  tests/execution_coordination \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/orchestrator/test_default_workflow_services.py \
  -q
```

- [ ] **Step 4: Run Ruff / diff whitespace**

```bash
uv run ruff check \
  platform/provider_binding/src/design_provider_binding \
  platform/execution_reconciliation/src/design_execution_reconciliation \
  platform/execution_coordination/src/design_execution_coordination \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/provider_binding/test_task8_hash_lookup.py \
  tests/execution_reconciliation \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_langgraph_graph.py \
  tests/architecture/test_real_owner_workflow_boundaries.py

git diff --check
```

Apply repository no-new-diagnostics policy if unrelated historical diagnostics remain; do not suppress new Task 8 diagnostics.

- [ ] **Step 5: Push exact Task 8 HEAD and verify designated PostgreSQL lane**

`durable-persistence.yml` currently defines PostgreSQL 17 job `execution-saga-postgres` and explicitly runs:

```text
tests/execution_reconciliation/test_postgres_dispatch_intent.py
```

Require that job on the exact Task 8 closing SHA to be:

```text
completed / success
new Task 8 PostgreSQL contract cases collected
new Task 8 PostgreSQL contract cases non-skipped
```

A workflow-level SUCCESS without evidence that the new cases were collected is insufficient; inspect job logs if needed.

- [ ] **Step 6: Task 8 closure record**

Record all of:

```text
Provider Binding exact full-hash success GREEN
same-first12/different-full-hash negative GREEN
in-memory dispatch store contract GREEN
PostgreSQL dispatch store contract non-skipped GREEN
SUCCEEDED + HOST_COMMITTED terminal projection GREEN
FAILED_BEFORE_COMMIT + SAFE_TO_RETRY terminal projection GREEN
terminal + incompatible OUTCOME_UNKNOWN conflict GREEN
real coordinator SUCCEEDED GREEN
real coordinator DIVERGED GREEN
unknown outcome -> execution AsyncOperationRef with durable saga_id GREEN
atomic saga_id + wait checkpoint GREEN
resume -> RECOVER_OR_WAIT with no redispatch GREEN
UnknownOutcomeRecovery external-entrypoint safety regression GREEN
architecture guard GREEN
exact-head designated PostgreSQL CI GREEN
```

Only then mark Task 8 CLOSED and continue to Task 9.

---

### Task 9: Add real-owner LangGraph E2E acceptance A–D/F/G plus safe-wait execution acceptance

**Files:**
- Create: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Modify: `tests/architecture/test_real_owner_workflow_boundaries.py`
- Do not delete/rewrite: `tests/orchestrator/test_workflow_end_to_end.py::_ScenarioOwners`

**Interfaces:**
- Consumes: closed Task 8 real execution composition and existing Task 6/7 real-owner path.
- Produces: one complete reference composition test module using real internal owners and only the approved environment doubles.

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
real HostDispatchIntentStore contract
real execution recovery projection
+ explicit deterministic environment/presentation boundaries only
```

- [ ] **Step 1: Happy-path RED A**

Drive one canonical operation through proposal HITL and approval to terminal `WorkflowPhase.COMPLETED`. Assert final `saga_id` resolves from the real Saga store and all final refs resolve through their authoritative stores.

- [ ] **Step 2: HITL RED B**

Assert proposal pause id is exact, stale/wrong pause resume is rejected, and ACCEPT continues into the same real-owner composition. Do not weaken existing HITL contract.

- [ ] **Step 3: Async freshness RED C**

Force semantic reconstruction async wait. On resume, assert the exact three-ref freshness tuple is newly persisted atomically and Impact consumes that exact tuple.

- [ ] **Step 4: Missing authoritative ref RED D**

Delete/remove one owner-local object after checkpoint, reconstruct the workflow runtime, and resume. Assert fail closed and zero downstream Host mutation calls. Do not reconstruct missing truth from checkpoint body.

- [ ] **Step 5: Unknown execution safe-wait RED**

Drive the real-owner flow until Host execute returns commit-state-unknown. Assert the saver-backed state contains:

```text
saga_id = durable Saga id
phase = APPLY_WAIT
resume_node = refresh_execution_owner
execution async ref.operation_id = same Saga id
```

Resume once and assert:

```text
owner read returns OUTCOME_UNKNOWN
workflow routes RECOVER_OR_WAIT
Host execute count remains exactly 1
```

Do not call `UnknownOutcomeRecovery` from workflow code in this test.

- [ ] **Step 6: Refs-only checkpoint RED F**

Inspect supported saver state after success and after unknown-outcome wait. Reject full owner bodies including:

```text
SemanticSnapshot
SnapshotSet
ImpactAnalysis
ApprovalScopeDefinitionV2 / ApprovalScopeBoundaryV2
CanonicalChangeSet
ApprovalRecord / ExecutionGrantV2
ExecutionPlanV2
ProviderBindingSetV2
StoredExecutionSagaV2
HostDispatchIntent
ActualDelta
```

Stable ids/refs/navigation and `saga_id` are allowed.

- [ ] **Step 7: Architecture RED/GREEN G**

The E2E module may not import/construct `_ScenarioOwners`, owner-private selectors/dicts, V1 execution surfaces, or a test-authored Saga/dispatch/recovery state machine.

- [ ] **Step 8: Run GREEN**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/orchestrator/test_real_owner_workflow_end_to_end.py -q
uv run pytest tests/architecture/test_real_owner_workflow_boundaries.py -q
uv run ruff check \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
```

- [ ] **Step 9: Commit Task 9**

```bash
git add \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
git commit -m "test: add real owner workflow end to end acceptance"
```

---

### Task 10: Prove durable safe-wait restart/no-double-Host behavior and close exact-head CI

**Files:**
- Modify: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Inspect: `.github/workflows/workflow-orchestrator.yml`
- Inspect: `.github/workflows/durable-persistence.yml`
- Inspect: `.github/workflows/phase-i-real-cross-host-materialization-saga.yml`
- Inspect: `.github/workflows/step37-cross-host-saga-failure-injection.yml`
- Inspect: `.github/workflows/repository-regression.yml`
- Modify CI only if exact current collection proves required tests are not scheduled.

**Interfaces:**
- Consumes: PostgreSQL workflow checkpoint/artifact stores, PostgreSQL Saga/dispatch stores, real Task 8 composition, public external `UnknownOutcomeRecovery`.
- Produces: durability evidence and final implementation closure. It does not add autonomous recovery scheduling.

- [ ] **Step 1: Write PostgreSQL restart/no-double-Host RED E**

Use real PostgreSQL for workflow checkpoint/artifact state plus Saga/dispatch persistence:

```text
runtime A reaches durable Saga + OUTCOME_UNKNOWN
Host execute count = 1
close/discard runtime A, checkpointer connection, artifact-store connection, Saga/store connection
construct runtime B with fresh connections/services over the same PostgreSQL data
resume same workflow
runtime B re-reads saga_id + exact dispatch owner truth
route = RECOVER_OR_WAIT
Host execute count remains 1
```

Do not share an in-memory Saga or dispatch store across runtime A/B.

- [ ] **Step 2: Prove external recovery advancement is observable, without claiming autonomous completion**

From the durable unknown state, invoke the existing public recovery owner explicitly from the test harness/composition boundary:

```python
result = unknown_outcome_recovery.recover(
    stored_saga=...,
    execution_slice=...,
    authority=...,
    binding_set=...,
    dispatch_intent=...,
)
```

Then construct/read through fresh workflow services again and assert they observe the updated authoritative Saga/dispatch truth.

The assertion must stop at what current owners actually guarantee. It may prove `SAFE_TO_RETRY`, reconciled Slice truth, or another durable projection depending on supplied HostOutcomeProbe evidence. It must **not** require workflow-owned scheduling or final convergence unless current owner semantics already produce that state without new production changes.

- [ ] **Step 3: Preserve fast scenario regression**

```bash
uv run pytest tests/orchestrator/test_workflow_end_to_end.py -q
```

`_ScenarioOwners` remains legal only for the fast orchestration regression.

- [ ] **Step 4: Run PostgreSQL capability suite locally/in CI-equivalent environment**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/orchestrator/test_artifact_postgres.py \
  tests/execution_reconciliation/test_postgres_dispatch_intent.py \
  tests/execution_reconciliation/test_postgres_saga_store_v2.py \
  tests/execution_coordination/test_host_effect_crash_windows.py \
  -q
```

PostgreSQL skips are acceptable for a developer machine only; they are not closure evidence.

- [ ] **Step 5: Run focused architecture and Ruff gate**

```bash
uv run pytest \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  tests/architecture/test_canonical_v2_boundaries.py \
  -q

uv run ruff check \
  platform/provider_binding/src/design_provider_binding \
  platform/execution_reconciliation/src/design_execution_reconciliation \
  platform/execution_coordination/src/design_execution_coordination \
  platform/orchestrator/src/design_orchestrator \
  tests/provider_binding/test_task8_hash_lookup.py \
  tests/execution_reconciliation \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py

git diff --check
```

- [ ] **Step 6: Scope audit before final push**

Compare the final implementation head against approved written-spec HEAD `41d763ada50ed50e9c3322d54e1879b170d5b3fe` and reject unrelated changes in:

```text
MCP/Agent front door
real AutoCAD/Revit acceptance
compensation executor
V1 retirement
new outbox/inbox/replay architecture
owner-wide PostgreSQL migration
unrelated dependency upgrades
support-matrix expansion
recovery scheduler/worker
generic materialized forward-resume/convergence continuation
```

Expected production responsibility changes are limited to the File Structure Freeze above plus any test-only compatibility edits directly caused by those public contracts.

- [ ] **Step 7: Push exact final HEAD and require repository CI**

Require all PR-triggered workflows for the exact final SHA to reach `completed / success`, with zero failure/in-progress/queued. At minimum inspect evidence for:

```text
Python 3.11 canonical repository regression
Python 3.14 repository regression
Ruff no-new-diagnostics / architecture gates
Workflow Orchestrator PostgreSQL lane
Durable persistence execution-saga-postgres PostgreSQL 17 lane
Phase I execution reconciliation / coordination regressions
Step37 failure-injection regression
.NET 10
Revit Core
```

For `execution-saga-postgres`, inspect logs and confirm the new Task 8 PostgreSQL dispatch contract cases were collected and were **not skipped**.

- [ ] **Step 8: Final closure evidence**

Record:

```text
Task 8 exact owner API/parity evidence
Task 9 A–D/F/G real-owner E2E evidence
unknown-outcome safe-wait E2E evidence
PostgreSQL fresh-runtime no-double-Host evidence
external UnknownOutcomeRecovery advancement observable after fresh read
no claim of autonomous recovery scheduler or guaranteed final convergence
fast _ScenarioOwners regression preserved
scope audit clean
all exact-head CI workflows success
```

Only then mark the implementation phase CLOSED. Merge/merged-main observation/lifecycle closeout remain separate gates under the baseline plan.

---

## Acceptance Matrix

| Approved requirement | Plan evidence |
| --- | --- |
| Provider Binding exact hash lookup | Task 8.1 |
| Full hash equality, including same-first12 collision-shaped negative | Task 8.1 |
| Public dispatch-intent store contract | Task 8.2 |
| In-memory/PostgreSQL parity | Task 8.2 + Task 8.6 exact-head PostgreSQL lane |
| Exact Saga/Slice lookup not filtered by active state | Task 8.2 + Task 8.4 |
| Saga/dispatch precedence owned outside adapter | Task 8.3 + architecture guard |
| `SUCCEEDED + HOST_COMMITTED` terminal | Task 8.3 + Task 8.4 |
| `FAILED_BEFORE_COMMIT + SAFE_TO_RETRY` terminal while evidence remains durable | Task 8.3 |
| incompatible terminal `OUTCOME_UNKNOWN` fails closed | Task 8.3 |
| Real Saga success | Task 8.4 |
| Real DIVERGED without compensation | Task 8.4 |
| Unknown outcome persists and never blindly redispatches | Task 8.4 / 8.5 / 9 / 10 |
| Saga id + execution wait atomic checkpoint | Task 8.5 |
| Task 8 safe-wait boundary explicit | Task 8.6 |
| `UnknownOutcomeRecovery` remains explicit external recovery entrypoint | Task 8.6 + Task 10 |
| Real-owner E2E A–D/F/G | Task 9 |
| Durable PostgreSQL fresh-runtime no-double-Host proof | Task 10 |
| PostgreSQL formal closure non-skipped | Task 8.6 + Task 10 |
| Exact-head repository regression | Task 10 |

---

## STOP Conditions

Stop implementation and return to Design/Plan if any of these are proven by RED/repository facts:

```text
Provider Binding owner cannot provide exact full-hash lookup without changing its identity contract beyond this spec.
Dispatch intent uniqueness is not actually saga_id + execution_slice_hash.
PostgreSQL and in-memory transition semantics cannot share the public contract without a broader persistence redesign.
Execution Coordination cannot determine the approved terminal/recovery combinations from existing durable Saga/Slice/dispatch truth.
Canonical begin_execution cannot reconstruct coordinator inputs through public owner APIs without a new reverse index or private cache.
Task 7 exactly-one-slice assumption is no longer true on the implementation HEAD.
LangGraph cannot atomically persist saga_id with the execution wait using the existing state/checkpointer model.
Formal PostgreSQL CI cannot execute the new contract cases non-skipped without a CI architecture change.
A requirement would need autonomous recovery scheduling or generic materialized forward-resume/convergence continuation.
```

Do not manufacture GREEN by adding adapter-private maps, choosing latest/current rows, deriving owner ids from hash prefixes in the adapter, weakening full-hash equality, treating timeout as proof of non-commit, or relabeling safe wait as complete recovery.

---

## Written-Plan Gate

This plan is the implementation authority for Amendment B only after human written-plan review approval.

Before approval:

```text
Task 8 product implementation FORBIDDEN
Task 9 implementation FORBIDDEN
Task 10 implementation FORBIDDEN
Task 7 baseline MUST NOT be rolled back
```

After approval, execute strictly:

```text
Task 8.1 Provider Binding exact hash RED/GREEN
→ Task 8.2 dispatch store public contract + in-memory/PostgreSQL parity RED/GREEN
→ Task 8.3 execution recovery projection RED/GREEN
→ Task 8.4 canonical execution-owner wiring RED/GREEN
→ Task 8.5 atomic Saga-id wait RED/GREEN
→ Task 8.6 focused + exact-head PostgreSQL closure
→ Task 8 CLOSED
→ Task 9 real-owner E2E acceptance
→ Task 10 PostgreSQL fresh-runtime durability + exact-head repository closure
```
