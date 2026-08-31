# Step37 Cross-Host Saga Failure Injection Design

**Status:** FROZEN DESIGN CANDIDATE — pending user review

**Base:** `main` at `2b114462c9932d478f752564c0449224125ed58f` (Step36 merged)

**Goal:** Add a provider-neutral execution coordinator above Step33 that can drive one immutable Saga across multiple `HostRuntimeRef` values, stop deterministically on failure, preserve durable partial-commit truth, and expose compensation evidence without inventing inverse Host commands.

## 1. Why Step37 exists

Step33 already defines and persists the execution Saga truth. It owns:

- immutable `ExecutionSagaDefinition`;
- canonical Slice ordering and dependencies;
- per-Slice lifecycle state;
- `FAILED_BEFORE_COMMIT`, `SCOPE_BREACH`, `VERIFY_FAILED`, and `BLOCKED`;
- `PARTIALLY_COMMITTED`, `COMPENSATING`, `COMPENSATED`, and `COMPENSATION_FAILED`;
- scope comparison, semantic verification, and compensation evidence.

Step36 proved a real AutoCAD Host can execute a governed CREATE and reconcile the resulting `ActualDelta` back into Step33.

What is still missing is the runtime layer that drives more than one Host-bound Slice in one Saga and behaves correctly when the second or later Slice fails.

Step37 adds that runtime coordination layer. It does not replace or duplicate Step33.

## 2. Chosen architecture

Create a new provider-neutral package:

```text
platform/execution_coordination/
  src/design_execution_coordination/
```

The primary component is:

```python
ExecutionSagaCoordinator
```

It sits above Step33 and composes existing Step30–33 artifacts through narrow ports:

```text
Step29 CanonicalChangeSet
        ↓
Step30 ExecutionPlan
        ↓
Step31 ProviderBinding / runtime routing
        ↓
Step32 AdmittedExecutionAuthority
        ↓
┌────────────────────────────────────┐
│ Step37 ExecutionSagaCoordinator    │
│                                    │
│ - canonical Slice progression      │
│ - dependency gating                │
│ - exact HostRuntimeRef routing     │
│ - failure classification           │
│ - stop / no-retry decisions        │
│ - invokes Step33 primitives        │
└────────────────┬───────────────────┘
                 │
          HostExecutionPort
          ┌──────┴───────┐
          ↓              ↓
       HOST-A          HOST-B
          │              │
          └──────┬───────┘
                 ↓
           ActualDelta / failure
                 ↓
            existing Step33
      scope compare → verify → store
                 ↓
      SUCCEEDED / PARTIALLY_COMMITTED
                 ↓
         CompensationProposal
```

## 3. Frozen ownership boundaries

### 3.1 Step33 remains source of truth

Step37 must not create a second Saga state machine.

The following remain owned by `design_execution_reconciliation`:

- Saga definition/hash/id;
- Saga revision CAS;
- Slice lifecycle statuses;
- failure-to-`BLOCKED` propagation;
- `PARTIALLY_COMMITTED` determination;
- scope comparison result persistence;
- semantic verification result persistence;
- compensation proposal construction and validation;
- compensation lifecycle persistence.

Step37 may read Step33 state and invoke public Step33 service methods only.

### 3.2 Step37 owns progression, not authority creation

Step37 owns the decision to attempt the next canonical eligible Slice.

It does not implement Step31 binding or Step32 authorization rules. Those are exposed to Step37 through an authority port that returns a real `AdmittedExecutionAuthority` or an explicit failure.

### 3.3 Host implementations remain native

Step37 must not know AutoCAD, Revit, Civil 3D, Rhino, IFC authoring APIs, or any native entity vocabulary.

No Step37 production file may contain or depend on mechanisms such as:

- `Autodesk.AutoCAD`;
- `GetOffsetCurves`;
- `LWPOLYLINE`;
- Revit `Transaction` APIs;
- Host-specific command names used only to implement native mutation.

The coordinator sees only provider-neutral execution artifacts and `HostRuntimeRef` routing identities.

### 3.4 D5 / semantic evidence remains external

Step37 does not rebuild semantic snapshots or projections.

After Host commit, verification evidence is supplied through a provider-neutral evidence port. Step37 passes that evidence into the existing Step33 semantic verifier.

