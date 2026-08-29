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

Step 29 separates:

```text
immutable canonical execution intent
```

from:

```text
workflow / governance / provider / runtime state
```

This is required because approval and verification state can change over time while the transaction identity must remain stable.

A ChangeSet hash that changed when an approval moved from `PENDING` to `APPROVED`, or when a verification report arrived, could not be a stable approval/execution binding.

Therefore Step 29 SHALL implement only the immutable canonical transaction body. Step 30–33 own later execution/governance/runtime artifacts.

---

## 3. Chosen package strategy

### 3.1 Chosen: reclaim `platform/changeset`

Step 29 SHALL formally replace the existing Phase-2 HostDelta-centric placeholder under:

```text
platform/changeset/
```

with:

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

### 3.2 Why replacement is preferred

The current package is materially different from the v0.6 canonical contract:

- it collects `HostDelta` values;
- it supports mutable builder behavior;
- it imports Host-facing contracts;
- its execution placeholders expose native concerns before ProviderBinding;
- it is not currently included in the root pytest pythonpath.

The old model is not a prior version of the same semantic contract. Keeping both would create two incompatible meanings of “ChangeSet”.

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

Step 29 SHALL freeze the material canonical arguments and exact D6 evidence projection associated with that proposal.

### 4.3 Step 27 owns impact and propagation evidence

Step 29 consumes the exact `ImpactAnalysis` and SHALL NOT recompute dependency traversal, propagation classification, or constraints.

Step27 `PropagationBundle.proposed_changes[]` is planning evidence. It is **not** itself a canonical operation.

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
- stable construction-id derivation.

### 4.6 Later steps retain later-step authority

Step 30 owns execution partitioning.

Step 31 owns ProviderBinding.

Step 32 owns risk/policy/approval/grant.

Step 33 owns actual deltas, verification results, reconciliation, scope comparison, and saga/compensation runtime behavior.

---

## 5. Provider-neutral upstream evidence projections

Step29 needs exact Step23 and D6 evidence, but the canonical ChangeSet package should not depend on provider/native code or query the orchestrator Catalog at runtime.

The workflow boundary SHALL assemble small immutable provider-neutral evidence values from the exact already-selected upstream objects.

### 5.1 `CanonicalOperationContractEvidence`

Projected from the exact Step23 `CanonicalOperationDefinition`:

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

- `effects[]` exactly equals the normalized Step23 effects;
- `argument_schema` is the exact Step23 canonical input schema;
- `verification_contract` is the exact Step23 verification contract;
- `definition_fingerprint` is deterministic over the semantic definition body;
- Step29 includes the definition fingerprint in the operation semantic body;
- no provider schema or capability profile may manufacture this evidence.

### 5.2 `BoundOperationEvidence`

Projected from the exact D6 `BoundOperationProposal`:

```text
BoundOperationEvidence {
  canonical_operation
  canonical_operation_version
  arguments

  context_snapshot_id
  context_snapshot_hash
  document_ref
  semantic_environment_id

  binding_evidence
  bound_operation_fingerprint
  bound_operation_evidence_fingerprint
}
```

`bound_operation_fingerprint` is the Step27/Step29 shared **material-operation** fingerprint defined in §6.

`bound_operation_evidence_fingerprint` is a Step29 semantic/audit fingerprint over the complete provider-neutral D6 projection, including binding evidence and context-snapshot evidence.

Step29 does not treat the D6 ContextSnapshot as the same object as Step27 `PlanningSnapshotBinding`; only the required cross-links in §9 are compared.

---

## 6. Review-discovered prerequisite: verifiable D6 → Step27 binding

### 6.1 The existing gap

The current Step27 `analysis_fingerprint` correctly commits to:

```text
canonical operation
operation version
material canonical arguments
PlanningSnapshot
SnapshotSet
SemanticEnvironment
impact inputs
IntentBoundary
```

However the current public `ImpactAnalysis` output exposes only:

```text
canonical_operation
direct_targets
planning_snapshot_ref
snapshot_set_ref
semantic_environment_ref
...
analysis_fingerprint
```

It does **not** expose a separately verifiable fingerprint for the exact bound operation material that produced the analysis.

