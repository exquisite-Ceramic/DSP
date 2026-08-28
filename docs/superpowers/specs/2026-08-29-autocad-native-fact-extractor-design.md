# AutoCAD Native Fact Extractor Design

## Status

Approved in architecture discussion on 2026-08-29 for Spec v0.6 Phase E, Step 19: AutoCAD native fact extractor.

This document freezes the Step 19 boundary between AutoCAD-native observation and the `NormalizedDesignFact` contract introduced in Step 18. It does not amend the main Spec beyond choosing concrete Step 19 implementation details consistent with the frozen architecture.

Implementation MUST NOT begin until this written design has been reviewed and approved by the user. After approval, the next step is a separate implementation plan produced with the project planning workflow.

## Goal

Introduce a read-only AutoCAD-native fact extraction path that captures stable Host-local snapshots inside the AutoCAD plugin and converts those snapshots, through a thin sidecar adapter, into the already-frozen `NormalizedDesignFactBatch` contract.

The intended Step 19 pipeline is:

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

Step 19 answers:

```text
What native facts can AutoCAD expose, at one known document revision,
in a Host-local shape that can be deterministically normalized?
```

Step 19 does not answer:

```text
What IFC / DSP Core / Metro / Enterprise semantic meaning do those facts have?
```

That interpretation belongs to Step 20+ Semantic Providers.

## Source-of-Truth Alignment

Spec v0.6 freezes these relevant principles:

- Host design-time native state remains authoritative in the Host application.
- Host native facts pass through a Semantic Adapter into a stable data contract.
- L1 Normalized interoperability uses `NormalizedDesignFact` while canonical classification may remain unknown.
- Core modules must not understand AutoCAD Handle, AutoCAD layer conventions, Autodesk SDK types, or enterprise mappings.
- Phase E Step 19 is AutoCAD native fact extraction; Step 20 is enterprise A-WALL mapping; Step 21 proves `A-WALL → IfcWall` without D5 changes.

The approved Step 18 design also freezes `NormalizedDesignFact` as a Host-neutral transport contract and explicitly keeps `autocad.layer / A-WALL` as evidence rather than canonical meaning.

## Architectural Choice

### Chosen approach: plugin native snapshot + sidecar thin normalization

```text
Autodesk API zone
  hosts/autocad/plugin/AutoCAD.AgentHost/Native/*
        ↓
Host-local snapshot DTO
        ↓ HostCommand READ response
Sidecar DesignFactAdapter
        ↓
design_fact_contracts.NormalizedDesignFactBatch
```

This preserves the current AutoCAD architecture in which `Native/` is the only zone allowed to reference `Autodesk.*`.

### Rejected approach: plugin directly emits `NormalizedDesignFact`

This would reduce one transformation step but couple the Autodesk plugin more tightly to the stable ingestion contract. Step 19 instead keeps native observation and normalized transport as separate responsibilities.

### Rejected approach: platform/Semantic Service understands AutoCAD properties

This would recreate Host-specific branches in platform code and violate the v0.6 boundary. AutoCAD-native interpretation remains inside the AutoCAD Host plane.

## Component Responsibilities

### 1. Plugin Native Extractor

The plugin owns direct AutoCAD SDK access.

It SHALL:

- execute read-only entity extraction inside the active AutoCAD document;
- acquire the existing document lock before reading;
- use one AutoCAD transaction for one extraction request where practical;
- freeze one document revision for the returned snapshot set;
- resolve requested entity handles to live entities;
- capture only Host-native observations;
- never assign IFC / Metro / DSP Core / enterprise canonical semantics.

The extractor MUST remain inside the Host plugin boundary and may use Autodesk SDK types internally.

### 2. Host-local NativeSnapshot

`NativeSnapshot` is a Host-local response shape, not a new cross-Host public contract.

The minimum logical shape is:

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

The wire response between AutoCAD plugin and AutoCAD sidecar may use JSON-compatible object shapes consistent with the existing `HostCommandResult.payload` mechanism.