### 3.5 Compensation remains governed

Step37 must never infer an inverse Host command.

Examples of forbidden behavior:

```text
offset +300mm  -> silently execute offset -300mm
move +5m       -> silently execute move -5m
create entity  -> silently delete entity
```

The only allowed Step37 compensation action is to expose or request a Step33 `CompensationProposal` based on durable failure evidence plus caller-supplied canonical recovery effects.

Executing recovery is a new governed execution and must re-enter the existing canonical authority chain. Step37 does not bypass Steps27–32 to call a Host directly for compensation.

## 4. New provider-neutral contracts

The implementation plan may refine names, but these semantics are frozen.

### 4.1 Coordination result

```python
class CoordinationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"
```

`RECOVERY_REQUIRED` is reserved for an execution attempt whose Host commit state is unknown. It is intentionally not projected into a false Step33 terminal state.

```python
@dataclass(frozen=True, slots=True)
class CoordinationResult:
    saga_id: str
    saga_revision: int
    status: CoordinationStatus
    active_slice_hash: str | None
    failure_ref: str | None
```

### 4.2 Authority port

```python
class ExecutionAuthorityPort(Protocol):
    def admit(
        self,
        execution_slice: ExecutionSlice,
    ) -> AdmittedExecutionAuthority | AuthorityFailure:
        ...
```

`AuthorityFailure` means no Host mutation occurred. Once a Step33 admission reservation exists, Step37 records it as `FAILED_BEFORE_COMMIT`.

The returned authority must join exactly to:

- the requested `execution_slice_hash`;
- the same ChangeSet hash;
- the same approved scope hash;
- the exact Slice `host_runtime_ref.host_instance_id`.

Any mismatch is a coordination integrity failure before the Host is called.

### 4.3 Host execution port

```python
class HostExecutionPort(Protocol):
    def execute(
        self,
        execution_slice: ExecutionSlice,
        authority: AdmittedExecutionAuthority,
    ) -> HostExecutionResult:
        ...
```

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

`HostExecutionResult` is the closed union `HostCommitted | HostFailed`.

A Host adapter may internally distinguish more detailed native failures, but Step37 only needs the commit-certainty boundary.

### 4.4 Host routing

```python
class HostExecutionRegistry(Protocol):
    def resolve(self, runtime_ref: HostRuntimeRef) -> HostExecutionPort:
        ...
```

Routing is by the exact `HostRuntimeRef` carried by the `ExecutionSlice`.

The registry must not silently fall back from one Host instance to another.

### 4.5 Verification evidence port

```python
class VerificationEvidencePort(Protocol):
    def build_bundle(
        self,
        *,
        execution_slice: ExecutionSlice,
        actual_delta: ActualDelta,
        canonical_changeset: CanonicalChangeSet,
        approval_scope_boundary: ApprovalScopeBoundary,
    ) -> VerificationEvidenceBundle:
        ...
```

The port is responsible only for supplying already-governed provider-neutral evidence. Step37 must not encode D5 storage/projection internals.

## 5. Deterministic coordinator algorithm

Step37 executes sequentially. Parallel Slice execution is out of scope.

For one Saga:

1. Create or load the Step33 Saga from the exact Step29/28/30 lineage.
2. Read `definition.ordered_slice_hashes` from Step33.
3. Resolve the next Slice by exact hash from the Step30 `ExecutionPlan`.
4. Ask Step33 to `reserve_slice_admission(...)` using CAS.
5. Ask `ExecutionAuthorityPort` for the exact Step32 authority.
6. If authority acquisition fails, call `fail_slice_before_commit(...)` and stop.
7. Validate the authority against the exact Slice and call Step33 `confirm_slice_admitted(...)`.
8. Resolve the exact Host through `HostExecutionRegistry`.
9. Call `HostExecutionPort.execute(...)` once.
10. Handle the closed Host result:
    - `HostFailed(BEFORE_COMMIT)`: call `fail_slice_before_commit(...)`; stop.
    - `HostFailed(COMMIT_STATE_UNKNOWN)`: do not call `fail_slice_before_commit`, do not fabricate `ActualDelta`, do not retry, do not admit another Slice; return `RECOVERY_REQUIRED`.
    - `HostCommitted`: validate and record the real `ActualDelta` with Step33.
