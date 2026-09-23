# Task 8 Execution Owner Lookup Amendment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Each production change follows RED → verify RED → minimal GREEN → focused verification → commit. Do not collapse gates.

**Status:** Proposed — written-plan review pending

**Goal:** Complete Task 8 real execution-owner wiring without duplicating authoritative owner semantics: add exact Provider Binding hash lookup, publish one durable dispatch-intent store contract with in-memory/PostgreSQL parity, expose owner-level Saga/dispatch recovery projection, wire real Saga/coordination/reconciliation into `CanonicalWorkflowOwnerPorts`, atomically persist Saga identity with execution wait, and prove safe-wait/no-blind-redispatch behavior before continuing the real-owner E2E.

**Architecture:** `CanonicalWorkflowOwnerPorts` remains a composition adapter. Provider Binding owns binding-set identity lookup. Execution Reconciliation owns dispatch-intent persistence and transitions. Execution Coordination owns interpretation of Saga + dispatch evidence. LangGraph owns only workflow navigation/checkpoint state. Task 8 is explicitly **safe-wait integration**, not autonomous unknown-outcome recovery scheduling and not generic materialized forward-resume/convergence continuation.

**Tech Stack:** Python 3.11 / 3.14, LangGraph 1.2.x, `langgraph-checkpoint-postgres` 3.x, PostgreSQL 17, pytest, Ruff, GitHub Actions. No dependency upgrade is authorized.

**Spec:** `docs/superpowers/specs/2026-09-23-task8-execution-owner-lookup-amendment-design.md`

**Approved written-spec HEAD:** `41d763ada50ed50e9c3322d54e1879b170d5b3fe`

**Baseline implementation plan:** `docs/superpowers/plans/2026-09-20-real-owner-e2e-workflow.md`

---

## Current Checkpoint

The implementation branch before this plan is:

```text
branch: feat/capability-real-owner-e2e-workflow
approved spec head: 41d763ada50ed50e9c3322d54e1879b170d5b3fe
Task 7: CLOSED
Task 8 product implementation: NOT STARTED
```

The currently unwired execution seam is still:

```text
CanonicalWorkflowOwnerPorts.begin_execution
CanonicalWorkflowOwnerPorts.get_execution_owner_state
CanonicalWorkflowOwnerPorts.verify_reconcile
```

`durable-persistence.yml` already owns a PostgreSQL 17 job named `execution-saga-postgres` and already executes `tests/execution_reconciliation/test_postgres_dispatch_intent.py`. Therefore this plan does not authorize a CI workflow edit by default. The new PostgreSQL parity assertions must be placed in that already-collected test surface.

---

## Global Constraints

- Task 7 remains CLOSED and must not be rolled back.
- `CanonicalWorkflowOwnerPorts` may assemble requests and consume public read models; it must not own Provider Binding identity rules, dispatch transition rules, Saga/dispatch precedence, reconciliation, convergence, or retry policy.
- `get_by_hash(binding_set_hash)` must validate a canonical lowercase SHA-256 and must prove `returned.binding_set_hash == requested_binding_set_hash` before returning.
- A same-first-12-hex/different-full-hash case must fail closed. A matching content-addressed short id is never sufficient evidence of exact hash equality.
- Malformed binding hashes fail with the existing digest validation behavior (`ValueError`). A missing exact artifact fails with `PROVIDER_BINDING_SET_REFERENCE_NOT_FOUND`. A short-id collision/full-hash mismatch fails with `PROVIDER_BINDING_INTEGRITY_INVALID`.
- `HostDispatchIntentStore.get_for_saga_slice(saga_id, execution_slice_hash)` is an exact owner lookup. It must not filter by active/terminal Saga state and must not select a latest/current row.
- In-memory and PostgreSQL dispatch-intent stores must implement the same public contract and preserve the same replay/CAS semantics.
- Formal Task 8 closure requires the PostgreSQL contract cases to run **non-skipped** and pass on the exact Task 8 closing SHA.
- Workflow recovery reads the exact Slice identity from the durable Saga definition. Current workflow scope remains exactly one `ExecutionSliceV2`; multi-slice workflow expansion is out of scope.
- Saga/dispatch precedence belongs to Execution Coordination. The orchestrator adapter must not encode a private status matrix.
- `SUCCEEDED + Slice SUCCEEDED + HOST_COMMITTED` means no active unresolved workflow recovery.
- `FAILED + Slice FAILED_BEFORE_COMMIT + SAFE_TO_RETRY` means no active unresolved workflow recovery; the durable `SAFE_TO_RETRY` row remains observable in the owner store.
- Terminal Saga plus incompatible unresolved `OUTCOME_UNKNOWN` fails closed with `CoordinationError.code == "HOST_RECOVERY_EVIDENCE_CONFLICT"`.
- `UnknownOutcomeRecovery.recover` remains the explicit public external recovery entrypoint. Task 8 does not add a scheduler/worker and does not claim autonomous recovery to final convergence.
- When `begin_execution()` returns an execution `AsyncOperationRef`, graph state must atomically persist its `operation_id` as `saga_id` together with the async ref, resume node, and `APPLY_WAIT` phase.
- Checkpoints may contain ids/refs/navigation only. They must not persist `HostDispatchIntent`, `StoredExecutionSagaV2`, `ProviderBindingSetV2`, `ExecutionPlanV2`, `ActualDelta`, or other authoritative owner bodies.
- Deterministic doubles are limited to true environment boundaries: Host readiness, Host execute/read-back, Host outcome probe, verification/convergence evidence IO, runtime/provider observation, preview/HITL evidence, and clock.
- No new compensation behavior, V1 revival, owner-private lookup, adapter-private lineage cache, outbox/inbox architecture, owner-wide PostgreSQL migration, real AutoCAD/Revit acceptance, MCP front door, support-matrix expansion, recovery scheduler, or generic forward-resume engine.
- New Python code uses complete Chinese comments/docstrings and current repository Ruff conventions.

---

## Review Focus

