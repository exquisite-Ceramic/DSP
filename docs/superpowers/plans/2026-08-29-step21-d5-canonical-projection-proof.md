# Step 21 — D5 Canonical Projection Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the real Step 19 AutoCAD normalized facts and Step 20 Enterprise Mapping projection reach the existing D5 freshness barrier as canonical `ifc:IfcWall` classification evidence, with zero D5/Orchestrator/semantic production changes.

**Architecture:** Add only test composition, architecture guards, and a dedicated CI workflow. The E2E test uses the real `DesignFactAdapter`, real pinned `SemanticService` environment, and real Enterprise Mapping provider, then wraps provider-neutral canonical claims in the existing D5 `ReconstructionResult` callback contract. D5 production remains unchanged and only evaluates canonical classification coverage/depth/assurance through `FreshnessResolver`.

**Tech Stack:** Python 3.11, pytest, existing `design_fact_contracts`, `autocad_sidecar`, `semantic_service`, `semantic_runtime`, IFC4.3 provider, Enterprise Mapping provider, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md`

## Global Constraints

- Base is `main@0ce330abb10a33ae85025f516554d95386480fb5`.
- Work only on `feat/step21-d5-canonical-projection-proof`; never write directly to `main`.
- Production diff must remain zero under `contracts/`, `hosts/autocad/`, `platform/orchestrator/`, `platform/semantic_mcp/`, `platform/semantic_runtime/`, `platform/semantic_service/`, `providers/semantics/dsp_core/`, `providers/semantics/enterprise_mapping/`, `providers/semantics/ifc43/`, `providers/semantics/metro_v32/`, and `platform/changeset/`.
- Allowed implementation paths are limited to `tests/`, `.github/workflows/`, `docs/superpowers/specs/`, and `docs/superpowers/plans/`.
- Use the real Step 19 Python sidecar `DesignFactAdapter`; do not import or exercise AutoCAD .NET/plugin implementation in Step 21 tests.
- Use the exact pinned providers `buildingSMART.ifc43@4.3.2.0` and `dsp.enterprise.mapping@1.0.0`.
- D5 must never inspect `A-WALL`, `autocad.layer`, or enterprise provider identity to choose `IfcWall`.
- A canonical classification guarantee must be `coverage=RESOLVED`, `semantic_depth=CANONICAL`, `assurance=RULE_DERIVED`, `geometry=NONE`.
- Never inflate `RULE_DERIVED` to `STANDARD_MAPPED` or `NATIVE_ASSERTED`.
- Near matches `A-WALLISH` and `X-A-WALL` must not satisfy D5 classification freshness.
- A task requiring `STANDARD_MAPPED` assurance must fail closed against the Step 20 `RULE_DERIVED` claim.
- Step 21 may create deterministic test-only `SemanticProjectionRef` values but must not define or add a production projection hashing/building contract.
- Do not add Semantic MCP endpoints, SemanticId, geometry reconstruction, ChangeSet behavior, Host mutation, Metro mapping, IFC vocabulary, or Step 22 task-fidelity logic.
- Use `pytest --import-mode=importlib` for multi-suite regressions that include semantic provider test trees.

---

## File Structure

Create exactly these implementation files unless execution discovers a repository-level blocker that requires revising the approved design:

```text
tests/integration/test_step21_d5_canonical_projection.py
    Real Step19 -> Step20 -> existing D5 positive/negative proof.
    Contains only test-local composition helpers and deterministic test lineage builders.

tests/semantic_runtime/test_step21_architecture.py
    Repository architecture guards proving D5/Orchestrator have no enterprise rule knowledge
    and the A-WALL production rule has one production owner.

.github/workflows/step21-d5-canonical-projection.yml
    Step21 path trigger, changed-file boundary gate, targeted proof, architecture guards,
    and relevant regression suites.
```

Do not modify any existing production source file. Prefer adding the dedicated Step 21 workflow rather than modifying existing Step 19/20 workflows.

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
- Produces: a test-local `_reconstruction_from_claims(...) -> ReconstructionResult` that understands only canonical claim structure and D5 enums.
- Produces: deterministic test-local `_projection_ref(...) -> SemanticProjectionRef`; this is explicitly not a production hashing contract.

- [ ] **Step 1: Create the test module with fixtures/imports and a deliberately unresolved reconstruction helper**

Create the file with these imports and constants first:

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


def _contract(*, assurance: AssuranceLevel = AssuranceLevel.RULE_DERIVED):
    return build_operation_contract(
        project_id="project-step21",
        document_ref=DOCUMENT_ID,
        canonical_operation="classify.v1",
        targets=(TARGET_SUBJECT,),
        arguments={},
        requirements=(_classification_requirement(assurance),),
    )
```

