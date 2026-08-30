# Step 33 Execution Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use strict TDD: write the focused RED test, run it and confirm the expected failure, implement the minimum GREEN change, rerun focused tests and relevant owner regressions, inspect the diff, then commit before moving to the next task.

**Goal:** Implement Step33 as the provider-neutral post-execution reconciliation boundary that turns admitted Slice authority + authoritative Host read-back into deterministic scope comparison, independently proves semantic results from pinned evidence, and durably coordinates cross-Host partial-failure recovery through a sequential Saga without XA/2PC or hidden native undo.

**Architecture:** Add one `design_execution_reconciliation` package. `ActualDelta` is the authoritative normalized side-effect fact; `ScopeComparator` evaluates it only against the exact Step28 Boundary/Slice scope; `SemanticVerifier` evaluates exact Step29 ValidationTasks only after scope passes and only over snapshot-bound evidence; `ExecutionSaga` records immutable plan lineage plus durable CAS lifecycle state. Step33 consumes public Step28–32 validators/contracts, never reimplements their hash bodies, never queries D5 internals, and never branches on Host product. The only upstream production enhancement is Step30 public `validate_execution_plan_integrity()` using the already-frozen plan hash.

**Tech Stack:** Python 3.11, frozen dataclasses, enums, `typing.Protocol`, `threading.RLock`, Step29 public `canonical_hash`, public Step28/29/30/32 contracts, public `semantic_runtime` snapshot refs, public `host_contracts.HostEntityRef`, pytest, `ThreadPoolExecutor`, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md`

## Global Constraints

- Planning branch: `feat/step33-execution-reconciliation`; approved design HEAD before this plan is `d8493b0dee8389f1be76bc568526831ac3f94ef5`, with merge-base exactly `main@cef76e111f74d10f063eedfebc7efc0d805caefa`.
- Keep implementation on `feat/step33-execution-reconciliation` unless the human explicitly requests a new branch.
- Distribution: `design-execution-reconciliation`; source package: `design_execution_reconciliation`.
- Existing Step28–32 semantic hash algorithms MUST NOT change.
- Step28, Step29, Step31, Step32 production code MUST NOT change absent a newly surfaced and explicitly approved blocker.
- Step30 production changes are limited to public `validate_execution_plan_integrity()` and export wiring; `ExecutionPlan`, Unit/Slice contracts, planner behavior, and existing hashes remain unchanged.
- Step33 Core MUST NOT import Host implementations, Host command dispatch, provider implementations, D5 projection-storage internals, or database-vendor clients.
- No Step33 production branch may depend on AutoCAD/Revit/Tekla product names, native categories/layers, native transaction APIs, `UNDO`, or provider-specific verification logic.
- Domain logic MUST NOT read wall clock time. All audit times are explicit UTC inputs.
- `HostCommandResult.status == OK` and Host self-reported `verification` data never produce semantic PASS by themselves.
- Scope comparison MUST precede semantic verification for a committed Slice. A persisted `SCOPE_BREACH` is authoritative and cannot be downgraded by later verification.
- v0.6 allows at most one active side-effecting Slice across the whole Saga. Independent roots still use one deterministic global topological/hash order.
- Compensation is a new governed write workflow. Step33 may seal recovery intent/evidence, but never emit a Host rollback command and never reuse the original ExecutionGrant as compensation authority.
- Store protocol owns atomicity/CAS/idempotency. Service/domain logic owns validation, exact joins, deterministic hashes, transition legality, and stable error mapping.
- The in-memory store is a transaction-faithful reference implementation using one `RLock` around each mutating operation; it is not permission to weaken persistent-store semantics.

## Execution-Approval Refinements Discovered During Planning

The written design already froze the relevant behavior, but implementation decomposition exposed three missing Step33-only evidence fields. These MUST be synchronized into the design spec in Task 1 before production code begins. User approval of this implementation plan is also approval of these narrow refinements; none modifies Step28–32 contracts/hashes.

1. `ActualChange.source_canonical_kind?` is required so a `CreationRule.source_selector` using Step28 `PredicateField.CANONICAL_KIND` can be evaluated without D5 lookup.
2. `DELTA_EQUALS_ARGUMENT` requires task-scoped pre-write evidence. `VerificationEvidenceBundle` therefore adds `baseline_snapshot_ref?`, `baseline_projection_ref?`, and `baseline_subject_evidence[]`; `VerificationSubjectEvidence` adds `snapshot_id` + `snapshot_hash` so both baseline and post evidence are explicitly snapshot-bound.
3. `SemanticVerificationRequest` adds the exact `approval_scope_boundary` and `actual_delta`. Current public `validate_changeset_integrity(changeset, boundary)` requires the Boundary, and exact post-revision verification requires the authoritative ActualDelta rather than only its hash.

Baseline rules are fail-closed:

```text
DELTA_EQUALS_ARGUMENT present
→ baseline snapshot/evidence required
→ baseline snapshot identity == CanonicalChangeSet.planning_snapshot_ref
→ same SemanticEnvironment
→ required baseline subject/path present
otherwise EVIDENCE_INSUFFICIENT / REQUIRED_BASELINE_MISSING
```

No unit conversion belongs in Step33. Verification evidence and canonical operation arguments must already be expressed in canonical semantic units. If an assertion supplies a tolerance unit, explicit observed/expected units must agree; otherwise evidence is insufficient.

## Stable Step33 Top-Level Error Codes

```text
ACTUAL_DELTA_INPUT_INVALID
ACTUAL_DELTA_INTEGRITY_INVALID
RECONCILIATION_LINEAGE_MISMATCH
RECONCILIATION_REVISION_INVALID

SCOPE_COMPARISON_INVALID
SCOPE_BREACH

VERIFY_INPUT_INVALID
VERIFY_CONTRACT_MISMATCH
VERIFY_CONTRACT_UNSUPPORTED
VERIFY_EVIDENCE_INSUFFICIENT
VERIFY_FAILED

SAGA_INPUT_INVALID
SAGA_INTEGRITY_INVALID
SAGA_TRANSITION_INVALID
SAGA_CONFLICT
SAGA_PREDECESSOR_NOT_SUCCEEDED
SAGA_ALREADY_TERMINAL

COMPENSATION_CONFLICT
```

Structured detail codes include at minimum:

```text
ENTITY_OUTSIDE_SCOPE
ASPECT_OUTSIDE_SCOPE
CREATION_OPERATION_FORBIDDEN
CREATION_KIND_FORBIDDEN
CREATION_SOURCE_FORBIDDEN
CREATION_DERIVATION_MISMATCH
CREATION_COUNT_EXCEEDED
DELETION_FORBIDDEN
LINEAGE_MISMATCH
EXPECTED_VALUE_MISMATCH
REQUIRED_FIELD_MISSING
REQUIRED_BASELINE_MISSING
```

Natural-language messages never drive retry/replan/compensation decisions.

## File Map

### Targeted upstream production changes

- `platform/execution_planning/src/design_execution_planning/integrity.py`
- `platform/execution_planning/src/design_execution_planning/__init__.py`

### Step33 production

- `platform/execution_reconciliation/pyproject.toml`
- `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- `platform/execution_reconciliation/src/design_execution_reconciliation/scope_comparator.py`
- `platform/execution_reconciliation/src/design_execution_reconciliation/verifier.py`
- `platform/execution_reconciliation/src/design_execution_reconciliation/saga.py`
- `platform/execution_reconciliation/src/design_execution_reconciliation/store.py`
- `platform/execution_reconciliation/src/design_execution_reconciliation/service.py`

