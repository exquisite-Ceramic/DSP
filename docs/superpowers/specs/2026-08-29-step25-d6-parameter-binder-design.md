# Step 25 — Deterministic D6 Parameter Binder Design

**Status:** Approved design  
**Date:** 2026-08-29  
**Base:** `main@02e6c5040da9ad38f809b26ed00a6878569af777`  
**Branch:** `feat/step25-d6-parameter-binder`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step 25 implements the D6 deterministic Parameter Binder that sits after D4/LLM operation selection and before Phase-B Operation Freshness.

The frozen pipeline is:

```text
ContextSnapshot
  ↓
D4 ResolvedOperation / LLM Action Space
  ↓
LLM OperationProposal                    # canonical_operation + INTENT only
  ↓
D6 ParameterBinder
  ├─ INTENT
  ├─ CONTEXT
  ├─ CANONICAL_DEFAULT
  └─ DERIVED
  ↓
BoundOperationProposal
  ↓
derive OperationFreshnessContract
  ↓
D5 Freshness / Coverage / Assurance barrier
  ↓
PlanningSnapshot / SnapshotSet
```

Step 25 MUST NOT implement Host-native interaction or ProviderBinding.

## 2. Roadmap boundary

The already approved Step 23 roadmap remains normative:

```text
Step25 — D6 Slot Binder
Step26 — InteractionSession / Host interaction
Step27+ — Impact / ChangeSet / Governance
Step30 — canonical ExecutionUnit
Step31 — ProviderBinding / binding_set_hash
```

Provider-native values are therefore out of scope for Step 25.

## 3. Ownership model

### 3.1 LLM owns only INTENT values

An `OperationProposal` carries:

```text
canonical_operation
intent_arguments
```

`intent_arguments` MAY contain only slots classified `INTENT` by the platform-owned `CanonicalOperationDefinition.slot_binding_policy`.

The binder MUST reject an LLM/user attempt to provide `CONTEXT`, `CANONICAL_DEFAULT`, `DERIVED`, or `PROVIDER` slots.

### 3.2 D6 owns deterministic canonical binding

Step 25 binds:

```text
INTENT
CONTEXT
CANONICAL_DEFAULT
DERIVED
```

using explicit contract metadata and registered deterministic recipes/resolvers.

D6 MUST NOT infer ownership from field names, descriptions, Host product names, or provider schemas.

### 3.3 PROVIDER is deferred

`PROVIDER` slots are not populated in Step 25. Examples that remain forbidden here include:

```text
AutoCAD Handle
Revit ElementId
internal unit
revision token
idempotency key
provider_server
provider_tool
```

Provider-native binding belongs to Step 31.

## 4. Public contracts

### 4.1 OperationProposal

```text
OperationProposal {
  canonical_operation
  intent_arguments
}
```

For MOVE:

```json
{
  "canonical_operation": "move.v1",
  "intent_arguments": {
    "displacement": [100, 0, 0]
  }
}
```

### 4.2 ParameterBindingContext

D6 consumes a small provider-neutral read model bound to the same ContextSnapshot used for planning:

```text
ParameterBindingContext {
  context_snapshot_id
  context_snapshot_hash
  document_ref
  semantic_environment_ref
  selection[]               # SemanticId only
  context_values{}
}
```

This is intentionally distinct from Step 24 `SemanticEligibilityContext`:

```text
SemanticEligibilityContext = can this canonical action apply?
ParameterBindingContext     = what are this action's canonical slot values?
```

The binder MUST NOT import D5 storage/projection internals or Host packages.

### 4.3 BindingResolverKind

Step 25 freezes deterministic recipe kinds:

```text
CONTEXT_SELECTION
CONTEXT_VALUE
CANONICAL_DEFAULT
DERIVED
```

These are implementation instructions for non-INTENT canonical slots. They do not replace the canonical slot binding class.

### 4.4 SlotBindingRecipe

```text
SlotBindingRecipe {
  slot
  resolver_kind
  source_key?
  default_value?
}
```

Validation MUST ensure the recipe kind agrees with `slot_binding_policy`:

```text
CONTEXT           → CONTEXT_SELECTION | CONTEXT_VALUE
CANONICAL_DEFAULT → CANONICAL_DEFAULT
DERIVED           → DERIVED
INTENT             → no deterministic recipe
PROVIDER           → no Step25 recipe
```

For `move.v1`:

```text
targets:
  binding_class = CONTEXT
  resolver_kind = CONTEXT_SELECTION

displacement:
  binding_class = INTENT
```

### 4.5 Derived resolver registry

DERIVED recipes reference a stable resolver id. `ParameterBinder` receives a registry:

```text
resolver_id → deterministic callable
```

A missing resolver MUST fail closed.

In Step 25 v1, derived resolvers run after INTENT, CONTEXT, and CANONICAL_DEFAULT bindings and receive a read-only snapshot of the already bound canonical arguments. Dependencies between multiple DERIVED slots are not modeled as a DAG in this step.

### 4.6 Binding evidence

Every slot actually bound by Step 25 emits typed evidence:

```text
SlotBindingEvidence {
  slot
  binding_class
  source
  source_ref?
}
```

Examples:

```text
targets      ← ContextSnapshot.selection
displacement ← OperationProposal.intent_arguments
unit         ← CanonicalDefault
value        ← DerivedResolver:<resolver_id>
```

PROVIDER slots are deferred and therefore do not claim Step25 binding evidence.

### 4.7 PlanningRequirements

