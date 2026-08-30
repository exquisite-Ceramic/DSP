# Step 32 Gateway Authorization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Use strict TDD: write the focused RED test, run it and confirm the expected failure, implement the minimum GREEN change, rerun focused tests, then commit before moving to the next task.

**Goal:** Implement Step32 as the authoritative provider-neutral Gateway authorization boundary that converts one exact verified ApprovalAdmission into durable ApprovalRecord evidence and one exact approved ExecutionSlice + ProviderBindingSet into lineage-scoped ExecutionGrant authority, with explicit atomic state semantics and no Host mutation ownership.

**Architecture:** Step32 is a separate `design_gateway_authorization` package. It consumes public integrity validators owned by Steps 28–31, performs deterministic exact joins and least-privilege checks, computes Step32-only authorization hashes, and delegates all uniqueness/CAS/lineage atomicity to a provider-neutral `GatewayAuthorizationStore`. A transaction-faithful in-memory store is included for v1 tests. Step32 never reimplements upstream semantic hash bodies, never chooses providers, never emits HostCommand/ActualDelta, and never performs verification or compensation.

**Tech Stack:** Python 3.11, frozen dataclasses, `typing.Protocol`, `threading.RLock`, Step29 public `canonical_hash`, pytest, `ThreadPoolExecutor`, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-30-step32-gateway-authorization-design.md`

## Global Constraints

- Planning base: `feat/step32-gateway-authorization-design@f89f705456728bcf539ef1ec1bb33330febd4cb7`, whose merge-base is `main@0e567cc786ad88e99337f062c06222190e4c22d2`.
- Create implementation branch `feat/step32-gateway-authorization` from the approved design branch when execution begins.
- Distribution: `design-gateway-authorization`; source package: `design_gateway_authorization`.
- Keep the approved design document and this plan in the implementation branch.
- Step28 hash semantics MUST NOT change. Step28 changes are witness retention plus public validation only.
- Step29 ChangeSet hash semantics MUST NOT change. Step29 changes are public integrity reconstruction only.
- Step30 Unit/Slice hash semantics MUST NOT change. Step30 changes are public integrity validation only.
- Step31 production code MUST NOT change. Step32 must call existing `validate_provider_binding_set()`.
- Approval admission consumption is strict one-time: same id/same fingerprint is already-consumed; same id/different fingerprint is conflict.
- Grant issuance is idempotent by `(approval_hash, execution_slice_hash, binding_set_hash)`. A later retry `issued_at` never creates a second authority.
- Grant lineage lock key is `(approval_hash, execution_slice_hash)`, with at most one ACTIVE grant authority per lineage.
- An ADMITTED grant with a different BindingSet blocks transparent rebinding with `EXECUTION_GRANT_ALREADY_ADMITTED`.
- Immutable ApprovalRecord/ExecutionGrant bodies are separate from mutable lifecycle projections.
- Domain validation uses only explicit UTC times supplied in requests/calls; no `datetime.now()`, `time.time()`, or equivalent wall-clock reads.
- Store protocol owns atomicity, uniqueness, CAS, lineage serialization, and lifecycle persistence. Service owns validation, exact joins, least privilege, hashing, and error mapping.
- `InMemoryGatewayAuthorizationStore` must model transactional semantics with a single re-entrant lock around each atomic operation; it is not permission to weaken the protocol contract.
- Step32 MUST NOT import Host implementations, Host command dispatch, ActualDelta, Verify, ScopeComparator, Saga implementations, PostgreSQL, Redis, or DynamoDB clients.
- No production code may branch on AutoCAD/Revit/Tekla product names.

## Stable Step32 Error Codes

```text
APPROVAL_INPUT_INVALID
APPROVAL_INTEGRITY_INVALID
APPROVAL_ADMISSION_EXPIRED
APPROVAL_ADMISSION_ALREADY_CONSUMED
APPROVAL_ADMISSION_CONFLICT
APPROVAL_SCOPE_MISMATCH
SEMANTIC_ENVIRONMENT_MISMATCH
APPROVAL_OPERATION_FORBIDDEN
APPROVAL_RECORD_NOT_FOUND
APPROVAL_REVOKED

