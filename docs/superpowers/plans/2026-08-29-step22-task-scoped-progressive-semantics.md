# Step 22 — Task-Scoped Progressive Semantics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make canonical operations, not unbound Host providers, own D5 task semantic requirements, then prove D5 upgrades only the explicitly requested aspects, coverage, semantic depth, assurance, and geometry fidelity.

**Architecture:** Add one platform-owned `operation_freshness_requirements` field to `CanonicalOperationDefinition`; make `OperationResolver` copy that canonical metadata into `ResolvedOperation` instead of unioning candidate provider `execution_freshness`. Keep provider execution freshness intact on provider candidates for future late-bound execution admission. Reuse the existing D5 requirement parser, `FreshnessContract`, `FreshnessResolver`, `DirtyMap`, and snapshot model unchanged, and prove progressive minimality with focused integration tests plus an exact changed-file CI gate.

**Tech Stack:** Python 3.11, dataclasses, pytest, jsonschema, existing `autocad_sidecar`, `design_orchestrator`, `semantic_runtime`, Semantic Service/provider stack for Step21 regression, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-step22-task-scoped-progressive-semantics-design.md`

## Global Constraints

- Base: `main@112864e529e4573b81947b97596d3d05ca4344bd`.
- Branch: `feat/step22-task-scoped-progressive-semantics`.
- Never write directly to `main`.
- Canonical task semantic requirements are owned by `CanonicalOperationDefinition`.
- Provider `DesignCapabilityProfile.execution_freshness` remains provider-owned metadata and must remain available in `ResolutionResult.provider_candidates`.
- Candidate-provider `execution_freshness` must not be unioned into `ResolvedOperation.operation_freshness_requirements` before ProviderBinding.
- `MOVE_V1.operation_freshness_requirements` is exactly `PLACEMENT / FRESH`.
- `MOVE_V1` may still aggregate provider effects including `PLACEMENT` and `GEOMETRY`; effects must not implicitly become freshness requirements.
- No new semantic requirement DTO.
- No D5 public API or production-code change.
- No Host production-code change.
- No Semantic Service, Semantic MCP, IFC, Metro, Enterprise Mapping, ChangeSet, approval, execution-grant, or ProviderBinding implementation change.
- Do not make the LLM choose freshness, coverage, assurance, semantic depth, or geometry fidelity.
- Preserve existing fail-closed behavior for freshness, coverage, semantic depth, assurance, geometry fidelity, revision, and exact coverage matching.
- `RULE_DERIVED` evidence must never be reported as stronger assurance.
- A task targeting one semantic entity must not silently expand to whole-document or whole-project coverage.
- Do not merge the resulting PR without explicit user merge authorization.

---

## File Structure

```text
platform/orchestrator/src/design_orchestrator/canonical_operations.py
    Adds platform-owned operation_freshness_requirements and pins MOVE_V1 to PLACEMENT/FRESH.

platform/orchestrator/src/design_orchestrator/operation_resolver.py
    Copies canonical operation freshness requirements into ResolvedOperation; stops provider-union inflation.

tests/orchestrator/test_operation_resolver.py
    D4 ownership regression: canonical requirements win; provider execution freshness remains internal.

tests/integration/test_step22_task_scoped_progressive.py
    D4 -> D5 progressive proof for MOVE, classification-only, coverage minimality, and explicit stronger geometry.

.github/workflows/step22-task-scoped-progressive.yml
    Exact changed-file boundary and focused/relevant regression suites.

docs/superpowers/specs/2026-08-29-step22-task-scoped-progressive-semantics-design.md
    Approved design baseline.

docs/superpowers/plans/2026-08-29-step22-task-scoped-progressive-semantics.md
    This implementation plan.
