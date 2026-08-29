# Step 30 Execution Partitioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a provider-neutral immutable execution-planning layer that projects one frozen Step29 canonical operation to one canonical `ExecutionUnit`, deterministically groups units into approved Host/document `ExecutionSlice` values, preserves the Step29 dependency graph, and emits a content-addressed `ExecutionPlan` without choosing providers or carrying runtime state.

**Architecture:** Step30 is a separate `design_execution_planning` package. It consumes the exact `CanonicalChangeSet`, exact `ApprovalScopeBoundary`, and a task-scoped `RuntimeRoutingEvidence`; it validates the Step29↔Step28 binding, re-verifies Step29 operation hashes against exact scope rule bodies, checks closed-world runtime routing, selects the least-authority Step28 slice scope, then builds immutable Unit→Slice→Plan hashes in an acyclic direction. RevisionBarrier, ProviderBinding, approval/grant state, native identifiers, execution status, ActualDelta, verification, rollback, and Saga state remain outside this package.

**Tech Stack:** Python 3.11, frozen dataclasses, `MappingProxyType`, Step29 canonical SHA-256 JSON hashing, pytest, Ruff, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-step30-execution-partitioning-design.md`

## Global Constraints

- Base is `main@4c64286734a128c49e302e5685529502a5207086`; implementation branch is `feat/step30-execution-partitioning`.
- New distribution name is `design-execution-planning`; source package is `design_execution_planning`.
- Step30 depends only on provider-neutral upstream contracts from `design_changeset` and `design_approval_scope`.
- Step30 MUST NOT query D5, Host registries, Host MCP, sidecars, providers, or Host APIs.
- Step30 MUST NOT contain `provider_id`, `provider_tool`, native IDs, native units, `binding_set_hash`, ApprovalRecord, ExecutionGrant, ActualDelta, verification result, rollback/Saga state, or mutable execution status.
- Runtime route input is task-scoped and closed-world: its semantic IDs must equal the union of all Step29 operation targets after normalization.
- `1 CanonicalChangeOperation = 1 ExecutionUnit` in v1; an operation whose targets resolve across multiple Host runtime boundaries fails closed.
- Step30 re-verifies each source Step29 operation using the frozen Step29 `compute_scope_rule_fingerprint()` and `compute_operation_semantic_hash()` algorithms.
- Step29 v1 `scope_rule_ids` resolve only against `ApprovalScopeBoundary.existing_entity_rules`.
- Slice scope selection is derived by Step30 from `ApprovalScopeBoundary.execution_slice_scopes`; the caller cannot choose a slice scope.
- Execution dependencies are a one-to-one projection of Step29 `ChangeDependency`; Step30 cannot add, remove, reverse, or optimize edges.
- `ExecutionUnit` has no `execution_slice_id` reverse reference; membership is owned by `ExecutionSlice.execution_units` to keep hashing acyclic.
- Unit, Slice, and Plan are frozen immutable artifacts with deterministic normalization and construction IDs derived from their full SHA-256 hashes.
- RevisionBarrier happens after Step30 and before Step31; its pass/fail result is not included in Step30 hashes.
- Provider switching later MUST leave `ExecutionPlan`, `ExecutionSlice`, and `ExecutionUnit` unchanged.

---

## File Map

### New Step30 package

- `platform/execution_planning/pyproject.toml` — Python package metadata for `design-execution-planning`.
- `platform/execution_planning/src/design_execution_planning/contracts.py` — frozen routing/Unit/Slice/Plan DTOs and `ExecutionPlanningError`.
- `platform/execution_planning/src/design_execution_planning/hashing.py` — deterministic routing, unit, slice, dependency, and plan hash functions.
- `platform/execution_planning/src/design_execution_planning/planner.py` — fail-closed upstream validation and deterministic partitioning.
- `platform/execution_planning/src/design_execution_planning/__init__.py` — explicit public API.
- `pyproject.toml` — add `platform/execution_planning/src` to pytest `pythonpath`.

### Step30 tests

- `tests/execution_planning/conftest.py` — real Step28→29 fixture builder plus routing helpers.
- `tests/execution_planning/test_step30_contracts.py` — frozen DTO/public API/defensive normalization.
- `tests/execution_planning/test_step30_hashing.py` — deterministic three-level hashing.
- `tests/execution_planning/test_step30_routing.py` — route hash, closed-world coverage, conflict, and non-partitionable operation checks.
- `tests/execution_planning/test_step30_scope_selection.py` — Step28 binding and least-authority slice-scope selection.
- `tests/execution_planning/test_step30_planner.py` — one-to-one Unit projection and Slice grouping.
- `tests/execution_planning/test_step30_dependencies.py` — exact Step29 DAG projection including cross-slice edges.
- `tests/execution_planning/test_step30_architecture.py` — provider/native/governance/runtime leakage guards.

### CI

- `.github/workflows/step30-execution-partitioning.yml` — exact PR boundary, focused Step30 tests, Step28/29 regressions, Ruff, and full repository pytest.

---

### Task 1: Add the package shell and immutable public contracts

**Files:**
- Create: `platform/execution_planning/pyproject.toml`
- Create: `platform/execution_planning/src/design_execution_planning/contracts.py`
- Create: `platform/execution_planning/src/design_execution_planning/__init__.py`
- Modify: `pyproject.toml`
- Create: `tests/execution_planning/test_step30_contracts.py`

**Interfaces:**
- Produces: `ExecutionPlanningError(code: str, message: str)`
- Produces: `HostRuntimeRef(host_type, host_instance_id, document_ref)`
- Produces: `RuntimeEntityRoute(semantic_id, host_runtime_ref)`
- Produces: `RuntimeRoutingEvidence(routing_snapshot_id, routes, routing_snapshot_hash)`
- Produces: `ApprovedExecutionScopeRef(scope_id, scope_hash, execution_slice_scope_rule_id)`
- Produces: `ExecutionUnit(...)`, `ExecutionSlice(...)`, `ExecutionDependency(...)`, `ExecutionPlan(...)`
- Produces: `ExecutionPlanningRequest(canonical_changeset, approval_scope_boundary, runtime_routing_evidence)`

- [ ] **Step 1: Write the failing contract tests**

Create `tests/execution_planning/test_step30_contracts.py` with concrete checks:

```python
from dataclasses import FrozenInstanceError

