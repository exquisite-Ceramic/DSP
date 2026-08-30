# Step 32 — Gateway Authorization Design

**Status:** Implemented and verified  
**Date:** 2026-08-30  
**Base:** `main@0e567cc786ad88e99337f062c06222190e4c22d2`  
**Branch:** `feat/step32-gateway-authorization`  
**Implementation commit:** `57562db00239f4a747f042609bb73755152da0b4`  
**Verification:** GitHub Actions run `33302605334` — `success`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

Verification commands executed by the successful implementation run:

```bash
pytest -q tests/approval_scope/test_step28_integrity.py
pytest -q tests/changeset/test_step29_integrity.py
pytest -q tests/execution_planning/test_step30_integrity.py
pytest -q tests/gateway_authorization
pytest -q tests/approval_scope
pytest -q tests/changeset
pytest -q tests/execution_planning
pytest -q tests/provider_binding
ruff check \
  platform/approval_scope/src/design_approval_scope \
  platform/changeset/src/design_changeset \
  platform/execution_planning/src/design_execution_planning \
  platform/gateway_authorization/src/design_gateway_authorization \
  tests/approval_scope tests/changeset tests/execution_planning tests/gateway_authorization
pytest -q --import-mode=importlib
```

## 1. Purpose

Step32 introduces the authoritative Gateway authorization boundary between immutable planning/binding evidence and Host mutation.

It answers two separate questions:

```text
Approval side:
Given one already-verified, one-time ApprovalAdmission,
this exact immutable CanonicalChangeSet,
and this exact ApprovalScopeBoundary,
what durable ApprovalRecord is authorized and persisted?
```

and:

```text
Execution side:
Given one authoritative ApprovalRecord,
this exact ExecutionSlice,
and this exact ProviderBindingSet,
what single execution authority may be issued and admitted for this logical Slice execution?
```

Step32 does **not** decide canonical intent, semantic applicability, impact, approval effect scope, ChangeSet semantics, execution partitioning, provider selection, Host command translation, ActualDelta reconciliation, verification, rollback, or Saga compensation.

The frozen flow is:

```text
verified ApprovalAdmission
        +
Step29 CanonicalChangeSet
        +
Step28 ApprovalScopeBoundary
        ↓
Step32 deterministic approval validation
        ↓
atomic consume + durable ApprovalRecord
        ↓
approval_hash
        ↓
Step30 ExecutionSlice
        +
Step31 ProviderBindingSet
        ↓
Step32 deterministic grant validation
        ↓
GrantLineage lock
        ↓
ExecutionGrant
        ↓
CAS ACTIVE → ADMITTED
        ↓
AdmittedExecutionAuthority
        ↓
Provider / Host mutation
        ↓
Step33 Verify / ScopeComparator / Saga
```

Central invariants:

> One `admission_id` produces at most one `ApprovalRecord`.

> One `(approval_hash, execution_slice_hash)` lineage has at most one ACTIVE execution authority.

> One `ExecutionGrant` represents at most one logical Slice execution.

> An ADMITTED Slice cannot silently rebind to another ProviderBindingSet and execute again.

---

## 2. Master-spec alignment

The master spec freezes `ApprovalRecord / ExecutionGrant` as Gateway-owned authorization evidence and places Step32 after Provider Binding and before Host execution.

Relevant semantic requirements are:

```text
Preview / Approval / Execute
must bind the same ChangeSet hash and approved scope.

ApprovalRecord
must bind SemanticEnvironment.

ProviderBindingSet changes
must change binding_set_hash
and invalidate the old ExecutionGrant.

MODEL_OPERATION
must not execute without Gateway authorization,
ApprovalRecord, and ExecutionGrant.
```

Step32 therefore owns:

```text
approval admission consumption
approval authorization evidence
execution-grant issuance
approval/grant lifecycle authorization state
atomic authorization state
structured authorization failures
```

Step32 does not become the owner of upstream semantic hashing. Integrity remains owned by the step that defines each immutable semantic object.

---

## 3. Scope and non-goals

### 3.1 In scope