Therefore a later Step29 caller could present:

```text
same canonical operation
same targets
different displacement/other material argument
old ImpactAnalysis
```

and Step29 could not prove the mismatch without recomputing Step27 from its full original request.

Step29 MUST NOT recompute Step27.

### 6.2 Required Step27 hardening

Step29 implementation SHALL make the minimal upstream contract hardening:

```text
ImpactAnalysis {
  ...
  bound_operation_fingerprint
  analysis_fingerprint
}
```

The shared material-operation fingerprint is:

```text
bound_operation_fingerprint = SHA-256(
  canonical_json({
    canonical_operation,
    canonical_operation_version,
    arguments
  })
)
```

where `arguments` are the fully bound provider-neutral canonical arguments from D6.

Step27 SHALL compute this value from the exact `BoundOperationProposal` it analyzes.

Step29 SHALL recompute the same value from `BoundOperationEvidence` and require exact equality.

Failure:

```text
CHANGESET_IMPACT_MISMATCH
```

### 6.3 Existing Step27 `analysis_fingerprint` remains stable

This hardening SHALL NOT change the semantic payload/algorithm of the existing Step27 `analysis_fingerprint` for equivalent input.

The new field simply exposes a verifiable sub-binding that Step27 already semantically commits to.

This prevents unnecessary Step27/Step28 fingerprint churn while making Step29's authority-sensitive join provable.

The Step27 written design SHALL be amended during Step29 implementation to record this binding field.

---

## 7. Core public contracts

All public Step29 value contracts SHALL be frozen/immutable and defensively normalize mutable caller containers.

### 7.1 `ApprovalScopeDefinitionRef`

```text
ApprovalScopeDefinitionRef {
  scope_definition_id
  scope_body_hash
}
```

`scope_body_hash` is semantic and enters the ChangeSet hash.

`scope_definition_id` is a construction/reference id and does not independently authorize anything.

### 7.2 `OperationSourceEvidence`

```text
OperationSourceEvidence {
  source_kind              ROOT_BOUND_OPERATION | DERIVED_PROPAGATION
  source_fingerprint

  propagation_bundle_id?
  proposed_change_hash?
}
```

For ROOT, `source_fingerprint` is the complete `bound_operation_evidence_fingerprint`.

For DERIVED, the source binds the exact Step27 bundle/proposal fingerprint.

