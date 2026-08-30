# Step 30 — Execution Partitioning Design

**Status:** Implemented; verification complete  
**Date:** 2026-08-29  
**Base:** `main@4c64286734a128c49e302e5685529502a5207086`  
**Branch:** `feat/step30-execution-partitioning`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step 30 introduces the immutable execution-partitioning layer between the frozen canonical transaction from Step29 and provider/native execution binding in Step31.

It answers one question:

```text
Given this exact CanonicalChangeSet, this exact ApprovalScopeBoundary,
and this exact task-scoped runtime routing snapshot,
which canonical operation executes in which Host/document execution slice,
and what execution ordering must be preserved?
```

It does **not** answer:

```text
Which provider/tool executes an operation?
Which native object id should be used?
How canonical units become native units?
Who approves the transaction?
Which risk/policy tier applies?
What ExecutionGrant is issued?
Whether a runtime RevisionBarrier passes?
What actually changed in the Host?
How verification, reconciliation, rollback, or Saga compensation proceeds?
```

The intended Phase-G flow is:

```text
Step 29 CanonicalChangeSet
+ Step 28 ApprovalScopeBoundary
+ task-scoped RuntimeRoutingEvidence
        ↓
Step 30 ExecutionPlanner
        ↓
immutable ExecutionPlan
  ├─ ExecutionSlice[]
  │    └─ ExecutionUnit[]
  └─ ExecutionDependency[]
        ↓
RevisionBarrier
        ↓
Step 31 ProviderBinding / binding_set_hash
        ↓
Step 32 ExecutionGrant
        ↓
Step 33 Apply / ActualDelta / Verify / ScopeComparator / Saga
```

The central invariant is:

> Step30 may partition and project the exact Step29 canonical transaction onto already-resolved runtime Host/document routes inside the exact Step28 approval boundary. It MUST NOT split or rewrite canonical operations, widen authority, choose providers, resolve native identities, or absorb runtime state.

---

## 2. Master-spec interpretation

The v0.6 master spec freezes three relevant boundaries:

```text
ExecutionSlice = Host instance + document + approved scope boundary
ExecutionUnit  = minimum provider-binding unit, still canonical/provider-neutral
ProviderBinding = provider/native execution choice made after execution planning
```

The master spec also requires:

```text
SemanticIdentity
  ↓ HostBinding (persistent)
Host document/native entity
  ↓ runtime resolution
HostRuntimeRef
  ↓ ExecutionSlice
  ↓ ProviderBinding
```

and requires unresolved runtime Host references to fail closed.

Step30 therefore consumes a small task-scoped provider-neutral runtime-routing evidence object. It does not query D5, Host registries, sidecars, providers, or Host APIs itself.

The master-spec DTO sketch includes mutable fields such as `status` on `ExecutionSlice`. Step30 deliberately excludes such runtime state from the immutable planning artifact. Runtime apply/failure/compensation state belongs to Step33.

The master-spec DTO sketch also places `execution_slice_id` inside `ExecutionUnit`. Step30 omits that reverse reference because slice membership is already represented by the parent `ExecutionSlice.execution_units[]`, and a content-derived Unit ID depending on a content-derived Slice ID would create a hash cycle.

---

## 3. Chosen package strategy

Step30 SHALL be implemented as a separate package:

```text
platform/execution_planning/
  pyproject.toml
  src/design_execution_planning/
    __init__.py
    contracts.py
    hashing.py
    planner.py
```

The distribution name SHALL be:

```text
design-execution-planning
```

This package SHALL depend only on provider-neutral upstream contracts needed for deterministic partitioning, primarily:

```text
design_changeset
design_approval_scope
```

It SHALL NOT live inside `design_changeset`, because Step29 owns canonical transaction identity while Step30 owns execution partitioning. Keeping them physically separate prevents later provider/runtime concerns from contaminating the immutable ChangeSet package.

---

## 4. Ownership boundary

### 4.1 Step28 owns approval authority

Step28 remains authoritative for:

```text
ApprovalScopeBoundary.scope_hash
ApprovalScopeBoundary.scope_body_hash
existing/creation/deletion rules
execution_slice_scopes[]
```