- immutable Step32 contracts;
- stable Step32 hashing;
- `GatewayAuthorizationStore` provider-neutral atomic semantics;
- `GatewayAuthorizationService` deterministic validation and joins;
- strict one-time approval-admission consumption;
- idempotent grant get-or-create;
- Slice-scoped grant lineage locking;
- CAS admission;
- grant/approval revocation semantics;
- derived expiry projection;
- targeted public integrity APIs in Steps 28–30;
- exact use of Step31 `validate_provider_binding_set()`;
- Step33 authorization handoff evidence;
- focused CI, concurrency tests, and architecture guards.

### 3.2 Out of scope

Step32 MUST NOT:

```text
change Canonical Action semantics
change ApprovalScope semantics
change ChangeSet hash semantics
split or merge ExecutionUnits/Slices
choose providers
change ProviderBinding hash semantics
translate HostCommand
perform Host mutation
produce ActualDelta
verify success
perform hidden rollback
implement Saga compensation
implement database-vendor-specific persistence in domain service
read wall-clock time inside deterministic validation
```

---

## 4. Validation ownership and targeted upstream integrity enhancement

Step32 MUST NOT copy the hash-body construction of Steps 28–31.

Frozen ownership:

```text
Step28 owns ApprovalScopeBoundary integrity
Step29 owns CanonicalChangeSet integrity
Step30 owns ExecutionUnit / ExecutionSlice integrity
Step31 owns ProviderBindingSet integrity
Step32 consumes those public validators
```

Current Step28 and Step29 DTOs do not retain enough witness material for a complete self-integrity check. Step32 therefore requires narrowly scoped upstream enhancements that preserve existing semantic hash algorithms and existing hash values.

### 4.1 Step28: self-validating final ApprovalScopeBoundary

The final boundary carries forward the Step28 commitment inputs already included in `scope_body_hash`:

```text
ApprovalScopeBoundary {
  scope_id

  scope_definition_id
  impact_analysis_fingerprint
  canonical_effect_evidence
  intent_boundary
  planning_snapshot_ref
  snapshot_set_ref
  semantic_environment_ref

  changeset_hash
  scope_body_hash

  existing_entity_rules[]
  creation_rules[]
  deletion_rules[]
  propagation_bundle_ids[]
  execution_slice_scopes[]

  scope_hash
}
```

Step28 exports:

```text
validate_approval_scope_boundary(boundary)
```

Validation:

```text
recompute exact existing Step28 scope_body_hash
↓
compare boundary.scope_body_hash
↓
recompute exact existing H(scope_body_hash + changeset_hash)
↓
compare boundary.scope_hash
```

This is witness retention only. The existing Step28 hash definition is unchanged.

### 4.2 Step29: full ChangeSet integrity with exact Step28 boundary

Step29 exports:

```text
validate_changeset_integrity(
  changeset,
  approval_scope_boundary,
)
```

A single-argument validator is insufficient because the current operation semantic hash uses scope-rule fingerprints while `CanonicalChangeOperation` retains scope-rule ids.

The validator resolves each operation's exact `scope_rule_ids` against the supplied validated Boundary and uses Step29's existing `compute_scope_rule_fingerprint()` and semantic hashing functions to reconstruct:

```text
root operation hash
derived operation hashes
change dependency semantic payloads
preconditions
affected entities
semantic impacts
validation tasks
full ChangeSet semantic body
changeset_hash
```

Step32 never assembles this body itself.

### 4.3 Step30: public Unit/Slice integrity validator

Step30 exports:

```text
validate_execution_slice_integrity(execution_slice)
```

It must:

```text
recompute every ExecutionUnit.execution_unit_hash
↓
compare every Unit hash
↓
recompute ExecutionSlice.execution_slice_hash
↓
compare Slice hash
```

Validating only the Slice hash is insufficient because the Slice hash references Unit hashes, not every Unit body field directly.

### 4.4 Step31: use existing public validator

Step32 calls exactly:

```text
validate_provider_binding_set(
  provider_binding_set,
  execution_slice,
)
```

No Step31 hashing or provider-binding validation is copied into Step32.

---

## 5. ApprovalAdmission boundary

`ApprovalAdmission` is already-authenticated and already-policy-evaluated Gateway evidence. Step32 consumes it; Step32 does not create the user approval decision.

The Step32 boundary contract is:

```text
ApprovalAdmission {
  admission_id

  changeset_hash
  approved_scope_hash

  semantic_environment_ref
  approver
  policy_snapshot_hash
  policy_allowed_operations[]

  approved_at
  expires_at

  admission_fingerprint
}
```

