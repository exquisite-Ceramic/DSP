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

```text
branch: feat/capability-real-owner-e2e-workflow
approved spec head: 41d763ada50ed50e9c3322d54e1879b170d5b3fe
Task 7: CLOSED
Task 8 product implementation: NOT STARTED
```

The currently unwired execution seam is:

```text
CanonicalWorkflowOwnerPorts.begin_execution
CanonicalWorkflowOwnerPorts.get_execution_owner_state
CanonicalWorkflowOwnerPorts.verify_reconcile
```

`durable-persistence.yml` already owns PostgreSQL 17 job `execution-saga-postgres` and already executes `tests/execution_reconciliation/test_postgres_dispatch_intent.py`. This plan therefore does not authorize a CI workflow edit by default. New PostgreSQL parity assertions must live in that already-collected test surface.

---

## Global Constraints

- Task 7 remains CLOSED and must not be rolled back.
- `CanonicalWorkflowOwnerPorts` may assemble requests and consume public read models; it must not own Provider Binding identity rules, dispatch transition rules, Saga/dispatch precedence, reconciliation, convergence, or retry policy.
- `get_by_hash(binding_set_hash)` validates canonical lowercase SHA-256 and proves `returned.binding_set_hash == requested_binding_set_hash` before returning.
- A same-first-12-hex/different-full-hash case fails closed. A matching short content-addressed id is never sufficient evidence of exact hash equality.
- Malformed binding hashes retain the owner digest-validation behavior (`ValueError`). A missing exact artifact uses `PROVIDER_BINDING_SET_REFERENCE_NOT_FOUND`. A short-id collision/full-hash mismatch uses existing owner code `PROVIDER_BINDING_INTEGRITY_INVALID`.
- `HostDispatchIntentStore.get_for_saga_slice(saga_id, execution_slice_hash)` is an exact owner lookup. It never filters by active/terminal Saga state and never selects a latest/current row.
- In-memory and PostgreSQL dispatch-intent stores implement the same public contract and preserve the same replay/CAS semantics.
- Formal Task 8 closure requires PostgreSQL contract cases to run **non-skipped** and pass on the exact Task 8 closing SHA.
- Workflow recovery reads the exact Slice identity from the durable Saga definition. Current workflow scope remains exactly one `ExecutionSliceV2`; multi-slice workflow expansion is out of scope.
- Saga/dispatch precedence belongs to Execution Coordination. The orchestrator adapter does not encode a private status matrix.
- `SUCCEEDED + Slice SUCCEEDED + HOST_COMMITTED` means no active unresolved workflow recovery.
- `FAILED + Slice FAILED_BEFORE_COMMIT + SAFE_TO_RETRY` means no active unresolved workflow recovery; the durable `SAFE_TO_RETRY` row remains observable in the owner store.
- Terminal Saga plus incompatible unresolved `OUTCOME_UNKNOWN` fails closed with `CoordinationError.code == "HOST_RECOVERY_EVIDENCE_CONFLICT"`.
- `UnknownOutcomeRecovery.recover` remains the explicit public external recovery entrypoint. Task 8 does not add a scheduler/worker and does not claim autonomous recovery to final convergence.
- When `begin_execution()` returns an execution `AsyncOperationRef`, graph state atomically persists its `operation_id` as `saga_id` together with async ref, resume node, and `APPLY_WAIT` phase.
- Checkpoints contain ids/refs/navigation only. They do not persist `HostDispatchIntent`, `StoredExecutionSagaV2`, `ProviderBindingSetV2`, `ExecutionPlanV2`, `ActualDelta`, or other authoritative owner bodies.
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
6. **Dependency ownership:** reference composition explicitly injects both the same logical dispatch-intent store used by the coordinator and the approved execution-recovery projection callable/service. The adapter creates neither dependency itself.

Every focus item has a direct RED/GREEN test below.

---

## Supersession of Baseline Tasks 8–10

This plan supersedes only Task 8/9/10 portions of `docs/superpowers/plans/2026-09-20-real-owner-e2e-workflow.md`.

These historical assumptions are no longer implementation authority:

```text
Task 8 can use the existing dispatch-intent surface without a public store contract.
Task 8 may derive Provider Binding identity from a binding hash inside the adapter.
Task 8 may classify recovery from active Slice + dispatch enum inside the adapter.
Task 10 unknown-outcome acceptance must automatically recover/reconcile to terminal.
```

Corrected sequence:

