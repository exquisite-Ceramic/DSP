# NormalizedDesignFact Contract Design

## Status

Approved in architecture discussion on 2026-08-28. This document defines the design boundary for Spec v0.6 Phase E, Step 18: the `NormalizedDesignFact` contract.

Implementation MUST NOT begin until this written design has been reviewed and approved by the user. After approval, the next step is a separate implementation plan produced with the project planning workflow.

Where this design specifies details not frozen by Spec v0.6, those details are Step 18 implementation decisions and MUST NOT be interpreted as amendments to the main Spec.

## Goal

Introduce a stable, Host-neutral ingestion contract between Host/native fact extraction and semantic interpretation.

The intended pipeline remains:

```text
HostDelta / Host read
  ↓
Native Fact Extractor
  ↓
Semantic Adapter
  ↓
NormalizedDesignFactBatch
  ↓
Semantic Service / Providers
  ↓
Canonical Claims
  ↓
D5 Collaboration Kernel
```

`NormalizedDesignFact` answers:

```text
What normalized fact did a producer observe from this Host-native subject,
and how can that fact be transported with revision and provenance intact?
```

It does not answer:

```text
What canonical entity/property does this ultimately mean?
```

That interpretation belongs to Semantic Service / Semantic Providers and later D5 reconstruction.

## Architectural Classification

This is an architectural contract change because future Host adapters, semantic adapters, providers, and ingestion tests will depend on the interface.

Step 18 therefore introduces an independent shared contract namespace rather than extending either of the existing owners:

```text
HostContracts          = Host execution/read boundary
DesignFactContracts    = normalized ingestion fact boundary
Semantic Service       = semantic vocabulary/mapping/validation boundary
D5                      = canonical collaboration projection
```

The new contract MUST NOT be owned by `host_contracts` or `semantic_service`.

Recommended package / namespace names are:

```text
Python: design_fact_contracts
.NET:   DesignFactContracts
Schema: contracts/schemas/normalized-design-fact*.schema.json
```

## Source of Truth and Contract Authority

The normative field baseline comes from Spec v0.6 §17.2:

```text
fact_id
producer
host_ref
source_revision
subject_native_ref
fact_kind
predicate
value
value_type
unit
geometry_ref
source_scheme
source_code
provenance
```

Step 18 SHALL preserve all of those fields in the public wire contract.

Spec v0.6 also freezes the responsibility boundary:

```text
NormalizedDesignFact solves how data moves, not what it ultimately means.
```

No implementation convenience may weaken that boundary.

## Contract Ownership and Dependency Direction

The desired dependency direction is:

```text
Host native extractor
        ↓
Host-local/native facts
        ↓
Semantic Adapter
        ↓
DesignFactContracts
        ↓
Semantic Service / Semantic Providers
        ↓
SemanticClaim / canonical claims
```

The following dependency directions are forbidden in Step 18:

```text
DesignFactContracts → concrete AutoCAD implementation
DesignFactContracts → concrete Revit implementation
DesignFactContracts → concrete Tekla implementation
DesignFactContracts → IFC4.3 provider implementation
DesignFactContracts → Metro provider implementation
DesignFactContracts → D5 implementation
DesignFactContracts → Autodesk.* types
DesignFactContracts → host execution/provider binding types
```

The contract may share field semantics with v0.6 `HostRuntimeRef`, but it MUST remain transport-neutral and MUST NOT require an active execution provider.

## Public Contract Shape

### NormalizedDesignFact

The logical contract is:

```text
NormalizedDesignFact {
  fact_id
  producer
  host_ref
  source_revision
  subject_native_ref
  fact_kind
  predicate
  value
  value_type
  unit
  geometry_ref
  source_scheme
  source_code
  provenance
}
```

The wire representation SHALL use snake_case JSON property names in both Python and .NET serialization.

### fact_id

`fact_id` is a required non-empty string identifying one normalized observation.

Step 18 does not prescribe a global ID generation algorithm. Producers are responsible for emitting IDs suitable for deduplication/audit within their ingestion pipeline.

### producer

`producer` is a required non-empty string identifying the component that emitted the normalized fact, for example a Host semantic adapter.

`producer` is not a Semantic Provider identity and does not confer semantic authority.

### host_ref

`host_ref` is a required structured reference with the semantics of Spec v0.6 `HostRuntimeRef`:

```text
HostRef {
  host_type
  host_instance_id
  document_id
}
```

All three values are required non-empty strings.

This identifies the Host runtime/document from which the native observation was read. It does not identify an execution provider implementation and does not become persistent semantic identity.

### source_revision

`source_revision` is a required non-negative integer and represents the Host document revision against which the fact was observed.

This matches the current Host revision model used by `HostDelta` and preserves a deterministic freshness barrier for later ingestion stages.

### subject_native_ref

`subject_native_ref` is a required structured Host-native subject reference:

```text
NativeSubjectRef {
  document_id
  native_id
  native_kind?
}
```

`document_id` and `native_id` are required non-empty strings. `native_kind` is an optional non-empty string when known.

`subject_native_ref.document_id` MUST equal `host_ref.document_id`.

The contract MUST NOT contain `semantic_id`. Semantic identity may only be established later by semantic reconstruction / identity binding.

Host SDK objects such as Autodesk `ObjectId` MUST NOT cross this boundary; native identifiers are serialized as stable strings.

### fact_kind

`fact_kind` is a required transport-level discriminator.

Step 18 freezes the following minimal vocabulary:

```text
PROPERTY
CLASSIFICATION
PLACEMENT
BOUNDS
GEOMETRY
RELATIONSHIP
IDENTITY
```

These values classify the shape/purpose of an observed native fact; they do not assert IFC, DSP Core, Metro, or enterprise canonical meaning.

Unknown extension values are not accepted in v1 of this contract. Extending this enum is a contract-versioning change.

### predicate

`predicate` is an optional non-empty string naming the normalized/native predicate within the producer's source vocabulary.

Examples may include a native field name such as `layer` or `native_kind`; the contract does not assign canonical meaning to those names.

A fact kind that does not naturally require a predicate MAY omit it.

### value and value_type

`value` carries the normalized JSON-compatible payload.

`value_type` is required and SHALL use this closed vocabulary:

```text
NULL
STRING
INTEGER
NUMBER
BOOLEAN
OBJECT
ARRAY
```

`value` MUST be compatible with `value_type`.

Only JSON-compatible values are permitted. Host SDK objects, arbitrary Python objects, .NET runtime types, file handles, and provider implementation objects are forbidden.

For `OBJECT`, object keys MUST be strings. Nested values MUST recursively remain JSON-compatible.

### unit

`unit` is an optional non-empty string carrying the unit token associated with `value` when the native/normalized fact is measured.

Step 18 transports the unit token but does not decide whether that unit is canonical or valid for a later semantic term.

### geometry_ref

`geometry_ref` is an optional non-empty string referencing geometry available through an external/native geometry retrieval mechanism.

Step 18 does not embed full geometry payloads in `NormalizedDesignFact` and does not define geometry reconstruction.

The reference is evidence/transport metadata, not canonical geometry identity.

### source_scheme and source_code

`source_scheme` and `source_code` are optional non-empty strings used to preserve native classification or coding evidence.

They SHALL be either both present or both absent.

Example:

```text
source_scheme = "autocad.layer"
source_code   = "A-WALL"
```

This pair is evidence only. In particular, Step 18 MUST NOT transform `A-WALL` into `ifc:IfcWall`; that belongs to later semantic mapping.

### provenance

`provenance` is an ordered array of zero or more non-empty strings describing source evidence / derivation references supplied by the producer.

The contract preserves these references without assigning assurance or semantic authority.

`provenance` defaults to an empty array when omitted by an in-process constructor, but wire serializers SHALL emit it explicitly for deterministic contract shape.

## Batch Contract

Spec v0.6 names `NormalizedDesignFactBatch` in the ingestion pipeline. Step 18 SHALL therefore freeze the minimal batch envelope at the same time as the fact contract:

```text
NormalizedDesignFactBatch {
  facts: [NormalizedDesignFact, ...]
}
```

`facts` is required and MAY be empty. An empty batch is a valid normalized result for a read/extraction request that produced no facts.

Step 18 deliberately does not add duplicate batch-level `producer`, `host_ref`, revision, task, semantic environment, or request metadata. Each fact remains self-describing according to the Spec v0.6 field baseline; broader transport envelopes may be introduced later when a concrete ingestion API requires them.

## Validation and Failure Semantics

The contract validators MUST fail closed for malformed facts.

At minimum, validation SHALL reject:

- missing/blank required text fields;
- negative `source_revision`;
- invalid `fact_kind`;
- invalid `value_type`;
- `value` incompatible with `value_type`;
- non-JSON-compatible nested values;
- blank optional strings when explicitly supplied;
- mismatched `host_ref.document_id` and `subject_native_ref.document_id`;
- `source_scheme` without `source_code`, or `source_code` without `source_scheme`;
- non-string or blank provenance entries;
- unknown top-level JSON properties in the JSON Schema wire contract.

Validation errors are contract errors. Step 18 does not introduce semantic mapping errors, IFC validation errors, Metro validation errors, freshness policy errors, or D5 assurance decisions.

## Immutability

Python and .NET in-process representations SHOULD be immutable/value-oriented where practical.

Nested `OBJECT` / `ARRAY` values MUST be defensively normalized or copied so callers cannot mutate an accepted fact and silently alter its meaning after validation.

The JSON wire contract remains ordinary JSON.

## Serialization and Language Parity

Step 18 SHALL freeze three equivalent representations:

```text
1. JSON Schema
2. Python contract implementation
3. .NET contract implementation
```

Python and .NET round-trips MUST preserve the same snake_case wire shape.

The contract SHALL include shared golden test vectors so parity is checked from the same serialized examples rather than from language-specific assumptions.

At minimum the vectors SHALL cover:

```text
valid property fact
valid classification evidence fact (A-WALL)
valid object value
valid empty batch
invalid source classification pair
invalid document mismatch
invalid value/value_type combination
```

## Proposed Repository Layout

```text
contracts/
├─ schemas/
│  ├─ normalized-design-fact.schema.json
│  └─ normalized-design-fact-batch.schema.json
│
├─ python/
│  ├─ design_fact_contracts/
│  │  ├─ __init__.py
│  │  ├─ refs.py
│  │  └─ fact.py
│  └─ pyproject.toml
│
├─ dotnet/
│  ├─ DesignFactContracts/
│  │  ├─ DesignFactContracts.csproj
│  │  ├─ DesignFactHostRef.cs
│  │  ├─ NativeSubjectRef.cs
│  │  ├─ NormalizedDesignFact.cs
│  │  └─ NormalizedDesignFactBatch.cs
│  └─ DesignFactContracts.Tests/
│     ├─ DesignFactContracts.Tests.csproj
│     └─ ...
│
└─ test_vectors/
   └─ normalized_design_fact/
      └─ ...
```

The existing Python `contracts/python/pyproject.toml` currently publishes only `host_contracts*`; Step 18 SHALL update packaging deliberately so `design_fact_contracts*` is an explicit package surface rather than an accidental module.

The new .NET namespace SHALL be separate from `HostContracts` even though both live under `contracts/dotnet`.

## Public API Intent

The Python public surface SHALL expose the normalized contract types from `design_fact_contracts` without requiring consumers to import implementation-private modules.

The .NET public surface SHALL expose the corresponding DTO/value types from the `DesignFactContracts` namespace.

The Step 18 contract is intended to be usable by future Step 19 AutoCAD extraction code without importing Semantic Service or D5.

## Explicit Non-Goals for Step 18

Step 18 MUST NOT implement or modify:

- AutoCAD native fact extraction (Step 19);
- Revit or Tekla extraction;
- enterprise `A-WALL` mapping (Step 20);
- `A-WALL → ifc:IfcWall` proof (Step 21);
- task-scoped aspect/fidelity upgrading (Step 22);
- `NormalizedDesignFact → SemanticClaim` mapping execution;
- IFC4.3 Provider behavior;
- Metro Semantic Provider behavior;
- DSP Core Provider behavior;
- D5 reconstruction / coverage / freshness behavior;
- semantic identity allocation;
- Host write APIs;
- ProviderBinding / ExecutionGrant;
- gRPC or MCP ingestion transport endpoints.

## Testing Strategy

Implementation SHALL use TDD and preserve the existing repository contract-testing style.

The test layers are:

```text
JSON Schema tests
  prove allowed/rejected wire shapes

Python unit + serialization tests
  prove construction, validation, immutability, and round-trip

.NET unit + serialization tests
  prove equivalent validation and round-trip

Cross-language golden-vector conformance tests
  prove both implementations agree on the shared wire contract

Architecture/source tests
  prove no Autodesk/IFC/Metro/D5 implementation dependency leaks into the contract package
```

A Step 18 PR is complete only when the new targeted tests pass and the existing relevant Host Contract / semantic service suites remain green.

## Acceptance Criteria

Step 18 is complete when all of the following are true:

1. `NormalizedDesignFact` exists as an independent shared contract, not as a Host or Semantic Service DTO.
2. Every Spec v0.6 §17.2 baseline field is represented in the wire shape.
3. `NormalizedDesignFactBatch` is frozen with a minimal `facts` envelope.
4. Host runtime/document identity and native subject identity are preserved without introducing `SemanticId`.
5. `fact_kind` and `value_type` use stable closed transport vocabularies.
6. Native classification evidence such as `autocad.layer / A-WALL` can be transported without assigning IFC meaning.
7. Values are JSON-compatible and Host SDK/native runtime types cannot leak across the boundary.
8. JSON Schema, Python, and .NET representations are equivalent.
9. Shared golden vectors prove cross-language serialization/conformance.
10. No AutoCAD extractor, semantic mapping, provider behavior, D5 reconstruction, or execution path is added in this PR.
11. Existing relevant contract and semantic tests remain green.

## Phase Boundary After Step 18

After this contract is merged, Phase E may proceed to Step 19:

```text
AutoCAD native fact extractor
```

That extractor will be allowed to emit facts such as:

```text
native_id   = A31
native_kind = LWPOLYLINE
layer       = A-WALL
```

through the frozen `NormalizedDesignFact` contract, while canonical interpretation remains outside the Host extractor and outside Step 18.