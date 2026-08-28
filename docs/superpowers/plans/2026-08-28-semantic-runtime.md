# D5 v0.6 Baseline Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Evolve PR #5 from the v0.5 freshness MVP into the v0.6 D5 baseline: provider-neutral 1:N identity, progressive semantic requirements, classification/assurance, and snapshots bound to semantic projection and one pinned SemanticEnvironment.

**Architecture:** Preserve the working ChangeJournal/DirtyMap and the deterministic revision/coverage freshness barrier. Replace the old `IdentityBinding + ifc_global_id` model with `SemanticIdentity + HostBinding[] + ExternalIdentity[]`, then extend freshness value objects so Coverage/Maturity, Semantic Depth, Geometry Fidelity, Freshness, and Assurance remain orthogonal. `ReconstructionResult`, `SemanticSnapshot`, and `SnapshotSet` gain provider-neutral projection/environment references, but this PR MUST NOT implement Semantic MCP, IFC/Metro providers, D6, or D7.

**Tech Stack:** Python 3.11, dataclasses/enums/hashlib/json, pytest, GitHub Actions.

**Spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md` sections 4, 19, 20, 43 and Appendices A/D.

## Global Constraints

- Host remains the real-time native source of truth; D5 is a progressive canonical projection.
- `semantic_runtime` MUST NOT import AutoCAD/Revit/Tekla native packages.
- `semantic_runtime` MUST NOT hardcode enterprise layer/family/category mappings.
- D5 MUST NOT special-case IFC GlobalId; external identities use `scheme + value`.
- One SemanticIdentity MAY have multiple HostBindings.
- Persistent HostBinding MUST remain separate from runtime HostRuntimeRef/provider binding.
- `CLASSIFICATION` is a first-class SemanticAspect.
- Freshness, Coverage/Maturity, Semantic Depth, Geometry Fidelity, and Assurance are orthogonal.
- Context Freshness defaults to geometry `NONE/BOUNDS`; Phase B occurs after D6 material binding.
- Snapshot MUST bind exact Host revision, contract coverage, SemanticProjectionRef, and SemanticEnvironmentRef.
- One SnapshotSet MUST use one pinned SemanticEnvironment.
- SnapshotSet contains PlanningSnapshots only, one per document.
- Semantic MCP Server, IFC4.3 Provider, DSP Core Provider, Metro Provider, Enterprise Mapping Provider, D6, and D7 are follow-up PRs.

---

### Task 1: Replace IFC-special identity with 1:N host/external identity

**Files:**
- Modify: `platform/semantic_runtime/src/semantic_runtime/identity.py`
- Modify: `platform/semantic_runtime/src/semantic_runtime/__init__.py`
- Delete: `tests/semantic_runtime/test_identity_ifc_binding.py`
- Create: `tests/semantic_runtime/test_identity_multihost.py`
- Modify: `tests/semantic_runtime/test_semantic_runtime.py`

**Interfaces:**
- Produces: `SemanticIdentity`, `HostBinding`, `ExternalIdentity`, `IdentityRegistry.ensure_identity()`, `bind_host()`, `bind_external()`, `host_bindings()`, `external_identities()`, `by_host()`, `by_external()`.
- Invariant: `(host_type, document_id, native_id)` and `(scheme, value)` each map to at most one semantic identity; one semantic identity may own many bindings.

- [ ] **Step 1: Write failing multi-host and generic external-identity tests**

```python
from semantic_runtime import ExternalIdentity, HostBinding, IdentityConflictError, IdentityRegistry


def test_one_semantic_identity_can_bind_autocad_and_revit() -> None:
    registry = IdentityRegistry()
    registry.ensure_identity("S-WALL-001")
    cad = registry.bind_host(HostBinding("S-WALL-001", "autocad", "dwg-1", "A31", "LWPOLYLINE"))
    revit = registry.bind_host(HostBinding("S-WALL-001", "revit", "rvt-1", "38912", "Wall"))

    assert registry.host_bindings("S-WALL-001") == (cad, revit)
    assert registry.by_host("autocad", "dwg-1", "A31").semantic_id == "S-WALL-001"
    assert registry.by_host("revit", "rvt-1", "38912").semantic_id == "S-WALL-001"


