# Task 8 Execution Owner Lookup Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Every production change follows RED → verify RED → minimal GREEN → focused verification → commit. Do not collapse gates.

**Status:** Proposed — written-plan re-review pending

**Goal:** Complete Task 8 real execution-owner wiring without duplicating authoritative owner semantics: add exact Provider Binding hash lookup, publish one durable Host dispatch-intent store contract with in-memory/PostgreSQL parity, expose owner-owned Saga/dispatch recovery projection, wire real Saga/coordination/reconciliation into `CanonicalWorkflowOwnerPorts`, atomically persist Saga identity with execution wait, then complete the baseline real-owner E2E including a supported cross-runtime recovery point that reaches terminal state without a second Host mutation.

**Architecture:** `CanonicalWorkflowOwnerPorts` remains a composition adapter. Provider Binding owns binding-set identity lookup. Execution Reconciliation owns dispatch-intent persistence and transitions. Execution Coordination owns interpretation of Saga + dispatch evidence. LangGraph owns only workflow navigation/checkpoint state. Task 8 adds **safe-wait integration** for unknown Host outcomes; it does not add an autonomous recovery scheduler. This limitation does **not** weaken baseline Task 10 acceptance: at least one already-supported runtime/process recovery point must still resume through fresh runtime/services, avoid duplicate Host execution, and reach terminal workflow state.

**Tech Stack:** Python 3.11 / 3.14, LangGraph 1.2.x, `langgraph-checkpoint-postgres` 3.x, PostgreSQL 17, pytest, Ruff, GitHub Actions. No dependency upgrade is authorized.

**Approved design spec:** `docs/superpowers/specs/2026-09-23-task8-execution-owner-lookup-amendment-design.md`

**Approved written-spec HEAD:** `41d763ada50ed50e9c3322d54e1879b170d5b3fe`

**Baseline implementation plan:** `docs/superpowers/plans/2026-09-20-real-owner-e2e-workflow.md`

**Rejected plan revision:** `43e028508952ca2aedc204d5d5d41f8718c07a8b`

---

## Review Revision Record

This revision addresses the three findings raised against `43e02850…`.

1. **Baseline Task 10 terminal recovery is restored.** Unknown-outcome safe wait and explicit `UnknownOutcomeRecovery.recover()` observability are supplemental acceptance. They do not replace baseline acceptance E. Task 10 now pins an existing supported recovery point: process loss after real `begin_execution()` has durably completed the Saga but before the LangGraph node update is committed. A fresh runtime must replay the same execution lineage, observe the existing terminal Saga before Host dispatch, keep total Host execute count at one, and reach terminal workflow state. If implementation facts disprove this recovery point and no other existing supported point satisfies baseline E, stop for Design amendment; do not lower acceptance.
2. **Shared dispatch-store tests consume real Saga lineage.** The backend-neutral contract no longer invents `SAGA-*` parent ids. Each backend fixture supplies an intent factory derived from `build_saga_v2_contract_fixture()`. The PostgreSQL fixture first creates the exact parent Saga with `PostgresExecutionSagaStoreV2.create_saga()`, preserving the real foreign key and owner constraints. The in-memory backend uses the same legal fixture lineage.
3. **Recovery projection now has a complete decision contract for the reviewed gaps.** The plan explicitly covers `dispatch_intent is None`, exact Saga/Slice/grant/binding/Host lineage mismatch, terminal precedence, and `RECONCILED + nonterminal Saga`. The last case must expose no active Host-effect recovery but must still route `RECOVER_OR_WAIT` from the nonterminal Saga status; it may neither redispatch nor claim completion.

---

## Current Checkpoint

```text
branch: feat/capability-real-owner-e2e-workflow
approved spec head: 41d763ada50ed50e9c3322d54e1879b170d5b3fe
Task 7: CLOSED
Task 8 product implementation: NOT STARTED
Task 9 product/test implementation: NOT STARTED
Task 10 product/test implementation: NOT STARTED
```

The currently unwired execution seam remains:

```text
CanonicalWorkflowOwnerPorts.begin_execution
CanonicalWorkflowOwnerPorts.get_execution_owner_state
CanonicalWorkflowOwnerPorts.verify_reconcile
```

`durable-persistence.yml` already owns PostgreSQL 17 job `execution-saga-postgres` and already executes `tests/execution_reconciliation/test_postgres_dispatch_intent.py`. No CI workflow edit is authorized by default. New PostgreSQL parity assertions must live in that already-collected test surface.

---

## Global Constraints

- Task 7 remains CLOSED and must not be rolled back.
- `CanonicalWorkflowOwnerPorts` may assemble requests and consume public read models; it must not own Provider Binding identity rules, dispatch transition rules, Saga/dispatch precedence, reconciliation, convergence, or retry policy.
- `get_by_hash(binding_set_hash)` validates canonical lowercase SHA-256 and proves `returned.binding_set_hash == requested_binding_set_hash` before returning.
- Same-first-12-hex/different-full-hash must fail closed. Matching a short content-addressed id is not exact identity evidence.
- Malformed binding hashes retain owner digest validation (`ValueError`). Missing exact artifacts use `PROVIDER_BINDING_SET_REFERENCE_NOT_FOUND`. Short-id collision/full-hash mismatch uses existing owner code `PROVIDER_BINDING_INTEGRITY_INVALID`.
- `HostDispatchIntentStore.get_for_saga_slice(saga_id, execution_slice_hash)` is exact owner lookup. It never selects latest/current and never filters by active/terminal Saga state.
- In-memory and PostgreSQL dispatch stores implement one public contract with the same replay and CAS semantics.
- PostgreSQL shared-contract tests must preserve the real `host_dispatch_intent.saga_id` foreign key by creating the parent Saga first.
- Formal Task 8 closure requires new PostgreSQL contract cases to be collected, non-skipped, and green on the exact Task 8 closing SHA.
- Current workflow scope remains exactly one `ExecutionSliceV2`; multi-slice workflow expansion is out of scope.
- Saga/dispatch precedence belongs to Execution Coordination. The orchestrator adapter does not encode a private status matrix.
- Recovery projection validates exact Saga/Slice identity and, once admitted lineage exists, exact grant/binding/Host identity.
- Terminal Saga plus incompatible unresolved dispatch evidence fails closed with `CoordinationError.code == "HOST_RECOVERY_EVIDENCE_CONFLICT"`.
- `UnknownOutcomeRecovery.recover()` remains the explicit external unknown-outcome recovery entrypoint. Task 8 does not add a scheduler/worker and does not claim generic forward-resume/convergence continuation.
- The safe-wait limitation above applies to unknown-outcome progression only; it does not cancel baseline Task 10 cross-runtime terminal recovery acceptance at an already-supported recovery point.
- When `begin_execution()` returns an execution `AsyncOperationRef`, graph state atomically persists its `operation_id` as `saga_id` together with async ref, resume node, and `APPLY_WAIT` phase.
- Checkpoints contain ids/refs/navigation only. They do not become truth for `HostDispatchIntent`, `StoredExecutionSagaV2`, `ProviderBindingSetV2`, `ExecutionPlanV2`, `ActualDelta`, or other owner bodies.
- Deterministic doubles are limited to true environment boundaries: Host readiness, Host execute/read-back, Host outcome probe, verification/convergence evidence IO, runtime/provider observation, preview/HITL evidence, clock, and explicit test-only process-loss injection.
- Process-loss injection may interrupt the workflow boundary but may not fabricate or mutate owner truth.
- No new compensation behavior, V1 revival, owner-private lookup, adapter-private lineage cache, outbox/inbox architecture, owner-wide PostgreSQL migration, real AutoCAD/Revit acceptance, MCP front door, support-matrix expansion, recovery scheduler, or generic forward-resume engine.
- New Python code uses complete Chinese comments/docstrings and current repository Ruff conventions.

