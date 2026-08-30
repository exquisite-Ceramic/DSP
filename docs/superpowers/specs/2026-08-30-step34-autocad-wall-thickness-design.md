# Step34 AutoCAD Wall Thickness Design

## Status

Frozen after design approval on 2026-08-30.

## Context

Phase H originally ordered the first real wall-thickness proof as Revit followed by AutoCAD. The implementation order is intentionally adjusted because Revit is not currently available in the development environment:

- Step34: wall thickness / AutoCAD
- Step35: Revit deferred until a real Revit Host is available
- Step36: OFFSET CREATE / CreationRule / SCOPE_BREACH remains unchanged
- Step37: cross-host Saga failure injection remains unchanged

This is a Host-order adjustment only. It does not change the Phase H architectural acceptance criteria.

## Goal

Prove the complete approved DSP execution chain against a real AutoCAD Host by changing one semantic wall's canonical thickness from 200 mm to 300 mm and reaching Step33 `SUCCEEDED` only after scope reconciliation and independent semantic verification.

The proof must exercise:

`Canonical Action -> ChangeSet -> ApprovalScopeBoundary -> ExecutionSlice -> ProviderBinding -> ExecutionGrant -> AutoCAD Host mutation -> provider-neutral ActualDelta -> ScopeComparator -> D5 reconstruction -> SemanticVerifier -> Step33 lifecycle`

Host success alone is insufficient.

## Frozen AutoCAD MVP Representation

The Step34 enterprise/Host convention is:

- AutoCAD entity kind: `LWPOLYLINE`
- AutoCAD layer: `A-WALL`
- wall thickness native source: `Polyline.ConstantWidth`
- fixture document length unit: millimetres

Example pre-state:

```text
Layer = A-WALL
Entity = LWPOLYLINE
ConstantWidth = 200
Document length unit = mm
```

The requested canonical post-state is:

```text
dsp:WallThickness = 300 mm
```

### Boundary rule

`LWPOLYLINE`, `ConstantWidth`, AutoCAD Handle values, and AutoCAD document-unit APIs are Host/provider-native concepts. They MUST NOT become DSP Core concepts, D4 semantic eligibility terms, or Step33 reconciliation vocabulary.

Core-facing state remains canonical:

- classification: `ifc:IfcWall`
- property: `dsp:WallThickness`
- changed aspect: `PROPERTIES`
- identity: semantic identity, not AutoCAD Handle

## Existing Capabilities Reused

Step34 reuses existing capabilities rather than redesigning them:

1. Enterprise mapping already maps `A-WALL` / `A-WALL-*` classification evidence to `ifc:IfcWall`.
2. DSP Core already defines `dsp:WallThickness` as a numeric wall-like property with unit `mm`.
3. `NormalizedDesignFact` already supports `FactKind.PROPERTY`, numeric values, units, native source scheme/code, provenance, and deterministic fact IDs.
4. ProviderBinding already owns native target constraints; D4 remains canonical-only.
5. Step32 remains the authority/admission boundary.
6. Step33 already owns `ActualDelta`, `ScopeComparator`, semantic verification, and the execution reconciliation lifecycle.

## Canonical Operation Contract

The current MVP canonical catalog contains `move.v1` but no wall-thickness operation. Step34 therefore adds one platform-owned Host-independent operation definition; this extends the canonical action catalog without changing D4 resolution architecture.

Frozen contract identity:

```text
canonical_operation = set_wall_thickness.v1
version = 1.0.0
category = MODEL_OPERATION
```

Frozen canonical arguments:

```json
{
  "targets": ["<semantic-id>"],
  "thickness": {
    "value": 300.0,
    "unit": "mm"
  }
}
```

Ownership:

- `targets` = CONTEXT-bound semantic identities
- `thickness` = INTENT-bound canonical measurement

Canonical effects are exactly `PROPERTIES`.

Canonical entity eligibility is wall-semantic, expressed with canonical classification evidence such as `ifc:IfcWall`; it must not mention `LWPOLYLINE`, AutoCAD Handle, layer, or `ConstantWidth`.

The verification contract is semantic and argument-bound:

```json
{
  "type": "SEMANTIC_ASSERTIONS_V1",
  "version": "1.0.0",
  "assertions": [
    {
      "subjects": {"from_argument": "targets"},
      "path": "properties.dsp:WallThickness",
      "operator": "EQUALS_ARGUMENT",
      "argument": "thickness"
    }
  ]
}
```

