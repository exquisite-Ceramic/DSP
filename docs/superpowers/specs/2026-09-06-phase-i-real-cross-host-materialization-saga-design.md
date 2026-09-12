# Phase I — Real Cross-Host Materialization Saga Design

**Status:** FROZEN DESIGN — user approved on 2026-09-06
**Base:** `main@44621cc065872282c2beed6217ed48e1c5f1b0cc`
**Phase:** I
**Primary goal:** Prove one canonical wall-thickness change can be materialized, executed, reconciled, and converged across real AutoCAD and real Revit within one governed Saga without inventing distributed transaction semantics.

---

## 1. Purpose

Phase H proved a real Revit Host can execute the existing canonical operation `set_wall_thickness.v1` and produce provider-neutral `ActualDelta` evidence compatible with Step33 reconciliation. Step34 already proved the corresponding real AutoCAD wall-thickness path. Step37 already provides a provider-neutral coordinator over multiple `HostRuntimeRef` values, but its current cross-Host proof uses different execution slices rather than one canonical effect replicated into multiple required Host materializations.

Phase I closes that gap.

The target proof is:

```text
one canonical semantic entity
        +
one canonical change operation
        ↓
one immutable materialization plan
        ├─ REQUIRED AutoCAD materialization
        └─ REQUIRED Revit materialization
        ↓
provider/native binding for each materialization
        ↓
all-required readiness barrier
        ↓
sequential real Host execution
        ↓
per-materialization ActualDelta + scope + verification
        ↓
cross-Host canonical convergence
        ↓
Saga SUCCEEDED
```

The canonical operation remains:

```text
operation = set_wall_thickness.v1
target    = ifc:IfcWall
effect    = PROPERTIES
example   = 200 mm → 300 mm
```

Phase I does not add a second wall-thickness operation, does not duplicate the canonical effect, and does not reinterpret implicit Host geometry regeneration as a separate canonical `GEOMETRY` effect.

---

## 2. Architectural classification

This is an architectural evolution because the existing Step30 v1 invariant is:

```text
1 CanonicalChangeOperation = 1 ExecutionUnit
```

and Step31 v1 is:

```text
1 ExecutionUnit = 1 ProviderBinding
```

That design does not allow one canonical operation to be silently fanned out to multiple Host runtimes.

Phase I therefore introduces a first-class materialization layer before Step30 rather than hiding fan-out inside Step31 or Step37.

The selected architecture is:

```text
Step28 ApprovalScopeBoundary
        +
Step29 CanonicalChangeSet
        +
MaterializationTopologySnapshot
        ↓
MaterializationPlanner
        ↓
immutable MaterializationPlan
        ↓
Step30 v2 ExecutionPlan
        ↓
Step31 ProviderBinding
        ↓
Step32 ExecutionGrant
        ↓
CrossHostReadinessBarrier
        ↓
Step33 / Step37 execution + reconciliation
        ↓
CrossHostConvergenceVerifier
```

---

## 3. Explicitly rejected approaches

### 3.1 Rejected: Step30 directly decides replication

Step30 must not decide both how many materializations exist and how to partition execution. That mixes product topology with execution planning.

### 3.2 Rejected: Step31 one-to-many fan-out

Step31 must not discover that one ExecutionUnit really means multiple Hosts. Approval, planning, grant issuance, and Saga definition must know the exact required execution topology before binding.

### 3.3 Rejected: Step37 duplicates canonical operations

Step37 must not clone `set_wall_thickness.v1` per Host. There is one canonical semantic intent and multiple materialization obligations.

### 3.4 Rejected: runtime geometry/name/order matching

Cross-Host identity must not be inferred from approximate geometry, naming, list position, layer order, element order, or similarity heuristics.

### 3.5 Rejected: XA/2PC or distributed locking

Phase I does not make AutoCAD and Revit one ACID transaction. It reduces predictable partial commit through readiness and preserves partial-commit truth when races still occur.

---

## 4. Materialization topology ownership

The authoritative owner of required materializations is a new platform-level `MaterializationTopologyRegistry`.

It produces immutable snapshots:

```text
MaterializationTopologySnapshot {
  topology_environment_id
  topology_revision
  slots[]
  topology_snapshot_hash
}
```

`topology_environment_id` is an opaque identity for the materialization-topology namespace/workspace. It is not a Semantic Environment id and confers no semantic-provider authority.