---

## Review Focus

1. **Full-hash identity:** first-12 equality never substitutes for full 64-character digest equality.
2. **Real PostgreSQL lineage:** shared store tests use a real persisted parent Saga; FK failure must not mask the API under test.
3. **No-intent semantics:** owner projection distinguishes legal pre-dispatch absence from evidence loss after a Host-effect state.
4. **Cross-lineage rejection:** wrong Saga, Slice, grant, binding, or Host evidence fails closed.
5. **Residual terminal evidence:** compatible `HOST_COMMITTED`, `RECONCILED`, or `SAFE_TO_RETRY` evidence does not mechanically create active recovery after terminal Saga/Slice truth.
6. **Nonterminal reconciled window:** `RECONCILED + nonterminal Saga` never redispatches and never reports terminal completion.
7. **Unknown-outcome replay:** durable Saga + `OUTCOME_UNKNOWN` never creates a second Host mutation command.
8. **Baseline durability E:** one supported process-loss recovery point must use a fresh runtime/services, keep Host execute count at one, and reach terminal workflow state.
9. **PostgreSQL parity:** in-memory GREEN alone cannot close Task 8.
10. **Dependency ownership:** reference composition explicitly injects the same logical dispatch-intent store used by the coordinator and the approved execution-recovery projection callable/service.

---

## Supersession Boundary

This Amendment supersedes only baseline Task 8/9/10 implementation details that conflict with the approved owner-API/safe-wait design. It does **not** supersede baseline acceptance E or H.

The following old implementation assumptions are superseded:

```text
Task 8 can use the concrete dispatch-intent surface without a public store contract.
Task 8 may derive Provider Binding identity from binding_set_hash inside the adapter.
Task 8 may classify Saga/dispatch recovery combinations inside the adapter.
Task 8 unknown outcome may resume without atomically retaining durable saga_id.
```

The following baseline acceptance remains authoritative:

```text
E. cross an existing supported runtime/process recovery point
   -> fresh runtime/services
   -> same durable execution lineage
   -> no second Host execution
   -> terminal workflow result

H. PostgreSQL + repository exact-head regression GREEN
```

Unknown-outcome acceptance added by this Amendment is separate:

```text
OUTCOME_UNKNOWN
-> durable saga_id + async wait
-> fresh runtime re-reads authoritative owner truth
-> RECOVER_OR_WAIT
-> no blind redispatch
-> optional explicit external UnknownOutcomeRecovery progression is observable
```

That supplemental path is not allowed to be presented as a substitute for baseline E.

---

## File Structure Freeze

| File | Responsibility |
| --- | --- |
| `platform/provider_binding/src/design_provider_binding/store_v2.py` | Exact owner-local `get_by_hash()` + full-hash equality |
| `platform/provider_binding/src/design_provider_binding/__init__.py` | Export approved V2 store surface only if required |
| `platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent_store.py` | Public `HostDispatchIntentStore` protocol + in-memory reference implementation |
| `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py` | Public exact Saga/Slice lookup on existing durable store |
| `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py` | Package-root public exports |
| `platform/execution_coordination/src/design_execution_coordination/recovery.py` | Read-only Saga/dispatch recovery projection; preserve `UnknownOutcomeRecovery` semantics |
| `platform/execution_coordination/src/design_execution_coordination/__init__.py` | Export approved recovery projection surface |
| `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py` | Public-owner request assembly + injected recovery projection consumption |
| `platform/orchestrator/src/design_orchestrator/langgraph_graph.py` | Atomic Saga id + execution-wait navigation |
| `tests/provider_binding/test_task8_hash_lookup.py` | Exact/full-hash lookup contract |
| `tests/execution_reconciliation/dispatch_intent_store_contract.py` | Backend-neutral shared store assertions; consumes backend-provided real-lineage factory |
| `tests/execution_reconciliation/test_dispatch_intent_store.py` | In-memory shared contract using real Saga fixture lineage |
| `tests/execution_reconciliation/test_postgres_dispatch_intent.py` | PostgreSQL shared contract; creates real Saga parent before intent |
| `tests/execution_coordination/test_task8_execution_recovery_projection.py` | Complete reviewed recovery projection matrix and lineage negatives |
| `tests/orchestrator/test_canonical_owner_execution.py` | Real Saga/coordinator execution + nonterminal routing/no-redispatch assertions |
| `tests/orchestrator/test_canonical_owner_ports.py` | Constructor shape + explicit dependency composition regression |
| `tests/orchestrator/test_langgraph_graph.py` | Atomic Saga id/wait and saver-backed resume routing |
| `tests/orchestrator/test_real_owner_workflow_end_to_end.py` | Real-owner LangGraph acceptance, supported terminal recovery point, unknown safe wait |
| `tests/architecture/test_real_owner_workflow_boundaries.py` | No private lookup/maps/status matrix/V1/test authority |
| `.github/workflows/durable-persistence.yml` | Inspect only by default; PostgreSQL 17 already collects `test_postgres_dispatch_intent.py` |
| other existing CI workflow files listed in Task 10 | Inspect before any edit; edit only if exact collection proves a required acceptance is unscheduled |

If implementation proves a required **production** file outside this table is necessary, stop and amend Design/Plan before editing it.

---

# Task 8

## Task 8.1 — Add exact Provider Binding full-hash lookup

**Files**

- Modify `platform/provider_binding/src/design_provider_binding/store_v2.py`
- Modify `platform/provider_binding/src/design_provider_binding/__init__.py` only if package-root export changes
- Create `tests/provider_binding/test_task8_hash_lookup.py`

