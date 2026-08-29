# Enterprise A-WALL Mapping Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze and implement the Phase E fact-projection seam, then add a data-driven enterprise provider that projects Step 19 `autocad.layer / A-WALL*` classification evidence into provider-provenanced `SemanticClaim(canonical_term_id="ifc:IfcWall")` without changing AutoCAD, IFC, Metro, Semantic Runtime/D5, or Semantic MCP production code.

**Architecture:** `NormalizedDesignFactBatch` becomes the provider-neutral input to a versioned `SemanticProjectionProvider.project_facts()` contract. `SemanticService.project_facts()` calls only pinned providers that declare both `PROJECTION` and compatibility token `dsp.semantic.projection-facts.v1`; existing IFC/Metro marker-only PROJECTION providers remain unchanged and are ignored by this path. `dsp.enterprise.mapping@1.0.0` owns packaged YAML rules and emits canonical claims while IFC4.3 remains authoritative for the meaning of `ifc:*` terms.

**Tech Stack:** Python 3.11, pytest, `host-contracts` / `design_fact_contracts`, `semantic-service`, PyYAML 6.0.3, existing IFC4.3 provider for conformance, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-enterprise-a-wall-mapping-provider-design.md`

## Global Constraints

- Step 18 `NormalizedDesignFact` / `NormalizedDesignFactBatch` wire and in-process contracts MUST NOT change.
- Step 19 AutoCAD plugin/sidecar production code MUST NOT change.
- IFC4.3 and Metro provider production code/manifests MUST NOT change; their existing `PROJECTION` capability remains marker-only because they do not declare `dsp.semantic.projection-facts.v1`.
- Semantic Runtime / D5 production code MUST NOT change in Step 20. The D5 zero-change extensibility proof belongs to Step 21.
- Semantic MCP production code and tool surface MUST NOT change; Step 20 adds only the in-process logical `SemanticService.project_facts()` method.
- `SemanticClaim` MUST NOT gain `source_scheme` / `source_code`; those remain structured NDF input evidence.
- `semantic_service` MAY import `design_fact_contracts.NormalizedDesignFactBatch`, but MUST NOT re-export it from `semantic_service.__init__`.
- The Python dependency name is `host-contracts>=0.1.0`; do not invent a `design-fact-contracts` distribution.
- Semantic Service production code MUST contain no enterprise mapping constants such as `A-WALL`, `A-WALL-`, `autocad.layer`, or `ifc:IfcWall`.
- Enterprise rules are checked-in machine data, not Python product branches.
- Enterprise provider production code MUST NOT import `autocad_sidecar`, Autodesk/Revit/Tekla SDKs, `semantic_runtime`, `semantic_mcp`, Metro provider implementation code, IFC provider implementation code, or `ifcopenshell`.
- Enterprise provider manifest is exactly `dsp.enterprise.mapping@1.0.0`, type `ENTERPRISE`, namespace `ifc`, authority `EXTENSION`, capability `PROJECTION`, compatibility `dsp.semantic.projection-facts.v1`, exact dependency `buildingSMART.ifc43@4.3.2.0`.
- No `acme:*` namespace or intermediate enterprise vocabulary is introduced in Step 20.
- A matching A-WALL claim uses `assurance="RULE_DERIVED"`, preserves source fact provenance, and has ordered evidence `design-fact:<fact_id>`, `mapping:<mapping_id>`.
- Native subject locator is `native://<host_type>/<host_instance_id>/<urlencoded-document_id>/<urlencoded-native_id>` with every dynamic path segment encoded by `urllib.parse.quote(..., safe="")`; it is not a `SemanticId`.
- Matching supports only `EXACT` and `PREFIX`. A-WALL behavior is: `A-WALL`, `A-WALL-EXT`, `A-WALL-INT`, and case-insensitive equivalents match; `A-WALLISH` and `X-A-WALL` do not.
- Rule ordering is not priority. Conflicting overlapping rules fail closed.
- Keep the eventual PR unmerged until the user explicitly authorizes merge.

---

### Task 1: Freeze the versioned Semantic Service fact-projection seam

**Files:**
- Modify: `platform/semantic_service/pyproject.toml`
- Modify: `platform/semantic_service/src/semantic_service/providers.py`
- Modify: `platform/semantic_service/src/semantic_service/registry.py`
- Modify: `platform/semantic_service/src/semantic_service/service.py`
- Modify: `platform/semantic_service/src/semantic_service/__init__.py`
- Modify: `tests/semantic_service/helpers.py`
- Modify: `tests/semantic_service/test_provider_contracts.py`
- Modify: `tests/semantic_service/test_registry.py`
- Modify: `tests/semantic_service/test_semantic_service_public_surface.py`
- Create: `tests/semantic_service/test_service_projection.py`