`admission_fingerprint` commits all authoritative admission content except `admission_id` itself:

```text
admission_fingerprint = H({
  changeset_hash,
  approved_scope_hash,
  semantic_environment_ref,
  approver,
  policy_snapshot_hash,
  sorted(policy_allowed_operations),
  approved_at,
  expires_at
})
```

Step32 owns the canonical helper that computes/validates this fingerprint. The one-time `admission_id` is a store identity; the fingerprint is the immutable authority-content identity used for replay/conflict detection.

`approved_at` is the approval fact time. `expires_at` is the admission validity deadline. Both are immutable authorization evidence.

---

## 6. Approval consumption contract

Input:

```text
ApprovalConsumptionRequest {
  admission
  canonical_changeset
  approval_scope_boundary
  consumed_at
}
```

`consumed_at` is explicit UTC input. It is both the deterministic admission-expiry evaluation time and the Gateway consumption audit time. It MUST NOT overwrite or reinterpret `approved_at`.

The validation order is fixed:

```text
contract/type validation
↓
admission fingerprint integrity
↓
admission expiry at consumed_at
↓
Step28 ApprovalScopeBoundary integrity
↓
Step29 CanonicalChangeSet integrity
↓
admission ↔ ChangeSet ↔ scope exact join
↓
SemanticEnvironment exact match
↓
canonical-operation least-privilege check
↓
compute ApprovalRecord + approval_hash
↓
atomic consume + persist
```

Admission is valid only when:

```text
consumed_at < admission.expires_at
```

Validation order is normative because stable error classification and audit behavior must not depend on incidental implementation order.

---

## 7. Approval exact join

Step32 MUST require:

```text
admission.changeset_hash
== changeset.changeset_hash
== boundary.changeset_hash
```

and:

```text
changeset.approval_scope_definition_ref.scope_body_hash
== boundary.scope_body_hash
```

and:

```text
admission.approved_scope_hash
== boundary.scope_hash
```

Semantic environment must be an exact value match:

```text
admission.semantic_environment_ref
== changeset.semantic_environment_ref
== boundary.semantic_environment_ref
```

No id-based guessing, fallback, normalization, or automatic repair is allowed.

Canonical operations are:

```text
changeset_operations = {
  changeset.root_operation.canonical_operation,
  changeset.derived_operations[*].canonical_operation
}
```

They must satisfy:

```text
changeset_operations
⊆ admission.policy_allowed_operations
```

The durable least-privilege set is:

```text
ApprovalRecord.allowed_operations
= changeset_operations
```

The broader policy allowance is not persisted as execution authority.

---

## 8. ApprovalRecord and lifecycle

Frozen immutable contract:

```text
ApprovalRecord {
  approval_id

  admission_id
  admission_fingerprint

  changeset_hash
  approved_scope_hash

  semantic_environment_ref
  approver
  policy_snapshot_hash

  allowed_operations[]

  approved_at
  consumed_at

  approval_hash
}
```

`approval_id` is a construction/address identity and MUST NOT carry independent authorization semantics.

Mutable revocation state is separate:

```text
ApprovalLifecycle {
  state:
    ACTIVE
    REVOKED

  revoked_at?
  revocation_reason?
}
```

A successfully consumed ApprovalRecord starts ACTIVE. Admission expiry applies before consumption only; a durable ApprovalRecord does not automatically become invalid merely because the original one-time Admission later passes its `expires_at`. Subsequent authority loss is explicit revocation.

### 8.1 Approval hash

```text
approval_hash = H({
  admission_fingerprint,

  changeset_hash,
  approved_scope_hash,

  semantic_environment_ref,
  approver,
  policy_snapshot_hash,

  sorted(allowed_operations),

  approved_at
})
```

Excluded from `approval_hash`:

```text
approval_id
admission_id
consumed_at
ApprovalLifecycle.state
revoked_at
revocation_reason
approval_hash itself
```

Rationale:

```text
approval_id
= construction/address identity

admission_id
= one-time store identity;
  authoritative content is already committed by admission_fingerprint

consumed_at
= Gateway ingestion/audit time,
  not user approval truth

revocation lifecycle
= mutable authorization state,
  not immutable approval body
```

Two records with the same immutable approval authority body have the same `approval_hash` even if construction ids or consumption audit time differ.

---

