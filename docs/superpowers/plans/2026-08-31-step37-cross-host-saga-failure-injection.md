# Step37 Cross-Host Saga Failure Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-neutral `ExecutionSagaCoordinator` that drives one immutable Step33 Saga across multiple Step30 `HostRuntimeRef` values, stops deterministically on failure, preserves partial-commit truth, and hands recovery back to governed compensation without inventing inverse Host commands.

**Architecture:** Create a new `design_execution_coordination` package above Step33. The coordinator owns only forward progression: create/load the Step33 Saga, follow the immutable Step33 Slice order, obtain Step32 authority through a narrow port, route to the exact Host runtime, make one Host attempt, and delegate commit/scope/verification/failure persistence to existing Step33 public APIs. Failure injection is test-only and uses the same authority/Host/evidence ports; Step33 remains the sole Saga state machine.

**Tech Stack:** Python 3.11, dataclasses, `typing.Protocol`, pytest, existing DSP Steps 27–33 packages, existing Step33 `ExecutionReconciliationService`/`InMemoryExecutionSagaStore`, GitHub Actions, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-31-step37-cross-host-saga-failure-injection-design.md`

## Global Constraints

- Step37 is sequential only. No parallel Slice execution, distributed two-phase commit, or global rollback transaction.
- `design_execution_reconciliation` remains the source of truth for Saga ids/hashes/revisions, Slice statuses, `BLOCKED`, `FAILED`, `PARTIALLY_COMMITTED`, scope/verification evidence, and compensation lifecycle.
- Dependency direction is one-way: `design_execution_coordination -> design_execution_reconciliation`. Step33 must not import Step37.
- `HostRuntimeRef` is reused from `design_execution_planning`; do not create a second runtime-identity type.
- Step37 must not import `hosts.autocad.*`, future Revit Host packages, AutoCAD/Revit APIs, or provider-native entity vocabulary.
- Step37 does not implement Step31 binding or Step32 authorization policy. It consumes a real `AdmittedExecutionAuthority` through `ExecutionAuthorityPort`.
- D5 snapshot/projection construction stays outside Step37. `VerificationEvidencePort` supplies provider-neutral `VerificationEvidenceBundle` values.
- Expected Host execution outcomes use the closed union `HostCommitted | HostFailed`; expected failures are not Python exceptions.
- `HostFailed(BEFORE_COMMIT)` is the only Host result that may be persisted as Step33 `FAILED_BEFORE_COMMIT`.
- `HostFailed(COMMIT_STATE_UNKNOWN)` must not call `fail_slice_before_commit`, must not fabricate `ActualDelta`, must not retry, and must not admit another Slice.
- Any unresolved active Slice at `ExecutionSagaCoordinator.execute(...)` entry returns `RECOVERY_REQUIRED` with no Host call and no automatic recovery/replay.
- A completed `SUCCEEDED` Slice is never re-executed. `FAILED_BEFORE_COMMIT`, `SCOPE_BREACH`, `VERIFY_FAILED`, and `BLOCKED` Slices are never re-executed inside the same Saga.
- A `PARTIALLY_COMMITTED` Saga never resumes ordinary forward execution.
- Step37 never infers an inverse Host command. Compensation derives from durable Step33 evidence plus caller-supplied canonical recovery effects and must re-enter Steps 27–32 before another Host mutation.
- Coordinator-generated timestamps come from injected `CoordinationClock`; production Step37 code must not call wall-clock APIs directly.
- Failure injection helpers live under `tests/` only. No production Host gets a Step37 debug/failure flag.
- AutoCAD plugin and sidecar production code are read-only for Step37 MVP. If either changes, reopen the relevant live AutoCAD acceptance gate explicitly.
- Step33 state/failure semantics, Step31 ProviderBinding, and Step32 GatewayAuthorization production code are read-only unless TDD proves a genuine public-interface gap; if such a gap appears, stop and return to design review rather than editing those layers ad hoc.
- Ruff uses the repository's baseline-aware no-new-diagnostics policy; do not claim the repository has zero historical Ruff findings.

## Planned file map

### Production

- Create `platform/execution_coordination/pyproject.toml` — package metadata only.
- Create `platform/execution_coordination/src/design_execution_coordination/contracts.py` — Step37 immutable values/errors only.
- Create `platform/execution_coordination/src/design_execution_coordination/ports.py` — narrow provider-neutral protocols only.
- Create `platform/execution_coordination/src/design_execution_coordination/coordinator.py` — deterministic forward algorithm and compensation-proposal handoff.
- Create `platform/execution_coordination/src/design_execution_coordination/__init__.py` — public Step37 API exports only.
- Modify `pyproject.toml` — add only `platform/execution_coordination/src` to pytest `pythonpath`.

### Tests

- Create `tests/execution_coordination/conftest.py` — public-API-only three-Slice fixture, real Step32 authorities, signed `ActualDelta`/verification evidence builders, deterministic fake Step37 ports.
- Create `tests/execution_coordination/test_step37_contracts.py` — contract validation and public API.
- Create `tests/execution_coordination/test_step37_fixture.py` — prove the fixture itself is a real three-Slice/two-plus-runtime Step29–33 lineage.
- Create `tests/execution_coordination/test_step37_success.py` — exact routing and full two-plus-Host success.
- Create `tests/execution_coordination/test_step37_precommit_failures.py` — authority/Host pre-commit failures, blocking, durable predecessor truth.
- Create `tests/execution_coordination/test_step37_postcommit_failures.py` — scope breach and semantic verification failure after real `ActualDelta` persistence.
- Create `tests/execution_coordination/test_step37_unknown_commit.py` — fail-closed ambiguous commit and restart no-replay.
- Create `tests/execution_coordination/test_step37_compensation.py` — durable proposal handoff and compensation-failure harness proof.
- Create `tests/integration/test_step37_architecture.py` — dependency/native-vocabulary/failure-injection/inverse-command guards.

### CI

- Create `.github/workflows/step37-cross-host-saga-failure-injection.yml` — dedicated offline Step37 gate.

---

### Task 1: Scaffold Step37 contracts and ports

**Files:**
- Create: `platform/execution_coordination/pyproject.toml`
- Create: `platform/execution_coordination/src/design_execution_coordination/contracts.py`
- Create: `platform/execution_coordination/src/design_execution_coordination/ports.py`
- Create: `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Modify: `pyproject.toml`
- Test: `tests/execution_coordination/test_step37_contracts.py`

