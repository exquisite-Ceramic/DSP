# Phase H Revit Wall Thickness Gap Closure Design

**Status:** FROZEN DESIGN — approach A approved; written-spec review pending  
**Date:** 2026-09-01  
**Base:** `main@6a611d369ad3b1b189c977f3676f6af38c8a170f`  
**Branch:** `feat/phase-h-revit-wall-thickness-gap-closure`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Close the Phase H Revit gap by proving that the existing DSP canonical / approval / execution / reconciliation core can drive one real Revit wall-thickness mutation without adding Revit-specific semantics to platform core.

This is an architectural parity proof, not a generic Revit authoring feature.

The success claim is:

> AutoCAD and Revit, despite different native object models and execution/threading constraints, execute the same canonical `set_wall_thickness.v1` through the same Step27-37 governance and reconciliation semantics, while Host-specific knowledge remains behind Host/provider adapters.

## 2. Decision

Adopt **Exclusive Isolated WallType MVP**.

The first Revit implementation supports exactly one approved target wall per execution. The target must be a Basic Wall whose `WallType` is used by exactly that wall and whose native dependency/isolation checks show no supported cross-entity associativity that could be changed by the thickness mutation.

The MVP therefore requires all of the following before mutation:

```text
approved target count = 1
WallKind = Basic
WallType user set = exactly the approved wall
CompoundStructure exists
CompoundStructure is not vertically compound
exactly one editable non-membrane thickness layer
no hosted inserts/openings in the supported isolation probe
no joined wall at either location-curve end in the supported isolation probe
```

Any failed isolation condition is a **before-commit rejection**. The provider does not duplicate WallTypes, widen the approval scope, or hide wider native effects.

## 3. Why this gap closure exists

The repository already proves the governed path with AutoCAD through canonical operation resolution, deterministic impact, approval scope, immutable ChangeSet, execution partitioning, provider binding, gateway authorization, reconciliation, CREATE scope enforcement, and cross-host Saga coordination.

However, `main` still contains only `hosts/autocad` as a real Host family. The original Phase H ordering expected a Revit wall-thickness proof as well.

This gap closure therefore tests the architectural claim that Host expansion should remain close to O(N): adding Revit must add a Host/provider integration, not a Revit branch in Core.

## 4. Frozen reuse boundary

The following production semantics are read-only for this phase unless implementation proves a public-interface defect and this design is reopened:

- D4 operation resolver semantics;
- `set_wall_thickness.v1` canonical operation definition;
- Step27 deterministic impact semantics;
- Step28 approval-scope semantics;
- Step29 immutable ChangeSet semantics;
- Step30 `HostRuntimeRef`, `ExecutionSlice`, and routing semantics;
- Step31 provider-binding contracts and resolver semantics;
- Step32 admission / grant semantics;
- Step33 `ActualDelta`, scope comparison, semantic verification, Saga states, and compensation semantics;
- Step37 `ExecutionSagaCoordinator` semantics;
- shared `NormalizedDesignFact` wire contract;
- shared HostCommand JSON schema;
- AutoCAD production code.

Revit API types, category names, WallType rules, CompoundStructure mechanics, unit APIs, threading rules, and native dependency probes must remain outside those layers.

If implementation requires platform Core to learn `WallType`, `CompoundStructure`, `OST_Walls`, `ExternalEvent`, Revit internal units, or Revit transaction APIs, implementation stops and design is reopened.

## 5. Canonical operation remains unchanged

The Revit Host executes the existing platform operation:

```text
canonical_operation = set_wall_thickness.v1
canonical target     = ifc:IfcWall
effects              = PROPERTIES
argument              = thickness { value: positive number, unit: mm }
verification          = properties.dsp:WallThickness EQUALS_ARGUMENT thickness
```

There is no `set_revit_wall_thickness`, `set_walltype_width`, or Revit-specific canonical aspect.

This is required for cross-Host semantic parity: Step34 already froze the same action for AutoCAD as `PROPERTIES` only. A Revit provider may not redefine the public meaning of a canonical operation merely because its native implementation uses a different object model.

