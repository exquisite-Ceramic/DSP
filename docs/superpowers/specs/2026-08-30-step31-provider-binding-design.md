# Step 31 — Provider Binding Design

**Status:** Design approved; implementation not started  
**Date:** 2026-08-30  
**Base:** `main@69dbe0886c7a2fe497ed58bf3b82676007a667dd`  
**Branch:** `feat/step31-provider-binding`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step31 introduces deterministic late binding from the immutable provider-neutral execution plan produced by Step30 into immutable provider/native execution bindings.

It answers one question:

```text
Given this exact immutable ExecutionSlice,
this exact slice-scoped provider/native execution snapshot,
and this exact registered provider binding adapter set,
which provider implementation binds each ExecutionUnit,
which native targets and provider-native payload will be used,
and what binding_set_hash must Step32 authorize?
```

It does **not** answer:

```text
What canonical mutation does the user intend?
How canonical operations are partitioned across Host/document slices?
Whether the user approved the ChangeSet?
Whether the runtime RevisionBarrier passes?
What ExecutionGrant is issued?
How HostCommand envelopes/idempotency/retry are constructed?
Whether the Host mutation succeeds?
What ActualDelta occurred?
How verification, reconciliation, rollback, or Saga compensation proceeds?
```

The intended Phase-G flow is:

```text
Step29 CanonicalChangeSet
        ↓
Step30 immutable ExecutionPlan
  └─ ExecutionSlice[]
       └─ ExecutionUnit[]
        ↓
RevisionBarrier
        ↓
Step31 ProviderResolver
  + slice-scoped ProviderExecutionSnapshot
  + ProviderBindingAdapterRegistry
        ↓
immutable ProviderBindingSet
  └─ ProviderBinding[]
        ↓
binding_set_hash
        ↓
Step32 ExecutionGrant
        ↓
Step33 HostCommand / Apply / ActualDelta / Verify / Saga
```

The central invariant is:

> Step31 may choose and freeze the provider/native implementation of an exact Step30 ExecutionUnit. It MUST NOT change canonical semantics, repartition units, widen approved scope, create execution authorization, or perform Host mutation.

---

## 2. Master-spec interpretation

The v0.6 master spec freezes these relevant boundaries:

```text
ExecutionUnit = minimum provider-binding unit, still canonical/provider-neutral
ProviderBinding = provider/native execution choice made after execution planning
ExecutionGrant = per-ExecutionSlice authorization bound to binding_set_hash
HostCommand = final native execution envelope after authorization
```

The master spec explicitly places Provider Resolver after execution planning and requires late binding to consider at least:

```text
HostRuntimeRef
provider_native_constraints
Policy / Trust
Provider version / compatibility
Health / availability
License / certification
```

It also requires Provider Resolver to leave these immutable:

```text
canonical_operation
targets
arguments
expected_effects
approved scope
```

The master spec further requires:

```text
old binding_set_hash → old grant invalid
new binding_set_hash → reissue grant
```

without requiring repeated user approval when the canonical ChangeSet and approved semantic scope remain unchanged.

Step31 therefore owns authorization-relevant execution implementation identity, but not user approval or Host dispatch.

---

## 3. Chosen package strategy

Step31 SHALL be implemented as a separate package:

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

The distribution name SHALL be:

```text
design-provider-binding
```

Primary dependencies SHALL be provider-neutral runtime contracts only:

```text
design_execution_planning
jsonschema
```

The package MAY reuse the repository's canonical JSON/SHA-256 helper by importing a stable public helper from an upstream provider-neutral package if available. It MUST NOT depend on AutoCAD/Revit/Tekla sidecar packages, Host SDKs, Host command dispatchers, approval/grant packages, or verification/Saga packages.

The package is physically separate from `design_execution_planning` because Step30 owns provider-neutral execution partition identity while Step31 owns provider/native implementation identity.

---

## 4. Ownership boundary

### 4.1 Step30 owns immutable execution intent

Step30 remains authoritative for:

```text
ExecutionSlice.execution_slice_id
ExecutionSlice.execution_slice_hash
ExecutionSlice.host_runtime_ref
ExecutionSlice.approved_scope_ref
ExecutionUnit.execution_unit_id
ExecutionUnit.execution_unit_hash
ExecutionUnit canonical_operation
targets
arguments
preconditions
expected_effects
ExecutionDependency graph
```

Step31 MUST NOT split, merge, reorder, rewrite, or replace an ExecutionUnit.

### 4.2 RevisionBarrier remains outside Step31

Runtime order is:

```text
Step30 ExecutionPlan
        ↓
RevisionBarrier
        ↓
Step31 ProviderBinding
```

Step31 may validate ProviderExecutionSnapshot expiry/freshness evidence, but it MUST NOT create a second Host-revision concurrency truth or reinterpret planning revision requirements.

### 4.3 Step31 owns implementation selection and binding identity

Step31 owns:

- exact ExecutionSlice ↔ ProviderExecutionSnapshot integrity checks;
- closed-world native target binding validation;
- deterministic candidate filtering/ranking;
- deterministic adapter selection;
- provider-native target/payload/precondition materialization;
- provider input-schema validation;
- immutable ProviderBinding construction;
- binding_hash and slice-level binding_set_hash.

### 4.4 Step32 owns authorization

Step32 owns:

```text
ApprovalRecord
ExecutionGrant
allowed_operations
authorization expiry
```

Step31 never decides whether the user approved a mutation and never issues a grant.

### 4.5 Step33 owns Host mutation and runtime state

Step33 owns:

```text
HostCommand
command_id
idempotency key
retry/dispatch state
ActualDelta
verification result
scope comparison
rollback/compensation
Saga state
```

Step31 MUST NOT call `send_command()` or otherwise mutate a Host.

---

## 5. Chosen evidence strategy

### 5.1 Chosen: slice-scoped immutable ProviderExecutionSnapshot

Step31 SHALL NOT live-query D3, Host sidecars, health services, license services, policy services, or HostBinding registries during deterministic resolution.

Instead, workflow code SHALL assemble one immutable provider-neutral execution snapshot per Step30 ExecutionSlice:

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

The snapshot is task/slice scoped. It contains only the provider/native evidence required to bind the exact slice.

This follows the same architectural pattern already used elsewhere in the platform:

```text
external mutable world
        ↓
small immutable task-scoped evidence
        ↓
pure deterministic core
```

### 5.2 Why Step31 does not consume sidecar-local DesignCapabilityProfile directly

Current Host capability DTOs are discovery-local and may still contain legacy mixed semantics such as a single `entity_constraints` field.

The master spec requires canonical semantic constraints and provider-native constraints to be separated:

```text
canonical_entity_constraints → D4 / canonical applicability
provider_native_constraints  → Step31 / execution validation
```

Step31 therefore consumes a normalized provider-execution candidate contract rather than importing any Host-specific capability DTO.

---

## 6. Binding granularity

Step31 v1 freezes:

```text
1 ExecutionUnit = exactly 1 ProviderBinding
```

An ExecutionUnit may contain multiple canonical targets, but one selected provider implementation MUST bind all of them.

Forbidden:

```text
EU-01
├─ Provider A binds subset A
└─ Provider B binds subset B
```

If no single eligible provider can bind all targets, Step31 fails closed with:

```text
PROVIDER_CANDIDATE_UNAVAILABLE
```

Step31 MUST NOT silently split the Unit. If a future canonical operation legitimately requires mixed-provider execution, that partitionability must be modeled upstream rather than hidden inside late binding.

---

## 7. Frozen public contracts

### 7.1 EligibilityState

The five provider eligibility dimensions use one provider-neutral state enum:

```text
EligibilityState {
  SATISFIED
  UNSATISFIED
  UNKNOWN
}
```

Only `SATISFIED` passes the corresponding Step31 eligibility gate. `UNKNOWN` fails closed.

### 7.2 NativeConstraint

Step31 v1 intentionally supports a minimal deterministic native-constraint language:

```text
NativeConstraintOperator {
  EQ
  IN
}

NativeConstraint {
  field
  operator
  values[]
}
```

For v1, the only generic field is:

```text
native_kind
```

Examples:

```text
native_kind EQ "Wall"
native_kind IN ["LINE", "LWPOLYLINE", "ARC"]
```

The generic core compares opaque strings. It does not understand what an AutoCAD `LWPOLYLINE` or a Revit `Wall` means.

More complex Host-specific editability/parameter/design-option rules SHALL be projected by snapshot producers into explicit eligibility evidence or added later through a separately designed constraint extension. Step31 v1 is not a generic Host rule engine.

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

`host_binding_fingerprint` SHALL be recomputable from the exact persistent HostBinding semantic body:

```text
semantic_id
host_type
document_ref
native_id
native_kind
```

The generic core MUST recompute and verify this fingerprint rather than trusting caller-supplied digest material.

`host_instance_id` is deliberately absent because it is runtime-session identity, not persistent HostBinding identity. Runtime instance identity comes from the parent Step30 `HostRuntimeRef`.

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

- `policy_priority` is a non-negative deterministic integer; smaller values rank first.
- candidate state fields are `EligibilityState`.
- `provider_input_schema` must itself be a valid JSON Schema.
- `candidate_fingerprint` is recomputed by Step31 from the full candidate semantic body.
- candidates are immutable evidence, not caller instructions to force a tool.

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

`valid_until` is REQUIRED in v1 and SHALL be a normalized UTC RFC3339 timestamp.

`snapshot_id` is an opaque provenance identifier and is not semantic hash material.

### 7.6 ProviderPreconditionBinding

Provider-native precondition translation must remain mechanically traceable to every canonical Step30 precondition:

```text
ProviderPreconditionBinding {
  source_precondition_fingerprint
  provider_precondition
}
```

The source fingerprint SHALL be a canonical SHA-256 digest over the exact Step30 `ChangePrecondition` body:

```text
kind
subject_ref
evidence_ref
```

Adapter output MUST contain exactly one ProviderPreconditionBinding for every distinct Step30 precondition fingerprint and no extras.

This proves complete translation coverage. It does not permit the generic core to reinterpret Host-specific precondition semantics.

### 7.7 ProviderBindingMaterial

Adapters return only provider-native transformation material:

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
binding_id
binding_hash
binding_set_hash
canonical_operation
canonical targets
expected_effects
approved scope
provider identity/version
ExecutionGrant
HostCommand
```

Those values are either upstream immutable semantics or generic Step31-owned identity.

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

`binding_expires_at` equals the snapshot `valid_until` in v1.

Future designs MAY add candidate-level/native-binding-level deadlines and derive the minimum deadline, but Step31 v1 does not introduce those additional validity sources.

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

The snapshot refs are immutable provenance metadata. They are deliberately not authorization hash material.

Therefore two resolution records created from different snapshots MAY have the same `binding_set_hash` when the selected providers, native bindings, adapted execution material, and binding expiry are authorization-equivalent.

`binding_set_id` is the semantic authorization identity:

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

`admission_time` is an explicit normalized UTC timestamp used only to evaluate snapshot expiry. It does NOT enter candidate ranking or any Step31 semantic hash.

The resolver MUST NOT read the process wall clock directly. Supplying admission time explicitly preserves deterministic testing and replay.

---

## 8. Snapshot integrity and closed-world rules

Before candidate selection, Step31 MUST verify:

```text
snapshot.execution_slice_id   == slice.execution_slice_id
snapshot.execution_slice_hash == slice.execution_slice_hash
snapshot.host_runtime_ref      == slice.host_runtime_ref
```

Any mismatch returns:

```text
PROVIDER_SLICE_MISMATCH
```

Every NativeTargetBindingEvidence MUST also match the Slice Host type/document and its HostBinding fingerprint must recompute exactly.

### 8.1 Exact native-target coverage

Let:

```text
required_targets = union(slice.execution_units[*].targets)
```

Then:

```text
set(snapshot.native_target_bindings.semantic_id)
==
required_targets
```

Failures:

```text
missing target
→ PROVIDER_NATIVE_BINDING_UNRESOLVED

