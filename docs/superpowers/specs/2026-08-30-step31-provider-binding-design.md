# Step 31 — Provider Binding Design

**Status:** Design approved; implementation not started  
**Date:** 2026-08-30  
**Base:** `main@69dbe0886c7a2fe497ed58bf3b82676007a667dd`  
**Branch:** `feat/step31-provider-binding`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step31 introduces deterministic late binding from Step30's immutable provider-neutral execution plan into immutable provider/native execution bindings.

It answers:

```text
Given this exact ExecutionSlice,
this exact slice-scoped provider/native execution snapshot,
and this exact registered adapter set,
which provider implementation binds each ExecutionUnit,
which native targets/provider payload will be used,
and what binding_set_hash must Step32 authorize?
```

It does **not** answer canonical intent, execution partitioning, approval, RevisionBarrier admission, Host mutation, retry/idempotency, ActualDelta, verification, rollback, or Saga compensation.

The frozen flow is:

```text
Step29 CanonicalChangeSet
        ↓
Step30 immutable ExecutionPlan
        ↓
RevisionBarrier
        ↓
Step31 ProviderResolver
  + ProviderExecutionSnapshot
  + ProviderBindingAdapterRegistry
        ↓
ProviderBindingSet
  └─ ProviderBinding[]
        ↓
binding_set_hash
        ↓
Step32 ExecutionGrant
        ↓
Step33 HostCommand / Apply / Verify / Saga
```

Central invariant:

> Step31 may choose and freeze the provider/native implementation of an exact Step30 ExecutionUnit. It MUST NOT change canonical semantics, repartition units, widen approved scope, create execution authorization, or perform Host mutation.

---

## 2. Master-spec interpretation

The master spec freezes:

```text
ExecutionUnit   = minimum provider-binding unit; still canonical/provider-neutral
ProviderBinding = provider/native choice made after execution planning
ExecutionGrant  = per-Slice authorization bound to binding_set_hash
HostCommand     = final native execution envelope after authorization
```

Provider Resolver is late-bound after execution planning and considers at least:

```text
HostRuntimeRef
provider_native_constraints
Policy / Trust
Provider version / compatibility
Health / availability
License / certification
```

It MUST NOT change:

```text
canonical_operation
targets
arguments
expected_effects
approved scope
```

Provider switching changes implementation identity, not canonical approval identity:

```text
old binding_set_hash → old grant invalid
new binding_set_hash → reissue grant
```

Repeated user approval is not required when ChangeSet and approved semantic scope remain unchanged.

---

## 3. Package strategy

Step31 SHALL be a separate package:

```text
platform/provider_binding/
  pyproject.toml
  src/design_provider_binding/
    __init__.py
    contracts.py
    hashing.py
    resolver.py
    adapters.py
```

Distribution:

```text
design-provider-binding
```

Primary provider-neutral dependencies:

```text
design_execution_planning
jsonschema
```

The package MUST NOT depend on AutoCAD/Revit/Tekla sidecars, Host SDKs, Host dispatchers, approval/grant packages, or verification/Saga packages.

Step30 owns execution partition identity. Step31 owns provider/native implementation identity. They remain physically separate.

---

## 4. Ownership boundary

### 4.1 Step30 remains authoritative

Step31 consumes but never rewrites:

```text
ExecutionSlice.execution_slice_id/hash
ExecutionSlice.host_runtime_ref
ExecutionSlice.approved_scope_ref
ExecutionUnit.execution_unit_id/hash
ExecutionUnit.canonical_operation
ExecutionUnit.targets
ExecutionUnit.arguments
ExecutionUnit.preconditions
ExecutionUnit.expected_effects
```

Step31 MUST NOT split, merge, optimize, replace, or reorder canonical Units.

### 4.2 RevisionBarrier remains outside Step31

Runtime ordering stays:

```text
Step30 → RevisionBarrier → Step31
```

Step31 validates provider snapshot expiry, but it does not create a second Host-revision truth or reinterpret planning freshness/coverage/assurance requirements.

### 4.3 Step31 owns