## 9. GatewayAuthorizationStore

Step32 state is authoritative Gateway state. Domain logic MUST NOT rely on a process-local dictionary contract.

Provider-neutral protocol:

```text
GatewayAuthorizationStore
```

Required atomic operations:

```text
consume_admission_once(...)
get_approval(...)
revoke_approval(...)

issue_or_get_grant(...)
get_grant(...)
admit_grant(...)
revoke_grant(...)
```

`get_approval()` returns authoritative immutable `ApprovalRecord` plus its authoritative `ApprovalLifecycle` projection; callers never submit lifecycle state as authority.

The Step32 service MUST NOT know PostgreSQL, Redis, DynamoDB, SQL syntax, distributed-lock implementation, or vendor-specific transaction APIs.

A v1 `InMemoryGatewayAuthorizationStore` is permitted for deterministic tests, but its externally observable semantics MUST model a real transactional store.

---

## 10. Atomic admission consumption

The logical database constraint is equivalent to:

```text
UNIQUE(admission_id)
```

Store operation:

```text
consume_admission_once(
  admission_id,
  admission_fingerprint,
  approval_record
)
```

must atomically perform:

```text
BEGIN

assert admission_id has not been consumed
insert durable ApprovalRecord + ACTIVE ApprovalLifecycle
record admission consumption identity/fingerprint

COMMIT
```

The following split writes are forbidden:

```text
mark admission consumed
↓
ApprovalRecord insert later fails
```

and:

```text
insert ApprovalRecord
↓
consumption marker later fails
```

Atomicity invariant:

```text
one admission_id
→ at most one durable ApprovalRecord
```

No state is allowed in which the token is consumed without durable approval evidence or durable approval evidence exists without the corresponding one-time consumption record.

---

## 11. Admission replay and conflict semantics

The store retains at least:

```text
admission_id
admission_fingerprint
approval_id
```

If the same `admission_id` is consumed again with the same fingerprint:

```text
APPROVAL_ADMISSION_ALREADY_CONSUMED
```

No second `ApprovalRecord` is created.

If the same `admission_id` is later presented with a different fingerprint:

```text
APPROVAL_ADMISSION_CONFLICT
```

This is not reduced to ordinary replay because it indicates the same one-time authority identity has been associated with different authoritative content.

Approval admission consumption is intentionally **strict one-time**, not idempotent get-or-create.

---

## 12. ExecutionGrant request

Input:

```text
ExecutionGrantRequest {
  approval_id
  execution_slice
  provider_binding_set
  issued_at
}
```

The caller supplies only `approval_id`, not a caller-owned `ApprovalRecord` value.

Step32 resolves:

```text
approval_id
↓
GatewayAuthorizationStore.get_approval()
↓
authoritative ApprovalRecord + ApprovalLifecycle
```

This prevents a caller from presenting a modified approval object or lifecycle projection as authority.

---

## 13. Grant issuance validation pipeline

Fixed order:

```text
contract/type validation
↓
ApprovalRecord exists
↓
ApprovalLifecycle is ACTIVE
↓
Step30 ExecutionSlice integrity
↓
Slice changeset_hash == ApprovalRecord.changeset_hash
↓
Slice approved_scope_ref.scope_hash == ApprovalRecord.approved_scope_hash
↓
Step31 ProviderBindingSet structural/hash integrity
↓
BindingSet exactly binds this Slice
↓
host_instance_id consistency
↓
Slice canonical operations ⊆ ApprovalRecord.allowed_operations
↓
binding expiry validation at issued_at
↓
derive grant expiry
↓
compute candidate ExecutionGrant + grant_hash
↓
atomic issue_or_get_grant
```

The Slice operation set is derived from exact `ExecutionUnit.canonical_operation` values and must be a subset of approval least privilege.

---

## 14. ExecutionGrant

Frozen immutable contract:

```text
ExecutionGrant {
  grant_id

  approval_id
  approval_hash

  changeset_hash
  approved_scope_hash

  execution_slice_id
  execution_slice_hash

  binding_set_hash
  host_instance_id

  allowed_operations[]

  issued_at
  expires_at

  grant_hash
}
```

`allowed_operations` is the exact canonical operation set present in the Slice, after verifying it is a subset of the ApprovalRecord allowance.

### 14.1 Grant expiry

v1 expiry is deterministic least privilege:

```text
expires_at = min(
  binding.binding_expires_at
  for binding in provider_binding_set.bindings
)
```

Requirement:

```text
issued_at < expires_at
```

No policy or service may extend a Grant beyond any immutable ProviderBinding expiry.

### 14.2 Grant hash

```text
grant_hash = H({
  approval_hash,

  changeset_hash,
  approved_scope_hash,

  execution_slice_hash,
  binding_set_hash,

  host_instance_id,
  sorted(allowed_operations),

  issued_at,
  expires_at
})
```

Excluded:

```text
grant_id
approval_id
execution_slice_id
GrantLifecycle.state
admitted_at
revoked_at
superseded_by_grant_id
grant_hash itself
```

Semantic authority is already committed by `approval_hash`, `execution_slice_hash`, and `binding_set_hash`; construction ids do not enter the immutable authorization identity.

---

## 15. Grant lifecycle projection

Mutable lifecycle is separate from immutable `ExecutionGrant`:

```text
GrantLifecycle {
  state:
    ACTIVE
    ADMITTED
    REVOKED
    EXPIRED

  admitted_at?
  revoked_at?
  revocation_reason?
  superseded_by_grant_id?
}
```

`EXPIRED` is a deterministic projection from immutable `expires_at`:

```text
now >= expires_at
→ effective state EXPIRED
```

The store does not require a background job that rewrites every ACTIVE row to EXPIRED.

---

## 16. Grant lineage and concurrency lock scope

The logical authority key is:

```text
GrantLineageKey = (
  approval_hash,
  execution_slice_hash
)
```

The invariant is:

```text
one approval_hash + execution_slice_hash
→ at most one ACTIVE grant authority
```

A uniqueness key of:

```text
approval_hash
+ execution_slice_hash
+ binding_set_hash
```

is insufficient because a provider switch could otherwise leave two simultaneously ACTIVE grants for the same logical Slice.

Provider rebinding must occur under the lineage lock.

---

## 17. `issue_or_get_grant()` state semantics

Within one lineage:

```text
ACTIVE + same binding_set_hash
→ return the already-committed existing Grant unchanged

ACTIVE + different binding_set_hash
→ atomically revoke/supersede old ACTIVE Grant
→ create exactly one new ACTIVE Grant

ADMITTED + same binding_set_hash
→ return the same already-committed Grant
→ retry/recovery path only

ADMITTED + different binding_set_hash
→ EXECUTION_GRANT_ALREADY_ADMITTED

REVOKED + same binding_set_hash
→ EXECUTION_GRANT_REVOKED
→ never resurrect identical revoked authority

REVOKED + different binding_set_hash
→ may issue a new Grant if all validation still passes

EXPIRED + same binding_set_hash
→ EXECUTION_GRANT_EXPIRED

EXPIRED + fresh different binding_set_hash
→ may issue a new Grant if all validation still passes
```

The exact idempotency identity for issuance is:

```text
approval_hash
+ execution_slice_hash
+ binding_set_hash
```

`issued_at` is part of the immutable Grant body, but it is **not** a retry discriminator. When concurrent or repeated requests for the same idempotency identity provide different `issued_at` values, the first transaction that commits creates the Grant; losing/retry callers receive that existing Grant unchanged, including its original `issued_at`, `expires_at`, and `grant_hash`.

This prevents network retry time from creating a second authority while preserving the first actual issuance time in the immutable grant body.

Grant issuance is intentionally **idempotent get-or-create**. This differs from approval admission consumption, which is strict one-time.

---

## 18. ADMITTED provider-switch prohibition

If:

```text
Grant A
binding_set_hash = PBS-A
state = ADMITTED
```

and a caller requests a new Grant for:

```text
PBS-B
```

Step32 MUST NOT perform:

```text
revoke A
→ issue B
→ execute Slice again
```

It must return:

```text
EXECUTION_GRANT_ALREADY_ADMITTED
```

Once a Slice has entered Host mutation, rebinding/re-execution is a Step33 verification/recovery/compensation concern, not a transparent Step32 provider switch.

---

## 19. `admit_grant()` CAS semantics

First admission is a compare-and-swap equivalent transition:

```text
ACTIVE → ADMITTED
```

with conditions equivalent to:

```text
WHERE grant_hash = ?
  AND state = ACTIVE
  AND parent ApprovalLifecycle = ACTIVE
  AND admitted_at < expires_at
```

