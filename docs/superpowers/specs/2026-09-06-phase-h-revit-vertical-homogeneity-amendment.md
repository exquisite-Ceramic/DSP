# Phase H Revit Vertical Homogeneity Amendment

**Status:** FROZEN DESIGN AMENDMENT — approved from live Revit evidence  
**Date:** 2026-09-06  
**Amends:** `docs/superpowers/specs/2026-09-01-phase-h-revit-wall-thickness-gap-closure-design.md`  
**Scope:** Revit `CompoundStructure` eligibility only

## 1. Trigger

The first real Revit 2027 isolated-wall smoke test exposed a mismatch between the frozen MVP wording and Autodesk Revit API semantics.

The controlled target was a Basic Wall using an exclusive `PH-Isolated-200` WallType with one 200 mm structural layer. The DSP command was rejected before commit with:

```text
code          = VERTICALLY_COMPOUND_WALL_UNSUPPORTED
commit_state  = BEFORE_COMMIT
revision      = 0 -> 0
```

No transaction was committed and the model was not mutated. The fail-closed behavior therefore worked as designed; the defect was the eligibility predicate.

## 2. Corrected Revit API fact

`CompoundStructure.IsVerticallyCompound` is not equivalent to "the wall has actual vertical layer variation".

Autodesk documents that a vertically compound structure can have no horizontal breaks, in which case both `IsVerticallyCompound` and `IsVerticallyHomogeneous()` are true. `IsVerticallyHomogeneous()` is the API predicate that answers whether the structure is one set of parallel layers extending from bottom to top.

References:

- https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/7f06ea80-ba2f-aecb-be51-cb463769ae1b.htm
- https://help.autodesk.com/cloudhelp/2026/ENU/Revit-API-MainReference/files/html/9b801ee8-b10b-dbef-313d-b0ef0d555ea4.htm

`SetLayerWidth` also supports a vertically compound structure when the selected layer is associated with a single simple region. Therefore `IsVerticallyCompound == true` alone is too broad a rejection condition for this MVP.

## 3. Amended eligibility invariant

The following clauses supersede the original "CompoundStructure is not vertically compound" wording in sections 2 and 10 of the frozen Phase H design.

Before mutation, the supported WallType shape is:

```text
WallKind = Basic
CompoundStructure exists
CompoundStructure.IsVerticallyHomogeneous() == true
exactly one editable non-membrane thickness layer
candidate SetLayerWidth succeeds in memory
candidate GetWidth() matches requested total within tolerance
```

A structure with `IsVerticallyCompound == true` is therefore not rejected merely for that property when `IsVerticallyHomogeneous() == true`.

A structure with `IsVerticallyHomogeneous() == false` remains outside the MVP and must fail before transaction.

## 4. Error contract

Keep the existing stable error code for compatibility:

```text
VERTICALLY_COMPOUND_WALL_UNSUPPORTED
```

Its effective Phase H meaning after this amendment is "vertically non-homogeneous CompoundStructure is unsupported". The native diagnostic message should state that directly.

No shared HostCommand schema, canonical operation, ActualDelta contract, Step27-33/37 semantics, D4 semantics, enterprise mapping, or AutoCAD production behavior changes as part of this amendment.

## 5. Safety boundary remains narrow

This amendment does not add general support for arbitrary vertically compound walls. The existing guards remain mandatory:

- exactly one approved wall;
- Basic Wall only;
- exclusive WallType;
- no supported inserts/openings;
- no actual endpoint joins;
- no unsupported/unproven associativity;
- exactly one editable non-membrane layer;
- in-memory candidate validation before transaction;
- exactly one Revit transaction on the success path;
- mandatory post-commit identity/location/relationship and width read-back;
- idempotent replay performs no second mutation.

If `SetLayerWidth` cannot legally modify the selected region, the native API exception remains a before-commit planning/validation failure because candidate construction occurs before the Revit transaction.

## 6. Regression proof

Offline architecture coverage must assert that the Native planner:

```text
uses CompoundStructure.IsVerticallyHomogeneous()
does not reject solely on if (structure.IsVerticallyCompound)
retains GetLayers / SetLayerWidth / GetWidth candidate validation
```

The real Revit acceptance gate must then re-run against the unchanged isolated wall fixture and prove:

```text
probe           -> REVISION_CONFLICT / BEFORE_COMMIT
mutation        -> OK / width_after_mm = 300 / transaction_attempt_count = 1
revision        -> advances after commit
post invariants -> identity/location/relationship proven
replay          -> replayed = true / no revision advance
```

Task 11 and Phase H remain incomplete until this amended predicate is built against the pinned Revit 2027 installation and the real live acceptance path passes.
