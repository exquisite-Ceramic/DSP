# DSP Cross-owner Delivery & Crash Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement ADR-009’s owner-local transactional outbox/inbox and durable Host-effect recovery rules on top of the ADR-008 PostgreSQL substrate, without introducing a broker, distributed transaction, or second business orchestrator.

**Architecture:** Use the existing `execution_saga` owner as the first complete reference path. Saga state and its outbound event are committed in one owner-local PostgreSQL transaction; delivery is at-least-once; inbound durable side effects use an inbox receipt in the consumer owner transaction. Host mutation remains outside PostgreSQL, so a durable dispatch intent is committed before the Host call, the same stable idempotency key is reused across retries/recovery, and ambiguous transport outcomes become an explicit `OUTCOME_UNKNOWN` recovery state that can only be resolved from Host/read-back/reconciliation evidence. The existing Execution Saga V2 remains the execution truth; delivery and effect-journal records support it but do not replace it.

**Tech Stack:** Python 3.11 canonical / Python 3.14 compatibility, `uv`, pytest, psycopg 3, PostgreSQL 17 reference CI service, existing AutoCAD/Revit sidecars and Phase I live harness.

**Spec:** `docs/adr/ADR-009-cross-owner-delivery-crash-recovery.md`

**Depends on:** `docs/superpowers/plans/2026-09-16-durable-persistence-substrate.md` completed first. Runtime implementation starts from merged architecture review plus the completed durable-persistence implementation branch.

## Global Constraints

- Local ACID transaction scope is one authoritative owner only; never include Gateway, D5, ChangeSet, Workflow Orchestrator, or Host writes in the `execution_saga` transaction.
- Delivery semantics are at-least-once. Do not claim transport-level exactly-once.
- The outbox record is committed atomically with the producer’s durable business transition.
- A durable-state-changing consumer must deduplicate by `event_id` in the same local transaction as its own state change.
- No Kafka, NATS, RabbitMQ, Redis Streams, or CDC platform is introduced by this plan.
- A Host side effect is never assumed failed solely because the response is missing.
- The same logical Host command must retain the same stable `idempotency_key` during recovery.
- Existing `ExecutionSagaStoreV2` `saga_revision` / `expected_revision` CAS semantics remain unchanged.
- `PARTIALLY_COMMITTED`, `DIVERGED`, scope breach, verification failure, and compensation semantics remain owned by the existing Saga/domain layer.
- Outbox delivery success is not workflow success, and workflow/checkpoint progress is not Host commit evidence.
- Every new production module must contain Chinese comments/docstrings for non-obvious recovery invariants, consistent with the repository’s current code-commenting style.

---

### Task 1: Add owner-local delivery and Host-effect journal schema

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/migrations/0002_delivery_recovery.sql`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres.py`
- Create: `tests/execution_reconciliation/test_postgres_delivery_schema.py`

**Interfaces:**
- Producer outbox table: `execution_saga.outbox`
- Consumer inbox table for this owner: `execution_saga.inbox_receipt`
- Host effect intent table: `execution_saga.host_dispatch_intent`
- Append-only Host observation table: `execution_saga.host_dispatch_observation`

- [ ] **Step 1: Write the RED schema test**

```python
from __future__ import annotations

import os

import pytest

from design_execution_reconciliation.postgres import (
    apply_execution_saga_migrations,
    connect_postgres,
)


@pytest.mark.skipif(
    not os.environ.get("DSP_TEST_POSTGRES_DSN"),
    reason="DSP_TEST_POSTGRES_DSN is required",
)
def test_delivery_recovery_tables_are_execution_saga_owned() -> None:
    conn = connect_postgres(os.environ["DSP_TEST_POSTGRES_DSN"])
    apply_execution_saga_migrations(conn)
    rows = conn.execute(
        """
        select table_schema, table_name
        from information_schema.tables
        where table_schema = 'execution_saga'
        """
    ).fetchall()
    names = {row["table_name"] for row in rows}
    assert {
        "outbox",
        "inbox_receipt",
        "host_dispatch_intent",
        "host_dispatch_observation",
    } <= names
```

