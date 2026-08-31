# Step37 Cross-Host Saga Failure Injection Design

**Status:** FROZEN DESIGN CANDIDATE — pending user review

**Base:** `main` at `2b114462c9932d478f752564c0449224125ed58f` (Step36 merged)

**Goal:** Add a provider-neutral execution coordinator above Step33 that drives one immutable Saga across multiple `HostRuntimeRef` values, stops deterministically on failure, preserves durable partial-commit truth, and exposes compensation evidence without inventing inverse Host commands.

## 1. Current facts

Step33 already owns durable Saga truth: immutable `ExecutionSagaDefinition`, canonical Slice order/dependencies, CAS revisions, per-Slice lifecycle, failure-to-`BLOCKED` propagation, `FAILED` versus `PARTIALLY_COMMITTED`, scope/verification persistence, and compensation evidence/lifecycle.

Step36 proved a real AutoCAD Host can produce a governed `ActualDelta` that Step33 reconciles. Step37 therefore adds only the missing runtime coordinator across multiple Host-bound Slices.

`HostRuntimeRef` is the provider-neutral Step30 contract from `design_execution_planning`; Step37 reuses it exactly.

## 2. Chosen architecture

Create:

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

Step33 remains source of truth for Saga ids/hashes/revisions, Slice statuses, `BLOCKED`, `PARTIALLY_COMMITTED`, scope/verification results, and compensation state.

Step37 owns only forward progression: select the next Step33-ordered Slice, obtain exact Step32 authority through a port, route to the exact Host, make one execution attempt, classify commit certainty, invoke Step33 public transitions, and stop when forward execution is unsafe.

Step37 does not implement Step31 ProviderBinding or Step32 GatewayAuthorization rules.

Step37 production code must not import Host implementations or contain native mechanisms such as `Autodesk.AutoCAD`, `GetOffsetCurves`, `LWPOLYLINE`, Revit transaction APIs, or provider-specific entity vocabulary.

D5 semantic evidence remains external. A provider-neutral evidence port supplies `VerificationEvidenceBundle` values; Step37 does not understand projection/storage internals.

Compensation remains governed. Step37 never infers inverse Host commands. Recovery starts from Step33 durable evidence plus caller-supplied canonical recovery effects and must re-enter the existing canonical authority chain before a Host mutation.

## 4. Frozen provider-neutral interfaces

```python
class CoordinationStatus(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    RECOVERY_REQUIRED = "RECOVERY_REQUIRED"

@dataclass(frozen=True, slots=True)
class CoordinationResult:
    saga_id: str
    saga_revision: int
    status: CoordinationStatus
    active_slice_hash: str | None
    failure_ref: str | None
```

`RECOVERY_REQUIRED` means Step37 cannot safely continue without authoritative recovery of external facts. It is not projected into a fabricated Step33 terminal status.

```python
class CoordinationClock(Protocol):
    def now(self) -> str: ...
```

Coordinator-generated timestamps come from this injected clock; Step37 does not call wall-clock APIs directly.

```python
@dataclass(frozen=True, slots=True)
class AuthorityFailure:
    failure_ref: str
    failed_at: str

class ExecutionAuthorityPort(Protocol):
    def admit(
        self,
        execution_slice: ExecutionSlice,
    ) -> AdmittedExecutionAuthority | AuthorityFailure: ...
```

An authority failure is confirmed pre-Host. A returned authority must match the exact Slice hash, ChangeSet hash, approved scope hash, and Slice `host_runtime_ref.host_instance_id`. Any mismatch stops before Host execution.

```python
class HostFailurePhase(str, Enum):
    BEFORE_COMMIT = "BEFORE_COMMIT"
    COMMIT_STATE_UNKNOWN = "COMMIT_STATE_UNKNOWN"

@dataclass(frozen=True, slots=True)
class HostCommitted:
    actual_delta: ActualDelta
    committed_at: str

@dataclass(frozen=True, slots=True)
class HostFailed:
    phase: HostFailurePhase
    failure_ref: str
    failed_at: str

HostExecutionResult = HostCommitted | HostFailed

class HostExecutionPort(Protocol):
    def execute(
        self,
        execution_slice: ExecutionSlice,
        authority: AdmittedExecutionAuthority,
    ) -> HostExecutionResult: ...
```

Step37 needs only commit certainty; native adapters may retain richer native errors internally.

```python
class HostExecutionRegistry(Protocol):
    def resolve(self, runtime_ref: HostRuntimeRef) -> HostExecutionPort: ...
```

No fallback between Host instances is allowed.

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

## 5. Coordinator entry point

The coordinator is constructed with:

```text
ExecutionReconciliationService
ExecutionAuthorityPort
HostExecutionRegistry
VerificationEvidencePort
CoordinationClock
```

`ExecutionSagaCoordinator.execute(...)` receives the exact `CanonicalChangeSet`, `ApprovalScopeBoundary`, and `ExecutionPlan`, then creates or idempotently loads the Step33 Saga. It does not accept raw Host commands, native entity ids, inverse commands, or caller-supplied Slice ordering.