```text
Task 8 owner API/parity + canonical execution wiring + safe wait
→ Task 9 real-owner LangGraph E2E A–D/F/G + unknown-outcome safe-wait acceptance
→ Task 10 durable PostgreSQL restart/no-double-Host proof + exact-head repository closure
```

Task 10 may explicitly invoke `UnknownOutcomeRecovery.recover` from the test/composition boundary and prove that a fresh workflow read observes updated owner truth. It must not claim workflow-owned scheduling or guaranteed final convergence.

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
| `tests/execution_reconciliation/dispatch_intent_store_contract.py` | Backend-neutral shared store assertions |
| `tests/execution_reconciliation/test_dispatch_intent_store.py` | In-memory store contract |
| `tests/execution_reconciliation/test_postgres_dispatch_intent.py` | Existing PostgreSQL lane + shared Task 8 contract |
| `tests/execution_coordination/test_task8_execution_recovery_projection.py` | Owner precedence/conflict matrix |
| `tests/orchestrator/test_canonical_owner_execution.py` | Real Saga/coordinator/reconciliation success, DIVERGED, unknown safe wait |
| `tests/orchestrator/test_canonical_owner_ports.py` | Constructor shape + explicit dependency composition regression |
| `tests/orchestrator/test_langgraph_graph.py` | Atomic Saga id/wait and recovery resume routing |
| `tests/orchestrator/test_real_owner_workflow_end_to_end.py` | Real-owner LangGraph acceptance |
| `tests/architecture/test_real_owner_workflow_boundaries.py` | No private lookup/maps/status matrix/V1/test authority |
| `.github/workflows/durable-persistence.yml` | Inspect only by default; PostgreSQL 17 already collects `test_postgres_dispatch_intent.py` |

If implementation proves a required production file outside this table is necessary, stop and amend the plan before editing that file.

---

# Task 8

## Task 8.1: Add exact Provider Binding hash lookup

**Files:**
- Modify: `platform/provider_binding/src/design_provider_binding/store_v2.py`
- Modify only if public export changes: `platform/provider_binding/src/design_provider_binding/__init__.py`
- Create: `tests/provider_binding/test_task8_hash_lookup.py`

**Consumes:** `ProviderBindingSetV2`, `ProviderBindingError`, `resolve_provider_bindings_v2`, `tests.provider_binding._support.build_phase_i_binding_inputs`.

**Produces public method:**

```text
InMemoryProviderBindingSetV2Store.get_by_hash(binding_set_hash: str) -> ProviderBindingSetV2
```

- [ ] **Step 1: Write exact-hash success RED**

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

- [ ] **Step 2: Write same-prefix/different-full-hash RED**

Use `dataclasses.replace` on a real V2 binding set. This deliberately creates a structurally valid local id/hash pair while preserving an intentionally synthetic full hash, which isolates the store lookup contract from full Step31 semantic validation.

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

- [ ] **Step 3: Write malformed/unresolved REDs**

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

- [ ] **Step 4: Verify RED**

```bash
uv run pytest tests/provider_binding/test_task8_hash_lookup.py -q
```

Expected: RED because `InMemoryProviderBindingSetV2Store` has no `get_by_hash()`.

- [ ] **Step 5: Implement minimal owner lookup**

Add owner-local canonical digest validation in `store_v2.py`. Resolve by owner-managed index or owner-managed short id, re-run `_validate_reference()`, then enforce complete equality before return:

```python
_validate_reference(binding_set)
if binding_set.binding_set_hash != requested_hash:
    raise ProviderBindingError(
        "PROVIDER_BINDING_INTEGRITY_INVALID",
        "ProviderBindingSetV2 full hash does not match requested owner hash",
    )
return binding_set
```

The adapter never derives this id and never reads `_items`.

- [ ] **Step 6: Run GREEN + owner regression**

```bash
uv run pytest tests/provider_binding/test_task8_hash_lookup.py tests/provider_binding -q
uv run ruff check \
  platform/provider_binding/src/design_provider_binding/store_v2.py \
  tests/provider_binding/test_task8_hash_lookup.py
```

- [ ] **Step 7: Commit Task 8.1**

```bash
git status --short
git add \
  platform/provider_binding/src/design_provider_binding/store_v2.py \
  tests/provider_binding/test_task8_hash_lookup.py
git commit -m "feat: add exact provider binding hash lookup"
```

If `design_provider_binding/__init__.py` actually changed, stage it explicitly after confirming the diff.

