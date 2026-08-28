# D5 v0.6 Baseline Completion — Execution Record

**PR:** #5 `feat(semantic): add D5 semantic runtime`  
**Branch:** `feat/semantic-runtime`  
**Spec basis:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md` sections 4, 19, 20, 43 and Appendices A/D.

This file records the executed v0.6 D5 baseline plan. The implementation was performed task-by-task with RED→GREEN tests for behavior changes and fresh GitHub Actions verification after each implementation task.

## Goal

Evolve the v0.5 freshness MVP into the provider-neutral v0.6 D5 baseline:

- 1:N semantic identity across Hosts;
- generic external identities rather than IFC-special fields;
- first-class `CLASSIFICATION`;
- orthogonal progressive semantic axes;
- exact revision/coverage/guarantee freshness barriers;
- immutable snapshots bound to semantic projection and one pinned SemanticEnvironment.

## Frozen architecture constraints

- Host remains the real-time native source of truth; D5 is a progressive canonical projection.
- `semantic_runtime` must not import AutoCAD/Revit/Tekla native packages.
- `semantic_runtime` must not hardcode enterprise layer/family/category mappings.
- D5 must not special-case IFC GlobalId; external identities use `scheme + value`.
- One `SemanticIdentity` may own multiple `HostBinding` values.
- Persistent `HostBinding` remains separate from runtime Host/provider binding.
- `CLASSIFICATION` is a first-class `SemanticAspect`.
- Freshness, Coverage/Maturity, Semantic Depth, Geometry Fidelity, and Assurance remain orthogonal.
- Context Freshness stays at geometry `NONE/BOUNDS`; Phase B is derived after D6 material binding.
- Snapshot binds exact Host revision, exact contract coverage, `SemanticProjectionRef`, and `SemanticEnvironmentRef`.
- One `SnapshotSet` uses one pinned `SemanticEnvironment` and contains PlanningSnapshots only, one per document.
- Semantic MCP, Semantic Service, IFC4.3/DSP Core/Metro/Enterprise providers, D6, and D7 are follow-up PRs.

---

## Task 1 — Replace IFC-special identity with 1:N host/external identity

**Commit:** `70adb382d9a31191dfa5d0a9ba25f4153d8c6962` — `refactor(semantic): support multi-host identities`

- [x] Introduce immutable `SemanticIdentity`, `HostBinding`, and `ExternalIdentity`.
- [x] Add `IdentityRegistry.ensure_identity()`, `bind_host()`, `bind_external()`, `host_bindings()`, `external_identities()`, `by_host()`, and `by_external()`.
- [x] Enforce uniqueness of `(host_type, document_id, native_id)` across semantic identities.
- [x] Enforce uniqueness of `(scheme, value)` across semantic identities.
- [x] Allow one semantic identity to own multiple HostBindings.
- [x] Remove `IdentityBinding`, `bind_ifc_global_id`, and the IFC-special identity test.
- [x] Represent IFC GlobalId generically as an `ExternalIdentity`, e.g. scheme `ifc.global_id`.
- [x] RED verified on missing new public API; GREEN verified locally.
- [x] GitHub Actions verification after Task 1: **24 focused passed; 165 full passed, 4 live-AutoCAD skips**.

## Task 2 — Add progressive axes and `CLASSIFICATION`

**Commit:** `d7d24d8c1b5f614f31349ce8e1f902dfb8cfc05e` — `feat(semantic): add progressive requirement axes`

- [x] Add `SemanticAspect.CLASSIFICATION`.
- [x] Add ordered `CoverageState` (`UNRESOLVED`, `PARTIAL`, `RESOLVED`).
- [x] Add ordered `SemanticDepth` (`NATIVE`, `NORMALIZED`, `CANONICAL`, `DOMAIN`).
- [x] Add ordered `AssuranceLevel` (`UNKNOWN`, `HEURISTIC`, `RULE_DERIVED`, `STANDARD_MAPPED`, `NATIVE_ASSERTED`).
- [x] Keep existing `GeometryLevel` as the single Geometry Fidelity enum.
- [x] Extend `AspectRequirement` and `AspectGuarantee` with independent progressive axes.
- [x] Include progressive requirement axes in deterministic contract hashing.
- [x] Extend `requirements_from_mappings()` with fail-closed canonical enum parsing.
- [x] Merge duplicate requirements per aspect independently by axis.
- [x] Stop the D3→D4→D5 bridge test from locking provider-native entity kinds into D5.
- [x] RED verified on missing enums/fields; GREEN verified locally.
- [x] GitHub Actions verification after Task 2: **32 focused passed; 173 full passed, 4 live-AutoCAD skips**.

## Task 3 — Bind reconstruction/snapshots to projection and environment

**Commit:** `c34556ad0c11a79c4e86a4f60c4eb07ffbda2d36` — `feat(semantic): bind snapshots to semantic environment`

- [x] Add provider-neutral `SemanticProjectionRef`.
- [x] Add provider-neutral `SemanticEnvironmentRef`.
- [x] Require both refs on accepted `ReconstructionResult` values.
- [x] Store and hash both refs in `SemanticSnapshot`.
- [x] Make direct `SemanticSnapshot.create()` reject exact-coverage mismatch.
- [x] Make snapshot hash change when projection or environment content changes.
- [x] Enforce PlanningSnapshot-only `SnapshotSet` with one snapshot per document.
- [x] Enforce one pinned `SemanticEnvironmentRef` across every SnapshotSet member.
- [x] Bind SnapshotSet hash to environment, member snapshot hash, Host revision, and projection ref.
- [x] Keep refs as value objects only; no Provider registry/routing/cache/MCP implementation was added.
- [x] RED verified on missing refs/fields; GREEN verified locally.
- [x] GitHub Actions verification after Task 3: **36 focused passed; 177 full passed, 4 live-AutoCAD skips**.

## Task 4 — Enforce progressive requirements in `FreshnessResolver`

**Commit:** `fde3ab04e3b29e30fc1152d9d5d431ae3177b8ba` — `feat(semantic): enforce coverage and assurance barriers`

- [x] Aggregate the strongest matching guarantee independently per progressive axis.
- [x] Reject missing aspect freshness.
- [x] Reject insufficient Geometry Fidelity.
- [x] Reject insufficient/missing Coverage/Maturity when requested.
- [x] Reject insufficient/missing Semantic Depth when requested.
- [x] Reject insufficient Assurance.
- [x] Keep revision, exact coverage, and guarantee `coverage_ref` checks fail-closed.
- [x] Produce deterministic missing reasons such as `CLASSIFICATION.assurance`.
- [x] Preserve fail-before-`DirtyMap.mark_fresh()` ordering for every barrier.
- [x] RED verified: weak progressive guarantees incorrectly passed before implementation.
- [x] GREEN verified: coverage, depth, assurance rejection and passing classification cases all succeeded.
- [x] GitHub Actions run #70: **40 focused passed; 181 full passed, 4 live-AutoCAD skips**.

## Task 5 — Public surface, leakage checks, final PR closeout

- [x] Public surface exposes `SemanticIdentity`, `HostBinding`, `ExternalIdentity`, `SemanticProjectionRef`, and `SemanticEnvironmentRef`.
- [x] Public surface no longer exposes `IdentityBinding`.
- [x] Add a permanent `test_public_surface.py` guard for the public API and architecture leakage rules.
- [x] Verify runtime source contains no `Autodesk`, `BuiltInCategory`, `if host ==`, or `ifc_global_id` leakage.
- [x] Verify runtime source contains no `SemanticProvider`, `McpSemantic`, `MetroProvider`, or `Ifc43Provider` implementation leakage.
- [x] Keep `.github/workflows/semantic-runtime.yml` unchanged because its existing paths/install commands already cover D5 code, tests, this plan, and full regression.
- [x] Update PR #5 description to the v0.6 baseline and explicitly preserve follow-up boundaries.
- [x] Record pre-closeout implementation evidence from run #70: **40 focused passed; 181 full passed, 4 skipped**.
- [x] Closeout commit `3096e546e5027ebe52609eb98e0687c8092c5741` received fresh PR merge-ref CI in run #72: **42 focused passed; 183 full passed, 4 skipped**. All four skips are the existing live-AutoCAD tests gated by `AGENT_HOST_TEST=1`.

### Task 5 verification commands

```bash
python - <<'PY'
import semantic_runtime as s
assert not hasattr(s, "IdentityBinding")
assert hasattr(s, "SemanticIdentity")
assert hasattr(s, "HostBinding")
assert hasattr(s, "ExternalIdentity")
assert hasattr(s, "SemanticProjectionRef")
assert hasattr(s, "SemanticEnvironmentRef")
PY