## 6. Deterministic forward algorithm

1. Create/load Step33 Saga from exact Step29/28/30 lineage.
2. Read `definition.ordered_slice_hashes` from Step33.
3. If Saga is `SUCCEEDED`, `FAILED`, or `PARTIALLY_COMMITTED`, return the corresponding coordination result without Host calls.
4. If any Slice is already active (`ADMISSION_RESERVED`, `ADMITTED`, `HOST_COMMITTED`, or `RECONCILING`) at coordinator entry, return `RECOVERY_REQUIRED` without any Host call or automatic recovery attempt. Recovery of an incomplete active Slice is outside the Step37 MVP forward executor.
5. Resolve the next Slice by exact hash from Step30.
6. Call Step33 `reserve_slice_admission(...)` using CAS and the injected clock.
7. Call `ExecutionAuthorityPort.admit(...)`.
8. On `AuthorityFailure`, call Step33 `fail_slice_before_commit(...)` and stop.
9. Validate authority lineage/Host instance and call Step33 `confirm_slice_admitted(...)`.
10. Resolve the exact Host through `HostExecutionRegistry` and call `execute(...)` exactly once.
11. On `HostFailed(BEFORE_COMMIT)`, call Step33 `fail_slice_before_commit(...)` and stop.
12. On `HostFailed(COMMIT_STATE_UNKNOWN)`, do not record false failure, do not fabricate `ActualDelta`, do not retry, do not advance; return `RECOVERY_REQUIRED`.
13. On `HostCommitted`, record the real `ActualDelta` in Step33.
14. Call Step33 `begin_reconciliation(...)`.
15. Build/run/persist `ScopeComparisonRequest` using the exact authority, delta, boundary and Slice.
16. On `SCOPE_BREACH`, stop; Step33 owns `PARTIALLY_COMMITTED` and later `BLOCKED` states.
17. Obtain provider-neutral verification evidence from `VerificationEvidencePort`.
18. Resolve exactly the validation task ids assigned by the immutable Saga definition.
19. Build/run/persist `SemanticVerificationRequest`.
20. On failed/insufficient verification, stop; Step33 owns `VERIFY_FAILED`, `PARTIALLY_COMMITTED`, and later `BLOCKED` states.
21. On Slice success, continue with the next Step33-ordered Slice.
22. When all Slices succeed, return `SUCCEEDED`.

The coordinator never computes a different order and never bypasses Step33 CAS.

## 7. Commit-state uncertainty rule

`COMMIT_STATE_UNKNOWN` is fail-closed. If the Host may have committed but Step37 lacks trustworthy commit evidence, Step37 must not mark `FAILED_BEFORE_COMMIT`, create a fake/empty `ActualDelta`, retry the Host command, advance another Slice, or generate compensation as though commit evidence were known.

The Slice remains at its last durable active Step33 state, normally `ADMITTED`. Existing Step33 one-active-Slice rules block further admission. A later coordinator run sees that active Slice and again returns `RECOVERY_REQUIRED` without replaying the Host mutation.

Step37 does not add a convenience Step33 `UNKNOWN` status that would misstate model truth.

## 8. Failure injection

Failure injection exists only in deterministic test doubles implementing the same production ports. No production Host gets a Step37 debug command or failure flag.

Required cases:

```text
AUTHORITY_BEFORE_ADMISSION
HOST_BEFORE_COMMIT
HOST_COMMIT_STATE_UNKNOWN
SCOPE_BREACH
VERIFY_FAILED
COMPENSATION_FAILED
```

Mappings:

- authority failure -> Step33 `FAILED_BEFORE_COMMIT`;
- confirmed Host pre-commit failure -> Step33 `FAILED_BEFORE_COMMIT`;
- unknown commit state -> coordinator `RECOVERY_REQUIRED`, no fabricated Step33 failure;
- scope breach after committed provider-neutral evidence -> Step33 `SCOPE_BREACH`;
- failed verification after committed within-scope evidence -> Step33 `VERIFY_FAILED`;
- compensation result with `succeeded=False` -> existing Step33 `COMPENSATION_FAILED`.

## 9. Required proof scenarios

### Two Host runtimes succeed

One Saga contains at least two distinct `HostRuntimeRef` values. Each Host is called exactly once for its own Slice; no Host receives another Host's Slice; Saga ends `SUCCEEDED`.

### Later Host fails before commit

```text
Slice A = SUCCEEDED
Slice B = FAILED_BEFORE_COMMIT
Slice C = BLOCKED
Saga    = PARTIALLY_COMMITTED
```

Slice B has no `actual_delta_hash`.

### First Slice fails before any commit

```text
Slice A = FAILED_BEFORE_COMMIT
later   = BLOCKED
Saga    = FAILED
```

No Step33 compensation proposal is valid because the Saga is not partially committed.