- [ ] **Step 2: Run the test and verify RED**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest tests/execution_reconciliation/test_postgres_delivery_schema.py -q
```

Expected: FAIL because migration `0002_delivery_recovery.sql` does not exist.

- [ ] **Step 3: Add migration `0002_delivery_recovery.sql`**

Use owner-local DDL equivalent to:

```sql
CREATE TABLE IF NOT EXISTS execution_saga.outbox (
    event_id uuid PRIMARY KEY,
    event_type text NOT NULL,
    aggregate_ref text NOT NULL,
    aggregate_revision bigint,
    occurred_at timestamptz NOT NULL,
    payload jsonb NOT NULL,
    attempt_count integer NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    claimed_until timestamptz,
    published_at timestamptz
);

CREATE INDEX IF NOT EXISTS idx_execution_saga_outbox_pending
    ON execution_saga.outbox (published_at, claimed_until, occurred_at);

CREATE TABLE IF NOT EXISTS execution_saga.inbox_receipt (
    event_id uuid PRIMARY KEY,
    producer_owner text NOT NULL,
    event_type text NOT NULL,
    source_ref text NOT NULL,
    source_revision bigint,
    processed_at timestamptz NOT NULL,
    result_ref text
);

CREATE TABLE IF NOT EXISTS execution_saga.host_dispatch_intent (
    dispatch_intent_id uuid PRIMARY KEY,
    saga_id text NOT NULL REFERENCES execution_saga.saga_v2(saga_id),
    execution_slice_hash char(64) NOT NULL,
    grant_hash char(64) NOT NULL,
    binding_set_hash char(64) NOT NULL,
    host_instance_id text NOT NULL,
    document_ref text NOT NULL,
    idempotency_key uuid NOT NULL,
    expected_host_revision text,
    status text NOT NULL,
    intent_revision bigint NOT NULL DEFAULT 0 CHECK (intent_revision >= 0),
    prepared_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    UNIQUE (saga_id, execution_slice_hash),
    UNIQUE (document_ref, idempotency_key)
);

CREATE TABLE IF NOT EXISTS execution_saga.host_dispatch_observation (
    observation_id uuid PRIMARY KEY,
    dispatch_intent_id uuid NOT NULL
        REFERENCES execution_saga.host_dispatch_intent(dispatch_intent_id),
    observation_kind text NOT NULL,
    observed_at timestamptz NOT NULL,
    evidence_ref text,
    evidence_hash char(64),
    detail jsonb NOT NULL DEFAULT '{}'::jsonb
);
```

Do not add foreign keys to other owner schemas.

- [ ] **Step 4: Make the existing migration runner apply both migrations monotonically**

`apply_execution_saga_migrations(conn)` must enumerate package SQL files by numeric prefix and record each filename/version in `execution_saga.schema_migrations`. Do not hard-code only `0001`.

- [ ] **Step 5: Run GREEN and commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest \
  tests/execution_reconciliation/test_postgres_schema_v2.py \
  tests/execution_reconciliation/test_postgres_delivery_schema.py -q

git add platform/execution_reconciliation/src/design_execution_reconciliation/migrations \
  platform/execution_reconciliation/src/design_execution_reconciliation/postgres.py \
  tests/execution_reconciliation/test_postgres_delivery_schema.py
git commit -m "feat: add execution saga delivery recovery schema"
```

---

### Task 2: Define the private delivery envelope and deterministic Saga event identity

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/delivery.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_delivery_contracts.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class OwnerEvent:
    event_id: UUID
    event_type: str
    producer_owner: str
    aggregate_ref: str
    aggregate_revision: int | None
    occurred_at: str
    payload: Mapping[str, object]


def build_saga_transition_event(
    before: StoredExecutionSagaV2 | None,
    after: StoredExecutionSagaV2,
    *,
    occurred_at: str,
) -> OwnerEvent: ...
```

- [ ] **Step 1: Write the RED contract tests**

```python
from uuid import UUID

from design_execution_reconciliation.delivery import build_saga_transition_event


def test_saga_transition_event_is_deterministic(v2_ready_saga) -> None:
    first = build_saga_transition_event(
        None,
        v2_ready_saga,
        occurred_at="2026-09-16T16:00:00Z",
    )
    second = build_saga_transition_event(
        None,
        v2_ready_saga,
        occurred_at="2026-09-16T16:00:00Z",
    )
    assert first == second
    assert isinstance(first.event_id, UUID)
    assert first.producer_owner == "execution_saga"
    assert first.aggregate_ref == v2_ready_saga.definition.saga_id
    assert first.aggregate_revision == v2_ready_saga.saga_revision
    assert set(first.payload) == {
        "saga_id",
        "saga_revision",
        "saga_status",
        "saga_definition_hash",
    }
