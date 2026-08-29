# Step 28 ApprovalScopeBoundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the provider-neutral Step28 closed-world `ApprovalScopeDefinition` planner, deterministic hashing, and final ChangeSet-hash binding exactly as frozen in the approved design.

**Architecture:** Add an independent `platform/approval_scope` package that consumes only public `design_impact` value contracts plus a small `CanonicalEffectEvidence` projection supplied by orchestration. Keep contracts, canonical hashing, and admission/planning separate. Step28 v1 supports existing-entity aspect scope only; create/delete DTOs are frozen but non-empty requests fail closed until typed canonical existence-effect authority exists.

**Tech Stack:** Python 3.11+, stdlib `dataclasses`/`enum`/`hashlib`/`json`, pytest 8+, existing `design_impact` public contracts.

**Spec:** `docs/superpowers/specs/2026-08-29-step28-approval-scope-boundary-design.md`

## Global Constraints

- Do not modify the legacy mutable `platform/changeset` production model.
- `design_approval_scope` may import public `design_impact` values only; it must not import Host product packages, provider execution contracts, `HostCommand`, policy, approval, grant, or Step23 orchestrator implementation classes.
- Scope is closed-world / deny-by-default.
- Machine effect authority is the intersection of Step23 `CanonicalEffectEvidence`, carried-forward Step27 `IntentBoundary`, and explicit Step28 direct-effect/recipe evidence.
- `dependency_ref` is the authoritative recipe binding key; `rule_ref` is optional provenance except when binding a deterministic propagation bundle.
- Effect-bearing predicted impacts are determined only by `requires_verification` or membership in a deterministic propagation bundle; do not infer from propagation action names.
- Non-empty create/delete requests fail `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED` in v1.
- `execution_slice_scopes` are declarative scope rules, never concrete future slice ids.
- `scope_body_hash` is deterministic canonical JSON + SHA-256 and excludes opaque construction ids from semantic identity.
- Final `scope_hash = SHA256(canonical_json({"scope_body_hash": ..., "changeset_hash": ...}))`.
- Final ChangeSet binding accepts only lowercase 64-hex hashes and cannot widen the frozen scope body.
- Preserve Step23–27 regression behavior.

---

### Task 1: Package wiring and immutable scope contracts

**Files:**
- Create: `platform/approval_scope/src/design_approval_scope/contracts.py`
- Create: `platform/approval_scope/src/design_approval_scope/__init__.py`
- Modify: `pyproject.toml`
- Test: `tests/approval_scope/test_step28_contracts.py`

**Interfaces:**
- Consumes: `design_impact.IntentBoundary`, `design_impact.ImpactAnalysis` only at planner level; contracts remain provider-neutral.
- Produces: `ApprovalScopeError`, `CanonicalAspect`, predicate enums/types, selectors, `CanonicalEffectEvidence`, `DirectEntityEffect`, `ScopeEffectRecipe`, `ExistingEntityRule`, frozen `CreationRule`/`DeletionRule`, `ExecutionSliceScopeRule`, `ApprovalScopeDefinition`, `ApprovalScopeBoundary`, `ApprovalScopePlanRequest`.

- [ ] **Step 1: Write failing contract tests**

Create `tests/approval_scope/test_step28_contracts.py` with focused tests proving: canonical aspect enum rejects native values; selectors require exactly one of entities/predicate; predicate AST accepts only non-empty conjunctions with `EQ`/`IN` cardinality; values normalize deterministically; direct effects and recipes require non-empty aspect sets; boundary/hash-bearing DTOs are immutable/value-oriented; creation/deletion DTOs exist but carry no self-authorizing behavior.

Example API assertions:

```python
import pytest
from design_approval_scope import (
    CanonicalAspect,
    EntityPredicate,
    EntitySelector,
    PredicateField,
    PredicateOperator,
    PredicateTerm,
)


def test_selector_requires_exactly_one_selector_form():
    with pytest.raises(ValueError):
        EntitySelector()
    with pytest.raises(ValueError):
        EntitySelector(entities=("WALL-001",), predicate=EntityPredicate(all_of=(
            PredicateTerm(PredicateField.SEMANTIC_ID, PredicateOperator.EQ, ("WALL-001",)),
        )))


def test_predicate_eq_requires_exactly_one_value():
    with pytest.raises(ValueError):
        PredicateTerm(PredicateField.SEMANTIC_ID, PredicateOperator.EQ, ("A", "B"))


def test_native_aspect_is_not_a_canonical_aspect():
    with pytest.raises(ValueError):
        CanonicalAspect("AutoCAD.Handle")
```

- [ ] **Step 2: Run RED test**

Run:

```bash
pytest tests/approval_scope/test_step28_contracts.py -q
```

Expected: collection/import failure because `design_approval_scope` does not exist yet.

- [ ] **Step 3: Implement minimal immutable contracts**

Implement frozen/slots dataclasses and enums. Normalize text by stripping, normalize set-like tuple fields by sorting and deduplicating where semantically appropriate, reject empty selectors/aspect lists, and use only this canonical aspect vocabulary:

```python
class CanonicalAspect(str, Enum):
    IDENTITY = "IDENTITY"
    PROPERTIES = "PROPERTIES"
    PLACEMENT = "PLACEMENT"
    GEOMETRY = "GEOMETRY"
    SPATIAL = "SPATIAL"
    CONNECTIVITY = "CONNECTIVITY"
    RELATIONSHIPS = "RELATIONSHIPS"
    CONSTRAINTS = "CONSTRAINTS"
    CLASSIFICATION = "CLASSIFICATION"
```

Define stable error codes through `ApprovalScopeError(code, message)`.

Update `pyproject.toml` `pythonpath` with:

```toml
"platform/approval_scope/src",
```

- [ ] **Step 4: Run GREEN contract tests**

Run:

```bash
pytest tests/approval_scope/test_step28_contracts.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml platform/approval_scope/src/design_approval_scope tests/approval_scope/test_step28_contracts.py
git commit -m "feat(step28): add approval scope contracts"
```

---

### Task 2: Deterministic semantic hashing and pure ChangeSet binding

**Files:**
- Create: `platform/approval_scope/src/design_approval_scope/hashing.py`
- Modify: `platform/approval_scope/src/design_approval_scope/__init__.py`
- Test: `tests/approval_scope/test_step28_hashing.py`

**Interfaces:**
- Consumes: normalized contract values from Task 1.
- Produces: `compute_scope_body_hash(...)`, `bind_changeset(scope_definition, changeset_hash, scope_id) -> ApprovalScopeBoundary`.

- [ ] **Step 1: Write failing hashing tests**

Tests must prove equivalent list/set ordering produces the same `scope_body_hash`; changing an allowed aspect, canonical operation version/effects, intent boundary body, impact fingerprint, planning snapshot, snapshot set, or semantic environment changes it; opaque `rule_id`/`slice_scope_rule_id` values do not perturb the semantic hash; lowercase SHA-256 ChangeSet hashes are required; same scope + different ChangeSet hash yields different `scope_hash`; bind preserves every normalized rule body and accepts no replacement scope lists.

- [ ] **Step 2: Run RED hashing tests**

```bash
pytest tests/approval_scope/test_step28_hashing.py -q
```

Expected: import/attribute failure because hashing functions do not exist.

- [ ] **Step 3: Implement canonical hash helpers**

Use only deterministic JSON:

```python
def _sha256_json(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
```

Build semantic payloads from normalized rule content, replacing cross-references to construction ids with content fingerprints. `bind_changeset` validates `re.fullmatch(r"[0-9a-f]{64}", changeset_hash)` and computes final `scope_hash` from only `scope_body_hash` + `changeset_hash`.

- [ ] **Step 4: Run GREEN hashing tests**

```bash
pytest tests/approval_scope/test_step28_hashing.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/approval_scope/src/design_approval_scope tests/approval_scope/test_step28_hashing.py
git commit -m "feat(step28): add deterministic scope hashing"
```

---

### Task 3: Closed-world planner core and authority intersection