- exact Slice ↔ ProviderExecutionSnapshot integrity;
- closed-world native binding validation;
- deterministic candidate filtering/ranking;
- deterministic Adapter selection;
- provider-native target/argument/native-metadata materialization;
- optional provider-native enforcement projections;
- provider input-schema validation;
- immutable ProviderBinding construction;
- `binding_hash` and Slice-level `binding_set_hash`.

### 4.4 Step32 owns

```text
ApprovalRecord
ExecutionGrant
allowed_operations
authorization expiry
```

Step31 never decides whether the user approved a mutation and never issues a grant.

### 4.5 Step33 owns

```text
HostCommand
command_id
idempotency/retry/dispatch
ActualDelta
verification
scope comparison
rollback/compensation
Saga state
```

Step31 MUST NOT call `send_command()` or mutate a Host.

---

## 5. Evidence strategy

### 5.1 Slice-scoped immutable ProviderExecutionSnapshot

Step31 SHALL NOT live-query D3, Host sidecars, HostBinding storage, health/license/certification services, policy engines, or MCP sessions while resolving.

Workflow code supplies one immutable provider-neutral snapshot per Slice:

```text
1 ExecutionSlice
      ↓
1 ProviderExecutionSnapshot
      ↓
N ExecutionUnit
      ↓
N ProviderBinding
      ↓
1 binding_set_hash
```

This keeps the deterministic core isolated from mutable external state.

### 5.2 Do not import sidecar-local capability DTOs

Current Host capability DTOs may contain legacy mixed semantics. Step31 instead consumes a normalized execution candidate with `provider_native_constraints` separated from canonical applicability constraints.

---

## 6. Binding granularity

Step31 v1 freezes:

```text
1 ExecutionUnit = exactly 1 ProviderBinding
```

A Unit may contain multiple targets, but one provider implementation MUST bind all of them.

Forbidden:

```text
EU-01
├─ Provider A binds subset A
└─ Provider B binds subset B
```

If no single eligible provider can bind the full Unit:

```text
PROVIDER_CANDIDATE_UNAVAILABLE
```

Step31 never silently splits a Unit.

---

## 7. Public contracts

### 7.1 EligibilityState

```text
EligibilityState {
  SATISFIED
  UNSATISFIED
  UNKNOWN
}
```

Only `SATISFIED` passes. `UNKNOWN` fails closed.

### 7.2 NativeConstraint

Step31 v1 intentionally supports only a minimal deterministic constraint language:

```text
NativeConstraintOperator { EQ, IN }

NativeConstraint {
  field
  operator
  values[]
}
```

The only v1 generic field is:

```text
native_kind
```

Examples:

```text
native_kind EQ "Wall"
native_kind IN ["LINE", "LWPOLYLINE", "ARC"]
```

The core compares opaque strings; it does not understand Host ontology.

### 7.3 NativeTargetBindingEvidence

```text
NativeTargetBindingEvidence {
  semantic_id
  host_type
  document_ref
  native_id
  native_kind
  host_binding_fingerprint
}
```

`host_binding_fingerprint` is recomputed from:

```text
semantic_id
host_type
document_ref
native_id
native_kind
```

`host_instance_id` stays outside persistent HostBinding identity and comes from the Slice's HostRuntimeRef.

### 7.4 ProviderExecutionCandidate

```text
ProviderExecutionCandidate {
  provider_server
  provider_tool
  provider_version

  canonical_operation
  compatible_operation_versions[]

  input_adapter_version

  provider_native_constraints[]
  provider_input_schema

  verification_contract
  rollback_contract

  trust_state
  compatibility_state
  health_state
  license_state
  certification_state

  policy_priority
  candidate_fingerprint
}
```

Rules:

- `policy_priority` is a non-negative deterministic integer; lower ranks first.
- state fields use `EligibilityState`.
- `provider_input_schema` must be a valid JSON Schema.
- candidate fingerprint is recomputed from the full candidate semantic body.
- candidates are evidence, not caller instructions to force a tool.

### 7.5 ProviderExecutionSnapshot

```text
ProviderExecutionSnapshot {
  snapshot_id
  execution_slice_id
  execution_slice_hash
  host_runtime_ref
  native_target_bindings[]
  provider_candidates[]
  valid_until
  snapshot_hash
}
```

