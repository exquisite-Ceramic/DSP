# Step 30 Execution Partitioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral immutable execution-planning layer that projects each frozen Step29 canonical operation to exactly one canonical `ExecutionUnit`, groups Units into approved Host/document `ExecutionSlice` values, preserves the Step29 dependency graph, and emits a deterministic `ExecutionPlan` without choosing providers or carrying runtime state.

**Architecture:** Step30 is a separate `design_execution_planning` package. It consumes the exact `CanonicalChangeSet`, exact `ApprovalScopeBoundary`, and task-scoped `RuntimeRoutingEvidence`; it validates those bindings, re-verifies Step29 operation hashes from the exact Step28 rule bodies, applies closed-world route validation and least-authority slice-scope selection, then builds Unit → Slice → Plan hashes in one acyclic direction. RevisionBarrier, ProviderBinding, approval/grant state, native identifiers, execution status, ActualDelta, verification, rollback, and Saga state remain outside Step30.

**Tech Stack:** Python 3.11, frozen dataclasses, `MappingProxyType`, Step29 canonical SHA-256 JSON hashing, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-step30-execution-partitioning-design.md`

## Global Constraints

- Base: `main@4c64286734a128c49e302e5685529502a5207086`; branch: `feat/step30-execution-partitioning`.
- Distribution: `design-execution-planning`; source package: `design_execution_planning`.
- Step30 imports only provider-neutral contracts from `design_changeset` and `design_approval_scope`.
- Step30 MUST NOT query D5, Host registries, Host MCP, sidecars, providers, or Host APIs.
- Forbidden Step30 production concepts: `provider_id`, `provider_tool`, native IDs/units, `binding_set_hash`, ApprovalRecord, ExecutionGrant, ActualDelta, verification results, rollback/Saga state, mutable execution status.
- Runtime routing is task-scoped and closed-world: route semantic IDs equal the union of all Step29 operation targets.
- v1 invariant: `1 CanonicalChangeOperation = 1 ExecutionUnit`; Step30 never splits targets.
- Step30 re-verifies each source operation with Step29 `compute_scope_rule_fingerprint()` + `compute_operation_semantic_hash()`.
- Step29 v1 operation `scope_rule_ids` resolve only against `ApprovalScopeBoundary.existing_entity_rules`.
- Caller cannot select slice scope; Step30 derives a unique least-authority `ExecutionSliceScopeRule`.
- Step30 projects Step29 dependencies exactly; no new, removed, reversed, or optimized edges.
- `ExecutionUnit` contains no `execution_slice_id`; parent membership is owned by `ExecutionSlice`.
- RevisionBarrier occurs after Step30; its result is not Step30 hash material.
- Provider switching later MUST NOT alter Step30 Plan/Slice/Unit identities.

## Stable Step30 Error Codes

```text
EXECUTION_INPUT_INVALID
EXECUTION_SCOPE_MISMATCH
EXECUTION_ROUTE_HASH_MISMATCH
EXECUTION_ROUTE_UNRESOLVED
EXECUTION_ROUTE_CONFLICT
EXECUTION_ROUTE_EXTRANEOUS
EXECUTION_OPERATION_MISMATCH
EXECUTION_OPERATION_NOT_PARTITIONABLE
EXECUTION_SLICE_SCOPE_UNCOVERED
EXECUTION_SLICE_SCOPE_AMBIGUOUS
EXECUTION_DEPENDENCY_INVALID
```

---

## File Map

### Production

- `platform/execution_planning/pyproject.toml`
- `platform/execution_planning/src/design_execution_planning/contracts.py`
- `platform/execution_planning/src/design_execution_planning/hashing.py`
- `platform/execution_planning/src/design_execution_planning/planner.py`
- `platform/execution_planning/src/design_execution_planning/__init__.py`
- `pyproject.toml` — add `platform/execution_planning/src` to pytest `pythonpath`.

### Tests

- `tests/execution_planning/conftest.py`
- `tests/execution_planning/test_step30_contracts.py`
- `tests/execution_planning/test_step30_hashing.py`
- `tests/execution_planning/test_step30_routing.py`
- `tests/execution_planning/test_step30_scope_selection.py`
- `tests/execution_planning/test_step30_planner.py`
- `tests/execution_planning/test_step30_dependencies.py`
- `tests/execution_planning/test_step30_architecture.py`

### CI

- `.github/workflows/step30-execution-partitioning.yml`

---

### Task 1: Package shell and immutable contracts

**Files:**
- Create: `platform/execution_planning/pyproject.toml`
- Create: `platform/execution_planning/src/design_execution_planning/contracts.py`
- Create: `platform/execution_planning/src/design_execution_planning/__init__.py`
- Modify: `pyproject.toml`
- Create: `tests/execution_planning/test_step30_contracts.py`

**Interfaces:**
- Produces `ExecutionPlanningError(code, message)`.
- Produces `HostRuntimeRef`, `RuntimeEntityRoute`, `RuntimeRoutingEvidence`, `ApprovalScopeRef`, `ApprovedExecutionScopeRef`, `ExecutionUnit`, `ExecutionSlice`, `ExecutionDependency`, `ExecutionPlan`, `ExecutionPlanningRequest`.
- `ExecutionPlanner` is NOT exported until Task 4 creates it.

- [ ] **Step 1: Write failing contract tests**

```python
from dataclasses import FrozenInstanceError
import pytest