import pytest


def test_public_contracts_are_frozen_and_unit_has_no_reverse_slice_reference():
    from design_execution_planning import HostRuntimeRef, ExecutionUnit

    runtime = HostRuntimeRef("REVIT", "RVT-01", "DOC-1")
    with pytest.raises(FrozenInstanceError):
        runtime.document_ref = "DOC-2"

    assert "execution_slice_id" not in ExecutionUnit.__dataclass_fields__


def test_execution_planning_request_cannot_choose_provider_or_slice():
    from design_execution_planning import ExecutionPlanningRequest

    fields = set(ExecutionPlanningRequest.__dataclass_fields__)
    assert {"provider_id", "provider_tool", "execution_slice_scope_rule_id"}.isdisjoint(fields)
```

Also assert `RuntimeRoutingEvidence.routes`, `ExecutionSlice.execution_units`, and `ExecutionPlan.execution_slices/execution_dependencies` normalize to tuples, IDs/hashes reject blank/invalid values, and mutable `arguments` inside `ExecutionUnit` are defensively copied behind a read-only mapping.

- [ ] **Step 2: Run and verify RED**

Run:

```bash
pytest -q tests/execution_planning/test_step30_contracts.py
```

Expected: FAIL because `design_execution_planning` does not exist.

- [ ] **Step 3: Add package metadata and pytest path**

Create:

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

Add this exact line to root `[tool.pytest.ini_options].pythonpath`:

```toml
"platform/execution_planning/src",
```

- [ ] **Step 4: Implement validation/immutability helpers and DTOs**

Use frozen slotted dataclasses and defensive mapping copies. The core shapes are:

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
```