pytest -q tests/semantic_runtime
pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime

! grep -R "Autodesk\|BuiltInCategory\|if host ==\|ifc_global_id" platform/semantic_runtime/src/semantic_runtime
! grep -R "SemanticProvider\|McpSemantic\|MetroProvider\|Ifc43Provider" platform/semantic_runtime/src/semantic_runtime
```

Expected skips are limited to the four existing live-AutoCAD integration tests gated by `AGENT_HOST_TEST=1`.

---

## Explicit follow-up PR boundaries

### Follow-up A — Semantic Service / Semantic MCP

Create `platform/semantic_service` and provider contracts/registry/routing/environment/cache. IFC4.3, DSP Core, Metro, and Enterprise semantic providers live behind this service. Host-specific normalization/mapping logic does not move into D5 Core.

### Follow-up B — D3/D4 Canonical Action Contract

Refactor `DesignCapabilityProfile.entity_constraints` into provider-native constraints plus platform-owned canonical semantic constraints; add operation title/description/slot metadata and coverage/assurance requirements; stop exposing provider-native entity kinds to the LLM action space.

### Follow-up C — D6/D7

Only after D5 + Semantic Service + D4 contract boundaries are frozen: Parameter Binder/InteractionSession, Impact/Propagation, ChangeSet/ApprovalScopeBoundary, ExecutionSlice/canonical ExecutionUnit, ProviderBinding/ExecutionGrant, Verify/Scope Comparator/Saga.

## Closeout status

Tasks 1–5 are complete. The v0.6 D5 baseline is implementation-complete, public-surface/leakage guarded, and verified on the PR merge ref. PR #5 may leave Draft and enter normal review; merging remains a separate review decision.