**Interfaces:**

```python
FACT_PROJECTION_COMPATIBILITY = "dsp.semantic.projection-facts.v1"

@runtime_checkable
class SemanticProjectionProvider(SemanticProvider, Protocol):
    def project_facts(
        self,
        facts: NormalizedDesignFactBatch,
    ) -> tuple[SemanticClaim, ...]: ...
```

```python
class SemanticService:
    def project_facts(
        self,
        facts: NormalizedDesignFactBatch,
        environment_id: str,
    ) -> tuple[SemanticClaim, ...]: ...
```

- [ ] Add `host-contracts>=0.1.0` to `platform/semantic_service/pyproject.toml`.
- [ ] RED: add a `ProjectionProvider` fake in `tests/semantic_service/helpers.py` whose manifest declares `PROJECTION + dsp.semantic.projection-facts.v1`, records calls, and returns a supplied tuple of `SemanticClaim` values.
- [ ] RED: replace the old broad marker assertion with two explicit contract tests:

```python
def test_projection_marker_without_facts_v1_does_not_require_batch_api():
    provider = VocabularyProvider(claim_projection=True)
    assert SemanticCapability.PROJECTION in provider.manifest.capabilities
    assert FACT_PROJECTION_COMPATIBILITY not in provider.manifest.compatibility
    assert not isinstance(provider, SemanticProjectionProvider)


def test_facts_v1_projection_provider_implements_callable_protocol():
    provider = ProjectionProvider()
    assert FACT_PROJECTION_COMPATIBILITY in provider.manifest.compatibility
    assert isinstance(provider, SemanticProjectionProvider)
```

- [ ] RED: add registry tests proving (a) marker-only PROJECTION still registers; (b) compatibility token without PROJECTION fails `ProviderCapabilityError`; (c) token + PROJECTION without `project_facts()` fails; (d) a real facts-v1 projection provider registers.
- [ ] RED: create `tests/semantic_service/test_service_projection.py` with a minimal empty batch:

```python
from design_fact_contracts import NormalizedDesignFactBatch

EMPTY_BATCH = NormalizedDesignFactBatch(())
```

and prove:
  - only selected pinned facts-v1 projection providers are called;
  - marker-only PROJECTION providers are not called and are not failures;
  - provider call order is pinned `(provider_id, version)` order;
  - each provider-returned tuple order is preserved;
  - a provider exception aborts the operation rather than returning partial claims;
  - non-`SemanticClaim` output fails closed;
  - forged/missing `provider_id` or `provider_version` fails closed;
  - an empty environment or environment with no facts-v1 participant returns `()`.
- [ ] RED: update `test_semantic_service_public_surface.py` so `NormalizedDesignFactBatch` is still **not exported** by `semantic_service`, but its type name is no longer forbidden inside Semantic Service source. Continue forbidding `A-WALL`, `autocad.layer`, concrete provider imports, D5/semantic_runtime, MCP, Autodesk/Revit/Tekla leakage.
- [ ] Run the semantic-service projection/registry tests and verify RED because the callable protocol/token/service method do not yet exist.
- [ ] GREEN: in `providers.py`, import `NormalizedDesignFactBatch`, define/export `FACT_PROJECTION_COMPATIBILITY`, make `SemanticProjectionProvider` runtime-checkable, and add `project_facts()` exactly as frozen.
- [ ] GREEN: in `registry.py`, preserve existing VOCABULARY/MAPPING/VALIDATION checks and add only the versioned rule:

```python
if FACT_PROJECTION_COMPATIBILITY in manifest.compatibility:
    if SemanticCapability.PROJECTION not in manifest.capabilities:
        raise ProviderCapabilityError(...)
    if not isinstance(provider, SemanticProjectionProvider):
        raise ProviderCapabilityError(...)
```

Do **not** require callable projection from marker-only PROJECTION providers.
- [ ] GREEN: in `service.py`, add `project_facts()` that iterates pinned providers, selects only `PROJECTION + facts-v1`, calls the protocol, requires `tuple` output, requires each item is `SemanticClaim`, checks exact `provider_id/provider_version` against the emitter, preserves provider/result order, and wraps provider execution errors in `SemanticServiceError` with provider id/version and exception type.
- [ ] GREEN: export `FACT_PROJECTION_COMPATIBILITY` and `SemanticProjectionProvider` from `semantic_service`; do not export NDF classes.
- [ ] Run `pytest -q tests/semantic_service/test_provider_contracts.py tests/semantic_service/test_registry.py tests/semantic_service/test_service_projection.py tests/semantic_service/test_semantic_service_public_surface.py` GREEN.
- [ ] Run full `tests/semantic_service` GREEN and confirm existing IFC/Metro marker-only behavior remains registerable through their existing tests.
- [ ] Commit `feat(semantics): add versioned design fact projection seam`.

