# Step37 Cross-Host Saga Failure Injection Design

**Status:** FROZEN DESIGN CANDIDATE — pending user review

**Base:** `main` at `2b114462c9932d478f752564c0449224125ed58f` (Step36 merged)

**Goal:** Add a provider-neutral execution coordinator above Step33 that can drive one immutable Saga across multiple `HostRuntimeRef` values, stop deterministically on failure, preserve durable partial-commit truth, and expose compensation evidence without inventing inverse Host commands.

## 1. Current facts

Step33 already owns the durable Saga truth:

- immutable `ExecutionSagaDefinition` and canonical Slice order;
- dependency gating and one-active-Slice persistence rules;
- `FAILED_BEFORE_COMMIT`, `SCOPE_BREACH`, `VERIFY_FAILED`, `BLOCKED`;
- `READY`, `EXECUTING`, `PARTIALLY_COMMITTED`, `SUCCEEDED`, `FAILED`;
- compensation proposal/evidence and compensation lifecycle;
- CAS/idempotent persistence of admission, Host commit, scope and verification evidence.

Its failure store already blocks later not-started Slices and determines `FAILED` versus `PARTIALLY_COMMITTED`. Step37 must drive these rules, not recreate them.

Step36 proved a real AutoCAD Host can produce a governed `ActualDelta` that Step33 reconciles. The remaining gap is runtime coordination across more than one Host-bound Slice when a later Slice fails.

`HostRuntimeRef` is a Step30 provider-neutral contract defined by `design_execution_planning`; Step37 reuses it exactly.

## 2. Chosen architecture

Create a new package:

```text
platform/execution_coordination/
  src/design_execution_coordination/
```

Primary component:

```python
ExecutionSagaCoordinator
```

Dependency direction:

```text
Step29 CanonicalChangeSet
        ↓
Step30 ExecutionPlan + HostRuntimeRef
        ↓
Step31/32 binding + admitted authority via port
        ↓
Step37 ExecutionSagaCoordinator
        ↓
exact HostExecutionPort selected by HostRuntimeRef
        ↓
ActualDelta / classified failure
        ↓
existing Step33 reconciliation service/store
```

Step37 is an execution coordinator, not a second reconciliation layer and not a distributed transaction manager.

## 3. Frozen ownership boundaries

### Step33 remains source of truth

Step37 may read `StoredExecutionSaga` and invoke public Step33 service methods. It does not own or redefine:

- Saga ids/hashes/revisions;
- Slice lifecycle statuses;
- failure-to-`BLOCKED` propagation;
- `PARTIALLY_COMMITTED` determination;
- scope/verification persistence;
- compensation evidence or compensation terminal status.

### Step37 owns forward progression

Step37 owns only:

- selecting the next Slice from Step33 `ordered_slice_hashes`;
- exact routing to the Slice `HostRuntimeRef`;
- obtaining exact Step32 authority through a port;
- making one Host execution attempt;
- classifying commit certainty;
- invoking Step33 transitions in the correct order;
- stopping when forward execution is unsafe.

### Step31/32 remain authoritative

Step37 does not implement ProviderBinding or GatewayAuthorization rules. `ExecutionAuthorityPort` returns either a real `AdmittedExecutionAuthority` or a pre-Host failure.

### Host implementations remain native

Step37 production code must not import Host implementations or contain native mechanisms such as `Autodesk.AutoCAD`, `GetOffsetCurves`, `LWPOLYLINE`, Revit transaction APIs, or provider-specific entity vocabulary.

### D5 evidence remains external

Step37 does not rebuild semantic snapshots/projections. A provider-neutral evidence port supplies a `VerificationEvidenceBundle`; Step37 passes it to the existing Step33 verifier.

### Compensation remains governed

Step37 never infers inverse Host commands. Recovery begins from a Step33 `CompensationProposal` based on durable evidence plus caller-supplied canonical recovery effects. Any recovery mutation is a new governed execution that re-enters the existing canonical authority chain before a Host is called.

## 4. Frozen provider-neutral interfaces