### 7.3 `CanonicalChangeOperation`

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
  source_evidence
}
```

Normative rules:

- `expected_effects[]` is generated from matched `CanonicalOperationContractEvidence.effects[]`;
- callers cannot override `expected_effects[]`;
- `targets[]` are canonical semantic ids only;
- `arguments` are canonical arguments only;
- provider/native metadata is forbidden;
- raw scope-rule construction ids do not add independent semantic entropy to hashing.

### 7.4 `DerivedOperationMaterialization`

Input contract only; not authority:

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

### 7.5 `ChangeDependency`

```text
ChangeDependency {
  predecessor_operation_id
  successor_operation_id
  reason_ref
}
```

Step29 v1 admits only evidence-backed:

```text
ROOT → DERIVED
```

Arbitrary caller-authored `DERIVED → DERIVED` causality is unsupported.

### 7.6 `ChangePrecondition`

```text
ChangePrecondition {
  kind
  subject_ref
  evidence_ref
}
```

Kinds use an explicit closed vocabulary projected from machine requirements, initially including:

```text
OPERATION_FRESHNESS
COVERAGE
ASSURANCE
```

### 7.7 `SemanticImpactEvidence`

```text
SemanticImpactEvidence {
  source_semantic_id
  affected_semantic_id
  dependency_ref
  propagation_owner
  propagation_action
  requires_verification
}
```

This is a deterministic projection of Step27 `PredictedImpact` and does not grant mutation authority.

### 7.8 `ValidationTask`

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

Validation tasks are future verification obligations, not results.

### 7.9 `CanonicalChangeSet`

```text
CanonicalChangeSet {
  changeset_id
  task_id
  project_id?

  planning_snapshot_ref
  snapshot_set_ref
  semantic_environment_ref

  impact_analysis_fingerprint
  bound_operation_fingerprint

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

Every nested semantic collection is immutable and deterministically normalized.

---

## 8. Exactly one root operation in v1

The master spec sketches plural root operations, but the current Step25 → Step27 → Step28 pipeline is constructed around one bound operation and one impact analysis.

Supporting multiple root operations now would require a separate design for:

```text
multiple ImpactAnalysis composition
scope union/intersection semantics
cross-root causality
multi-root validation obligations
batch-level snapshot compatibility
```

Therefore Step29 v1 has exactly one `root_operation`.

Future batching may introduce a higher-level transaction composer without changing the meaning of one canonical operation node.

---

## 9. Root operation materialization and cross-input validation

The root operation is deterministically materialized from:

```text
BoundOperationEvidence
+ ImpactAnalysis
+ CanonicalOperationContractEvidence
+ ApprovalScopeDefinition
```

Step29 SHALL verify at minimum:

```text
BoundOperationEvidence.canonical_operation
  == ImpactAnalysis.canonical_operation

BoundOperationEvidence.bound_operation_fingerprint
  == ImpactAnalysis.bound_operation_fingerprint

BoundOperationEvidence.semantic_environment_id
  == ImpactAnalysis.semantic_environment_ref.environment_id

BoundOperationEvidence.document_ref
  == ImpactAnalysis.planning_snapshot_ref.document_ref

normalized BoundOperationEvidence.arguments["targets"]
  == ImpactAnalysis.direct_targets

BoundOperationEvidence.canonical_operation
  == ApprovalScopeDefinition.canonical_effect_evidence.canonical_operation

BoundOperationEvidence.canonical_operation_version
  == ApprovalScopeDefinition.canonical_effect_evidence.canonical_operation_version

CanonicalOperationContractEvidence operation/version
  == BoundOperationEvidence operation/version

normalized CanonicalOperationContractEvidence.effects
  == ApprovalScopeDefinition.canonical_effect_evidence.allowed_aspects

BoundOperationEvidence.arguments
  satisfy exact canonical argument schema
```

Important distinction:

```text
D6 ContextSnapshot id/hash
!= Step27 PlanningSnapshot id/hash by definition
```

Step29 SHALL NOT compare those ids/hashes for equality. Their document/environment cross-links and their own fingerprints are bound separately.

Changing material canonical arguments changes `bound_operation_fingerprint` and therefore cannot reuse the prior ImpactAnalysis.

---

## 10. Step27 / Step28 planning-state consistency

Step29 SHALL revalidate the exact fields already frozen in Step28:

```text
ImpactAnalysis.planning_snapshot_ref
  == ApprovalScopeDefinition.planning_snapshot_ref

ImpactAnalysis.snapshot_set_ref
  == ApprovalScopeDefinition.snapshot_set_ref

ImpactAnalysis.semantic_environment_ref
  == ApprovalScopeDefinition.semantic_environment_ref

ImpactAnalysis.analysis_fingerprint
  == ApprovalScopeDefinition.impact_analysis_fingerprint
```

It SHALL also require the planning snapshot to remain a member of the supplied `SnapshotSetBinding` and all planning/snapshot environment bindings to refer to the same semantic environment.

Any mismatch fails closed.

---

## 11. Derived operation materialization is explicit

### 11.1 PropagationBundle is not a canonical action

Step27 `PropagationBundle.proposed_changes[]` currently contains structured planning descriptions such as affected semantic id, action, and rule ref. It does not contain a full canonical operation name/version/argument contract.

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

### 11.2 Dual binding

Every derived operation binds to both:

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

### 11.3 Proposed-change fingerprinting

Each Step27 proposed-change mapping is canonical-JSON normalized and independently hashed:

```text
proposed_change_hash = SHA-256(canonical_json(proposed_change_body))
```

A `proposed_change_hash` may be materialized at most once.

Unknown or duplicate proposal references fail closed.

### 11.4 Required completeness

For every propagation bundle whose `bundle_id` is admitted in:

```text
ApprovalScopeDefinition.propagation_bundle_ids
```

Step29 SHALL require **every** `PropagationBundle.proposed_changes[]` entry to be materialized exactly once.

This is intentionally stronger than caller-selected partial materialization because the current Step27 deterministic bundle shape has one proposed mutation description per affected semantic entity.

Step29 MUST reject:

```text
missing admitted proposal
duplicate admitted proposal
unknown proposal
proposal from a non-admitted bundle
```

Advisory-only impacts and Host-native verification-only impacts do not become derived mutation nodes merely because they appear in `affected_entities`.

---

## 12. Step28 scope coverage

### 12.1 Explicit-entity authority only in v1

Step28 supports explicit entity selectors and a restricted predicate selector. Step29 v1 does not own a snapshot-bound predicate evaluator.

Mutation materialization SHALL therefore use only `ExistingEntityRule` values whose selector explicitly enumerates the target semantic id.

Predicate-only membership cannot be accepted based on caller assertion.

Failure:

```text
CHANGESET_SCOPE_MEMBERSHIP_UNRESOLVED
```

### 12.2 Full effect coverage

For every materialized operation and every target:

```text
expected_effects
  ⊆ union(allowed_aspects of explicit Step28 rules covering that target)
```

Coverage may be provided by multiple explicit rules, but must be complete.

Example:

```text
MOVE WALL-001
expected_effects = {PLACEMENT, GEOMETRY}
```

If scope authorizes only:

```text
WALL-001 -> {PLACEMENT}
```

Step29 fails with:

```text
CHANGESET_SCOPE_EFFECT_EXCEEDED
```

### 12.3 Scope cannot be widened

Step29 MUST NOT:

- add entities to a selector;
- add aspects to an existing rule;
- convert predicate scope into explicit permission by assertion;
- activate Step28 creation/deletion rules unsupported in v1;
- add propagation bundles not already admitted.

---

## 13. Creation and deletion remain unsupported in v1

Step28 v1 rejects non-empty creation/deletion authority because the current Step23 contract does not expose typed canonical existence-effect authority.

Step29 SHALL preserve that restriction.

No caller may encode CREATE/DELETE as a generic derived operation to bypass Step28's existence-effect restriction.

Future create/delete support requires Step23 typed authority first, then Step28 scope activation, then Step29 consumption.

---

## 14. Change DAG

Step27 predicts impact/propagation. Step29 freezes actual canonical mutation causality.

Only materialized canonical operations are mutation DAG nodes. A predicted impact requiring verification is not automatically a mutation node.

Step29 v1 admits only evidence-backed:

```text
ROOT → DERIVED
```

The builder rejects:

- unknown operation ids in edges;
- self edges;
- duplicate semantic edges;
- cycles;
- arbitrary `DERIVED → DERIVED` edges;
- edges not justified by the derived operation's exact propagation source evidence.

---

## 15. Preconditions

Step29 preconditions are deterministic projections of D6 planning requirements, not policy prose.

Initial closed kinds:

```text
OPERATION_FRESHNESS
COVERAGE
ASSURANCE
```

SnapshotSet and SemanticEnvironment identity are top-level transaction bindings and SHALL NOT be weakened into optional precondition text.

Preconditions are normalized and included in `changeset_hash`.

---

## 16. Affected entities and semantic impacts

### 16.1 `affected_entities[]`

The affected entity set is the deterministic union of:

```text
ImpactAnalysis.direct_targets
+
all PredictedImpact.affected_semantic_id
```

This is evidence/reporting scope, not mutation authority.

### 16.2 `semantic_impacts[]`

`semantic_impacts[]` is a normalized immutable projection of Step27 predicted impacts preserving:

```text
source_semantic_id
affected_semantic_id
dependency_ref
propagation_owner
propagation_action
requires_verification
```

It MUST NOT convert impact evidence into permission.

---

## 17. Validation tasks

Validation tasks are generated deterministically from:

```text
root CanonicalOperationContractEvidence.verification_contract
derived CanonicalOperationContractEvidence.verification_contract
PredictedImpact.requires_verification
```

For example, a canonical MOVE verification contract may create a root Host read-back obligation, while a Host-native predicted impact with `requires_verification=true` may create a dependency revalidation/read-back obligation without creating a derived mutation node.

Step29 defines only the obligation. Actual verification execution/results belong to Step33.

`validation_task_id` is deterministically derived from task semantic content and excluded as independent entropy from the ChangeSet hash.

---

## 18. ChangeSet hashing

### 18.1 Canonical function

```text
changeset_hash = SHA-256(canonical_json(semantic_changeset_body))
```

Canonical JSON uses stable key ordering, compact separators, UTF-8, normalized enums/mappings, and deterministic collection ordering where semantic order is not meaningful.

### 18.2 Semantic hash body

The semantic body includes at least:

```text
task_id
project_id?

planning_snapshot_ref
snapshot_set_ref
semantic_environment_ref

impact_analysis_fingerprint
bound_operation_fingerprint

scope_body_hash

root operation semantic body
derived operation semantic bodies
change dependency semantic bodies

preconditions
affected_entities
semantic_impacts
validation_tasks
```

Each operation semantic body includes:

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

For the root operation, source evidence includes the complete `bound_operation_evidence_fingerprint`, so D6 binding/context evidence is also frozen into transaction identity.

### 18.3 Construction ids excluded

The following do not add independent entropy:

```text
changeset_id
operation_id
scope_definition_id
validation_task_id
```

When another semantic object references one of these ids, hashing resolves it to the referenced semantic fingerprint/meaning rather than raw opaque id text.

### 18.4 Material changes that must change hash

Any material change to the following changes `changeset_hash`:

```text
canonical operation/version
canonical contract semantic definition
canonical arguments
targets
D6 bound-operation evidence
Step27 derived materialization
Change DAG causality
PlanningSnapshot
SnapshotSet
SemanticEnvironment
ImpactAnalysis fingerprint
scope_body_hash
preconditions
validation obligations
```

### 18.5 Stable ids

Recommended construction ids:

```text
changeset_id = "CS-" + changeset_hash[:12]
operation_id = "COP-" + operation_hash[:12]
validation_task_id = "VT-" + validation_task_hash[:12]
```

Random UUID identity SHALL NOT determine semantic transaction identity.

---

## 19. No final ApprovalScopeBoundary inside ChangeSet hash

The ChangeSet carries only:

```text
ApprovalScopeDefinitionRef {
  scope_definition_id
  scope_body_hash
}
```

It MUST NOT contain final `ApprovalScopeBoundary.scope_hash` as part of its own semantic hash.

Correct order:

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

Including final `scope_hash` in ChangeSet would create a cycle because Step28 final `scope_hash` itself binds `changeset_hash`.

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

- accepts the generated lowercase SHA-256 hash;
- leaves the frozen Step28 semantic body unchanged;
- binds exactly the generated ChangeSet hash;
- derives the final Step28 scope hash only through the existing binder.

Step29 MUST NOT add a second scope-binding implementation.

---

## 21. Step30 input contract

Step30 SHALL consume exactly:

```text
CanonicalChangeSet
+
ApprovalScopeBoundary
```

and first validate:

```text
ApprovalScopeBoundary.changeset_hash
  == CanonicalChangeSet.changeset_hash

ApprovalScopeBoundary.scope_body_hash
  == CanonicalChangeSet.approval_scope_definition_ref.scope_body_hash
```

Step30 SHALL NOT rebuild the transaction from D6, Step27, or Step28 planner requests.

Responsibility split:

```text
Step29: what canonical mutation exists
Step30: how the immutable mutation is partitioned for execution
Step31: which provider binds each canonical execution unit
```

---

## 22. Fields explicitly excluded from Step29

The Step29 production contract MUST NOT contain runtime authority for:

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

Workflow/runtime status is associated externally by stable transaction identity, e.g.:

```text
changeset_hash -> workflow/checkpoint state
```

rather than mutating the ChangeSet.

---

## 23. Builder request

The Step29 builder input is semantically equivalent to:

```text
ChangeSetBuildRequest {
  task_id
  project_id?

  bound_operation_evidence
  impact_analysis
  approval_scope_definition

  canonical_operation_definitions[]
  derived_materializations[]
}
```

`canonical_operation_definitions[]` are the immutable `CanonicalOperationContractEvidence` projections from §5.1.

The builder does not accept caller-provided:

```text
expected_effects
changeset_hash
final scope_hash
provider bindings
approval state
runtime verification results
```

---

## 24. Error contract

Step29 exposes one stable domain exception:

```text
ChangeSetError(code, message)
```

Initial machine-code vocabulary:

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

Raw `ValueError`, jsonschema exceptions, or implementation-specific exceptions are not the public workflow-decision contract.

---

## 25. Architecture constraints

`design_changeset` remains provider-neutral.

Architecture tests SHALL prove no dependency on:

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

The package MUST NOT define production Step30 `ExecutionSlice` / `ExecutionUnit` implementations or Step33 verifier/saga implementations.

It SHALL expose an explicit public `__all__`.

All public transaction/value DTOs are immutable/frozen and normalize mutable caller containers into immutable value structures.

The package MAY consume public provider-neutral Step27/Step28 contracts. Upstream D6/Step23 objects are supplied through the evidence projections in §5 rather than by querying implementation registries inside Step29.

---

## 26. Legacy placeholder removal guard

Step29 SHALL include a repository-level migration test proving these Phase-2 placeholder files no longer exist:

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

## 27. TDD acceptance criteria

Implementation SHALL use RED → GREEN cycles covering at least:

### 27.1 Contracts / upstream binding

1. missing new package/API is RED before implementation;
2. public DTOs are frozen/value-oriented;
3. mutable containers normalize to immutable values;
4. Step27 exposes `bound_operation_fingerprint`;
5. existing Step27 `analysis_fingerprint` remains unchanged for equivalent inputs after the hardening;
6. Step29 rejects same-target/different-material-argument D6 evidence paired with an old ImpactAnalysis;
7. public `__all__` is explicit.

### 27.2 Hashing

8. equivalent semantic inputs with different non-semantic ordering produce the same `changeset_hash`;
9. canonical argument change changes hash;
10. D6 binding/context evidence change changes hash where material to `bound_operation_evidence_fingerprint`;
11. PlanningSnapshot/SnapshotSet/SemanticEnvironment change changes hash;
12. `scope_body_hash` change changes hash;
13. opaque construction ids do not independently change hash.

### 27.3 Root canonical contract

14. canonical operation mismatch is rejected;
15. canonical operation version mismatch with Step28 effect evidence is rejected;
16. canonical arguments validate against exact Step23-derived schema evidence;
17. expected effects come from canonical contract evidence, not caller input;
18. root target mismatch with ImpactAnalysis is rejected;
19. Step23 contract effects must equal Step28 canonical effect evidence.

### 27.4 Derived materialization

20. unknown propagation bundle is rejected;
21. non-admitted propagation bundle is rejected;
22. unknown `proposed_change_hash` is rejected;
23. duplicate proposal materialization is rejected;
24. every proposal in an admitted deterministic bundle must be materialized exactly once;
25. Host-native verification-only impact does not become a derived mutation;
26. advisory-only impact does not create permission or mutation.

### 27.5 Scope

27. direct/derived target outside explicit entity authority is rejected;
28. effect outside Step28 allowed aspects is rejected;
29. predicate-only scope membership is rejected in v1;
30. Step29 cannot activate creation/deletion authority.

### 27.6 Change DAG

31. evidence-backed `ROOT → DERIVED` is valid;
32. arbitrary `DERIVED → DERIVED` is rejected in v1;
33. unknown/self/cyclic edge is rejected.

### 27.7 Evidence / validation

34. `affected_entities` is deterministic union of direct and predicted affected entities;
35. semantic impacts remain evidence, not mutation permission;
36. validation tasks are generated deterministically from canonical verification contracts and `requires_verification` evidence.

### 27.8 Step28 integration

37. generated `changeset_hash` binds through Step28 `bind_changeset()`;
38. Step28 scope semantic body is unchanged after binding;
39. final boundary binds exactly the produced ChangeSet hash.

### 27.9 Migration / regression

40. legacy HostDelta ChangeSet files are removed;
41. `host-contracts` dependency is removed from `platform/changeset`;
42. architecture guard proves no host/provider/native leakage;
43. Step29 does not own Step30/31/32/33 artifacts;
44. Step28 focused regression remains green;
45. Step27 focused regression remains green;
46. Step25/26 relevant regressions remain green;
47. Ruff remains green;
48. full repository pytest remains green.

---

## 28. CI boundary

Step29 SHALL add a focused GitHub Actions workflow, recommended:

```text
.github/workflows/step29-immutable-changeset.yml
```

It SHALL run:

1. Step29 diff-boundary validation;
2. Step29 contract tests;
3. Step29 hashing tests;
4. Step29 builder tests;
5. Step29 architecture/migration tests;
6. Step27 binding-hardening tests;
7. Step28 regressions;
8. Step27 regressions;
9. Step25/26 relevant regressions;
10. existing D4→D5 freshness bridge where required by repository baseline;
11. Ruff;
12. full repository pytest.

The workflow SHALL not claim final success if full regression or lint is skipped after a prior failure; a fresh final head must complete all required gates.

---

## 29. Non-goals

Step29 v1 deliberately does not implement:

- multiple root-operation batching;
- predicate selector evaluation;
- CREATE/DELETE canonical existence effects;
- provider selection/capability negotiation;
- provider input adaptation;
- host/document execution slicing;
- approval policy evaluation;
- approval records or execution grants;
- actual delta capture;
- verification result evaluation;
- rollback/compensation/saga execution;
- mutable workflow status inside ChangeSet;
- caller-authored semantic effects.

---

## 30. Security and fail-closed posture

Step29 treats all cross-step joins as authority-sensitive.

It fails closed unless it can prove:

```text
this exact material bound operation
belongs to this ImpactAnalysis
which belongs to this frozen ApprovalScopeDefinition
and every mutation node
is an exact Step23 canonical contract instance
fully covered by explicit Step28 effect authority
```

Forbidden fallbacks include:

```text
infer operation from propagation action text
infer target membership from predicate without evaluation
trust caller-provided expected_effects
trust caller-provided changeset_hash
silently omit an admitted deterministic derived proposal
silently duplicate a propagation proposal
silently accept mismatched snapshots/environments
reuse ImpactAnalysis after changing material canonical arguments
```

---

## 31. Final design invariants

Step29 is complete only when all are true:

1. there is exactly one canonical meaning of ChangeSet in `platform/changeset`;
2. the ChangeSet is immutable from creation;
3. exactly one root canonical operation is frozen;
4. Step27 exposes a verifiable `bound_operation_fingerprint` without changing existing `analysis_fingerprint` semantics;
5. Step29 proves its D6 material operation is the one analyzed by Step27;
6. derived operations are explicitly tied to both Step27 proposal evidence and Step23 contract evidence;
7. expected effects are generated from Step23 authority, never caller-authored;
8. all mutation targets/effects are covered by Step28 explicit-entity rules;
9. predicate-only membership fails closed in v1;
10. every proposal in an admitted deterministic propagation bundle is materialized exactly once;
11. Change DAG v1 only admits evidence-backed `ROOT → DERIVED` causality;
12. affected/impact/validation data remain evidence/obligations, not permission expansion;
13. `changeset_hash` is deterministic over semantic transaction identity;
14. construction ids do not alter semantic identity;
15. final Step28 `scope_hash` is not part of the ChangeSet hash, avoiding circular binding;
16. produced hash binds through Step28's existing pure binder without changing scope body;
17. Step30 receives only `CanonicalChangeSet + ApprovalScopeBoundary` as execution-planning input;
18. no Host/provider/native/approval/runtime state leaks into ChangeSet;
19. old HostDelta-centric ChangeSet placeholder/dependency is removed;
20. focused tests, upstream regressions, lint, and full repository regression remain green.

---

## 32. Review gate

This written spec incorporates the three design sections explicitly approved in chat on 2026-08-29 plus one self-review correction discovered by comparing the approved design against the current Step27 production contract: the explicit `bound_operation_fingerprint` prerequisite in §6.

No production implementation plan or Step29 code should begin until the written spec is reviewed for consistency with:

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