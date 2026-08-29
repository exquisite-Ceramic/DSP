# Step 28 — ApprovalScopeBoundary / Effect Scope Design

**Status:** Approved in-chat design; written-spec review pending  
**Date:** 2026-08-29  
**Base:** `main@3f6f90e16690d7e9ad3231f874763786bcb52823`  
**Branch:** `feat/step28-approval-scope-boundary`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step 28 introduces a standalone, provider-neutral governance boundary that answers one question:

```text
What canonical effects may be approved for this exact impact result?
```

It does **not** answer:

```text
Who may approve?
Does policy require HITL?
What is the approval tier?
Which provider/tool executes the change?
What is the final immutable ChangeSet body?
```

The intended Phase-G flow remains:

```text
Step 27 ImpactAnalysis
        ↓
Step 28 ApprovalScopeDefinition
        ↓
Step 29 immutable ChangeSet
        ↓
bind real ChangeSet hash
        ↓
ApprovalScopeBoundary
        ↓
Step 30 ExecutionSlice / ExecutionUnit
        ↓
Step 31 ProviderBinding
        ↓
Step 32 ApprovalRecord / ExecutionGrant
        ↓
Step 33 Verify / ScopeComparator / Saga
```

The central invariant is:

> Step 28 decides the maximum closed-world canonical effect scope. Step 29 may bind that scope to one immutable ChangeSet, but MUST NOT widen it.

---

## 2. Master-spec ordering contradiction and resolution

The v0.6 body orders the flow as:

```text
Impact
  ↓
ApprovalScopeBoundary
  ↓
ChangeSetBuilder
  ↓
Immutable ChangeSet
```

However Appendix A.6 defines the final normative DTO with:

```text
ApprovalScopeBoundary {
  scope_id
  changeset_hash
  ...
  execution_slice_scopes[]
  scope_hash
}
```

The final `changeset_hash` cannot exist before Step 29, and concrete `ExecutionSlice` ids cannot exist before Step 30.

Step 28 MUST NOT manufacture placeholder values such as:

```text
changeset_hash = "TBD"
execution_slice_id = "future-id"
```

The design therefore freezes a two-stage contract:

```text
Step 28:
  immutable ApprovalScopeDefinition
  + scope_body_hash

Step 29:
  immutable ChangeSet
  + real changeset_hash
  ↓
  bind_changeset(...)
  ↓
  ApprovalScopeBoundary
  + scope_hash
```

`execution_slice_scopes[]` is defined as a declarative future-slice boundary, never as a list of future slice ids.

---

## 3. Chosen architecture

### 3.1 Chosen: independent `platform/approval_scope`

Step 28 SHALL introduce:

```text
platform/approval_scope/
  src/design_approval_scope/
    __init__.py
    contracts.py
    planner.py
    hashing.py
```

The package owns:

- immutable effect-scope contracts;
- deterministic closed-world scope planning;
- structured selector/predicate validation;
- stable scope hashing;
- the pure bind operation from a frozen definition to a real ChangeSet hash.

It MAY depend on the public `design_impact` contract.

It MUST NOT depend on Host/product execution packages or the current legacy `changeset` production model.

The core package also MUST NOT import D4/orchestrator implementation classes merely to read the Canonical Action Catalog. Instead, the orchestration boundary supplies a small immutable provider-neutral `CanonicalEffectEvidence` value assembled from the exact Step 23 `CanonicalOperationDefinition` selected for the bound operation.

### 3.2 Rejected: build final boundary inside legacy `platform/changeset`

The current `platform/changeset` package still models a mutable list of `HostDelta` values and therefore does not represent the v0.6 canonical immutable ChangeSet contract.

Step 28 MUST NOT be coupled to that placeholder in order to obtain an artificial `changeset_hash`.

### 3.3 Rejected: make `ImpactAnalyzer` emit approval scope directly

Step 27 owns prediction, propagation classification, constraints, and exceptions. Step 28 owns governance effect boundaries.

Merging them would make dependency analysis authoritative for approval scope and would erase the independent contract that Step 29 and Step 33 need.

---

## 4. Ownership boundary

### 4.1 Step 23 owns canonical operation effect authority

The Step 23 Canonical Action contract is the platform source of truth for the semantic effects of the user operation.

Current production `CanonicalOperationDefinition.effects` is an aspect-level contract. For `move.v1` it is exactly:

```text
PLACEMENT
GEOMETRY
```

Step 28 SHALL consume an immutable projection of that authority:

```text
CanonicalEffectEvidence {
  canonical_operation
  canonical_operation_version
  allowed_aspects[]
}
```

