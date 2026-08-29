# Step 21 — D5 Canonical Projection Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the real Step 19 AutoCAD normalized facts and Step 20 Enterprise Mapping projection reach the existing D5 freshness barrier as canonical `ifc:IfcWall` classification evidence, while D5, Orchestrator, Host, Semantic Service, and semantic-provider production code remain unchanged.

**Architecture:** Add only test composition, architecture guards, and one dedicated CI workflow. The E2E proof uses the real `DesignFactAdapter`, the real pinned `SemanticService`, IFC4.3 plus Enterprise Mapping providers, and the existing D5 `FreshnessResolver` reconstruction callback. A private test helper maps provider-neutral canonical claim structure to existing D5 aspect evidence; it never interprets AutoCAD layers or enterprise mapping rules.

**Tech Stack:** Python 3.11, pytest, existing `design_fact_contracts`, `autocad_sidecar`, `semantic_service`, `semantic_runtime`, IFC4.3 semantic provider, Enterprise Mapping provider, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md`

## Global Constraints

- Base is `main@0ce330abb10a33ae85025f516554d95386480fb5`.
- Work only on `feat/step21-d5-canonical-projection-proof`; never write directly to `main`.
- Production diff must remain zero under `contracts/`, `hosts/autocad/`, `platform/orchestrator/`, `platform/semantic_mcp/`, `platform/semantic_runtime/`, `platform/semantic_service/`, `providers/semantics/dsp_core/`, `providers/semantics/enterprise_mapping/`, `providers/semantics/ifc43/`, `providers/semantics/metro_v32/`, and `platform/changeset/`.
- Allowed implementation paths are exactly the Step 21 files named in this plan under `tests/`, `.github/workflows/`, `docs/superpowers/specs/`, and `docs/superpowers/plans/`.
- Use the real Step 19 Python sidecar `DesignFactAdapter`; do not import or exercise AutoCAD .NET/plugin implementation in Step 21 tests.
- Use exact pinned providers `buildingSMART.ifc43@4.3.2.0` and `dsp.enterprise.mapping@1.0.0`.
- D5 must never inspect `A-WALL`, `autocad.layer`, `dsp.enterprise.mapping`, or Host product identity to choose `IfcWall`.
- The accepted D5 classification guarantee is exactly `coverage=RESOLVED`, `semantic_depth=CANONICAL`, `assurance=RULE_DERIVED`, `geometry=NONE`.
- Never inflate `RULE_DERIVED` to `STANDARD_MAPPED` or `NATIVE_ASSERTED`.
- `A-WALLISH` and `X-A-WALL` must not satisfy D5 classification freshness.
- A contract requiring `STANDARD_MAPPED` assurance must fail closed against the Step 20 `RULE_DERIVED` claim.
- Step 21 may construct deterministic test-only `SemanticProjectionRef` values, but must not create a production projection-reference builder or hashing standard.
- Do not add a Semantic MCP endpoint, SemanticId, geometry reconstruction, ChangeSet behavior, Host mutation, Metro mapping, IFC vocabulary, or Step 22 task-fidelity logic.
- Use `pytest --import-mode=importlib` for multi-suite semantic-provider regressions.
- Do not merge the resulting PR without explicit user merge authorization.

---

## File Structure

Create exactly these implementation files:

```text
tests/integration/test_step21_d5_canonical_projection.py
    Real Step19 -> Step20 -> existing D5 positive/negative proof.
    Owns only private test-composition and deterministic test-lineage helpers.

tests/semantic_runtime/test_step21_architecture.py
    Repository guards for zero D5/Orchestrator enterprise-rule knowledge,
    dependency direction, and single production ownership of the A-WALL rule.

.github/workflows/step21-d5-canonical-projection.yml
    Exact-file diff gate, Step21 targeted tests, upstream regressions,
    and relevant full Python regression.
