# Step37 Cross-Host Saga Failure Injection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a provider-neutral `ExecutionSagaCoordinator` that drives one immutable Step33 Saga across multiple Step30 `HostRuntimeRef` values, stops deterministically on failure, preserves partial-commit truth, and hands recovery back to governed compensation without inventing inverse Host commands.

**Architecture:** Create a new `design_execution_coordination` package above Step33. It owns only forward progression: create/load the Step33 Saga, follow Step33's immutable Slice order, obtain exact Step32 authority through a narrow port, route to the exact Host runtime, make one Host execution attempt, and delegate all durable commit/scope/verification/failure truth to Step33 public APIs. Failure injection exists only in test doubles implementing the same production ports.

**Tech Stack:** Python 3.11, dataclasses, `typing.Protocol`, pytest, existing DSP Steps 27–33 packages, Step33 `ExecutionReconciliationService`/`InMemoryExecutionSagaStore`, GitHub Actions, Ruff.

**Spec:** `docs/superpowers/specs/2026-08-31-step37-cross-host-saga-failure-injection-design.md` (user-approved on 2026-08-31; approved branch version includes the fail-closed active-Slice rule).

## Global Constraints

- Step37 executes Slices sequentially only. No parallel execution, distributed two-phase commit, or global rollback transaction.
- Step33 remains the sole source of Saga ids/hashes/revisions, Slice states, `BLOCKED`, `FAILED`, `PARTIALLY_COMMITTED`, scope/verification evidence, and compensation lifecycle.
- Dependency direction is one-way: `design_execution_coordination -> design_execution_reconciliation`; Step33 must never import Step37.
- Reuse `HostRuntimeRef` from `design_execution_planning`; do not create another runtime-identity type.
- Step37 production code must not import Host implementations or native vocabulary such as `Autodesk.AutoCAD`, `GetOffsetCurves`, `LWPOLYLINE`, Revit APIs, or provider-native entity types.
- Step37 does not implement Step31 binding or Step32 authorization policy. `ExecutionAuthorityPort` returns a real `AdmittedExecutionAuthority` or an explicit `AuthorityFailure`.
- D5 snapshot/projection construction stays outside Step37. `VerificationEvidencePort` returns provider-neutral `VerificationEvidenceBundle` values.
- Expected Host outcomes are the closed union `HostCommitted | HostFailed`; expected failures are values, not exceptions.
- Only `HostFailed(BEFORE_COMMIT)` may become Step33 `FAILED_BEFORE_COMMIT`.
- `HostFailed(COMMIT_STATE_UNKNOWN)` must not call `fail_slice_before_commit`, fabricate `ActualDelta`, retry Host mutation, or admit another Slice.
- Any active Slice (`ADMISSION_RESERVED`, `ADMITTED`, `HOST_COMMITTED`, `RECONCILING`) present at coordinator entry returns `RECOVERY_REQUIRED` with no authority/Host call and no automatic recovery.
- `SUCCEEDED`, `FAILED_BEFORE_COMMIT`, `SCOPE_BREACH`, `VERIFY_FAILED`, and `BLOCKED` Slices are never re-executed in the same Saga.
- A `PARTIALLY_COMMITTED` Saga never resumes normal forward execution.
- `COMPENSATING`, `COMPENSATED`, and `COMPENSATION_FAILED` are not forward-executable states; `execute()` fails closed with `CoordinationError("SAGA_NOT_FORWARD_EXECUTABLE", ...)` and makes no Host call.
- Step37 never infers inverse Host commands. Recovery derives from Step33 durable evidence plus caller-supplied canonical recovery effects and must re-enter Steps 27–32 before another Host mutation.
- Coordinator-created timestamps come only from injected `CoordinationClock`; production Step37 does not call wall-clock APIs.
- Failure injection helpers live only in `tests/`.
- Step31, Step32, Step33 state/failure production semantics and AutoCAD plugin/sidecar production code are read-only for this plan. A proven public-interface gap is a stop condition requiring design review.
- AutoCAD live acceptance is not required unless Step37 changes AutoCAD production code.
- Repository-wide Ruff remains baseline-aware; Step37-owned files themselves must have zero `E/F/I` diagnostics.

## File map

Production:

```text
platform/execution_coordination/pyproject.toml
platform/execution_coordination/src/design_execution_coordination/__init__.py
platform/execution_coordination/src/design_execution_coordination/contracts.py
platform/execution_coordination/src/design_execution_coordination/ports.py
platform/execution_coordination/src/design_execution_coordination/coordinator.py
pyproject.toml
```

Tests:

```text
tests/execution_coordination/conftest.py
tests/execution_coordination/test_step37_contracts.py
tests/execution_coordination/test_step37_fixture.py
tests/execution_coordination/test_step37_success.py
tests/execution_coordination/test_step37_precommit_failures.py
tests/execution_coordination/test_step37_postcommit_failures.py
tests/execution_coordination/test_step37_unknown_commit.py
tests/execution_coordination/test_step37_compensation.py
tests/integration/test_step37_architecture.py
```

