# AutoCAD Native Fact Extractor Design

## Status

Approved in architecture discussion on 2026-08-29 for Spec v0.6 Phase E, Step 19: AutoCAD native fact extractor.

This document freezes the Step 19 boundary between AutoCAD-native observation and the `NormalizedDesignFact` contract introduced in Step 18. It chooses concrete Step 19 implementation details consistent with the main Spec; it does not amend the main Spec.

Implementation MUST NOT begin until this written design has been reviewed and approved by the user. After approval, the next step is a separate implementation plan.

## Goal

Introduce a read-only AutoCAD-native extraction path that captures Host-local snapshots inside the AutoCAD plugin and converts those snapshots, through a thin sidecar adapter, into the frozen `NormalizedDesignFactBatch` contract.

```text
AutoCAD Entity
    ↓
Plugin Native Extractor
    ↓
Host-local NativeSnapshot
    ↓
Sidecar DesignFactAdapter
    ↓
NormalizedDesignFactBatch
```

Step 19 answers what AutoCAD natively observed at one known document revision. It does not decide what IFC / DSP Core / Metro / Enterprise meaning those observations have.

## Architecture Alignment

Spec v0.6 freezes the relevant boundary:

- Host design-time native state remains authoritative in the Host application.
- Host native facts pass through a Semantic Adapter into a stable data contract.
- L1 Normalized interoperability uses `NormalizedDesignFact` while canonical classification may remain unknown.
- Core modules must not understand AutoCAD Handle, AutoCAD layer conventions, Autodesk SDK types, or enterprise mappings.
- Phase E Step 19 is AutoCAD native extraction; Step 20 is enterprise A-WALL mapping; Step 21 proves `A-WALL → IfcWall` without D5 changes.

The Step 18 contract already freezes `autocad.layer / A-WALL` as source evidence rather than canonical meaning.

## Chosen Architecture

```text
Autodesk API zone
  hosts/autocad/plugin/AutoCAD.AgentHost/Native/*
        ↓
Host-local snapshot JSON
        ↓ HostCommand READ
AutoCAD sidecar DesignFactAdapter
        ↓
design_fact_contracts.NormalizedDesignFactBatch
```

This preserves the existing rule that `Native/` is the only AutoCAD plugin zone allowed to reference `Autodesk.*`.

Rejected alternatives:

1. **Plugin directly emits `NormalizedDesignFact`** — fewer lines, but couples Autodesk-native observation to the stable cross-Host ingestion contract.
2. **Platform/Semantic Service understands AutoCAD properties** — violates the v0.6 Host-neutral core boundary and would cause Host-specific growth in platform code.

## Component Responsibilities

### Plugin Native Extractor

The plugin owns direct AutoCAD SDK access. It SHALL:

- execute a read-only extraction request against the active AutoCAD document;
- acquire the existing document lock;
- capture one document revision for the complete request;
- use one read transaction for the requested entity set where practical;
- resolve requested handles to live entities;
- capture only Host-native observations;
- never assign IFC, Metro, DSP Core, or enterprise canonical semantics.

### Host-local Snapshot

The snapshot is AutoCAD-local and MUST NOT move into `contracts/`.

```text
AutoCADNativeSnapshotBatch {
  host_instance_id
  document_id
  revision
  entities[]
}

AutoCADNativeEntitySnapshot {
  native_id
  native_kind
  layer
  bounds?
}
```

It is carried inside the existing JSON-compatible `HostCommandResult.payload` mechanism.

### Sidecar DesignFactAdapter

The sidecar adapter SHALL:

- depend on `design_fact_contracts`;
- validate the Host-local snapshot shape;
- create `DesignFactHostRef` and `NativeSubjectRef` values;
- preserve document/runtime identity, revision, handle, native kind, layer, and optional bounds;
- produce deterministic `fact_id` values;
- return `NormalizedDesignFactBatch`;
- perform only transport-level `fact_kind` / `predicate` selection.

It MUST NOT import Semantic Service, D5, IFC4.3, Metro, or Enterprise mapping implementations.

## Host Runtime Identity

Every normalized fact uses:

```text
host_type = "autocad"
host_instance_id = <plugin-session UUID>
document_id = <active AutoCAD document id>
```

The plugin SHALL create one UUID string when the plugin process/AppDomain initializes and reuse it for the lifetime of that plugin session. It MAY change after AutoCAD restarts. It is runtime identity, not `SemanticId`.

## Revision Consistency

One snapshot batch MUST correspond to one document revision.

The extractor SHALL:

1. identify the active document;
2. acquire its document lock;
3. capture the current revision;
4. read all requested entities for that request;
5. return the captured revision with the batch.

The sidecar MUST copy the batch revision into every emitted `NormalizedDesignFact.source_revision`.

Step 19 MUST NOT combine observations from different revisions into one batch while claiming one revision.

## Handle-Scoped Read Contract

The plugin adds one HostCommand READ operation:

```text
design.extract_native_snapshot
```

Input payload:

```text
handles: string[]
```

Rules:

- `handles` is required;
- every handle must be a non-empty string and valid AutoCAD handle token;
- empty array is valid and returns an empty entity list at the current revision;
- duplicate handles are de-duplicated while preserving first-seen order;
- malformed, unresolved, erased, or unreadable requested entities cause the request to fail closed;
- an extraction failure SHOULD identify the offending handle using the existing Host error model.

Requested subjects are never silently skipped. Later freshness/coverage logic must be able to distinguish “successful empty request” from “requested entity could not be read.”

## Native Kind

`native_kind` SHALL use the AutoCAD/DXF entity token from the SDK where available, rather than the .NET CLR class name.

Examples:

```text
LWPOLYLINE
LINE
ARC
```

A readable entity without a non-empty native kind fails closed.

## Layer Evidence

The native snapshot preserves the actual AutoCAD layer string without interpretation.

For every entity, the sidecar emits:

```text
fact_kind     = CLASSIFICATION
predicate     = "layer"
value         = <actual layer>
value_type    = STRING
source_scheme = "autocad.layer"
source_code   = <actual layer>
```

Therefore an `A-WALL` entity carries:

```text
source_scheme = "autocad.layer"
source_code   = "A-WALL"
```

No layer name is privileged. Step 19 MUST NOT contain `A-WALL → IfcWall` or any other canonical layer mapping.

## Native-Kind Identity Evidence

For every entity, the sidecar also emits:

```text
fact_kind  = IDENTITY
predicate  = "native_kind"
value      = <native_kind>
value_type = STRING
```

The subject remains the frozen Step 18 native reference:

```text
subject_native_ref.document_id
subject_native_ref.native_id
subject_native_ref.native_kind
```

No `semantic_id` is allocated.

## Bounds Evidence

If the entity has valid AutoCAD geometric extents, the snapshot MAY include:

```text
bounds = {
  min: { x, y, z },
  max: { x, y, z }
}
```

The sidecar then emits:

```text
fact_kind  = BOUNDS
predicate  = "geometric_extents"
value      = <bounds object>
value_type = OBJECT
```

Absence of valid extents is allowed and simply omits the BOUNDS fact. Step 19 does not embed full geometry, canonicalize coordinates, assign geometry fidelity, or perform topology reconstruction.

## Deterministic Fact IDs

Fact IDs are stable for the same observation at the same revision.

The canonical fact key is UTF-8 text:

```text
autocad-fact-v1|<document_id>|<source_revision>|<native_id>|<fact_kind>|<predicate>
```

`fact_id` SHALL be the lowercase hexadecimal SHA-256 digest of that exact key.

Changing revision, entity, fact kind, or predicate changes the ID. Re-normalizing the same key produces the same ID. The version prefix prevents a future algorithm/key-shape revision from being ambiguous.

## Producer and Provenance

Every emitted fact SHALL use:

```text
producer = "autocad.sidecar.design_fact_adapter.v1"
```

Every fact SHALL include one ordered provenance item:

```text
autocad.native|document=<document_id>|native=<native_id>|revision=<source_revision>
```

This string is evidence only. It does not assign assurance or semantic authority.

## Sidecar API Boundary

Step 19 adds a typed sidecar entry point:

```text
extract_design_facts(handles: list[str]) -> NormalizedDesignFactBatch
```

Implementation path:

```text
CommandDispatcher.extract_design_facts
  ↓
HostCommand READ design.extract_native_snapshot
  ↓
DesignFactAdapter.normalize
  ↓
NormalizedDesignFactBatch
```

**Step 19 SHALL NOT add a new Host MCP tool or Semantic MCP endpoint.** The proof uses the existing internal sidecar/HostCommand path. Protocol exposure, if later required, is a separate decision.

## Error Handling

The extractor fails closed for:

- no active AutoCAD document;
- blank/malformed requested handle;
- unresolved or erased handle;
- unreadable entity;
- missing native kind;
- blank layer;
- invalid snapshot values;
- document/runtime/revision inconsistency.

The sidecar relies on `NormalizedDesignFact` validation and propagates malformed snapshot/contract failures rather than repairing them silently.

## Dependency Direction