### Step 1: Write RED — exact hash success

Use real V2 builders from `tests.provider_binding._support`:

```python
binding_set = resolve_provider_bindings_v2(
    slices["autocad"],
    snapshots["autocad"],
)
store = InMemoryProviderBindingSetV2Store()
store.put(binding_set)
resolved = store.get_by_hash(binding_set.binding_set_hash)
assert resolved == binding_set
assert resolved.binding_set_hash == binding_set.binding_set_hash
```

### Step 2: Write RED — same short id, different full hash

Build a real binding set, then use `dataclasses.replace()` only to isolate the owner-local lookup contract:

```python
stored_hash = "a" * 12 + "2" * 52
requested_hash = "a" * 12 + "1" * 52
collision = replace(
    original,
    binding_set_id=f"PBSV2-{stored_hash[:12]}",
    binding_set_hash=stored_hash,
)
store.put(collision)

with pytest.raises(ProviderBindingError) as exc_info:
    store.get_by_hash(requested_hash)
assert exc_info.value.code == "PROVIDER_BINDING_INTEGRITY_INVALID"
```

### Step 3: Write RED — malformed and unresolved hashes

```python
@pytest.mark.parametrize("value", ["", "A" * 64, "a" * 63, "g" * 64])
def test_get_by_hash_rejects_noncanonical_digest(value: str) -> None:
    with pytest.raises(ValueError):
        InMemoryProviderBindingSetV2Store().get_by_hash(value)


def test_get_by_hash_reports_missing_exact_artifact() -> None:
    with pytest.raises(ProviderBindingError) as exc_info:
        InMemoryProviderBindingSetV2Store().get_by_hash("b" * 64)
    assert exc_info.value.code == "PROVIDER_BINDING_SET_REFERENCE_NOT_FOUND"
```

### Step 4: Verify RED

```bash
uv run pytest tests/provider_binding/test_task8_hash_lookup.py -q
```

Expected: `get_by_hash()` does not exist.

### Step 5: Minimal GREEN

Implement canonical digest validation and owner-local lookup. Before returning:

```python
_validate_reference(binding_set)
if binding_set.binding_set_hash != requested_hash:
    raise ProviderBindingError(
        "PROVIDER_BINDING_INTEGRITY_INVALID",
        "ProviderBindingSetV2 full hash does not match requested owner hash",
    )
return binding_set
```

The orchestrator never derives `PBSV2-<hash[:12]>` and never reads `_items`.

### Step 6: Verify GREEN

```bash
uv run pytest tests/provider_binding/test_task8_hash_lookup.py tests/provider_binding -q
uv run ruff check \
  platform/provider_binding/src/design_provider_binding/store_v2.py \
  tests/provider_binding/test_task8_hash_lookup.py
```

### Step 7: Commit

```bash
git status --short
git add \
  platform/provider_binding/src/design_provider_binding/store_v2.py \
  tests/provider_binding/test_task8_hash_lookup.py
git commit -m "feat: add exact provider binding hash lookup"
```

If `design_provider_binding/__init__.py` actually changed, inspect and stage it explicitly.

---

## Task 8.2 — Publish one HostDispatchIntentStore contract and prove in-memory/PostgreSQL parity

**Files**

- Create `platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent_store.py`
- Modify `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py`
- Modify `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create `tests/execution_reconciliation/dispatch_intent_store_contract.py`
- Create `tests/execution_reconciliation/test_dispatch_intent_store.py`
- Modify `tests/execution_reconciliation/test_postgres_dispatch_intent.py`

**Public contract**

```text
prepare(intent) -> HostDispatchIntent
get(dispatch_intent_id) -> HostDispatchIntent | None
get_for_saga_slice(saga_id, execution_slice_hash) -> HostDispatchIntent | None
mark_dispatched(dispatch_intent_id, expected_revision, observed_at) -> HostDispatchIntent
mark_outcome_unknown(dispatch_intent_id, expected_revision, failure_ref, observed_at) -> HostDispatchIntent
mark_host_committed(dispatch_intent_id, expected_revision, evidence_hash, observed_at) -> HostDispatchIntent
mark_safe_to_retry(dispatch_intent_id, expected_revision, evidence_ref, observed_at) -> HostDispatchIntent
mark_reconciled(dispatch_intent_id, expected_revision, evidence_hash, observed_at) -> HostDispatchIntent
```

### Step 1: RED fixture contract — backend provides legal Saga lineage

`dispatch_intent_store_contract.py` must **not** synthesize its own Saga id. Define shared assertions to accept an intent factory:

```text
assert_lookup_and_replay_contract(store, intent_factory)
assert_unknown_contract(store, intent_factory)
assert_committed_reconciled_contract(store, intent_factory)
assert_safe_retry_contract(store, intent_factory)
assert_lineage_conflict_contract(store, intent_factory)
assert_cas_conflict_contract(store, intent_factory)
```

Freeze the factory contract:

```text
intent_factory(*, index: int = 0, grant_hash: str | None = None,
               binding_set_hash: str | None = None) -> HostDispatchIntent
```

Every factory call derives `saga_id`, `execution_slice_hash`, Host identity, document identity, and default grant/binding hashes from `build_saga_v2_contract_fixture()`; overrides are only for an intentional same-Saga/Slice lineage conflict.

Each shared assertion runs against a **fresh backend fixture**, so one test's transitions never contaminate another.

### Step 2: In-memory backend fixture

`tests/execution_reconciliation/test_dispatch_intent_store.py` uses:

```text
ctx, definition = build_saga_v2_contract_fixture()
store = InMemoryHostDispatchIntentStore()
intent_factory = factory bound to ctx + definition
```

Even though in-memory has no FK, it uses the same legal lineage shape as PostgreSQL.

### Step 3: PostgreSQL backend fixture with real parent Saga

Reuse the existing PostgreSQL setup pattern:

```python
dsn = require_postgres_dsn()
apply_execution_saga_postgres_migrations(dsn)
ctx, definition = build_saga_v2_contract_fixture()

saga_store = PostgresExecutionSagaStoreV2(dsn)
saga_store.create_saga(definition, created_at=ctx["t0"])
saga_store.close()