ProviderBinding translates the canonical operation to a Revit provider tool. D4 never sees `Wall`, `WallType`, `CompoundStructure`, `OST_Walls`, layer indices, Revit internal units, or Revit transaction details.

## 6. Canonical effect versus native representation regeneration

This section resolves the geometry ambiguity explicitly.

Step23 defines `effects` as **canonical semantic effects expected from the user operation**. Step34 then freezes wall thickness as `PROPERTIES` only and proves a property-only `ActualDelta` even though changing AutoCAD `LWPOLYLINE.ConstantWidth` also changes the entity's rendered/native width.

Revit must preserve the same canonical abstraction.

For `set_wall_thickness.v1`:

- changing the approved wall's canonical `dsp:WallThickness` is a `PROPERTIES` change;
- Host-internal BRep/tessellation/solid regeneration that is solely the physical representation of that same approved thickness property is **not independently projected as `CanonicalAspect.GEOMETRY`**;
- changing a native support object such as the exclusive `WallType` is implementation evidence, not a fabricated second canonical design entity;
- this rule does **not** permit the provider to hide another semantic entity or another independently observable canonical aspect that changed through Host associativity.

The master spec requires Host read-back / ActualDelta to include implicit associativity effects and requires `ActualDelta ⊆ ApprovalScopeBoundary`. Step27 likewise models `HOST_NATIVE` propagation as something DSP predicts and later verifies rather than a duplicate platform mutation.

Therefore any of the following remain material actual side effects when observed:

```text
another canonical entity changed
another wall changed
placement/location curve changed
relationships/hosting changed
an independently modeled geometry aspect changed beyond the entailed wall-thickness representation
an unexpected create/delete occurred
```

Such effects may not be dropped merely to keep the Slice in scope.

The MVP avoids needing new approved propagation by using the isolation preconditions in §9 and by post-commit read-back checks in §13.

## 7. Host architecture

Add a new Host family under `hosts/revit` following the existing Host boundary:

```text
DSP platform
    |
    | shared HostCommand / NormalizedDesignFact contracts
    v
hosts/revit/sidecar        Python, Revit-free
    |
    | Named Pipe, HostContract JSON unchanged
    v
hosts/revit/plugin         .NET, in Revit process
    |
    | queue Host request
    v
ExternalEvent.Raise()
    |
    v
IExternalEventHandler.Execute(UIApplication)
    |
    v
Revit API + Transaction
```

### 7.1 Transport scope

The MVP uses **Named Pipe only**.

The existing gRPC proto still names its service `AutoCadHost`; this phase does not rename/generalize it because transport migration is independent of Revit semantic parity. Revit gRPC support requires a separate design review.

The shared HostCommand JSON shape remains unchanged. Mutating Revit commands use the existing idempotency key and revision precondition.

### 7.2 Threading invariant

No background pipe listener, Python sidecar, Task, worker thread, or timer may call the Revit API directly.

The plugin may receive and queue requests outside the Revit API context, but all accesses to `Autodesk.Revit.*` execute from a valid Revit API callback. For asynchronous Host requests the MVP uses `ExternalEvent` and `IExternalEventHandler.Execute(UIApplication)`.

The Host request completes only after the handler produces a deterministic result or failure value.

### 7.3 Native API confinement

Revit API references are confined to the plugin native/API boundary:

```text
hosts/revit/plugin/**/Native/**
```

The plugin project file may contain `RevitAPI.dll` / `RevitAPIUI.dll` references needed to compile that boundary.

Non-native plugin logic depends on plugin-local interfaces/value contracts and must not spread `Autodesk.Revit.*` types into sidecar, platform, semantic providers, shared contracts, or generic tests.

ExternalEvent/bootstrap implementations that necessarily implement Autodesk interfaces belong in the Native boundary.

## 8. Revit native target identity

Persist native binding identity as:

```text
host_type       = revit
native_id       = Element.UniqueId
native_kind     = Wall
```