same semantic_id with duplicate/conflicting binding evidence
→ PROVIDER_NATIVE_BINDING_CONFLICT

semantic_id not required by this Slice
→ PROVIDER_NATIVE_BINDING_EXTRANEOUS
```

Identical duplicate rows are still rejected as conflict; snapshot producers must emit one authoritative binding row per semantic target.

### 8.2 Candidate scope

Alternative candidates are allowed, including candidates that are not selected.

However every candidate's `canonical_operation` MUST match at least one ExecutionUnit canonical operation in the Slice. Completely unrelated candidate rows are invalid snapshot content:

```text
PROVIDER_CANDIDATE_INVALID
```

This keeps ProviderExecutionSnapshot slice/task scoped while still allowing multiple alternatives per operation.

### 8.3 Snapshot hash

Step31 SHALL recompute:

```text
snapshot_hash = SHA256(
  execution_slice_hash
  + host_runtime_ref
  + normalized native target binding evidence
  + normalized provider candidate fingerprints/bodies
  + valid_until
)
```

`snapshot_id` is excluded.

Mismatch returns:

```text
PROVIDER_SNAPSHOT_HASH_MISMATCH
```

If:

```text
admission_time >= valid_until
```

Step31 returns:

```text
PROVIDER_SNAPSHOT_EXPIRED
```

No candidate selection or adapter invocation occurs after an expired snapshot is detected.

---

## 9. Candidate fingerprint

`candidate_fingerprint` SHALL bind at least:

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

Any semantic change to the candidate evidence therefore changes its fingerprint.

Step31 MUST recompute every fingerprint before selection. A supplied digest mismatch or invalid candidate schema returns:

```text
PROVIDER_CANDIDATE_INVALID
```

---

## 10. Deterministic candidate eligibility

For each ExecutionUnit, candidate filtering order is fixed:

```text
1. canonical_operation exact match
2. execution_unit.canonical_operation_version ∈ compatible_operation_versions
3. every provider_native_constraint is satisfied by every native target for the Unit
4. trust_state == SATISFIED
5. compatibility_state == SATISFIED
6. health_state == SATISFIED
7. license_state == SATISFIED
8. certification_state == SATISFIED
```

Policy is already frozen into candidate eligibility evidence and `policy_priority`; Step31 does not live-call a policy engine.

Candidates failing native constraints are filtered. If the snapshot explicitly claims candidates but native constraints eliminate every candidate, the final Unit outcome is:

```text
PROVIDER_CANDIDATE_UNAVAILABLE
```

A specific candidate whose native constraint syntax is invalid returns:

```text
PROVIDER_CANDIDATE_INVALID
```

The separate code:

```text
PROVIDER_NATIVE_CONSTRAINT_UNSATISFIED
```

is reserved for direct validation helpers/tests and diagnostics where a candidate is explicitly checked, not for changing normal multi-candidate fallback semantics.

---

## 11. Deterministic candidate ranking and ambiguity

Eligible candidates rank by:

```text
(
  policy_priority ASC,
  provider_server ASC,
  provider_tool ASC,
  provider_version ASC
)
```

The winner is the unique first semantic provider identity.

### 11.1 Important tie rule

A previous informal sketch included `candidate_fingerprint` inside the ranking key while also describing different fingerprints as an ambiguous tie. Those two statements cannot both be true.

The frozen machine rule is therefore:

- ranking identity excludes `candidate_fingerprint`;
- if two candidate rows have the same ranking identity and the same candidate fingerprint, the snapshot contains a duplicate and is invalid;
- if two candidate rows have the same ranking identity but different candidate fingerprints, the snapshot contains conflicting evidence for the same provider identity/version/priority and resolution fails closed.

Both cases return:

```text
PROVIDER_CANDIDATE_AMBIGUOUS
```

Step31 never resolves such a conflict using discovery order, registration order, random choice, or LLM preference.

---

## 12. No exception-driven provider fallback

After deterministic selection, exactly one selected candidate is passed to its adapter.

If adaptation fails because native material, schema adaptation, or adapter logic cannot produce a valid binding, Step31 returns:

```text
PROVIDER_BINDING_ADAPTATION_FAILED
```

Step31 MUST NOT catch that failure and silently try the next-ranked candidate.

Reason:

```text
snapshot says selected candidate is eligible
        ↓