1. **Full-hash identity:** matching the first 12 hex characters cannot satisfy `get_by_hash()` unless the complete 64-character digest also matches.
2. **Residual dispatch evidence after terminal Saga:** legal `HOST_COMMITTED` or `SAFE_TO_RETRY` rows must not mechanically force `RECOVER_OR_WAIT` once compatible terminal Saga/Slice truth exists.
3. **Conflicting terminal evidence:** terminal Saga plus unresolved `OUTCOME_UNKNOWN` fails closed instead of silently preferring either owner state.
4. **Unknown-outcome replay:** once durable Saga + dispatch intent exist, retries/resume must not issue a second Host mutation command.
5. **PostgreSQL parity:** in-memory GREEN alone cannot close Task 8; the shared contract must execute against PostgreSQL 17 non-skipped on the exact closing SHA.
6. **Dependency ownership:** reference composition injects both the same logical dispatch-intent store used by the coordinator and the approved execution-recovery projection callable/service. The adapter creates neither dependency itself.

Every focus item has a direct RED/GREEN test below.

---

## Supersession of Baseline Tasks 8–10

This plan supersedes only the Task 8/9/10 portions of `docs/superpowers/plans/2026-09-20-real-owner-e2e-workflow.md`.

These historical assumptions are no longer implementation authority:

```text
Task 8 can use the existing dispatch-intent surface without a public store contract.
Task 8 may derive Provider Binding identity from a binding hash inside the adapter.
Task 8 may classify recovery from active Slice + dispatch enum inside the adapter.
Task 10 unknown-outcome acceptance must automatically recover/reconcile to terminal.
```

The corrected sequence is:

```text
Task 8 owner API/parity + canonical execution wiring + safe wait
→ Task 9 real-owner LangGraph E2E A–D/F/G + unknown-outcome safe-wait acceptance
→ Task 10 durable PostgreSQL restart/no-double-Host proof + exact-head repository closure
```

Task 10 may explicitly invoke `UnknownOutcomeRecovery.recover` from the test/composition boundary and prove that a fresh workflow read observes the updated owner truth. It must not claim workflow-owned scheduling or guaranteed final convergence.

---

## File Structure Freeze

| File | Responsibility |
| --- | --- |
| `platform/provider_binding/src/design_provider_binding/store_v2.py` | Exact owner-local `get_by_hash()` + full-hash equality |
| `platform/provider_binding/src/design_provider_binding/__init__.py` | Export approved V2 store surface when required |
| `platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent_store.py` | Public `HostDispatchIntentStore` protocol + in-memory reference implementation |
| `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py` | Public exact Saga/Slice lookup on existing durable store |
| `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py` | Package-root public exports |
| `platform/execution_coordination/src/design_execution_coordination/recovery.py` | Read-only Saga/dispatch recovery projection; preserve `UnknownOutcomeRecovery` semantics |
| `platform/execution_coordination/src/design_execution_coordination/__init__.py` | Export approved recovery projection surface |
| `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py` | Public-owner request assembly + injected recovery projection consumption |
| `platform/orchestrator/src/design_orchestrator/langgraph_graph.py` | Atomic Saga id + execution-wait navigation |
| `tests/provider_binding/test_task8_hash_lookup.py` | Exact/full-hash lookup contract |
| `tests/execution_reconciliation/dispatch_intent_store_contract.py` | Backend-neutral shared store assertions |
| `tests/execution_reconciliation/test_dispatch_intent_store.py` | In-memory store contract |
| `tests/execution_reconciliation/test_postgres_dispatch_intent.py` | Existing PostgreSQL lane + shared Task 8 contract |
| `tests/execution_coordination/test_task8_execution_recovery_projection.py` | Owner precedence/conflict matrix |
| `tests/orchestrator/test_canonical_owner_execution.py` | Real Saga/coordinator/reconciliation success, DIVERGED, unknown safe wait |
| `tests/orchestrator/test_langgraph_graph.py` | Atomic Saga id/wait and recovery resume routing |
| `tests/orchestrator/test_real_owner_workflow_end_to_end.py` | Real-owner LangGraph acceptance |
| `tests/architecture/test_real_owner_workflow_boundaries.py` | No private lookup/maps/status matrix/V1/test authority |
| `.github/workflows/durable-persistence.yml` | Inspect only by default; existing PostgreSQL 17 collection already includes `test_postgres_dispatch_intent.py` |

If implementation proves a required production file outside this responsibility table is necessary, stop and amend the plan before editing that file.

---

# Task 8

### Task 8.1: Add exact Provider Binding hash lookup

**Files:**
- Modify: `platform/provider_binding/src/design_provider_binding/store_v2.py`
- Modify only if needed for public import: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Create: `tests/provider_binding/test_task8_hash_lookup.py`

**Consumes:** `ProviderBindingSetV2`, `ProviderBindingError`, `resolve_provider_bindings_v2`, `tests.provider_binding._support.build_phase_i_binding_inputs`, `tests.provider_binding._support.snapshot`.

**Produces this public method:**

```text
InMemoryProviderBindingSetV2Store.get_by_hash(binding_set_hash: str) -> ProviderBindingSetV2
```

#### Step 1: Write exact-hash success RED

Create `tests/provider_binding/test_task8_hash_lookup.py` with the real V2 builder path:

```python
from design_provider_binding import (
    InMemoryProviderBindingSetV2Store,
    resolve_provider_bindings_v2,
)
from tests.provider_binding._support import build_phase_i_binding_inputs


def test_v2_store_resolves_exact_full_hash() -> None:
    _, slices, snapshots = build_phase_i_binding_inputs()
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

#### Step 2: Write same-prefix/different-full-hash RED

Use `dataclasses.replace` on a real V2 binding set. The replacement remains structurally valid for the current owner-local store because `ProviderBindingSetV2.__post_init__` validates digest shape and the store's current `_validate_reference()` validates only the id/full-hash prefix relation.

```python
from dataclasses import replace

import pytest
from design_provider_binding import ProviderBindingError


