# Metro Semantic Provider Design

## Status

Approved section-by-section in architecture discussion on 2026-08-28. This document defines the design boundary for Spec v0.6 Phase D, step 17: the Metro Semantic Provider.

Implementation MUST NOT begin until this written design has been reviewed and approved by the user. After approval, the next step is a separate implementation plan produced with the project planning workflow.

Where this design specifies implementation details not frozen by Spec v0.6, those details are PR #10 implementation decisions and MUST NOT be interpreted as amendments to the main Spec.

## Goal

Add an independent Metro DOMAIN Semantic Provider for the Metro V3.2 semantic baseline on top of the already-pinned IFC4.3 standard semantics.

The provider identity is:

```text
provider_id: dsp.metro.semantic
provider_type: DOMAIN
version: "3.2"
```

Its responsibility is to answer:

```text
How does the Metro domain use legal IFC4.3 semantics?
```

It does not answer:

```text
What is legal IFC4.3?
```

That remains the responsibility of:

```text
buildingSMART.ifc43@4.3.2.0
```

It also does not answer:

```text
What did this specific project finally choose for an unfrozen design decision?
```

Project-specific BEP / IDS / enterprise or project provider layers own those choices after they are explicitly frozen.

The intended layering is:

```text
Host native facts
    ↓
NormalizedDesignFact                     Phase E
    ↓
IFC4.3 + DSP Core canonical semantics    STANDARD / CORE
    ↓
Metro semantic interpretation            DOMAIN
    ↓
Project / enterprise frozen decisions    later layer
```

PR #10 must preserve the distinction between standard semantics, domain semantics, and project decisions.

## Architectural Classification

This is a new reference-provider subsystem and therefore an architectural change.

The provider is isolated behind the provider-neutral Semantic Service contracts already frozen in Phase C. PR #10 MUST NOT change Semantic Service DTOs merely to accommodate Metro-specific metadata.

The desired production dependency direction is:

```text
pinned Metro machine source
        ↓
Metro Provider
        ↓
Semantic Service provider contracts
```

The exact IFC dependency is expressed through the provider manifest and Semantic Environment:

```text
dsp.metro.semantic@3.2
    requires
buildingSMART.ifc43@4.3.2.0
```

The following concrete dependency directions are forbidden:

```text
Metro Provider       → ifc43_semantic_provider implementation
semantic_service     → Metro Provider implementation
semantic_runtime     → Metro Provider implementation
semantic_mcp         → Metro Provider implementation
D5                   → Metro Provider implementation
Host adapters        → Metro Provider implementation through platform core
```

Platform consumers continue to use `SemanticService` and a pinned `SemanticEnvironment`; they do not import the concrete Metro provider.

## Source of Truth

### Human semantic source

The primary human-reviewed domain source for PR #10 is:

```text
IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版
```

Its target standard schema is:

```text
IFC4X3_ADD2 / IFC 4.3.2.0
```

The source contains multiple kinds of material and PR #10 MUST preserve their different normative strength:

- Metro domain vocabulary;
- legal IFC usage guidance;
- project-extension `PsetProj_*` / `QtoProj_*` data dictionary material;
- field requirement levels such as P-M / P-C / P-R;
- prohibited or invalid IFC usage;
- IDS-oriented requirements;
- recommended mappings;
- examples;
- project decisions that must be explicitly frozen;
- geometry / engineering validation rules that require more context than one semantic claim.

The source document is not itself parsed at runtime.

### IFC authority boundary

If a Metro source statement conflicts with the pinned formal IFC4X3_ADD2 semantics, the IFC standard provider wins.

Metro cannot redefine standard IFC entities, attributes, enums, Pset/Qto terms, datatype semantics, or schema legality.

The authority order remains:

```text
1. IFC4X3_ADD2 Schema legality
2. IFC official entity / Pset / Qto semantics
3. Metro domain mappings and PsetProj/QtoProj semantics
4. Metro IDS requirements
5. Metro project-specific validation rules
```

### Pinned machine source