**Files:**
- Create: `platform/approval_scope/src/design_approval_scope/planner.py`
- Modify: `platform/approval_scope/src/design_approval_scope/__init__.py`
- Test: `tests/approval_scope/test_step28_planner.py`

**Interfaces:**
- Consumes: `ApprovalScopePlanRequest`, public `design_impact.ImpactAnalysis`, `design_impact.IntentBoundary`.
- Produces: `ApprovalScopePlanner.plan(request) -> ApprovalScopeDefinition`.

- [ ] **Step 1: Write RED tests for direct scope and authority consistency**

Use a shared MOVE fixture with canonical effect evidence `move.v1@1.0.0 -> PLACEMENT, GEOMETRY`. Prove:

```text
canonical_effect_evidence.canonical_operation == impact_analysis.canonical_operation
intent_boundary.direct_targets == impact_analysis.direct_targets
intent_boundary.allowed_canonical_effects ⊆ canonical_effect_evidence.allowed_aspects
direct_entity_effect.allowed_aspects ⊆ both authorities
```

Failure codes must distinguish `SCOPE_EFFECT_CONTRACT_MISMATCH`, `SCOPE_INPUT_INVALID`, and `SCOPE_RULE_INVALID`.

- [ ] **Step 2: Run RED direct planner tests**

```bash
pytest tests/approval_scope/test_step28_planner.py -k "direct or authority" -q
```

Expected: fail because planner is absent.

- [ ] **Step 3: Implement direct-rule admission**

Create one exact-entity `ExistingEntityRule` per direct target from explicit `DirectEntityEffect`; never derive aspects from `canonical_operation` text. Reject missing direct effect for a direct target and reject any direct effect targeting a non-direct entity.

- [ ] **Step 4: Run GREEN direct planner tests**

```bash
pytest tests/approval_scope/test_step28_planner.py -k "direct or authority" -q
```

Expected: PASS.

- [ ] **Step 5: Write RED tests for predicted impacts and recipes**

Prove:

- Host-native `requires_verification=True` with no recipe -> `SCOPE_EFFECT_UNDEFINED`.
- Entity in deterministic propagation bundle with no recipe -> `SCOPE_EFFECT_UNDEFINED`.
- Advisory-only predicted impact with neither condition needs no recipe and creates no permission.
- Unknown `dependency_ref` recipe -> `SCOPE_RULE_INVALID`.
- Recipe aspect outside either authority -> `SCOPE_RULE_INVALID`.
- Bundle-bound `rule_ref` must equal bundle rule and be in `IntentBoundary.allowed_derived_rule_refs`.
- Action names such as `REVALIDATE`/`RECOMPUTE` never determine allowed aspects.

- [ ] **Step 6: Run RED recipe tests**

```bash
pytest tests/approval_scope/test_step28_planner.py -k "recipe or predicted or bundle" -q
```

Expected: targeted failures for missing recipe logic.

- [ ] **Step 7: Implement recipe admission**

Index predicted impacts by `dependency_ref`; index deterministic bundles by id and affected entity. A predicted impact is effect-bearing iff `requires_verification is True` or its affected id appears in at least one deterministic bundle. Materialize an exact-entity `ExistingEntityRule` only from an explicit valid recipe. Admit a propagation bundle id only when an explicit recipe references it and validates its exact rule ref.

- [ ] **Step 8: Run GREEN planner tests**

```bash
pytest tests/approval_scope/test_step28_planner.py -q
```

Expected: PASS for all direct and recipe behavior implemented so far.

- [ ] **Step 9: Commit**

```bash
git add platform/approval_scope/src/design_approval_scope/planner.py platform/approval_scope/src/design_approval_scope/__init__.py tests/approval_scope/test_step28_planner.py
git commit -m "feat(step28): plan closed world effect scope"
```

---

### Task 4: Blocking exceptions, existence-effect gate, and slice-scope validation

**Files:**
- Modify: `platform/approval_scope/src/design_approval_scope/planner.py`
- Test: `tests/approval_scope/test_step28_planner.py`

**Interfaces:**
- Extends: `ApprovalScopePlanner.plan` from Task 3.
- Produces: complete Step28 v1 admission behavior.