EXECUTION_GRANT_INPUT_INVALID
EXECUTION_GRANT_SLICE_MISMATCH
EXECUTION_GRANT_BINDING_MISMATCH
EXECUTION_GRANT_OPERATION_FORBIDDEN
EXECUTION_BINDING_EXPIRED
EXECUTION_GRANT_EXPIRED
EXECUTION_GRANT_REVOKED
EXECUTION_GRANT_ALREADY_ADMITTED
EXECUTION_GRANT_CONFLICT
```

Upstream integrity validators keep their own stable owner-specific codes. Step32 maps them to Step32 integrity/mismatch codes and preserves the upstream code as structured detail on `GatewayAuthorizationError`.

## File Map

### Targeted upstream production changes

- `platform/approval_scope/src/design_approval_scope/contracts.py`
- `platform/approval_scope/src/design_approval_scope/planner.py`
- `platform/approval_scope/src/design_approval_scope/hashing.py`
- `platform/approval_scope/src/design_approval_scope/__init__.py`
- `platform/changeset/src/design_changeset/integrity.py` — new
- `platform/changeset/src/design_changeset/__init__.py`
- `platform/execution_planning/src/design_execution_planning/integrity.py` — new
- `platform/execution_planning/src/design_execution_planning/__init__.py`

### Step32 production

- `platform/gateway_authorization/pyproject.toml`
- `platform/gateway_authorization/src/design_gateway_authorization/contracts.py`
- `platform/gateway_authorization/src/design_gateway_authorization/hashing.py`
- `platform/gateway_authorization/src/design_gateway_authorization/store.py`
- `platform/gateway_authorization/src/design_gateway_authorization/service.py`
- `platform/gateway_authorization/src/design_gateway_authorization/__init__.py`
- `pyproject.toml`

### Tests

- `tests/approval_scope/test_step28_integrity.py`
- `tests/changeset/test_step29_integrity.py`
- `tests/execution_planning/test_step30_integrity.py`
- `tests/gateway_authorization/conftest.py`
- `tests/gateway_authorization/test_step32_contracts.py`
- `tests/gateway_authorization/test_step32_hashing.py`
- `tests/gateway_authorization/test_step32_approval_service.py`
- `tests/gateway_authorization/test_step32_store_approval.py`
- `tests/gateway_authorization/test_step32_grant_service.py`
- `tests/gateway_authorization/test_step32_grant_lineage.py`
- `tests/gateway_authorization/test_step32_admission_and_revocation.py`
- `tests/gateway_authorization/test_step32_architecture.py`

### CI / docs

- `.github/workflows/step32-gateway-authorization.yml`
- `docs/superpowers/specs/2026-08-30-step32-gateway-authorization-design.md`
- `docs/superpowers/plans/2026-08-30-step32-gateway-authorization.md`

---

## Task 1: Make Step28 final scope evidence self-validating without changing its hashes

**Files:**
- Modify: `platform/approval_scope/src/design_approval_scope/contracts.py`
- Modify: `platform/approval_scope/src/design_approval_scope/planner.py`
- Modify: `platform/approval_scope/src/design_approval_scope/hashing.py`
- Modify: `platform/approval_scope/src/design_approval_scope/__init__.py`
- Create: `tests/approval_scope/test_step28_integrity.py`
- Update existing Step28 tests only where constructor shape changes require it.

### 1.1 RED: freeze witness retention and tamper detection

Create tests that first prove the missing capability:

```python
from dataclasses import replace

import pytest
from design_approval_scope import (
    ApprovalScopeError,
    bind_changeset,
    validate_approval_scope_boundary,
)


def test_final_boundary_retains_every_scope_body_commitment(step28_definition):
    boundary = bind_changeset(step28_definition, "a" * 64, "SCOPE-32")
    assert boundary.scope_definition_id == step28_definition.scope_definition_id
    assert boundary.impact_analysis_fingerprint == step28_definition.impact_analysis_fingerprint
    assert boundary.canonical_effect_evidence == step28_definition.canonical_effect_evidence
    assert boundary.intent_boundary == step28_definition.intent_boundary
    assert boundary.planning_snapshot_ref == step28_definition.planning_snapshot_ref
    assert boundary.snapshot_set_ref == step28_definition.snapshot_set_ref
    assert boundary.semantic_environment_ref == step28_definition.semantic_environment_ref


def test_boundary_rule_tamper_fails_integrity(step28_boundary):
    rule = step28_boundary.existing_entity_rules[0]
    tampered = replace(
        step28_boundary,
        existing_entity_rules=(replace(rule, allowed_aspects=("PLACEMENT",)),),
    )
    with pytest.raises(ApprovalScopeError) as exc:
        validate_approval_scope_boundary(tampered)
    assert exc.value.code == "SCOPE_INTEGRITY_INVALID"
```

Also cover tampering of planning snapshot, SnapshotSet, semantic environment, intent boundary, `changeset_hash`, and `scope_hash` while retaining the old digest.

Run:

```bash
pytest -q tests/approval_scope/test_step28_integrity.py
```

Expected RED: missing `intent_boundary` on `ApprovalScopeDefinition`/Boundary and missing `validate_approval_scope_boundary`.

### 1.2 GREEN: retain `intent_boundary` in Definition and full commitment witness in Boundary

Add the already-hashed `intent_boundary` to `ApprovalScopeDefinition`; this is necessary because the current planner passes it into `compute_scope_body_hash()` but drops it from the returned DTO.

```python
@dataclass(frozen=True, slots=True)
class ApprovalScopeDefinition:
    scope_definition_id: str
    impact_analysis_fingerprint: str
    canonical_effect_evidence: CanonicalEffectEvidence
    intent_boundary: Any
    planning_snapshot_ref: Any
    snapshot_set_ref: Any
    semantic_environment_ref: Any
    existing_entity_rules: tuple[ExistingEntityRule, ...]
    creation_rules: tuple[CreationRule, ...]
    deletion_rules: tuple[DeletionRule, ...]
    propagation_bundle_ids: tuple[str, ...]
    execution_slice_scope_rules: tuple[ExecutionSliceScopeRule, ...]
    scope_body_hash: str
```

Update `ApprovalScopePlanner.plan()` to pass `intent_boundary=intent` into the Definition constructor.

Expand Boundary with the carry-forward commitment fields frozen by the design. `bind_changeset()` copies those fields from the validated Definition without recomputing or altering any existing hash body.

### 1.3 GREEN: owner-side integrity validator

In `hashing.py` add:

```python
def validate_approval_scope_boundary(boundary: ApprovalScopeBoundary) -> None:
    expected_body = compute_scope_body_hash(
        impact_analysis_fingerprint=boundary.impact_analysis_fingerprint,
        canonical_effect_evidence=boundary.canonical_effect_evidence,
        intent_boundary=boundary.intent_boundary,
        planning_snapshot_ref=boundary.planning_snapshot_ref,
        snapshot_set_ref=boundary.snapshot_set_ref,
        semantic_environment_ref=boundary.semantic_environment_ref,
        existing_entity_rules=boundary.existing_entity_rules,
        creation_rules=boundary.creation_rules,
        deletion_rules=boundary.deletion_rules,
        propagation_bundle_ids=boundary.propagation_bundle_ids,
        execution_slice_scope_rules=boundary.execution_slice_scopes,
    )
    expected_scope = _sha256_json(
        {"scope_body_hash": expected_body, "changeset_hash": boundary.changeset_hash}
    )
    if expected_body != boundary.scope_body_hash or expected_scope != boundary.scope_hash:
        raise ApprovalScopeError("SCOPE_INTEGRITY_INVALID", "approval scope integrity mismatch")