No Host-native verification token is used as the Step33 semantic success condition.

## Native Snapshot Contract Extension

Step34 extends only the AutoCAD Host-local snapshot DTO. It does not alter the frozen Step18 `NormalizedDesignFact` contract.

For a supported millimetre `LWPOLYLINE`, the native snapshot may include:

```json
{
  "nativeId": "A31",
  "nativeKind": "LWPOLYLINE",
  "layer": "A-WALL",
  "properties": {
    "constantWidth": {
      "value": 200.0,
      "unit": "mm"
    }
  }
}
```

`properties` is optional so existing entities and existing Step19 behavior remain valid.

The Host extractor must never label an unknown drawing unit as `mm`. Step34 mutation support is deliberately limited to AutoCAD documents whose length unit is explicitly millimetres. A mutation request against another/unknown unit must be rejected before commit with a deterministic Host error; no implicit conversion is introduced in Step34.

## Normalized Property Fact

The AutoCAD sidecar converts the native `ConstantWidth` observation into an existing `NormalizedDesignFact`:

```text
fact_kind      = PROPERTY
predicate      = constant_width
value          = 200.0
value_type     = NUMBER
unit           = mm
source_scheme  = autocad.property
source_code    = LWPOLYLINE.ConstantWidth
```

The fact remains provider-neutral at the contract level while preserving source evidence required by the enterprise mapping provider.

The deterministic fact ID continues to use the existing tuple:

`document_id + source_revision + native_id + fact_kind + predicate`

No Step18 schema change is permitted for Step34.

## Enterprise Semantic Projection

The Enterprise Mapping provider is extended so its existing mapping rule mechanism can project both classification and property facts.

A Step34 property mapping rule is added conceptually as:

```yaml
mapping_id: autocad-lwpolyline-constant-width-wall-thickness
source_scheme: autocad.property
match_type: EXACT
pattern: LWPOLYLINE.ConstantWidth
case_sensitive: true
target_term_id: dsp:WallThickness
assurance: RULE_DERIVED
```

Projection semantics are fact-kind specific:

- `CLASSIFICATION` -> claim predicate `classification`, value `None`, unit `None`
- `PROPERTY` -> claim predicate `property`, value copied from the fact, unit copied from the fact

Only supported fact kinds are projected. Existing classification behavior and conflict detection remain unchanged.

For the Step34 fixture this yields:

```text
A-WALL -> ifc:IfcWall
LWPOLYLINE.ConstantWidth = 200 mm -> dsp:WallThickness = 200 mm
```

## AutoCAD Provider Capability and Binding

The AutoCAD provider surface adds a wall-thickness capability bound to `set_wall_thickness.v1`.

Provider-native eligibility remains in ProviderBinding/capability metadata. The AutoCAD binding may constrain the native target to `LWPOLYLINE`; D4 must see only canonical wall eligibility.

The provider-side input adapter translates the admitted canonical measurement into the Host command argument required by the AutoCAD plugin. This translation occurs after ProviderBinding/Step32 admission, not inside canonical resolution.

## AutoCAD Mutation Operation

Step34 adds one narrow Host operation for the frozen convention. The sidecar converts a canonical wall-thickness execution intent into a Host command targeting one or more already-bound native `LWPOLYLINE` references.

The Host operation must:

1. validate request arguments and positive finite target width;
2. enforce expected document revision through the existing revision barrier;
3. resolve every requested Handle;
4. require every target to be an AutoCAD `Polyline` / `LWPOLYLINE` compatible with `ConstantWidth`;
5. require the active document length unit to be millimetres;
6. read native width before mutation;
7. set `ConstantWidth` inside the existing Host transaction pattern;
8. read native width after mutation;
9. perform Host-local verification that every target equals the requested width;
10. return `OK` only after Host-local verification succeeds;
11. advance document revision only on successful commit.

The operation must remain idempotent under the existing Host idempotency mechanism.

The canonical action and Step32 authority are not embedded into `HostCommand`. Dispatch to this operation occurs only after the orchestration boundary possesses admitted execution authority.

## ActualDelta Boundary

The AutoCAD result is not itself a Step33 `ActualDelta`.

The integration/orchestration boundary constructs a provider-neutral `ActualDelta` using the approved grant/binding/slice lineage and semantic identity.

For the successful Step34 mutation the only change is:

```text
ActualChange.kind = MODIFY
ActualChange.semantic_id = <wall semantic identity>
ActualChange.changed_aspects = [PROPERTIES]
```