11. Call Step33 `begin_reconciliation(...)`.
12. Build `ScopeComparisonRequest` from the exact authority, `ActualDelta`, boundary, and Slice.
13. Call Step33 `compare_scope(...)` and `record_scope_result(...)`.
14. If the result is `SCOPE_BREACH`, stop. Step33 owns `PARTIALLY_COMMITTED` and downstream `BLOCKED` transitions.
15. Obtain the verification bundle through `VerificationEvidencePort`.
16. Resolve exactly the validation tasks assigned by the immutable Saga definition.
17. Build `SemanticVerificationRequest` and invoke Step33 verification.
18. Persist the verification result.
19. If verification fails or evidence is insufficient, stop. Step33 owns `VERIFY_FAILED`, `PARTIALLY_COMMITTED`, and downstream `BLOCKED` transitions.
20. If the Slice succeeds, proceed to the next canonical eligible Slice.
21. When every Slice succeeds, return `SUCCEEDED`.

The coordinator must never compute an alternative Slice order. Step33 order is authoritative.

## 6. Commit-state uncertainty rule

`COMMIT_STATE_UNKNOWN` is the most important fail-closed rule in Step37.

Example:

```text
Step37 sends Host command
Host commits transaction
connection drops before response reaches Step37
```

Step37 cannot know whether the model changed.

Therefore it must not:

- mark `FAILED_BEFORE_COMMIT`;
- create an empty/fake `ActualDelta`;
- retry the command;
- advance to the next Slice;
- generate compensation as though commit evidence were known.

Instead:

- the Step33 Slice remains active at its last durable pre-commit state, normally `ADMITTED`;
- the Saga therefore cannot admit another Slice under the existing one-active-Slice invariant;
- Step37 returns `RECOVERY_REQUIRED` with a durable/external `failure_ref` supplied by the Host port;
- later recovery must obtain authoritative Host facts and then either reconstruct real commit evidence or establish that no commit happened before execution can continue.

Step37 does not add a fake Step33 `UNKNOWN` status just to make the coordinator look complete.

## 7. Failure injection design

Failure injection lives in test doubles implementing the same production ports.

There is no production `debug_failure_mode` flag and no special AutoCAD command for Step37 testing.

The deterministic harness must support these injection points:

```text
AUTHORITY_BEFORE_ADMISSION
AFTER_ADMISSION_BEFORE_HOST_CALL
HOST_BEFORE_COMMIT
HOST_COMMIT_STATE_UNKNOWN
SCOPE_BREACH
VERIFY_FAILED
COMPENSATION_FAILED
```

Mapping:

- `AUTHORITY_BEFORE_ADMISSION` -> `AuthorityFailure` -> Step33 `FAILED_BEFORE_COMMIT`.
- `AFTER_ADMISSION_BEFORE_HOST_CALL` -> `HostFailed(BEFORE_COMMIT)` before mutation.
- `HOST_BEFORE_COMMIT` -> `HostFailed(BEFORE_COMMIT)` from the Host port.
- `HOST_COMMIT_STATE_UNKNOWN` -> `HostFailed(COMMIT_STATE_UNKNOWN)` -> no Step33 failure fabrication.
- `SCOPE_BREACH` -> real/synthetic provider-neutral `ActualDelta`, then a deterministic Step33 `ScopeComparisonResult(SCOPE_BREACH)`.
- `VERIFY_FAILED` -> committed `ActualDelta`, within-scope result, then deterministic Step33 failed verification evidence/result.
- `COMPENSATION_FAILED` -> Step33 compensation execution result with `succeeded=False`; no inverse Host command is generated by Step37.

## 8. Required Step37 proof scenarios

### Scenario A — two Host runtimes succeed

One Saga contains at least two Slices with different `HostRuntimeRef` values.

Expected:

```text
Slice A -> Host A -> SUCCEEDED
Slice B -> Host B -> SUCCEEDED
Saga -> SUCCEEDED
```

Assertions:

- each Host port is called exactly once for its own Slice;
- no Host receives the other Host's Slice;
- actual deltas join the exact authority and Host instance;
- execution follows Step33 canonical order.

### Scenario B — second Host fails before commit

```text
Slice A -> Host A -> committed/reconciled/SUCCEEDED
Slice B -> Host B -> BEFORE_COMMIT failure
Slice C -> never called
```