`admitted_at` is explicit UTC input and is also the deterministic expiry-evaluation time for admission.

The operation must be atomic.

Two concurrent provider requests for the same Grant can produce only one state transition.

A repeated call using the same already-ADMITTED `grant_hash` returns the same logical admission result and is interpreted as retry/recovery for the **same logical Slice execution**. It MUST NOT authorize a second execution.

---

## 20. Revoke/admit race

The race is defined by transaction order, not thread timing.

### 20.1 Revoke commits first

```text
ACTIVE → REVOKED
```

Later admission fails with:

```text
EXECUTION_GRANT_REVOKED
```

Host mutation must not begin.

### 20.2 Admit commits first

```text
ACTIVE → ADMITTED
```

A later revoke records:

```text
ADMITTED → REVOKED lifecycle projection
```

but cannot pretend already-started execution never existed.

Gateway issues revocation/cancellation signaling. Step33 then owns:

```text
stop not-yet-started work where possible
↓
verify actual Host state
↓
compensate when required
```

No hidden rollback is permitted.

---

## 21. Approval revocation cascade

Revoking an ApprovalRecord is an authoritative parent revocation.

The store operation must atomically make the approval non-authoritative and apply child semantics:

```text
ApprovalLifecycle ACTIVE → REVOKED

ACTIVE child Grants
→ REVOKED

ADMITTED child Grants
→ retain admitted execution evidence
→ record revocation/cancellation projection
```

After approval revocation:

```text
issue_execution_grant(...)
→ APPROVAL_REVOKED

admit_grant(...)
→ APPROVAL_REVOKED
```

Already-started execution follows Step33 verify/reconcile/compensation; it is never erased from audit history.

---

## 22. GatewayAuthorizationService API

Recommended package:

```text
platform/gateway_authorization/
  src/design_gateway_authorization/
    contracts.py
    hashing.py
    store.py
    service.py
```

Primary façade:

```text
GatewayAuthorizationService
```

Public domain operations:

```text
consume_approval(
  ApprovalConsumptionRequest
) -> ApprovalRecord

issue_execution_grant(
  ExecutionGrantRequest
) -> ExecutionGrant

admit_execution_grant(
  grant_hash,
  admitted_at
) -> AdmittedExecutionAuthority

revoke_approval(
  approval_id,
  revoked_at,
  reason
)

revoke_execution_grant(
  grant_hash,
  revoked_at,
  reason
)
```

Step32 hashing exports at least:

```text
compute_admission_fingerprint(...)
compute_approval_hash(...)
compute_grant_hash(...)
```

Service owns:

```text
deterministic validation
exact cross-step joins
Step32 hashing
least privilege
stable error mapping
```

Store owns:

```text
atomicity
uniqueness
CAS
lineage locking
durable lifecycle state
```

---

## 23. Step33 handoff

Step32 does not create `ActualDelta` and does not verify mutation success.

After successful admission, Step32 exposes immutable authority evidence:

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

Execution evidence must permit Step33 to reconstruct the authorization lineage:

```text
ActualDelta / execution result
→ grant_hash
→ binding_set_hash
→ execution_slice_hash
→ changeset_hash
→ approved_scope_hash
```

Step33 can then independently prove:

```text
which canonical Slice was authorized
which ProviderBindingSet was authorized
which approval authorized it
whether ActualDelta stayed inside approved scope
```

Host command names or human-readable logs are not authorization evidence.

---

## 24. Stable Step32 error codes

Frozen internal codes:

```text
APPROVAL_INPUT_INVALID
APPROVAL_INTEGRITY_INVALID

APPROVAL_ADMISSION_EXPIRED
APPROVAL_ADMISSION_ALREADY_CONSUMED
APPROVAL_ADMISSION_CONFLICT

APPROVAL_SCOPE_MISMATCH
SEMANTIC_ENVIRONMENT_MISMATCH
APPROVAL_OPERATION_FORBIDDEN

APPROVAL_RECORD_NOT_FOUND
APPROVAL_REVOKED

EXECUTION_GRANT_INPUT_INVALID
EXECUTION_GRANT_SLICE_MISMATCH
EXECUTION_GRANT_BINDING_MISMATCH
EXECUTION_GRANT_OPERATION_FORBIDDEN

EXECUTION_BINDING_EXPIRED

EXECUTION_GRANT_EXPIRED
EXECUTION_GRANT_REVOKED
EXECUTION_GRANT_ALREADY_ADMITTED
EXECUTION_GRANT_CONFLICT
```