**Interfaces:**
- Consumes: `ExecutionSlice`, `HostRuntimeRef`, `AdmittedExecutionAuthority`, `ActualDelta`, `VerificationEvidenceBundle`, `CanonicalChangeSet`, `ApprovalScopeBoundary`.
- Produces: `CoordinationError`, `CoordinationStatus`, `CoordinationResult`, `CoordinationClock`, `AuthorityFailure`, `ExecutionAuthorityPort`, `HostFailurePhase`, `HostCommitted`, `HostFailed`, `HostExecutionResult`, `HostExecutionPort`, `HostExecutionRegistry`, `VerificationEvidencePort`.

- [ ] **Step 1: Write the RED public-contract test**

Create `tests/execution_coordination/test_step37_contracts.py` with imports from the future public package and assertions for the closed enums/value validation:

```python
import pytest

from design_execution_coordination import (
    AuthorityFailure,
    CoordinationResult,
    CoordinationStatus,
    HostFailed,
    HostFailurePhase,
)


def test_step37_coordination_contracts_are_closed_and_validated():
    result = CoordinationResult(
        saga_id="SG-STEP37",
        saga_revision=3,
        status=CoordinationStatus.RECOVERY_REQUIRED,
        active_slice_hash="a" * 64,
        failure_ref="HOST-TIMEOUT-001",
    )
    assert result.status is CoordinationStatus.RECOVERY_REQUIRED

    failure = HostFailed(
        phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
        failure_ref="HOST-TIMEOUT-001",
        failed_at="2026-08-31T12:00:00Z",
    )
    assert failure.phase is HostFailurePhase.COMMIT_STATE_UNKNOWN

    with pytest.raises(ValueError):
        CoordinationResult(
            saga_id="SG-STEP37",
            saga_revision=-1,
            status=CoordinationStatus.FAILED,
            active_slice_hash=None,
            failure_ref=None,
        )

    with pytest.raises(ValueError):
        AuthorityFailure(failure_ref="", failed_at="2026-08-31T12:00:00Z")
```

- [ ] **Step 2: Run the test and observe RED**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_contracts.py -q
```

Expected: collection/import failure because `design_execution_coordination` does not exist.

- [ ] **Step 3: Add package metadata and root pythonpath**

Create `platform/execution_coordination/pyproject.toml` exactly in the repository package style:

```toml
[project]
name = "design-execution-coordination"
version = "0.1.0"
description = "Provider-neutral cross-host execution Saga coordination for DSP."
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Add this entry to root `pyproject.toml` `[tool.pytest.ini_options].pythonpath` immediately after execution planning/reconciliation neighbors:

```toml
"platform/execution_coordination/src",
```

Do not add Host implementation paths or a workspace refactor.

- [ ] **Step 4: Implement immutable Step37 values**

Create `contracts.py` with the exact public shapes:

```python
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from design_execution_reconciliation import ActualDelta

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")


class CoordinationError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = _text(code, "code")


class CoordinationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"


class HostFailurePhase(str, Enum):
    BEFORE_COMMIT = "BEFORE_COMMIT"
    COMMIT_STATE_UNKNOWN = "COMMIT_STATE_UNKNOWN"


@dataclass(frozen=True, slots=True)
class CoordinationResult:
    saga_id: str
    saga_revision: int
    status: CoordinationStatus | str
    active_slice_hash: str | None
    failure_ref: str | None


@dataclass(frozen=True, slots=True)
class AuthorityFailure:
    failure_ref: str
    failed_at: str


@dataclass(frozen=True, slots=True)
class HostCommitted:
    actual_delta: ActualDelta
    committed_at: str


@dataclass(frozen=True, slots=True)
class HostFailed:
    phase: HostFailurePhase | str
    failure_ref: str
    failed_at: str


HostExecutionResult = HostCommitted | HostFailed
```

Implement `_text`, optional text, digest, optional digest, non-negative revision and enum normalization in the same strict style as Step33 contracts. `active_slice_hash` is `None` or lowercase SHA-256. `failure_ref` is provider-neutral non-empty text when present. `HostCommitted.actual_delta` must be an `ActualDelta`; timestamps are non-empty text.

- [ ] **Step 5: Implement narrow protocols**

Create `ports.py`:

```python
from __future__ import annotations

from typing import Protocol

from design_approval_scope import ApprovalScopeBoundary
from design_changeset import CanonicalChangeSet
from design_execution_planning import ExecutionSlice, HostRuntimeRef
from design_execution_reconciliation import ActualDelta, VerificationEvidenceBundle
from design_gateway_authorization import AdmittedExecutionAuthority

from .contracts import AuthorityFailure, HostExecutionResult


class CoordinationClock(Protocol):
    def now(self) -> str: ...


class ExecutionAuthorityPort(Protocol):
    def admit(
        self,
        execution_slice: ExecutionSlice,
    ) -> AdmittedExecutionAuthority | AuthorityFailure: ...


class HostExecutionPort(Protocol):
    def execute(
        self,
        execution_slice: ExecutionSlice,
        authority: AdmittedExecutionAuthority,
    ) -> HostExecutionResult: ...


class HostExecutionRegistry(Protocol):
    def resolve(self, runtime_ref: HostRuntimeRef) -> HostExecutionPort: ...


class VerificationEvidencePort(Protocol):
    def build_bundle(
        self,
        *,
        execution_slice: ExecutionSlice,
        actual_delta: ActualDelta,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundary,
    ) -> VerificationEvidenceBundle: ...
```

No protocol may accept native ids, Host command strings, inverse commands, or provider-specific types.

- [ ] **Step 6: Export only the Step37 public API**

Create `__init__.py` exporting every type above. Do not export internal validation helpers.

- [ ] **Step 7: Run focused contract tests**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_contracts.py -q
```

Expected: PASS.

- [ ] **Step 8: Run import/lint smoke checks**

Run:

```bash
python -c "import design_execution_coordination; print('design_execution_coordination OK')"
ruff check --select E,F,I platform/execution_coordination tests/execution_coordination/test_step37_contracts.py
```

Expected: both succeed with no Step37 diagnostics.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml platform/execution_coordination tests/execution_coordination/test_step37_contracts.py
git commit -m "feat: add Step37 coordination contracts"
```

---

### Task 2: Build the real three-Slice cross-host fixture and deterministic ports