```

The already-approved documentation files remain:

```text
docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md
docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md
```

No production source file is modified in Step 21.

---

### Task 1: Add the real Step19 -> Step20 -> D5 end-to-end proof

**Files:**
- Create: `tests/integration/test_step21_d5_canonical_projection.py`
- Reference only: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/design_fact_adapter.py`
- Reference only: `platform/semantic_service/src/semantic_service/service.py`
- Reference only: `platform/semantic_runtime/src/semantic_runtime/freshness.py`
- Reference only: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/projection.py`

**Interfaces:**
- Consumes: `DesignFactAdapter.normalize_snapshot(payload) -> NormalizedDesignFactBatch`.
- Consumes: `SemanticService.project_facts(facts, environment_id) -> tuple[SemanticClaim, ...]`.
- Consumes: `FreshnessResolver.resolve(contract, expected_host_revision=..., reconstruct=...) -> SemanticSnapshot`.
- Produces: private test helper `_reconstruction_from_claims(contract: FreshnessContract, revision: str, *, facts: NormalizedDesignFactBatch, claims: tuple[SemanticClaim, ...], environment: SemanticEnvironment) -> ReconstructionResult`.
- Produces: private test helper `_projection_ref(facts: NormalizedDesignFactBatch, claims: tuple[SemanticClaim, ...], environment: SemanticEnvironment) -> SemanticProjectionRef`.

- [ ] **Step 1: Write the positive failing proof**

Create `tests/integration/test_step21_d5_canonical_projection.py` with the imports, stable fixture, pinned semantic stack, requirement builder, and positive test below. Deliberately reference `_reconstruction_from_claims` before defining it so this first test cycle is RED only at the D5 composition seam.

```python
from __future__ import annotations

from hashlib import sha256
import json

import pytest

from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from design_fact_contracts import FactKind, NormalizedDesignFactBatch
from enterprise_mapping_provider import ENTERPRISE_MAPPING_PROVIDER
from ifc43_semantic_provider import IFC43_PROVIDER
from semantic_runtime import (
    AspectGuarantee,
    AspectRequirement,
    AssuranceLevel,
    CoverageState,
    DirtyMap,
    FreshnessContract,
    FreshnessResolver,
    FreshnessState,
    FreshnessUnsatisfiedError,
    GeometryLevel,
    ReconstructionResult,
    SemanticAspect,
    SemanticDepth,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SnapshotKind,
    build_operation_contract,
)
from semantic_service import (
    ProviderRef,
    SemanticClaim,
    SemanticEnvironment,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
)


DOCUMENT_ID = "C:/models/station.dwg"
TARGET_SUBJECT = "native://autocad/autocad-session-1/C%3A%2Fmodels%2Fstation.dwg/A31"


def _snapshot(layer: str) -> dict[str, object]:
    return {
        "hostInstanceId": "autocad-session-1",
        "documentId": DOCUMENT_ID,
        "revision": 42,
        "entities": [
            {
                "nativeId": "A31",
                "nativeKind": "LWPOLYLINE",
                "layer": layer,
            }
        ],
    }


def _semantic_stack() -> tuple[SemanticService, SemanticEnvironment]:
    registry = SemanticProviderRegistry()
    registry.register(IFC43_PROVIDER)
    registry.register(ENTERPRISE_MAPPING_PROVIDER)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (
            ProviderRef("buildingSMART.ifc43", "4.3.2.0"),
            ProviderRef("dsp.enterprise.mapping", "1.0.0"),
        ),
        registry,
    )
    return SemanticService(registry, store), environment


def _classification_requirement(
    assurance: AssuranceLevel = AssuranceLevel.RULE_DERIVED,
) -> AspectRequirement:
    return AspectRequirement(
        SemanticAspect.CLASSIFICATION,
        geometry_level=GeometryLevel.NONE,
        minimum_coverage=CoverageState.RESOLVED,
        semantic_depth=SemanticDepth.CANONICAL,
        minimum_assurance=assurance,
    )


def _contract(
    *,
    assurance: AssuranceLevel = AssuranceLevel.RULE_DERIVED,
) -> FreshnessContract:
    return build_operation_contract(
        project_id="project-step21",
        document_ref=DOCUMENT_ID,
        canonical_operation="classify.v1",
        targets=(TARGET_SUBJECT,),
        arguments={},
        requirements=(_classification_requirement(assurance),),
    )