`ElementId` may be retained as ephemeral diagnostic evidence but is not the durable binding identity.

A ProviderBinding resolves the approved semantic wall to exactly one current Revit `Wall` by `UniqueId` in the execution document. Missing, wrong-kind, or wrong-document resolution fails before mutation.

## 9. Exclusive and isolated target invariant

The entire MVP, not merely the live test, is single-target:

```text
len(approved targets) == 1
```

Let:

```text
A = {approved target Wall.UniqueId}
S = {UniqueId of every Wall in the document whose type id == target.WallType.Id}
```

Mutation is eligible only when:

```text
S == A
```

If `S != A`, return:

```text
code  = SHARED_WALL_TYPE_OUTSIDE_SCOPE
phase = BEFORE_COMMIT
```

The Revit provider also performs a deterministic **native isolation probe** before transaction commit. For the MVP it must prove at minimum:

1. there are no hosted inserts/openings returned by the supported Wall insert probe;
2. neither endpoint of the wall's location curve is currently joined to another wall according to the supported location/join probe;
3. no provider-supported dependency probe reports another design element that this operation is expected to mutate.

If isolation cannot be proven, fail closed before mutation. Stable codes may include:

```text
WALL_INSERTS_OUTSIDE_MVP
WALL_JOIN_OUTSIDE_MVP
WALL_ASSOCIATIVITY_UNPROVEN
```

This isolation is a native execution precondition, not a new canonical semantic rule.

Requirements for every before-commit isolation failure:

- no mutating Revit Transaction is committed;
- no `ActualDelta` is fabricated;
- no duplicate WallType is created;
- no successor Slice is treated as if the Host mutation succeeded.

## 10. Supported WallType shape

The MVP accepts only:

- `WallKind.Basic`;
- non-null `CompoundStructure`;
- `CompoundStructure.IsVerticallyCompound == false`;
- exactly one editable non-membrane layer under the deterministic rule below;
- desired thickness positive and convertible from canonical millimetres to the selected Revit version's internal length units.

The deterministic layer rule is intentionally narrow:

1. enumerate `CompoundStructure.GetLayers()` in native order;
2. exclude membrane layers and layers whose width cannot legally be set;
3. require exactly one remaining editable layer;
4. set that layer so the resulting total wall width equals the canonical requested thickness.

Unsupported cases fail before mutation with stable codes such as:

```text
UNSUPPORTED_WALL_KIND
VERTICALLY_COMPOUND_WALL_UNSUPPORTED
AMBIGUOUS_WALL_THICKNESS_LAYER
```

Multi-layer redistribution policy is outside this gap closure.

## 11. Mutation algorithm

For the one admitted wall:

```text
resolve Wall by UniqueId
    -> verify document/runtime identity
    -> verify target count == 1
    -> verify current revision
    -> verify WallKind.Basic
    -> obtain WallType + CompoundStructure
    -> verify Exclusive WallType invariant
    -> verify native isolation invariant
    -> verify supported layer shape
    -> capture native pre-state evidence
    -> convert canonical mm to Revit internal length units
    -> construct modified CompoundStructure
    -> begin Revit Transaction
    -> WallType.SetCompoundStructure(modified)
    -> commit Transaction
    -> capture DocumentChanged/native transaction evidence
    -> read WallType.GetCompoundStructure().GetWidth()
    -> read target Wall identity/location/relationship invariants
    -> convert read-back width to mm
    -> emit Host result evidence
```

The read-back is mandatory. A successful API call without post-commit read-back is insufficient evidence for Host success.

## 12. Document revision barrier

Each live Revit Host instance maintains a session-scoped monotonic integer revision per document.

The plugin subscribes to `ControlledApplication.DocumentChanged`. The revision owner is this document-change observer; command execution must not independently increment a second counter for its own transaction.

The existing HostCommand revision precondition remains authoritative:

```text
expected_revision == current_host_revision
```