Step30 MUST NOT create new scope rules, widen an existing rule, infer new entity/aspect authority, or allow a caller to choose a broader slice scope.

### 4.2 Step29 owns canonical transaction semantics

Step29 remains authoritative for:

```text
CanonicalChangeSet.changeset_hash
CanonicalChangeOperation semantic body
operation targets
canonical arguments
expected effects
operation source evidence
ChangeDependency causality
preconditions
```

Step30 MUST NOT rebuild, split, merge, rewrite, optimize, or reinterpret Step29 canonical operations.

### 4.3 Runtime resolution is external to Step30

An external workflow/runtime-resolution boundary resolves the current task's semantic targets into provider-neutral HostRuntimeRef facts before Step30.

Step30 consumes those facts through `RuntimeRoutingEvidence`; it does not query D5, HostBinding storage, Host registries, Host MCP, or providers.

### 4.4 Step30 owns execution partitioning

Step30 owns:

- exact Step29 ↔ Step28 binding validation;
- exact task-scoped runtime-route evidence validation;
- one-to-one CanonicalChangeOperation → ExecutionUnit projection;
- deterministic approved-slice-scope selection;
- deterministic Host/document/scope grouping into ExecutionSlice values;
- exact Step29 dependency → ExecutionDependency projection;
- deterministic Unit/Slice/Plan hashing and construction IDs.

### 4.5 Step31 owns ProviderBinding

Step31 owns:

```text
persistent HostBinding/native entity resolution
provider capability matching
provider_id/provider_tool
provider version/compatibility
provider-native constraints
native unit conversion
native payload shaping
binding_set_hash
```

Provider choice MUST NOT modify Step30 artifacts.

### 4.6 Step32 owns governance artifacts

Step32 owns:

```text
ApprovalRecord
risk/policy state
ExecutionGrant
```

Step30 does not hash or carry approval runtime state.

### 4.7 Step33 owns runtime execution state

Step33 owns:

```text
apply state
ActualDelta
verification result
scope comparison
retry/idempotent recovery
rollback/compensation
Saga state
```

Step30 artifacts contain no mutable workflow status.

---

## 5. Chosen runtime-routing strategy

### 5.1 Chosen: supplied task-scoped provider-neutral evidence

The workflow SHALL supply a small immutable `RuntimeRoutingEvidence` value that binds only the runtime Host/document facts needed by this ChangeSet.

This is preferred over Step30 querying D5/Host runtime registries because execution partitioning must not become a stateful runtime lookup service.

It is also preferred over introducing a complete HostBinding/HostRuntimeResolver subsystem as a Step30 prerequisite. Step30 needs only the already-resolved provider-neutral projection.

### 5.2 Runtime Host projection

Step30 uses the master-spec HostRuntimeRef semantics:

```text
HostRuntimeRef {
  host_type
  host_instance_id
  document_ref
}
```

`document_ref` is the Step30 field spelling corresponding to the master-spec `document_id` concept already used by current Step28/29 contracts.

A `HostRuntimeRef` MUST NOT contain:

```text
native_id
native_kind
provider_id
provider_tool
provider version
native units
Host API payload
```

### 5.3 RuntimeEntityRoute

```text
RuntimeEntityRoute {
  semantic_id
  host_runtime_ref
}
```

Each `semantic_id` maps to exactly one HostRuntimeRef in one `RuntimeRoutingEvidence` snapshot.

### 5.4 RuntimeRoutingEvidence

```text
RuntimeRoutingEvidence {
  routing_snapshot_id
  routes[]
  routing_snapshot_hash
}
```

The hash SHALL be recomputed by Step30 over normalized route semantics. A caller-provided hash is evidence to verify, not authority to trust.

The routing snapshot is task-scoped, not a global Host-registry snapshot.

---

## 6. Exact closed-world routing coverage

Define:

```text
required_targets = union(
  CanonicalChangeSet.root_operation.targets,
  CanonicalChangeSet.derived_operations[*].targets
)
```

`RuntimeRoutingEvidence.routes[].semantic_id` MUST equal `required_targets` exactly after normalization.

Therefore:

```text
missing required target
→ EXECUTION_ROUTE_UNRESOLVED

same semantic_id with different HostRuntimeRef values
→ EXECUTION_ROUTE_CONFLICT

route for semantic_id outside required_targets
→ EXECUTION_ROUTE_EXTRANEOUS
```

Duplicate byte-for-byte identical routes MAY normalize to one semantic route before hashing; conflicting duplicates MUST fail closed.

The closed-world rule prevents unrelated runtime Host-session changes from introducing meaningless entropy into `execution_plan_hash`.

---

## 7. ExecutionPlanningRequest

```text
ExecutionPlanningRequest {
  canonical_changeset
  approval_scope_boundary
  runtime_routing_evidence
}
```

The request contains no caller-selected slice, no provider choice, no native target, no approval state, and no mutable execution status.

Step30 SHALL validate public input types and reject malformed public values with stable Step30 domain errors.

---

## 8. Step29 ↔ Step28 exact binding

Before any routing or partitioning, Step30 SHALL require:

```text
CanonicalChangeSet.changeset_hash
  == ApprovalScopeBoundary.changeset_hash

CanonicalChangeSet.approval_scope_definition_ref.scope_body_hash
  == ApprovalScopeBoundary.scope_body_hash
```

Step29 v1 materializes canonical mutation authority only from explicit Step28 `existing_entity_rules`; its `CanonicalChangeOperation.scope_rule_ids` therefore reference existing-entity rule IDs only.

For every Step29 operation, Step30 SHALL require every `scope_rule_id` to resolve to exactly one rule in:

```text
ApprovalScopeBoundary.existing_entity_rules
```

The exact boundary rule bodies are also required to recompute the Step29 operation semantic hash described in §11.1.

Any binding or rule-resolution mismatch fails:

```text
EXECUTION_SCOPE_MISMATCH
```

Step30 MUST NOT accept an equivalent-looking but differently bound scope.

---

## 9. Core v1 partitioning invariant

### 9.1 One CanonicalChangeOperation equals one ExecutionUnit

Step30 v1 freezes:

```text
1 CanonicalChangeOperation
=
1 ExecutionUnit
```

Step30 MUST NOT split one operation by target, Host, document, provider, or convenience.

The current Step23 canonical operation contract does not expose machine-readable semantics proving that arbitrary target-level splitting preserves operation semantics. Therefore splitting would rewrite the frozen Step29 transaction.

### 9.2 All operation targets must share one runtime route boundary

For each CanonicalChangeOperation, every target MUST resolve to the same:

```text
host_type
host_instance_id
document_ref
```

Otherwise Step30 fails:

```text
EXECUTION_OPERATION_NOT_PARTITIONABLE
```

### 9.3 Cross-Host ChangeSets remain supported

Cross-Host execution is supported when different Step29 canonical operations route to different Host/document boundaries, for example:

```text
CanonicalChangeSet
├─ root operation    → Revit Host/document
└─ derived operation → AutoCAD Host/document
```

Step30 creates separate ExecutionSlices while preserving the existing Step29 dependency edge.

---

## 10. Deterministic approved-slice-scope selection

The caller MUST NOT select `execution_slice_scope_rule_id`.

For one operation routed to one `document_ref`, Step30 derives candidates from:

```text
ApprovalScopeBoundary.execution_slice_scopes[]
```

Because Step29 v1 operation scope authority comes from existing-entity rules, a candidate is eligible only if:

```text
candidate.document_ref == operation runtime document_ref
```

and:

```text
operation.scope_rule_ids ⊆ candidate.existing_rule_ids
```

For least-authority comparison, candidate authority is the normalized set:

```text
candidate_authority = union(
  candidate.existing_rule_ids,
  candidate.creation_rule_ids,
  candidate.deletion_rule_ids
)
```

and candidate surplus is:

```text
surplus = candidate_authority - set(operation.scope_rule_ids)
```

Step30 then applies deterministic least-authority selection:

1. retain only candidates with complete existing-rule coverage;
2. choose candidates having minimum `len(surplus)`;
3. normalize each tied candidate body as:

```text
(
  document_ref,
  sorted(existing_rule_ids),
  sorted(creation_rule_ids),
  sorted(deletion_rule_ids)
)
```

