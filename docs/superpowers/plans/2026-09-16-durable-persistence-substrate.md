# DSP Durable Persistence Substrate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish the ADR-008 PostgreSQL reference durability pattern without creating a shared-database monolith, and prove that pattern first on the existing `ExecutionSagaStoreV2` boundary while preserving its exact CAS/replay semantics.

**Architecture:** Keep the domain/store protocol provider-neutral. PostgreSQL exists only behind the execution-reconciliation infrastructure adapter. The first durable owner is `execution_saga`: its schema, migrations, codec, credentials and transaction boundary remain owner-scoped. The existing immutable Saga V2 state machine remains the business truth; persistence must not invent a second state machine. Transition rules are factored into pure/domain helpers so the in-memory and PostgreSQL stores share one semantic implementation. PostgreSQL stores a versioned JSONB snapshot plus an explicit `saga_revision` CAS column; JSONB shape is private infrastructure, not a DSP contract.

**Tech Stack:** Python 3.11 canonical / Python 3.14 compatibility, `uv`, pytest, psycopg 3, PostgreSQL 17 reference CI service, GitHub Actions.

**Architecture authority:** `docs/adr/ADR-008-durable-state-persistence-ownership.md`, `docs/adr/ADR-009-cross-owner-delivery-crash-recovery.md`, `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md` §25.13, §34.5, §43.

**Depends on:** Merge PR #51 before runtime implementation begins. Execute this plan on a fresh implementation branch from that merged `main`; do not implement runtime code on the architecture-review branch.

## Global Constraints

- `ExecutionSagaStoreV2` remains the public domain persistence port; existing callers must not import psycopg or SQL.
- `saga_revision` + `expected_revision` conflict behavior is observable domain behavior and MUST remain unchanged.
- PostgreSQL transaction scope is execution-saga-owner local only. No D5/Gateway/ChangeSet cross-schema read or write is permitted.
- Do not introduce SQLAlchemy/Alembic merely for this slice. Use psycopg 3 and packaged, monotonic owner-local SQL migrations; revisit migration tooling only with evidence from a second/third owner.
- Do not use pickle for durable state. Persist a versioned, explicit JSON-compatible representation and reconstruct validated domain dataclasses on read.
- The in-memory store remains available for fast unit tests; reference production configuration uses PostgreSQL explicitly.
- This plan establishes the reference substrate and migrates the critical Execution Saga V2 owner first. It does **not** migrate every D5/Gateway/ChangeSet/Interaction owner in the same change set.
- Every task ends with a reviewable commit and runs the relevant targeted test before broad regression.

---

### Task 1: Add the PostgreSQL dependency and a dedicated persistence verification lane

**Files:**
- Modify: `platform/execution_reconciliation/pyproject.toml`
- Modify: `uv.lock`
- Create: `.github/workflows/durable-persistence.yml`
- Create: `tests/architecture/test_durable_persistence_boundary.py`

**Interfaces:**
- Package-local runtime dependency: `psycopg[binary,pool]>=3.2,<4`.
- Test DSN: `DSP_TEST_POSTGRES_DSN`.
- Production DSN is not read by domain modules; configuration is passed to the infrastructure factory added later.

- [ ] **Step 1: Write the RED architecture test**

```python
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "platform" / "execution_reconciliation"


def test_execution_reconciliation_owns_postgres_dependency() -> None:
    data = tomllib.loads((PACKAGE / "pyproject.toml").read_text(encoding="utf-8"))
    deps = tuple(data["project"]["dependencies"])
    assert any(item.startswith("psycopg") for item in deps)


def test_domain_state_modules_do_not_import_psycopg() -> None:
    for name in ("saga_state_v2.py", "saga_contracts_v2.py", "saga_v2.py"):
        text = (PACKAGE / "src" / "design_execution_reconciliation" / name).read_text(
            encoding="utf-8"
        )
        assert "psycopg" not in text
```

- [ ] **Step 2: Verify RED**

Run: `uv run python -m pytest tests/architecture/test_durable_persistence_boundary.py -q`

Expected: FAIL because `design-execution-reconciliation` currently declares no database dependency.

- [ ] **Step 3: Add the package-local dependency and refresh the committed lock**

Run:

```bash
uv add --package design-execution-reconciliation 'psycopg[binary,pool]>=3.2,<4'
uv lock
```

Do not add psycopg to the root application dependencies or unrelated owner packages.

- [ ] **Step 4: Add the PostgreSQL CI lane**

Create `.github/workflows/durable-persistence.yml` with a `postgres:17` service, health check, Python 3.11, `uv sync --locked --all-packages`, and:

```bash
DSP_TEST_POSTGRES_DSN='postgresql://postgres:postgres@localhost:5432/dsp_test' \
  uv run python -m pytest \
  tests/execution_reconciliation/test_postgres_schema_v2.py \
  tests/execution_reconciliation/test_postgres_saga_store_v2.py -q
```

The files may not exist until later tasks; keep this workflow in the same implementation branch and expect it to become green before plan closeout.

- [ ] **Step 5: Run architecture test GREEN and commit**

```bash
uv run python -m pytest tests/architecture/test_durable_persistence_boundary.py -q
git add platform/execution_reconciliation/pyproject.toml uv.lock \
  .github/workflows/durable-persistence.yml \
  tests/architecture/test_durable_persistence_boundary.py
git commit -m "build: add execution saga postgres reference dependency"
```

---

### Task 2: Create the owner-scoped migration package and schema bootstrap

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/migrations/__init__.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/migrations/0001_execution_saga_v2.sql`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres.py`
- Modify: `platform/execution_reconciliation/pyproject.toml`
- Create: `tests/execution_reconciliation/test_postgres_schema_v2.py`

**Schema:** `execution_saga` only.

- [ ] **Step 1: Write the RED integration test**

The test must require `DSP_TEST_POSTGRES_DSN`, skip only when that variable is absent, run the package migration function, then query `information_schema`/`pg_catalog` and assert that these owner-local objects exist:

```text
execution_saga.schema_migrations
execution_saga.saga_v2
```

Also assert no migration creates `semantic_runtime`, `gateway`, or `changeset` objects.

- [ ] **Step 2: Verify RED against local PostgreSQL**

Run:

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
uv run python -m pytest tests/execution_reconciliation/test_postgres_schema_v2.py -q
```

Expected: FAIL because the migration package does not exist.

- [ ] **Step 3: Implement `0001_execution_saga_v2.sql`**

Use owner-local DDL equivalent to:

```sql
CREATE SCHEMA IF NOT EXISTS execution_saga;

