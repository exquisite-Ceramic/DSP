# Step36 OFFSET CREATE / CreationRule / SCOPE_BREACH Design

## Status

Frozen after design approval on 2026-08-31.

## Context

Step34 proved a real AutoCAD `MODIFY` path through canonical action, approval scope, execution authority, real Host mutation, provider-neutral `ActualDelta`, Step33 scope reconciliation, semantic verification, and Saga success.

Step36 advances the Phase H proof from modification authority to **existence-effect authority**. The target scenario is an AutoCAD OFFSET-style operation that creates a new derived wall-like entity from one approved semantic source wall.

The current codebase already contains part of this architecture:

- Step28 defines `CreationRule` and `ExecutionSliceScopeRule.creation_rule_ids`.
- Step33 `ScopeComparator` already evaluates `ActualChangeKind.CREATE`, including canonical operation, created kind, source selector, derivation, and `max_count`.
- Step33 already emits deterministic creation violations such as `CREATION_OPERATION_FORBIDDEN`, `CREATION_KIND_FORBIDDEN`, `CREATION_SOURCE_FORBIDDEN`, `CREATION_DERIVATION_MISMATCH`, and `CREATION_COUNT_EXCEEDED`.

However, creation authority is not yet admitted end-to-end:

- Step23 canonical operation contracts express only canonical aspect effects.
- Step27 `IntentBoundary` expresses only canonical aspect effects and derived rule refs.
- Step28 currently rejects all requested creation/deletion rules with `SCOPE_EXISTENCE_EFFECT_UNSUPPORTED`.
- Step29 scope coverage and hashing assume operation authority is always backed by `ExistingEntityRule`.
- Step30 scope binding and slice selection likewise assume `scope_rule_ids` refer only to existing-entity rules.

Step36 closes that authority gap without turning CREATE into a fake canonical aspect and without allowing request-time scope expansion.

## Goal

Prove this authority chain:

`Canonical OFFSET Action -> explicit CREATE envelope -> IntentBoundary -> Step28 CreationRule -> Step29 ChangeSet -> Step30 ExecutionSlice -> Step31 ProviderBinding -> Step32 admission -> AutoCAD OFFSET creation -> provider-neutral ActualDelta.CREATE -> Step33 ScopeComparator`

The critical security proof is:

```text
one approved creation, matching source/kind/derivation
    -> WITHIN_SCOPE

two actual creations against max_count = 1
    -> CREATION_COUNT_EXCEEDED
    -> SCOPE_BREACH
```

Step36 is primarily an **existence-authority and scope-reconciliation proof**. It does not redefine semantic identity assignment for newly created entities and does not require a new CREATE-specific Step33 semantic-verification language.

## Architectural Decision

### Explicit existence effects

CREATE and DELETE are not `CanonicalAspect` values.

Canonical aspects describe what may change **on an existing entity**:

- `PROPERTIES`
- `PLACEMENT`
- `GEOMETRY`
- `SPATIAL`
- `CONNECTIVITY`
- `RELATIONSHIPS`
- `CONSTRAINTS`
- `CLASSIFICATION`
- `IDENTITY`

CREATE/DELETE instead change entity existence. Step36 therefore introduces an explicit canonical existence-effect vocabulary:

```text
CanonicalExistenceEffect.CREATE
CanonicalExistenceEffect.DELETE
```

Only CREATE is enabled by Step36. DELETE remains reserved and deny-by-default.

### Canonical creation envelope

A bare `CREATE` flag is not sufficient authority. Otherwise a caller could request a `CreationRule` that silently expands created kind, count, or derivation.

A canonical operation that permits CREATE must therefore carry an immutable creation envelope:

```text
CanonicalCreationContract
  entity_kinds
  max_count
  required_derivation
```

For Step36 `offset.v1`, the frozen envelope is:

```text
existence_effects = [CREATE]
creation_contract.entity_kinds = [ifc:IfcWall]
creation_contract.max_count = 1
creation_contract.required_derivation = RULE-OFFSET-WALL
```

Step28 may only admit a requested `CreationRule` that is equal to or narrower than this canonical envelope. A request cannot enlarge canonical authority.