def test_a_wall_reaches_existing_d5_as_canonical_ifc_wall() -> None:
    facts = DesignFactAdapter().normalize_snapshot(_snapshot("A-WALL"))
    classification = next(
        fact for fact in facts.facts if fact.fact_kind is FactKind.CLASSIFICATION
    )
    assert classification.source_scheme == "autocad.layer"
    assert classification.source_code == "A-WALL"

    service, environment = _semantic_stack()
    claims = service.project_facts(facts, environment.environment_id)
    assert len(claims) == 1
    claim = claims[0]
    assert claim.subject == TARGET_SUBJECT
    assert claim.predicate == "classification"
    assert claim.canonical_term_id == "ifc:IfcWall"
    assert claim.assurance == "RULE_DERIVED"
    assert claim.provider_id == "dsp.enterprise.mapping"
    assert claim.provider_version == "1.0.0"

    dirty = DirtyMap()
    dirty.mark_dirty(DOCUMENT_ID, TARGET_SUBJECT, (SemanticAspect.CLASSIFICATION,))
    contract = _contract()

    snapshot = FreshnessResolver(dirty).resolve(
        contract,
        expected_host_revision="42",
        reconstruct=lambda current, revision: _reconstruction_from_claims(
            current,
            revision,
            facts=facts,
            claims=claims,
            environment=environment,
        ),
    )

    assert snapshot.kind is SnapshotKind.PLANNING
    assert snapshot.semantic_environment_ref == SemanticEnvironmentRef(
        environment.environment_id,
        environment.content_hash,
    )
    assert snapshot.projection_ref.normalized_fact_batch_hash is not None
    assert snapshot.projection_ref.semantic_model_version == "step21-proof-v1"

    guarantee = snapshot.aspect_guarantees[0]
    assert guarantee.aspect is SemanticAspect.CLASSIFICATION
    assert guarantee.coverage_state is CoverageState.RESOLVED
    assert guarantee.semantic_depth is SemanticDepth.CANONICAL
    assert guarantee.assurance_level is AssuranceLevel.RULE_DERIVED
    assert guarantee.geometry_level is GeometryLevel.NONE

    assert dirty.state(
        DOCUMENT_ID,
        TARGET_SUBJECT,
        SemanticAspect.CLASSIFICATION,
    ) is FreshnessState.FRESH
    assert dirty.state(
        DOCUMENT_ID,
        TARGET_SUBJECT,
        SemanticAspect.GEOMETRY,
    ) is FreshnessState.UNKNOWN
```

- [ ] **Step 2: Run the positive proof and verify RED occurs at the missing D5 composition helper**

Run:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py::test_a_wall_reaches_existing_d5_as_canonical_ifc_wall
```

Expected: `FAIL` with `NameError: name '_reconstruction_from_claims' is not defined`. The Step 19 normalization and Step 20 projection assertions occur before that call; if they fail, diagnose the upstream contract instead of weakening this test.

- [ ] **Step 3: Implement the minimal provider-neutral test composition helper**

Insert these helpers before the tests:

```python
def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _claim_payload(claim: SemanticClaim) -> dict[str, object]:
    return {
        "subject": claim.subject,
        "predicate": claim.predicate,
        "canonical_term_id": claim.canonical_term_id,
        "value": claim.value,
        "unit": claim.unit,
        "assurance": claim.assurance,
        "provenance": list(claim.provenance),
        "evidence": list(claim.evidence),
        "provider_id": claim.provider_id,
        "provider_version": claim.provider_version,
    }


def _projection_ref(
    facts: NormalizedDesignFactBatch,
    claims: tuple[SemanticClaim, ...],
    environment: SemanticEnvironment,
) -> SemanticProjectionRef:
    provider_payload = [
        {
            "provider_id": provider.provider_id,
            "version": provider.version,
            "content_hash": provider.content_hash,
        }
        for provider in environment.providers
    ]
    fact_hash = _digest(facts.to_dict())
    projection_hash = _digest(
        {
            "environment_id": environment.environment_id,
            "environment_hash": environment.content_hash,
            "claims": [_claim_payload(claim) for claim in claims],
        }
    )
    return SemanticProjectionRef(
        projection_id=f"step21:{projection_hash}",
        projection_hash=projection_hash,
        semantic_model_version="step21-proof-v1",
        provider_set_hash=_digest(provider_payload),
        mapping_profile_set_hash=_digest(
            {"projection_fixture_providers": provider_payload}
        ),
        normalized_fact_batch_hash=fact_hash,
    )


def _reconstruction_from_claims(
    contract: FreshnessContract,
    revision: str,
    *,
    facts: NormalizedDesignFactBatch,
    claims: tuple[SemanticClaim, ...],
    environment: SemanticEnvironment,
) -> ReconstructionResult:
    requested = set(contract.coverage.root_entities)
    strongest_by_subject: dict[str, AssuranceLevel] = {}

    for claim in claims:
        if claim.subject not in requested:
            continue
        if claim.predicate != "classification":
            continue
        if claim.canonical_term_id is None:
            continue
        try:
            assurance = AssuranceLevel[claim.assurance]
        except KeyError as exc:
            raise ValueError(
                f"unknown canonical claim assurance: {claim.assurance!r}"
            ) from exc
        strongest_by_subject[claim.subject] = max(
            assurance,
            strongest_by_subject.get(claim.subject, AssuranceLevel.UNKNOWN),
        )

    guarantees: tuple[AspectGuarantee, ...] = ()
    if requested and requested.issubset(strongest_by_subject):
        guarantees = (
            AspectGuarantee(
                SemanticAspect.CLASSIFICATION,
                geometry_level=GeometryLevel.NONE,
                coverage_state=CoverageState.RESOLVED,
                semantic_depth=SemanticDepth.CANONICAL,
                assurance_level=min(
                    strongest_by_subject[subject] for subject in requested
                ),
            ),
        )

    return ReconstructionResult(
        document_ref=contract.coverage.document_ref,
        host_revision=revision,
        coverage=contract.coverage,
        guarantees=guarantees,
        projection_ref=_projection_ref(facts, claims, environment),
        semantic_environment_ref=SemanticEnvironmentRef(
            environment.environment_id,
            environment.content_hash,
        ),
    )
```