def test_ifc_global_id_is_generic_external_identity() -> None:
    registry = IdentityRegistry()
    registry.ensure_identity("S-WALL-001")
    external = registry.bind_external(ExternalIdentity("S-WALL-001", "ifc.global_id", "2Ksd"))

    assert registry.by_external("ifc.global_id", "2Ksd") == external
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/semantic_runtime/test_identity_multihost.py`
Expected: import/API failures for the new identity contract.

- [ ] **Step 3: Implement immutable identity value objects and fail-closed registry indexes**

```python
@dataclass(frozen=True, slots=True)
class SemanticIdentity:
    semantic_id: str


@dataclass(frozen=True, slots=True)
class HostBinding:
    semantic_id: str
    host_type: str
    document_id: str
    native_id: str
    native_kind: str


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    semantic_id: str
    scheme: str
    value: str
```

Registry indexes SHALL be semantic id → identity, semantic id → host bindings, semantic id → external identities, host key → binding, external key → identity. Rebinding an occupied host/external key to another semantic id raises `IdentityConflictError`.

- [ ] **Step 4: Replace all `IdentityBinding` / `bind_ifc_global_id` assertions**

Run: `grep -R "IdentityBinding\|ifc_global_id\|bind_ifc_global_id" tests/semantic_runtime platform/semantic_runtime/src/semantic_runtime`
Expected after edits: no production/test references except migration/spec prose.

- [ ] **Step 5: Run focused identity tests**

Run: `pytest -q tests/semantic_runtime/test_identity_multihost.py tests/semantic_runtime/test_semantic_runtime.py`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add platform/semantic_runtime/src/semantic_runtime/identity.py platform/semantic_runtime/src/semantic_runtime/__init__.py tests/semantic_runtime
git commit -m "refactor(semantic): support multi-host identities"
```

---

### Task 2: Add progressive coverage, semantic depth, assurance, and CLASSIFICATION

**Files:**
- Modify: `platform/semantic_runtime/src/semantic_runtime/freshness.py`
- Modify: `platform/semantic_runtime/src/semantic_runtime/adapters.py`
- Modify: `platform/semantic_runtime/src/semantic_runtime/__init__.py`
- Create: `tests/semantic_runtime/test_progressive_requirements.py`
- Modify: `tests/semantic_runtime/test_d4_freshness_integration.py`

**Interfaces:**
- Produces: `CoverageState`, `SemanticDepth`, `AssuranceLevel`, `SemanticAspect.CLASSIFICATION` and extended `AspectRequirement` / `AspectGuarantee`.
- Keeps existing `GeometryLevel` as the implementation enum for the Spec's Geometry Fidelity axis; do not introduce a second competing geometry enum in this PR.

- [ ] **Step 1: Write failing orthogonality/gate tests**

```python
from semantic_runtime import (
    AspectGuarantee, AspectRequirement, AssuranceLevel, CoverageState,
    GeometryLevel, SemanticAspect, SemanticDepth,
)


def test_classification_is_first_class_aspect() -> None:
    assert SemanticAspect.CLASSIFICATION.value == "CLASSIFICATION"


def test_requirement_keeps_progressive_axes_separate() -> None:
    requirement = AspectRequirement(
        SemanticAspect.CLASSIFICATION,
        minimum_coverage=CoverageState.RESOLVED,
        semantic_depth=SemanticDepth.CANONICAL,
        minimum_assurance=AssuranceLevel.RULE_DERIVED,
    )
    assert requirement.geometry_level is GeometryLevel.NONE
```

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/semantic_runtime/test_progressive_requirements.py`
Expected: missing enum/field failures.

- [ ] **Step 3: Implement ordered progressive enums**

```python
class CoverageState(IntEnum):
    UNRESOLVED = 0
    PARTIAL = 1
    RESOLVED = 2