adapter says it cannot bind
```

This is evidence/adapter inconsistency. Hidden fallback would make runtime exception behavior part of provider selection and would mask bad evidence.

Correct recovery is external:

```text
fail closed
→ refresh provider/native execution evidence
→ rerun Step31
```

---

## 13. ProviderBindingAdapter boundary

### 13.1 Adapter protocol

The generic protocol is:

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

The adapter may perform provider/Host-specific transformation such as:

```text
SemanticId/native binding → native target format
canonical units → provider-native units
canonical arguments → provider input payload
canonical precondition → provider-native precondition representation
provider-native operation variant metadata
```

The generic Step31 package does not understand those transformations.

### 13.2 Adapter registry

Adapters are injected via:

```text
ProviderBindingAdapterRegistry
```

Registry key is `provider_server`.

At most one adapter may be registered for a provider_server in one resolver instance.

Conflicting registration returns:

```text
PROVIDER_ADAPTER_CONFLICT
```

Missing adapter returns:

```text
PROVIDER_ADAPTER_UNAVAILABLE
```

The selected adapter's declared `adapter_version` MUST exactly equal `selected_candidate.input_adapter_version`; mismatch is treated as adapter unavailable/incompatible and fails closed.

The generic core MUST NOT contain branches such as:

```python
if host_type == "AUTOCAD": ...
elif host_type == "REVIT": ...
```

and MUST NOT dynamically import Host packages.

---

## 14. Adapter output integrity gate

After Adapter output, generic Step31 validates all authorization-relevant binding material before hashing.

### 14.1 Native target completeness

The Adapter's `native_targets[]` MUST bind exactly the ExecutionUnit target set:

```text
set(native_targets.semantic_id)
==
set(execution_unit.targets)
```

The Adapter cannot add, remove, substitute, or duplicate semantic targets.

Failure:

```text
PROVIDER_NATIVE_TARGET_MISMATCH
```

Each returned native target MUST equal the already-frozen NativeTargetBindingEvidence for that semantic target. An adapter may reformat provider payload representation, but it cannot select a different native identity than the snapshot evidence.

### 14.2 Canonical semantics are structurally unmodifiable

`ProviderBindingMaterial` contains no fields for:

```text
canonical_operation
canonical targets
expected_effects
approved scope
```

ProviderBinding provider identity/version fields are copied by generic core from the selected candidate rather than supplied by the Adapter.

This makes canonical rewriting structurally unrepresentable through the Adapter API.

### 14.3 Preconditions

For each exact Step30 precondition fingerprint, Adapter output MUST contain exactly one corresponding ProviderPreconditionBinding.

Missing, extra, duplicate, or unknown source fingerprints fail with:

```text
PROVIDER_BINDING_ADAPTATION_FAILED
```

The generic core validates translation coverage, not Host-specific semantic equivalence.

### 14.4 Provider input schema

Adapter `provider_arguments` MUST validate against the selected candidate `provider_input_schema`.

Invalid payload returns:

```text
PROVIDER_INPUT_SCHEMA_INVALID
```

This is distinct from Step29 canonical-argument schema validation:

```text
Step29: canonical arguments → Canonical Action schema
Step31: provider arguments  → provider execution input schema
```

### 14.5 Native binding metadata

`native_binding_metadata` is immutable opaque JSON-like provider material needed to execute the selected implementation but not naturally represented as targets/arguments/preconditions.

Allowed examples include:

```text
parameter binding reference
transaction/native operation variant
provider schema discriminator
```

Forbidden examples include non-semantic runtime noise:

```text
log timestamp
debug trace
request duration
mutable retry state
```

If metadata can change actual execution behavior, it is binding hash material.

---

## 15. Binding expiry

Step31 v1 requires snapshot expiry and freezes:

```text
binding_expires_at = provider_execution_snapshot.valid_until
```

The expiry is authorization-relevant semantic material and therefore enters `binding_hash`.

Consequently, extending or changing the validity window changes:

```text
binding_hash
→ binding_set_hash
→ Step32 must issue a new ExecutionGrant
```

This is intentionally strict in v1.

---

## 16. Hashing model

All Step31 hashes SHALL use canonical JSON + SHA-256 with stable normalized collection ordering.

Construction IDs MUST NOT be substituted for full hashes inside semantic hash bodies.

### 16.1 Host binding fingerprint

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

As defined in §9, candidate fingerprint binds the full normalized candidate semantic body.

### 16.3 ProviderBinding hash

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

### 16.4 Why snapshot hash is excluded from binding_hash

Snapshot hash is input-integrity/provenance evidence, not selected execution identity.

Example:

```text
Candidate A selected
Candidate B unused
Candidate C unused
```

If only unused Candidate C health evidence changes while A, native targets, adapted payload, contracts, and expiry remain unchanged, actual authorized execution material has not changed.

Therefore an unrelated candidate change may change `snapshot_hash` without changing `binding_hash`.

The selected candidate's exact evidence still enters the binding via `selected_candidate_fingerprint`.

### 16.5 binding_set_hash

For one ExecutionSlice:

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

The hash MUST use full 64-character binding hashes, never `PB-<12-char>` construction IDs.

`provider_execution_snapshot_id/hash` are excluded from authorization hash material for the same provenance reason described above.

### 16.6 Hash sensitivity

Any selected execution-material change MUST change binding hash and therefore binding_set_hash, including:

```text
provider server/tool/version
selected candidate fingerprint
adapter version
host instance/document
native target/native kind/native id
provider arguments
provider preconditions
native binding metadata
verification contract
rollback contract
binding expiry
```

Provider switching MUST leave these upstream identities unchanged:

```text
ChangeSet hash
ExecutionUnit hash
ExecutionSlice hash
```

while changing:

```text
ProviderBinding hash
binding_set_hash
```

---

## 17. Stable fail-closed errors

Step31 v1 freezes these machine-readable codes:

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

No error path may silently change provider winner, split an ExecutionUnit, widen target scope, or dispatch a Host command.

---

## 18. Step32 handoff

Step31 outputs one immutable ProviderBindingSet per ExecutionSlice.

Step32 consumes authorization-relevant identity including at least:

```text
execution_slice_id
execution_slice_hash
binding_set_hash
host_instance_id
```

plus governance evidence such as:

```text
ApprovalRecord
changeset_hash
approved_scope_hash
allowed_operations
expires_at
```

Step32 then issues the per-Slice ExecutionGrant.

Step31 MUST NOT:

```text
generate approval_id
inspect approver identity
re-decide approved semantic scope
issue ExecutionGrant
choose allowed_operations
send HostCommand
```

The expected invalidation rule is:

```text
same ChangeSet + same approved scope + changed ProviderBindingSet
        ↓