**Files:**
- Create: `tests/execution_coordination/conftest.py`
- Create: `tests/execution_coordination/test_step37_fixture.py`

**Interfaces:**
- Consumes: public Step27–33 APIs only.
- Produces test-only: `Step37Transaction`, `step37_three_slice_transaction`, `build_authority_for_slice`, `build_delta_for_slice`, `build_verification_bundle`, `FixedClock`, `DeterministicAuthorityPort`, `DeterministicHostPort`, `DeterministicHostRegistry`, `DeterministicEvidencePort`.

- [ ] **Step 1: Write a fixture characterization test**

Create `test_step37_fixture.py`:

```python
def test_step37_fixture_has_three_slices_and_multiple_runtime_identities(
    step37_three_slice_transaction,
):
    plan = step37_three_slice_transaction.execution_plan
    assert len(plan.execution_slices) == 3
    runtime_refs = tuple(slice_.host_runtime_ref for slice_ in plan.execution_slices)
    assert len(set(runtime_refs)) == 3
    assert {ref.host_instance_id for ref in runtime_refs} == {
        "HOST-STEP37-A",
        "HOST-STEP37-B",
        "HOST-STEP37-C",
    }
```

This test characterizes existing Steps 27–30; it is allowed to start GREEN once the fixture exists because this task builds test infrastructure rather than production behavior.

- [ ] **Step 2: Build one public-API-only Step37 transaction**

In `conftest.py`, define:

```python
@dataclass(frozen=True, slots=True)
class Step37Transaction:
    canonical_changeset: CanonicalChangeSet
    approval_scope_boundary: ApprovalScopeBoundary
    execution_plan: ExecutionPlan
```

Construct one root `semantic.assertions.v1` operation targeting `WALL-001` with `properties.thickness == 300.0`, using the exact semantic-assertions schema/verification-contract shape already proven in `tests/execution_reconciliation/conftest.py`.

Add two deterministic Step27 dependency edges from `WALL-001`:

```python
DependencyEdge(
    dependency_id="DEP-STEP37-B",
    source_semantic_id="WALL-001",
    target_semantic_id="ANNOTATION-002",
    strength=DependencyStrength.SOFT,
    propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
    propagation_action=PropagationAction.RECOMPUTE,
    rule_ref="RULE-STEP37-B",
)

DependencyEdge(
    dependency_id="DEP-STEP37-C",
    source_semantic_id="WALL-001",
    target_semantic_id="TAG-003",
    strength=DependencyStrength.SOFT,
    propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
    propagation_action=PropagationAction.RECOMPUTE,
    rule_ref="RULE-STEP37-C",
)
```

Freeze the intent boundary to `CanonicalAspect.PROPERTIES` and allow exactly `RULE-STEP37-B` and `RULE-STEP37-C`. For each returned propagation bundle, resolve it by `bundle.rule_ref`, create one `ScopeEffectRecipe`, one derived existing-entity rule id, and one `DerivedOperationMaterialization` using `semantic.assertions.v1`, `targets=(affected_semantic_id,)`, arguments `{"targets": [affected_semantic_id], "assertions": {"properties.thickness": 300.0}}`, and the exact recipe scope rule id.

Create one `ExecutionSliceScopeRule` for `DOC-STEP37` covering the direct rule plus both derived rule ids. Route the three semantic ids to the same document but three exact runtime identities:

```python
HostRuntimeRef("TEST_HOST", "HOST-STEP37-A", "DOC-STEP37")
HostRuntimeRef("TEST_HOST", "HOST-STEP37-B", "DOC-STEP37")
HostRuntimeRef("TEST_HOST", "HOST-STEP37-C", "DOC-STEP37")
```

Use `ExecutionPlanner().plan(...)` and assert the plan contains exactly three Slices. Do not hand-construct an invalid Step30 plan.

- [ ] **Step 3: Add real Step32 authority builders**

For each execution Slice, build a `ProviderBindingSet` using only provider-neutral test values (`provider_server="step37.fixture.provider"`, `provider_tool="execute"`, `native_kind="TEST_ENTITY"`) and issue/admit a real Step32 grant through `GatewayAuthorizationService`, following the public sequence:

```text
consume_approval -> issue_execution_grant -> admit_execution_grant
```

Each authority must carry that Slice's exact `execution_slice_hash`, `binding_set_hash`, `host_instance_id`, ChangeSet hash and approved scope hash. Use a fresh in-memory Gateway store per Slice so the fixture does not introduce cross-Slice consumption policy that Step37 does not own.

- [ ] **Step 4: Add signed ActualChange/ActualDelta builders**

Use the existing public Step33 hash functions, never hard-code fake hashes:

```python
def signed_change(**values) -> ActualChange:
    draft = ActualChange(actual_change_hash="0" * 64, **values)
    return replace(draft, actual_change_hash=compute_actual_change_hash(draft))


def signed_delta(execution_slice, authority, *changes) -> ActualDelta:
    draft = ActualDelta(
        actual_delta_id=f"AD-STEP37-{authority.host_instance_id}",
        grant_hash=authority.grant_hash,
        binding_set_hash=authority.binding_set_hash,
        execution_slice_hash=authority.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=10,
        revision_after=11,
        changes=tuple(changes),
        actual_delta_hash="0" * 64,
    )
    return replace(draft, actual_delta_hash=compute_actual_delta_hash(draft))
```

For normal success, create one `MODIFY` change per Slice target with `changed_aspects=(CanonicalAspect.PROPERTIES,)`. For scope-breach injection, allow the helper to build the same signed delta with `changed_aspects=(CanonicalAspect.GEOMETRY,)`.

- [ ] **Step 5: Add signed semantic verification evidence**

Build real `VerificationEvidenceBundle` values in the same public style as `test_step33_service.py::_signed_happy_bundle`, but parameterize the Slice target and property value. The normal bundle has `properties={"thickness": 300.0}` and `evidence_aspects=(CanonicalAspect.PROPERTIES,)`; the failing bundle uses `properties={"thickness": 301.0}` so the real Step33 `SemanticVerifier` returns `FAILED`, not a fabricated result.

Always compute `evidence_bundle_hash` with `compute_verification_evidence_bundle_hash`. The bundle's snapshot/document/revision/environment/actual-delta lineage must join the real transaction and delta exactly.

- [ ] **Step 6: Add deterministic test-only ports**

Implement in `conftest.py`:

```python
@dataclass
class FixedClock:
    value: str = "2026-08-31T12:00:00Z"
    calls: int = 0

    def now(self) -> str:
        self.calls += 1
        return self.value


class DeterministicAuthorityPort:
    def __init__(self, outcomes):
        self.outcomes = dict(outcomes)
        self.calls = []

    def admit(self, execution_slice):
        self.calls.append(execution_slice.execution_slice_hash)
        return self.outcomes[execution_slice.execution_slice_hash]


class DeterministicHostPort:
    def __init__(self, outcomes):
        self.outcomes = dict(outcomes)
        self.calls = []

    def execute(self, execution_slice, authority):
        self.calls.append((execution_slice.execution_slice_hash, authority.host_instance_id))
        return self.outcomes[execution_slice.execution_slice_hash]


class DeterministicHostRegistry:
    def __init__(self, ports):
        self.ports = dict(ports)
        self.resolutions = []

    def resolve(self, runtime_ref):
        self.resolutions.append(runtime_ref)
        return self.ports[runtime_ref]
```

`DeterministicEvidencePort` records Slice hashes and returns a signed bundle with configured property value. All injection configuration remains in tests.

- [ ] **Step 7: Run fixture characterization**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_fixture.py -q -vv
```

Expected: one fixture test PASS and no Step37 production code needed yet.

- [ ] **Step 8: Commit**

```bash
git add tests/execution_coordination/conftest.py tests/execution_coordination/test_step37_fixture.py
git commit -m "test: add Step37 cross-host saga fixture"
```

---

### Task 3: Implement deterministic coordinator preflight, terminal projection, and active-Slice guard

**Files:**
- Create: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Create: `tests/execution_coordination/test_step37_success.py`
- Create: `tests/execution_coordination/test_step37_unknown_commit.py`

**Interfaces:**
- Consumes: Task 1 contracts/ports, exact Step29/28/30 artifacts, `ExecutionReconciliationService`.
- Produces:

```python
class ExecutionSagaCoordinator:
    def __init__(
        self,
        *,
        reconciliation: ExecutionReconciliationService,
        authority_port: ExecutionAuthorityPort,
        host_registry: HostExecutionRegistry,
        evidence_port: VerificationEvidencePort,
        clock: CoordinationClock,
    ) -> None: ...

    def execute(
        self,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundary,
        execution_plan: ExecutionPlan,
    ) -> CoordinationResult: ...
```

- [ ] **Step 1: Write RED for unresolved active Slice restart**

In `test_step37_unknown_commit.py`, use the real Step33 service/store to create the Saga, reserve and confirm the first Slice manually, then call the future coordinator. Assert:

```python
result = coordinator.execute(changeset, boundary, plan)
assert result.status is CoordinationStatus.RECOVERY_REQUIRED
assert result.active_slice_hash == first_slice.execution_slice_hash
assert authority_port.calls == []
assert all(port.calls == [] for port in host_ports)
```

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_unknown_commit.py::test_active_slice_at_entry_requires_recovery_without_host_replay -q
```

Expected: FAIL because `ExecutionSagaCoordinator` is not defined.

- [ ] **Step 3: Implement preflight helpers**

In `coordinator.py`, define constants using Step33 enums:

```python
_ACTIVE = frozenset({
    SliceReconciliationStatus.ADMISSION_RESERVED,
    SliceReconciliationStatus.ADMITTED,
    SliceReconciliationStatus.HOST_COMMITTED,
    SliceReconciliationStatus.RECONCILING,
})
```

Implement helpers that:

1. call `reconciliation.create_saga(changeset, boundary, plan)` idempotently;
2. assert returned definition hashes join the supplied ChangeSet/scope/plan exactly;
3. build `slice_by_hash` from `execution_plan.execution_slices` and require every `definition.ordered_slice_hashes` value to resolve exactly once;
4. project existing Step33 `SUCCEEDED`, `FAILED`, and `PARTIALLY_COMMITTED` to the corresponding `CoordinationStatus` with no Host call;
5. reject `COMPENSATING`, `COMPENSATED`, or `COMPENSATION_FAILED` with `CoordinationError("SAGA_NOT_FORWARD_EXECUTABLE", ...)` and no Host call;
6. if any Slice is `_ACTIVE`, return `RECOVERY_REQUIRED` with that exact `active_slice_hash` and no external calls.

Do not add a Step33 status for this case.

- [ ] **Step 4: Add terminal no-replay tests**

Drive one fixture Saga to each of `FAILED` and `PARTIALLY_COMMITTED` using real Step33 failure APIs, call coordinator again, and assert the returned status reflects stored truth while authority/Host call logs remain empty.

- [ ] **Step 5: Run preflight tests**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_unknown_commit.py -q
```

Expected: PASS for active/terminal no-replay tests. Full forward success may still be RED until Task 4.

- [ ] **Step 6: Export coordinator and commit**

Add `ExecutionSagaCoordinator` to `__init__.py`, then:

```bash
git add platform/execution_coordination tests/execution_coordination/test_step37_unknown_commit.py
git commit -m "feat: guard Step37 saga restart state"
```

---

### Task 4: Add reservation, exact Step32 authority, exact Host routing, and the full success path

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Test: `tests/execution_coordination/test_step37_success.py`

**Interfaces:**
- Consumes: Task 2 real authorities/deltas/evidence and Task 3 preflight.
- Produces: complete normal forward Slice progression to `CoordinationStatus.SUCCEEDED`.

- [ ] **Step 1: Write RED two-plus-Host success test**

Configure all three Slices with real Step32 authorities, three exact Host registry entries, success `HostCommitted` deltas, and passing evidence. Assert:

```python
result = coordinator.execute(changeset, boundary, plan)
assert result.status is CoordinationStatus.SUCCEEDED
assert result.active_slice_hash is None

stored = reconciliation.get_saga(result.saga_id)
assert stored is not None
assert stored.status is ExecutionSagaStatus.SUCCEEDED
assert all(
    state.status is SliceReconciliationStatus.SUCCEEDED
    for state in stored.slice_states
)
assert authority_port.calls == list(stored.definition.ordered_slice_hashes)
assert [ref.host_instance_id for ref in registry.resolutions] == [
    slice_by_hash[h].host_runtime_ref.host_instance_id
    for h in stored.definition.ordered_slice_hashes
]
```

Also assert each Host port was called exactly once and only with its own Slice/authority host instance.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_success.py -q -vv
```