class SemanticDepth(IntEnum):
    NATIVE = 0
    NORMALIZED = 1
    CANONICAL = 2
    DOMAIN = 3


class AssuranceLevel(IntEnum):
    UNKNOWN = 0
    HEURISTIC = 1
    RULE_DERIVED = 2
    STANDARD_MAPPED = 3
    NATIVE_ASSERTED = 4
```

Extend `AspectRequirement` with optional `minimum_coverage`, optional `semantic_depth`, existing geometry level, and `minimum_assurance=UNKNOWN`. Extend `AspectGuarantee` with actual coverage/depth/assurance evidence.

- [ ] **Step 4: Extend the mapping adapter without adding Host/provider imports**

`requirements_from_mappings()` SHALL accept canonical keys `minimum_coverage`, `semantic_depth`, `geometry_level`, and `minimum_assurance`; unknown enum names fail closed.

- [ ] **Step 5: Stop the D3→D4→D5 bridge test from locking native entity semantics into D5**

In `test_real_d3_move_freshness_flows_through_d4_into_d5_contract`, use an empty `entity_kinds` context (or otherwise bypass native entity filtering) so this test verifies only freshness-contract translation. Native/canonical entity-constraint separation belongs to the later D3/D4 PR.

- [ ] **Step 6: Run focused tests and commit**

Run: `pytest -q tests/semantic_runtime/test_progressive_requirements.py tests/semantic_runtime/test_d4_freshness_integration.py`
Expected: PASS.

```bash
git add platform/semantic_runtime/src/semantic_runtime tests/semantic_runtime
git commit -m "feat(semantic): add progressive requirement axes"
```

---

### Task 3: Bind reconstruction and snapshots to projection/environment references

**Files:**
- Modify: `platform/semantic_runtime/src/semantic_runtime/freshness.py`
- Modify: `platform/semantic_runtime/src/semantic_runtime/__init__.py`
- Modify: `tests/semantic_runtime/test_project_snapshot_binding.py`
- Modify: `tests/semantic_runtime/test_snapshot_contract_shape.py`
- Create: `tests/semantic_runtime/test_snapshot_environment.py`

**Interfaces:**
- Produces: `SemanticProjectionRef`, `SemanticEnvironmentRef`.
- `ReconstructionResult` requires projection/environment refs.
- `SemanticSnapshot` hashes projection/environment refs.
- `SnapshotSet` derives and freezes one `semantic_environment_ref` shared by all members.

- [ ] **Step 1: Write failing snapshot-environment tests**

```python
from semantic_runtime import SemanticEnvironmentRef, SnapshotSet, SnapshotSetError


def test_snapshot_set_requires_one_pinned_environment(planning_snapshot_factory) -> None:
    env_a = SemanticEnvironmentRef("ENV-A", "hash-a")
    env_b = SemanticEnvironmentRef("ENV-B", "hash-b")
    first = planning_snapshot_factory(document="doc-a", environment=env_a)
    second = planning_snapshot_factory(document="doc-b", environment=env_b)

    with pytest.raises(SnapshotSetError, match="SemanticEnvironment"):
        SnapshotSet.create((first, second))
```

Also add a test proving snapshot hash changes when only `projection_hash` or environment hash changes.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/semantic_runtime/test_snapshot_environment.py`
Expected: missing reference types/fields.

- [ ] **Step 3: Implement provider-neutral reference contracts**

```python
@dataclass(frozen=True, slots=True)
class SemanticEnvironmentRef:
    environment_id: str
    content_hash: str


@dataclass(frozen=True, slots=True)
class SemanticProjectionRef:
    projection_id: str
    projection_hash: str
    semantic_model_version: str
    provider_set_hash: str
    mapping_profile_set_hash: str
    normalized_fact_batch_hash: str | None = None
```