## Backward Compatibility Rule

Step36 must not change semantic hashes for existing operations such as `move.v1` and `set_wall_thickness.v1` when their existence-effect fields are empty.

This applies to:

- Step23 canonical contract fingerprints;
- Step27 impact-analysis fingerprints;
- Step28 scope body hashes;
- Step29 canonical contract fingerprints and operation semantic hashes;
- Step30 execution slice / plan hashes where existing rule authority is unchanged.

New existence-effect fields MUST use backward-compatible semantic serialization:

- empty/default existence effects do not add new semantic hash material to legacy payloads;
- non-empty existence effects and creation contracts are included in hash material for Step36 operations;
- existing `ExistingEntityRule` fingerprint payloads remain byte-for-byte unchanged;
- creation/deletion rule fingerprints use typed semantic payloads so they cannot collide with an existing-entity rule that happens to contain similar fields.

Construction IDs remain excluded from semantic hashes according to the existing Step28/29 conventions.

## Canonical Operation Contract

Step36 adds one platform-owned operation:

```text
canonical_operation = offset.v1
version = 1.0.0
category = MODEL_OPERATION
```

### Source target

The canonical target is the **existing source semantic entity**, not the newly created entity.

For the Step36 MVP, exactly one source target is permitted:

```json
{
  "targets": ["WALL-001"]
}
```

The source is canonically eligible as `ifc:IfcWall`.

ProviderBinding may further require an AutoCAD-native `LWPOLYLINE`, but `LWPOLYLINE` never enters D4 canonical eligibility.

### Offset intent

The canonical arguments are:

```json
{
  "targets": ["WALL-001"],
  "distance": {
    "value": 300.0,
    "unit": "mm"
  },
  "side_point": {
    "x": 5000.0,
    "y": 2000.0,
    "z": 0.0,
    "unit": "mm"
  }
}
```

Ownership:

- `targets` = `CONTEXT`
- `distance` = `INTENT`
- `side_point` = `INTENT`

`distance` must be finite and strictly positive.

`side_point` expresses **which side of the source geometry** the user intends. Canonical semantics do not encode AutoCAD curve orientation or a signed native offset distance. The AutoCAD provider determines which native `GetOffsetCurves(+d)` / `GetOffsetCurves(-d)` result corresponds to the canonical side point.

This keeps orientation-specific geometry logic inside the provider/Host boundary.

### Existing-entity aspects

`offset.v1` does not authorize mutation of the source entity in Step36:

```text
effects = []
```

The operation is valid because it has a non-empty existence effect:

```text
existence_effects = [CREATE]
```

Canonical operation validation must require at least one of:

- non-empty existing-entity `effects`, or
- non-empty `existence_effects`.

### Verification contract

Step36 does not introduce a new CREATE-specific semantic assertion language. `offset.v1` therefore has no Step33 semantic verification contract in this step.

The successful one-create path must prove `ScopeComparator == WITHIN_SCOPE` and produce reconciliation-ready evidence. It is not required to reach final Step33 `SUCCEEDED` solely from a new CREATE-specific semantic verifier.

The breach path must terminate through existing Step33 scope-breach handling before semantic verification.

## Step27 Intent Boundary

`IntentBoundary` gains:

```text
allowed_existence_effects: tuple[CanonicalExistenceEffect, ...] = ()
```

For the Step36 action:

```text
direct_targets = [WALL-001]
allowed_canonical_effects = []
allowed_existence_effects = [CREATE]
allowed_derived_rule_refs = []
```

This field is part of Step27 authorization semantics.

Backward-compatibility hashing rule: an empty `allowed_existence_effects` value does not alter historical Step27 analysis fingerprints; a non-empty value is committed into the Step36 analysis fingerprint.

Step27 does not invent creation rules. It only carries the user/agent intent boundary forward so Step28 can prove the requested creation authority is within both canonical and intent limits.

## Step28 Approval Scope

### Canonical effect evidence

`CanonicalEffectEvidence` gains provider-neutral existence authority and the canonical creation envelope.

For Step36 it represents:

```text
canonical_operation = offset.v1
canonical_operation_version = 1.0.0
allowed_aspects = []
allowed_existence_effects = [CREATE]
creation_contract:
  entity_kinds = [ifc:IfcWall]
  max_count = 1
  required_derivation = RULE-OFFSET-WALL
```

`allowed_aspects` may be empty only when non-empty existence authority is present.

### Creation rule admission

The existing `CreationRule` contract is reused:

```text
CreationRule
  rule_id
  canonical_operation
  source_selector
  entity_kinds
  max_count
  required_derivation
```

No replacement creation-rule model is introduced.

For Step36 the admitted rule is conceptually:

```text
rule_id = CR-<deterministic>
canonical_operation = offset.v1
source_selector = entities:[WALL-001]
entity_kinds = [ifc:IfcWall]
max_count = 1
required_derivation = RULE-OFFSET-WALL
```

The planner admits it only if all of these are true:

1. `CREATE` is present in exact Step23 canonical effect evidence;
2. `CREATE` is present in `IntentBoundary.allowed_existence_effects`;
3. `canonical_operation` exactly matches the analyzed operation;
4. the source selector is explicit and contains only direct source targets from the exact impact analysis;
5. requested `entity_kinds` are a subset of the canonical creation contract kinds;
6. requested `max_count` is present and is less than or equal to canonical `max_count`;
7. requested `required_derivation` exactly matches the canonical required derivation;
8. the rule is referenced by an `ExecutionSliceScopeRule.creation_rule_ids` entry for the correct document;
9. every admitted creation rule is covered by exactly the normal closed-world slice-scope accounting used by Step28.

If any condition fails, planning fails closed. The planner must never silently widen or normalize an over-broad request into an allowed rule.

### Existing Step28 behavior retained

- blocking `ImpactException` still makes the scope non-approvable;
- existing direct/propagated modification scope behavior remains unchanged;
- `ScopeEffectRecipe` remains only for predicted existing-entity effects;
- deletion remains unsupported in Step36;
- approver identity, approval records, grants, and admission remain outside Step28.

## Step29 Immutable ChangeSet

Step29 must become rule-kind aware without changing the public meaning of `CanonicalChangeOperation.scope_rule_ids`.

`scope_rule_ids` remains a generic list of Step28 mutation-authority rule IDs. It may refer to:

- `ExistingEntityRule` for existing-entity mutations;
- `CreationRule` for CREATE operations;
- later `DeletionRule` for DELETE operations.

### Rule fingerprinting

`compute_scope_rule_fingerprint()` becomes type-aware.

Compatibility requirement:

- `ExistingEntityRule` produces exactly its pre-Step36 fingerprint payload;
- `CreationRule` fingerprint commits `canonical_operation`, source selector semantics, created kinds, max count, and required derivation;
- `DeletionRule` may be supported for fingerprint completeness but is not admitted by Step36.

### Root operation coverage

For `offset.v1`, Step29 must resolve creation authority from the exact Step28 definition rather than demanding an existing-entity rule for the source.

The selected rule must prove:

```text
operation = offset.v1
source target = WALL-001
created kind allowed = ifc:IfcWall
max_count = 1
required derivation = RULE-OFFSET-WALL
```

The source target remains `operation.targets` because ProviderBinding must bind the existing source entity.

Step29 does not pre-assign the semantic identity of the created entity.

For the Step36 MVP, one root `offset.v1` operation must resolve to **exactly one** admissible `CreationRule`. If zero rules match, authority is missing. If more than one distinct creation-rule semantic body could authorize the same operation, Step29 must fail closed rather than choose one by ordering or construction ID.

### Contract fingerprint

`CanonicalOperationContractEvidence` must carry the new existence semantics. Its semantic fingerprint includes non-empty existence effects / creation contract for Step36 while leaving legacy operation fingerprints unchanged when the new fields are empty.

### Validation tasks

Step36 does not create a new canonical semantic validation task for `offset.v1`. Existing Step29 validation-task behavior for prior operations is unchanged.

## Step30 Execution Planning

Step30 must treat slice authority as the union of all rule kinds:

```text
existing_rule_ids
creation_rule_ids
deletion_rule_ids
```

