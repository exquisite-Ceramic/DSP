# IFC4.3 Standard Semantic Provider Design

## Status

Approved in architecture discussion on 2026-08-28. This document defines the design boundary for Spec v0.6 Phase D, step 16: the IFC4.3 Standard Semantic Provider.

Implementation MUST NOT begin until this written design has been reviewed and approved by the user. After approval, the next step is a separate implementation plan produced with the project planning workflow.

Where this design specifies implementation details not frozen by Spec v0.6, those details are PR #9 implementation decisions and MUST NOT be interpreted as amendments to the main Spec.

## Goal

Add an independent reference Semantic Provider for the official IFC4.3 standard semantics used by DSP.

The provider SHALL be the canonical `ifc:*` authority for the pinned standard release:

```text
provider_id: buildingSMART.ifc43
provider_type: STANDARD
version: "4.3.2.0"
namespace: ifc
schema: IFC4X3_ADD2
```

It gives Semantic Service a deterministic, pinned interpretation of IFC entity, inheritance, attribute, enum, select, defined type, relationship, official Pset/Qto, datatype, and claim-level Schema legality semantics without moving IFC implementation knowledge into `semantic_service`, `semantic_runtime`, `semantic_mcp`, D5, or Host adapters.

The intended layering remains:

```text
Host native facts
    ↓
NormalizedDesignFact                Phase E
    ↓
Canonical IFC / DSP semantics       IFC4.3 Provider + DSP Core Provider
    ↓
Metro / Enterprise semantics        Metro / Enterprise Providers
```

The IFC Provider defines standard state semantics. It does not define DSP Canonical Actions such as `wall.thickness.set.v1`.

## Architectural Classification

This is a new reference-provider subsystem and therefore an architectural change. The provider is isolated behind the already-frozen Semantic Provider contracts introduced in Phase C.

The implementation MUST preserve this dependency direction:

```text
pinned IfcOpenShell
      ↓
IFC4.3 Provider
      ↓
Semantic Service provider contracts
```

The following dependency directions are forbidden:

```text
semantic_service  → IfcOpenShell
semantic_runtime  → IfcOpenShell
semantic_mcp      → IfcOpenShell
D5                → concrete IFC Provider implementation
Host adapters     → concrete IFC Provider implementation through platform core
```

Platform consumers continue to use `SemanticService` and a pinned `SemanticEnvironment`; they do not import the concrete IFC provider.

## Source of Truth

### Machine-semantic authority

The authoritative semantic target is:

```text
IFC4X3_ADD2 / IFC 4.3.2.0
```

The provider MUST reject any runtime schema source whose identifier or semantic version does not exactly match the pinned release.

A release label such as “IFC4.3” is insufficient. The provider is defined against the exact standard version `4.3.2.0`.

### Implementation engine

The recommended implementation engine is a pinned IfcOpenShell package, initially:

```text
ifcopenshell==0.8.5
```

IfcOpenShell is an implementation/inspection engine, not the semantic authority. The provider MUST normalize the reflected IFC schema into its own immutable records before serving queries.

Changing the parsing/reflection library without changing the normalized machine semantics MUST NOT change the provider semantic content hash.

The source loader MUST NOT silently substitute another schema/Pset/Qto release or a floating “latest” template set. If the pinned implementation source cannot provide a reproducible IFC4X3_ADD2-compatible schema plus official Pset/Qto corpus, implementation MUST stop and surface the source compatibility problem rather than weaken the provider version claim.

### Metro V3.2 source boundary

The uploaded source:

```text
IFC4.3地铁BIM数据标准_V3.2_构件属性增强合并版.md
```

is an important downstream domain standard, but it is not an IFC standard authority.

For PR #9 it SHALL be used only as a reference/conformance corpus. It provides useful positive and negative IFC examples, such as legal railway/building/MEP terms and prohibited/non-existent names.

It MUST NOT determine IFC truth. If a Metro assertion conflicts with IFC4X3_ADD2, the official IFC Schema wins.

The document SHALL become a primary semantic input for the later Metro Semantic Provider, which owns Metro domain mappings, `PsetProj_*` / `QtoProj_*`, field status such as P-M/P-C/P-R, IDS requirements, and Metro engineering rules.

The IFC Provider MUST NOT compile or vendor the Metro document into its machine-semantic catalog.

