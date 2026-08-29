# Step 25 D6 Parameter Binder Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the deterministic D6 Parameter Binder that combines LLM-owned INTENT values with provider-neutral context/default/derived canonical bindings and emits an auditable `BoundOperationProposal` before Phase-B freshness.

**Architecture:** Add one focused orchestrator module, `parameter_binder.py`, consuming the Step23 `CanonicalOperationDefinition` contract and a new ContextSnapshot-bound `ParameterBindingContext`. The binder uses explicit per-operation recipes for `CONTEXT`, `CANONICAL_DEFAULT`, and `DERIVED` slots, rejects non-INTENT LLM input, defers `PROVIDER` slots, validates canonical arguments with JSON Schema, and emits immutable binding evidence and planning requirements. No Host/provider package is imported.

**Tech Stack:** Python 3.11, dataclasses/enums/mapping proxies, `jsonschema>=4.20`, pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-step25-d6-parameter-binder-design.md`

## Global Constraints

- `main` baseline is `02e6c5040da9ad38f809b26ed00a6878569af777`.
- Work only on `feat/step25-d6-parameter-binder`.
- Step25 binds `INTENT`, `CONTEXT`, `CANONICAL_DEFAULT`, and `DERIVED` only.
- `PROVIDER` remains deferred until Step31.
- Do not import Host packages, provider implementations, D5 projection/storage types, or HostCommand into the production D6 module.
- Do not add InteractionSession, Host canvas prompts, Impact, ChangeSet, ExecutionUnit rewrites, ProviderBinding, or HostCommand generation.
- Every production behavior must be preceded by a failing test.
- Existing Step23/Step24 and relevant Python regressions must remain green.

---

### Task 1: Freeze Step25 design and verification boundary

**Files:**
- Create: `docs/superpowers/specs/2026-08-29-step25-d6-parameter-binder-design.md`
- Create: `docs/superpowers/plans/2026-08-29-step25-d6-parameter-binder.md`
- Create: `.github/workflows/step25-d6-parameter-binder.yml`

**Interfaces:**
- Consumes: master spec v0.6 D6 contract and Step23 canonical action contract.
- Produces: executable Step25 scope, CI test entry points, and regression boundary.

- [ ] **Step 1: Save the approved design spec**

The design spec must freeze `OperationProposal`, `ParameterBindingContext`, explicit recipes, binding evidence, `PlanningRequirements`, `BoundOperationProposal`, fail-closed rules, MOVE fixture, Phase-B ordering, and out-of-scope boundaries.

- [ ] **Step 2: Save this implementation plan**

Keep every implementation task TDD-sized and reference exact files/interfaces.

- [ ] **Step 3: Add Step25 workflow**

Create `.github/workflows/step25-d6-parameter-binder.yml` that installs the existing Python verification stack and runs:

```bash
pytest -q tests/orchestrator/test_step25_parameter_binder.py
pytest -q tests/orchestrator/test_step25_architecture.py
pytest -q tests/orchestrator/test_canonical_operations.py
pytest -q tests/orchestrator/test_operation_resolver.py
pytest -q tests/orchestrator/test_step24_semantic_eligibility.py
pytest -q tests/semantic_runtime/test_d4_freshness_integration.py
pytest -q --import-mode=importlib \
  contracts/python/tests \
  tests/contracts \
  tests/integration \
  tests/orchestrator \
  tests/semantic_runtime
```

The workflow may include a branch-scoped exact-diff guard, but such a guard MUST run only when `github.head_ref == 'feat/step25-d6-parameter-binder'` so it cannot break later PRs.

- [ ] **Step 4: Commit docs/workflow boundary**

```bash
git add docs/superpowers/specs/2026-08-29-step25-d6-parameter-binder-design.md \
        docs/superpowers/plans/2026-08-29-step25-d6-parameter-binder.md \
        .github/workflows/step25-d6-parameter-binder.yml
git commit -m "docs(step25): freeze D6 parameter binder boundary"
```

---

### Task 2: RED — freeze the D6 public contract and MOVE behavior

**Files:**
- Create: `tests/orchestrator/test_step25_parameter_binder.py`
- Create: `tests/orchestrator/test_step25_architecture.py`

**Interfaces:**
- Consumes: `CanonicalOperationDefinition`, `MOVE_V1`, `MVP_CANONICAL_OPERATIONS`, `SlotBindingClass` from `design_orchestrator.canonical_operations`.
- Produces expected production interfaces in `design_orchestrator.parameter_binder`:
  - `BindingError`
  - `BindingResolverKind`
  - `OperationProposal`
  - `ParameterBindingContext`
  - `SlotBindingRecipe`
  - `OperationBindingRecipe`
  - `SlotBindingEvidence`
  - `PlanningRequirements`
  - `CanonicalOperationRef`
  - `ContextSnapshotRef`
  - `BoundOperationProposal`
  - `ParameterBinder`
  - `MOVE_V1_BINDING_RECIPE`
  - `MVP_BINDING_RECIPES`

- [ ] **Step 1: Write failing MOVE happy-path test**

```python
from design_orchestrator.canonical_operations import MVP_CANONICAL_OPERATIONS
from design_orchestrator.parameter_binder import (
    MVP_BINDING_RECIPES,
    OperationProposal,
    ParameterBinder,
    ParameterBindingContext,
)