### Scope binding

`_validate_scope_binding()` must resolve `scope_rule_ids` against the closed union of Step28 rule indexes, not only `existing_entity_rules`.

Duplicate rule IDs across rule kinds are invalid because a generic `scope_rule_ids` reference must resolve to exactly one semantic authority rule.

### Slice selection

For one operation, required authority is the operation's exact `scope_rule_ids` set.

A candidate `ExecutionSliceScopeRule` covers the operation when the required rules are a subset of the union:

```text
existing_rule_ids U creation_rule_ids U deletion_rule_ids
```

Least-authority tie-breaking remains unchanged.

For Step36, Step30 does not generate or relocate a `CreationRule`. It must select an existing Step28 `ExecutionSliceScopeRule` for the source document whose `creation_rule_ids` contains the exact creation rule already committed by Step29. The resulting `ExecutionSlice.approved_scope_ref` binds to that slice-scope rule.

### Runtime routing

Runtime routing remains source-target based:

```text
WALL-001 -> AutoCAD host instance / document
```

No runtime route is required for the not-yet-created entity.

## Step31 ProviderBinding

ProviderBinding continues to bind only existing source targets.

For AutoCAD `offset.v1`, native evidence may require:

```text
native type = LWPOLYLINE / Polyline
source Handle = <native id>
```

Native target constraints remain ProviderBinding/provider owned.

No created Handle exists at binding time and none is fabricated in Step31.

## Step32 Gateway Admission

Step32 receives the exact Step30 slice and Step31 binding set and remains unchanged in responsibility:

- validate exact lineage;
- atomically consume approval admission;
- produce admitted execution authority;
- do not reinterpret `CreationRule` semantics;
- do not create Host-native commands itself.

The admitted slice hash commits the Step36 creation authority through the Step28/29/30 hash chain.

## AutoCAD Provider Surface

The AutoCAD provider adds an OFFSET capability bound to `offset.v1`.

Provider-native eligibility may constrain the source entity to AutoCAD `LWPOLYLINE` / compatible `Polyline`.

Frozen Host wire semantics are provider/Host-local. The command must carry:

- bound source native reference(s);
- positive offset distance in explicit millimetres;
- side point in explicit millimetres;
- existing revision precondition;
- idempotency key.

The Host wire does not carry Step28 scope rules, Step32 grant objects, or semantic classification terms.

## AutoCAD Native OFFSET Behavior

Step36 supports only AutoCAD documents explicitly configured in millimetres, matching the Step34 unit-safety rule.

The native operation must:

1. require exactly one bound source Handle;
2. require active document units = millimetres;
3. resolve the source inside one AutoCAD transaction;
4. require source type compatible with the frozen Polyline/LWPOLYLINE convention;
5. require positive finite distance and finite side-point coordinates;
6. compute candidate native offsets without mutating/committing the source;
7. deterministically select the candidate corresponding to the requested canonical side point;
8. require the selected native result set to contain exactly one supported created entity for the Step36 happy path;
9. append exactly that new entity to the source entity's owning model space/block table record as appropriate for the supported fixture;
10. preserve the enterprise wall classification convention required for semantic reconstruction, including the source wall layer convention for the Step36 fixture;
11. perform Host-local read-back/postcondition checks before commit;
12. commit once;
13. advance document revision only after successful commit;
14. return the actual newly created native entity reference after commit.

Any ambiguity, zero result, unsupported result type, extra result, unit mismatch, invalid source, or postcondition failure must fail closed before revision advance.

Step36 does not implement a generic AutoCAD OFFSET engine for arbitrary entity kinds.

## Provider-Neutral ActualDelta

The orchestration/integration boundary constructs `ActualDelta`; the Host command result itself is not an `ActualDelta`.

A successful Step36 creation produces one provider-neutral change:

```text
ActualChange.change_kind = CREATE
ActualChange.canonical_operation = offset.v1
ActualChange.canonical_kind = ifc:IfcWall
ActualChange.source_semantic_id = WALL-001
ActualChange.source_canonical_kind = ifc:IfcWall
ActualChange.derivation_rule = RULE-OFFSET-WALL
ActualChange.host_entity_ref = <actual newly created Host entity ref>
```