```

- [ ] **Step 2: Verify RED**

```bash
uv run python -m pytest tests/execution_reconciliation/test_delivery_contracts.py -q
```

- [ ] **Step 3: Implement deterministic identity**

Use a fixed namespace and UUIDv5 over owner + event type + aggregate + revision:

```python
_EVENT_NAMESPACE = UUID("61d30c68-1980-5d8a-aeda-b9160e0c8f37")


def _event_id(event_type: str, aggregate_ref: str, revision: int) -> UUID:
    return uuid5(
        _EVENT_NAMESPACE,
        f"execution_saga:{event_type}:{aggregate_ref}:{revision}",
    )
```

`build_saga_transition_event` must copy only stable refs/hash/status metadata; it must not serialize the whole Saga snapshot into the event payload.

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run python -m pytest tests/execution_reconciliation/test_delivery_contracts.py -q
git add platform/execution_reconciliation/src/design_execution_reconciliation/delivery.py \
  platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py \
  tests/execution_reconciliation/test_delivery_contracts.py
git commit -m "feat: define execution saga owner events"
```

---

### Task 3: Commit Saga transition + outbox event atomically

**Files:**
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_saga_store_v2.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_outbox.py`
- Create: `tests/execution_reconciliation/test_postgres_saga_outbox_atomicity.py`

**Interfaces:**

```python
def insert_outbox_event(conn, event: OwnerEvent) -> None: ...

def load_pending_outbox(conn, *, limit: int) -> tuple[OwnerEvent, ...]: ...
```

- [ ] **Step 1: Write the RED atomicity test**

Arrange a valid Saga transition, force `insert_outbox_event()` to raise after the Saga `UPDATE` but before transaction commit, and assert after rollback that both remain unchanged:

```python
assert reloaded.saga_revision == before.saga_revision
assert pending_event_ids(conn) == set()
```

Then execute the same transition without the injected failure and assert exactly one event exists for revision `N+1`.

- [ ] **Step 2: Verify RED**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest \
  tests/execution_reconciliation/test_postgres_saga_outbox_atomicity.py -q
```

- [ ] **Step 3: Insert the outbox record inside the existing CAS transaction**

The successful PostgreSQL transition path must be structurally equivalent to:

```python
with self._pool.connection() as conn:
    with conn.transaction():
        current = self._load_for_transition(conn, saga_id)
        next_state = transition(current)
        changed = self._cas_update(conn, current, next_state, expected_revision)
        if not changed:
            raise ReconciliationError("SAGA_CONFLICT", "Saga V2 revision changed")
        event = build_saga_transition_event(
            current,
            next_state,
            occurred_at=self._clock.now(),
        )
        insert_outbox_event(conn, event)
return next_state
```

Do not publish to the network inside this transaction.

- [ ] **Step 4: Make replay-safe no-op calls produce no duplicate transition event**

If a store method returns the already-recorded state because the same evidence was replayed, it must not emit a second logical transition. The deterministic `event_id` uniqueness constraint is a final guard, not a substitute for correct no-op detection.

- [ ] **Step 5: Run GREEN and commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest \
  tests/execution_reconciliation/test_postgres_saga_outbox_atomicity.py \
  tests/execution_reconciliation/test_postgres_saga_store_v2.py -q

git add platform/execution_reconciliation/src/design_execution_reconciliation/postgres_saga_store_v2.py \
  platform/execution_reconciliation/src/design_execution_reconciliation/postgres_outbox.py \
  tests/execution_reconciliation/test_postgres_saga_outbox_atomicity.py
git commit -m "feat: atomically publish saga transitions to outbox"
```

---

### Task 4: Implement at-least-once outbox claim/dispatch without a broker

**Files:**
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_outbox.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/outbox_dispatcher.py`
- Create: `tests/execution_reconciliation/test_outbox_dispatcher.py`

**Interfaces:**

```python
class OutboxSink(Protocol):
    def send(self, event: OwnerEvent) -> None: ...


class PostgresOutboxDispatcher:
    def dispatch_batch(self, *, limit: int = 100) -> int: ...
```

- [ ] **Step 1: Write RED crash-window tests**

