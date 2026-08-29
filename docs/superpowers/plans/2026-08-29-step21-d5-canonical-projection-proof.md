# Step 21 — D5 Canonical Projection Proof Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prove the real Step 19 AutoCAD normalized facts and Step 20 Enterprise Mapping projection reach the existing D5 freshness barrier as canonical `ifc:IfcWall` classification evidence, with zero D5/Orchestrator/semantic production changes.

**Architecture:** Add only test composition, architecture guards, and one dedicated CI workflow. The proof uses the real `DesignFactAdapter`, exact pinned `SemanticService` environment, real IFC4.3 and Enterprise Mapping providers, then the existing D5 `FreshnessResolver` reconstruction callback. The test-only bridge understands only canonical claim structure; it never interprets AutoCAD layers or enterprise rules.

**Tech Stack:** Python 3.11, pytest, `design_fact_contracts`, `autocad_sidecar`, `semantic_service`, `semantic_runtime`, IFC4.3 semantic provider, Enterprise Mapping provider, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md`

## Global Constraints

- Base: `main@0ce330abb10a33ae85025f516554d95386480fb5`.
- Branch: `feat/step21-d5-canonical-projection-proof`.
- Never write directly to `main`.
- Production diff must remain zero under `contracts/`, `hosts/autocad/`, `platform/`, and `providers/semantics/`.
- The only implementation files allowed are:
  - `tests/integration/test_step21_d5_canonical_projection.py`
  - `tests/semantic_runtime/test_step21_architecture.py`
  - `.github/workflows/step21-d5-canonical-projection.yml`
  - the approved Step 21 design and plan documents.
- Use real Step 19 Python `DesignFactAdapter`; do not invoke AutoCAD .NET/plugin code.
- Pin exactly `buildingSMART.ifc43@4.3.2.0` and `dsp.enterprise.mapping@1.0.0`.
- D5 must not inspect `A-WALL`, `autocad.layer`, `dsp.enterprise.mapping`, or Host product identity to infer `IfcWall`.
- Positive D5 guarantee is exactly `CLASSIFICATION / RESOLVED / CANONICAL / RULE_DERIVED / geometry NONE`.
- Never upgrade `RULE_DERIVED` to `STANDARD_MAPPED` or `NATIVE_ASSERTED`.
- `A-WALLISH` and `X-A-WALL` must not satisfy classification freshness.
- A `STANDARD_MAPPED` requirement against this same data must fail closed.
- `SemanticProjectionRef` construction in this step is test-only and non-normative.
- No Semantic MCP endpoint, SemanticId, geometry reconstruction, ChangeSet, Host mutation, Metro mapping, IFC vocabulary extension, or Step 22 fidelity logic.
- Use `pytest --import-mode=importlib` for multi-provider regression collections.
- Do not merge the resulting PR without explicit user merge authorization.

---

## File Structure

```text
tests/integration/test_step21_d5_canonical_projection.py
    Real Step19 -> Step20 -> existing D5 positive/negative proof.

tests/semantic_runtime/test_step21_architecture.py
    D5/Orchestrator semantic-boundary and rule-ownership guards.

.github/workflows/step21-d5-canonical-projection.yml
    Exact-file boundary gate plus targeted and relevant regression suites.
```

No production file is modified.

---

### Task 1: Prove Step19 -> Step20 -> existing D5

**Files:**
- Create: `tests/integration/test_step21_d5_canonical_projection.py`
- Reference: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/design_fact_adapter.py`
- Reference: `platform/semantic_service/src/semantic_service/service.py`
- Reference: `platform/semantic_runtime/src/semantic_runtime/freshness.py`

**Interfaces:**
- Consumes: `DesignFactAdapter.normalize_snapshot(payload) -> NormalizedDesignFactBatch`.
- Consumes: `SemanticService.project_facts(facts, environment_id) -> tuple[SemanticClaim, ...]`.
- Consumes: `FreshnessResolver.resolve(...) -> SemanticSnapshot`.
- Produces only private test helpers `_projection_ref(...)` and `_reconstruction_from_claims(...)`.

- [ ] **Step 1: Write the positive test first**

Create the module with these imports and fixture helpers:

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
        "entities": [{
            "nativeId": "A31",
            "nativeKind": "LWPOLYLINE",
            "layer": layer,
        }],
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


