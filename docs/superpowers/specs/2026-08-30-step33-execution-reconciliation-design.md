# Step33 — Execution Reconciliation / ScopeComparator / Saga Design

> Status: Implemented; implementation proof recorded at `78476f6dfa9d8b99d96be142138b576fe50d2dfa` / Actions `33325648436`; exact status-HEAD CI is still required before merge
> Date: 2026-08-30
> Base: `main@cef76e111f74d10f063eedfebc7efc0d805caefa`
> Branch: `feat/step33-execution-reconciliation`
> Master spec: `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`
> Phase: G / Step33 — Verify / ScopeComparator / Saga

---

## 1. Purpose

Step33 closes the execution loop after Step32 has admitted an `ExecutionGrant` and Host side effects may have occurred. It answers three independent questions:

```text
ScopeComparator
= Did the Host actually modify only what the approval allowed?

SemanticVerifier
= If the side effects stayed inside scope, is the resulting design semantically correct?

ExecutionSaga
= Given the durable side effects and reconciliation results so far, may execution continue, or must it stop and recover?
```

Step33 MUST preserve the master-spec invariants that Host read-back / `ActualDelta` is the authoritative reconciliation fact, `ActualDelta ⊄ ApprovalScopeBoundary` is a blocking `SCOPE_BREACH`, and cross-host failure uses Saga / Compensating ChangeSet rather than XA/2PC.

Step33 is provider-neutral. It MUST NOT add Host product branches or interpret Revit, AutoCAD, Tekla, native API types, layer conventions, BuiltInCategory values, native command names, or provider-specific rollback mechanisms.

---

## 2. Non-goals

Step33 does not:

- execute Host commands;
- translate canonical operations into provider/native arguments;
- issue or admit `ExecutionGrant` authority;
- own D5 semantic storage or projection internals;
- own Semantic Provider implementations;
- redefine Step28 scope semantics;
- redefine Step29 ChangeSet semantics or hashes;
- redefine Step30 Slice/Unit semantics or existing hashes;
- redefine Step31 ProviderBinding semantics;
- bypass normal approval for compensation;
- implement XA/2PC;
- hide recovery through native `UNDO`, transaction rollback, or equivalent Host-specific escape hatches.

---

## 3. Fixed upstream handoff

The authoritative pre-execution lineage remains:

```text
ApprovalScopeBoundary      Step28
        ↓
CanonicalChangeSet         Step29
        ↓
ExecutionPlan / Slice      Step30
        ↓
ProviderBindingSet         Step31
        ↓
ApprovalRecord / Grant     Step32
        ↓
AdmittedExecutionAuthority
```

Step32 hands Step33:

```text
AdmittedExecutionAuthority {
  approval_hash
  grant_hash
  changeset_hash
  approved_scope_hash
  execution_slice_hash
  binding_set_hash
  host_instance_id
  admitted_at
}
```

Step33 MUST consume this lineage as immutable authority evidence. It MUST NOT repair missing joins or infer replacement hashes.

---

## 4. New subsystem boundary

Step33 introduces one provider-neutral subsystem:

```text
platform/execution_reconciliation/
  src/design_execution_reconciliation/
    contracts.py
    hashing.py
    scope_comparator.py
    verifier.py
    saga.py
    store.py
    service.py
```

Responsibilities:

- `contracts.py`: immutable Step33 value contracts and stable enums/errors.
- `hashing.py`: Step33-only canonical hashes.
- `scope_comparator.py`: deterministic `ActualDelta` vs `ApprovalScopeBoundary` evaluation.
- `verifier.py`: deterministic `ValidationTask` evaluation over snapshot-bound semantic evidence.
- `saga.py`: deterministic state-transition and continuation rules.
- `store.py`: durable atomicity/CAS/idempotent-recovery semantics.
- `service.py`: cross-step joins, deterministic orchestration of pure Step33 operations, and stable error mapping.

Step33 Core MAY depend only on stable public contracts/validators from Step28–32 and stable semantic snapshot/environment contracts. It MUST NOT read D5 internal projection storage.

---

## 5. Targeted Step30 enhancement

Saga creation must bind the complete intact Step30 `ExecutionPlan`, not a caller-invented Slice list. Step30 SHALL therefore expose:

```python
validate_execution_plan_integrity(execution_plan)
```

The validator SHALL:

- validate every `ExecutionSlice` using existing Step30 semantics;
- validate execution-dependency references and plan membership;
- recompute the existing execution-plan semantic body and existing `execution_plan_hash`;
- fail closed on mismatch.

This MUST NOT change the Step30 `ExecutionPlan` contract or any existing Step30 hash algorithm.

No Step28, Step29, Step31, or Step32 production contract change is required by this design.

---

# 6. Provider-neutral ActualDelta

## 6.1 Boundary

Existing Host `HostDelta` is a Host-local stream over `document_id + native_id` and revisions. It is necessary provenance, but it cannot directly prove semantic approval-scope membership because Step28 operates over `SemanticId`, canonical kinds/aspects, creation derivation, and deletion authority.

Step33 therefore consumes a normalized provider-neutral `ActualDelta` assembled at the Host/Execution → reconciliation boundary.

