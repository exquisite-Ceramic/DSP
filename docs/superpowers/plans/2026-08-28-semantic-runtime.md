# D5 Semantic Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the v0.5 Appendix D step 5 Semantic Runtime minimum: Identity Registry, Change Journal, Dirty Map, contract-bound Context/Planning Snapshots, SnapshotSet, and two-phase freshness.

**Architecture:** Keep D5 in the existing host-neutral `platform/semantic_runtime` package. Model freshness contracts and immutable snapshots as deterministic value objects with canonical hashes; keep identity/journal/dirty tracking in focused modules; use a deterministic `FreshnessResolver` that accepts selective reconstruction results, enforces revision stability and exact contract coverage, then emits a ContextSnapshot or PlanningSnapshot. Do not add D6 interaction/parameter binding or D7 ChangeSet/execution behavior.

**Tech Stack:** Python 3.11, dataclasses/enums/hashlib/json, pytest, GitHub Actions.

**Spec:** `Enterprise_Collaborative_Design_Agent_Spec_v0.5.md` sections 7–8, AR-017/AR-026/AR-028, Appendix D step 5.

## Global Constraints

- Host remains the real-time design source of truth; Semantic Runtime is a progressive task-scoped projection.
- v0.1 semantic aspects: IDENTITY, PROPERTIES, PLACEMENT, GEOMETRY, SPATIAL, CONNECTIVITY, RELATIONSHIPS, CONSTRAINTS.
- Freshness states: FRESH, STALE, DIRTY, UNKNOWN, RECONSTRUCTING.
- Context Freshness is Phase A before Operation Resolution and should stay at geometry level 0–1.
- Operation Freshness is Phase B after OperationProposal/parameter binding and follows selected operation requirements.
- SemanticSnapshot MUST bind freshness contract, coverage, base host revision, aspect guarantees, and hash.
- SnapshotSet for ChangeSet use MUST contain PlanningSnapshots only; single-host MVP still uses the set abstraction.
- Host revision changes during reconstruction MUST invalidate the snapshot rather than silently reusing it.
- Coverage MUST NOT silently expand during reconstruction.
- No Autodesk native types may enter the platform package.

---

### Task 1: Freeze D5 contracts with focused tests

**Files:**
- Create: `tests/semantic_runtime/test_semantic_runtime.py`
- Create: `.github/workflows/semantic-runtime.yml`

**Interfaces:**
- Consumes: spec v0.5 sections 7–8 and D4 freshness requirement dictionaries.
- Produces: executable contract for the D5 public API.

- [ ] Write tests first for identity round-trip/conflicts, journal→dirty aspect invalidation, context geometry cap, operation contract hashing, contract-bound snapshots, revision/coverage/guarantee barriers, and PlanningSnapshot-only SnapshotSet.
- [ ] Run focused CI and verify RED is caused by missing `semantic_runtime` implementation.

### Task 2: Implement identity, journal, and dirty tracking

**Files:**
- Create: `platform/semantic_runtime/src/semantic_runtime/identity.py`
- Create: `platform/semantic_runtime/src/semantic_runtime/journal.py`

**Interfaces:**
- Produces: `IdentityBinding`, `IdentityRegistry`, `HostDeltaRecord`, `JournalEntry`, `ChangeJournal`, `DirtyMap`.

- [ ] Implement immutable identity bindings with bidirectional lookup and fail-closed rebinding.
- [ ] Implement append-only in-memory journal sequence and entity+aspect Dirty Map states.
- [ ] Run focused tests and keep unrelated freshness tests red until Task 3.

### Task 3: Implement freshness contracts, snapshots, and resolver

**Files:**
- Create: `platform/semantic_runtime/src/semantic_runtime/freshness.py`
- Create: `platform/semantic_runtime/src/semantic_runtime/__init__.py`

**Interfaces:**
- Produces: semantic/freshness enums, `AspectRequirement`, `Coverage`, `FreshnessContract`, `ReconstructionResult`, `SemanticSnapshot`, `SnapshotSet`, `FreshnessResolver`, context/operation contract builders, structured freshness errors.

- [ ] Implement deterministic canonical hashing for contracts/snapshots/snapshot sets.
- [ ] Enforce Phase A geometry <= BOUNDS.
- [ ] Bind Phase B contract identity to canonical operation, targets, arguments, and operation freshness requirements.
- [ ] Reject changed host revision, mismatched/expanded coverage, and insufficient guarantees.
- [ ] Mark only guaranteed root entity aspects FRESH after a successful barrier.
- [ ] Emit CONTEXT snapshots for Phase A and PLANNING snapshots for Phase B.
- [ ] Reject ContextSnapshots in SnapshotSet.

### Task 4: Verification and PR

**Files:**
- Modify if required: `platform/semantic_runtime/pyproject.toml`
- PR: `feat/semantic-runtime` → `main`

- [ ] Run focused D5 tests.
- [ ] Run full Python regression including D3/D4 suites.
- [ ] Review for D6/D7 scope creep and host/native leakage.
- [ ] Open Ready-for-Review PR only after green CI.