def test_move_binds_context_targets_and_intent_displacement() -> None:
    binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
    bound = binder.bind(
        OperationProposal("move.v1", {"displacement": [100, 0, 0]}),
        ParameterBindingContext(
            context_snapshot_id="CS-25",
            context_snapshot_hash="hash-25",
            document_ref="drawing-001",
            semantic_environment_ref="env-25",
            selection=("S-001", "S-002"),
        ),
    )

    assert bound.operation.canonical_operation == "move.v1"
    assert bound.arguments == {
        "targets": ["S-001", "S-002"],
        "displacement": [100, 0, 0],
    }
    assert bound.binding_evidence["targets"].source == "ContextSnapshot.selection"
    assert bound.binding_evidence["displacement"].source == "OperationProposal.intent_arguments"
```

- [ ] **Step 2: Add fail-closed proposal ownership tests**

Tests must prove:

```text
unknown operation                      → BindingError
unknown proposal slot                  → BindingError
LLM supplies CONTEXT targets           → BindingError
missing required INTENT displacement   → BindingError
empty required context selection       → BindingError
```

- [ ] **Step 3: Add explicit recipe/default/derived/provider tests**

Construct small synthetic `CanonicalOperationDefinition` fixtures proving:

```text
CONTEXT without recipe                        → fail
CANONICAL_DEFAULT with explicit literal       → pass
CANONICAL_DEFAULT without recipe              → fail
DERIVED with registered resolver              → pass
DERIVED with missing/unregistered resolver    → fail
PROVIDER required slot absent in D6           → allowed/deferred
LLM attempts PROVIDER slot                    → fail
recipe class mismatches canonical policy      → fail during binder construction
```

- [ ] **Step 4: Add canonical schema validation tests**

Use MOVE to prove a malformed displacement such as `[100, 0]` fails JSON Schema validation even though the slot ownership is otherwise correct.

- [ ] **Step 5: Add planning requirements and defensive-copy tests**

Prove `BoundOperationProposal.planning_requirements.operation_freshness_requirements` equals MOVE's platform-owned PLACEMENT/FRESH requirement and that mutating source proposal/context/default containers after construction cannot mutate the bound output.

- [ ] **Step 6: Add architecture guard**

`tests/orchestrator/test_step25_architecture.py` must read `parameter_binder.py` source and reject case-insensitive occurrences/imports of production-native concepts including:

```text
autocad
revit
tekla
hostcommand
providerbinding
provider_tool
provider_server
handle
elementid
```

The guard may allow the generic word `PROVIDER` only as `SlotBindingClass.PROVIDER`/deferred contract terminology; it must not allow provider routing/native implementation fields.

- [ ] **Step 7: Run RED tests and verify expected failure**

Run:

```bash
pytest -q tests/orchestrator/test_step25_parameter_binder.py \
          tests/orchestrator/test_step25_architecture.py
```

Expected: collection/import failure because `design_orchestrator.parameter_binder` does not yet exist. This is the required RED state.

- [ ] **Step 8: Commit RED tests**

```bash
git add tests/orchestrator/test_step25_parameter_binder.py \
        tests/orchestrator/test_step25_architecture.py
git commit -m "test(step25): freeze D6 parameter binder contract"
```

---

### Task 3: GREEN — implement the deterministic binder

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/parameter_binder.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Modify: `pyproject.toml`
- Test: `tests/orchestrator/test_step25_parameter_binder.py`
- Test: `tests/orchestrator/test_step25_architecture.py`

**Interfaces:**
- Consumes: `CanonicalOperationDefinition`, `SlotBindingClass`, `MOVE_V1`.
- Produces the exact public names listed in Task 2.

- [ ] **Step 1: Promote JSON Schema to runtime dependency**

Change root dependencies from:

```toml
dependencies = []
```

to:

```toml
dependencies = [
    "jsonschema>=4.20",
]
```

Keep the existing dev dependency entry; duplication between project runtime and dev extras is acceptable for this repository layout.

- [ ] **Step 2: Implement immutable input/output value objects**

Create `parameter_binder.py` with frozen/slots dataclasses and defensive copying for:

```python
class BindingError(ValueError): ...