A stale revision fails before mutation. A plugin restart creates a new `host_instance_id`; a revision from an old Host runtime cannot silently authorize a new runtime.

The successful command returns the revision that contains the committed side effects.

## 13. Native post-commit evidence and actual side effects

The Revit plugin must retain transaction/read-back evidence sufficient for the execution integration layer to distinguish:

```text
expected support-object mutation
expected target wall property outcome
unexpected external native change evidence
```

At minimum, the provider records:

- Wall UniqueId;
- WallType UniqueId;
- layer index;
- total width before/after;
- target location/identity invariant evidence before/after;
- document revision before/after;
- Revit document-change evidence associated with the transaction where deterministically attributable.

Native support-object writes such as the exclusive WallType do not become a second canonical `ActualChange` merely because Revit stores the property there.

However, the integration boundary may produce `HostCommitted` only after it can construct a truthful provider-neutral `ActualDelta` for the canonical effects that actually occurred. It must not knowingly discard a mapped canonical side effect outside the approved wall/property scope.

If post-commit evidence shows a wider semantic effect and that effect can be normalized, it must enter `ActualDelta` and Step33 decides `SCOPE_BREACH`.

If a real commit is known to have occurred but the integration layer cannot establish enough identity/evidence to truthfully normalize the observed wider effect, it must **not fabricate a clean `ActualDelta`** and must not label the event `FAILED_BEFORE_COMMIT`. Such a case is outside the success path and is a design-review stop if current Step37 contracts cannot represent it without semantic loss.

The controlled MVP fixture and isolation checks are specifically intended to prevent this unresolved post-commit condition from being part of the positive acceptance path.

## 14. Idempotency

For the same idempotency key and identical effective command fingerprint:

- first successful execution performs one Revit mutation;
- replay returns the stored successful result;
- replay performs no second Revit transaction;
- revision does not advance because of replay itself.

Reuse with a conflicting command fingerprint fails closed rather than executing a different mutation under the same key.

## 15. ProviderBinding

Step31 remains generic. A Revit binding uses existing fields, conceptually:

```text
provider_server = revit-local
provider_tool   = revit.set_wall_thickness
host_type       = revit
native_id       = <Wall.UniqueId>
native_kind     = Wall
```

Provider-native constraints may require `native_kind == Wall` using existing Step31 `NativeConstraint` semantics.

The provider adapter may carry native evidence/arguments such as Wall UniqueId, WallType UniqueId, selected layer index, and native-unit values. Those values do not become canonical operation inputs.

Step31 must not change merely to add Revit vocabulary.

## 16. Revit design facts

The Revit adapter converts native snapshots into the already-frozen `NormalizedDesignFact` contract.

Minimum facts:

### Identity

```text
fact_kind   = IDENTITY
predicate   = native_kind
value       = Wall
native_id   = Wall.UniqueId
native_kind = Wall
```

### Classification

```text
fact_kind     = CLASSIFICATION
predicate     = builtin_category
source_scheme = revit.builtin_category
source_code   = OST_Walls
value         = OST_Walls
```

### Wall thickness

```text
fact_kind     = PROPERTY
predicate     = wall_thickness
source_scheme = revit.property
source_code   = WallType.CompoundStructure.TotalWidth
value         = <number>
unit          = mm
```

The Revit adapter owns Revit-internal-unit -> millimetre conversion. D5 and Semantic Service do not learn Revit unit APIs.

The adapter producer id and deterministic fact-id namespace are Revit-specific; the emitted contract shape remains shared.

## 17. Enterprise semantic mapping

Extend the enterprise mapping catalog rather than D5 or IFC provider code.

Required mappings:

```text
revit.builtin_category / OST_Walls
    -> ifc:IfcWall

revit.property / WallType.CompoundStructure.TotalWidth
    -> dsp:WallThickness
```

The IFC4.3 provider remains authoritative for `ifc:*` vocabulary meaning. The enterprise mapper only projects structured source evidence.

No Markdown parsing, Revit API call, or Host-specific branch enters Semantic Service.