4. if tied candidates have different normalized bodies, fail `EXECUTION_SLICE_SCOPE_AMBIGUOUS`;
5. if tied candidates have the same normalized body and differ only by `slice_scope_rule_id`, choose the lexicographically smallest `slice_scope_rule_id` as a deterministic construction reference;
6. if no candidate exists, fail `EXECUTION_SLICE_SCOPE_UNCOVERED`.

This means semantic ambiguity fails closed, while duplicate semantically equivalent Step28 slice-scope entries do not introduce nondeterminism.

Step30 does not expand scope to make a partition possible.

---

## 11. ExecutionUnit contract

```text
ExecutionUnit {
  execution_unit_id

  source_operation_id
  source_operation_hash

  canonical_operation
  canonical_operation_version
  canonical_definition_fingerprint

  targets[]
  arguments
  preconditions[]
  expected_effects[]

  execution_unit_hash
}
```

### 11.1 Source binding and exact Step29 operation re-verification

`source_operation_id` references the exact Step29 `CanonicalChangeOperation.operation_id`.

Step30 SHALL independently recompute the exact Step29 semantic operation hash by:

1. resolving every `CanonicalChangeOperation.scope_rule_id` against the supplied `ApprovalScopeBoundary.existing_entity_rules`;
2. computing each exact Step29 `compute_scope_rule_fingerprint(rule)` value;
3. invoking the frozen Step29 `compute_operation_semantic_hash(...)` algorithm over:

```text
origin
canonical_operation
canonical_operation_version
canonical_definition_fingerprint
targets
arguments
expected_effects
resolved scope_rule_fingerprints
source_evidence
```

4. requiring:

```text
CanonicalChangeOperation.operation_id
  == "COP-" + recomputed_operation_hash[:12]
```

Any mismatch fails:

```text
EXECUTION_OPERATION_MISMATCH
```

The recomputed full digest becomes `source_operation_hash`.

This validation proves that Step30 is projecting the exact Step29 semantic operation rather than trusting an opaque construction ID.

### 11.2 Canonical projection

The following fields MUST be copied without semantic modification from the source operation:

```text
canonical_operation
canonical_operation_version
canonical_definition_fingerprint
targets
arguments
expected_effects
```

### 11.3 Preconditions in v1

Every ExecutionUnit SHALL carry the complete immutable Step29 `CanonicalChangeSet.preconditions` collection in v1.

Step30 does not interpret, narrow, or discard precondition obligations. A future version may introduce machine-readable precondition-to-operation scoping, but v1 fails closed by preserving the full frozen set.

### 11.4 No reverse slice reference

`ExecutionUnit` SHALL NOT contain `execution_slice_id`.

Membership is expressed by `ExecutionSlice.execution_units[]`. This keeps hash derivation acyclic and avoids duplicate ownership of the parent relation.

### 11.5 Forbidden Unit fields

ExecutionUnit MUST NOT contain:

```text
provider_id
provider_tool
native_id
native_kind
AutoCAD Handle
Revit ElementId
internal/native unit payload
binding_set_hash
approval_id
ExecutionGrant
runtime status
ActualDelta
verification result
rollback/Saga state
```

---

## 12. ExecutionSlice contracts

### 12.1 ApprovedExecutionScopeRef

```text
ApprovedExecutionScopeRef {
  scope_id
  scope_hash
  execution_slice_scope_rule_id
}
```

The referenced slice-scope rule MUST come from the exact supplied ApprovalScopeBoundary and MUST be the result of §10 deterministic selection.

### 12.2 ExecutionSlice

```text
ExecutionSlice {
  execution_slice_id

  changeset_id
  changeset_hash

  host_runtime_ref
  approved_scope_ref

  execution_units[]

  execution_slice_hash
}
```

An ExecutionSlice is grouped by the exact key:

```text
(
  host_type,
  host_instance_id,
  document_ref,
  execution_slice_scope_rule_id
)
```

Two ExecutionUnits with different values for any key component MUST appear in different slices.

ExecutionSlice is not a provider boundary. It contains no provider/native execution material.