---

## Task 8.2: Publish one HostDispatchIntentStore contract and prove in-memory/PostgreSQL parity

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent_store.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/dispatch_intent_store_contract.py`
- Create: `tests/execution_reconciliation/test_dispatch_intent_store.py`
- Modify: `tests/execution_reconciliation/test_postgres_dispatch_intent.py`

**Consumes:** `HostDispatchIntent`, `HostDispatchStatus`, `build_host_dispatch_intent`, `ReconciliationError`, existing PostgreSQL CAS/observation implementation.

**Produces protocol methods:**

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

`InMemoryHostDispatchIntentStore` implements the complete protocol. `PostgresHostDispatchIntentStore` satisfies the same protocol without exposing `_select_by_slice()`.

- [ ] **Step 1: Create deterministic shared contract fixtures**

At the top of `tests/execution_reconciliation/dispatch_intent_store_contract.py` use a local digest helper and the real domain builder:

```python
from hashlib import sha256

from design_execution_reconciliation import build_host_dispatch_intent


def _digest(label: str) -> str:
    return sha256(label.encode("utf-8")).hexdigest()


def make_intent(label: str):
    return build_host_dispatch_intent(
        saga_id=f"SAGA-{label}",
        execution_slice_hash=_digest(f"slice:{label}"),
        grant_hash=_digest(f"grant:{label}"),
        binding_set_hash=_digest(f"binding:{label}"),
        host_instance_id="host-A",
        document_ref="doc-A",
        expected_host_revision=None,
        prepared_at="2026-09-23T00:00:00Z",
    )
```

- [ ] **Step 2: Add backend-neutral lookup/replay/transition contract**

Create explicit shared assertion functions. Core cases are:

```python
def assert_lookup_and_replay_contract(store) -> None:
    candidate = make_intent("lookup")
    prepared = store.prepare(candidate)
    replayed = store.prepare(candidate)
    assert replayed == prepared
    assert store.get(prepared.dispatch_intent_id) == prepared
    assert store.get_for_saga_slice(
        prepared.saga_id,
        prepared.execution_slice_hash,
    ) == prepared


def assert_unknown_contract(store) -> None:
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


def assert_committed_reconciled_contract(store) -> None:
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


def assert_safe_retry_contract(store) -> None:
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

Also add explicit helpers proving:

```text
same saga_id + execution_slice_hash with different grant/binding lineage -> DISPATCH_INTENT_CONFLICT
stale expected_revision on a transition -> DISPATCH_INTENT_CONFLICT
```

Build the conflicting second intent with the same Saga/Slice and different full `grant_hash`/`binding_set_hash`; do not mutate private store state.

- [ ] **Step 3: Add in-memory RED**

Create `tests/execution_reconciliation/test_dispatch_intent_store.py` and invoke every shared assertion against `InMemoryHostDispatchIntentStore`.

Expected RED: public protocol/reference implementation does not exist.

- [ ] **Step 4: Add PostgreSQL RED in the existing CI-collected file**

Modify `tests/execution_reconciliation/test_postgres_dispatch_intent.py` to invoke the same shared assertions against `PostgresHostDispatchIntentStore` under `DSP_TEST_POSTGRES_DSN`.

After a row reaches a non-PREPARED state, assert exact lookup still returns it:

```python
resolved = store.get_for_saga_slice(
    intent.saga_id,
    intent.execution_slice_hash,
)
assert resolved is not None
assert resolved.dispatch_intent_id == intent.dispatch_intent_id
```

- [ ] **Step 5: Verify RED**

```bash
uv run pytest tests/execution_reconciliation/test_dispatch_intent_store.py -q
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/execution_reconciliation/test_postgres_dispatch_intent.py -q
```

Expected: missing public reference store/protocol and missing public `get_for_saga_slice()`.

- [ ] **Step 6: Implement public protocol + in-memory owner store**

Create `dispatch_intent_store.py` with owner-private exact indexes:

```text
dispatch_intent_id -> HostDispatchIntent
(saga_id, execution_slice_hash) -> dispatch_intent_id
```

`prepare()` rejects different admitted lineage for an existing Saga/Slice with `DISPATCH_INTENT_CONFLICT`. Transition methods enforce `expected_revision` CAS and return a new immutable revision. If replay/CAS validation is extracted, keep it in `design_execution_reconciliation` and reuse it from both backends.

- [ ] **Step 7: Implement PostgreSQL public exact lookup**

