# Step 27 — Dependency / Constraint / Impact / Propagation Design

**Status:** Approved in-chat design; written-spec review pending  
**Date:** 2026-08-29  
**Base:** `main@80fb3a181494673e83e5466adc92275d30315790`  
**Branch:** `feat/step27-impact-layer`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step 27 introduces a standalone, provider-neutral **Impact Layer** between the completed D6 binding/interaction flow and the later D7 governance/execution flow.

The Step 27 responsibility is narrowly defined as:

```text
Given a fully materialized canonical operation,
its Phase-B PlanningSnapshot / SnapshotSet,
and structured dependency / constraint evidence,
compute what this task may affect,
what must be propagated or revalidated,
and what must be escalated as an exception.
```

The resulting architecture is:

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

The master spec also explicitly separates five graph concepts:

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

An IFC or Metro relationship MAY be evidence used to derive or support a dependency, but it MUST NOT automatically become a dependency merely because two entities are semantically related.

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

The package owns task-scoped impact analysis contracts and deterministic analysis behavior.

It SHALL NOT be implemented inside `platform/changeset`, because ChangeSet remains a later consumer of the analysis result.

### 3.2 Rejected: implement impact inside `platform/changeset`

Rejected because the current `platform/changeset` package is an earlier execution placeholder and does not yet represent the final v0.6 D7 model. Coupling Step 27 to it would blur the boundary between prediction/propagation and immutable execution intent.

### 3.3 Rejected: introduce a graph database now

Step 27 freezes graph semantics and consumes structured evidence, but it does not need a project-wide graph persistence engine, graph query service, Neo4j dependency, or full-model dependency rebuild.

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

Step 27 SHALL consume D5 refs/evidence; it SHALL NOT mutate D5 authoritative state.

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

The master-spec values are frozen:

```text
HARD
SOFT
ADVISORY
```

Semantic meaning:

- `HARD` — a system/engineering invariant must be preserved;
- `SOFT` — a design choice exists and may require review/replan;
- `ADVISORY` — the relationship affects checking or user guidance but does not itself mandate a model change.

Unknown values MUST fail closed.

### 5.2 Propagation owner

The master-spec values are frozen:

```text
HOST_NATIVE
SEMANTIC_RUNTIME
AGENT
```

Meaning:

- `HOST_NATIVE` — native Host associativity is expected to create the side effect; DSP predicts and later verifies it;
- `SEMANTIC_RUNTIME` — the propagation can be derived deterministically by platform semantic rules;
- `AGENT` — the propagation contains design freedom and requires replan / HITL rather than automatic mutation.

### 5.3 Propagation action

The master-spec action vocabulary is frozen:

```text
AUTO_MUTATE
RECOMPUTE
REVALIDATE
MARK_DIRTY
REPLAN
BLOCK
```

In Step 27, `AUTO_MUTATE` is purely a planning classification. It means “eligible to become a deterministic derived modification in a later ChangeSet.” It MUST NOT cause model mutation in Step 27.

---

## 6. Long-lived evidence contracts

Step 27 SHALL distinguish long-lived relationship/dependency/constraint evidence from task-runtime impact output.

### 6.1 `RelationshipEvidence`

Conceptual contract:

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

Conceptual contract:

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
- `strength`, `propagation_owner`, and `propagation_action` use the frozen enums;
- provider-native object ids/types are forbidden;
- evidence refs are informational/provenance bindings, not free-form authority overrides.

### 6.3 `ConstraintRule`

Conceptual contract:

```text
ConstraintRule {
  constraint_id
  applies_to[]
  rule_kind
  severity
  evaluation_spec
  evidence_refs[]
}
```

`evaluation_spec` MUST be structured and deterministically evaluable in the Step 27 MVP. Natural-language prose MAY accompany the rule for human explanation but MUST NOT be the machine decision mechanism.

The MVP SHALL use a deliberately small structured constraint form sufficient to prove deterministic evaluation. Step 27 does not introduce a general-purpose DSL or arbitrary code execution engine.

---

## 7. Task-runtime input contract

The analyzer input conceptually contains:

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

At minimum, the analysis input/output must preserve stable references/hashes for:

```text
PlanningSnapshot
SnapshotSet
SemanticEnvironmentRef
```

If the analyzer is given inconsistent snapshot/environment references, it MUST fail closed rather than silently analyze mixed state.

### 7.3 Intent boundary

The request SHALL carry a structured intent boundary describing which direct entities/effects the user requested.

A derived impact outside that boundary is not automatically forbidden, but it MUST be identified so downstream review can distinguish intended change from derived scope expansion.

---

## 8. Core analysis algorithm

Step 27 SHALL be deterministic-first and SHALL NOT call a free-form LLM.

Conceptual sequence:

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

Conceptual contract:

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

- every predicted affected entity must be traceable to an explicit dependency/rule decision;
- `HOST_NATIVE` impacts normally set `requires_verification = true` because the Host is expected to produce the associated side effect;
- predicted impact does not itself contain a HostCommand or provider-native routing metadata.

---

## 10. `PropagationBundle`