The Step34 approved scope therefore permits only `MODIFY / PROPERTIES` for the target semantic wall.

AutoCAD native concepts such as Handle, `LWPOLYLINE`, and `ConstantWidth` MUST NOT appear in `ActualDelta`.

## Reconciliation and Verification

A successful Host command does not mark the execution slice successful.

After the real Host mutation:

1. read back the entity through the native snapshot path;
2. normalize the post-state fact;
3. reconstruct semantic state through the semantic provider stack / D5 path;
4. construct the Step33 verification evidence for the exact assigned verification task;
5. run `ScopeComparator` against the approved scope;
6. run the independent `SemanticVerifier` against canonical post-state evidence.

Required successful results:

```text
ScopeComparator = WITHIN_SCOPE
properties["dsp:WallThickness"] = { value: 300, unit: "mm" }
SemanticVerifier = PASS
Step33 slice = SUCCEEDED
```

Host-local verification and independent semantic verification are intentionally separate proofs.

## Negative Proofs

Step34 must include at least these negative cases:

### Wrong semantic post-state

Host execution/read-back or reconstructed semantics do not prove 300 mm.

Expected result: `VERIFY_FAILED`; no false `SUCCEEDED`.

### Extra actual scope

ActualDelta contains a change outside the approved `MODIFY / PROPERTIES` scope.

Expected result: `SCOPE_BREACH`; no false `SUCCEEDED`.

### Stale revision

The Host document revision differs from the expected revision before mutation.

Expected result: execution is rejected before mutation/commit; no false success and no revision advance from the rejected command.

### Unsupported document units

The active AutoCAD document is not explicitly millimetres.

Expected result: deterministic Host rejection before mutation/commit. Step34 does not perform implicit unit conversion.

## Live Test Harness Requirement

Current multi-instance AutoCAD plugin instances expose dynamic named pipes of the form:

`EnterpriseDesignAgent.<MachineName>-<AutoCADPID>`

Step34 live tests must use the existing AutoCAD pipe discovery mechanism (or the explicit selected transport) rather than constructing a default `HostAdapter()` that assumes the obsolete fixed `EnterpriseDesignAgent` pipe.

The plugin MUST NOT be changed back to a fixed global pipe name; doing so would regress the multi-instance Host identity design.

## Files/Subsystems Allowed to Change

Step34 may change only what is necessary in these areas:

- platform canonical operation catalog/tests for `set_wall_thickness.v1`
- AutoCAD provider capability/profile and post-binding input translation
- AutoCAD plugin native snapshot extraction
- AutoCAD plugin wall-thickness command/handler/verifier and registration
- AutoCAD sidecar snapshot normalization
- AutoCAD sidecar model/command dispatch surface for wall thickness
- Enterprise Mapping property projection/data rule
- Step34 integration/reconciliation proof tests
- live AutoCAD test harness discovery wiring
- Step34 docs / focused CI

## Explicit Non-Goals

Step34 MUST NOT redesign or add AutoCAD-specific knowledge to:

- D4 semantic eligibility architecture
- DSP Core semantic term model
- Step18 `NormalizedDesignFact` schema
- ProviderBinding native/core separation
- Step28 ApprovalScope model
- Step29 ChangeSet hashing
- Step30 execution planning
- Step32 authorization/admission semantics
- Step33 `ActualDelta` semantics
- Step33 `ScopeComparator`
- Step33 `SemanticVerifier`
- cross-host Saga semantics
- Revit execution
- OFFSET creation semantics

## Acceptance Criteria

Given a real AutoCAD document explicitly configured in millimetres containing a selected `A-WALL` `LWPOLYLINE` with `ConstantWidth = 200`:

When the approved canonical action requests `dsp:WallThickness = 300 mm`:

1. the actual AutoCAD entity ends with `ConstantWidth == 300`;
2. Host-local read-back verification succeeds;
3. document revision advances on the successful commit;
4. provider-neutral `ActualDelta` contains only `MODIFY / PROPERTIES` for the semantic wall;
5. `ScopeComparator == WITHIN_SCOPE`;
6. D5/semantic reconstruction proves `dsp:WallThickness == 300 mm`;
7. independent `SemanticVerifier == PASS`;
8. Step33 reaches `SUCCEEDED` only after the reconciliation and verification gates pass;
9. wrong-value, extra-scope, stale-revision, and unsupported-unit negative cases cannot produce false success.

This acceptance proof is Step34.