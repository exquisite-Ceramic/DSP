# Step 33 Execution Reconciliation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Use strict TDD: write the focused RED test, run it and confirm the expected failure, implement the minimum GREEN change, rerun focused tests and owner regressions, inspect the diff, then commit before moving to the next task.

**Goal:** Implement Step33 as the provider-neutral post-execution reconciliation boundary that turns admitted Slice authority + authoritative Host read-back into deterministic scope comparison, independently proves semantic outcomes from pinned evidence, and durably coordinates cross-Host partial-failure recovery through a sequential Saga without XA/2PC or hidden native undo.

**Architecture:** Add one `design_execution_reconciliation` package. `ActualDelta` is the authoritative normalized side-effect fact; `ScopeComparator` evaluates it only against the exact Step28 Boundary/Slice scope; `SemanticVerifier` evaluates exact Step29 ValidationTasks only after scope passes and only over snapshot-bound evidence; `ExecutionSaga` binds the complete Step30 plan, deterministically assigns required ValidationTasks to Slices, and records durable CAS lifecycle state. Step33 consumes public Step28–32 validators/contracts, never reimplements their semantic hash bodies, never queries D5 internal storage, and never branches on Host product. The only upstream production enhancement is Step30 public `validate_execution_plan_integrity()` using the already-frozen plan hash.

**Tech Stack:** Python 3.11, frozen dataclasses, enums, `typing.Protocol`, `threading.RLock`, Step29 public `canonical_hash`, public Step28/29/30/32 contracts, public `semantic_runtime` snapshot refs, public `host_contracts.HostEntityRef`, pytest, `ThreadPoolExecutor`, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md`

## Global Constraints

- Planning branch: `feat/step33-execution-reconciliation`; approved design HEAD before the implementation-plan commits is `d8493b0dee8389f1be76bc568526831ac3f94ef5`, with merge-base exactly `main@cef76e111f74d10f063eedfebc7efc0d805caefa`.
- Keep implementation on `feat/step33-execution-reconciliation` unless the human explicitly requests a different branch.
- Distribution: `design-execution-reconciliation`; source package: `design_execution_reconciliation`.
- Existing Step28–32 semantic hash algorithms MUST NOT change.
- Step28, Step29, Step31, and Step32 production code MUST NOT change absent a newly surfaced and explicitly approved blocker.
- Step30 production changes are limited to public `validate_execution_plan_integrity()` and export wiring; `ExecutionPlan`, Unit/Slice contracts, planner behavior, and existing hashes remain unchanged.
- Step33 Core MUST NOT import Host implementations, Host command dispatch, provider implementations, D5 projection-storage internals, or database-vendor clients.
- No Step33 production branch may depend on AutoCAD/Revit/Tekla product names, native categories/layers, native transaction APIs, `UNDO`, or provider-specific verification logic.
- Domain logic MUST NOT read wall clock time. All audit times are explicit UTC inputs.
- `HostCommandResult.status == OK` and Host self-reported `verification` data never produce semantic PASS by themselves.
- Scope comparison MUST precede semantic verification for a committed Slice. A persisted `SCOPE_BREACH` is authoritative and cannot be downgraded by later verification.
- v0.6 allows at most one active side-effecting Slice across the whole Saga. Independent roots still use one deterministic global topological/hash order.
- A Slice may reach `SUCCEEDED` only after its **complete Saga-assigned ValidationTask set** has produced a persisted semantic PASS. Caller-supplied task omission is not allowed.
- Compensation is a new governed write workflow. Step33 may seal recovery intent/evidence, but never emits a Host rollback command and never reuses the original ExecutionGrant as compensation authority.
- Store protocol owns atomicity/CAS/idempotency. Service/domain logic owns validation, exact joins, deterministic hashes, transition legality, and stable error mapping.
- The in-memory store is a transaction-faithful reference implementation using one `RLock` around each mutating operation; it is not permission to weaken persistent-store semantics.

## Execution-Approval Refinements Discovered During Planning

Implementation decomposition exposed four Step33-only contract details needed to make the already-approved behavior executable. These MUST be synchronized into the design spec in Task 1 before production code begins. **Approval of this implementation plan is also approval of these four narrow refinements.** None modifies a Step28–32 contract or hash.

1. `ActualChange.source_canonical_kind?` is required so a `CreationRule.source_selector` using Step28 `PredicateField.CANONICAL_KIND` can be evaluated without D5 lookup.
2. `DELTA_EQUALS_ARGUMENT` requires task-scoped pre-write evidence. `VerificationEvidenceBundle` therefore adds `baseline_snapshot_ref?`, `baseline_projection_ref?`, and `baseline_subject_evidence[]`; `VerificationSubjectEvidence` adds `snapshot_id` + `snapshot_hash` so baseline and post evidence are explicitly snapshot-bound.
3. `SemanticVerificationRequest` adds the exact `approval_scope_boundary` and authoritative `actual_delta`. Current public `validate_changeset_integrity(changeset, boundary)` requires the Boundary, and exact post-revision verification requires the ActualDelta rather than only its hash.
4. `ExecutionSagaDefinition` adds deterministic `slice_validation_assignments[]`. Step29 ValidationTasks are ChangeSet-scoped and Step30 currently has no task-to-Slice field; without a derived assignment a caller could omit required tasks. Step33 derives the assignment from the immutable ChangeSet + ExecutionPlan and binds it into `saga_definition_hash`.

Baseline rules are fail-closed:

```text
DELTA_EQUALS_ARGUMENT present
→ baseline snapshot/evidence required
→ baseline snapshot identity == CanonicalChangeSet.planning_snapshot_ref
→ same SemanticEnvironment
→ required baseline subject/path present
otherwise EVIDENCE_INSUFFICIENT / REQUIRED_BASELINE_MISSING
```

No unit conversion belongs in Step33. Verification evidence and canonical operation arguments must already use canonical semantic units. If an assertion supplies a tolerance unit, explicit observed/expected units must agree; otherwise evidence is insufficient.

## Stable Step33 Top-Level Errors

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

Structured details include at minimum:

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

## Task 1: Synchronize executable Step33 refinements into the approved design spec

**Files:**
- Modify: `docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md`

- [ ] **1.1 Update written-spec status**

After the human approves this plan, change the header to:

```text
Status: Written spec and implementation plan approved; implementation not started
```

- [ ] **1.2 Add source selector evidence**

Add `source_canonical_kind?` to `ActualChange` and freeze creation-source selector context:

```text
SEMANTIC_ID      -> ActualChange.source_semantic_id
CANONICAL_KIND   -> ActualChange.source_canonical_kind
SOURCE_ENTITY    -> ActualChange.source_semantic_id
DERIVATION_RULE  -> ActualChange.derivation_rule
```

Missing evidence makes that selector non-matching; Step33 never backfills it from Host metadata or D5.

- [ ] **1.3 Add baseline verification evidence**

Update `VerificationEvidenceBundle`:

```text
baseline_snapshot_ref?
baseline_projection_ref?
baseline_subject_evidence[]
```

Update `VerificationSubjectEvidence`:

```text
snapshot_id
snapshot_hash
```

Update `SemanticVerificationRequest`:

```text
admitted_execution_authority
approval_scope_boundary
canonical_changeset
actual_delta
validation_tasks[]
verification_evidence_bundle
verified_at
```

- [ ] **1.4 Add deterministic Slice validation-task assignments**

Update Saga definition:

```text
SliceValidationAssignment {
  execution_slice_hash
  validation_task_ids[]
}