dispatch_store = PostgresHostDispatchIntentStore(dsn)
intent_factory = factory_bound_to(ctx, definition)
```

The factory must emit:

```text
intent.saga_id == definition.saga_id
intent.execution_slice_hash == definition.ordered_slice_hashes[index]
```

The shared contract therefore tests the public store API under the real `host_dispatch_intent.saga_id` foreign key instead of failing first on a fabricated parent id.

### Step 4: Shared RED cases

The exact shared cases are:

```text
exact prepare + replay
get(id)
get_for_saga_slice(exact saga, exact slice)
row remains lookup-visible after non-PREPARED transition
DISPATCHED -> OUTCOME_UNKNOWN
DISPATCHED -> HOST_COMMITTED -> RECONCILED
DISPATCHED -> SAFE_TO_RETRY
same Saga/Slice + different grant/binding lineage -> DISPATCH_INTENT_CONFLICT
stale expected_revision -> DISPATCH_INTENT_CONFLICT
```

No shared assertion reads SQL tables or private in-memory dictionaries.

### Step 5: Verify RED

```bash
uv run pytest tests/execution_reconciliation/test_dispatch_intent_store.py -q
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/execution_reconciliation/test_postgres_dispatch_intent.py -q
```

Expected RED must be missing public protocol/reference store and/or missing public `get_for_saga_slice()`, **not** a PostgreSQL FK violation.

### Step 6: Minimal GREEN — public protocol and in-memory owner

Create `dispatch_intent_store.py` with exact private indexes:

```text
dispatch_intent_id -> HostDispatchIntent
(saga_id, execution_slice_hash) -> dispatch_intent_id
```

`prepare()` preserves exact replay and rejects changed admitted lineage. All transitions enforce CAS revision and return a new immutable intent revision. Any shared validation helper stays inside `design_execution_reconciliation` and is reused by both backends.

### Step 7: Minimal GREEN — PostgreSQL exact lookup

Add public:

```text
PostgresHostDispatchIntentStore.get_for_saga_slice(saga_id, execution_slice_hash)
```

It validates inputs, opens the existing transaction boundary, calls `_select_by_slice()` only internally, and decodes zero/one row. No active-Saga predicate and no latest/current selection.

### Step 8: Verify GREEN + parity

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

### Step 9: Commit

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

## Task 8.3 — Freeze complete owner-level Saga/dispatch recovery projection

**Files**

- Modify `platform/execution_coordination/src/design_execution_coordination/recovery.py`
- Modify `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Create `tests/execution_coordination/test_task8_execution_recovery_projection.py`

**Public projection**

```python
class ExecutionRecoveryDisposition(str, Enum):
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SAFE_TO_RETRY = "SAFE_TO_RETRY"


@dataclass(frozen=True, slots=True)
class ExecutionRecoveryProjection:
    disposition: ExecutionRecoveryDisposition | None
```

```text
project_execution_recovery(
    stored_saga: StoredExecutionSagaV2,
    execution_slice_hash: str,
    dispatch_intent: HostDispatchIntent | None,
) -> ExecutionRecoveryProjection
```

`None` means **no active unresolved Host-effect recovery**. It does not mean the Saga is complete and it does not authorize Host dispatch.

### Step 1: RED — exact requested Slice

The requested `execution_slice_hash` must occur exactly once in `stored_saga.definition.ordered_slice_hashes` and exactly once in `stored_saga.slice_states`.

Missing/ambiguous Slice:

```text
-> CoordinationError.code == SAGA_INTEGRITY_INVALID
```

### Step 2: RED — intent identity and admitted-lineage validation

When `dispatch_intent` exists, require:

```text
dispatch_intent.saga_id == stored_saga.definition.saga_id
dispatch_intent.execution_slice_hash == requested execution_slice_hash
```

When the exact Slice state has admitted lineage fields, also require:

```text
dispatch_intent.grant_hash == slice_state.grant_hash
dispatch_intent.binding_set_hash == slice_state.binding_set_hash
dispatch_intent.host_instance_id == slice_state.admitted_host_instance_id
```

Add one RED for each mismatch:

```text
wrong Saga
wrong Slice
wrong grant hash
wrong binding-set hash
wrong Host instance
```

Every mismatch fails with:

```text
CoordinationError.code == HOST_RECOVERY_EVIDENCE_CONFLICT
```

No adapter-level check duplicates this matrix.

### Step 3: RED — `dispatch_intent is None` matrix

Freeze these owner decisions from the current coordinator write order:

| Slice durable state | Intent absent | Projection |
| --- | --- | --- |
| `NOT_STARTED` | legal: Host command has not been prepared | `None` |
| `ADMISSION_RESERVED` | legal crash window before durable intent creation | `RECOVERY_REQUIRED` |
| `ADMITTED` | legal crash window before durable intent creation | `RECOVERY_REQUIRED` |
| `BLOCKED` | legal no-Host-effect terminal/blocking state | `None` |
| `HOST_COMMITTED` | incompatible: current write order requires an intent | `HOST_RECOVERY_EVIDENCE_CONFLICT` |
| `RECONCILING` | incompatible: current write order requires an intent | `HOST_RECOVERY_EVIDENCE_CONFLICT` |
| `SUCCEEDED` | incompatible evidence loss | `HOST_RECOVERY_EVIDENCE_CONFLICT` |
| `FAILED_BEFORE_COMMIT` | incompatible evidence loss | `HOST_RECOVERY_EVIDENCE_CONFLICT` |
| `SCOPE_BREACH` | incompatible evidence loss | `HOST_RECOVERY_EVIDENCE_CONFLICT` |
| `VERIFY_FAILED` | incompatible evidence loss | `HOST_RECOVERY_EVIDENCE_CONFLICT` |

The test must construct real immutable Saga/Slice state fixtures; it must not bypass dataclass invariants with private mutation.

### Step 4: RED — nonterminal intent matrix

For exact, lineage-compatible, nonterminal owner truth:

| Dispatch status | Projection |
| --- | --- |
| `PREPARED` | `RECOVERY_REQUIRED` |
| `DISPATCHED` | `RECOVERY_REQUIRED` |
| `OUTCOME_UNKNOWN` | `OUTCOME_UNKNOWN` |
| `HOST_COMMITTED` | `RECOVERY_REQUIRED` |
| `SAFE_TO_RETRY` | `SAFE_TO_RETRY` |
| `RECONCILED` | `None` |

`RECONCILED -> None` means the Host-effect ambiguity has been resolved. The Saga remains authoritative for whether workflow execution is still active or terminal.

### Step 5: RED — terminal precedence and conflict

Pin at least these combinations:

```text
Saga SUCCEEDED + Slice SUCCEEDED + exact HOST_COMMITTED
-> None

Saga SUCCEEDED + Slice SUCCEEDED + exact RECONCILED
-> None

Saga FAILED + Slice FAILED_BEFORE_COMMIT + exact SAFE_TO_RETRY
-> None
-> store still returns SAFE_TO_RETRY

terminal Saga + terminal Slice + OUTCOME_UNKNOWN
-> HOST_RECOVERY_EVIDENCE_CONFLICT

terminal Saga + terminal Slice + PREPARED or DISPATCHED
-> HOST_RECOVERY_EVIDENCE_CONFLICT
```