CI:

```text
.github/workflows/step37-cross-host-saga-failure-injection.yml
```

---

### Task 1: Add Step37 immutable contracts and ports

**Files:**
- Create: `platform/execution_coordination/pyproject.toml`
- Create: `platform/execution_coordination/src/design_execution_coordination/contracts.py`
- Create: `platform/execution_coordination/src/design_execution_coordination/ports.py`
- Create: `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Modify: `pyproject.toml`
- Test: `tests/execution_coordination/test_step37_contracts.py`

**Interfaces:**
- Produces: `CoordinationError`, `CoordinationStatus`, `CoordinationResult`, `AuthorityFailure`, `HostFailurePhase`, `HostCommitted`, `HostFailed`, `HostExecutionResult`, `CoordinationClock`, `ExecutionAuthorityPort`, `HostExecutionPort`, `HostExecutionRegistry`, `VerificationEvidencePort`.

- [ ] **Step 1: Write the RED public API test**

```python
import pytest

from design_execution_coordination import (
    AuthorityFailure,
    CoordinationResult,
    CoordinationStatus,
    HostFailed,
    HostFailurePhase,
)


def test_step37_contracts_are_closed_and_validated():
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

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/execution_coordination/test_step37_contracts.py -q
```

Expected: import/collection failure because `design_execution_coordination` does not exist.

- [ ] **Step 3: Create package metadata and root import path**

`platform/execution_coordination/pyproject.toml`:

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

Add exactly this entry to root `[tool.pytest.ini_options].pythonpath`:

```toml
"platform/execution_coordination/src",
```

- [ ] **Step 4: Implement `contracts.py`**

Public shapes:

```python
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

Implement strict helpers in the Step33 contract style: non-empty text, optional text, lowercase SHA-256 for `active_slice_hash`, non-negative integer `saga_revision`, enum normalization. `HostCommitted.actual_delta` must be `ActualDelta`; timestamps are non-empty text.

- [ ] **Step 5: Implement `ports.py`**

```python
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

Imports must come only from provider-neutral Step28–33 packages. No port accepts raw Host commands/native ids/inverse commands.

- [ ] **Step 6: Export public API and run GREEN**

```bash
python -m pytest tests/execution_coordination/test_step37_contracts.py -q
python -c "import design_execution_coordination; print('design_execution_coordination OK')"
ruff check --select E,F,I platform/execution_coordination tests/execution_coordination/test_step37_contracts.py
```

Expected: PASS / import OK / zero Step37 diagnostics.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml platform/execution_coordination tests/execution_coordination/test_step37_contracts.py
git commit -m "feat: add Step37 coordination contracts"
```

---

### Task 2: Build the exact three-Slice Step29–33 test fixture

**Files:**
- Create: `tests/execution_coordination/conftest.py`
- Create: `tests/execution_coordination/test_step37_fixture.py`

**Interfaces:**
- Produces test-only `Step37Transaction`, three exact Step32 authorities, signed deltas/evidence, and deterministic authority/Host/evidence ports.

- [ ] **Step 1: Freeze the canonical test contract in `conftest.py`**

Use exactly:

```python
_SEMANTIC_ASSERTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "targets": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
        },
        "assertions": {"type": "object"},
    },
    "required": ["targets", "assertions"],
    "additionalProperties": False,
}

_SEMANTIC_ASSERTIONS_CONTRACT = {
    "type": "SEMANTIC_ASSERTIONS_V1",
    "version": "1.0.0",
    "assertions": [
        {
            "subjects": {"from_argument": "targets"},
            "path": "properties.thickness",
            "operator": "EQUALS_LITERAL",
            "value": 300.0,
        }
    ],
}

_SEMANTIC_ASSERTIONS_EFFECTS = (CanonicalAspect.PROPERTIES,)
```

Compute the contract definition fingerprint with `compute_contract_definition_fingerprint(...)`, then construct `CanonicalOperationContractEvidence(canonical_operation="semantic.assertions.v1", canonical_operation_version="1.0.0", argument_schema=..., effects=..., verification_contract=..., definition_fingerprint=...)`.

- [ ] **Step 2: Build the root bound evidence explicitly**

Construct `BoundOperationProposal` with:

```python
operation=CanonicalOperationRef("semantic.assertions.v1", "1.0.0")
arguments={
    "targets": ["WALL-001"],
    "assertions": {"properties.thickness": 300.0},
}
context_snapshot_ref=ContextSnapshotRef(
    "CS-STEP37",
    "context-hash-step37",
    "DOC-STEP37",
)
semantic_environment_ref="ENV-STEP37"
```

Use `SlotBindingEvidence` for `targets` as `CONTEXT` and `assertions` as `INTENT`. Build `BoundOperationEvidence` by computing both `compute_bound_operation_fingerprint(...)` and `compute_bound_operation_evidence_fingerprint(...)`; do not use hard-coded operation hashes.

