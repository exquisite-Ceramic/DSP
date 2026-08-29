# Enterprise A-WALL Mapping Provider Design

> Phase E — Step 20  
> Status: Design freeze candidate  
> Date: 2026-08-29  
> Base: `main@33dc9371346539135c51acdcd1521b1dc759fe9d`  
> Parent work: Step 18 `NormalizedDesignFact` contract; Step 19 AutoCAD native fact extractor

## 1. Goal

Phase E Step 20 introduces the first enterprise semantic projection from Host-normalized evidence into a canonical semantic claim.

The required proof case is:

```text
AutoCAD native entity
  -> layer = A-WALL / A-WALL-*
  -> NormalizedDesignFact CLASSIFICATION evidence
  -> pinned Enterprise Semantic Provider
  -> ifc:IfcWall SemanticClaim
```

The implementation must preserve the v0.6 architecture boundary:

- AutoCAD plugin/sidecar knows AutoCAD facts, but does not know enterprise meaning.
- `NormalizedDesignFact` transports structured source evidence, but does not decide final semantics.
- Enterprise Provider owns enterprise mapping rules such as `autocad.layer / A-WALL-* -> ifc:IfcWall`.
- Semantic Service owns pinned-environment routing and provider conformance, but does not own the mapping rule.
- IFC4.3 Provider remains authoritative for the meaning of `ifc:*` terms.
- D5 consumes canonical claims/projection results and does not contain `A-WALL`, AutoCAD layer logic, or enterprise mapping tables.

This step freezes the Phase E projection contract that was intentionally deferred when Semantic Service Core was introduced.

## 2. Why this is an architectural step

Step 20 is the first point where a low-semantic Host-native classification fact becomes a canonical classification through an enterprise rule.

A wrong boundary here would make later Host support grow in the platform core:

```text
if host == "autocad" and layer.startswith("A-WALL"):
    return "ifc:IfcWall"
```

That is explicitly forbidden by the v0.6 hub-and-spoke/core-boundary rules.

The Step 20 contract therefore has to be reusable for later examples such as:

```text
Revit native category evidence
  -> Enterprise Provider
  -> canonical IFC term

Tekla native class evidence
  -> Enterprise Provider
  -> canonical IFC term
```

without modifying Semantic Service or D5 for each Host convention.

## 3. Existing contracts and the Phase E seam

### 3.1 Step 18 input contract

`NormalizedDesignFact` already carries the source evidence needed for this proof:

```text
fact_kind
predicate
value
source_scheme
source_code
host_ref
source_revision
subject_native_ref
provenance
```

Step 19 emits AutoCAD classification evidence as:

```text
fact_kind     = CLASSIFICATION
predicate     = layer
value         = <actual layer>
source_scheme = autocad.layer
source_code   = <actual layer>
```

For an A-WALL entity this is still only native evidence. Step 19 must never map it to IFC.

### 3.2 Existing `SemanticClaim`

Semantic Service currently defines `SemanticClaim` as provider-neutral semantic output:

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

The main spec describes this as the unified claim emitted by providers. It must remain an output semantic DTO; it must not be repurposed as a hidden container for `source_scheme/source_code` ingestion fields.

### 3.3 Deferred `SemanticProjectionProvider`

Phase C deliberately froze `SemanticProjectionProvider` only as a manifest capability marker and deferred the concrete `project_facts()` payload until Phase E, when `NormalizedDesignFactBatch` existed.

Step 20 consumes that seam.

## 4. Architectural decision

Use a **provider-neutral projection gate**:

```text
NormalizedDesignFactBatch
        |
        v
SemanticService.project_facts(...)
        |
        +-- pinned PROJECTION provider A
        +-- pinned PROJECTION provider B
        +-- pinned Enterprise Projection Provider
                            |
                            v
                       SemanticClaim[]
        |
        v
caller / later D5 integration
```

The key rule is:

```text
NormalizedDesignFactBatch = provider input
SemanticClaim             = provider output
```

The existing mapping API remains unchanged:

```text
SemanticClaim -> find_mappings() -> MappingCandidate[]
```

Step 20 does not overload that API with pre-canonical source evidence.

## 5. Rejected alternatives

### 5.1 Extend `SemanticClaim` with `source_scheme/source_code`

Rejected.

It would mix two abstraction levels in one DTO:

```text
pre-semantic ingestion evidence
+
canonical semantic claim
```

It also inverts the main-spec rule that providers emit claims.