def test_runtime_ref_is_frozen():
    from design_execution_planning import HostRuntimeRef
    ref = HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    with pytest.raises(FrozenInstanceError):
        ref.document_ref = "DOC-2"


def test_unit_has_no_reverse_slice_reference():
    from design_execution_planning import ExecutionUnit
    assert "execution_slice_id" not in ExecutionUnit.__dataclass_fields__


def test_request_cannot_choose_provider_or_slice_scope():
    from design_execution_planning import ExecutionPlanningRequest
    fields = set(ExecutionPlanningRequest.__dataclass_fields__)
    assert {"provider_id", "provider_tool", "execution_slice_scope_rule_id"}.isdisjoint(fields)
```

Also test tuple normalization, lowercase 64-hex digest validation, non-empty text validation, and defensive copy/read-only handling for `ExecutionUnit.arguments`.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/execution_planning/test_step30_contracts.py
```

Expected: import failure because the package does not exist.

- [ ] **Step 3: Add package metadata and pytest path**

```toml
[project]
name = "design-execution-planning"
version = "0.1.0"
description = "Provider-neutral immutable execution partitioning contracts for DSP."
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Add to root pytest `pythonpath`:

```toml
"platform/execution_planning/src",
```

- [ ] **Step 4: Implement contracts**

Core exact shapes:

```python
@dataclass(frozen=True, slots=True)
class HostRuntimeRef:
    host_type: str
    host_instance_id: str
    document_ref: str

@dataclass(frozen=True, slots=True)
class RuntimeEntityRoute:
    semantic_id: str
    host_runtime_ref: HostRuntimeRef

@dataclass(frozen=True, slots=True)
class RuntimeRoutingEvidence:
    routing_snapshot_id: str
    routes: tuple[RuntimeEntityRoute, ...]
    routing_snapshot_hash: str
```

Do not deduplicate `RuntimeRoutingEvidence.routes` in the DTO; Task 4 must see duplicate entries to distinguish identical duplicates from conflicts.

```python
@dataclass(frozen=True, slots=True)
class ApprovalScopeRef:
    scope_id: str
    scope_hash: str

@dataclass(frozen=True, slots=True)
class ApprovedExecutionScopeRef:
    scope_id: str
    scope_hash: str
    execution_slice_scope_rule_id: str
```

```python
@dataclass(frozen=True, slots=True)
class ExecutionUnit:
    execution_unit_id: str
    source_operation_id: str
    source_operation_hash: str
    canonical_operation: str
    canonical_operation_version: str
    canonical_definition_fingerprint: str
    targets: tuple[str, ...]
    arguments: Mapping[str, Any]
    preconditions: tuple[ChangePrecondition, ...]
    expected_effects: tuple[CanonicalAspect, ...]
    execution_unit_hash: str