### Tests / repo wiring

- `tests/execution_planning/test_step30_integrity.py`
- `tests/execution_reconciliation/conftest.py`
- `tests/execution_reconciliation/test_step33_actual_delta.py`
- `tests/execution_reconciliation/test_step33_scope_existing.py`
- `tests/execution_reconciliation/test_step33_scope_existence.py`
- `tests/execution_reconciliation/test_step33_verification_evidence.py`
- `tests/execution_reconciliation/test_step33_verifier.py`
- `tests/execution_reconciliation/test_step33_saga_definition.py`
- `tests/execution_reconciliation/test_step33_saga_store.py`
- `tests/execution_reconciliation/test_step33_failure_and_compensation.py`
- `tests/execution_reconciliation/test_step33_service.py`
- `tests/execution_reconciliation/test_step33_architecture.py`
- `pyproject.toml`
- `.github/workflows/step33-execution-reconciliation.yml`
- `docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md`

---

## Task 1: Synchronize executable evidence refinements into the approved design spec

**Files:**
- Modify: `docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md`

- [ ] **1.1 Update the written-spec status and exact Step33-only refinements**

Change the header to factual planning state, for example:

```text
Status: Written spec approved; implementation plan approved; implementation not started
```

Add `source_canonical_kind?` to `ActualChange`, and explicitly map creation-source selector fields:

```text
CreationRule.source_selector candidate context
SEMANTIC_ID      -> ActualChange.source_semantic_id
CANONICAL_KIND   -> ActualChange.source_canonical_kind
SOURCE_ENTITY    -> ActualChange.source_semantic_id
DERIVATION_RULE  -> ActualChange.derivation_rule
```

This mapping is provider-neutral read-model semantics. Missing evidence means the selector does not match; it is never backfilled from Host metadata.

- [ ] **1.2 Add baseline evidence for `DELTA_EQUALS_ARGUMENT`**

Amend the bundle shape:

```text
VerificationEvidenceBundle {
  ...
  post_execution_snapshot_ref
  post_execution_projection_ref
  base_host_revision

  baseline_snapshot_ref?
  baseline_projection_ref?

  contract_evidence[]
  subject_evidence[]
  baseline_subject_evidence[]
  evidence_bundle_hash
}
```

Amend subject evidence:

```text
VerificationSubjectEvidence {
  semantic_id
  canonical_kind
  ...
  evidence_aspects[]
  snapshot_id
  snapshot_hash
  projection_ref
}
```

Amend `SemanticVerificationRequest`:

```text
SemanticVerificationRequest {
  admitted_execution_authority
  approval_scope_boundary
  canonical_changeset
  actual_delta
  validation_tasks[]
  verification_evidence_bundle
  verified_at
}
```

Add hash semantics so baseline refs/evidence are included when present.

- [ ] **1.3 Self-check the document before any code**

Run repository-local text checks when implementation begins:

```bash
grep -n "source_canonical_kind\|baseline_subject_evidence\|approval_scope_boundary\|actual_delta" \
  docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md
git diff --check
```

Expected: all four refinements appear; no whitespace errors.

- [ ] **1.4 Commit the docs-only refinement**

```bash
git add docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md
git commit -m "docs(step33): complete executable reconciliation evidence contract"
```

---

## Task 2: Add owner-side Step30 `ExecutionPlan` integrity reconstruction

**Files:**
- Modify: `platform/execution_planning/src/design_execution_planning/integrity.py`
- Modify: `platform/execution_planning/src/design_execution_planning/__init__.py`
- Modify: `tests/execution_planning/test_step30_integrity.py`

- [ ] **2.1 RED: freeze full-plan integrity behavior**

Extend `test_step30_integrity.py` with a real two-Slice plan using existing `routing_for_transaction()` and different Host instances. Tests must prove:

- valid single-Slice and cross-Slice plans pass;
- tampered Slice body fails through existing Slice validator;
- dependency predecessor/successor unit id not present in the plan fails `EXECUTION_PLAN_INTEGRITY_INVALID`;
- duplicate unit id across Slices fails;
- dependency self/membership ambiguity fails;
- changing `reason_ref` without recomputing plan hash fails;
- changing routing snapshot hash fails plan hash reconstruction;
- changing Slice membership/order cannot escape the existing set-based plan hash semantics;
- `execution_plan_id != XP-<hash prefix>` fails.

Run:

```bash
pytest -q tests/execution_planning/test_step30_integrity.py
```

Expected RED: import/attribute failure for `validate_execution_plan_integrity` or new tests fail because only Slice integrity exists.

- [ ] **2.2 GREEN: reconstruct the existing plan hash without private planner imports**

Add to `integrity.py`:

```python
def validate_execution_plan_integrity(execution_plan: ExecutionPlan) -> None:
    if not isinstance(execution_plan, ExecutionPlan):
        raise TypeError("execution_plan must be ExecutionPlan")

    for execution_slice in execution_plan.execution_slices:
        validate_execution_slice_integrity(execution_slice)

    unit_by_id: dict[str, ExecutionUnit] = {}
    for execution_slice in execution_plan.execution_slices:
        for unit in execution_slice.execution_units:
            if unit.execution_unit_id in unit_by_id:
                _invalid("EXECUTION_PLAN_INTEGRITY_INVALID", "duplicate execution unit id")
            unit_by_id[unit.execution_unit_id] = unit

    dependency_semantics = []
    for dependency in execution_plan.execution_dependencies:
        predecessor = unit_by_id.get(dependency.predecessor_execution_unit_id)
        successor = unit_by_id.get(dependency.successor_execution_unit_id)
        if predecessor is None or successor is None:
            _invalid("EXECUTION_PLAN_INTEGRITY_INVALID", "dependency endpoint not in plan")
        dependency_semantics.append(
            (predecessor.execution_unit_hash, successor.execution_unit_hash, dependency.reason_ref)
        )

    expected = compute_execution_plan_hash(
        changeset_hash=execution_plan.changeset_hash,
        scope_hash=execution_plan.approval_scope_ref.scope_hash,
        routing_snapshot_hash=execution_plan.routing_snapshot_hash,
        execution_slice_hashes=(s.execution_slice_hash for s in execution_plan.execution_slices),
        execution_dependencies=dependency_semantics,
    )
    if expected != execution_plan.execution_plan_hash:
        _invalid("EXECUTION_PLAN_INTEGRITY_INVALID", "execution plan body mismatch")
    if execution_plan.execution_plan_id != f"XP-{expected[:12]}":
        _invalid("EXECUTION_PLAN_INTEGRITY_INVALID", "execution plan id mismatch")
```

Do not import `_dependency_hash_semantics` or any private planner helper.

Export from `design_execution_planning.__init__`.

- [ ] **2.3 GREEN verification + owner regression**

```bash
pytest -q tests/execution_planning/test_step30_integrity.py
pytest -q tests/execution_planning
ruff check platform/execution_planning/src/design_execution_planning tests/execution_planning
git diff --check
```

- [ ] **2.4 Commit**

```bash
git add platform/execution_planning/src/design_execution_planning/integrity.py \
  platform/execution_planning/src/design_execution_planning/__init__.py \
  tests/execution_planning/test_step30_integrity.py
git commit -m "feat(step30): validate complete execution plans"
```