## 6.2 Contracts

```text
ActualDelta {
  actual_delta_id

  grant_hash
  binding_set_hash
  execution_slice_hash
  changeset_hash
  approved_scope_hash

  host_instance_id
  document_ref
  revision_before
  revision_after

  changes[]
  actual_delta_hash
}
```

```text
ActualChange {
  change_kind: CREATE | MODIFY | DELETE

  semantic_id?
  canonical_kind?
  changed_aspects[]

  canonical_operation?
  source_execution_unit_hash?
  source_semantic_id?
  derivation_rule?

  host_entity_ref?       # provenance and stable instance discriminator only
  actual_change_hash
}
```

## 6.3 Required semantics

- `MODIFY` MUST carry `semantic_id` and at least one canonical `changed_aspect`.
- `DELETE` MUST carry `semantic_id`.
- `CREATE` MUST carry `canonical_operation` and a stable instance discriminator. The discriminator is `semantic_id` when available, otherwise `host_entity_ref` MUST be present.
- `CREATE` MAY lack a stable post-create `semantic_id` at normalization time, but MUST carry enough canonical evidence to evaluate the applicable Step28 `CreationRule`; where the rule requires it this includes `canonical_kind`, `source_semantic_id`, and `derivation_rule`.
- `source_execution_unit_hash`, when present, MUST identify a member of the exact admitted `ExecutionSlice`. It is provenance/lineage evidence, not a substitute for CreationRule matching.
- `changed_aspects` MUST use the Step28 canonical aspect vocabulary.
- `host_entity_ref` MUST NOT drive semantic authorization decisions from native type/category/layer/product metadata. It MAY distinguish two otherwise identical CREATE instances when no `semantic_id` exists.
- The Step32 lineage in `ActualDelta` MUST exactly match the admitted authority before comparison starts.
- `revision_after` MUST represent the Host read-back revision containing the side effects; revision regressions are invalid.

The normalized `ActualDelta` is the authoritative statement of actual Host side effects. D5 reconstruction verifies semantic outcome; it does not replace or overwrite `ActualDelta`.

## 6.4 ActualChange identity

`actual_change_hash` SHALL hash the canonical normalized change body, including the stable instance discriminator. Host-native metadata not needed to distinguish the changed instance MUST NOT change authorization semantics.

The canonical instance key used for ordering/allocation SHALL be:

```text
semantic_id                        if available
else (document_ref, native_id)     from host_entity_ref
```

A CREATE with neither identity form is invalid.

## 6.5 ActualDelta identity

```text
actual_delta_hash = H({
  grant_hash,
  binding_set_hash,
  execution_slice_hash,
  changeset_hash,
  approved_scope_hash,
  host_instance_id,
  document_ref,
  revision_before,
  revision_after,
  sorted(actual_change_hashes)
})
```

The hash MUST exclude `actual_delta_id`, receipt timestamps, and itself.

Re-reading the same committed revision with the same normalized side effects MUST produce the same `actual_delta_hash` after response loss/retry.

---

# 7. ScopeComparator

## 7.1 Responsibility

`ScopeComparator` answers exactly:

> Is every normalized actual Host side effect authorized by the exact Step28 boundary and exact Step30 Slice scope?

It does not decide whether the final design result is correct.

## 7.2 Input

```text
ScopeComparisonRequest {
  admitted_execution_authority
  actual_delta
  approval_scope_boundary
  execution_slice
}
```

## 7.3 Validation order

The comparator SHALL execute in this order:

1. type/contract integrity;
2. exact Step32 authority lineage joins;
3. Step28 boundary integrity;
4. Step30 Slice integrity;
5. Host/document/revision consistency;
6. exact `ExecutionSliceScopeRule` resolution;
7. `MODIFY` evaluation;
8. `DELETE` evaluation;
9. `CREATE` evaluation and count allocation;
10. immutable hashed result.

No later rule may repair an earlier mismatch.

## 7.4 MODIFY

For every `MODIFY`:

- `semantic_id` MUST match an allowed `ExistingEntityRule` available to the Slice;
- every changed canonical aspect MUST be contained in the authorized aspect union for that entity under the Slice scope;
- unmatched entity or unauthorized aspect is a violation.

## 7.5 DELETE

For every `DELETE`, `semantic_id` MUST match a `DeletionRule` available to the Slice. Absence of applicable deletion authority is a violation.

## 7.6 CREATE

For every `CREATE`, authorization MUST be proven from Step28 `CreationRule` semantics, including as applicable:

- `canonical_operation`;
- source selector;
- canonical entity kind;
- required derivation;
- `max_count`.

A create is not authorized merely because its canonical kind is generally known or the provider reported success.

### 7.6.1 Deterministic overlapping-rule allocation

If a create matches multiple `CreationRule`s, create-to-rule assignment is a deterministic allocation problem. An allocation is valid only when every create is assigned to an eligible rule and every rule respects `max_count` where present.

If multiple valid allocations exist, the comparator SHALL choose the lexicographically canonical allocation ordered by:

```text
(rule_id, actual_change stable instance key, actual_change_hash)
```

Container/Python iteration order MUST NOT affect the result. No valid allocation means `SCOPE_BREACH`.