### Task 2: Build the immutable Enterprise Mapping Provider machine source and catalog

**Files:**
- Create: `providers/semantics/enterprise_mapping/pyproject.toml`
- Create: `providers/semantics/enterprise_mapping/README.md`
- Create: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/__init__.py`
- Create: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/errors.py`
- Create: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/model.py`
- Create: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/hashing.py`
- Create: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/source.py`
- Create: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/catalog.py`
- Create: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/golden.py`
- Create: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/data/enterprise_mappings_v1.yaml`
- Create: `tests/semantic_providers/enterprise_mapping/test_source_catalog.py`
- Create: `tests/semantic_providers/enterprise_mapping/test_hashing.py`
- Create: `tests/semantic_providers/enterprise_mapping/test_manifest.py`

**Machine source:**

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

**Immutable model:**

```python
class MatchType(str, Enum):
    EXACT = "EXACT"
    PREFIX = "PREFIX"

@dataclass(frozen=True, slots=True)
class EnterpriseMappingRule:
    mapping_id: str
    source_scheme: str
    match_type: MatchType
    pattern: str
    case_sensitive: bool
    target_term_id: str
    assurance: str
```

- [ ] RED: add source/catalog tests for exact metadata, two rule IDs, stable sorted rule ordering, supported enum values, and immutable records.
- [ ] RED: add fail-closed parametrized tests for duplicate IDs, blank source scheme/pattern/target, unsupported match type, non-boolean case sensitivity, malformed target without `namespace:local`, and assurance outside `{NATIVE_ASSERTED, STANDARD_MAPPED, RULE_DERIVED, HEURISTIC, UNKNOWN}`.
- [ ] RED: add overlap-conflict tests. Freeze overlap logic for the only supported EXACT/PREFIX language:
  - EXACT/EXACT overlap when the exact strings can be equal under the pair's case-sensitivity semantics;
  - EXACT/PREFIX overlap when some casing of the exact string can satisfy the prefix;
  - PREFIX/PREFIX overlap when one normalized prefix can prefix the other;
  - overlapping rules with different `(target_term_id, assurance)` fail catalog construction;
  - overlapping rules with identical semantic output are allowed because one fact may retain separate mapping evidence.
- [ ] RED: add hashing tests proving rule order does not change `content_hash`, a machine semantic change does, and optional `description` fields/comments do not affect hash payload.
- [ ] Run enterprise source/catalog/hash tests and verify RED because the package is absent.
- [ ] GREEN: add `pyproject.toml` with dependencies `semantic-service>=0.1.0`, `host-contracts>=0.1.0`, `PyYAML==6.0.3`, setuptools `src` discovery, and package data `data/*.yaml`.
- [ ] GREEN: implement typed provider-local errors: `EnterpriseSemanticProviderError`, `EnterpriseSourceError`, `EnterpriseCatalogBuildError`, `EnterpriseProjectionError`.
- [ ] GREEN: implement source loading using `importlib.resources.files(...)`, `yaml.safe_load`, strict root metadata validation, and no runtime network/Markdown parsing.
- [ ] GREEN: implement canonical SHA-256 hashing with sorted mapping keys and normalized sequence/set values, following existing IFC/Metro patterns.
- [ ] GREEN: normalize source into immutable rules, sort by `mapping_id`, validate ambiguity pairwise, and compute `content_hash` only from machine metadata + rule semantics. Exclude optional `description` fields from hash payload.
- [ ] Compute the reviewed golden hash from the implemented catalog with:

```bash
python -c "from enterprise_mapping_provider.catalog import build_catalog; from enterprise_mapping_provider.source import load_raw_machine_source; print(build_catalog(load_raw_machine_source()).content_hash)"
```

Freeze the exact printed lowercase SHA-256 in `golden.py`; production provider import must fail closed if the rebuilt hash differs.
- [ ] GREEN: create the provider manifest object (or provider skeleton if projection body is still `return ()`) with exact identity/authority/dependency/compatibility values. Registration through `SemanticProviderRegistry` must succeed once it implements `project_facts()`; until Task 3, catalog tests may instantiate the model/catalog directly rather than registering an incomplete provider.
- [ ] Run source/catalog/hash tests GREEN.
- [ ] Commit `feat(enterprise): add immutable semantic mapping catalog`.