Names and semantics below are frozen for the implementation plan.

### Coordination status

```python
class CoordinationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
```

```python
@dataclass(frozen=True, slots=True)
class CoordinationResult:
    saga_id: str
    saga_revision: int
    status: CoordinationStatus
    active_slice_hash: str | None
    failure_ref: str | None
```

`RECOVERY_REQUIRED` means Step37 cannot safely continue without authoritative recovery of external facts. It is not projected into a fabricated Step33 terminal status.

### Deterministic clock

```python
class CoordinationClock(Protocol):
    def now(self) -> str: ...
```

All coordinator-generated `reserved_at`, local failure timestamps, and reconciliation timestamps come from this injected clock. Step37 production code must not call wall-clock APIs directly.

### Authority port

```python
@dataclass(frozen=True, slots=True)
class AuthorityFailure:
    failure_ref: str
    failed_at: str
```

```python
class ExecutionAuthorityPort(Protocol):
    def admit(
        self,
        execution_slice: ExecutionSlice,
    ) -> AdmittedExecutionAuthority | AuthorityFailure: ...
```

An authority failure is pre-Host and therefore has confirmed no Host mutation.

A returned authority must match exactly:

- `execution_slice_hash`;
- ChangeSet hash;
- approved scope hash;
- Slice `host_runtime_ref.host_instance_id`.

Mismatch is an integrity failure and the Host is not called.

### Host execution port

```python
class HostFailurePhase(str, Enum):
    BEFORE_COMMIT = "BEFORE_COMMIT"
    COMMIT_STATE_UNKNOWN = "COMMIT_STATE_UNKNOWN"
```

```python
@dataclass(frozen=True, slots=True)
class HostCommitted:
    actual_delta: ActualDelta
    committed_at: str

@dataclass(frozen=True, slots=True)
class HostFailed:
    phase: HostFailurePhase
    failure_ref: str
    failed_at: str
```

`HostExecutionResult = HostCommitted | HostFailed`.

```python
class HostExecutionPort(Protocol):
    def execute(
        self,
        execution_slice: ExecutionSlice,
        authority: AdmittedExecutionAuthority,
    ) -> HostExecutionResult: ...
```

Step37 needs only commit certainty. Native adapters may retain more detailed native errors internally.

### Exact Host registry

```python
class HostExecutionRegistry(Protocol):
    def resolve(self, runtime_ref: HostRuntimeRef) -> HostExecutionPort: ...
```

No fallback between Host instances is allowed.

### Verification evidence port

