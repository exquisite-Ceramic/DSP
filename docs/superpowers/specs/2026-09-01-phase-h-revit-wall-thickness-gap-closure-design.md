# Phase H Revit Wall Thickness Gap Closure Design

**Status:** FROZEN DESIGN — user-approved approach A on 2026-09-01

**Purpose:** Close the Phase H Revit gap by proving that the existing DSP canonical / approval / execution / reconciliation core can drive one real Revit wall-thickness mutation without adding Revit-specific semantics to platform core.

## 1. Decision

Adopt **Exclusive WallType MVP**.

The first real Revit acceptance supports `set_wall_thickness.v1` only when every target wall uses a Basic `WallType` whose effective native side effects are confined to the already-approved canonical target set. The initial live acceptance is intentionally narrower: exactly one selected wall, one WallType used by exactly that wall, a non-vertically-compound structure, and exactly one editable non-membrane layer.

If the target WallType is shared by any wall outside the approved target set, execution fails before opening a mutating Revit transaction with stable failure code:

`SHARED_WALL_TYPE_OUTSIDE_SCOPE`

The coordinator, Step33, and canonical scope are not widened to hide native type-level side effects.

## 2. Why this gap closure exists

The repository now proves the full governed path with AutoCAD, including canonical operation resolution, deterministic impact, closed approval scope, immutable ChangeSet, execution partitioning, provider binding, gateway authorization, reconciliation, CREATE scope enforcement, and cross-host Saga coordination. However, `main` still contains only `hosts/autocad` as a real Host implementation.

This gap closure is therefore an architectural acceptance test: a second Host with materially different native object semantics must fit behind the same platform contracts.

Success means the platform can say, with real evidence, that adding Revit did **not** require a Revit branch in D4, Step27, Step28, Step29, Step30, Step32, Step33, or Step37.

## 3. Frozen reuse boundary

The following production semantics are **read-only for this phase** unless implementation proves an unavoidable public-interface defect and design is reopened:

- D4 operation resolver semantics
- `set_wall_thickness.v1` canonical operation definition
- Step27 deterministic impact semantics
- Step28 approval-scope semantics
- Step29 immutable ChangeSet semantics
- Step30 `HostRuntimeRef`, `ExecutionSlice`, and routing semantics
- Step31 provider-binding contracts and resolver semantics
- Step32 admission / grant semantics
- Step33 `ActualDelta`, scope comparison, semantic verification, Saga states, and compensation semantics
- Step37 `ExecutionSagaCoordinator` semantics
- shared `NormalizedDesignFact` wire contract
- shared HostCommand JSON schema
- AutoCAD production code

Revit-specific API types, category names, WallType rules, CompoundStructure mechanics, and threading rules must remain outside those layers.

## 4. Canonical operation remains unchanged

The Revit Host executes the existing canonical operation:

```text
canonical_operation = set_wall_thickness.v1
canonical target     = ifc:IfcWall
effect               = PROPERTIES
argument             = thickness { value: positive number, unit: mm }
verification          = dsp:WallThickness EQUALS_ARGUMENT thickness
```

There is no `set_revit_wall_thickness`, `set_walltype_width`, or Revit-specific canonical aspect.

ProviderBinding translates the canonical operation to the Revit provider tool. D4 never sees `Wall`, `WallType`, `CompoundStructure`, `OST_Walls`, layer indices, Revit internal units, or Revit transaction details.

## 5. Host architecture

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
hosts/revit/plugin         .NET 8, Revit process
    |
    | queued command
    v
ExternalEvent.Raise()
    |
    v
IExternalEventHandler.Execute(UIApplication)
    |
    v