A new semantic ID is optional at this stage under the existing Step33 contract. `host_entity_ref` provides the stable instance discriminator required by current creation allocation logic.

The provider-neutral comparison semantics must not depend on:

- `LWPOLYLINE` as a canonical kind;
- `ConstantWidth`;
- AutoCAD signed offset distance;
- AutoCAD curve orientation;
- raw Handle values except inside the existing `HostEntityRef` provenance/instance discriminator.

## Step33 ScopeComparator

The existing creation comparator is the frozen authority checker for Step36.

For each CREATE it already checks, in order:

1. canonical operation;
2. created canonical kind;
3. source selector;
4. required derivation;
5. deterministic allocation against rule `max_count`.

Step36 should not replace this algorithm.

### Happy path

Given one actual creation:

```text
operation = offset.v1
kind = ifc:IfcWall
source = WALL-001
derivation = RULE-OFFSET-WALL
```

and one admitted `CreationRule(max_count=1)`, expected result:

```text
ScopeComparisonStatus.WITHIN_SCOPE
```

### Breach path

Given two distinct actual created Host entities that both individually match the same admitted creation rule with `max_count=1`, expected result:

```text
ScopeComparisonStatus.SCOPE_BREACH
violation = CREATION_COUNT_EXCEEDED
```

The comparison must be deterministic regardless of input order.

The Step33 Saga/service must record the scope breach and must not continue into semantic success for that slice.

## Live AutoCAD Proof

Step36 should reuse the dynamic named-pipe live harness introduced in Step34.

A real AutoCAD live fixture should contain one selected source wall convention entity:

```text
Entity = LWPOLYLINE / Polyline
Layer = A-WALL
INSUNITS = millimetres
```

The live happy-path proof must show:

- exact source selected and bound;
- one real AutoCAD entity created by `offset.v1`;
- document revision advances exactly once;
- returned new native ref resolves after commit;
- source entity remains present and is not modified outside the operation's intended non-mutating source semantics;
- normalized/provider evidence can classify the new entity as the intended canonical wall kind;
- provider-neutral `ActualDelta.CREATE` compares `WITHIN_SCOPE`.

A live or deterministic Host-level fault-injection proof must also demonstrate that if the Host reports/produces two actual created entities for one admitted `max_count=1` rule, the provider-neutral Step33 comparison returns `CREATION_COUNT_EXCEEDED / SCOPE_BREACH`.

The second proof may use controlled integration evidence rather than deliberately corrupting a user drawing with an unsafe Host implementation. The production Host must itself remain fail-closed and produce exactly one result for the supported MVP command.

## Negative Proofs

Step36 must include at least the following:

### No canonical CREATE authority

Caller requests a `CreationRule` for an operation whose exact Step23 contract does not include CREATE.

Expected: Step28 rejects before scope construction.

### Intent does not allow CREATE

Step23 permits CREATE but the carried `IntentBoundary` does not.

Expected: Step28 rejects.

### Created kind widened

Requested rule permits a kind outside the canonical creation envelope.

Expected: Step28 rejects.

### Count widened

Canonical `max_count=1`; requested rule asks for `max_count>1` or omits a finite bound.

Expected: Step28 rejects.

### Derivation mismatch

Requested or actual derivation differs from `RULE-OFFSET-WALL`.

Expected: Step28 rejects over-broad requested authority, or Step33 reports `CREATION_DERIVATION_MISMATCH` for actual evidence.

### Source mismatch

Actual creation claims a source not admitted by the rule's explicit source selector.

Expected: `CREATION_SOURCE_FORBIDDEN / SCOPE_BREACH`.

### Kind mismatch

Actual created canonical kind is not admitted.

Expected: `CREATION_KIND_FORBIDDEN / SCOPE_BREACH`.

### Count exceeded

Two actual created entities match a rule whose `max_count=1`.

Expected: `CREATION_COUNT_EXCEEDED / SCOPE_BREACH`.

### Creation rule missing from slice

The boundary contains a rule but the exact execution slice scope does not reference it.