```python
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

Define a separate plan-level `ApprovalScopeRef(scope_id, scope_hash)` so the plan does not falsely imply one slice rule applies globally.

- [ ] **Step 5: Export an explicit public API**

`__all__` must include only:

```python
[
    "ApprovalScopeRef",
    "ApprovedExecutionScopeRef",
    "ExecutionDependency",
    "ExecutionPlan",
    "ExecutionPlanner",
    "ExecutionPlanningError",
    "ExecutionPlanningRequest",
    "ExecutionSlice",
    "ExecutionUnit",
    "HostRuntimeRef",
    "RuntimeEntityRoute",
    "RuntimeRoutingEvidence",
]
```

`ExecutionPlanner` may remain unresolved until Task 4; tests in this task should import contracts directly until planner exists, then Task 4 updates `__init__.py` atomically.

- [ ] **Step 6: Run contract tests and commit**

Run:

```bash
pytest -q tests/execution_planning/test_step30_contracts.py
```

Expected: PASS.

Commit:

```bash
git add platform/execution_planning pyproject.toml tests/execution_planning/test_step30_contracts.py
git commit -m "feat(step30): add immutable execution planning contracts"
```

---

### Task 2: Implement deterministic routing, Unit, Slice, and Plan hashing

**Files:**
- Create: `platform/execution_planning/src/design_execution_planning/hashing.py`
- Modify: `platform/execution_planning/src/design_execution_planning/__init__.py`
- Create: `tests/execution_planning/test_step30_hashing.py`

**Interfaces:**
- Consumes: Step29 `canonical_hash` from `design_changeset`
- Produces: `compute_routing_snapshot_hash(routes) -> str`
- Produces: `compute_execution_unit_hash(...) -> str`
- Produces: `compute_execution_slice_hash(...) -> str`
- Produces: `compute_execution_plan_hash(...) -> str`

- [ ] **Step 1: Write failing hashing tests**

Use deterministic examples:

```python
def test_routing_hash_ignores_route_input_order():
    a = RuntimeEntityRoute("A", HostRuntimeRef("REVIT", "RVT-1", "DOC"))
    b = RuntimeEntityRoute("B", HostRuntimeRef("REVIT", "RVT-1", "DOC"))
    assert compute_routing_snapshot_hash((a, b)) == compute_routing_snapshot_hash((b, a))


def test_slice_hash_changes_when_host_instance_changes():
    first = compute_execution_slice_hash(
        changeset_hash="a" * 64,
        scope_hash="b" * 64,
        execution_slice_scope_rule_id="SSR-1",
        host_runtime_ref=HostRuntimeRef("REVIT", "RVT-1", "DOC"),
        execution_unit_hashes=("c" * 64,),
    )
    second = compute_execution_slice_hash(
        changeset_hash="a" * 64,
        scope_hash="b" * 64,
        execution_slice_scope_rule_id="SSR-1",
        host_runtime_ref=HostRuntimeRef("REVIT", "RVT-2", "DOC"),
        execution_unit_hashes=("c" * 64,),
    )
    assert first != second
```

Also test Unit hash changes for source operation hash/targets/arguments/preconditions/effects; Slice hash ignores Unit ordering but changes membership; Plan hash changes for routing hash/slice hash/dependency semantics; construction IDs do not enter hash helpers.

- [ ] **Step 2: Run and verify RED**

```bash
pytest -q tests/execution_planning/test_step30_hashing.py
```

Expected: FAIL because hashing functions do not exist.

- [ ] **Step 3: Reuse Step29 canonical hashing rather than fork it**

Start `hashing.py` with:

```python
from design_changeset import canonical_hash
```

Do not copy Step29 JSON encoding code. This guarantees byte-level consistency with the operation source re-verification in Task 3.

- [ ] **Step 4: Implement exact semantic payloads**

Routing payload:

```python
[
    {
        "semantic_id": route.semantic_id,
        "host_runtime_ref": {
            "host_type": route.host_runtime_ref.host_type,
            "host_instance_id": route.host_runtime_ref.host_instance_id,
            "document_ref": route.host_runtime_ref.document_ref,
        },
    }
    for route in sorted(routes, key=lambda item: item.semantic_id)
]
```

Unit payload binds `changeset_hash`, `source_operation_hash`, canonical operation/version/definition fingerprint, normalized targets, arguments, full Step29 preconditions, and expected effects. It does not bind `execution_unit_id` or any slice/provider field.

Slice payload binds `changeset_hash`, `scope_hash`, selected slice-scope rule ID, `HostRuntimeRef`, and sorted unique Unit hashes.

Plan payload binds `changeset_hash`, global `scope_hash`, `routing_snapshot_hash`, sorted Slice hashes, and normalized dependency semantic tuples. It excludes `execution_plan_id`, provider material, and runtime state.

- [ ] **Step 5: Run hashing tests and commit**

```bash
pytest -q tests/execution_planning/test_step30_hashing.py
```

Expected: PASS.

```bash
git add platform/execution_planning/src/design_execution_planning/hashing.py \
  platform/execution_planning/src/design_execution_planning/__init__.py \
  tests/execution_planning/test_step30_hashing.py