Then add the positive test below, referencing `_reconstruction_from_claims` before that helper exists:

```python
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

- [ ] **Step 2: Run the positive proof and confirm RED is only the missing test-composition helper**

Run:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py::test_a_wall_reaches_existing_d5_as_canonical_ifc_wall
```

Expected: `FAIL` with `NameError: name '_reconstruction_from_claims' is not defined` after the real Step 19 and Step 20 assertions have executed successfully. If failure occurs earlier in the real adapter/provider chain, stop and diagnose rather than weakening the test.

- [ ] **Step 3: Add deterministic test-lineage helpers and provider-neutral claim -> D5 reconstruction composition**

Add these helpers above the tests:

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
    contract,
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
            raise ValueError(f"unknown canonical claim assurance: {claim.assurance!r}") from exc
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

Important review rule: `_reconstruction_from_claims` must contain none of `A-WALL`, `autocad.layer`, `IfcWall`, `dsp.enterprise.mapping`, or Host-product branches. It maps only canonical claim structure to existing D5 aspect evidence.

- [ ] **Step 4: Run the positive proof and confirm GREEN**

Run:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py::test_a_wall_reaches_existing_d5_as_canonical_ifc_wall
```

Expected: `1 passed`.

- [ ] **Step 5: Add near-match fail-closed tests**

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

- [ ] **Step 6: Run the near-match tests and confirm GREEN**

Run:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py -k near_match
```

Expected: `2 passed`.

- [ ] **Step 7: Add the stronger-assurance fail-closed test**

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

Expected: `4 passed` (positive + two parameterized near matches + stronger assurance).

- [ ] **Step 9: Inspect the diff and prove Task 1 touched test code only**

Run:

```bash
git diff --name-only main...HEAD
```

Expected at this point: the approved Step 21 design/plan documents plus `tests/integration/test_step21_d5_canonical_projection.py`; no production path.

- [ ] **Step 10: Commit Task 1**

```bash
git add tests/integration/test_step21_d5_canonical_projection.py
git commit -m "test(step21): prove canonical wall projection reaches D5"
```

---

### Task 2: Add architecture guards for zero enterprise-rule knowledge in D5/Orchestrator

**Files:**
- Create: `tests/semantic_runtime/test_step21_architecture.py`
- Reference only: `platform/semantic_runtime/`
- Reference only: `platform/orchestrator/`
- Reference only: `providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/data/enterprise_mappings_v1.yaml`

**Interfaces:**
- Consumes: repository source tree only.
- Produces: fail-fast tests that prevent Step 21 or future changes from copying enterprise `A-WALL` knowledge into D5/Orchestrator or adding forbidden package dependencies.

- [ ] **Step 1: Create repository scanning helpers**

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

- [ ] **Step 3: Add the production rule single-owner guard**

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

If this test reveals an existing non-rule production occurrence that predates Step 21, inspect it. Do not broaden the allowlist mechanically. The approved design requires the machine-readable Enterprise Mapping YAML to remain the only production owner of the A-WALL rule.

- [ ] **Step 4: Run architecture guards**

Run:

```bash
pytest -q tests/semantic_runtime/test_step21_architecture.py
```

Expected: `4 passed`.

If a guard fails against the unchanged base, compare the failing occurrence to `main@0ce330abb10a33ae85025f516554d95386480fb5`. Only revise the test if the occurrence is demonstrably existing, non-rule metadata and the revised guard still proves the approved ownership boundary; otherwise treat it as an architecture defect rather than weakening the test.

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

### Task 3: Add Step 21 CI with a strict changed-file boundary and regressions

**Files:**
- Create: `.github/workflows/step21-d5-canonical-projection.yml`

**Interfaces:**
- Consumes: Step 21 test modules from Tasks 1–2.
- Produces: PR/push verification that blocks production-path drift and runs the exact real semantic stack used by Step 21.

- [ ] **Step 1: Create the workflow trigger and environment installation**

Create the workflow with this exact skeleton:

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