## Provider Manifest

The manifest is frozen as:

```text
provider_id = buildingSMART.ifc43
provider_type = STANDARD
version = 4.3.2.0
namespaces = [ifc]
authority = ifc -> AUTHORITATIVE
capabilities = VOCABULARY, VALIDATION, PROJECTION
requires = []
```

### Capability interpretation

#### VOCABULARY

Fully implemented in PR #9.

The provider resolves and describes standard IFC terms and returns term schemas with exact provider provenance.

#### VALIDATION

Implemented only at the claim-level boundary supported by the existing `SemanticClaim` contract.

PR #9 MUST NOT claim complete IFC file/model validation.

#### PROJECTION

Declared as the existing marker capability only.

The Phase C `SemanticProjectionProvider` protocol deliberately has no frozen `project_facts()` signature yet. PR #9 does not invent one. The actual fact-projection contract is introduced with `NormalizedDesignFact` in Phase E.

#### MAPPING

Not declared.

The standard IFC Provider does not map Host-native facts or Metro concepts to IFC terms. Enterprise/Metro mapping providers own those responsibilities.

## Authoritative Scope

The `ifc` namespace authority covers the official IFC4X3_ADD2 meaning of:

- entities;
- inheritance;
- entity attributes;
- relationships;
- enumerations and enum literals;
- selects;
- defined/simple types;
- IFC datatypes;
- official Pset definitions;
- official Qto definitions;
- official Pset/Qto members;
- Schema-level legality representable at the current claim boundary.

Metro and Enterprise providers may use `ifc` as an extension/mapping/validation target but MUST NOT redefine canonical `ifc:*` meaning.

An environment containing a second `AUTHORITATIVE` owner for namespace `ifc` MUST fail closed through the existing Semantic Environment authority rules.

## Canonical Term Identity

### Top-level declarations

Top-level IFC declarations use the standard name directly after the namespace:

```text
ifc:IfcWall
ifc:IfcDoor
ifc:IfcAlignment
ifc:IfcRelAggregates
ifc:IfcWallTypeEnum
ifc:IfcLengthMeasure
```

The namespace plus standard term name plus pinned provider version forms the canonical identity.

Descriptions are presentation metadata and do not define identity.

### Official property and quantity sets

Official buildingSMART sets use their standard names:

```text
ifc:Pset_WallCommon
ifc:Qto_WallBaseQuantities
```

Project sets such as `PsetProj_WallDesign` are not IFC terms and MUST NOT resolve through this provider.

### Direct members

Direct entity attributes, Pset properties, and Qto quantities use owner-qualified stable identities:

```text
ifc:IfcWall.PredefinedType
ifc:Pset_WallCommon.FireRating
ifc:Qto_WallBaseQuantities.Width
```

### Enum literals

Enum literals also use owner-qualified member identities:

```text
ifc:IfcWallTypeEnum.SOLIDWALL
ifc:IfcRailwayPartTypeEnum.TRACK
```

The enum term schema lists these literal identities deterministically. A literal MUST NOT exist as an unqualified global IFC term because identical literal text may occur in multiple enums.

Select members remain references to their canonical declaration identities rather than duplicate terms owned by the select.

### Inherited attributes

An inherited field keeps the canonical identity of the declaration that owns it.

Example:

```text
ifc:IfcRoot.Name
```

is the canonical identity of `Name`; `IfcWall` schema output may reference that inherited member, but the provider MUST NOT manufacture duplicate identities such as `ifc:IfcWall.Name` merely because the inherited attribute is visible on `IfcWall`.

This avoids identity duplication across the IFC inheritance tree.

### Exact lookup

Lookup is exact and deterministic.

The provider MUST NOT:

- case-fold IFC names;
- fuzzy-match invalid terms;
- silently substitute similar entities;
- map invalid terms to Metro-approved alternatives;
- normalize `IfcTunnel` into another legal entity.

Unknown terms fail deterministically.

## Immutable Normalized Catalog

### Build phase

Provider construction performs a one-time normalization pipeline:

```text
pinned IfcOpenShell schema
        ↓ exact source version check
schema declarations + official Pset/Qto templates
        ↓ normalization
immutable provider records
        ↓ canonical index + content hash
runtime provider
```

The runtime query path uses only the immutable catalog/index.

No network request is permitted during term resolution, description, schema lookup, or claim validation.