For post-commit terminal Slice states (`SUCCEEDED`, `SCOPE_BREACH`, `VERIFY_FAILED`) an exact residual `HOST_COMMITTED` or `RECONCILED` row is read evidence, not an instruction to redispatch. For `FAILED_BEFORE_COMMIT`, `SAFE_TO_RETRY` is the compatible terminal evidence. Other impossible backward combinations fail closed.

### Step 6: RED — `RECONCILED + nonterminal Saga` is neither redispatch nor completion

Construct the legitimate write-order window:

```text
Saga status = EXECUTING or CONVERGENCE_PENDING
exact Slice is still nonterminal/reconciling
exact dispatch intent = RECONCILED
```

Owner projection:

```text
projection.disposition is None
```

Then, in `tests/orchestrator/test_canonical_owner_execution.py` or the existing nearest workflow routing test, feed the resulting `ExecutionOwnerView` to `decide_apply_resume()` with a checkpoint containing the same `saga_id` and assert:

```text
route == RECOVER_OR_WAIT
route != MAY_DISPATCH
route != TERMINAL_EXECUTION_STATE
```

Also assert no `begin_execution()`/Host mutation call occurs during that refresh decision. This explicitly proves that `None` recovery disposition is not treated as completion and nonterminal Saga truth still blocks redispatch.

### Step 7: Verify RED

```bash
uv run pytest \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  -q
```

Expected: public projection is missing; integration cases cannot yet be satisfied by real owner wiring.

### Step 8: Minimal GREEN

Implement a read-only projection in Execution Coordination. It may reuse package-private helpers such as exact Slice lookup and existing terminal status definitions, but it must not:

```text
probe Host
mutate dispatch intent
mutate Saga
run reconciliation
run convergence
schedule retry
import design_orchestrator
```

Order of evaluation is frozen:

```text
1. validate exact Slice membership
2. validate intent Saga/Slice identity if intent exists
3. validate grant/binding/Host lineage when Slice admission evidence exists
4. classify legal/illegal absent-intent state
5. apply compatible terminal Saga/Slice precedence
6. reject incompatible terminal unresolved evidence
7. classify remaining nonterminal dispatch status
```

### Step 9: Verify GREEN + owner regressions

```bash
uv run pytest \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  tests/execution_coordination/test_unknown_outcome_recovery.py \
  tests/execution_coordination/test_phase_i_materialized_success.py \
  tests/execution_coordination/test_phase_i_materialized_divergence.py \
  tests/execution_coordination/test_phase_i_materialized_unknown_commit.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  -q

uv run ruff check \
  platform/execution_coordination/src/design_execution_coordination/recovery.py \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  tests/orchestrator/test_canonical_owner_execution.py
```

### Step 10: Commit

```bash
git add \
  platform/execution_coordination/src/design_execution_coordination/recovery.py \
  platform/execution_coordination/src/design_execution_coordination/__init__.py \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  tests/orchestrator/test_canonical_owner_execution.py
git commit -m "feat: expose execution recovery projection"
```

---

## Task 8.4 — Wire real execution owners into CanonicalWorkflowOwnerPorts

**Files**

- Modify `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Create/extend `tests/orchestrator/test_canonical_owner_execution.py`
- Modify `tests/orchestrator/test_canonical_owner_ports.py`
- Modify `tests/architecture/test_real_owner_workflow_boundaries.py`

**Constructor additions**

```text
dispatch_intent_store
execution_recovery_projection
```

Reference composition passes the same logical dispatch store object to the real `MaterializedExecutionSagaCoordinator` and the adapter. It injects the public Execution Coordination projection callable/service. The adapter instantiates neither dependency.

### Step 1: RED — constructor/composition ownership

Update constructor-shape tests. At fixture level prove the same `InMemoryHostDispatchIntentStore` instance is passed to coordinator and adapter. Do not add a production debug property solely to prove object identity.

### Step 2: RED — real success

Use real:

```text
ExecutionReconciliationServiceV2
MaterializedExecutionSagaCoordinator
ExecutionSagaStoreV2
InMemoryHostDispatchIntentStore
CrossHostConvergenceVerifier
project_execution_recovery
```

Only Host/evidence/clock/environment boundaries may be deterministic doubles.

Assert:

```text
begin_execution -> durable saga_id
Saga status SUCCEEDED
active_dispatch_recovery is None
Host execute count == 1
matching durable dispatch row may remain compatible residual evidence
```

### Step 3: RED — real DIVERGED

Inject divergence only through evidence IO. Assert real convergence produces `DIVERGED`, Saga is `DIVERGED`, active dispatch recovery is absent, Host execute count is one, and no compensation API is invoked.

### Step 4: RED — unknown-outcome safe wait

Have Host execute return `COMMIT_STATE_UNKNOWN`:

```text
durable Saga exists
durable dispatch intent == OUTCOME_UNKNOWN
begin_execution -> AsyncOperationRef(kind=EXECUTION_JOB, owner=execution, operation_id=saga_id)
get_execution_owner_state -> active recovery OUTCOME_UNKNOWN
Host execute count == 1
```

Repeat `begin_execution()` for the same exact lineage and assert Host execute count remains one. Existing coordinator durable replay/recovery state must stop a second mutation.

### Step 5: RED — exact binding join

Use a grant whose exact `binding_set_hash` is unresolved. Failure must occur before coordinator/Host execution. Adapter source may not derive a `PBSV2-` id.

### Step 6: RED — architecture boundary

Extend architecture guard to reject adapter references to:

```text
provider-binding `_items`
PostgreSQL dispatch private selectors
manual PBSV2 hash-prefix derivation
adapter-local saga->dispatch map
adapter-local grant->binding map
adapter-local terminal/recovery matrix
ScenarioOwners/test authority
V1 execution surfaces
```

Require `dispatch_intent_store` and `execution_recovery_projection` as explicit dependencies.

### Step 7: Verify RED

```bash
uv run pytest \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  -q
```

### Step 8: Minimal GREEN — request assembly only

`begin_execution()` performs only:

```text
resolve exact ExecutionPlanV2 by ref id/full hash
require grant_ref.content_hash
resolve Gateway V2 grant by that full hash
verify returned full grant hash and exact Slice lineage
admit through Gateway public API
resolve ProviderBindingSetV2 through get_by_hash(authority.binding_set_hash)
verify returned full binding hash
resolve exact ChangeSet / Approval Scope / MaterializationPlan
rebuild convergence profile through public design_convergence builder
verify convergence hash against frozen plan lineage
call MaterializedExecutionSagaCoordinator.execute
map terminal coordinator result to saga_id
map RECOVERY_REQUIRED to execution AsyncOperationRef carrying saga_id
fail closed on READINESS_FAILED/NOT_CREATED without inventing saga_id
```

`get_execution_owner_state()` performs only:

```text
load StoredExecutionSagaV2 by saga_id
require exactly one ordered Slice for current workflow scope
read get_for_saga_slice(saga_id, exact_slice_hash)
call injected execution_recovery_projection
map non-null disposition to HostDispatchRecoveryView
return ExecutionOwnerView preserving Saga status/revision
```

`verify_reconcile()` reuses the same owner read/projection and returns only when Saga is terminal and no active unresolved recovery exists. It does not run a second reconciler.

### Step 9: Verify GREEN

```bash
uv run pytest \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  -q