Add public signature:

```text
PostgresHostDispatchIntentStore.get_for_saga_slice(
    saga_id: str,
    execution_slice_hash: str,
) -> HostDispatchIntent | None
```

Validate inputs, use the store's existing transaction boundary, call `_select_by_slice()` only internally, and decode zero/one row. No Saga-active predicate is added.

- [ ] **Step 8: Run GREEN + recovery regressions**

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

- [ ] **Step 9: Commit Task 8.2**

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

## Task 8.3: Put Saga/dispatch recovery precedence in Execution Coordination

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/recovery.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Create: `tests/execution_coordination/test_task8_execution_recovery_projection.py`

**Consumes:** `StoredExecutionSagaV2`, `SliceReconciliationStateV2`, `ExecutionSagaStatusV2`, `SliceReconciliationStatusV2`, `HostDispatchIntent`, `HostDispatchStatus`, `CoordinationError`.

**Produces immutable owner projection:**

```python
class ExecutionRecoveryDisposition(str, Enum):
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
    SAFE_TO_RETRY = "SAFE_TO_RETRY"


@dataclass(frozen=True, slots=True)
class ExecutionRecoveryProjection:
    disposition: ExecutionRecoveryDisposition | None
```

Public callable signature:

```text
project_execution_recovery(
    stored_saga: StoredExecutionSagaV2,
    execution_slice_hash: str,
    dispatch_intent: HostDispatchIntent | None,
) -> ExecutionRecoveryProjection
```

`disposition is None` means no active unresolved Host-effect recovery. This module must not import `design_orchestrator`.

- [ ] **Step 1: Write terminal-compatible REDs**

```text
Saga SUCCEEDED + Slice SUCCEEDED + dispatch HOST_COMMITTED
-> disposition is None

Saga FAILED + Slice FAILED_BEFORE_COMMIT + dispatch SAFE_TO_RETRY
-> disposition is None
-> durable dispatch store still returns SAFE_TO_RETRY
```

- [ ] **Step 2: Write unresolved REDs**

For a non-terminal Saga/exact Slice prove:

```text
OUTCOME_UNKNOWN -> OUTCOME_UNKNOWN
SAFE_TO_RETRY -> SAFE_TO_RETRY
PREPARED -> RECOVERY_REQUIRED
DISPATCHED -> RECOVERY_REQUIRED
HOST_COMMITTED -> RECOVERY_REQUIRED
RECONCILED -> None
```

- [ ] **Step 3: Write terminal-conflict RED**

```python
with pytest.raises(CoordinationError) as exc_info:
    project_execution_recovery(stored_saga, slice_hash, dispatch_intent)
assert exc_info.value.code == "HOST_RECOVERY_EVIDENCE_CONFLICT"
```

The fixture is a terminal Saga + terminal exact Slice + matching `OUTCOME_UNKNOWN` intent.

- [ ] **Step 4: Write exact-Slice RED**

```python
with pytest.raises(CoordinationError) as exc_info:
    project_execution_recovery(stored_saga, "f" * 64, dispatch_intent)
assert exc_info.value.code == "SAGA_INTEGRITY_INVALID"
```

- [ ] **Step 5: Verify RED**

```bash
uv run pytest tests/execution_coordination/test_task8_execution_recovery_projection.py -q
```

Expected: public projection types/function do not exist.

- [ ] **Step 6: Implement minimal read-only projection**

Reuse the package's terminal status set, exact `_slice_state()` semantics, `UnknownOutcomeRecovery` intent vocabulary, and existing coordinator write ordering. The helper never probes Host, mutates dispatch state, mutates Saga, runs Step33 reconciliation, runs convergence, or schedules retries.

- [ ] **Step 7: Run GREEN + existing owner regressions**

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

## Task 8.4: Wire real execution owners into CanonicalWorkflowOwnerPorts

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Create: `tests/orchestrator/test_canonical_owner_execution.py`
- Modify: `tests/orchestrator/test_canonical_owner_ports.py`
- Modify: `tests/architecture/test_real_owner_workflow_boundaries.py`

**Consumes:** Task 8.1 exact Provider Binding lookup, Task 8.2 `HostDispatchIntentStore`, Task 8.3 owner recovery projection, real `MaterializedExecutionSagaCoordinator`, real `ExecutionReconciliationServiceV2`, real Saga store, real Gateway V2, real convergence builder/verifier.

**Existing workflow-facing signatures remain:**

