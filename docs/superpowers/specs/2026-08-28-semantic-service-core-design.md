# Semantic Service Core Design

## Goal

Introduce a provider-neutral `platform/semantic_service` subsystem that owns semantic provider contracts, immutable provider registration, namespace authority, deterministic routing, and pinned `SemanticEnvironment` construction without moving Host-native mapping, IFC/Metro vocabulary implementations, MCP transport, or D5 projection state into the service core.

This is Phase C of `Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`. It starts after the D5 v0.6 baseline has frozen `SemanticProjectionRef` and `SemanticEnvironmentRef`.

## Architectural Decision

Use **domain core first, MCP adapter second**.

```text
Platform / D5 integration
        |
        v
SemanticService logical contract
        |
        +-- SemanticProviderRegistry
        +-- authority + routing
        +-- SemanticEnvironmentStore
        +-- immutable provider metadata cache
        |
        v
Provider capability contracts
        |
        +-- future IFC4.3 Provider
        +-- future DSP Core Provider
        +-- future Metro Provider
        +-- future Enterprise Provider

Semantic MCP Server is a later thin transport adapter over the same service contract.
```

MCP is protocol/transport, not the domain boundary. `semantic_service` therefore must not import the MCP SDK in this PR.

## Source-of-Truth Boundary

The owner split remains:

- Host native design state -> Host application.
- Semantic definitions, provider versions, namespace authority, and pinned semantic environments -> Semantic Service + pinned Providers.
- Canonical progressive projection, DirtyMap, journal, freshness, and snapshots -> D5.
- Canonical Action definitions -> Action Catalog / D4 boundary.
- Host execution capability and native write mechanics -> Host/Execution Providers.

`semantic_service` must not become a second D5 and must not become a Host adapter.

## Package Boundary

Create a new independent Python package:

```text
platform/semantic_service/
  pyproject.toml
  src/semantic_service/
    __init__.py
    manifest.py
    providers.py
    registry.py
    environment.py
    service.py
    errors.py

tests/semantic_service/
```

The package targets Python 3.11 and follows the existing `src/` packaging pattern used by `platform/semantic_runtime`.

### Dependency direction

`semantic_service` SHALL NOT import `semantic_runtime`.

The packages meet through stable values at an integration boundary:

```text
SemanticEnvironment.environment_id
SemanticEnvironment.content_hash
        |
        v
D5 SemanticEnvironmentRef(environment_id, content_hash)
```

The adapter constructing the D5 ref is deliberately trivial. This avoids making semantic definitions depend on D5 implementation types and prevents a Semantic Service <-> D5 dependency cycle.

The same rule applies to assurance and claim evidence: the service contract uses provider-neutral values and a later D5 integration adapter converts them into D5 guarantees.

## Scope of the First PR

The first PR implements only:

1. immutable provider manifest/value contracts;
2. provider capability contracts;
3. provider registry with immutable-version rules;
4. namespace authority checks;
5. deterministic capability routing;
6. pinned `SemanticEnvironment` construction and immutable lookup;
7. deterministic machine-semantic hashing;
8. an in-memory immutable provider/environment metadata cache;
9. logical `SemanticService` query methods for vocabulary, mapping, validation, provider manifest, and environment lookup;
10. conformance and architecture tests.

## Explicit Non-Goals

The first PR does not implement:

- Semantic MCP server/client transport;
- IFC4.3 vocabulary data;
- DSP Core vocabulary data;
- Metro vocabulary/rules;
- enterprise A-WALL or other Host-native mappings;
- AutoCAD/Revit/Tekla extractors;
- `NormalizedDesignFact` / `NormalizedDesignFactBatch` ingestion;
- bulk `semantic.project_facts` remote APIs;
- D5 reconstruction changes;
- D3/D4 canonical action refactor;
- D6/D7 execution or governance behavior;
- database/distributed registry;
- automatic provider upgrade or a mutable `latest` semantic environment.

## Provider Manifest

### Required fields

`SemanticProviderManifest` is immutable and contains:

```text
provider_id
provider_type
version
content_hash
namespaces[]
capabilities[]
authority[]
compatibility[]
requires[]
```

`provider_type` is one of:

```text
STANDARD
CORE
DOMAIN
ENTERPRISE
```

`capabilities` is a set of:

```text
VOCABULARY
MAPPING
VALIDATION
PROJECTION
```

`requires[]` contains exact provider dependencies for this baseline:

```text
provider_id
version
```

Example:

```text
dsp.metro.semantic@3.2
requires buildingSMART.ifc43@4.3.2.0
```

Exact dependency versions are intentional. Constraint solving and floating ranges are unnecessary for the baseline and make environment reproducibility harder.

### Namespace authority

Authority is declared per namespace. The baseline distinguishes:

```text
AUTHORITATIVE
EXTENSION
```