uv run ruff check \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
```

### Step 10: Commit

```bash
git add \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
git commit -m "feat: wire real execution owner composition"
```

---

## Task 8.5 — Atomically persist Saga identity with execution wait

**Files**

- Modify `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify `tests/orchestrator/test_langgraph_graph.py`

### Step 1: RED — execution async state is atomic

Have `begin_execution()` return:

```python
AsyncOperationRef(
    kind=AsyncOperationKind.EXECUTION_JOB,
    owner="execution",
    operation_id="SAGA-123",
)
```

Supported saver state must contain in the same node update:

```text
saga_id = SAGA-123
async_operation_ref.operation_id = SAGA-123
resume_node = refresh_execution_owner
phase = APPLY_WAIT
```

### Step 2: RED — non-execution async operation never becomes saga_id

Return another valid async kind and prove its operation id is not copied into `saga_id`.

### Step 3: RED — saver-backed unknown resume does not redispatch

Resume with durable `saga_id`; owner view exposes `OUTCOME_UNKNOWN`:

```text
refresh_execution_owner -> RECOVER_OR_WAIT
begin_execution call count unchanged
Host/service mutation call count unchanged
```

### Step 4: Verify RED

```bash
uv run pytest tests/orchestrator/test_langgraph_graph.py -k "execution and saga" -q
```

### Step 5: Minimal GREEN

Only when:

```text
kind == EXECUTION_JOB
owner == execution
```

copy `operation_id` into `saga_id` in the same returned state update as async ref/resume/phase. Do not change graph topology or `decide_apply_resume()`.

### Step 6: Verify GREEN

```bash
uv run pytest \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_langgraph_runtime.py \
  -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py
```

### Step 7: Commit

```bash
git add \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py
git commit -m "fix: persist saga identity with execution wait"
```

---

## Task 8.6 — Close Task 8 with safe-wait and exact-head PostgreSQL evidence

### Step 1: Re-prove external recovery boundary

```bash
uv run pytest \
  tests/execution_coordination/test_unknown_outcome_recovery.py \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  -q
```

Evidence must show:

```text
UnknownOutcomeRecovery has HostOutcomeProbe but no Host mutation port
insufficient evidence may leave OUTCOME_UNKNOWN unresolved
before-commit evidence may advance to SAFE_TO_RETRY
commit evidence may advance existing reconciliation/dispatch truth
workflow-owned scheduler is not asserted
```

### Step 2: Focused Task 8 suite

```bash
uv run pytest \
  tests/provider_binding/test_task8_hash_lookup.py \
  tests/execution_reconciliation/test_dispatch_intent_store.py \
  tests/execution_reconciliation/test_postgres_dispatch_intent.py \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  tests/execution_coordination/test_unknown_outcome_recovery.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/orchestrator/test_langgraph_graph.py \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  -q
```

A developer-machine PostgreSQL skip is not closure evidence.

### Step 3: Owner regressions

```bash
uv run pytest \
  tests/provider_binding \
  tests/execution_reconciliation \
  tests/execution_coordination \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/orchestrator/test_default_workflow_services.py \
  -q
```

### Step 4: Ruff + whitespace

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
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/orchestrator/test_langgraph_graph.py \
  tests/architecture/test_real_owner_workflow_boundaries.py

git diff --check
```

### Step 5: Exact-head PostgreSQL 17 gate

Push exact Task 8 closing SHA. Require:

```text
durable-persistence.yml / execution-saga-postgres = completed / success
new shared PostgreSQL dispatch contract cases collected
new shared PostgreSQL dispatch contract cases non-skipped
no FK failure from fabricated parent Saga ids
```

Inspect job logs; workflow-level green alone is insufficient.

### Step 6: Task 8 closure record

Record all of:

```text
exact Provider Binding full-hash lookup GREEN
same-prefix/full-hash collision negative GREEN
in-memory dispatch contract GREEN
PostgreSQL dispatch contract non-skipped GREEN with real parent Saga
absent-intent matrix GREEN
cross Saga/Slice/grant/binding/Host negatives GREEN
terminal compatible residual evidence GREEN
terminal unresolved evidence conflict GREEN
RECONCILED + nonterminal -> RECOVER_OR_WAIT/no redispatch/no terminal GREEN
real coordinator SUCCEEDED GREEN
real coordinator DIVERGED GREEN
unknown outcome -> execution AsyncOperationRef carrying durable saga_id GREEN
atomic saga_id + wait checkpoint GREEN
unknown resume -> RECOVER_OR_WAIT without redispatch GREEN
architecture guard GREEN
exact-head PostgreSQL 17 lane GREEN
```

Only then mark Task 8 CLOSED.

---

# Task 9

## Task 9 — Add real-owner LangGraph E2E A–D/F/G plus unknown-outcome safe-wait acceptance

**Files**

- Create `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Modify `tests/architecture/test_real_owner_workflow_boundaries.py`
- Preserve `tests/orchestrator/test_workflow_end_to_end.py::_ScenarioOwners`

**Real internal composition**

```text
LangGraphWorkflowRuntime
PostgreSQL checkpointer
PostgreSQL WorkflowArtifactStore
OperationResolver / ParameterBinder
FreshnessResolver / RevisionBarrier
Impact / Approval Scope / ChangeSet
Materialization / Execution Planning
Gateway V2 / Provider Binding V2
Saga / Coordination / Reconciliation / Convergence
HostDispatchIntentStore
injected execution recovery projection
```

Only registered environment/presentation boundaries may be deterministic doubles.

### Step 1: RED A — happy path

Drive one canonical operation through proposal HITL and approval to `WorkflowPhase.COMPLETED`. Final `saga_id` must resolve from the real Saga owner; every final ref resolves through its authoritative store.

### Step 2: RED B — HITL

Prove exact proposal `pause_id`, stale/wrong pause rejection, and ACCEPT continuing into the same real-owner composition.

### Step 3: RED C — async freshness