```text
begin_execution(execution_plan_ref: StableRef, grant_ref: StableRef) -> str | AsyncOperationRef
get_execution_owner_state(saga_id: str) -> ExecutionOwnerView
verify_reconcile(saga_id: str) -> ExecutionOwnerView
```

**Approved constructor additions:**

```text
dispatch_intent_store
execution_recovery_projection
```

Reference composition passes the same logical dispatch-intent store object to the real coordinator and adapter, and passes `project_execution_recovery` as `execution_recovery_projection`. The adapter instantiates neither dependency. Production code does not add runtime object-identity introspection.

- [ ] **Step 1: Write constructor/composition RED**

Update `tests/orchestrator/test_canonical_owner_ports.py` expected constructor names and the real composition fixture. Build one `InMemoryHostDispatchIntentStore`, inject it into coordinator and adapter, and inject `project_execution_recovery` into adapter.

Fixture-level assertions may prove object reuse:

```python
assert coordinator_dispatch_store is shared_dispatch_store
assert adapter_dispatch_store is shared_dispatch_store
```

No production property or debug API is added solely for this assertion; use fixture variables before constructor calls.

- [ ] **Step 2: Write real success RED**

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

```python
saga_id = ports.begin_execution(execution_plan_ref, grant_ref)
assert isinstance(saga_id, str)
view = ports.get_execution_owner_state(saga_id)
assert view.saga.status == "SUCCEEDED"
assert view.active_dispatch_recovery is None
assert counting_host.execute_calls == 1
```

Read the matching dispatch row separately and permit/assert `HOST_COMMITTED`; success still projects terminal/no-active-recovery.

- [ ] **Step 3: Write real DIVERGED RED**

Inject divergence only through the allowed evidence boundary. Assert real convergence status and Saga status are `DIVERGED`, `ExecutionOwnerView` is terminal with no active recovery, Host execute count is one, and no compensation surface is invoked.

- [ ] **Step 4: Write unknown-outcome safe-wait RED**

Have Host execute return `COMMIT_STATE_UNKNOWN`. Assert:

```text
durable Saga exists
durable dispatch intent status = OUTCOME_UNKNOWN
begin_execution returns execution AsyncOperationRef
operation owner = execution
operation id = durable Saga id
get_execution_owner_state exposes OUTCOME_UNKNOWN active recovery
Host execute count = 1
```

Call `begin_execution()` again for the same execution-plan/grant lineage. Existing coordinator replay behavior must observe the active durable Saga and return recovery without reaching Host; Host execute count remains `1`.

- [ ] **Step 5: Write Provider Binding hash-join negative**

Arrange a grant/authority whose full `binding_set_hash` is unresolved. Assert failure occurs before coordinator/Host execution and adapter source contains no `PBSV2-` derivation.

- [ ] **Step 6: Write architecture RED**

Extend `tests/architecture/test_real_owner_workflow_boundaries.py` to reject production adapter references to:

```text
provider-binding `_items`
PostgresHostDispatchIntentStore private selectors
manual PBSV2 hash-prefix derivation
adapter-local saga->dispatch map
adapter-local grant->binding map
adapter-local terminal/recovery status matrix
ScenarioOwners/test authority
V1 execution surfaces
```

Also require `dispatch_intent_store` and `execution_recovery_projection` to remain explicit constructor dependencies.

- [ ] **Step 7: Verify RED**

```bash
uv run pytest \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py \
  -q
```

Expected: execution methods remain fail-closed/not wired and constructor shape lacks approved dependencies.

- [ ] **Step 8: Implement request assembly and owner projection consumption**

`begin_execution()` only performs:

```text
resolve exact ExecutionPlanV2 by ref id and full hash
require grant_ref.content_hash
resolve Gateway grant using gateway_authorization_store.get_grant_v2(grant_ref.content_hash)
require returned grant exists and full grant_hash equals grant_ref.content_hash
obtain admitted authority through gateway_authorization.admit_execution_grant(grant_hash, admitted_at)
resolve binding set through provider_binding_store.get_by_hash(authority.binding_set_hash)
require returned full binding hash equals authority.binding_set_hash
resolve exact ChangeSet, Approval Scope boundary, MaterializationPlan
rebuild convergence profile through design_convergence public builder
require rebuilt convergence hash matches frozen plan lineage
call MaterializedExecutionSagaCoordinator.execute
map coordinator SUCCEEDED/DIVERGED/FAILED/PARTIALLY_COMMITTED to durable saga_id
map coordinator RECOVERY_REQUIRED to execution AsyncOperationRef carrying durable saga_id
map READINESS_FAILED/NOT_CREATED to stable fail-closed workflow error
```