git commit -m "feat(step30): add deterministic execution plan hashing"
```

---

### Task 3: Add real Step28→29 fixtures, upstream binding validation, and least-authority scope selection

**Files:**
- Create: `tests/execution_planning/conftest.py`
- Create: `tests/execution_planning/test_step30_scope_selection.py`
- Create: `platform/execution_planning/src/design_execution_planning/planner.py`

**Interfaces:**
- Produces internal: `_validate_scope_binding(changeset, boundary) -> dict[str, ExistingEntityRule]`
- Produces internal: `_source_operation_hash(operation, rules_by_id) -> str`
- Produces internal: `_select_slice_scope(operation, document_ref, boundary) -> ExecutionSliceScopeRule`
- Test fixture returns a real `(CanonicalChangeSet, ApprovalScopeBoundary)` built via Step28/29 production APIs.

- [ ] **Step 1: Build a reusable real fixture from the Step29 finalization path**

In `conftest.py`, adapt `tests/changeset/test_step29_finalization.py` into:

```python
@pytest.fixture
def step30_transaction():
    request, scope = build_step29_request_and_scope()
    changeset = ChangeSetBuilder().build(request)
    boundary = bind_changeset(scope, changeset.changeset_hash, "SCOPE-30")
    return changeset, boundary
```

The fixture must include one root and one deterministic derived operation so later tasks can test same-slice and cross-slice behavior without inventing malformed Step29 values.

- [ ] **Step 2: Write scope/source verification tests**

```python
def test_scope_must_bind_exact_changeset(step30_transaction):
    changeset, boundary = step30_transaction
    bad = replace(boundary, changeset_hash="0" * 64)
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(_request(changeset, bad))
    assert exc.value.code == "EXECUTION_SCOPE_MISMATCH"


def test_source_operation_id_is_reverified_against_exact_scope_rule_body(step30_transaction):
    changeset, boundary = step30_transaction
    tampered = replace(changeset.root_operation, arguments={"targets": ["WALL-001"], "displacement": [999.0, 0.0, 0.0]})
    bad_changeset = replace(changeset, root_operation=tampered)
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(_request(bad_changeset, boundary))
    assert exc.value.code == "EXECUTION_OPERATION_MISMATCH"
```

Also test missing operation `scope_rule_id` in boundary → `EXECUTION_SCOPE_MISMATCH`.

- [ ] **Step 3: Write least-authority scope tests**

Create three boundary variants from the real fixture:

```python
def test_unique_minimum_surplus_scope_is_selected(...): ...
def test_semantically_different_equal_minimum_scopes_are_ambiguous(...): ...
def test_duplicate_semantically_equal_scope_uses_lexicographically_smallest_id(...): ...
def test_uncovered_operation_fails_closed(...): ...
```

Expected error codes are exactly `EXECUTION_SLICE_SCOPE_AMBIGUOUS` and `EXECUTION_SLICE_SCOPE_UNCOVERED`.

- [ ] **Step 4: Run and verify RED**

```bash
pytest -q tests/execution_planning/test_step30_scope_selection.py
```

Expected: FAIL because `ExecutionPlanner` and helpers are absent.

- [ ] **Step 5: Implement upstream binding validation**

The validator must require:

```python
changeset.changeset_hash == boundary.changeset_hash
changeset.approval_scope_definition_ref.scope_body_hash == boundary.scope_body_hash
```

Build `rules_by_id` from `boundary.existing_entity_rules`; reject duplicate IDs and reject any operation rule reference absent from the map.

- [ ] **Step 6: Recompute exact Step29 operation hashes**

For each operation:

```python
scope_fingerprints = tuple(
    sorted(compute_scope_rule_fingerprint(rules_by_id[rule_id]) for rule_id in operation.scope_rule_ids)
)
source_hash = compute_operation_semantic_hash(
    origin=operation.origin,
    canonical_operation=operation.canonical_operation,
    canonical_operation_version=operation.canonical_operation_version,
    canonical_definition_fingerprint=operation.canonical_definition_fingerprint,
    targets=operation.targets,
    arguments=operation.arguments,
    expected_effects=operation.expected_effects,
    scope_rule_fingerprints=scope_fingerprints,
    source_evidence=operation.source_evidence,
)
if operation.operation_id != f"COP-{source_hash[:12]}":
    raise ExecutionPlanningError("EXECUTION_OPERATION_MISMATCH", ...)