class BindingResolverKind(str, Enum):
    CONTEXT_SELECTION = "CONTEXT_SELECTION"
    CONTEXT_VALUE = "CONTEXT_VALUE"
    CANONICAL_DEFAULT = "CANONICAL_DEFAULT"
    DERIVED = "DERIVED"

@dataclass(frozen=True, slots=True)
class OperationProposal:
    canonical_operation: str
    intent_arguments: Mapping[str, Any]

@dataclass(frozen=True, slots=True)
class ParameterBindingContext:
    context_snapshot_id: str
    context_snapshot_hash: str
    document_ref: str
    semantic_environment_ref: str
    selection: tuple[str, ...] = ()
    context_values: Mapping[str, Any] = field(default_factory=dict)

@dataclass(frozen=True, slots=True)
class CanonicalOperationRef:
    canonical_operation: str
    version: str

@dataclass(frozen=True, slots=True)
class ContextSnapshotRef:
    context_snapshot_id: str
    context_snapshot_hash: str
    document_ref: str

@dataclass(frozen=True, slots=True)
class SlotBindingEvidence:
    slot: str
    binding_class: SlotBindingClass
    source: str
    source_ref: str | None = None

@dataclass(frozen=True, slots=True)
class PlanningRequirements:
    operation_freshness_requirements: tuple[dict[str, Any], ...]
    coverage_requirements: tuple[dict[str, Any], ...]
    assurance_requirements: tuple[dict[str, Any], ...]

@dataclass(frozen=True, slots=True)
class BoundOperationProposal:
    operation: CanonicalOperationRef
    arguments: Mapping[str, Any]
    binding_evidence: Mapping[str, SlotBindingEvidence]
    context_snapshot_ref: ContextSnapshotRef
    planning_requirements: PlanningRequirements
    semantic_environment_ref: str
```

Mapping-valued fields must be copied and exposed read-only with `MappingProxyType` where practical.

- [ ] **Step 3: Implement recipe contracts and validation**

Implement:

```python
@dataclass(frozen=True, slots=True)
class SlotBindingRecipe:
    slot: str
    resolver_kind: BindingResolverKind
    source_key: str | None = None
    default_value: Any = <private sentinel>

@dataclass(frozen=True, slots=True)
class OperationBindingRecipe:
    canonical_operation: str
    slots: tuple[SlotBindingRecipe, ...]
```

`ParameterBinder.__init__` must build unique operation/recipe indexes and fail on duplicate operation ids, duplicate recipe ids/slots, missing deterministic recipes, unexpected recipes for INTENT/PROVIDER slots, and binding-class/resolver-kind mismatches.

- [ ] **Step 4: Implement deterministic resolution**

Use this ordering:

```text
INTENT
CONTEXT
CANONICAL_DEFAULT
DERIVED
PROVIDER deferred
```

Sources:

```text
INTENT                → OperationProposal.intent_arguments
CONTEXT_SELECTION     → ParameterBindingContext.selection
CONTEXT_VALUE         → ParameterBindingContext.context_values[source_key]
CANONICAL_DEFAULT     → SlotBindingRecipe.default_value
DERIVED               → registered resolver[source_key]
```

Derived resolver signature:

```python
Callable[[
    CanonicalOperationDefinition,
    OperationProposal,
    ParameterBindingContext,
    Mapping[str, Any],
], Any]
```

The mapping passed to DERIVED resolvers contains a defensive read-only snapshot of already bound non-derived arguments.

- [ ] **Step 5: Implement required-slot and JSON Schema barrier**

Before returning:

1. require every canonical `required` slot except `PROVIDER` slots;
2. make a deep copy of the canonical schema;
3. remove required PROVIDER slot names from only the copied schema's root `required` array;
4. call `jsonschema.validate(instance=arguments, schema=validation_schema)`;
5. translate `jsonschema.ValidationError`/`SchemaError` into `BindingError` without exposing provider-native data.

- [ ] **Step 6: Add MOVE recipe**

```python
MOVE_V1_BINDING_RECIPE = OperationBindingRecipe(
    canonical_operation="move.v1",
    slots=(
        SlotBindingRecipe(
            slot="targets",
            resolver_kind=BindingResolverKind.CONTEXT_SELECTION,
        ),
    ),
)

MVP_BINDING_RECIPES = (MOVE_V1_BINDING_RECIPE,)
```

- [ ] **Step 7: Export the Step25 public surface**

Update `design_orchestrator/__init__.py` to export the Step25 contracts and binder without changing existing exports.

- [ ] **Step 8: Run focused GREEN tests**

```bash
pytest -q tests/orchestrator/test_step25_parameter_binder.py \
          tests/orchestrator/test_step25_architecture.py