PR #10 SHALL create a checked-in, versioned machine source, recommended as:

```text
providers/semantics/metro_v32/data/metro_v3_2.yaml
```

The machine source is a reviewed representation of the Metro semantics selected from the V3.2 human source.

Runtime behavior is:

```text
checked-in metro_v3_2.yaml
        ↓
structural validation
        ↓
semantic consistency validation
        ↓
normalization
        ↓
immutable MetroCatalog
        ↓
content-hash verification
        ↓
Metro Provider
```

Runtime MUST NOT parse the Markdown source, scrape documentation, fetch live network resources, or infer rules from prose.

### Source-document digest

The implementation SHALL compute and freeze a SHA-256 digest of the exact V3.2 source document used to produce the reviewed machine source.

The digest is provenance evidence, not provider semantic identity.

Therefore:

```text
source_document_sha256
    = exact human source bytes

content_hash
    = normalized machine semantics exposed by the provider
```

A prose or formatting-only source change MAY change the source-document digest without changing `content_hash`.

A machine-semantic change MUST change `content_hash`.

The concrete source digest is an implementation artifact and is not a main-Spec architecture invariant.

## Normative Classification

Every machine record whose meaning depends on the Metro source's normative strength MUST carry a structured classification rather than relying on natural-language wording.

The recommended classification set is:

```text
NORMATIVE
PROJECT_EXTENSION_DRAFT
RECOMMENDED
EXAMPLE
DECISION_OPTION
PROHIBITED
```

The implementation MAY encode these as strings or an internal enum, but their semantic distinction is required.

### Meaning of classifications

`NORMATIVE` means the Metro V3.2 baseline gives an unambiguous machine-relevant domain rule that PR #10 may enforce within the available provider contract.

`PROJECT_EXTENSION_DRAFT` means the source defines or recommends project extension semantics such as `PsetProj_*` data structures, but formal project registration / IDS approval remains a project-governance step.

`RECOMMENDED` means guidance exists but PR #10 MUST NOT silently upgrade it into a unique active mapping or mandatory project decision.

`EXAMPLE` is presentation/test/reference material and MUST NOT become a machine constraint merely because it appears in the source.

`DECISION_OPTION` represents an explicitly unfrozen project decision option.

`PROHIBITED` represents an explicit invalid usage or forbidden pattern that can be represented as a deterministic rule.

## Project Decision Boundary

### DEC-01 through DEC-10

PR #10 MUST NOT freeze the project's DEC-01 through DEC-10 choices.

If the Metro V3.2 source says that a project must choose among alternatives, the Metro Provider records those alternatives and their source-level recommendation, if any, but does not activate one as the project's final mapping.

Example conceptual record:

```yaml
decision_id: DEC-03
subject_term_id: metro:TrackBed
state: UNFROZEN
options:
  - ifc:IfcSlab
  - ifc:IfcCourse
recommended_option: null
```

A recommended default MAY be recorded when the V3.2 source provides one, but recommendation is not project approval.

### No implicit project freezing

The following implication is forbidden:

```text
option appears in V3.2
→ Metro Provider silently selects it
→ find_mappings() treats it as executable truth
```

Only explicitly ACTIVE deterministic domain mappings may be returned through the existing mapping capability.

Unfrozen project choices remain metadata until a later project / enterprise layer explicitly freezes them.

## Provider Manifest

The manifest is frozen as:

```text
provider_id = dsp.metro.semantic
provider_type = DOMAIN
version = 3.2
namespaces = [metro, ifc]
authority =
    metro -> AUTHORITATIVE
    ifc   -> EXTENSION
capabilities = VOCABULARY, MAPPING, VALIDATION, PROJECTION
requires = [buildingSMART.ifc43@4.3.2.0]
```

### Namespace meaning

`metro` is owned authoritatively by this provider.

`ifc` is declared only as an extension namespace so the provider can supply Metro mapping and validation behavior concerning IFC claims.

`ifc: EXTENSION` MUST NOT be interpreted as permission to redefine or resolve canonical IFC vocabulary terms.