Safe deterministic propagation SHOULD be grouped by rule/action rather than producing one approval line per entity.

Conceptual contract:

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
- bundles MUST be stable for equivalent input ordering.

A bundle is appropriate only when the rule/action is deterministic and homogeneous enough to review as one propagation class.

---

## 11. `ImpactException`

The design follows the master spec's **exception-first review** principle.

Conceptual contract:

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

Step 27 SHALL create an exception when at least one of the following applies:

- `propagation_owner == AGENT`;
- `propagation_action == REPLAN`;
- `propagation_action == BLOCK`;
- a hard constraint fails;
- the predicted propagation exceeds the declared intent boundary;
- the analyzer cannot deterministically evaluate required structured evidence;
- required evidence is internally inconsistent.

`AGENT` ownership MUST NOT be silently converted into `AUTO_MUTATE`.

---

## 12. `ImpactAnalysis`

The Step 27 output is frozen conceptually as:

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

The implementation SHALL be value-oriented and defensively copy mutable input structures.

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

The fingerprint SHALL bind at least:

```text
canonical operation
material canonical arguments
direct targets
PlanningSnapshot ref/hash
SnapshotSet ref/hash
SemanticEnvironment ref/hash
normalized dependency edges
normalized constraint rules
intent boundary
```

Changing any material item above MUST change the fingerprint.

The fingerprint exists so Step 28+ can bind review/governance decisions to one exact impact analysis result.

---

## 14. MOVE reference vertical

Step 27 SHALL prove the architecture with a provider-neutral MOVE fixture rather than introducing a new wall-thickness canonical operation in the same step.

Example input:

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

For `OPENING-001`, `HOST_NATIVE + REVALIDATE` means DSP predicts the Host-native associativity effect and requires later verification; Step 27 does not generate a duplicate platform mutation.

---

## 15. Constraint behavior in the MVP

The MVP SHALL include at least one structured deterministic constraint fixture that can:

```text
PASS
FAIL
NOT_APPLICABLE
```

A failed `HARD` constraint SHALL generate a blocking exception.

An invalid or un-evaluable required constraint MUST fail closed or create a blocking exception according to whether the request itself is invalid versus the design state violates a valid rule. The distinction SHALL be encoded with structured reason codes, not natural-language parsing.

Step 27 SHALL NOT introduce arbitrary Python callbacks from providers as constraint rules.

---

## 16. Error handling

The package SHALL expose stable, machine-readable error categories/codes for invalid analysis input. At minimum the implementation must distinguish:

```text
SNAPSHOT_MISMATCH
SEMANTIC_ENVIRONMENT_MISMATCH
DEPENDENCY_INVALID
CONSTRAINT_INVALID
IMPACT_INPUT_INVALID
```

These are Step 27 domain errors. Integration with the repository-wide `ErrorShape` envelope may be performed by callers; the core analyzer SHOULD remain usable as a deterministic library.

Natural-language error text MUST NOT drive retry/replan behavior.

---

## 17. Architecture constraints

Step 27 architecture tests SHALL enforce:

1. `design_impact` does not import AutoCAD, Revit, Tekla, or other Host product packages.
2. `design_impact` does not import `HostCommand`.
3. `design_impact` does not call ChangeSetBuilder or provider execution paths.
4. provider-native ids/types cannot appear in public impact contracts.
5. Relationship evidence cannot be implicitly promoted to DependencyEdge by the analyzer.
6. Semantic provider packages may provide evidence fixtures/adapters but do not own propagation decisions.

---

## 18. TDD acceptance criteria

The implementation plan SHALL cover at least the following RED→GREEN behavior:

1. Relationship evidence alone does not produce predicted impact.
2. Dependency strength accepts only `HARD/SOFT/ADVISORY`.
3. Propagation owner accepts only `HOST_NATIVE/SEMANTIC_RUNTIME/AGENT`.
4. Propagation action accepts only `AUTO_MUTATE/RECOMPUTE/REVALIDATE/MARK_DIRTY/REPLAN/BLOCK`.
5. `HOST_NATIVE` produces prediction/verification requirements without a platform mutation proposal.
6. `SEMANTIC_RUNTIME` deterministic propagation can become a `PropagationBundle`.
7. `AGENT` propagation enters the Exception Set.
8. `BLOCK` creates a blocking exception.
9. safe homogeneous propagation with the same rule/action groups deterministically.
10. impact outside the intent boundary enters the Exception Set.
11. invalid structured constraint evidence fails closed.
12. failed HARD constraint creates a blocking exception.
13. PlanningSnapshot/SnapshotSet mismatch fails closed.
14. SemanticEnvironment mismatch fails closed.
15. identical semantic inputs produce a stable fingerprint regardless of input ordering.
16. changing a material dependency/rule/snapshot/argument changes the fingerprint.
17. Metro/enterprise evidence does not directly construct a ChangeSet.
18. `design_impact` has no Host product imports.
19. `design_impact` has no HostCommand execution path.
20. Step25/26 regression suites remain green.
21. Step27 output is sufficient for Step28 to consume without provider-native data.

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

The frozen sequence remains:

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