```

Export it publicly.

### 1.4 Regression: prove hash algorithms did not change

Keep the old known semantic-equivalence tests and add a regression that constructs equivalent pre-enhancement material and asserts the exact same `scope_body_hash` and `scope_hash` formulas.

Run:

```bash
pytest -q tests/approval_scope
```

Expected GREEN: all Step28 tests pass.

### 1.5 Commit

```bash
git add platform/approval_scope tests/approval_scope
git commit -m "feat(step28): expose full scope integrity validation"
```

---

## Task 2: Add Step29 full CanonicalChangeSet integrity reconstruction

**Files:**
- Create: `platform/changeset/src/design_changeset/integrity.py`
- Modify: `platform/changeset/src/design_changeset/__init__.py`
- Create: `tests/changeset/test_step29_integrity.py`

### 2.1 RED: exact valid ChangeSet passes, material tampering fails

Reuse the real root+derived transaction builder already exercised in Step29 tests. Test root operation arguments, derived operation arguments, scope rule references, dependencies, preconditions, semantic impacts, validation tasks, and final `changeset_hash`.

```python
from dataclasses import replace

import pytest
from design_changeset import ChangeSetError, validate_changeset_integrity


def test_real_changeset_passes_full_integrity(changeset_and_boundary):
    changeset, boundary = changeset_and_boundary
    validate_changeset_integrity(changeset, boundary)


def test_root_operation_body_tamper_fails(changeset_and_boundary):
    changeset, boundary = changeset_and_boundary
    root = replace(changeset.root_operation, arguments={"targets": ["WALL-001"], "displacement": [999, 0, 0]})
    tampered = replace(changeset, root_operation=root)
    with pytest.raises(ChangeSetError) as exc:
        validate_changeset_integrity(tampered, boundary)
    assert exc.value.code == "CHANGESET_INTEGRITY_INVALID"
```

Run:

```bash
pytest -q tests/changeset/test_step29_integrity.py
```

Expected RED: public validator missing.

### 2.2 GREEN: reconstruct operation hashes from exact Boundary rules

Implement `integrity.py` using only Step29-owned public/internal hashing primitives. Do not import Step32.

Key helper:

```python
def _operation_hash(operation: CanonicalChangeOperation, rules_by_id) -> str:
    try:
        fingerprints = tuple(
            sorted(compute_scope_rule_fingerprint(rules_by_id[rule_id]) for rule_id in operation.scope_rule_ids)
        )
    except KeyError as exc:
        raise ChangeSetError(
            "CHANGESET_INTEGRITY_INVALID",
            f"unresolved Step28 scope rule: {exc.args[0]}",
        ) from exc
    return compute_operation_semantic_hash(
        origin=operation.origin,
        canonical_operation=operation.canonical_operation,
        canonical_operation_version=operation.canonical_operation_version,
        canonical_definition_fingerprint=operation.canonical_definition_fingerprint,
        targets=operation.targets,
        arguments=operation.arguments,
        expected_effects=operation.expected_effects,
        scope_rule_fingerprints=fingerprints,
        source_evidence=operation.source_evidence,
    )
```

Validate deterministic construction identities as integrity witnesses:

```python
if operation.operation_id != f"COP-{operation_hash[:12]}":
    _invalid("operation id does not match semantic operation hash")
```

Recreate the builder's exact dependency semantic payload by resolving predecessor/successor operation ids to their recomputed hashes; do not hash construction ids.

Recreate validation-task semantic payload with the same fields as the builder:

```python
{
    "kind": task.kind.value,
    "subject_semantic_ids": list(task.subject_semantic_ids),
    "canonical_operation_ref": task.canonical_operation_ref,
    "dependency_ref": task.dependency_ref,
    "contract_ref": task.contract_ref,
}
```

Then rebuild the exact current semantic body and call existing `compute_changeset_hash()`.

Before final hash comparison require:
- `changeset.changeset_hash == boundary.changeset_hash`;
- `changeset.approval_scope_definition_ref.scope_body_hash == boundary.scope_body_hash`;
- unique operation ids;
- every dependency references real operations;
- every operation scope rule exists in Boundary.

Export `validate_changeset_integrity` from `design_changeset.__init__`.

### 2.3 Run owner regressions

```bash
pytest -q tests/changeset
```

Expected GREEN: all Step29 tests pass and no existing ChangeSet hash changes.

### 2.4 Commit

```bash
git add platform/changeset tests/changeset
git commit -m "feat(step29): add canonical changeset integrity validator"
```

---

## Task 3: Add Step30 ExecutionUnit/ExecutionSlice integrity validation

**Files:**
- Create: `platform/execution_planning/src/design_execution_planning/integrity.py`
- Modify: `platform/execution_planning/src/design_execution_planning/__init__.py`
- Create: `tests/execution_planning/test_step30_integrity.py`

### 3.1 RED

Build a real ExecutionPlan through existing Step30 fixtures, select a Slice, and mutate Unit arguments without changing its old hash.

```python
from dataclasses import replace

import pytest
from design_execution_planning import ExecutionPlanningError, validate_execution_slice_integrity


