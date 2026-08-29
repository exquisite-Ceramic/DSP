# Step 29 — Immutable Canonical ChangeSet Design

**Status:** Approved in-chat design; written-spec review pending  
**Date:** 2026-08-29  
**Base:** `main@130d61072ab561ce3fb013433ceca3edd803c0e0`  
**Branch:** `feat/step29-immutable-canonical-changeset`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step 29 introduces the provider-neutral immutable canonical transaction that answers one question:

```text
What exact canonical design mutation is authorized for execution by this frozen planning result and approval-scope body?
```

It does **not** answer:

```text
Which provider/tool executes each operation?
How are operations partitioned into host/document execution slices?
Who approves the transaction?
What policy/risk tier applies?
What execution grant is issued?
What actually changed at runtime?
How is verification/reconciliation/rollback performed?
```

The intended Phase-G flow becomes:

```text
Step 25/26 BoundOperationProposal
        ↓
Step 27 ImpactAnalysis
        ↓
Step 28 ApprovalScopeDefinition
        ↓
Step 29 CanonicalChangeSet
        + changeset_hash
        ↓
Step 28 bind_changeset(...)
        ↓
ApprovalScopeBoundary
        ↓
Step 30 ExecutionSlice / canonical ExecutionUnit
        ↓
Step 31 ProviderBinding
        ↓
Step 32 ApprovalRecord / ExecutionGrant
        ↓
Step 33 Apply / ActualDelta / Verify / ScopeComparator / Saga
```

The central invariant is:

> Step 29 freezes the exact canonical logical transaction. It may consume previously admitted scope, but MUST NOT widen Step 28 authority, infer provider/native behavior, or absorb runtime workflow state.

---

## 2. Master-spec interpretation

The v0.6 master spec describes ChangeSet as a **canonical logical transaction**, not a Host command collection. Its broader DTO sketches also mention future/runtime concepts such as approval, risk, verification, rollback, and status.

Step 29 resolves that breadth by separating:

```text
immutable canonical execution intent
```

from:

```text
workflow / governance / provider / runtime state
```

This is necessary because approval and verification states are expected to change over time while the transaction identity must remain stable.

A ChangeSet hash that changed when an approval moved from `PENDING` to `APPROVED`, or when a verification report arrived, could not serve as a stable approval/execution binding.

Therefore Step 29 SHALL implement the immutable canonical transaction body only. Step 30–33 own the later execution/governance/runtime artifacts.

---

## 3. Chosen package strategy

### 3.1 Chosen: reclaim `platform/changeset`

Step 29 SHALL formally replace the existing Phase-2 HostDelta-centric placeholder under:

```text
platform/changeset/
```

with the canonical v0.6 package:

```text
platform/changeset/
  pyproject.toml
  src/design_changeset/
    __init__.py
    contracts.py
    hashing.py
    builder.py
```

The current legacy files:

```text
platform/changeset/src/changeset/model.py
platform/changeset/src/changeset/builder.py
platform/changeset/src/changeset/execution_slice.py
platform/changeset/src/changeset/execution_unit.py
platform/changeset/src/changeset/verification.py
```

SHALL be removed.

No compatibility shim or alias SHALL expose the old mutable HostDelta ChangeSet as the new canonical ChangeSet.

### 3.2 Why replacement is safe and preferred

The current package is a Phase-2 placeholder whose model is materially different from the v0.6 canonical contract:

- it collects `HostDelta` values;
- it supports mutable builder behavior;
- it imports Host-facing contracts;
- its execution placeholders expose native execution concerns before ProviderBinding;
- it is not currently included in the root pytest pythonpath.

The old model is therefore not a prior version of the same semantic contract. Keeping both would create two incompatible meanings of “ChangeSet”.

### 3.3 Rejected alternatives

Rejected:

```text
platform/canonical_changeset
```

because it would permanently leave two packages representing ChangeSet.

Rejected:

```text
platform/changeset/src/changeset + src/design_changeset
```

because one distribution would continue carrying both HostDelta-centric and canonical transaction semantics.

---

## 4. Ownership boundary

### 4.1 Step 23 owns canonical operation authority

Step 23 remains authoritative for:

```text
canonical operation name
canonical operation version
canonical argument schema
canonical semantic effects
verification contract
```

Step 29 MUST NOT infer effects from operation names, provider capability, natural language, propagation actions, or caller-supplied effect lists.