The D6 output carries the canonical requirements needed to derive Phase-B planning barriers:

```text
PlanningRequirements {
  operation_freshness_requirements
  coverage_requirements
  assurance_requirements
}
```

These values come only from `CanonicalOperationDefinition`, never from candidate provider metadata.

### 4.8 BoundOperationProposal

```text
BoundOperationProposal {
  operation
  arguments
  binding_evidence
  context_snapshot_ref
  planning_requirements
  semantic_environment_ref
}
```

Step 25 represents `operation` as a stable `CanonicalOperationRef` containing canonical operation id + version.

`context_snapshot_ref` contains snapshot id/hash/document ref only; `semantic_environment_ref` stays explicit as a separate field.

For MOVE:

```text
operation:
  canonical_operation = move.v1
  version = 1.0.0

arguments:
  targets = [S-WALL-001]
  displacement = [100, 0, 0]

binding_evidence:
  targets:
    binding_class = CONTEXT
    source = ContextSnapshot.selection
  displacement:
    binding_class = INTENT
    source = OperationProposal.intent_arguments
```

No Host-native identity or provider routing value may appear.

## 5. Binder algorithm

For one proposal/context pair, `ParameterBinder.bind(...)` SHALL:

1. resolve exactly one platform canonical operation definition;
2. reject unknown canonical operation ids;
3. validate that every submitted proposal key is a canonical slot;
4. reject submitted keys whose binding class is not `INTENT`;
5. bind supplied INTENT values and require every required INTENT slot;
6. bind CONTEXT slots only through explicit recipes;
7. bind CANONICAL_DEFAULT slots only through explicit literal default recipes;
8. bind DERIVED slots only through registered deterministic resolver ids;
9. leave PROVIDER slots absent;
10. require every required non-PROVIDER slot to be bound;
11. validate bound arguments against the full canonical JSON Schema with only required PROVIDER slots temporarily deferred;
12. produce immutable/defensively copied `BoundOperationProposal` values and binding evidence.

## 6. Fail-closed rules

The binder MUST fail closed when:

- the operation is unknown;
- proposal arguments contain unknown slots;
- proposal arguments contain a non-INTENT slot;
- a required INTENT slot is missing;
- a CONTEXT/DEFAULT/DERIVED slot has no explicit recipe;
- a recipe binding class conflicts with the canonical slot policy;
- a required context value is unavailable;
- a canonical default recipe has no explicit default value;
- a DERIVED resolver id is absent or unregistered;
- a required non-PROVIDER slot remains unbound;
- JSON Schema validation fails;
- context snapshot id/hash/document/environment identifiers are empty.

Optional deterministic slots MAY remain absent only when their resolver has no value and the canonical schema does not require the slot.

## 7. Immutability

All inputs that are mappings/lists SHALL be defensively copied on construction or output.

Mutating caller-owned proposal/context/default dictionaries after construction MUST NOT mutate D6 state or a completed `BoundOperationProposal`.

## 8. MOVE_V1 frozen Step25 fixture

Existing Step 23 canonical contract remains unchanged:

```text
canonical_operation = move.v1
version             = 1.0.0

targets:
  binding = CONTEXT

displacement:
  binding = INTENT

operation freshness:
  PLACEMENT / FRESH
```

Step 25 adds only the D6 recipe:

```text
move.v1.targets → CONTEXT_SELECTION
```

Given:

```text
ContextSnapshot.selection = [S-001, S-002]
LLM displacement          = [100, 0, 0]
```

D6 SHALL produce:

```text
targets      = [S-001, S-002]
displacement = [100, 0, 0]
```

with no Host/provider-native values.

## 9. Phase-B boundary

Step 25 does not execute the D5 barrier. It only produces the complete canonical material needed by the next stage.

The required ordering remains:

```text
D6 material binding
  ↓
BoundOperationProposal
  ↓
derive OperationFreshnessContract
  ↓
D5 selective reconstruction / barrier
```

A later integration step may translate `planning_requirements.operation_freshness_requirements` through semantic-runtime requirement normalization.

## 10. Out of scope

Step 25 MUST NOT add:

- `InteractionSession` or Host canvas prompts — Step 26;
- Impact/propagation — Step 27+;
- ChangeSet/Approval — Step 27+;
- canonical ExecutionSlice/ExecutionUnit rewrite — Step 30;
- provider native constraints — Step 31;
- ProviderBinding or binding_set_hash — Step 31;
- HostCommand creation;
- AutoCAD/Revit/Tekla-specific branches;
- Host-native identity conversion;
- provider input adapter/unit conversion.

## 11. Acceptance criteria

Step 25 is complete only when tests prove:

1. MOVE binds `targets` from snapshot selection and `displacement` from INTENT.
2. LLM cannot submit `targets` or other non-INTENT slots.
3. Unknown/missing required slots fail closed.
4. Empty required context selection fails closed.
5. explicit canonical defaults work and missing default recipes fail closed.
6. registered DERIVED resolvers work and missing resolver ids fail closed.
7. PROVIDER slots remain deferred and cannot be supplied by LLM.
8. complete arguments are canonical-schema validated.
9. binding evidence records source ownership for every Step25-bound slot.
10. planning requirements are copied only from canonical action metadata.
11. outputs are defensive copies.
12. architecture guards prevent imports/references to AutoCAD/Revit/Tekla, HostCommand, provider_tool, handles, ElementId, or ProviderBinding in the production D6 module.
13. Step23/Step24 and relevant Python regressions remain green.