Do not install Orchestrator, Semantic MCP, Metro, or DSP Core merely to make the targeted proof run. Those modules are not participants in the Step 21 proof path. The relevant full regression step below may still execute repository tests whose dependency set is satisfied by the established semantic stack; if a suite needs an additional existing package, add only that existing dependency and document why in the commit.

- [ ] **Step 2: Add the changed-file boundary gate**

Append before tests:

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

The allowlist is intentionally exact-file, not broad `tests/**`, so future scope drift cannot hide in unrelated test files.

- [ ] **Step 3: Add targeted proof and architecture guard steps**

Append:

```yaml
      - name: Run Step21 canonical projection proof
        run: |
          pytest -q tests/integration/test_step21_d5_canonical_projection.py

      - name: Run Step21 architecture guards
        run: |
          pytest -q tests/semantic_runtime/test_step21_architecture.py
```

Expected locally: Step 21 targeted total remains `8 passed`.

- [ ] **Step 4: Add upstream regression steps**

Append:

```yaml
      - name: Run semantic-runtime progressive regression
        run: |
          pytest -q tests/semantic_runtime

      - name: Run Semantic Service projection regression
        run: |
          pytest -q \
            tests/semantic_service/test_provider_contracts.py \
            tests/semantic_service/test_registry.py \
            tests/semantic_service/test_service_projection.py \
            tests/semantic_service/test_d5_environment_ref_compatibility.py

      - name: Run Enterprise Mapping regression
        run: |
          pytest -q tests/semantic_providers/enterprise_mapping

      - name: Run Step19 AutoCAD design-fact adapter regression
        run: |
          pytest -q tests/integration/test_autocad_design_fact_adapter.py
```

Before committing, verify the exact Step 19 adapter regression filename exists. If the current repository uses a different existing filename, substitute the exact current file discovered from `tests/integration/`; do not create a duplicate regression file just to match this plan.

- [ ] **Step 5: Add the relevant full Python regression using importlib mode**

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

This intentionally does not add Metro or Semantic MCP to the Step 21 workflow because Step 21 changes none of their production/test surfaces. Existing independent workflows continue protecting them. If execution-time repository policy requires the same broader set as Step 20, widen only the regression command, not the Step 21 production boundary.

- [ ] **Step 6: Verify workflow syntax and targeted commands locally**

Run the exact test commands from the workflow in sequence:

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

Expected: all pass; existing environment-dependent live AutoCAD tests may remain skipped according to their existing guards. Record exact pass/skip counts for the PR description.

- [ ] **Step 7: Verify the changed-file boundary manually against `main`**

Run:

```bash
changed="$(git diff --name-only main...HEAD)"
printf '%s\n' "$changed"
bad="$(printf '%s\n' "$changed" | grep -Ev '^(\.github/workflows/step21-d5-canonical-projection\.yml|docs/superpowers/(specs/2026-08-29-step21-d5-canonical-projection-proof-design\.md|plans/2026-08-29-step21-d5-canonical-projection-proof\.md)|tests/integration/test_step21_d5_canonical_projection\.py|tests/semantic_runtime/test_step21_architecture\.py)$' || true)"
test -z "$bad"
```

Expected: exit code `0` and exactly the four approved Step 21 files plus the already-approved design/plan pair as applicable; no production path.

- [ ] **Step 8: Commit Task 3**

```bash
git add .github/workflows/step21-d5-canonical-projection.yml
git commit -m "ci(step21): verify zero-diff D5 projection proof"
```

---

### Task 4: Final verification, design alignment review, and PR preparation

**Files:**
- Modify only if review finds documentation inconsistency: `docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md`
- Modify only if execution details changed: `docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md`
- No production files.

**Interfaces:**
- Consumes: all artifacts from Tasks 1–3.
- Produces: review evidence and a PR-ready branch; does not merge.

- [ ] **Step 1: Run the focused Step 21 acceptance suite from a clean working tree**

Run:

```bash
pytest -q \
  tests/integration/test_step21_d5_canonical_projection.py \
  tests/semantic_runtime/test_step21_architecture.py
```

Expected: `8 passed`.

- [ ] **Step 2: Run the relevant full regression one final time**

Run:

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

Expected: all pass, with only existing documented skips/warnings. This final local verification is intentionally as broad as Step 20 even though the dedicated Step 21 workflow may remain narrower.

- [ ] **Step 3: Re-run the zero-production diff gate**