Cover these exact cases:

```text
A. pending event -> send succeeds -> published_at set
B. send raises -> published_at remains null -> next batch retries same event_id
C. send succeeds but process crashes before mark-published -> lease expires -> same event_id is sent again
D. two dispatchers claim concurrently -> each row is owned by at most one active lease
```

The sink records received `event_id` values so case C explicitly proves duplicate delivery is expected.

- [ ] **Step 2: Implement claim with PostgreSQL adapter details only**

Use a short transaction with `FOR UPDATE SKIP LOCKED`, increment `attempt_count`, and set `claimed_until = now() + interval '30 seconds'`. Return decoded `OwnerEvent` values after the claim transaction commits.

- [ ] **Step 3: Implement dispatch and acknowledgement**

For each claimed event:

```python
try:
    self._sink.send(event)
except Exception:
    self._store.release_claim(event.event_id)
    continue
self._store.mark_published(event.event_id)
```

`mark_published()` must be idempotent. A duplicate send caused by a crash after `send()` but before `mark_published()` is valid ADR-009 behavior.

- [ ] **Step 4: Run GREEN and commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest tests/execution_reconciliation/test_outbox_dispatcher.py -q

git add platform/execution_reconciliation/src/design_execution_reconciliation \
  tests/execution_reconciliation/test_outbox_dispatcher.py
git commit -m "feat: add at least once postgres outbox dispatcher"
```

---

### Task 5: Implement transactional inbox receipt for durable consumers

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_inbox.py`
- Create: `tests/execution_reconciliation/test_postgres_inbox.py`

**Interfaces:**

```python
class PostgresInbox:
    def consume(
        self,
        event: OwnerEvent,
        *,
        apply: Callable[[Connection, OwnerEvent], str | None],
        processed_at: str,
    ) -> str | None: ...
```

- [ ] **Step 1: Write RED duplicate and rollback tests**

In test setup create an owner-local test projection table under `execution_saga`; the production migration must not include it. Then assert:

```python
calls = 0

def apply(conn, event):
    nonlocal calls
    calls += 1
    conn.execute("insert into execution_saga.test_projection ...")
    return "projection:1"

first = inbox.consume(event, apply=apply, processed_at=NOW)
second = inbox.consume(event, apply=apply, processed_at=NOW)
assert first == second == "projection:1"
assert calls == 1
```

Also make `apply()` raise and verify both the projection write and inbox receipt roll back.

- [ ] **Step 2: Implement single-transaction dedupe**

Algorithm:

```python
with conn.transaction():
    inserted = insert inbox receipt with ON CONFLICT DO NOTHING
    if not inserted:
        return existing result_ref
    result_ref = apply(conn, event)
    update receipt with result_ref
    return result_ref
```

The callback receives the same connection so its owner-local state mutation and receipt are one transaction.

- [ ] **Step 3: Run GREEN and commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest tests/execution_reconciliation/test_postgres_inbox.py -q

git add platform/execution_reconciliation/src/design_execution_reconciliation/postgres_inbox.py \
  tests/execution_reconciliation/test_postgres_inbox.py
git commit -m "feat: add transactional execution saga inbox receipt"
```

---

### Task 6: Add durable Host dispatch intent and stable idempotency identity

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/dispatch_intent.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_dispatch_intent.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_dispatch_intent.py`
- Create: `tests/execution_reconciliation/test_postgres_dispatch_intent.py`

**Interfaces:**

```python
class HostDispatchStatus(str, Enum):
    PREPARED = "PREPARED"
    DISPATCHED = "DISPATCHED"
    OUTCOME_UNKNOWN = "OUTCOME_UNKNOWN"
    HOST_COMMITTED = "HOST_COMMITTED"
    SAFE_TO_RETRY = "SAFE_TO_RETRY"
    RECONCILED = "RECONCILED"


@dataclass(frozen=True, slots=True)
class HostDispatchIntent:
    dispatch_intent_id: UUID
    saga_id: str
    execution_slice_hash: str
    grant_hash: str
    binding_set_hash: str
    host_instance_id: str
    document_ref: str
    idempotency_key: UUID
    expected_host_revision: str | None
    status: HostDispatchStatus
    intent_revision: int
    prepared_at: str


def build_host_dispatch_intent(..., prepared_at: str) -> HostDispatchIntent: ...
```

