# D5 Semantic Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Implement the v0.5 Appendix D step 5 Semantic Runtime minimum: Identity Registry, Change Journal, Dirty Map, contract-bound Context/Planning Snapshots, SnapshotSet, and two-phase freshness.

**Architecture:** Keep D5 in the existing host-neutral `platform/semantic_runtime` package. Model freshness contracts and immutable snapshots as deterministic value objects with canonical hashes; keep identity/journal/dirty tracking in focused modules; use a deterministic `FreshnessResolver` that accepts selective reconstruction results, enforces revision stability and exact contract coverage/scope, then emits a ContextSnapshot or PlanningSnapshot. Do not add D6 interaction/parameter binding or D7 ChangeSet/execution behavior.

**Tech Stack:** Python 3.11, dataclasses/enums/hashlib/json, pytest, GitHub Actions.

**Spec:** `Enterprise_Collaborative_Design_Agent_Spec_v0.5.md` sections 7–8, AR-017/AR-026/AR-028, Appendix A.2/A.9, Appendix D step 5.

## Global Constraints

- Host remains the real-time design source of truth; Semantic Runtime is a progressive task-scoped projection.
- v0.1 semantic aspects: IDENTITY, PROPERTIES, PLACEMENT, GEOMETRY, SPATIAL, CONNECTIVITY, RELATIONSHIPS, CONSTRAINTS.
- Freshness states: FRESH, STALE, DIRTY, UNKNOWN, RECONSTRUCTING.
- Context Freshness is Phase A before Operation Resolution and should stay at geometry level 0–1.
- Operation Freshness is Phase B after OperationProposal/parameter binding and follows selected operation requirements.
- SemanticFreshnessContract and SemanticSnapshot bind a real `project_id`; no synthetic/default project identity is introduced.
- SemanticSnapshot binds freshness contract, exact coverage, base host revision, scoped aspect guarantees, and hash.
- SnapshotSet for ChangeSet use contains PlanningSnapshots only, with one member per document; single-host MVP still uses the set abstraction.
- Host revision changes during reconstruction invalidate the snapshot rather than silently reusing it.
- Coverage MUST NOT silently expand during reconstruction, and guarantee scope mismatch fails before Dirty Map state is marked FRESH.
- No Autodesk native types may enter the platform package.

---

### Task 1: Freeze D5 contracts with focused tests

**Files:**
- Create: `tests/semantic_runtime/test_semantic_runtime.py`
- Create: `.github/workflows/semantic-runtime.yml`

**Interfaces:**
- Consumes: spec v0.5 sections 7–8 and D4 freshness requirement dictionaries.
- Produces: executable contract for the D5 public API.

- [x] Write tests first for identity round-trip/conflicts, journal→dirty aspect invalidation, context geometry cap, operation contract hashing, contract-bound snapshots, revision/coverage/guarantee barriers, and PlanningSnapshot-only SnapshotSet.
- [x] Run focused CI and verify RED is caused by missing `semantic_runtime` implementation (`ModuleNotFoundError`).

### Task 2: Implement identity, journal, and dirty tracking

**Files:**
- Create: `platform/semantic_runtime/src/semantic_runtime/identity.py`
- Create: `platform/semantic_runtime/src/semantic_runtime/journal.py`

**Interfaces:**
- Produces: `IdentityBinding`, `IdentityRegistry`, `HostDeltaRecord`, `JournalEntry`, `ChangeJournal`, `DirtyMap`.

- [x] Implement immutable semantic/native identity bindings with fail-closed rebinding.
- [x] Support optional/on-demand IFC GlobalId binding and uniqueness without changing semantic/native identity.
- [x] Implement append-only in-memory journal sequence and entity+aspect Dirty Map states.

### Task 3: Implement freshness contracts, snapshots, and resolver

**Files:**
- Create: `platform/semantic_runtime/src/semantic_runtime/freshness.py`
- Create: `platform/semantic_runtime/src/semantic_runtime/adapters.py`
- Create: `platform/semantic_runtime/src/semantic_runtime/__init__.py`

**Interfaces:**
- Produces: semantic/freshness enums, `AspectRequirement`, `AspectGuarantee`, `Coverage`, `FreshnessContract`, `ReconstructionResult`, `SemanticSnapshot`, `SnapshotSet`, `FreshnessResolver`, context/operation contract builders, D4 freshness metadata adapter, structured freshness errors.

- [x] Implement deterministic canonical hashing for contracts/snapshots/snapshot sets.
- [x] Enforce Phase A geometry <= BOUNDS.
- [x] Bind Phase B contract identity to project, canonical operation, targets, arguments, and operation freshness requirements.
- [x] Normalize real D3/D4 freshness metadata into D5 requirements without importing Host/MCP production types.
- [x] Reject changed host revision, mismatched/expanded coverage, mismatched guarantee scope, and insufficient guarantees.
- [x] Mark only contract-required root entity aspects FRESH after a successful barrier.
- [x] Emit CONTEXT snapshots for Phase A and PLANNING snapshots for Phase B.
- [x] Bind Snapshot guarantees to the contract coverage reference and include `project_id`.
- [x] Reject ContextSnapshots and duplicate-document PlanningSnapshots in SnapshotSet.

### Task 4: Verification and PR

**Files:**
- PR: `feat/semantic-runtime` → `main`

- [x] Verify `semantic-runtime` installs as an editable package in CI.
- [x] Run focused D5 tests: **24 passed** on code head `5ac89b4fceb9af109f5dd78fed31eae7946690c4`.
- [x] Run full Python regression including D3/D4 suites: **165 passed, 4 skipped**; skips are live AutoCAD gates requiring `AGENT_HOST_TEST=1`.
- [x] Review for D6/D7 scope creep and Autodesk/native leakage; none introduced.
- [x] Keep PR unmerged and move it to Ready for Review only after final-head CI is green.

## TDD / Review Evidence

1. Initial invalid RED exposed only CI scaffolding (`semantic-runtime` editable install before `src/` existed); CI was corrected without production code.
2. Valid RED: `ModuleNotFoundError: semantic_runtime`.
3. GREEN core: Identity Registry, Change Journal, Dirty Map, Freshness contracts/snapshots/resolver.
4. Review RED: missing D4→D5 `requirements_from_mappings`; fixed with provider-neutral adapter and real `cad.move → D4 → D5` integration test.
5. Review RED: five contract-shape gaps covering IFC on-demand identity, neighborhood relations, explicit FRESH guarantee, and Planning SnapshotSet invariants.
6. Review RED: Appendix A.2/A.9 review caught missing `project_id` and guarantee coverage scope; scope mismatch additionally verifies Dirty Map remains DIRTY.
7. Final code GREEN before documentation closeout: **24 focused passed; 165 full passed, 4 live-AutoCAD skips**.