def test_execution_unit_body_tamper_is_detected(real_execution_slice):
    unit = real_execution_slice.execution_units[0]
    bad = replace(unit, arguments={**dict(unit.arguments), "tampered": True})
    tampered_slice = replace(real_execution_slice, execution_units=(bad, *real_execution_slice.execution_units[1:]))
    with pytest.raises(ExecutionPlanningError) as exc:
        validate_execution_slice_integrity(tampered_slice)
    assert exc.value.code == "EXECUTION_UNIT_INTEGRITY_INVALID"
```

Also mutate Slice host instance, scope hash, and unit list with old `execution_slice_hash`.

Run:

```bash
pytest -q tests/execution_planning/test_step30_integrity.py
```

Expected RED: validator missing.

### 3.2 GREEN

Implement:

```python
def validate_execution_slice_integrity(execution_slice: ExecutionSlice) -> None:
    for unit in execution_slice.execution_units:
        expected = compute_execution_unit_hash(
            changeset_hash=execution_slice.changeset_hash,
            source_operation_hash=unit.source_operation_hash,
            canonical_operation=unit.canonical_operation,
            canonical_operation_version=unit.canonical_operation_version,
            canonical_definition_fingerprint=unit.canonical_definition_fingerprint,
            targets=unit.targets,
            arguments=unit.arguments,
            preconditions=unit.preconditions,
            expected_effects=unit.expected_effects,
        )
        if expected != unit.execution_unit_hash or unit.execution_unit_id != f"EU-{expected[:12]}":
            raise ExecutionPlanningError(
                "EXECUTION_UNIT_INTEGRITY_INVALID",
                "execution unit semantic identity mismatch",
            )

    expected_slice = compute_execution_slice_hash(
        changeset_hash=execution_slice.changeset_hash,
        scope_hash=execution_slice.approved_scope_ref.scope_hash,
        execution_slice_scope_rule_id=execution_slice.approved_scope_ref.execution_slice_scope_rule_id,
        host_runtime_ref=execution_slice.host_runtime_ref,
        execution_unit_hashes=(unit.execution_unit_hash for unit in execution_slice.execution_units),
    )
    if expected_slice != execution_slice.execution_slice_hash or execution_slice.execution_slice_id != f"XS-{expected_slice[:12]}":
        raise ExecutionPlanningError(
            "EXECUTION_SLICE_INTEGRITY_INVALID",
            "execution slice semantic identity mismatch",
        )
```

Export it publicly.

### 3.3 Regressions and commit

```bash
pytest -q tests/execution_planning
git add platform/execution_planning tests/execution_planning
git commit -m "feat(step30): add execution slice integrity validator"
```

---

## Task 4: Create Step32 package, immutable contracts, canonical hashes, and RED CI shell

**Files:**
- Create: `platform/gateway_authorization/pyproject.toml`
- Create: `platform/gateway_authorization/src/design_gateway_authorization/contracts.py`
- Create: `platform/gateway_authorization/src/design_gateway_authorization/hashing.py`
- Create: `platform/gateway_authorization/src/design_gateway_authorization/__init__.py`
- Modify: `pyproject.toml`
- Create: `tests/gateway_authorization/conftest.py`
- Create: `tests/gateway_authorization/test_step32_contracts.py`
- Create: `tests/gateway_authorization/test_step32_hashing.py`
- Create: `.github/workflows/step32-gateway-authorization.yml`

### 4.1 RED: package contract shape before package exists

Freeze exact dataclass field sets and immutability. Required public contracts:

```text
GatewayAuthorizationError
ApprovalState
GrantState
ApprovalAdmission
ApprovalConsumptionRequest
ApprovalRecord
ApprovalLifecycle
StoredApproval
ExecutionGrantRequest
ExecutionGrant
GrantLifecycle
StoredGrant
AdmittedExecutionAuthority
```

`StoredApproval` and `StoredGrant` are read-side state views pairing immutable evidence with lifecycle projection; callers never supply these as write authority.

Example test:

```python
from dataclasses import fields


def test_approval_record_separates_immutable_evidence_from_lifecycle():
    from design_gateway_authorization import ApprovalRecord
    assert {f.name for f in fields(ApprovalRecord)} == {
        "approval_id", "admission_id", "admission_fingerprint",
        "changeset_hash", "approved_scope_hash", "semantic_environment_ref",
        "approver", "policy_snapshot_hash", "allowed_operations",
        "approved_at", "consumed_at", "approval_hash",
    }
```

Run:

```bash
pytest -q tests/gateway_authorization/test_step32_contracts.py
```

Expected RED: `design_gateway_authorization` missing.

### 4.2 GREEN: package shell and common normalization

`platform/gateway_authorization/pyproject.toml`:

```toml
[project]
name = "design-gateway-authorization"
version = "0.1.0"
description = "Provider-neutral durable Gateway authorization contracts for DSP."
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Add these paths to root pytest configuration:

```toml
"platform/gateway_authorization/src",
"tests/gateway_authorization",
```

Use the same RFC3339 UTC normalization convention as Step31 contracts: accept `Z`/`+00:00`, reject naive/non-UTC values, normalize to `Z`.

`GatewayAuthorizationError` carries stable code plus structured upstream detail:

```python
class GatewayAuthorizationError(ValueError):
    def __init__(self, code: str, message: str, *, upstream_code: str | None = None) -> None:
        super().__init__(message)
        self.code = _text(code, "code")
        self.upstream_code = None if upstream_code is None else _text(upstream_code, "upstream_code")
```

Normalize operation tuples as unique sorted non-empty strings where authority requires at least one operation.