`AUTHORITATIVE` means the provider owns canonical term meaning for that namespace inside an environment.

`EXTENSION` means the provider may contribute mapping/validation/domain extension behavior involving that namespace but cannot become the source of canonical vocabulary meaning for that namespace.

Example:

```text
buildingSMART.ifc43
  ifc -> AUTHORITATIVE

dsp.metro.semantic
  metro -> AUTHORITATIVE
  ifc -> EXTENSION
```

The first PR does not implement an overlay policy that rewrites authoritative term definitions.

### Immutable version rule

Within one registry:

```text
(provider_id, version) -> exactly one content_hash
```

Registering the same `(provider_id, version)` with a different `content_hash` fails closed.

Registering the identical manifest/provider again is idempotent.

A provider may expose multiple versions, but they remain separate immutable registrations.

## Machine-Semantic Hashing

Presentation text must not accidentally control semantic identity.

A deterministic `manifest_hash` is computed from machine-relevant manifest fields using canonical JSON with sorted keys/collections:

```text
provider_id
provider_type
version
content_hash
namespaces
authority
capabilities
compatibility
requires
```

Labels, human descriptions, localized prose, health state, network address, process identity, and MCP transport metadata are excluded.

The provider's declared `content_hash` remains mandatory. The service does not pretend it can recompute the internal contents of a remote future provider; provider conformance is responsible for changing `content_hash` whenever machine semantics change.

## Provider Capability Contracts

Providers do not implement one giant interface. All provider objects expose an immutable manifest, while capability-specific protocols remain separate.

### `SemanticVocabularyProvider`

Provides canonical vocabulary functions for namespaces for which it is authoritative:

```text
resolve_term(term_id)
describe_term(term_id, locale=None)
get_term_schema(term_id)
```

Returned values include provider provenance (`provider_id`, `version`, `content_hash`).

### `SemanticMappingProvider`

Provides deterministic mapping candidates:

```text
find_mappings(source_claim, target_namespace=None)
```

The service aggregates candidates; it does not silently choose one by LLM-style preference. Every result carries provider/mapping provenance and a stable mapping identifier.

### `SemanticValidationProvider`

Provides deterministic validation results:

```text
validate_claim(claim)
```

Providers may return applicable pass/fail findings or `NOT_APPLICABLE`. Findings carry provider/rule provenance.

### `SemanticProjectionProvider`

The capability name is frozen now because it is part of the Provider Manifest and Phase C architecture.

The first PR exports the projection capability contract as a marker tied to the provider manifest, but does **not** freeze a `project_facts()` payload signature. The concrete projection method is introduced together with `NormalizedDesignFactBatch` in Phase E so the service core does not invent a temporary fact DTO that immediately becomes legacy.

This is a deliberate phase boundary rather than an incomplete implementation.

## Semantic Claim Boundary

Vocabulary queries do not need D5 objects. Mapping and validation use a provider-neutral `SemanticClaim` aligned with Spec v0.6 section 17.3:

```text
subject
predicate
canonical_term_id
value
unit
assurance
provenance
evidence
provider_id
provider_version
```

The service treats `assurance` as a canonical string token from the Spec vocabulary in this PR. A later D5 integration adapter maps it to D5 `AssuranceLevel`. This keeps the dependency explicit without making Semantic Service import D5.

## SemanticProviderRegistry

`SemanticProviderRegistry` owns provider registration and immutable lookup. It does **not** own environment construction or storage.

Required operations:

```text
register(provider)
get(provider_id, version)
get_manifest(provider_id, version)
versions(provider_id)
providers_with_capability(capability)
```

The registry contains provider objects for in-process testing/initial operation, but registration semantics are independent of provider transport. A future `McpSemanticProviderAdapter` can implement the same capability protocols without changing registry consumers.

### Registration checks

Registration fails closed when:

- required manifest fields are empty/invalid;
- a capability claimed by the manifest is not implemented by the supplied provider object, except the PROJECTION marker behavior described above;
- `(provider_id, version)` is already bound to another `content_hash`;
- namespace declarations are malformed;
- an exact declared dependency is self-referential.

Dependency existence is checked when pinning an environment, not when registering an isolated provider version, so providers can be loaded in any order.

## SemanticEnvironment

`SemanticEnvironment` is the immutable interpretation environment used for planning/approval.

It contains a sorted tuple of `PinnedProvider` records. Each record contains:

```text
provider_id
provider_type
version
content_hash
manifest_hash
namespaces
capabilities
authority
compatibility
requires
```

The environment `content_hash` is computed from canonical JSON over the complete sorted pinned-provider records.

Therefore changing any machine-relevant item below changes the environment hash:

- selected provider version;
- provider content hash;
- namespace authority;
- capability set;
- compatibility declaration;
- dependency declaration.