`valid_until` is REQUIRED in v1 and normalized UTC RFC3339.

`snapshot_id` is opaque provenance identity and is excluded from the semantic snapshot hash.

### 7.6 ProviderPreconditionBinding

Provider-native preconditions are an **optional additional enforcement projection**, not a replacement for Step30 canonical preconditions:

```text
ProviderPreconditionBinding {
  source_precondition_fingerprint
  provider_precondition
}
```

The source fingerprint is SHA-256 over the exact Step30 `ChangePrecondition` body:

```text
kind
subject_ref
evidence_ref
```

Important v1 rule:

- Step30 preconditions are currently planning requirements (`OPERATION_FRESHNESS`, `COVERAGE`, `ASSURANCE`).
- They are already bound by `execution_unit_hash` and admitted by upstream planning/barrier logic.
- Step31 therefore does **not** require every canonical precondition to become a Host/provider-native precondition.
- If an Adapter emits provider-native preconditions, each emitted row MUST reference a real Step30 source precondition fingerprint; unknown or duplicate source references fail closed.
- Provider-native preconditions can add enforcement but cannot erase canonical preconditions from the immutable Unit they bind.

This avoids forcing semantic coverage/assurance requirements into Host command syntax while preserving traceability for any native enforcement that is emitted.

### 7.7 ProviderBindingMaterial

Adapters return only transformation material:

```text
ProviderBindingMaterial {
  native_targets[]
  provider_arguments
  provider_preconditions[]
  native_binding_metadata
}
```

Adapters MUST NOT return:

```text
binding_id/hash
binding_set_hash
canonical_operation
targets/expected_effects
approved scope
provider identity/version
ExecutionGrant
HostCommand
```

### 7.8 ProviderBinding

```text
ProviderBinding {
  binding_id

  execution_unit_id
  execution_unit_hash
  execution_slice_id
  execution_slice_hash

  canonical_operation

  provider_server
  provider_tool
  provider_version
  selected_candidate_fingerprint

  host_instance_id
  document_ref
  input_adapter_version

  native_targets[]
  provider_arguments
  provider_preconditions[]
  native_binding_metadata

  verification_contract
  rollback_contract

  binding_expires_at
  binding_hash
}
```

In v1:

```text
binding_expires_at = snapshot.valid_until
```

### 7.9 ProviderBindingSet

```text
ProviderBindingSet {
  binding_set_id
  execution_slice_id
  execution_slice_hash
  provider_execution_snapshot_id
  provider_execution_snapshot_hash
  bindings[]
  binding_set_hash
}
```

Snapshot refs are immutable provenance metadata, deliberately excluded from authorization hash material.

Two resolution records from different snapshots MAY have the same `binding_set_hash` when selected providers/native material/expiry are authorization-equivalent.

Authorization identity:

```text
binding_set_id = "PBS-" + binding_set_hash[:12]
```

### 7.10 ProviderBindingRequest

```text
ProviderBindingRequest {
  execution_slice
  provider_execution_snapshot
  admission_time
}
```

`admission_time` is explicit normalized UTC time used only for expiry admission. It does not enter ranking or semantic hashes. Resolver code MUST NOT read wall-clock time directly.

---

## 8. Snapshot integrity

Before candidate selection:

```text
snapshot.execution_slice_id   == slice.execution_slice_id
snapshot.execution_slice_hash == slice.execution_slice_hash
snapshot.host_runtime_ref      == slice.host_runtime_ref
```

Mismatch:

```text
PROVIDER_SLICE_MISMATCH
```

Every native binding must also match Slice Host type/document and recompute its HostBinding fingerprint exactly.

### 8.1 Closed-world native targets

Let:

```text
required_targets = union(slice.execution_units[*].targets)
```

Then:

```text
set(snapshot.native_target_bindings.semantic_id) == required_targets
```

Failures:

```text
missing      → PROVIDER_NATIVE_BINDING_UNRESOLVED
duplicate/conflicting → PROVIDER_NATIVE_BINDING_CONFLICT
extraneous   → PROVIDER_NATIVE_BINDING_EXTRANEOUS
```

Even identical duplicate rows are rejected; one authoritative row per semantic target is required.

