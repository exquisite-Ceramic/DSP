# Step33 — Execution Reconciliation / ScopeComparator / Saga Design

> Status: Design approved in chat; written-spec review pending  
> Date: 2026-08-30  
> Base: `main@cef76e111f74d10f063eedfebc7efc0d805caefa`  
> Branch: `feat/step33-execution-reconciliation`  
> Master spec: `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`  
> Phase: G / Step33 — Verify / ScopeComparator / Saga

---

## 1. Purpose

Step33 closes the execution loop after Step32 has admitted an `ExecutionGrant` and a Host mutation has occurred. It must answer three independent questions without collapsing their responsibilities:

```text
ScopeComparator
= Did the Host actually modify only what the approval allowed?

SemanticVerifier
= Given that the side effects stayed inside scope, is the resulting design semantically correct?

ExecutionSaga
= Given the durable side effects and verification outcomes so far, may the workflow continue, or must it stop and recover?
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
- redefine Step29 ChangeSet semantics or hash algorithms;
- redefine Step30 Slice / Unit semantics or existing hash algorithms;
- redefine Step31 ProviderBinding semantics;
- bypass normal approval for compensation;
- implement XA/2PC;
- hide recovery through native `UNDO`, transaction rollback, or equivalent Host-specific escape hatches.

---

## 3. Upstream ownership and fixed handoff

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

Step33 introduces one top-level provider-neutral subsystem:

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
- `hashing.py`: Step33-only canonical semantic hashes.
- `scope_comparator.py`: deterministic `ActualDelta` vs `ApprovalScopeBoundary` evaluation.
- `verifier.py`: deterministic `ValidationTask` evaluation over snapshot-bound semantic evidence.
- `saga.py`: deterministic state-transition rules and next-action eligibility.
- `store.py`: durable atomicity/CAS/idempotent-recovery semantics for Saga state.
- `service.py`: validates cross-step joins and coordinates the pure Step33 domain operations.

Step33 Core MAY depend only on stable public contracts/validators from Step28–32 and stable semantic snapshot/environment contracts. It MUST NOT read D5 internal projection storage.

---

## 5. Targeted Step30 enhancement

Step33 needs to prove that a Saga binds the complete, intact Step30 `ExecutionPlan`, not an arbitrary caller-supplied Slice list. Therefore Step30 SHALL add one public integrity API:

```python
validate_execution_plan_integrity(execution_plan)
```

The validator SHALL:

- validate every `ExecutionSlice` using existing Step30 semantics;
- validate dependency references and plan membership;
- recompute the existing execution-plan semantic body and existing `execution_plan_hash`;
- fail closed if the stored plan/hash does not match.

This enhancement MUST NOT change the Step30 `ExecutionPlan` contract or any existing Step30 hash algorithm.

No Step28, Step29, Step31, or Step32 production contract change is required by this design.

---

# 6. Provider-neutral ActualDelta

## 6.1 Why `HostDelta` is not the Step33 comparison contract

Existing Host `HostDelta` is a Host-local change stream over `document_id + native_id` and revisions. That is necessary provenance, but it cannot directly prove semantic scope membership because Step28 scope rules operate over `SemanticId`, canonical kinds, canonical aspects, creation derivation, and deletion authority.

Step33 therefore consumes a normalized, provider-neutral `ActualDelta` assembled at the Host/Execution → reconciliation boundary.

## 6.2 Contract

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

Each change is:

```text
ActualChange {
  change_kind: CREATE | MODIFY | DELETE

  semantic_id?
  canonical_kind?
  changed_aspects[]

  source_semantic_id?
  derivation_rule?

  host_entity_ref?   # provenance only
}
```

## 6.3 Required semantics

- `MODIFY` MUST carry `semantic_id` and at least one canonical `changed_aspect`.
- `DELETE` MUST carry `semantic_id`.
- `CREATE` MAY lack a stable post-create `semantic_id` at normalization time, but MUST carry enough canonical evidence to evaluate the applicable Step28 `CreationRule`; where required by the rule, this includes `canonical_kind`, `source_semantic_id`, and `derivation_rule`.
- `changed_aspects` MUST use the Step28 canonical aspect vocabulary.
- `host_entity_ref` is provenance only. `ScopeComparator` MUST NOT make authorization decisions from native ids, native types, Host products, layer names, categories, or provider metadata.
- The full Step32 lineage in `ActualDelta` MUST exactly match the admitted authority before scope comparison begins.
- `revision_after` MUST represent the Host read-back revision containing the side effects. Revision regressions are invalid.

The normalized `ActualDelta` is the authoritative statement of actual Host side effects for reconciliation. D5 reconstruction verifies semantic outcome; it does not replace or overwrite `ActualDelta`.

---

## 7. ActualDelta semantic identity

`actual_delta_hash` SHALL be:

```text
H({
  grant_hash,
  binding_set_hash,
  execution_slice_hash,
  changeset_hash,
  approved_scope_hash,
  host_instance_id,
  document_ref,
  revision_before,
  revision_after,
  canonicalized_changes
})
```

The hash MUST exclude:

- `actual_delta_id`;
- observation/receipt timestamps;
- `actual_delta_hash` itself.

Re-reading the same committed revision with the same normalized side effects MUST produce the same semantic `actual_delta_hash` even after response loss/retry.

---

# 8. ScopeComparator

## 8.1 Responsibility

`ScopeComparator` answers exactly one question:

> Is every normalized actual Host side effect authorized by the exact Step28 boundary and the exact Step30 Slice scope?

It does not decide whether the final design result is correct.

## 8.2 Input

```text
ScopeComparisonRequest {
  admitted_execution_authority
  actual_delta
  approval_scope_boundary
  execution_slice
}
```

## 8.3 Deterministic validation order

The comparator SHALL execute in this order:

1. type/contract integrity;
2. exact Step32 authority lineage joins;
3. Step28 boundary integrity;
4. Step30 Slice integrity;
5. Host/document/revision consistency;
6. resolve the exact `ExecutionSliceScopeRule` referenced by the Slice;
7. evaluate `MODIFY` changes;
8. evaluate `DELETE` changes;
9. evaluate `CREATE` changes including count allocation;
10. produce an immutable, hashed comparison result.

No later rule is allowed to repair an earlier mismatch.

## 8.4 MODIFY

For every `MODIFY`:

- `semantic_id` MUST be matched by an allowed `ExistingEntityRule` available to the Slice;
- every changed canonical aspect MUST be contained in the union of authorized aspects for that entity under the Slice scope;
- an unmatched entity or unauthorized aspect is a scope violation.

## 8.5 DELETE

For every `DELETE`:

- `semantic_id` MUST match a `DeletionRule` available to the Slice;
- absence of an applicable deletion rule is a scope violation.

## 8.6 CREATE

For every `CREATE`, authorization MUST be proven from the Step28 `CreationRule` semantics, including as applicable:

- canonical operation;
- source selector;
- canonical entity kind;
- required derivation;
- `max_count`.

A create is not authorized merely because its canonical kind is generally known or because the provider reported success.

### 8.6.1 Deterministic overlapping-rule allocation

If actual creates can match more than one `CreationRule`, the comparator SHALL treat create-to-rule assignment as a deterministic allocation problem.

An allocation is valid only when every create is assigned to an eligible rule and each rule's assigned count is `<= max_count` when a maximum exists.

If multiple valid allocations exist, the comparator SHALL choose the canonical allocation ordered by stable `rule_id` and stable normalized change identity. Python/container iteration order MUST NOT affect the result.

No valid allocation means `SCOPE_BREACH`.

## 8.7 Output

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

Violation details SHALL use stable machine codes, including at minimum:

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

The outer machine condition remains `SCOPE_BREACH`; detail codes are for audit/recovery planning and do not replace it.

A `SCOPE_BREACH` MUST block remaining not-yet-admitted Saga slices.

---

# 9. VerificationEvidenceBundle

## 9.1 Problem

Step29 stores `ValidationTask.contract_ref`, a content-addressed verification semantic reference, but intentionally does not embed all verification contract bodies in the ChangeSet. Likewise, D5 `SemanticSnapshot` binds projection/environment/freshness/coverage/assurance but does not serve as an inline entity-value dump.

Step33 therefore consumes a snapshot-bound, provider-neutral evidence bundle assembled by the Semantic/D5 integration layer.

## 9.2 Contract

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

Contract evidence:

```text
VerificationContractEvidence {
  contract_ref
  contract_body
}
```

Subject evidence is a task-scoped read model:

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

The integration layer SHOULD include only the subject × aspect × field evidence required by the ValidationTasks. It MUST NOT require a full IFC/Metro mirror.

## 9.3 Integrity rules

For every referenced verification contract:

```text
H(contract_body) == ValidationTask.contract_ref
```

The evidence bundle's SemanticEnvironment MUST exactly match the ChangeSet/approval planning environment. Snapshot/projection references MUST prove the post-execution Host revision being verified.

Missing evidence is not success.

---

# 10. SemanticVerifier

## 10.1 Responsibility

`SemanticVerifier` evaluates the exact Step29 `ValidationTask` semantics over the exact snapshot-bound evidence bundle. It does not decide execution order or Saga continuation.

Host self-reported verification fields may be retained as diagnostics/provenance but MUST NOT directly produce a platform verification PASS.

## 10.2 Input

```text
SemanticVerificationRequest {
  admitted_execution_authority
  canonical_changeset
  validation_tasks[]
  verification_evidence_bundle
  verified_at
}
```

`validation_tasks[]` MUST be an exact subset of `canonical_changeset.validation_tasks`. The caller may not invent new tasks.

## 10.3 Validation order

The verifier SHALL execute in this order:

1. request/type integrity;
2. authority lineage exact joins;
3. Step29 ChangeSet integrity;
4. evidence-bundle integrity/hash;
5. SemanticEnvironment exact match;
6. post-execution snapshot/projection/revision lineage;
7. `ValidationTask.contract_ref` ↔ contract evidence matching;
8. `H(contract_body) == contract_ref`;
9. subject-evidence completeness;
10. deterministic contract evaluation;
11. deterministic aggregate result.

## 10.4 Result model

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

Per task:

```text
ValidationTaskResult {
  validation_task_id
  status: PASSED | FAILED | EVIDENCE_INSUFFICIENT
  observations[]
  failure_codes[]
  task_result_hash
}
```

Aggregate rules are fixed:

```text
all task results PASSED
→ PASSED