The assembler outside `design_approval_scope` constructs this value from the exact Step 23 `CanonicalOperationDefinition` used by the workflow.

Requirements:

- `canonical_operation` MUST equal `ImpactAnalysis.canonical_operation`;
- `allowed_aspects[]` MUST equal the normalized Step 23 action `effects` for that operation/version;
- all aspects MUST be canonical semantic aspects;
- the normalized evidence is included in `scope_body_hash`.

Step 28 does not infer effects from an operation name, provider profile, or natural-language description.

### 4.2 Step 27 owns impact evidence and the carried-forward intent boundary

Step 28 consumes `ImpactAnalysis` including:

```text
analysis_fingerprint
planning_snapshot_ref
snapshot_set_ref
semantic_environment_ref
predicted_impacts[]
propagation_bundles[]
exceptions[]
```

and the exact immutable `IntentBoundary` that was supplied to the Step 27 request.

Step 28 does not recompute dependency traversal or constraints.

### 4.3 Step 28 owns effect-scope admission

Step 28 decides:

- which existing entities may change;
- which canonical aspects may change on each admitted entity set;
- whether creation/deletion rules have an upstream canonical existence-effect authority;
- which propagation bundles are admitted;
- within which document/effect partitions future `ExecutionSlice` values may be planned;
- whether the impact result is approvable at all.

The master DTO shapes for creation and deletion are frozen in this step, but the current Step 23 contract has **no typed CREATE/DELETE existence-effect authority**. Therefore the Step 28 v1 planner MUST reject non-empty requested creation/deletion rules rather than treating caller-supplied rules as authority. See §§12–13.

### 4.4 Step 29 owns immutable ChangeSet materialization

Step 29 receives a frozen scope definition and creates the canonical immutable ChangeSet.

Step 29 may only bind the resulting real `changeset_hash` to the existing scope body. It MUST NOT:

- add a new existing-entity rule;
- add an aspect to an existing rule;
- add creation or deletion permission;
- add a propagation bundle;
- widen a slice-scope rule.

Any scope change requires a new `ApprovalScopeDefinition` and therefore a new `scope_body_hash`.

### 4.5 Step 32 / Gateway owns approval authority

Step 28 MUST NOT contain:

```text
approver
approval tier
risk level
policy decision
ApprovalToken
ApprovalRecord
ExecutionGrant
PolicySnapshot
```

Those are later governance records.

---

## 5. Core two-stage contracts

### 5.1 `ApprovalScopeDefinition`

Step 28 produces:

```text
ApprovalScopeDefinition {
  scope_definition_id

  impact_analysis_fingerprint
  canonical_effect_evidence
  planning_snapshot_ref
  snapshot_set_ref
  semantic_environment_ref

  existing_entity_rules[]
  creation_rules[]
  deletion_rules[]

  propagation_bundle_ids[]
  execution_slice_scope_rules[]

  scope_body_hash
}
```

The value is immutable/value-oriented.

The following identifiers are opaque audit identifiers and are not semantic permission themselves:

```text
scope_definition_id
rule_id
slice_scope_rule_id
```

The normalized rule bodies and exact upstream bindings are the authority for `scope_body_hash`.

For Step 28 v1 with the current Step 23 action contract:

```text
creation_rules = []
deletion_rules = []
```

unless and until the canonical action contract gains a typed existence-effect authority and this Step 28 contract is explicitly revised to consume it.

### 5.2 Final `ApprovalScopeBoundary`

After Step 29 has produced a real immutable ChangeSet hash:

```text
ApprovalScopeBoundary {
  scope_id

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

`execution_slice_scopes[]` is the final serialized form of the declarative `ExecutionSliceScopeRule` values from Step 28. It does not contain concrete `execution_slice_id` values.

### 5.3 Pure bind contract

The package exposes a pure operation conceptually equivalent to:

```text
bind_changeset(
  scope_definition,
  changeset_hash,
  scope_id,
) -> ApprovalScopeBoundary
```

Requirements:

- `changeset_hash` MUST be a lowercase 64-hex SHA-256 digest produced by the Step 29 immutable ChangeSet canonical hash contract; placeholder/TBD values are invalid;
- every rule body MUST be copied exactly from the frozen definition;
- bind MUST NOT accept replacement or extra rule lists;
- bind MUST NOT depend on ProviderBinding, HostCommand, approval state, or policy state.

If Step 29 later changes the repository-wide canonical digest algorithm, that change requires an explicit contract revision rather than silent acceptance of arbitrary hash strings.

---

## 6. Closed-world semantics

`ApprovalScopeBoundary` is deny-by-default.

The semantic rule is:

```text
not explicitly admitted
    => not allowed