def test_v2_store_rejects_short_id_collision_on_full_hash() -> None:
    _, slices, snapshots = build_phase_i_binding_inputs()
    original = resolve_provider_bindings_v2(
        slices["autocad"],
        snapshots["autocad"],
    )
    stored_hash = "a" * 12 + "2" * 52
    requested_hash = "a" * 12 + "1" * 52
    collision = replace(
        original,
        binding_set_id=f"PBSV2-{stored_hash[:12]}",
        binding_set_hash=stored_hash,
    )
    store = InMemoryProviderBindingSetV2Store()
    store.put(collision)

    with pytest.raises(ProviderBindingError) as exc_info:
        store.get_by_hash(requested_hash)

    assert exc_info.value.code == "PROVIDER_BINDING_INTEGRITY_INVALID"
```

The test intentionally proves that a derived `PBSV2-aaaaaaaaaaaa` id is insufficient without complete digest equality.

#### Step 3: Write malformed/unresolved REDs

```python
@pytest.mark.parametrize("value", ["", "A" * 64, "a" * 63, "g" * 64])
def test_v2_store_rejects_noncanonical_hash(value: str) -> None:
    store = InMemoryProviderBindingSetV2Store()
    with pytest.raises(ValueError):
        store.get_by_hash(value)


def test_v2_store_reports_unresolved_exact_hash() -> None:
    store = InMemoryProviderBindingSetV2Store()
    with pytest.raises(ProviderBindingError) as exc_info:
        store.get_by_hash("b" * 64)
    assert exc_info.value.code == "PROVIDER_BINDING_SET_REFERENCE_NOT_FOUND"
```

#### Step 4: Verify RED

```bash
uv run pytest tests/provider_binding/test_task8_hash_lookup.py -q
```

Expected: RED because `InMemoryProviderBindingSetV2Store` has no `get_by_hash()`.

#### Step 5: Implement minimal owner lookup

Inside `store_v2.py`, validate the requested digest using the owner's existing digest rule, resolve inside the owner, re-run `_validate_reference()`, then compare the complete hash before returning.

The required decision is:

```python
_validate_reference(binding_set)
if binding_set.binding_set_hash != requested_hash:
    raise ProviderBindingError(
        "PROVIDER_BINDING_INTEGRITY_INVALID",
        "ProviderBindingSetV2 full hash does not match requested owner hash",
    )
return binding_set
```

Do not expose or read `_items` from the orchestrator adapter.

#### Step 6: Run GREEN + owner regression

```bash
uv run pytest tests/provider_binding/test_task8_hash_lookup.py tests/provider_binding -q
uv run ruff check \
  platform/provider_binding/src/design_provider_binding/store_v2.py \
  tests/provider_binding/test_task8_hash_lookup.py
```

#### Step 7: Commit Task 8.1

```bash
git add \
  platform/provider_binding/src/design_provider_binding/store_v2.py \
  tests/provider_binding/test_task8_hash_lookup.py

git add platform/provider_binding/src/design_provider_binding/__init__.py \
  2>/dev/null || true

git commit -m "feat: add exact provider binding hash lookup"
```

Before committing, use `git status --short` and do not stage `__init__.py` unless it actually changed.

---

### Task 8.2: Publish one HostDispatchIntentStore contract and prove in-memory/PostgreSQL parity

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent_store.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/dispatch_intent_store_contract.py`
- Create: `tests/execution_reconciliation/test_dispatch_intent_store.py`
- Modify: `tests/execution_reconciliation/test_postgres_dispatch_intent.py`

**Consumes:** `HostDispatchIntent`, `HostDispatchStatus`, `build_host_dispatch_intent`, `ReconciliationError`, existing PostgreSQL CAS/observation implementation.

**Produces this protocol surface:**

```text
prepare(intent: HostDispatchIntent) -> HostDispatchIntent
get(dispatch_intent_id: UUID) -> HostDispatchIntent | None
get_for_saga_slice(saga_id: str, execution_slice_hash: str) -> HostDispatchIntent | None
mark_dispatched(dispatch_intent_id: UUID, *, expected_revision: int, observed_at: str) -> HostDispatchIntent
mark_outcome_unknown(dispatch_intent_id: UUID, *, expected_revision: int, failure_ref: str, observed_at: str) -> HostDispatchIntent
mark_host_committed(dispatch_intent_id: UUID, *, expected_revision: int, evidence_hash: str, observed_at: str) -> HostDispatchIntent
mark_safe_to_retry(dispatch_intent_id: UUID, *, expected_revision: int, evidence_ref: str, observed_at: str) -> HostDispatchIntent
mark_reconciled(dispatch_intent_id: UUID, *, expected_revision: int, evidence_hash: str, observed_at: str) -> HostDispatchIntent
```

`InMemoryHostDispatchIntentStore` implements the complete protocol. `PostgresHostDispatchIntentStore` must satisfy the same protocol without exposing `_select_by_slice()`.

#### Step 1: Create a backend-neutral contract harness

Create `tests/execution_reconciliation/dispatch_intent_store_contract.py`. Use `build_host_dispatch_intent()` for every logical command. Split the contract into deterministic helper assertions instead of one mutable mega-sequence:

```python
def assert_lookup_and_replay_contract(store, make_intent) -> None:
    candidate = make_intent("lookup")
    prepared = store.prepare(candidate)
    replayed = store.prepare(candidate)
    assert replayed == prepared
    assert store.get(prepared.dispatch_intent_id) == prepared
    assert store.get_for_saga_slice(
        prepared.saga_id,
        prepared.execution_slice_hash,
    ) == prepared


def assert_unknown_contract(store, make_intent) -> None:
    prepared = store.prepare(make_intent("unknown"))
    dispatched = store.mark_dispatched(
        prepared.dispatch_intent_id,
        expected_revision=prepared.intent_revision,
        observed_at="2026-09-23T00:00:01Z",
    )
    unknown = store.mark_outcome_unknown(
        dispatched.dispatch_intent_id,
        expected_revision=dispatched.intent_revision,
        failure_ref="HOST_TIMEOUT",
        observed_at="2026-09-23T00:00:02Z",
    )
    assert unknown.status is HostDispatchStatus.OUTCOME_UNKNOWN


def assert_committed_reconciled_contract(store, make_intent) -> None:
    prepared = store.prepare(make_intent("commit"))
    dispatched = store.mark_dispatched(
        prepared.dispatch_intent_id,
        expected_revision=prepared.intent_revision,
        observed_at="2026-09-23T00:00:03Z",
    )
    committed = store.mark_host_committed(
        dispatched.dispatch_intent_id,
        expected_revision=dispatched.intent_revision,
        evidence_hash="c" * 64,
        observed_at="2026-09-23T00:00:04Z",
    )
    reconciled = store.mark_reconciled(
        committed.dispatch_intent_id,
        expected_revision=committed.intent_revision,
        evidence_hash="d" * 64,
        observed_at="2026-09-23T00:00:05Z",
    )
    assert reconciled.status is HostDispatchStatus.RECONCILED


def assert_safe_retry_contract(store, make_intent) -> None:
    prepared = store.prepare(make_intent("safe"))
    dispatched = store.mark_dispatched(
        prepared.dispatch_intent_id,
        expected_revision=prepared.intent_revision,
        observed_at="2026-09-23T00:00:06Z",
    )
    safe = store.mark_safe_to_retry(
        dispatched.dispatch_intent_id,
        expected_revision=dispatched.intent_revision,
        evidence_ref="HOST_CONFIRMED_NOT_COMMITTED",
        observed_at="2026-09-23T00:00:07Z",
    )
    assert safe.status is HostDispatchStatus.SAFE_TO_RETRY
```

Also add two explicit helpers:

```text
same saga_id + execution_slice_hash but different admitted lineage -> DISPATCH_INTENT_CONFLICT
stale expected_revision on any transition -> DISPATCH_INTENT_CONFLICT
```

The contract helper must not inspect SQL tables or an in-memory private dict.

#### Step 2: Add in-memory RED

Create `tests/execution_reconciliation/test_dispatch_intent_store.py` and invoke every shared contract helper against `InMemoryHostDispatchIntentStore`.

Expected RED: the public protocol/reference implementation does not exist.

#### Step 3: Add PostgreSQL RED in the already collected file

Modify `tests/execution_reconciliation/test_postgres_dispatch_intent.py` to invoke the same shared contract helpers against `PostgresHostDispatchIntentStore` under `DSP_TEST_POSTGRES_DSN`.

Add a direct exact lookup assertion after a row reaches a non-PREPARED state:

```python
resolved = store.get_for_saga_slice(
    intent.saga_id,
    intent.execution_slice_hash,
)
assert resolved is not None
assert resolved.dispatch_intent_id == intent.dispatch_intent_id
```

The API takes only Saga/Slice identity; there is no active-Saga filter.

#### Step 4: Verify RED

```bash
uv run pytest tests/execution_reconciliation/test_dispatch_intent_store.py -q
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/execution_reconciliation/test_postgres_dispatch_intent.py -q
```

Expected: missing public store protocol/reference implementation and missing public `get_for_saga_slice()`.

#### Step 5: Implement the public protocol and in-memory store

Create `dispatch_intent_store.py`. The in-memory owner implementation keeps exact indexes internally and preserves the current durable identity/replay contract:

```text
dispatch_intent_id -> HostDispatchIntent
(saga_id, execution_slice_hash) -> dispatch_intent_id
```

`prepare()` must reject a second different admitted lineage for the same Saga/Slice with `DISPATCH_INTENT_CONFLICT`. Transition methods must use `expected_revision` CAS and return a new immutable intent revision. No caller may mutate stored objects in place.

If common replay/CAS validation is extracted, keep that helper inside `design_execution_reconciliation` and use it from both backends.

#### Step 6: Implement PostgreSQL public exact lookup

Add:

```text
PostgresHostDispatchIntentStore.get_for_saga_slice(
    saga_id: str,
    execution_slice_hash: str,
) -> HostDispatchIntent | None
```

The public method validates its inputs, opens the existing store transaction, calls the store's own `_select_by_slice()` internally, and decodes zero/one row. `_select_by_slice()` remains private to the PostgreSQL implementation.

#### Step 7: Run GREEN + recovery regressions

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

#### Step 8: Commit Task 8.2

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

**Consumes:** `StoredExecutionSagaV2`, `SliceReconciliationStateV2`, `ExecutionSagaStatusV2`, `SliceReconciliationStatusV2`, `HostDispatchIntent`, `HostDispatchStatus`, `CoordinationError`.

**Produces:**

```python
class ExecutionRecoveryDisposition(str, Enum):
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SAFE_TO_RETRY = "SAFE_TO_RETRY"


@dataclass(frozen=True, slots=True)
class ExecutionRecoveryProjection:
    disposition: ExecutionRecoveryDisposition | None
```

and this public callable signature:

```text
project_execution_recovery(
    stored_saga: StoredExecutionSagaV2,
    execution_slice_hash: str,
    dispatch_intent: HostDispatchIntent | None,
) -> ExecutionRecoveryProjection
```

`disposition is None` means there is no active unresolved Host-effect recovery. This module must not import `design_orchestrator`.

#### Step 1: Write terminal-compatible REDs

Add exact cases:

```text
Saga SUCCEEDED + Slice SUCCEEDED + dispatch HOST_COMMITTED
-> disposition is None

Saga FAILED + Slice FAILED_BEFORE_COMMIT + dispatch SAFE_TO_RETRY
-> disposition is None
-> dispatch store still returns SAFE_TO_RETRY
```

The projection is read-only and never erases durable evidence.

#### Step 2: Write unresolved REDs

For a non-terminal Saga/exact Slice, prove:

```text
OUTCOME_UNKNOWN -> OUTCOME_UNKNOWN
SAFE_TO_RETRY -> SAFE_TO_RETRY
PREPARED -> RECOVERY_REQUIRED
DISPATCHED -> RECOVERY_REQUIRED
HOST_COMMITTED -> RECOVERY_REQUIRED
RECONCILED -> None
```