Provider/Gateway external boundaries MAY normalize detailed internal execution failures to the master-spec core code:

```text
EXECUTION_GRANT_INVALID
```

but audit, recovery, and replan logic MUST retain the concrete internal structured code. Natural-language messages are never used for machine branching.

Upstream validator errors are caught and mapped to the appropriate Step32 integrity/mismatch code while preserving the upstream code in structured audit detail.

---

## 25. Deterministic time semantics

All relevant time values are explicit UTC inputs or immutable upstream fields:

```text
approved_at
admission.expires_at
consumed_at
issued_at
binding_expires_at
admitted_at
revoked_at
```

Domain validation MUST NOT call wall-clock APIs internally.

Deterministic evaluation times are:

```text
Approval admission expiry → consumed_at
Grant issuance/binding expiry → issued_at
Grant admission expiry → admitted_at
Revocation audit → revoked_at
```

Expiry is derived from immutable timestamps and never mutates authorization hashes after construction.

---

## 26. Complete test matrix

### 26.1 Integrity

```text
Step28 Boundary full self-integrity succeeds
Step28 rule tamper fails
Step28 planning/snapshot/environment tamper fails
Step28 changeset_hash tamper fails

Step29 full ChangeSet integrity succeeds
Step29 root operation tamper fails
Step29 derived operation tamper fails
Step29 scope-rule linkage tamper fails
Step29 dependency tamper fails
Step29 precondition tamper fails

Step30 ExecutionUnit body tamper fails
Step30 ExecutionSlice body tamper fails

Step31 malformed ProviderBindingSet rejected through public validator
```

### 26.2 Approval

```text
valid Admission creates exactly one ApprovalRecord + ACTIVE ApprovalLifecycle
approved_at is preserved from Admission
consumed_at does not change approval semantics
expired Admission rejected
admission fingerprint tamper rejected

ChangeSet hash mismatch rejected
scope hash mismatch rejected
scope_body_hash join mismatch rejected
SemanticEnvironment mismatch rejected
operation outside policy rejected

allowed_operations equals exact ChangeSet operation set

same admission_id + same fingerprint second consume
→ APPROVAL_ADMISSION_ALREADY_CONSUMED

same admission_id + different fingerprint
→ APPROVAL_ADMISSION_CONFLICT

concurrent same Admission creates one Record
failed Record persistence does not consume Admission
failed consumption persistence does not leave ApprovalRecord

approval_hash deterministic
construction ids do not affect approval_hash
consumed_at does not affect approval_hash
approved_at does affect approval_hash
Admission expiry after successful consumption does not revoke ApprovalRecord
explicit approval revoke changes lifecycle but not approval_hash
```

### 26.3 Grant

```text
approval_id must resolve from Store
missing ApprovalRecord rejected
revoked ApprovalRecord rejected

Slice integrity required
Slice changeset mismatch rejected
Slice scope mismatch rejected

BindingSet integrity required
BindingSet Slice mismatch rejected
host_instance mismatch rejected
Slice operation outside approval rejected
expired binding rejected

grant expiry equals minimum binding expiry
grant_hash deterministic
construction ids do not affect grant_hash

same lineage + same BindingSet concurrent request
→ one Grant, both callers receive same committed Grant

same lineage + same BindingSet retry with later issued_at
→ existing original Grant returned unchanged

ACTIVE old BindingSet + new BindingSet
→ old superseded/revoked + exactly one new ACTIVE Grant

ADMITTED old BindingSet + new BindingSet
→ EXECUTION_GRANT_ALREADY_ADMITTED

REVOKED same BindingSet
→ not resurrected

same ADMITTED grant retry
→ same logical execution admission

ACTIVE admit CAS race
→ only one transition

revoke-before-admit
→ admission rejected

admit-before-revoke
→ admitted evidence retained + cancellation/revocation projection

expiry projected from expires_at
→ no background expiry task required

approval revoke prevents new Grant
approval revoke prevents later admit
approval revoke revokes ACTIVE child Grants
approval revoke preserves evidence for ADMITTED child execution
```