```text
MaterializationSlot {
  materialization_slot_id
  semantic_target_ref
  required_host_type
  document_ref
  requirement
}
```

Phase I supports only:

```text
requirement = REQUIRED
```

For the wall-thickness acceptance case:

```text
WALL-001 / AUTOCAD / REQUIRED
WALL-001 / REVIT   / REQUIRED
```

Runtime availability MUST NOT alter requiredness.

The following is forbidden:

```text
Revit offline
→ remove Revit from the plan
→ run AutoCAD only
→ report success
```

A topology change requires a new topology revision and therefore a new immutable plan.

`host_instance_id` is not topology identity and MUST NOT appear in `MaterializationTopologySnapshot`.

---

## 5. Materialization plan

`MaterializationPlanner` consumes the exact approved semantic lineage and frozen topology snapshot and produces:

```text
MaterializationPlan {
  changeset_hash
  approved_scope_hash
  topology_snapshot_hash
  intents[]
  required_set_hash
  convergence_profile_hash
  materialization_plan_hash
}
```

```text
MaterializationIntent {
  materialization_id
  source_operation_id
  source_operation_hash
  semantic_targets[]
  materialization_slot_id
  required_host_type
  expected_effects[]
}
```

The canonical operation is not copied semantically. A materialization intent is an obligation to realize the same canonical effect in a required Host slot.

The plan MUST bind exactly:

```text
Step29 changeset_hash
Step28 approved_scope_hash
MaterializationTopologySnapshot.topology_snapshot_hash
versioned ConvergenceComparisonProfile hash
```

The same logical execution may retry readiness against the same immutable plan, but the required set, ChangeSet, approved scope, topology snapshot, and convergence profile MUST remain unchanged.

---

## 6. Step28 integrity evolution

Step28 remains the owner of approved semantic effect boundaries. It does not create materialization plans.

Phase I introduces a versioned approval boundary for materialized execution:

```text
ApprovalScopeBoundaryV2 {
  ...existing Step28 semantic fields...
  topology_snapshot_hash
  scope_body_hash
}
```

`topology_snapshot_hash` is REQUIRED in the V2 semantic body and therefore participates in the V2 scope hash.

Rules:

```text
Step28 V1 artifacts remain valid for existing non-Phase-I flows.
Phase I MaterializationPlan requires ApprovalScopeBoundaryV2.
V1 approval cannot authorize a Phase I materialization plan.
V2 approval formed against topology snapshot A cannot authorize topology snapshot B.
```

This is a versioned integrity extension; old Step28 hashes never silently acquire new meaning.

---

## 7. Step30 v2 execution planning

The Step30 v1 invariant evolves from:

```text
1 CanonicalChangeOperation = 1 ExecutionUnit
```

to the Step30 V2 invariant:

```text
1 MaterializationIntent = 1 ExecutionUnit
```

Step30 V1 remains valid for historical/non-materialized execution plans. Phase I plans MUST use Step30 V2.

Step30 V2 does not decide the number of materializations. It consumes the frozen `MaterializationPlan` and deterministically projects intents into execution units/slices. Every V2 ExecutionUnit/Slice must carry immutable lineage sufficient to join back to its exact `materialization_id` and `materialization_plan_hash`.

Phase I uses a versioned deterministic ordering policy:

```text
stable_host_type_then_slot.v1
```

For the acceptance case the canonical execution order is:

```text
1. AutoCAD
2. Revit
```

Step37 continues to execute Step30 order; it MUST NOT compute a different order.

Parallel Host mutation remains out of scope.

---

## 8. Cross-Host semantic identity

A DSP semantic entity has one canonical `semantic_id`.

Phase I uses:

```text
semantic_id = WALL-001
```

This value is not an AutoCAD Handle, not a Revit ElementId, not a Revit UniqueId, and not an IFC GlobalId requirement.

Each required materialization resolves the semantic identity through an explicit persistent Host binding whose semantic body is:

```text
SemanticHostBinding {
  semantic_id
  host_type
  document_ref
  native_id
  native_kind
  host_binding_fingerprint
}
```

`SemanticHostBinding` is the persistent conceptual record; Step31's existing `NativeTargetBindingEvidence` is the execution-snapshot projection of the same binding semantics. Phase I MUST reuse the existing Step31 fingerprint algorithm rather than introduce a second binding identity algorithm.