```python
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

The port returns provider-neutral evidence only. Step37 does not understand D5 projection/storage details.

## 5. Coordinator entry point

The coordinator is constructed with:

```text
ExecutionReconciliationService
ExecutionAuthorityPort
HostExecutionRegistry
VerificationEvidencePort
CoordinationClock
```

Its forward-execution request contains the exact:

```text
CanonicalChangeSet
ApprovalScopeBoundary
ExecutionPlan
```

`ExecutionSagaCoordinator.execute(...)` creates or idempotently loads the Step33 Saga from those artifacts and returns `CoordinationResult`.

It does not accept raw Host commands, native entity ids, inverse commands, or a caller-supplied alternative Slice order.

## 6. Deterministic forward algorithm

For one Saga:

1. Create/load Step33 Saga from exact Step29/28/30 lineage.
2. Read Step33 `definition.ordered_slice_hashes`.
3. If Saga is `SUCCEEDED`, return `SUCCEEDED` without Host calls.
4. If Saga is `FAILED`, return `FAILED` without Host calls.
5. If Saga is `PARTIALLY_COMMITTED`, return `PARTIALLY_COMMITTED` without normal forward execution.
6. If any Slice is already active (`ADMISSION_RESERVED`, `ADMITTED`, `HOST_COMMITTED`, or `RECONCILING`) at coordinator entry, do not re-run mutation; return `RECOVERY_REQUIRED` unless the implementation can complete only pure Step33 persistence from already supplied durable evidence. Step37 MVP does not invent missing external evidence.
7. Resolve the next Slice by exact hash from the Step30 `ExecutionPlan`.
8. Call Step33 `reserve_slice_admission(...)` using the injected clock and current Saga CAS revision.
9. Call `ExecutionAuthorityPort.admit(...)`.
10. If it returns `AuthorityFailure`, call Step33 `fail_slice_before_commit(...)` and stop.
11. Validate exact authority lineage and Host instance; then call Step33 `confirm_slice_admitted(...)`.
12. Resolve the exact Host through `HostExecutionRegistry`.
13. Call `HostExecutionPort.execute(...)` exactly once.
14. Handle the closed result:
    - `HostFailed(BEFORE_COMMIT)`: call Step33 `fail_slice_before_commit(...)`; stop.
    - `HostFailed(COMMIT_STATE_UNKNOWN)`: do not record a false failure, do not fabricate `ActualDelta`, do not retry, do not advance; return `RECOVERY_REQUIRED`.
    - `HostCommitted`: record the real `ActualDelta` with Step33.
15. Call Step33 `begin_reconciliation(...)`.
16. Build `ScopeComparisonRequest` from exact authority, delta, boundary, and Slice.
17. Run Step33 `compare_scope(...)` then `record_scope_result(...)`.
18. On `SCOPE_BREACH`, stop; Step33 owns `PARTIALLY_COMMITTED` and later `BLOCKED` states.
19. Build provider-neutral verification evidence through `VerificationEvidencePort`.
20. Resolve exactly the validation task ids assigned to the Slice by the immutable Saga definition.
21. Build `SemanticVerificationRequest`, run Step33 verification, and persist the result.
22. On failed/insufficient verification, stop; Step33 owns `VERIFY_FAILED`, `PARTIALLY_COMMITTED`, and later `BLOCKED` states.
23. On Slice success, continue with the next Step33-ordered eligible Slice.
24. When all Slices succeed, return `SUCCEEDED`.

The coordinator never computes a different order and never bypasses Step33 CAS.

## 7. Commit-state uncertainty is fail-closed

`COMMIT_STATE_UNKNOWN` covers cases such as:

```text
Step37 sends Host command
Host may commit
transport drops before a trustworthy response arrives
```

Step37 must not:

- mark `FAILED_BEFORE_COMMIT`;
- create an empty/fake `ActualDelta`;
- retry the Host command;
- advance another Slice;
- build compensation as though commit evidence were known.

The Slice remains at its last durable active Step33 state, normally `ADMITTED`. Existing Step33 one-active-Slice rules then prevent forward admission. Step37 returns `RECOVERY_REQUIRED` with the Host-supplied `failure_ref`.

A later run sees the unresolved active Slice and must not call the Host again automatically.

Step37 does not add a convenience `UNKNOWN` Step33 status that would misstate model truth.

## 8. Failure injection design

Failure injection exists only in deterministic test doubles implementing the production ports. No production Host gets a Step37 debug command or failure flag.

Required injection cases:

```text
AUTHORITY_BEFORE_ADMISSION
HOST_BEFORE_COMMIT
HOST_COMMIT_STATE_UNKNOWN
SCOPE_BREACH
VERIFY_FAILED
COMPENSATION_FAILED
```

Mappings:

- authority failure -> `FAILED_BEFORE_COMMIT`;
- Host confirmed pre-commit failure -> `FAILED_BEFORE_COMMIT`;
- unknown commit state -> coordinator `RECOVERY_REQUIRED`, no fabricated Step33 failure;
- scope breach after real/synthetic provider-neutral commit evidence -> Step33 `SCOPE_BREACH`;
- failed verification after committed within-scope evidence -> Step33 `VERIFY_FAILED`;
- compensation result `succeeded=False` -> existing Step33 `COMPENSATION_FAILED`.

## 9. Required proof scenarios

### A. Two Host runtimes succeed

One Saga has at least two Slices with different `HostRuntimeRef` values.

Expected:

```text
Slice A -> Host A -> SUCCEEDED
Slice B -> Host B -> SUCCEEDED
Saga -> SUCCEEDED
```

Each Host is called exactly once for its own Slice and never receives the other Host's Slice.

### B. Later Host fails before commit

```text
Slice A -> SUCCEEDED
Slice B -> BEFORE_COMMIT
Slice C -> never called
```

Expected durable truth:

```text
Slice A = SUCCEEDED
Slice B = FAILED_BEFORE_COMMIT
Slice C = BLOCKED
Saga    = PARTIALLY_COMMITTED
```

Slice B has no `actual_delta_hash`.

### C. First Slice fails before any commit

Expected:

```text
Slice A = FAILED_BEFORE_COMMIT
later   = BLOCKED
Saga    = FAILED
```

No Step33 compensation proposal is valid because the Saga is not partially committed.

### D. Later Host commits then breaches scope

Expected:

```text
Slice A = SUCCEEDED
Slice B = SCOPE_BREACH with real ActualDelta evidence
later   = BLOCKED
Saga    = PARTIALLY_COMMITTED
```

### E. Later Host commits then fails verification

Expected:

```text
Slice A = SUCCEEDED
Slice B = VERIFY_FAILED with real ActualDelta + scope evidence
later   = BLOCKED
Saga    = PARTIALLY_COMMITTED
```

### F. Host commit state is unknown

Expected:

```text
Coordinator = RECOVERY_REQUIRED
active Slice remains at last durable Step33 state
later Slices are not admitted
Host is not retried on coordinator restart
```

## 10. Compensation handoff

Step37 may delegate creation of a Step33 `CompensationProposal`:

```python
create_compensation_proposal(
    source_saga_id,
    failed_slice_hash,
    desired_recovery_effects,
)
```

The proposal is derived only from durable Step33 evidence:

- committed Slice hashes;
- `ActualDelta` hashes;
- verification failure refs;
- scope breach refs;
- caller-supplied canonical recovery effects.

Step37 has no API that accepts or generates an inverse Host command. Recovery execution is outside normal forward execution of the failed Saga and must re-enter the existing canonical authority pipeline before any Host mutation.

## 11. Idempotency and restart rules

- `SUCCEEDED` Slices are never re-executed.
- `FAILED_BEFORE_COMMIT`, `SCOPE_BREACH`, `VERIFY_FAILED`, and `BLOCKED` Slices are never re-executed in the same Saga.
- `PARTIALLY_COMMITTED` Sagas never resume ordinary forward execution.
- an unresolved active Slice is not automatically replayed.
- Step33 CAS conflicts stop coordination; Step37 does not retry a mutation to resolve persistence races.
- Step33 idempotent evidence persistence does not imply Host mutation replay is safe.

## 12. Integrity checks before Host mutation

Step37 validates before calling a Host:

- Saga ChangeSet hash == supplied ChangeSet hash;
- Saga approved scope hash == supplied boundary hash;
- Saga execution plan hash == supplied execution plan hash;
- Slice hash appears exactly once in the Step30 plan and belongs to the immutable Saga definition;
- authority Slice hash, ChangeSet hash, approved scope hash, and Host instance all join exactly;
- Host registry resolution matches the exact Step30 `HostRuntimeRef`.

After commit, Step33 remains responsible for `ActualDelta` hash/lineage validation. Step37 does not implement a second hashing scheme.

## 13. Dependency direction

Allowed Step37 production dependencies:

```text
design_approval_scope
design_changeset
design_execution_planning  # includes HostRuntimeRef
design_gateway_authorization
design_execution_reconciliation
```

Forbidden dependencies:

```text
hosts.autocad.*
future hosts.revit.*
AutoCAD/Revit native APIs
provider-specific native entity models
```

`design_execution_reconciliation` must not import `design_execution_coordination`; dependency direction is Step37 -> Step33 only.

## 14. Expected read-only production boundaries

Step37 MVP treats these as read-only unless TDD proves a genuine public-interface gap:

- Step33 state/failure semantics;
- Step31 provider binding production code;
- Step32 gateway authorization production code;
- AutoCAD plugin production code;
- AutoCAD sidecar production code.

If implementation appears to require changing Step33 failure meanings or inserting native vocabulary into Step37 core, implementation stops and returns to design review.

## 15. Test strategy

### Unit

Prove:

- exact Host registry routing;
- authority mismatch rejection before Host call;
- Step33 order is the only progression order;
- clock injection controls coordinator timestamps;
- unresolved active Slice returns `RECOVERY_REQUIRED` without Host replay.

### Integration

Use a provider-neutral three-Slice fixture with at least two distinct `HostRuntimeRef` values. Use real Step33 service/store components and deterministic fake authority/Host/evidence ports. Inject every required failure and assert exact persisted Step33 state.

### Architecture guard

Prove:

- Step37 imports Step33, never the reverse;
- no AutoCAD/Revit native vocabulary in Step37 production code;
- failure injection helpers live only under tests;
- no production failure-debug switch;
- no inverse Host command API;
- unknown commit state cannot call `fail_slice_before_commit`;
- two distinct Host runtime identities are exercised.

### Regression

Keep green:

- Step29 changeset;
- Step30 execution planning;
- Step31 provider binding;
- Step32 gateway authorization;
- all Step33 reconciliation tests;
- Step34 AutoCAD wall-thickness offline integration;
- Step36 AutoCAD OFFSET/CREATE/scope-breach offline integration;
- full repository importlib suite.

## 16. Dedicated CI

Add a Step37 workflow covering:

- Step37 spec/plan;
- `platform/execution_coordination/**`;
- Step29–33 packages used by the coordinator;
- Step37 tests;
- Step34/36 execution-contract regressions.

Required gate:

1. Step37 unit/integration/architecture tests;
2. Step29–33 regressions;
3. Step34/36 offline regressions;
4. full importlib regression;
5. Ruff no-new-diagnostics policy against current `main` baseline;
6. `git diff --check main...HEAD`.

Step37 itself adds no live AutoCAD requirement because the MVP does not change AutoCAD production code. If AutoCAD production code changes, live acceptance must be reopened explicitly.

## 17. Non-goals

Step37 does not add:

- parallel Slice execution;
- distributed two-phase commit;
- global rollback transactions;
- automatic retries after ambiguous Host failures;
- automatic inverse-command generation;
- a second real production Host implementation;
- Revit support;
- new semantic identity protocols;
- new Step33 statuses for coordinator convenience;
- provider-specific production failure injection hooks;
- automatic compensation Host execution outside Steps27–32 authority.

## 18. Completion gate

```text
two different HostRuntimeRefs participate in one Saga: PASS
Step33 canonical Slice order drives execution: PASS
successor cannot execute before predecessor succeeds: PASS
exact Host routing prevents cross-instance execution: PASS
pre-commit failure never fabricates ActualDelta: PASS
first-slice pre-commit failure -> FAILED + later BLOCKED: PASS
later pre-commit failure after prior commit -> PARTIALLY_COMMITTED: PASS
committed predecessor remains durably committed after later failure: PASS
post-commit scope breach -> PARTIALLY_COMMITTED + later BLOCKED: PASS
post-commit verify failure -> PARTIALLY_COMMITTED + later BLOCKED: PASS
COMMIT_STATE_UNKNOWN fails closed without retry or false failure state: PASS
restart with unresolved active Slice does not replay Host mutation: PASS
compensation proposal derives only from durable Step33 evidence: PASS
coordinator never invents inverse Host commands: PASS
compensation is handed back to the governed canonical authority chain: PASS
Host-native vocabulary absent from Step37 production code: PASS
failure injection exists only in test doubles: PASS
Step33/34/36 regressions remain green: PASS
full offline regression/lint/diff gate: PASS
```

## 19. Design decision

> Progress only when the prior Slice has durable reconciled success. When commit certainty is lost, stop. When a committed Slice breaches scope or fails semantic verification, preserve partial-commit truth and require governed compensation. Never manufacture rollback truth.