### Catalog content

The catalog SHALL normalize at least:

- schema identifier and version;
- declaration kind and name;
- entity abstract state;
- direct supertype;
- direct attributes;
- attribute type expressions;
- optionality;
- aggregation kind and cardinality where exposed by the source;
- enum literals as owner-qualified members;
- select members as declaration references;
- defined-type underlying types;
- official Pset/Qto names;
- official Pset/Qto applicability metadata available from the pinned source;
- official Pset property / Qto quantity names;
- property/quantity data kinds and relevant enum/unit constraints exposed by the source.

Relationships are IFC entities and are normalized through the same declaration model rather than a separate hand-maintained relationship table.

### Runtime cache boundary

The provider may use process-local memoization so multiple provider instances do not repeat expensive reflection, provided the memoized object is immutable and keyed by the exact pinned source identity.

It MUST NOT introduce a new mutable platform-wide semantic cache. Semantic Service continues to own provider registration and Semantic Environment storage.

## Deterministic Semantic Hashing

The provider `content_hash` represents normalized machine semantics, not implementation artifacts.

### Included in `content_hash`

The canonical hash payload SHALL include the normalized machine-relevant catalog, including:

- exact schema identifier/version;
- declaration kind/name;
- inheritance;
- abstract state;
- attribute name/type/optionality/aggregation/cardinality;
- owner-qualified enum literal identities;
- select member declaration identities;
- defined type semantics;
- official Pset/Qto identity;
- official Pset/Qto applicability;
- official Pset/Qto member machine types and relevant constraints.

### Excluded from `content_hash`

The following are presentation or implementation metadata and MUST NOT affect semantic content identity:

- human descriptions;
- localized prose;
- examples;
- documentation URLs;
- Metro usage notes;
- Python object representations;
- memory addresses;
- source iteration order;
- IfcOpenShell package version by itself.

The IfcOpenShell version is still pinned as a reproducibility/dependency control, but semantic identity comes from the normalized standard semantics.

### Canonical encoding

Use the same semantic-hashing discipline already proven by the DSP Core provider:

```text
canonical normalized values
→ sorted keys / deterministic collections
→ compact JSON
→ UTF-8
→ SHA-256 lowercase hex
```

The implementation MAY reuse a shared future utility only if doing so does not create a concrete-provider dependency between providers. For PR #9, duplication of the tiny canonical hash utility is preferable to coupling the IFC provider to `dsp_core_semantic_provider`.

### Golden content-hash lock

The first successful implementation SHALL record the expected `content_hash` for the exact normalized `buildingSMART.ifc43@4.3.2.0` catalog as a golden regression value in the IFC provider test/constant boundary.

Every focused CI run MUST reconstruct the catalog from the pinned source and assert the resulting hash equals that expected value.

Changing the golden hash requires an explicit machine-semantic review. A dependency, normalization, or source-corpus change MUST NOT silently update the expected value.

This lock makes a fresh process/install detect semantic drift even when there is no previously populated in-memory registry to compare against.

### Immutable version behavior

Within Semantic Service:

```text
(buildingSMART.ifc43, 4.3.2.0) -> exactly one content_hash
```

If a code/library change causes the same provider ID/version to emit different machine semantics, the golden hash regression MUST fail before release, and registration against an already loaded conflicting version MUST expose the drift through the existing immutable-version conflict behavior. It MUST NOT silently replace the previously registered meaning.

## Vocabulary Result Semantics

### `resolve_term`

Returns exact term identity, kind, and pinned provider provenance.

Expected kinds may include provider-defined stable strings such as:

```text
ENTITY
RELATIONSHIP
ENUM
ENUM_LITERAL
SELECT
DEFINED_TYPE
ATTRIBUTE
PSET
PSET_PROPERTY
QTO
QTO_QUANTITY
```

The design freezes the semantic distinction, not a requirement to change Semantic Service's DTO enum surface; the current `ResolvedTerm.kind` is a string and can carry these values without a platform contract change.

### `describe_term`

Description text is presentation metadata.

The initial provider MAY use documentation text available from the pinned implementation source. Failure to provide localized text MUST NOT change canonical identity or content hash.

Unsupported locales may deterministically fall back to the default description behavior rather than invent translated standard semantics.

### `get_term_schema`