Revit API + Transaction
```

### 5.1 Transport scope

The MVP uses **Named Pipe only**.

The existing gRPC proto names its service `AutoCadHost`; this phase does not rename or generalize that service because transport migration is independent of Revit semantic parity. Revit gRPC support requires a separate design review.

The shared HostCommand JSON shape remains unchanged. Mutating Revit commands still carry the existing idempotency key and revision precondition.

### 5.2 Threading invariant

No background pipe listener, Python sidecar, Task, worker thread, or timer may call the Revit API directly.

The plugin may receive and queue requests away from the Revit API context, but all reads and writes that touch `Autodesk.Revit.*` must execute from a valid Revit API callback. For asynchronous host requests the MVP uses `ExternalEvent` and `IExternalEventHandler.Execute(UIApplication)`.

The Host request completes only after that handler has produced a deterministic result or failure value.

## 6. Revit native target identity

For persisted native binding identity use:

```text
host_type       = revit
native_id       = Element.UniqueId
native_kind     = Wall
```

`ElementId` may be carried as ephemeral diagnostic evidence but is not the durable binding identity.

Rationale: Autodesk defines `Element.UniqueId` as a stable unique identifier within the document, suitable for external persistence and later retrieval; `ElementId` may change in situations where `UniqueId` remains stable.

A ProviderBinding must resolve the approved semantic wall to exactly one current Revit `Wall` by `UniqueId` in the execution document. Missing, duplicated, wrong-kind, or wrong-document resolution fails before mutation.

## 7. Revit wall-thickness native model

A Revit wall's compound width belongs to its `WallType` / `CompoundStructure`, not to an independently writable instance-width property.

Autodesk documents these native facts:

- compound layers determine total host-object thickness;
- total width cannot be set directly; layer widths must change;
- the modified `CompoundStructure` must be written back to the `HostObjAttributes` / WallType;
- changing that type affects every instance using it;
- a distinct layer combination normally requires duplicating the type.

That type-level sharing is the central safety issue for this phase.

## 8. Exclusive WallType invariant

Before mutation, the Revit provider must derive the set:

```text
S = all Wall instances in the same document whose type id == target.WallType.Id
A = approved target Wall UniqueIds for this ExecutionSlice
```

Mutation is eligible only if:

```text
S == A
```

The first live acceptance further requires:

```text
len(A) == 1
len(S) == 1
```

This is a native precondition, not a new canonical entity rule. It proves that the native support-object mutation cannot affect an unapproved canonical wall.

If `S != A`, return:

```text
code = SHARED_WALL_TYPE_OUTSIDE_SCOPE
phase = BEFORE_COMMIT
```

Requirements:

- no mutating Revit Transaction is committed;
- no `ActualDelta` is fabricated;
- no duplicate WallType is created;
- no successor Slice is admitted as if the Host mutation succeeded.

## 9. Supported WallType shape for the MVP

The MVP accepts only:

- `WallKind.Basic`;
- non-null `CompoundStructure`;
- `CompoundStructure.IsVerticallyCompound == false`;
- exactly one editable non-membrane layer selected by the Revit provider's deterministic rule;
- desired thickness is positive and convertible from canonical millimetres to Revit internal length units.

The deterministic first-version layer rule is intentionally narrow:

1. enumerate `CompoundStructure.GetLayers()` in native order;
2. exclude membrane layers and zero-width/non-width-editable candidates;
3. require exactly one remaining editable layer;
4. set that layer's width so the resulting total wall width equals the canonical requested thickness.

If the shape does not satisfy this rule, fail before mutation with a stable provider/Host failure such as:

- `UNSUPPORTED_WALL_KIND`
- `VERTICALLY_COMPOUND_WALL_UNSUPPORTED`
- `AMBIGUOUS_WALL_THICKNESS_LAYER`

Multi-layer redistribution policy is explicitly outside this gap closure.

## 10. Mutation algorithm

For one admitted execution:

```text
resolve Wall by UniqueId
    -> verify document/runtime identity
    -> verify current revision
    -> verify WallKind.Basic
    -> obtain WallType + CompoundStructure
    -> verify Exclusive WallType invariant
    -> verify supported layer shape
    -> convert canonical mm to Revit internal length units
    -> construct modified CompoundStructure
    -> begin Revit Transaction
    -> WallType.SetCompoundStructure(modified)
    -> commit Transaction
    -> read WallType.GetCompoundStructure().GetWidth()
    -> convert read-back width to mm
    -> emit Host result
