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

### 3.2 Rejected: build final boundary inside legacy `platform/changeset`

The current `platform/changeset` package still models a mutable list of `HostDelta` values and therefore does not represent the v0.6 canonical immutable ChangeSet contract.

Step 28 MUST NOT be coupled to that placeholder in order to obtain an artificial `changeset_hash`.

### 3.3 Rejected: make `ImpactAnalyzer` emit approval scope directly

Step 27 owns prediction, propagation classification, constraints, and exceptions. Step 28 owns governance effect boundaries.

Merging them would make dependency analysis authoritative for approval scope and would erase the independent contract that Step 29 and Step 33 need.

---

## 4. Ownership boundary

### 4.1 Step 27 owns impact evidence

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

Step 28 does not recompute dependency traversal or constraints.

### 4.2 Step 28 owns effect-scope admission

Step 28 decides:

- which existing entities may change;
- which canonical aspects may change on each admitted entity set;
- what creations are admissible;
- what deletions are admissible;
- which propagation bundles are admitted;
- within which document/effect partitions future `ExecutionSlice` values may be planned;
- whether the impact result is approvable at all.

### 4.3 Step 29 owns immutable ChangeSet materialization

Step 29 receives a frozen scope definition and creates the canonical immutable ChangeSet.

Step 29 may only bind the resulting real `changeset_hash` to the existing scope body. It MUST NOT:

- add a new existing-entity rule;
- add an aspect to an existing rule;
- add creation or deletion permission;
- add a propagation bundle;
- widen a slice-scope rule.

Any scope change requires a new `ApprovalScopeDefinition` and therefore a new `scope_body_hash`.

### 4.4 Step 32 / Gateway owns approval authority

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

- `changeset_hash` MUST be non-empty and real; placeholder/TBD values are invalid;
- every rule body MUST be copied exactly from the frozen definition;
- bind MUST NOT accept replacement or extra rule lists;
- bind MUST NOT depend on ProviderBinding, HostCommand, approval state, or policy state.

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

Likewise, an existing entity admitted for `PLACEMENT` and `GEOMETRY` is **not** implicitly admitted for:

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
- duplicate direct effects for the same semantic id normalize to one exact rule only when their aspect sets are identical; conflicting duplicates are invalid;
- a direct effect cannot introduce a non-direct target.

For MOVE, upstream canonical effect evidence may state:

```text
WALL-001 -> [PLACEMENT, GEOMETRY]
```

Step 28 copies that explicit canonical effect boundary; it does not derive the aspect set from the text `MOVE`.

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

### 10.2 No action-name inference

The planner MUST NOT contain logic such as:

```text
REVALIDATE => allow PLACEMENT + GEOMETRY
RECOMPUTE  => allow PROPERTIES
```

Propagation action names classify behavior; they do not define authorized aspects.

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
- no blocking exception prevents scope planning.

A provider or semantic package cannot enlarge scope merely by emitting a relationship/rule name. The platform-owned recipe/admission step remains authoritative.

---

## 12. Creation rules

Create-like operations cannot be verified with an old-entity allowlist alone.

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

Requirements:

- `canonical_operation` is a canonical operation id, never a provider tool name;
- `source_selector` uses the same restricted selector AST;
- `entity_kinds[]` contains canonical kind identifiers only;
- `max_count`, when present, is a positive integer;
- `required_derivation`, when present, is an exact structured derivation/rule reference;
- no creation permission exists unless a `CreationRule` exists.

Example future OFFSET rule:

```text
canonical_operation = offset.v1
source = WALL-001
entity_kinds = [ifc:IfcWall]
max_count = 1
required_derivation = RULE-OFFSET-WALL
```

Creating three walls plus one unrelated polyline would therefore be outside the approved scope.

---

## 13. Deletion rules

```text
DeletionRule {
  rule_id
  selector
}
```

Deletion is always explicit.

No deletion rule means no deletion permission.