---

## Task 3: Create the Step33 package and freeze ActualDelta contracts/hashes

**Files:**
- Create: `platform/execution_reconciliation/pyproject.toml`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/conftest.py`
- Create: `tests/execution_reconciliation/test_step33_actual_delta.py`
- Modify: `pyproject.toml`

- [ ] **3.1 RED: freeze public ActualDelta contract semantics**

Tests must cover:

- `ActualChangeKind` exactly `CREATE/MODIFY/DELETE`;
- MODIFY requires `semantic_id` and non-empty canonical aspects;
- DELETE requires `semantic_id`;
- CREATE requires `canonical_operation` plus stable instance key (`semantic_id` or `HostEntityRef`);
- CREATE may carry `source_semantic_id`, `source_canonical_kind`, `derivation_rule`, `source_execution_unit_hash`;
- `HostEntityRef.document_id` must equal the delta `document_ref` when used as CREATE identity;
- `native_type` changes do not alter `actual_change_hash` when `semantic_id` or `(document_id,native_id)` identity is unchanged;
- changed-aspect input order does not change identity;
- `revision_after < revision_before` fails `RECONCILIATION_REVISION_INVALID`;
- same semantic side effects + same revision/lineage re-hash identically;
- tampered `actual_change_hash` or `actual_delta_hash` fails `ACTUAL_DELTA_INTEGRITY_INVALID`.

Run:

```bash
pytest -q tests/execution_reconciliation/test_step33_actual_delta.py
```

Expected RED: package/import does not exist.

- [ ] **3.2 GREEN: scaffold immutable contracts**

`contracts.py` public minimum:

```python
class ReconciliationError(ValueError):
    def __init__(self, code: str, message: str, *, upstream_code: str | None = None,
                 detail_codes: tuple[str, ...] = ()) -> None: ...

class ActualChangeKind(str, Enum):
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"

@dataclass(frozen=True, slots=True)
class ActualChange:
    change_kind: ActualChangeKind
    semantic_id: str | None = None
    canonical_kind: str | None = None
    changed_aspects: tuple[CanonicalAspect | str, ...] = ()
    canonical_operation: str | None = None
    source_execution_unit_hash: str | None = None
    source_semantic_id: str | None = None
    source_canonical_kind: str | None = None
    derivation_rule: str | None = None
    host_entity_ref: HostEntityRef | None = None
    actual_change_hash: str = ""

@dataclass(frozen=True, slots=True)
class ActualDelta:
    actual_delta_id: str
    grant_hash: str
    binding_set_hash: str
    execution_slice_hash: str
    changeset_hash: str
    approved_scope_hash: str
    host_instance_id: str
    document_ref: str
    revision_before: int
    revision_after: int
    changes: tuple[ActualChange, ...]
    actual_delta_hash: str
```

Validate only intrinsic contract facts in dataclass initialization; semantic hash reconstruction belongs to public hash validators.

- [ ] **3.3 GREEN: deterministic Step33-only hash API**

Use Step29 public `canonical_hash`; do not duplicate JSON canonicalization.

```python
def compute_actual_change_hash(change: ActualChange) -> str: ...
def compute_actual_delta_hash(delta: ActualDelta) -> str: ...
def validate_actual_delta_integrity(delta: ActualDelta) -> None: ...
```

Stable instance payload:

```python
if change.semantic_id is not None:
    instance = {"kind": "SEMANTIC_ID", "semantic_id": change.semantic_id}
elif change.host_entity_ref is not None:
    instance = {
        "kind": "HOST_ENTITY",
        "document_id": change.host_entity_ref.document_id,
        "native_id": change.host_entity_ref.native_id,
    }
else:
    instance = None
```

Never hash `HostEntityRef.native_type` as semantic authorization identity.

- [ ] **3.4 Build shared Step33 fixtures without changing upstream fixtures**

`tests/execution_reconciliation/conftest.py` should expose helpers that assemble:

1. a real Step28→29→30 single-Slice transaction with a custom `SEMANTIC_ASSERTIONS_V1` canonical contract and **no dependency edges**, so its ChangeSet has one executable canonical ValidationTask;
2. a real two-Slice Step30 plan from existing Step30 transaction semantics for Saga tests;
3. a real Step32 admitted authority by reusing public Gateway service/store APIs;
4. helper constructors that compute valid ActualChange/ActualDelta hashes.

Do not edit `tests/gateway_authorization/conftest.py` just to share fixtures; use test-local helper loading or construct through public APIs.

- [ ] **3.5 Wire package path and run GREEN**

Add to root pytest pythonpath:

```toml
"platform/execution_reconciliation/src",
"tests/execution_reconciliation",
```

Run:

```bash
pytest -q tests/execution_reconciliation/test_step33_actual_delta.py
pytest -q tests/execution_planning/test_step30_integrity.py
ruff check platform/execution_reconciliation/src/design_execution_reconciliation tests/execution_reconciliation/test_step33_actual_delta.py
```

- [ ] **3.6 Commit**

```bash
git add platform/execution_reconciliation pyproject.toml tests/execution_reconciliation
git commit -m "feat(step33): add authoritative actual delta contracts"
```

---

## Task 4: Implement existing-entity MODIFY/DELETE ScopeComparator semantics

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/scope_comparator.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_step33_scope_existing.py`

- [ ] **4.1 RED: exact lineage/error precedence and MODIFY rules**

Freeze precedence with tests:

```text
bad ActualDelta hash
→ ACTUAL_DELTA_INTEGRITY_INVALID

valid delta + authority hash mismatch
→ RECONCILIATION_LINEAGE_MISMATCH

bad Step28 boundary
→ SCOPE_COMPARISON_INVALID with upstream_code=SCOPE_INTEGRITY_INVALID

bad Step30 slice
→ SCOPE_COMPARISON_INVALID with upstream Step30 code
```

Then prove:

- existing entity + allowed aspect → `WITHIN_SCOPE`;
- one entity covered by multiple Slice-authorized ExistingEntityRules unions allowed aspects deterministically;
- entity outside Slice rules → `SCOPE_BREACH / ENTITY_OUTSIDE_SCOPE`;
- one unauthorized aspect → `SCOPE_BREACH / ASPECT_OUTSIDE_SCOPE`;
- predicate selectors support all Step28 fields from actual-change context;
- Host `native_type` changes cannot change result.

- [ ] **4.2 RED: DELETE authority**

Use a manually constructed **valid** Step28 Boundary with deletion rules. Do not modify Step28 planner: current v1 planner intentionally rejects existence effects, while public Step28 contracts/hashing already represent them.

Prove:

- matching Slice-authorized DeletionRule → pass;
- matching Boundary rule not referenced by current Slice → breach;
- no deletion rule → `DELETION_FORBIDDEN`.

Run:

```bash
pytest -q tests/execution_reconciliation/test_step33_scope_existing.py
```

- [ ] **4.3 GREEN: comparator result contracts**

Add:

```python
class ScopeComparisonStatus(str, Enum):
    WITHIN_SCOPE = "WITHIN_SCOPE"
    SCOPE_BREACH = "SCOPE_BREACH"

@dataclass(frozen=True, slots=True)
class ScopeMatch:
    actual_change_hash: str
    rule_id: str

@dataclass(frozen=True, slots=True)
class ScopeViolation:
    code: str
    actual_change_hash: str
    rule_id: str | None = None

@dataclass(frozen=True, slots=True)
class ScopeComparisonRequest:
    admitted_execution_authority: AdmittedExecutionAuthority
    actual_delta: ActualDelta
    approval_scope_boundary: ApprovalScopeBoundary
    execution_slice: ExecutionSlice

@dataclass(frozen=True, slots=True)
class ScopeComparisonResult:
    status: ScopeComparisonStatus
    actual_delta_hash: str
    approved_scope_hash: str
    execution_slice_hash: str
    matched_changes: tuple[ScopeMatch, ...]
    violations: tuple[ScopeViolation, ...]
    comparison_hash: str
```

Hash results from sorted semantic matches/violations.

- [ ] **4.4 GREEN: one provider-neutral selector evaluator**

Private selector context:

```python
@dataclass(frozen=True)
class _SelectorContext:
    semantic_id: str | None
    canonical_kind: str | None
    source_entity: str | None
    derivation_rule: str | None
```

Map Step28 predicate fields only; never inspect Host metadata:

```python
PredicateField.SEMANTIC_ID      -> context.semantic_id
PredicateField.CANONICAL_KIND   -> context.canonical_kind
PredicateField.SOURCE_ENTITY    -> context.source_entity
PredicateField.DERIVATION_RULE  -> context.derivation_rule
```

`EQ` and `IN` are pure string membership comparisons.

- [ ] **4.5 GREEN: comparator service**

```python
class ScopeComparator:
    def compare(self, request: ScopeComparisonRequest) -> ScopeComparisonResult:
        validate_actual_delta_integrity(request.actual_delta)
        self._validate_authority_lineage(request)
        self._validate_boundary(request.approval_scope_boundary)
        self._validate_slice(request.execution_slice)
        slice_scope = self._resolve_exact_slice_scope(request)
        ...
```

Scope breach is a result, not an exception after valid inputs. Input/integrity/lineage problems are `ReconciliationError` exceptions.

- [ ] **4.6 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_scope_existing.py
pytest -q tests/approval_scope/test_step28_integrity.py tests/execution_planning/test_step30_integrity.py
ruff check platform/execution_reconciliation/src/design_execution_reconciliation tests/execution_reconciliation

git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): compare actual existing-entity scope"
```

---

## Task 5: Implement deterministic CREATE rule matching and count allocation

**Files:**
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/scope_comparator.py`
- Extend: `tests/execution_reconciliation/test_step33_scope_existence.py`

- [ ] **5.1 RED: build valid synthetic CREATE Boundary/Slice witnesses**

Construct Step28 `ApprovalScopeDefinition` directly with public contracts, compute `scope_body_hash` via public `compute_scope_body_hash()`, then use public `bind_changeset()`. This is test-only witness creation and MUST NOT weaken the current Step28 planner's `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED` behavior.

Tests cover:

- correct canonical operation/kind/source/derivation/count passes;
- canonical operation mismatch → `CREATION_OPERATION_FORBIDDEN`;
- kind mismatch → `CREATION_KIND_FORBIDDEN`;
- source explicit entity mismatch → `CREATION_SOURCE_FORBIDDEN`;
- source predicate `CANONICAL_KIND` consumes `source_canonical_kind`;
- missing `source_canonical_kind` for such a selector fails closed, never D5 lookup;
- required derivation mismatch → `CREATION_DERIVATION_MISMATCH`;
- `max_count` overflow → `CREATION_COUNT_EXCEEDED`;
- Boundary rule not referenced by current Slice cannot authorize creation;
- CREATE `source_execution_unit_hash`, when present, must belong to exact Slice or input fails `RECONCILIATION_LINEAGE_MISMATCH`.

- [ ] **5.2 RED: overlapping rules use canonical allocation**

Construct at least three creates and two overlapping rules where greedy input-order assignment can fail but a valid allocation exists. Reverse rule/change input order and prove identical result/hash.

Canonical solution order:

```text
(rule_id, stable_instance_key, actual_change_hash)
```

Use deterministic backtracking over sorted candidates because `max_count` creates a small bipartite capacity problem. Do not rely on dict/list insertion order.

- [ ] **5.3 GREEN: staged eligibility + deterministic allocation**

Implement staged filters so the most useful stable violation detail can be emitted before capacity allocation:

```text
Slice-authorized rules
→ canonical_operation
→ entity_kind
→ source_selector
→ required_derivation
→ capacity allocation
```

For source selector use:

```text
semantic_id     = change.source_semantic_id
canonical_kind  = change.source_canonical_kind
source_entity   = change.source_semantic_id
derivation_rule = change.derivation_rule
```

Then allocate all creates globally across eligible rules. If no full allocation exists solely because capacity is exhausted, emit `CREATION_COUNT_EXCEEDED`.

- [ ] **5.4 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_scope_existence.py
pytest -q tests/execution_reconciliation/test_step33_scope_existing.py
pytest -q tests/approval_scope

git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): enforce deterministic creation scope"
```

---

## Task 6: Freeze VerificationEvidenceBundle integrity, baseline binding, and hashes

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_step33_verification_evidence.py`

- [ ] **6.1 RED: content-addressed contract evidence**

Tests prove:

- `H(contract_body) == contract_ref` is mandatory;
- duplicate `contract_ref` with different bodies fails `VERIFY_CONTRACT_MISMATCH`;
- subject evidence identity is unique by `(snapshot_id, snapshot_hash, semantic_id)`;
- post subject evidence must match bundle post snapshot id/hash and post projection ref;
- bundle environment must exactly match `(environment_id, content_hash)` of ChangeSet/Boundary planning environment;
- post snapshot `base_host_revision == str(actual_delta.revision_after)`;
- bundle `actual_delta_hash`, Slice hash, ChangeSet hash match exact request lineage;
- evidence hash is deterministic under input ordering.

- [ ] **6.2 RED: delta baseline binding**

For any requested ValidationTask whose executable contract contains `DELTA_EQUALS_ARGUMENT`:

- missing baseline snapshot → `VERIFY_EVIDENCE_INSUFFICIENT` / `REQUIRED_BASELINE_MISSING`;
- baseline snapshot id/hash/document/environment must exactly match `canonical_changeset.planning_snapshot_ref`;
- baseline subject evidence must be bound to baseline snapshot id/hash;
- missing required baseline subject/path is insufficient, not a semantic mismatch;
- baseline evidence may be absent when no delta assertion is requested.

- [ ] **6.3 GREEN: evidence contracts**

Minimum shapes:

```python
@dataclass(frozen=True, slots=True)
class VerificationContractEvidence:
    contract_ref: str
    contract_body: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class VerificationSubjectEvidence:
    semantic_id: str
    canonical_kind: str | None
    properties: Mapping[str, Any]
    placement: Any | None
    geometry_evidence: Any | None
    relationships: tuple[Mapping[str, Any], ...]
    constraints: tuple[Mapping[str, Any], ...]
    classification: tuple[Any, ...]
    evidence_aspects: tuple[CanonicalAspect | str, ...]
    snapshot_id: str
    snapshot_hash: str
    projection_ref: Any

@dataclass(frozen=True, slots=True)
class VerificationEvidenceBundle:
    evidence_bundle_id: str
    changeset_hash: str
    execution_slice_hash: str
    actual_delta_hash: str
    semantic_environment_ref: Any
    post_execution_snapshot_ref: Any
    post_execution_projection_ref: Any
    base_host_revision: str
    baseline_snapshot_ref: Any | None
    baseline_projection_ref: Any | None
    contract_evidence: tuple[VerificationContractEvidence, ...]
    subject_evidence: tuple[VerificationSubjectEvidence, ...]
    baseline_subject_evidence: tuple[VerificationSubjectEvidence, ...]
    evidence_bundle_hash: str
```