#### Step 3: Write terminal-conflict RED

Construct terminal Saga + terminal exact Slice + matching `OUTCOME_UNKNOWN` dispatch intent.

```python
with pytest.raises(CoordinationError) as exc_info:
    project_execution_recovery(stored_saga, slice_hash, dispatch_intent)
assert exc_info.value.code == "HOST_RECOVERY_EVIDENCE_CONFLICT"
```

#### Step 4: Write exact-Slice RED

Pass an execution slice hash absent from `stored_saga.definition.ordered_slice_hashes`.

```python
with pytest.raises(CoordinationError) as exc_info:
    project_execution_recovery(stored_saga, "f" * 64, dispatch_intent)
assert exc_info.value.code == "SAGA_INTEGRITY_INVALID"
```

#### Step 5: Verify RED

```bash
uv run pytest tests/execution_coordination/test_task8_execution_recovery_projection.py -q
```

Expected: the public projection types/function do not exist.

#### Step 6: Implement minimal read-only projection

Implement the matrix in Execution Coordination by reusing the same terminal status set, exact `_slice_state()` semantics, `UnknownOutcomeRecovery` intent vocabulary, and coordinator write ordering already present in this package.

The helper must not:

```text
probe Host
mutate dispatch intent
mutate Saga
run Step33 reconciliation
run convergence
schedule retry
```

It only classifies already-durable owner truth.

#### Step 7: Run GREEN + existing owner regressions

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

#### Step 8: Commit Task 8.3

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

**Consumes:** Task 8.1 exact Provider Binding lookup, Task 8.2 `HostDispatchIntentStore`, Task 8.3 owner recovery projection, real `MaterializedExecutionSagaCoordinator`, real `ExecutionReconciliationServiceV2`, real Saga store, real Gateway V2, real convergence builder/verifier.

**Existing workflow-facing signatures remain:**

```text
begin_execution(execution_plan_ref: StableRef, grant_ref: StableRef) -> str | AsyncOperationRef
get_execution_owner_state(saga_id: str) -> ExecutionOwnerView
verify_reconcile(saga_id: str) -> ExecutionOwnerView
```

**Constructor addition required by the approved spec:**

```text
dispatch_intent_store
execution_recovery_projection
```

Reference composition passes the **same logical dispatch-intent store instance** to the coordinator and the adapter, and passes the approved Execution Coordination projection callable/service as `execution_recovery_projection`. The adapter must not instantiate either dependency. No runtime object-identity assertion is added to production code.

#### Step 1: Write constructor/composition RED

Extend the existing constructor-shape/composition test so `CanonicalWorkflowOwnerPorts` receives both new explicit dependencies. Build one `InMemoryHostDispatchIntentStore`, pass that object to the real coordinator and to the adapter, and pass `project_execution_recovery` as the projection dependency.

Assert only fixture composition identity:

```python
assert coordinator_dispatch_store is shared_dispatch_store
assert adapter_dispatch_store is shared_dispatch_store
```

Do not add production introspection to prove identity.

#### Step 2: Write real success RED

Create `tests/orchestrator/test_canonical_owner_execution.py` using real:

```text
ExecutionReconciliationServiceV2
MaterializedExecutionSagaCoordinator
ExecutionSagaStoreV2
InMemoryHostDispatchIntentStore
CrossHostConvergenceVerifier
project_execution_recovery
```

Use only allowed Host/evidence/clock doubles.

Drive `begin_execution()` from exact execution-plan/grant refs and assert:

```python
saga_id = ports.begin_execution(execution_plan_ref, grant_ref)
assert isinstance(saga_id, str)
view = ports.get_execution_owner_state(saga_id)
assert view.saga.status == "SUCCEEDED"
assert view.active_dispatch_recovery is None
assert counting_host.execute_calls == 1
```

Read the matching dispatch row separately and allow/assert `HOST_COMMITTED`; success must still project terminal/no-active-recovery.

#### Step 3: Write real DIVERGED RED

Inject divergent evidence only through the allowed evidence boundary. Assert:

```text
real convergence result = DIVERGED
real Saga status = DIVERGED
ExecutionOwnerView.saga.status = DIVERGED
active_dispatch_recovery = None
Host execute count = 1
no compensation API is invoked
```

#### Step 4: Write unknown-outcome safe-wait RED

Have Host execute return `COMMIT_STATE_UNKNOWN`. Assert:

```text
durable Saga exists
durable dispatch intent status = OUTCOME_UNKNOWN
begin_execution returns AsyncOperationRef
AsyncOperationRef.kind = EXECUTION_JOB
AsyncOperationRef.owner = execution
AsyncOperationRef.operation_id = durable Saga id
get_execution_owner_state(saga_id).active_dispatch_recovery.state = OUTCOME_UNKNOWN
Host execute count = 1
```

Call `begin_execution()` a second time with the same execution-plan/grant lineage. Existing coordinator replay behavior must observe the active durable Saga and return recovery without reaching Host again; Host execute count remains `1`.

#### Step 5: Write Provider Binding hash-join negative

Arrange a grant/authority whose exact `binding_set_hash` is unresolved. Assert failure occurs before coordinator/Host execution and adapter code never derives `PBSV2-<first12>`.

#### Step 6: Write architecture RED

Extend `tests/architecture/test_real_owner_workflow_boundaries.py` so production adapter source fails the guard if it references:

```text
provider binding `_items`
PostgresHostDispatchIntentStore private selector names
manual PBSV2 hash-prefix derivation
adapter-local saga->dispatch map
adapter-local grant->binding map
adapter-local terminal/recovery status matrix
ScenarioOwners/test authority
V1 execution surfaces
```

Also assert the approved projection dependency is explicit rather than imported from a private module.

#### Step 7: Verify RED

```bash
uv run pytest \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  -q
```

Expected: execution methods remain fail-closed/not wired and constructor shape lacks the two approved dependencies.

#### Step 8: Implement request assembly and owner projection consumption

`begin_execution()` performs only this sequence:

```text
resolve exact ExecutionPlanV2 by ref id and full hash
require grant_ref.content_hash
resolve exact Gateway grant by that full hash
obtain the admitted authority through Gateway public API
resolve binding set through provider_binding_store.get_by_hash(authority.binding_set_hash)
require returned full binding hash == authority.binding_set_hash
resolve exact ChangeSet, Approval Scope boundary, and MaterializationPlan from owner stores
rebuild convergence profile through design_convergence public builder
require rebuilt convergence hash matches frozen plan lineage
call MaterializedExecutionSagaCoordinator.execute
map coordinator SUCCEEDED/DIVERGED/FAILED/PARTIALLY_COMMITTED to durable saga_id
map coordinator RECOVERY_REQUIRED to execution AsyncOperationRef carrying durable saga_id
map READINESS_FAILED/NOT_CREATED to a stable fail-closed workflow error
```

`get_execution_owner_state()` performs only:

```text
load StoredExecutionSagaV2 by saga_id
require exactly one ordered_slice_hash for current workflow scope
read dispatch_intent_store.get_for_saga_slice(saga_id, exact_slice_hash)
call injected execution_recovery_projection(stored_saga, exact_slice_hash, intent)
map owner disposition to HostDispatchRecoveryView when disposition is non-null
return ExecutionOwnerView
```

`verify_reconcile()` reuses the same owner read/projection. It returns only when Saga is terminal and active unresolved recovery is absent. It does not run a second reconciler.

#### Step 9: Run GREEN

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

#### Step 10: Commit Task 8.4

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

**Consumes:** existing `AsyncOperationRef`, `AsyncOperationKind.EXECUTION_JOB`, `saga_id` graph state field, existing saver-backed graph tests.

**Produces:** one atomic `apply_or_recover` state update containing durable Saga identity plus execution wait navigation.

#### Step 1: Write execution-async atomic-state RED

Have the test service return:

```python
AsyncOperationRef(
    kind=AsyncOperationKind.EXECUTION_JOB,
    owner="execution",
    operation_id="SAGA-123",
)
```

Read the persisted state through the supported graph/saver API and assert:

```python
assert snapshot.values["saga_id"] == "SAGA-123"
assert snapshot.values["resume_node"] == "refresh_execution_owner"
assert snapshot.values["phase"] == WorkflowPhase.APPLY_WAIT.value
assert snapshot.values["async_operation_ref"]["operation_id"] == "SAGA-123"
```

#### Step 2: Write non-execution async negative

Return another valid async kind and assert that its `operation_id` is not copied into `saga_id`.

#### Step 3: Write resume/no-redispatch RED

Resume from saver-backed execution wait with durable `saga_id`. Have `get_execution_owner_state()` return `ExecutionOwnerView` with active `OUTCOME_UNKNOWN` recovery and assert:

```text
refresh_execution_owner -> RECOVER_OR_WAIT
begin_execution call count does not increase
Host/service mutation call count does not increase
```

The graph must re-read owner truth and must not infer Host outcome from checkpoint position.

#### Step 4: Verify RED

```bash
uv run pytest tests/orchestrator/test_langgraph_graph.py -k "execution and saga" -q
```

Expected: current execution async branch saves the wait but not Saga identity.

#### Step 5: Implement minimal graph change

Inside `apply_or_recover`, only an async result satisfying both conditions:

```text
kind == AsyncOperationKind.EXECUTION_JOB
owner == "execution"
```

may copy `operation_id` into `saga_id`. Merge that field into the **same node update** returned with `async_operation_ref`, `resume_node="refresh_execution_owner"`, and `phase=APPLY_WAIT`.

Do not change topology or `decide_apply_resume()`.

#### Step 6: Run GREEN + runtime regression

```bash
uv run pytest \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_langgraph_runtime.py \
  -q

uv run ruff check \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py
```

#### Step 7: Commit Task 8.5

```bash
git add \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py

git commit -m "fix: persist saga identity with execution wait"
```

---

### Task 8.6: Close Task 8 with safe-wait and exact-head PostgreSQL evidence

**Files:**
- Modify tests only if one closure assertion is missing from Tasks 8.1–8.5.
- Inspect: `.github/workflows/durable-persistence.yml`
- Do not edit CI unless the exact implementation HEAD proves the existing job no longer collects `tests/execution_reconciliation/test_postgres_dispatch_intent.py`.

#### Step 1: Re-prove the external recovery boundary

```bash
uv run pytest \
  tests/execution_coordination/test_unknown_outcome_recovery.py \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  -q
```

Required evidence:

```text
UnknownOutcomeRecovery depends on HostOutcomeProbe, not a Host mutation port
insufficient probe evidence may leave OUTCOME_UNKNOWN unresolved
before-commit evidence may advance durable intent to SAFE_TO_RETRY
commit evidence may advance existing reconciliation/dispatch truth
workflow-owned scheduling is not asserted
```

#### Step 2: Run focused Task 8 suite

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

A local PostgreSQL skip is development evidence only and cannot close Task 8.

#### Step 3: Run owner regressions

```bash
uv run pytest \
  tests/provider_binding \
  tests/execution_reconciliation \
  tests/execution_coordination \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/orchestrator/test_default_workflow_services.py \
  -q
```

#### Step 4: Run Ruff and whitespace gate

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

Use the repository no-new-diagnostics policy for unrelated historical Ruff findings. New Task 8 diagnostics are not suppressible closure evidence.

#### Step 5: Push exact Task 8 HEAD and verify PostgreSQL 17 lane

The exact closing SHA must have `durable-persistence.yml / execution-saga-postgres` at `completed / success`.

Inspect the job log and prove that the new shared Task 8 contract cases inside `test_postgres_dispatch_intent.py` were collected and **not skipped**. Workflow-level SUCCESS without collection evidence is insufficient.

#### Step 6: Record Task 8 closure

Record all of:

```text
Provider Binding exact full-hash success GREEN
same-first12/different-full-hash negative GREEN
in-memory dispatch store shared contract GREEN
PostgreSQL dispatch store shared contract non-skipped GREEN
SUCCEEDED + HOST_COMMITTED terminal projection GREEN
FAILED_BEFORE_COMMIT + SAFE_TO_RETRY terminal projection GREEN
terminal + OUTCOME_UNKNOWN conflict code GREEN
real coordinator SUCCEEDED GREEN
real coordinator DIVERGED GREEN
unknown outcome -> execution AsyncOperationRef carrying durable saga_id GREEN
atomic saga_id + wait checkpoint GREEN
resume -> RECOVER_OR_WAIT without redispatch GREEN
UnknownOutcomeRecovery external-entrypoint safety regression GREEN
architecture guard GREEN
exact-head PostgreSQL 17 lane GREEN
```

Only then mark Task 8 CLOSED and continue to Task 9.

---

# Task 9

### Task 9: Add real-owner LangGraph E2E A–D/F/G plus execution safe-wait acceptance

**Files:**
- Create: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Modify: `tests/architecture/test_real_owner_workflow_boundaries.py`
- Preserve: `tests/orchestrator/test_workflow_end_to_end.py::_ScenarioOwners`

**Consumes:** closed Task 8 real execution composition plus the already-closed Task 6/7 real-owner path.

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
real injected execution recovery projection
explicit deterministic environment/presentation boundaries only
```

#### Step 1: Happy-path RED A

Drive one canonical operation through proposal HITL and approval to terminal `WorkflowPhase.COMPLETED`. Assert the final `saga_id` resolves from the real Saga store and every final ref resolves through its authoritative store.

#### Step 2: HITL RED B

Assert exact proposal `pause_id`, stale/wrong-pause rejection, and ACCEPT continuing into the same real-owner composition. Preserve predecessor HITL semantics.

#### Step 3: Async freshness RED C

Force semantic reconstruction async wait. After resume, assert the operation/planning-snapshot/snapshot-set tuple is newly persisted atomically and Impact consumes that exact tuple.

#### Step 4: Missing-owner-ref RED D

Remove one authoritative owner-local object after checkpoint, reconstruct the workflow runtime, and resume. Assert fail closed and zero downstream Host mutation calls. The checkpoint must not recreate missing owner truth.

#### Step 5: Unknown execution safe-wait RED

Drive Host execute to `COMMIT_STATE_UNKNOWN`. Through the supported PostgreSQL saver API assert:

```text
saga_id = durable Saga id
phase = APPLY_WAIT
resume_node = refresh_execution_owner
execution async operation_id = the same Saga id
```

Resume once and assert:

```text
owner read exposes OUTCOME_UNKNOWN
workflow route remains RECOVER_OR_WAIT
Host execute count remains exactly 1
```

Do not call `UnknownOutcomeRecovery` from workflow code in this test.

#### Step 6: Refs-only checkpoint RED F

Inspect persisted state after success and after unknown-outcome wait. Reject serialized bodies of:

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

Stable refs, navigation fields, and `saga_id` are allowed.

#### Step 7: Architecture RED/GREEN G

The real-owner E2E module may not import/construct `_ScenarioOwners`, private owner selectors/dicts, V1 execution surfaces, or a test-authored Saga/dispatch/recovery state machine.

#### Step 8: Run GREEN

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/orchestrator/test_real_owner_workflow_end_to_end.py -q

uv run pytest tests/architecture/test_real_owner_workflow_boundaries.py -q

uv run ruff check \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
```

#### Step 9: Commit Task 9

```bash
git add \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/architecture/test_real_owner_workflow_boundaries.py

git commit -m "test: add real owner workflow end to end acceptance"
```

---

# Task 10

### Task 10: Prove durable safe-wait restart/no-double-Host behavior and close exact-head CI

**Files:**
- Modify: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Inspect: `.github/workflows/workflow-orchestrator.yml`
- Inspect: `.github/workflows/durable-persistence.yml`
- Inspect: `.github/workflows/phase-i-real-cross-host-materialization-saga.yml`
- Inspect: `.github/workflows/step37-cross-host-saga-failure-injection.yml`
- Inspect: `.github/workflows/repository-regression.yml`
- Modify a workflow file only if exact current collection proves the required test is not scheduled.

**Consumes:** PostgreSQL workflow checkpoint/artifact stores, PostgreSQL Saga/dispatch stores, real Task 8 composition, public `UnknownOutcomeRecovery`.

**Produces:** durability and final implementation evidence only. It does not add autonomous recovery scheduling.

#### Step 1: PostgreSQL fresh-runtime/no-double-Host RED E

Use real PostgreSQL for workflow checkpoint/artifact state and real PostgreSQL Saga/dispatch persistence:

```text
runtime A reaches durable Saga + OUTCOME_UNKNOWN
Host execute count = 1
close/discard runtime A and its checkpointer/artifact/Saga/dispatch connections
construct runtime B with fresh connections/services over the same PostgreSQL data
resume the same workflow id/thread id
runtime B restores durable saga_id from checkpoint
runtime B re-reads exact Saga/Slice dispatch owner truth
workflow route = RECOVER_OR_WAIT
Host execute count remains 1
```

Do not share an in-memory Saga store, dispatch store, or workflow artifact store across runtime A/B.

#### Step 2: Prove explicit external recovery advancement is observable

From the durable unknown state, resolve recovery inputs from public owner truth rather than test locals:

```python
durable_saga = reconciliation.get_saga(saga_id)
assert durable_saga is not None
exact_slice = execution_plan.execution_slices[0]
authority = gateway_authorization.admit_execution_grant(
    grant_ref.content_hash,
    observed_at,
)
binding_set = provider_binding_store.get_by_hash(authority.binding_set_hash)
dispatch_intent = dispatch_intent_store.get_for_saga_slice(
    saga_id,
    exact_slice.execution_slice_hash,
)
assert dispatch_intent is not None

result = unknown_outcome_recovery.recover(
    stored_saga=durable_saga,
    execution_slice=exact_slice,
    authority=authority,
    binding_set=binding_set,
    dispatch_intent=dispatch_intent,
)
```