Provider order supplied by callers does not change the hash.

### Environment identity

The baseline uses a content-addressed ID:

```text
environment_id = "sem-env:" + content_hash
```

The full hash is retained. The same pinned provider set yields the same environment ID/hash; a different machine-semantic environment cannot reuse the ID.

This prevents mutable aliases such as `production-latest` from entering PlanningSnapshot semantics.

## SemanticEnvironmentStore

`SemanticEnvironmentStore` owns pinning and immutable environment lookup. It depends on a `SemanticProviderRegistry`; the registry does not depend on the store.

Required operations:

```text
pin(selections, registry) -> SemanticEnvironment
get(environment_id) -> SemanticEnvironment
get_by_hash(content_hash) -> SemanticEnvironment
```

Environment creation requires explicit selections by `provider_id + version`. There is no planning API meaning "use latest".

For each selected provider, pinning verifies:

1. registration exists;
2. every exact `requires[]` dependency is also selected at the required version;
3. the dependency's registered version/hash is immutable;
4. no namespace has more than one `AUTHORITATIVE` provider.

Vocabulary authority is additionally checked at resolution time: the requested term namespace must have exactly one authoritative selected provider with `VOCABULARY` capability.

An `EXTENSION` provider may coexist with the authoritative owner of a namespace.

### Store immutability

The first PR provides an in-memory immutable store:

```text
content_hash -> SemanticEnvironment
environment_id -> SemanticEnvironment
```

Writing a different object under an occupied ID/hash fails closed.

The core does not implement disk persistence, distributed invalidation, TTLs, or automatic refresh. Those concerns belong to later adapters/deployment work.

## Routing Rules

### Vocabulary resolution

For a term such as:

```text
ifc:IfcWall
```

routing is:

```text
parse namespace `ifc`
-> load pinned environment
-> find exactly one AUTHORITATIVE selected provider for `ifc`
-> require VOCABULARY capability
-> call that provider only
-> return provider-provenanced result
```

There is no fallback to an extension provider when the authoritative provider is absent or fails.

### Mapping

`find_mappings()` calls all selected `MAPPING`-capable providers in deterministic `(provider_id, version)` order.

Results are aggregated and sorted by stable `(mapping_id, provider_id, provider_version)` keys. Candidates retain provenance; the service does not silently collapse semantic conflicts.

### Validation

`validate_claim()` calls all selected `VALIDATION`-capable providers in deterministic order. Providers may return `NOT_APPLICABLE`.

The service aggregates findings. It does not use majority voting and does not let a domain provider erase an authoritative standard failure.

A later policy layer may decide which findings gate a specific action, but Semantic Service preserves every finding with provenance.

## SemanticService Logical Contract

`SemanticService` composes one registry plus one environment store. Its initial surface is:

```text
resolve_term(term_id, environment_id)
describe_term(term_id, environment_id, locale=None)
get_term_schema(term_id, environment_id)
validate_claim(claim, environment_id)
find_mappings(source_claim, environment_id, target_namespace=None)
get_provider_manifest(provider_id, version)
get_environment(environment_id)
```

Every machine-semantic query that can vary by provider version requires an explicit pinned `environment_id`.

This intentionally tightens the Spec's suggested signatures by making the pinned environment explicit instead of relying on an implicit process-wide default.

The service does not expose `project_facts` in this PR.

## MCP Boundary for the Next PR

The next PR may expose a thin MCP adapter corresponding to:

```text
semantic.resolve_term
semantic.describe_term
semantic.get_term_schema
semantic.validate_claim
semantic.find_mappings
semantic.get_provider_manifest
semantic.get_environment
```

The MCP layer translates request/response payloads to the logical service contract and owns protocol errors/auth/routing concerns. It does not implement semantic authority, registry conflict resolution, or provider meaning.

The core package must remain usable and fully testable without MCP installed.

## Data Flow

### Term lookup

```text
D5/Orchestrator integration
  -> SemanticService.resolve_term(term, env_id)
  -> SemanticEnvironmentStore loads immutable environment
  -> SemanticProviderRegistry resolves selected provider object
  -> service enforces namespace authority/capability
  -> provider resolves term
  -> service returns term + provider provenance
```

### Mapping/validation

```text
provider-neutral SemanticClaim
  -> SemanticService
  -> deterministic capability fan-out inside pinned environment
  -> provider findings/candidates
  -> aggregate without silent overwrite
  -> caller/D5 integration decides how claims become projection evidence
```

### Snapshot binding

```text
SemanticEnvironmentStore pins environment
  -> SemanticEnvironment(environment_id, content_hash)
  -> integration constructs D5 SemanticEnvironmentRef
  -> D5 ReconstructionResult / PlanningSnapshot binds the ref
```

No Provider implementation ID is stored as Host identity.