`host_instance_id` remains outside persistent HostBinding identity.

For Revit, `native_id` is `Element.UniqueId`; `ElementId` remains diagnostic only.

For Phase I MVP:

```text
1 semantic_id × 1 required Host slot = exactly 1 native binding
```

Unsupported many-to-one or one-to-many materialization cardinality fails closed:

```text
UNSUPPORTED_MATERIALIZATION_CARDINALITY
```

Missing authoritative binding:

```text
IDENTITY_BINDING_UNRESOLVED
```

Duplicate/conflicting binding:

```text
IDENTITY_BINDING_CONFLICT
```

No runtime matching heuristic is permitted.

---

## 9. Step31 binding boundary

Step31 remains late-bound provider/native resolution.

It may:

- select a provider implementation;
- bind the exact semantic target to the exact native target;
- use runtime health/license/certification evidence projected into its immutable provider snapshot;
- produce immutable `ProviderBindingSet` values.

It may not:

- add or remove required materializations;
- repartition a materialization intent;
- change semantic identity;
- widen scope;
- authorize execution;
- mutate a Host.

Phase I requires a cross-materialization identity check after all required ProviderBindingSets exist and before readiness is admitted.

For every required materialization:

```text
binding.semantic_id
== materialization.semantic_target_ref
```

and Host type/document/fingerprint/Slice/materialization lineage MUST exactly match.

A changed native binding invalidates the old binding set and old grant. If canonical intent, approved scope, and frozen topology are unchanged, this does not by itself require repeated semantic approval.

---

## 10. Step32 authority evolution

Phase I uses a versioned materialization-aware grant. Existing V1 grants remain valid only for their existing non-Phase-I flows.

Each Phase I grant must authorize one exact required materialization execution, not merely a generic Slice.

The materialization-aware grant lineage binds at minimum:

```text
approval_hash
changeset_hash
approved_scope_hash
materialization_plan_hash
materialization_id
execution_slice_hash
binding_set_hash
host_instance_id
```

Any materialization-plan or binding change requires new execution authority.

A grant issued for `WALL-001 / AUTOCAD` cannot be reused for `WALL-001 / REVIT`, another semantic entity, another native binding, or another plan revision.

---

## 11. All-required readiness barrier

Before the first Host mutation, every REQUIRED materialization must pass a provider-neutral readiness barrier.

```text
all required materializations
  bound
  authorized
  reachable
  document matched
  target resolvable
  Host preflight READY
        ↓
barrier PASS
```

If any required materialization fails readiness:

```text
CoordinationResult = READINESS_FAILED
0 Host commits
0 active Step33 Slice
```

`READINESS_FAILED` is a pre-start coordination outcome, not a fabricated Step33 terminal Saga state.

The same immutable plan may be checked again only while the exact Step31 bindings/snapshots and Step32 grants remain valid. If binding/provider evidence or grants expire/change, the workflow must re-run the appropriate binding/authorization steps; requiredness and canonical approval may not be silently changed.

The barrier is an observation, not a reservation or lock.

A Host must revalidate immediately before its own mutation because document revision, target state, or local preconditions may change after readiness passes.

The provider-neutral interface is conceptually:

```text
HostReadinessPort.check(...) -> HostReadinessReceipt
```

A receipt binds at minimum:

```text
materialization_id
materialization_plan_hash
execution_slice_hash
binding_set_hash
grant_hash
host_runtime_ref
document_ref
observed_revision
ready
readiness_receipt_hash
```

Provider-specific preflight logic stays inside the Host boundary. Core platform code must not learn Revit Wall isolation rules or AutoCAD entity mechanics.

---

## 12. Sequential execution and race truth

After readiness passes, Step37 executes slices sequentially in Step30 order.

A later Host may still fail before commit due to a real race.

Example:

```text
T0 AutoCAD READY + Revit READY
T1 barrier PASS
T2 AutoCAD commits successfully
T3 Revit document revision changes
T4 Revit pre-transaction revalidation fails
```

The durable truth is:

```text
AutoCAD Slice = SUCCEEDED
Revit Slice   = FAILED_BEFORE_COMMIT
Saga          = PARTIALLY_COMMITTED
```

Readiness must never be treated as a commit guarantee.

---

## 13. Existing Step33/37 truth semantics retained

The existing rules remain authoritative:

- `ActualDelta` is the truth of known Host side effects.
- `SCOPE_BREACH` is blocking.
- failed or insufficient semantic verification blocks success.
- `COMMIT_STATE_UNKNOWN` returns `RECOVERY_REQUIRED` and MUST NOT be rewritten as a false pre-commit failure.
- an unresolved active Slice is never automatically replayed.
- compensation is governed and never inferred as an inverse Host command.

Phase I does not introduce XA, hidden retry, fabricated empty ActualDelta, native UNDO, or silent rollback.

---

## 14. Compensation boundary

Phase I may record compensation evidence and create or expose a governed `CompensationProposal` through existing Step33 semantics.

Phase I does not automatically execute compensation.

The following is forbidden:

```text
AutoCAD committed
Revit failed
→ automatically set AutoCAD back to 200 mm
```

Any recovery mutation must re-enter the canonical authority chain:

```text
canonical recovery effect
→ approval/scope
→ ChangeSet
→ materialization plan
→ binding
→ grant
→ Host execution
```

The platform never derives an inverse native command from a failed Saga.

---

## 15. Local materialization success

A required materialization is locally successful only after all of the following are durable:

```text
known Host commit
real ActualDelta
ScopeComparator = WITHIN_SCOPE
SemanticVerifier = PASSED
```

Host self-report alone cannot produce platform success.

Phase I reuses existing Step33 verification semantics rather than adding Host-specific post-read checks to the cross-Host coordinator.

---

## 16. Cross-Host convergence

Local success is necessary but not sufficient for global Saga success.

Phase I adds a separate provider-neutral convergence gate:

```text
canonical intended state
        =
AutoCAD canonical post-state
        =
Revit canonical post-state
```

The convergence gate is entered only after every REQUIRED Slice is locally `SUCCEEDED`.

The convergence layer consumes only canonical post-execution evidence reconstructed through the existing semantic/D5 boundary. It MUST NOT read AutoCAD handles, Revit UniqueIds as semantic values, internal Revit feet, DWG-native width payloads, or Host-specific response JSON.

The evidence envelope is conceptually:

```text
ConvergenceEvidenceSet {
  changeset_hash
  materialization_plan_hash
  required_set_hash
  convergence_profile_hash
  materializations[]
  convergence_evidence_hash
}
```

```text
MaterializationCanonicalEvidence {
  materialization_id
  semantic_id
  execution_slice_hash
  actual_delta_hash
  verification_hash
  semantic_environment_ref
  post_execution_projection_ref
  canonical_kind
  verified_fields{}
  evidence_aspects[]
  evidence_hash
}
```

The evidence set is closed-world:

```text
set(evidence.materialization_id) == required materialization set
```

Missing, duplicate, extraneous, mismatched, or lineage-inconsistent evidence fails closed.

---

## 17. Convergence comparison semantics

Cross-Host convergence does not require byte-for-byte equality and does not simply rerun the local ValidationTask predicate.

Phase I introduces a versioned, content-addressed `ConvergenceComparisonProfile` derived deterministically from the exact Step29 verification semantics for the fields/aspects that require cross-Host convergence.

The profile reuses the same canonical field selection, unit normalization, numeric tolerance, and comparison primitives already authorized by the ChangeSet. It MUST NOT invent a second unit/tolerance policy.

The profile defines pairwise semantic equivalence across required materializations. This is distinct from a local acceptance predicate. For example, a future local validation rule may accept any value in a permitted interval while the convergence profile can still require the two accepted materializations to be mutually equivalent under the same canonical numeric tolerance.

Example:

```text
intended = 0.300 m
AutoCAD  = 0.3000000000 m
Revit    = 0.3000000004 m
```

may converge when the two post-states are semantically equivalent under the exact profile tolerance.

`convergence_profile_hash` is part of `MaterializationPlan` and `ConvergenceEvidenceSet` lineage. Changing the profile requires a new plan and new execution authority; it cannot be altered after Host commits.

Only fields/aspects required by the exact ChangeSet verification semantics are compared. Phase I does not construct a full IFC mirror solely for convergence.

---

## 18. Convergence result and Step33 Saga V2 truth

Phase I introduces:

```text
ConvergenceStatus {
  CONVERGED
  DIVERGED
  EVIDENCE_INSUFFICIENT
}
```

and a Step33 Saga V2 terminal truth:

```text
DIVERGED
```

A Phase I Saga V2 definition binds the exact:

```text
changeset_hash
approved_scope_hash
materialization_plan_hash
required_set_hash
execution_plan_hash
```

and does not become `SUCCEEDED` merely because all Slices are locally successful.

`DIVERGED` is reachable only after every REQUIRED Slice is locally `SUCCEEDED`. It means all required Host commits and local reconciliation results are known, but global cross-Host canonical convergence was not proved.

This is intentionally distinct from:

```text
PARTIALLY_COMMITTED
```

which means some required materialization did not complete successfully after another durable commit already occurred.

A convergence failure MUST NOT rewrite a locally successful Slice into `VERIFY_FAILED`.

Valid durable state:

```text
AutoCAD Slice = SUCCEEDED
Revit Slice   = SUCCEEDED
Convergence   = DIVERGED
Saga          = DIVERGED
```

The Saga may become `SUCCEEDED` only after:

```text
all REQUIRED Slices locally SUCCEEDED
AND
convergence = CONVERGED
```

`EVIDENCE_INSUFFICIENT` maps to Saga `DIVERGED` with stable detail:

```text
CONVERGENCE_EVIDENCE_INSUFFICIENT
```

because local success exists but global convergence was not sufficiently proven.

Existing Step33 V1 Saga artifacts retain their historical semantics; the new terminal truth and materialization lineage belong to Saga V2.

---

## 19. CrossHostConvergenceVerifier ownership

`CrossHostConvergenceVerifier` owns only:

1. required evidence completeness;
2. exact plan/ChangeSet/semantic identity/profile lineage;
3. extraction of ChangeSet-required canonical fields;
4. deterministic versioned pairwise canonical comparison;
5. immutable `ConvergenceResult` construction.

It MUST NOT:

- call AutoCAD or Revit;
- perform Host reads;
- interpret native units;
- modify `ActualDelta`;
- rerun ScopeComparator;
- reinterpret approval;
- issue grants;
- select compensation;
- mutate Saga Slice history.

---

## 20. Phase I error semantics

Stable Phase I-level errors/details must include at minimum:

```text
MATERIALIZATION_TOPOLOGY_MISMATCH
MATERIALIZATION_PLAN_HASH_MISMATCH
MATERIALIZATION_REQUIRED_SET_MISMATCH
UNSUPPORTED_MATERIALIZATION_CARDINALITY
IDENTITY_BINDING_UNRESOLVED
IDENTITY_BINDING_CONFLICT
MATERIALIZATION_BINDING_MISMATCH
MATERIALIZATION_AUTHORITY_MISMATCH
READINESS_FAILED
READINESS_LINEAGE_MISMATCH
CONVERGENCE_PROFILE_MISMATCH
CONVERGENCE_EVIDENCE_MISSING
CONVERGENCE_EVIDENCE_CONFLICT
CONVERGENCE_LINEAGE_MISMATCH
CONVERGENCE_DIVERGED
CONVERGENCE_EVIDENCE_INSUFFICIENT
```

Existing Step31/32/33/37 errors remain unchanged unless a versioned public-contract evolution explicitly requires otherwise.

Phase I implementation must not reuse an existing error code with a different meaning.

---

## 21. Real positive acceptance scenario

The primary live proof uses one controlled semantic wall:

```text
semantic_id = WALL-001
```

with exactly one authoritative AutoCAD binding and one authoritative Revit binding.

Starting state:

```text
AutoCAD wall thickness = 200 mm
Revit wall thickness   = 200 mm
```

Canonical request:

```text
set_wall_thickness.v1
WALL-001
300 mm
```

The acceptance evidence must prove:

```text
Topology required set      = {AUTOCAD, REVIT}
MaterializationPlan        = immutable and hash-valid
AutoCAD identity binding   = exact
Revit identity binding     = exact
AutoCAD readiness          = READY
Revit readiness            = READY
barrier                    = PASS
AutoCAD transaction        = exactly one intended mutation
Revit transaction          = exactly one intended mutation
AutoCAD ActualDelta        = real + lineage-valid
Revit ActualDelta          = real + lineage-valid
AutoCAD scope              = WITHIN_SCOPE
Revit scope                = WITHIN_SCOPE
AutoCAD verification       = PASSED
Revit verification         = PASSED
AutoCAD canonical thickness= 300 mm
Revit canonical thickness  = 300 mm
cross_host                 = CONVERGED
Saga                       = SUCCEEDED
```