### Later Host commits then breaches scope

```text
Slice A = SUCCEEDED
Slice B = SCOPE_BREACH with real ActualDelta evidence
later   = BLOCKED
Saga    = PARTIALLY_COMMITTED
```

### Later Host commits then fails verification

```text
Slice A = SUCCEEDED
Slice B = VERIFY_FAILED with real ActualDelta + scope evidence
later   = BLOCKED
Saga    = PARTIALLY_COMMITTED
```

### Host commit state is unknown

```text
Coordinator = RECOVERY_REQUIRED
active Slice remains at last durable Step33 state
later Slices are not admitted
Host is not retried on coordinator restart
```

## 10. Compensation handoff

Step37 may delegate creation of a Step33 `CompensationProposal`, but does not execute recovery directly. The proposal derives only from committed Slice hashes, real `ActualDelta` hashes, verification/scope failure refs, and caller-supplied canonical recovery effects.

Step37 has no API that accepts or generates an inverse Host command. Recovery execution is outside normal forward execution of the failed Saga and must re-enter the existing canonical authority pipeline before any Host mutation.

## 11. Idempotency and restart rules

- `SUCCEEDED` Slices are never re-executed.
- `FAILED_BEFORE_COMMIT`, `SCOPE_BREACH`, `VERIFY_FAILED`, and `BLOCKED` Slices are never re-executed in the same Saga.
- `PARTIALLY_COMMITTED` Sagas never resume ordinary forward execution.
- unresolved active Slices are not automatically replayed or recovered by Step37 MVP.
- Step33 CAS conflicts stop coordination; Step37 does not retry a mutation to resolve persistence races.
- Step33 idempotent persistence never implies Host mutation replay is safe.

## 12. Integrity before Host mutation

Step37 validates:

- Saga ChangeSet hash == supplied ChangeSet hash;
- Saga approved scope hash == supplied boundary hash;
- Saga execution plan hash == supplied execution plan hash;
- Slice hash appears exactly once in Step30 and belongs to the immutable Saga definition;
- authority Slice hash, ChangeSet hash, approved scope hash, and Host instance all join exactly;
- Host registry resolution matches the exact Step30 `HostRuntimeRef`.

After commit, Step33 remains responsible for `ActualDelta` integrity/lineage. Step37 does not implement a second hashing scheme.

## 13. Dependency direction

Allowed Step37 production dependencies:

```text
design_approval_scope
design_changeset
design_execution_planning  # includes HostRuntimeRef
design_gateway_authorization
design_execution_reconciliation
```

Forbidden:

```text
hosts.autocad.*
future hosts.revit.*
AutoCAD/Revit native APIs
provider-specific native entity models
```

`design_execution_reconciliation` must not import `design_execution_coordination`; direction is Step37 -> Step33 only.

## 14. Expected read-only production boundaries

Step37 MVP treats Step33 state/failure semantics, Step31 ProviderBinding, Step32 GatewayAuthorization, AutoCAD plugin, and AutoCAD sidecar as read-only unless TDD proves a genuine public-interface gap. If implementation appears to require changing Step33 failure meanings or inserting native vocabulary into Step37 core, stop and return to design review.

## 15. Test strategy

Unit tests cover exact Host routing, authority mismatch rejection, Step33-only ordering, injected clock behavior, and unresolved-active-Slice restart behavior.

Integration tests use a provider-neutral three-Slice fixture with at least two distinct `HostRuntimeRef` values, real Step33 service/store components, and deterministic fake authority/Host/evidence ports. Every required failure case asserts exact persisted Step33 state.

Architecture tests prove Step37 imports Step33 but never the reverse, Host-native vocabulary is absent, failure injection helpers live only under tests, no production failure switch exists, no inverse Host command API exists, unknown commit state cannot call `fail_slice_before_commit`, and two Host runtime identities are exercised.

Regression must keep Step29–33, Step34 offline, Step36 offline, and full importlib tests green.

## 16. Dedicated CI

Add a Step37 workflow covering the Step37 spec/plan, `platform/execution_coordination/**`, Step29–33 dependencies, Step37 tests, and Step34/36 execution-contract regressions.

Required gate:

1. Step37 unit/integration/architecture tests;
2. Step29–33 regressions;
3. Step34/36 offline regressions;
4. full importlib regression;
5. Ruff no-new-diagnostics policy against current `main` baseline;
6. `git diff --check main...HEAD`.

Step37 adds no live AutoCAD requirement because MVP does not change AutoCAD production code. Any later AutoCAD production change reopens live acceptance explicitly.

## 17. Non-goals

Step37 does not add parallel Slice execution, distributed two-phase commit, global rollback transactions, automatic retries after ambiguous Host failures, automatic inverse-command generation, a second real production Host, Revit support, new semantic identity protocols, new Step33 statuses for convenience, provider-specific production failure injection, or compensation Host execution outside Steps27–32 authority.

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