These are references only. Do not add registry/routing/provider logic to D5.

- [ ] **Step 4: Extend ReconstructionResult and SemanticSnapshot hash payloads**

Both refs SHALL be required for accepted reconstruction results. `SemanticSnapshot.create()` SHALL reject result coverage that differs from the contract even when called directly, not only through `FreshnessResolver`.

- [ ] **Step 5: Enforce SnapshotSet environment invariant**

All members MUST be PlanningSnapshots, one per document, and have equal `SemanticEnvironmentRef`. SnapshotSet hash SHALL include the environment ref plus each member's snapshot hash, host revision, and projection ref/hash.

- [ ] **Step 6: Run focused snapshot tests and commit**

Run: `pytest -q tests/semantic_runtime/test_project_snapshot_binding.py tests/semantic_runtime/test_snapshot_contract_shape.py tests/semantic_runtime/test_snapshot_environment.py`
Expected: PASS.

```bash
git add platform/semantic_runtime/src/semantic_runtime tests/semantic_runtime
git commit -m "feat(semantic): bind snapshots to semantic environment"
```

---

### Task 4: Enforce progressive requirements in FreshnessResolver

**Files:**
- Modify: `platform/semantic_runtime/src/semantic_runtime/freshness.py`
- Modify: `tests/semantic_runtime/test_semantic_runtime.py`
- Modify: `tests/semantic_runtime/test_progressive_requirements.py`

**Interfaces:**
- Consumes extended `AspectRequirement` / `AspectGuarantee` from Task 2.
- Produces deterministic failures for insufficient freshness, coverage, semantic depth, geometry fidelity, or assurance before DirtyMap is marked FRESH.

- [ ] **Step 1: Write failing barrier tests**

```python
def test_barrier_rejects_fresh_but_low_assurance_claim() -> None:
    requirement = AspectRequirement(
        SemanticAspect.CLASSIFICATION,
        minimum_coverage=CoverageState.RESOLVED,
        semantic_depth=SemanticDepth.CANONICAL,
        minimum_assurance=AssuranceLevel.STANDARD_MAPPED,
    )
    weak = AspectGuarantee(
        SemanticAspect.CLASSIFICATION,
        coverage_state=CoverageState.RESOLVED,
        semantic_depth=SemanticDepth.CANONICAL,
        assurance_level=AssuranceLevel.RULE_DERIVED,
    )
    # resolve(...) must raise FreshnessUnsatisfiedError and leave DirtyMap DIRTY
```

Add equivalent coverage and semantic-depth failures, plus a passing `CLASSIFICATION` case.

- [ ] **Step 2: Run tests and verify RED**

Run: `pytest -q tests/semantic_runtime/test_progressive_requirements.py`
Expected: resolver currently checks only aspect/geometry.

- [ ] **Step 3: Extend guarantee-strength comparison**

For each requirement, the strongest matching guarantee must satisfy every requested axis. Build a structured `missing` reason list such as `CLASSIFICATION.assurance` rather than weakening the barrier.

- [ ] **Step 4: Preserve fail-before-mark-fresh ordering**

No DirtyMap mutation may happen until revision, exact scope, guarantee coverage_ref, and all progressive requirement checks pass.

- [ ] **Step 5: Run all D5 tests and commit**

Run: `pytest -q tests/semantic_runtime`
Expected: PASS.

```bash
git add platform/semantic_runtime/src/semantic_runtime/freshness.py tests/semantic_runtime
git commit -m "feat(semantic): enforce coverage and assurance barriers"
```

---

### Task 5: Update public surface, CI evidence, and PR scope