Force semantic reconstruction wait. Resume must atomically persist the new operation/planning-snapshot/snapshot-set refs; Impact consumes that exact tuple.

### Step 4: RED D — missing owner truth

Remove one owner-local object after checkpoint, rebuild runtime, resume, and fail closed before any downstream Host mutation. Checkpoint data may not reconstruct the missing owner body.

### Step 5: Supplemental unknown-outcome safe wait

Drive Host execute to `COMMIT_STATE_UNKNOWN`. Saver-backed state must contain:

```text
saga_id = durable Saga id
phase = APPLY_WAIT
resume_node = refresh_execution_owner
execution async operation_id = same Saga id
```

Fresh resume:

```text
owner state = OUTCOME_UNKNOWN
route = RECOVER_OR_WAIT
Host execute count remains 1
```

This test does not call `UnknownOutcomeRecovery` from workflow code and does not replace Task 10 baseline terminal recovery E.

### Step 6: RED F — refs-only checkpoint

Reject serialized owner bodies including:

```text
SemanticSnapshot
SnapshotSet
ImpactAnalysis
ApprovalScopeDefinitionV2
ApprovalScopeBoundaryV2
CanonicalChangeSet
ApprovalRecord
ExecutionGrantV2
ExecutionPlanV2
ProviderBindingSetV2
StoredExecutionSagaV2
HostDispatchIntent
ActualDelta
```

Stable refs/navigation and `saga_id` are allowed.

### Step 7: RED/GREEN G — architecture

The real-owner E2E may not import/construct `_ScenarioOwners`, private owner selectors/dicts, V1 execution surfaces, or a test-authored Saga/dispatch/recovery state machine.

### Step 8: Verify GREEN

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/orchestrator/test_real_owner_workflow_end_to_end.py -q
uv run pytest tests/architecture/test_real_owner_workflow_boundaries.py -q
uv run ruff check \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
```

### Step 9: Commit

```bash
git add \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
git commit -m "test: add real owner workflow end to end acceptance"
```

---

# Task 10

## Task 10 — Prove supported durable terminal recovery, unknown safe wait, and exact-head CI

**Files**

- Modify `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Inspect `.github/workflows/workflow-orchestrator.yml`
- Inspect `.github/workflows/durable-persistence.yml`
- Inspect `.github/workflows/phase-i-real-cross-host-materialization-saga.yml`
- Inspect `.github/workflows/step37-cross-host-saga-failure-injection.yml`
- Inspect `.github/workflows/repository-regression.yml`
- Modify a workflow only if exact current collection proves required acceptance is unscheduled

Task 10 has **two distinct durability paths**. They must not be conflated:

```text
A. baseline supported recovery point -> fresh runtime -> no duplicate Host -> terminal result
B. unknown-outcome safe wait -> fresh runtime -> RECOVER_OR_WAIT -> no duplicate Host
```

Path B is supplemental and cannot satisfy Path A.

### Step 1: RED E — supported process-loss recovery reaches terminal without second Host execution

Use real PostgreSQL workflow checkpoint/artifact persistence plus real PostgreSQL Saga/dispatch persistence and one counting Host boundary.

Freeze this existing supported recovery window:

```text
1. workflow has reached the apply node with authoritative refs already persisted
2. runtime A calls the real CanonicalWorkflowOwnerPorts.begin_execution()
3. real coordinator performs the Host mutation exactly once and durably reaches terminal Saga truth
4. begin_execution returns terminal saga_id to a test-only process-loss wrapper
5. wrapper raises SimulatedProcessLoss before apply_or_recover returns its LangGraph state update
6. therefore owner truth is durable but that node's saga_id/next-navigation update is not the recovery source of truth
7. close/discard runtime A, PostgreSQL checkpointer/artifact connections, Saga service/store connection, and dispatch-store connection
8. construct runtime B with fresh services/connections over the same PostgreSQL data
9. resume the same workflow/thread from the last committed checkpoint
10. runtime B replays the same exact execution refs
11. coordinator create_saga/replay resolves the existing durable Saga and terminal projection before any new Host dispatch
12. total Host execute count remains exactly 1
13. workflow continues through authoritative execution read/verification to WorkflowPhase.COMPLETED
```

The process-loss wrapper is allowed only as a fault injector around the real workflow service call. It must delegate to real `begin_execution()` and may only raise after receiving the returned `saga_id`; it may not write Saga/dispatch/checkpoint state itself.

Required assertions:

```text
runtime A owner Saga is terminal before injected loss
runtime A Host execute count == 1
runtime B uses fresh owner/checkpoint/artifact connections
runtime B does not share an in-memory Saga/dispatch/artifact owner with runtime A
runtime B final phase == COMPLETED
runtime B final saga_id == runtime A durable Saga id
Host execute count across A+B == 1
```

This acceptance relies on existing coordinator replay semantics: an already-terminal persisted Saga is projected before the Host dispatch path. No automatic recovery scheduler is required.

**STOP / Design condition:** if the actual RED proves this is not a supported recovery point under the current saver/runtime contract, inspect other already-supported process recovery points. If no existing point can satisfy baseline E without new architecture, stop and propose Design amendment. Do **not** replace E with unknown-outcome safe wait or lower “terminal result” to “observable recovery truth.”

### Step 2: Supplemental PostgreSQL unknown-outcome fresh-runtime safe wait

Independently prove:

```text
runtime A reaches durable Saga + OUTCOME_UNKNOWN
Host execute count == 1
close/discard runtime A and owner/checkpoint/artifact connections
runtime B is reconstructed fresh against the same PostgreSQL data
runtime B restores saga_id from checkpoint
runtime B re-reads exact Saga/Slice dispatch truth
route == RECOVER_OR_WAIT
Host execute count remains 1
```

This proves no blind redispatch while outcome remains unresolved. It is not baseline E terminal recovery.

### Step 3: Supplemental explicit external recovery observability

From the durable unknown state, resolve every input from public owner truth:

```text
StoredExecutionSagaV2 by saga_id
exact single ExecutionSliceV2 from authoritative ExecutionPlanV2
Gateway admitted authority by exact grant hash
ProviderBindingSetV2 by exact authority.binding_set_hash
dispatch intent by exact saga_id + execution_slice_hash
```

Call public `UnknownOutcomeRecovery.recover()` explicitly from the test/composition boundary. Then rebuild/read through fresh workflow services and assert the updated authoritative owner truth is visible.

The assertion stops at what current owners guarantee (`SAFE_TO_RETRY`, reconciled Slice truth, or another durable projection according to probe evidence). It does not satisfy Step 1 and does not assert an autonomous workflow scheduler.

### Step 4: Preserve fast scenario regression