- [ ] **Step 3: Build Step27 impact with exactly two derived targets**

Use one environment/planning/snapshot-set bound to `DOC-STEP37`. Freeze these edges:

```python
edges = (
    DependencyEdge(
        dependency_id="DEP-STEP37-B",
        source_semantic_id="WALL-001",
        target_semantic_id="ANNOTATION-002",
        strength=DependencyStrength.SOFT,
        propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
        propagation_action=PropagationAction.RECOMPUTE,
        rule_ref="RULE-STEP37-B",
    ),
    DependencyEdge(
        dependency_id="DEP-STEP37-C",
        source_semantic_id="WALL-001",
        target_semantic_id="TAG-003",
        strength=DependencyStrength.SOFT,
        propagation_owner=PropagationOwner.SEMANTIC_RUNTIME,
        propagation_action=PropagationAction.RECOMPUTE,
        rule_ref="RULE-STEP37-C",
    ),
)
```

Intent:

```python
IntentBoundary(
    direct_targets=("WALL-001",),
    allowed_canonical_effects=(CanonicalAspect.PROPERTIES.value,),
    allowed_derived_rule_refs=("RULE-STEP37-B", "RULE-STEP37-C"),
)
```

Call `ImpactAnalyzer().analyze(...)` with both edges. Require exactly two `propagation_bundles`, index them as:

```python
bundle_by_rule = {bundle.rule_ref: bundle for bundle in impact.propagation_bundles}
assert set(bundle_by_rule) == {"RULE-STEP37-B", "RULE-STEP37-C"}
```

- [ ] **Step 4: Materialize exactly two Step29 derived operations**

For each edge, create:

```python
bundle = bundle_by_rule[edge.rule_ref]
recipe = ScopeEffectRecipe(
    recipe_id=f"REC-{edge.dependency_id}",
    dependency_ref=edge.dependency_id,
    allowed_aspects=(CanonicalAspect.PROPERTIES,),
    rule_ref=edge.rule_ref,
    propagation_bundle_id=bundle.bundle_id,
)
derived_rule_id = recipe_existing_rule_id(recipe, edge.target_semantic_id)
materialization = DerivedOperationMaterialization(
    propagation_bundle_id=bundle.bundle_id,
    proposed_change_hash=compute_proposed_change_hash(bundle.proposed_changes[0]),
    canonical_operation="semantic.assertions.v1",
    canonical_operation_version="1.0.0",
    targets=(edge.target_semantic_id,),
    arguments={
        "targets": [edge.target_semantic_id],
        "assertions": {"properties.thickness": 300.0},
    },
    scope_rule_ids=(derived_rule_id,),
)
```

Build Step28 scope with one direct `PROPERTIES` rule for `WALL-001`, both recipes, and one `ExecutionSliceScopeRule("SLICE-SCOPE-STEP37", "DOC-STEP37", existing_rule_ids=(direct_rule_id, derived_rule_b, derived_rule_c))`.

Build `CanonicalChangeSet` with the exact canonical contract and both materializations, then bind its hash to the scope boundary.

- [ ] **Step 5: Produce three Step30 Slices from three exact runtime identities**

Route:

```python
routes = (
    RuntimeEntityRoute(
        "WALL-001",
        HostRuntimeRef("TEST_HOST", "HOST-STEP37-A", "DOC-STEP37"),
    ),
    RuntimeEntityRoute(
        "ANNOTATION-002",
        HostRuntimeRef("TEST_HOST", "HOST-STEP37-B", "DOC-STEP37"),
    ),
    RuntimeEntityRoute(
        "TAG-003",
        HostRuntimeRef("TEST_HOST", "HOST-STEP37-C", "DOC-STEP37"),
    ),
)
```

Compute `RuntimeRoutingEvidence` with `compute_routing_snapshot_hash(routes)` and run `ExecutionPlanner().plan(...)`. Require `len(execution_slices) == 3`.

- [ ] **Step 6: Write fixture characterization test**

```python
def test_step37_fixture_is_real_three_slice_cross_host_lineage(
    step37_three_slice_transaction,
):
    plan = step37_three_slice_transaction.execution_plan
    assert len(plan.execution_slices) == 3
    refs = tuple(slice_.host_runtime_ref for slice_ in plan.execution_slices)
    assert len(set(refs)) == 3
    assert {ref.host_instance_id for ref in refs} == {
        "HOST-STEP37-A",
        "HOST-STEP37-B",
        "HOST-STEP37-C",
    }
```

- [ ] **Step 7: Build real Step32 authority for every Slice**

For each Slice, construct a signed `ProviderBindingSet` using provider-neutral test values (`provider_server="step37.fixture.provider"`, `provider_tool="execute"`, `native_kind="TEST_ENTITY"`) and real `compute_host_binding_fingerprint`, `compute_binding_hash`, and `compute_binding_set_hash` functions. Then use a fresh `InMemoryGatewayAuthorizationStore` and:

```text
GatewayAuthorizationService.consume_approval
GatewayAuthorizationService.issue_execution_grant
GatewayAuthorizationService.admit_execution_grant
```

Return the real `AdmittedExecutionAuthority`. Assert its `execution_slice_hash`, `changeset_hash`, `approved_scope_hash`, and `host_instance_id` equal the Slice lineage.

- [ ] **Step 8: Add signed delta builders**

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

Normal success creates one `MODIFY` per target with `changed_aspects=(CanonicalAspect.PROPERTIES,)`. Scope-breach injection uses the same signed delta but `changed_aspects=(CanonicalAspect.GEOMETRY,)`.

- [ ] **Step 9: Add an exact signed verification-bundle builder**

For a Slice with one target `target` and a real delta, build:

```python
environment = SemanticEnvironmentRef(
    changeset.semantic_environment_ref.environment_id,
    changeset.semantic_environment_ref.content_hash,
)
projection = SemanticProjectionRef(
    projection_id=f"PROJ-STEP37-{authority.host_instance_id}",
    projection_hash=canonical_hash({"step37": "projection", "host": authority.host_instance_id}),
    semantic_model_version="step37-test",
    provider_set_hash=canonical_hash({"step37": "providers"}),
    mapping_profile_set_hash=canonical_hash({"step37": "mappings"}),
    normalized_fact_batch_hash=canonical_hash({"step37": "facts", "host": authority.host_instance_id}),
)
snapshot = SemanticSnapshot(
    snapshot_id=f"PS-STEP37-{authority.host_instance_id}",
    kind=SnapshotKind.PLANNING,
    project_id=changeset.project_id,
    freshness_contract_id="FC-STEP37",
    freshness_contract_hash=canonical_hash({"step37": "freshness"}),
    document_ref=delta.document_ref,
    base_host_revision=str(delta.revision_after),
    coverage=Coverage(delta.document_ref, (target,)),
    projection_ref=projection,
    semantic_environment_ref=environment,
    aspect_guarantees=(),
    hash=canonical_hash({"step37": "snapshot", "delta": delta.actual_delta_hash}),
)
subject = VerificationSubjectEvidence(
    semantic_id=target,
    canonical_kind="dsp:Step37TestEntity",
    properties={"thickness": property_value},
    placement=None,
    geometry_evidence=None,
    relationships=(),
    constraints=(),
    classification=(),
    evidence_aspects=(CanonicalAspect.PROPERTIES,),
    snapshot_id=snapshot.snapshot_id,
    snapshot_hash=snapshot.hash,
    projection_ref=projection,
)
draft = VerificationEvidenceBundle(
    evidence_bundle_id=f"VEB-STEP37-{authority.host_instance_id}",
    changeset_hash=changeset.changeset_hash,
    execution_slice_hash=authority.execution_slice_hash,
    actual_delta_hash=delta.actual_delta_hash,
    semantic_environment_ref=environment,
    post_execution_snapshot_ref=snapshot,
    post_execution_projection_ref=projection,
    base_host_revision=str(delta.revision_after),
    baseline_snapshot_ref=None,
    baseline_projection_ref=None,
    contract_evidence=(
        VerificationContractEvidence(
            contract_ref=canonical_hash(_SEMANTIC_ASSERTIONS_CONTRACT),
            contract_body=_SEMANTIC_ASSERTIONS_CONTRACT,
        ),
    ),
    subject_evidence=(subject,),
    baseline_subject_evidence=(),
    evidence_bundle_hash="0" * 64,
)
return replace(
    draft,
    evidence_bundle_hash=compute_verification_evidence_bundle_hash(draft),
)
```

`property_value=300.0` is the pass case; `301.0` is the real-verifier fail case.

- [ ] **Step 10: Add deterministic test-only ports**

Implement `FixedClock`, `DeterministicAuthorityPort`, `DeterministicHostPort`, `DeterministicHostRegistry`, and `DeterministicEvidencePort` with call logs. Each lookup is by exact `execution_slice_hash` or exact `HostRuntimeRef`. `DeterministicEvidencePort.build_bundle(...)` derives `target` from the sole execution unit/target in that Slice and calls the signed bundle builder with the configured property value.

- [ ] **Step 11: Run fixture gate and commit**

```bash
python -m pytest tests/execution_coordination/test_step37_fixture.py -q -vv
ruff check --select E,F,I tests/execution_coordination/conftest.py tests/execution_coordination/test_step37_fixture.py
git add tests/execution_coordination/conftest.py tests/execution_coordination/test_step37_fixture.py
git commit -m "test: add Step37 cross-host saga fixture"
```

Expected: three-Slice fixture PASS and zero diagnostics.

---

### Task 3: Add coordinator preflight, terminal projection, and active-Slice restart guard