```

```python
@dataclass(frozen=True, slots=True)
class ExecutionSlice:
    execution_slice_id: str
    changeset_id: str
    changeset_hash: str
    host_runtime_ref: HostRuntimeRef
    approved_scope_ref: ApprovedExecutionScopeRef
    execution_units: tuple[ExecutionUnit, ...]
    execution_slice_hash: str

@dataclass(frozen=True, slots=True)
class ExecutionDependency:
    predecessor_execution_unit_id: str
    successor_execution_unit_id: str
    reason_ref: str

@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    execution_plan_id: str
    changeset_id: str
    changeset_hash: str
    approval_scope_ref: ApprovalScopeRef
    routing_snapshot_id: str
    routing_snapshot_hash: str
    execution_slices: tuple[ExecutionSlice, ...]
    execution_dependencies: tuple[ExecutionDependency, ...]
    execution_plan_hash: str
```

`ExecutionPlanningRequest` fields are exactly `canonical_changeset`, `approval_scope_boundary`, `runtime_routing_evidence`.

- [ ] **Step 5: Export only contracts now**

`__all__` contains the ten DTO/error names above plus `ExecutionPlanningRequest`; do not mention `ExecutionPlanner` yet.

- [ ] **Step 6: Run GREEN and commit**

```bash
pytest -q tests/execution_planning/test_step30_contracts.py
git add platform/execution_planning pyproject.toml tests/execution_planning/test_step30_contracts.py
git commit -m "feat(step30): add immutable execution planning contracts"
```

---

### Task 2: Deterministic hashing

**Files:**
- Create: `platform/execution_planning/src/design_execution_planning/hashing.py`
- Modify: `platform/execution_planning/src/design_execution_planning/__init__.py`
- Create: `tests/execution_planning/test_step30_hashing.py`

**Interfaces:**
- Consumes `design_changeset.canonical_hash`.
- Produces `compute_routing_snapshot_hash`, `compute_execution_unit_hash`, `compute_execution_slice_hash`, `compute_execution_plan_hash`.

- [ ] **Step 1: Write failing hash tests**

```python
def test_route_order_does_not_change_routing_hash():
    a = RuntimeEntityRoute("A", HostRuntimeRef("REVIT", "RVT-1", "DOC"))
    b = RuntimeEntityRoute("B", HostRuntimeRef("REVIT", "RVT-1", "DOC"))
    assert compute_routing_snapshot_hash((a, b)) == compute_routing_snapshot_hash((b, a))


def test_slice_hash_changes_when_host_instance_changes():
    common = dict(
        changeset_hash="a" * 64,
        scope_hash="b" * 64,
        execution_slice_scope_rule_id="SSR-1",
        execution_unit_hashes=("c" * 64,),
    )
    first = compute_execution_slice_hash(
        host_runtime_ref=HostRuntimeRef("REVIT", "RVT-1", "DOC"), **common
    )
    second = compute_execution_slice_hash(
        host_runtime_ref=HostRuntimeRef("REVIT", "RVT-2", "DOC"), **common
    )
    assert first != second
```

Add tests that Unit hash changes with source operation hash/targets/arguments/preconditions/effects; Slice hash is Unit-order independent but membership-sensitive; Plan hash changes with route hash/slice hash/dependency semantics; construction IDs are absent from hash function parameters.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/execution_planning/test_step30_hashing.py
```

- [ ] **Step 3: Implement hash payloads using Step29 canonical hash**

```python
from design_changeset import canonical_hash
```

Routing hashes normalized routes sorted by semantic ID and HostRuntimeRef tuple. Unit hash binds `changeset_hash`, `source_operation_hash`, canonical operation/version/definition, targets, arguments, full preconditions, expected effects. Slice hash binds `changeset_hash`, `scope_hash`, selected slice-scope rule ID, HostRuntimeRef, sorted Unit hashes. Plan hash binds `changeset_hash`, global `scope_hash`, `routing_snapshot_hash`, sorted Slice hashes, normalized execution dependencies.

- [ ] **Step 4: Export hash helpers, run GREEN, commit**