def _contract(
    assurance: AssuranceLevel = AssuranceLevel.RULE_DERIVED,
) -> FreshnessContract:
    return build_operation_contract(
        project_id="project-step21",
        document_ref=DOCUMENT_ID,
        canonical_operation="classify.v1",
        targets=(TARGET_SUBJECT,),
        arguments={},
        requirements=(
            AspectRequirement(
                SemanticAspect.CLASSIFICATION,
                geometry_level=GeometryLevel.NONE,
                minimum_coverage=CoverageState.RESOLVED,
                semantic_depth=SemanticDepth.CANONICAL,
                minimum_assurance=assurance,
            ),
        ),
    )
```

Then add the positive test while `_reconstruction_from_claims` is still undefined:

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
        DOCUMENT_ID, TARGET_SUBJECT, SemanticAspect.CLASSIFICATION
    ) is FreshnessState.FRESH
    assert dirty.state(
        DOCUMENT_ID, TARGET_SUBJECT, SemanticAspect.GEOMETRY
    ) is FreshnessState.UNKNOWN
```

- [ ] **Step 2: Verify RED at the composition seam**

Run:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py::test_a_wall_reaches_existing_d5_as_canonical_ifc_wall
```

Expected: failure with `NameError` for `_reconstruction_from_claims` after Step 19 and Step 20 assertions pass.

- [ ] **Step 3: Add deterministic test lineage and provider-neutral reconstruction**

Add:

```python
def _digest(payload: object) -> str:
    return sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()


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
    providers = [
        {
            "provider_id": item.provider_id,
            "version": item.version,
            "content_hash": item.content_hash,
        }
        for item in environment.providers
    ]
    projection_hash = _digest({
        "environment_id": environment.environment_id,
        "environment_hash": environment.content_hash,
        "claims": [_claim_payload(claim) for claim in claims],
    })
    return SemanticProjectionRef(
        projection_id=f"step21:{projection_hash}",
        projection_hash=projection_hash,
        semantic_model_version="step21-proof-v1",
        provider_set_hash=_digest(providers),
        mapping_profile_set_hash=_digest({"providers": providers}),
        normalized_fact_batch_hash=_digest(facts.to_dict()),
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
    strongest: dict[str, AssuranceLevel] = {}

    for claim in claims:
        if claim.subject not in requested:
            continue
        if claim.predicate != "classification" or claim.canonical_term_id is None:
            continue
        try:
            assurance = AssuranceLevel[claim.assurance]
        except KeyError as exc:
            raise ValueError(
                f"unknown canonical claim assurance: {claim.assurance!r}"
            ) from exc
        strongest[claim.subject] = max(
            assurance,
            strongest.get(claim.subject, AssuranceLevel.UNKNOWN),
        )

    guarantees: tuple[AspectGuarantee, ...] = ()
    if requested and requested.issubset(strongest):
        guarantees = (
            AspectGuarantee(
                SemanticAspect.CLASSIFICATION,
                geometry_level=GeometryLevel.NONE,
                coverage_state=CoverageState.RESOLVED,
                semantic_depth=SemanticDepth.CANONICAL,
                assurance_level=min(strongest[item] for item in requested),
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

The helper must contain no `A-WALL`, `autocad.layer`, `IfcWall`, `dsp.enterprise.mapping`, or Host-specific branch.

- [ ] **Step 4: Verify positive GREEN**

Run the positive test again. Expected: `1 passed`.

- [ ] **Step 5: Add near-match fail-closed coverage**

```python
@pytest.mark.parametrize("layer", ["A-WALLISH", "X-A-WALL"])
def test_near_match_layer_does_not_satisfy_d5_classification(layer: str) -> None:
    facts = DesignFactAdapter().normalize_snapshot(_snapshot(layer))
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
        DOCUMENT_ID, TARGET_SUBJECT, SemanticAspect.CLASSIFICATION
    ) is FreshnessState.DIRTY
```

Run:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py -k near_match
```

Expected: `2 passed`.

- [ ] **Step 6: Add assurance-strength fail-closed coverage**

```python
def test_rule_derived_claim_cannot_satisfy_standard_mapped_requirement() -> None:
    facts = DesignFactAdapter().normalize_snapshot(_snapshot("A-WALL"))
    service, environment = _semantic_stack()
    claims = service.project_facts(facts, environment.environment_id)
    assert len(claims) == 1
    assert claims[0].assurance == "RULE_DERIVED"

    dirty = DirtyMap()
    dirty.mark_dirty(DOCUMENT_ID, TARGET_SUBJECT, (SemanticAspect.CLASSIFICATION,))
    contract = _contract(AssuranceLevel.STANDARD_MAPPED)
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
        DOCUMENT_ID, TARGET_SUBJECT, SemanticAspect.CLASSIFICATION
    ) is FreshnessState.DIRTY
```

- [ ] **Step 7: Run Task 1 suite and commit**

Run:

```bash
pytest -q tests/integration/test_step21_d5_canonical_projection.py
```

Expected: `4 passed`.

Then:

```bash
git add tests/integration/test_step21_d5_canonical_projection.py
git commit -m "test(step21): prove canonical wall projection reaches D5"
```

---

### Task 2: Add architecture guards

**Files:**
- Create: `tests/semantic_runtime/test_step21_architecture.py`

**Interfaces:**
- Consumes repository source text only.
- Produces four fail-fast architecture tests.

- [ ] **Step 1: Create tree scanners and guards**

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
            ".py", ".cs", ".yaml", ".yml", ".json", ".toml"
        }:
            yield path


def _tree_text(root: Path) -> str:
    return "\n".join(path.read_text(encoding="utf-8") for path in _text_files(root))


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


def test_a_wall_rule_has_one_production_source_owner() -> None:
    roots = (
        ROOT / "contracts",
        ROOT / "hosts",
        ROOT / "platform",
        ROOT / "providers" / "semantics",
    )
    hits = []
    for root in roots:
        for path in _text_files(root):
            if "A-WALL" in path.read_text(encoding="utf-8"):
                hits.append(path.relative_to(ROOT))
    assert hits == [ENTERPRISE_RULE.relative_to(ROOT)]
```

- [ ] **Step 2: Run architecture guards**

```bash
pytest -q tests/semantic_runtime/test_step21_architecture.py
```

Expected: `4 passed`. Do not weaken a failing boundary test with a broad allowlist.

- [ ] **Step 3: Run all Step 21 focused tests and commit**

```bash
pytest -q \
  tests/integration/test_step21_d5_canonical_projection.py \
  tests/semantic_runtime/test_step21_architecture.py
```

Expected: `8 passed`.

Commit:

```bash
git add tests/semantic_runtime/test_step21_architecture.py
git commit -m "test(step21): guard D5 semantic boundaries"
```

---

### Task 3: Add exact-boundary CI

**Files:**
- Create: `.github/workflows/step21-d5-canonical-projection.yml`
- Existing Step 19 regression path: `tests/contracts/test_autocad_design_fact_adapter.py`

**Interfaces:**
- Consumes Task 1/2 tests plus current upstream regression suites.
- Produces one Step 21 workflow with an exact-file PR diff gate.

- [ ] **Step 1: Create workflow setup and boundary gate**

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
            echo "Step21 changed files outside approved boundary:"
            printf '%s\n' "$bad"
            exit 1
          fi
```

- [ ] **Step 2: Add targeted and upstream regression steps**

Append:

```yaml
      - name: Run Step21 canonical projection proof
        run: pytest -q tests/integration/test_step21_d5_canonical_projection.py
      - name: Run Step21 architecture guards
        run: pytest -q tests/semantic_runtime/test_step21_architecture.py
      - name: Run semantic-runtime regression
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
      - name: Run relevant full Python regression
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

- [ ] **Step 3: Execute the exact workflow commands locally**

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

Expected: all pass. Existing live AutoCAD tests may remain skipped only under their existing `AGENT_HOST_TEST=1` guard. Capture fresh pass/skip/warning counts for the PR description.

- [ ] **Step 4: Run exact-file boundary locally and commit**

```bash
changed="$(git diff --name-only main...HEAD)"
bad="$(printf '%s\n' "$changed" | grep -Ev '^(\.github/workflows/step21-d5-canonical-projection\.yml|docs/superpowers/(specs/2026-08-29-step21-d5-canonical-projection-proof-design\.md|plans/2026-08-29-step21-d5-canonical-projection-proof\.md)|tests/integration/test_step21_d5_canonical_projection\.py|tests/semantic_runtime/test_step21_architecture\.py)$' || true)"
printf '%s\n' "$changed"
test -z "$bad"
```

Expected: exit code `0`.

Commit:

```bash
git add .github/workflows/step21-d5-canonical-projection.yml
git commit -m "ci(step21): verify zero-diff D5 projection proof"
```

---

### Task 4: Final verification and draft PR

**Files:**
- Review only: Step 21 design and plan.
- No production files.

**Interfaces:**
- Consumes Tasks 1–3.
- Produces verified PR-ready branch and a draft PR; never merges.

- [ ] **Step 1: Run fresh focused verification**

```bash
pytest -q \
  tests/integration/test_step21_d5_canonical_projection.py \
  tests/semantic_runtime/test_step21_architecture.py
```

Expected: `8 passed`.

- [ ] **Step 2: Run broad semantic regression**

```bash
python -m pip install \
  -e providers/semantics/dsp_core \
  -e providers/semantics/metro_v32
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

Expected: all pass with only existing documented skips/warnings. Use the actual current counts in the PR description.

- [ ] **Step 3: Prove final diff is exactly five files**

```bash
git diff --name-only main...HEAD
```

Expected exactly:

```text
.github/workflows/step21-d5-canonical-projection.yml
docs/superpowers/plans/2026-08-29-step21-d5-canonical-projection-proof.md
docs/superpowers/specs/2026-08-29-step21-d5-canonical-projection-proof-design.md
tests/integration/test_step21_d5_canonical_projection.py
tests/semantic_runtime/test_step21_architecture.py
```

- [ ] **Step 4: Prove helper neutrality and zero production diff**

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

git diff --name-only main...HEAD | grep -E '^(contracts/|hosts/|platform/|providers/)' && exit 1 || true
```

Expected: helper check prints `OK`; production diff command prints nothing.

- [ ] **Step 5: Review progressive semantics**

Verify positive snapshot is exactly:

```text
CLASSIFICATION
coverage_state = RESOLVED
semantic_depth = CANONICAL
assurance_level = RULE_DERIVED
geometry_level = NONE
```

Verify the stronger assurance test fails at `CLASSIFICATION.assurance`, and near-match cases fail at `CLASSIFICATION.freshness`.

- [ ] **Step 6: Create draft PR using fresh verification results**

PR title:

```text
test(step21): prove A-WALL canonical projection reaches D5
```

PR body must contain these sections and must paste the exact focused and broad pytest result lines produced immediately above rather than a prefilled count:

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
Paste the exact focused Step21 pytest summary line.
Paste the exact broad Python regression pytest summary line, including skips/warnings when present.
Changed-file boundary: exactly the five approved Step21 files.
```

Create the PR as **draft**. Do not merge without separate explicit user authorization.

---

## Self-Review Checklist

- [x] Every positive acceptance requirement maps to Task 1 assertions.
- [x] Near-match failures depend on missing canonical evidence, not D5 hardcoded rule logic.
- [x] Stronger assurance fails through existing `FreshnessResolver` comparison.
- [x] `_reconstruction_from_claims` is provider-neutral and Host-neutral.
- [x] `SemanticProjectionRef` construction is test-only and explicitly non-normative.
- [x] Exact pinned environment identity flows into `SemanticEnvironmentRef`.
- [x] Architecture guards cover D5, Orchestrator, dependency direction, and single A-WALL production ownership.
- [x] Current Step 19 adapter regression path is `tests/contracts/test_autocad_design_fact_adapter.py`.
- [x] Type names used by the plan are exported by current `semantic_runtime` and `semantic_service` public surfaces.
- [x] CI boundary permits only the five approved Step 21 artifacts.
- [x] No production source edit is planned.
- [x] Final regression covers contracts, integration, Orchestrator, D5, Semantic Service, DSP Core, IFC4.3, Metro v3.2, and Enterprise Mapping.
- [x] The plan contains no unresolved implementation filename, interface, or runtime-data token.

## Execution Handoff

Execution mode is **Inline Execution**. At implementation start:

1. Read and follow `superpowers:executing-plans`.
2. Read and follow `superpowers:test-driven-development` before implementation changes.
3. Execute Tasks 1–4 in order, preserving RED/GREEN checkpoints and commit boundaries.
4. Read and follow `superpowers:verification-before-completion` before claiming completion or PR readiness.
5. Create the draft PR only after fresh verification.
6. Do not merge without explicit user merge authorization.