### 5.2 Encode source evidence in claim strings

Rejected examples:

```text
predicate = "autocad.layer"
value = "A-WALL"
```

or:

```text
evidence = ("autocad.layer:A-WALL",)
```

and ask providers to parse those strings.

That would discard the typed Step 18 boundary and create stringly-typed coupling.

### 5.3 Add A-WALL handling to AutoCAD sidecar or D5

Rejected.

The sidecar owns normalization, not enterprise semantics. D5 owns canonical progressive projection state, not enterprise mapping tables.

## 6. Projection provider contract

Step 20 freezes `SemanticProjectionProvider` as a runtime-checkable capability protocol:

```python
@runtime_checkable
class SemanticProjectionProvider(SemanticProvider, Protocol):
    def project_facts(
        self,
        facts: NormalizedDesignFactBatch,
    ) -> tuple[SemanticClaim, ...]: ...
```

Design requirements:

1. input is the frozen Step 18 batch contract;
2. output is immutable `SemanticClaim` values;
3. provider execution must be deterministic for the same provider content + same batch;
4. provider must not mutate the input batch;
5. provider may emit zero, one, or multiple claims;
6. no provider may directly mutate D5 state;
7. no projection provider receives a concrete Host SDK object or Host-native API type.

### 6.1 Dependency direction

`semantic_service` may depend on the stable Python `design_fact_contracts` package because the Phase E projection contract explicitly consumes `NormalizedDesignFactBatch`.

The dependency direction is:

```text
design_fact_contracts
      ^
      |
semantic_service provider protocol
      ^
      |
enterprise semantic provider
```

`design_fact_contracts` must not import Semantic Service.

`semantic_runtime` / D5 must not import AutoCAD sidecar modules.

## 7. Semantic Service projection routing

Add the logical service method:

```python
SemanticService.project_facts(
    facts: NormalizedDesignFactBatch,
    environment_id: str,
) -> tuple[SemanticClaim, ...]
```

The service owns only orchestration/conformance:

1. load the exact pinned `SemanticEnvironment`;
2. iterate selected providers in deterministic pinned `(provider_id, version)` order;
3. call only providers declaring `SemanticCapability.PROJECTION`;
4. require each such provider to implement `SemanticProjectionProvider`;
5. fail closed if a provider raises;
6. validate each returned item is a `SemanticClaim`;
7. validate returned `provider_id` and `provider_version` exactly match the pinned provider that emitted it;
8. aggregate without silently collapsing conflicts;
9. sort deterministically.

The service must not contain any logic equivalent to:

```text
autocad
A-WALL
A-WALL-
IfcWall
```

### 7.1 Claim ordering

Aggregate projection results using a deterministic ordering key:

```text
subject
predicate or ""
canonical_term_id or ""
provider_id or ""
provider_version or ""
evidence tuple
```

Ordering is for reproducibility only. It does not assign authority or semantic preference.

### 7.2 Fail-closed behavior

If any selected projection provider fails, `project_facts()` fails instead of returning a silent partial projection.

This matches existing mapping/validation behavior and prevents a task from appearing semantically complete when one pinned provider was unavailable.

## 8. Registry conformance change

The current registry validates VOCABULARY, MAPPING, and VALIDATION implementations but intentionally treats PROJECTION as a marker.

Step 20 ends that temporary exception.

If a manifest declares:

```text
SemanticCapability.PROJECTION
```

registration must require the object to satisfy `SemanticProjectionProvider`.

This is a provider-neutral contract change. It contains no enterprise or AutoCAD knowledge.

Existing providers that currently declare PROJECTION but do not implement `project_facts()` must either:

- implement a deterministic no-op projection returning `()` when projection is not yet in their Step 20 scope; or
- stop declaring PROJECTION until they implement it.

For this baseline, prefer the smallest truthful capability declaration. A provider must not claim a callable capability it does not implement.

## 9. Enterprise provider package

Create a dedicated provider package:

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

Tests live under:

```text
tests/semantic_providers/enterprise_mapping/
```

The package must not import AutoCAD plugin or sidecar modules. Its only Host knowledge comes from stable source-scheme tokens carried by `NormalizedDesignFact`.

## 10. Enterprise provider manifest

Freeze the initial manifest as:

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

requires:
  buildingSMART.ifc43@4.3.2.0