Step 28 does not infer delete permission from `replacement`, `split`, `rebuild`, or other natural-language operation descriptions.

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
- each rule MUST be assigned to at least one compatible document scope before the definition is considered complete;
- unknown/future `execution_slice_id` values are forbidden.

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
  impact_analysis
  intent_boundary

  direct_entity_effects[]
  scope_effect_recipes[]

  creation_rules[]
  deletion_rules[]
  execution_slice_scope_rules[]
}
```

`intent_boundary` is supplied explicitly because Step 27 uses it to classify intent expansion, while Step 28 needs the same machine-readable boundary when validating that explicit scope evidence has not reintroduced an out-of-intent effect.

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
3. Validate IntentBoundary/direct-target consistency
4. Validate direct canonical effect evidence
5. Materialize direct ExistingEntityRule values
6. Match predicted impacts to explicit ScopeEffectRecipe values
7. Fail closed for undefined effect-bearing impact scope
8. Materialize admitted predicted-side-effect ExistingEntityRule values
9. Validate explicit CreationRule / DeletionRule values
10. Admit only propagation bundles backed by explicit recipes
11. Validate declarative ExecutionSliceScopeRule coverage
12. Normalize all rule ordering/set-valued fields
13. Compute scope_body_hash
14. Return immutable ApprovalScopeDefinition
```

No step may query Host APIs or provider execution schemas.

---

## 18. Hashing contract

Hashing follows the repository's deterministic canonical-JSON + SHA-256 pattern.

### 18.1 `scope_body_hash`

`scope_body_hash` binds the exact normalized pre-ChangeSet effect boundary and at minimum includes:

```text
impact_analysis_fingerprint
planning_snapshot id/hash/document
snapshot_set id/hash/member ids
semantic_environment id/hash
normalized existing_entity_rules
normalized creation_rules
normalized deletion_rules
normalized propagation_bundle_ids
normalized execution_slice_scope_rules
```

Opaque generated ids MUST NOT make semantically identical scope bodies hash differently unless the id is itself a semantic reference used by another rule. Hash payloads therefore use normalized rule content and stable cross-references rather than object construction order.

Equivalent input ordering MUST produce the same hash.

Changing any material permission or upstream snapshot/environment/impact binding MUST change `scope_body_hash`.

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
SCOPE_PREDICATE_INVALID
SCOPE_RULE_INVALID
SCOPE_SLICE_RULE_INVALID
CHANGESET_HASH_INVALID
```

Rules:

- malformed/unknown aspect, selector, predicate, or rule -> fail closed;
- blocking impact exception -> `SCOPE_NOT_APPROVABLE`;
- required predicted side effect without explicit recipe -> `SCOPE_EFFECT_UNDEFINED`;
- future/placeholder ChangeSet hash -> `CHANGESET_HASH_INVALID`;
- natural-language text MUST NOT drive retry or scope expansion.

---

## 20. MOVE reference vertical

### 20.1 Safe case

Input:

```text
MOVE WALL-001

ImpactAnalysis:
  direct:
    WALL-001

  predicted:
    OPENING-001
      dependency_ref = DEP-OPENING
      owner = HOST_NATIVE
      action = REVALIDATE

    ANNOTATION-002
      dependency_ref = DEP-ANNOTATION
      owner = SEMANTIC_RUNTIME
      action = RECOMPUTE

  bundle:
    PB-ANNOTATION
```

Explicit Step 28 evidence:

```text
DirectEntityEffect:
  WALL-001 -> [PLACEMENT, GEOMETRY]

ScopeEffectRecipe:
  DEP-OPENING -> [PLACEMENT, GEOMETRY]

ScopeEffectRecipe:
  DEP-ANNOTATION -> [PLACEMENT, PROPERTIES]
  propagation_bundle_id = PB-ANNOTATION
```

Expected definition:

```text
existing:
  WALL-001       [PLACEMENT, GEOMETRY]
  OPENING-001    [PLACEMENT, GEOMETRY]
  ANNOTATION-002 [PLACEMENT, PROPERTIES]

propagation_bundle_ids:
  [PB-ANNOTATION]