ExecutionSlice also contains no runtime `status` field. Runtime state belongs to Step33.

---

## 13. ExecutionDependency contract

```text
ExecutionDependency {
  predecessor_execution_unit_id
  successor_execution_unit_id
  reason_ref
}
```

Step30 SHALL construct a one-to-one map:

```text
Step29 operation_id → Step30 execution_unit_id
```

Then each Step29 `ChangeDependency` is mechanically projected:

```text
predecessor_operation_id → successor_operation_id
```

into:

```text
predecessor_execution_unit_id → successor_execution_unit_id
```

with the exact Step29 `reason_ref` preserved.

Step30 MUST NOT:

```text
invent a dependency
delete a dependency
reverse a dependency
optimize dependency ordering
add provider-based ordering
add Host-convenience ordering
```

Cross-slice dependencies are preserved exactly. Step30 describes ordering only; Step33 owns partial-failure and Saga behavior.

Invalid dependency projection fails:

```text
EXECUTION_DEPENDENCY_INVALID
```

---

## 14. ExecutionPlan contract

```text
ExecutionPlan {
  execution_plan_id

  changeset_id
  changeset_hash

  approval_scope_ref {
    scope_id
    scope_hash
  }

  routing_snapshot_id
  routing_snapshot_hash

  execution_slices[]
  execution_dependencies[]

  execution_plan_hash
}
```

The ExecutionPlan is the immutable top-level Step30 artifact.

It freezes:

```text
which canonical transaction
under which exact approval scope
using which exact task-scoped runtime route snapshot
partitioned into which Host/document/scope slices
with which canonical execution units
and with which preserved execution dependencies
```

It intentionally does not freeze provider selection.

---

## 15. Deterministic hashing

All Step30 hashing SHALL use the same canonical JSON principles established in Step29:

- stable key ordering;
- deterministic collection normalization where order is semantically irrelevant;
- lowercase SHA-256 hex digests;
- no mutable runtime state;
- construction IDs do not add independent semantic authority unless explicitly named below as a bound reference.

### 15.1 routing_snapshot_hash

The routing snapshot hash binds the normalized exact task-scoped mapping:

```text
semantic_id
→ host_type
→ host_instance_id
→ document_ref
```

Step30 SHALL recompute and verify the supplied routing hash.

### 15.2 source_operation_hash

`source_operation_hash` is the full recomputed Step29 canonical operation semantic hash from §11.1.

### 15.3 execution_unit_hash

`execution_unit_hash` binds:

```text
changeset_hash
source_operation_hash
canonical_operation
canonical_operation_version
canonical_definition_fingerprint
targets
arguments
preconditions
expected_effects
```

It does not bind slice identity, provider identity, native identity, approval state, or runtime status.

Construction ID:

```text
execution_unit_id = "EU-" + execution_unit_hash[:12]
```

### 15.4 execution_slice_hash

`execution_slice_hash` binds:

```text
changeset_hash
approval_scope_boundary.scope_hash
selected execution_slice_scope_rule_id
host_runtime_ref
sorted execution_unit_hashes
```

Construction ID:

```text
execution_slice_id = "XS-" + execution_slice_hash[:12]
```

The parent Slice owns Unit membership; Unit hashes never depend on Slice ID/hash.

### 15.5 execution_plan_hash

`execution_plan_hash` binds:

```text
changeset_hash
approval_scope_boundary.scope_hash
routing_snapshot_hash
sorted execution_slice_hashes
normalized execution dependency semantic payloads
```

For plan hashing, each dependency semantic payload SHALL be:

```text
{
  predecessor_execution_unit_hash,
  successor_execution_unit_hash,
  reason_ref
}
```

resolved from the deterministic Unit map. Raw Unit construction IDs do not add independent hash entropy.

Construction ID:

```text
execution_plan_id = "XP-" + execution_plan_hash[:12]
```

### 15.6 Hash hierarchy

The acyclic identity hierarchy is:

```text
CanonicalChangeSet hash
        ↓
ExecutionUnit hash
        ↓
ExecutionSlice hash
        ↓
ExecutionPlan hash
```

ProviderBinding does not enter any Step30 hash.