Review invariant: `_reconstruction_from_claims` contains none of `A-WALL`, `autocad.layer`, `IfcWall`, `dsp.enterprise.mapping`, or Host-product branches. It maps only canonical claim structure to D5 classification evidence.

- [ ] **Step 4: Run the positive proof and verify GREEN**

Run:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py::test_a_wall_reaches_existing_d5_as_canonical_ifc_wall
```

Expected: `1 passed`.

- [ ] **Step 5: Write near-match fail-closed tests**

Append:

```python
@pytest.mark.parametrize("layer", ["A-WALLISH", "X-A-WALL"])
def test_near_match_layer_does_not_satisfy_d5_classification(layer: str) -> None:
    facts = DesignFactAdapter().normalize_snapshot(_snapshot(layer))
    classification = next(
        fact for fact in facts.facts if fact.fact_kind is FactKind.CLASSIFICATION
    )
    assert classification.source_scheme == "autocad.layer"
    assert classification.source_code == layer

    service, environment = _semantic_stack()
    claims = service.project_facts(facts, environment.environment_id)
    assert claims == ()

    dirty = DirtyMap()
    dirty.mark_dirty(DOCUMENT_ID, TARGET_SUBJECT, (SemanticAspect.CLASSIFICATION,))
    contract = _contract()

    with pytest.raises(
        FreshnessUnsatisfiedError,
        match=r"CLASSIFICATION\.freshness",
    ):
        FreshnessResolver(dirty).resolve(
            contract,
            expected_host_revision="42",
            reconstruct=lambda current, revision: _reconstruction_from_claims(
                current,
                revision,
                facts=facts,
                claims=claims,
                environment=environment,
            ),
        )

    assert dirty.state(
        DOCUMENT_ID,
        TARGET_SUBJECT,
        SemanticAspect.CLASSIFICATION,
    ) is FreshnessState.DIRTY
```

- [ ] **Step 6: Run the near-match tests**

Run:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py -k near_match
```

Expected: `2 passed`.

- [ ] **Step 7: Write stronger-assurance fail-closed test**

Append:

```python
def test_rule_derived_claim_cannot_satisfy_standard_mapped_requirement() -> None:
    facts = DesignFactAdapter().normalize_snapshot(_snapshot("A-WALL"))
    service, environment = _semantic_stack()
    claims = service.project_facts(facts, environment.environment_id)
    assert len(claims) == 1
    assert claims[0].assurance == "RULE_DERIVED"

    dirty = DirtyMap()
    dirty.mark_dirty(DOCUMENT_ID, TARGET_SUBJECT, (SemanticAspect.CLASSIFICATION,))
    contract = _contract(assurance=AssuranceLevel.STANDARD_MAPPED)

    with pytest.raises(
        FreshnessUnsatisfiedError,
        match=r"CLASSIFICATION\.assurance",
    ):
        FreshnessResolver(dirty).resolve(
            contract,
            expected_host_revision="42",
            reconstruct=lambda current, revision: _reconstruction_from_claims(
                current,
                revision,
                facts=facts,
                claims=claims,
                environment=environment,
            ),
        )

    assert dirty.state(
        DOCUMENT_ID,
        TARGET_SUBJECT,
        SemanticAspect.CLASSIFICATION,
    ) is FreshnessState.DIRTY
```

- [ ] **Step 8: Run the complete Step 21 E2E module**