```

The read-back is mandatory. A successful `SetCompoundStructure` call without post-commit read-back is insufficient evidence for Host success.

## 11. Document revision barrier

Each live Revit Host instance maintains a session-scoped monotonic integer revision.

The plugin subscribes to `ControlledApplication.DocumentChanged`. Autodesk documents that this event is raised after a Revit transaction is committed, undone, or redone and is intended for keeping external data synchronized with the Revit database.

The Host increments its revision for each relevant document-change event.

The existing HostCommand revision precondition remains authoritative:

```text
expected_revision == current_host_revision
```

A stale revision fails before mutation with the existing revision-conflict pattern. A plugin restart creates a new `host_instance_id`; a revision from an old Host runtime cannot silently authorize mutation in a new runtime.

Implementation must avoid double-counting its own commit. The revision owner is the document-change observer; command execution reads the resulting revision after commit rather than independently incrementing a second counter.

## 12. Idempotency

The Revit Host follows the existing mutating-command idempotency rule.

For the same idempotency key and identical effective command fingerprint:

- the first successful execution performs one Revit mutation;
- replay returns the stored successful result;
- replay performs no second Revit transaction;
- revision does not advance because of the replay itself.

Reuse with a conflicting command fingerprint fails closed rather than executing a different mutation under the same key.

## 13. ProviderBinding

Step31 remains generic. A Revit binding uses the existing fields, for example conceptually:

```text
provider_server = revit-local
provider_tool   = revit.set_wall_thickness
host_type       = revit
native_id       = <Wall.UniqueId>
native_kind     = Wall
```

Provider-native constraints may require `native_kind == Wall` using the existing Step31 `NativeConstraint` contract.

The provider adapter may carry native arguments/evidence such as Wall UniqueId, resolved WallType UniqueId, supported-layer index, and canonical thickness converted for the Host command, but those values do not become canonical operation inputs.

Step31 must not be changed merely to add Revit vocabulary.

## 14. Revit design facts

The Revit adapter converts a native snapshot into the already-frozen `NormalizedDesignFact` contract.

Minimum wall facts for this phase:

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

The Revit adapter owns the conversion from Revit internal units to millimetres. D5 and Semantic Service do not learn Revit unit APIs.

The adapter producer id and deterministic fact-id namespace must be Revit-specific but the emitted contract shape remains shared.

## 15. Enterprise semantic mapping

Extend the enterprise mapping catalog rather than D5 or IFC provider code.

Required deterministic mappings:

```text
revit.builtin_category / OST_Walls
    -> ifc:IfcWall

revit.property / WallType.CompoundStructure.TotalWidth
    -> dsp:WallThickness
```

The IFC4.3 provider remains authoritative for `ifc:*` vocabulary meaning. The enterprise mapper only projects structured source evidence.

No Markdown parsing, Revit API call, or Host-specific branch enters Semantic Service.

## 16. Post-execution semantic reconstruction

The proof path is:

```text
real Revit Wall
    -> Revit native read-back
    -> Revit NormalizedDesignFact batch
    -> SemanticService projection
    -> enterprise mapping
    -> ifc:IfcWall + dsp:WallThickness
    -> D5 / semantic projection snapshot
    -> Step33 VerificationEvidenceBundle