```bash
pytest -q tests/execution_planning/test_step30_hashing.py
git add platform/execution_planning/src/design_execution_planning tests/execution_planning/test_step30_hashing.py
git commit -m "feat(step30): add deterministic execution planning hashes"
```

---

### Task 3: Real Step28→29 fixture, exact scope binding, and least-authority slice scope

**Files:**
- Create: `tests/execution_planning/conftest.py`
- Create: `tests/execution_planning/test_step30_scope_selection.py`
- Create: `platform/execution_planning/src/design_execution_planning/planner.py`

**Interfaces:**
- Internal `_validate_scope_binding(changeset, boundary) -> dict[str, ExistingEntityRule]`.
- Internal `_source_operation_hash(operation, rules_by_id) -> str`.
- Internal `_select_slice_scope(operation, document_ref, boundary) -> ExecutionSliceScopeRule`.

- [ ] **Step 1: Build a real upstream fixture**

Adapt the production chain from `tests/changeset/test_step29_finalization.py` into a pytest fixture that returns a real Step29 ChangeSet with one ROOT + one DERIVED operation and a bound Step28 `ApprovalScopeBoundary`:

```python
@pytest.fixture
def step30_transaction():
    request, scope = build_step29_request_and_scope()
    changeset = ChangeSetBuilder().build(request)
    boundary = bind_changeset(scope, changeset.changeset_hash, "SCOPE-30")
    return changeset, boundary
```

- [ ] **Step 2: Write failing binding/hash re-verification tests**

```python
def test_scope_must_bind_exact_changeset(step30_transaction):
    changeset, boundary = step30_transaction
    bad = replace(boundary, changeset_hash="0" * 64)
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(valid_request(changeset, bad))
    assert exc.value.code == "EXECUTION_SCOPE_MISMATCH"


def test_tampered_operation_fails_reverification(step30_transaction):
    changeset, boundary = step30_transaction
    bad_root = replace(changeset.root_operation, arguments={"targets": ["WALL-001"], "displacement": [999.0, 0.0, 0.0]})
    bad_changeset = replace(changeset, root_operation=bad_root)
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(valid_request(bad_changeset, boundary))
    assert exc.value.code == "EXECUTION_OPERATION_MISMATCH"
```

Also test unknown operation `scope_rule_id` → `EXECUTION_SCOPE_MISMATCH`.

- [ ] **Step 3: Write failing least-authority tests**

Add explicit tests for: unique minimum surplus succeeds; no covering scope → `EXECUTION_SLICE_SCOPE_UNCOVERED`; equal-minimum different normalized bodies → `EXECUTION_SLICE_SCOPE_AMBIGUOUS`; equal normalized bodies differing only in ID choose lexicographically smallest ID.

- [ ] **Step 4: Run RED**

```bash
pytest -q tests/execution_planning/test_step30_scope_selection.py
```

- [ ] **Step 5: Implement exact Step28↔29 binding and Step29 operation hash check**

Require:

```python
changeset.changeset_hash == boundary.changeset_hash
changeset.approval_scope_definition_ref.scope_body_hash == boundary.scope_body_hash
```

Resolve every operation rule ID in `boundary.existing_entity_rules`; compute rule fingerprints with `compute_scope_rule_fingerprint`; then recompute the source digest with `compute_operation_semantic_hash`. Require:

```python
operation.operation_id == f"COP-{source_hash[:12]}"
```

- [ ] **Step 6: Implement deterministic least-authority selection**

Eligibility is matching `document_ref` plus `set(operation.scope_rule_ids) <= set(candidate.existing_rule_ids)`. Surplus is the candidate's union of existing/creation/deletion IDs minus operation rule IDs. Different tied normalized bodies fail ambiguous; identical bodies choose the lexicographically smallest ID.

- [ ] **Step 7: Run GREEN and commit**

```bash
pytest -q tests/execution_planning/test_step30_scope_selection.py
git add platform/execution_planning/src/design_execution_planning/planner.py tests/execution_planning/conftest.py tests/execution_planning/test_step30_scope_selection.py
git commit -m "feat(step30): validate execution scope partitioning"
```

---

### Task 4: Closed-world routing and one-to-one ExecutionUnit projection