### 4.3 RED/GREEN: Step32-only hashes

Use public Step29 `canonical_hash` as the canonical byte-level primitive. Do not import any upstream private body helper.

```python
def compute_admission_fingerprint(admission: ApprovalAdmission) -> str:
    return canonical_hash({
        "changeset_hash": admission.changeset_hash,
        "approved_scope_hash": admission.approved_scope_hash,
        "semantic_environment_ref": admission.semantic_environment_ref,
        "approver": admission.approver,
        "policy_snapshot_hash": admission.policy_snapshot_hash,
        "policy_allowed_operations": sorted(admission.policy_allowed_operations),
        "approved_at": admission.approved_at,
        "expires_at": admission.expires_at,
    })
```

`compute_approval_hash()` includes only the frozen fields from the approved design; `approval_id`, `admission_id`, `consumed_at`, lifecycle state are absent from its signature/body.

`compute_grant_hash()` includes only:

```text
approval_hash
changeset_hash
approved_scope_hash
execution_slice_hash
binding_set_hash
host_instance_id
sorted(allowed_operations)
issued_at
expires_at
```

Hash tests must prove:
- mapping/order determinism;
- construction ids do not affect hashes;
- `consumed_at` does not affect approval hash;
- `approved_at` does affect approval hash;
- `issued_at` does affect a newly constructed grant hash;
- grant lifecycle does not affect grant hash.

Run:

```bash
pytest -q tests/gateway_authorization/test_step32_contracts.py tests/gateway_authorization/test_step32_hashing.py
```

### 4.4 Create workflow shell

The workflow path filter and PR boundary must include only the frozen implementation boundary. Initial focused steps may run Task 4 tests; later Task 10 expands the full verification matrix.

### 4.5 Commit

```bash
git add platform/gateway_authorization tests/gateway_authorization pyproject.toml .github/workflows/step32-gateway-authorization.yml
git commit -m "feat(step32): define gateway authorization contracts and hashes"
```

---

## Task 5: Implement deterministic ApprovalAdmission → ApprovalRecord service pipeline

**Files:**
- Create: `platform/gateway_authorization/src/design_gateway_authorization/service.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/__init__.py`
- Create: `tests/gateway_authorization/test_step32_approval_service.py`
- Extend: `tests/gateway_authorization/conftest.py`

### 5.1 RED: fixed validation order and exact joins

Use a spy store with only `consume_admission_once()` and record whether it was called. Build real Step28/29 evidence; do not use fake hashes for integrity tests.

Cover:
- admission fingerprint mismatch;
- `consumed_at >= expires_at`;
- Step28 integrity failure;
- Step29 integrity failure;
- three-way changeset mismatch;
- scope-body mismatch;
- approved scope mismatch;
- SemanticEnvironment mismatch;
- operation outside policy;
- exact least-privilege `allowed_operations`;
- `approved_at` copied from Admission and `consumed_at` retained separately;
- no store write occurs before all validation succeeds.

Example:

```python
def test_approval_allowed_operations_are_exact_changeset_operations(valid_approval_request, spy_store):
    service = GatewayAuthorizationService(spy_store)
    record = service.consume_approval(valid_approval_request)
    expected = {
        valid_approval_request.canonical_changeset.root_operation.canonical_operation,
        *(op.canonical_operation for op in valid_approval_request.canonical_changeset.derived_operations),
    }
    assert set(record.allowed_operations) == expected
    assert set(record.allowed_operations) <= set(valid_approval_request.admission.policy_allowed_operations)
```

Run:

```bash
pytest -q tests/gateway_authorization/test_step32_approval_service.py
```

Expected RED: service missing.

### 5.2 GREEN: implement the normative order

`GatewayAuthorizationService.consume_approval()` must execute exactly:

```python
def consume_approval(self, request: ApprovalConsumptionRequest) -> ApprovalRecord:
    self._require_approval_request(request)
    self._validate_admission_fingerprint(request.admission)
    self._validate_admission_expiry(request.admission, request.consumed_at)
    self._validate_scope_integrity(request.approval_scope_boundary)
    self._validate_changeset_integrity(
        request.canonical_changeset,
        request.approval_scope_boundary,
    )
    self._validate_approval_join(request)
    allowed_operations = self._least_privilege_operations(request)
    record = self._build_approval_record(request, allowed_operations)
    return self._store.consume_admission_once(
        request.admission.admission_id,
        request.admission.admission_fingerprint,
        record,
    )
```

When Step28/29 validators raise owner-specific errors, map to `APPROVAL_INTEGRITY_INVALID` and preserve `exc.code` as `upstream_code`.

Use deterministic construction id:

```python
approval_id = f"AR-{approval_hash[:12]}"
```

### 5.3 Verify and commit

```bash
pytest -q tests/gateway_authorization/test_step32_approval_service.py
pytest -q tests/approval_scope tests/changeset
git add platform/gateway_authorization tests/gateway_authorization
git commit -m "feat(step32): validate approval admission deterministically"
```

---

## Task 6: Define transactional Store protocol and atomic approval consumption

**Files:**
- Create: `platform/gateway_authorization/src/design_gateway_authorization/store.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/__init__.py`
- Create: `tests/gateway_authorization/test_step32_store_approval.py`

### 6.1 RED: freeze protocol semantics through observable behavior

Tests must prove:
- first consume persists `StoredApproval(record, ACTIVE lifecycle)`;
- same admission id + same fingerprint raises `APPROVAL_ADMISSION_ALREADY_CONSUMED`;
- same admission id + different fingerprint raises `APPROVAL_ADMISSION_CONFLICT`;
- 20+ concurrent consumes of one Admission result in exactly one durable ApprovalRecord;
- `get_approval(approval_id)` returns authoritative record+lifecycle;
- missing approval returns no state to store-level caller; service maps it later;
- no externally observable half-consumed state.