```

- [ ] **Step 7: Implement deterministic least-authority selection**

Filter by matching `document_ref` and `operation.scope_rule_ids <= set(candidate.existing_rule_ids)`. Compute surplus over the union of existing/creation/deletion IDs. If tied normalized bodies differ, fail ambiguous; if bodies match, choose the lexicographically smallest `slice_scope_rule_id`.

- [ ] **Step 8: Run focused tests and commit**

```bash
pytest -q tests/execution_planning/test_step30_scope_selection.py
```

Expected: PASS.

```bash
git add platform/execution_planning/src/design_execution_planning/planner.py \
  tests/execution_planning/conftest.py \
  tests/execution_planning/test_step30_scope_selection.py
git commit -m "feat(step30): validate scope and select least authority slice"
```

---

### Task 4: Validate closed-world runtime routing and project exactly one ExecutionUnit per operation

**Files:**
- Modify: `platform/execution_planning/src/design_execution_planning/planner.py`
- Modify: `platform/execution_planning/src/design_execution_planning/__init__.py`
- Create: `tests/execution_planning/test_step30_routing.py`
- Create: `tests/execution_planning/test_step30_planner.py`

**Interfaces:**
- Produces internal: `_normalize_routes(evidence, required_targets) -> dict[str, HostRuntimeRef]`
- Produces internal: `_build_unit(changeset, operation, source_operation_hash) -> ExecutionUnit`
- Produces public: `ExecutionPlanner.plan(request: ExecutionPlanningRequest) -> ExecutionPlan`

- [ ] **Step 1: Write routing fail-closed tests**

```python
def test_missing_route_fails_unresolved(step30_transaction): ...  # EXECUTION_ROUTE_UNRESOLVED
def test_conflicting_duplicate_route_fails(step30_transaction): ...  # EXECUTION_ROUTE_CONFLICT
def test_extraneous_route_fails(step30_transaction): ...  # EXECUTION_ROUTE_EXTRANEOUS
def test_wrong_routing_snapshot_hash_fails(step30_transaction): ...
```

For the hash mismatch, use the stable Step30 input error code defined in `ExecutionPlanningError` for invalid evidence; keep that code fixed once introduced and use it consistently in tests and implementation.

- [ ] **Step 2: Write operation partitionability and Unit projection tests**

```python
def test_every_step29_operation_becomes_exactly_one_execution_unit(step30_transaction):
    plan = ExecutionPlanner().plan(valid_request(step30_transaction))
    source_ids = {
        unit.source_operation_id
        for slice_ in plan.execution_slices
        for unit in slice_.execution_units
    }
    changeset, _ = step30_transaction
    assert source_ids == {
        changeset.root_operation.operation_id,
        *(op.operation_id for op in changeset.derived_operations),
    }


def test_one_operation_cannot_span_host_boundaries(...):
    # use a valid multi-target source operation fixture and route its targets to different runtime refs
    with pytest.raises(ExecutionPlanningError) as exc:
        ExecutionPlanner().plan(request)
    assert exc.value.code == "EXECUTION_OPERATION_NOT_PARTITIONABLE"
```

Also assert Unit copies operation/version/definition/targets/arguments/effects exactly, carries the complete ChangeSet precondition tuple, has `source_operation_hash` equal to the recomputed Step29 digest, and derives `execution_unit_id == "EU-" + execution_unit_hash[:12]`.

- [ ] **Step 3: Run and verify RED**

```bash
pytest -q tests/execution_planning/test_step30_routing.py \
  tests/execution_planning/test_step30_planner.py