```

Therefore:

```text
deletion_rules = []
```

means:

```text
no entity deletion is approved
```

and not:

```text
delete behavior is unspecified
```

Likewise:

```text
creation_rules = []
```

means no new entity may be created.

An existing entity admitted for `PLACEMENT` and `GEOMETRY` is **not** implicitly admitted for:

```text
CLASSIFICATION
PROPERTIES
IDENTITY
CONNECTIVITY
RELATIONSHIPS
CONSTRAINTS
SPATIAL
```

This closed-world rule is the basis for Step 33:

```text
ActualDelta ⊆ ApprovalScopeBoundary
```

Anything outside the explicit rule set is a scope breach.

---

## 7. Existing-entity rule

```text
ExistingEntityRule {
  rule_id
  selector
  allowed_aspects[]
}
```

`allowed_aspects[]` MUST contain explicit canonical aspect identifiers only.

Step 28 v1 freezes the vocabulary to the current canonical semantic aspect set:

```text
IDENTITY
PROPERTIES
PLACEMENT
GEOMETRY
SPATIAL
CONNECTIVITY
RELATIONSHIPS
CONSTRAINTS
CLASSIFICATION
```

Host-native fields, provider tool arguments, API type names, and arbitrary strings are invalid aspects.

Example MOVE direct rule:

```text
WALL-001:
  allowed_aspects = [PLACEMENT, GEOMETRY]
```

This does not authorize classification, material/property, identity, or arbitrary association changes.

---

## 8. Structured selectors and predicates

A selector is exactly one of:

```text
EntitySelector {
  entities[]
  |
  predicate
}
```

The two forms are mutually exclusive.

Free-form strings, SQL, Python, JavaScript, provider callbacks, or LLM descriptions are forbidden.

### 8.1 Predicate AST

Step 28 v1 supports only conjunction:

```text
EntityPredicate {
  all_of[]
}
```

Each term is:

```text
PredicateTerm {
  field:
    SEMANTIC_ID
    CANONICAL_KIND
    SOURCE_ENTITY
    DERIVATION_RULE

  operator:
    EQ
    IN

  values[]
}
```

Requirements:

- `all_of[]` MUST be non-empty;
- term values MUST be non-empty normalized strings;
- `EQ` requires exactly one value;
- `IN` requires one or more values;
- duplicate terms/values normalize deterministically;
- unknown fields/operators fail closed;
- no `OR`, `NOT`, regex, arbitrary expression, or external function exists in Step 28 v1.

The limited AST is intentionally sufficient for deterministic Step 33 matching without becoming a general policy/DSL engine.

---

## 9. Explicit direct-effect evidence

Step 28 MUST NOT infer direct mutation aspects from the operation name alone.

The planner request therefore includes explicit canonical direct-effect evidence:

```text
DirectEntityEffect {
  semantic_id
  allowed_aspects[]
}
```

Rules:

- `semantic_id` MUST belong to `ImpactAnalysis.direct_targets`;
- `allowed_aspects[]` MUST be non-empty;
- every direct-effect aspect MUST be present in `CanonicalEffectEvidence.allowed_aspects`;
- every direct-effect aspect MUST also be present in the exact Step 27 `IntentBoundary.allowed_canonical_effects` supplied with this planning request;
- duplicate direct effects for the same semantic id normalize to one exact rule only when their aspect sets are identical; conflicting duplicates are invalid;
- a direct effect cannot introduce a non-direct target.

For MOVE, the canonical authority is:

```text
CanonicalEffectEvidence:
  move.v1@1.0.0
  allowed_aspects = [PLACEMENT, GEOMETRY]
```

and explicit direct evidence may state:

```text
WALL-001 -> [PLACEMENT, GEOMETRY]
```

Step 28 copies that explicit boundary; it does not derive the aspect set from the text `MOVE`.

---

## 10. Predicted impacts require explicit effect recipes

A predicted impact is not automatically an approved mutation.

The path is:

```text
PredictedImpact
      ↓
explicit ScopeEffectRecipe
      ↓