**Files:**
- Create: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/__init__.py`
- Create: `tests/execution_coordination/test_step37_unknown_commit.py`

**Interfaces:**

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

- [ ] **Step 1: Write RED active-Slice restart test**

Use real Step33 to create a Saga, reserve the first Slice and confirm its real authority manually. Then call coordinator and assert `RECOVERY_REQUIRED`, exact active hash, and zero authority/Host calls from the coordinator.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/execution_coordination/test_step37_unknown_commit.py::test_active_slice_at_entry_requires_recovery_without_host_replay -q
```

Expected: import/name failure for `ExecutionSagaCoordinator`.

- [ ] **Step 3: Implement preflight**

Define:

```python
_ACTIVE = frozenset({
    SliceReconciliationStatus.ADMISSION_RESERVED,
    SliceReconciliationStatus.ADMITTED,
    SliceReconciliationStatus.HOST_COMMITTED,
    SliceReconciliationStatus.RECONCILING,
})
```

`execute()` first calls `reconciliation.create_saga(...)`, validates definition ChangeSet/scope/plan hashes against supplied artifacts, requires every `ordered_slice_hash` to resolve exactly once in `execution_plan.execution_slices`, then applies these no-I/O gates:

```text
SUCCEEDED -> CoordinationStatus.SUCCEEDED
FAILED -> CoordinationStatus.FAILED
PARTIALLY_COMMITTED -> CoordinationStatus.PARTIALLY_COMMITTED
COMPENSATING / COMPENSATED / COMPENSATION_FAILED -> CoordinationError(SAGA_NOT_FORWARD_EXECUTABLE)
any _ACTIVE Slice -> CoordinationStatus.RECOVERY_REQUIRED with active_slice_hash
```

- [ ] **Step 4: Prove terminal states never replay**

Use real Step33 failure methods to create `FAILED` and `PARTIALLY_COMMITTED` fixtures; call coordinator and assert no authority/Host calls.

- [ ] **Step 5: Run GREEN and commit**

```bash
python -m pytest tests/execution_coordination/test_step37_unknown_commit.py -q
ruff check --select E,F,I platform/execution_coordination tests/execution_coordination/test_step37_unknown_commit.py
git add platform/execution_coordination tests/execution_coordination/test_step37_unknown_commit.py
git commit -m "feat: guard Step37 saga restart state"
```

---

### Task 4: Implement exact authority/routing and full cross-host success

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Create: `tests/execution_coordination/test_step37_success.py`

- [ ] **Step 1: Write RED three-Host success test**

Configure every Slice with its real Step32 authority, exact Host registry entry, signed success `HostCommitted` delta, and `property_value=300.0` evidence. Assert final Step33 Saga/Slices are all `SUCCEEDED`, authority calls equal `ordered_slice_hashes`, registry resolutions equal the ordered Slices' exact `HostRuntimeRef` values, and each Host port is called exactly once for its own Slice/authority identity.

- [ ] **Step 2: Run RED**

```bash
python -m pytest tests/execution_coordination/test_step37_success.py -q -vv
```

Expected: FAIL at first unimplemented forward transition.

- [ ] **Step 3: Implement one forward Slice attempt**

For the first Step33-ordered `NOT_STARTED` Slice:

```text
reserve_slice_admission(clock.now())
authority_port.admit(slice)
validate authority
confirm_slice_admitted
host_registry.resolve(slice.host_runtime_ref)
host.execute(slice, authority) exactly once
```

Require authority equality for `execution_slice_hash`, `changeset_hash`, `approved_scope_hash`, and `host_instance_id`.

- [ ] **Step 4: Add a structurally valid authority mismatch test**

Do not mutate a real grant hash. Construct a new `AdmittedExecutionAuthority` using all fields from a real authority except:

```python
host_instance_id="HOST-STEP37-WRONG"
```

This remains structurally valid Step32 data but must be rejected by Step37 before Host routing. Because Host mutation has not started, call Step33 `fail_slice_before_commit(...)` with `clock.now()` and return `failure_ref="COORDINATION_AUTHORITY_MISMATCH"`. Assert failed Slice has no `actual_delta_hash` and Host call logs are empty.

- [ ] **Step 5: Implement committed reconciliation path**

For `HostCommitted`:

```text
record_host_commit(actual_delta, committed_at)
begin_reconciliation
compare_scope(ScopeComparisonRequest(authority, delta, boundary, slice))
record_scope_result
```

If within scope, resolve the one `SliceValidationAssignment` for the Slice, map its ids to exact `canonical_changeset.validation_tasks`, call `evidence_port.build_bundle(...)`, create `SemanticVerificationRequest(..., verified_at=clock.now())`, call `verify_semantics`, then `record_verification_result(..., reconciled_at=clock.now())`.

Step37 must not compute Step33 result hashes; Step33 does.

- [ ] **Step 6: Loop only after durable success**