Concurrency example:

```python
from concurrent.futures import ThreadPoolExecutor


def test_same_admission_concurrency_creates_one_record(store, approval_record):
    def consume():
        try:
            return store.consume_admission_once(
                approval_record.admission_id,
                approval_record.admission_fingerprint,
                approval_record,
            )
        except GatewayAuthorizationError as exc:
            return exc.code

    with ThreadPoolExecutor(max_workers=16) as pool:
        results = list(pool.map(lambda _: consume(), range(32)))

    successes = [item for item in results if isinstance(item, ApprovalRecord)]
    assert len(successes) == 1
    assert results.count("APPROVAL_ADMISSION_ALREADY_CONSUMED") == 31
```

### 6.2 GREEN: protocol plus `RLock` in-memory reference implementation

Protocol shape:

```python
class GatewayAuthorizationStore(Protocol):
    def consume_admission_once(
        self,
        admission_id: str,
        admission_fingerprint: str,
        approval_record: ApprovalRecord,
    ) -> ApprovalRecord: ...

    def get_approval(self, approval_id: str) -> StoredApproval | None: ...
    def revoke_approval(self, approval_id: str, revoked_at: str, reason: str) -> StoredApproval: ...
    def issue_or_get_grant(self, grant: ExecutionGrant) -> ExecutionGrant: ...
    def get_grant(self, grant_hash: str) -> StoredGrant | None: ...
    def admit_grant(self, grant_hash: str, admitted_at: str) -> AdmittedExecutionAuthority: ...
    def revoke_grant(self, grant_hash: str, revoked_at: str, reason: str) -> StoredGrant: ...
```

In-memory state includes:

```python
self._lock = threading.RLock()
self._consumptions: dict[str, tuple[str, str]] = {}
self._approvals: dict[str, StoredApproval] = {}
self._grants: dict[str, StoredGrant] = {}
self._lineages: dict[tuple[str, str], list[str]] = {}
```

`consume_admission_once()` performs conflict/replay detection and both persistence updates while holding the same lock. There is no pre-write in the service.

### 6.3 Atomic failure boundary test

Use a test-only protocol implementation that raises before commit to prove `GatewayAuthorizationService` itself has not marked anything consumed. Keep failure injection out of production store APIs.

### 6.4 Verify and commit

```bash
pytest -q tests/gateway_authorization/test_step32_store_approval.py tests/gateway_authorization/test_step32_approval_service.py
git add platform/gateway_authorization tests/gateway_authorization
git commit -m "feat(step32): add atomic gateway authorization store"
```

---

## Task 7: Implement authoritative ExecutionGrant validation and issuance candidate construction

**Files:**
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/service.py`
- Extend: `tests/gateway_authorization/conftest.py`
- Create: `tests/gateway_authorization/test_step32_grant_service.py`

### 7.1 Build one real cross-step fixture

The gateway fixture must assemble:

```text
real Step29 CanonicalChangeSet
+ real Step28 validated Boundary
→ real Step30 ExecutionPlan/Slice
→ real Step31 ProviderResolver/ProviderBindingSet
→ real Step32 ApprovalRecord in Store
```

Reuse existing test helper logic rather than inventing a fake BindingSet. The fixture should make it easy to produce a second Step31 BindingSet for the same Slice by changing selected provider material/expiry while keeping Step29/30 identity unchanged.

### 7.2 RED: grant pipeline

Cover:
- unknown approval id → `APPROVAL_RECORD_NOT_FOUND`;
- revoked approval → `APPROVAL_REVOKED`;
- Step30 integrity failure → `EXECUTION_GRANT_SLICE_MISMATCH` with upstream detail;
- Slice changeset mismatch;
- Slice scope mismatch;
- Step31 binding-set validator failure → `EXECUTION_GRANT_BINDING_MISMATCH`;
- BindingSet exact Slice mismatch;
- host instance inconsistency across bindings/Slice;
- Slice operation not allowed by ApprovalRecord;
- `issued_at >= any binding_expires_at` → `EXECUTION_BINDING_EXPIRED`;
- `expires_at == min(binding_expires_at)`;
- exact Slice operation set becomes Grant `allowed_operations`;
- deterministic `grant_hash` and `EG-<prefix>` construction id.

Run:

```bash
pytest -q tests/gateway_authorization/test_step32_grant_service.py
```

Expected RED: issuance not implemented.

### 7.3 GREEN: authoritative lookup and upstream validators

Implementation skeleton:

```python
def issue_execution_grant(self, request: ExecutionGrantRequest) -> ExecutionGrant:
    self._require_grant_request(request)
    stored = self._store.get_approval(request.approval_id)
    if stored is None:
        self._error("APPROVAL_RECORD_NOT_FOUND", "approval record not found")
    if stored.lifecycle.state is ApprovalState.REVOKED:
        self._error("APPROVAL_REVOKED", "approval is revoked")

    self._validate_slice_integrity(request.execution_slice)
    self._validate_slice_approval_join(stored.record, request.execution_slice)
    self._validate_binding_set(request.provider_binding_set, request.execution_slice)
    self._validate_host_consistency(request.execution_slice, request.provider_binding_set)
    operations = self._validate_grant_operations(stored.record, request.execution_slice)
    expires_at = self._derive_grant_expiry(request.provider_binding_set, request.issued_at)
    grant = self._build_grant(stored.record, request, operations, expires_at)
    return self._store.issue_or_get_grant(grant)
