# Step 27 — Dependency / Constraint / Impact / Propagation Design

**Status:** Approved in-chat design; written-spec review pending  
**Date:** 2026-08-29  
**Base:** `main@80fb3a181494673e83e5466adc92275d30315790`  
**Branch:** `feat/step27-impact-layer`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step 27 introduces a standalone, provider-neutral **Impact Layer** between the completed D6 binding/interaction flow and the later D7 governance/execution flow.

Its responsibility is narrowly defined as:

```text
Given a fully materialized canonical operation,
its Phase-B PlanningSnapshot / SnapshotSet,
and structured dependency / constraint evidence,
compute what this task may affect,
what must be propagated or revalidated,
and what must be escalated as an exception.
```

The architecture is:

```text
BoundOperationProposal
        +
PlanningSnapshot / SnapshotSet
        +
SemanticEnvironmentRef
        +
Dependency / Constraint Evidence
        ↓
ImpactAnalyzer
        ↓
ImpactAnalysis
  ├─ predicted impacts
  ├─ propagation bundles
  └─ exception set
        ↓
Step 28 ApprovalScopeBoundary
```

Step 27 MUST NOT build, approve, bind, execute, or apply a ChangeSet.

---

## 2. Why Step 27 is a separate platform boundary

The v0.6 master spec places the Impact Layer after D6 and Phase-B freshness, but before D7 ChangeSet/governance:

```text
BoundOperationProposal
→ Operation Freshness
→ PlanningSnapshot / SnapshotSet
→ Impact Analyzer / Propagation
→ ApprovalScopeBoundary
→ ChangeSetBuilder
```

The master spec also separates five graph concepts:

1. Relationship Graph — long-lived semantic relationships;
2. Dependency Graph — long-lived change-dependency evidence;
3. Constraint / Invariant Graph — long-lived post-change requirements;
4. Change Impact Graph — task-runtime predicted impact;
5. Change DAG — task-runtime final derived-change / execution causality.

These concepts MUST NOT collapse into one generic graph.

In particular:

```text
RelationshipEdge != DependencyEdge
```

An IFC or Metro relationship MAY be evidence used to support a dependency, but it MUST NOT automatically become a dependency merely because two entities are semantically related.

---

## 3. Chosen approach

### 3.1 Chosen: independent `platform/impact` package

Step 27 SHALL introduce:

```text
platform/impact/
  src/design_impact/
    __init__.py
    contracts.py
    rules.py
    analyzer.py
```

The package owns task-scoped impact contracts and deterministic analysis behavior.

It SHALL NOT be implemented inside `platform/changeset`, because ChangeSet remains a later consumer of the analysis result.

### 3.2 Rejected: impact inside `platform/changeset`

Rejected because the current `platform/changeset` package is an earlier execution placeholder and does not yet represent the final v0.6 D7 model. Coupling Step 27 to it would blur prediction/propagation and immutable execution intent.

### 3.3 Rejected: graph database now

Step 27 freezes graph semantics and consumes structured evidence, but it does not introduce a project-wide graph persistence engine, graph query service, Neo4j dependency, or full-model dependency rebuild.

Storage/index technology remains replaceable behind the evidence contracts.

---

## 4. Ownership model

### 4.1 D5 / Semantic Runtime owns canonical task state

D5 remains authoritative for:

- canonical semantic projection;
- task-scoped progressive reconstruction;
- freshness / coverage / assurance;
- PlanningSnapshot / SnapshotSet;
- SemanticEnvironment pinning;
- semantic provenance and relationship evidence available to the task.

Step 27 consumes D5 refs/evidence; it does not mutate D5 authoritative state.

### 4.2 Semantic Providers contribute evidence, not propagation decisions

IFC4.3, Metro Semantic, and future enterprise providers MAY contribute structured evidence such as:

```text
domain relationships
IDS requirements
engineering constraints
validation rules
mapping provenance
```

They MUST NOT directly own:

```text
propagation owner
propagation action
Exception Set classification
ChangeSet construction
Host mutation
```

Those decisions belong to the platform Dependency / Constraint / Impact layer.

### 4.3 Impact Layer owns task-scoped prediction/classification

The Impact Layer owns:

- dependency traversal for the current operation;
- constraint evaluation against affected entities;
- impact classification;
- propagation owner/action classification;
- deterministic propagation bundling;
- exception extraction;
- stable analysis fingerprinting.

### 4.4 D7 remains downstream

Step 28+ owns approval scope, immutable ChangeSet, execution planning, ProviderBinding, grants, apply, verify, and reconcile.

Step 27 output is evidence/input to those later phases only.

---

## 5. Frozen enums

### 5.1 Dependency strength

```text
HARD
SOFT
ADVISORY
```

