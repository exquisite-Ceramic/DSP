# Enterprise Mapping Provider

`dsp.enterprise.mapping@1.0.0` is the Phase E Step 20 ENTERPRISE Semantic Provider. It deterministically projects structured `NormalizedDesignFact` classification evidence into provider-neutral `SemanticClaim` values without teaching Semantic Service, D5, or Host adapters any enterprise layer convention.

## Identity and authority

- provider: `dsp.enterprise.mapping@1.0.0`
- provider type: `ENTERPRISE`
- capability: `PROJECTION`
- compatibility: `dsp.semantic.projection-facts.v1`
- namespace: `ifc`
- authority: `EXTENSION`
- exact dependency: `buildingSMART.ifc43@4.3.2.0`

The provider may emit claims that reference IFC terms, but it does not own IFC vocabulary meaning. `buildingSMART.ifc43@4.3.2.0` remains the `AUTHORITATIVE` provider for `ifc:*` term resolution.

## Machine mapping source

Runtime rules are packaged in `src/enterprise_mapping_provider/data/enterprise_mappings_v1.yaml`. The provider loads this local YAML with `yaml.safe_load`, normalizes it into an immutable catalog, and verifies the semantic payload against the reviewed SHA-256:

`8128d6fcac45933a27ec3da63359c8ec97a4e33a0319b051e466c6a20ac8e41d`

Optional descriptions/comments are not semantic hash input. Runtime network access and Markdown parsing are not part of the provider path.

The Step 20 catalog contains two case-insensitive rules over structured source evidence:

- EXACT: `source_scheme=autocad.layer`, `source_code=A-WALL`
- PREFIX: `source_scheme=autocad.layer`, `source_code` beginning with `A-WALL-`

Both map to `ifc:IfcWall` with assurance `RULE_DERIVED`. Matching is restricted to EXACT and PREFIX; regex/glob behavior is intentionally unsupported. Catalog construction and runtime projection both fail closed on ambiguous matches that disagree on target term or assurance.

## Projection contract

Only `FactKind.CLASSIFICATION` facts with non-null `source_scheme` and `source_code` participate. Matching uses those structured fields only; `predicate`, `value`, and provenance text cannot create a mapping match.

A matched derivation emits a claim equivalent to:

```text
subject            = native://<host_type>/<host_instance_id>/<document_id>/<native_id>
predicate          = classification
canonical_term_id  = ifc:IfcWall
value              = null
unit               = null
assurance          = RULE_DERIVED
provenance         = <input fact provenance, verbatim>
evidence           = (design-fact:<fact_id>, mapping:<mapping_id>)
provider_id        = dsp.enterprise.mapping
provider_version   = 1.0.0
```

Subject locator segments are URL-encoded. Derivations are ordered deterministically by `(subject, mapping_id, fact_id)`, and separate fact/rule derivations remain separate claims so mapping evidence is not collapsed.

## Step 19 -> Step 20 boundary

The intended proof path is:

```text
AutoCAD native snapshot
  -> Step 19 DesignFactAdapter
  -> NormalizedDesignFact(CLASSIFICATION, autocad.layer, A-WALL)
  -> SemanticService.project_facts(...)
  -> pinned dsp.enterprise.mapping@1.0.0
  -> SemanticClaim(classification, ifc:IfcWall, RULE_DERIVED)
  -> ifc:IfcWall resolved by buildingSMART.ifc43@4.3.2.0
```

The Enterprise provider depends only on stable contracts and Semantic Service interfaces. It does not import AutoCAD/Revit/Tekla APIs or adapters, IFC/Metro concrete provider implementations, Semantic Runtime/D5, or Semantic MCP.

## Step 20 non-goals

Step 20 does not add an `acme:*` vocabulary, a Semantic MCP projection endpoint, D5 integration, Host SDK dependencies, or production changes to AutoCAD, IFC, Metro, Semantic Runtime/D5, or Semantic MCP. The explicit zero-change D5 end-to-end proof remains Phase E Step 21.