Semantic Service vocabulary routing continues to require exactly one AUTHORITATIVE provider for a namespace. Therefore canonical `ifc:*` vocabulary resolution remains owned by `buildingSMART.ifc43@4.3.2.0`.

### DSP Core dependency

PR #10 SHALL NOT add a dependency on `dsp.core@1.0` unless the actual reviewed Metro machine source contains machine-semantic `dsp:*` references that require it.

No speculative dependency is added merely because DSP Core commonly coexists in a production environment.

## Capability Interpretation

### VOCABULARY

Implemented in PR #10 for Metro-owned terms.

The provider resolves exact `metro:*` identities, descriptions, and machine-readable schemas.

Representative Metro vocabulary may include domain concepts, project-extension properties, mapping-rule terms, validation-rule terms, and decision metadata terms where stable identity improves auditability.

### MAPPING

Implemented only for ACTIVE deterministic mappings supported by the reviewed V3.2 machine source.

Unfrozen decision options, recommendations, examples, and project-extension drafts that still require project choice MUST NOT be returned as active mappings.

### VALIDATION

Implemented only at the claim-local boundary supported by the existing `SemanticClaim` contract.

PR #10 MUST NOT advertise complete Metro IDS / project / model / geometry validation.

### PROJECTION

Declared as the existing marker capability only.

The Phase C `SemanticProjectionProvider` protocol has no concrete `project_facts()` signature. PR #10 does not invent one.

Fact projection remains a Phase E concern after `NormalizedDesignFact` is frozen.

## Canonical Metro Term Identity

### Namespace rule

Metro semantic identities use:

```text
metro:<stable-domain-term>
```

They MUST NOT masquerade as official IFC terms.

### Project property identity

A project property carried physically in a `PsetProj_*` is a Metro semantic term, not an `ifc:*` term.

Example:

```text
physical carrier:
PsetProj_TunnelSegment.ConstructionMethod

canonical semantic identity:
metro:TunnelSegment.ConstructionMethod
```

The term schema may record:

```text
carrier_kind = PROJECT_PSET
ifc_pset_name = PsetProj_TunnelSegment
ifc_property_name = ConstructionMethod
ifc_data_type = ifc:IfcLabel
applicable_entity = ifc:IfcFacilityPartCommon
predefined_type = SEGMENT
```

This keeps semantic identity separate from storage/carrier convention.

### Mapping-rule identity

Active mapping rules SHOULD have stable Metro identities so callers can retrieve their full constraints without changing the provider-neutral `MappingCandidate` DTO.

Recommended form:

```text
metro:Mapping.<SourceConcept>.<TargetConcept>
```

Example:

```text
metro:Mapping.TunnelSegment.ToIfcFacilityPartCommon
```

The exact naming convention is a PR #10 implementation decision, but mapping IDs MUST be stable, exact, versioned through provider provenance, and collision-free.

### Validation-rule identity

Machine validation rules use stable rule IDs under the Metro provider, for example:

```text
metro:Rule.ProhibitIfcTunnelEntity
metro:Rule.TunnelSegment.ConstructionMethod.AllowedValues
```

Rule IDs are machine identities and therefore contribute to machine-semantic content hashing.

## Metro Machine Data Model

The machine source SHALL be able to represent at least four record classes:

```text
terms
mappings
validation_rules
decisions
```

### Term records

A Metro term record may include:

```text
term_id
kind
normative_class
value datatype
allowed values
unit semantics
requirement level
cardinality metadata
applicability
carrier metadata
stage metadata
source reference
human description
```

Not every term requires every field.

### Project-extension carrier metadata

For `PsetProj_*` / `QtoProj_*` semantics, machine records SHOULD preserve the V3.2 data-dictionary dimensions relevant to later IDS/project validation, including where present:

```text
PsetName / QtoName
PropertyName / QuantityName
IfcDataType
Cardinality
AllowedValues
ApplicableEntity
Stage
Source
ResponsibleDiscipline
ValidationRule
```