### 8.2 Candidate scope

Alternative candidates are allowed, including unused alternatives, but every candidate canonical operation MUST correspond to at least one Unit in the Slice. Unrelated candidates are invalid snapshot content:

```text
PROVIDER_CANDIDATE_INVALID
```

### 8.3 Snapshot hash

```text
snapshot_hash = SHA256({
  execution_slice_hash,
  host_runtime_ref,
  normalized native target evidence,
  normalized candidate semantic bodies/fingerprints,
  valid_until
})
```

`snapshot_id` is excluded.

Mismatch:

```text
PROVIDER_SNAPSHOT_HASH_MISMATCH
```

Expiry rule:

```text
admission_time >= valid_until
→ PROVIDER_SNAPSHOT_EXPIRED
```

No Adapter is called after expiry failure.

---

## 9. Candidate fingerprint

`candidate_fingerprint` binds:

```text
provider_server
provider_tool
provider_version
canonical_operation
compatible_operation_versions
input_adapter_version
provider_native_constraints
provider_input_schema
verification_contract
rollback_contract
trust_state
compatibility_state
health_state
license_state
certification_state
policy_priority
```

Step31 recomputes every fingerprint. Digest mismatch, invalid schema, or invalid constraint syntax returns:

```text
PROVIDER_CANDIDATE_INVALID
```

---

## 10. Deterministic candidate eligibility

For each Unit, filtering order is fixed:

```text
1. canonical_operation exact match
2. Unit canonical operation version is compatible
3. every provider_native_constraint is satisfied by every Unit native target
4. trust_state == SATISFIED
5. compatibility_state == SATISFIED
6. health_state == SATISFIED
7. license_state == SATISFIED
8. certification_state == SATISFIED
```

Policy is already projected into candidate state/priority evidence; Step31 does not live-call a policy service.

If all candidates are filtered:

```text
PROVIDER_CANDIDATE_UNAVAILABLE
```

`PROVIDER_NATIVE_CONSTRAINT_UNSATISFIED` remains available for direct constraint-validation diagnostics/tests, but normal multi-candidate resolution continues filtering and only returns UNAVAILABLE when no eligible candidate remains.

---

## 11. Deterministic ranking and ambiguity

Eligible candidates rank by:

```text
(
  policy_priority ASC,
  provider_server ASC,
  provider_tool ASC,
  provider_version ASC
)
```

Version ordering here is a deterministic identity tie-breaker, not a claim that lexical version order means "better". Any intended version preference must be projected into `policy_priority` by the snapshot producer.

### 11.1 Tie rule

`candidate_fingerprint` is **not** a winner tie-breaker.

If two rows have the same ranking identity:

- same fingerprint → duplicate candidate evidence;
- different fingerprints → conflicting evidence for the same provider identity/version/priority.

Both fail closed:

```text
PROVIDER_CANDIDATE_AMBIGUOUS
```

Resolver never uses discovery order, registration order, randomness, or LLM preference.

---

## 12. No exception-driven provider fallback

After deterministic selection, exactly one candidate is sent to its Adapter.

If adaptation fails:

```text
PROVIDER_BINDING_ADAPTATION_FAILED
```

Step31 MUST NOT secretly try the next-ranked candidate.

Recovery is external:

```text
fail closed
→ refresh provider/native evidence
→ rerun Step31
```

This prevents runtime exception behavior from becoming an undocumented provider-selection algorithm.

---

## 13. ProviderBindingAdapter

### 13.1 Protocol

```text
ProviderBindingAdapter {
  adapter_version

  bind(
    execution_unit,
    host_runtime_ref,
    selected_candidate,
    native_target_bindings
  ) -> ProviderBindingMaterial
}
```

Adapters may perform Host/provider-specific transformations such as:

```text
semantic/native binding → provider target format
canonical units → native/internal units
canonical arguments → provider input payload
optional native enforcement projection
native operation variant metadata
```

### 13.2 Registry

Adapters are injected through:

```text
ProviderBindingAdapterRegistry
```

Key: `provider_server`.

At most one Adapter may be registered for a provider_server in one resolver instance.

Errors:

```text
missing adapter      → PROVIDER_ADAPTER_UNAVAILABLE
conflicting adapter  → PROVIDER_ADAPTER_CONFLICT
```

The Adapter's declared version MUST exactly match `selected_candidate.input_adapter_version`; mismatch fails closed as unavailable/incompatible.

Generic Step31 code MUST NOT contain Host branches such as `if host_type == "AUTOCAD"` and MUST NOT dynamically import Host packages.

---

## 14. Adapter output integrity

### 14.1 Native targets

Adapter output must bind exactly the Unit target set:

```text
set(material.native_targets.semantic_id)
==
set(execution_unit.targets)
```

It cannot add, remove, substitute, or duplicate targets.

Failure:

```text
PROVIDER_NATIVE_TARGET_MISMATCH
```

Each returned native target must equal the frozen snapshot evidence for that semantic target. Adapter formatting may change; native identity may not.

### 14.2 Canonical semantics are structurally unmodifiable

Adapter material has no canonical operation/effect/scope fields. Provider identity/version is copied by generic core from the selected candidate. Canonical rewriting is therefore structurally unrepresentable through the Adapter API.

### 14.3 Optional provider-native preconditions

`provider_preconditions[]` may be empty.

If non-empty:

- every `source_precondition_fingerprint` must correspond to an exact Step30 source precondition;
- duplicate source references fail closed;
- no Adapter-generated precondition may claim a nonexistent source precondition.

Failure:

```text
PROVIDER_BINDING_ADAPTATION_FAILED
```

The core does **not** require complete native translation of all Step30 preconditions, because those are canonical planning/barrier requirements rather than a Host command schema.

### 14.4 Provider input schema

Adapter `provider_arguments` must validate against selected candidate `provider_input_schema`.

Failure:

```text
PROVIDER_INPUT_SCHEMA_INVALID
```

This is distinct from Step29 canonical-argument validation:

```text
Step29: canonical arguments → Canonical Action schema
Step31: provider arguments  → Provider execution schema
```

### 14.5 Native binding metadata

`native_binding_metadata` is immutable opaque execution-semantic metadata that does not fit target/argument/precondition fields, for example parameter-binding refs, native operation variants, or provider schema discriminators.

Runtime noise such as debug traces, latency, mutable retry state, or log timestamps MUST NOT enter this mapping.

Any metadata that can change actual execution behavior is binding hash material.

---

## 15. Binding expiry

Step31 v1 freezes:

```text
binding_expires_at = snapshot.valid_until
```

Expiry is authorization-relevant and enters `binding_hash`.

Changing the validity window therefore changes:

```text
binding_hash
→ binding_set_hash
→ old ExecutionGrant cannot be reused
```

Future versions MAY add candidate/native-binding-level deadlines and derive the minimum, but v1 does not.

---

## 16. Hashing model

All Step31 hashes use canonical JSON + SHA-256 with normalized collection ordering.

Construction IDs MUST NOT be substituted for full hashes inside semantic hash bodies.

### 16.1 HostBinding fingerprint

```text
host_binding_fingerprint = SHA256({
  semantic_id,
  host_type,
  document_ref,
  native_id,
  native_kind
})
```

### 16.2 Candidate fingerprint

As defined in §9.

### 16.3 binding_hash

```text
binding_hash = SHA256({
  execution_unit_hash,
  execution_slice_hash,
  canonical_operation,

  provider_server,
  provider_tool,
  provider_version,
  selected_candidate_fingerprint,

  host_instance_id,
  document_ref,
  input_adapter_version,

  normalized native_targets,
  provider_arguments,
  normalized provider_preconditions,
  native_binding_metadata,

  verification_contract,
  rollback_contract,
  binding_expires_at
})
```

Excluded:

```text
binding_id
provider_execution_snapshot_id
provider_execution_snapshot_hash
```

Construction ID:

```text
binding_id = "PB-" + binding_hash[:12]
```

### 16.4 Why snapshot hash is excluded

Snapshot hash is input integrity/provenance, not selected execution identity.

If only an unused candidate changes while winner/native payload/contracts/expiry remain identical, `snapshot_hash` may change while `binding_hash` remains unchanged.