Therefore a provider switch may change Step31 `binding_set_hash` and invalidate/reissue Step32 ExecutionGrant while leaving ChangeSet, ExecutionUnit, ExecutionSlice, and ExecutionPlan unchanged.

---

## 16. Deterministic planning algorithm

Step30 SHALL execute the following pure planning pipeline:

```text
1. validate request/public types
2. verify ChangeSet ↔ ApprovalScopeBoundary exact binding
3. resolve every Step29 operation scope rule against exact boundary existing rules
4. recompute and verify RuntimeRoutingEvidence hash
5. enforce exact closed-world target-route coverage
6. enumerate Step29 operations in deterministic semantic order
7. for each operation:
     a. recompute exact Step29 source operation hash from boundary rule fingerprints
     b. require operation_id == COP-<hash-prefix>
     c. resolve all targets from RuntimeRoutingEvidence
     d. require one HostRuntimeRef across all targets
     e. derive the unique deterministic least-authority slice scope
     f. materialize exactly one ExecutionUnit
8. verify every Step29 operation produced exactly one Unit
9. group Units by HostRuntimeRef + selected slice scope
10. materialize deterministic ExecutionSlices
11. project every Step29 ChangeDependency exactly once
12. verify no dependency was added, omitted, reversed, duplicated, or unresolved
13. compute ExecutionPlan hash and construction ID
14. return immutable ExecutionPlan
```

The algorithm performs no I/O after the request has been assembled.

---

## 17. Fail-closed error contract

Step30 SHALL expose a stable domain exception carrying a machine-readable error code, for example `ExecutionPlanningError(code, message)`.

At minimum the following codes are frozen:

```text
EXECUTION_INPUT_INVALID
EXECUTION_SCOPE_MISMATCH
EXECUTION_ROUTING_HASH_MISMATCH
EXECUTION_ROUTE_UNRESOLVED
EXECUTION_ROUTE_CONFLICT
EXECUTION_ROUTE_EXTRANEOUS
EXECUTION_OPERATION_MISMATCH
EXECUTION_OPERATION_NOT_PARTITIONABLE
EXECUTION_SLICE_SCOPE_UNCOVERED
EXECUTION_SLICE_SCOPE_AMBIGUOUS
EXECUTION_DEPENDENCY_INVALID
```

`EXECUTION_OPERATION_MISMATCH` covers a Step29 operation whose recomputed semantic hash does not match its `COP-<hash-prefix>` identity or whose projected canonical fields do not remain exact.

Step30 SHALL fail closed rather than infer or repair authority-sensitive data.

---

## 18. Immutability requirements

All public Step30 value contracts SHALL be frozen/immutable.

Mutable caller containers SHALL be defensively copied/normalized before being stored.

After construction, later caller mutation of input mappings/lists MUST NOT change:

```text
RuntimeRoutingEvidence
ExecutionUnit
ExecutionSlice
ExecutionPlan
or any computed hash
```

Step30 contains no mutable workflow lifecycle field.

---

## 19. RevisionBarrier placement

RevisionBarrier is mandatory in the runtime chain but is **not** owned by Step30 and is not part of the ExecutionPlan hash.

Runtime order remains:

```text
ExecutionPlanning
↓
RevisionBarrier
↓
ProviderBinding
↓
ExecutionGrant
↓
Apply
```

RevisionBarrier checks whether exact target Host revision/planning preconditions still match after user approval and execution planning.

A stale revision returns the existing runtime error:

```text
REVISION_CONFLICT
```

A RevisionBarrier pass/fail result is transient runtime admission state. It MUST NOT change immutable Step30 planning identity.

---

## 20. Step31 handoff contract

Step31 receives immutable Step30 values:

```text
ExecutionSlice
  ├─ HostRuntimeRef
  ├─ ApprovedExecutionScopeRef
  └─ ExecutionUnit[]
```

Only after this handoff may the execution layer introduce:

```text
persistent HostBinding
native entity refs
provider capability
provider_id
provider_tool
provider version
provider-native constraints
native units
native payload
```

Step31 then produces:

```text
ExecutionUnit
   ↓
ProviderBinding[]
   ↓
binding_set_hash
```