The provider records these semantics without asserting that a particular project has already registered or approved the extension.

### Requirement level

P-M / P-C / P-R are requirement metadata, not `ValidationStatus` values.

Example:

```text
requirement_level = P-M
```

means the project/domain standard defines a mandatory field at the appropriate applicability/stage boundary.

It does not mean a single claim is automatically a FAIL when the provider has no complete entity/batch coverage information.

### Decision records

Decision records SHALL preserve:

```text
decision_id
subject term
state
options
recommended option if source provides one
source reference
```

The initial PR #10 baseline keeps the project DEC set UNFROZEN unless the source itself unambiguously defines a non-project domain mapping rather than an open project decision.

## Mapping Model

### Internal rich mapping record

Metro requires more mapping semantics than the current provider-neutral `MappingCandidate` DTO can carry.

Therefore PR #10 SHALL keep a richer provider-local mapping model while preserving the existing public DTO.

A local mapping record may contain:

```text
mapping_id
source_term_id
state
normative_class
target_term_id
target constraints
carrier metadata
applicability
evidence/source references
```

Example conceptual schema:

```yaml
mapping_id: metro:Mapping.TunnelSegment.ToIfcFacilityPartCommon
source_term_id: metro:TunnelSegment
state: ACTIVE
normative_class: NORMATIVE
target:
  term_id: ifc:IfcFacilityPartCommon
  constraints:
    - term_id: ifc:IfcFacilityPartCommon.PredefinedType
      equals: SEGMENT
```

### Public mapping projection

`find_mappings()` returns the existing provider-neutral result:

```text
MappingCandidate(
    mapping_id,
    target_term_id,
    provenance,
    evidence,
)
```

The complete Metro constraints are retrieved by resolving/querying the stable mapping rule term schema rather than extending `MappingCandidate`.

PR #10 MUST NOT modify Semantic Service DTOs to encode Metro-specific fields.

### Active mapping gate

Only mappings explicitly normalized to:

```text
state = ACTIVE
```

may be returned by `find_mappings()`.

The following classes MUST NOT become active mappings solely by appearing in the source:

```text
DECISION_OPTION
RECOMMENDED
EXAMPLE
unfrozen project choice
project-extension draft requiring project registration
```

A Metro term with only unfrozen options returns no active mapping.

This is intentional fail-closed behavior.

### Target namespace filtering

When `target_namespace="ifc"`, the Metro Provider returns only active mappings whose target is in the IFC namespace.

For unsupported target namespaces it returns no candidate rather than inventing cross-domain behavior.

### Non-Metro source claims

`find_mappings()` is not a Host-native classifier.

PR #10 MUST NOT inspect AutoCAD layer names, Revit categories, Tekla classes, Host IDs, or enterprise conventions such as `A-WALL`.

Host/enterprise native classification belongs to later providers/adapters in Phase E.

## IFC Reference Boundary

### References, not copied semantics

Metro machine records may reference canonical IFC IDs such as:

```text
ifc:IfcFacilityPartCommon
ifc:IfcSlab
ifc:IfcCourse
ifc:IfcLengthMeasure
```

The Metro Provider MUST NOT copy the complete IFC entity/type/Pset semantics into its own catalog.

IFC inheritance, attributes, official enums, official Pset/Qto semantics, datatypes, and schema legality remain in the IFC Provider.

### No concrete IFC provider import

Production Metro code MUST NOT import:

```text
ifc43_semantic_provider
ifcopenshell
```

The exact dependency is enforced through Semantic Environment pinning, not a concrete Python package dependency.

### Integration conformance

Focused integration tests SHALL create an environment containing the exact IFC and Metro providers and assert that every active canonical `ifc:*` target used by Metro resolves through the IFC Provider.

This protects against a reproducible Metro machine source containing false IFC names.

## Prohibited IFC Usage

The Metro V3.2 source identifies several names/usages that must not be treated as legal IFC4.3 entities, including representative cases such as:

```text
IfcTunnel
IfcTunnelPart
IfcTrack
IfcSprinkler
IfcFanCoilUnit
IfcPrecastConcreteElement
```

PR #10 MUST NOT register these as canonical `ifc:*` terms.

Prohibited or invalid usage is represented as Metro validation/rule metadata, not fake IFC vocabulary.

Therefore:

```text
resolve_term("ifc:IfcTunnel")
```

continues to fail through the IFC Provider.

Metro may provide a prohibition finding or legal replacement guidance when the current claim contains enough context, but it does not rewrite the IFC namespace.

## Claim-Local Validation Boundary

The current provider-neutral `SemanticClaim` contains:

```text
subject
predicate
canonical_term_id
value
unit
assurance
provenance
evidence
provider_id/provider_version
```

It is not a complete Metro entity, IDS applicability set, relationship graph, geometry model, or project-stage context.

Therefore PR #10 validation is intentionally narrow.

### In scope

Where a supplied claim contains sufficient information, Metro validation may deterministically check:

- Metro canonical term existence;
- Metro term/value datatype compatibility;
- allowed-value / domain enum legality;
- project-extension property value compatibility;
- prohibited explicit usage detectable from the claim;
- active mapping constraints representable from one claim;
- obvious Metro rule constraints requiring no missing entity/batch/graph/geometry context;
- whether a claim is outside the Metro validator's scope.

Findings use stable rule IDs and exact provider provenance.

### Requirement levels are metadata

P-M / P-C / P-R MUST NOT be converted directly into PASS/FAIL/WARNING-style statuses.

For example, if a `P-M` property is supplied with an invalid value, PR #10 may FAIL its datatype or enum rule.

If the property is entirely absent, a single `SemanticClaim` invocation cannot prove that an applicable entity is missing a required field because it lacks complete coverage information.

Therefore absence validation is deferred.

### P-C rules

A conditional P-C rule may be evaluated only if the condition is entirely representable in the current claim-local context.

If evaluation requires another claim, entity state, relationship, project stage, system context, or other batch information, the provider returns `NOT_APPLICABLE` for that contextual rule rather than guessing.

### Units

Where correct unit interpretation requires an IFC `IfcUnitAssignment`, project unit context, or quantity context absent from the claim, Metro validation returns a contextual `NOT_APPLICABLE` finding rather than assuming a unit system.

### Out of scope

PR #10 does not claim complete validation of:

- missing mandatory fields across an entity;
- P-C conditions requiring multiple facts;
- complete IDS required/optional/prohibited evaluation;
- model/entity cardinality;
- uniqueness constraints requiring a collection;
- PartOf/system/relationship graph requirements;
- geometry validity;
- Alignment continuity;
- clearance envelopes;
- clashes;
- closed solids;
- full engineering calculations;
- project delivery conformance;
- complete IFC STEP files.

These checks require later batch/model/IDS/geometry contexts.

## IDS Boundary

PR #10 SHALL compile/store IDS-oriented rule metadata but SHALL NOT introduce a full IDS execution engine.

Rule records may include:

```text
rule_id
applicable entity
predefined type
property/attribute target
requirement level
datatype
allowed values
cardinality metadata
stage
condition reference
validation kind
source reference
```

The goal is to avoid reparsing the Metro source when Phase E and later project validation gain entity coverage and batch context.

The existence of this metadata MUST NOT be described as complete IDS compliance checking.

## Projection Boundary

`PROJECTION` remains marker-only in PR #10.

No Metro-specific `project_facts()` or Host-to-Metro projection API is introduced.

The intended later flow remains:

```text
Host native facts
    ↓
NormalizedDesignFact
    ↓
enterprise/native mapping evidence
    ↓
IFC canonical projection
    ↓
Metro domain upgrade as required
```

The actual normalized fact contract starts in Spec v0.6 Phase E, step 18.

## Deterministic Semantic Hashing

The Metro provider `content_hash` represents normalized machine semantics, not documentation formatting.

### Included in `content_hash`