## 18. Post-execution semantic reconstruction

The proof path is:

```text
real Revit Wall
    -> native read-back
    -> Revit NormalizedDesignFact batch
    -> SemanticService projection
    -> enterprise mapping
    -> ifc:IfcWall + dsp:WallThickness
    -> D5 / semantic projection snapshot
    -> Step33 VerificationEvidenceBundle
```

The verification subject must prove:

```text
classification contains ifc:IfcWall
properties.dsp:WallThickness == requested canonical thickness
```

A Host-native success flag alone cannot make Step33 verification pass.

## 19. ActualDelta projection

Under the exclusive/isolation invariants, the expected canonical mutation is:

```text
change_kind     = MODIFY
semantic_id     = <approved wall semantic id>
canonical_kind  = ifc:IfcWall
changed_aspects = (PROPERTIES,)
```

This matches the already-frozen Step34 cross-Host meaning of `set_wall_thickness.v1`.

The Revit WallType mutation is native support-object evidence, not a fabricated second canonical design entity. WallType UniqueId, layer index, native before/after width, and transaction evidence remain provider/Host evidence.

If actual normalized canonical evidence contains another entity or aspect, it must not be deleted to force this expected projection. Step33 scope comparison remains authoritative.

## 20. Failure semantics

### Before commit

Examples:

- target count != 1;
- stale document revision;
- target not found / wrong native kind / wrong document;
- shared WallType outside approved target;
- hosted inserts/openings outside MVP;
- joined wall outside MVP;
- associativity cannot be proven isolated;
- unsupported wall kind;
- vertically compound wall;
- ambiguous editable layer;
- invalid unit conversion;
- invalid idempotency reuse.

These failures produce no `ActualDelta` and use the existing precommit failure path.

### Ambiguous commit

If transport/plugin coordination loses certainty after the transaction may have committed, map to the existing `COMMIT_STATE_UNKNOWN` behavior. It must not be rewritten as a precommit failure and must not be blindly retried.

### Confirmed commit with unnormalizable wider side effect

This is not `BEFORE_COMMIT` and not semantically equivalent to a clean `HostCommitted` result. If encountered, implementation stops and the design is reopened rather than falsifying `ActualDelta` or overloading `COMMIT_STATE_UNKNOWN` to mean something it does not mean.

## 21. Scope and verification remain Step33-owned

After a confirmed, truthfully normalized Host commit:

- any extra canonical aspect/entity outside the approved boundary -> Step33 `SCOPE_BREACH`;
- reconstructed wall thickness differing from the canonical request -> `VERIFY_FAILED`;
- only within-scope ActualDelta + passing semantic verification -> Slice/Saga `SUCCEEDED`.

Revit code cannot override those decisions.

## 22. No inferred rollback

This phase adds no Revit inverse-command logic.

A failed/partially committed execution uses existing Step33 durable evidence and compensation proposal semantics. Any recovery mutation is new canonical recovery intent that re-enters the governed chain.

No coordinator or Host adapter may silently restore the previous WallType width as an ungoverned global rollback.

## 23. File / component boundary

Expected new/changed production areas are limited to Revit Host integration and enterprise mapping:

```text
hosts/revit/plugin/**
hosts/revit/sidecar/**
providers/semantics/enterprise_mapping/**
```

Test/docs/CI areas may include:

```text
tests/revit/**
tests/integration/test_phase_h_revit_*.py
docs/runbooks/revit-*.md
.github/workflows/phase-h-revit-wall-thickness*.yml
```

Shared contracts may receive only build/compatibility/test wiring proven necessary by the existing wire format; changing their semantic shape is not approved.

Platform Step27-37 production directories are expected to remain unchanged.

## 24. Revit version / .NET build baseline

This phase does **not** claim one .NET target works for every current Revit release/update.

The implementation plan must lock one concrete installed Revit version for the real-host acceptance and target the runtime officially required by that exact release.

Known current compatibility facts include:

- Revit 2025 moved add-ins to the .NET 8 family;
- Revit 2026 originally used .NET 8, but Autodesk's current Revit 2026 update documentation reports .NET 10 support/migration for Revit 2026.5.

Therefore the build must not encode the stale rule `Revit 2025+ == net8.0-windows`.

Multi-version plugin packaging is a non-goal. If the acceptance machine's installed Revit version is not known when the implementation plan is written, the plan must make the exact live-build target an explicit external acceptance prerequisite rather than guessing it.

## 25. Test strategy

### 25.1 Pure / offline

Prove without live Revit:

- Revit native snapshot -> deterministic `NormalizedDesignFact` values;
- enterprise mappings -> `ifc:IfcWall` and `dsp:WallThickness`;
- ProviderBinding accepts exact Revit Wall target and rejects wrong native kind;
- target-count guard rejects more than one target;
- supported WallType-shape evaluator is deterministic;
- shared-type mismatch produces `SHARED_WALL_TYPE_OUTSIDE_SCOPE` before mutation;
- insert/join/isolation failures are precommit;
- canonical mm / Revit internal-unit conversion behavior is deterministic for the pinned API version;
- idempotency replay returns prior success without re-execution;
- architecture guard prevents Revit API leakage outside plugin Native boundary;
- platform Step27-37 production source remains unchanged.

### 25.2 Plugin-local tests

Keep Revit mechanics behind narrow plugin-local interfaces so deterministic tests can prove:

- request queue -> ExternalEvent handler dispatch;
- no mutation on failed preflight;
- exactly one transaction attempt on success;
- no second transaction on idempotent replay;
- read-back controls success evidence;
- native transaction evidence is captured;
- ambiguous post-commit completion is not downgraded to precommit failure.

### 25.3 Real Revit acceptance

Use a controlled RVT fixture containing exactly one Basic wall with:

- an exclusive supported WallType;
- no hosted insert/opening;
- no wall join at either end under the chosen isolation probe;
- no other known provider-supported association expected to mutate.

Required positive proof:

```text
canonical request = 300 mm
real Wall pre-read != 300 mm
one Revit mutation commits
real post-read = 300 mm
reconstructed dsp:WallThickness = 300 mm
ActualDelta = target MODIFY / PROPERTIES only
ScopeComparator = WITHIN_SCOPE
SemanticVerifier = PASSED
Saga = SUCCEEDED
```

Required negative proofs:

1. **Shared WallType** — second unapproved wall uses same type -> precommit `SHARED_WALL_TYPE_OUTSIDE_SCOPE`, no mutation.
2. **Hosted insert / join isolation** — supported associativity probe detects dependency -> precommit reject, no mutation.
3. **Stale revision** — mismatch -> no transaction commit.
4. **Idempotency replay** — same key -> same successful result, no second mutation or replay-caused revision increment.
5. **Wrong reconstructed width** — real/fixture Host commit can exist, semantic evidence reports different width -> `VERIFY_FAILED`, Saga not `SUCCEEDED`.
6. **Extra canonical aspect** — deliberately constructed truthful reconciliation evidence contains another aspect -> `SCOPE_BREACH`, Saga not `SUCCEEDED`.

## 26. Completion gates

The gap closure is complete only when all are evidenced:

```text
real Revit Host exists under hosts/revit                                PASS
same set_wall_thickness.v1 canonical contract reused                    PASS
canonical effect remains PROPERTIES consistently across AutoCAD/Revit   PASS
Step27-30 production semantics unchanged                                PASS
Step31 contract/resolver production semantics unchanged                 PASS
Step32 production semantics unchanged                                   PASS
Step33 production semantics unchanged                                   PASS
Step37 production semantics unchanged                                   PASS
Revit API absent from platform/sidecar/semantic core                    PASS
Revit API confined to plugin Native boundary                            PASS
Revit command enters API context through ExternalEvent                  PASS
Wall identity persists by UniqueId                                      PASS
MVP rejects target count != 1                                           PASS
shared WallType outside approval fails before mutation                  PASS
insert/join/isolation failure occurs before mutation                    PASS
no hidden WallType duplication/CREATE                                   PASS
real 300 mm wall mutation commits once                                  PASS
real post-commit read-back equals 300 mm                                PASS
native transaction/read-back evidence retained                          PASS
Revit facts project to ifc:IfcWall + dsp:WallThickness                  PASS
truthful ActualDelta reports approved wall/property outcome              PASS
ScopeComparator = WITHIN_SCOPE                                          PASS
SemanticVerifier = PASSED                                               PASS
Saga = SUCCEEDED                                                        PASS
stale revision is precommit/no mutation                                 PASS
idempotency replay has no second mutation                               PASS
wrong semantic reconstruction -> VERIFY_FAILED                          PASS
extra canonical aspect -> SCOPE_BREACH                                  PASS
existing AutoCAD / Step27-37 regressions remain green                   PASS
```

## 27. Explicit non-goals

This gap closure does not implement:

- multiple target walls in one Revit thickness execution;
- automatic duplication of shared WallTypes;
- automatic reassignment to a duplicated type;
- canonical CREATE authority for Revit type objects;
- approval expansion to all walls sharing a type;
- general multi-layer wall redistribution;
- vertically compound walls;
- stacked walls or curtain walls;
- walls with supported detected inserts/joins/associativity;
- generalized Revit dependency/impact policy;
- Revit gRPC transport;
- automatic rollback/inverse Host commands;
- multi-version Revit packaging;
- Revit-specific branches in platform semantic/execution core.

Each requires a separate design decision if later needed.

## 28. Architecture success criterion

The strongest result is not merely "Revit can set a wall width." It is:

> A real Revit Host can execute the already-frozen canonical wall-thickness meaning through the same governance/reconciliation core as AutoCAD, while Revit-specific type sharing, unit conversion, API threading, identity, and native isolation remain provider/Host concerns.

If that claim cannot be achieved without lying about actual side effects, the implementation must stop and reopen the design rather than weakening scope comparison.

## 29. Repository references

- `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`
- `docs/superpowers/specs/2026-08-29-step23-canonical-action-contract-design.md`
- `docs/superpowers/specs/2026-08-29-step27-impact-layer-design.md`
- `docs/superpowers/specs/2026-08-29-step28-approval-scope-boundary-design.md`
- `docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md`
- `docs/superpowers/specs/2026-08-30-step34-autocad-wall-thickness-design.md`
- `platform/orchestrator/src/design_orchestrator/canonical_operations.py`
- `contracts/python/design_fact_contracts/`
- `contracts/schemas/host-command.schema.json`
- `platform/provider_binding/src/design_provider_binding/`
- `platform/execution_reconciliation/src/design_execution_reconciliation/`
- `platform/execution_coordination/src/design_execution_coordination/`
- `providers/semantics/enterprise_mapping/`

## 30. Autodesk references reviewed

- CompoundStructure / walls, floors, ceilings and roofs: <https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API/files/Revit_API_Developers_Guide/Revit_Geometric_Elements/Walls_Floors_Ceilings_Roofs_and_Openings/Revit_API_Revit_API_Developers_Guide_Revit_Geometric_Elements_Walls_Floors_Ceilings_Roofs_and_Openings_CompoundStructure_html.html>
- `Element.UniqueId`: <https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/f9a9cb77-6913-6d41-ecf5-4398a24e8ff8.htm>
- External Events: <https://help.autodesk.com/cloudhelp/2025/CHS/Revit-API/files/Revit_API_Developers_Guide/Advanced_Topics/Revit_API_Revit_API_Developers_Guide_Advanced_Topics_External_Events_html.html>
- `ControlledApplication.DocumentChanged`: <https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/f7acc5b4-a1b4-12ca-802b-0ee78942589e.htm>
- Revit 2026 updates / runtime changes: <https://help.autodesk.com/view/RVT/2026/ENU/?guid=RevitReleaseNotes_2026updates_html>