```

Expected: FAIL because routing/Unit construction is incomplete.

- [ ] **Step 4: Implement exact routing coverage**

Compute:

```python
required_targets = {
    target
    for operation in (changeset.root_operation, *changeset.derived_operations)
    for target in operation.targets
}
```

Normalize byte-identical duplicate routes to one mapping, reject conflicting duplicates, compare the normalized key set exactly to `required_targets`, and recompute the supplied `routing_snapshot_hash` with `compute_routing_snapshot_hash()` before accepting it.

- [ ] **Step 5: Enforce one runtime boundary per operation**

For one operation:

```python
runtime_refs = {routes[target] for target in operation.targets}
if len(runtime_refs) != 1:
    raise ExecutionPlanningError(
        "EXECUTION_OPERATION_NOT_PARTITIONABLE",
        "one canonical operation cannot span Host runtime boundaries",
    )
```

Do not split targets or synthesize multiple Units.

- [ ] **Step 6: Build immutable ExecutionUnits**

Call `compute_execution_unit_hash()` with the full ChangeSet preconditions and derive:

```python
execution_unit_id = f"EU-{execution_unit_hash[:12]}"
```

- [ ] **Step 7: Export `ExecutionPlanner` and run tests**

```bash
pytest -q tests/execution_planning/test_step30_routing.py \
  tests/execution_planning/test_step30_planner.py
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add platform/execution_planning/src/design_execution_planning \
  tests/execution_planning/test_step30_routing.py \
  tests/execution_planning/test_step30_planner.py
git commit -m "feat(step30): project canonical execution units"
```

---

### Task 5: Group Units into deterministic ExecutionSlices and preserve the Step29 dependency graph

**Files:**
- Modify: `platform/execution_planning/src/design_execution_planning/planner.py`
- Create: `tests/execution_planning/test_step30_dependencies.py`
- Extend: `tests/execution_planning/test_step30_planner.py`

**Interfaces:**
- Produces: exact grouping key `(host_type, host_instance_id, document_ref, execution_slice_scope_rule_id)`
- Produces: `ExecutionDependency` from exact Step29 `ChangeDependency`
- Finalizes: `ExecutionPlan` and all Unit/Slice/Plan construction IDs.

- [ ] **Step 1: Write Slice grouping tests**

Add cases proving:

```python
def test_units_with_same_runtime_and_scope_share_one_slice(...): ...
def test_different_host_instance_creates_different_slice(...): ...
def test_different_document_creates_different_slice(...): ...
def test_different_approved_slice_scope_creates_different_slice(...): ...
def test_slice_id_and_hash_are_deterministic_under_operation_input_order(...): ...
```

Each Slice must bind the exact ChangeSet ID/hash, exact `HostRuntimeRef`, selected `ApprovedExecutionScopeRef`, sorted Units, and `execution_slice_id == "XS-" + execution_slice_hash[:12]`.

- [ ] **Step 2: Write dependency projection tests**

```python
def test_change_dependencies_project_one_to_one(step30_transaction):
    changeset, _ = step30_transaction
    plan = ExecutionPlanner().plan(valid_request(step30_transaction))
    unit_by_source = {
        unit.source_operation_id: unit.execution_unit_id
        for slice_ in plan.execution_slices
        for unit in slice_.execution_units
    }
    assert plan.execution_dependencies == tuple(
        sorted(
            (
                ExecutionDependency(
                    unit_by_source[dep.predecessor_operation_id],
                    unit_by_source[dep.successor_operation_id],
                    dep.reason_ref,
                )
                for dep in changeset.change_dependencies
            ),
            key=lambda dep: (
                dep.predecessor_execution_unit_id,
                dep.successor_execution_unit_id,
                dep.reason_ref,
            ),
        )
    )
```

Add a cross-slice version where root and derived operations route to different Host instances and assert the edge remains present unchanged. Add malformed dependency references and expect `EXECUTION_DEPENDENCY_INVALID`.

- [ ] **Step 3: Run and verify RED**

```bash
pytest -q tests/execution_planning/test_step30_planner.py \
  tests/execution_planning/test_step30_dependencies.py