Allowed:

```text
AutoCAD Native/* → Autodesk.*
AutoCAD command handler → Native extractor
AutoCAD sidecar → HostContracts
AutoCAD DesignFactAdapter → design_fact_contracts
```

Forbidden:

```text
design_fact_contracts → AutoCAD implementation
Semantic Service → Autodesk.*
D5 → Autodesk.*
AutoCAD extractor → semantic_service
AutoCAD extractor → semantic_runtime
AutoCAD extractor → IFC / Metro / Enterprise semantic providers
```

## Expected Repository Changes

```text
hosts/autocad/plugin/AutoCAD.AgentHost/
├─ Native/AutoCADNativeFactApi.cs
├─ Commands/Design/ExtractNativeSnapshotHandler.cs
├─ Commands/HostCommandHandler.cs
└─ Identity/HostInstanceIdentity.cs

hosts/autocad/sidecar/src/autocad_sidecar/
├─ adapter/design_fact_adapter.py
└─ execution/command_dispatcher.py
```

Tests and CI files may also be added, but Step 18 contract definitions themselves MUST NOT be changed unless a genuine contract defect is discovered and separately approved.

## Testing Strategy

Implementation SHALL use TDD.

Pure tests without live AutoCAD MUST prove:

- empty snapshot → empty `NormalizedDesignFactBatch`;
- one entity → IDENTITY + CLASSIFICATION;
- valid bounds → BOUNDS;
- `A-WALL` remains `autocad.layer / A-WALL` evidence;
- no `semantic_id` or `ifc:IfcWall` appears;
- same snapshot/revision → same fact IDs;
- revision change → different fact IDs;
- runtime/document identity is copied correctly;
- malformed snapshot fails closed;
- duplicate handles cannot duplicate emitted facts.

Host command/fake transport tests MUST prove the sidecar sends `design.extract_native_snapshot` and normalizes its response.

Architecture/source tests MUST prove:

- Autodesk references remain confined to plugin `Native/` under the existing ADR rule;
- the new command handler delegates native reads rather than embedding mapping logic;
- no IFC/Metro/Enterprise canonical mapping is hardcoded into Step 19;
- Semantic Service and D5 gain no AutoCAD dependency.

A live AutoCAD integration test MAY be added as optional/skipped-by-default proof, but ordinary CI MUST NOT require a live AutoCAD instance.

## Explicit Non-Goals

Step 19 MUST NOT implement or modify:

- enterprise A-WALL mapping provider (Step 20);
- `A-WALL → IfcWall` proof (Step 21);
- task-scoped aspect/fidelity upgrading (Step 22);
- `SemanticClaim` production;
- IFC4.3 / Metro / DSP Core Provider behavior;
- D5 reconstruction, identity allocation, freshness, coverage, maturity, or assurance;
- canonical unit or coordinate conversion;
- full geometry serialization/reconstruction;
- Revit/Tekla extraction;
- Host write behavior;
- ProviderBinding / ExecutionGrant;
- Host MCP catalog expansion;
- Semantic MCP ingestion protocol.

## Acceptance Criteria

Step 19 is complete when:

1. AutoCAD has a read-only native snapshot operation for requested handles.
2. Autodesk SDK objects remain inside the plugin native boundary.
3. One extraction request is represented at one frozen document revision.
4. The snapshot carries session/document identity plus handle, DXF/native kind, layer, and optional bounds.
5. The sidecar converts snapshots into the unchanged Step 18 `NormalizedDesignFactBatch`.
6. Each readable entity produces native-kind IDENTITY and layer CLASSIFICATION evidence; valid extents additionally produce BOUNDS.
7. `A-WALL` is transported only as `autocad.layer / A-WALL` evidence.
8. No IFC/Metro/Enterprise mapping or D5 behavior is introduced.
9. Fact IDs follow the frozen deterministic SHA-256 rule.
10. Missing/malformed/unreadable requested entities fail closed rather than being silently omitted.
11. Pure tests run without live AutoCAD and prove snapshot-to-NDF behavior.
12. Existing relevant Host/sidecar/contract regression tests remain green.
13. Architecture tests prove no Host-specific dependency leaks into Semantic Service or D5.

## Phase Boundary After Step 19

After Step 19 is merged, Phase E proceeds to Step 20: the enterprise A-WALL mapping provider.

Step 20 may interpret:

```text
fact_kind     = CLASSIFICATION
predicate     = layer
value         = A-WALL
source_scheme = autocad.layer
source_code   = A-WALL
```

The AutoCAD extractor itself must not change when that mapping is added.
