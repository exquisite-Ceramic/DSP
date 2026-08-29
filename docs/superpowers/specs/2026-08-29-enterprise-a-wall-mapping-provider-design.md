# Enterprise A-WALL Mapping Provider Design

> Phase E — Step 20  
> Status: Design freeze candidate  
> Date: 2026-08-29  
> Base: `main@33dc9371346539135c51acdcd1521b1dc759fe9d`  
> Parent work: Step 18 `NormalizedDesignFact`; Step 19 AutoCAD native fact extractor

## 1. Goal

Step 20 introduces the first enterprise semantic projection from Host-normalized evidence into a canonical semantic claim:

```text
AutoCAD native entity
  -> layer = A-WALL / A-WALL-*
  -> NormalizedDesignFact CLASSIFICATION evidence
  -> pinned Enterprise Semantic Provider
  -> SemanticClaim(canonical_term_id = ifc:IfcWall)
```

The implementation must preserve the v0.6 ownership boundary:

- AutoCAD plugin/sidecar knows AutoCAD facts but not enterprise meaning.
- `NormalizedDesignFact` transports structured source evidence but does not decide final semantics.
- Enterprise Provider owns enterprise mapping rules such as `autocad.layer / A-WALL-* -> ifc:IfcWall`.
- Semantic Service owns pinned-environment routing and provider conformance, not the rule itself.
- IFC4.3 Provider remains authoritative for the meaning of `ifc:*` terms.
- D5 does not contain `A-WALL`, AutoCAD layer logic, or enterprise mapping tables.

Step 20 freezes the Phase E fact-projection contract that Phase C intentionally deferred until `NormalizedDesignFactBatch` existed.

## 2. Architectural problem

Step 19 produces source evidence such as:

```text
fact_kind     = CLASSIFICATION
predicate     = layer
value         = A-WALL
source_scheme = autocad.layer
source_code   = A-WALL
```

That is still L1 normalized evidence. It is not yet a canonical IFC classification.

Putting the rule into AutoCAD or D5 would create Host-specific branches in platform core:

```text
if host == "autocad" and layer.startswith("A-WALL"):
    return "ifc:IfcWall"
```

The correct reusable seam is:

```text
NormalizedDesignFactBatch
  -> Enterprise Projection Provider
  -> SemanticClaim
```

so future Revit/Tekla enterprise conventions can use the same provider contract without modifying Semantic Service or D5.

## 3. Existing contracts

### 3.1 `NormalizedDesignFact`

Step 18 already carries the required structured input:

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

Step 20 does not change this contract.

### 3.2 `SemanticClaim`

Semantic Service already defines the provider-neutral semantic output:

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

The main spec describes this as the unified claim emitted by providers. It must remain an output DTO; Step 20 must not add `source_scheme/source_code` to it merely to feed enterprise mapping.

### 3.3 Existing PROJECTION marker

Phase C deliberately left `SemanticProjectionProvider` as a marker and did not freeze `project_facts()` yet.

Existing IFC/Metro providers already declare `SemanticCapability.PROJECTION` under that old marker meaning. Step 20 must not retroactively force production changes into those providers just to satisfy the new callable API.

Therefore Step 20 introduces a **versioned projection compatibility token** using the manifest field that already exists for compatibility declarations.

## 4. Architectural decision

Freeze a provider-neutral fact projection API, versioned by compatibility token:

```text
compatibility token:
  dsp.semantic.projection-facts.v1
```

A provider participates in the new Step 20 callable fact-projection path only when its manifest declares both:

```text
capabilities contains PROJECTION
compatibility contains dsp.semantic.projection-facts.v1
```

This preserves existing Phase C marker-only providers unchanged while making the new callable contract explicit and machine-visible.

Pipeline:

```text
NormalizedDesignFactBatch
        |
        v
SemanticService.project_facts(...)
        |
        +-- selected provider with PROJECTION only
        |      -> legacy marker; not called by facts-v1 path
        |
        +-- selected provider with
               PROJECTION
               + dsp.semantic.projection-facts.v1
                    |
                    v
              project_facts(batch)
                    |
                    v
               SemanticClaim[]
        |
        v
caller / later D5 integration
```

Key abstraction rule:

```text
NormalizedDesignFactBatch = provider input
SemanticClaim             = provider output
```

The existing `SemanticClaim -> find_mappings() -> MappingCandidate[]` API remains unchanged.

## 5. Rejected alternatives

### 5.1 Extend `SemanticClaim` with ingestion fields