Run:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py
```

Expected: `4 passed` — one positive case, two parameterized near-match cases, and one stronger-assurance case.

- [ ] **Step 9: Verify Task 1 changed no production path**

Run:

```bash
git diff --name-only main...HEAD
```

Expected at this checkpoint: approved Step 21 docs plus `tests/integration/test_step21_d5_canonical_projection.py`; no production path.

- [ ] **Step 10: Commit Task 1**

```bash
git add tests/integration/test_step21_d5_canonical_projection.py
git commit -m "test(step21): prove canonical wall projection reaches D5"
```

---

### Task 2: Add architecture guards for zero D5/Orchestrator enterprise-rule knowledge

**Files:**
- Create: `tests/semantic_runtime/test_step21_architecture.py`
- Reference only: `platform/semantic_runtime/`
- Reference only: `platform/orchestrator/`
- Reference only: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/data/enterprise_mappings_v1.yaml`

**Interfaces:**
- Consumes: repository source tree.
- Produces: regression guards that fail if D5/Orchestrator acquire Host/enterprise rule knowledge or if the production `A-WALL` rule is duplicated.

- [ ] **Step 1: Create source-tree scanning helpers**

Create:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "platform" / "semantic_runtime"
ORCHESTRATOR = ROOT / "platform" / "orchestrator"
ENTERPRISE_RULE = (
    ROOT
    / "providers"
    / "semantics"
    / "enterprise_mapping"
    / "src"
    / "enterprise_mapping_provider"
    / "data"
    / "enterprise_mappings_v1.yaml"
)


def _text_files(root: Path):
    for path in root.rglob("*"):
        if path.is_file() and path.suffix in {
            ".py",
            ".cs",
            ".yaml",
            ".yml",
            ".json",
            ".toml",
        }:
            yield path


def _tree_text(root: Path) -> str:
    return "\n".join(
        path.read_text(encoding="utf-8") for path in _text_files(root)
    )
```

- [ ] **Step 2: Add D5 and Orchestrator knowledge/dependency guards**

Append:

```python
def test_d5_runtime_has_no_enterprise_or_autocad_mapping_knowledge() -> None:
    text = _tree_text(RUNTIME)
    for forbidden in ("A-WALL", "autocad.layer", "dsp.enterprise.mapping"):
        assert forbidden not in text


def test_d5_runtime_does_not_depend_on_semantic_service_or_enterprise_provider() -> None:
    text = _tree_text(RUNTIME)
    assert "semantic_service" not in text
    assert "enterprise_mapping_provider" not in text


def test_orchestrator_has_no_enterprise_mapping_knowledge_or_dependency() -> None:
    text = _tree_text(ORCHESTRATOR)
    for forbidden in (
        "A-WALL",
        "autocad.layer",
        "dsp.enterprise.mapping",
        "enterprise_mapping_provider",
    ):
        assert forbidden not in text
```

- [ ] **Step 3: Add single production rule-owner guard**

Append:

```python
def test_a_wall_rule_has_one_production_source_owner() -> None:
    production_roots = (
        ROOT / "contracts",
        ROOT / "hosts",
        ROOT / "platform",
        ROOT / "providers" / "semantics",
    )
    hits = []
    for root in production_roots:
        for path in _text_files(root):
            if "A-WALL" in path.read_text(encoding="utf-8"):
                hits.append(path.relative_to(ROOT))

    assert hits == [ENTERPRISE_RULE.relative_to(ROOT)]
```

The scan intentionally excludes docs and tests and ignores README/Markdown presentation text. The machine-readable Enterprise Mapping YAML is the sole production owner of this rule.

- [ ] **Step 4: Run architecture guards**

Run:

```bash
pytest -q tests/semantic_runtime/test_step21_architecture.py
```

Expected: `4 passed`. A failure is an architecture-boundary failure; do not add a broad allowlist to make the test green.

- [ ] **Step 5: Run Step 21 targeted tests together**

Run:

```bash
pytest -q \
  tests/integration/test_step21_d5_canonical_projection.py \
  tests/semantic_runtime/test_step21_architecture.py
```

Expected: `8 passed`.

- [ ] **Step 6: Commit Task 2**

```bash
git add tests/semantic_runtime/test_step21_architecture.py
git commit -m "test(step21): guard D5 semantic boundaries"
```

---

### Task 3: Add Step 21 CI with exact changed-file boundary and upstream regressions

**Files:**
- Create: `.github/workflows/step21-d5-canonical-projection.yml`
- Reference only: `tests/contracts/test_autocad_design_fact_adapter.py`
- Reference only: `.github/workflows/enterprise-semantic-provider.yml`

**Interfaces:**
- Consumes: Step 21 tests from Tasks 1–2 and existing Step 19/20 regression suites.
- Produces: PR verification that blocks production-path drift and exercises the real semantic stack.

- [ ] **Step 1: Create workflow trigger and install the exact Step 21 stack**

Create:

```yaml
name: Step21 D5 canonical projection proof