Expected: FAIL at the first unimplemented forward transition.

- [ ] **Step 3: Implement one complete forward iteration**

For the next Step33-ordered `NOT_STARTED` Slice:

```text
reserve_slice_admission
-> authority_port.admit
-> validate authority joins exact Slice/ChangeSet/scope/host instance
-> confirm_slice_admitted
-> host_registry.resolve(exact HostRuntimeRef)
-> HostExecutionPort.execute exactly once
```

If the authority is a real `AdmittedExecutionAuthority`, require exact equality for:

```python
authority.execution_slice_hash == execution_slice.execution_slice_hash
authority.changeset_hash == stored.definition.changeset_hash
authority.approved_scope_hash == stored.definition.approved_scope_hash
authority.host_instance_id == execution_slice.host_runtime_ref.host_instance_id
```

On mismatch, no Host call is allowed. Because no Host mutation has started, close the active reservation with Step33 `fail_slice_before_commit(...)` using `clock.now()` and return the resulting `FAILED` or `PARTIALLY_COMMITTED` status with `failure_ref="COORDINATION_AUTHORITY_MISMATCH"`.

Resolve the Host by the exact `execution_slice.host_runtime_ref`; do not fall back by `host_type` alone.

- [ ] **Step 4: Persist committed evidence and reconcile through real Step33 components**

For `HostCommitted`:

```text
record_host_commit
-> begin_reconciliation
-> compare_scope(ScopeComparisonRequest(...))
-> record_scope_result
```

If scope is within bounds, resolve the exact `slice_validation_assignments` entry from the immutable Saga definition, map those ids back to `canonical_changeset.validation_tasks`, obtain a bundle from `VerificationEvidencePort`, then:

```text
verify_semantics(SemanticVerificationRequest(...))
-> record_verification_result
```

Use `clock.now()` for `verified_at` and `reconciled_at`. Do not compute Step33 evidence hashes in production Step37 code; Step33 validates and computes its own result hashes.

- [ ] **Step 5: Loop only after durable Slice success**

After `record_verification_result`, continue only if that Slice is now `SUCCEEDED`. Reload Step33 state on each iteration. When Step33 reports Saga `SUCCEEDED`, return `CoordinationStatus.SUCCEEDED`.

Never derive a second Slice order; always use `stored.definition.ordered_slice_hashes`.

- [ ] **Step 6: Add authority mismatch negative**

Create a `replace(authority, host_instance_id="HOST-WRONG")` or mismatched Slice authority that remains structurally valid, return it from the authority port, then assert:

```python
assert no_host_calls
assert failed_state.status is SliceReconciliationStatus.FAILED_BEFORE_COMMIT
assert failed_state.actual_delta_hash is None
```

- [ ] **Step 7: Run Task 4 tests**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_success.py -q
python -m pytest tests/execution_coordination/test_step37_unknown_commit.py -q
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add platform/execution_coordination/src/design_execution_coordination/coordinator.py tests/execution_coordination/test_step37_success.py
git commit -m "feat: coordinate cross-host saga success"
```

---

### Task 5: Prove authority and Host pre-commit failure semantics

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Create: `tests/execution_coordination/test_step37_precommit_failures.py`

**Interfaces:**
- Consumes: `AuthorityFailure`, `HostFailed(BEFORE_COMMIT)`, real Step33 `fail_slice_before_commit`.
- Produces: exact `FAILED` vs `PARTIALLY_COMMITTED` behavior with downstream `BLOCKED` handled by Step33.

- [ ] **Step 1: Write RED for first-Slice authority failure**

Configure the first canonical Slice outcome as:

```python
AuthorityFailure(
    failure_ref="AUTH-DENIED-STEP37",
    failed_at="2026-08-31T12:01:00Z",
)
```

Assert after `execute(...)`:

```text
first = FAILED_BEFORE_COMMIT
later = BLOCKED
Saga = FAILED
no ActualDelta on failed Slice
no Host calls
```

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_precommit_failures.py::test_first_slice_authority_failure_fails_without_host_mutation -q
```

Expected: FAIL until `AuthorityFailure` branch is implemented.

- [ ] **Step 3: Implement AuthorityFailure branch**

After reservation, if `authority_port.admit(...)` returns `AuthorityFailure`, call:

```python
stored = reconciliation.fail_slice_before_commit(
    saga_id,
    execution_slice.execution_slice_hash,
    expected_revision=stored.saga_revision,
    failed_at=authority_failure.failed_at,
)
```

Return `FAILED` or `PARTIALLY_COMMITTED` by projecting the resulting Step33 status. Use the supplied `failure_ref`. Do not call Host registry.

- [ ] **Step 4: Write and implement first-Slice Host BEFORE_COMMIT failure**

Return:

```python
HostFailed(
    phase=HostFailurePhase.BEFORE_COMMIT,
    failure_ref="HOST-PRECOMMIT-STEP37",
    failed_at="2026-08-31T12:02:00Z",
)
```

After real authority confirmation, coordinator calls `fail_slice_before_commit` and stops. Assert first Slice failed, later Slices blocked, Saga failed, no `actual_delta_hash`.

- [ ] **Step 5: Prove later pre-commit failure preserves committed predecessor**

Configure first canonical Slice success, second `HostFailed(BEFORE_COMMIT)`. The third Slice must never be routed. Assert exact durable truth:

```text
Slice 0 = SUCCEEDED and retains actual_delta_hash
Slice 1 = FAILED_BEFORE_COMMIT and actual_delta_hash is None
Slice 2 = BLOCKED
Saga = PARTIALLY_COMMITTED
```