```

Production files outside the two orchestrator files above must remain unchanged.

---

### Task 1: Move task-semantic ownership into the canonical operation contract

**Files:**
- Modify: `tests/orchestrator/test_operation_resolver.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_operations.py`
- Modify: `platform/orchestrator/src/design_orchestrator/operation_resolver.py`

**Interfaces:**
- Consumes existing `CanonicalOperationDefinition` fields: `canonical_operation`, `category`, `input_schema`, `verification_contract`, `context_freshness_requirements`.
- Produces new field: `operation_freshness_requirements: tuple[dict[str, Any], ...] = ()`.
- `MOVE_V1.operation_freshness_requirements` is exactly `({"aspect": "PLACEMENT", "required_state": "FRESH"},)`.
- `ResolvedOperation.operation_freshness_requirements` remains the same public field and type; only its owner/source changes.
- Provider candidate objects retain their existing `execution_freshness` unchanged.

- [ ] **Step 1: Add the multi-provider RED regression**

Append to `tests/orchestrator/test_operation_resolver.py`:

```python
def test_canonical_operation_owns_task_freshness_not_provider_union() -> None:
    canonical = CanonicalOperationDefinition(
        canonical_operation="move.v1",
        category="MODEL_OPERATION",
        input_schema=json.loads(json.dumps(GENERIC_CANONICAL_SCHEMA)),
        verification_contract={"type": "HOST_READ_BACK"},
        operation_freshness_requirements=(
            {"aspect": "PLACEMENT", "required_state": "FRESH"},
        ),
    )
    profiles = (
        Profile(
            "autocad.local",
            "cad.move",
            execution_freshness=(
                {"aspect": "PLACEMENT", "required_state": "FRESH"},
            ),
        ),
        Profile(
            "vendor.optimized",
            "vendor.move",
            execution_freshness=(
                {"aspect": "PLACEMENT", "required_state": "FRESH"},
                {
                    "aspect": "GEOMETRY",
                    "required_state": "FRESH",
                    "geometry_level": "EXACT",
                },
            ),
        ),
    )

    result = OperationResolver((canonical,)).resolve(
        profiles,
        context("autocad.local", "vendor.optimized"),
    )
    resolved = result.resolved_operations[0]

    assert resolved.operation_freshness_requirements == (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    vendor = next(
        profile
        for profile in result.provider_candidates.values()
        if profile.provider_server == "vendor.optimized"
    )
    assert vendor.execution_freshness == (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
        {
            "aspect": "GEOMETRY",
            "required_state": "FRESH",
            "geometry_level": "EXACT",
        },
    )
```

Also add the effect/non-requirement separation regression:

```python
def test_effects_do_not_implicitly_create_task_freshness_requirements() -> None:
    result = OperationResolver((MOVE_V1,)).resolve(
        (Profile("autocad.local", "cad.move"),),
        context("autocad.local"),
    )
    resolved = result.resolved_operations[0]

    assert resolved.operation_freshness_requirements == (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    assert set(resolved.effects) == {"PLACEMENT", "GEOMETRY"}
```

- [ ] **Step 2: Run the ownership test to verify RED**

Run:

```bash
pytest -q tests/orchestrator/test_operation_resolver.py::test_canonical_operation_owns_task_freshness_not_provider_union
```

Expected before production changes: FAIL because `CanonicalOperationDefinition` does not yet accept `operation_freshness_requirements`.

- [ ] **Step 3: Add the canonical operation field with defensive copying**

In `platform/orchestrator/src/design_orchestrator/canonical_operations.py`, add the field immediately after `context_freshness_requirements`:

```python
operation_freshness_requirements: tuple[dict[str, Any], ...] = ()
```

Extend `__post_init__`:

```python
object.__setattr__(
    self,
    "operation_freshness_requirements",
    tuple(deepcopy(item) for item in self.operation_freshness_requirements),
)
```

Set `MOVE_V1` explicitly:

```python
operation_freshness_requirements=(
    {"aspect": "PLACEMENT", "required_state": "FRESH"},
),
```

Do not add geometry, classification, coverage, semantic-depth, or assurance requirements to `MOVE_V1`.

- [ ] **Step 4: Make D4 copy canonical freshness instead of unioning providers**

In `_build_resolved_operation()` in `platform/orchestrator/src/design_orchestrator/operation_resolver.py`, replace:

```python
operation_freshness_requirements=self._aggregate_mapping_items(
    profile.execution_freshness for profile in profiles
),
```

with:

```python
operation_freshness_requirements=deepcopy(
    definition.operation_freshness_requirements
),
```

Delete `_aggregate_mapping_items()` if it has no remaining caller after this change. Do not change `_aggregate_effects()`, risk aggregation, preview/rollback aggregation, provider-candidate IDs, Host filtering, Entity filtering, Policy filtering, or Task ranking.

- [ ] **Step 5: Verify Task 1 GREEN**

Run:

```bash
pytest -q tests/orchestrator/test_operation_resolver.py
```

Expected: all existing resolver tests plus the two new ownership regressions pass.

Then run the existing D4 -> D5 contract bridge:

```bash
pytest -q tests/semantic_runtime/test_d4_freshness_integration.py
```

Expected: existing real AutoCAD MOVE test still resolves to exactly:

```python
(AspectRequirement(SemanticAspect.PLACEMENT),)
```

- [ ] **Step 6: Commit Task 1**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/canonical_operations.py \
  platform/orchestrator/src/design_orchestrator/operation_resolver.py \
  tests/orchestrator/test_operation_resolver.py
git commit -m "fix(step22): make canonical operations own task freshness"
```

---

### Task 2: Prove D5 only upgrades requested aspects and fidelity

**Files:**
- Create: `tests/integration/test_step22_task_scoped_progressive.py`
- Reference only: `tests/integration/test_step21_d5_canonical_projection.py`
- Reference only: `platform/semantic_runtime/src/semantic_runtime/freshness.py`
- Reference only: `platform/semantic_runtime/src/semantic_runtime/journal.py`

**Interfaces:**
- Consumes real AutoCAD `cad.move` capability through `build_tool_definitions()` + `parse_design_capability()`.
- Consumes real D4 `OperationResolver((MOVE_V1,))`.
- Consumes `requirements_from_mappings(...) -> tuple[AspectRequirement, ...]`.
- Consumes existing `build_operation_contract(...)`, `FreshnessResolver.resolve(...)`, `DirtyMap`, `AspectGuarantee`, `ReconstructionResult`.
- Produces tests only; no new runtime helper or production interface.

- [ ] **Step 1: Create deterministic test references and reconstruction helper**

Create `tests/integration/test_step22_task_scoped_progressive.py` with:

```python
from __future__ import annotations

import pytest

from autocad_sidecar.capability.profile import parse_design_capability
from autocad_sidecar.mcp_server import build_tool_definitions
from design_orchestrator.canonical_operations import MOVE_V1
from design_orchestrator.operation_resolver import OperationResolver, ResolutionContext
from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    AssuranceLevel,
    CoverageState,
    DirtyMap,
    FreshnessResolver,
    FreshnessState,
    FreshnessUnsatisfiedError,
    GeometryLevel,
    ReconstructionResult,
    SemanticAspect,
    SemanticDepth,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    build_operation_contract,
    requirements_from_mappings,
)

PROJECTION_REF = SemanticProjectionRef(
    "step22-projection",
    "step22-projection-hash",
    "step22-proof-v1",
    "step22-provider-set-hash",
    "step22-mapping-profile-set-hash",
)
ENVIRONMENT_REF = SemanticEnvironmentRef(
    "step22-environment",
    "step22-environment-hash",
)


def _result(contract, revision: str, *guarantees: AspectGuarantee) -> ReconstructionResult:
    return ReconstructionResult(
        document_ref=contract.coverage.document_ref,
        host_revision=revision,
        coverage=contract.coverage,
        guarantees=tuple(guarantees),
        projection_ref=PROJECTION_REF,
        semantic_environment_ref=ENVIRONMENT_REF,
    )
```

The helper must return exactly the guarantees supplied by the test. It must not add aspects, increase semantic depth, increase assurance, or increase geometry level.

- [ ] **Step 2: Add the real MOVE minimality proof**

Add:

```python
def test_real_move_upgrades_only_placement() -> None:
    tools = {tool["name"]: tool for tool in build_tool_definitions()}
    profile = parse_design_capability(
        tools["cad.move"],
        provider_server="autocad.local",
    )
    resolution = OperationResolver((MOVE_V1,)).resolve(
        (profile,),
        ResolutionContext(
            host_provider_servers=frozenset({"autocad.local"}),
            entity_kinds=frozenset(),
        ),
    )
    resolved = resolution.resolved_operations[0]
    requirements = requirements_from_mappings(
        resolved.operation_freshness_requirements
    )

    assert requirements == (AspectRequirement(SemanticAspect.PLACEMENT),)
    assert "GEOMETRY" in resolved.effects

    contract = build_operation_contract(
        project_id="project-step22",
        document_ref="drawing-001",
        canonical_operation=resolved.canonical_operation,
        targets=("sem-line-001",),
        arguments={"displacement": [500, 0, 0]},
        requirements=requirements,
    )
    assert contract.coverage.root_entities == ("sem-line-001",)

    dirty = DirtyMap()
    dirty.mark_dirty(
        "drawing-001",
        "sem-line-001",
        (
            SemanticAspect.PLACEMENT,
            SemanticAspect.GEOMETRY,
            SemanticAspect.CLASSIFICATION,
        ),
    )

    snapshot = FreshnessResolver(dirty).resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda current, revision: _result(
            current,
            revision,
            AspectGuarantee(SemanticAspect.PLACEMENT),
        ),
    )

    assert tuple(item.aspect for item in snapshot.aspect_guarantees) == (
        SemanticAspect.PLACEMENT,
    )
    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.PLACEMENT
    ) is FreshnessState.FRESH
    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.GEOMETRY
    ) is FreshnessState.DIRTY
    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.CLASSIFICATION
    ) is FreshnessState.DIRTY
```

This proves the difference between pre-operation requirements and post-operation effects.

- [ ] **Step 3: Add classification-only progressive proof**

Add:

```python
def test_classification_only_task_does_not_upgrade_geometry_or_assurance() -> None:
    requirement = AspectRequirement(
        SemanticAspect.CLASSIFICATION,
        geometry_level=GeometryLevel.NONE,
        minimum_coverage=CoverageState.RESOLVED,
        semantic_depth=SemanticDepth.CANONICAL,
        minimum_assurance=AssuranceLevel.RULE_DERIVED,
    )
    contract = build_operation_contract(
        project_id="project-step22",
        document_ref="drawing-001",
        canonical_operation="classify.v1",
        targets=("sem-wall-001",),
        arguments={},
        requirements=(requirement,),
    )
    dirty = DirtyMap()
    dirty.mark_dirty(
        "drawing-001",
        "sem-wall-001",
        (SemanticAspect.CLASSIFICATION, SemanticAspect.GEOMETRY),
    )

    snapshot = FreshnessResolver(dirty).resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda current, revision: _result(
            current,
            revision,
            AspectGuarantee(
                SemanticAspect.CLASSIFICATION,
                coverage_state=CoverageState.RESOLVED,
                semantic_depth=SemanticDepth.CANONICAL,
                assurance_level=AssuranceLevel.RULE_DERIVED,
            ),
        ),
    )

    assert len(snapshot.aspect_guarantees) == 1
    guarantee = snapshot.aspect_guarantees[0]
    assert guarantee.aspect is SemanticAspect.CLASSIFICATION
    assert guarantee.geometry_level is GeometryLevel.NONE
    assert guarantee.semantic_depth is SemanticDepth.CANONICAL
    assert guarantee.assurance_level is AssuranceLevel.RULE_DERIVED
    assert dirty.state(
        "drawing-001", "sem-wall-001", SemanticAspect.CLASSIFICATION
    ) is FreshnessState.FRESH
    assert dirty.state(
        "drawing-001", "sem-wall-001", SemanticAspect.GEOMETRY
    ) is FreshnessState.DIRTY
```

- [ ] **Step 4: Add explicit stronger-geometry fail-closed proof**

Add:

```python
def test_exact_geometry_is_required_only_when_explicitly_requested() -> None:
    contract = build_operation_contract(
        project_id="project-step22",
        document_ref="drawing-001",
        canonical_operation="geometry.inspect.v1",
        targets=("sem-line-001",),
        arguments={},
        requirements=(
            AspectRequirement(
                SemanticAspect.GEOMETRY,
                GeometryLevel.EXACT,
            ),
        ),
    )
    dirty = DirtyMap()
    dirty.mark_dirty(
        "drawing-001",
        "sem-line-001",
        (SemanticAspect.GEOMETRY, SemanticAspect.CLASSIFICATION),
    )

    with pytest.raises(
        FreshnessUnsatisfiedError,
        match=r"GEOMETRY\.geometry",
    ):
        FreshnessResolver(dirty).resolve(
            contract,
            expected_host_revision="42",
            reconstruct=lambda current, revision: _result(
                current,
                revision,
                AspectGuarantee(
                    SemanticAspect.GEOMETRY,
                    GeometryLevel.BOUNDS,
                ),
            ),
        )

    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.GEOMETRY
    ) is FreshnessState.DIRTY

    snapshot = FreshnessResolver(dirty).resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda current, revision: _result(
            current,
            revision,
            AspectGuarantee(
                SemanticAspect.GEOMETRY,
                GeometryLevel.EXACT,
            ),
        ),
    )

    assert snapshot.aspect_guarantees[0].geometry_level is GeometryLevel.EXACT
    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.GEOMETRY
    ) is FreshnessState.FRESH
    assert dirty.state(
        "drawing-001", "sem-line-001", SemanticAspect.CLASSIFICATION
    ) is FreshnessState.DIRTY
```

- [ ] **Step 5: Verify Step22 focused D5 proof**

Run:

```bash
pytest -q tests/integration/test_step22_task_scoped_progressive.py
```

Expected: `3 passed`.

Then run existing progressive and Step21 guarantees:

```bash
pytest -q \
  tests/semantic_runtime/test_progressive_requirements.py \
  tests/integration/test_step21_d5_canonical_projection.py
```

Expected: all existing fail-closed coverage/depth/assurance tests and Step21 classification proof remain green.

- [ ] **Step 6: Commit Task 2**

```bash
git add tests/integration/test_step22_task_scoped_progressive.py
git commit -m "test(step22): prove task-scoped progressive reconstruction"
```

---

### Task 3: Add Step22 CI and exact architecture boundary

**Files:**
- Create: `.github/workflows/step22-task-scoped-progressive.yml`
- Reference only: `.github/workflows/step21-d5-canonical-projection.yml`
- Reference only: `.github/workflows/operation-resolver.yml`
- Reference only: `.github/workflows/semantic-runtime.yml`

**Interfaces:**
- Produces one PR workflow named `Step22 task-scoped progressive semantics`.
- Enforces an exact seven-file Step22 boundary.
- Reuses the full semantic stack so Step21 regression runs without optional-provider skips.

- [ ] **Step 1: Create the workflow trigger and dependency setup**

Create `.github/workflows/step22-task-scoped-progressive.yml` beginning with:

```yaml
name: Step22 task-scoped progressive semantics

on:
  pull_request:
    paths:
      - "platform/orchestrator/src/design_orchestrator/canonical_operations.py"
      - "platform/orchestrator/src/design_orchestrator/operation_resolver.py"
      - "tests/orchestrator/test_operation_resolver.py"
      - "tests/integration/test_step22_task_scoped_progressive.py"
      - "docs/superpowers/specs/2026-08-29-step22-task-scoped-progressive-semantics-design.md"
      - "docs/superpowers/plans/2026-08-29-step22-task-scoped-progressive-semantics.md"
      - ".github/workflows/step22-task-scoped-progressive.yml"
  push:
    paths:
      - "platform/orchestrator/src/design_orchestrator/canonical_operations.py"
      - "platform/orchestrator/src/design_orchestrator/operation_resolver.py"
      - "tests/orchestrator/test_operation_resolver.py"
      - "tests/integration/test_step22_task-scoped-progressive.py"
      - ".github/workflows/step22-task-scoped-progressive.yml"
  workflow_dispatch:

jobs:
  step22-task-scoped-progressive:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install Step22 stack
        run: |
          python -m pip install pytest pytest-asyncio jsonschema PyYAML==6.0.3
          python -m pip install \
            -e contracts/python \
            -e hosts/autocad/sidecar \
            -e platform/semantic_runtime \
            -e platform/semantic_service \
            -e platform/semantic_mcp \
            -e providers/semantics/dsp_core \
            -e providers/semantics/ifc43 \
            -e providers/semantics/metro_v32 \
            -e providers/semantics/enterprise_mapping
```

The root `pyproject.toml` already provides `platform/orchestrator/src` in pytest `pythonpath`; do not modify `pyproject.toml` in Step22.

- [ ] **Step 2: Add an exact PR changed-file gate**

Add:

```yaml
      - name: Verify Step22 PR diff boundary
        if: github.event_name == 'pull_request'
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          changed="$(git diff --name-only "$BASE_SHA...$HEAD_SHA")"
          printf '%s\n' "$changed"
          bad="$(printf '%s\n' "$changed" | grep -Ev '^(\.github/workflows/step22-task-scoped-progressive\.yml|docs/superpowers/(specs/2026-08-29-step22-task-scoped-progressive-semantics-design\.md|plans/2026-08-29-step22-task-scoped-progressive-semantics\.md)|platform/orchestrator/src/design_orchestrator/(canonical_operations|operation_resolver)\.py|tests/orchestrator/test_operation_resolver\.py|tests/integration/test_step22_task_scoped_progressive\.py)$' || true)"
          if [ -n "$bad" ]; then
            echo "Step22 changed files outside approved boundary:"
            printf '%s\n' "$bad"
            exit 1
          fi
```

This gate is the primary proof that Step22 did not modify D5, Host, Semantic Service/MCP, semantic providers, contracts, or ChangeSet production code.

- [ ] **Step 3: Add focused and regression commands**

Add these workflow steps in this order:

```yaml
      - name: Run Step22 D4 ownership tests
        run: pytest -q tests/orchestrator/test_operation_resolver.py

      - name: Run Step22 progressive D5 proof
        run: pytest -q tests/integration/test_step22_task_scoped_progressive.py

      - name: Run existing D4 to D5 freshness bridge
        run: pytest -q tests/semantic_runtime/test_d4_freshness_integration.py

      - name: Run progressive semantic runtime regression
        run: pytest -q tests/semantic_runtime/test_progressive_requirements.py

      - name: Run Step21 canonical projection regression
        run: |
          pytest -q \
            tests/integration/test_step21_d5_canonical_projection.py \
            tests/semantic_runtime/test_step21_architecture.py

      - name: Run relevant full Python regression
        run: |
          pytest -q --import-mode=importlib \
            contracts/python/tests \
            tests/contracts \
            tests/integration \
            tests/orchestrator \
            tests/semantic_runtime \
            tests/semantic_service \
            tests/semantic_mcp \
            tests/semantic_providers/dsp_core \
            tests/semantic_providers/ifc43 \
            tests/semantic_providers/metro_v32 \
            tests/semantic_providers/enterprise_mapping
```

- [ ] **Step 4: Commit Task 3**

```bash
git add .github/workflows/step22-task-scoped-progressive.yml
git commit -m "ci(step22): enforce progressive semantics boundary"
```

---

### Task 4: Final verification, architecture review, and PR preparation

**Files:**
- No new production files.
- Review all seven approved Step22 files.

**Interfaces:**
- Consumes the final branch head.
- Produces verification evidence and a draft PR only after fresh green checks.

- [ ] **Step 1: Verify the exact branch diff against the merged Step21 base**

Run:

```bash
git diff --name-only 112864e529e4573b81947b97596d3d05ca4344bd...HEAD
```

Expected changed files are exactly:

```text
.github/workflows/step22-task-scoped-progressive.yml
docs/superpowers/plans/2026-08-29-step22-task-scoped-progressive-semantics.md
docs/superpowers/specs/2026-08-29-step22-task-scoped-progressive-semantics-design.md
platform/orchestrator/src/design_orchestrator/canonical_operations.py
platform/orchestrator/src/design_orchestrator/operation_resolver.py
tests/integration/test_step22_task_scoped_progressive.py
tests/orchestrator/test_operation_resolver.py
```

Any additional changed path is a stop condition until reviewed against the approved design.

- [ ] **Step 2: Verify forbidden production areas have zero diff**

Run:

```bash
git diff --exit-code 112864e529e4573b81947b97596d3d05ca4344bd...HEAD -- \
  platform/semantic_runtime \
  platform/semantic_service \
  platform/semantic_mcp \
  hosts/autocad \
  providers/semantics \
  contracts \
  platform/changeset
```

Expected: exit code `0` and no diff output.

- [ ] **Step 3: Run focused local verification from the final tree**

Run:

```bash
pytest -q tests/orchestrator/test_operation_resolver.py
pytest -q tests/integration/test_step22_task_scoped_progressive.py
pytest -q tests/semantic_runtime/test_d4_freshness_integration.py
pytest -q tests/semantic_runtime/test_progressive_requirements.py
pytest -q tests/integration/test_step21_d5_canonical_projection.py
```

All must pass on the final tree. Do not claim success from earlier runs.

- [ ] **Step 4: Run the broad relevant Python regression**

Run:

```bash
pytest -q --import-mode=importlib \
  contracts/python/tests \
  tests/contracts \
  tests/integration \
  tests/orchestrator \
  tests/semantic_runtime \
  tests/semantic_service \
  tests/semantic_mcp \
  tests/semantic_providers/dsp_core \
  tests/semantic_providers/ifc43 \
  tests/semantic_providers/metro_v32 \
  tests/semantic_providers/enterprise_mapping
```

Expected: zero failures. Existing live-AutoCAD gated skips are acceptable only if they remain the known `AGENT_HOST_TEST=1` cases.

- [ ] **Step 5: Review the final implementation against the ownership checklist**

Confirm all statements are true:

```text
CanonicalOperationDefinition owns operation_freshness_requirements.
MOVE_V1 canonical requirement is PLACEMENT/FRESH only.
ResolvedOperation copies canonical requirements.
Provider execution_freshness remains on provider candidates.
No candidate-provider freshness union feeds D5 before binding.
Effects do not implicitly become task semantic requirements.
MOVE makes only PLACEMENT fresh in the Step22 proof.
Classification-only task leaves GEOMETRY dirty.
Exact geometry fails closed until EXACT evidence is supplied.
No stronger assurance is fabricated.
Operation coverage remains exactly the explicit target set.
D5 production diff is zero.
Host production diff is zero.
Semantic provider production diff is zero.
Step23 ProviderBinding/execution admission is not implemented here.
```

- [ ] **Step 6: Push the final branch and require fresh GitHub Actions evidence**

Push `feat/step22-task-scoped-progressive-semantics` and verify the Step22 workflow completes successfully at the exact final head SHA. If an existing workflow also triggers because of the two orchestrator production files, it must also be green before PR readiness is claimed.

- [ ] **Step 7: Open a draft PR against `main`**

Use title:

```text
fix(step22): keep D5 reconstruction task-scoped
```

PR body must state:

```text
Goal: Canonical Operation owns D5 task semantic requirements; unbound providers cannot inflate reconstruction.

Production changes:
- canonical_operations.py: add canonical operation_freshness_requirements; MOVE_V1 = PLACEMENT/FRESH.
- operation_resolver.py: copy canonical requirements instead of unioning provider execution_freshness.

Preserved boundaries:
- provider execution_freshness retained for future late ProviderBinding/execution admission;
- D5 production diff 0;
- Host production diff 0;
- Semantic provider production diff 0;
- no Step23 ProviderBinding implementation.

Proofs:
- multi-provider stronger provider precondition does not inflate D5 task requirement;
- MOVE upgrades only PLACEMENT;
- classification-only task leaves geometry untouched;
- exact geometry only required when explicit and fails closed otherwise;
- Step21 canonical classification proof remains green.
```

Keep the PR draft until final review is clean. Never merge without explicit user authorization.

---

## Completion Criterion

Step 22 is complete only when fresh verification proves this chain:

```text
Canonical task
  -> CanonicalOperationDefinition.operation_freshness_requirements
  -> ResolvedOperation.operation_freshness_requirements
  -> requirements_from_mappings
  -> D5 FreshnessContract
  -> only requested aspects/fidelity reconstructed
  -> only requested aspects marked fresh
```

and independently proves:

```text
candidate provider execution_freshness
  remains provider-owned metadata
  != source of pre-binding D5 task requirements
```

The final architecture rule is:

> The task determines what D5 must understand. A selected Host provider may later require stronger execution evidence, but unselected providers cannot increase D5 semantic reconstruction scope.