### 4.2 Step 25/26 owns the bound root proposal

The root mutation instance originates from the exact bound operation produced by D6 / interaction binding.

Step 29 SHALL freeze the material canonical arguments and upstream planning evidence associated with that proposal.

### 4.3 Step 27 owns impact and propagation evidence

Step 29 consumes the exact `ImpactAnalysis` and SHALL NOT recompute dependency traversal, propagation classification, or constraints.

Step 27 `PropagationBundle.proposed_changes[]` remains planning evidence. It is **not** itself a canonical operation.

### 4.4 Step 28 owns the maximum effect scope

Step 29 consumes one immutable `ApprovalScopeDefinition` and may only materialize mutations covered by that definition.

Step 29 MUST NOT add:

```text
new entity authority
new canonical aspects
new propagation bundles
creation/deletion authority
new future-slice scope
```

### 4.5 Step 29 owns final canonical transaction materialization

Step 29 owns:

- root canonical operation materialization;
- explicit derived canonical operation materialization;
- final canonical change causality for v1;
- deterministic precondition obligations;
- deterministic affected-entity projection;
- deterministic semantic-impact projection;
- deterministic validation-task obligations;
- immutable transaction hashing;
- stable `changeset_id` derivation.

### 4.6 Later steps retain later-step authority

Step 30 owns execution partitioning.

Step 31 owns ProviderBinding.

Step 32 owns risk/policy/approval/grant.

Step 33 owns actual deltas, verification results, reconciliation, scope comparison, and saga/compensation runtime behavior.

---

## 5. Canonical operation contract evidence

Step 29 must validate operation instances against the exact Step 23 canonical contract without coupling `design_changeset` to the entire orchestrator implementation package.

The workflow boundary SHALL therefore provide immutable provider-neutral evidence projected from the exact Step 23 definition:

```text
CanonicalOperationContractEvidence {
  canonical_operation
  canonical_operation_version
  argument_schema
  effects[]
  verification_contract
  definition_fingerprint
}
```

Requirements:

- the evidence MUST be assembled from the exact Step 23 `CanonicalOperationDefinition` selected by the workflow;
- `effects[]` MUST exactly equal the normalized Step 23 effects;
- `argument_schema` MUST be the exact canonical input schema required to validate the material arguments;
- `verification_contract` MUST be the exact Step 23 verification contract;
- `definition_fingerprint` MUST be deterministic over the semantic definition body;
- Step 29 SHALL include the relevant definition fingerprint in the semantic operation body so a contract-version semantic change changes transaction identity.

`design_changeset` MUST NOT query provider registries or Host capabilities to manufacture this evidence.

---

## 6. Core public contracts

Step 29 SHALL expose frozen/value-oriented contracts. The exact Python naming MAY be refined during implementation, but the semantic fields below are normative.

### 6.1 `ApprovalScopeDefinitionRef`

```text
ApprovalScopeDefinitionRef {
  scope_definition_id
  scope_body_hash
}
```

`scope_body_hash` is semantic and enters the ChangeSet hash.

`scope_definition_id` is a construction/reference id and does not independently authorize anything.

### 6.2 `CanonicalChangeOperation`

```text
CanonicalChangeOperation {
  operation_id
  origin                   ROOT | DERIVED

  canonical_operation
  canonical_operation_version
  canonical_definition_fingerprint

  targets[]
  arguments
  expected_effects[]

  scope_rule_ids[]
  source
}
```

Normative rules:

- `expected_effects[]` MUST be generated by Step29 from the matched `CanonicalOperationContractEvidence.effects[]`;
- callers MUST NOT be able to override `expected_effects[]`;
- `targets[]` are canonical semantic ids only;
- `arguments` are canonical arguments only;
- provider/native metadata is forbidden;
- `scope_rule_ids[]` identify Step28 rules used to prove coverage, but rule ids themselves are construction references and are normalized to semantic scope coverage in hashing.

### 6.3 Operation origin

```text
OperationOrigin = ROOT | DERIVED
```

Step29 v1 contains exactly one root operation.

### 6.4 `DerivedOperationMaterialization`

This is an input contract, not direct authority:

```text
DerivedOperationMaterialization {
  propagation_bundle_id
  proposed_change_hash

  canonical_operation
  canonical_operation_version
  targets[]
  arguments

  scope_rule_ids[]
}
```