`get_execution_owner_state()` only performs:

```text
load StoredExecutionSagaV2 by saga_id
require exactly one ordered_slice_hash for current workflow scope
read dispatch_intent_store.get_for_saga_slice(saga_id, exact_slice_hash)
call injected execution_recovery_projection(stored_saga, exact_slice_hash, dispatch_intent)
map non-null owner disposition to HostDispatchRecoveryView
return ExecutionOwnerView
```

`verify_reconcile()` reuses the same owner read/projection and returns only when Saga is terminal and active unresolved recovery is absent. It never runs a second reconciler.

- [ ] **Step 9: Run GREEN**

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

- [ ] **Step 10: Commit Task 8.4**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py \
  tests/orchestrator/test_canonical_owner_execution.py \
  tests/orchestrator/test_canonical_owner_ports.py \
  tests/architecture/test_real_owner_workflow_boundaries.py
git commit -m "feat: wire real execution owner composition"
```

---

## Task 8.5: Atomically persist Saga identity with execution wait

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify: `tests/orchestrator/test_langgraph_graph.py`

**Consumes:** existing `AsyncOperationRef`, `AsyncOperationKind.EXECUTION_JOB`, `saga_id` graph state field, saver-backed graph tests.

- [ ] **Step 1: Write execution-async atomic-state RED**

```python
AsyncOperationRef(
    kind=AsyncOperationKind.EXECUTION_JOB,
    owner="execution",
    operation_id="SAGA-123",
)
```

Read persisted state through supported graph/saver API and assert:

```python
assert snapshot.values["saga_id"] == "SAGA-123"
assert snapshot.values["resume_node"] == "refresh_execution_owner"
assert snapshot.values["phase"] == WorkflowPhase.APPLY_WAIT.value
assert snapshot.values["async_operation_ref"]["operation_id"] == "SAGA-123"
```

- [ ] **Step 2: Write non-execution async negative**

Return another valid async kind and assert its `operation_id` is not copied into `saga_id`.

- [ ] **Step 3: Write resume/no-redispatch RED**

Resume from saver-backed execution wait with durable `saga_id`. Have `get_execution_owner_state()` return `ExecutionOwnerView` with active `OUTCOME_UNKNOWN` recovery. Assert:

```text
refresh_execution_owner -> RECOVER_OR_WAIT
begin_execution call count does not increase
Host/service mutation call count does not increase
```

- [ ] **Step 4: Verify RED**

```bash
uv run pytest tests/orchestrator/test_langgraph_graph.py -k "execution and saga" -q
```

Expected: current execution async branch saves wait navigation but not Saga identity.

- [ ] **Step 5: Implement minimal graph change**

Only an async result satisfying:

```text
kind == AsyncOperationKind.EXECUTION_JOB
owner == "execution"
```

may copy `operation_id` into `saga_id`. Merge the field into the same node update returned with `async_operation_ref`, `resume_node="refresh_execution_owner"`, and `phase=APPLY_WAIT`. Do not change topology or `decide_apply_resume()`.

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

## Task 8.6: Close Task 8 with safe-wait and exact-head PostgreSQL evidence

**Files:**
- Modify tests only if a closure assertion is missing from Tasks 8.1–8.5.
- Inspect: `.github/workflows/durable-persistence.yml`
- Do not edit CI unless exact implementation HEAD proves the existing job no longer collects `tests/execution_reconciliation/test_postgres_dispatch_intent.py`.

- [ ] **Step 1: Re-prove external recovery boundary**

```bash
uv run pytest \
  tests/execution_coordination/test_unknown_outcome_recovery.py \
  tests/execution_coordination/test_task8_execution_recovery_projection.py \
  -q