**Files:**
- Modify: `platform/execution_planning/src/design_execution_planning/planner.py`
- Modify: `platform/execution_planning/src/design_execution_planning/__init__.py`
- Create: `tests/execution_planning/test_step30_routing.py`
- Create: `tests/execution_planning/test_step30_planner.py`

**Interfaces:**
- Internal `_normalize_routes(evidence, required_targets) -> dict[str, HostRuntimeRef]`.
- Internal `_build_unit(changeset, operation, source_operation_hash) -> ExecutionUnit`.
- Public `ExecutionPlanner.plan(request: ExecutionPlanningRequest) -> ExecutionPlan`.

- [ ] **Step 1: Write route failure tests**

```python
def test_wrong_routing_hash_fails(step30_transaction):
    request = valid_request(step30_transaction, routing_snapshot_hash="0" * 64)
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(request)
    assert exc.value.code == "EXECUTION_ROUTE_HASH_MISMATCH"
```

Add missing route → `EXECUTION_ROUTE_UNRESOLVED`, conflicting duplicate → `EXECUTION_ROUTE_CONFLICT`, extraneous route → `EXECUTION_ROUTE_EXTRANEOUS`, and byte-identical duplicate route normalization success.

- [ ] **Step 2: Write one-operation-one-Unit tests**

```python
def test_every_source_operation_appears_exactly_once(step30_transaction):
    changeset, _ = step30_transaction
    plan = ExecutionPlanner().plan(valid_request(step30_transaction))
    source_ids = [
        unit.source_operation_id
        for slice_ in plan.execution_slices
        for unit in slice_.execution_units
    ]
    expected = [changeset.root_operation.operation_id, *(op.operation_id for op in changeset.derived_operations)]
    assert sorted(source_ids) == sorted(expected)
    assert len(source_ids) == len(set(source_ids))
```

Create a real valid multi-target Step29 operation fixture; route its targets to different HostRuntimeRefs and require `EXECUTION_OPERATION_NOT_PARTITIONABLE`.

- [ ] **Step 3: Run RED**

```bash
pytest -q tests/execution_planning/test_step30_routing.py tests/execution_planning/test_step30_planner.py
```

- [ ] **Step 4: Implement closed-world routing**

Compute required target set from all source operations. Preserve duplicate entries until conflict analysis. Recompute `compute_routing_snapshot_hash()` from normalized semantic routes; mismatch → `EXECUTION_ROUTE_HASH_MISMATCH`. Compare normalized semantic IDs exactly to required targets.

- [ ] **Step 5: Enforce one runtime boundary and build Units**

```python
runtime_refs = {route_index[target] for target in operation.targets}
if len(runtime_refs) != 1:
    raise ExecutionPlanningError(
        "EXECUTION_OPERATION_NOT_PARTITIONABLE",
        "one canonical operation cannot span Host runtime boundaries",
    )
```

Copy operation/version/definition/targets/arguments/effects without semantic modification. Every Unit carries the complete `changeset.preconditions`. Derive `execution_unit_id = "EU-" + execution_unit_hash[:12]`.

- [ ] **Step 6: Export `ExecutionPlanner` now**

Add `ExecutionPlanner` to `design_execution_planning.__all__` only after `planner.py` defines it.

- [ ] **Step 7: Run GREEN and commit**

```bash
pytest -q tests/execution_planning/test_step30_routing.py tests/execution_planning/test_step30_planner.py
git add platform/execution_planning/src/design_execution_planning tests/execution_planning/test_step30_routing.py tests/execution_planning/test_step30_planner.py
git commit -m "feat(step30): project canonical execution units"
```

---

### Task 5: Deterministic ExecutionSlice grouping and exact dependency projection

**Files:**
- Modify: `platform/execution_planning/src/design_execution_planning/planner.py`
- Extend: `tests/execution_planning/test_step30_planner.py`
- Create: `tests/execution_planning/test_step30_dependencies.py`

**Interfaces:**
- Slice grouping key: `(host_type, host_instance_id, document_ref, execution_slice_scope_rule_id)`.
- Exact `operation_id -> execution_unit_id` map for dependency projection.