It explicitly connects Step27 planning evidence to a Step23 canonical operation contract.

### 6.5 `ChangeDependency`

```text
ChangeDependency {
  predecessor_operation_id
  successor_operation_id
  reason_ref
}
```

In v1 the only admissible mutation causality is evidence-backed:

```text
ROOT → DERIVED
```

Arbitrary caller-declared `DERIVED → DERIVED` causality is unsupported until an upstream dependency layer emits stable multi-level derived causality.

### 6.6 `ChangePrecondition`

```text
ChangePrecondition {
  kind
  subject_ref
  evidence_ref
}
```

Kinds SHALL be an explicit closed vocabulary derived from upstream machine requirements, for example:

```text
OPERATION_FRESHNESS
COVERAGE
ASSURANCE
```

Free-form precondition policy text is not authoritative.

### 6.7 `SemanticImpactEvidence`

```text
SemanticImpactEvidence {
  source
  affected_semantic_id
  dependency_ref
  propagation_owner
  propagation_action
  requires_verification
}
```

This is a deterministic projection of Step27 predicted impact evidence.

It does **not** grant mutation authority.

### 6.8 `ValidationTask`

```text
ValidationTask {
  validation_task_id
  kind
  subject_semantic_ids[]
  canonical_operation_ref?
  dependency_ref?
  contract_ref
}
```

Validation tasks are obligations describing what later verification must prove. They are not verification results.

### 6.9 `CanonicalChangeSet`

```text
CanonicalChangeSet {
  changeset_id
  task_id
  project_id?

  planning_snapshot_ref
  base_snapshot_set_ref
  semantic_environment_ref

  impact_analysis_fingerprint

  approval_scope_definition_ref

  root_operation
  derived_operations[]
  change_dependencies[]

  preconditions[]
  affected_entities[]
  semantic_impacts[]
  validation_tasks[]

  changeset_hash
}
```

Every nested semantic collection SHALL be immutable and deterministically normalized.

---

## 7. Exactly one root operation in v1

The master spec sketches plural root operations, but the current Step25 → Step27 → Step28 pipeline is constructed around one bound operation and one impact analysis.

Supporting multiple root operations now would require a separate design for:

```text
multiple ImpactAnalysis composition
scope union/intersection semantics
cross-root causality
multi-root validation obligations
batch-level argument/snapshot compatibility
```

These are not Step29 v1 concerns.

Therefore:

```text
len(root_operations) == 1
```

is represented directly as one `root_operation` field.

Future batching may introduce a higher-level transaction composer without changing the meaning of one canonical operation node.

---

## 8. Root operation materialization

The root operation SHALL be deterministically materialized from:

```text
BoundOperationProposal
+ matching ImpactAnalysis
+ exact CanonicalOperationContractEvidence
+ ApprovalScopeDefinition
```

Step29 SHALL verify at minimum:

```text
bound operation name/version
    == ImpactAnalysis canonical operation identity

bound planning snapshot
    == ImpactAnalysis planning snapshot

bound semantic environment
    == ImpactAnalysis semantic environment

root targets
    == ImpactAnalysis direct targets

canonical definition name/version
    == bound operation name/version

arguments
    satisfy exact canonical argument schema
```

A deterministic `bound_operation_hash` SHALL be computed from the material canonical proposal body and its planning/environment evidence.

The root operation source evidence SHALL include that fingerprint.

Changing canonical arguments while keeping the same ImpactAnalysis MUST change the final ChangeSet hash.

---

## 9. Derived operation materialization is explicit

### 9.1 PropagationBundle is not a canonical action

Step27 `PropagationBundle.proposed_changes[]` contains structured planning descriptions but does not provide a canonical operation name/version/argument contract.

Step29 MUST NOT infer a canonical operation from:

```text
RECOMPUTE
AUTO_MUTATE
REVALIDATE
rule_ref
dependency_ref
arbitrary proposed_changes keys
natural language
```

### 9.2 Dual binding

Every derived operation SHALL be bound to both:

1. exact Step27 propagation proposal evidence; and
2. exact Step23 canonical operation contract evidence.

The builder SHALL verify:

```text
propagation_bundle_id
  ∈ exact ImpactAnalysis.propagation_bundles

proposed_change_hash
  ∈ exact selected bundle.proposed_changes[]

canonical operation/version
  resolves to exact supplied Step23 contract evidence

arguments
  satisfy that exact canonical schema

targets + contract effects
  are fully covered by ApprovalScopeDefinition
```