ExecutionSagaDefinition {
  ...
  slice_validation_assignments[]
  saga_definition_hash
}
```

Freeze assignment algorithm:

```text
CANONICAL_OPERATION task
→ resolve exactly one ChangeSet operation by
  canonical_operation_ref + exact subject_semantic_ids
→ assign to Slice containing that operation's ExecutionUnit

DEPENDENCY_VERIFICATION task
→ resolve exactly one SemanticImpactEvidence by
  dependency_ref + affected subject
→ if affected semantic id is target of exactly one ChangeSet operation,
  assign to that operation's Slice
→ otherwise assign to the Slice containing the source_semantic_id operation
→ ambiguous/unresolved assignment = SAGA_INTEGRITY_INVALID
```

Every ChangeSet ValidationTask must be assigned exactly once. `saga_definition_hash` includes sorted assignment semantics.

- [ ] **1.5 Check and commit docs-only synchronization**

```bash
grep -n "source_canonical_kind\|baseline_subject_evidence\|SliceValidationAssignment\|approval_scope_boundary" \
  docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md
git diff --check
git add docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md
git commit -m "docs(step33): complete executable reconciliation evidence contract"
```

---

## Task 2: Add owner-side Step30 `ExecutionPlan` integrity reconstruction

**Files:**
- Modify: `platform/execution_planning/src/design_execution_planning/integrity.py`
- Modify: `platform/execution_planning/src/design_execution_planning/__init__.py`
- Modify: `tests/execution_planning/test_step30_integrity.py`

- [ ] **2.1 RED: freeze full-plan integrity**

Extend real Step30 fixtures/tests to prove:

- valid single-Slice and two-Slice plans pass;
- tampered Slice fails through existing Slice integrity;
- dependency endpoint not present in any Slice fails `EXECUTION_PLAN_INTEGRITY_INVALID`;
- duplicate execution-unit id across Slices fails;
- dependency self/membership ambiguity fails;
- changed dependency `reason_ref` fails existing plan-hash reconstruction;
- changed routing snapshot hash fails;
- reordering already-valid Slice/dependency tuples does not change the existing set/sorted semantic plan identity;
- `execution_plan_id != XP-<hash[:12]>` fails.

Run:

```bash
pytest -q tests/execution_planning/test_step30_integrity.py
```

Expected RED: `validate_execution_plan_integrity` does not exist / new assertions fail.

- [ ] **2.2 GREEN: reconstruct only existing public semantics**

Add imports for `ExecutionPlan` and `compute_execution_plan_hash`; reuse `validate_execution_slice_integrity()` for every Slice. Build `unit_by_id`, reject duplicates, resolve every `ExecutionDependency` endpoint, convert dependencies to `(predecessor.execution_unit_hash, successor.execution_unit_hash, reason_ref)`, call the existing public plan hash, and enforce `XP-` id.

Public function:

```python
def validate_execution_plan_integrity(execution_plan: ExecutionPlan) -> None:
    """Reconstruct one immutable Step30 ExecutionPlan fail-closed."""
```

Do **not** import `_dependency_hash_semantics` or any other private planner helper.

Export it from `design_execution_planning.__init__`.

- [ ] **2.3 GREEN + owner regression + commit**

```bash
pytest -q tests/execution_planning/test_step30_integrity.py
pytest -q tests/execution_planning
ruff check platform/execution_planning/src/design_execution_planning tests/execution_planning
git diff --check
git add platform/execution_planning/src/design_execution_planning/integrity.py \
  platform/execution_planning/src/design_execution_planning/__init__.py \
  tests/execution_planning/test_step30_integrity.py
git commit -m "feat(step30): validate complete execution plans"
```

---

## Task 3: Create Step33 package and freeze ActualDelta contracts/hashes

**Files:**
- Create: `platform/execution_reconciliation/pyproject.toml`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/conftest.py`
- Create: `tests/execution_reconciliation/test_step33_actual_delta.py`
- Modify: `pyproject.toml`

- [ ] **3.1 RED: intrinsic ActualDelta contract behavior**

Tests cover:

- `ActualChangeKind` exactly CREATE/MODIFY/DELETE;
- MODIFY requires `semantic_id` + at least one Step28 `CanonicalAspect`;
- DELETE requires `semantic_id`;
- CREATE requires `canonical_operation` + stable instance discriminator (`semantic_id` else `HostEntityRef`);
- CREATE accepts provider-neutral `source_semantic_id`, `source_canonical_kind`, `derivation_rule`, `source_execution_unit_hash`;
- Host identity discriminator requires `HostEntityRef.document_id == ActualDelta.document_ref`;
- `HostEntityRef.native_type` changes do not change semantic ActualChange identity;
- changed-aspect input order does not change identity;
- `revision_after < revision_before` → `RECONCILIATION_REVISION_INVALID`;
- same lineage/revision/normalized side effects re-hash identically;
- tampered change/delta hash → `ACTUAL_DELTA_INTEGRITY_INVALID`.

Run:

```bash
pytest -q tests/execution_reconciliation/test_step33_actual_delta.py
```

Expected RED: Step33 package/import absent.

- [ ] **3.2 GREEN: package metadata and root test wiring**

Create:

```toml
[project]
name = "design-execution-reconciliation"
version = "0.1.0"
description = "Provider-neutral execution reconciliation, verification, and Saga contracts for DSP."
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Add root pytest pythonpath entries:

```toml
"platform/execution_reconciliation/src",
"tests/execution_reconciliation",
```

- [ ] **3.3 GREEN: immutable ActualDelta contracts**

Minimum public contracts:

```python
class ReconciliationError(ValueError):
    # code, upstream_code?, detail_codes[]

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

Intrinsic validation belongs in contracts; hash reconstruction remains public hashing API.

- [ ] **3.4 GREEN: deterministic semantic hashes**

Use Step29 public `canonical_hash()` only:

```python
def compute_actual_change_hash(change: ActualChange) -> str: ...
def compute_actual_delta_hash(delta: ActualDelta) -> str: ...
def validate_actual_delta_integrity(delta: ActualDelta) -> None: ...
```

ActualChange instance identity payload is:

```text
semantic_id if available
else (host_entity_ref.document_id, host_entity_ref.native_id)
```

Never hash `native_type` as authorization identity. ActualDelta hash includes sorted `actual_change_hash` values and exact Step32 lineage/revisions; excludes ids/timestamps/hash itself.

- [ ] **3.5 Build public-API-only Step33 fixtures**

`tests/execution_reconciliation/conftest.py` builds:

1. a real single-Slice Step28→29→30 transaction with a **test-owned** `SEMANTIC_ASSERTIONS_V1` canonical contract and no dependency edges;
2. a real two-Slice plan using existing Step30 transaction semantics for Saga tests;
3. a real Step32 admitted authority through public Gateway APIs;
4. hash-correct ActualChange/ActualDelta helper constructors.

Do not modify upstream test fixtures for sharing convenience.

- [ ] **3.6 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_actual_delta.py
pytest -q tests/execution_planning/test_step30_integrity.py
ruff check platform/execution_reconciliation/src/design_execution_reconciliation \
  tests/execution_reconciliation/test_step33_actual_delta.py
git diff --check
git add platform/execution_reconciliation pyproject.toml tests/execution_reconciliation
git commit -m "feat(step33): add authoritative actual delta contracts"
```

---

## Task 4: Implement MODIFY/DELETE ScopeComparator semantics

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/scope_comparator.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_step33_scope_existing.py`

- [ ] **4.1 RED: freeze input/integrity precedence**

```text
bad ActualDelta hash
→ ACTUAL_DELTA_INTEGRITY_INVALID
valid delta + Step32 authority mismatch
→ RECONCILIATION_LINEAGE_MISMATCH
bad Step28 Boundary
→ SCOPE_COMPARISON_INVALID + upstream SCOPE_INTEGRITY_INVALID
bad Step30 Slice
→ SCOPE_COMPARISON_INVALID + upstream Step30 code
```

Also enforce exact authority joins for grant/binding/slice/changeset/scope/host instance, Slice document == Delta document, and optional `source_execution_unit_hash` membership in the exact Slice.

- [ ] **4.2 RED: MODIFY**

Prove:

- explicit matching ExistingEntityRule + allowed aspect → WITHIN_SCOPE;
- multiple Slice-authorized rules for same entity union allowed aspects deterministically;
- entity outside Slice rules → SCOPE_BREACH / ENTITY_OUTSIDE_SCOPE;
- unauthorized aspect → SCOPE_BREACH / ASPECT_OUTSIDE_SCOPE;
- predicate selector fields map only to semantic ActualChange context;
- Host native metadata cannot affect comparison.

- [ ] **4.3 RED: DELETE with synthetic final Boundary**

Current Step28 planner intentionally rejects non-empty existence effects. Do not change it. Build a valid test-only `ApprovalScopeDefinition` directly from public Step28 contracts, compute public `scope_body_hash`, then `bind_changeset()`.

Prove matching Slice-authorized DeletionRule passes; Boundary-only/non-Slice rule and no rule both breach with `DELETION_FORBIDDEN`.

- [ ] **4.4 GREEN: contracts/hash/comparator**

Add frozen result types:

```text
ScopeComparisonStatus = WITHIN_SCOPE | SCOPE_BREACH
ScopeMatch(actual_change_hash, rule_id)
ScopeViolation(code, actual_change_hash, rule_id?)
ScopeComparisonRequest(authority, delta, boundary, execution_slice)
ScopeComparisonResult(status, hashes, matched_changes, violations, comparison_hash)
```

Private `_SelectorContext` maps:

```text
SEMANTIC_ID     -> semantic_id
CANONICAL_KIND  -> canonical_kind
SOURCE_ENTITY   -> source_entity
DERIVATION_RULE -> derivation_rule
```