deletion_rules:
  []
```

The exact annotation aspect set comes from the explicit recipe, not from the word `RECOMPUTE`.

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

---

## 21. Architecture constraints

Architecture tests SHALL enforce:

1. `design_approval_scope` does not import AutoCAD, Revit, Tekla, or other Host product packages.
2. It does not import `HostCommand` or provider execution contracts.
3. It does not depend on the current legacy `platform/changeset` mutable HostDelta model.
4. It may consume public `design_impact` value contracts only.
5. Provider/native ids and tool schemas do not appear in public Step 28 contracts.
6. Relationship evidence alone cannot create scope permission.
7. Propagation action names cannot determine allowed canonical aspects.
8. Blocking `ImpactException` values cannot be converted into larger scope.
9. Creation and deletion are deny-by-default.
10. `execution_slice_scopes` never contains future concrete slice ids.
11. Step 29 binding can add only `changeset_hash`, final `scope_id`, and derived `scope_hash`; it cannot widen the frozen body.
12. Policy/risk/approver/grant records remain outside Step 28.

---

## 22. TDD acceptance criteria for the later implementation plan

The implementation plan MUST include RED -> GREEN coverage for at least:

1. Empty deletion rules deny all deletions.
2. Existing entity permission is aspect-specific and deny-by-default.
3. Unknown/native aspect values fail closed.
4. Entity selectors require exactly one of entities or predicate.
5. Predicate AST rejects free-form expressions and unknown operators/fields.
6. `EQ` and `IN` cardinality rules are enforced.
7. Relationship evidence alone cannot enlarge scope.
8. Direct entity effects cannot target an entity outside `ImpactAnalysis.direct_targets`.
9. Direct effect aspects are never inferred from the canonical operation name.
10. A predicted Host-native effect with no explicit recipe fails `SCOPE_EFFECT_UNDEFINED`.
11. A deterministic propagation bundle with no explicit recipe is not admitted.
12. A recipe keyed by an unknown `dependency_ref` fails closed.
13. `rule_ref` is optional provenance, not the authoritative machine key.
14. A blocking ImpactException returns `SCOPE_NOT_APPROVABLE` and no definition.
15. A non-blocking advisory exception does not enlarge effect scope.
16. Creation requires an explicit `CreationRule`.
17. Creation `max_count` and canonical kind constraints are preserved.
18. Deletion requires an explicit `DeletionRule`.
19. Execution-slice scope rules may reference only rules in the same definition.
20. No future `execution_slice_id` can appear in Step 28 contracts.
21. Input list/set ordering does not change `scope_body_hash`.
22. Changing an allowed aspect changes `scope_body_hash`.
23. Changing impact fingerprint changes `scope_body_hash`.
24. Changing PlanningSnapshot/SnapshotSet/SemanticEnvironment binding changes `scope_body_hash`.
25. Step 28 cannot create a final boundary without a real ChangeSet hash.
26. Binding the same scope body to different ChangeSet hashes yields different `scope_hash` values.
27. Binding MUST preserve the frozen rule body byte-for-byte after normalization.
28. Provider/native metadata leakage is rejected by architecture tests.
29. Step 27 / Step 26 / Step 25 regression suites remain green.

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
- Host-specific mutation schemas.

---

## 24. Completion boundary

Step 28 is complete when the repository has a provider-neutral package whose public behavior proves:

```text
ImpactAnalysis
  + explicit canonical direct effects
  + explicit effect recipes
  + explicit create/delete rules
  + declarative slice scope
        ↓
closed-world immutable ApprovalScopeDefinition
        ↓
real Step29 ChangeSet hash only
        ↓
final ApprovalScopeBoundary
```

and when no code path can silently turn:

```text
"was impacted"
```

into:

```text
"is approved to mutate arbitrarily"
```

The frozen boundary is therefore:

```text
Step 28 = what effects may be approved
Step 29 = what immutable canonical change is proposed inside that scope
Step 32 = who may approve/execute it
Step 33 = whether actual effects stayed inside it
```