This DTO is intentionally AutoCAD-specific and MUST NOT move into `contracts/`.

### 3. Sidecar DesignFactAdapter

The sidecar adapter owns the thin transformation from AutoCAD-local snapshot shape to the stable Step 18 contract.

It SHALL:

- depend on `design_fact_contracts`;
- create `DesignFactHostRef` and `NativeSubjectRef` values;
- preserve `document_id`, `host_instance_id`, `revision`, handle, native kind, layer, and bounds evidence;
- generate deterministic `fact_id` values;
- return `NormalizedDesignFactBatch`;
- perform no semantic mapping beyond transport-level `fact_kind` / `predicate` selection.

It MUST NOT import Semantic Service, D5, IFC4.3, Metro, or Enterprise mapping implementations.

## Host Instance Identity

`NormalizedDesignFact.host_ref` requires:

```text
host_type
host_instance_id
document_id
```

Step 19 SHALL use:

```text
host_type = "autocad"
```

`host_instance_id` is a runtime AutoCAD/plugin-session identity and MAY change when AutoCAD restarts. It is not persistent semantic identity and MUST NOT be used as `SemanticId`.

The plugin SHALL expose one non-empty host instance identifier for the life of the plugin session. The implementation may generate this once during plugin process/lifecycle initialization.

## Document Revision Consistency

A returned `AutoCADNativeSnapshotBatch` MUST represent one document revision.

The extractor SHALL:

1. identify the active document;
2. acquire the document lock;
3. capture the current document revision;
4. read all requested entities for that request under the same read operation;
5. return that frozen revision with the snapshot batch.

The sidecar MUST copy that batch revision into every emitted `NormalizedDesignFact.source_revision`.

Step 19 MUST NOT combine facts read from different document revisions into one normalized batch while pretending they share a revision.

## Entity Resolution Semantics

The request is handle-scoped.

Conceptual read operation:

```text
design.extract_native_snapshot(handles[])
```

Rules:

- `handles` is required as an array of non-empty strings;
- an empty array is valid and returns an empty entity snapshot list at the current revision;
- duplicate handles SHOULD be normalized deterministically so the response does not duplicate facts accidentally;
- malformed handles, erased entities, unresolved handles, or entities that cannot be opened for read MUST fail closed rather than silently claiming successful complete extraction;
- the response SHOULD identify the failed handle in the contract error detail where the existing Host error model permits it.

Step 19 deliberately chooses fail-closed explicit extraction over silently skipping missing requested entities, because later freshness/coverage logic must distinguish “read and found nothing” from “could not read the requested subject.”

## Native Entity Kind

For the frozen Step 19 proof path, `native_kind` SHALL use AutoCAD's native/DXF entity type token where available rather than a .NET CLR class name.

Examples:

```text
LWPOLYLINE
LINE
ARC
```

This keeps the evidence closer to AutoCAD's native vocabulary and avoids leaking implementation-language type names into normalized facts.

If the SDK cannot produce a non-empty native kind for an otherwise readable entity, extraction MUST fail closed for that entity.

## Layer Evidence

Every readable AutoCAD `Entity` exposes a layer name.

The native snapshot SHALL preserve the actual layer string without enterprise interpretation.

The sidecar SHALL emit one normalized classification evidence fact per entity:

```text
fact_kind     = CLASSIFICATION
predicate     = "layer"
value         = <actual AutoCAD layer string>
value_type    = STRING
source_scheme = "autocad.layer"
source_code   = <actual AutoCAD layer string>
```

For an entity on `A-WALL` this becomes:

```text
source_scheme = "autocad.layer"
source_code   = "A-WALL"
```

Step 19 MUST NOT contain:

```text
A-WALL → IfcWall
A-WALL → any canonical wall classification
```

No specific layer name is privileged by the extractor.

## Identity Evidence

The sidecar SHALL emit one transport-level identity/native-kind fact per entity:

```text
fact_kind  = IDENTITY
predicate  = "native_kind"
value      = <native_kind>
value_type = STRING
```

