# DSP Core Semantic Provider Design

## Goal

Implement Spec v0.6 Phase D step 15 as the first concrete reference Semantic Provider: an immutable, deterministic `dsp:*` vocabulary provider that plugs into the already-merged Semantic Service and Semantic MCP layers without changing their domain contracts.

This provider exists to define cross-industry DSP collaboration semantics that IFC does not own. It is deliberately the smallest real Provider that proves the Phase C boundaries before IFC4.3 and Metro providers add larger vocabularies and validation rules.

## Architecture Position

Production code imports remain acyclic:

```text
dsp_core_semantic_provider ---> semantic_service contracts
semantic_mcp              ---> semantic_service contracts
semantic_service           -X-> concrete provider packages
```

Runtime call flow is the opposite direction at the Provider boundary because the registry holds a concrete object behind the stable protocol:

```text
Semantic MCP
    ↓
SemanticService
    ↓ protocol call
DspCoreSemanticProvider
```

The provider MUST NOT import:

```text
semantic_runtime
semantic_mcp
AutoCAD / Revit / Tekla packages
IFC or Metro provider implementations
orchestrator / D4
D6 / D7 execution modules
Gateway
```

Tests MAY compose the provider with `semantic_service` and `semantic_mcp` to prove integration. Production provider code depends only on the stable `semantic_service` provider contract.

## Package Layout

Create the first reference-provider root using the repository target layout from Spec v0.6 §39:

```text
providers/
  semantics/
    dsp_core/
      pyproject.toml
      src/
        dsp_core_semantic_provider/
          __init__.py
          catalog.py
          hashing.py
          provider.py
      README.md

tests/
  semantic_providers/
    dsp_core/
      test_manifest.py
      test_catalog.py
      test_provider.py
      test_service_integration.py
      test_mcp_integration.py
      test_architecture.py
```

Do not create empty IFC or Metro package scaffolding in this PR.

## Provider Identity and Authority

The baseline provider manifest is:

```text
provider_id   = dsp.core.semantic
provider_type = CORE
version       = 0.6
namespaces    = [dsp]
capabilities  = [VOCABULARY]
authority     = dsp -> AUTHORITATIVE
requires      = []
```

Only `VOCABULARY` is claimed in the first version. The provider does not claim MAPPING, VALIDATION, or PROJECTION merely because future DSP semantics may use those capabilities.

`dsp:*` vocabulary authority belongs to this provider inside any pinned SemanticEnvironment that selects it. IFC, Metro, Enterprise, and Host providers must not redefine the canonical meaning of `dsp:*` terms.

## Term Definition Model

The provider owns an internal immutable `SemanticTermDefinition` value. It is a provider implementation detail, not a new Semantic Service contract.

```text
SemanticTermDefinition
  term_id
  version
  kind
  domain
  range
  unit?
  allowed_values[]
  constraints
  label
  description
```

The fields split into two classes.

### Machine-semantic fields

These participate in provider content hashing:

```text
term_id
version
kind
domain
range
unit
allowed_values
constraints
```

### Presentation-only fields

These do not participate in semantic content hashing:

```text
label
description
```

The provider stores both label and description because Spec v0.6 requires them as presentation metadata. The current Semantic Service `TermDescription` contract exposes description text but has no structured label field; PR #8 does not widen that stable service contract. `label` remains provider-owned presentation metadata for now.

## Initial Canonical Term Set

The provider contains exactly the eight DSP Core terms named by Spec v0.6 §14 for the first baseline:

```text
dsp:SemanticIdentity
dsp:HostBinding
dsp:ExternalIdentity
dsp:WallThickness
dsp:Freshness
dsp:Assurance
dsp:Snapshot
dsp:ChangeSet
```

No Host-native, IFC-specific, Metro-specific, or enterprise-specific terms are added.

### `dsp:SemanticIdentity`

```text
kind   = TYPE
domain = DSP_COLLABORATION
range  = SEMANTIC_IDENTITY
unit   = null
constraints:
  host_bindings = 0..N
  external_identities = 0..N
```

It represents the stable platform semantic identity concept. It does not carry an IFC GlobalId special field.

### `dsp:HostBinding`

```text
kind   = TYPE
domain = SEMANTIC_IDENTITY
range  = HOST_NATIVE_IDENTITY_BINDING
unit   = null
constraints:
  required = [host_type, document_id, native_id]
```

This is semantic vocabulary for the binding concept; it does not expose Revit ElementId, AutoCAD Handle, or any concrete Host type in the canonical definition.

### `dsp:ExternalIdentity`

```text
kind   = TYPE
domain = SEMANTIC_IDENTITY
range  = EXTERNAL_IDENTITY_BINDING
unit   = null
constraints:
  required = [scheme, value]
```

Specific schemes such as `ifc.global_id` remain values, not special DSP Core fields.

### `dsp:WallThickness`

```text
kind   = PROPERTY
domain = WALL_LIKE_DESIGN_ELEMENT
range  = NUMBER
unit   = mm
constraints:
  minimum_exclusive = 0
```