Run:

```bash
git diff --name-only main...HEAD
```

Then verify every path is exactly one of:

```text
docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md
docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md
tests/integration/test_step21_d5_canonical_projection.py
tests/semantic_runtime/test_step21_architecture.py
.github/workflows/step21-d5-canonical-projection.yml
```

Any other changed path is a Step 21 scope violation and must be removed or separately designed before PR creation.

- [ ] **Step 4: Review the E2E helper for forbidden semantic ownership**

Run:

```bash
grep -nE 'A-WALL|autocad\.layer|IfcWall|dsp\.enterprise\.mapping' \
  tests/integration/test_step21_d5_canonical_projection.py
```

Expected: matches appear only in test fixture/assertion sections (`_snapshot`, source fact assertions, expected canonical result, pinned provider setup), never inside `_reconstruction_from_claims` or `_projection_ref`.

Manually inspect `_reconstruction_from_claims` and confirm it branches only on:

```text
requested claim subject
predicate == classification
canonical_term_id is present
claim assurance
```

- [ ] **Step 5: Review assurance/fidelity against the approved design**

Confirm the positive D5 guarantee is exactly:

```text
CLASSIFICATION
coverage_state = RESOLVED
semantic_depth = CANONICAL
assurance_level = RULE_DERIVED
geometry_level = NONE
```

Confirm `STANDARD_MAPPED` requirement fails and geometry is never requested/reconstructed.

- [ ] **Step 6: Confirm no new production contract was accidentally frozen**

Verify there is no new public helper/API under production packages for:

```text
SemanticClaim ingestion
SemanticProjectionRef construction
projection hashing
A-WALL matching
AutoCAD -> IFC conversion
```

The test-only `step21-proof-v1` lineage identifier must occur only in the Step 21 integration test and documentation.

- [ ] **Step 7: Commit any review-only documentation correction if necessary**

Only if Tasks 1–6 uncovered a genuine mismatch between the approved design and executable proof:

```bash
git add docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md \
        docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md
git commit -m "docs(step21): align proof with verified implementation"
```

Do not create a cosmetic review commit when no correction is required.

- [ ] **Step 8: Prepare a draft PR; do not merge**

PR title:

```text
test(step21): prove A-WALL canonical projection reaches D5
```

PR body must include:

```markdown
## Goal
Prove Step19 AutoCAD facts -> Step20 Enterprise Mapping -> canonical ifc:IfcWall -> existing D5 FreshnessResolver/PlanningSnapshot with zero D5 production changes.

## Frozen boundaries
- D5 production diff: 0
- Orchestrator production diff: 0
- Enterprise mapping production diff: 0
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
- normalized_fact_batch_hash populated in test projection lineage

## Verification
Paste exact focused and broad pytest pass/skip counts and the changed-file boundary output from the final run.
```

Create the PR as draft unless the established project flow for Step 21 explicitly directs otherwise. Do not merge without a separate explicit user merge authorization.

---

## Self-Review Checklist

Before execution handoff, verify this plan against the approved design:

- [ ] Every positive acceptance item in design section 9 maps to Task 1 assertions.
- [ ] `A-WALLISH` and `X-A-WALL` fail through missing canonical evidence, not hardcoded D5 rejection logic.
- [ ] `STANDARD_MAPPED` requirement fails through existing `FreshnessResolver` assurance comparison.
- [ ] `_reconstruction_from_claims` contains no Host/enterprise mapping constants.
- [ ] `SemanticProjectionRef` construction exists only in test code and is labeled test-only.
- [ ] Exact pinned environment identity is copied into `SemanticEnvironmentRef`.
- [ ] Architecture guards cover D5, Orchestrator, dependency direction, and A-WALL production ownership.
- [ ] CI boundary allows only the two Step 21 test files, design, plan, and dedicated workflow.
- [ ] No existing production file is modified.
- [ ] Final regression includes the broad semantic provider suite used for Step 20 confidence.
- [ ] No placeholder (`TBD`, `TODO`, “implement later”) remains.

## Execution Handoff

Plan execution should use **Inline Execution** in the current session, because that is the established project execution mode. At execution start, read and follow `superpowers:executing-plans`; before each implementation change, follow `superpowers:test-driven-development`; before completion claims, follow `superpowers:verification-before-completion`.

Do not merge the resulting PR without explicit merge authorization.