ExistingEntityRule / admitted propagation
```

### 10.1 `ScopeEffectRecipe`

The machine binding key follows the current Step 27 public contract:

```text
ScopeEffectRecipe {
  recipe_id
  dependency_ref
  allowed_aspects[]
  rule_ref?
  propagation_bundle_id?
}
```

`dependency_ref` is authoritative because current `PredictedImpact` exposes `dependency_ref` but does not expose `rule_ref`.

`rule_ref`, when present, is provenance/consistency evidence only. Step 28 MUST NOT require a Step 27 contract change merely to obtain it.

`propagation_bundle_id`, when present, MUST identify a bundle in the exact `ImpactAnalysis` and MUST be consistent with the affected entity/rule relationship represented by the recipe.

Every recipe aspect MUST be present in both:

```text
CanonicalEffectEvidence.allowed_aspects
IntentBoundary.allowed_canonical_effects
```

A recipe cannot use Step 28 to reintroduce an effect that either the Canonical Action contract or Step 27 intent did not admit.

### 10.2 No action-name inference

The planner MUST NOT contain logic such as:

```text
REVALIDATE => allow PLACEMENT + GEOMETRY
RECOMPUTE  => allow PROPERTIES
```

Propagation action names classify behavior; they do not define authorized aspects.

For Step 28 v1, a `PredictedImpact` is **effect-bearing** exactly when at least one of the following structured Step 27 facts is true:

```text
PredictedImpact.requires_verification == true
```

or:

```text
PredictedImpact.affected_semantic_id
  appears in a deterministic ImpactAnalysis.propagation_bundles[].affected_entities
```

This classification MUST NOT inspect `propagation_action` names. A non-blocking advisory-only predicted impact that is neither verification-bearing nor represented by a deterministic propagation bundle does not create permission and does not require a recipe.

If an effect-bearing predicted impact has no explicit recipe:

```text
SCOPE_EFFECT_UNDEFINED
```

and planning fails closed.

### 10.3 Relationship evidence cannot expand scope

A semantic relationship alone never creates a scope rule.

Only explicit Step 27 dependency/impact evidence plus an explicit Step 28 effect recipe may admit a predicted side effect.

---

## 11. Propagation bundles

`propagation_bundle_ids[]` records deterministic Step 27 bundles that have been explicitly admitted by Step 28.

Step 28 MUST NOT blindly copy every bundle merely because it exists in `ImpactAnalysis`.

A bundle may be admitted only when:

- it belongs to the exact impact result;
- its affected entities are covered by explicit effect recipes;
- those recipes define exact allowed canonical aspects;
- every admitted recipe aspect is within both the Canonical Action effect evidence and exact Step 27 intent boundary;
- no blocking exception prevents scope planning.

When a recipe supplies both `propagation_bundle_id` and `rule_ref`, `rule_ref` MUST equal the referenced bundle's `rule_ref`. That rule ref MUST also be present in `IntentBoundary.allowed_derived_rule_refs`. For a Host-native verification impact that has no propagation bundle, `rule_ref` remains optional because the current public `PredictedImpact` contract does not expose it; Step 27's blocking intent-expansion classification remains authoritative for whether that dependency was admitted.

A provider or semantic package cannot enlarge scope merely by emitting a relationship/rule name. The platform-owned recipe/admission step remains authoritative.

---

## 12. Creation rules and the v1 activation gate

Create-like operations cannot be verified with an old-entity allowlist alone, so the master Step 28 contract freezes the rule shape now:

```text
CreationRule {
  rule_id
  canonical_operation
  source_selector
  entity_kinds[]
  max_count?
  required_derivation?
}
```

The semantic requirements remain:

- `canonical_operation` is a canonical operation id, never a provider tool name;
- `source_selector` uses the same restricted selector AST;
- `entity_kinds[]` contains canonical kind identifiers only;
- `max_count`, when present, is a positive integer;
- `required_derivation`, when present, is an exact structured derivation/rule reference;
- no creation permission exists unless an admitted `CreationRule` exists.

However, the current Step 23 `CanonicalOperationDefinition.effects` contract contains canonical **aspect effects only**. It does not say that an operation is authorized to create entities, nor does it encode allowed created kinds/count/derivation.

Therefore Step 28 v1 MUST NOT treat a caller-supplied `CreationRule` as self-authorizing. Until a later Canonical Action contract revision provides typed existence-effect authority:

```text
requested_creation_rules != []
  -> SCOPE_EXISTENCE_EFFECT_UNSUPPORTED
  -> no ApprovalScopeDefinition
```

and successful Step 28 v1 output always has:

```text
creation_rules = []
```

A future OFFSET/COPY/ROUTE action may activate this rule shape only after upstream canonical action metadata can prove the corresponding create authority. At that time Step 28 must consume that structured evidence explicitly; it still may not infer create authority from the operation name.

---

## 13. Deletion rules and the v1 activation gate

The master contract likewise freezes:

```text
DeletionRule {
  rule_id
  selector
}
```

Deletion is always explicit and closed-world.

But the current Step 23 action effect contract has no typed delete/existence authority. Therefore Step 28 v1 MUST reject a non-empty requested deletion scope:

```text
requested_deletion_rules != []
  -> SCOPE_EXISTENCE_EFFECT_UNSUPPORTED
  -> no ApprovalScopeDefinition