A ProviderBinding MUST NOT alter ExecutionUnit canonical semantics.

Changing provider/native binding while the canonical plan remains the same MUST leave all Step30 hashes unchanged and change the relevant Step31 `binding_set_hash`.

---

## 21. Step32 runtime-order clarification

The numbered implementation steps represent contract ownership, not necessarily chronological runtime construction order.

The master runtime may have a durable ApprovalRecord before execution planning, while Step32 remains the implementation owner of the ApprovalRecord/ExecutionGrant contracts.

Therefore:

- Step30 does not own or hash ApprovalRecord fields;
- the Orchestrator/Gateway is responsible for ensuring production execution planning occurs under valid governance admission;
- Step31 ProviderBinding may occur after RevisionBarrier;
- Step32 issues a per-slice ExecutionGrant bound to the exact ChangeSet, approved scope, Host instance, execution slice, and Step31 `binding_set_hash`.

This distinction prevents governance lifecycle state from contaminating deterministic Step30 identity.

---

## 22. Architecture guard

The Step30 production package SHALL reject leakage of provider/native/governance/runtime concerns.

Architecture tests SHALL at least guard against production Step30 fields/imports such as:

```text
provider_id
provider_tool
native_id
native_kind
ElementId
Handle
internal_unit
binding_set_hash
approval_id
ExecutionGrant
ActualDelta
verification_status
rollback
saga
mutable status
```

The package MAY refer to Step31/32/33 concepts in documentation/tests that verify boundaries, but production contracts/planner code must remain provider-neutral and runtime-state-free.

---

## 23. Required test matrix

### 23.1 Determinism

- identical ChangeSet + ApprovalScopeBoundary + RuntimeRoutingEvidence produces byte-equivalent normalized artifacts and identical Unit/Slice/Plan hashes;
- caller collection order does not change semantically order-insensitive hashes;
- opaque construction ordering does not change Plan identity.

### 23.2 Scope and source-operation binding

- different `changeset_hash` is rejected;
- different `scope_body_hash` is rejected;
- operation `scope_rule_id` absent from boundary existing rules is rejected;
- recomputed Step29 operation hash must match `COP-<hash-prefix>`;
- changing exact boundary rule semantics causes the old Step29 operation identity to fail verification;
- Step30 never expands scope to make routing succeed.

### 23.3 Routing

- exact route coverage succeeds;
- missing route fails `EXECUTION_ROUTE_UNRESOLVED`;
- conflicting duplicate route fails `EXECUTION_ROUTE_CONFLICT`;
- extraneous route fails `EXECUTION_ROUTE_EXTRANEOUS`;
- wrong routing hash fails `EXECUTION_ROUTING_HASH_MISMATCH`.

### 23.4 Partitioning

One operation crossing any of the following fails `EXECUTION_OPERATION_NOT_PARTITIONABLE`:

```text
host_type
host_instance_id
document_ref
```

Different Step29 operations may route to different Host/document slices.

### 23.5 Slice-scope selection

- unique minimum-authority candidate succeeds;
- no candidate fails `EXECUTION_SLICE_SCOPE_UNCOVERED`;
- tied minimum candidates with different normalized authority bodies fail `EXECUTION_SLICE_SCOPE_AMBIGUOUS`;
- semantically duplicate tied candidates choose the lexicographically smallest rule ID deterministically;
- extra creation/deletion rule authority counts toward candidate surplus;
- caller cannot provide/override chosen slice scope.

### 23.6 Canonical projection

- every Step29 operation produces exactly one ExecutionUnit;
- no operation may be omitted or duplicated;
- target/argument/effect/version/definition-fingerprint changes are rejected or necessarily produce different verified source/unit hashes;
- every Unit carries the complete v1 Step29 precondition set.

### 23.7 Dependency projection

- every Step29 dependency produces exactly one ExecutionDependency;
- cross-slice dependency is retained;
- added/deleted/reversed/unknown dependency fails `EXECUTION_DEPENDENCY_INVALID`.

### 23.8 Immutability

- mutating caller-owned route, argument, or collection values after construction cannot mutate Step30 artifacts;
- no public Step30 artifact exposes mutable lifecycle status.