Expected durable truth:

```text
Slice A = SUCCEEDED
Slice B = FAILED_BEFORE_COMMIT
Slice C = BLOCKED
Saga    = PARTIALLY_COMMITTED
```

The failed Slice has no `actual_delta_hash`.

### Scenario C — first Host fails before any commit

```text
Slice A -> BEFORE_COMMIT failure
```

Expected:

```text
Slice A = FAILED_BEFORE_COMMIT
later   = BLOCKED
Saga    = FAILED
```

No compensation proposal is valid because there is no prior durable Host commit.

### Scenario D — second Host commits but breaches scope

```text
Slice A -> SUCCEEDED
Slice B -> HOST_COMMITTED
        -> SCOPE_BREACH
Slice C -> BLOCKED
```

Expected:

```text
Saga = PARTIALLY_COMMITTED
```

The compensation proposal must include durable commit evidence from the committed Slices. No inverse native command is inferred.

### Scenario E — second Host commits but semantic verification fails

```text
Slice A -> SUCCEEDED
Slice B -> HOST_COMMITTED
        -> WITHIN_SCOPE
        -> VERIFY_FAILED
Slice C -> BLOCKED
```

Expected:

```text
Saga = PARTIALLY_COMMITTED
```

The failed verification evidence is preserved and available to the compensation proposal.

### Scenario F — commit state is unknown

```text
Slice A -> SUCCEEDED
Slice B -> ADMITTED
        -> COMMIT_STATE_UNKNOWN
```

Expected:

```text
Coordinator = RECOVERY_REQUIRED
Slice B     = remains at last durable active state
Slice C     = NOT_STARTED but cannot be admitted
```

The Host command is not retried automatically.

A second coordinator run must detect the unresolved active Slice and return recovery-required again without calling the Host.

## 9. Compensation handoff

Step37 may expose a convenience method that delegates to Step33:

```python
create_compensation_proposal(
    source_saga_id,
    failed_slice_hash,
    desired_recovery_effects,
)
```

It must not execute recovery directly.

The proposal remains based on:

- committed Slice hashes;
- real `ActualDelta` hashes;
- verification failure refs;
- scope breach refs;
- caller-supplied canonical desired recovery effects.

A subsequent recovery execution is a new canonical request/change set and must return through the existing authority pipeline before any Host mutation.

Step37 tests must include an architecture assertion that the coordinator has no API accepting raw inverse Host commands.

## 10. Idempotency and restart behavior

Step37 relies on Step33 CAS and idempotent evidence recording.

Frozen rules:

- a completed `SUCCEEDED` Slice is never re-executed;
- a `FAILED_BEFORE_COMMIT`, `SCOPE_BREACH`, or `VERIFY_FAILED` Slice is never re-executed inside the same Saga;
- a `BLOCKED` Slice is never admitted;
- a Saga in `PARTIALLY_COMMITTED` does not resume normal forward execution;
- an unresolved active Slice after `COMMIT_STATE_UNKNOWN` is never re-executed automatically;
- CAS conflict from Step33 stops the coordinator and surfaces a coordination conflict instead of retrying mutation;
- replaying pure Step33 persistence with identical evidence may use Step33's existing idempotency, but replaying a Host mutation is not inferred safe merely because persistence is idempotent.

## 11. Data integrity checks performed by Step37

Before a Host call, Step37 must validate:

- Saga ChangeSet hash == supplied ChangeSet hash;
- Saga approved scope hash == supplied boundary hash;
- Saga execution plan hash == supplied execution plan hash;
- Slice hash is in the immutable Saga definition;
- exact Step30 Slice exists once;
- authority `execution_slice_hash` matches the Slice;
- authority ChangeSet/scope lineage matches the Saga;
- authority Host instance matches the Slice runtime ref;
- Host registry resolution is exact.

After a Host commit, Step33 remains responsible for validating `ActualDelta` integrity and authority lineage.

Step37 must not weaken or duplicate those checks with a second hashing implementation.

## 12. Package dependency direction

Allowed production dependencies for `design_execution_coordination`:

```text
design_approval_scope
design_changeset
design_execution_planning
design_gateway_authorization
design_execution_reconciliation
host_contracts / provider-neutral HostRuntimeRef contract
```