- [ ] **Step 6: Run focused failures and Step33 regression**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_precommit_failures.py -q
python -m pytest tests/execution_reconciliation/test_step33_failure_and_compensation.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add platform/execution_coordination/src/design_execution_coordination/coordinator.py tests/execution_coordination/test_step37_precommit_failures.py
git commit -m "feat: stop Step37 on precommit failures"
```

---

### Task 6: Prove post-commit scope breach and semantic verification failure

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Create: `tests/execution_coordination/test_step37_postcommit_failures.py`

**Interfaces:**
- Consumes: real signed committed `ActualDelta`, real Step33 `ScopeComparator`, real Step33 `SemanticVerifier`, test-only evidence variation.
- Produces: no forward execution after `SCOPE_BREACH` or `VERIFY_FAILED`.

- [ ] **Step 1: Write RED scope-breach scenario**

First Slice succeeds normally. For second Slice, return a real signed `HostCommitted` delta whose `MODIFY` change uses `changed_aspects=(CanonicalAspect.GEOMETRY,)` while the approved rule permits only `PROPERTIES`.

Assert:

```python
assert stored.slice_states[1].status is SliceReconciliationStatus.SCOPE_BREACH
assert stored.slice_states[1].actual_delta_hash is not None
assert stored.slice_states[2].status is SliceReconciliationStatus.BLOCKED
assert stored.status is ExecutionSagaStatus.PARTIALLY_COMMITTED
assert result.status is CoordinationStatus.PARTIALLY_COMMITTED
assert third_host.calls == []
```

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_postcommit_failures.py::test_second_host_commit_scope_breach_stops_and_blocks_later_slice -q
```

Expected: FAIL if coordinator incorrectly continues into verification/third Slice.

- [ ] **Step 3: Stop immediately after persisted scope breach**

After `record_scope_result`, inspect the returned Step33 Slice/Saga status. If scope result is `SCOPE_BREACH`, return `PARTIALLY_COMMITTED` with `failure_ref=result.comparison_hash`. Do not ask the evidence port for a bundle and do not route another Host.

- [ ] **Step 4: Write RED verification failure scenario using real verifier**

First Slice succeeds. Second Slice returns a within-scope `PROPERTIES` delta. Configure `DeterministicEvidencePort` for the second Slice to emit `properties.thickness = 301.0` against the real `SEMANTIC_ASSERTIONS_V1` contract requiring `300.0`.

Assert:

```text
second Slice = VERIFY_FAILED
verification_hash is persisted
second actual_delta_hash is persisted
third Slice = BLOCKED
Saga = PARTIALLY_COMMITTED
third Host not called
```

- [ ] **Step 5: Implement verification-stop projection**

After `record_verification_result`, if Step33 does not report Slice `SUCCEEDED`, stop. For `VERIFY_FAILED`, return `PARTIALLY_COMMITTED` with `failure_ref=verification_result.verification_hash`.

Treat `VerificationStatus.EVIDENCE_INSUFFICIENT` identically for forward-progression purposes: persist the real result, let Step33 mark `VERIFY_FAILED`, and stop.

- [ ] **Step 6: Run post-commit tests**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_postcommit_failures.py -q
python -m pytest tests/execution_reconciliation/test_step33_scope_existing.py tests/execution_reconciliation/test_step33_verifier.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add platform/execution_coordination/src/design_execution_coordination/coordinator.py tests/execution_coordination/test_step37_postcommit_failures.py
git commit -m "feat: stop Step37 after committed reconciliation failure"
```

---

### Task 7: Freeze ambiguous Host commit as recovery-required with no retry

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Modify: `tests/execution_coordination/test_step37_unknown_commit.py`

**Interfaces:**
- Consumes: `HostFailed(COMMIT_STATE_UNKNOWN)`.
- Produces: `CoordinationStatus.RECOVERY_REQUIRED`, active Slice retained at last durable Step33 state, no Host replay on restart.

- [ ] **Step 1: Write RED ambiguous-commit test**

Configure first Slice success and second Host outcome:

```python
HostFailed(
    phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
    failure_ref="HOST-ACK-LOST-STEP37",
    failed_at="2026-08-31T12:03:00Z",
)
```

Assert immediately:

```python
assert result.status is CoordinationStatus.RECOVERY_REQUIRED
assert result.active_slice_hash == second_slice.execution_slice_hash
assert result.failure_ref == "HOST-ACK-LOST-STEP37"
assert second_state.status is SliceReconciliationStatus.ADMITTED
assert second_state.actual_delta_hash is None
assert third_state.status is SliceReconciliationStatus.NOT_STARTED
```

Critically, do **not** expect `FAILED_BEFORE_COMMIT` or `BLOCKED` because commit truth is unknown.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_unknown_commit.py::test_unknown_commit_state_fails_closed_without_false_step33_failure -q
```

Expected: FAIL until the branch is explicit.

- [ ] **Step 3: Implement exact unknown-commit branch**

When the Host result phase is `COMMIT_STATE_UNKNOWN`:

```python
return CoordinationResult(
    saga_id=stored.definition.saga_id,
    saga_revision=stored.saga_revision,
    status=CoordinationStatus.RECOVERY_REQUIRED,
    active_slice_hash=execution_slice.execution_slice_hash,
    failure_ref=host_result.failure_ref,
)
```

There must be no Step33 mutation after the Host result, especially no `fail_slice_before_commit` and no `record_host_commit`.

- [ ] **Step 4: Prove restart does not replay Host mutation**

Call `execute(...)` again with the same coordinator/store. Assert:

```python
assert second_host.calls == [(second_slice.execution_slice_hash, second_authority.host_instance_id)]
assert authority_port.calls.count(second_slice.execution_slice_hash) == 1
assert replay.status is CoordinationStatus.RECOVERY_REQUIRED
assert replay.active_slice_hash == second_slice.execution_slice_hash
```

The second call is stopped by the Task 3 active-Slice entry guard before authority/Host calls.

- [ ] **Step 5: Run unknown-commit suite**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_unknown_commit.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add platform/execution_coordination/src/design_execution_coordination/coordinator.py tests/execution_coordination/test_step37_unknown_commit.py
git commit -m "feat: fail closed on ambiguous Host commit"
```

---

### Task 8: Add governed compensation proposal handoff and prove no inverse Host execution

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Create: `tests/execution_coordination/test_step37_compensation.py`

**Interfaces:**
- Produces:

```python
def create_compensation_proposal(
    self,
    *,
    source_saga_id: str,
    failed_slice_hash: str,
    desired_recovery_effects: tuple[Mapping[str, Any], ...],
) -> CompensationProposal: ...
```

- [ ] **Step 1: Write RED durable-evidence compensation test**

Drive a real Step37 Saga into `PARTIALLY_COMMITTED` through a second-Slice scope breach. Then call:

```python
proposal = coordinator.create_compensation_proposal(
    source_saga_id=stored.definition.saga_id,
    failed_slice_hash=failed_slice.execution_slice_hash,
    desired_recovery_effects=(
        {
            "canonical_operation": "semantic.assertions.v1",
            "targets": ["WALL-001"],
            "arguments": {"assertions": {"properties.thickness": 300.0}},
        },
    ),
)
```

Assert `proposal.committed_slice_hashes` and `proposal.actual_delta_refs` equal the durable Step33 state; `proposal.scope_breach_refs` includes the persisted comparison hash. Also assert no additional Host call occurred while creating the proposal.

- [ ] **Step 2: Run RED**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_compensation.py::test_compensation_proposal_uses_only_durable_step33_evidence -q
```