Support only Step28 EQ/IN semantics. Explicit entity selectors compare against context `semantic_id`.

`ScopeComparator.compare()` calls public `validate_approval_scope_boundary()` and `validate_execution_slice_integrity()`. Valid inputs with unauthorized effects return a hashed SCOPE_BREACH result; integrity/lineage faults raise `ReconciliationError`.

- [ ] **4.5 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_scope_existing.py
pytest -q tests/approval_scope/test_step28_integrity.py tests/execution_planning/test_step30_integrity.py
ruff check platform/execution_reconciliation/src/design_execution_reconciliation tests/execution_reconciliation
git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): compare actual existing-entity scope"
```

---

## Task 5: Implement deterministic CREATE matching and capacity allocation

**Files:**
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/scope_comparator.py`
- Create: `tests/execution_reconciliation/test_step33_scope_existence.py`

- [ ] **5.1 RED: staged CreationRule matching**

Using test-only valid Step28 creation Boundaries, prove:

- canonical operation/kind/source/derivation/count all satisfied → pass;
- operation mismatch → CREATION_OPERATION_FORBIDDEN;
- kind mismatch → CREATION_KIND_FORBIDDEN;
- explicit/predicate source mismatch → CREATION_SOURCE_FORBIDDEN;
- source predicate CANONICAL_KIND consumes `source_canonical_kind`;
- missing required source semantic evidence fails closed, never D5 lookup;
- required derivation mismatch → CREATION_DERIVATION_MISMATCH;
- rule absent from current Slice cannot authorize;
- `max_count` overflow → CREATION_COUNT_EXCEEDED.

Creation source-selector context is frozen to:

```text
semantic_id     = change.source_semantic_id
canonical_kind  = change.source_canonical_kind
source_entity   = change.source_semantic_id
derivation_rule = change.derivation_rule
```

- [ ] **5.2 RED: overlapping rules require deterministic global allocation**

Construct at least three creates + two overlapping rules where input-order greedy assignment can fail even though a full capacity-respecting assignment exists. Reverse rule/change ordering and prove identical matches + comparison hash.

Canonical search order:

```text
rule_id
stable instance key
actual_change_hash
```

- [ ] **5.3 GREEN: deterministic backtracking allocation**

Filter candidate rules in stages:

```text
Slice-authorized
→ canonical_operation
→ entity kind
→ source selector
→ required derivation
→ global capacity allocation
```

Use sorted deterministic backtracking; stop at first lexicographically canonical complete assignment. If eligibility exists but no complete assignment because capacity is exhausted, emit CREATION_COUNT_EXCEEDED.

- [ ] **5.4 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_scope_existence.py
pytest -q tests/execution_reconciliation/test_step33_scope_existing.py
pytest -q tests/approval_scope
git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): enforce deterministic creation scope"
```

---

## Task 6: Freeze VerificationEvidenceBundle intrinsic integrity and hashes

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_step33_verification_evidence.py`

- [ ] **6.1 RED: immutable evidence bodies**

Intrinsic bundle tests prove:

- `H(contract_body) == contract_ref` is mandatory;
- duplicate contract_ref with different body → VERIFY_CONTRACT_MISMATCH;
- subject evidence unique by `(snapshot_id, snapshot_hash, semantic_id)` within post/baseline sets;
- duplicate semantic subject with different evidence for the same snapshot fails;
- contract/property/relationship/constraint mappings are defensive immutable copies;
- subject evidence order and contract evidence order do not change bundle hash;
- changing baseline/post snapshot/projection/evidence changes bundle hash.

Cross-object joins to ChangeSet/Boundary/ActualDelta happen in Task 7, not in the intrinsic hash validator.

- [ ] **6.2 GREEN: evidence contracts**

Create frozen:

```text
VerificationContractEvidence(contract_ref, contract_body)
VerificationSubjectEvidence(
  semantic_id, canonical_kind,
  properties, placement, geometry_evidence,
  relationships, constraints, classification,
  evidence_aspects,
  snapshot_id, snapshot_hash, projection_ref
)
VerificationEvidenceBundle(
  evidence_bundle_id,
  changeset_hash, execution_slice_hash, actual_delta_hash,
  semantic_environment_ref,
  post_execution_snapshot_ref, post_execution_projection_ref,
  base_host_revision,
  baseline_snapshot_ref?, baseline_projection_ref?,
  contract_evidence, subject_evidence, baseline_subject_evidence,
  evidence_bundle_hash
)
```

Use `MappingProxyType(deepcopy(dict(...)))` for nested mappings; normalize tuples deterministically.

- [ ] **6.3 GREEN: public hash/intrinsic validator**

```python
def compute_verification_evidence_bundle_hash(bundle: VerificationEvidenceBundle) -> str: ...
def validate_verification_evidence_bundle_integrity(bundle: VerificationEvidenceBundle) -> None: ...
```

The intrinsic validator recomputes contract refs and the complete bundle hash. It does not need a ChangeSet or ActualDelta.

- [ ] **6.4 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_verification_evidence.py
pytest -q tests/execution_reconciliation/test_step33_actual_delta.py
ruff check platform/execution_reconciliation/src/design_execution_reconciliation tests/execution_reconciliation
git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): bind immutable verification evidence"
```

---

## Task 7: Implement deterministic `SEMANTIC_ASSERTIONS_V1` SemanticVerifier

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/verifier.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_step33_verifier.py`

- [ ] **7.1 RED: exact request joins before evaluation**

Freeze request:

```text
SemanticVerificationRequest(
  admitted_execution_authority,
  approval_scope_boundary,
  canonical_changeset,
  actual_delta,
  validation_tasks,
  verification_evidence_bundle,
  verified_at
)
```

Tests prove this order:

1. ActualDelta intrinsic integrity;
2. exact Step32 authority ↔ ActualDelta lineage;
3. public Step28 Boundary integrity;
4. public `validate_changeset_integrity(changeset, boundary)`;
5. requested tasks are exact full values from `changeset.validation_tasks` (no invented/mutated task);
6. bundle intrinsic integrity;
7. bundle ChangeSet/Slice/ActualDelta hashes exact;
8. SemanticEnvironment exact by `(environment_id, content_hash)`;
9. post snapshot id/hash/projection refs consistent with every post subject evidence;
10. post snapshot document matches Delta and `base_host_revision == str(actual_delta.revision_after)`;
11. contract lookup/hash;
12. baseline requirements if a requested executable assertion uses DELTA_EQUALS_ARGUMENT.

- [ ] **7.2 RED: exact baseline binding for delta assertions**

Prove:

- baseline absent for DELTA → EVIDENCE_INSUFFICIENT / REQUIRED_BASELINE_MISSING;
- baseline snapshot id/hash/document/environment exactly match `canonical_changeset.planning_snapshot_ref`;
- baseline subject evidence snapshot id/hash + projection match baseline refs;
- missing baseline subject/path → insufficiency, not mismatch;
- baseline may be absent when no delta assertion exists.

- [ ] **7.3 RED: fixed provider-neutral operators**

Use a test-owned Step29 canonical contract with `SEMANTIC_ASSERTIONS_V1`; do not edit production canonical definitions. Cover all operators:

```text
EXISTS
NOT_EXISTS
EQUALS_LITERAL
EQUALS_ARGUMENT
DELTA_EQUALS_ARGUMENT
RELATIONSHIP_EXISTS
CLASSIFICATION_IS
```

Canonical assertion shapes:

```json
{"subjects":{"from_argument":"targets"},"path":"properties.thickness","operator":"EXISTS"}
{"subjects":{"from_argument":"targets"},"path":"properties.thickness","operator":"EQUALS_LITERAL","value":0.3}
{"subjects":{"from_argument":"targets"},"path":"properties.thickness","operator":"EQUALS_ARGUMENT","argument":"thickness"}
{"subjects":{"from_argument":"targets"},"path":"placement.x","operator":"DELTA_EQUALS_ARGUMENT","argument":"dx"}
{"subjects":{"from_argument":"targets"},"operator":"RELATIONSHIP_EXISTS","relationship":{"type":"HOSTED_BY","target":"WALL-001"}}
{"subjects":{"from_argument":"targets"},"operator":"CLASSIFICATION_IS","value":"ifc:IfcWall"}
```

Only `subjects.from_argument` is supported in v0.6. Unsupported subject selectors/contracts return EVIDENCE_INSUFFICIENT + VERIFY_CONTRACT_UNSUPPORTED, never an operation-specific branch.

- [ ] **7.4 RED: status aggregation**

- all assertions true → task PASSED;
- wrong value → FAILED + EXPECTED_VALUE_MISMATCH;
- required post subject/path/aspect missing → EVIDENCE_INSUFFICIENT + REQUIRED_FIELD_MISSING;
- unsupported `{"type":"HOST_READ_BACK"}` cannot PASS;
- any FAILED dominates aggregate;
- otherwise any insufficiency → aggregate EVIDENCE_INSUFFICIENT.

`SemanticVerifier` may evaluate an explicitly provided ChangeSet-task subset; **it does not authorize Slice success**. Task 8/9 binds the complete required subset to each Slice, and Service/Store reject omissions.

- [ ] **7.5 GREEN: generic evaluator + immutable result hashes**

Resolve canonical operation task to exactly one ChangeSet operation by:

```text
canonical_operation_ref == "<operation>@<version>"
subject_semantic_ids == operation.targets
```

Use generic dot-path lookup over mappings/attributes. No Host/product/canonical-operation branch.

Comparison rules:

- exact canonical equality by default;
- optional absolute tolerance only for numeric canonical values;
- no unit conversion;
- if values are `{value, unit}` and tolerance has unit, units must agree;
- DELTA computes canonical `post - baseline`.

Add frozen `VerificationStatus`, `ValidationTaskResult`, `SemanticVerificationResult` plus:

```text
compute_validation_task_result_hash
compute_semantic_verification_hash
SemanticVerifier.verify(request)
```

Audit `verified_at` is not part of semantic verification hash.

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

## Task 8: Build immutable Saga definition, Slice DAG/order, and required ValidationTask assignments

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/saga.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_step33_saga_definition.py`

- [ ] **8.1 RED: exact Step28→30 lineage**

Saga creation calls public validators and proves:

- invalid Boundary/ChangeSet/ExecutionPlan → SAGA_INTEGRITY_INVALID + structured upstream code;
- ChangeSet/Boundary/Plan hash joins exact;
- plan approved scope == exact Boundary;
- planning SemanticEnvironment exact;
- definition derives all Slices/dependencies from the validated plan; caller cannot provide an arbitrary Slice list.

- [ ] **8.2 RED: project unit dependencies to Slice DAG**

Map every Step30 unit id to its Slice. Cross-Slice unit dependencies become one `SliceDependency(predecessor_slice_hash, successor_slice_hash, sorted reason_refs)`; same-Slice dependencies produce no self edge. Reject a projected cycle.

- [ ] **8.3 RED: deterministic global sequential order**

Use Kahn topological sort with `execution_slice_hash` as tie-break among simultaneously eligible roots. Prove input tuple reordering does not change ordered Slice hashes or definition hash.

- [ ] **8.4 RED: every Step29 ValidationTask assigns exactly once**

Add:

```text
SliceValidationAssignment(
  execution_slice_hash,
  validation_task_ids
)
```

Derivation:

- CANONICAL_OPERATION: resolve exact ChangeSet operation from operation ref + exact subjects, then locate its ExecutionUnit/Slice by `source_operation_id`;
- DEPENDENCY_VERIFICATION: resolve exact `SemanticImpactEvidence` using `dependency_ref` + affected subject; if affected semantic id is a target of exactly one ChangeSet operation, use that operation's Slice; otherwise locate the source semantic id's operation/Slice;
- zero/multiple resolution → SAGA_INTEGRITY_INVALID;
- every ValidationTask id appears in exactly one assignment;
- assignments sort by Slice hash and task id;
- `saga_definition_hash` changes if assignment changes.

This assignment is the fail-closed coverage barrier that prevents caller task omission.

- [ ] **8.5 GREEN: definition contracts/builder/hash**

Create frozen:

```text
SliceDependency
SliceValidationAssignment
ExecutionSagaDefinition(
  saga_id,
  changeset_hash,
  approved_scope_hash,
  semantic_environment_ref,
  execution_plan_hash,
  ordered_slice_hashes,
  slice_dependencies,
  slice_validation_assignments,
  saga_definition_hash
)
ExecutionSagaBuilder.build(changeset, boundary, execution_plan)
```

Freeze `saga_id = SG-<saga_definition_hash[:12]>`.

- [ ] **8.6 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_saga_definition.py
pytest -q tests/execution_planning
pytest -q tests/approval_scope/test_step28_integrity.py tests/changeset/test_step29_integrity.py
git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): freeze deterministic saga definitions"
```