Returns a machine-readable schema map appropriate to the term kind.

Examples:

- entity: supertype, abstract flag, direct members, inherited-member references;
- attribute: owner, declared type, optionality, aggregation/cardinality;
- enum: owner-qualified literal references;
- enum literal: owner enum and literal value;
- select: member declaration references;
- defined type: underlying type;
- Pset/Qto: applicability and member references;
- Pset/Qto member: data/quantity type and relevant constraints.

The schema output MUST be deterministic and composed only from the immutable catalog.

## Claim-Level Validation Boundary

`SemanticValidationProvider.validate_claim()` is intentionally narrow because the current provider-neutral `SemanticClaim` is not a complete IFC instance graph.

### In scope

Where the supplied claim provides sufficient information, validation may check:

- canonical term existence;
- expected term/member kind;
- whether an attribute/Pset/Qto member exists;
- enum literal legality;
- basic Python/value compatibility with the declared IFC datatype;
- obvious standard unit/type compatibility representable from the claim;
- direct schema constraints that require no missing model context.

The provider SHALL return deterministic `ValidationFinding` results with stable rule IDs and exact provider provenance.

### Out of scope

PR #9 MUST NOT advertise complete validation of:

- an IFC STEP file;
- a complete IFC instance graph;
- EXPRESS WHERE rules requiring graph/context evaluation;
- inverse relationship consistency;
- model-level relationship cardinality;
- complete `IfcUnitAssignment` semantics where the claim lacks model context;
- geometry validity;
- closed solids;
- clashes;
- clearance;
- Alignment continuity;
- georeferencing consistency across a file;
- IDS information requirements;
- Metro P-M/P-C/P-R rules;
- Metro engineering rules.

Those checks require later file/model, IDS, geometry, or domain-specific contracts. The provider MUST fail closed or return `NOT_APPLICABLE` when the claim lacks the context needed to decide a standard rule. It MUST NOT guess.

## Error Model

Provider-local construction/runtime errors are separate from Semantic Service domain errors.

Recommended local hierarchy:

```text
Ifc43ProviderError
  Ifc43SourceVersionError
  Ifc43CatalogBuildError
  Ifc43TermNotFoundError
  Ifc43ValidationError
```

`Ifc43ValidationError` is for validator execution/configuration failure; a semantic claim that violates a standard rule is represented as a normal `ValidationFinding(status=FAIL)`, not as an exception.

The provider does not add new public Semantic Service errors. Existing Semantic Service behavior remains responsible for:

- manifest validity;
- provider registration conflicts;
- missing providers;
- claimed capability mismatch;
- namespace authority conflicts;
- environment integrity;
- term-resolution wrapping.

### Fail-closed source version rule

Construction MUST fail if the underlying schema is not exactly `IFC4X3_ADD2 / 4.3.2.0`.

There is no best-effort fallback to another IFC4.3 patch/addendum.

## Metro V3.2 Conformance Corpus

The Metro V3.2 document is useful for proving that the IFC provider recognizes the standard layer correctly while refusing domain-only or non-existent IFC names.

Representative positive cases SHALL include terms exercised by the Metro source, for example:

```text
IfcRailway
IfcRailwayPart
IfcAlignment
IfcLinearPlacement
IfcRail
IfcTrackElement
IfcMechanicalFastener
IfcWall
IfcSlab
IfcBeam
IfcColumn
IfcOpeningElement
IfcBorehole
IfcGeomodel
IfcGeotechnicalStratum
IfcDistributionSystem
IfcDistributionPort
Pset_WallCommon
Qto_WallBaseQuantities
Pset_Stationing
```

Representative negative IFC entity cases SHALL include names the Metro source explicitly says do not exist in IFC4.3, for example:

```text
IfcTunnel
IfcTunnelPart
IfcTrack
IfcSprinkler
IfcFanCoilUnit
IfcPrecastConcreteElement
```

A negative case proves the IFC provider rejects the name. It does not implement the Metro replacement mapping. The later Metro provider owns mappings such as tunnel/domain concepts to legal IFC4.3 expressions.

The conformance suite SHOULD also encode a small set of official IFC4.3.2 expected Pset/Qto/entity/member facts independently of runtime introspection. Those reference assertions are tests, not a second runtime catalog, and protect against an implementation source that is reproducible but semantically mismatched with the claimed release.

## Package and File Boundary