CREATE TABLE IF NOT EXISTS execution_saga.schema_migrations (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS execution_saga.saga_v2 (
    saga_id text PRIMARY KEY,
    saga_revision bigint NOT NULL CHECK (saga_revision >= 0),
    definition_hash char(64) NOT NULL,
    status text NOT NULL,
    snapshot jsonb NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

Migration application must be idempotent and version recorded. Put SQL inside the Python package and add setuptools package-data for `migrations/*.sql`; do not depend on the repository working directory at runtime.

- [ ] **Step 4: Implement the narrow PostgreSQL helper**

`postgres.py` should expose only infrastructure primitives such as:

```python
def connect_postgres(dsn: str): ...
def apply_execution_saga_migrations(conn) -> None: ...
```

No domain state class imports psycopg.

- [ ] **Step 5: Run GREEN and commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest tests/execution_reconciliation/test_postgres_schema_v2.py -q
git add platform/execution_reconciliation tests/execution_reconciliation/test_postgres_schema_v2.py
git commit -m "feat: add execution saga postgres schema migration"
```

---

### Task 3: Add an explicit versioned Saga V2 persistence codec

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/saga_persistence_v2.py`
- Create: `tests/execution_reconciliation/test_saga_persistence_v2.py`

**Contract:** persisted representation is private infrastructure with `schema_version = 1`; domain reconstruction must pass the existing dataclass validators.

- [ ] **Step 1: Write RED round-trip tests**

Use the existing `_v2_definition()` fixture path from `tests/execution_reconciliation/test_saga_v2_store.py` to create a Saga, drive at least reservation + admission, encode it, JSON round-trip it, decode it, and assert exact equality.

Also assert:

```python
payload["schema_version"] == 1
assert "__dict__" not in payload
assert "pickle" not in repr(payload).lower()
```

- [ ] **Step 2: Verify RED**

Run: `uv run python -m pytest tests/execution_reconciliation/test_saga_persistence_v2.py -q`

- [ ] **Step 3: Implement field-by-field codec**

Expose:

```python
def encode_stored_saga_v2(value: StoredExecutionSagaV2) -> dict[str, object]: ...
def decode_stored_saga_v2(payload: Mapping[str, object]) -> StoredExecutionSagaV2: ...
```

Encode enums as their string value and nested tuples as JSON arrays. Reconstruct `SemanticEnvironmentRef`, `SliceDependency`, `SliceValidationAssignment`, `ExecutionSagaDefinitionV2`, `SliceReconciliationStateV2`, then `StoredExecutionSagaV2`; do not bypass constructors with `object.__new__`.

- [ ] **Step 4: Run GREEN and commit**

```bash
uv run python -m pytest tests/execution_reconciliation/test_saga_persistence_v2.py -q
git add platform/execution_reconciliation/src/design_execution_reconciliation/saga_persistence_v2.py \
  tests/execution_reconciliation/test_saga_persistence_v2.py
git commit -m "feat: add execution saga durable codec"
```

---

### Task 4: Extract one shared Saga V2 transition engine before adding a second store

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/saga_transitions_v2.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/saga_store_v2.py`
- Modify: `tests/execution_reconciliation/test_saga_v2_store.py`
- Modify: related `tests/execution_reconciliation/test_saga_v2_*.py` only as required by the refactor

**Reason:** PostgreSQL must not copy the large transition/validation body from `InMemoryExecutionSagaStoreV2`; two copies would drift and create two business state machines.

- [ ] **Step 1: Add a failing semantic-parity test around a pure transition**

Start with reservation: given a `StoredExecutionSagaV2`, call the new pure function and assert it produces the same revision/status/evidence as the existing in-memory store, including replay-safe evidence and `SAGA_CONFLICT` on different evidence.

- [ ] **Step 2: Extract transition functions incrementally**

Move the semantic rules for:

```text
create initial state
reserve_slice_admission
confirm_slice_admitted
record_host_commit
begin_reconciliation
record_scope_result
record_verification_result
fail_slice_before_commit
record_convergence_outcome
```

into pure helpers that accept the current immutable state and return the next immutable state. Keep integrity helpers in domain code; do not import psycopg.

- [ ] **Step 3: Make the in-memory store a lock + load/save adapter**

It should retain thread safety and current replay behavior but delegate every transition to the shared helpers.

- [ ] **Step 4: Run the existing Saga V2 suite unchanged**

```bash
uv run python -m pytest tests/execution_reconciliation/test_saga_v2_store.py -q
uv run python -m pytest tests/execution_reconciliation -q
```

Expected: all existing Phase I Saga V2 behavior remains GREEN.

- [ ] **Step 5: Commit**

```bash
git add platform/execution_reconciliation/src/design_execution_reconciliation \
  tests/execution_reconciliation
git commit -m "refactor: share execution saga v2 transition engine"
```

---

### Task 5: Implement `PostgresExecutionSagaStoreV2` with strict SQL CAS

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_saga_store_v2.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_postgres_saga_store_v2.py`

- [ ] **Step 1: Write RED create/get/restart tests**

Test sequence:

```python
store_a = PostgresExecutionSagaStoreV2(dsn)
stored = store_a.create_saga(definition)
store_a.close()
store_b = PostgresExecutionSagaStoreV2(dsn)
assert store_b.get_saga(definition.saga_id) == stored
```

Also test idempotent create of the exact definition and `SAGA_CONFLICT` if the same `saga_id` is bound to different definition evidence.

- [ ] **Step 2: Implement create/get**

Use `encode_stored_saga_v2`/`decode_stored_saga_v2`. `create_saga` uses insert-on-conflict followed by exact definition comparison; it must not silently replace an existing saga.

- [ ] **Step 3: Write RED CAS transition test**

Two independent store/connection instances load revision `N`; both attempt different valid transitions with `expected_revision=N`; exactly one commits revision `N+1`; the loser raises `ReconciliationError(code="SAGA_CONFLICT")`.

- [ ] **Step 4: Implement a single transition primitive**

Use one internal method equivalent to:

```python
def _transition(self, saga_id, expected_revision, transition):
    # BEGIN
    # SELECT current snapshot
    # decode + domain transition
    # UPDATE execution_saga.saga_v2
    #   SET saga_revision = next.saga_revision, snapshot = ..., status = ...
    #   WHERE saga_id = %s AND saga_revision = %s
    # if rowcount != 1 -> SAGA_CONFLICT
    # COMMIT
```

Do not rely on a row lock as the externally visible concurrency contract; the `WHERE saga_revision = expected_revision` CAS must remain present.

- [ ] **Step 5: Implement all `ExecutionSagaStoreV2` methods through that primitive**

Replay-safe same-evidence calls must return the current stored state just as `InMemoryExecutionSagaStoreV2` does.

- [ ] **Step 6: Run GREEN and commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest tests/execution_reconciliation/test_postgres_saga_store_v2.py -q
git add platform/execution_reconciliation tests/execution_reconciliation/test_postgres_saga_store_v2.py
git commit -m "feat: add postgres execution saga v2 store"
```

---

### Task 6: Turn store parity into a reusable conformance suite

**Files:**
- Create: `tests/execution_reconciliation/saga_store_v2_contract.py`
- Modify: `tests/execution_reconciliation/test_saga_v2_store.py`
- Modify: `tests/execution_reconciliation/test_postgres_saga_store_v2.py`

- [ ] **Step 1: Extract the existing observable contract cases**

Parameterize/store-factory the common cases: initial state, reservation replay, strict CAS conflict, exact authority lineage, Host commit evidence, reconciliation, verification failure, scope breach, pre-commit failure, convergence success/divergence.

- [ ] **Step 2: Run against in-memory and PostgreSQL backends**

PostgreSQL cases require the DSN; in-memory cases never do.

- [ ] **Step 3: Add restart persistence and multi-connection CAS only to the PostgreSQL suite**

- [ ] **Step 4: Run both suites and commit**

```bash
uv run python -m pytest tests/execution_reconciliation/test_saga_v2_store.py -q
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run python -m pytest tests/execution_reconciliation/test_postgres_saga_store_v2.py -q
git add tests/execution_reconciliation
git commit -m "test: enforce execution saga store backend parity"
```

---

### Task 7: Add explicit runtime configuration without silently changing tests

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/saga_store_factory.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_saga_store_factory.py`
- Create: `docs/runbooks/durable-persistence-reference.md`

- [ ] **Step 1: Write RED factory tests**

Require explicit backend selection:

```text
memory   -> InMemoryExecutionSagaStoreV2
postgres -> PostgresExecutionSagaStoreV2, DSN required
unknown  -> fail closed
```

No production path may infer PostgreSQL merely because a DSN happens to exist.

- [ ] **Step 2: Implement the narrow factory**

Suggested surface:

```python
def create_execution_saga_store_v2(*, backend: str, postgres_dsn: str | None = None): ...
```

- [ ] **Step 3: Write the runbook**

Document: owner schema, migration command/API, required credential scope, test DSN, backup responsibility, how to inspect `saga_revision`, and the explicit statement that this credential MUST NOT read/write D5/Gateway/ChangeSet schemas.

- [ ] **Step 4: Test and commit**

```bash
uv run python -m pytest tests/execution_reconciliation/test_saga_store_factory.py -q
git add platform/execution_reconciliation tests/execution_reconciliation/test_saga_store_factory.py \
  docs/runbooks/durable-persistence-reference.md
git commit -m "feat: configure execution saga durable backend explicitly"
```

---

### Task 8: Close the durable-persistence gate

**Files:**
- Modify: `.github/workflows/durable-persistence.yml` only if the preceding tasks exposed missing paths/commands
- Modify: `docs/runbooks/durable-persistence-reference.md` with verified commands/results

- [ ] **Step 1: Run targeted PostgreSQL verification**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run python -m pytest \
  tests/execution_reconciliation/test_postgres_schema_v2.py \
  tests/execution_reconciliation/test_postgres_saga_store_v2.py -q
```

Expected: PASS with restart and concurrent CAS cases.

- [ ] **Step 2: Run owner regression**

```bash
uv run python -m pytest tests/execution_reconciliation -q
uv run ruff check --select E,F,I platform/execution_reconciliation tests/execution_reconciliation
```

- [ ] **Step 3: Run repository truth gates**

```bash
uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
git diff --check
```

Expected: both canonical Python modes GREEN; no new Ruff diagnostics/whitespace errors.

- [ ] **Step 4: Verify architecture properties explicitly**

Confirm with tests/review that:

```text
Postgres adapter preserves ExecutionSagaStoreV2 protocol
stale expected_revision => SAGA_CONFLICT
process restart => saga reloads exactly
no cross-owner SQL/table access
no psycopg import in domain state/contracts
in-memory backend still passes identical conformance suite
```

- [ ] **Step 5: Commit final evidence/runbook updates**

```bash
git add .github/workflows/durable-persistence.yml docs/runbooks/durable-persistence-reference.md
git commit -m "docs: close durable persistence reference gate"
```

## Exit Criteria

This plan is complete only when the PostgreSQL integration lane is green, `PostgresExecutionSagaStoreV2` survives process/store recreation, concurrent stale writers produce the existing `SAGA_CONFLICT`, all in-memory Saga tests remain green, and no caller outside the execution-saga owner needs to know a PostgreSQL table/schema/JSONB shape.

The next implementation plan is `2026-09-16-cross-owner-delivery-crash-recovery.md`; it may rely on the transaction/codec/PostgreSQL foundation established here but must not weaken this plan's owner boundary.