### 23.9 Provider independence

- changing only hypothetical Step31 provider selection has no effect on ExecutionUnit, ExecutionSlice, or ExecutionPlan hashes;
- no Step30 production object contains native/provider payload.

### 23.10 Runtime separation

- RevisionBarrier result is absent from Plan semantics and hashes;
- Step30 has no ActualDelta/verification/Saga state.

### 23.11 Upstream regressions

Step30 CI SHALL run focused regressions for at least:

```text
Step28 approval scope boundary
Step29 immutable canonical ChangeSet
```

and the full repository test suite before merge.

---

## 24. CI boundary

Step30 SHALL add a dedicated workflow covering:

```text
exact PR diff boundary
Step30 contracts
Step30 routing/hash tests
Step30 partitioning tests
Step30 scope-selection tests
Step30 dependency projection tests
Step30 architecture tests
Step28 regression
Step29 regression
Ruff
full repository pytest
```

The exact changed-file boundary SHOULD be limited to the Step30 package, Step30 tests/workflow, root test configuration if required, this written design, and the later implementation plan.

---

## 25. Explicitly deferred concerns

Step30 v1 does not implement:

```text
splittable canonical operations
multi-root ChangeSet composition
provider/native binding
provider health/license/certification selection
native ID resolution
native unit conversion
RevisionBarrier execution
ApprovalRecord/ExecutionGrant
HostCommand/idempotency
ActualDelta
verification/reconciliation
scope comparator
rollback/compensation/Saga
mutable execution status
```

A future splittable-operation feature requires an explicit machine-readable Step23 contract proving split semantics. It must not be inferred by Step30.

---

## 26. Acceptance criteria

Step30 is complete when all of the following are true:

1. A deterministic immutable ExecutionPlan can be built from exact Step29 ChangeSet, exact Step28 ApprovalScopeBoundary, and exact task-scoped RuntimeRoutingEvidence.
2. Runtime routing is closed-world and its hash is independently recomputed.
3. Every Step29 `scope_rule_id` resolves to the exact supplied boundary existing rule, and Step30 can recompute the exact Step29 operation semantic hash.
4. Every Step29 CanonicalChangeOperation maps to exactly one canonical ExecutionUnit.
5. A single operation crossing Host instance or document boundaries fails closed rather than being split.
6. Step30 deterministically selects a unique least-authority execution-slice scope from the frozen Step28 boundary, with machine-defined tie handling.
7. ExecutionSlices group Units only by HostRuntimeRef + approved slice scope.
8. Every Step29 ChangeDependency is projected exactly once, including cross-slice dependencies.
9. Unit/Slice/Plan hashes are deterministic, acyclic, provider-independent, and bound to the exact upstream artifacts they consume.
10. Step30 artifacts contain no provider/native/governance/runtime-state leakage.
11. RevisionBarrier remains a runtime gate after planning and before ProviderBinding, outside the Plan hash.
12. Step31 can consume immutable ExecutionSlice/ExecutionUnit values without Step30 choosing provider/native behavior.
13. Focused Step30 tests, Step28/29 regressions, Ruff, and full repository pytest are green.

---

## 27. Final architectural invariant

```text
Step29 CanonicalChangeSet
  owns canonical mutation identity

Step28 ApprovalScopeBoundary
  owns maximum approved authority

RuntimeRoutingEvidence
  supplies exact current provider-neutral Host/document routing facts

Step30 ExecutionPlan
  owns deterministic execution partitioning only

RevisionBarrier
  gates stale runtime state

Step31 ProviderBinding
  owns provider/native realization

Step32 Governance
  owns ApprovalRecord / ExecutionGrant

Step33 Runtime
  owns apply / ActualDelta / verify / reconcile / Saga
```

Or, compactly:

```text
Step30 routing authority
=
supplied RuntimeRoutingEvidence
+ frozen Step28 slice scope
+ frozen Step29 operation DAG

Step30 MUST NOT:
- query Host/D5 for routing
- split canonical operations
- invent dependencies
- widen scope
- choose providers
- resolve native targets
- generate native payloads
- carry mutable runtime status
```