### 26.4 Regression

```text
Step28 approval-scope suite remains green
Step29 ChangeSet suite remains green
Step30 execution-planning suite remains green
Step31 provider-binding suite remains green
full repository regression remains green
Ruff remains green
```

---

## 27. Architecture guards

Production Step32 MUST satisfy:

```text
no Host implementation imports
no AutoCAD/Revit/Tekla product branches
no PostgreSQL/Redis/DynamoDB implementation imports in service/domain layer
no HostCommand ownership
no ActualDelta ownership
no Saga implementation
no wall-clock reads in deterministic validation
```

Dependency guards must prove:

```text
Step32 calls Step28 public integrity validator
Step32 calls Step29 public integrity validator
Step32 calls Step30 public integrity validator
Step32 calls Step31 validate_provider_binding_set()

Step32 does not reconstruct private Step28 hash body
Step32 does not reconstruct private Step29 hash body
Step32 does not reconstruct private Step30 hash body
Step32 does not reconstruct private Step31 binding hash body
```

---

## 28. PR and implementation boundary

The Step32 implementation branch may change:

```text
platform/gateway_authorization/**
tests/gateway_authorization/**

platform/approval_scope/**
tests/approval_scope/**

platform/changeset/**
tests/changeset/**

platform/execution_planning/**
tests/execution_planning/**

docs/superpowers/specs/2026-08-30-step32-gateway-authorization-design.md
docs/superpowers/plans/2026-08-30-step32-gateway-authorization.md
.github/workflows/step32-gateway-authorization.yml
pyproject.toml
```

Upstream production changes are limited to:

```text
Step28:
self-validating Boundary witness retention
+ public integrity validator

Step29:
public full-integrity validator

Step30:
public ExecutionUnit / ExecutionSlice integrity validator
```

The implementation MUST NOT use Step32 as justification to change:

```text
canonical operation semantics
ApprovalScope meaning
existing Step28 scope hash algorithm
existing Step29 ChangeSet hash algorithm
ExecutionUnit/ExecutionSlice partition semantics
existing Step30 hash algorithms
provider selection semantics
existing Step31 binding hash algorithms
```

---

## 29. Transaction model summary

Approval side:

```text
verified ApprovalAdmission
      ↓
deterministic Step28/29 integrity validation
      ↓
exact admission ↔ ChangeSet ↔ scope join
      ↓
least privilege
      ↓
compute ApprovalRecord / approval_hash
      ↓
atomic consume_admission_once
      ↓
durable ACTIVE ApprovalRecord
```

Grant side:

```text
authoritative ACTIVE ApprovalRecord
+ exact Step30 ExecutionSlice
+ exact Step31 ProviderBindingSet
      ↓
deterministic validation
      ↓
lock (approval_hash, execution_slice_hash) lineage
      ↓
return same committed Grant
or invalidate prior ACTIVE binding authority
      ↓
issue/get exactly one Grant
      ↓
CAS ACTIVE → ADMITTED
      ↓
one logical Slice execution
      ↓
Step33 Verify / ScopeComparator / Saga
```

Final frozen invariants:

```text
one admission_id
→ at most one ApprovalRecord

one approval_hash + execution_slice_hash
→ at most one ACTIVE Grant authority

one Grant
→ at most one logical Slice execution

same issuance idempotency identity
→ retry never creates a new authority from a later issued_at

ADMITTED Slice
→ cannot silently rebind and execute again

revoked identical Grant authority
→ cannot be resurrected by retry

Step32 authorization state
→ Gateway authoritative store boundary
```

---

## 30. Final design decision

Step32 is frozen as a separate provider-neutral Gateway authorization subsystem with two independent deterministic pipelines and one explicit authoritative store boundary.

The design deliberately distinguishes:

```text
Approval admission consumption
= strict one-time authority consumption

ExecutionGrant issuance
= idempotent lineage/binding-scoped get-or-create

ExecutionGrant admission
= CAS-protected one-logical-execution transition
```

Step32 binds existing immutable truths; it does not reinterpret them.

The only upstream changes required are integrity witness/API enhancements so each upstream owner can verify its own complete semantic object. Existing Step28–31 semantic hash definitions remain unchanged.

Implementation subsequently followed the approved implementation plan and strict TDD. The verified implementation commit and executed verification matrix are recorded in this document header.