```

Required evidence:

```text
UnknownOutcomeRecovery depends on HostOutcomeProbe, not a Host mutation port
insufficient evidence may leave OUTCOME_UNKNOWN unresolved
before-commit evidence may advance durable intent to SAFE_TO_RETRY
commit evidence may advance existing reconciliation/dispatch truth
workflow-owned scheduling is not asserted
```

- [ ] **Step 2: Run focused Task 8 suite**

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

A local PostgreSQL skip is development evidence only and cannot close Task 8.

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

- [ ] **Step 4: Run Ruff + whitespace gate**

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

Use repository no-new-diagnostics policy for unrelated historical Ruff findings. New Task 8 diagnostics are not suppressible closure evidence.

- [ ] **Step 5: Push exact Task 8 HEAD and verify PostgreSQL 17 lane**

The exact closing SHA must have `durable-persistence.yml / execution-saga-postgres` at `completed / success`. Inspect the job log and prove new Task 8 shared contract cases inside `test_postgres_dispatch_intent.py` were collected and **not skipped**. Workflow-level SUCCESS without collection evidence is insufficient.

- [ ] **Step 6: Record Task 8 closure**

```text
Provider Binding exact full-hash success GREEN
same-first12/different-full-hash negative GREEN
in-memory dispatch store shared contract GREEN
PostgreSQL dispatch store shared contract non-skipped GREEN
SUCCEEDED + HOST_COMMITTED terminal projection GREEN
FAILED_BEFORE_COMMIT + SAFE_TO_RETRY terminal projection GREEN
terminal + OUTCOME_UNKNOWN conflict code GREEN
same dispatch store composition GREEN
explicit recovery projection dependency GREEN
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

## Task 9: Add real-owner LangGraph E2E A–D/F/G plus execution safe-wait acceptance

**Files:**
- Create: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Modify: `tests/architecture/test_real_owner_workflow_boundaries.py`
- Preserve: `tests/orchestrator/test_workflow_end_to_end.py::_ScenarioOwners`

**Consumes:** closed Task 8 real execution composition plus closed Task 6/7 real-owner path.

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

- [ ] **Step 1: Happy-path RED A**

Drive one canonical operation through proposal HITL and approval to terminal `WorkflowPhase.COMPLETED`. Assert final `saga_id` resolves from the real Saga store and every final ref resolves through its authoritative store.

- [ ] **Step 2: HITL RED B**

Assert exact proposal `pause_id`, stale/wrong-pause rejection, and ACCEPT continuing into the same real-owner composition. Preserve predecessor HITL semantics.

- [ ] **Step 3: Async freshness RED C**

Force semantic reconstruction async wait. After resume, assert operation/planning-snapshot/snapshot-set refs are newly persisted atomically and Impact consumes that exact tuple.

- [ ] **Step 4: Missing-owner-ref RED D**

Remove one authoritative owner-local object after checkpoint, reconstruct workflow runtime, and resume. Assert fail closed and zero downstream Host mutation calls. Checkpoint data must not recreate missing owner truth.

- [ ] **Step 5: Unknown execution safe-wait RED**

Drive Host execute to `COMMIT_STATE_UNKNOWN`. Through supported PostgreSQL saver API assert:

```text
saga_id = durable Saga id
phase = APPLY_WAIT
resume_node = refresh_execution_owner
execution async operation_id = same Saga id
```

Resume once and assert:

```text
owner read exposes OUTCOME_UNKNOWN
workflow route remains RECOVER_OR_WAIT
Host execute count remains exactly 1
```

Do not call `UnknownOutcomeRecovery` from workflow code in this test.

- [ ] **Step 6: Refs-only checkpoint RED F**

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

- [ ] **Step 7: Architecture RED/GREEN G**

The real-owner E2E module may not import/construct `_ScenarioOwners`, private owner selectors/dicts, V1 execution surfaces, or a test-authored Saga/dispatch/recovery state machine.

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

# Task 10

## Task 10: Prove durable safe-wait restart/no-double-Host behavior and close exact-head CI

**Files:**
- Modify: `tests/orchestrator/test_real_owner_workflow_end_to_end.py`
- Inspect: `.github/workflows/workflow-orchestrator.yml`
- Inspect: `.github/workflows/durable-persistence.yml`
- Inspect: `.github/workflows/phase-i-real-cross-host-materialization-saga.yml`
- Inspect: `.github/workflows/step37-cross-host-saga-failure-injection.yml`
- Inspect: `.github/workflows/repository-regression.yml`
- Modify a workflow file only if exact current collection proves the required test is not scheduled.

**Consumes:** PostgreSQL workflow checkpoint/artifact stores, PostgreSQL Saga/dispatch stores, real Task 8 composition, public `UnknownOutcomeRecovery`.

**Produces:** durability/final implementation evidence only; it does not add autonomous recovery scheduling.

- [ ] **Step 1: PostgreSQL fresh-runtime/no-double-Host RED E**