- [ ] **Step 1: Write Slice grouping tests**

Add tests proving same key shares one Slice; differing host instance/document/slice-scope ID creates separate Slices; Unit input order does not change Slice identity. Assert `execution_slice_id == "XS-" + execution_slice_hash[:12]`.

- [ ] **Step 2: Write exact dependency tests**

```python
def test_dependencies_project_one_to_one(step30_transaction):
    changeset, _ = step30_transaction
    plan = ExecutionPlanner().plan(valid_request(step30_transaction))
    unit_by_source = {
        unit.source_operation_id: unit.execution_unit_id
        for slice_ in plan.execution_slices
        for unit in slice_.execution_units
    }
    expected = {
        (
            unit_by_source[dep.predecessor_operation_id],
            unit_by_source[dep.successor_operation_id],
            dep.reason_ref,
        )
        for dep in changeset.change_dependencies
    }
    actual = {
        (dep.predecessor_execution_unit_id, dep.successor_execution_unit_id, dep.reason_ref)
        for dep in plan.execution_dependencies
    }
    assert actual == expected
```

Route ROOT and DERIVED to different host instances while keeping an approved document/scope, and assert the dependency survives cross-slice. Invalid predecessor/successor reference → `EXECUTION_DEPENDENCY_INVALID`.

- [ ] **Step 3: Run RED**

```bash
pytest -q tests/execution_planning/test_step30_planner.py tests/execution_planning/test_step30_dependencies.py
```

- [ ] **Step 4: Group Units, hash Slices, project DAG, finalize Plan**

Sort Units by Unit hash inside each grouping key. Hash/derive each Slice. Build a total source operation map, project every Step29 edge mechanically, sort dependency tuples deterministically. Create `ApprovalScopeRef(boundary.scope_id, boundary.scope_hash)`. Derive `execution_plan_id = "XP-" + execution_plan_hash[:12]`.

- [ ] **Step 5: Run all focused Step30 behavior tests and commit**

```bash
pytest -q tests/execution_planning/test_step30_hashing.py \
  tests/execution_planning/test_step30_routing.py \
  tests/execution_planning/test_step30_scope_selection.py \
  tests/execution_planning/test_step30_planner.py \
  tests/execution_planning/test_step30_dependencies.py
git add platform/execution_planning/src/design_execution_planning/planner.py tests/execution_planning/test_step30_planner.py tests/execution_planning/test_step30_dependencies.py
git commit -m "feat(step30): build execution slices and plan DAG"
```

---

### Task 6: Architecture guards, dedicated CI, and final exact-head verification

**Files:**
- Create: `tests/execution_planning/test_step30_architecture.py`
- Create: `.github/workflows/step30-execution-partitioning.yml`
- Modify: `docs/superpowers/specs/2026-08-29-step30-execution-partitioning-design.md` only after implementation verification, to mark implemented status.

**Interfaces:**
- Dedicated workflow name: `Step30 execution partitioning`.
- PR diff guard allows only the Step30 spec/plan/workflow, `platform/execution_planning/**`, `tests/execution_planning/**`, and root `pyproject.toml`.

- [ ] **Step 1: Write architecture guards**

```python
ROOT = Path(__file__).resolve().parents[2]
PACKAGE = ROOT / "platform" / "execution_planning" / "src" / "design_execution_planning"


def test_step30_has_no_later_layer_leakage():
    forbidden = (
        "host_contracts", "HostCommand", "ProviderBinding", "provider_id", "provider_tool",
        "native_id", "ElementId", "Handle", "internal_unit", "binding_set_hash",
        "ApprovalRecord", "ExecutionGrant", "ActualDelta", "VerificationReport",
    )
    text = "\n".join(path.read_text(encoding="utf-8") for path in sorted(PACKAGE.glob("*.py")))
    for marker in forbidden:
        assert marker not in text


def test_step30_fields_keep_runtime_state_out():
    assert "execution_slice_id" not in ExecutionUnit.__dataclass_fields__
    assert "status" not in ExecutionSlice.__dataclass_fields__
    assert {"provider_id", "provider_tool"}.isdisjoint(ExecutionPlanningRequest.__dataclass_fields__)
```