- [ ] **Step 1: Write RED deterministic-key tests**

Two calls for the same immutable Saga/Slice/grant/binding/document lineage must produce the same `dispatch_intent_id` and `idempotency_key`. Changing the grant or Slice must change both.

- [ ] **Step 2: Implement UUIDv5 identities from immutable execution lineage**

Use fixed namespaces and inputs equivalent to:

```python
intent_name = (
    f"{saga_id}:{execution_slice_hash}:{grant_hash}:"
    f"{binding_set_hash}:{host_instance_id}:{document_ref}"
)
dispatch_intent_id = uuid5(_DISPATCH_NAMESPACE, intent_name)
idempotency_key = uuid5(_IDEMPOTENCY_NAMESPACE, intent_name)
```

Do not include wall-clock time in either identity.

- [ ] **Step 3: Implement PostgreSQL create/get/CAS transition methods**

Expose:

```python
class PostgresHostDispatchIntentStore:
    def prepare(self, intent: HostDispatchIntent) -> HostDispatchIntent: ...
    def get(self, dispatch_intent_id: UUID) -> HostDispatchIntent | None: ...
    def mark_dispatched(self, ..., expected_revision: int, observed_at: str) -> HostDispatchIntent: ...
    def mark_outcome_unknown(self, ..., expected_revision: int, failure_ref: str, observed_at: str) -> HostDispatchIntent: ...
    def mark_host_committed(self, ..., expected_revision: int, evidence_hash: str, observed_at: str) -> HostDispatchIntent: ...
    def mark_safe_to_retry(self, ..., expected_revision: int, evidence_ref: str, observed_at: str) -> HostDispatchIntent: ...
    def mark_reconciled(self, ..., expected_revision: int, evidence_hash: str, observed_at: str) -> HostDispatchIntent: ...
```

Every state change uses `WHERE intent_revision = expected_revision`, increments revision once, and appends a `host_dispatch_observation` row in the same owner-local transaction.

- [ ] **Step 4: Prove restart durability and stale-writer conflict**

Close one store instance, reopen another, load the intent, then race two independent transitions from the same revision; exactly one succeeds.

- [ ] **Step 5: Run GREEN and commit**

```bash
uv run python -m pytest tests/execution_reconciliation/test_dispatch_intent.py -q
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest tests/execution_reconciliation/test_postgres_dispatch_intent.py -q

git add platform/execution_reconciliation/src/design_execution_reconciliation \
  tests/execution_reconciliation/test_dispatch_intent.py \
  tests/execution_reconciliation/test_postgres_dispatch_intent.py
git commit -m "feat: persist host dispatch intent and recovery evidence"
```

---

### Task 7: Persist intent before Host I/O and thread the stable idempotency key through execution ports

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/contracts.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/ports.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/materialized_coordinator.py`
- Modify: `tests/execution_coordination/_materialized_support.py`
- Modify: `tests/execution_coordination/conftest.py`
- Create: `tests/execution_coordination/test_phase_i_durable_dispatch_intent.py`
- Modify: `tests/integration/phase_i_live_host.py`

**Interfaces:**

Add a provider-neutral execution context:

```python
@dataclass(frozen=True, slots=True)
class HostDispatchContext:
    dispatch_intent_id: str
    idempotency_key: str
    saga_id: str
    execution_slice_hash: str
```

Change the materialized Host port to:

```python
class MaterializedHostExecutionPort(Protocol):
    def execute(
        self,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
        dispatch_context: HostDispatchContext,
    ) -> HostExecutionResult: ...