on:
  pull_request:
    paths:
      - "tests/integration/test_step21_d5_canonical_projection.py"
      - "tests/semantic_runtime/test_step21_architecture.py"
      - "docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md"
      - "docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md"
      - ".github/workflows/step21-d5-canonical-projection.yml"
  push:
    paths:
      - "tests/integration/test_step21_d5_canonical_projection.py"
      - "tests/semantic_runtime/test_step21_architecture.py"
      - ".github/workflows/step21-d5-canonical-projection.yml"
  workflow_dispatch:

jobs:
  step21-d5-canonical-projection:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: .
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install Step21 semantic stack
        run: |
          python -m pip install pytest pytest-asyncio jsonschema PyYAML==6.0.3
          python -m pip install \
            -e contracts/python \
            -e hosts/autocad/sidecar \
            -e platform/semantic_runtime \
            -e platform/semantic_service \
            -e providers/semantics/ifc43 \
            -e providers/semantics/enterprise_mapping
```

Do not install Orchestrator, Semantic MCP, Metro, or DSP Core for the targeted proof; they are not Step 21 runtime participants.

- [ ] **Step 2: Add exact changed-file boundary gate**

Append before test execution:

```yaml
      - name: Verify Step21 PR diff boundary
        if: github.event_name == 'pull_request'
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          changed="$(git diff --name-only "$BASE_SHA...$HEAD_SHA")"
          printf '%s\n' "$changed"
          bad="$(printf '%s\n' "$changed" | grep -Ev '^(\.github/workflows/step21-d5-canonical-projection\.yml|docs/superpowers/(specs/2026-08-29-step21-d5-canonical-projection-proof-design\.md|plans/2026-08-29-step21-d5-canonical-projection-proof\.md)|tests/integration/test_step21_d5_canonical_projection\.py|tests/semantic_runtime/test_step21_architecture\.py)$' || true)"
          if [ -n "$bad" ]; then
            echo "Step21 changed files outside the approved zero-production boundary:"
            printf '%s\n' "$bad"
            exit 1
          fi