```

Expected: FAIL until Slice grouping and dependency projection are complete.

- [ ] **Step 4: Group Units by exact key and create Slice hashes**

For each operation, retain its resolved runtime ref and selected slice scope alongside the constructed Unit. Group by the four-field key, sort Units by `execution_unit_hash`, hash the Slice, then derive `XS-...` IDs.

- [ ] **Step 5: Project dependencies mechanically**

Build a total `operation_id -> execution_unit_id` map. Require every Step29 predecessor/successor to exist exactly once. Create no edge not present in the ChangeSet and preserve each `reason_ref` byte-for-byte.

- [ ] **Step 6: Finalize the plan hash and ID**

Create plan-level `ApprovalScopeRef(boundary.scope_id, boundary.scope_hash)`, hash sorted Slice hashes plus normalized dependencies and routing hash, and derive:

```python
execution_plan_id = f"XP-{execution_plan_hash[:12]}"
```

- [ ] **Step 7: Run all focused Step30 behavior tests and commit**

```bash
pytest -q tests/execution_planning/test_step30_hashing.py \
  tests/execution_planning/test_step30_routing.py \
  tests/execution_planning/test_step30_scope_selection.py \
  tests/execution_planning/test_step30_planner.py \
  tests/execution_planning/test_step30_dependencies.py
```

Expected: PASS.

```bash
git add platform/execution_planning/src/design_execution_planning/planner.py \
  tests/execution_planning/test_step30_planner.py \
  tests/execution_planning/test_step30_dependencies.py
git commit -m "feat(step30): build execution slices and plan DAG"
```

---

### Task 6: Add architecture guards and lock the Step31/32/33 boundary

**Files:**
- Create: `tests/execution_planning/test_step30_architecture.py`
- Modify if necessary: `platform/execution_planning/src/design_execution_planning/__init__.py`

**Interfaces:**
- Verifies the public API is explicit.
- Verifies all public Step30 value contracts are frozen dataclasses.
- Verifies forbidden provider/native/governance/runtime concepts do not leak into production package source or request fields.

- [ ] **Step 1: Write the architecture guard**

Use the Step29 architecture-test pattern:

```python
ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = ROOT / "platform" / "execution_planning" / "src" / "design_execution_planning"


def test_step30_production_has_no_provider_native_or_runtime_leakage():
    forbidden = (
        "host_contracts",
        "HostCommand",
        "ProviderBinding",
        "provider_id",
        "provider_tool",
        "native_id",
        "ElementId",
        "Handle",
        "internal_unit",
        "binding_set_hash",
        "ApprovalRecord",
        "ExecutionGrant",
        "ActualDelta",
        "VerificationReport",
        "rollback",
        "saga",
    )
    production = "\n".join(
        path.read_text(encoding="utf-8") for path in sorted(PACKAGE_ROOT.glob("*.py"))
    )
    for marker in forbidden:
        assert marker not in production
```

Add explicit field guards:

```python
def test_step30_inputs_cannot_self_authorize_or_select_provider():
    request_fields = set(ExecutionPlanningRequest.__dataclass_fields__)
    unit_fields = set(ExecutionUnit.__dataclass_fields__)
    slice_fields = set(ExecutionSlice.__dataclass_fields__)
    assert {"provider_id", "provider_tool", "execution_slice_scope_rule_id"}.isdisjoint(request_fields)
    assert "execution_slice_id" not in unit_fields
    assert "status" not in slice_fields
```

- [ ] **Step 2: Run and verify RED if leakage exists**

```bash
pytest -q tests/execution_planning/test_step30_architecture.py
```

Expected: PASS once the production package respects the design; any failure is a boundary bug to fix before proceeding.

- [ ] **Step 3: Run Step28/29 regressions**

```bash
pytest -q tests/approval_scope tests/changeset
```

Expected: PASS. Step30 must not modify Step28/29 semantics.

- [ ] **Step 4: Commit**

```bash
git add tests/execution_planning/test_step30_architecture.py \
  platform/execution_planning/src/design_execution_planning/__init__.py