## 7.7 Output

```text
ScopeComparisonResult {
  status: WITHIN_SCOPE | SCOPE_BREACH

  actual_delta_hash
  approved_scope_hash
  execution_slice_hash

  matched_changes[]
  violations[]
  comparison_hash
}
```

Violation details SHALL use stable machine codes including at minimum:

```text
ENTITY_OUTSIDE_SCOPE
ASPECT_OUTSIDE_SCOPE
CREATION_KIND_FORBIDDEN
CREATION_SOURCE_FORBIDDEN
CREATION_DERIVATION_MISMATCH
CREATION_COUNT_EXCEEDED
DELETION_FORBIDDEN
LINEAGE_MISMATCH
```

The outer condition remains `SCOPE_BREACH`; detail codes are for audit/recovery planning.

A `SCOPE_BREACH` MUST block remaining not-yet-admitted Saga slices. Semantic verification for that Slice MUST NOT run as a success gate after a scope breach; the authoritative failure is already `SCOPE_BREACH`.

---

# 8. VerificationEvidenceBundle

## 8.1 Purpose

Step29 stores content-addressed `ValidationTask.contract_ref` values but intentionally does not embed every verification contract body. D5 `SemanticSnapshot` binds projection/environment/freshness/coverage/assurance but is not an inline entity-value dump.

Step33 therefore consumes a snapshot-bound provider-neutral evidence bundle assembled by the Semantic/D5 integration layer.

## 8.2 Contract

```text
VerificationEvidenceBundle {
  evidence_bundle_id

  changeset_hash
  execution_slice_hash
  actual_delta_hash

  semantic_environment_ref

  post_execution_snapshot_ref
  post_execution_projection_ref
  base_host_revision

  contract_evidence[]
  subject_evidence[]

  evidence_bundle_hash
}
```

```text
VerificationContractEvidence {
  contract_ref
  contract_body
}
```

```text
VerificationSubjectEvidence {
  semantic_id
  canonical_kind

  properties{}
  placement?
  geometry_evidence?
  relationships[]
  constraints[]
  classification[]

  evidence_aspects[]
  projection_ref
}
```

The integration layer SHOULD return only the subject × aspect × field evidence required by the ValidationTasks. A full IFC/Metro mirror is not required.

## 8.3 Integrity

For every referenced contract:

```text
H(contract_body) == ValidationTask.contract_ref
```

The bundle SemanticEnvironment MUST exactly match the ChangeSet/approval planning environment. Snapshot/projection references MUST prove the post-execution Host revision being verified.

Missing evidence is not success.

---

# 9. SemanticVerifier

## 9.1 Responsibility

`SemanticVerifier` evaluates the exact Step29 `ValidationTask` semantics over exact snapshot-bound evidence. It does not decide execution order or Saga continuation.

Host self-reported verification fields may be diagnostics/provenance but MUST NOT directly produce a platform PASS.

## 9.2 Input

```text
SemanticVerificationRequest {
  admitted_execution_authority
  canonical_changeset
  validation_tasks[]
  verification_evidence_bundle
  verified_at
}
```

`validation_tasks[]` MUST be an exact subset of `canonical_changeset.validation_tasks`; callers may not invent tasks.

## 9.3 Validation order

1. request/type integrity;
2. authority lineage exact joins;
3. Step29 ChangeSet integrity;
4. evidence-bundle integrity/hash;
5. SemanticEnvironment exact match;
6. post-execution snapshot/projection/revision lineage;
7. task `contract_ref` ↔ contract evidence matching;
8. `H(contract_body) == contract_ref`;
9. subject-evidence completeness;
10. deterministic contract evaluation;
11. deterministic aggregate result.

## 9.4 Result

```text
VerificationStatus =
  PASSED
  FAILED
  EVIDENCE_INSUFFICIENT
```

```text
SemanticVerificationResult {
  verification_id
  changeset_hash
  execution_slice_hash
  actual_delta_hash
  evidence_bundle_hash
  task_results[]
  status
  verification_hash
}
```

```text
ValidationTaskResult {
  validation_task_id
  status: PASSED | FAILED | EVIDENCE_INSUFFICIENT
  observations[]
  failure_codes[]
  task_result_hash
}
```

Aggregation is fixed:

```text
all PASSED                     → PASSED
any FAILED                     → FAILED
no FAILED + any INSUFFICIENT   → EVIDENCE_INSUFFICIENT
```

Execution-loop mapping is fixed:

```text
PASSED                 → verification passes
FAILED                 → VERIFY_FAILED
EVIDENCE_INSUFFICIENT  → VERIFY_FAILED
                         detail = VERIFY_EVIDENCE_INSUFFICIENT
```

The platform therefore distinguishes "proved wrong" from "could not sufficiently prove correct", while both fail closed for production writes.

---

# 10. Declarative verification contract

Step33 SHALL support provider-neutral:

```text
SEMANTIC_ASSERTIONS_V1
```

Example:

```json
{
  "type": "SEMANTIC_ASSERTIONS_V1",
  "assertions": [
    {
      "subjects": {"from_argument": "targets"},
      "path": "properties.thickness",
      "operator": "EQUALS_ARGUMENT",
      "argument": "thickness",
      "tolerance": {"absolute": 0.001, "unit": "m"}
    }
  ]
}
```