## Error Model

The core uses typed fail-closed domain errors:

```text
SemanticServiceError
  ManifestValidationError
  ProviderRegistrationConflictError
  ProviderNotFoundError
  ProviderCapabilityError
  ProviderDependencyError
  NamespaceAuthorityError
  EnvironmentIntegrityError
  EnvironmentNotFoundError
  TermResolutionError
```

Rules:

- manifest/version/hash conflicts never auto-replace existing registration;
- missing dependencies prevent environment pinning;
- dual authoritative namespace ownership prevents environment pinning;
- missing authoritative vocabulary provider prevents canonical term resolution;
- provider execution exceptions are wrapped with provider provenance and never converted into guessed semantic results;
- failed remote behavior is handled by the later adapter, not by weakening domain invariants.

## Security and Trust Boundary

Semantic Providers are untrusted implementations until certified by policy/conformance.

The core preserves:

- immutable version/hash identity;
- namespace authority;
- exact dependencies;
- deterministic environment hash;
- result provenance;
- fail-closed conflicts.

The first PR does not implement trust scoring or Gateway authorization. Those may filter which registered versions are selectable before environment pinning, but they must not change the meaning of an already-pinned environment.

## Testing Strategy

The first PR is test-driven and adds `tests/semantic_service/`.

### Manifest / registration

- identical registration is idempotent;
- same `(provider_id, version)` with another `content_hash` fails;
- claimed capabilities match implemented capability protocols;
- exact self-dependency fails;
- multiple versions of one provider coexist.

### Authority

- one authoritative provider owns `ifc` in an environment;
- two authoritative `ifc` providers fail pinning;
- an `EXTENSION` provider may coexist with the authoritative owner;
- vocabulary resolution never falls back to an extension provider.

### Environment

- provider input order does not affect environment hash;
- changing version changes environment hash;
- changing provider content hash changes environment hash;
- changing authority/capabilities/compatibility/dependencies changes manifest/environment hash;
- identical pinned sets create identical content-addressed environment IDs;
- missing exact dependency fails pinning;
- environment store refuses mutable rebinding.

### Routing

- vocabulary lookup uses only namespace authority;
- mapping fan-out order and output order are deterministic;
- validation aggregates findings without majority voting or overwrite;
- all outputs retain provider provenance.

### Architecture

`platform/semantic_service/src/semantic_service` must contain no imports/references that couple the core to:

```text
Autodesk
Revit
AutoCAD
Tekla
semantic_runtime
MCP transport/server implementation
Ifc43Provider
MetroProvider
enterprise layer/family/category mapping
```

The package may use neutral term IDs such as `ifc:IfcWall` in tests/examples, but no IFC vocabulary implementation belongs in core.

## CI

Add a dedicated Semantic Service workflow or extend the existing Python verification workflow so CI executes:

```text
pytest -q tests/semantic_service
pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime tests/semantic_service
```

The implementation plan should choose the smallest CI change that preserves existing D5 verification and adds the new package to editable installs.

## PR / Branch Strategy

The branch is:

```text
feat/semantic-service-core
```

It is stacked from the current D5 PR #5 head because `main` does not yet contain the D5 v0.6 baseline. A draft Semantic Service PR should initially target `feat/semantic-runtime` so its diff contains only Semantic Service work.

After PR #5 merges, retarget the Semantic Service PR to `main` and re-run complete merge-ref verification before marking it ready for review.

## Follow-up Boundaries

After this core is frozen:

1. **Semantic MCP Adapter** — thin remote protocol surface over `SemanticService`.
2. **DSP Core + IFC4.3 Providers** — real authoritative vocabulary/validation/projection implementations.
3. **Metro Provider** — domain extensions and Metro rules depending on the pinned IFC provider.
4. **Normalized ingestion / enterprise proof** — `NormalizedDesignFactBatch`, Host extractors, enterprise mapping provider, and the A-WALL -> `ifc:IfcWall` proof without D5 changes.
5. **D3/D4 Canonical Action Contract** remains a separate workstream and must not leak into Semantic Service Core.

## Acceptance Boundary

The Semantic Service Core baseline is complete when all of the following are true:

- provider versions are immutable in the registry;
- namespace authority conflicts fail closed;
- registry and environment-store ownership are separate;
- routing is deterministic inside one pinned environment;
- the same provider set yields the same environment hash regardless of input order;
- machine-semantic manifest changes alter environment identity;
- the service resolves vocabulary, mapping, and validation through capability contracts without knowledge of concrete IFC/Metro/Enterprise classes;
- D5 can bind `environment_id + content_hash` without Semantic Service importing D5;
- no MCP transport or Host-native mapping exists in the core package;
- full existing Python regression remains green apart from existing live-Host gated tests.

No unresolved implementation decisions are required before writing the implementation plan.