Using `mm` as this term's canonical semantic unit is a PR #8 design choice consistent with the existing wall-thickness examples; it is not a provider/native execution unit. Native unit conversion remains a later ProviderBinding concern.

### `dsp:Freshness`

```text
kind   = STATE
domain = SEMANTIC_ASPECT
range  = ENUM
allowed_values =
  FRESH
  STALE
  DIRTY
  UNKNOWN
  RECONSTRUCTING
```

The allowed values match the already-frozen D5 `FreshnessState` vocabulary. The provider does not import D5 to obtain them; conformance tests compare the provider vocabulary to the public runtime values at an integration boundary.

### `dsp:Assurance`

```text
kind   = STATE
domain = SEMANTIC_CLAIM
range  = ORDERED_ENUM
allowed_values =
  UNKNOWN
  HEURISTIC
  RULE_DERIVED
  STANDARD_MAPPED
  NATIVE_ASSERTED
```

The ordering is the existing D5 baseline order. As with freshness, production provider code does not import D5.

### `dsp:Snapshot`

```text
kind   = TYPE
domain = COLLABORATION_STATE
range  = IMMUTABLE_SEMANTIC_SNAPSHOT
unit   = null
constraints:
  snapshot_kind = [CONTEXT, PLANNING]
  planning_requires = [semantic_projection_ref, semantic_environment_ref]
```

This defines the cross-industry concept and its baseline invariants, not the D5 storage implementation.

### `dsp:ChangeSet`

```text
kind   = TYPE
domain = MODEL_OPERATION
range  = IMMUTABLE_CANONICAL_LOGICAL_TRANSACTION
unit   = null
constraints:
  approval_binds = [changeset_hash, approved_scope_hash, semantic_environment_ref]
  provider_native_payload_forbidden = true
```

This freezes the semantic concept from Spec v0.6 without implementing D7 storage, approval, execution, or saga behavior in this PR.

## Term Schema Surface

`get_term_schema(term_id)` returns the machine-semantic fields through the existing immutable `semantic_service.TermSchema` DTO.

Canonical schema shape:

```text
{
  "term_id": "dsp:WallThickness",
  "version": "0.6",
  "kind": "PROPERTY",
  "domain": "WALL_LIKE_DESIGN_ELEMENT",
  "range": "NUMBER",
  "unit": "mm",
  "allowed_values": [],
  "constraints": {...}
}
```

Presentation label/description are intentionally not embedded in this machine-semantic schema.

`resolve_term(term_id)` returns the existing `ResolvedTerm(term_id, kind, provenance)`.

`describe_term(term_id, locale=None)` returns the canonical description through `TermDescription`. Localization catalogs are out of scope; an unsupported/non-default locale falls back to the canonical description and reports `locale=None` rather than pretending a translation exists.

Unknown terms fail deterministically inside the provider. The Semantic Service already wraps provider exceptions into `TermResolutionError`, so the provider does not invent a second cross-service error contract.

## Deterministic Content Hashing

The provider `content_hash` is content-addressed from the complete machine-semantic catalog.

Algorithm:

```text
1. take every SemanticTermDefinition.machine_payload()
2. sort definitions by term_id
3. normalize mappings by sorted key JSON
4. normalize set-like values into deterministic ordered lists
5. JSON encode with sorted keys and compact separators
6. sha256 -> lowercase hex content_hash
```

The manifest uses this computed hash; it is not a hand-maintained constant.

Required invariants:

```text
same machine semantics + different term insertion order
  -> same content_hash

label/description-only change
  -> same content_hash

kind/domain/range/unit/allowed_values/constraints change
  -> different content_hash

provider content_hash change
  -> SemanticProviderManifest.manifest_hash changes
  -> pinned SemanticEnvironment content_hash/id changes
```

The term `version` is part of each machine payload. Reusing one provider version with different machine semantics remains fail-closed through the already-implemented SemanticProviderRegistry immutable-version rule.

## Provider Implementation

`DspCoreSemanticProvider` implements only `SemanticVocabularyProvider`.

It owns:

```text
manifest
resolve_term(term_id)
describe_term(term_id, locale=None)
get_term_schema(term_id)
```

The provider uses one immutable catalog indexed by exact canonical `term_id`. Lookup is exact and case-sensitive; no fuzzy aliasing, LLM matching, or implicit namespace correction is performed.

Every returned `ResolvedTerm`, `TermDescription`, and `TermSchema` carries one exact provenance value derived from the provider manifest:

```text
ProviderProvenance(
  provider_id = dsp.core.semantic,
  version = 0.6,
  content_hash = <computed catalog hash>
)
```

This is required because Semantic Service rejects results whose provenance does not exactly match the pinned Provider manifest.

## Service and MCP Integration Proof

The provider is registered and consumed through existing Phase C contracts; no production integration adapter is added.

Service-level proof:

```text
DspCoreSemanticProvider
  -> SemanticProviderRegistry.register(provider)
  -> SemanticEnvironmentStore.pin([dsp.core.semantic@0.6])
  -> SemanticService.resolve_term("dsp:WallThickness", env_id)
  -> SemanticService.get_term_schema(...)
```