Rejected because it mixes pre-semantic source evidence and canonical semantic output in one DTO.

### 5.2 Encode source evidence in strings

Rejected examples:

```text
predicate = autocad.layer
value = A-WALL
```

or parsing:

```text
evidence = autocad.layer:A-WALL
```

Providers must use the typed NDF `source_scheme/source_code` fields, not string conventions hidden in claim fields.

### 5.3 Put A-WALL mapping in AutoCAD, Metro, IFC, or D5

Rejected. AutoCAD owns extraction/normalization; Metro owns domain semantics; IFC owns IFC vocabulary; D5 owns progressive canonical state. Enterprise mapping belongs in an ENTERPRISE provider.

### 5.4 Globally reinterpret every existing PROJECTION provider

Rejected. Existing IFC/Metro manifests were created while PROJECTION was explicitly marker-only. Step 20 uses the versioned compatibility token instead of requiring unrelated provider edits or changing their environment hashes.

## 6. Fact projection provider contract

Add a runtime-checkable provider protocol:

```python
@runtime_checkable
class SemanticProjectionProvider(SemanticProvider, Protocol):
    def project_facts(
        self,
        facts: NormalizedDesignFactBatch,
    ) -> tuple[SemanticClaim, ...]: ...
```

Requirements:

1. input is the frozen Step 18 `NormalizedDesignFactBatch`;
2. output is immutable `SemanticClaim` values;
3. same provider content + same input batch must produce the same ordered tuple;
4. provider must not mutate the batch;
5. provider may emit zero, one, or many claims;
6. provider must not mutate D5;
7. provider receives no Autodesk/Revit/Tekla SDK object.

### 6.1 Versioned conformance rule

Registry validation becomes:

```text
if compatibility contains dsp.semantic.projection-facts.v1:
    manifest must also contain PROJECTION
    provider must implement SemanticProjectionProvider
```

A provider that has PROJECTION without the compatibility token remains a valid legacy marker-only provider and is not called by `SemanticService.project_facts()`.

A provider that declares the compatibility token without PROJECTION fails registration.

This lets Step 20 freeze the callable API without modifying existing IFC/Metro provider source or manifests.

### 6.2 Dependency direction

The Python `design_fact_contracts` module is shipped by the existing `host-contracts` distribution. Therefore `platform/semantic_service/pyproject.toml` adds:

```text
host-contracts>=0.1.0
```

not a new `design-fact-contracts` distribution.

Dependency direction stays acyclic:

```text
host-contracts / design_fact_contracts
            ^
            |
     semantic_service
            ^
            |
 enterprise_mapping_provider
```

`design_fact_contracts` must not import Semantic Service. `semantic_runtime` / D5 must not import AutoCAD sidecar modules.

## 7. `SemanticService.project_facts()`

Add:

```python
SemanticService.project_facts(
    facts: NormalizedDesignFactBatch,
    environment_id: str,
) -> tuple[SemanticClaim, ...]
```

Service responsibilities only:

1. load the exact pinned `SemanticEnvironment`;
2. iterate selected providers in deterministic pinned `(provider_id, version)` order;
3. select only providers declaring both PROJECTION and `dsp.semantic.projection-facts.v1`;
4. require the selected object to satisfy `SemanticProjectionProvider`;
5. call `project_facts(facts)`;
6. fail closed if any participating provider raises;
7. require every returned item to be `SemanticClaim`;
8. require each claim's `provider_id/provider_version` to equal the pinned provider that emitted it;
9. preserve participating provider order and each provider's returned tuple order.

The last rule avoids inventing a generic serializer/sort order for arbitrary `SemanticClaim.value`. Determinism is instead part of the provider contract and is conformance-tested.

Marker-only PROJECTION providers are ignored by this method; they are not treated as failures because they do not claim the facts-v1 compatibility surface.

Semantic Service production code must contain no enterprise rule token such as:

```text
A-WALL
A-WALL-
autocad.layer
ifc:IfcWall
```

## 8. Enterprise provider package

Create:

```text
providers/semantics/enterprise_mapping/
  README.md
  pyproject.toml
  src/enterprise_mapping_provider/
    __init__.py
    provider.py
    model.py
    source.py
    catalog.py
    projection.py
    hashing.py
    errors.py
    data/
      enterprise_mappings_v1.yaml
```

Tests:

```text
tests/semantic_providers/enterprise_mapping/
```

The package may understand stable source-scheme tokens from NDF, but must not import AutoCAD plugin/sidecar code.

### 8.1 Package dependencies