The fixed provider-neutral operator vocabulary initially includes:

```text
EXISTS
NOT_EXISTS
EQUALS_LITERAL
EQUALS_ARGUMENT
DELTA_EQUALS_ARGUMENT
RELATIONSHIP_EXISTS
CLASSIFICATION_IS
```

The evaluator MUST NOT branch by Host product or provider-specific operation.

Legacy/weak contracts such as `{"type":"HOST_READ_BACK"}` do not prove semantic correctness by themselves. When deterministic semantic proof is required but the contract cannot be executed, the result MUST be `EVIDENCE_INSUFFICIENT` with detail `VERIFY_CONTRACT_UNSUPPORTED`.

Published verification semantics MUST NOT be silently strengthened in place if that changes the existing contract fingerprint. Such semantic change requires versioned contract/operation evolution.

---

# 11. Verification examples

## 11.1 Inside scope but wrong value

```text
set_thickness.v1
WALL-001
thickness = 300 mm
```

Actual side effect:

```text
WALL-001
MODIFY
changed_aspects = [PROPERTIES]
```

If Step28 authorizes `WALL-001 / PROPERTIES`, ScopeComparator returns `WITHIN_SCOPE`.

If post-execution evidence says:

```text
WALL-001.properties.thickness = 350 mm
```

SemanticVerifier returns `FAILED` with detail `EXPECTED_VALUE_MISMATCH`; Slice outcome is `VERIFY_FAILED`, not `SCOPE_BREACH`.

## 11.2 Missing evidence

If reconstruction proves only `IDENTITY`/`CLASSIFICATION` but validation requires `PROPERTIES.thickness`, the task result is `EVIDENCE_INSUFFICIENT` with detail `REQUIRED_FIELD_MISSING`, mapped to `VERIFY_FAILED`.

---

# 12. Execution Saga

## 12.1 Responsibility

Step33 Saga records durable post-admission execution/reconciliation state and enforces continuation barriers. LangGraph remains workflow driver; Gateway remains authorization owner.

## 12.2 Immutable definition

```text
ExecutionSagaDefinition {
  saga_id

  changeset_hash
  approved_scope_hash
  semantic_environment_ref
  execution_plan_hash

  ordered_slice_hashes[]
  slice_dependencies[]

  saga_definition_hash
}
```

Saga creation MUST validate:

- Step28 `ApprovalScopeBoundary` integrity;
- Step29 `CanonicalChangeSet` integrity;
- Step30 `ExecutionPlan` integrity;
- exact ChangeSet ↔ Boundary ↔ Plan joins;
- Saga slices equal Step30 plan slices;
- Saga slice dependencies are deterministically derived from Step30 execution-unit dependencies.

### 12.2.1 Slice dependency derivation

Step30 dependencies are between `ExecutionUnit`s. Step33 SHALL derive a Slice dependency edge `Slice A → Slice B` when any Step30 unit dependency crosses from a unit in A to a unit in B. Same-Slice dependencies remain Step30-local and do not create a self edge.

The derived Slice DAG MUST be acyclic if the validated Step30 plan is valid.

### 12.2.2 Canonical sequential order

v0.6 uses one canonical sequential order for all side-effecting Slices, including independent DAG roots. `ordered_slice_hashes` SHALL be a deterministic topological order of the derived Slice DAG, with `execution_slice_hash` as the tie-breaker among simultaneously eligible Slices.

This order is part of `saga_definition_hash` and removes scheduling ambiguity across retries/processes.

## 12.3 Durable lifecycle

```text
StoredExecutionSaga {
  definition
  saga_revision
  state
  slice_states[]
  compensation_refs[]
}
```

Saga states:

```text
READY
EXECUTING
PARTIALLY_COMMITTED
SUCCEEDED
COMPENSATING
COMPENSATED
COMPENSATION_FAILED
FAILED
```

`SUCCEEDED` requires every required Slice to have durably reached `SUCCEEDED` after commit, scope PASS, and semantic verification PASS.

---

# 13. Slice reconciliation lifecycle

```text
SliceReconciliationState {
  execution_slice_hash
  sequence_index

  state:
    NOT_STARTED
    ADMISSION_RESERVED
    ADMITTED
    HOST_COMMITTED
    RECONCILING
    SUCCEEDED
    FAILED_BEFORE_COMMIT
    VERIFY_FAILED
    SCOPE_BREACH
    BLOCKED
    COMPENSATED
    COMPENSATION_FAILED

  grant_hash?
  actual_delta_hash?
  scope_comparison_hash?
  semantic_verification_hash?

  reserved_at?
  admitted_at?
  committed_at?
  reconciled_at?
}
```

`HOST_COMMITTED` is not success.

Outcome mapping:

| Host commit | Scope | Verify | Slice outcome |
|---|---|---|---|
| no | — | — | `FAILED_BEFORE_COMMIT` |
| yes | breach | not run as success gate | `SCOPE_BREACH` |
| yes | within | failed | `VERIFY_FAILED` |
| yes | within | insufficient | `VERIFY_FAILED` |
| yes | within | passed | `SUCCEEDED` |