---

## Task 9: Implement CAS Saga Store, sequential admission, and successful reconciliation

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/store.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Create: `tests/execution_reconciliation/test_step33_saga_store.py`

- [ ] **9.1 RED: lifecycle contracts**

Saga states:

```text
READY EXECUTING PARTIALLY_COMMITTED SUCCEEDED
COMPENSATING COMPENSATED COMPENSATION_FAILED FAILED
```

Slice states:

```text
NOT_STARTED ADMISSION_RESERVED ADMITTED HOST_COMMITTED RECONCILING
SUCCEEDED FAILED_BEFORE_COMMIT VERIFY_FAILED SCOPE_BREACH BLOCKED
COMPENSATED COMPENSATION_FAILED
```

`SliceReconciliationState` carries `execution_slice_hash`, `sequence_index`, optional Grant/ActualDelta/scope/verification hashes, and explicit reserved/admitted/committed/reconciled timestamps. `StoredExecutionSaga` carries immutable definition, `saga_revision`, state, ordered Slice states, compensation refs.

- [ ] **9.2 RED: create/reserve one global active Slice**

Prove:

- create revision 0, READY, all NOT_STARTED;
- same definition replay idempotent; same saga id/different definition conflicts;
- only lowest canonical eligible sequence can reserve;
- all dependency predecessors must be SUCCEEDED;
- while any Slice is RESERVED/ADMITTED/HOST_COMMITTED/RECONCILING no other Slice reserves;
- 32 concurrent reserve calls yield one logical reservation;
- stale expected revision → SAGA_CONFLICT.

- [ ] **9.3 RED: reserve→Step32 admission crash recovery**

With real Step32 service/store:

```text
Step33 reserve
→ Step32 admit
→ lose Step33 confirmation
→ retry Step32 same grant gets same authority/original admitted_at
→ Step33 confirm same authority
```

Same confirmation evidence recovers; different Grant/slice/host evidence conflicts.

- [ ] **9.4 RED: successful reconciliation path with complete task coverage**

```text
ADMITTED
→ record_host_commit
→ HOST_COMMITTED
→ begin_reconciliation
→ RECONCILING
→ record_scope_result(WITHIN_SCOPE)
→ record_verification_result(PASSED with exactly assigned task ids)
→ SUCCEEDED
```

Store rejects:

- verification before persisted WITHIN_SCOPE;
- verification whose ActualDelta hash differs from committed/scope evidence;
- PASSED result missing any `SliceValidationAssignment.validation_task_id`;
- result containing a task assigned to another Slice;
- FAILED/INSUFFICIENT result becoming SUCCEEDED.

All Slices SUCCEEDED → Saga SUCCEEDED; then and only then terminal success.

- [ ] **9.5 GREEN: Protocol + RLock reference implementation**

`ExecutionSagaStore` includes atomic:

```text
create_saga
get_saga
reserve_slice_admission
confirm_slice_admitted
record_host_commit
begin_reconciliation
record_scope_result
record_verification_result
```

Every mutating method accepts expected `saga_revision` (except idempotent creation) and explicit timestamps where applicable. Same transition/same evidence returns existing logical state; different evidence or stale revision conflicts.

- [ ] **9.6 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_saga_store.py
pytest -q tests/gateway_authorization/test_step32_admission_and_revocation.py
ruff check platform/execution_reconciliation/src/design_execution_reconciliation tests/execution_reconciliation
git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): persist sequential saga reconciliation"
```

---

## Task 10: Implement partial failures, atomic blocking, and governed compensation evidence

**Files:**
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/contracts.py`
- Extend: `platform/execution_reconciliation/src/design_execution_reconciliation/hashing.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/saga.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/store.py`
- Create: `tests/execution_reconciliation/test_step33_failure_and_compensation.py`

- [ ] **10.1 RED: pre-commit failure**

```text
first Slice fails before Host commit + no earlier committed/succeeded Slice
→ Slice FAILED_BEFORE_COMMIT
→ Saga FAILED
```

If any earlier Slice SUCCEEDED/committed:

```text
later pre-commit failure
→ PARTIALLY_COMMITTED
→ all remaining NOT_STARTED atomically BLOCKED
```

- [ ] **10.2 RED: committed failures**

```text
HOST_COMMITTED + SCOPE_BREACH
→ Slice SCOPE_BREACH
→ PARTIALLY_COMMITTED
→ remaining BLOCKED
→ semantic verification success gate prohibited
```