**Files:**
- Modify: `platform/semantic_runtime/src/semantic_runtime/__init__.py`
- Modify: `.github/workflows/semantic-runtime.yml` only if test paths/install commands require it
- Modify: `docs/superpowers/plans/2026-08-28-semantic-runtime.md`
- PR metadata: #5

**Interfaces:**
- Public D5 baseline exports only D5 value objects/resolvers/references.
- No `SemanticProvider`, MCP server, IFC/Metro vocabulary, D6, or D7 implementation is added.

- [ ] **Step 1: Verify public API no longer exposes old identity types**

Run: `python - <<'PY'
import semantic_runtime as s
assert not hasattr(s, "IdentityBinding")
assert hasattr(s, "SemanticIdentity")
assert hasattr(s, "HostBinding")
assert hasattr(s, "ExternalIdentity")
assert hasattr(s, "SemanticProjectionRef")
assert hasattr(s, "SemanticEnvironmentRef")
PY`
Expected: PASS.

- [ ] **Step 2: Run focused regression**

Run: `pytest -q tests/semantic_runtime`
Expected: all focused tests PASS.

- [ ] **Step 3: Run full Python regression**

Run: `pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime`
Expected: all non-live tests PASS; only live AutoCAD tests gated by `AGENT_HOST_TEST=1` may skip.

- [ ] **Step 4: Run architecture leakage scans**

```bash
! grep -R "Autodesk\|BuiltInCategory\|if host ==\|ifc_global_id" platform/semantic_runtime/src/semantic_runtime
! grep -R "SemanticProvider\|McpSemantic\|MetroProvider\|Ifc43Provider" platform/semantic_runtime/src/semantic_runtime
```

Expected: both commands succeed (no matches).

- [ ] **Step 5: Update PR #5 description**

PR body SHALL describe the v0.6 D5 baseline and explicitly list follow-up PRs: Semantic Service/Providers and D3/D4 action-contract refactor. Remove the old claims that `ifc_global_id` is a D5 field or that v0.5 Appendix D is the active implementation basis.

- [ ] **Step 6: Record final verification evidence and commit**

```bash
git add .github/workflows/semantic-runtime.yml docs/superpowers/plans/2026-08-28-semantic-runtime.md platform/semantic_runtime tests/semantic_runtime
git commit -m "docs: close D5 v0.6 baseline verification"
```

---

## Explicit Follow-up PR Boundaries

### Follow-up A — Semantic Service / Semantic MCP

Create `platform/semantic_service` and provider contracts/registry/routing/environment/cache. Implement no Host mapping in D5. IFC4.3, DSP Core, Metro, and Enterprise semantic providers belong behind this service.

### Follow-up B — D3/D4 Canonical Action Contract

Refactor `DesignCapabilityProfile.entity_constraints` to `provider_native_constraints`; add platform-owned canonical semantic constraints, operation title/description/slot metadata, coverage/assurance requirements, and stop exposing provider-native entity kinds to the LLM action space.

### Follow-up C — D6/D7

Only after D5 + Semantic Service + D4 contract boundaries are frozen: Parameter Binder/InteractionSession, Impact, ChangeSet, ExecutionSlice, canonical ExecutionUnit, ProviderBinding, grants, verify/scope/saga.

## Self-Review

- Spec coverage: this plan covers v0.6 Phase B D5 Baseline Completion only; Semantic Service, Action Contract, D6, and D7 are intentionally split into follow-up PRs.
- Placeholder scan: no TBD/TODO/"implement later" steps are used as implementation instructions.
- Type consistency: `SemanticIdentity`, `HostBinding`, `ExternalIdentity`, progressive enums, `SemanticProjectionRef`, and `SemanticEnvironmentRef` are introduced before later tasks consume them.
- Existing green evidence before this refactor: PR merge-ref at branch head `2a24b7b...` ran **24 focused passed; 165 full passed, 4 live-AutoCAD skips**. That evidence is baseline-only and must be replaced by fresh evidence after Tasks 1–5.