### 13.1 Mandatory reconciliation order

For a committed Slice:

```text
HOST_COMMITTED
→ RECONCILING
→ ScopeComparator
```

If scope result is `SCOPE_BREACH`, Slice immediately becomes `SCOPE_BREACH`; remaining Slices are blocked and semantic verification is not used to override or downgrade that failure.

Only `WITHIN_SCOPE` may proceed to:

```text
D5 reconstruct
→ VerificationEvidenceBundle
→ SemanticVerifier
```

`record_verification_result` MUST reject a Slice without a previously persisted `WITHIN_SCOPE` comparison result for the same `actual_delta_hash`.

---

# 14. Sequential admission barrier for v0.6

v0.6 SHALL allow at most one active side-effecting Slice at a time across the entire Saga, not merely one per dependency chain.

The only Slice eligible for `ADMISSION_RESERVED` is the lowest `sequence_index` Slice still `NOT_STARTED`, and all of its derived Slice predecessors MUST already be `SUCCEEDED`.

While any Slice is in:

```text
ADMISSION_RESERVED
ADMITTED
HOST_COMMITTED
RECONCILING
```

no other Slice may be reserved/admitted.

Thus even two independent DAG roots execute in the frozen canonical sequence. Parallel-safe execution groups are deferred beyond Step33 v0.6 unless a later ADR revises this rule.

---

# 15. Admission reservation and crash recovery

Cross-subsystem crash window:

```text
NOT_STARTED
→ ADMISSION_RESERVED     # Step33 durable CAS
→ Step32 admit grant
→ ADMITTED               # Step33 confirmation
```

`ADMISSION_RESERVED` is an explicit recovery point. Because Step32 recovers repeated admission of the same already-admitted Grant, workflow replay may query/retry Step32 and complete Step33 confirmation without creating a second Host mutation.

Step33 MUST NOT infer `ADMITTED` from elapsed time.

---

# 16. Failure transitions

## 16.1 No committed side effect

If the first/only attempted Slice fails before Host commit and no earlier Slice committed:

```text
Slice → FAILED_BEFORE_COMMIT
Saga  → FAILED
```

No compensation is required.

## 16.2 Partial commit

If any earlier Slice is already `SUCCEEDED` and a later Slice fails before commit, or if any committed Slice ends `VERIFY_FAILED`/`SCOPE_BREACH`:

```text
Saga → PARTIALLY_COMMITTED
```

All remaining `NOT_STARTED` Slices MUST atomically become `BLOCKED`; no new reservation/admission is allowed.

A committed failure MUST NOT collapse to a simple no-side-effect `FAILED` state.

---

# 17. Compensation boundary

Step33 MUST NOT emit Host-native rollback commands or construct an ungoverned reverse operation.

It produces provider-neutral recovery intent/evidence:

```text
CompensationProposal {
  compensation_proposal_id

  source_saga_id
  source_changeset_hash
  failed_slice_hash
  committed_slice_hashes[]

  actual_delta_refs[]
  verification_failure_refs[]
  scope_breach_refs[]

  desired_recovery_effects[]
  proposal_hash
}
```

A real compensation write MUST re-enter the normal DSP write path from current facts:

```text
CompensationProposal
→ current semantic reconstruction
→ canonical recovery action
→ Impact
→ ApprovalScopeBoundary
→ immutable Compensating ChangeSet
→ ApprovalRecord
→ ExecutionSlice
→ ProviderBinding
→ ExecutionGrant
→ Host mutation
→ Step33 reconciliation again
```

The original `ExecutionGrant` MUST NOT automatically authorize compensation. Enterprise policy MAY automatically approve some low-risk compensating ChangeSets, but that is Gateway policy, not Saga self-authorization.

---

# 18. Compensation terminal semantics

```text
original business intent completed
→ SUCCEEDED

original intent failed,
known committed side effects successfully compensated
→ COMPENSATED

compensation also failed
→ COMPENSATION_FAILED
```

`COMPENSATED` MUST NOT become `SUCCEEDED`.

`COMPENSATION_FAILED` is terminal for automatic Step33 recovery in v0.6 and requires HITL/manual or separately authorized recovery. No unbounded automatic compensation loop is allowed.

---

# 19. Store atomicity, CAS, and replay

The Step33 Store owns:

- atomic Saga creation/uniqueness;
- `saga_revision` CAS;
- per-Slice transition serialization;
- global sequential admission reservation;
- atomic blocking of remaining Slices on partial failure;
- immutable evidence refs for committed transitions;
- compensation lifecycle transitions;
- same-evidence idempotent recovery;
- different-evidence conflict detection.

Representative operations:

```text
create_saga
reserve_slice_admission
confirm_slice_admitted
record_host_commit
record_scope_result
record_verification_result
fail_slice_before_commit
begin_compensation
record_compensation_result
get_saga
```

Every mutating operation SHALL require expected `saga_revision` or equivalent atomic lineage precondition.

Rules:

- same logical transition + same evidence hash replay → return/recover existing logical result;
- same logical transition + different evidence → `SAGA_CONFLICT`;
- stale revision → conflict;
- terminal Saga states reject unrelated new execution transitions.