any task result FAILED
→ FAILED

no FAILED but any EVIDENCE_INSUFFICIENT
→ EVIDENCE_INSUFFICIENT
```

Execution-loop mapping:

```text
PASSED
→ verification passes

FAILED
→ VERIFY_FAILED

EVIDENCE_INSUFFICIENT
→ VERIFY_FAILED
  detail = VERIFY_EVIDENCE_INSUFFICIENT
```

Therefore the platform distinguishes "proved wrong" from "could not sufficiently prove correct", but both fail closed for a production write.

---

## 11. Declarative verification contract

Step33 SHALL support a provider-neutral declarative contract type:

```text
SEMANTIC_ASSERTIONS_V1
```

The contract describes semantic assertions as data rather than Host or operation-specific Python branches. Example shape:

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

Step33 Core MAY support a small fixed operator vocabulary, initially including:

```text
EXISTS
NOT_EXISTS
EQUALS_LITERAL
EQUALS_ARGUMENT
DELTA_EQUALS_ARGUMENT
RELATIONSHIP_EXISTS
CLASSIFICATION_IS
```

The evaluator MUST NOT contain branches such as:

```text
if host == "REVIT": ...
if operation == "set_revit_wall_thickness": ...
```

Legacy/weak contracts such as `{"type":"HOST_READ_BACK"}` do not prove semantic correctness by themselves. If a ValidationTask requires semantic proof and its contract cannot be executed deterministically, the result MUST be `EVIDENCE_INSUFFICIENT` with detail `VERIFY_CONTRACT_UNSUPPORTED`.

Published canonical-operation verification semantics MUST NOT be silently strengthened in place if that would change the existing contract fingerprint. Such semantic change requires an appropriate versioned contract/operation evolution.

---

## 12. Verification examples

### 12.1 Inside scope but wrong value

Intent/bound operation:

```text
set_thickness.v1
WALL-001
thickness = 300 mm
```

Actual Host side effect:

```text
WALL-001
MODIFY
changed_aspects = [PROPERTIES]
```

If Step28 authorizes `WALL-001 / PROPERTIES`, ScopeComparator returns:

```text
WITHIN_SCOPE
```

If post-execution evidence is:

```text
WALL-001.properties.thickness = 350 mm
```

SemanticVerifier returns:

```text
FAILED
failure detail = EXPECTED_VALUE_MISMATCH
```

The Slice outcome is `VERIFY_FAILED`, not `SCOPE_BREACH`.

### 12.2 Missing semantic evidence

If the read-back reconstruction proves only `IDENTITY` and `CLASSIFICATION` but the task requires `PROPERTIES.thickness`, the task result is:

```text
EVIDENCE_INSUFFICIENT
failure detail = REQUIRED_FIELD_MISSING
```

The production execution loop maps this to `VERIFY_FAILED`.

---

# 13. Execution Saga

## 13.1 Responsibility

Step33 Saga records durable post-admission execution/reconciliation state and enforces deterministic continuation barriers. LangGraph remains the workflow driver; Gateway remains the authorization owner.

Step33 answers:

> Given the durable state of all Slices, is the next requested transition valid?

It does not issue permissions itself.

## 13.2 Immutable definition

```text
ExecutionSagaDefinition {
  saga_id

  changeset_hash
  approved_scope_hash
  semantic_environment_ref
  execution_plan_hash

  ordered_slice_hashes[]
  execution_dependencies[]

  saga_definition_hash
}
```

Saga creation MUST validate:

- Step28 `ApprovalScopeBoundary` integrity;
- Step29 `CanonicalChangeSet` integrity;
- Step30 `ExecutionPlan` integrity;
- exact ChangeSet ↔ Boundary ↔ Plan joins;
- all Saga slice/dependency members equal the Step30 plan members.

The Saga definition is immutable after creation.

## 13.3 Durable lifecycle

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

A Saga may become `SUCCEEDED` only when every required Slice has durably reached `SUCCEEDED` after Host commit, scope comparison PASS, and semantic verification PASS.

---

## 14. Slice reconciliation lifecycle

```text
SliceReconciliationState {
  execution_slice_hash

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

`HOST_COMMITTED` is not success. A committed Slice MUST complete reconciliation before it can become `SUCCEEDED`.

Required outcome mapping:

| Host commit | Scope | Verify | Slice outcome |
|---|---|---|---|
| no | — | — | `FAILED_BEFORE_COMMIT` |
| yes | breach | — | `SCOPE_BREACH` |
| yes | within | failed | `VERIFY_FAILED` |
| yes | within | insufficient | `VERIFY_FAILED` |
| yes | within | passed | `SUCCEEDED` |

---

# 15. Sequential admission barrier for v0.6

v0.6 SHALL default to sequential side-effecting Slice admission.

No next Slice may become admitted until every required predecessor Slice is durably reconciled and `SUCCEEDED`.

```text
previous required predecessor
RECONCILED + SUCCEEDED
        ↓
next Slice may be reserved/admitted
```

This rule makes the master-spec requirement "scope breach stops remaining slices" enforceable: not-yet-started later Slices have not yet produced Host side effects.

Parallel-safe execution groups are explicitly deferred beyond Step33 v0.6 unless a later ADR revises this rule.

---

## 16. Admission reservation and crash recovery

There is an unavoidable cross-subsystem crash window between Step33 deciding a Slice may proceed and Step32 durably admitting its Grant. Therefore Step33 SHALL use a reservation state:

```text
NOT_STARTED
→ ADMISSION_RESERVED     # Step33 durable CAS
→ Step32 admit grant
→ ADMITTED               # Step33 confirmation
```

If the process crashes while the Slice is `ADMISSION_RESERVED`, that state is an explicit recovery point.

Because Step32 already recovers repeated admission of the same already-admitted Grant, the workflow may retry/read Step32 authority and complete the Step33 confirmation without creating a second Host mutation.

Step33 MUST NOT infer `ADMITTED` merely from elapsed time.

---

# 17. Failure transitions

## 17.1 Failure before any commit

If the first Slice fails before Host commit and no earlier Slice committed:

```text
Slice → FAILED_BEFORE_COMMIT
Saga  → FAILED
```

No compensation is required because DSP has no committed Host mutation to undo.

## 17.2 Later pre-commit failure after prior success

```text
Slice A → SUCCEEDED
Slice B → FAILED_BEFORE_COMMIT
```

The Saga MUST enter:

```text
PARTIALLY_COMMITTED
```

All remaining not-yet-admitted Slices MUST atomically become `BLOCKED`.

## 17.3 Verification failure after commit

A committed Slice with `VERIFY_FAILED` has already changed the Host. Therefore the Saga MUST enter `PARTIALLY_COMMITTED` and block remaining Slices; it MUST NOT collapse directly to a simple no-side-effect `FAILED` state.

## 17.4 Scope breach after commit

A committed Slice with `SCOPE_BREACH` MUST enter the same partial/recovery path, block remaining Slices, and preserve the scope violation evidence.

---

# 18. Compensation boundary

Step33 MUST NOT compensate by emitting Host-native rollback commands or by constructing an ungoverned reverse operation.

Step33 produces only a provider-neutral recovery proposal/evidence object:

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

It states what canonical recovery effects are desired based on actual committed evidence. It does not state how Revit/AutoCAD/Tekla should undo the change.

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

The original `ExecutionGrant` MUST NOT automatically authorize compensation.

Enterprise policy MAY automatically approve a class of low-risk compensating ChangeSets, but that is a Gateway policy decision, not Saga self-authorization.

---

## 19. Compensation terminal semantics

Original Saga outcomes remain truthful:

```text
original business intent fully completed
→ SUCCEEDED

original business intent failed,
known committed side effects successfully compensated
→ COMPENSATED

compensation also failed
→ COMPENSATION_FAILED
```

`COMPENSATED` MUST NOT be rewritten as `SUCCEEDED`.

`COMPENSATION_FAILED` is terminal for automatic Step33 recovery in v0.6 and requires HITL/manual recovery or a separately authorized recovery workflow. Step33 MUST NOT enter an unbounded automatic compensation loop.

---

# 20. Store atomicity, CAS, and replay

The Step33 Store owns:

- atomic Saga creation/uniqueness;
- `saga_revision` CAS;
- per-Slice transition serialization;
- sequential admission reservation;
- atomic blocking of remaining Slices on partial failure;
- immutable evidence refs for committed transitions;
- compensation lifecycle transitions;
- idempotent same-evidence recovery;
- conflict detection for different evidence.

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

Every mutating operation SHALL require an expected `saga_revision` or an equivalent atomic lineage precondition.

Rules:

- same logical transition + same evidence hash replay → return/recover the already committed logical result;
- same logical transition + different evidence → `SAGA_CONFLICT`;
- stale `saga_revision` → conflict;
- terminal Saga states reject unrelated new execution transitions.

The Store owns atomicity; the service owns deterministic validation and stable domain-error mapping.

---

# 21. Time model

Step33 domain logic MUST NOT read the wall clock.

All timestamps are explicit inputs/evidence, including as applicable:

```text
reserved_at
admitted_at
committed_at
reconciled_at
verified_at
compensation_started_at
compensation_completed_at
```

Audit timestamps do not silently change semantic evidence identity unless explicitly included in a defined Step33 hash.

---

# 22. Step33 hashes

Step33 adds new hashes only. It MUST NOT modify Step28–32 existing semantic hashes.

## 22.1 Scope comparison

Conceptually:

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

## 22.2 Verification evidence

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

## 22.3 Verification result

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

## 22.4 Saga definition

```text
saga_definition_hash = H({
  changeset_hash,
  approved_scope_hash,
  semantic_environment_ref,
  execution_plan_hash,
  ordered_slice_hashes,
  execution_dependencies
})
```

Mutable Saga lifecycle state is not folded back into `saga_definition_hash`.

---

# 23. Stable Step33 errors

Top-level Step33 machine errors SHALL include:

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

Violation/task detail codes such as `ENTITY_OUTSIDE_SCOPE`, `CREATION_COUNT_EXCEEDED`, `EXPECTED_VALUE_MISMATCH`, and `REQUIRED_FIELD_MISSING` are structured detail. Natural-language messages MUST NOT drive retry/replan/compensation decisions.

---

# 24. Service facade

The provider-neutral facade is tentatively:

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

`reconcile_slice(...)` MAY be a convenience facade over already-created immutable scope/verification evidence, but it MUST NOT hide external Host execution, D5 reconstruction, or Semantic Service lookups inside the pure domain transaction.

---

# 25. Architecture guardrails

The Step33 package MUST fail architecture tests if production code introduces:

- Host product names/branches (`AutoCAD`, `Revit`, `Tekla`, etc.);
- Host-native command/transaction APIs;
- provider-specific verification paths;
- direct D5 internal projection-storage imports;
- hidden native rollback/undo logic;
- XA/2PC transaction managers;
- direct DB-vendor APIs in domain service code;
- `datetime.now`, `datetime.utcnow`, `time.time`, or equivalent wall-clock reads;
- private Step28–32 implementation/hash imports where a public validator/contract exists.

Step33 MUST use public integrity validators from Step28–30 and the frozen public contracts of Step31–32.

---

# 26. Test matrix / Definition of Done

Step33 is not complete until fresh CI on the exact final branch HEAD proves at least the following.

## 26.1 ActualDelta

- deterministic semantic hash;
- same committed revision + same normalized side effects re-hash identically;
- bad lineage fails before comparison;
- revision regression fails closed;
- Host-native provenance cannot change authorization outcome.

## 26.2 ScopeComparator

- MODIFY allowed entity/aspect passes;
- MODIFY unauthorized aspect returns `SCOPE_BREACH`;
- DELETE without deletion authority returns `SCOPE_BREACH`;
- CREATE inside kind/source/derivation/count passes;
- CREATE wrong kind fails;
- CREATE wrong source fails;
- CREATE derivation mismatch fails;
- CREATE over `max_count` fails;
- overlapping CreationRules produce deterministic canonical allocation;
- implicit Host associativity side effects must be represented in ActualDelta and are evaluated, not ignored.

## 26.3 SemanticVerifier

- contract body hash must equal `ValidationTask.contract_ref`;
- SemanticEnvironment drift fails closed;
- snapshot/revision mismatch fails closed;
- semantic assertion pass → `PASSED`;
- expected-value mismatch → `FAILED` / `VERIFY_FAILED`;
- missing required subject/field/aspect → `EVIDENCE_INSUFFICIENT` / `VERIFY_FAILED`;
- unsupported weak contract cannot produce PASS;
- Host self-reported verification success cannot bypass independent evidence evaluation.

## 26.4 Saga

- first Slice pre-commit failure with no commits → `FAILED`;
- A success + B pre-commit failure → `PARTIALLY_COMMITTED`;
- committed `VERIFY_FAILED` → `PARTIALLY_COMMITTED`;
- committed `SCOPE_BREACH` → `PARTIALLY_COMMITTED`;
- partial failure atomically blocks remaining Slices;
- no next Slice reservation before all required predecessors are `SUCCEEDED`;
- concurrent reservation attempts permit only the valid single sequential winner;
- reserve → Step32 admit crash window is recoverable through `ADMISSION_RESERVED`;
- same transition/evidence replay is idempotent recovery;
- same transition/different evidence conflicts;
- all required Slices reconciled `SUCCEEDED` → Saga `SUCCEEDED`;
- compensated original Saga ends `COMPENSATED`, never `SUCCEEDED`;
- compensation failure ends `COMPENSATION_FAILED`.

## 26.5 Cross-step regressions

Fresh CI MUST run Step28, Step29, Step30, Step31, Step32 regression suites plus full-repository tests and the Step33 architecture/lint matrix.

The frozen master-spec acceptance behaviors covered by Step33 include:

```text
ActualDelta outside scope stops remaining slices
second cross-host Slice failure enters Saga/partial state
cross-host Saga preserves auditable partial/compensation state
```

---

# 27. Frozen implementation boundary

The Step33 implementation branch may modify only:

```text
platform/execution_reconciliation/**
tests/execution_reconciliation/**

platform/execution_planning/**
tests/execution_planning/**
  # only the targeted ExecutionPlan integrity validator and its tests

docs/superpowers/specs/**
docs/superpowers/plans/**

.github/workflows/step33-execution-reconciliation.yml
pyproject.toml
```

The Step33 implementation MUST NOT modify, absent a newly approved blocker:

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

A newly discovered blocker that requires crossing this boundary MUST be surfaced and explicitly re-approved before implementation continues.

---

# 28. Phase H handoff

A completed Step33 provides the execution/reconciliation substrate for:

```text
Step34 — wall thickness / Revit
  ActualDelta MODIFY(PROPERTIES)
  + independent semantic thickness verification

Step35 — wall thickness / AutoCAD
  same canonical verification path
  zero Host branches in Core

Step36 — OFFSET CREATE scope case
  CreationRule kind/source/derivation/count
  including SCOPE_BREACH behavior

Step37 — cross-host SnapshotSet/Saga failure injection
  Slice A success
  Slice B failure
  → PARTIALLY_COMMITTED
  → remaining BLOCKED
  → auditable Compensating ChangeSet workflow
```

Step33 therefore closes Phase G from immutable intent and authorization to observed side effects, independent verification, and auditable partial-failure recovery.

---

# 29. Frozen design decisions

The following decisions are approved and normative for this design:

1. Step33 consumes a provider-neutral `ActualDelta`; it does not compare raw HostDelta directly to semantic approval scope.
2. `ScopeComparator` and `SemanticVerifier` are separate: unauthorized side effects are `SCOPE_BREACH`; incorrect in-scope outcomes are `VERIFY_FAILED`.
3. Verification uses a snapshot-bound `VerificationEvidenceBundle`; Step33 does not directly query D5 internal storage or Semantic Provider implementations.
4. Machine-unexecutable or insufficient verification evidence cannot produce PASS.
5. v0.6 cross-host Saga defaults to sequential Slice admission.
6. A committed Slice followed by `SCOPE_BREACH` or `VERIFY_FAILED` places the Saga in `PARTIALLY_COMMITTED` and blocks remaining Slices.
7. Compensation is expressed as provider-neutral recovery intent and must re-enter the normal ChangeSet → Approval → Grant write path.
8. Original execution authority does not automatically authorize compensation.
9. `COMPENSATED` is distinct from `SUCCEEDED`.
10. Step33 lifecycle recovery is durable/CAS-based and uses explicit timestamps; domain logic does not read wall clock time.
11. Existing Step28–32 semantic hash algorithms remain unchanged.
12. Step30 gains only a public `validate_execution_plan_integrity()` integrity API required for Saga creation.