After verification persistence, reload Step33. Continue only when current Slice is `SUCCEEDED`. Use `stored.definition.ordered_slice_hashes` on every iteration. Return `SUCCEEDED` only when Step33 Saga is `SUCCEEDED`.

- [ ] **Step 7: Run GREEN and commit**

```bash
python -m pytest tests/execution_coordination/test_step37_success.py tests/execution_coordination/test_step37_unknown_commit.py -q
ruff check --select E,F,I platform/execution_coordination tests/execution_coordination
git add platform/execution_coordination/src/design_execution_coordination/coordinator.py tests/execution_coordination/test_step37_success.py
git commit -m "feat: coordinate cross-host saga success"
```

---

### Task 5: Implement authority/Host pre-commit failure stop semantics

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Create: `tests/execution_coordination/test_step37_precommit_failures.py`

- [ ] **Step 1: RED first-Slice authority failure**

Return `AuthorityFailure("AUTH-DENIED-STEP37", "2026-08-31T12:01:00Z")`. Assert first Slice `FAILED_BEFORE_COMMIT`, both later Slices `BLOCKED`, Saga `FAILED`, no `ActualDelta`, no Host call.

- [ ] **Step 2: Implement AuthorityFailure branch**

After reservation, call Step33 `fail_slice_before_commit(...)` with the failure's `failed_at`, then project resulting Step33 status to `FAILED` or `PARTIALLY_COMMITTED`; return the supplied `failure_ref`.

- [ ] **Step 3: RED/implement Host BEFORE_COMMIT**

Return:

```python
HostFailed(
    phase=HostFailurePhase.BEFORE_COMMIT,
    failure_ref="HOST-PRECOMMIT-STEP37",
    failed_at="2026-08-31T12:02:00Z",
)
```

After real authority confirmation, call `fail_slice_before_commit`, stop, and never create/record an `ActualDelta`.

- [ ] **Step 4: Prove later failure preserves predecessor and blocks successor**

First Slice success, second `BEFORE_COMMIT`. Assert Slice0 `SUCCEEDED` with durable `actual_delta_hash`; Slice1 `FAILED_BEFORE_COMMIT` without delta; Slice2 `BLOCKED`; Saga `PARTIALLY_COMMITTED`; third Host never called.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest tests/execution_coordination/test_step37_precommit_failures.py -q
python -m pytest tests/execution_reconciliation/test_step33_failure_and_compensation.py -q
git add platform/execution_coordination/src/design_execution_coordination/coordinator.py tests/execution_coordination/test_step37_precommit_failures.py
git commit -m "feat: stop Step37 on precommit failures"
```

---

### Task 6: Implement post-commit scope/verification stop semantics

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Create: `tests/execution_coordination/test_step37_postcommit_failures.py`

- [ ] **Step 1: RED real scope breach after commit**

First Slice succeeds. Second returns a signed `HostCommitted` delta whose only `MODIFY` change has `changed_aspects=(CanonicalAspect.GEOMETRY,)` against the approved `PROPERTIES` rule. Assert second state `SCOPE_BREACH` with real `actual_delta_hash`, third `BLOCKED`, Saga `PARTIALLY_COMMITTED`, third Host never called.

- [ ] **Step 2: Stop after persisted scope breach**

After `record_scope_result`, if status is `SCOPE_BREACH`, return `CoordinationStatus.PARTIALLY_COMMITTED` with `failure_ref=scope_result.comparison_hash`. Do not call evidence port.

- [ ] **Step 3: RED real semantic verification failure**

First Slice succeeds. Second returns within-scope `PROPERTIES` delta. Configure evidence port with `property_value=301.0`; the real Step33 `SemanticVerifier` must return failed evidence against literal `300.0`. Assert second `VERIFY_FAILED` with persisted `verification_hash` and `actual_delta_hash`, third `BLOCKED`, Saga `PARTIALLY_COMMITTED`.

- [ ] **Step 4: Stop after failed/insufficient verification**

Persist the real verification result. If Step33 marks the Slice `VERIFY_FAILED`, return `PARTIALLY_COMMITTED` with `failure_ref=verification_result.verification_hash`. `EVIDENCE_INSUFFICIENT` is also non-progressable and is persisted through the same Step33 failure state.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest tests/execution_coordination/test_step37_postcommit_failures.py -q
python -m pytest tests/execution_reconciliation/test_step33_scope_existing.py tests/execution_reconciliation/test_step33_verifier.py -q
git add platform/execution_coordination/src/design_execution_coordination/coordinator.py tests/execution_coordination/test_step37_postcommit_failures.py
git commit -m "feat: stop Step37 after committed reconciliation failure"
```

---

### Task 7: Implement ambiguous commit fail-closed and restart no-replay

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Modify: `tests/execution_coordination/test_step37_unknown_commit.py`

- [ ] **Step 1: RED unknown commit**

First Slice succeeds; second returns:

```python
HostFailed(
    phase=HostFailurePhase.COMMIT_STATE_UNKNOWN,
    failure_ref="HOST-ACK-LOST-STEP37",
    failed_at="2026-08-31T12:03:00Z",
)
```

Assert `RECOVERY_REQUIRED`, active hash is second Slice, second state remains `ADMITTED`, no `actual_delta_hash`, third remains `NOT_STARTED`, and no Step33 failure state is fabricated.

- [ ] **Step 2: Implement exact branch**

Return:

```python
CoordinationResult(
    saga_id=stored.definition.saga_id,
    saga_revision=stored.saga_revision,
    status=CoordinationStatus.RECOVERY_REQUIRED,
    active_slice_hash=execution_slice.execution_slice_hash,
    failure_ref=host_result.failure_ref,
)
```

Do not call any Step33 mutation after the ambiguous Host result.

- [ ] **Step 3: Prove restart no-replay**

Call `execute(...)` again. The Task3 entry guard must fire before authority/Host. Assert second Host has exactly one historical call and authority port admitted second Slice exactly once.

- [ ] **Step 4: Run and commit**

```bash
python -m pytest tests/execution_coordination/test_step37_unknown_commit.py -q
git add platform/execution_coordination/src/design_execution_coordination/coordinator.py tests/execution_coordination/test_step37_unknown_commit.py
git commit -m "feat: fail closed on ambiguous Host commit"
```

---

### Task 8: Add governed compensation-proposal handoff

**Files:**
- Modify: `platform/execution_coordination/src/design_execution_coordination/coordinator.py`
- Create: `tests/execution_coordination/test_step37_compensation.py`

**Interface:**

```python
def create_compensation_proposal(
    self,
    *,
    source_saga_id: str,
    failed_slice_hash: str,
    desired_recovery_effects: tuple[Mapping[str, Any], ...],
) -> CompensationProposal: ...
```

- [ ] **Step 1: RED durable proposal test**

Drive a second-Slice scope breach, then call the method with one canonical recovery effect mapping. Assert `committed_slice_hashes`, `actual_delta_refs`, and `scope_breach_refs` equal durable Step33 state and no extra Host call occurs.

- [ ] **Step 2: Implement thin Step33 delegation**

```python
return self._reconciliation.create_compensation_proposal(
    CompensationProposalRequest(
        source_saga_id=source_saga_id,
        failed_slice_hash=failed_slice_hash,
        desired_recovery_effects=desired_recovery_effects,
    )
)
```

No Host/authority/evidence port call is allowed.

- [ ] **Step 3: Prove no-commit Saga cannot compensate**

Drive first-Slice pre-commit failure (`FAILED`) and assert Step33 rejects proposal creation with `ReconciliationError`/compensation conflict. Do not add a Step37 bypass.

- [ ] **Step 4: Prove compensation failure remains Step33 truth**

For a real partially committed Saga, call Step33 `begin_compensation(...)`, then:

```python
CompensationExecutionRef(
    compensation_proposal_hash=proposal.proposal_hash,
    compensating_changeset_hash="f" * 64,
    succeeded=False,
    completed_at="2026-08-31T12:30:00Z",
)
```

Persist through Step33 `record_compensation_result(...)` and assert source Saga `COMPENSATION_FAILED`. Coordinator exposes no inverse-command/recovery-execution method.

- [ ] **Step 5: Run and commit**

```bash
python -m pytest tests/execution_coordination/test_step37_compensation.py -q
python -m pytest tests/execution_reconciliation/test_step33_failure_and_compensation.py -q
git add platform/execution_coordination/src/design_execution_coordination/coordinator.py tests/execution_coordination/test_step37_compensation.py
git commit -m "feat: hand Step37 recovery to governed compensation"
```

---

### Task 9: Add architecture guard

**Files:**
- Create: `tests/integration/test_step37_architecture.py`

- [ ] **Step 1: Freeze dependency/native/failure boundaries**

Implement these source assertions:

```python
CORE = Path("platform/execution_coordination/src/design_execution_coordination")
STEP33 = Path("platform/execution_reconciliation/src/design_execution_reconciliation")


def _source(root):
    return "\n".join(path.read_text(encoding="utf-8") for path in root.glob("*.py"))


def test_step37_core_has_no_native_host_vocabulary():
    text = _source(CORE)
    for forbidden in (
        "Autodesk.AutoCAD",
        "GetOffsetCurves",
        "LWPOLYLINE",
        "Autodesk.Revit",
        "TransactionGroup",
    ):
        assert forbidden not in text


def test_step33_does_not_depend_on_step37():
    assert "design_execution_coordination" not in _source(STEP33)


def test_failure_injection_is_test_only():
    text = _source(CORE)
    assert "debug_failure_mode" not in text
    assert "failure_injection" not in text


def test_coordinator_has_no_inverse_host_command_api():
    params = inspect.signature(ExecutionSagaCoordinator.execute).parameters
    assert not {name for name in params if any(word in name for word in ("command", "inverse", "rollback"))}
```