Mappings must be defensive immutable copies (`MappingProxyType(deepcopy(...))`) so external mutation cannot change evidence after hashing.

- [ ] **6.4 GREEN: evidence hashing/validation helpers**

```python
def compute_verification_evidence_bundle_hash(bundle: VerificationEvidenceBundle) -> str: ...
def validate_verification_evidence_bundle_integrity(bundle: VerificationEvidenceBundle) -> None: ...
```

Hash baseline refs/evidence only as explicit fields; empty/None normalizes deterministically.

- [ ] **6.5 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_verification_evidence.py
pytest -q tests/execution_reconciliation/test_step33_actual_delta.py
ruff check platform/execution_reconciliation/src/design_execution_reconciliation tests/execution_reconciliation

git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): bind semantic verification evidence"
```

---

## Task 7: Implement deterministic `SEMANTIC_ASSERTIONS_V1` SemanticVerifier

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/verifier.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_step33_verifier.py`

- [ ] **7.1 RED: request integrity and exact upstream joins**

Freeze `SemanticVerificationRequest`:

```python
@dataclass(frozen=True, slots=True)
class SemanticVerificationRequest:
    admitted_execution_authority: AdmittedExecutionAuthority
    approval_scope_boundary: ApprovalScopeBoundary
    canonical_changeset: CanonicalChangeSet
    actual_delta: ActualDelta
    validation_tasks: tuple[ValidationTask, ...]
    verification_evidence_bundle: VerificationEvidenceBundle
    verified_at: str
```

Tests prove:

- Boundary integrity and `validate_changeset_integrity(changeset, boundary)` are called through public APIs;
- ActualDelta integrity + authority lineage exact match precede rule evaluation;
- requested ValidationTasks are an exact subset by full semantic equality/id of `changeset.validation_tasks`;
- invented/mutated task → `VERIFY_INPUT_INVALID`;
- contract body mismatch → `VERIFY_CONTRACT_MISMATCH`;
- environment/post revision mismatch fails before assertion evaluation.

- [ ] **7.2 RED: fixed operator vocabulary**

Create a clean Step28→29 transaction whose canonical contract is `SEMANTIC_ASSERTIONS_V1`; do not alter production canonical operation definitions. Test every operator generically:

```text
EXISTS
NOT_EXISTS
EQUALS_LITERAL
EQUALS_ARGUMENT
DELTA_EQUALS_ARGUMENT
RELATIONSHIP_EXISTS
CLASSIFICATION_IS
```

Use these canonical assertion conventions:

```json
{"subjects":{"from_argument":"targets"},"path":"properties.thickness","operator":"EXISTS"}
{"subjects":{"from_argument":"targets"},"path":"properties.thickness","operator":"EQUALS_LITERAL","value":0.3}
{"subjects":{"from_argument":"targets"},"path":"properties.thickness","operator":"EQUALS_ARGUMENT","argument":"thickness"}
{"subjects":{"from_argument":"targets"},"path":"placement.x","operator":"DELTA_EQUALS_ARGUMENT","argument":"dx"}
{"subjects":{"from_argument":"targets"},"operator":"RELATIONSHIP_EXISTS","relationship":{"type":"HOSTED_BY","target":"WALL-001"}}
{"subjects":{"from_argument":"targets"},"operator":"CLASSIFICATION_IS","value":"ifc:IfcWall"}
```

Only `subjects.from_argument` is supported in v0.6; unsupported subject selectors fail `VERIFY_CONTRACT_UNSUPPORTED` rather than becoming operation-specific code.

- [ ] **7.3 RED: status semantics**

Prove:

- all assertions true → task `PASSED`;
- observed value differs → `FAILED` + `EXPECTED_VALUE_MISMATCH`;
- missing post subject/path/aspect → `EVIDENCE_INSUFFICIENT` + `REQUIRED_FIELD_MISSING`;
- missing baseline for delta → `EVIDENCE_INSUFFICIENT` + `REQUIRED_BASELINE_MISSING`;
- unsupported `{"type":"HOST_READ_BACK"}` → `EVIDENCE_INSUFFICIENT` + `VERIFY_CONTRACT_UNSUPPORTED`;
- any FAILED dominates aggregate;
- otherwise any insufficiency → aggregate `EVIDENCE_INSUFFICIENT`;
- no validation tasks is not silently PASS unless the request intentionally requests the exact empty ChangeSet task set; production Slice success gating later requires the ChangeSet's required Slice tasks.

- [ ] **7.4 GREEN: generic path/assertion evaluator**

Implement no Host or canonical-operation branches. Resolve the source operation only to obtain canonical arguments:

```python
operation_ref = f"{operation.canonical_operation}@{operation.canonical_operation_version}"
```

A canonical-operation ValidationTask must resolve exactly one matching ChangeSet operation and exact task subjects must equal that operation's targets.

Dot-path lookup walks mappings/attributes only; missing path returns a sentinel so EXISTS/NOT_EXISTS can distinguish absence from `None`.

Numeric tolerance:

```python
def _equal(expected, actual, tolerance) -> bool:
    # exact canonical equality by default
    # if absolute tolerance exists, both values must be numeric canonical values
```

No unit conversion. If values carry `{value, unit}` and tolerance supplies a unit, units must agree before comparing numeric `value`.

`DELTA_EQUALS_ARGUMENT` computes `post - baseline` on canonical numeric values.

- [ ] **7.5 GREEN: immutable task/result hashes**

Add:

```python
class VerificationStatus(str, Enum): ...
@dataclass(frozen=True, slots=True) class ValidationTaskResult: ...
@dataclass(frozen=True, slots=True) class SemanticVerificationResult: ...

def compute_validation_task_result_hash(...): ...
def compute_semantic_verification_hash(...): ...

class SemanticVerifier:
    def verify(self, request: SemanticVerificationRequest) -> SemanticVerificationResult: ...
```

`verified_at` is audit evidence but does not alter semantic verification hash unless the spec explicitly says so; keep it outside the hash.

- [ ] **7.6 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_verifier.py
pytest -q tests/execution_reconciliation/test_step33_verification_evidence.py
pytest -q tests/changeset/test_step29_integrity.py
ruff check platform/execution_reconciliation/src/design_execution_reconciliation tests/execution_reconciliation

git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): verify snapshot-bound semantic results"
```

---

## Task 8: Implement immutable Saga definition, Slice dependency projection, and canonical order

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/saga.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_step33_saga_definition.py`

- [ ] **8.1 RED: Saga creation validates exact Step28→30 lineage**

Tests must prove:

- invalid Boundary → `SAGA_INTEGRITY_INVALID` with upstream detail;
- invalid ChangeSet → `SAGA_INTEGRITY_INVALID`;
- invalid ExecutionPlan → `SAGA_INTEGRITY_INVALID`;
- ChangeSet/Boundary/Plan hash mismatch fails;
- Plan scope hash must equal exact approved scope;
- semantic environment must exactly match ChangeSet/Boundary;
- caller cannot provide an arbitrary Slice list: definition is derived from the validated plan only.