Expected: FAIL because coordinator convenience method does not exist.

- [ ] **Step 3: Implement thin delegation only**

Implementation must only construct a Step33 request and delegate:

```python
return self._reconciliation.create_compensation_proposal(
    CompensationProposalRequest(
        source_saga_id=source_saga_id,
        failed_slice_hash=failed_slice_hash,
        desired_recovery_effects=desired_recovery_effects,
    )
)
```

No Host registry/authority/evidence port is used by this method.

- [ ] **Step 4: Prove first-Slice failure cannot create compensation**

Drive Saga `FAILED` before any commit and assert Step33 raises `ReconciliationError` with compensation conflict when the convenience method is called. Do not add a Step37 workaround.

- [ ] **Step 5: Prove compensation failure remains Step33 truth**

For the partially committed fixture, use public Step33 APIs to `begin_compensation(...)` with the proposal, then persist:

```python
CompensationExecutionRef(
    compensation_proposal_hash=proposal.proposal_hash,
    compensating_changeset_hash="f" * 64,
    succeeded=False,
    completed_at="2026-08-31T12:30:00Z",
)
```

Assert the source Saga becomes `COMPENSATION_FAILED`. This is a failure-injection harness proof only; the coordinator must expose no method that executes an inverse Host command.

- [ ] **Step 6: Run compensation tests**

Run:

```bash
python -m pytest tests/execution_coordination/test_step37_compensation.py -q
python -m pytest tests/execution_reconciliation/test_step33_failure_and_compensation.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add platform/execution_coordination/src/design_execution_coordination/coordinator.py tests/execution_coordination/test_step37_compensation.py
git commit -m "feat: hand Step37 recovery to governed compensation"
```

---

### Task 9: Add Step37 architecture guard

**Files:**
- Create: `tests/integration/test_step37_architecture.py`

**Interfaces:**
- Consumes production source tree and public Step37 API.
- Produces no production behavior; freezes package dependency/native/failure-injection boundaries.

- [ ] **Step 1: Write architecture tests**

Cover these exact assertions:

```python
CORE = Path("platform/execution_coordination/src/design_execution_coordination")
STEP33 = Path("platform/execution_reconciliation/src/design_execution_reconciliation")


def test_step37_core_has_no_native_host_vocabulary():
    text = "\n".join(path.read_text(encoding="utf-8") for path in CORE.glob("*.py"))
    for forbidden in (
        "Autodesk.AutoCAD",
        "GetOffsetCurves",
        "LWPOLYLINE",
        "Autodesk.Revit",
        "TransactionGroup",
    ):
        assert forbidden not in text


def test_step33_does_not_depend_on_step37():
    text = "\n".join(path.read_text(encoding="utf-8") for path in STEP33.glob("*.py"))
    assert "design_execution_coordination" not in text


def test_failure_injection_is_not_a_production_switch():
    text = "\n".join(path.read_text(encoding="utf-8") for path in CORE.glob("*.py"))
    assert "debug_failure_mode" not in text
    assert "failure_injection" not in text


def test_coordinator_has_no_inverse_host_command_api():
    params = inspect.signature(ExecutionSagaCoordinator.execute).parameters
    forbidden = {name for name in params if "command" in name or "inverse" in name or "rollback" in name}
    assert forbidden == set()
```

Add a runtime guard test for `COMMIT_STATE_UNKNOWN` using a spy Step33 facade or the Task 7 real-store fixture and assert `fail_slice_before_commit` is never called on that path. Do not rely only on string matching for this safety property.

- [ ] **Step 2: Run architecture RED/GREEN check**

Run:

```bash
python -m pytest tests/integration/test_step37_architecture.py -q -vv
```

Expected: PASS once Tasks 1–8 satisfy the frozen architecture.

- [ ] **Step 3: Run Step37 package lint**

Run:

```bash
ruff check --select E,F,I platform/execution_coordination tests/execution_coordination tests/integration/test_step37_architecture.py
```