The selected candidate's exact body still binds through `selected_candidate_fingerprint`.

### 16.5 binding_set_hash

```text
binding_set_hash = SHA256({
  execution_slice_hash,
  sorted(full 64-hex binding_hash values)
})
```

Construction ID:

```text
binding_set_id = "PBS-" + binding_set_hash[:12]
```

The hash MUST use full binding hashes, never `PB-<12-char>` IDs.

Snapshot ID/hash are excluded from authorization hash material. `ProviderBindingSet` therefore acts as an immutable resolution record whose authorization identity is `binding_set_hash`; provenance refs may differ while authorization-equivalent binding content remains the same.

### 16.6 Sensitivity

Any selected execution-material change MUST change binding hash/set hash, including:

```text
provider server/tool/version
selected candidate fingerprint
adapter version
host instance/document
native id/kind
provider arguments
provider-native preconditions
native metadata
verification contract
rollback contract
binding expiry
```

Provider switching leaves upstream hashes unchanged:

```text
ChangeSet hash
ExecutionUnit hash
ExecutionSlice hash
```

and changes:

```text
ProviderBinding hash
binding_set_hash
```

---

## 17. Fail-closed error codes

```text
PROVIDER_BINDING_INPUT_INVALID

PROVIDER_SLICE_MISMATCH
PROVIDER_SNAPSHOT_HASH_MISMATCH
PROVIDER_SNAPSHOT_EXPIRED

PROVIDER_NATIVE_BINDING_UNRESOLVED
PROVIDER_NATIVE_BINDING_CONFLICT
PROVIDER_NATIVE_BINDING_EXTRANEOUS

PROVIDER_CANDIDATE_INVALID
PROVIDER_CANDIDATE_UNAVAILABLE
PROVIDER_CANDIDATE_AMBIGUOUS
PROVIDER_NATIVE_CONSTRAINT_UNSATISFIED

PROVIDER_ADAPTER_UNAVAILABLE
PROVIDER_ADAPTER_CONFLICT
PROVIDER_BINDING_ADAPTATION_FAILED

PROVIDER_NATIVE_TARGET_MISMATCH
PROVIDER_INPUT_SCHEMA_INVALID

PROVIDER_BINDING_HASH_MISMATCH
PROVIDER_BINDING_SET_INVALID
```

No error path may silently select another provider after Adapter failure, split a Unit, widen targets/scope, or dispatch a Host command.

`PROVIDER_BINDING_HASH_MISMATCH` is reserved for public hash-validation helpers / externally supplied immutable binding validation. Normal resolver construction computes rather than accepts binding hashes.

---

## 18. Step32 handoff

Step31 outputs one ProviderBindingSet per ExecutionSlice.

Step32 consumes authorization-relevant identity including at least:

```text
execution_slice_id
execution_slice_hash
binding_set_hash
host_instance_id
```

plus governance evidence:

```text
ApprovalRecord
changeset_hash
approved_scope_hash
allowed_operations
expires_at
```

Step31 MUST NOT generate approval IDs, inspect approvers, re-decide approved scope, choose allowed operations, issue ExecutionGrant, or send HostCommand.

Expected invalidation behavior:

```text
same ChangeSet + same approved scope + changed ProviderBindingSet
        ↓
no repeated user approval
        ↓
old grant invalid
        ↓
new binding_set_hash
        ↓
reissue ExecutionGrant
```

---

## 19. Architecture guards

Step31 production code SHALL contain no direct import of Host-specific or execution/governance runtime packages.

Guard at least:

```text
autocad_sidecar
Revit/Tekla SDK packages
HostAdapter
CommandDispatcher
send_command
HostCommand
ApprovalRecord
ExecutionGrant
ActualDelta
Saga
mutable rollback/retry/idempotency state
```

Generic resolver code SHALL contain no `host_type == ...` provider-specific branches.

`rollback_contract` as immutable contract data is allowed; rollback runtime ownership is not.

---

## 20. Test matrix

Implementation MUST cover:

| Category | Required behavior |
|---|---|
| Contracts | frozen DTOs, tuple normalization, defensive mappings, digest/timestamp validation |
| Snapshot binding | Slice ID/hash/HostRuntimeRef mismatch rejected |
| Snapshot hash | supplied hash recomputed; mismatch rejected |
| Snapshot expiry | explicit admission time before expiry succeeds; at/after expiry rejects |
| Native identity | HostBinding fingerprint recomputed |
| Closed-world native targets | missing/conflict/extraneous rejected |
| Candidate validity | bad fingerprint/schema/constraint syntax rejected |
| Candidate scope | unrelated canonical operation rejected |
| Candidate filters | version/trust/compatibility/health/license/certification/native constraint gates |
| Determinism | candidate/input ordering does not alter winner |
| Ranking | policy priority then stable provider identity |
| Ambiguity | duplicate/conflicting same-rank provider identity fails closed |
| Unit granularity | one EU → exactly one PB; no partial/mixed provider binding |
| Adapter registry | missing/conflicting/version-mismatched adapter rejected |
| No hidden fallback | selected Adapter failure does not try next candidate |
| Target integrity | Adapter cannot add/remove/substitute/duplicate targets |
| Native preconditions | optional; emitted rows must reference real unique source preconditions |
| Provider schema | adapted arguments must validate |
| Hash determinism | collection ordering does not alter semantic hashes |
| Binding sensitivity | selected provider/native/payload/preconditions/contracts/expiry change alters binding hash |
| Binding-set sensitivity | any full binding hash change alters binding_set_hash |
| Full-hash rule | set hash uses full 64-hex binding hashes, never PB IDs |
| Unused candidate | may change snapshot hash but not binding/set hash if winner material+expiry unchanged |
| Provider switch | ChangeSet/EU/Slice hashes unchanged; PB/set hashes change |
| Step32 boundary | no approval/grant fields or behavior in Step31 |
| Runtime boundary | no HostCommand/dispatch/retry/ActualDelta/Saga |
| Regression | Step30, Step29, and existing capability/resolver tests remain GREEN |

---

## 21. Determinism requirements

For the same:

```text
ExecutionSlice semantic body
ProviderExecutionSnapshot semantic body
admission result (not expired)
registered Adapter implementation/version
```

Step31 produces the same:

```text
selected candidate per Unit
ProviderBinding semantic body
binding_hash
ProviderBindingSet binding contents
binding_set_hash
```

These MUST NOT affect selection:

```text
candidate ordering
native binding ordering
Adapter registration ordering
discovery ordering
randomness
LLM preference
wall-clock lookup inside resolver
exception-driven fallback
```

Any two admission times before the same snapshot expiry produce identical binding semantics.

---

## 22. v1 non-goals

Step31 v1 deliberately does not implement:

- live provider discovery/health polling;
- global Provider Registry infrastructure;
- HostBinding Resolution Service;
- arbitrary native constraint DSL;
- mixed-provider binding of one ExecutionUnit;
- candidate/native-target independent expiry deadlines;
- direct MCP invocation;
- HostCommand creation/dispatch;
- approval/grant logic;
- verification/rollback/Saga runtime execution.

These remain extendable behind the frozen evidence/Adapter boundary.

---

## 23. Final architecture

```text
Step30 immutable ExecutionSlice
              +
ProviderExecutionSnapshot
              ↓
      snapshot integrity
              ↓
  closed-world native identity
              ↓
 deterministic candidate filtering
              ↓
 deterministic provider winner
              ↓
 ProviderBindingAdapter transformation
              ↓
 target/source-ref/schema integrity gates
              ↓
 immutable ProviderBinding
              ↓
          binding_hash
              ↓
 all Slice bindings normalized
              ↓
 immutable ProviderBindingSet
              ↓
        binding_set_hash
              ↓
            Step32
        ExecutionGrant
```

Final ownership invariant:

```text
Canonical semantics
  Step29 / Step30 own

Implementation selection + provider/native binding identity
  Step31 owns

Execution authorization
  Step32 owns

Host mutation + read-back + verification + reconciliation + Saga
  Step33 owns
```

Step31 is complete when it can deterministically prove and hash **how this already-approved canonical ExecutionUnit would be implemented**, without changing **what the Unit means** and without yet authorizing or performing the Host mutation.