### 9.3 Proposed-change fingerprinting

Each Step27 proposed change mapping SHALL be canonical-JSON normalized and hashed independently:

```text
proposed_change_hash = SHA-256(canonical_json(proposed_change_body))
```

A `proposed_change_hash` may be materialized at most once.

Unknown or duplicate proposal references fail closed.

### 9.4 Required completeness

For every Step28-admitted deterministic platform mutation proposal:

```text
exactly one derived materialization is required
```

Step29 MUST reject a transaction that silently drops an admitted deterministic mutation or materializes the same proposal twice.

Advisory-only impacts and Host-native verification-only impacts do not become derived mutation nodes merely because they appear in `affected_entities`.

---

## 10. Step28 scope coverage

### 10.1 Explicit-entity authority only in v1

Step28 supports both explicit entity selectors and a restricted predicate selector. Step29 v1 does not own a snapshot-bound predicate evaluator.

Therefore mutation materialization SHALL only use Step28 rules whose selector explicitly enumerates the target semantic id.

Predicate-only membership cannot be accepted based on caller assertion.

Failure code:

```text
CHANGESET_SCOPE_MEMBERSHIP_UNRESOLVED
```

### 10.2 Full effect coverage

For every materialized operation and every target:

```text
expected_effects
  ⊆ union(allowed_aspects of explicit Step28 rules covering that target)
```

Coverage may be provided by more than one explicit rule, but it must be complete.

Example:

```text
MOVE WALL-001
expected_effects = {PLACEMENT, GEOMETRY}
```

If Step28 authorizes only:

```text
WALL-001 -> {PLACEMENT}
```

Step29 MUST fail with:

```text
CHANGESET_SCOPE_EFFECT_EXCEEDED
```

### 10.3 Scope cannot be widened

Step29 MUST NOT:

- add entities to a selector;
- add aspects to any existing rule;
- convert predicate scope into explicit permission by assertion;
- activate Step28 creation/deletion rules unsupported in v1;
- add propagation bundles not already admitted.

---

## 11. Creation and deletion remain unsupported in v1

Step28 v1 already rejects non-empty creation/deletion authority because the current Step23 contract does not expose typed canonical existence-effect authority.

Step29 SHALL preserve that restriction.

No Step29 caller may materialize a CREATE/DELETE mutation by encoding it as a generic derived operation while bypassing Step28's existence-effect restriction.

If a future Step23 contract introduces typed create/delete authority, Step28 must first activate matching scope rules before Step29 may consume them.

---

## 12. Change DAG

### 12.1 Impact graph and Change DAG are distinct

Step27 predicts impact and propagation.

Step29 freezes actual canonical mutation causality.

Only materialized canonical operations are mutation DAG nodes.

Predicted impacts requiring verification are not automatically mutation nodes.

### 12.2 v1 admissible edges

Step29 v1 SHALL allow only evidence-backed:

```text
ROOT → DERIVED
```

where the derived operation is explicitly tied to a propagation bundle/proposal caused by the root planning result.

Caller-declared arbitrary:

```text
DERIVED → DERIVED
```

edges SHALL fail closed in v1.

### 12.3 Structural validity

The builder SHALL reject:

- unknown operation ids in edges;
- self edges;
- duplicate semantic edges;
- cycles;
- edges not supported by v1 causality rules.

Even though v1 restrictions make cycles difficult to construct, cycle validation remains an explicit invariant.

---

## 13. Preconditions

Step29 preconditions are deterministic projections of upstream machine requirements, not policy text.

Examples include:

```text
OPERATION_FRESHNESS
COVERAGE
ASSURANCE
```

SnapshotSet and SemanticEnvironment identity are top-level transaction bindings and SHALL NOT be weakened into optional precondition text.

Precondition normalization SHALL be deterministic and included in `changeset_hash`.

---

## 14. Affected entities and semantic impacts

### 14.1 `affected_entities[]`

The affected entity set SHALL be the deterministic union of:

```text
ImpactAnalysis.direct_targets
+
all predicted affected semantic ids
```

This list is evidence/reporting scope, not mutation authority.

An entity may be affected or require verification without being a mutation target.

### 14.2 `semantic_impacts[]`

`semantic_impacts[]` SHALL be a normalized immutable projection of the Step27 predicted impacts used by this transaction.

