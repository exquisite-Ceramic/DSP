# Step 21 — D5 Canonical Projection Proof Design

> Status: Approved design baseline  
> Date: 2026-08-29  
> Branch: `feat/step21-d5-canonical-projection-proof`  
> Base: `main@0ce330abb10a33ae85025f516554d95386480fb5`  
> Master spec: `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step 21 proves the architecture assembled in Steps 18–20 reaches the existing D5 progressive semantic barrier without teaching D5 any AutoCAD, enterprise-layer, or provider-specific rule.

The required proof is:

```text
AutoCAD native snapshot
  -> Step 19 DesignFactAdapter
  -> NormalizedDesignFactBatch
  -> Step 20 SemanticService.project_facts()
  -> canonical SemanticClaim(ifc:IfcWall)
  -> existing D5 reconstruction boundary
  -> existing FreshnessResolver
  -> PlanningSnapshot with fresh canonical CLASSIFICATION
```

The success condition is intentionally stronger than “an integration test passes.” Step 21 must demonstrate that a new enterprise mapping rule can change semantic meaning upstream while D5 production code remains unchanged.

## 2. Master-spec alignment

The v0.6 master spec assigns the authoritative owners as follows:

- Host Application owns design-time native state.
- Semantic Service + pinned Providers own semantic definitions and mappings.
- D5 owns the task-scoped canonical semantic projection.
- D5 uses progressive, task-scoped, aspect-scoped, coverage-scoped, on-demand reconstruction.
- DSP Core may understand canonical vocabulary such as `ifc:IfcWall` but must not understand Host-native or enterprise conventions such as AutoCAD handles or `A-WALL` layer rules.

Therefore Step 21 must not move `A-WALL` knowledge into D5, Orchestrator, Semantic Runtime, IFC provider, Metro provider, or any shared Core module.

## 3. Decision

### 3.1 Chosen approach: contract-level end-to-end proof

Step 21 will add a test-only composition path that uses the real Step 19 adapter, the real Step 20 Semantic Service projection API, the real enterprise mapping provider, and the existing D5 `FreshnessResolver` reconstruction callback.

No D5 production interface is added or modified.

The test composition layer is allowed to translate already-canonical `SemanticClaim` output into the existing D5 `ReconstructionResult` envelope because the existing D5 API explicitly defines reconstruction as an injected callback. This translation is test orchestration, not a new production semantic owner.

### 3.2 Rejected: D5 imports `SemanticClaim`

`SemanticClaim` currently belongs to the `semantic_service` package while `semantic-runtime` intentionally has zero package dependencies. Making D5 import Semantic Service solely for this proof would reverse the desired dependency direction and prematurely freeze a production claim-ingestion contract.

### 3.3 Rejected: Orchestrator interprets claims

The Orchestrator must not become the owner of semantic reconstruction or enterprise mappings. It may coordinate later workflows, but it must not interpret `A-WALL`, select `IfcWall`, or upgrade assurance/fidelity.

### 3.4 Rejected: new D5 claim store

Step 21 does not justify introducing a persistent or in-memory canonical claim store. The roadmap requirement is to prove the existing D5 progressive reconstruction boundary can consume the result of Steps 19–20. A durable projection store, if needed, requires a separate design and lifecycle contract.

## 4. Frozen end-to-end scenario

The positive reference scenario is one synthetic AutoCAD native snapshot:

```json
{
  "hostInstanceId": "autocad-session-1",
  "documentId": "C:/models/station.dwg",
  "revision": 42,
  "entities": [
    {
      "nativeId": "A31",
      "nativeKind": "LWPOLYLINE",
      "layer": "A-WALL"
    }
  ]
}
```

Step 19 must produce a `NormalizedDesignFactBatch` containing the classification fact:

```text
fact_kind     = CLASSIFICATION
predicate     = layer
source_scheme = autocad.layer
source_code   = A-WALL
subject       = native AutoCAD subject A31
```

Step 20 must project exactly the canonical classification claim already frozen by PR #13:

```text
predicate         = classification
canonical_term_id = ifc:IfcWall
assurance         = RULE_DERIVED
provider_id       = dsp.enterprise.mapping
provider_version  = 1.0.0
```

D5 must never inspect the source layer code to decide that the subject is a wall.

## 5. D5 operation requirement

The Step 21 proof uses a classification-only operation freshness requirement:

```text
aspect            = CLASSIFICATION
geometry_level    = NONE
minimum_coverage  = RESOLVED
semantic_depth    = CANONICAL
minimum_assurance = RULE_DERIVED
```

This requirement is deliberate:

- `RULE_DERIVED` is the exact assurance emitted by the enterprise mapping provider.
- Step 21 must not upgrade `RULE_DERIVED` to `STANDARD_MAPPED` or `NATIVE_ASSERTED`.
- Classification is canonical because the claim is `ifc:IfcWall`.
- Geometry remains `NONE`; Step 21 does not need wall geometry.
- Coverage is `RESOLVED` only for the requested target/aspect represented by the proof fixture.

Step 22, not Step 21, owns proving that tasks request only the aspects/fidelity they actually need and upgrade requirements only when justified.

## 6. Existing D5 boundary used unchanged

Step 21 uses the existing API shape:

```python
FreshnessResolver.resolve(
    contract,
    expected_host_revision="42",
    reconstruct=reconstruct,
)
```

The reconstruction callback returns the already-existing:

```python
ReconstructionResult(
    document_ref=...,
    host_revision=...,
    coverage=...,
    guarantees=(...),
    projection_ref=...,
    semantic_environment_ref=...,
)
```

The positive case must provide one `AspectGuarantee`:

```python
AspectGuarantee(
    SemanticAspect.CLASSIFICATION,
    geometry_level=GeometryLevel.NONE,
    coverage_state=CoverageState.RESOLVED,
    semantic_depth=SemanticDepth.CANONICAL,
    assurance_level=AssuranceLevel.RULE_DERIVED,
)
```

No new D5 enum, DTO, resolver branch, or assurance level is introduced.

## 7. Pinned Semantic Environment

The proof must use an exact pinned environment containing:

```text
buildingSMART.ifc43@4.3.2.0
dsp.enterprise.mapping@1.0.0
```

The environment must be constructed by the real `SemanticProviderRegistry` + `SemanticEnvironmentStore.pin()` path.

The `SemanticEnvironmentRef` passed into D5 must copy exactly:

```text
environment.environment_id
environment.content_hash
```

This preserves the master-spec rule that planning state binds the exact Semantic Environment used for reconstruction.

## 8. SemanticProjectionRef in Step 21

`SemanticProjectionRef` is required by the existing D5 `ReconstructionResult`. Step 21 will provide a deterministic test projection reference, but it will **not** declare a new production hashing standard.

The test helper may derive deterministic values from the exact test inputs using canonical JSON serialization:

- `normalized_fact_batch_hash`: SHA-256 of `NormalizedDesignFactBatch.to_dict()` serialized with sorted keys and compact separators.
- `projection_hash`: SHA-256 of the pinned environment identity plus the projected canonical claim payload used by this proof.
- `projection_id`: test-scoped content-addressed identifier derived from `projection_hash`.
- `provider_set_hash` and `mapping_profile_set_hash`: deterministic test fixture digests over the exact pinned provider identities/content hashes relevant to this proof.
- `semantic_model_version`: a test fixture value identifying the Step 21 proof contract.

These values exist only to satisfy and exercise the already-frozen D5 lineage fields. Step 21 must not add a production helper under `platform/semantic_runtime`, `platform/semantic_service`, or another shared package that silently freezes this hashing algorithm.

If the project later needs a production-wide `SemanticProjectionRef` construction contract, that must be designed explicitly and versioned independently.

## 9. Positive acceptance case

The positive end-to-end test must prove all of the following in one chain:

1. The AutoCAD snapshot is normalized by the real `DesignFactAdapter`.
2. The normalized batch contains the expected `autocad.layer/A-WALL` classification fact.
3. The real pinned Semantic Environment contains IFC4.3 + Enterprise Mapping.
4. The real `SemanticService.project_facts()` returns exactly one applicable wall classification claim for A31.
5. The claim has `canonical_term_id == "ifc:IfcWall"`.
6. The claim assurance is exactly `RULE_DERIVED`.
7. The reconstruction callback derives the D5 classification guarantee from the existence and assurance of the canonical classification claim, not from `A-WALL` directly.
8. The existing `FreshnessResolver` accepts the result.
9. The resulting snapshot is a `PLANNING` snapshot.
10. The snapshot binds the exact D5 `SemanticEnvironmentRef` copied from the pinned environment.
11. The snapshot contains a `CLASSIFICATION` guarantee with:
    - `coverage_state == RESOLVED`
    - `semantic_depth == CANONICAL`
    - `assurance_level == RULE_DERIVED`
    - `geometry_level == NONE`
12. The snapshot `SemanticProjectionRef.normalized_fact_batch_hash` is populated by the deterministic test helper.
13. The D5 DirtyMap marks only the requested classification aspect fresh for the covered target.

## 10. Negative acceptance cases

### 10.1 Near-match enterprise codes do not satisfy D5 classification

At minimum, test:

```text
A-WALLISH
X-A-WALL
```

For each code:

- Step 19 still produces a normalized source classification fact.
- Step 20 produces no `ifc:IfcWall` claim.
- The test reconstruction callback must not fabricate a `CLASSIFICATION` guarantee.
- The existing D5 barrier must fail closed with `FreshnessUnsatisfiedError` for `CLASSIFICATION.freshness`.
- DirtyMap must remain dirty for the classification aspect.

This proves D5 freshness follows canonical semantic evidence, not mere availability of source facts.

### 10.2 Assurance is not silently strengthened

A dedicated assertion must prove the Step 20 `RULE_DERIVED` claim becomes a D5 `RULE_DERIVED` guarantee and is never raised to `STANDARD_MAPPED` or `NATIVE_ASSERTED`.

### 10.3 Stronger operation requirement fails closed

A contract requiring:

```text
minimum_assurance = STANDARD_MAPPED
```

against the same A-WALL proof data must fail with `FreshnessUnsatisfiedError` for `CLASSIFICATION.assurance`.

This proves the D5 progressive barrier remains authoritative even when canonical classification exists.

## 11. Test-composition responsibility

The Step 21 integration test may contain a small private helper that converts the projected canonical claims into D5 reconstruction evidence.

That helper may understand only provider-neutral/canonical fields needed by D5:

```text
claim.subject
claim.predicate
claim.canonical_term_id
claim.assurance
claim.provenance/evidence
```

It must not contain:

```text
A-WALL matching logic
autocad.layer matching logic
IfcWall selection logic based on Host fields
enterprise provider implementation branches
Metro-specific branches
Host product branches
```

The helper may recognize that a canonical claim whose predicate is `classification` contributes to the D5 `CLASSIFICATION` aspect. That is a canonical structural mapping, not an enterprise rule.

## 12. Production-code boundary

Step 21 is designed to require **zero production-code changes**.

The implementation PR must not modify production files under:

```text
contracts/
hosts/autocad/
platform/orchestrator/
platform/semantic_mcp/
platform/semantic_runtime/
platform/semantic_service/
providers/semantics/dsp_core/
providers/semantics/enterprise_mapping/
providers/semantics/ifc43/
providers/semantics/metro_v32/
platform/changeset/
```

Allowed implementation changes are limited to:

```text
docs/superpowers/specs/
docs/superpowers/plans/
tests/
.github/workflows/
```

The PR CI must contain a changed-file boundary gate that fails if Step 21 modifies a prohibited production path.

## 13. Architecture guards

Step 21 must add regression guards that prove:

1. `platform/semantic_runtime/` contains none of:
   - `A-WALL`
   - `autocad.layer`
   - `dsp.enterprise.mapping`
2. `platform/orchestrator/` contains none of those enterprise/Host mapping constants.
3. No Step 21 test helper imports the concrete AutoCAD plugin/.NET implementation; it may use the existing Python sidecar adapter because that is the Step 19 contract edge under test.
4. D5 production source does not import `semantic_service` or `enterprise_mapping_provider` as a consequence of Step 21.
5. Orchestrator production source does not import `enterprise_mapping_provider` or contain claim-to-wall logic.
6. The Enterprise Mapping YAML remains the only production owner of the `A-WALL -> ifc:IfcWall` rule.

## 14. CI boundary

A dedicated Step 21 workflow should run the smallest complete proof first, then relevant regressions.

Required categories:

```text
1. changed-file boundary gate
2. Step 21 positive/negative E2E proof tests
3. semantic-runtime progressive/freshness regression
4. semantic-service projection regression
5. enterprise mapping provider regression
6. Step 19 AutoCAD design-fact adapter regression
7. architecture guards
```

The workflow must use the same Python import strategy needed by the existing semantic-provider workflows to avoid duplicate test-module basename collisions.

Live AutoCAD integration is not required for Step 21; the synthetic native snapshot is sufficient because Step 19 already separately proves the plugin/sidecar extraction contract.

## 15. Non-goals

Step 21 does not:

- add a new Semantic MCP endpoint;
- add a D5 `SemanticClaim` store;
- add a new production `SemanticProjectionRef` builder;
- define a global canonical projection persistence format;
- create or stabilize a cross-session SemanticId for AutoCAD A31;
- change the enterprise A-WALL mapping rules;
- add Metro mappings;
- add IFC schema terms;
- add Revit/Tekla mappings;
- request or reconstruct geometry;
- infer thickness or other wall properties;
- create a ChangeSet;
- perform Host mutation;
- implement Step 22 task-driven aspect/fidelity minimization.

## 16. Expected implementation files

The subsequent implementation plan should prefer a minimal set such as:

```text
tests/integration/test_step21_d5_canonical_projection.py
# optional focused architecture guard file if separation improves clarity
# tests/semantic_runtime/test_step21_architecture.py
.github/workflows/step21-d5-canonical-projection.yml
docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md
```

Exact test file placement may be refined in the implementation plan, but production paths remain frozen as prohibited.

## 17. Completion criterion

Step 21 is complete only when the repository can prove:

```text
A-WALL
  -> autocad.layer source classification
  -> NormalizedDesignFact
  -> Enterprise Mapping Provider
  -> ifc:IfcWall canonical SemanticClaim
  -> existing D5 reconstruction callback boundary
  -> CLASSIFICATION guarantee
  -> existing FreshnessResolver
  -> PlanningSnapshot
```

while simultaneously proving:

```text
D5 production diff = 0
Orchestrator production diff = 0
Enterprise rule duplication outside provider = 0
Assurance inflation = 0
Geometry reconstruction = 0
```

That is the architectural proof Step 21 is intended to deliver.