Forbidden production dependencies:

```text
hosts.autocad.*
AutoCAD .NET/native APIs
future hosts.revit.*
provider-specific native entity models
```

`design_execution_reconciliation` must not import the new Step37 package. Dependency direction is one-way: Step37 -> Step33.

## 13. Existing production code expected to remain unchanged

The first Step37 implementation should treat these as read-only unless a proven public-interface gap is found during TDD:

- `platform/execution_reconciliation` state semantics;
- Step31 provider binding production code;
- Step32 gateway authorization production code;
- AutoCAD plugin production code;
- AutoCAD sidecar production code.

If implementation appears to require changing Step33 failure meanings or adding native Host vocabulary to core, stop and return to design review.

## 14. Test strategy

### 14.1 Unit tests

Create focused tests for:

- exact Host routing;
- authority mismatch rejection;
- canonical Slice progression;
- coordination status projection;
- no retry after unknown commit state;
- active Slice restart detection.

### 14.2 Integration tests

Build one provider-neutral three-Slice Saga with at least two distinct `HostRuntimeRef` values and deterministic fake ports.

Use real Step33 store/service components rather than mocking the Saga state machine.

Inject each required failure and assert the exact persisted Step33 state.

### 14.3 Regression tests

Step37 must keep green:

- Step29 changeset tests;
- Step30 execution planning tests;
- Step31 provider binding tests;
- Step32 gateway authorization tests;
- all Step33 execution reconciliation tests;
- Step34 AutoCAD wall-thickness integration tests;
- Step36 AutoCAD OFFSET / CREATE / scope-breach tests;
- full repository importlib regression.

### 14.4 Architecture guard

Add a Step37 architecture test that proves:

- `design_execution_coordination` imports Step33, never the reverse;
- no AutoCAD/Revit native vocabulary appears in Step37 production code;
- failure injection helpers exist only under tests;
- no production failure-debug switch exists;
- no inverse Host command API exists in the coordinator;
- `COMMIT_STATE_UNKNOWN` cannot call `fail_slice_before_commit` in the coordinator path;
- two distinct Host runtime identities are exercised by the cross-host integration fixture.

## 15. Dedicated CI

Add a Step37 workflow covering paths for:

- the Step37 spec and plan;
- `platform/execution_coordination/**`;
- Step29–33 packages used by the coordinator;
- Host contract/runtime identity packages;
- Step37 tests;
- Step34/36 regression tests relevant to Host execution contracts.

The CI gate must run:

1. Step37 unit/integration/architecture tests;
2. Step29–33 regressions;
3. Step34/36 offline regressions;
4. full importlib suite;
5. Ruff no-new-diagnostics policy consistent with the current repository baseline;
6. `git diff --check main...HEAD`.

No live AutoCAD requirement is introduced by Step37 itself because Step37 does not modify AutoCAD production code.

If AutoCAD production code is later changed as part of Step37, the live acceptance gate must be reopened explicitly.

## 16. Non-goals

Step37 does not add:

- parallel Slice execution;
- distributed two-phase commit;
- global rollback transactions across Hosts;
- automatic Host retries after ambiguous failures;
- automatic inverse-command generation;
- a second real production Host implementation;
- Revit support;
- a new semantic identity protocol;
- new Step33 Saga statuses merely for coordinator convenience;
- provider-specific failure injection hooks in production Hosts;
- automatic execution of compensation outside Steps27–32 authority.

## 17. Completion gate

Step37 is complete only when all of the following are proven:

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
restart with unresolved active Slice does not re-execute Host mutation: PASS
compensation proposal derives only from durable Step33 evidence: PASS
coordinator never invents inverse Host commands: PASS
compensation is handed back to the governed canonical authority chain: PASS
Host-native vocabulary absent from Step37 production code: PASS
failure injection exists only in test doubles: PASS
Step33/34/36 regressions remain green: PASS
full offline regression/lint/diff gate: PASS
```

## 18. Design decision summary

Step37 is an execution coordinator, not a new reconciliation layer and not a distributed transaction manager.

Its core rule is:

> Progress only when the previous Slice has durable, reconciled success. When commit certainty is lost, stop. When a committed Slice fails scope or semantic verification, preserve the partial commit and require governed compensation. Never manufacture rollback truth.