It SHALL preserve machine fields such as:

```text
source
affected entity
dependency_ref
propagation owner/action
requires_verification
```

It MUST NOT convert impact evidence into permission.

---

## 15. Validation tasks

Validation tasks SHALL be generated deterministically from machine contracts, including:

```text
root CanonicalOperationContractEvidence.verification_contract
derived CanonicalOperationContractEvidence.verification_contract
PredictedImpact.requires_verification
```

A Step23 MOVE verification contract may therefore create a root read-back obligation.

A Host-native predicted impact with `requires_verification=true` may create a dependency revalidation/read-back obligation without creating a derived mutation operation.

Step29 SHALL only define the obligation.

Actual verification execution/results belong to Step33.

Construction ids such as `validation_task_id` SHALL be deterministically derived from semantic task fingerprints and excluded as independent entropy from the ChangeSet semantic hash.

---

## 16. Snapshot and environment binding

The ChangeSet SHALL carry exact:

```text
planning_snapshot_ref
base_snapshot_set_ref
semantic_environment_ref
```

The builder SHALL revalidate upstream consistency instead of trusting that previous steps already did so.

At minimum:

```text
BoundOperationProposal planning/environment
  == ImpactAnalysis planning/environment

ImpactAnalysis planning/snapshot/environment
  == ApprovalScopeDefinition planning/snapshot/environment
```

Any mismatch fails closed.

This prevents mixing a valid bound operation, impact result, and scope body from different semantic worlds.

---

## 17. Impact and scope binding

Step29 SHALL require:

```text
ImpactAnalysis.analysis_fingerprint
  == ApprovalScopeDefinition.impact_analysis_fingerprint
```

The ChangeSet semantic body SHALL include:

```text
impact_analysis_fingerprint
scope_body_hash
```

`scope_definition_id` may be carried as a human/reference id but MUST NOT substitute for the semantic `scope_body_hash`.

---

## 18. ChangeSet hashing

### 18.1 Canonical hash function

Step29 SHALL use deterministic canonical JSON and SHA-256:

```text
changeset_hash = SHA-256(canonical_json(semantic_changeset_body))
```

Canonical JSON SHALL use stable key ordering, compact separators, UTF-8, normalized enums/tuples/mappings, and deterministic collection ordering where semantic order is not meaningful.

### 18.2 Semantic hash body

The semantic body SHALL include at least:

```text
task_id
project_id?

planning_snapshot_ref
base_snapshot_set_ref
semantic_environment_ref

impact_analysis_fingerprint
scope_body_hash

root operation semantic body
derived operation semantic bodies
change dependency semantic bodies

preconditions
affected_entities
semantic_impacts
validation_tasks
```

Each operation semantic body SHALL include:

```text
origin
canonical operation/version
canonical definition fingerprint
targets
canonical arguments
expected effects
semantic source evidence
semantic scope coverage
```

### 18.3 Construction ids excluded

The following SHALL NOT add independent entropy to `changeset_hash`:

```text
changeset_id
operation_id
scope_definition_id
validation_task_id
```

When such ids are referenced by another semantic object, hashing SHALL resolve them to the corresponding semantic fingerprint/meaning rather than raw opaque id text.

### 18.4 Changes that must change the hash

Any material change to the following MUST change `changeset_hash`:

```text
canonical operation/version
canonical contract semantic definition
canonical arguments
targets
derived materialization
Change DAG causality
PlanningSnapshot
SnapshotSet
SemanticEnvironment
ImpactAnalysis fingerprint
scope_body_hash
preconditions
validation obligations
```

### 18.5 Stable construction ids

Recommended deterministic ids:

```text
changeset_id = "CS-" + changeset_hash[:12]
operation_id = "COP-" + operation_hash[:12]
validation_task_id = "VT-" + validation_task_hash[:12]
```

UUID/random identity SHALL NOT determine semantic transaction identity.

---

## 19. No final ApprovalScopeBoundary inside the ChangeSet

The ChangeSet SHALL carry only the frozen Step28 definition reference:

```text
scope_definition_id
scope_body_hash
```

It MUST NOT contain final:

```text
ApprovalScopeBoundary.scope_hash
```

as part of its own hash body.

The correct order remains:

```text
ApprovalScopeDefinition
        ↓
CanonicalChangeSet
+ changeset_hash
        ↓
bind_changeset(scope_definition, changeset_hash)
        ↓
ApprovalScopeBoundary
+ scope_hash
```