- `HARD` — a system/engineering invariant must be preserved;
- `SOFT` — a design choice exists and may require review/replan;
- `ADVISORY` — affects checking/guidance but does not itself mandate a model change.

Unknown values fail closed.

### 5.2 Propagation owner

```text
HOST_NATIVE
SEMANTIC_RUNTIME
AGENT
```

- `HOST_NATIVE` — native Host associativity is expected to create the side effect; DSP predicts and later verifies it;
- `SEMANTIC_RUNTIME` — propagation can be derived deterministically by platform semantic rules;
- `AGENT` — propagation contains design freedom and requires replan / HITL rather than automatic mutation.

### 5.3 Propagation action

```text
AUTO_MUTATE
RECOMPUTE
REVALIDATE
MARK_DIRTY
REPLAN
BLOCK
```

In Step 27, `AUTO_MUTATE` is only a planning classification: “eligible to become a deterministic derived modification in a later ChangeSet.” It MUST NOT cause model mutation in Step 27.

---

## 6. Long-lived evidence contracts

### 6.1 `RelationshipEvidence`

```text
RelationshipEvidence {
  relationship_id
  source_semantic_id
  target_semantic_id
  relationship_type
  evidence_refs[]
}
```

A `RelationshipEvidence` object by itself MUST NOT authorize impact propagation.

### 6.2 `DependencyEdge`

```text
DependencyEdge {
  dependency_id
  source_semantic_id
  target_semantic_id

  strength
  propagation_owner
  propagation_action

  rule_ref?
  evidence_refs[]
}
```

Requirements:

- source and target use canonical `SemanticId` values;
- the edge is directional for change-impact purposes;
- strength/owner/action use the frozen enums;
- provider-native object ids/types are forbidden;
- evidence refs are provenance bindings, not authority overrides.

### 6.3 `ConstraintRule`

```text
ConstraintRule {
  constraint_id
  applies_to[]
  strength
  rule_kind
  evaluation_spec
  evidence_refs[]
}
```

`evaluation_spec` MUST be structured and deterministically evaluable in the Step 27 MVP. Natural-language prose MAY accompany a rule for humans but MUST NOT be the machine decision mechanism.

The MVP SHALL support only a small, explicit deterministic rule form sufficient for tests. It SHALL NOT introduce a general-purpose DSL or arbitrary provider-supplied code execution.

---

## 7. Task-runtime input contract

```text
ImpactAnalysisRequest {
  bound_operation
  planning_snapshot_ref
  snapshot_set_ref
  semantic_environment_ref
  dependency_edges[]
  constraint_rules[]
  relationship_evidence[]
  intent_boundary
}
```

### 7.1 Bound operation

The operation MUST already have completed D6 binding or D6 interaction resume.

Step 27 MUST NOT infer missing D6 slots and MUST NOT call Host interaction.

### 7.2 Snapshot binding

Impact analysis MUST be bound to the exact Phase-B planning state that justified the operation.

At minimum, the input/output preserves stable references/hashes for:

```text
PlanningSnapshot
SnapshotSet
SemanticEnvironmentRef
```

Inconsistent snapshot/environment references fail closed.

### 7.3 Structured `IntentBoundary`

Intent scope MUST be machine-readable, not inferred from prose.

The Step 27 conceptual boundary is:

```text
IntentBoundary {
  direct_targets[]
  allowed_canonical_effects[]
  allowed_derived_rule_refs[]
}
```

Meaning:

- `direct_targets` are the entities explicitly targeted by the canonical operation;
- `allowed_canonical_effects` are the canonical effects already declared for the user operation;
- `allowed_derived_rule_refs` identifies deterministic dependency/constraint rules that upstream planning/policy has explicitly accepted as ordinary derived scope for this analysis.

A dependency may predict an affected entity outside `direct_targets` without automatically becoming an exception. However, a **proposed derived change** is outside the intent boundary when it requires an effect not present in `allowed_canonical_effects`, or relies on a derived rule not present in `allowed_derived_rule_refs`.

`HOST_NATIVE + REVALIDATE` prediction is not treated as a platform proposed mutation and therefore does not become scope expansion solely because the affected entity is outside `direct_targets`; it is still surfaced for later verification.

Step 28 remains responsible for the authoritative approval scope decision. Step 27 only classifies deterministic scope expansion using this input boundary.

---

## 8. Core analysis algorithm

Step 27 is deterministic-first and SHALL NOT call a free-form LLM.

```text
1. Validate request/snapshot/environment consistency
2. Seed direct targets from BoundOperationProposal
3. Traverse explicit DependencyEdge objects
4. Produce PredictedImpact records
5. Evaluate applicable ConstraintRule objects
6. Classify propagation owner/action
7. Group safe deterministic propagation into bundles
8. Extract design-freedom / blocking / scope-expanding cases into exceptions
9. Compute stable analysis fingerprint
10. Return immutable/value-oriented ImpactAnalysis
```