Expected: Step30 fails closed or Step33 cannot authorize the creation.

### Unsupported document units

AutoCAD document units are not explicitly millimetres.

Expected: deterministic pre-commit Host rejection; no entity creation and no revision advance.

### Stale revision

Expected Host revision differs before mutation.

Expected: existing revision guard rejects before creation.

## Hash and Integrity Guards

Step36 must add tests proving:

1. legacy `move.v1` and `set_wall_thickness.v1` canonical fingerprints remain unchanged;
2. existing Step27 fingerprints remain unchanged when `allowed_existence_effects=()`;
3. existing Step28 scope hashes remain unchanged when no existence authority is present;
4. `ExistingEntityRule` fingerprints remain unchanged;
5. changing Step36 creation kind/count/derivation changes the relevant semantic hash;
6. changing a slice from one creation rule to another changes slice/scope semantics;
7. duplicate rule IDs across existing/creation/deletion rule kinds are rejected;
8. tampered creation authority fails integrity validation at the existing Step28/29/30 boundaries.

## Files / Subsystems Expected to Change

Step36 may change only what is necessary in:

- platform canonical operation contracts/catalog for existence effects and `offset.v1`;
- Step27 `IntentBoundary` and compatible hashing;
- Step28 canonical effect evidence, planner, hashing/integrity for creation admission;
- Step29 contract evidence, scope rule fingerprinting, builder/integrity for creation authority;
- Step30 scope binding and slice selection for generic rule-kind authority;
- AutoCAD capability/profile and post-binding input translation for `offset.v1`;
- AutoCAD Host narrow OFFSET handler/native wrapper/verifier/registration;
- sidecar command dispatch for OFFSET;
- integration/live tests for one CREATE and count breach;
- Step36 focused CI and design/implementation documentation.

Step31/32 production changes are allowed only if required to preserve exact lineage for the new Step30 slice; their responsibility boundaries must not expand.

## Explicit Non-Goals

Step36 MUST NOT:

- implement Revit execution;
- implement DELETE authority;
- convert CREATE into `CanonicalAspect`;
- let Step28 invent creation authority absent from Step23/27;
- introduce AutoCAD-native type names into D4 canonical eligibility;
- introduce a new global semantic identity protocol for created entities;
- build a generic COPY/SPLIT/OFFSET geometry subsystem;
- redesign Step33 creation allocation;
- add CREATE-specific semantic verifier operators unless separately designed later;
- change Step32 admission ownership;
- introduce 2PC or cross-host transaction semantics;
- implement Step37 cross-host Saga failure injection.

## Acceptance Criteria

Step36 is complete only when all of the following are proven:

1. `offset.v1` has explicit platform-owned CREATE authority with a closed canonical creation envelope.
2. Legacy operations with no existence effects retain their frozen semantic hashes.
3. Step27 carries explicit CREATE intent without widening existing intent semantics.
4. Step28 admits exactly one narrow `CreationRule` for the approved source/kind/count/derivation and rejects broader requests.
5. Step29 commits the creation rule into the immutable ChangeSet without requiring fake existing-entity mutation authority, and ambiguous multiple matching rules fail closed.
6. Step30 selects the least-authority Step28 slice-scope rule that already contains the exact creation rule in `creation_rule_ids`.
7. Step31 binds only the existing source entity; no pre-created native identity is fabricated.
8. Step32 admission remains exact and unchanged in responsibility.
9. A real AutoCAD `offset.v1` happy path creates exactly one supported entity and advances revision only after commit.
10. The resulting provider-neutral `ActualDelta.CREATE` contains the exact canonical operation, canonical created kind, source semantic ID, derivation ref, and actual created Host entity ref needed by Step33.
11. One matching actual creation compares `WITHIN_SCOPE`.
12. Two matching actual creations against `max_count=1` compare `SCOPE_BREACH` with `CREATION_COUNT_EXCEEDED` deterministically.
13. Wrong source, kind, derivation, missing slice authority, stale revision, and unsupported units cannot produce false success.
14. Existing Step28-34 regression suites remain green.

This acceptance proof is Step36.