```

Rationale:

- buildingSMART IFC provider remains the sole authoritative owner of `ifc:*` term meaning;
- enterprise provider contributes deterministic projection behavior involving IFC terms;
- the enterprise provider is not an IFC vocabulary replacement;
- the dependency guarantees the pinned environment includes the exact IFC baseline used by the rules.

Step 20 does not introduce an `acme:*` authoritative vocabulary.

## 11. Why no `acme:*` intermediate term in Step 20

The main spec gives a valid future example:

```text
A-WALL-EXT
  -> acme:ExteriorWall
  -> ifc:IfcWall
```

but the Phase E acceptance proof is narrower:

```text
A-WALL-* -> ifc:IfcWall
```

Introducing `acme:*` now would also require:

- an enterprise vocabulary authority;
- term schemas/descriptions;
- multi-hop mapping resolution policy;
- additional conflict rules.

Those are real future capabilities but are not necessary to prove the enterprise projection seam. Step 20 therefore projects directly to the canonical IFC term while keeping the provider architecture capable of adding enterprise vocabulary later.

## 12. Machine-owned rule source

Enterprise mappings must be data-driven and content-addressed, not hardcoded in Python branches.

Use a packaged YAML source following the existing Metro provider source-loading pattern.

Conceptual source:

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

### 12.1 Matching semantics

Freeze the supported Step 20 match kinds to:

```text
EXACT
PREFIX
```

No regex/glob language is introduced in this step.

Rules are evaluated only against `source_code` after an exact `source_scheme` match.

For the frozen A-WALL rules:

```text
A-WALL       -> match
A-WALL-EXT   -> match
A-WALL-INT   -> match
a-wall-ext   -> match
A-WALLISH    -> no match
X-A-WALL     -> no match
```

This prevents an overly broad `startswith("A-WALL")` rule from accepting unrelated codes.

### 12.2 Rule validation

Catalog construction fails closed for:

- duplicate `mapping_id`;
- blank source scheme/pattern/target term;
- unsupported match type;
- non-boolean `case_sensitive`;
- target not using `namespace:local` shape;
- assurance outside the frozen assurance vocabulary;
- contradictory duplicate rule definitions that would make exact source evidence nondeterministic.

### 12.3 Content hash

The provider `content_hash` must derive from canonical machine semantics, including:

- normalized metadata that affects interpretation;
- ordered canonical rule records;
- source scheme;
- match type/pattern/case sensitivity;
- target term;
- assurance.

Changing presentation comments/descriptions alone must not change machine semantic identity.

A reviewed golden content hash is frozen in code/tests, following the Metro provider pattern.

## 13. Input fact selection

The Enterprise Provider only considers facts satisfying all of:

```text
fact_kind     == CLASSIFICATION
source_scheme is not None
source_code   is not None
```

For the A-WALL rules it then requires:

```text
source_scheme == "autocad.layer"
```

The provider must not infer source code from free-form `value`, `predicate`, or provenance text when `source_code` is absent.

This preserves the structured Step 18 contract.

Facts of kind IDENTITY, BOUNDS, PROPERTY, GEOMETRY, PLACEMENT, or RELATIONSHIP are ignored by the A-WALL rules.

## 14. Subject locator

Projection needs a stable-in-batch subject reference without pretending to create a canonical `SemanticId`.

Freeze the Step 20 native locator format:

```text
native://<host_type>/<host_instance_id>/<url-encoded-document_id>/<url-encoded-native_id>
```

For Step 19 AutoCAD facts:

```text
native://autocad/<session-uuid>/<encoded-document>/<handle>
```

Rules:

- `host_type`, `host_instance_id`, `document_id`, and `native_id` come only from the NDF contract;
- document/native segments use UTF-8 URL percent encoding with no path-safe characters preserved except the URI separators owned by the format;
- this locator is a projection subject address, not semantic identity;
- a Host restart may change `host_instance_id`; Step 20 does not attempt durable cross-session identity reconciliation;
- D5 identity binding remains a later owner.

## 15. Output claim for A-WALL

A matching fact produces one classification claim:

```text
subject            = <native locator>
predicate          = classification
canonical_term_id  = ifc:IfcWall
value              = None
unit               = None
assurance          = RULE_DERIVED
provider_id        = dsp.enterprise.mapping
provider_version   = 1.0.0
```

### 15.1 Evidence

Freeze claim evidence as two ordered items:

```text
design-fact:<fact_id>
mapping:<mapping_id>
```

This makes the semantic derivation inspectable without requiring the caller to parse prose.

### 15.2 Provenance

The claim preserves the source fact provenance tuple verbatim:

```text
claim.provenance = source_fact.provenance
```

Provider identity/version are carried in the dedicated claim fields and checked by Semantic Service against the pinned provider.

The environment supplies the immutable provider content-hash binding; `SemanticClaim` is not expanded with a duplicate `provider_content_hash` field in Step 20.

## 16. Duplicate and conflict behavior

The provider may receive multiple classification facts for the same native subject.

### 16.1 Exact duplicate semantic derivations

If multiple facts would emit byte-equivalent semantic claims except for evidence/provenance, do not silently erase source evidence.

Step 20 keeps one claim per matched input fact/rule derivation. The service sorts deterministically but does not merge them.

Later D5 projection logic may decide how multiple evidence records support one canonical aspect.

### 16.2 Conflicting enterprise rules

If one source fact matches multiple active enterprise rules that produce different target terms or assurance values, catalog/provider evaluation fails closed rather than selecting one by order.

Rule order in YAML is not semantic priority.

## 17. IFC authority and validation boundary

The Enterprise Provider may emit `ifc:IfcWall` only because its manifest pins the exact IFC provider dependency:

```text
buildingSMART.ifc43@4.3.2.0
```

However, Step 20 does not make `SemanticService.project_facts()` automatically call `resolve_term()` for every emitted claim.

Reasons:

- projection routing and vocabulary resolution are separate capabilities;
- automatic nested provider calls would complicate failure semantics and duplicate work;
- provider conformance tests can prove all packaged targets resolve in the required IFC provider;
- the pinned environment already guarantees the required provider version is present.

Add conformance tests that every enterprise target term resolves under the required IFC provider baseline.

## 18. Metro semantics boundary

Metro Semantic remains useful to the overall architecture but is not the owner of `autocad.layer / A-WALL` enterprise convention.

Step 20 must not:

- add A-WALL mapping logic to `metro_v32`;
- change Metro source data to encode enterprise layer conventions;
- treat Metro as a Host adapter;
- change IFC authority.

Metro remains a DOMAIN provider layered on IFC4.3. Enterprise mapping is a separate ENTERPRISE provider.

## 19. MCP boundary

Step 20 adds no new Semantic MCP endpoint.

The main spec allows a future:

```text
semantic.project_facts
```

but does not require bulk projection to be remotely exposed in this baseline.

The logical in-process Semantic Service contract is enough to prove provider architecture first. A later MCP adapter may expose the same contract without changing provider meaning.

## 20. D5 boundary

Step 20 does not modify D5.

It only creates the provider-neutral projection capability and the enterprise provider that can emit canonical claims.

Phase E Step 21 is the explicit extensibility proof that wires the result through the D5 reconstruction path and demonstrates:

```text
A-WALL / A-WALL-*
  -> ifc:IfcWall