```text
HOST_COMMITTED + WITHIN_SCOPE + verifier FAILED/INSUFFICIENT
→ Slice VERIFY_FAILED
→ PARTIALLY_COMMITTED
→ remaining BLOCKED
```

Even a first-Slice committed failure is partial because a Host side effect exists.

- [ ] **10.3 RED: provider-neutral CompensationProposal**

Step33 does not infer an inverse operation. Freeze:

```text
CompensationProposalRequest(
  source_saga_id,
  failed_slice_hash,
  desired_recovery_effects[]
)

CompensationProposal(
  compensation_proposal_id,
  source_saga_id,
  source_changeset_hash,
  failed_slice_hash,
  committed_slice_hashes,
  actual_delta_refs,
  verification_failure_refs,
  scope_breach_refs,
  desired_recovery_effects,
  proposal_hash
)
```

`ExecutionSagaPlanner.create_compensation_proposal()` validates all source evidence against durable Saga state, then hashes caller/current-semantic-planner supplied **canonical recovery effects**. No Host command/native undo/original Grant is part of this contract.

- [ ] **10.4 RED: compensation lifecycle truth**

Use:

```text
CompensationExecutionRef(
  compensation_proposal_hash,
  compensating_changeset_hash,
  succeeded,
  completed_at
)
```

Prove PARTIALLY_COMMITTED→COMPENSATING only with exact proposal; success→COMPENSATED (never SUCCEEDED); failure→COMPENSATION_FAILED terminal; same evidence replay idempotent; different compensating ChangeSet/result→COMPENSATION_CONFLICT; no automatic recovery loop from COMPENSATION_FAILED.

- [ ] **10.5 GREEN + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_failure_and_compensation.py
pytest -q tests/execution_reconciliation/test_step33_saga_store.py
git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): add auditable partial failure compensation state"
```

---

## Task 11: Implement public `ExecutionReconciliationService` and cross-step integration

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/service.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Extend: `tests/execution_reconciliation/conftest.py`
- Create: `tests/execution_reconciliation/test_step33_service.py`

- [ ] **11.1 RED: facade boundaries**

Facade methods:

```text
create_saga(changeset, boundary, execution_plan)
reserve_slice_admission(...)
confirm_slice_admitted(...)
record_host_commit(...)
begin_reconciliation(...)
compare_scope(request)
record_scope_result(...)
verify_semantics(saga_id, slice_hash, request)
record_verification_result(...)
fail_slice_before_commit(...)
begin_compensation(...)
record_compensation_result(...)
get_saga(...)
```

`verify_semantics(saga_id, slice_hash, request)` loads the durable Saga and requires:

```text
request.validation_tasks ids
== exact SliceValidationAssignment.validation_task_ids
```

before calling pure `SemanticVerifier`. This is the task-omission barrier.

The facade MUST NOT hide Host execution, Step32 Grant admission, D5 reconstruction, Semantic Service lookup, or compensation ChangeSet creation inside a convenience transaction.

- [ ] **11.2 RED: complete one-Slice happy path**

Using real public Steps 28–32 + Step33:

```text
create Saga
→ reserve
→ real Step32 admit
→ confirm
→ record valid ActualDelta commit
→ begin reconciliation
→ compare/persist WITHIN_SCOPE
→ supply snapshot-bound evidence
→ verify exact assigned tasks PASSED
→ persist verification
→ Slice SUCCEEDED
→ Saga SUCCEEDED
```

Assert every authority/delta/scope/evidence/verification hash joins exactly.

- [ ] **11.3 RED: caller cannot omit a required task**

For a Saga Slice with assigned tasks, pass an empty/proper subset request to `verify_semantics`; expect VERIFY_INPUT_INVALID/SAGA_INTEGRITY_INVALID as frozen by service mapping, and prove Store cannot later accept that result as Slice success.

- [ ] **11.4 RED: two-Slice partial failure path**

```text
A fully SUCCEEDED
→ B reserve/admit/commit
→ B scope breach or verify failure
→ PARTIALLY_COMMITTED
→ remaining BLOCKED
→ provider-neutral CompensationProposal sealable
```

This is Step33's deterministic precursor to Phase H Step37; no real Host required here.

- [ ] **11.5 RED: response-loss/replay**

Simulate lost response after each Store mutation; same evidence recovers durable state, different evidence conflicts, and service never uses check-then-write to create a second active Slice.

- [ ] **11.6 GREEN: thin composition only**

Service composes `ExecutionSagaBuilder`, `ScopeComparator`, `SemanticVerifier`, `ExecutionSagaPlanner`, and Store. It maps public upstream errors to stable Step33 errors with `upstream_code`; Store remains owner of atomic mutations.

- [ ] **11.7 Verify + commit**

```bash
pytest -q tests/execution_reconciliation/test_step33_service.py
pytest -q tests/execution_reconciliation
pytest -q tests/gateway_authorization
pytest -q tests/execution_planning
git add platform/execution_reconciliation tests/execution_reconciliation
git commit -m "feat(step33): integrate execution reconciliation service"
```

---

## Task 12: Add architecture guards, Step33 CI, full regressions, and exact-HEAD proof

**Files:**
- Create: `tests/execution_reconciliation/test_step33_architecture.py`
- Create: `.github/workflows/step33-execution-reconciliation.yml`
- Modify: `docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md` only after exact final verification succeeds

- [ ] **12.1 RED: architecture guards**

AST/source tests reject Step33 production coupling to:

```text
AutoCAD/AUTOCAD/autocad_sidecar
Revit/REVIT
Tekla/TEKLA
HostCommand
native transaction/undo/rollback dispatch
psycopg/asyncpg/redis/boto3/DynamoDB
```

Public `HostEntityRef` is allowed only as opaque provenance/instance identity. Add a source/AST guard that `scope_comparator.py` never reads `host_entity_ref.native_type` for authorization.

Reject domain wall clocks:

```text
datetime.now
datetime.utcnow
time.time
```

Reject private upstream production imports:

```text
design_approval_scope.hashing
design_changeset.builder
design_execution_planning.planner
design_gateway_authorization.store
design_gateway_authorization.service
semantic_runtime.freshness
```

Require public validator imports where ownership needs them:

```text
validate_approval_scope_boundary
validate_changeset_integrity
validate_execution_slice_integrity
validate_execution_plan_integrity
```

- [ ] **12.2 Freeze workflow path boundary**

Exactly:

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

PR diff gate runs when `github.head_ref == 'feat/step33-execution-reconciliation'`.

- [ ] **12.3 Build CI from Step32 verification stack + Step33 editable**

Install the Step32 stack unchanged plus:

```text
-e platform/execution_reconciliation
```

Required CI matrix:

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

- [ ] **12.4 RED/GREEN workflow architecture test**

`test_step33_architecture.py` parses workflow and proves exact path filters, Step32 stack + Step33 install, required commands, Ruff targets, and full repository importlib test.

- [ ] **12.5 Fresh final verification session**

Run all commands below together and inspect exit status/output:

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
git diff --name-only cef76e111f74d10f063eedfebc7efc0d805caefa...HEAD
```