- [ ] **Step 2: Add runtime unknown-commit safety assertion**

Use the real Task7 fixture plus a spy wrapper around `ExecutionReconciliationService.fail_slice_before_commit`; execute the `COMMIT_STATE_UNKNOWN` case and assert spy count remains zero. This runtime proof is required in addition to source scanning.

- [ ] **Step 3: Run architecture and strict Step37 lint**

```bash
python -m pytest tests/integration/test_step37_architecture.py -q -vv
ruff check --select E,F,I platform/execution_coordination tests/execution_coordination tests/integration/test_step37_architecture.py
```

Expected: PASS and zero diagnostics.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/test_step37_architecture.py
git commit -m "test: guard Step37 coordination architecture"
```

---

### Task 10: Add dedicated CI and run final offline gate

**Files:**
- Create: `.github/workflows/step37-cross-host-saga-failure-injection.yml`

- [ ] **Step 1: Add push/PR path triggers**

Cover exactly the Step37 workflow/spec/plan, `pyproject.toml`, `platform/execution_coordination/**`, Step29–33 packages, `tests/execution_coordination/**`, `tests/execution_reconciliation/**`, `tests/integration/test_step37_architecture.py`, and Step34/36 integration regression files. Do not add AutoCAD plugin/sidecar production paths unless those files actually change.

- [ ] **Step 2: Install offline packages**

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

- [ ] **Step 3: Add focused/upstream test commands**

```bash
python -m pytest tests/execution_coordination -q
python -m pytest tests/integration/test_step37_architecture.py -q
python -m pytest tests/changeset -q
python -m pytest tests/execution_planning -q
python -m pytest tests/provider_binding -q
python -m pytest tests/gateway_authorization -q
python -m pytest tests/execution_reconciliation -q
```

- [ ] **Step 4: Add Step34/36 offline regression**

```bash
python -m pytest \
  tests/integration/test_step34_autocad_wall_thickness_command.py \
  tests/integration/test_step34_autocad_wall_thickness_reconciliation.py \
  tests/integration/test_step36_offset_creation_authority.py \
  tests/integration/test_step36_autocad_offset_command.py \
  tests/integration/test_step36_architecture.py \
  -q
```

No `AGENT_HOST_TEST=1` in CI.

- [ ] **Step 5: Add full importlib regression**

```bash
python -m pytest --import-mode=importlib -q
```

- [ ] **Step 6: Add strict Step37 lint plus repository baseline-aware Ruff**

Strict:

```bash
ruff check --select E,F,I platform/execution_coordination tests/execution_coordination tests/integration/test_step37_architecture.py
```

Baseline-aware repository scan: create `/tmp/dsp-main` from `origin/main`, run identical JSON Ruff scans on `platform hosts/autocad/sidecar tests`, normalize filenames to repository-relative paths, compare `Counter[(filename, code, message)]`, print main/head/new counts, and fail if `head - main` is non-empty. Copy the already-green Step36 Counter algorithm rather than changing its semantics.

- [ ] **Step 7: Add whitespace/boundary checks**

```bash
git diff --check
git diff --check origin/main...HEAD
git log --oneline origin/main..HEAD
git diff --name-only origin/main...HEAD
```

- [ ] **Step 8: Run final local/offline gate before claiming completion**

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

Then run the same repository-wide baseline-aware Ruff comparison as CI.

- [ ] **Step 9: Enforce final branch boundary**

Allowed implementation diff:

```text
pyproject.toml
platform/execution_coordination/**
tests/execution_coordination/**
tests/integration/test_step37_architecture.py
.github/workflows/step37-cross-host-saga-failure-injection.yml
docs/superpowers/specs/2026-08-31-step37-cross-host-saga-failure-injection-design.md
docs/superpowers/plans/2026-08-31-step37-cross-host-saga-failure-injection.md
```

If Step31/32/33 or AutoCAD production files appear, stop and return to design review unless a previously proven public-interface gap explicitly requires the change.

- [ ] **Step 10: Commit CI**

```bash
git add .github/workflows/step37-cross-host-saga-failure-injection.yml
git commit -m "ci: verify Step37 cross-host saga coordination"
```

---

## Final completion gate

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

## Stop conditions

Stop implementation and return to design review if any of these becomes true:

- Step30 cannot create the exact three-Slice fixture without changing Step30 production semantics.
- Step33 public APIs cannot persist a frozen failure outcome without changing existing status meanings.
- Step32 authority cannot be supplied through the frozen port without embedding Gateway policy into Step37.
- Host adapters would need to expose native vocabulary to Step37 core.
- `COMMIT_STATE_UNKNOWN` appears to require a false Step33 terminal failure to make progress.
- Recovery appears to require an inverse native command or bypassing Steps 27–32.
- AutoCAD production changes become necessary only to prove provider-neutral Step37 behavior.