```

with zero D5 Core source changes attributable to the enterprise mapping rule.

Do not pull that D5 integration proof into Step 20.

## 21. Expected repository changes

Provider-neutral contract changes:

```text
platform/semantic_service/
  pyproject.toml
  src/semantic_service/
    providers.py
    registry.py
    service.py
    __init__.py
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
tests/semantic_service/
  test_provider_contracts.py
  test_registry.py
  test_service_projection.py
  test_provider_provenance_boundary.py

tests/semantic_providers/enterprise_mapping/
  test_source.py
  test_catalog.py
  test_projection.py
  test_manifest.py
  test_service_integration.py
  test_architecture.py
  test_target_ifc_conformance.py
```

CI may add a focused Enterprise Semantic Provider workflow consistent with the existing IFC/Metro provider workflows.

No Step 20 production change is expected under:

```text
hosts/autocad/
platform/semantic_runtime/
providers/semantics/metro_v32/
providers/semantics/ifc43/
platform/orchestrator/
```

except test-only references needed to prove architecture boundaries.

## 22. Testing strategy

Implementation must follow TDD.

### 22.1 Projection contract tests

- a provider claiming PROJECTION must implement `project_facts()`;
- a no-PROJECTION provider is never called;
- providers are called in deterministic pinned order;
- output is deterministically sorted;
- provider exception aborts the projection instead of returning partial claims;
- forged provider id/version in output fails closed;
- input batch remains unchanged.

### 22.2 Enterprise source/catalog tests

- root metadata is exact;
- duplicate mapping IDs fail;
- unsupported match kinds fail;
- invalid assurance fails;
- rule semantic change changes content hash;
- presentation-only changes do not change machine hash where applicable;
- golden content hash matches reviewed source.

### 22.3 A-WALL projection tests

Given a valid Step 18 classification fact:

```text
source_scheme = autocad.layer
source_code = A-WALL
```

expect one claim targeting:

```text
ifc:IfcWall
```

Also prove:

```text
A-WALL-EXT  -> ifc:IfcWall
A-WALL-INT  -> ifc:IfcWall
a-wall-ext  -> ifc:IfcWall
A-WALLISH   -> no claim
X-A-WALL    -> no claim
```

### 22.4 Structured-evidence tests

- `value="A-WALL"` without `source_scheme/source_code` does not map;
- provenance text containing `A-WALL` does not map;
- non-CLASSIFICATION facts do not map;
- another source scheme with source code `A-WALL` does not map.

### 22.5 Authority/dependency tests

- enterprise provider type is ENTERPRISE;
- it declares only IFC EXTENSION authority;
- it requires exact `buildingSMART.ifc43@4.3.2.0`;
- environment pinning fails if required IFC provider is absent;
- all target IFC terms resolve through the selected IFC provider.

### 22.6 Architecture tests

Production source must prove:

- no `Autodesk.*` import outside Host Native boundary is introduced;
- Enterprise Provider imports no AutoCAD plugin/sidecar package;
- Semantic Service core contains no `A-WALL` or `IfcWall` mapping rule;
- D5/semantic runtime contains no `A-WALL` or `autocad.layer` enterprise logic;
- Metro provider contains no A-WALL mapping rule;
- AutoCAD sidecar still emits source evidence only and contains no `IfcWall` enterprise mapping.

## 23. Acceptance criteria

Step 20 is complete when all are true:

1. `SemanticProjectionProvider.project_facts(NormalizedDesignFactBatch)` is frozen as the Phase E projection capability contract.
2. Semantic Provider Registry enforces real PROJECTION implementation for manifests that claim it.
3. `SemanticService.project_facts()` performs pinned deterministic provider fan-out and fails closed.
4. A dedicated `dsp.enterprise.mapping@1.0.0` ENTERPRISE provider exists.
5. The provider has IFC EXTENSION authority and exact dependency on `buildingSMART.ifc43@4.3.2.0`.
6. Enterprise mapping rules are packaged machine data with deterministic content hashing, not Python Host branches.
7. `autocad.layer / A-WALL` projects to `ifc:IfcWall`.
8. `autocad.layer / A-WALL-*` projects to `ifc:IfcWall` using exact frozen prefix semantics.
9. Similar but invalid codes such as `A-WALLISH` do not map.
10. Mapping decisions use structured `source_scheme/source_code`, never evidence-string parsing.
11. Output assurance is `RULE_DERIVED` and evidence identifies both source fact and mapping rule.
12. Projection creates no `SemanticId` and does not perform durable identity reconstruction.
13. AutoCAD plugin/sidecar, Metro provider, IFC provider, and D5 Core receive no enterprise mapping implementation.
14. No new Semantic MCP endpoint is required.
15. Target IFC terms are conformance-tested against the required IFC provider.
16. Focused tests plus relevant existing Semantic Service/IFC/Metro/Step 18/Step 19 regressions are green.

## 24. Explicit non-goals

Step 20 does not implement:

- D5 reconstruction integration/proof (Step 21);
- task-scoped aspect/fidelity upgrade proof (Step 22);
- enterprise `acme:*` vocabulary;
- multi-hop semantic mapping;
- regex/glob mapping language;
- LLM-based classification;
- confidence scoring or heuristic matching;
- cross-session durable semantic identity;
- full geometry projection;
- AutoCAD write behavior;
- remote `semantic.project_facts` MCP transport;
- enterprise rules for Revit/Tekla beyond architecture extensibility.

## 25. Phase boundary after Step 20

The intended progression remains:

```text
Step 18
  freeze NormalizedDesignFact

Step 19
  AutoCAD native snapshot -> NormalizedDesignFactBatch

Step 20
  NormalizedDesignFactBatch
    -> pinned Enterprise Projection Provider
    -> canonical SemanticClaim(ifc:IfcWall)

Step 21
  prove A-WALL -> IfcWall through D5 path
  with no D5 rule/code changes

Step 22
  prove progressive reconstruction upgrades
  only required aspects/fidelity
```

This boundary keeps the platform extensible in O(N) Host/provider integrations instead of accumulating Host-specific rules in the collaboration kernel.