- [ ] **Step 1: Write RED tests**

Prove: any `ImpactException(blocking=True)` returns `SCOPE_NOT_APPROVABLE`; non-blocking advisory exceptions add no permission; any non-empty requested creation or deletion rules return `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED`; successful output has empty create/delete tuples; every existing rule id is assigned to at least one `ExecutionSliceScopeRule`; slice rules reject unknown rule ids; fields/contracts contain no `execution_slice_id`.

- [ ] **Step 2: Run RED tests**

```bash
pytest tests/approval_scope/test_step28_planner.py -k "blocking or existence or slice" -q
```

Expected: failures because gates/coverage validation are not implemented.

- [ ] **Step 3: Implement gates and slice coverage**

Order checks fail-closed before hash creation: blocking exception first; authority consistency; create/delete unsupported gate; direct/recipe admission; slice cross-reference validation; ensure union of `existing_rule_ids` across slice rules covers all admitted existing rule ids. Keep create/delete rule-id arrays empty in v1.

- [ ] **Step 4: Run GREEN full planner tests**

```bash
pytest tests/approval_scope/test_step28_planner.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/approval_scope/src/design_approval_scope/planner.py tests/approval_scope/test_step28_planner.py
git commit -m "feat(step28): enforce approval scope gates"
```

---

### Task 5: Architecture boundary tests and public API audit

**Files:**
- Create: `tests/approval_scope/test_step28_architecture.py`
- Modify: `platform/approval_scope/src/design_approval_scope/__init__.py`

**Interfaces:**
- Consumes: package source text/import graph.
- Produces: regression guard for Step28 ownership boundaries.

- [ ] **Step 1: Write RED architecture tests**

Scan `platform/approval_scope/src/design_approval_scope/*.py` and assert no imports/references to `hosts.`, AutoCAD/Revit/Tekla, `HostCommand`, provider tool/native identifiers, `design_orchestrator`, `platform.changeset`, approval/policy/grant DTOs. Assert planner imports only public `design_impact` values outside stdlib/package-local modules. Assert no `execution_slice_id` public contract field exists.

- [ ] **Step 2: Run architecture tests**

```bash
pytest tests/approval_scope/test_step28_architecture.py -q
```

Expected: PASS after correcting any accidental leakage; if the initial test exposes leakage, fix production imports/names rather than weakening the test.

- [ ] **Step 3: Audit public exports**

Make `design_approval_scope.__all__` explicit and include only the frozen public contracts, `ApprovalScopePlanner`, hash/bind functions, and stable error type.

- [ ] **Step 4: Run Step28 suite**

```bash
pytest tests/approval_scope -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/approval_scope/src/design_approval_scope/__init__.py tests/approval_scope/test_step28_architecture.py
git commit -m "test(step28): freeze approval scope architecture"
```

---

### Task 6: Regression, full verification, and PR readiness

**Files:**
- Modify only if verification exposes a Step28-owned defect.

**Interfaces:**
- Consumes: completed Step28 package.
- Produces: verified feature branch ready for review/merge.

- [ ] **Step 1: Run Step23–27 regression suites**

```bash
pytest tests/orchestrator tests/interaction tests/impact -q
```

Expected: PASS.

- [ ] **Step 2: Run full repository test suite**

```bash
pytest -q
```

Expected: PASS with 0 failures.

- [ ] **Step 3: Run Ruff on changed Python files**

```bash
ruff check platform/approval_scope/src/design_approval_scope tests/approval_scope
```

Expected: PASS.

- [ ] **Step 4: Compare feature branch to `main`**

Verify the diff contains only the approved Step28 design/plan, new `platform/approval_scope` package, Step28 tests, and the `pyproject.toml` pythonpath addition. Confirm no legacy `platform/changeset` production files changed.

- [ ] **Step 5: Final verification commit if needed**

If verification required a code/test correction, commit only the verified fix:

```bash
git add <verified-files>
git commit -m "fix(step28): close verification gaps"
```

Otherwise do not create an empty commit.