Every production/test path must lie inside the frozen Step33 boundary. No forbidden upstream production file may appear.

- [ ] **12.6 Only after all green: mark design implemented with exact evidence**

Record exact final implementation commit SHA and the commands actually run. Do not mark implemented from stale CI or an earlier commit.

- [ ] **12.7 Commit architecture/CI/status**

```bash
git add .github/workflows/step33-execution-reconciliation.yml \
  tests/execution_reconciliation/test_step33_architecture.py \
  docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md
git commit -m "test(step33): enforce reconciliation architecture and verification"
```

- [ ] **12.8 Fresh GitHub Actions proof on exact final branch HEAD**

Inspect the Step33 workflow run for the exact final HEAD. Completion requires `completed/success` for all required jobs/steps. If CI fails, return to TDD, fix, commit, and rerun; never report completion from stale evidence.

---

## Implementation Review Checkpoints

After each task:

1. Capture the focused RED failure before production implementation.
2. Implement only the minimum GREEN behavior for that task.
3. Rerun focused tests and owner regression suites for every changed production package.
4. Run `git diff --check` and inspect `git diff --stat` / changed paths.
5. Commit the task boundary before moving on.

At Tasks 5, 9, and 10, review determinism/transactions, not only final values:

- CREATE allocation is invariant to input/container ordering and respects every capacity.
- Saga eligibility inspection + reservation mutation occur inside one atomic Store operation.
- No service-side check-then-write substitutes for CAS.
- Same transition/evidence recovery returns already committed evidence; different evidence conflicts.
- Partial failure and remaining-Slice blocking happen atomically.
- Compensation never calls native rollback and never mutates original Grant authority.

At Tasks 6–8, review evidence/coverage integrity:

- every contract body is content-addressed by exact Step29 `contract_ref`;
- post evidence is bound to exact post Host revision and SemanticEnvironment;
- DELTA assertions are bound to exact pre-write planning baseline;
- every ChangeSet ValidationTask is assigned to exactly one Slice;
- Slice success requires exactly that complete assignment;
- missing evidence/task is failure/insufficiency, never inferred success;
- verifier has no Host/operation-specific semantic branch.

## Definition of Done

Step33 is complete only when fresh exact-HEAD evidence proves:

```text
Step30 ExecutionPlan reconstructs its existing immutable plan identity
no Step28–32 existing semantic hash algorithm changed

ActualDelta is deterministic, provider-neutral, authoritative
Host native_type/product metadata cannot alter scope authorization
bad lineage fails before scope evaluation

MODIFY allowed-aspect containment is exact
DELETE needs explicit current-Slice deletion authority
CREATE operation/kind/source/derivation/count are all enforced
overlapping CREATE allocation is deterministic
ActualDelta outside scope => SCOPE_BREACH + remaining Slice block

ValidationTask contract bodies are content-addressed exactly
post evidence pins exact post revision/environment
DELTA pins exact pre-write baseline evidence
unsupported/insufficient verification cannot PASS
wrong in-scope result => VERIFY_FAILED, not SCOPE_BREACH
Host success/self-verification cannot bypass SemanticVerifier

every Step29 ValidationTask assigns exactly once to a Saga Slice
caller cannot omit required Slice verification tasks
Saga definition binds exact Boundary + ChangeSet + complete ExecutionPlan
cross-Slice dependency projection/order is deterministic
independent roots still use one global sequential order
at most one Slice is reserved/active side-effecting
ADMISSION_RESERVED closes Step33→Step32 crash window
same evidence replay is idempotent; different evidence conflicts
HOST_COMMITTED is never SUCCEEDED

first no-side-effect pre-commit failure => FAILED
prior/committed side effects + later failure => PARTIALLY_COMMITTED
committed SCOPE_BREACH/VERIFY_FAILED => PARTIALLY_COMMITTED
remaining Slices atomically BLOCKED

compensation is provider-neutral auditable recovery intent
actual compensation re-enters normal ChangeSet/Approval/Grant workflow externally
original Grant never auto-authorizes compensation
successful compensation => COMPENSATED, never SUCCEEDED
failed compensation => COMPENSATION_FAILED, no automatic loop

Step33 has no Host product/provider/database-vendor execution coupling
no direct domain wall-clock reads
all Step28–32 regressions pass
all Step33 tests pass
Ruff passes
full repository tests pass
fresh GitHub Actions succeeds on exact final Step33 HEAD
```