Store owns atomicity; service owns deterministic validation and stable domain-error mapping.

---

# 20. Time model

Step33 domain logic MUST NOT read the wall clock. All times are explicit inputs/evidence, including as applicable:

```text
reserved_at
admitted_at
committed_at
reconciled_at
verified_at
compensation_started_at
compensation_completed_at
```

Audit timestamps do not alter semantic evidence identity unless a defined Step33 hash explicitly includes them.

---

# 21. Step33 hashes

Step33 adds new hashes only. Step28–32 existing hashes MUST remain unchanged.

```text
comparison_hash = H({
  actual_delta_hash,
  approved_scope_hash,
  execution_slice_hash,
  canonicalized_matches,
  canonicalized_violations,
  status
})
```

```text
evidence_bundle_hash = H({
  changeset_hash,
  execution_slice_hash,
  actual_delta_hash,
  semantic_environment_ref,
  post_execution_snapshot_ref,
  post_execution_projection_ref,
  base_host_revision,
  canonicalized_contract_evidence,
  canonicalized_subject_evidence
})
```

```text
verification_hash = H({
  changeset_hash,
  execution_slice_hash,
  actual_delta_hash,
  evidence_bundle_hash,
  canonicalized_task_results,
  status
})
```

```text
saga_definition_hash = H({
  changeset_hash,
  approved_scope_hash,
  semantic_environment_ref,
  execution_plan_hash,
  ordered_slice_hashes,
  slice_dependencies
})
```

Mutable Saga lifecycle is not folded into `saga_definition_hash`.

---

# 22. Stable Step33 errors

```text
ACTUAL_DELTA_INPUT_INVALID
ACTUAL_DELTA_INTEGRITY_INVALID
RECONCILIATION_LINEAGE_MISMATCH
RECONCILIATION_REVISION_INVALID

SCOPE_COMPARISON_INVALID
SCOPE_BREACH

VERIFY_INPUT_INVALID
VERIFY_CONTRACT_MISMATCH
VERIFY_CONTRACT_UNSUPPORTED
VERIFY_EVIDENCE_INSUFFICIENT
VERIFY_FAILED

SAGA_INPUT_INVALID
SAGA_INTEGRITY_INVALID
SAGA_TRANSITION_INVALID
SAGA_CONFLICT
SAGA_PREDECESSOR_NOT_SUCCEEDED
SAGA_ALREADY_TERMINAL

COMPENSATION_CONFLICT
```

Violation/task detail codes such as `ENTITY_OUTSIDE_SCOPE`, `CREATION_COUNT_EXCEEDED`, `EXPECTED_VALUE_MISMATCH`, and `REQUIRED_FIELD_MISSING` are structured detail. Natural-language text MUST NOT drive retry/replan/compensation decisions.

---

# 23. Service facade

The provider-neutral facade SHALL expose operations equivalent to:

```text
ExecutionReconciliationService

create_saga(...)
reserve_slice_admission(...)
confirm_slice_admitted(...)
record_host_commit(...)
compare_scope(...)
verify_semantics(...)
reconcile_slice(...)
fail_slice_before_commit(...)
begin_compensation(...)
record_compensation_result(...)
get_saga(...)
```

`reconcile_slice(...)` MAY be a convenience facade over already-created immutable scope/verification evidence, but MUST NOT hide external Host execution, D5 reconstruction, or Semantic Service lookups inside the pure domain transaction.

---

# 24. Architecture guardrails

Step33 production code MUST fail architecture tests if it introduces:

- Host product names/branches;
- Host-native command/transaction APIs;
- provider-specific verification paths;
- direct D5 internal projection-storage imports;
- hidden native rollback/undo logic;
- XA/2PC transaction managers;
- direct DB-vendor APIs in domain service code;
- `datetime.now`, `datetime.utcnow`, `time.time`, or equivalent wall-clock reads;
- private Step28–32 implementation/hash imports where public APIs exist.

Step33 MUST use public integrity validators from Step28–30 and frozen public contracts of Step31–32.

---

# 25. Test matrix / Definition of Done

Step33 is complete only when fresh CI on the exact final branch HEAD proves at least:

## 25.1 ActualDelta

- deterministic `actual_change_hash` and `actual_delta_hash`;
- same committed revision/effects re-hash identically;
- bad lineage fails before comparison;
- revision regression fails closed;
- CREATE without stable instance discriminator fails;
- Host-native provenance fields cannot alter semantic authorization outcome.

## 25.2 ScopeComparator

- allowed MODIFY entity/aspect passes;
- unauthorized MODIFY aspect breaches;
- DELETE without authority breaches;
- CREATE correct operation/kind/source/derivation/count passes;
- wrong operation/kind/source/derivation fails;
- `max_count` overflow fails;
- overlapping CreationRules use deterministic canonical allocation;
- implicit Host associativity side effects are represented/evaluated rather than ignored.

## 25.3 SemanticVerifier