Then construct/read through fresh workflow services again and assert they observe the updated authoritative Saga/dispatch truth.

Stop the assertion at what the current owners actually guarantee. Depending on `HostOutcomeProbe` evidence, the test may prove `SAFE_TO_RETRY`, reconciled Slice truth, or another durable projection. It must not require workflow-owned recovery scheduling or final convergence unless current owner semantics already reach that state without new production changes.

#### Step 3: Preserve fast scenario regression

```bash
uv run pytest tests/orchestrator/test_workflow_end_to_end.py -q
```

`_ScenarioOwners` remains legal only in that fast orchestration regression.

#### Step 4: Run PostgreSQL capability suite

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py \
  tests/orchestrator/test_artifact_postgres.py \
  tests/execution_reconciliation/test_postgres_dispatch_intent.py \
  tests/execution_reconciliation/test_postgres_saga_store_v2.py \
  tests/execution_coordination/test_host_effect_crash_windows.py \
  -q
```

Developer-machine PostgreSQL skips are not closure evidence.

#### Step 5: Run focused architecture/Ruff/whitespace gates

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

#### Step 6: Scope audit

Compare final implementation HEAD against approved spec HEAD `41d763ada50ed50e9c3322d54e1879b170d5b3fe` and reject unrelated changes in:

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

Expected production changes are limited to the File Structure Freeze plus test-only compatibility edits directly caused by the approved public contracts.

#### Step 7: Push exact final HEAD and require repository CI

Require every PR-triggered workflow for the exact final SHA to reach `completed / success`, with zero failure/in-progress/queued.

At minimum inspect evidence for:

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

For `execution-saga-postgres`, inspect logs and confirm the new Task 8 shared PostgreSQL dispatch contract cases were collected and were not skipped.

#### Step 8: Record final implementation closure

Record:

```text
Task 8 exact owner API/parity evidence
Task 9 A–D/F/G real-owner E2E evidence
unknown-outcome safe-wait E2E evidence
PostgreSQL fresh-runtime no-double-Host evidence
explicit external UnknownOutcomeRecovery advancement observed by a fresh owner read
no claim of autonomous recovery scheduler or guaranteed final convergence
fast _ScenarioOwners regression preserved
scope audit clean
all exact-head PR workflows success
```

Only then mark the implementation phase CLOSED. Merge, merged-main observation, and docs-only lifecycle closeout remain separate gates under the baseline plan.

---

## Acceptance Matrix

| Approved requirement | Plan evidence |
| --- | --- |
| Provider Binding exact hash lookup | Task 8.1 |
| Complete hash equality + same-first12 collision negative | Task 8.1 |
| Public dispatch-intent store contract | Task 8.2 |
| In-memory/PostgreSQL parity | Task 8.2 + Task 8.6 |
| Exact Saga/Slice lookup without active-state filtering | Task 8.2 + Task 8.4 |
| Saga/dispatch precedence owned outside adapter | Task 8.3 + Task 8.4 architecture guard |
| `SUCCEEDED + HOST_COMMITTED` terminal | Task 8.3 + Task 8.4 |
| `FAILED_BEFORE_COMMIT + SAFE_TO_RETRY` terminal while evidence remains durable | Task 8.3 |
| terminal + incompatible `OUTCOME_UNKNOWN` fail closed | Task 8.3 |
| Same dispatch store composed into coordinator + adapter | Task 8.4 composition test |
| Recovery projection explicitly injected | Task 8.4 constructor/composition test |
| Real Saga success | Task 8.4 |
| Real DIVERGED without compensation | Task 8.4 |
| Unknown outcome persists and cannot blind redispatch | Task 8.4 / 8.5 / 9 / 10 |
| Saga id + execution wait atomic checkpoint | Task 8.5 |
| Task 8 safe-wait boundary | Task 8.6 |
| `UnknownOutcomeRecovery.recover` remains external recovery entrypoint | Task 8.6 + Task 10 |
| Real-owner E2E A–D/F/G | Task 9 |
| Durable PostgreSQL fresh-runtime no-double-Host proof | Task 10 |
| PostgreSQL formal closure non-skipped | Task 8.6 + Task 10 |
| Exact-head repository regression | Task 10 |

---

## STOP Conditions

Stop implementation and return to Design/Plan if any RED or repository fact proves one of these conditions:

```text
Provider Binding cannot provide exact full-hash lookup without changing its identity contract beyond the approved spec.
Dispatch-intent durable uniqueness is not actually saga_id + execution_slice_hash.
In-memory/PostgreSQL stores cannot share the approved public contract without broader persistence redesign.
Execution Coordination cannot derive the approved terminal/recovery combinations from existing durable Saga/Slice/dispatch truth.
Canonical begin_execution cannot reconstruct coordinator inputs through public owner APIs without a new reverse index or private cache.
Task 7 exactly-one-slice assumption is no longer true on the implementation HEAD.
LangGraph cannot atomically persist saga_id with execution wait using the existing state/checkpointer model.
Formal PostgreSQL CI cannot execute the new contract cases non-skipped without a CI architecture change.
A requirement would need autonomous recovery scheduling or generic materialized forward-resume/convergence continuation.
```

Do not manufacture GREEN by adding adapter-private maps, selecting latest/current rows, deriving owner ids from hash prefixes inside the adapter, weakening full-hash equality, treating timeout as proof of non-commit, or relabeling safe wait as complete recovery.

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

After approval, execute strictly:

```text
Task 8.1 Provider Binding exact-hash RED/GREEN
→ Task 8.2 dispatch store public contract + in-memory/PostgreSQL parity RED/GREEN
→ Task 8.3 execution recovery projection RED/GREEN
→ Task 8.4 canonical execution-owner wiring RED/GREEN
→ Task 8.5 atomic Saga-id execution wait RED/GREEN
→ Task 8.6 focused + exact-head PostgreSQL Task 8 closure
→ Task 8 CLOSED
→ Task 9 real-owner E2E acceptance
→ Task 10 PostgreSQL fresh-runtime durability + exact-head repository closure
```