Relationship evidence may support explanation/provenance, but relationship traversal alone SHALL NOT create a dependency edge.

---

## 9. `PredictedImpact`

```text
PredictedImpact {
  source_semantic_id
  affected_semantic_id

  strength
  propagation_owner
  propagation_action

  dependency_ref
  evidence_refs[]
  requires_verification
}
```

Rules:

- every affected entity is traceable to an explicit dependency/rule decision;
- `HOST_NATIVE` impacts normally set `requires_verification = true`;
- predicted impact never contains HostCommand or provider-native routing metadata.

---

## 10. `PropagationBundle`

Safe deterministic propagation SHOULD be grouped by rule/action rather than producing one approval line per entity.

```text
PropagationBundle {
  bundle_id
  rule_ref

  strength
  propagation_owner
  propagation_action

  source_entities[]
  affected_entities[]

  deterministic
  proposed_changes[]
}
```

For Step 27:

- `proposed_changes` are canonical planning descriptions only;
- no ChangeSet id exists yet;
- no provider tool/native id exists;
- no mutation occurs;
- equivalent input ordering produces stable bundles.

A bundle is appropriate only when the rule/action is deterministic, non-blocking, and homogeneous enough to review as one propagation class.

---

## 11. `ImpactException`

The design follows the master spec's **exception-first review** principle.

```text
ImpactException {
  exception_id
  reason_code

  source_entities[]
  affected_entities[]

  strength
  propagation_owner
  requested_action

  blocking
  evidence_refs[]
}
```

Step 27 creates an exception when at least one applies:

- `propagation_owner == AGENT`;
- `propagation_action == REPLAN`;
- `propagation_action == BLOCK`;
- a valid HARD constraint evaluates to FAIL;
- a proposed derived change exceeds `IntentBoundary`;
- a valid rule explicitly classifies the situation as review-required.

`AGENT` ownership MUST NOT be silently converted into `AUTO_MUTATE`.

Invalid analysis definitions/inputs are **not** normal design exceptions; they fail closed as domain errors described in §16.

---

## 12. `ImpactAnalysis`

```text
ImpactAnalysis {
  analysis_id

  canonical_operation
  direct_targets[]

  planning_snapshot_ref
  snapshot_set_ref
  semantic_environment_ref

  predicted_impacts[]
  propagation_bundles[]
  exceptions[]

  analysis_fingerprint
}
```

The implementation SHALL be value-oriented and defensively copy mutable inputs.

The output MUST NOT contain:

```text
ChangeSet
ApprovalRecord
ExecutionSlice
ExecutionUnit
ProviderBinding
ExecutionGrant
HostCommand
AutoCAD Handle
Revit ElementId
provider_tool
```

---

## 13. Stable fingerprinting

Equivalent semantic inputs MUST produce the same `analysis_fingerprint` independent of incidental dictionary/list ordering.

The fingerprint binds at least:

```text
canonical operation
material canonical arguments
direct targets
PlanningSnapshot ref/hash
SnapshotSet ref/hash
SemanticEnvironment ref/hash
normalized dependency edges
normalized constraint rules
IntentBoundary
```

Changing any material item above changes the fingerprint.

Step 28+ can therefore bind governance decisions to one exact impact result.

---

## 14. MOVE reference vertical

Step 27 proves the architecture with a provider-neutral MOVE fixture rather than introducing a new wall-thickness canonical operation in the same step.

```text
Bound operation:
  move.v1
  targets = [WALL-001]

Dependencies:

WALL-001
 ├─ HARD → OPENING-001
 │    owner = HOST_NATIVE
 │    action = REVALIDATE
 │
 ├─ SOFT → ANNOTATION-002
 │    owner = SEMANTIC_RUNTIME
 │    action = RECOMPUTE
 │
 └─ SOFT → MEP-008
      owner = AGENT
      action = REPLAN
```

Expected classification:

```text
direct_targets:
  WALL-001

predicted_impacts:
  OPENING-001
  ANNOTATION-002
  MEP-008

propagation_bundles:
  ANNOTATION-002 → deterministic RECOMPUTE

exceptions:
  MEP-008 → REPLAN
```

For `OPENING-001`, `HOST_NATIVE + REVALIDATE` means DSP predicts Host-native associativity and requires later verification; Step 27 does not generate a duplicate platform mutation.

---

## 15. Constraint behavior in the MVP

The MVP includes at least one structured deterministic constraint fixture with outcomes:

```text
PASS
FAIL
NOT_APPLICABLE
```

The failure semantics are frozen:

```text
invalid ConstraintRule definition
or missing/invalid required evaluation input
    → fail closed with CONSTRAINT_INVALID or IMPACT_INPUT_INVALID

valid HARD ConstraintRule evaluates FAIL
    → ImpactException(blocking=true)

valid SOFT ConstraintRule evaluates FAIL
    → non-blocking review/replan exception unless the rule explicitly maps to BLOCK

valid rule evaluates PASS or NOT_APPLICABLE
    → no violation exception
```

This prevents implementation from treating malformed rule definitions as ordinary design problems.

Step 27 SHALL NOT execute arbitrary provider-supplied Python callbacks.

---

## 16. Error handling

The package exposes stable machine-readable domain errors at minimum:

```text
SNAPSHOT_MISMATCH
SEMANTIC_ENVIRONMENT_MISMATCH
DEPENDENCY_INVALID
CONSTRAINT_INVALID
IMPACT_INPUT_INVALID
```

Exact rules:

- malformed enum/edge structure → `DEPENDENCY_INVALID`;
- malformed constraint definition → `CONSTRAINT_INVALID`;
- missing/invalid data required to deterministically evaluate the request → `IMPACT_INPUT_INVALID`;
- inconsistent planning/snapshot refs → `SNAPSHOT_MISMATCH`;
- inconsistent semantic environment refs/hashes → `SEMANTIC_ENVIRONMENT_MISMATCH`.

Integration with repository-wide `ErrorShape` may be performed by callers; the core analyzer remains a deterministic library.

Natural-language error text MUST NOT drive retry/replan behavior.

---

## 17. Architecture constraints

Architecture tests SHALL enforce:

1. `design_impact` does not import AutoCAD, Revit, Tekla, or other Host product packages.
2. `design_impact` does not import `HostCommand`.
3. `design_impact` does not call ChangeSetBuilder or provider execution paths.
4. provider-native ids/types cannot appear in public impact contracts.
5. Relationship evidence cannot be implicitly promoted to DependencyEdge by the analyzer.
6. Semantic provider packages may contribute evidence but do not own propagation decisions.

---

## 18. TDD acceptance criteria

The implementation plan SHALL cover at least these RED→GREEN behaviors:

1. Relationship evidence alone does not produce predicted impact.
2. Dependency strength accepts only `HARD/SOFT/ADVISORY`.
3. Propagation owner accepts only `HOST_NATIVE/SEMANTIC_RUNTIME/AGENT`.
4. Propagation action accepts only `AUTO_MUTATE/RECOMPUTE/REVALIDATE/MARK_DIRTY/REPLAN/BLOCK`.
5. `HOST_NATIVE` produces prediction/verification requirements without a platform mutation proposal.
6. `SEMANTIC_RUNTIME` deterministic propagation can become a `PropagationBundle`.
7. `AGENT` propagation enters the Exception Set.
8. `BLOCK` creates a blocking exception.
9. safe homogeneous propagation with the same rule/action groups deterministically.
10. a proposed derived change outside `IntentBoundary` enters the Exception Set.
11. invalid structured dependency evidence fails closed.
12. invalid structured constraint evidence fails closed.
13. valid HARD constraint FAIL creates a blocking exception.
14. PlanningSnapshot/SnapshotSet mismatch fails closed.
15. SemanticEnvironment mismatch fails closed.
16. identical semantic inputs produce a stable fingerprint regardless of input ordering.
17. changing a material dependency/rule/snapshot/argument changes the fingerprint.
18. Metro/enterprise evidence cannot directly construct a ChangeSet.
19. `design_impact` has no Host product imports.
20. `design_impact` has no HostCommand execution path.
21. Step25/26 regressions remain green.
22. Step27 output is sufficient for Step28 without provider-native data.

---

## 19. Explicit non-goals

Step 27 MUST NOT implement:

```text
ApprovalScopeBoundary        # Step 28
immutable ChangeSet          # Step 29
Change DAG execution plan    # Step 29/30 boundary
ExecutionSlice               # Step 30
ExecutionUnit                # Step 30
ProviderBinding              # Step 31
ExecutionGrant
Host mutation
Host verification execution
full-project dependency graph rebuild
graph database/storage selection
arbitrary constraint DSL
free-form LLM impact classification
multi-Host distributed transaction
```

---

## 20. Roadmap boundary after Step 27

```text
Step 23  Canonical Action Contract
Step 24  Semantic Eligibility
Step 25  Deterministic Slot Binder
Step 26  InteractionSession / Host Interaction
Step 27  Dependency / Constraint / Impact / Propagation
Step 28  ApprovalScopeBoundary
Step 29  immutable ChangeSet
Step 30  ExecutionSlice / canonical ExecutionUnit
Step 31  ProviderBinding / binding_set_hash
```

Step 27 is complete only when it can deterministically transform a snapshot-bound canonical operation plus structured dependency/constraint evidence into a stable, provider-neutral `ImpactAnalysis`, while preserving all Step28+ responsibilities for later phases.