The final evidence record must bind the exact:

```text
changeset_hash
approved_scope_hash
topology_snapshot_hash
materialization_plan_hash
required_set_hash
convergence_profile_hash
AutoCAD execution_slice_hash
Revit execution_slice_hash
AutoCAD binding_set_hash
Revit binding_set_hash
AutoCAD grant_hash
Revit grant_hash
AutoCAD actual_delta_hash
Revit actual_delta_hash
AutoCAD verification_hash
Revit verification_hash
convergence_hash
```

---

## 22. Real partial-commit acceptance scenario

Phase I must prove a real deterministic race without production debug flags.

Required sequence:

```text
1. AutoCAD and Revit both pass readiness.
2. AutoCAD performs the real 200 → 300 mm mutation and reconciles successfully.
3. Before Revit execution, a test-only live-acceptance driver or operator performs a legitimate Revit document edit that advances DocumentChanged revision through ordinary Revit behavior; no production Host failure switch is used.
4. Revit receives the stale expected revision.
5. Revit returns REVISION_CONFLICT / BEFORE_COMMIT.
6. Step33 records:
   AutoCAD Slice = SUCCEEDED
   Revit Slice   = FAILED_BEFORE_COMMIT
   Saga          = PARTIALLY_COMMITTED
```

Requirements:

- Revit has no `ActualDelta` for the failed Slice.
- AutoCAD committed evidence remains durable.
- later execution stops.
- no automatic compensation runs.
- no production Host gets a failure-injection switch.
- any test-only live driver is outside production Host packages and cannot be enabled by production configuration.

---

## 23. Provider-neutral divergence acceptance

A separate integration test proves the Saga-level `DIVERGED` state without making a production Host intentionally write an incorrect value.

The fixture must use local validation semantics that legitimately allow more than one locally acceptable canonical result, together with the exact derived convergence profile that still requires mutual equivalence.

Example evidence:

```text
local allowed interval = [290 mm, 310 mm]
convergence tolerance  = exact profile tolerance
AutoCAD canonical evidence = 295 mm
Revit canonical evidence   = 305 mm
```

The test must prove:

```text
both required Slices locally SUCCEEDED
all required materialization evidence present
cross-host comparison = DIVERGED
Saga = DIVERGED
successful Slice history remains unchanged
```

This test demonstrates the architectural distinction between local semantic validity and global materialization convergence without introducing a production debug backdoor.

---

## 24. Architecture guards

Production architecture tests must prove:

- materialization planning is provider-neutral;
- Step30 consumes materialization intents but does not discover fan-out from Host availability;
- Step31 cannot add/remove materializations;
- Step37 does not clone canonical operations;
- convergence production code contains no AutoCAD/Revit SDK vocabulary;
- no runtime geometry/name/order identity matching exists;
- Revit persistent binding uses `UniqueId`, not `ElementId`;
- no production failure-injection switch is added;
- no automatic inverse Host command generation is added;
- no parallel Slice execution is introduced;
- no XA/2PC/distributed-lock implementation is introduced;
- V1 contract hashes do not silently change meaning;
- existing Step33 `ActualDelta`, scope, verification, and `COMMIT_STATE_UNKNOWN` truth semantics remain intact.

---

## 25. Expected subsystem boundaries

Implementation should prefer focused provider-neutral packages rather than expanding one orchestration file.

Expected conceptual ownership:

```text
platform/materialization_topology/
  topology contracts + immutable snapshot validation

platform/materialization_planning/
  deterministic topology × ChangeSet → MaterializationPlan
  convergence-profile derivation

platform/execution_planning/
  Step30 V2 projection from materialization intents

platform/provider_binding/
  Step31 materialization-aware binding lineage

platform/gateway_authorization/
  Step32 materialization-aware authority lineage

platform/execution_coordination/
  readiness orchestration + existing sequential forward coordinator

platform/execution_reconciliation/
  Step33 durable local Slice truth + Saga V2 truth evolution

platform/convergence/
  provider-neutral cross-Host canonical convergence
```

Exact file/package placement may be refined in the implementation plan, but dependency direction and responsibility boundaries are normative.

---

## 26. Migration/versioning constraints

Phase I is a versioned evolution, not an in-place semantic rewrite.