```

and successful v1 output always has:

```text
deletion_rules = []
```

Step 28 does not infer delete permission from `replacement`, `split`, `rebuild`, or other natural-language/canonical-operation names.

When a later canonical action contract explicitly freezes delete authority, Step 28 can be revised to admit a `DeletionRule` only when it is a subset of that exact upstream existence-effect evidence.

---

## 14. Blocking and advisory exceptions

Step 27 already classifies `ImpactException.blocking`.

Step 28 freezes:

```text
any ImpactException(blocking=true)
        ↓
SCOPE_NOT_APPROVABLE
        ↓
no ApprovalScopeDefinition
```

Typical examples include:

```text
AGENT + REPLAN
PROPAGATION BLOCK
HARD constraint failure
intent scope expansion
```

Step 28 MUST NOT convert a blocking exception into a larger scope.

Non-blocking advisory/review exceptions MAY remain visible to preview/governance, but they do not by themselves add existing, create, or delete permission.

---

## 15. Execution-slice scope rules

Step 30 creates concrete `ExecutionSlice` objects, so Step 28 cannot reference future slice ids.

The contract is declarative:

```text
ExecutionSliceScopeRule {
  slice_scope_rule_id
  document_ref
  existing_rule_ids[]
  creation_rule_ids[]
  deletion_rule_ids[]
}
```

Requirements:

- `document_ref` is provider-neutral;
- every referenced rule id MUST exist in the same `ApprovalScopeDefinition`;
- each admitted rule MUST be assigned to at least one compatible document scope before the definition is considered complete;
- unknown/future `execution_slice_id` values are forbidden;
- in v1, `creation_rule_ids[]` and `deletion_rule_ids[]` are necessarily empty because existence effects are not yet activated.

Step 30 MUST prove:

```text
ExecutionSlice effect scope
    ⊆ one ExecutionSliceScopeRule
```

Therefore:

```text
execution_slice_scopes != execution_slice_ids
```

---

## 16. Planner input

Conceptually:

```text
ApprovalScopePlanRequest {
  canonical_effect_evidence
  impact_analysis
  intent_boundary

  direct_entity_effects[]
  scope_effect_recipes[]

  requested_creation_rules[]
  requested_deletion_rules[]
  execution_slice_scope_rules[]
}
```

### 16.1 Canonical-effect evidence consistency

`canonical_effect_evidence` is assembled from the exact Step 23 action definition used by the workflow.

Step 28 validates:

```text
canonical_effect_evidence.canonical_operation
  == impact_analysis.canonical_operation
```

and requires:

```text
IntentBoundary.allowed_canonical_effects
  ⊆ CanonicalEffectEvidence.allowed_aspects