### Task 3: Project A-WALL evidence into canonical IFC claims and compose with Semantic Service

**Files:**
- Create: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/projection.py`
- Create/Modify: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/provider.py`
- Modify: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/__init__.py`
- Create: `tests/semantic_providers/enterprise_mapping/test_projection.py`
- Create: `tests/semantic_providers/enterprise_mapping/test_service_integration.py`
- Create: `tests/semantic_providers/enterprise_mapping/test_step19_autocad_integration.py`

**Projection helpers:**

```python
def native_subject_locator(fact: NormalizedDesignFact) -> str:
    return "native://{}/{}/{}/{}".format(
        quote(fact.host_ref.host_type, safe=""),
        quote(fact.host_ref.host_instance_id, safe=""),
        quote(fact.host_ref.document_id, safe=""),
        quote(fact.subject_native_ref.native_id, safe=""),
    )
```

```python
SemanticClaim(
    subject=native_subject_locator(fact),
    predicate="classification",
    canonical_term_id=rule.target_term_id,
    value=None,
    unit=None,
    assurance=rule.assurance,
    provenance=fact.provenance,
    evidence=(
        f"design-fact:{fact.fact_id}",
        f"mapping:{rule.mapping_id}",
    ),
    provider_id="dsp.enterprise.mapping",
    provider_version="1.0.0",
)
```

- [ ] RED: create a helper constructing a frozen CLASSIFICATION NDF with `source_scheme="autocad.layer"` and parametrized `source_code`.
- [ ] RED: prove `A-WALL`, `A-WALL-EXT`, `A-WALL-INT`, and `a-wall-ext` project to `ifc:IfcWall`; prove `A-WALLISH`, `X-A-WALL`, other source schemes, missing source evidence, and non-CLASSIFICATION facts emit no claims.
- [ ] RED: prove provider uses `source_scheme/source_code`, not `predicate`, `value`, or provenance text, by constructing misleading values that must not match.
- [ ] RED: prove exact claim fields, `RULE_DERIVED`, ordered evidence, verbatim provenance, URL-encoded document/native subject segments, and no SemanticId.
- [ ] RED: prove deterministic ordering is `(subject, mapping_id, fact_id)` and that separate matched fact/rule derivations remain separate claims.
- [ ] RED: with an injected synthetic conflicting catalog, prove runtime also fails closed if one fact matches rules with different target/assurance; YAML/list order must not select a winner.
- [ ] RED: create service integration using `IFC43_PROVIDER` + enterprise provider. Pin exact refs:

```python
IFC_REF = ProviderRef("buildingSMART.ifc43", "4.3.2.0")
ENTERPRISE_REF = ProviderRef("dsp.enterprise.mapping", "1.0.0")
```

Prove enterprise-only environment fails the exact IFC dependency, IFC remains `AUTHORITATIVE` for `ifc`, enterprise is `EXTENSION`, `service.project_facts()` emits the enterprise claim, and `service.resolve_term("ifc:IfcWall", env)` resolves through `buildingSMART.ifc43`.
- [ ] RED: prove every packaged `target_term_id` resolves through the required IFC provider baseline.
- [ ] RED: create Step19 integration test using `autocad_sidecar.adapter.design_fact_adapter.DesignFactAdapter` only in test code: normalize the existing synthetic A31/LWPOLYLINE/A-WALL snapshot, pass that `NormalizedDesignFactBatch` to `SemanticService.project_facts()`, and assert one classification claim to `ifc:IfcWall`. This is the Step19→Step20 proof, not D5 integration.
- [ ] Run projection/integration tests and verify RED because projection/provider implementation is absent/incomplete.
- [ ] GREEN: implement EXACT/PREFIX matcher using exact source-scheme equality and per-rule case-sensitive/case-insensitive source-code matching. Do not use regex/glob.
- [ ] GREEN: select only NDF `FactKind.CLASSIFICATION` facts with non-null structured source evidence.
- [ ] GREEN: build claims exactly as frozen and sort derivations by `(subject, mapping_id, fact_id)`.
- [ ] GREEN: implement `EnterpriseMappingProvider.project_facts()` and exact manifest; expose `ENTERPRISE_MAPPING_PROVIDER` singleton and catalog from package `__init__.py`.
- [ ] Run targeted enterprise projection/service/Step19 integration tests GREEN.
- [ ] Run IFC provider tests and Metro provider tests to verify both marker-only providers remain unchanged and registerable.
- [ ] Commit `feat(enterprise): project A-WALL evidence to IFC wall claims`.

### Task 4: Add architecture guards, CI, regression verification, and PR preparation

**Files:**
- Create: `tests/semantic_providers/enterprise_mapping/test_architecture.py`
- Finalize: `providers/semantics/enterprise_mapping/README.md`
- Create: `.github/workflows/enterprise-semantic-provider.yml`
- Optionally modify only tests/docs/workflow files needed to tighten Step 20 guards; do not modify excluded production owners.

- [ ] RED/GUARD: add architecture tests scanning Enterprise provider production for forbidden imports/tokens: `autocad_sidecar`, `Autodesk`, `Revit`, `Tekla`, `semantic_runtime`, `semantic_mcp`, `metro_semantic_provider`, `ifc43_semantic_provider`, `ifcopenshell`.
- [ ] GUARD: scan `platform/semantic_service/src/semantic_service` and prove no `A-WALL`, `A-WALL-`, `autocad.layer`, `ifc:IfcWall`, concrete enterprise provider import, concrete AutoCAD adapter import, D5/runtime, or MCP import. Allow `design_fact_contracts` as the new stable Phase E input contract.
- [ ] GUARD: prove `semantic_service` does not re-export `NormalizedDesignFactBatch` and that no `semantic.project_facts` MCP tool was added.
- [ ] GUARD: compare branch changed files to `main` and fail review if AutoCAD plugin/sidecar production, IFC provider production, Metro provider production, Semantic Runtime/D5 production, or Semantic MCP production changed.
- [ ] Finalize README with provider identity, exact IFC dependency, facts-v1 compatibility token, YAML source/golden hash, A-WALL matching behavior, claim shape, authority boundary, no runtime network/Markdown parsing, and explicit Step20 non-goals.
- [ ] Add `.github/workflows/enterprise-semantic-provider.yml` with PR/push path filters for enterprise provider, semantic-service changes, enterprise tests, Step20 spec/plan, and the workflow itself.
- [ ] CI install command should include the semantic stack needed by all Step20 proofs:

```bash
python -m pip install pytest pytest-asyncio jsonschema
python -m pip install \
  -e contracts/python \
  -e hosts/autocad/sidecar \
  -e platform/semantic_runtime \
  -e platform/semantic_service \
  -e platform/semantic_mcp \
  -e providers/semantics/dsp_core \
  -e providers/semantics/ifc43 \
  -e providers/semantics/metro_v32 \
  -e providers/semantics/enterprise_mapping