```

Expected: all Step25 tests pass.

- [ ] **Step 9: Commit production implementation**

```bash
git add platform/orchestrator/src/design_orchestrator/parameter_binder.py \
        platform/orchestrator/src/design_orchestrator/__init__.py \
        pyproject.toml
git commit -m "feat(step25): add deterministic D6 parameter binder"
```

---

### Task 4: Integrate D6 output with the existing Phase-B freshness bridge

**Files:**
- Modify: `tests/semantic_runtime/test_d4_freshness_integration.py`

**Interfaces:**
- Consumes: `ParameterBinder`, `OperationProposal`, `ParameterBindingContext`, `MVP_BINDING_RECIPES`, semantic-runtime `requirements_from_mappings`, `build_operation_contract`.
- Produces: proof that Step25 output supplies canonical target/material arguments and platform planning requirements to the existing Phase-B contract builder without Host/provider data.

- [ ] **Step 1: Write failing integration assertion first**

Extend the existing D4→D5 integration file with a test that:

```python
binder = ParameterBinder(MVP_CANONICAL_OPERATIONS, MVP_BINDING_RECIPES)
bound = binder.bind(
    OperationProposal("move.v1", {"displacement": [500, 0, 0]}),
    ParameterBindingContext(
        context_snapshot_id="CS-step25",
        context_snapshot_hash="hash-step25",
        document_ref="drawing-001",
        semantic_environment_ref="env-step25",
        selection=("sem-line-001",),
    ),
)
requirements = requirements_from_mappings(
    bound.planning_requirements.operation_freshness_requirements
)
contract = build_operation_contract(
    project_id="project-001",
    document_ref=bound.context_snapshot_ref.document_ref,
    canonical_operation=bound.operation.canonical_operation,
    targets=bound.arguments["targets"],
    arguments={"displacement": bound.arguments["displacement"]},
    requirements=requirements,
)
```

Assert PLACEMENT/FRESH is preserved and the fingerprint is produced.

- [ ] **Step 2: Run integration test**

```bash
pytest -q tests/semantic_runtime/test_d4_freshness_integration.py
```

Expected: PASS once Task 3 implementation exists. The test is still written before any bridge-specific production code; if no production change is required, this task remains an integration proof rather than adding unnecessary code.

- [ ] **Step 3: Commit the bridge proof**

```bash
git add tests/semantic_runtime/test_d4_freshness_integration.py
git commit -m "test(step25): prove D6 to Phase-B freshness bridge"
```

---

### Task 5: Full regression and PR closeout

**Files:**
- Verify all Step25 changed files only.
- No new production behavior should be added in this task.

**Interfaces:**
- Consumes: completed Step25 branch.
- Produces: verified PR ready for review, not merged automatically.

- [ ] **Step 1: Run focused regressions**

```bash
pytest -q tests/orchestrator/test_step25_parameter_binder.py
pytest -q tests/orchestrator/test_step25_architecture.py
pytest -q tests/orchestrator/test_canonical_operations.py
pytest -q tests/orchestrator/test_operation_resolver.py
pytest -q tests/orchestrator/test_step24_semantic_eligibility.py
pytest -q tests/semantic_runtime/test_d4_freshness_integration.py
```

All must pass.

- [ ] **Step 2: Run relevant full Python regression**

```bash
pytest -q --import-mode=importlib \
  contracts/python/tests \
  tests/contracts \
  tests/integration \
  tests/orchestrator \
  tests/semantic_runtime
```

All non-environmental tests must pass; known real-Host skips remain acceptable.

- [ ] **Step 3: Verify diff boundary**

Expected Step25 files:

```text
.github/workflows/step25-d6-parameter-binder.yml
docs/superpowers/specs/2026-08-29-step25-d6-parameter-binder-design.md
docs/superpowers/plans/2026-08-29-step25-d6-parameter-binder.md
platform/orchestrator/src/design_orchestrator/__init__.py
platform/orchestrator/src/design_orchestrator/parameter_binder.py
pyproject.toml
tests/orchestrator/test_step25_parameter_binder.py
tests/orchestrator/test_step25_architecture.py
tests/semantic_runtime/test_d4_freshness_integration.py
```

No Host implementation, semantic provider, ChangeSet, ExecutionUnit, or ProviderBinding production files may change.

- [ ] **Step 4: Open/update PR**

Title:

```text
feat(step25): deterministic D6 parameter binder
```

PR body must summarize:

- frozen D6 boundary;
- TDD RED evidence;
- deterministic recipes and ownership rules;
- PROVIDER deferral;
- MOVE proof;
- Phase-B bridge proof;
- exact changed files;
- focused/full CI results.

- [ ] **Step 5: Verify PR workflows on the final head SHA**

Require the Step25 workflow and all triggered existing regression workflows to complete successfully before calling the PR merge-ready.