The canonical hash payload SHALL include machine-semantic fields such as:

- provider semantic source version marker;
- Metro term IDs and kinds;
- normative classifications where machine behavior depends on them;
- value datatypes;
- allowed values;
- unit semantics;
- requirement levels;
- machine cardinality metadata;
- applicability;
- carrier identity and relevant project-extension metadata;
- ACTIVE mapping identity/source/target/constraints;
- validation rule IDs, kinds, and machine operands;
- prohibition rules;
- decision IDs;
- decision states;
- decision options;
- recommended option where it is machine metadata.

### Excluded from `content_hash`

The following are not semantic identity by themselves and MUST NOT affect `content_hash`:

- Markdown formatting;
- source page/line/section location by itself;
- explanatory prose;
- localized human labels/descriptions;
- examples that are not machine rules;
- documentation URLs;
- editorial wording;
- Python object representations;
- YAML key ordering.

A source-reference field may still be preserved for audit/provenance while being excluded from the semantic hash when it does not change machine behavior.

### Behavioral examples

If wording changes from one equivalent recommendation phrase to another while the normalized machine requirement stays:

```text
requirement_level = P-R
```

then `content_hash` remains unchanged.

If the rule changes:

```text
P-R → P-M
```

then `content_hash` changes.

If an allowed enum value is added or removed, `content_hash` changes.

If an unfrozen decision becomes a frozen/active mapping, `content_hash` changes.

### Canonical encoding

Use the same discipline established by DSP Core and IFC Provider:

```text
normalized values
→ deterministic collection ordering
→ sorted JSON keys
→ compact UTF-8 JSON
→ SHA-256 lowercase hex
```

The provider SHALL remain independent of the concrete DSP Core/IFC provider implementations even if the tiny hash utility is duplicated.

### Golden content-hash lock

The first implementation SHALL record the expected normalized Metro V3.2 machine `content_hash` after explicit review of representative vocabulary, mapping, validation, prohibition, and decision records.

Focused CI MUST rebuild the catalog from the pinned machine source and assert the resulting hash equals the reviewed golden value.

The golden value MUST NOT be automatically updated by generation tooling.

Changing it requires explicit machine-semantic review.

The concrete golden hash is an implementation-time result and is not frozen by this architectural design.

## Immutable Catalog

### Runtime ownership

Provider construction performs one normalization/build pass into provider-owned immutable records and indexes.

Runtime vocabulary, mapping, and validation queries read only the immutable catalog.

No network access is permitted.

### Machine-source validation

Construction MUST fail closed for at least:

```text
invalid machine-source structure
duplicate metro term ID
duplicate mapping ID
duplicate rule ID
unknown normative classification
unknown requirement level
invalid cardinality representation
mapping source references unknown Metro term
validation rule references unknown Metro term
ACTIVE mapping target has malformed canonical ID
conflicting ACTIVE mapping definitions
DEC state contradicts selected/frozen option
required project-extension property metadata missing its machine datatype
golden content-hash drift
```

Whether a syntactically valid `ifc:*` target actually exists is verified through IFC+Metro integration conformance, not by importing the concrete IFC provider during Metro catalog construction.

## Error Model

Provider-local construction/runtime errors are separate from Semantic Service domain errors.

Recommended hierarchy:

```text
MetroSemanticProviderError
  MetroSourceError
  MetroCatalogBuildError
  MetroTermNotFoundError
  MetroMappingError
  MetroValidationError
```

A normal semantic violation is represented through `ValidationFinding(status=FAIL)`, not an exception.

Exceptions represent source/catalog/provider execution failure.

PR #10 does not add new public Semantic Service error classes.

Existing Semantic Service errors remain responsible for:

- manifest validity;
- provider registration conflicts;
- capability/protocol mismatch;
- missing exact dependencies;
- namespace authority conflicts;
- environment integrity;
- provider operation wrapping/provenance checks.

## Semantic Environment Behavior

### Exact dependency gate

An environment selecting:

```text
dsp.metro.semantic@3.2
```

without:

```text
buildingSMART.ifc43@4.3.2.0
```

MUST fail through the existing exact dependency enforcement.

### Authority composition

A normal environment may include:

```text
dsp.core@1.0
buildingSMART.ifc43@4.3.2.0
dsp.metro.semantic@3.2
```

Authority remains:

```text
dsp:*   → dsp.core AUTHORITATIVE
ifc:*   → buildingSMART.ifc43 AUTHORITATIVE
metro:* → dsp.metro.semantic AUTHORITATIVE
```

Metro may extend validation/mapping behavior concerning IFC, but it never becomes the authoritative IFC vocabulary owner.

### No platform routing changes

The existing Semantic Service vocabulary/mapping/validation routing is sufficient for PR #10.

No special Metro routing, dedicated Metro MCP endpoint, or platform DTO extension is introduced.

## Conformance Test Matrix

PR #10 SHALL provide focused tests for the main Spec v0.6 semantic-provider conformance surfaces.

### Manifest

Verify:

```text
provider_id = dsp.metro.semantic
provider_type = DOMAIN
version = 3.2
VOCABULARY / MAPPING / VALIDATION / PROJECTION claimed
buildingSMART.ifc43@4.3.2.0 exact dependency
metro AUTHORITATIVE
ifc EXTENSION
```

### Source and catalog

Verify:

- machine source loads deterministically;
- source document digest metadata is exact and pinned;
- representative machine records preserve normative classification;
- duplicate/conflicting records fail closed;
- catalog is immutable;
- source iteration/key order does not alter normalized semantic hash.

### Content hash

Verify:

- repeated builds produce the same hash;
- reviewed golden hash is enforced;
- description/source-location-only changes do not alter semantic hash;
- requirement / enum / mapping / decision-state changes alter semantic hash.

### Vocabulary

Verify representative `metro:*` terms resolve exactly, including project-extension property semantics and stable mapping/rule identities selected for the catalog.

Lookup is case-sensitive and exact.

Unknown Metro terms fail deterministically.

### IFC authority boundary

Verify:

- Metro does not resolve `ifc:*` vocabulary authoritatively;
- IFC Provider remains the only authoritative `ifc` owner;
- Metro cannot redefine `ifc:IfcWall` or any other standard term;
- prohibited pseudo-entities such as `ifc:IfcTunnel` do not become valid terms.

### IFC reference conformance

In an environment containing exact IFC+Metro providers, every ACTIVE canonical `ifc:*` target and machine IFC datatype reference used by Metro SHALL resolve through the IFC Provider.

Representative negative source names remain unresolved by IFC.

### Mapping

Verify:

- deterministic ACTIVE mapping returns a `MappingCandidate`;
- returned provenance matches the pinned Metro provider;
- mapping IDs are stable;
- full constraints are available through the mapping term schema;
- target namespace filtering works;
- recommendation/example/unfrozen decision records do not return active mappings;
- a Metro term with no active mapping returns an empty result.

### Decisions

Verify representative DEC records remain UNFROZEN in the reference provider and cannot silently become active mapping results.

The test suite SHALL include at least one case where recommendation metadata exists but no mapping is returned.

### Validation

Verify deterministic claim-local behavior for representative:

- valid datatype;
- invalid datatype;
- allowed enum value;
- invalid enum value;
- explicit prohibited usage;
- non-Metro claim → NOT_APPLICABLE where appropriate;
- missing model/unit/context → NOT_APPLICABLE rather than guessed PASS/FAIL;
- stable rule IDs and exact provenance.

### Requiredness boundary

Verify that P-M metadata does not cause a missing-field FAIL when no complete entity/batch coverage is provided.

Verify that P-C rules requiring external facts are not guessed.

### Semantic Service / MCP

Verify the existing Semantic Service and Semantic MCP surfaces can:

- resolve/describe/schema-query Metro terms;
- return active Metro mappings;
- return Metro validation findings;
- inspect the Metro provider manifest;
- use the combined pinned Semantic Environment.