- [ ] **8.2 RED: project unit dependencies to Slice DAG**

Given Step30 unit dependencies:

```text
unit A in Slice X -> unit B in Slice Y
```

produce one normalized Slice edge X→Y with sorted unique `reason_refs`. Same-Slice dependencies do not create self edges. Duplicate unit dependencies collapse deterministically.

Reject a projected cycle with `SAGA_INTEGRITY_INVALID`; do not assume Step30 planner will always remain cycle-free forever.

- [ ] **8.3 RED: canonical global sequential order**

Prove:

- topological precedence is respected;
- two independent roots are ordered by `execution_slice_hash` tie-break;
- input Slice/dependency ordering does not change `ordered_slice_hashes` or `saga_definition_hash`;
- `saga_id == SG-<hash prefix>` (use one stable prefix and freeze it in tests).

- [ ] **8.4 GREEN: Saga definition contracts and builder**

```python
@dataclass(frozen=True, slots=True)
class SliceDependency:
    predecessor_slice_hash: str
    successor_slice_hash: str
    reason_refs: tuple[str, ...]

@dataclass(frozen=True, slots=True)
class ExecutionSagaDefinition:
    saga_id: str
    changeset_hash: str
    approved_scope_hash: str
    semantic_environment_ref: Any
    execution_plan_hash: str
    ordered_slice_hashes: tuple[str, ...]
    slice_dependencies: tuple[SliceDependency, ...]
    saga_definition_hash: str

class ExecutionSagaBuilder:
    def build(self, changeset, boundary, execution_plan) -> ExecutionSagaDefinition: ...
```

Use Kahn topological sort with a min-heap keyed by `execution_slice_hash` for simultaneously eligible Slices.

- [ ] **8.5 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_saga_definition.py
pytest -q tests/execution_planning
pytest -q tests/approval_scope/test_step28_integrity.py tests/changeset/test_step29_integrity.py

git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): freeze deterministic execution saga definitions"
```

---

## Task 9: Implement CAS Saga Store, sequential admission reservation, and successful reconciliation lifecycle

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/store.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_step33_saga_store.py`

- [ ] **9.1 RED: freeze stored lifecycle contracts**

```python
class SagaState(str, Enum):
    READY = "READY"
    EXECUTING = "EXECUTING"
    PARTIALLY_COMMITTED = "PARTIALLY_COMMITTED"
    SUCCEEDED = "SUCCEEDED"
    COMPENSATING = "COMPENSATING"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
    FAILED = "FAILED"

class SliceState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    ADMISSION_RESERVED = "ADMISSION_RESERVED"
    ADMITTED = "ADMITTED"
    HOST_COMMITTED = "HOST_COMMITTED"
    RECONCILING = "RECONCILING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_BEFORE_COMMIT = "FAILED_BEFORE_COMMIT"
    VERIFY_FAILED = "VERIFY_FAILED"
    SCOPE_BREACH = "SCOPE_BREACH"
    BLOCKED = "BLOCKED"
    COMPENSATED = "COMPENSATED"
    COMPENSATION_FAILED = "COMPENSATION_FAILED"
```

Freeze `SliceReconciliationState` and `StoredExecutionSaga` exact fields from the design, including `sequence_index`, immutable evidence hashes, explicit times, and `saga_revision`.

- [ ] **9.2 RED: create and reserve exactly one Slice**

Tests:

- `create_saga()` persists revision 0, `READY`, all Slice states `NOT_STARTED` in canonical order;
- same `saga_definition_hash` replay returns same state;
- same `saga_id` with different definition → `SAGA_CONFLICT`;
- only lowest eligible `sequence_index` can reserve;
- predecessor failure/non-success blocks reservation with `SAGA_PREDECESSOR_NOT_SUCCEEDED`;
- while any Slice is RESERVED/ADMITTED/HOST_COMMITTED/RECONCILING no other reservation succeeds;
- 32 concurrent reservation calls produce one logical reservation and deterministic same-evidence recovery, not multiple active Slices;
- stale expected revision → `SAGA_CONFLICT`.

- [ ] **9.3 RED: reserve→Step32 admit crash recovery**

Use real Step32 store/service:

```text
Step33 reserve Slice
Step32 admit Grant
simulate lost Step33 confirmation
retry Step32 same Grant -> same AdmittedExecutionAuthority/original admitted_at
Step33 confirm -> ADMITTED
```

`confirm_slice_admitted()` must bind authority Slice/hash/host/Grant to the reservation. Same authority replay returns existing logical state; different Grant hash conflicts.

- [ ] **9.4 RED: success path state machine**

Freeze:

```text
ADMITTED
→ record_host_commit(actual_delta_hash, committed_at)
→ HOST_COMMITTED
→ begin_reconciliation
→ RECONCILING
→ record_scope_result(WITHIN_SCOPE)
→ record_verification_result(PASSED)
→ SUCCEEDED
```

Rules:

- host commit requires admitted Slice;
- scope result hash/delta hash must match Slice evidence;
- verification cannot record before persisted `WITHIN_SCOPE` for same delta;
- all Slices SUCCEEDED → Saga SUCCEEDED;
- after one Slice SUCCEEDED, next canonical Slice becomes reservable;
- identical transition/evidence replay preserves original timestamps/revision semantics as defined by store; different evidence conflicts.

- [ ] **9.5 GREEN: protocol + `RLock` reference store**

Protocol minimum:

```python
class ExecutionSagaStore(Protocol):
    def create_saga(self, definition: ExecutionSagaDefinition) -> StoredExecutionSaga: ...
    def get_saga(self, saga_id: str) -> StoredExecutionSaga | None: ...
    def reserve_slice_admission(self, saga_id: str, slice_hash: str,
                                expected_revision: int, reserved_at: str) -> StoredExecutionSaga: ...
    def confirm_slice_admitted(self, saga_id: str, authority: AdmittedExecutionAuthority,
                               expected_revision: int) -> StoredExecutionSaga: ...
    def record_host_commit(self, saga_id: str, slice_hash: str, actual_delta_hash: str,
                           committed_at: str, expected_revision: int) -> StoredExecutionSaga: ...
    def begin_reconciliation(self, saga_id: str, slice_hash: str,
                             expected_revision: int) -> StoredExecutionSaga: ...
    def record_scope_result(self, saga_id: str, result: ScopeComparisonResult,
                            expected_revision: int, reconciled_at: str) -> StoredExecutionSaga: ...
    def record_verification_result(self, saga_id: str, result: SemanticVerificationResult,
                                   expected_revision: int, reconciled_at: str) -> StoredExecutionSaga: ...
```

All eligibility inspection and mutation happens inside one lock/transaction.

- [ ] **9.6 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_saga_store.py
pytest -q tests/gateway_authorization/test_step32_admission_and_revocation.py
ruff check platform/execution_reconciliation/src/design_execution_reconciliation tests/execution_reconciliation

git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): persist sequential saga reconciliation"
```

---

## Task 10: Implement partial-failure blocking and governed compensation evidence

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/store.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/saga.py`
- Create: `tests/execution_reconciliation/test_step33_failure_and_compensation.py`

- [ ] **10.1 RED: pre-commit failure semantics**

Prove:

```text
first attempted Slice FAILED_BEFORE_COMMIT + no prior committed/succeeded Slice
→ Saga FAILED
→ no compensation required
```