```

This prevents a locally widened IntentBoundary from becoming effect authority merely because Step 27 fingerprinted it.

The normalized operation identity, version, and aspect set are included in `scope_body_hash`.

### 16.2 Exact carried-forward IntentBoundary

`intent_boundary` MUST be the exact immutable value used by the Step 27 `ImpactAnalysisRequest` that produced `impact_analysis`; it is carried forward by the same workflow/checkpoint and MUST NOT be reconstructed from prose or widened locally by Step 28.

The current Step 27 `analysis_fingerprint` already binds the normalized `IntentBoundary`, but the public `ImpactAnalysis` DTO does not expose a standalone `intent_boundary_hash`. Step 28 v1 therefore freezes these rules:

- `intent_boundary.direct_targets` MUST exactly equal `ImpactAnalysis.direct_targets`;
- `intent_boundary.allowed_canonical_effects` MUST be a subset of `CanonicalEffectEvidence.allowed_aspects`;
- all direct-effect and recipe aspects MUST be subsets of both the canonical effect evidence and `intent_boundary.allowed_canonical_effects`;
- a recipe bound to a deterministic propagation bundle MUST use that bundle's exact `rule_ref`, which MUST be in `intent_boundary.allowed_derived_rule_refs`;
- any Step 27 blocking intent-expansion exception remains authoritative and stops planning before scope rules are materialized;
- the normalized `intent_boundary` body is included in `scope_body_hash`, so any changed boundary produces a different scope body and requires a fresh approval chain.

If the workflow cannot provide the exact Step 27 intent boundary, Step 28 fails closed with `SCOPE_INPUT_INVALID`. A future cross-process contract MAY expose a dedicated Step 27 `intent_boundary_hash`; Step 28 v1 does not silently invent one.

### 16.3 Existence-effect request gate

The request fields are present to freeze the final approval-scope vocabulary, but current v1 admits only:

```text
requested_creation_rules = []
requested_deletion_rules = []
```

Any non-empty value fails `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED` because current Step 23 canonical effects do not provide machine authority for existence changes.

The request MUST NOT contain:

```text
provider_tool
native_id
HostCommand
ApprovalRecord
ExecutionGrant
PolicySnapshot
legacy HostDelta ChangeSet
```

---

## 17. Deterministic planning algorithm

Step 28 is deterministic-first and SHALL NOT call a free-form LLM.

```text
1. Validate immutable ImpactAnalysis shape/bindings
2. Reject immediately if any blocking ImpactException exists
3. Validate CanonicalEffectEvidence operation/version/aspect vocabulary
4. Validate exact carried-forward IntentBoundary/direct-target consistency
5. Require IntentBoundary effects to be a subset of canonical action effects
6. Reject non-empty create/delete requests while existence-effect authority is unavailable
7. Validate direct canonical effect evidence against both authorities
8. Materialize direct ExistingEntityRule values
9. Match predicted impacts to explicit ScopeEffectRecipe values
10. Classify effect-bearing impacts only from requires_verification / deterministic bundles
11. Fail closed for undefined effect-bearing impact scope
12. Validate recipes against both effect authorities and referenced bundles
13. Materialize admitted predicted-side-effect ExistingEntityRule values
14. Admit only propagation bundles backed by explicit recipes
15. Validate declarative ExecutionSliceScopeRule coverage
16. Normalize all rule ordering/set-valued fields
17. Compute scope_body_hash
18. Return immutable ApprovalScopeDefinition
```

No step may query Host APIs or provider execution schemas.

---

## 18. Hashing contract

Hashing follows the repository's deterministic canonical-JSON + SHA-256 pattern.

### 18.1 `scope_body_hash`

`scope_body_hash` binds the exact normalized pre-ChangeSet effect boundary and at minimum includes:

```text
impact_analysis_fingerprint
normalized canonical_effect_evidence
normalized intent_boundary
planning_snapshot id/hash/document
snapshot_set id/hash/member ids
semantic_environment id/hash
normalized existing_entity_rules
normalized creation_rules
normalized deletion_rules
normalized propagation_bundle_ids
normalized execution_slice_scope_rules
```

Opaque generated ids MUST NOT make semantically identical scope bodies hash differently. Hash payloads therefore replace `rule_id` / `slice_scope_rule_id` construction identities with deterministic rule-content fingerprints and normalize slice-scope cross-references by those fingerprints rather than random ids.

Equivalent input ordering MUST produce the same hash.

Changing any material permission, canonical action effect evidence, intent boundary, or upstream snapshot/environment/impact binding MUST change `scope_body_hash`.

### 18.2 Final `scope_hash`

After Step 29:

```text
scope_hash = H({
  "scope_body_hash": scope_body_hash,
  "changeset_hash": changeset_hash
})
```

Therefore:

```text
same scope + different ChangeSet
    => different scope_hash

same ChangeSet + widened scope
    => different scope_body_hash
    => different scope_hash
```

`scope_id` is an audit identifier and is not a substitute for `scope_hash`.

---

## 19. Error model

The package exposes stable machine-readable domain errors at minimum:

```text
SCOPE_INPUT_INVALID
SCOPE_NOT_APPROVABLE
SCOPE_EFFECT_UNDEFINED
SCOPE_EFFECT_CONTRACT_MISMATCH
SCOPE_EXISTENCE_EFFECT_UNSUPPORTED
SCOPE_PREDICATE_INVALID
SCOPE_RULE_INVALID
SCOPE_SLICE_RULE_INVALID
CHANGESET_HASH_INVALID
```

Rules:

- malformed/unknown aspect, selector, predicate, or rule -> fail closed;
- missing/inconsistent canonical effect evidence -> `SCOPE_EFFECT_CONTRACT_MISMATCH`;
- missing or inconsistent carried-forward Step 27 `IntentBoundary` -> `SCOPE_INPUT_INVALID`;
- intent effects outside canonical action effects -> `SCOPE_EFFECT_CONTRACT_MISMATCH`;
- blocking impact exception -> `SCOPE_NOT_APPROVABLE`;
- required predicted side effect without explicit recipe -> `SCOPE_EFFECT_UNDEFINED`;
- recipe/direct effect outside either canonical authority -> `SCOPE_RULE_INVALID`;
- non-empty create/delete request before typed existence-effect authority exists -> `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED`;
- future/placeholder/non-SHA-256 ChangeSet hash -> `CHANGESET_HASH_INVALID`;
- natural-language text MUST NOT drive retry or scope expansion.

---

## 20. MOVE reference vertical

### 20.1 Safe case

Input:

```text
MOVE WALL-001