The subject identity remains:

```text
subject_native_ref.document_id
subject_native_ref.native_id
subject_native_ref.native_kind
```

No `semantic_id` is allocated in Step 19.

## Bounds Evidence

If AutoCAD geometric extents are valid for the entity, the native snapshot MAY include axis-aligned bounds:

```text
bounds = {
  min: { x, y, z },
  max: { x, y, z }
}
```

The sidecar SHALL emit one fact:

```text
fact_kind  = BOUNDS
predicate  = "geometric_extents"
value      = <bounds object>
value_type = OBJECT
```

Step 19 does not:

- embed full entity geometry;
- define coordinate canonicalization;
- change geometry fidelity state;
- claim `EXACT` canonical geometry;
- perform topology reconstruction.

If an entity type does not provide valid geometric extents, absence of the BOUNDS fact is permitted as long as identity and layer evidence were successfully extracted.

## Deterministic Fact IDs

Repeated normalization of the same native observation at the same document revision SHALL produce the same `fact_id`.

The logical ID input is:

```text
document_id
source_revision
native_id
fact_kind
predicate
```

The implementation SHALL use a deterministic namespaced digest/UUID scheme rather than random UUIDs.

The algorithm MUST be stable within Step 19 v1 and covered by tests. The exact hashing/UUID primitive is an implementation detail documented in the implementation plan.

## Producer and Provenance

The sidecar SHALL set a stable producer token identifying the AutoCAD design-fact adapter, for example:

```text
producer = "autocad.sidecar.design_fact_adapter.v1"
```

The exact frozen token will be chosen in implementation and tested.

Each emitted fact SHALL carry ordered provenance references sufficient to identify its Host-native origin without embedding SDK objects.

At minimum provenance SHALL include a deterministic native source reference derived from:

```text
host_type
document_id
native_id
source_revision
```

Step 19 provenance is source evidence only; it does not assign an assurance level.

## Sidecar Public API

The sidecar SHALL expose an internal typed entry point suitable for later Semantic ingestion:

```text
extract_design_facts(handles: list[str]) -> NormalizedDesignFactBatch
```

The sidecar MAY expose this through its existing Host-facing MCP surface as a read-only tool if that is needed for reference-path testing, but Step 19 MUST NOT introduce a new Semantic MCP ingestion endpoint.

The implementation plan must choose the smallest path needed to prove Step 19 without expanding protocol scope unnecessarily.

## Error Handling

Step 19 uses existing Host command/envelope error semantics.

The extractor SHALL fail closed for:

- no active AutoCAD document;
- blank/malformed requested handle;
- unresolved handle;
- erased entity;
- unreadable entity;
- missing native kind;
- blank layer where AutoCAD contract assumptions require a layer;
- invalid/non-JSON-compatible extracted value;
- revision/identity inconsistency discovered during normalization.

The adapter SHALL also rely on `NormalizedDesignFact` constructor validation and MUST propagate contract-validation failures rather than repair malformed input silently.

## Dependency Direction

Allowed:

```text
AutoCAD Native/* → Autodesk.*
AutoCAD command handler → Native extractor
AutoCAD sidecar → HostContracts
AutoCAD sidecar DesignFactAdapter → design_fact_contracts
```

Forbidden:

```text
contracts/design_fact_contracts → AutoCAD plugin/sidecar
Semantic Service → Autodesk.*
D5 → Autodesk.*
AutoCAD extractor → semantic_service
AutoCAD extractor → semantic_runtime
AutoCAD extractor → IFC provider
AutoCAD extractor → Metro provider
AutoCAD extractor → Enterprise mapping provider
```

The Step 19 implementation SHALL include architecture tests enforcing these boundaries where practical.

## Proposed Repository Changes

Expected plugin changes:

```text
hosts/autocad/plugin/AutoCAD.AgentHost/
├─ Native/
│  └─ AutoCADNativeFactApi.cs
├─ Commands/
│  ├─ HostCommandHandler.cs
│  └─ Design/
│     └─ ExtractNativeSnapshotHandler.cs
└─ Identity/ or Bootstrap/
   └─ host-instance session identity
```