```

Step32 calls only:

```python
validate_execution_slice_integrity(execution_slice)
validate_provider_binding_set(binding_set, execution_slice)
```

It must not call Step30/31 private helpers to reconstruct those objects.

### 7.4 Verify and commit

```bash
pytest -q tests/gateway_authorization/test_step32_grant_service.py
pytest -q tests/execution_planning tests/provider_binding
git add platform/gateway_authorization tests/gateway_authorization
git commit -m "feat(step32): issue exact execution grants"
```

---

## Task 8: Implement Grant lineage locking, provider-switch semantics, and issuance idempotency

**Files:**
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/store.py`
- Create: `tests/gateway_authorization/test_step32_grant_lineage.py`

### 8.1 RED: full state table

Freeze the design state table as tests:

```text
ACTIVE + same binding_set_hash      -> existing Grant unchanged
ACTIVE + different binding_set_hash -> old REVOKED/superseded; new ACTIVE
ADMITTED + same binding_set_hash    -> same Grant
ADMITTED + different binding_set_hash -> EXECUTION_GRANT_ALREADY_ADMITTED
REVOKED + same binding_set_hash     -> EXECUTION_GRANT_REVOKED
REVOKED + different binding_set_hash -> new Grant allowed
EXPIRED + same binding_set_hash     -> EXECUTION_GRANT_EXPIRED
EXPIRED + fresh different binding_set_hash -> new Grant allowed
```

Also prove same binding retry with a later `issued_at` returns the original Grant exactly:

```python
assert retried.grant_hash == original.grant_hash
assert retried.issued_at == original.issued_at
assert retried.expires_at == original.expires_at
```

Concurrency test: 32 requests for the same lineage/binding identity create exactly one grant hash.

### 8.2 GREEN: serialize by lineage under one atomic store operation

Under `RLock`:
1. derive lineage `(grant.approval_hash, grant.execution_slice_hash)`;
2. inspect existing grants in that lineage using effective lifecycle (including derived expiry);
3. apply the exact state table;
4. only after final decision mutate old lifecycle and/or insert new grant;
5. maintain `superseded_by_grant_id` for old ACTIVE provider-switch state.

Do not use `(approval_hash, slice_hash, binding_set_hash)` as the only uniqueness lock; it is only the issuance idempotency identity inside the broader lineage lock.

### 8.3 Commit

```bash
pytest -q tests/gateway_authorization/test_step32_grant_lineage.py tests/gateway_authorization/test_step32_grant_service.py
git add platform/gateway_authorization tests/gateway_authorization
git commit -m "feat(step32): enforce grant lineage authority"
```

---

## Task 9: Implement grant CAS admission, approval/grant revocation, and Step33 handoff

**Files:**
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/store.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/service.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/__init__.py`
- Create: `tests/gateway_authorization/test_step32_admission_and_revocation.py`

### 9.1 RED: CAS admission and idempotent same-grant recovery

Cover:
- ACTIVE + valid parent + `admitted_at < expires_at` → ADMITTED;
- same already-ADMITTED grant_hash returns identical logical `AdmittedExecutionAuthority`;
- expired grant at `admitted_at` → `EXECUTION_GRANT_EXPIRED`;
- revoked grant → `EXECUTION_GRANT_REVOKED`;
- parent approval revoked before admit → `APPROVAL_REVOKED`;
- concurrent admit calls produce one lifecycle transition and the same logical handoff evidence.

The handoff contract must exactly include:

```python
@dataclass(frozen=True, slots=True)
class AdmittedExecutionAuthority:
    approval_hash: str
    grant_hash: str
    changeset_hash: str
    approved_scope_hash: str
    execution_slice_hash: str
    binding_set_hash: str
    host_instance_id: str
    admitted_at: str
```

### 9.2 GREEN: atomic `admit_grant()`

Within the store lock:
- load exact grant by `grant_hash`;
- load parent ApprovalLifecycle;
- project expiry using explicit `admitted_at`;
- if ACTIVE and valid, persist ADMITTED once;
- if same grant already ADMITTED, return handoff with original stored `admitted_at` so recovery never invents a second logical execution start.

### 9.3 RED/GREEN: revoke/admit transaction ordering

Sequential tests prove both defined orders:

```text
revoke commit first -> later admit fails
admit commit first -> later revoke preserves ADMITTED evidence and records cancellation/revocation projection
```

A small barrier-based concurrency test may assert that whichever atomic store operation acquires the lock first determines the result; do not assert a scheduler-specific winner.

### 9.4 RED/GREEN: approval revocation cascade

`revoke_approval()` atomically:
- changes ApprovalLifecycle ACTIVE→REVOKED;
- changes all ACTIVE child Grants to REVOKED;
- preserves immutable ADMITTED evidence while recording child revocation/cancellation projection;
- makes future issue/admit fail `APPROVAL_REVOKED`.

`revoke_grant()`:
- ACTIVE→REVOKED;
- ADMITTED records REVOKED projection without erasing `admitted_at`;
- repeated same revoke is idempotent if reason/time are identical; conflicting repeated lifecycle write returns `EXECUTION_GRANT_CONFLICT`.

### 9.5 Verify and commit

```bash
pytest -q tests/gateway_authorization/test_step32_admission_and_revocation.py tests/gateway_authorization/test_step32_grant_lineage.py