Also assert every public value contract is a frozen dataclass and `__all__` has no duplicates/private names.

- [ ] **Step 2: Run architecture + Step28/29 regressions**

```bash
pytest -q tests/execution_planning/test_step30_architecture.py
pytest -q tests/approval_scope
pytest -q tests/changeset
```

Expected: PASS.

- [ ] **Step 3: Create dedicated workflow**

Path triggers:

```yaml
name: Step30 execution partitioning

on:
  push:
    paths:
      - "platform/execution_planning/**"
      - "tests/execution_planning/**"
      - "pyproject.toml"
      - "docs/superpowers/specs/2026-08-29-step30-execution-partitioning-design.md"
      - "docs/superpowers/plans/2026-08-30-step30-execution-partitioning.md"
      - ".github/workflows/step30-execution-partitioning.yml"
  pull_request:
    paths:
      - "platform/execution_planning/**"
      - "tests/execution_planning/**"
      - "pyproject.toml"
      - "docs/superpowers/specs/2026-08-29-step30-execution-partitioning-design.md"
      - "docs/superpowers/plans/2026-08-30-step30-execution-partitioning.md"
      - ".github/workflows/step30-execution-partitioning.yml"
  workflow_dispatch:
```

Install Step29 verification dependencies plus `-e platform/execution_planning`. Add an exact PR diff-boundary grep allowing only the files listed in the File Map.

- [ ] **Step 4: Add workflow verification commands in order**

```bash
pytest -q tests/execution_planning/test_step30_contracts.py
pytest -q tests/execution_planning/test_step30_hashing.py
pytest -q tests/execution_planning/test_step30_routing.py
pytest -q tests/execution_planning/test_step30_scope_selection.py
pytest -q tests/execution_planning/test_step30_planner.py
pytest -q tests/execution_planning/test_step30_dependencies.py
pytest -q tests/execution_planning/test_step30_architecture.py
pytest -q tests/approval_scope
pytest -q tests/changeset
ruff check platform/execution_planning/src/design_execution_planning tests/execution_planning
pytest -q --import-mode=importlib
```

- [ ] **Step 5: Commit CI/guards**

```bash
git add tests/execution_planning/test_step30_architecture.py .github/workflows/step30-execution-partitioning.yml
git commit -m "ci(step30): verify execution partitioning"
```

- [ ] **Step 6: Perform final exact-head verification before claiming completion**

Fresh evidence must show:

```text
Step30 focused tests: PASS
Step28 regressions: PASS
Step29 regressions: PASS
Ruff: All checks passed
Full repository pytest: PASS except only documented pre-existing/live-Host skips or warnings
Step30 PR diff boundary: PASS
Dedicated Step30 workflow on exact final head: completed/success
```

Any subsequent code change invalidates this evidence and requires the exact-head checks again.

- [ ] **Step 7: Mark design implemented only after Step 6**

Change only the spec status line to:

```text
**Status:** Implemented; verification complete
```

Then commit the status update and rerun the exact-head workflow because the head changed.

---

## Plan Self-Review Coverage

Every approved design invariant maps to a task/test:

- immutable contracts and no reverse Unit→Slice reference — Task 1;
- deterministic routing/Unit/Slice/Plan hashes — Task 2;
- exact ChangeSet↔Scope binding and Step29 operation re-verification — Task 3;
- least-authority slice-scope selection — Task 3;
- closed-world routing and route evidence hash verification — Task 4;
- one operation → one Unit and no target splitting — Task 4;
- complete Step29 preconditions preserved — Task 4;
- deterministic Slice grouping — Task 5;
- exact DAG/cross-slice dependency projection — Task 5;
- provider/native/governance/runtime separation — Task 6;
- Step28/29 regressions, Ruff, full repository tests, exact diff boundary, exact-head CI — Task 6.

No Step30 task introduces D5/Host lookup, RevisionBarrier implementation, ProviderBinding, `binding_set_hash`, ApprovalRecord/ExecutionGrant, HostCommand, ActualDelta, verification, rollback, or Saga behavior.