Expected: zero Step37-owned diagnostics.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_step37_architecture.py
git commit -m "test: guard Step37 coordination architecture"
```

---

### Task 10: Add dedicated Step37 CI and run the complete offline gate

**Files:**
- Create: `.github/workflows/step37-cross-host-saga-failure-injection.yml`

**Interfaces:**
- Produces: repository gate only.

- [ ] **Step 1: Create dedicated workflow triggers**

Trigger on push/PR changes to:

```text
.github/workflows/step37-cross-host-saga-failure-injection.yml
pyproject.toml
docs/superpowers/specs/2026-08-31-step37-cross-host-saga-failure-injection-design.md
docs/superpowers/plans/2026-08-31-step37-cross-host-saga-failure-injection.md
platform/execution_coordination/**
platform/changeset/**
platform/execution_planning/**
platform/provider_binding/**
platform/gateway_authorization/**
platform/execution_reconciliation/**
tests/execution_coordination/**
tests/execution_reconciliation/**
tests/integration/test_step37_architecture.py
tests/integration/test_step34_*.py
tests/integration/test_step36_*.py
```

Do not add AutoCAD plugin/sidecar paths unless Step37 actually changes those production areas.

- [ ] **Step 2: Install the exact offline verification stack**

Workflow install step:

```bash
python -m pip install pytest pytest-asyncio jsonschema PyYAML==6.0.3 ruff
python -m pip install \
  -e contracts/python \
  -e hosts/autocad/sidecar \
  -e platform/changeset \
  -e platform/execution_planning \
  -e platform/provider_binding \
  -e platform/gateway_authorization \
  -e platform/execution_reconciliation \
  -e platform/execution_coordination \
  -e platform/semantic_runtime \
  -e platform/semantic_service \
  -e platform/semantic_mcp \
  -e providers/semantics/dsp_core \
  -e providers/semantics/ifc43 \
  -e providers/semantics/metro_v32 \
  -e providers/semantics/enterprise_mapping
```

- [ ] **Step 3: Add focused Step37 and upstream gates**

Workflow commands:

```bash
python -m pytest tests/execution_coordination -q
python -m pytest tests/integration/test_step37_architecture.py -q
python -m pytest tests/changeset -q
python -m pytest tests/execution_planning -q
python -m pytest tests/provider_binding -q
python -m pytest tests/gateway_authorization -q
python -m pytest tests/execution_reconciliation -q
```

- [ ] **Step 4: Add Step34/36 offline regression commands**

Run at minimum:

```bash
python -m pytest \
  tests/integration/test_step34_autocad_wall_thickness_command.py \
  tests/integration/test_step34_autocad_wall_thickness_reconciliation.py \
  tests/integration/test_step36_offset_creation_authority.py \
  tests/integration/test_step36_autocad_offset_command.py \
  tests/integration/test_step36_architecture.py \
  -q
```

Do not set `AGENT_HOST_TEST=1`; Step37 does not require a live AutoCAD runner.

- [ ] **Step 5: Add full repository regression**

```bash
python -m pytest --import-mode=importlib -q
```

Expected: all repository tests green, with environment-dependent live tests skipped as before.

- [ ] **Step 6: Add baseline-aware Ruff gate**

Use the same normalized Counter-diff strategy as Step36, but scan the expanded current tree:

```bash
git worktree add /tmp/dsp-main origin/main
(
  cd /tmp/dsp-main
  ruff check --select E,F,I --output-format=json platform hosts/autocad/sidecar tests > /tmp/main-ruff.json || true
)
ruff check --select E,F,I --output-format=json platform hosts/autocad/sidecar tests > /tmp/head-ruff.json || true
```

Normalize repository-relative filenames and fail only if `head - main` contains new diagnostics. Print main/head/new counts. Additionally run a strict zero-diagnostic scan on Step37-owned files:

```bash
ruff check --select E,F,I platform/execution_coordination tests/execution_coordination tests/integration/test_step37_architecture.py
```

- [ ] **Step 7: Add diff/boundary checks**

```bash
git diff --check
git diff --check origin/main...HEAD
git log --oneline origin/main..HEAD
git diff --name-only origin/main...HEAD
```

- [ ] **Step 8: Run the exact final local/offline gate before claiming completion**

Run from the feature branch:

```bash
python -m pytest tests/execution_coordination -q
python -m pytest tests/integration/test_step37_architecture.py -q
python -m pytest tests/changeset tests/execution_planning tests/provider_binding tests/gateway_authorization tests/execution_reconciliation -q
python -m pytest \
  tests/integration/test_step34_autocad_wall_thickness_command.py \
  tests/integration/test_step34_autocad_wall_thickness_reconciliation.py \
  tests/integration/test_step36_offset_creation_authority.py \
  tests/integration/test_step36_autocad_offset_command.py \
  tests/integration/test_step36_architecture.py \
  -q
python -m pytest --import-mode=importlib -q
ruff check --select E,F,I platform/execution_coordination tests/execution_coordination tests/integration/test_step37_architecture.py
git diff --check main...HEAD
```

Then run the repository-wide baseline-aware Ruff comparison exactly as the workflow does.

- [ ] **Step 9: Verify branch boundary**

The intended implementation boundary is:

```text
pyproject.toml
platform/execution_coordination/**
tests/execution_coordination/**
tests/integration/test_step37_architecture.py
.github/workflows/step37-cross-host-saga-failure-injection.yml
docs/superpowers/specs/2026-08-31-step37-cross-host-saga-failure-injection-design.md
docs/superpowers/plans/2026-08-31-step37-cross-host-saga-failure-injection.md
```

If Step31/32/33 or AutoCAD production files appear in the final diff, stop and justify them against a proven public-interface gap before completion.

- [ ] **Step 10: Commit CI**

```bash
git add .github/workflows/step37-cross-host-saga-failure-injection.yml
git commit -m "ci: verify Step37 cross-host saga coordination"
```

---

## Final completion gate

Do not claim Step37 complete until fresh evidence proves every line below:

```text
two different HostRuntimeRefs participate in one Saga: PASS
three-Slice fixture exercises downstream BLOCKED truth: PASS
Step33 canonical Slice order drives execution: PASS
successor cannot execute before predecessor succeeds: PASS
exact Host routing prevents cross-instance execution: PASS
real Step32 authorities join exact Slice/ChangeSet/scope/Host identity: PASS
pre-commit failure never fabricates ActualDelta: PASS
first-slice pre-commit failure -> FAILED + later BLOCKED: PASS
later pre-commit failure after prior commit -> PARTIALLY_COMMITTED: PASS
committed predecessor remains durably committed after later failure: PASS
post-commit scope breach -> PARTIALLY_COMMITTED + later BLOCKED: PASS
post-commit verify failure -> PARTIALLY_COMMITTED + later BLOCKED: PASS
COMMIT_STATE_UNKNOWN fails closed without retry or false failure state: PASS
restart with unresolved active Slice does not replay authority or Host mutation: PASS
compensation proposal derives only from durable Step33 evidence: PASS
first-slice FAILED Saga cannot fabricate compensation: PASS
COMPENSATION_FAILED remains Step33 durable truth: PASS
coordinator never invents inverse Host commands: PASS
compensation is handed back to the governed canonical authority chain: PASS
Host-native vocabulary absent from Step37 production code: PASS
failure injection exists only in test doubles: PASS
Step33 production state semantics unchanged: PASS
AutoCAD plugin/sidecar production unchanged: PASS
Step33/34/36 regressions remain green: PASS
full repository importlib regression: PASS
Step37-owned strict Ruff: PASS
repository-wide no-new Ruff diagnostics vs main: PASS
git diff --check main...HEAD: PASS
```

## Implementation stop conditions

Stop implementation and return to design review if any of these occurs:

- Step30 cannot produce the required three-Slice fixture without changing Step30 production semantics.
- Step33 public APIs cannot persist one of the frozen failure outcomes without changing the meaning of existing statuses.
- Step32 authority cannot be supplied through the frozen port without embedding Gateway policy into Step37.
- A Host adapter would need to expose native vocabulary to Step37 core.
- `COMMIT_STATE_UNKNOWN` appears to require marking a false Step33 terminal failure to make progress.
- Recovery appears to require an inverse native command or bypassing Steps 27–32.
- AutoCAD production changes become necessary merely to prove provider-neutral Step37 behavior.