```

The verification subject for the approved wall must expose:

```text
classification contains ifc:IfcWall
properties.dsp:WallThickness == requested canonical thickness
```

A Host-native success flag alone cannot make Step33 verification pass.

## 17. ActualDelta projection

Under the Exclusive WallType invariant, the canonical observable mutation is projected as one `MODIFY` per approved wall:

```text
change_kind     = MODIFY
semantic_id     = <approved wall semantic id>
canonical_kind  = ifc:IfcWall
changed_aspects = (PROPERTIES,)
```

The Revit WallType mutation is native support-object evidence, not a fabricated second canonical design entity.

Provider/Host evidence may retain:

- Wall UniqueId;
- WallType UniqueId;
- layer index;
- width before/after in native and canonical units;
- document revision before/after.

That native evidence must not introduce Revit vocabulary into Step33 canonical scope comparison.

If the Exclusive WallType invariant cannot be proved, execution is forbidden; Step37 must not use this projection to conceal wider native effects.

## 18. Failure semantics

Expected failures are values and are classified before or after commit.

### Before commit

Examples:

- stale document revision;
- target not found;
- wrong native kind;
- shared WallType outside approved target set;
- unsupported wall kind;
- vertically compound wall;
- ambiguous editable layer;
- invalid canonical/native unit conversion;
- invalid idempotency reuse.

These failures produce no `ActualDelta` and are eligible for the existing Step37/Step33 precommit failure path.

### After possible commit

If transport or plugin coordination loses certainty after the Revit transaction may have committed, the Host result must map to the existing `COMMIT_STATE_UNKNOWN` behavior. It must not be rewritten as a precommit failure and must not be blindly retried.

Recovery requires restored Host facts / reconciliation under the existing Step37 fail-closed rule.

## 19. Scope and verification failures remain Step33-owned

After a confirmed Host commit:

- an `ActualDelta` with any extra canonical aspect must become Step33 `SCOPE_BREACH`;
- reconstructed wall thickness differing from the canonical request must become `VERIFY_FAILED`;
- only a within-scope delta plus passing semantic verification may make the Slice and Saga `SUCCEEDED`.

Revit provider code cannot override those decisions.

## 20. No inferred rollback

This phase does not add Revit inverse-command logic.

A failed or partially committed execution uses existing Step33 durable evidence and compensation proposal semantics. Any recovery mutation must be expressed as new canonical recovery intent and re-enter the governed chain.

No coordinator or Host adapter may infer "set previous WallType width" as an automatic global rollback without a separately governed operation.

## 21. File / component boundary

Expected new or changed areas are limited to Revit Host integration and host-neutral mapping/test surfaces:

```text
hosts/revit/plugin/**
hosts/revit/sidecar/**
providers/semantics/enterprise_mapping/**
tests/revit/** or equivalent focused host tests
tests/integration/test_phase_h_revit_*.py
docs/runbooks/revit-*.md
.github/workflows/phase-h-revit-wall-thickness*.yml
```

Shared contracts may receive only compatibility/test/build wiring proven necessary by the existing wire format; changing their semantic shape is not part of the approved design.

Platform directories Step27-37 are expected to remain production-code unchanged.

## 22. Build baseline

The Revit plugin uses the .NET 8 API family used by Revit 2025 and later. Autodesk's Revit 2026 developer requirements state that the Revit API requires Microsoft .NET 8.0 and references `RevitAPI.dll` and `RevitAPIUI.dll` from the installed Revit program directory.

This phase does not require a multi-Revit-version packaging system. The implementation plan must select one installed Revit 2025+ version for the real-host acceptance while keeping the code on APIs common to that supported .NET 8 family wherever practical.

## 23. Test strategy

### Pure / offline

Prove without a live Revit process:

- Revit native snapshot -> deterministic `NormalizedDesignFact` values;
- Revit enterprise mappings -> `ifc:IfcWall` and `dsp:WallThickness`;
- ProviderBinding accepts exact Revit Wall target and rejects wrong native kind;
- supported WallType-shape evaluator is deterministic;
- shared-type set difference produces `SHARED_WALL_TYPE_OUTSIDE_SCOPE` before mutation;
- canonical mm / Revit internal-unit conversion round trips within defined tolerance;
- idempotency store replays a prior success without re-execution;
- architecture guard prevents `Autodesk.Revit` imports outside `hosts/revit/plugin` native/API boundary and tests;
- platform Step27-37 production source remains unchanged.

### Plugin tests with Revit API abstractions

Keep Revit API mechanics behind narrow plugin-local interfaces so deterministic tests can prove:

- request queue -> ExternalEvent handler dispatch;
- no mutation on failed preflight;
- exactly one transaction attempt on success;
- no second transaction on idempotent replay;
- read-back result controls success evidence;
- ambiguous post-commit completion is not downgraded to precommit failure.

### Real Revit acceptance

Use a controlled RVT fixture containing a Basic wall with an exclusive, supported WallType.

Required positive proof:

```text
canonical request = 300 mm
real Wall pre-read != 300 mm
one Revit mutation commits
real post-read = 300 mm
reconstructed dsp:WallThickness = 300 mm
ActualDelta = MODIFY / PROPERTIES only
ScopeComparator = WITHIN_SCOPE
SemanticVerifier = PASSED
Saga = SUCCEEDED
```

Required negative proofs:

1. **Shared WallType** — a second unapproved wall uses the same type -> precommit `SHARED_WALL_TYPE_OUTSIDE_SCOPE`, no mutation.
2. **Stale revision** — precondition mismatch -> no transaction commit.
3. **Idempotency replay** — same key -> same successful result, no second mutation, no replay-caused revision increment.
4. **Wrong reconstructed width** — Host commit can be real, but semantic evidence reports a different width -> `VERIFY_FAILED`, Saga not `SUCCEEDED`.
5. **Extra canonical aspect** — deliberately constructed reconciliation evidence includes another aspect -> `SCOPE_BREACH`, Saga not `SUCCEEDED`.

## 24. Completion gates

The gap closure is complete only when all of these are evidenced:

```text
real Revit Host exists under hosts/revit                              PASS
same set_wall_thickness.v1 canonical contract reused                  PASS
Step27-30 production semantics unchanged                              PASS
Step31 contract/resolver production semantics unchanged               PASS
Step32 production semantics unchanged                                 PASS
Step33 production semantics unchanged                                 PASS
Step37 production semantics unchanged                                 PASS
Revit API absent from platform core                                   PASS
Revit command enters API context through ExternalEvent                PASS
Wall identity persists by UniqueId                                    PASS
shared WallType outside approval fails before mutation                PASS
no hidden WallType duplication/CREATE in MVP                          PASS
real 300 mm wall mutation commits once                                PASS
real post-commit read-back equals 300 mm                              PASS
Revit facts project to ifc:IfcWall + dsp:WallThickness                PASS
ActualDelta reports only approved canonical wall/property change       PASS
ScopeComparator = WITHIN_SCOPE                                        PASS
SemanticVerifier = PASSED                                             PASS
Saga = SUCCEEDED                                                       PASS
stale revision is precommit/no mutation                               PASS
idempotency replay has no second Revit mutation                       PASS
wrong semantic reconstruction -> VERIFY_FAILED                        PASS
extra canonical aspect -> SCOPE_BREACH                                PASS
existing AutoCAD / Step27-37 regressions remain green                 PASS
```

## 25. Explicit non-goals

This gap closure does **not** implement:

- automatic duplication of shared WallTypes;
- automatic reassignment of one wall to a duplicated type;
- canonical CREATE authority for Revit type objects;
- approval expansion to all walls sharing a type;
- general multi-layer wall redistribution;
- vertically compound walls;
- stacked walls or curtain walls;
- wall joins / hosted openings / geometry impact policy beyond the approved property proof;
- Revit gRPC transport;
- automatic rollback or inverse Host commands;
- multi-version Revit packaging;
- Revit-specific branches in platform semantic or execution core.

Each of those requires a separate design decision if later needed.

## 26. Architecture success criterion

The strongest outcome of this phase is not merely "Revit can set a wall width." It is:

> AutoCAD and Revit, despite having different native object models and execution/threading constraints, both execute the same canonical `set_wall_thickness.v1` through the same Step27-37 governance and reconciliation core, with Host-specific knowledge contained behind Host/provider adapters.

If implementation requires platform core to learn `WallType`, `CompoundStructure`, `OST_Walls`, `ExternalEvent`, or Revit unit APIs, the design has failed and must be reopened rather than patched around.

## 27. Authoritative references

Repository contracts used by this design:

- `platform/orchestrator/src/design_orchestrator/canonical_operations.py`
- `contracts/python/design_fact_contracts/`
- `contracts/schemas/host-command.schema.json`
- `platform/provider_binding/src/design_provider_binding/`
- `platform/execution_reconciliation/src/design_execution_reconciliation/`
- `platform/execution_coordination/src/design_execution_coordination/`
- `providers/semantics/enterprise_mapping/`
- `tests/integration/test_step34_autocad_wall_thickness_reconciliation.py`

Autodesk Revit API references reviewed for this design:

- CompoundStructure: https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API/files/Revit_API_Developers_Guide/Revit_Geometric_Elements/Walls_Floors_Ceilings_Roofs_and_Openings/Revit_API_Revit_API_Developers_Guide_Revit_Geometric_Elements_Walls_Floors_Ceilings_Roofs_and_Openings_CompoundStructure_html.html
- Element.UniqueId: https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/f9a9cb77-6913-6d41-ecf5-4398a24e8ff8.htm
- External Events: https://help.autodesk.com/cloudhelp/2025/CHS/Revit-API/files/Revit_API_Developers_Guide/Advanced_Topics/Revit_API_Revit_API_Developers_Guide_Advanced_Topics_External_Events_html.html
- ControlledApplication.DocumentChanged: https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/f7acc5b4-a1b4-12ca-802b-0ee78942589e.htm
- Revit 2026 development requirements (.NET 8): https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API/files/Revit_API_Developers_Guide/Introduction/Getting_Started/Welcome_to_the_Revit_Platform_API/Revit_API_Revit_API_Developers_Guide_Introduction_Getting_Started_Welcome_to_the_Revit_Platform_API_Development_Requirements_html.html