Transport-level proof uses the already-merged Semantic MCP adapter only in tests:

```text
SemanticService with pinned DSP Core Provider
  -> build_mcp_server(service)
  -> real MCP client
  -> semantic.resolve_term
  -> semantic.get_term_schema
```

The test proves the generic MCP layer transports a real Provider result. Production `dsp_core_semantic_provider` must not import `semantic_mcp`.

## Error Handling

Provider-local lookup failure is deterministic and contains no Host/native state.

The Semantic Service remains the owner of cross-provider/domain error normalization:

```text
provider lookup exception
  -> SemanticService TermResolutionError
  -> Semantic MCP ErrorShape translation
```

No new error codes are introduced in PR #8.

## Testing Strategy

Implementation follows RED -> GREEN TDD.

### Catalog/hash tests

- the exact eight-term baseline is present;
- duplicate term IDs are rejected at catalog construction;
- insertion order does not change `content_hash`;
- presentation-only edits do not change `content_hash`;
- machine-semantic edits do change `content_hash`;
- catalog and nested schema values are immutable/deterministic.

### Manifest tests

- provider ID/type/version are exact;
- namespace is exactly `dsp`;
- `dsp` authority is exactly AUTHORITATIVE;
- capability set is exactly `{VOCABULARY}`;
- no dependencies are declared;
- manifest `content_hash` equals the catalog hash.

### Vocabulary tests

- all eight terms resolve with exact provenance;
- schemas expose machine semantics and omit presentation metadata;
- descriptions are available without changing machine identity;
- unknown terms fail deterministically;
- lookup remains exact/case-sensitive.

### D5 vocabulary compatibility tests

At the test boundary only:

- `dsp:Freshness.allowed_values` equals public D5 `FreshnessState` values;
- `dsp:Assurance.allowed_values` equals public D5 `AssuranceLevel` values in order;
- no production import from the provider to `semantic_runtime` is allowed.

This prevents silent vocabulary drift while preserving package dependency direction.

### Semantic Service integration tests

- registry accepts the provider as VOCABULARY-capable;
- pinning produces an immutable environment;
- `dsp:*` resolves only through the authoritative DSP Core provider;
- returned provenance passes the existing pinned-provenance guard;
- a machine-semantic provider change produces a different environment identity.

### Semantic MCP integration test

Use the real MCP client harness already established by PR #7 to assert at least:

- `semantic.resolve_term("dsp:WallThickness", environment_id)` succeeds;
- `semantic.get_term_schema(...)` returns the deterministic schema;
- protocol/tool catalog remains the existing Semantic MCP contract.

This is an integration proof, not a new MCP surface.

### Architecture guard

Production provider sources must fail the guard if they import/reference:

```text
semantic_runtime
semantic_mcp
Autodesk
AutoCAD
Revit
Tekla
ifc: / Ifc*
metro:
A-WALL
provider-native IDs or execution tools
```

The guard should target actual imports/domain leakage without forbidding ordinary English documentation text in README/spec files.

## CI

Add a dedicated path-filtered workflow, for example `.github/workflows/dsp-core-semantic-provider.yml`.

It installs:

```text
semantic_service
semantic_mcp   # integration test only
dsp_core_semantic_provider
```

It runs:

```text
focused DSP Core provider tests
Semantic Service integration tests touched by the provider
full existing Python regression
```

The workflow runs on PRs that touch the provider/tests/design/plan/workflow and on matching pushes to `main`.

## Explicit Non-Goals

PR #8 does not implement or modify:

- IFC4.3 vocabulary/schema loading;
- Metro Semantic V3.2;
- Enterprise mappings such as A-WALL -> IfcWall;
- `NormalizedDesignFact` or semantic ingestion;
- AutoCAD/Revit/Tekla extractors;
- Semantic Service registry/routing/environment semantics;
- the seven Semantic MCP tool contracts;
- D5 reconstruction logic or snapshot storage;
- D3/D4 Canonical Action upgrade;
- D6 Parameter Binder / InteractionSession;
- D7 ChangeSet implementation, approval, ProviderBinding, execution, verification, or Saga;
- Gateway auth/policy/grant behavior;
- provider discovery/plugin loading;
- persistence/distributed provider registry;
- localization framework.

## Acceptance Boundary

PR #8 is complete when all of the following are true:

```text
1. dsp.core.semantic@0.6 is a valid CORE/VOCABULARY Provider.
2. It is the sole authoritative owner of dsp:* in a pinned environment.
3. The exact eight Spec §14 terms resolve deterministically.
4. Machine semantics and presentation metadata have separate hash behavior.
5. Term results carry exact pinned provenance.
6. A pinned environment can resolve DSP terms through SemanticService.
7. The existing Semantic MCP adapter can transport a real DSP Core term/schema.
8. D5 enum compatibility is proven only at the test boundary.
9. No Host/IFC/Metro/D5/MCP implementation concern leaks into provider production code.
10. Focused + full regression CI is green.
```

After this PR, Phase D continues with the IFC4.3 Standard Semantic Provider, then the Metro Semantic Provider.