Including final `scope_hash` in the ChangeSet semantic body would create a circular dependency because Step28 final `scope_hash` itself binds `changeset_hash`.

---

## 20. Step28 pure-bind compatibility

A successfully built `CanonicalChangeSet` MUST be directly bindable through the existing Step28 pure function:

```text
bind_changeset(
    approval_scope_definition,
    canonical_changeset.changeset_hash,
    scope_id,
)
```

Step29 tests SHALL prove that binding:

- succeeds for a valid lowercase SHA-256 hash;
- leaves the frozen Step28 semantic body unchanged;
- only adds the final ChangeSet binding and derived final scope hash.

Step29 MUST NOT add a second scope-binding implementation.

---

## 21. Step30 input contract

Step30 SHALL consume exactly:

```text
CanonicalChangeSet
+
ApprovalScopeBoundary
```

and SHALL first validate:

```text
ApprovalScopeBoundary.changeset_hash
  == CanonicalChangeSet.changeset_hash

ApprovalScopeBoundary.scope_body_hash
  == CanonicalChangeSet.approval_scope_definition_ref.scope_body_hash
```

Step30 SHALL NOT rebuild the transaction from D6, Step27, or Step28 planner requests.

The responsibility split is:

```text
Step29: what canonical mutation exists
Step30: how that immutable mutation is partitioned for execution
Step31: which provider binds each canonical execution unit
```

---

## 22. Fields explicitly excluded from Step29

The Step29 production contract MUST NOT contain or import runtime authority for:

```text
provider_tool
provider_id
input_adapter_version
binding_set_hash

host_instance_id
native_id
AutoCAD Handle
Revit ElementId
native/internal units

approval_id
approver
approval tier
policy_snapshot_hash
risk tier
ExecutionGrant

execution_slice_id
execution_unit_id

ActualDelta
VerificationReport
rollback command
saga runtime state

mutable workflow status
```

Workflow/runtime status SHALL be stored separately and associated by stable transaction identity, for example:

```text
changeset_hash -> workflow/checkpoint state
```

rather than mutating the ChangeSet.

---

## 23. Builder request

The Step29 builder input SHALL be semantically equivalent to:

```text
ChangeSetBuildRequest {
  task_id
  project_id?

  bound_operation
  impact_analysis
  approval_scope_definition

  canonical_operation_definitions[]
  derived_materializations[]
}
```

For package-boundary purposes, `canonical_operation_definitions[]` SHALL be supplied as the immutable `CanonicalOperationContractEvidence` projection defined in §5, assembled from exact Step23 definitions outside the package.

The builder SHALL not accept caller-provided:

```text
expected_effects
changeset_hash
final scope_hash
provider bindings
approval state
runtime verification results
```

---

## 24. Required cross-input validation

Before producing a ChangeSet, the builder SHALL revalidate all authority-bearing joins.

At minimum:

```text
bound_operation operation/version
  == impact_analysis operation/version

bound_operation planning/environment
  == impact_analysis planning/environment

impact_analysis planning/snapshot/environment
  == approval_scope_definition planning/snapshot/environment

impact_analysis.analysis_fingerprint
  == approval_scope_definition.impact_analysis_fingerprint

root targets
  == impact_analysis.direct_targets

root canonical contract
  == exact operation/version selected by bound operation

root expected effects
  == canonical contract effects

all mutation targets/effects
  ⊆ explicit Step28 entity/effect authority

all derived bundle/proposal refs
  ∈ exact ImpactAnalysis

all Step28-admitted deterministic mutation proposals
  are materialized exactly once
```

A builder SHALL fail closed on ambiguity rather than silently repairing mismatched inputs.

---

## 25. Error contract

Step29 SHALL expose one stable domain exception:

```text
ChangeSetError(code, message)
```

The machine `code` is workflow-significant.

The initial required code vocabulary is:

```text
CHANGESET_INPUT_INVALID
CHANGESET_SNAPSHOT_MISMATCH
CHANGESET_SEMANTIC_ENVIRONMENT_MISMATCH
CHANGESET_IMPACT_MISMATCH
CHANGESET_SCOPE_MISMATCH

CHANGESET_CANONICAL_OPERATION_UNKNOWN
CHANGESET_CANONICAL_OPERATION_VERSION_MISMATCH
CHANGESET_ARGUMENTS_INVALID
CHANGESET_TARGET_MISMATCH

CHANGESET_DERIVED_BUNDLE_UNKNOWN
CHANGESET_DERIVED_PROPOSAL_UNKNOWN
CHANGESET_DERIVED_PROPOSAL_DUPLICATE
CHANGESET_DERIVED_MATERIALIZATION_MISSING
CHANGESET_DERIVED_OPERATION_INVALID

CHANGESET_SCOPE_MEMBERSHIP_UNRESOLVED
CHANGESET_SCOPE_EFFECT_EXCEEDED

CHANGESET_DAG_INVALID
CHANGESET_HASH_INVALID
```

Raw `ValueError`, jsonschema exceptions, or implementation-specific exceptions SHALL NOT be the public workflow decision contract.

---

## 26. Architecture constraints

The `design_changeset` production package MUST remain provider-neutral.

Architecture tests SHALL prove that it does not depend on:

```text
host_contracts
hosts.*
providers.*
HostCommand
HostDelta
ProviderBinding
ExecutionGrant
ApprovalRecord
ActualDelta
Host-native identifiers
```

It MUST NOT define production Step30 `ExecutionSlice` / `ExecutionUnit` implementations or Step33 verifier/saga implementations.

The package SHALL expose an explicit public `__all__`.

All public transaction/value DTOs SHALL be immutable/frozen and shall normalize mutable caller containers into immutable value structures.

---

## 27. Legacy placeholder removal guard

Step29 SHALL include a repository-level migration test proving that the old Phase-2 placeholder files no longer exist:

```text
platform/changeset/src/changeset/model.py
platform/changeset/src/changeset/builder.py
platform/changeset/src/changeset/execution_slice.py
platform/changeset/src/changeset/execution_unit.py
platform/changeset/src/changeset/verification.py
```

`platform/changeset/pyproject.toml` SHALL remove the HostDelta-centric dependency on:

```text
host-contracts
```

The root `pyproject.toml` SHALL add:

```text
platform/changeset/src
```

to pytest's active pythonpath.

---

## 28. TDD acceptance criteria

Implementation SHALL use RED → GREEN cycles covering at least the following behavior.

### 28.1 Contracts and immutability

1. missing new package/API is RED before implementation;
2. public DTOs are frozen/value-oriented;
3. mutable input containers are normalized into immutable internal values;
4. public `__all__` is explicit.

### 28.2 Hashing

5. equivalent semantic inputs with different non-semantic ordering produce the same `changeset_hash`;
6. canonical argument change changes hash;
7. snapshot/environment change changes hash;
8. `scope_body_hash` change changes hash;
9. opaque construction ids do not independently change hash.

### 28.3 Root canonical contract

10. operation/version mismatch is rejected;
11. canonical arguments are validated against the exact Step23-derived schema evidence;
12. expected effects come from canonical contract evidence, not caller input;
13. root target mismatch with ImpactAnalysis is rejected.

### 28.4 Derived materialization

14. unknown propagation bundle is rejected;
15. unknown `proposed_change_hash` is rejected;
16. duplicate proposal materialization is rejected;
17. admitted deterministic proposal missing materialization is rejected;
18. Host-native verification-only impact does not become a derived mutation;
19. advisory-only impact does not create permission or a derived mutation.

### 28.5 Scope

20. direct/derived target outside explicit entity authority is rejected;
21. effect outside Step28 allowed aspects is rejected;
22. predicate-only scope membership is rejected in v1;
23. Step29 cannot activate creation/deletion authority.

### 28.6 Change DAG

24. evidence-backed `ROOT → DERIVED` is valid;
25. arbitrary `DERIVED → DERIVED` is rejected in v1;
26. unknown/self/cyclic edge is rejected.

### 28.7 Evidence projections

27. `affected_entities` is the deterministic union of direct and predicted affected entities;
28. semantic impacts remain evidence and do not authorize mutation;
29. verification tasks are generated deterministically from canonical verification contracts and `requires_verification` evidence.

### 28.8 Step28 integration

30. generated `changeset_hash` binds successfully through Step28 `bind_changeset()`;
31. Step28 scope semantic body is unchanged after binding;
32. final boundary binds exactly the produced ChangeSet hash.

### 28.9 Migration and architecture

33. legacy HostDelta ChangeSet files are removed;
34. `host-contracts` dependency is removed from `platform/changeset`;
35. architecture guard proves no host/provider/native leakage;
36. Step29 does not own Step30/31/32/33 runtime artifacts.