CanonicalEffectEvidence:
  canonical_operation = move.v1
  canonical_operation_version = 1.0.0
  allowed_aspects = [PLACEMENT, GEOMETRY]

ImpactAnalysis:
  direct:
    WALL-001

IntentBoundary:
  direct_targets = [WALL-001]
  allowed_canonical_effects = [PLACEMENT, GEOMETRY]
  allowed_derived_rule_refs = [RULE-OPENING, RULE-ANNOTATION]

ImpactAnalysis predicted:
  OPENING-001
    dependency_ref = DEP-OPENING
    owner = HOST_NATIVE
    action = REVALIDATE
    requires_verification = true

  ANNOTATION-002
    dependency_ref = DEP-ANNOTATION
    owner = SEMANTIC_RUNTIME
    action = RECOMPUTE

bundle:
  PB-ANNOTATION
  rule_ref = RULE-ANNOTATION
  deterministic = true
```

Explicit Step 28 evidence:

```text
DirectEntityEffect:
  WALL-001 -> [PLACEMENT, GEOMETRY]

ScopeEffectRecipe:
  DEP-OPENING -> [PLACEMENT, GEOMETRY]

ScopeEffectRecipe:
  DEP-ANNOTATION -> [PLACEMENT]
  rule_ref = RULE-ANNOTATION
  propagation_bundle_id = PB-ANNOTATION

requested_creation_rules = []
requested_deletion_rules = []
```

Expected definition:

```text
existing:
  WALL-001       [PLACEMENT, GEOMETRY]
  OPENING-001    [PLACEMENT, GEOMETRY]
  ANNOTATION-002 [PLACEMENT]

creation_rules:
  []

deletion_rules:
  []

propagation_bundle_ids:
  [PB-ANNOTATION]
```

The exact annotation aspect set comes from the explicit recipe constrained by `move.v1` canonical effects, not from the word `RECOMPUTE`.

### 20.2 Blocking case

```text
MOVE WALL-001
  ↓