At minimum, the implementation plan must treat these as explicit versioned surfaces:

```text
ApprovalScopeBoundary V2
MaterializationTopologySnapshot V1       # new
MaterializationPlan V1                   # new
ConvergenceComparisonProfile V1          # new
Step30 ExecutionPlan/Unit/Slice V2 path
Step32 materialization-aware Grant V2 path
Step33 SagaDefinition/SagaStatus V2 path
ConvergenceEvidenceSet/Result V1          # new
```

Existing Step31 binding semantics are reused; any Step31 wire/hash extension needed solely to carry materialization lineage must be versioned without changing the existing `NativeTargetBindingEvidence` fingerprint meaning.

Implementation must preserve the ability to validate historical Step28/30/31/32/33 artifacts created under prior contracts where required by existing tests and storage semantics.

Any hash-body change must be explicit and versioned. Old hashes must never silently acquire new meaning.

The implementation plan must identify every contract/hash whose semantic body changes and define backward-validation behavior before code changes begin.

---

## 27. Non-goals

Phase I does not add:

- a new canonical wall operation;
- a third Host;
- Revit multi-version packaging;
- AutoCAD/Revit transport unification;
- parallel Host commits;
- XA/2PC;
- distributed locks;
- automatic rollback;
- automatic compensation execution;
- inverse native command inference;
- Host-online-state-driven required-set downgrade;
- geometry-based entity matching;
- automatic initial cross-Host identity onboarding;
- composite materialization cardinality;
- full IFC model mirroring for convergence;
- new Revit wall behaviors beyond the Phase H MVP;
- new AutoCAD production semantics beyond the already proven wall-thickness path.

Initial HostBinding authoring/onboarding is a separate future design problem. Phase I consumes authoritative bindings rather than inventing them.

---

## 28. Completion gates

Phase I is complete only when the repository can prove all of the following:

```text
one canonical operation produces two REQUIRED materialization intents: PASS
required set cannot change because a Host is offline: PASS
ApprovalScopeBoundaryV2 binds topology snapshot: PASS
V1 approval cannot authorize Phase I materialization: PASS
materialization plan hash binds ChangeSet + scope + topology + convergence profile: PASS
Step30 V2 uses 1 materialization intent = 1 execution unit: PASS
Step31 cannot add/remove required materializations: PASS
one semantic_id resolves exactly one native target per required Host: PASS
missing/conflicting binding fails closed: PASS
all-required readiness blocks first commit if any Host is unready: PASS
readiness failure creates no active Step33 Slice: PASS
readiness is not treated as a commit guarantee: PASS
AutoCAD then Revit execution order is deterministic: PASS
real AutoCAD wall-thickness mutation succeeds: PASS
real Revit wall-thickness mutation succeeds: PASS
both real ActualDelta values reconcile WITHIN_SCOPE: PASS
both real semantic verifications PASSED: PASS
cross-Host canonical convergence is CONVERGED: PASS
positive real Saga ends SUCCEEDED only after convergence: PASS
real post-readiness Revit revision race yields PARTIALLY_COMMITTED: PASS
no false Revit ActualDelta is fabricated on pre-commit failure: PASS
COMMIT_STATE_UNKNOWN remains RECOVERY_REQUIRED: PASS
all-local-success but global mismatch can end DIVERGED: PASS
DIVERGED does not rewrite successful Slice history: PASS
no production failure switch exists: PASS
no automatic compensation executes: PASS
no inverse native command is inferred: PASS
no Host-native vocabulary leaks into materialization/convergence core: PASS
V1 contract/hash meanings remain stable: PASS
existing Step28–37 semantics not explicitly versioned by Phase I remain regression-green: PASS
Phase H Revit live acceptance remains green: PASS
AutoCAD wall-thickness live acceptance remains green: PASS
```

---

## 29. Final design decision

> A canonical design effect is approved once in semantic space and may carry multiple explicit required materialization obligations. Those obligations are frozen before execution, bound to authoritative Host identities, authorized individually, and all must be ready before the first mutation. Hosts then execute sequentially under the existing truthful Saga model. Every materialization must reconcile locally, and the Saga succeeds only when a separate provider-neutral convergence gate proves the resulting canonical states equivalent. Runtime availability never rewrites requiredness, readiness never pretends to be atomic commit, and partial or divergent real-world truth is preserved rather than hidden.