- contract body hash equals `ValidationTask.contract_ref`;
- SemanticEnvironment drift fails closed;
- snapshot/revision mismatch fails;
- assertion pass → `PASSED`;
- expected-value mismatch → `FAILED` / `VERIFY_FAILED`;
- missing evidence → `EVIDENCE_INSUFFICIENT` / `VERIFY_FAILED`;
- unsupported weak contract cannot PASS;
- Host self-reported success cannot bypass independent evaluation;
- verifier cannot run as the success gate after persisted `SCOPE_BREACH`.

## 25.4 Saga

- deterministic Slice dependency derivation/topological order;
- two independent root Slices still execute sequentially by hash tie-break order;
- at most one Slice may be active/reserved globally;
- first pre-commit failure with no commits → `FAILED`;
- A success + B pre-commit failure → `PARTIALLY_COMMITTED`;
- committed `VERIFY_FAILED` → `PARTIALLY_COMMITTED`;
- committed `SCOPE_BREACH` → `PARTIALLY_COMMITTED`;
- partial failure atomically blocks remaining Slices;
- no next reservation before canonical prior Slice and all required predecessors are `SUCCEEDED`;
- concurrent reservations permit only one valid winner;
- reserve → Step32 admit crash window recovers from `ADMISSION_RESERVED`;
- same transition/evidence replay recovers idempotently;
- different evidence conflicts;
- all Slices reconciled `SUCCEEDED` → Saga `SUCCEEDED`;
- compensation success → original Saga `COMPENSATED`, never `SUCCEEDED`;
- compensation failure → `COMPENSATION_FAILED`.

## 25.5 Cross-step regression

Fresh CI MUST run Step28, Step29, Step30, Step31, Step32 regression suites, Step33 architecture/lint matrix, and full-repository tests.

Acceptance behaviors include:

```text
ActualDelta outside scope stops remaining slices
second cross-host Slice failure enters Saga/partial state
cross-host Saga preserves auditable partial/compensation state
```

---

# 26. Frozen implementation boundary

Allowed changes:

```text
platform/execution_reconciliation/**
tests/execution_reconciliation/**

platform/execution_planning/**
tests/execution_planning/**
  # only validate_execution_plan_integrity and its tests

docs/superpowers/specs/**
docs/superpowers/plans/**

.github/workflows/step33-execution-reconciliation.yml
pyproject.toml
```

Forbidden absent a newly approved blocker:

```text
platform/gateway_authorization/**
platform/provider_binding/**
platform/approval_scope/**
platform/changeset/**

platform/orchestrator/**
platform/semantic_runtime/**
platform/semantic_service/**

hosts/**
providers/**
contracts/**
```

Any newly discovered blocker requiring boundary expansion MUST be surfaced and explicitly re-approved before implementation continues.

---

# 27. Phase H handoff

```text
Step34 — wall thickness / Revit
  ActualDelta MODIFY(PROPERTIES)
  + independent semantic thickness verification

Step35 — wall thickness / AutoCAD
  same canonical verification path
  zero Host branches in Core

Step36 — OFFSET CREATE scope case
  CreationRule operation/kind/source/derivation/count
  including SCOPE_BREACH

Step37 — cross-host SnapshotSet/Saga failure injection
  Slice A success
  Slice B failure
  → PARTIALLY_COMMITTED
  → remaining BLOCKED
  → auditable Compensating ChangeSet workflow
```

Step33 closes Phase G from immutable intent/authorization to observed side effects, independent verification, and auditable partial-failure recovery.

---

# 28. Frozen design decisions

1. Step33 consumes provider-neutral `ActualDelta`; it does not compare raw HostDelta directly with semantic approval scope.
2. `ScopeComparator` and `SemanticVerifier` are separate: unauthorized side effects are `SCOPE_BREACH`; incorrect in-scope outcomes are `VERIFY_FAILED`.
3. Verification uses snapshot-bound `VerificationEvidenceBundle`; Step33 does not directly query D5 internal storage or Semantic Provider implementations.
4. Machine-unexecutable or insufficient verification evidence cannot produce PASS.
5. v0.6 cross-host Saga uses one deterministic global sequential Slice order, including independent roots.
6. A committed `SCOPE_BREACH` or `VERIFY_FAILED` puts the Saga in `PARTIALLY_COMMITTED` and blocks remaining Slices.
7. Scope comparison precedes semantic verification; a scope breach is never overridden by verifier output.
8. Compensation is provider-neutral recovery intent and must re-enter the normal ChangeSet → Approval → Grant write path.
9. Original execution authority does not automatically authorize compensation.
10. `COMPENSATED` is distinct from `SUCCEEDED`.
11. Step33 recovery is durable/CAS-based with explicit timestamps and no domain wall-clock reads.
12. Existing Step28–32 semantic hash algorithms remain unchanged.
13. Step30 gains only public `validate_execution_plan_integrity()` for Saga creation.
14. CREATE evidence binds canonical operation and stable created-instance identity so CreationRule allocation is deterministic and auditable.

---

# 29. Implemented contract refinements and verification evidence

This section incorporates the Step33-only contract refinements that were discovered while decomposing and executing the implementation plan. It is normative together with the rest of this design and supersedes any narrower contract sketch in §§6, 8, 9, 12, and 21 where they differ. These refinements do not change any existing Step28, Step29, Step30, Step31, or Step32 semantic hash identity.

## 29.1 Creation source canonical-kind evidence