MEP-008
owner = AGENT
action = REPLAN
blocking ImpactException
```

Expected:

```text
SCOPE_NOT_APPROVABLE
no ApprovalScopeDefinition
```

Step 28 MUST NOT auto-add MEP-008 to a larger scope.

### 20.3 Unsupported existence-effect case

With current Step 23 action metadata:

```text
requested_creation_rules = [some CreationRule]
```

or:

```text
requested_deletion_rules = [some DeletionRule]
```

must produce:

```text
SCOPE_EXISTENCE_EFFECT_UNSUPPORTED
no ApprovalScopeDefinition
```

A caller cannot create authority by constructing the rule DTO itself.

---

## 21. Architecture constraints

Architecture tests SHALL enforce:

1. `design_approval_scope` does not import AutoCAD, Revit, Tekla, or other Host product packages.
2. It does not import `HostCommand` or provider execution contracts.
3. It does not depend on the current legacy `platform/changeset` mutable HostDelta model.
4. It may consume public `design_impact` value contracts only; Step 23 catalog access is adapted into provider-neutral `CanonicalEffectEvidence` outside the core package.
5. Provider/native ids and tool schemas do not appear in public Step 28 contracts.
6. Canonical action effects are an independent upper bound on Step 27 IntentBoundary effects.
7. Relationship evidence alone cannot create scope permission.
8. Propagation action names cannot determine allowed canonical aspects.
9. Effect-bearing classification may use only `requires_verification` and deterministic bundle membership.
10. Blocking `ImpactException` values cannot be converted into larger scope.
11. Creation and deletion are deny-by-default and remain inactive until typed canonical existence-effect authority exists.
12. `execution_slice_scopes` never contains future concrete slice ids.
13. Step 29 binding can add only `changeset_hash`, final `scope_id`, and derived `scope_hash`; it cannot widen the frozen body.
14. Policy/risk/approver/grant records remain outside Step 28.
15. A locally widened/reconstructed IntentBoundary cannot be used to preserve the same `scope_body_hash`.
16. A caller-supplied CreationRule/DeletionRule is never self-authorizing.

---

## 22. TDD acceptance criteria for the later implementation plan

The implementation plan MUST include RED -> GREEN coverage for at least:

1. Empty creation/deletion rules deny all creates/deletes.
2. Existing entity permission is aspect-specific and deny-by-default.
3. Unknown/native aspect values fail closed.
4. Entity selectors require exactly one of entities or predicate.
5. Predicate AST rejects free-form expressions and unknown operators/fields.
6. `EQ` and `IN` cardinality rules are enforced.
7. Relationship evidence alone cannot enlarge scope.
8. Canonical effect operation identity must equal `ImpactAnalysis.canonical_operation`.
9. IntentBoundary effects outside `CanonicalEffectEvidence.allowed_aspects` fail `SCOPE_EFFECT_CONTRACT_MISMATCH`.
10. Direct entity effects cannot target an entity outside `ImpactAnalysis.direct_targets`.
11. Direct effect aspects are never inferred from the canonical operation name.
12. Direct effect aspects outside either canonical action effects or `IntentBoundary.allowed_canonical_effects` fail closed.
13. A predicted Host-native verification effect with no explicit recipe fails `SCOPE_EFFECT_UNDEFINED`.
14. A deterministic propagation-bundle effect with no explicit recipe fails `SCOPE_EFFECT_UNDEFINED`.
15. Advisory-only predicted impact without verification/bundle membership creates no permission and needs no recipe.
16. A recipe keyed by an unknown `dependency_ref` fails closed.
17. `rule_ref` is optional provenance for Host-native verification, not the authoritative machine key.
18. Bundle-bound recipe `rule_ref` must equal the bundle rule and be allowed by the carried-forward intent boundary.
19. A recipe aspect outside canonical action effects fails closed even if a widened IntentBoundary contains it.
20. A blocking ImpactException returns `SCOPE_NOT_APPROVABLE` and no definition.
21. A non-blocking advisory exception does not enlarge effect scope.
22. Non-empty requested creation rules fail `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED` with current Step 23 effect metadata.
23. Non-empty requested deletion rules fail `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED` with current Step 23 effect metadata.
24. CreationRule/DeletionRule DTO existence alone cannot authorize an existence change.
25. Execution-slice scope rules may reference only rules in the same definition.
26. No future `execution_slice_id` can appear in Step 28 contracts.
27. Input list/set ordering does not change `scope_body_hash`.
28. Changing an allowed aspect changes `scope_body_hash`.
29. Changing canonical operation version/effect evidence changes `scope_body_hash`.
30. Changing the carried-forward intent boundary changes `scope_body_hash`.
31. Changing impact fingerprint changes `scope_body_hash`.
32. Changing PlanningSnapshot/SnapshotSet/SemanticEnvironment binding changes `scope_body_hash`.
33. Opaque rule construction ids do not perturb the semantic hash.
34. Step 28 cannot create a final boundary without a lowercase 64-hex real ChangeSet hash.
35. Binding the same scope body to different ChangeSet hashes yields different `scope_hash` values.
36. Binding MUST preserve the frozen rule body byte-for-byte after normalization.
37. Provider/native metadata leakage is rejected by architecture tests.
38. Step 27 / Step 26 / Step 25 / Step 24 / Step 23 regression suites remain green.

---

## 23. Non-goals for Step 28

Step 28 does not implement:

- immutable canonical ChangeSet body construction (Step 29);
- concrete ExecutionSlice or ExecutionUnit creation (Step 30);
- ProviderBinding or `binding_set_hash` (Step 31);
- ApprovalRecord, policy approval, approver identity, or ExecutionGrant (Step 32);
- ActualDelta comparator, SCOPE_BREACH handling, or Saga compensation (Step 33);
- a general-purpose policy language;
- arbitrary predicate code execution;
- IFC inheritance or semantic-provider reasoning;
- Host-specific mutation schemas;
- a new cross-process Step 27 intent-boundary proof field in v1;
- inventing a CREATE/DELETE existence-effect authority absent from the current Step 23 Canonical Action contract.

---

## 24. Completion boundary

Step 28 v1 is complete when the repository has a provider-neutral package whose public behavior proves:

```text
CanonicalEffectEvidence from Step 23
  + ImpactAnalysis
  + exact carried-forward IntentBoundary
  + explicit canonical direct effects
  + explicit effect recipes
  + deny-by-default create/delete gate
  + declarative slice scope
        ↓
closed-world immutable ApprovalScopeDefinition
        ↓
real Step29 ChangeSet hash only
        ↓
final ApprovalScopeBoundary
```

and when no code path can silently turn either:

```text
"was impacted"
```

or:

```text
"caller supplied a create/delete rule"
```

into:

```text
"is approved to mutate arbitrarily"
```

The frozen boundary is therefore:

```text
Step 23 = canonical user-operation effect authority
Step 27 = impact evidence + intent-boundary classification
Step 28 = what effects may be approved
Step 29 = what immutable canonical change is proposed inside that scope
Step 32 = who may approve/execute it
Step 33 = whether actual effects stayed inside it
```