Use real PostgreSQL for workflow checkpoint/artifact state and real PostgreSQL Saga/dispatch persistence:

```text
runtime A reaches durable Saga + OUTCOME_UNKNOWN
Host execute count = 1
close/discard runtime A and its checkpointer/artifact/Saga/dispatch connections
construct runtime B with fresh connections/services over same PostgreSQL data
resume same workflow id/thread id
runtime B restores durable saga_id from checkpoint
runtime B re-reads exact Saga/Slice dispatch owner truth
workflow route = RECOVER_OR_WAIT
Host execute count remains 1
```

Do not share an in-memory Saga store, dispatch store, or workflow artifact store across runtime A/B.

- [ ] **Step 2: Prove explicit external recovery advancement is observable**

Resolve recovery inputs from public owner truth rather than stale test-local bodies:

```python
assert grant_ref.content_hash is not None
durable_saga = reconciliation.get_saga(saga_id)
assert durable_saga is not None
exact_slice = execution_plan.execution_slices[0]
authority = gateway_authorization.admit_execution_grant(
    grant_ref.content_hash,
    "2026-09-23T00:10:00Z",
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

The second argument to `admit_execution_grant` is the existing public `admitted_at: str` parameter. Admission is idempotent for an already-admitted grant and returns the durable admitted authority.

Then construct/read through fresh workflow services again and assert they observe updated authoritative Saga/dispatch truth.

Stop at what current owners guarantee. Depending on `HostOutcomeProbe` evidence, the test may prove `SAFE_TO_RETRY`, reconciled Slice truth, or another durable projection. It must not require workflow-owned recovery scheduling or final convergence unless current owner semantics already reach that state without new production changes.

- [ ] **Step 3: Preserve fast scenario regression**

```bash
uv run pytest tests/orchestrator/test_workflow_end_to_end.py -q
```

`_ScenarioOwners` remains legal only in that fast orchestration regression.

- [ ] **Step 4: Run PostgreSQL capability suite**

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

- [ ] **Step 5: Run focused architecture/Ruff/whitespace gates**

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

- [ ] **Step 6: Scope audit**

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
generic materialized forward-resume/convergence continuation
```

Expected production changes are limited to File Structure Freeze plus test-only compatibility edits directly caused by approved public contracts.

- [ ] **Step 7: Push exact final HEAD and require repository CI**

Require every PR-triggered workflow for exact final SHA to reach `completed / success`, with zero failure/in-progress/queued.

At minimum inspect:

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

For `execution-saga-postgres`, inspect logs and confirm new Task 8 shared PostgreSQL dispatch contract cases were collected and were not skipped.

- [ ] **Step 8: Record final implementation closure**

```text
Task 8 exact owner API/parity evidence
Task 9 A–D/F/G real-owner E2E evidence
unknown-outcome safe-wait E2E evidence
PostgreSQL fresh-runtime no-double-Host evidence
explicit external UnknownOutcomeRecovery advancement observed by fresh owner read
no claim of autonomous recovery scheduler or guaranteed final convergence
fast _ScenarioOwners regression preserved
scope audit clean
all exact-head PR workflows success
```

Only then mark implementation phase CLOSED. Merge, merged-main observation, and docs-only lifecycle closeout remain separate gates under baseline plan.

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

Stop implementation and return to Design/Plan if any RED or repository fact proves:

```text
Provider Binding cannot provide exact full-hash lookup without changing identity contract beyond approved spec.
Dispatch-intent durable uniqueness is not saga_id + execution_slice_hash.
In-memory/PostgreSQL stores cannot share approved public contract without broader persistence redesign.
Execution Coordination cannot derive approved terminal/recovery combinations from existing durable Saga/Slice/dispatch truth.
Canonical begin_execution cannot reconstruct coordinator inputs through public owner APIs without a new reverse index/private cache.
Task 7 exactly-one-slice assumption is no longer true on implementation HEAD.
LangGraph cannot atomically persist saga_id with execution wait using existing state/checkpointer model.
Formal PostgreSQL CI cannot execute new contract cases non-skipped without CI architecture change.
A requirement would need autonomous recovery scheduling or generic materialized forward-resume/convergence continuation.
```

Do not manufacture GREEN by adding adapter-private maps, selecting latest/current rows, deriving owner ids from hash prefixes inside adapter, weakening full-hash equality, treating timeout as proof of non-commit, or relabeling safe wait as complete recovery.

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