Use the existing packaging pattern:

```text
semantic-service>=0.1.0
host-contracts>=0.1.0
PyYAML==6.0.3
```

## 9. Enterprise provider manifest

Freeze:

```text
provider_id   = dsp.enterprise.mapping
provider_type = ENTERPRISE
version       = 1.0.0

namespaces:
  ifc

capabilities:
  PROJECTION

authority:
  ifc -> EXTENSION

compatibility:
  dsp.semantic.projection-facts.v1

requires:
  buildingSMART.ifc43@4.3.2.0
```

Rationale:

- IFC provider remains the only authoritative owner of `ifc:*` vocabulary meaning;
- Enterprise provider contributes projection behavior involving IFC terms;
- exact IFC dependency pins the target semantic baseline;
- compatibility explicitly opts this provider into the Step 20 callable fact-projection API.

Step 20 does not add an `acme:*` namespace.

## 10. Why no `acme:*` intermediate term yet

The main spec shows a valid future chain:

```text
A-WALL-EXT
  -> acme:ExteriorWall
  -> ifc:IfcWall
```

but Step 20/21 only require the extensibility proof:

```text
A-WALL-* -> ifc:IfcWall
```

Adding `acme:*` now would also require enterprise vocabulary authority, term schemas, multi-hop mapping resolution, and new conflict rules. Those capabilities remain possible later without changing the fact-projection contract.

## 11. Machine-owned mapping source

Rules are packaged machine data, not Python `if/else` branches.

Use YAML, following the existing Metro provider source-loading approach:

```yaml
metadata:
  provider_id: dsp.enterprise.mapping
  provider_version: 1.0.0
  target_ifc_provider_id: buildingSMART.ifc43
  target_ifc_provider_version: 4.3.2.0
  target_ifc_schema: IFC4X3_ADD2

rules:
  - mapping_id: enterprise.autocad.layer.a-wall.exact.v1
    source_scheme: autocad.layer
    match:
      type: EXACT
      pattern: A-WALL
      case_sensitive: false
    target_term_id: ifc:IfcWall
    assurance: RULE_DERIVED

  - mapping_id: enterprise.autocad.layer.a-wall-prefix.v1
    source_scheme: autocad.layer
    match:
      type: PREFIX
      pattern: A-WALL-
      case_sensitive: false
    target_term_id: ifc:IfcWall
    assurance: RULE_DERIVED
```

### 11.1 Match semantics

Step 20 supports only:

```text
EXACT
PREFIX
```

No regex/glob language.

Rules first require exact `source_scheme`, then match `source_code`.

Frozen A-WALL behavior:

```text
A-WALL       -> match
A-WALL-EXT   -> match
A-WALL-INT   -> match
a-wall-ext   -> match
A-WALLISH    -> no match
X-A-WALL     -> no match
```

The `A-WALL-` prefix includes the delimiter to avoid accepting `A-WALLISH`.

### 11.2 Catalog validation

Fail closed for:

- duplicate `mapping_id`;
- blank source scheme/pattern/target;
- unsupported match type;
- non-boolean `case_sensitive`;
- malformed target term id;
- assurance outside the frozen vocabulary;
- ambiguous rule sets where the same source evidence can match rules producing conflicting target term or assurance.

Rule order is not priority.

### 11.3 Content hash

Provider `content_hash` derives from canonical machine semantics, including metadata that changes interpretation and normalized rule records.

A rule semantic change must change the content hash. Presentation comments/descriptions alone must not.

Freeze a reviewed golden hash in code/tests, consistent with the Metro provider pattern.

## 12. Input fact selection

The Enterprise Provider considers only facts where:

```text
fact_kind     == CLASSIFICATION
source_scheme is not None
source_code   is not None
```

For A-WALL rules:

```text
source_scheme == autocad.layer
```

It must not infer the source scheme/code from `predicate`, `value`, or provenance text when the structured fields are absent.

IDENTITY, BOUNDS, PROPERTY, GEOMETRY, PLACEMENT, and RELATIONSHIP facts are ignored by these rules.

## 13. Native subject locator

Projection needs a subject address without pretending to create a canonical `SemanticId`.

Freeze:

```text
native://<host_type>/<host_instance_id>/<encoded-document_id>/<encoded-native_id>
```

Each path segment is generated with UTF-8 `urllib.parse.quote(segment, safe="")`.

For Step 19 AutoCAD facts this is conceptually:

```text
native://autocad/<session-uuid>/<encoded-document>/<handle>
```

Rules:

- all components come only from NDF `host_ref` / `subject_native_ref`;
- this is a projection subject locator, not semantic identity;
- Host restart may change `host_instance_id`;
- Step 20 does not perform durable cross-session identity reconciliation;
- D5 identity binding remains a later owner.

## 14. A-WALL output claim

One matched fact/rule derivation emits:

```text
subject            = <native subject locator>
predicate          = classification
canonical_term_id  = ifc:IfcWall
value              = None
unit               = None
assurance          = RULE_DERIVED
provider_id        = dsp.enterprise.mapping
provider_version   = 1.0.0
```

### 14.1 Evidence

Freeze ordered evidence:

```text
design-fact:<fact_id>
mapping:<mapping_id>
```

### 14.2 Provenance

Preserve source provenance verbatim:

```text
claim.provenance = source_fact.provenance
```

Provider id/version use their dedicated claim fields. The pinned environment already binds provider content hash, so Step 20 does not expand `SemanticClaim` with a duplicate content-hash field.

## 15. Duplicate and conflict behavior

The Enterprise Provider emits one claim per matched input-fact/rule derivation and returns claims in deterministic order:

```text
subject
mapping_id
source fact_id
```

It does not silently merge evidence from different input facts.

If one source fact matches multiple rules that disagree on target term or assurance, evaluation fails closed. YAML order never resolves semantic conflict.

## 16. IFC authority/conformance boundary

The Enterprise Provider can emit IFC target terms because its environment requires:

```text
buildingSMART.ifc43@4.3.2.0
```

`SemanticService.project_facts()` does not automatically call `resolve_term()` for every emitted claim; projection routing and vocabulary lookup stay separate capabilities.

Provider conformance tests must prove every packaged enterprise target term resolves under the required IFC provider baseline.

## 17. Metro boundary

Metro Semantic remains a separate DOMAIN provider. It is not the owner of enterprise AutoCAD layer conventions.

Step 20 must not:

- modify `metro_v32` production code or machine source;
- add A-WALL mapping to Metro;
- make Metro interpret Host-native APIs;
- change IFC authority.

## 18. AutoCAD boundary

Step 20 must not modify AutoCAD plugin or sidecar production code.

Step 19 already emits the complete evidence needed by Step 20. The enterprise rule is consumed only after the NDF boundary.

## 19. MCP boundary

No new Semantic MCP endpoint is added.

The main spec permits a future `semantic.project_facts`, but Step 20 freezes and proves the logical in-process domain contract first.

## 20. D5 boundary

Step 20 makes no D5/`semantic_runtime` production change.

Step 21 is the explicit extensibility proof that wires projection through the D5 reconstruction path and demonstrates:

```text
A-WALL / A-WALL-*
  -> ifc:IfcWall
```

without adding the enterprise rule to D5 Core.

## 21. Expected repository changes

Provider-neutral contract:

```text
platform/semantic_service/pyproject.toml
platform/semantic_service/src/semantic_service/providers.py
platform/semantic_service/src/semantic_service/registry.py
platform/semantic_service/src/semantic_service/service.py
platform/semantic_service/src/semantic_service/__init__.py
```

New provider:

```text
providers/semantics/enterprise_mapping/
  README.md
  pyproject.toml
  src/enterprise_mapping_provider/
    __init__.py
    provider.py
    model.py
    source.py
    catalog.py
    projection.py
    hashing.py
    errors.py
    data/enterprise_mappings_v1.yaml
```

Tests:

```text
tests/semantic_service/test_provider_contracts.py
tests/semantic_service/test_registry.py
tests/semantic_service/test_service_projection.py
tests/semantic_service/test_provider_provenance_boundary.py

tests/semantic_providers/enterprise_mapping/
  test_source.py
  test_catalog.py
  test_projection.py
  test_manifest.py
  test_service_integration.py
  test_architecture.py
  test_target_ifc_conformance.py
```

A focused Enterprise Semantic Provider workflow may be added.

No Step 20 production change is expected under:

```text
hosts/autocad/
platform/semantic_runtime/
providers/semantics/metro_v32/
providers/semantics/ifc43/
platform/orchestrator/
```

## 22. TDD testing strategy

### 22.1 Projection compatibility tests

- PROJECTION without facts-v1 token remains a valid marker-only provider;
- facts-v1 token without PROJECTION fails registration;
- facts-v1 + PROJECTION without `project_facts()` fails registration;
- valid facts-v1 provider is called;
- marker-only provider is not called by `project_facts()`;
- participating providers are called in pinned provider order;
- output preserves deterministic provider tuple order;
- provider exception aborts instead of returning partial claims;
- forged output provider id/version fails closed;
- input batch remains unchanged.