git commit -m "test(step30): guard execution planning boundaries"
```

---

### Task 7: Add dedicated CI, exact diff boundary, lint, and full verification

**Files:**
- Create: `.github/workflows/step30-execution-partitioning.yml`
- Modify: `docs/superpowers/specs/2026-08-29-step30-execution-partitioning-design.md` only to change status to implementation-complete when all gates pass.
- Keep: `docs/superpowers/plans/2026-08-30-step30-execution-partitioning.md` as the implementation checklist.

**Interfaces:**
- Produces one dedicated workflow named `Step30 execution partitioning`.
- Enforces the Step30 PR file boundary.

- [ ] **Step 1: Create the workflow with exact path triggers**

Use:

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

Install the same verification stack as Step29 plus `-e platform/execution_planning`; also install `-e platform/changeset` and the existing packages needed by the real Step28→29 fixtures.

- [ ] **Step 2: Add the PR diff-boundary guard**

For PRs from `feat/step30-execution-partitioning`, allow only:

```text
.github/workflows/step30-execution-partitioning.yml
docs/superpowers/specs/2026-08-29-step30-execution-partitioning-design.md
docs/superpowers/plans/2026-08-30-step30-execution-partitioning.md
platform/execution_planning/pyproject.toml
platform/execution_planning/src/design_execution_planning/__init__.py
platform/execution_planning/src/design_execution_planning/contracts.py
platform/execution_planning/src/design_execution_planning/hashing.py
platform/execution_planning/src/design_execution_planning/planner.py
pyproject.toml
tests/execution_planning/conftest.py
tests/execution_planning/test_step30_contracts.py
tests/execution_planning/test_step30_hashing.py
tests/execution_planning/test_step30_routing.py
tests/execution_planning/test_step30_scope_selection.py
tests/execution_planning/test_step30_planner.py
tests/execution_planning/test_step30_dependencies.py
tests/execution_planning/test_step30_architecture.py
```

- [ ] **Step 3: Add focused and regression steps**

The workflow must run, in this order:

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

Do not add ProviderBinding or runtime-execution tests to Step30; those belong to later steps.

- [ ] **Step 4: Run local/available verification before pushing**

Run the same commands above. If the local environment cannot execute the repo because GitHub is the only source of truth, push the branch and use the dedicated Actions run; do not claim success before the exact final head is green.

- [ ] **Step 5: Update the spec status only after all implementation gates pass**

Change the header to:

```text
**Status:** Implemented; verification complete
```

Do not change architectural content during this status-only edit unless a verified implementation discrepancy requires a design amendment.

- [ ] **Step 6: Commit the workflow/status update**

```bash
git add .github/workflows/step30-execution-partitioning.yml \
  docs/superpowers/specs/2026-08-29-step30-execution-partitioning-design.md
git commit -m "ci(step30): verify execution partitioning"
```

- [ ] **Step 7: Final exact-head verification checklist**

Before declaring Step30 implementation complete, record fresh evidence for:

```text
Step30 focused tests: all PASS
Step28 regression suite: PASS
Step29 regression suite: PASS
Ruff: All checks passed
Full repository pytest: PASS except only documented pre-existing/live-Host skips or warnings
Step30 exact PR diff boundary: PASS
Dedicated Step30 workflow on exact final head: completed/success
```

If any code changes after this verification, repeat the exact-head workflow and final checks.

---

## Self-Review Checklist for the Executor

Before implementation completion, verify every design invariant has a concrete test:

- closed-world routing: missing/conflict/extraneous/hash mismatch;
- exact ChangeSet↔ApprovalScopeBoundary binding;
- Step29 operation ID/source hash re-verification from exact existing-rule bodies;
- unique least-authority slice-scope selection and deterministic duplicate-body tie-break;
- one operation → one Unit;
- one operation cannot span Host instance/document boundaries;
- complete Step29 preconditions preserved on every Unit;
- exact Host/document/scope grouping;
- exact DAG projection including cross-slice dependencies;
- deterministic Unit/Slice/Plan hashes and IDs;
- immutable DTOs and defensive mapping copies;
- no provider/native/governance/runtime leakage;
- Step28 and Step29 regressions remain green;
- RevisionBarrier/provider switching are demonstrably outside Step30 hash material.

The implementation must not introduce an orchestrator integration, runtime Host lookup service, ProviderBinding, ExecutionGrant, or Saga code in Step30. Those are later-step work.