`ActualChange` additionally carries:

```text
source_canonical_kind?
```

Step33 evaluates a Step28 `CreationRule.source_selector` only from provider-neutral `ActualChange` evidence:

```text
PredicateField.SEMANTIC_ID      -> ActualChange.source_semantic_id
PredicateField.CANONICAL_KIND   -> ActualChange.source_canonical_kind
PredicateField.SOURCE_ENTITY    -> ActualChange.source_semantic_id
PredicateField.DERIVATION_RULE  -> ActualChange.derivation_rule
```

Missing evidence makes that predicate non-matching. Step33 MUST NOT backfill source-selector evidence from Host-native type/category/layer metadata or by querying D5 internals.

## 29.2 Baseline evidence for DELTA_EQUALS_ARGUMENT

`VerificationEvidenceBundle` additionally carries:

```text
baseline_snapshot_ref?
baseline_projection_ref?
baseline_subject_evidence[]
```

`VerificationSubjectEvidence` additionally carries:

```text
snapshot_id
snapshot_hash
```

When any requested executable verification assertion uses `DELTA_EQUALS_ARGUMENT`:

```text
baseline snapshot/evidence required
→ baseline snapshot identity == CanonicalChangeSet.planning_snapshot_ref
→ baseline and post evidence share the exact SemanticEnvironment
→ required baseline subject/path must be present
otherwise EVIDENCE_INSUFFICIENT / REQUIRED_BASELINE_MISSING
```

The evidence-bundle hash includes baseline snapshot/projection references and baseline subject evidence when present. Step33 performs no unit conversion; canonical operation arguments and semantic evidence must already use canonical semantic units. If a tolerance unit is supplied, explicit observed/expected units must agree or evidence is insufficient.

## 29.3 SemanticVerifier exact joins

The implemented request contract is:

```text
SemanticVerificationRequest {
  admitted_execution_authority
  approval_scope_boundary
  canonical_changeset
  actual_delta
  validation_tasks[]
  verification_evidence_bundle
  verified_at
}
```

Step33 calls public Step29 `validate_changeset_integrity(changeset, boundary)` rather than reimplementing ChangeSet integrity. Post-execution revision verification joins to the authoritative `ActualDelta`, not merely a caller-supplied delta hash. Boundary, ChangeSet, authority, ActualDelta, Slice, evidence bundle, and SemanticEnvironment MUST join exactly before assertion evaluation.

## 29.4 Complete ValidationTask-to-Slice assignment

Step29 `ValidationTask`s are ChangeSet-scoped while Step30 has no task-to-Slice field. Step33 therefore derives immutable task ownership during Saga definition construction:

```text
SliceValidationAssignment {
  execution_slice_hash
  validation_task_ids[]
}

ExecutionSagaDefinition {
  ...
  slice_validation_assignments[]
  saga_definition_hash
}
```

Assignment is deterministic and complete:

```text
CANONICAL_OPERATION task
→ resolve exactly one ChangeSet operation by
  canonical_operation_ref + exact subject_semantic_ids
→ assign to the Slice containing that operation's ExecutionUnit

DEPENDENCY_VERIFICATION task
→ resolve exactly one SemanticImpactEvidence by
  dependency_ref + affected subject
→ if affected semantic id is the target of exactly one ChangeSet operation,
  assign to that operation's Slice
→ otherwise assign to the Slice containing the source_semantic_id operation
→ ambiguous or unresolved assignment = SAGA_INTEGRITY_INVALID
```

Every ChangeSet `ValidationTask` MUST be assigned exactly once. `slice_validation_assignments` are included in `saga_definition_hash` with canonical sorting.

A Slice may enter `SUCCEEDED` only after:

```text
persisted ScopeComparisonResult == WITHIN_SCOPE
+
persisted SemanticVerificationResult covers exactly every ValidationTask
assigned to that Slice by the Saga definition
+
verification aggregate == PASSED
```

Caller omission of an assigned task is invalid and cannot produce Slice success.

## 29.5 Fresh implementation verification

Implementation proof before this status update:

```text
implementation SHA: 78476f6dfa9d8b99d96be142138b576fe50d2dfa
GitHub Actions run: 33325648436
result: completed / success
```

The fresh final-verification session in that exact run executed together:

```bash
pytest -q tests/approval_scope
pytest -q tests/changeset
pytest -q tests/execution_planning
pytest -q tests/provider_binding
pytest -q tests/gateway_authorization
pytest -q tests/execution_reconciliation
ruff check \
  platform/execution_planning/src/design_execution_planning \
  platform/execution_reconciliation/src/design_execution_reconciliation \
  tests/execution_planning tests/execution_reconciliation
pytest -q --import-mode=importlib
git diff --check
git diff --check cef76e111f74d10f063eedfebc7efc0d805caefa...HEAD
git diff --name-only cef76e111f74d10f063eedfebc7efc0d805caefa...HEAD
```

The workflow also applied the frozen-path gate to the committed base-to-HEAD path list. All steps in run `33325648436`, including `Run fresh Step33 final verification session`, completed successfully. The design-status commit created by this section still requires the separate Task12.8 exact-HEAD Actions proof before Step33 is merge-ready.