and:

```text
Slice A SUCCEEDED
Slice B FAILED_BEFORE_COMMIT
→ Saga PARTIALLY_COMMITTED
→ every remaining NOT_STARTED Slice atomically BLOCKED
```

No later Slice can reserve.

- [ ] **10.2 RED: committed scope/verification failures**

Prove:

```text
HOST_COMMITTED + SCOPE_BREACH
→ Slice SCOPE_BREACH
→ Saga PARTIALLY_COMMITTED
→ remaining NOT_STARTED BLOCKED
→ semantic verification cannot be recorded as success gate
```

and:

```text
HOST_COMMITTED + WITHIN_SCOPE + verification FAILED/INSUFFICIENT
→ Slice VERIFY_FAILED
→ Saga PARTIALLY_COMMITTED
→ remaining BLOCKED
```

Even if the failing committed Slice is the first Slice, the Saga is partial rather than simple FAILED because a Host side effect exists.

- [ ] **10.3 RED: provider-neutral CompensationProposal sealing**

Do not infer an inverse operation. Freeze:

```python
@dataclass(frozen=True, slots=True)
class CompensationProposalRequest:
    source_saga_id: str
    failed_slice_hash: str
    desired_recovery_effects: tuple[Mapping[str, Any], ...]

@dataclass(frozen=True, slots=True)
class CompensationProposal:
    compensation_proposal_id: str
    source_saga_id: str
    source_changeset_hash: str
    failed_slice_hash: str
    committed_slice_hashes: tuple[str, ...]
    actual_delta_refs: tuple[str, ...]
    verification_failure_refs: tuple[str, ...]
    scope_breach_refs: tuple[str, ...]
    desired_recovery_effects: tuple[Mapping[str, Any], ...]
    proposal_hash: str
```

`ExecutionSagaPlanner.create_compensation_proposal(stored_saga, request)` validates that failed/committed/evidence refs come from the Saga, then seals caller-supplied provider-neutral recovery effects. No Host command or original Grant appears in proposal hash.

- [ ] **10.4 RED: compensation lifecycle truthfulness**

Introduce a minimal result reference:

```python
@dataclass(frozen=True, slots=True)
class CompensationExecutionRef:
    compensation_proposal_hash: str
    compensating_changeset_hash: str
    succeeded: bool
    completed_at: str
```

Tests:

- `begin_compensation()` only from `PARTIALLY_COMMITTED` with exact proposal;
- Saga → COMPENSATING;
- success → original Saga `COMPENSATED`, never SUCCEEDED;
- failure → `COMPENSATION_FAILED` terminal;
- repeated same evidence recovers idempotently;
- different compensating ChangeSet/result → `COMPENSATION_CONFLICT`;
- no automatic loop from `COMPENSATION_FAILED`.

- [ ] **10.5 GREEN + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_failure_and_compensation.py
pytest -q tests/execution_reconciliation/test_step33_saga_store.py

git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): add auditable partial failure compensation state"
```

---

## Task 11: Implement the public `ExecutionReconciliationService` facade and cross-step integration

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/service.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Extend: `tests/execution_reconciliation/conftest.py`
- Create: `tests/execution_reconciliation/test_step33_service.py`

- [ ] **11.1 RED: facade exposes only domain/external-boundary steps**

Public facade:

```python
class ExecutionReconciliationService:
    def __init__(self, store: ExecutionSagaStore) -> None: ...

    def create_saga(self, changeset, boundary, execution_plan) -> StoredExecutionSaga: ...
    def reserve_slice_admission(self, saga_id, slice_hash, expected_revision, reserved_at): ...
    def confirm_slice_admitted(self, saga_id, authority, expected_revision): ...
    def record_host_commit(self, saga_id, slice_hash, actual_delta, committed_at, expected_revision): ...
    def compare_scope(self, request: ScopeComparisonRequest) -> ScopeComparisonResult: ...
    def begin_reconciliation(self, saga_id, slice_hash, expected_revision): ...
    def record_scope_result(self, saga_id, result, expected_revision, reconciled_at): ...
    def verify_semantics(self, request: SemanticVerificationRequest) -> SemanticVerificationResult: ...
    def record_verification_result(self, saga_id, result, expected_revision, reconciled_at): ...
    def fail_slice_before_commit(...): ...
    def begin_compensation(...): ...
    def record_compensation_result(...): ...
    def get_saga(self, saga_id): ...
```

The facade MUST NOT hide Host execution, Step32 grant admission, D5 reconstruction, or Semantic Service lookup inside `reconcile_slice()`. Do not implement a convenience method that secretly performs those external effects.

- [ ] **11.2 RED: full one-Slice happy path**

Use public Steps 28–32 plus Step33:

```text
real ChangeSet/Boundary/Plan
→ create Saga
→ reserve
→ real Step32 admit
→ confirm admitted
→ record Host commit with valid ActualDelta
→ begin reconciliation
→ compare scope WITHIN_SCOPE
→ persist scope result
→ supply snapshot-bound bundle
→ SemanticVerifier PASSED
→ persist verification
→ Slice SUCCEEDED
→ Saga SUCCEEDED
```

Assert every persisted evidence hash joins exactly.

- [ ] **11.3 RED: two-Slice failure path**

Use real cross-Slice Step30 Plan:

```text
A reserve/admit/commit/reconcile/pass → SUCCEEDED
B reserve/admit/commit
B ActualDelta scope breach OR verify fail
→ PARTIALLY_COMMITTED
→ no remaining reservation
→ CompensationProposal can be sealed
```

This is the Step33 unit/integration precursor to Phase H Step37; it does not require real Revit/AutoCAD Hosts.

- [ ] **11.4 RED: crash/replay through facade**

Simulate:

- lost response after Store mutation;
- replay with same evidence returns durable state;
- replay with different evidence returns stable conflict;
- no service-side check-then-write sequence can create a second active Slice.

- [ ] **11.5 GREEN: compose existing pure components only**

The service should mostly map public upstream exceptions to Step33 errors and delegate:

```python
self._saga_builder = ExecutionSagaBuilder()
self._scope_comparator = ScopeComparator()
self._verifier = SemanticVerifier()
self._saga_planner = ExecutionSagaPlanner()
```

Store mutation remains atomic in Store methods.

- [ ] **11.6 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_service.py
pytest -q tests/execution_reconciliation
pytest -q tests/gateway_authorization
pytest -q tests/execution_planning

git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): integrate execution reconciliation service"
```

---

## Task 12: Add architecture guards, Step33 CI, final regressions, and verified design status

**Files:**
- Create: `tests/execution_reconciliation/test_step33_architecture.py`
- Create: `.github/workflows/step33-execution-reconciliation.yml`
- Modify: `docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md` only after all exact-head verification is green

- [ ] **12.1 RED: architecture guardrails**

AST/source tests must reject Step33 production coupling to:

```text
AutoCAD / AUTOCAD / autocad_sidecar
Revit / REVIT
Tekla / TEKLA
HostCommand
native transaction/undo/rollback dispatch
psycopg / asyncpg / redis / boto3 / DynamoDB
```

Allow public `HostEntityRef` only as opaque provenance/identity; forbid use of `native_type` inside `scope_comparator.py` authorization decisions.

Reject wall-clock calls:

```text
datetime.now
datetime.utcnow
time.time
```

Reject private upstream imports from:

```text
design_approval_scope.hashing
design_changeset.builder
design_execution_planning.planner
design_gateway_authorization.store
design_gateway_authorization.service
semantic_runtime.freshness internals beyond public package exports
```

Require `service.py`/domain owners to consume public validators:

```text
validate_approval_scope_boundary
validate_changeset_integrity
validate_execution_slice_integrity
validate_execution_plan_integrity
```

- [ ] **12.2 Freeze workflow path boundary exactly**

The Step33 workflow may trigger/accept only:

```text
.github/workflows/step33-execution-reconciliation.yml
docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md
docs/superpowers/plans/2026-08-30-step33-execution-reconciliation.md
platform/execution_reconciliation/**
tests/execution_reconciliation/**
platform/execution_planning/**
tests/execution_planning/**
pyproject.toml
```

PR diff gate applies when `github.head_ref == 'feat/step33-execution-reconciliation'`.

- [ ] **12.3 Build Step33 CI stack**

Follow Step32 setup and add `-e platform/execution_reconciliation` after Gateway. CI commands must include:

```bash
pytest -q tests/approval_scope/test_step28_integrity.py
pytest -q tests/changeset/test_step29_integrity.py
pytest -q tests/execution_planning/test_step30_integrity.py
pytest -q tests/execution_reconciliation
pytest -q tests/approval_scope
pytest -q tests/changeset
pytest -q tests/execution_planning
pytest -q tests/provider_binding
pytest -q tests/gateway_authorization
ruff check \
  platform/execution_planning/src/design_execution_planning \
  platform/execution_reconciliation/src/design_execution_reconciliation \
  tests/execution_planning tests/execution_reconciliation
pytest -q --import-mode=importlib
```

The workflow may additionally Ruff upstream frozen packages, but it must not omit Step30/33 targets above.

- [ ] **12.4 RED/GREEN architecture tests against workflow content**

`test_step33_architecture.py` should parse the workflow and prove:

- path filters equal frozen boundary;
- install stack includes Step32 stack + execution reconciliation;
- final test commands are present;
- Ruff includes Step30 + Step33 production/tests;
- full repository importlib test is present.

Run:

```bash
pytest -q tests/execution_reconciliation/test_step33_architecture.py
```

- [ ] **12.5 Final local/session verification before any completion claim**

Run in one fresh verification session:

```bash
pytest -q tests/approval_scope
pytest -q tests/changeset
pytest -q tests/execution_planning
pytest -q tests/provider_binding
pytest -q tests/gateway_authorization
pytest -q tests/execution_reconciliation
ruff check \
  platform/execution_planning/src/design_execution_planning \
  platform/execution_reconciliation/src/design_execution_reconciliation \
  tests/execution_planning tests/execution_reconciliation
pytest -q --import-mode=importlib
git diff --check
```

Then inspect exact diff boundary:

```bash
git diff --name-only cef76e111f74d10f063eedfebc7efc0d805caefa...HEAD
```

Every production/test path must be inside the frozen Step33 boundary. Historical Step33 spec/plan docs are expected additions. No forbidden upstream production path may appear.

- [ ] **12.6 Only after all green: update design implementation status**

Record the exact final implementation commit SHA and commands actually run. Do not mark Step33 implemented before fresh exact-HEAD evidence exists.

- [ ] **12.7 Commit architecture/CI/status**

```bash
git add .github/workflows/step33-execution-reconciliation.yml \
  tests/execution_reconciliation/test_step33_architecture.py \
  docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md
git commit -m "test(step33): enforce reconciliation architecture and verification"
```

- [ ] **12.8 Fresh GitHub Actions proof on exact final branch HEAD**

After pushing/final commit, inspect the workflow run for the exact final Step33 HEAD. Completion requires `completed/success` for the workflow jobs/steps corresponding to the matrix above. If CI fails, fix through TDD and rerun; never report completion from stale earlier commits.

---

## Implementation Review Checkpoints

After every task:

1. Capture the focused RED failure before production implementation.
2. Implement only the minimum GREEN behavior for that task.
3. Rerun focused tests and owner regression suites for every changed production package.
4. Run `git diff --check` and inspect `git diff --stat` / changed paths.
5. Commit the task boundary before moving on.

At Tasks 5, 9, and 10 specifically, review deterministic/transaction semantics rather than only output values:

- CREATE allocation result is invariant to input/container ordering and respects all `max_count` capacities.
- Saga eligibility inspection + reservation mutation occurs inside one atomic Store operation.
- No service-side check-then-write substitutes for CAS.
- Same transition/evidence recovery returns existing durable evidence, preserving original audit timestamps where the transition was already committed.
- Different evidence for the same logical transition conflicts.
- Partial failure and blocking of all remaining `NOT_STARTED` Slices happen atomically.
- Compensation never calls Host-native rollback and never mutates original Grant authority.

At Tasks 6–7, review evidence integrity:

- every contract body is content-addressed by the exact Step29 `contract_ref`;
- post evidence is bound to the exact post Host revision;
- delta assertions are bound to the exact pre-write PlanningSnapshot baseline;
- missing evidence is insufficient, never inferred success;
- verifier contains no Host/operation-specific branch.

## Definition of Done

Step33 is complete only when fresh exact-HEAD evidence proves all of the following:

```text
Step30 ExecutionPlan can reconstruct its existing immutable plan hash
no Step28–32 existing hash algorithm changed

ActualDelta is deterministic, provider-neutral, and authoritative for side effects
Host native_type/product metadata cannot alter scope authorization
bad lineage fails before scope evaluation

MODIFY allowed-aspect containment is exact
DELETE requires explicit Slice deletion authority
CREATE operation/kind/source/derivation/count are all enforced
CREATE overlapping-rule allocation is deterministic
ActualDelta outside scope returns SCOPE_BREACH and blocks remaining Slices

ValidationTask contract bodies are content-addressed exactly
post evidence is pinned to post Host revision/SemanticEnvironment
DELTA_EQUALS_ARGUMENT is pinned to exact pre-write baseline evidence
unsupported/insufficient contracts cannot PASS
wrong in-scope value returns VERIFY_FAILED, not SCOPE_BREACH
Host success/self-verification cannot bypass independent SemanticVerifier

Saga definition binds exact Boundary + ChangeSet + complete ExecutionPlan
cross-Slice dependencies project deterministically
independent roots still use one global deterministic sequential order
at most one Slice is reserved/active side-effecting at a time
ADMISSION_RESERVED closes the Step33→Step32 crash window
same evidence replay is idempotent; different evidence conflicts
HOST_COMMITTED is never equal to SUCCEEDED

first pre-commit failure with no committed side effect -> FAILED
prior success + later failure -> PARTIALLY_COMMITTED
committed SCOPE_BREACH/VERIFY_FAILED -> PARTIALLY_COMMITTED
remaining Slices atomically BLOCKED

compensation is an auditable provider-neutral proposal
compensation re-enters normal ChangeSet/Approval/Grant workflow externally
original Grant never auto-authorizes compensation
successful compensation -> COMPENSATED, never SUCCEEDED
failed compensation -> COMPENSATION_FAILED, no automatic loop

Step33 has no Host product/provider/database-vendor execution coupling
no direct domain wall-clock reads
all Step28–32 regressions pass
all Step33 tests pass
Ruff passes
full repository tests pass
fresh GitHub Actions succeeds on exact final Step33 HEAD
```
