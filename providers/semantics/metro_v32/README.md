# Metro V3.2 Semantic Provider

`dsp.metro.semantic@3.2` is DSP's reference DOMAIN Semantic Provider for the Metro V3.2 profile.

## Authority and dependency

- `metro`: `AUTHORITATIVE`
- `ifc`: `EXTENSION`
- exact dependency: `buildingSMART.ifc43@4.3.2.0`

Metro may add domain mapping and validation around IFC usage, but it never owns or redefines IFC vocabulary. Canonical `ifc:*` legality remains the responsibility of the IFC4.3 STANDARD Provider.

## Source

The reviewed human source is `IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版`, targeting `IFC4X3_ADD2 / IFC 4.3.2.0`.

- source document SHA-256: `596a140612f4d3af49dccfe01c235be28cf76b8280334bfc2920f29fc8ee422b`
- pinned machine source: `src/metro_semantic_provider/data/metro_v3_2.yaml`
- reviewed semantic content hash: `788e92d0257f4c79764fd35051d4bb49c629f88e482c10d8552c098096590474`
- runtime Markdown parsing: none
- runtime network lookup: none

The source-document digest proves which reviewed document was used. The provider `content_hash` hashes normalized machine semantics and intentionally excludes presentation wording and source-location prose.

## Machine-source coverage

The checked-in V3.2 machine source records the reviewed Phase D baseline:

- 37 Chapter 21 `PsetProj_*` containers
- 236 structured source rows plus 8 inline-only project Pset sources
- 380 normalized Metro terms
- 18 reviewed `ACTIVE` Metro-to-IFC mappings
- 9 explicit prohibition rules
- DEC-01 through DEC-10, all retained as `UNFROZEN`

`PsetProj_*` names are carrier metadata. They are not a new IFC namespace and are not canonical Metro term IDs. A project property is represented by a stable Metro identity such as `metro:TunnelSegment.ConstructionMethod`, with the physical `PsetProj_*` name stored in its term schema.

## Capabilities

### VOCABULARY

Owns exact, case-sensitive `metro:*` concepts, project-property semantics, mapping-rule records, validation-rule records, and decision metadata. It does not resolve `ifc:*` as Metro vocabulary.

### MAPPING

Returns only reviewed records whose state is `ACTIVE`, and only in the direction `metro:* -> ifc:*`. UNFROZEN DEC choices, recommendations, examples, and project options are not returned as executable mappings.

The existing provider-neutral `MappingCandidate` remains intentionally thin. Full constraints are queryable through the mapping rule's `metro:*` term schema.

### VALIDATION

Implements deterministic claim-local checks that the current `SemanticClaim` can actually support: known Metro terms, local datatype checks, controlled values, explicit prohibited IFC usage, and context findings when a unit or conditional rule needs external context.

P-M/P-C/P-R remain requirement metadata. The provider does not invent missing-property failures from a single claim, and P-C rules that need other facts are not treated as fully evaluable.

### PROJECTION

Claimed as the main-Spec marker capability only. PR #10 does not introduce `project_facts()`; Phase E owns projection over the future `NormalizedDesignFact` contract.

## DEC policy

DEC-01 through DEC-10 belong to project governance. The Metro Provider preserves their candidate options and recommendations but does not freeze them. An UNFROZEN decision never becomes an `ACTIVE` mapping merely because the source document recommends one option.

A future project or enterprise layer may freeze a project choice without changing the meaning of `dsp.metro.semantic@3.2`.

## IFC conformance

The provider production package stores provider-neutral `ifc:*` references but does not import `ifc43_semantic_provider` or `ifcopenshell`. Integration tests compose Metro with `buildingSMART.ifc43@4.3.2.0` and require every machine IFC reference to resolve through the IFC Provider's authoritative namespace.

False IFC names such as `IfcTunnel` are never registered as canonical `ifc:*` vocabulary. Where V3.2 explicitly prohibits such usage, the Metro Provider may emit a domain validation finding while IFC remains the vocabulary authority.

## Architecture boundary

This package does not depend on D5, Semantic Runtime, Semantic MCP implementation code, AutoCAD/Revit/Tekla APIs, native IDs, or Host classification logic. Semantic MCP uses the existing provider-neutral `semantic.*` tools; Metro adds no dedicated MCP endpoint.

## Non-goals

PR #10 does not implement full IDS evaluation, entity-level missingness/cardinality, cross-claim conditional evaluation, relationship-graph validation, IFC STEP-file validation, Alignment mathematics, clearance/clash/geometry checking, project DEC freezing, project approval of `PsetProj_*`, `NormalizedDesignFact`, Host extraction, AutoCAD `A-WALL` mapping, D5 changes, or runtime Markdown/network interpretation.