### 22.2 Enterprise source/catalog tests

- metadata is exact;
- duplicate mapping IDs fail;
- unsupported match type fails;
- invalid assurance fails;
- ambiguous rules fail;
- machine-semantic change changes content hash;
- golden content hash matches reviewed source.

### 22.3 A-WALL tests

Given `CLASSIFICATION + autocad.layer` evidence:

```text
A-WALL      -> ifc:IfcWall
A-WALL-EXT  -> ifc:IfcWall
A-WALL-INT  -> ifc:IfcWall
a-wall-ext  -> ifc:IfcWall
A-WALLISH   -> no claim
X-A-WALL    -> no claim
```

### 22.4 Structured evidence tests

- `value="A-WALL"` without `source_scheme/source_code` does not map;
- provenance text containing `A-WALL` does not map;
- non-CLASSIFICATION facts do not map;
- another source scheme with source code `A-WALL` does not map.

### 22.5 Authority/dependency tests

- provider type ENTERPRISE;
- IFC authority EXTENSION only;
- exact dependency `buildingSMART.ifc43@4.3.2.0`;
- environment pinning fails without required IFC provider;
- all enterprise IFC targets resolve through the existing IFC provider.

### 22.6 Architecture tests

Prove production source has no new enterprise mapping logic in:

```text
AutoCAD plugin/sidecar
Semantic Service core
Metro provider
IFC provider
D5 semantic_runtime
```

Enterprise Provider must import neither AutoCAD plugin nor sidecar packages.

## 23. Acceptance criteria

Step 20 is complete when:

1. `SemanticProjectionProvider.project_facts(NormalizedDesignFactBatch)` is frozen as the facts-v1 projection protocol.
2. `dsp.semantic.projection-facts.v1` opt-in is machine-visible in provider compatibility metadata.
3. Existing marker-only PROJECTION providers remain unchanged and are not invoked by the facts-v1 service path.
4. Registry fails closed for malformed facts-v1 declarations.
5. `SemanticService.project_facts()` performs pinned deterministic facts-v1 fan-out and fails closed.
6. `dsp.enterprise.mapping@1.0.0` exists as an ENTERPRISE provider with IFC EXTENSION authority.
7. The provider depends on exact `buildingSMART.ifc43@4.3.2.0`.
8. Enterprise rules are packaged machine data with deterministic content hash.
9. `autocad.layer / A-WALL` produces `ifc:IfcWall`.
10. `autocad.layer / A-WALL-*` produces `ifc:IfcWall` with the frozen delimiter-aware PREFIX rule.
11. Invalid near-matches such as `A-WALLISH` do not map.
12. Mapping uses structured `source_scheme/source_code`, never evidence-string parsing.
13. Output assurance is `RULE_DERIVED`; evidence names source fact and mapping rule.
14. Projection creates no `SemanticId`.
15. AutoCAD, Metro, IFC, and D5 production code remain unchanged.
16. No new Semantic MCP endpoint is required.
17. Every target IFC term is conformance-tested against the required IFC provider.
18. Focused tests and relevant Semantic Service / IFC / Metro / Step 18 / Step 19 regressions are green.

## 24. Non-goals

Step 20 does not implement:

- D5 reconstruction integration/proof (Step 21);
- task-scoped aspect/fidelity upgrade proof (Step 22);
- `acme:*` enterprise vocabulary;
- multi-hop mapping;
- regex/glob matching;
- LLM classification;
- confidence scoring/heuristics;
- durable cross-session semantic identity;
- full geometry projection;
- Host write behavior;
- remote `semantic.project_facts` MCP transport;
- Revit/Tekla enterprise rules beyond proving the generic architecture can support them later.

## 25. Phase boundary

```text
Step 18
  freeze NormalizedDesignFact

Step 19
  AutoCAD native snapshot
    -> NormalizedDesignFactBatch

Step 20
  NormalizedDesignFactBatch
    -> pinned facts-v1 Enterprise Projection Provider
    -> SemanticClaim(ifc:IfcWall)

Step 21
  prove A-WALL -> IfcWall through D5 path
  with no D5 enterprise rule/code changes

Step 22
  prove progressive reconstruction upgrades
  only required aspects/fidelity
```

This keeps Host/provider expansion close to O(N) and prevents enterprise conventions from accumulating in the collaboration kernel.