git add platform/gateway_authorization tests/gateway_authorization
git commit -m "feat(step32): add grant admission and revocation lifecycle"
```

---

## Task 10: Add architecture guards, finalize CI, run all regressions, and mark implementation status only after proof

**Files:**
- Create: `tests/gateway_authorization/test_step32_architecture.py`
- Modify: `.github/workflows/step32-gateway-authorization.yml`
- Modify: `docs/superpowers/specs/2026-08-30-step32-gateway-authorization-design.md` only after all verification commands are green.

### 10.1 RED: architecture guards

Use AST checks modeled on Step31 architecture tests. Production Step32 must have no imports/names/constants for:

```text
AutoCAD / AUTOCAD
autocad_sidecar
Revit / REVIT
Tekla / TEKLA
HostCommand
ActualDelta
ScopeComparator
Saga
psycopg / asyncpg
redis
boto3 / DynamoDB
```

Also reject direct wall-clock calls:

```text
datetime.now
datetime.utcnow
time.time
```

Add source-level guard that Step32 service imports the four public validators:

```text
validate_approval_scope_boundary
validate_changeset_integrity
validate_execution_slice_integrity
validate_provider_binding_set
```

and does not import these upstream private helpers/modules for integrity reconstruction:

```text
design_approval_scope.hashing._*
design_changeset.builder._*
design_execution_planning.planner._*
design_provider_binding.hashing._*
```

### 10.2 Finalize workflow PR boundary

Workflow path boundary must allow exactly:

```text
.github/workflows/step32-gateway-authorization.yml
docs/superpowers/specs/2026-08-30-step32-gateway-authorization-design.md
docs/superpowers/plans/2026-08-30-step32-gateway-authorization.md
platform/gateway_authorization/**
tests/gateway_authorization/**
platform/approval_scope/**
tests/approval_scope/**
platform/changeset/**
tests/changeset/**
platform/execution_planning/**
tests/execution_planning/**
pyproject.toml
```

The workflow must install the same repository verification stack as Step31 plus `-e platform/gateway_authorization`, then run:

```bash
pytest -q tests/approval_scope/test_step28_integrity.py
pytest -q tests/changeset/test_step29_integrity.py
pytest -q tests/execution_planning/test_step30_integrity.py
pytest -q tests/gateway_authorization
pytest -q tests/approval_scope
pytest -q tests/changeset
pytest -q tests/execution_planning
pytest -q tests/provider_binding
ruff check \
  platform/approval_scope/src/design_approval_scope \
  platform/changeset/src/design_changeset \
  platform/execution_planning/src/design_execution_planning \
  platform/gateway_authorization/src/design_gateway_authorization \
  tests/approval_scope tests/changeset tests/execution_planning tests/gateway_authorization
pytest -q --import-mode=importlib
```

### 10.3 Verify diff boundary before claiming completion

Run:

```bash
git diff --name-only <implementation-base>...HEAD
```

Every changed path must match the frozen boundary above. No Step31 production file may appear.

### 10.4 Fresh full verification

Run every command below in the same final verification session and inspect exit status/output:

```bash
pytest -q tests/approval_scope
pytest -q tests/changeset
pytest -q tests/execution_planning
pytest -q tests/provider_binding
pytest -q tests/gateway_authorization
ruff check \
  platform/approval_scope/src/design_approval_scope \
  platform/changeset/src/design_changeset \
  platform/execution_planning/src/design_execution_planning \
  platform/gateway_authorization/src/design_gateway_authorization \
  tests/approval_scope tests/changeset tests/execution_planning tests/gateway_authorization
pytest -q --import-mode=importlib
```

Do not mark the design Implemented if any command fails.

### 10.5 Only after all green: update implementation status

Change design header from:

```text
Status: Design frozen; implementation not started
```

to a factual implemented/verified status that includes the final implementation commit SHA and verification commands actually run.

### 10.6 Final commit

```bash
git add .github/workflows/step32-gateway-authorization.yml \
  tests/gateway_authorization/test_step32_architecture.py \
  docs/superpowers/specs/2026-08-30-step32-gateway-authorization-design.md

git commit -m "test(step32): enforce gateway authorization architecture"
```

---

## Implementation Review Checkpoints

After each task:

1. Show the RED failure from the focused new test before production implementation.
2. Show the focused GREEN result after the minimum implementation.
3. Run the owner regression suite for any upstream package changed in that task.
4. Inspect `git diff --stat` and `git diff --check`.
5. Commit only the task boundary; do not accumulate unrelated changes.

At Tasks 6, 8, and 9 specifically, review concurrency semantics rather than only final values:
- all relevant mutations occur under the same store atomic operation;
- no service-side check-then-write sequence substitutes for store atomicity;
- lineage inspection and supersede/create occur under one lock/transaction;
- admit/revoke state changes are compare-and-swap equivalent;
- retry results return the already-committed immutable evidence rather than reconstructing authority with a later timestamp.

## Definition of Done

Step32 is complete only when fresh evidence proves all of the following:

```text
Step28 Boundary can validate its complete current semantic commitment
Step29 ChangeSet can validate its complete current semantic commitment
Step30 Unit/Slice can validate its complete current semantic commitment
Step31 validator is consumed unchanged

one admission_id -> at most one ApprovalRecord
same admission id + different content -> conflict
approval allowed_operations -> exact ChangeSet operations

one approval_hash + execution_slice_hash -> at most one ACTIVE Grant authority
same binding retry -> same committed Grant
provider switch while ACTIVE -> old authority invalidated atomically
provider switch after ADMITTED -> blocked
revoked identical Grant -> never resurrected

one Grant -> at most one logical Slice admission
approval revoke -> prevents new issue/admit and revokes ACTIVE children
ADMITTED evidence -> never erased by revoke

Step32 has no Host/product/database-vendor execution coupling
no upstream semantic hash algorithm changed
all Step28–31 regressions pass
all Step32 tests pass
Ruff passes
full repository tests pass
```