no repeated user approval
        ↓
old ExecutionGrant invalid
        ↓
new binding_set_hash
        ↓
reissue ExecutionGrant
```

---

## 19. Architecture guards

The Step31 production package SHALL contain no direct import of Host-specific packages or execution/governance runtime packages.

Architecture tests SHALL guard against at least:

```text
autocad_sidecar
Revit SDK/package names
Tekla SDK/package names
HostAdapter
CommandDispatcher
send_command
HostCommand
ApprovalRecord
ExecutionGrant
ActualDelta
Saga
rollback runtime state
retry runtime state
idempotency runtime state
```

The presence of generic contract field names such as `rollback_contract` is allowed; mutable rollback execution ownership is not.

The generic resolver SHALL contain no `host_type == ...` provider-specific branching.

---

## 20. Test matrix

Implementation MUST include focused tests covering at least:

| Category | Required behavior |
|---|---|
| Contracts | frozen DTOs, tuple normalization, defensive mapping copy, digest/timestamp validation |
| Snapshot binding | slice ID/hash/HostRuntimeRef mismatch all fail closed |
| Snapshot hash | caller hash is recomputed; mismatch rejected |
| Snapshot expiry | explicit admission_time before expiry succeeds; at/after expiry rejects |
| Native identity | HostBinding fingerprint recomputed |
| Closed-world native targets | missing/conflict/extraneous all rejected |
| Candidate validity | bad candidate fingerprint/schema/constraint syntax rejected |
| Candidate scope | candidate for unrelated Slice operation rejected |
| Candidate filters | operation version/trust/compatibility/health/license/certification/native constraints filter deterministically |
| Candidate determinism | discovery/input ordering does not affect winner |
| Ranking | policy priority first, then stable provider identity |
| Ambiguity | same provider identity/rank with duplicate or conflicting evidence fails closed |
| Unit granularity | every EU maps to exactly one PB; no partial/multi-provider Unit binding |
| Adapter registry | missing/conflicting adapter rejected; adapter version must match |
| No hidden fallback | selected adapter failure does not try next candidate |
| Target integrity | Adapter cannot add/remove/substitute/duplicate targets |
| Preconditions | exact source-precondition fingerprint coverage required |
| Provider schema | adapted provider arguments must validate |
| Hash determinism | input collection ordering does not alter semantic hashes |
| Binding sensitivity | any selected provider/native/payload/precondition/contracts/expiry change alters binding hash |
| Binding-set sensitivity | any full binding hash change alters binding_set_hash |
| Full-hash rule | binding_set_hash uses full 64-hex binding hashes, not PB construction IDs |
| Unused candidate | unused candidate change may alter snapshot hash but does not alter binding/set hash when winner material and expiry are unchanged |
| Provider switch | ChangeSet/EU/Slice hashes unchanged; PB and binding_set hashes change |
| Step32 boundary | Step31 DTOs contain no approval/grant fields |
| Runtime boundary | no HostCommand/dispatch/retry/ActualDelta/Saga ownership |
| Regression | Step30, Step29, capability/resolver-related existing tests remain GREEN |

---

## 21. Determinism requirements

For the same:

```text
ExecutionSlice semantic body
ProviderExecutionSnapshot semantic body
admission_time validity result
registered adapter implementation/version
```

Step31 MUST produce the same:

```text
selected candidate per Unit
ProviderBinding semantic body
binding_hash
ProviderBindingSet bindings
binding_set_hash
```

The following MUST NOT affect winner selection:

```text
candidate input ordering
native binding input ordering
adapter registration ordering
discovery ordering
randomness
LLM preference
wall-clock lookup inside resolver
exception-driven fallback
```

`admission_time` affects only expiry admission. Any two admission times before the same required `valid_until` produce the same binding semantics.

---

## 22. v1 non-goals and future extensions

Step31 v1 deliberately does not implement:

- live provider discovery or health polling;
- full global Provider Registry infrastructure;
- full HostBinding Resolution Service;
- arbitrary native constraint DSL;
- mixed-provider binding of one ExecutionUnit;
- candidate-level/native-target-level independent expiry deadlines;
- direct MCP invocation;
- HostCommand creation or dispatch;
- approval/grant logic;
- verification/rollback/Saga runtime execution.

These can be added behind the frozen evidence/adapter boundaries without changing the core rule that immutable ExecutionUnit semantics precede provider/native binding.

---

## 23. Final architecture

The frozen Step31 design is:

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
 target/precondition/schema integrity gates
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

The final ownership invariant is:

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

Step31 is complete when it can deterministically prove and hash **how this already-approved canonical execution unit would be implemented**, without changing **what the canonical unit means** and without yet authorizing or performing the Host mutation.