```

The allowlist is exact-file, not `tests/**`, so unrelated test changes cannot mask scope drift.

- [ ] **Step 3: Add targeted Step 21 proof and architecture guards**

Append:

```yaml
      - name: Run Step21 canonical projection proof
        run: pytest -q tests/integration/test_step21_d5_canonical_projection.py

      - name: Run Step21 architecture guards
        run: pytest -q tests/semantic_runtime/test_step21_architecture.py
```

Expected local total for these two modules: `8 passed`.

- [ ] **Step 4: Add upstream regressions using current repository paths**

Append:

```yaml
      - name: Run semantic-runtime progressive regression
        run: pytest -q tests/semantic_runtime

      - name: Run Semantic Service projection regression
        run: |
          pytest -q \
            tests/semantic_service/test_provider_contracts.py \
            tests/semantic_service/test_registry.py \
            tests/semantic_service/test_service_projection.py \
            tests/semantic_service/test_d5_environment_ref_compatibility.py

      - name: Run Enterprise Mapping regression
        run: pytest -q tests/semantic_providers/enterprise_mapping

      - name: Run Step19 AutoCAD design-fact adapter regression
        run: pytest -q tests/contracts/test_autocad_design_fact_adapter.py
```

`tests/contracts/test_autocad_design_fact_adapter.py` is the current Step 19 adapter regression path and is frozen in this plan; do not substitute an integration filename.

- [ ] **Step 5: Add relevant full Python regression with importlib mode**

Append:

```yaml
      - name: Run relevant full Python regression tests
        run: |
          pytest -q --import-mode=importlib \
            contracts/python/tests \
            tests/contracts \
            tests/integration \
            tests/orchestrator \
            tests/semantic_runtime \
            tests/semantic_service \
            tests/semantic_providers/ifc43 \
            tests/semantic_providers/enterprise_mapping
```

This workflow is intentionally narrower than the final review suite because Step 21 changes no Metro, DSP Core, or Semantic MCP surface. Their existing workflows remain independent guards.

- [ ] **Step 6: Run the workflow commands locally before committing**

Run in this exact order:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py
pytest -q tests/semantic_runtime/test_step21_architecture.py
pytest -q tests/semantic_runtime
pytest -q \
  tests/semantic_service/test_provider_contracts.py \
  tests/semantic_service/test_registry.py \
  tests/semantic_service/test_service_projection.py \
  tests/semantic_service/test_d5_environment_ref_compatibility.py
pytest -q tests/semantic_providers/enterprise_mapping
pytest -q tests/contracts/test_autocad_design_fact_adapter.py
pytest -q --import-mode=importlib \
  contracts/python/tests \
  tests/contracts \
  tests/integration \
  tests/orchestrator \
  tests/semantic_runtime \
  tests/semantic_service \
  tests/semantic_providers/ifc43 \
  tests/semantic_providers/enterprise_mapping
```

Expected: all pass. Existing live AutoCAD tests guarded by `AGENT_HOST_TEST=1` may remain skipped under their existing conditions; record exact pass/skip/warning counts for the PR body.

- [ ] **Step 7: Run the exact-file diff gate locally**

Run:

```bash
changed="$(git diff --name-only main...HEAD)"
printf '%s\n' "$changed"
bad="$(printf '%s\n' "$changed" | grep -Ev '^(\.github/workflows/step21-d5-canonical-projection\.yml|docs/superpowers/(specs/2026-08-29-step21-d5-canonical-projection-proof-design\.md|plans/2026-08-29-step21-d5-canonical-projection-proof\.md)|tests/integration/test_step21_d5_canonical_projection\.py|tests/semantic_runtime/test_step21_architecture\.py)$' || true)"
test -z "$bad"
```

Expected: exit code `0`.

- [ ] **Step 8: Commit Task 3**

```bash
git add .github/workflows/step21-d5-canonical-projection.yml
git commit -m "ci(step21): verify zero-diff D5 projection proof"
```

---

### Task 4: Final verification, design alignment, and draft PR preparation

**Files:**
- Review: `docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md`
- Review: `docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md`
- No production files.

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces: verified PR-ready branch and a draft PR; does not merge.

- [ ] **Step 1: Run focused Step 21 acceptance suite from a clean working tree**

Run:

```bash
pytest -q \
  tests/integration/test_step21_d5_canonical_projection.py \
  tests/semantic_runtime/test_step21_architecture.py
```

Expected: `8 passed`.

- [ ] **Step 2: Run broad semantic regression used for final confidence**

Install existing provider packages needed by the broader suite if not already installed:

```bash
python -m pip install \
  -e providers/semantics/dsp_core \
  -e providers/semantics/metro_v32
```

Then run:

```bash
pytest -q --import-mode=importlib \
  contracts/python/tests \
  tests/contracts \
  tests/integration \
  tests/orchestrator \
  tests/semantic_runtime \
  tests/semantic_service \
  tests/semantic_providers/dsp_core \
  tests/semantic_providers/ifc43 \
  tests/semantic_providers/metro_v32 \
  tests/semantic_providers/enterprise_mapping
```

Expected: all pass with only existing documented skips/warnings. Capture exact counts rather than copying historical Step 20 counts.

- [ ] **Step 3: Prove the final branch has exactly the approved five changed files**

Run:

```bash
git diff --name-only main...HEAD
```

Expected paths only:

```text
.github/workflows/step21-d5-canonical-projection.yml
docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md
docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md
tests/integration/test_step21_d5_canonical_projection.py
tests/semantic_runtime/test_step21_architecture.py
```

Any additional changed path is a Step 21 scope violation and must be removed before PR creation.

- [ ] **Step 4: Prove the reconstruction helper contains no enterprise/Host mapping rule**

Run:

```bash
python - <<'PY'
from pathlib import Path

path = Path("tests/integration/test_step21_d5_canonical_projection.py")
text = path.read_text(encoding="utf-8")
start = text.index("def _reconstruction_from_claims(")
end = text.index("\ndef test_", start)
helper = text[start:end]
for forbidden in ("A-WALL", "autocad.layer", "IfcWall", "dsp.enterprise.mapping"):
    assert forbidden not in helper, forbidden
print("provider-neutral reconstruction helper: OK")
PY
```

Expected: `provider-neutral reconstruction helper: OK`.

- [ ] **Step 5: Review progressive evidence against the approved design**

Confirm the positive PlanningSnapshot has exactly:

```text
aspect            = CLASSIFICATION
coverage_state    = RESOLVED
semantic_depth    = CANONICAL
assurance_level   = RULE_DERIVED
geometry_level    = NONE
```

Confirm the `STANDARD_MAPPED` requirement test fails through existing `FreshnessResolver` assurance comparison and that no geometry requirement/guarantee appears.

- [ ] **Step 6: Confirm no production contract was accidentally created**

Run:

```bash
git diff --name-only main...HEAD | grep -E '^(contracts/|hosts/|platform/|providers/)' && exit 1 || true
```

Expected: no output.

Also verify `step21-proof-v1` occurs only in Step 21 test/docs:

```bash
grep -R -n "step21-proof-v1" \
  tests/integration/test_step21_d5_canonical_projection.py \
  docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md \
  docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md
```

Expected: matches only in those Step 21 artifacts.

- [ ] **Step 7: Review design/spec coverage and commit documentation correction only if verification exposes a factual mismatch**

Compare the executed proof against design sections 9–17. If a factual mismatch exists, correct only the Step 21 design/plan documents and commit:

```bash
git add \
  docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md \
  docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md
git commit -m "docs(step21): align proof with verified implementation"
```

If no factual mismatch exists, do not create a documentation-only churn commit.

- [ ] **Step 8: Create a draft PR without merging**

Use title:

```text
test(step21): prove A-WALL canonical projection reaches D5
```

Use body:

```markdown
## Goal
Prove Step19 AutoCAD facts -> Step20 Enterprise Mapping -> canonical ifc:IfcWall -> existing D5 FreshnessResolver/PlanningSnapshot with zero D5 production changes.

## Frozen boundaries
- D5 production diff: 0
- Orchestrator production diff: 0
- Enterprise Mapping production diff: 0
- Semantic Service production diff: 0
- No Semantic MCP endpoint
- No geometry reconstruction
- No assurance inflation

## Acceptance evidence
- A-WALL -> ifc:IfcWall -> D5 CLASSIFICATION fresh
- A-WALLISH rejected
- X-A-WALL rejected
- RULE_DERIVED cannot satisfy STANDARD_MAPPED
- Exact SemanticEnvironmentRef bound into PlanningSnapshot
- normalized_fact_batch_hash populated in test-only projection lineage

## Verification
- Focused Step21: <replace with exact verified count before PR creation>
- Broad Python regression: <replace with exact verified pass/skip/warning counts before PR creation>
- Changed-file boundary: exactly the five approved Step21 files
```

The angle-bracket fields above are PR-body data populated from the immediately preceding verification commands, not implementation placeholders: do not create the PR until they contain the exact current counts.

Create the PR as **draft**. Do not merge without separate explicit user authorization.

---

## Self-Review Checklist

Before execution handoff, confirm all items below:

- [x] Positive design acceptance maps to Task 1 assertions.
- [x] `A-WALLISH` and `X-A-WALL` fail because Step 20 emits no canonical classification claim, not because D5 hardcodes rejection logic.
- [x] `STANDARD_MAPPED` fails through existing D5 assurance comparison.
- [x] `_reconstruction_from_claims` is provider-neutral and Host-neutral.
- [x] `SemanticProjectionRef` construction is test-only and explicitly non-normative.
- [x] Exact pinned `SemanticEnvironmentRef` is copied into `ReconstructionResult` and PlanningSnapshot.
- [x] Architecture guards cover D5, Orchestrator, dependency direction, and single production A-WALL rule ownership.
- [x] Current Step 19 adapter regression path is `tests/contracts/test_autocad_design_fact_adapter.py`.
- [x] CI changed-file gate allows only the five approved Step 21 artifacts.
- [x] No production source file is part of the implementation plan.
- [x] Type names and public imports used in Task 1 match the current public surfaces of `semantic_runtime` and `semantic_service`.
- [x] Final regression covers DSP Core, IFC4.3, Metro v3.2, Enterprise Mapping, Semantic Service, D5, Orchestrator, integration, and contracts.
- [x] No `TBD`, `TODO`, “implement later”, unresolved filename, or unresolved interface remains in this plan.

## Execution Handoff

Execution mode is **Inline Execution**, matching the established project workflow. At implementation start:

1. Read and follow `superpowers:executing-plans`.
2. Read and follow `superpowers:test-driven-development` before implementation changes.
3. Execute Tasks 1–4 in order, preserving the RED/GREEN checkpoints and commit boundaries above.
4. Read and follow `superpowers:verification-before-completion` before claiming Step 21 complete or PR-ready.
5. Create the draft PR after fresh verification.
6. Do not merge without explicit user merge authorization.