No Metro-specific MCP method is required.

### Architecture

Tests/guards SHALL prevent:

```text
Metro Provider → ifcopenshell
Metro Provider → ifc43_semantic_provider
Metro Provider → semantic_runtime / semantic_mcp implementation
Metro Provider → Host providers
Metro Provider → D5/D6/D7
platform core   → concrete Metro provider
```

The provider must also contain no Host-native product conventions such as AutoCAD layer names, Revit ElementId/category identifiers, or enterprise `A-WALL` classification logic.

### Regression

Focused PR #10 verification MUST run together with the existing Semantic Service, Semantic MCP, DSP Core, and IFC4.3 Provider regression suites.

Before merge, run the full relevant Python regression used by the preceding semantic-provider PRs.

## Recommended Package Boundary

Recommended package layout:

```text
providers/semantics/metro_v32/
  pyproject.toml
  README.md
  data/
    metro_v3_2.yaml
  src/metro_semantic_provider/
    __init__.py
    source.py
    model.py
    normalization.py
    catalog.py
    hashing.py
    mapping.py
    validation.py
    provider.py
    errors.py
```

The exact internal split is an implementation-plan detail. The architectural requirements are:

- machine source is checked in and version-pinned;
- source validation is separate from runtime query behavior;
- records become immutable before serving;
- mapping and validation remain provider-local;
- no runtime Markdown parser;
- no concrete IFC provider import.

## Non-Goals for PR #10

PR #10 explicitly does not implement:

- a complete IDS execution engine;
- complete entity-level missing-required-field validation;
- P-C evaluation requiring multiple claims or model context;
- relationship-graph / system / PartOf validation;
- complete cardinality/uniqueness evaluation across a model;
- IFC STEP-file validation;
- Alignment continuity calculations;
- clearance / clash / geometry validation;
- complete engineering calculations;
- project delivery acceptance;
- freezing DEC-01 through DEC-10 on behalf of a project;
- treating recommended/example `PsetProj_*` content as already project-approved;
- a project-specific Metro provider;
- `NormalizedDesignFact`;
- Host-native extraction;
- AutoCAD/Revit/Tekla classification logic;
- enterprise `A-WALL` mapping;
- concrete Host→IFC or Host→Metro projection;
- D5 reconstruction changes;
- D6/D7 action/execution changes;
- Semantic Service DTO changes;
- special Metro MCP endpoints;
- direct `ifc43_semantic_provider` imports;
- IfcOpenShell dependency;
- runtime network lookup;
- runtime parsing of the V3.2 Markdown source.

## Phase Boundary After PR #10

Completing PR #10 closes Spec v0.6 Phase D reference providers:

```text
15. DSP Core Provider          complete
16. IFC4.3 Provider            complete
17. Metro Semantic Provider    PR #10
```

The next phase is deliberately different:

```text
Phase E — Ingestion / Progressive Proof
18. NormalizedDesignFact contract
19. AutoCAD native fact extractor
20. enterprise A-WALL mapping provider
21. prove A-WALL → IfcWall without D5 changes
22. prove task only upgrades required aspects/fidelity
```

PR #10 MUST NOT pull Phase E ingestion concerns forward merely to demonstrate the Metro provider.

## Design Summary

The architectural contract is:

```text
Metro V3.2 human-reviewed source
        ↓
reviewed pinned metro_v3_2.yaml
        ↓
immutable MetroCatalog
        │
        ├─ metro:* authoritative vocabulary
        ├─ ACTIVE deterministic domain mappings
        ├─ claim-local Metro validation
        └─ unfrozen decision / IDS-oriented metadata
        ↓
existing Semantic Service / Semantic MCP

buildingSMART.ifc43@4.3.2.0
        ↑ exact dependency + IFC authority
```

The provider boundary can be summarized as:

> IFC Provider answers what legal IFC4.3 means. Metro Provider answers how the Metro domain uses legal IFC4.3. A concrete project answers which unfrozen project option it finally selects.

This separation is mandatory for PR #10.