```

- [ ] Add targeted Step20 gate:

```bash
pytest -q \
  tests/semantic_service/test_provider_contracts.py \
  tests/semantic_service/test_registry.py \
  tests/semantic_service/test_service_projection.py \
  tests/semantic_service/test_semantic_service_public_surface.py \
  tests/semantic_providers/enterprise_mapping
```

- [ ] Add semantic-provider regression gate:

```bash
pytest -q \
  tests/semantic_service \
  tests/semantic_providers/dsp_core \
  tests/semantic_providers/ifc43 \
  tests/semantic_providers/metro_v32 \
  tests/semantic_providers/enterprise_mapping
```

- [ ] Add relevant full Python regression gate:

```bash
pytest -q \
  contracts/python/tests \
  tests/contracts \
  tests/integration \
  tests/orchestrator \
  tests/semantic_runtime \
  tests/semantic_service \
  tests/semantic_mcp \
  tests/semantic_providers/dsp_core \
  tests/semantic_providers/ifc43 \
  tests/semantic_providers/metro_v32 \
  tests/semantic_providers/enterprise_mapping
```

- [ ] Run/inspect all workflows at the **actual final branch head**. Do not reuse evidence from an earlier commit.
- [ ] Compare `main...feat/enterprise-a-wall-mapping-provider`; expected production changes are limited to provider-neutral Semantic Service fact-projection seam + new Enterprise provider. Explicitly verify zero production diffs under AutoCAD, IFC, Metro, Semantic Runtime/D5, and Semantic MCP.
- [ ] Verify final acceptance scenario:

```text
Step19 AutoCAD snapshot A31 / LWPOLYLINE / A-WALL
  -> NormalizedDesignFact(CLASSIFICATION, autocad.layer, A-WALL)
  -> pinned dsp.enterprise.mapping@1.0.0
  -> SemanticClaim(classification, ifc:IfcWall, RULE_DERIVED)
  -> ifc:IfcWall vocabulary resolves through buildingSMART.ifc43@4.3.2.0
```

with no D5 integration yet.
- [ ] Prepare a PR against `main` describing Step 20 only, the versioned facts-v1 seam, marker-only IFC/Metro compatibility, data-driven enterprise rules, exact IFC authority/dependency, Step19→Step20 proof, and explicit Step21 deferral.
- [ ] Keep the PR unmerged until explicit user authorization.