Create a new independent package:

```text
providers/semantics/ifc43/
  pyproject.toml
  README.md
  src/ifc43_semantic_provider/
    __init__.py
    source.py
    model.py
    normalization.py
    catalog.py
    hashing.py
    provider.py
    validation.py
```

Recommended test boundary:

```text
tests/semantic_providers/ifc43/
  test_source_version.py
  test_catalog.py
  test_term_identity.py
  test_pset_qto.py
  test_hashing.py
  test_provider_manifest.py
  test_validation.py
  test_service_integration.py
  test_mcp_integration.py
  test_metro_reference_cases.py
  test_architecture.py
```

A focused CI workflow may be added under:

```text
.github/workflows/ifc43-semantic-provider.yml
```

The exact test-file split is an implementation-plan detail; the architectural boundary is frozen here.

## Dependency Policy

The package targets Python 3.11 and depends on:

```text
semantic-service
ifcopenshell==0.8.5
```

The Semantic Service dependency follows the same provider-package direction as the DSP Core provider.

IfcOpenShell MUST NOT be added to Semantic Service, Semantic MCP, or D5 package dependencies as part of PR #9.

If the pinned IfcOpenShell distribution cannot be installed in supported CI/runtime targets, implementation MUST stop and surface that as a dependency/feasibility problem rather than weakening the schema-version or reproducibility rules.

## Semantic Service Integration

The provider uses existing Phase C contracts without changing them.

Expected integration flow:

```text
registry.register(IFC43_PROVIDER)
        ↓
SemanticEnvironmentStore.pin([
  dsp.core@1.0,
  buildingSMART.ifc43@4.3.2.0,
])
        ↓
SemanticService.resolve_term("ifc:IfcWall", environment_id)
        ↓
exact authoritative IFC provider
```

The provider MUST be usable through the existing Semantic MCP adapter without adding IFC-specific MCP tools.

The seven existing Semantic MCP tools remain unchanged.

## Architecture Invariants

PR #9 SHALL add architecture/conformance tests proving at least:

1. `ifc:*` is authoritative only through the pinned IFC Provider.
2. A second authoritative `ifc` provider makes environment pinning fail closed.
3. Metro/Enterprise extension providers cannot replace IFC canonical vocabulary authority.
4. `semantic_service` does not import IfcOpenShell.
5. `semantic_runtime` does not import IfcOpenShell or the concrete IFC provider.
6. `semantic_mcp` does not import IfcOpenShell or the concrete IFC provider.
7. the IFC provider does not import Host-native AutoCAD/Revit/Tekla packages.
8. the IFC provider does not import Metro implementation packages.
9. no Host-specific mapping is embedded in the IFC provider.
10. no DSP Canonical Action is owned by the IFC provider.
11. no runtime network lookup is required for semantic resolution.
12. machine-semantic hash excludes presentation-only text.
13. the expected IFC4.3.2.0 golden catalog hash cannot change silently.

## Conformance Test Matrix

PR #9 SHALL satisfy the main Spec's Semantic Provider conformance requirements as follows:

| Conformance item | IFC4.3 Provider requirement |
|---|---|
| manifest validity | exact STANDARD manifest for `buildingSMART.ifc43@4.3.2.0` |
| namespace ownership | `ifc -> AUTHORITATIVE` |
| version/content hash stability | deterministic + golden hash; same ID/version with changed machine semantics fails closed |
| term resolution | entity/type/enum/enum-literal/select/relationship/Pset/Qto/member cases |
| schema output | inheritance, members, enum/select/type, Pset/Qto metadata |
| mapping determinism | N/A because MAPPING is not declared |
| validation determinism | claim-level legality/type/enum findings are deterministic |
| conflict behavior | immutable provider version and authority conflicts fail closed |
| authority enforcement | extension providers cannot own canonical `ifc:*` meaning |
| environment pinning | exact IFC version participates in deterministic SemanticEnvironment identity |

### Required reference cases

Tests SHOULD include at minimum representative cases from these semantic families:

- building element: `IfcWall`;
- opening/relationship: `IfcOpeningElement`, `IfcRelVoidsElement`;
- railway: `IfcRailway`, `IfcRailwayPart`, `IfcRail`, `IfcTrackElement`;
- alignment/linear placement: `IfcAlignment`, `IfcLinearPlacement`;
- geotechnical: `IfcBorehole`, `IfcGeotechnicalStratum`;
- MEP/system: `IfcDistributionSystem`, `IfcDistributionPort`;
- enum and owner-qualified enum literal;
- invalid enum literal;
- defined datatype;
- official `Pset_*`;
- official `Qto_*`;
- inherited attribute identity;
- known non-existent IFC entity names from the Metro corpus.

## TDD and Verification Requirement

Implementation MUST follow RED → GREEN TDD.

Before implementation completion is claimed, verification MUST include:

- focused IFC provider tests;
- full relevant repository regression tests;
- Semantic Service integration tests;
- real existing Semantic MCP client integration tests;
- architecture import/boundary tests;
- Metro reference corpus positive/negative cases;
- deterministic and golden content-hash tests;
- source-version mismatch failure test;
- immutable same-version/different-content conflict test.

Live Host integration tests may remain skipped under their existing explicit environment guard; PR #9 itself MUST NOT require AutoCAD/Revit/Tekla to run.

## Explicit Non-Goals

PR #9 does not implement:

- Metro Semantic Provider;
- `metro:*` vocabulary;
- `PsetProj_*` / `QtoProj_*` semantics;
- Metro P-M/P-C/P-R field rules;
- Metro IDS requirements;
- Metro tunnel/clearance/PSD/MEP mapping policy;
- Enterprise A-WALL or other Host-native mapping;
- Host-native fact extraction;
- `NormalizedDesignFact` or `NormalizedDesignFactBatch`;
- `project_facts()` / concrete PROJECTION payloads;
- D5 reconstruction changes;
- full IFC STEP file ingestion;
- complete IFC file validation;
- geometry engine integration;
- Alignment mathematical continuity validation;
- clashes or clearance analysis;
- georeferencing file-level validation;
- D4 Canonical Action changes;
- D6 slot binding;
- D7 execution/governance behavior;
- Host execution behavior;
- new IFC-specific MCP tools;
- changes to the stable Semantic MCP seven-tool surface;
- bundling the full buildingSMART standard corpus into the repository;
- bundling the Metro V3.2 document into the provider package.

## Implementation Sequence Relationship

This provider is Phase D step 16:

```text
15. DSP Core Provider             PR #8, merged
16. IFC4.3 Provider               PR #9, this design
17. Metro Semantic Provider       next
```

Phase E ingestion and progressive mapping work starts only after the reference-provider layer is in place.

The intended provider authority chain is:

```text
buildingSMART IFC4X3_ADD2
          │ AUTHORITATIVE ifc:*
          ▼
IFC4.3 Provider
          │ exact pinned dependency / canonical target
          ▼
Metro Semantic Provider
          │ owns metro:* and Metro domain policy
          ▼
Enterprise/project providers
```

Metro and Enterprise layers may extend, map to, and validate against IFC, but they cannot redefine the official canonical meaning of `ifc:*` terms.

## Acceptance Criteria

The design is implemented correctly when all of the following are true:

1. `buildingSMART.ifc43@4.3.2.0` registers as the sole authoritative `ifc` provider in a valid environment.
2. the provider refuses a non-`IFC4X3_ADD2 / 4.3.2.0` source and does not fall back to floating Pset/Qto semantics.
3. standard IFC entities, relationships, datatypes, enums, enum literals, Psets, Qtos, and members resolve through stable canonical identities.
4. enum literals use owner-qualified identities and inherited attributes preserve declaration-owner canonical identity.
5. known non-existent IFC entity names fail deterministically and are not auto-mapped.
6. the provider emits deterministic term schemas from an immutable normalized catalog.
7. the provider's content hash is stable under iteration/presentation changes, changes when machine semantics change, and is locked by a golden regression value.
8. claim-level standard validation is deterministic and explicitly returns N/A when required model context is absent.
9. the provider does not claim MAPPING and does not implement Metro/Host mapping logic.
10. PROJECTION remains marker-only until Phase E.
11. the existing Semantic Service and Semantic MCP public contracts remain unchanged.
12. Metro V3.2 is used only as PR #9 conformance/reference input, not IFC authority.
13. architecture tests prove no concrete IFC dependency leaks into platform core, D5, Semantic MCP, or Host adapters.
14. focused and repository regression verification pass before PR #9 is marked ready for review.