```

Inject a dispatch-intent store into `MaterializedExecutionSagaCoordinator`.

- [ ] **Step 1: Write RED ordering test**

Use a fake store and Host port to record calls. The expected sequence for one Slice is exactly:

```text
reserve_slice_admission
confirm_slice_admitted
prepare_dispatch_intent
mark_dispatched
host.execute(... same idempotency_key ...)
record_host_commit or record unknown outcome
```

Assert `host.execute` is never reached if `prepare()` fails.

- [ ] **Step 2: Update coordinator constructor and Host port contract**

Require `dispatch_intents` to provide `prepare/get/mark_*` methods. Keep readiness checks before Saga creation exactly as today.

- [ ] **Step 3: Build and persist the intent before Host I/O**

Inside the Slice loop, after admission and before `host_port.execute`, do:

```python
intent = build_host_dispatch_intent(
    saga_id=definition.saga_id,
    execution_slice_hash=execution_slice.execution_slice_hash,
    grant_hash=authority.grant_hash,
    binding_set_hash=binding_set.binding_set_hash,
    host_instance_id=authority.host_instance_id,
    document_ref=execution_slice.host_runtime_ref.document_ref,
    expected_host_revision=None,
    prepared_at=self._clock.now(),
)
intent = self._dispatch_intents.prepare(intent)
intent = self._dispatch_intents.mark_dispatched(
    intent.dispatch_intent_id,
    expected_revision=intent.intent_revision,
    observed_at=self._clock.now(),
)
```

Then pass `HostDispatchContext` to the Host port.

- [ ] **Step 4: Handle Host outcomes without inventing commit truth**

For `HostCommitted`, persist `HOST_COMMITTED` observation using `actual_delta_hash` before advancing Saga `record_host_commit`.

For `HostFailed(BEFORE_COMMIT)`, record `SAFE_TO_RETRY` evidence, then use the existing Saga `fail_slice_before_commit` path.

For `HostFailed(COMMIT_STATE_UNKNOWN)`, record `OUTCOME_UNKNOWN` and return `RECOVERY_REQUIRED`; do not call the Host again in that execution pass.

- [ ] **Step 5: Replace random write idempotency in the Phase I live harness**

Where `tests/integration/phase_i_live_host.py` builds the AutoCAD/Revit write command, use `dispatch_context.idempotency_key` as the Host contract’s `idempotencyKey`. Remove per-call `uuid.uuid4()` for that write identity; unrelated UUID use may remain.

- [ ] **Step 6: Run platform tests and commit**

```bash
uv run python -m pytest \
  tests/execution_coordination/test_phase_i_durable_dispatch_intent.py \
  tests/execution_coordination/test_phase_i_materialized_success.py \
  tests/execution_coordination/test_phase_i_materialized_unknown_commit.py -q

git add platform/execution_coordination \
  tests/execution_coordination \
  tests/integration/phase_i_live_host.py
git commit -m "feat: persist host intent before materialized execution"
```

---

### Task 8: Implement evidence-driven unknown-outcome recovery

**Files:**
- Create: `platform/execution_coordination/src/design_execution_coordination/recovery.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/ports.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Create: `tests/execution_coordination/test_unknown_outcome_recovery.py`

**Interfaces:**

```python
class HostOutcomeProbe(Protocol):
    def resolve(
        self,
        execution_slice: ExecutionSliceV2,
        dispatch_context: HostDispatchContext,
    ) -> HostCommitted | HostFailed: ...


class UnknownOutcomeRecovery:
    def recover(
        self,
        *,
        stored_saga: StoredExecutionSagaV2,
        execution_slice: ExecutionSliceV2,
        authority: AdmittedExecutionAuthorityV2,
        binding_set: ProviderBindingSetV2,
        dispatch_intent: HostDispatchIntent,
    ) -> MaterializedCoordinationResult: ...
```

- [ ] **Step 1: Write RED recovery cases**

Cover:

```text
1. OUTCOME_UNKNOWN + Host proof of same command committed -> persist HOST_COMMITTED -> existing scope/verify/reconcile path
2. OUTCOME_UNKNOWN + positive proof command not committed and revision precondition still valid -> mark SAFE_TO_RETRY
3. OUTCOME_UNKNOWN + insufficient evidence -> remain RECOVERY_REQUIRED; no Host mutation
4. already HOST_COMMITTED intent replay -> never dispatch again; continue reconcile from durable evidence
```

- [ ] **Step 2: Implement evidence-first decision rules**

Recovery must query using the same `dispatch_intent_id` / `idempotency_key`. It may use a Host durable command-result lookup when available, otherwise read-back/revision/semantic evidence. It must never convert a timeout alone into `SAFE_TO_RETRY`.

- [ ] **Step 3: Reuse existing reconciliation rather than adding a second verifier**

When commitment is proven, feed the recovered `ActualDelta` through the existing `record_host_commit -> begin_reconciliation -> compare_scope -> verify_semantics` sequence. Do not implement separate recovery-only scope or verification rules.

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run python -m pytest tests/execution_coordination/test_unknown_outcome_recovery.py -q
git add platform/execution_coordination/src/design_execution_coordination \
  tests/execution_coordination/test_unknown_outcome_recovery.py