Expected sidecar changes:

```text
hosts/autocad/sidecar/src/autocad_sidecar/
├─ adapter/
│  └─ design_fact_adapter.py
└─ execution/
   └─ command_dispatcher.py
```

The implementation plan SHALL refine exact paths after checking current test conventions and build constraints.

## Testing Strategy

Implementation SHALL use TDD.

### Pure sidecar unit tests

Use synthetic Host-local snapshot payloads to prove:

- empty snapshot batch → empty `NormalizedDesignFactBatch`;
- one entity → identity + classification facts;
- valid bounds → BOUNDS fact;
- `A-WALL` preserved as `autocad.layer / A-WALL`;
- no `semantic_id` or `ifc:IfcWall` appears;
- repeated same revision snapshot yields identical fact IDs;
- changing revision changes fact IDs;
- document/host identity is copied correctly;
- malformed snapshots fail closed.

These tests MUST NOT require live AutoCAD.

### Host command / transport tests

Use current injected/fake transport patterns to prove the sidecar sends the correct read command and normalizes the response.

### Plugin architecture/source tests

Prove:

- Autodesk SDK references remain confined to `Native/` according to ADR-001;
- the new command handler delegates native reading rather than embedding semantic mapping;
- no IFC/Metro/Enterprise semantic token is hardcoded into the extractor path.

### Optional live AutoCAD integration

A live-host test MAY prove one known selected/known-handle entity returns a valid normalized batch, but live AutoCAD is not required for ordinary CI success.

## Explicit Non-Goals for Step 19

Step 19 MUST NOT implement or modify:

- enterprise A-WALL mapping provider (Step 20);
- `A-WALL → IfcWall` canonical mapping proof (Step 21);
- task-scoped aspect/fidelity upgrading (Step 22);
- SemanticClaim production;
- IFC4.3 Provider behavior;
- Metro Semantic Provider behavior;
- DSP Core Provider behavior;
- D5 reconstruction, identity allocation, freshness, coverage, maturity, or assurance;
- canonical unit conversion;
- canonical coordinate conversion;
- full geometry serialization/reconstruction;
- Revit/Tekla extractors;
- Host write behavior;
- ProviderBinding / ExecutionGrant;
- Semantic MCP ingestion protocol.

## Acceptance Criteria

Step 19 is complete when all of the following are true:

1. AutoCAD has a read-only native snapshot extraction path for requested handles.
2. Autodesk SDK objects do not cross the plugin native boundary.
3. One extraction request is represented at one frozen document revision.
4. The snapshot includes Host instance/document identity and entity handle/native kind/layer, with bounds when available.
5. The sidecar converts snapshots into the frozen Step 18 `NormalizedDesignFactBatch` without modifying that contract.
6. Each readable entity produces transport-level native-kind identity and layer classification evidence facts.
7. `A-WALL` is transported only as `autocad.layer / A-WALL` evidence.
8. No `IfcWall`, IFC mapping, Metro mapping, Enterprise mapping, or D5 behavior is introduced.
9. Fact IDs are deterministic for the same document revision and observation.
10. Requested missing/malformed/unreadable entities fail closed rather than being silently omitted.
11. Pure tests run without live AutoCAD and prove snapshot-to-NDF behavior.
12. Existing relevant Host/sidecar/contract regression tests remain green.
13. Architecture tests prove no new Host-specific dependency leaks into Semantic Service or D5.

## Phase Boundary After Step 19

After Step 19 is merged, Phase E proceeds to Step 20:

```text
enterprise A-WALL mapping provider
```

At that point a fact such as:

```text
fact_kind     = CLASSIFICATION
predicate     = layer
value         = A-WALL
source_scheme = autocad.layer
source_code   = A-WALL
```

may be interpreted by an Enterprise Semantic Provider.

The AutoCAD extractor itself remains unchanged when that mapping is added.