```bash
uv run pytest tests/orchestrator/test_workflow_end_to_end.py -q
```

`_ScenarioOwners` remains legal only in this fast orchestration regression.

### Step 5: PostgreSQL capability suite

Before editing CI, inspect the listed workflows and record exact owner jobs/test paths.

Run in PostgreSQL-capable environment:

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/orchestrator/test_artifact_postgres.py \
  tests/orchestrator/test_postgres_checkpoint.py \
  tests/execution_reconciliation/test_postgres_dispatch_intent.py \
  tests/execution_reconciliation/test_postgres_saga_store_v2.py \
  tests/execution_coordination/test_host_effect_crash_windows.py \
  -q
```

PostgreSQL skips are not closure evidence.

### Step 6: Architecture/Ruff/whitespace

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

### Step 7: Scope audit

Compare final implementation HEAD against approved spec HEAD `41d763ada50ed50e9c3322d54e1879b170d5b3fe`. Reject unrelated changes in:

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
generic materialized forward-resume/convergence engine
```

### Step 8: Exact-head repository CI

Require every PR-triggered workflow for the exact final SHA to be `completed / success`, zero failure/in-progress/queued. At minimum inspect:

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

For `execution-saga-postgres`, inspect logs and prove new Task 8 shared PostgreSQL dispatch contract cases were collected and non-skipped.

### Step 9: Final closure record

Record separately:

```text
Task 8 owner API/parity evidence
Task 9 A–D/F/G real-owner E2E evidence
baseline E supported process-loss recovery -> fresh runtime -> COMPLETED
baseline E Host execute count remains exactly 1
unknown-outcome safe-wait fresh-runtime evidence
explicit external UnknownOutcomeRecovery advancement observed by fresh owner read
no claim of autonomous recovery scheduler
fast _ScenarioOwners regression preserved
scope audit clean
all exact-head PR workflows success
```

Only then mark the implementation phase CLOSED. Merge, merged-main observation, and docs-only lifecycle closeout remain separate gates under the baseline plan.

---

## Acceptance Matrix

| Requirement | Evidence |
| --- | --- |
| Provider Binding exact hash lookup | Task 8.1 |
| Same-first12/different-full-hash negative | Task 8.1 |
| Public dispatch-intent store contract | Task 8.2 |
| Shared contract uses real Saga lineage | Task 8.2 |
| PostgreSQL FK preserved | Task 8.2 exact parent-Saga fixture |
| In-memory/PostgreSQL parity | Task 8.2 + 8.6 |
| Exact Saga/Slice lookup without active-state filtering | Task 8.2 |
| `dispatch_intent=None` pre/during/terminal decisions | Task 8.3 |
| Wrong Saga/Slice intent rejected | Task 8.3 |
| Wrong grant/binding/Host lineage rejected | Task 8.3 |
| Compatible terminal residual dispatch evidence | Task 8.3 |
| Terminal unresolved evidence fails closed | Task 8.3 |
| `RECONCILED + nonterminal Saga` does not redispatch or complete | Task 8.3 + 8.4 |
| Same dispatch store composed into coordinator + adapter | Task 8.4 |
| Recovery projection explicitly injected | Task 8.4 |
| Real Saga success | Task 8.4 |
| Real DIVERGED without compensation | Task 8.4 |
| Unknown outcome never blindly redispatches | Task 8.4 / 8.5 / 9 / 10 |
| Saga id + execution wait atomic checkpoint | Task 8.5 |
| Unknown safe-wait boundary | Task 8.6 / 9 / 10 |
| Public `UnknownOutcomeRecovery.recover()` remains external entrypoint | Task 8.6 + 10 |
| Real-owner E2E A–D/F/G | Task 9 |
| Baseline E: fresh runtime, no duplicate Host, terminal result | Task 10 Step 1 |
| Supplemental unknown-outcome fresh-runtime safe wait | Task 10 Step 2 |
| PostgreSQL formal closure non-skipped | Task 8.6 + 10 |
| Exact-head repository regression H | Task 10 |

---

## STOP Conditions

Stop implementation and return to Design/Plan if any RED or repository fact proves:

```text
Provider Binding cannot provide exact full-hash lookup without changing its identity contract beyond approved spec.
Dispatch-intent durable uniqueness is not saga_id + execution_slice_hash.
PostgreSQL shared contract cannot preserve real Saga FK without broader persistence redesign.
In-memory/PostgreSQL stores cannot share one transition/replay contract without broader persistence redesign.
Execution Coordination cannot determine reviewed recovery combinations from existing durable Saga/Slice/dispatch truth.
Current Slice state does not carry enough admitted grant/binding/Host lineage to reject mismatched intent evidence.
Canonical begin_execution cannot reconstruct coordinator inputs through public owner APIs without a new reverse index/private cache.
Task 7 exactly-one-slice assumption is no longer true on implementation HEAD.
LangGraph cannot atomically persist saga_id with execution wait using the existing state/checkpointer model.
Formal PostgreSQL CI cannot execute new contract cases non-skipped without a CI architecture change.
The Task 10 Step 1 process-loss window is not a supported recovery point and no other existing supported point can reach terminal without duplicate Host execution.
A required baseline terminal recovery proof would need new recovery scheduler/generic forward-resume architecture.
```

For the last two conditions, raise a Design amendment. Do not downgrade baseline E to safe wait or external recovery observability.

Do not manufacture GREEN by adding adapter-private maps, selecting latest/current rows, inventing parent Saga ids, weakening full-hash equality, treating timeout as proof of non-commit, treating `recovery=None` as Saga completion, or relabeling safe wait as complete recovery.

---

## Written-Plan Gate

This plan becomes Amendment B implementation authority only after human written-plan review approval.

Before approval:

```text
Task 8 product implementation FORBIDDEN
Task 9 implementation FORBIDDEN
Task 10 implementation FORBIDDEN
Task 7 baseline MUST NOT be rolled back
```

After approval execute strictly:

```text
Task 8.1 exact Provider Binding hash RED/GREEN
-> Task 8.2 dispatch store contract + real-lineage in-memory/PostgreSQL parity RED/GREEN
-> Task 8.3 complete owner recovery projection matrix RED/GREEN
-> Task 8.4 canonical execution-owner wiring RED/GREEN
-> Task 8.5 atomic Saga-id execution wait RED/GREEN
-> Task 8.6 focused + exact-head PostgreSQL Task 8 closure
-> Task 8 CLOSED
-> Task 9 real-owner E2E + unknown safe-wait acceptance
-> Task 10 baseline supported terminal recovery E
-> Task 10 supplemental unknown safe-wait/external recovery observability
-> Task 10 exact-head repository CI H
-> implementation phase CLOSED
```