git commit -m "feat: add evidence driven unknown outcome recovery"
```

---

### Task 9: Prove ADR-009 crash windows and repository regression

**Files:**
- Create: `tests/execution_reconciliation/test_delivery_crash_windows.py`
- Create: `tests/execution_coordination/test_host_effect_crash_windows.py`
- Modify: `.github/workflows/durable-persistence.yml`
- Modify: `docs/runbooks/phase-i-real-cross-host-materialization-saga.md`

**Interfaces:** no new public interfaces; this task closes evidence.

- [ ] **Step 1: Encode crash windows A-D for delivery**

The test module must prove:

```text
A. rollback before local commit -> no state transition and no outbox event
B. state + outbox committed before dispatcher crash -> pending event survives restart
C. delivery before consumer commit -> redelivery is accepted
D. consumer commit before sender ack -> duplicate event does not repeat consumer side effect
```

- [ ] **Step 2: Encode crash windows E-G for Host effects**

The test module must prove:

```text
E. intent committed before Host call -> restart resumes same dispatch identity
F. Host may have committed before platform observation -> OUTCOME_UNKNOWN, never blind retry
G. prior Slice committed and later Slice fails -> existing PARTIALLY_COMMITTED/Saga behavior remains intact
```

- [ ] **Step 3: Extend the durable-persistence CI lane**

Run PostgreSQL-backed delivery tests plus the platform-only recovery tests:

```bash
DSP_TEST_POSTGRES_DSN='postgresql://postgres:postgres@localhost:5432/dsp_test' \
  uv run python -m pytest \
  tests/execution_reconciliation/test_postgres_delivery_schema.py \
  tests/execution_reconciliation/test_postgres_saga_outbox_atomicity.py \
  tests/execution_reconciliation/test_outbox_dispatcher.py \
  tests/execution_reconciliation/test_postgres_inbox.py \
  tests/execution_reconciliation/test_postgres_dispatch_intent.py \
  tests/execution_reconciliation/test_delivery_crash_windows.py \
  tests/execution_coordination/test_host_effect_crash_windows.py -q
```

- [ ] **Step 4: Update the runbook with explicit operator semantics**

Document these exact rules:

```text
RECOVERY_REQUIRED / OUTCOME_UNKNOWN is not equivalent to FAILED.
Do not issue a new logical command identity during recovery.
Reuse the original idempotency key when a replay is proven safe.
Do not manually mark a Saga successful from transport logs alone.
Recover from Saga + dispatch intent + Host/read-back/reconciliation evidence.
```

- [ ] **Step 5: Run full canonical regression**

```bash
uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
uv run ruff check --select E,F,I platform hosts/autocad/sidecar tests
```

Then run Revit Core:

```bash
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj -f net8.0
```

Expected: no new regression relative to the repository baseline.

- [ ] **Step 6: Commit plan closeout implementation**

```bash
git add tests/execution_reconciliation \
  tests/execution_coordination \
  .github/workflows/durable-persistence.yml \
  docs/runbooks/phase-i-real-cross-host-materialization-saga.md
git commit -m "test: prove cross owner crash recovery invariants"
```

---

## Self-Review Checklist

Before declaring this implementation complete, verify all of the following against ADR-009:

- [ ] Domain transition and outbox publication are one owner-local transaction.
- [ ] Dispatcher is explicitly at-least-once and duplicate delivery is covered by tests.
- [ ] Consumer durable mutation and inbox receipt are one owner-local transaction.
- [ ] No broker is a correctness dependency.
- [ ] No global event total order is introduced.
- [ ] Event payloads carry stable refs/hashes rather than duplicated mutable domain objects.
- [ ] Host dispatch intent is durable before Host mutation.
- [ ] Host idempotency key is stable across restart/recovery.
- [ ] `COMMIT_STATE_UNKNOWN` becomes durable `OUTCOME_UNKNOWN` semantics rather than `FAILED`.
- [ ] Unknown outcomes are resolved only from explicit Host/read-back/reconciliation evidence.
- [ ] Existing Saga V2 CAS and `PARTIALLY_COMMITTED` / `DIVERGED` semantics remain authoritative.
- [ ] Audit and outbox responsibilities remain separate.
- [ ] No PostgreSQL-specific type/API leaks into Host or canonical public contracts.