### 28.10 Regression gates

37. Step28 focused regression remains green;
38. Step27 focused regression remains green;
39. Step25/26 relevant regression remains green;
40. Ruff remains green;
41. full repository pytest remains green.

---

## 29. CI boundary

Step29 SHALL add a focused GitHub Actions workflow, recommended name:

```text
.github/workflows/step29-immutable-changeset.yml
```

The workflow SHALL trigger on Step29 package/tests/docs/root-pythonpath paths and run:

1. Step29 diff-boundary validation;
2. Step29 contract tests;
3. Step29 hashing tests;
4. Step29 builder tests;
5. Step29 architecture/migration tests;
6. Step28 regressions;
7. Step27 regressions;
8. Step25/26 relevant regressions;
9. existing D4→D5 freshness bridge where required by the repository regression baseline;
10. Ruff;
11. full repository pytest.

The focused CI SHALL not claim success if full repository regression or lint is skipped after a prior failure unless the failing root cause is fixed and a fresh head run completes all required gates.

---

## 30. Non-goals

Step29 v1 deliberately does not implement:

- multiple root-operation batching;
- predicate selector evaluation;
- CREATE/DELETE canonical existence effects;
- provider selection or capability negotiation;
- provider input adaptation;
- host/document execution slicing;
- approval policy evaluation;
- approval records or execution grants;
- actual delta capture;
- verification result evaluation;
- rollback/compensation/saga execution;
- mutable workflow status inside the ChangeSet;
- caller-authored semantic effects.

These are intentionally deferred to the contract owner identified elsewhere in Phase G.

---

## 31. Security and fail-closed posture

Step29 SHALL treat all cross-step joins as authority-sensitive.

It MUST fail closed if it cannot prove:

```text
this bound operation
belongs to this impact analysis
which belongs to this frozen scope body
and every mutation node
is an exact canonical contract instance
fully covered by explicit approved effect authority
```

No fallback inference SHALL widen authority.

Specifically forbidden fallbacks include:

```text
infer an operation from propagation action text
infer target membership from a predicate without evaluation
trust caller-provided expected_effects
trust caller-provided changeset_hash
silently omit an admitted deterministic derived mutation
silently duplicate a propagation proposal
silently accept mismatched snapshots/environments
```

---

## 32. Final design invariants

Step29 is complete only when all of the following are true:

1. there is exactly one canonical meaning of ChangeSet in `platform/changeset`;
2. the ChangeSet is immutable from creation;
3. one root operation is frozen from the bound D6 proposal;
4. derived operations are explicitly tied to both Step27 proposal evidence and Step23 canonical contract evidence;
5. expected effects are generated from canonical contract authority, never caller-authored;
6. all mutation targets/effects are fully covered by Step28 explicit-entity rules;
7. predicate-only membership is fail-closed in v1;
8. admitted deterministic derived mutations are materialized exactly once;
9. Change DAG v1 only admits evidence-backed `ROOT → DERIVED` causality;
10. affected/impact/validation data remain evidence and obligations, not permission expansion;
11. `changeset_hash` is deterministic over semantic transaction identity;
12. construction ids do not alter semantic identity;
13. final `ApprovalScopeBoundary.scope_hash` is not part of the ChangeSet hash, avoiding circular binding;
14. the produced hash binds through Step28's existing pure binder without changing scope body;
15. Step30 receives only `CanonicalChangeSet + ApprovalScopeBoundary` as the execution-planning boundary;
16. no Host/provider/native/approval/runtime state leaks into the canonical ChangeSet;
17. the old HostDelta-centric ChangeSet placeholder and dependency are removed;
18. focused tests, architecture guards, lint, and full repository regression remain green.

---

## 33. Review gate

This written spec was produced from three design sections explicitly approved in chat on 2026-08-29.

No production implementation plan or Step29 code should begin until this written spec has been reviewed for consistency with:

```text
master spec v0.6
Step23 canonical action authority
Step25/26 BoundOperationProposal
Step27 ImpactAnalysis / PropagationBundle
Step28 ApprovalScopeDefinition / bind_changeset
legacy platform/changeset migration boundary
Step30–33 ownership boundaries
```

After written-spec approval, the next artifact SHALL be the Step29 implementation plan, followed by TDD execution on this branch.