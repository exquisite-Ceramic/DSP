# Metro Semantic Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Spec v0.6 Phase D step 17 as `dsp.metro.semantic@3.2`, an isolated DOMAIN Semantic Provider that owns `metro:*`, returns only reviewed ACTIVE `metro:* -> ifc:*` mappings, performs claim-local Metro validation, and preserves project decisions as unfrozen metadata.

**Architecture:** The Metro V3.2 Markdown is the human audit source only. PR #10 packages a reviewed `metro_v3_2.yaml`, validates/normalizes it once into immutable provider-local records, computes a deterministic machine-semantic SHA-256 hash, and exposes the existing Semantic Service `VOCABULARY`, `MAPPING`, `VALIDATION`, and marker-only `PROJECTION` contracts. IFC truth remains owned by `buildingSMART.ifc43@4.3.2.0`; Metro production code stores `ifc:*` references but never imports the concrete IFC provider.

**Tech Stack:** Python 3.11+, `semantic-service>=0.1.0`, `PyYAML==6.0.3`, dataclasses, `MappingProxyType`, canonical JSON + SHA-256, pytest/pytest-asyncio, existing Semantic MCP, existing IFC4.3 and DSP Core providers for integration tests.

**Spec:** `docs/superpowers/specs/2026-08-28-metro-semantic-provider-design.md`

## Global Constraints

- Provider identity: `dsp.metro.semantic@3.2`; type: `DOMAIN`.
- Namespaces: `metro`, `ifc`; authority: `metro -> AUTHORITATIVE`, `ifc -> EXTENSION`.
- Capabilities: exactly `VOCABULARY`, `MAPPING`, `VALIDATION`, `PROJECTION`.
- Exact dependency: `buildingSMART.ifc43@4.3.2.0`.
- No `dsp.core@1.0` dependency unless reviewed machine data actually contains machine-semantic `dsp:*` references.
- Production Metro code MUST NOT import `ifc43_semantic_provider`, `ifcopenshell`, `semantic_runtime`, `semantic_mcp`, Host providers, D5, D6, or D7.
- Existing production files under `platform/semantic_service`, `platform/semantic_runtime`, `platform/semantic_mcp`, Hosts, D5/D6/D7 MUST NOT change for PR #10.
- Runtime reads packaged YAML only; no runtime Markdown parsing, scraping, or network access.
- Human-source SHA-256 is exactly `596a140612f4d3af49dccfe01c235be28cf76b8280334bfc2920f29fc8ee422b`.
- `metro:*` is the only vocabulary namespace this provider resolves authoritatively.
- PR #10 active mapping direction is only `metro:* -> ifc:*`.
- `RECOMMENDED`, `EXAMPLE`, `PROJECT_EXTENSION_DRAFT`, unfrozen decisions, and project-choice options MUST NOT become active mappings.
- DEC-01 through DEC-10 remain `UNFROZEN`.
- `P-M`, `P-C`, `P-R` are requirement metadata, not validation statuses.
- Claim-local validation MUST NOT pretend to implement complete IDS, entity/batch missing-field checks, graph/cardinality, uniqueness, geometry, Alignment continuity, clash, clearance, or project acceptance.
- `PROJECTION` stays marker-only; do not add `project_facts()`.
- Golden `content_hash` is frozen only after human inspection of the complete normalized catalog and MUST NOT be auto-updated by CI/tooling.
- Implementation decisions in this plan are not main-Spec amendments.
- Follow RED -> GREEN TDD; each task ends with a separately reviewable commit.

## File Structure

```text
providers/semantics/metro_v32/
  pyproject.toml
  README.md
  src/metro_semantic_provider/
    __init__.py
    errors.py
    hashing.py
    model.py
    source.py
    normalization.py
    catalog.py
    mapping.py
    validation.py
    provider.py
    golden.py
    data/metro_v3_2.yaml

tests/semantic_providers/metro_v32/
  test_metro_v32_source.py
  test_metro_v32_catalog.py
  test_metro_v32_hashing.py
  test_metro_v32_mapping.py
  test_metro_v32_validation.py
  test_metro_v32_provider.py
  test_metro_v32_service_integration.py
  test_metro_v32_mcp_integration.py
  test_metro_v32_architecture.py

.github/workflows/metro-semantic-provider.yml
```

All test basenames include `metro_v32` to avoid the pytest module-name collisions found during PR #9.

---

### Task 1: Package boundary, source feasibility gate, and exact source provenance

**Files:**
- Create: `providers/semantics/metro_v32/pyproject.toml`
- Create: `providers/semantics/metro_v32/src/metro_semantic_provider/errors.py`
- Create: `providers/semantics/metro_v32/src/metro_semantic_provider/source.py`
- Create: `providers/semantics/metro_v32/src/metro_semantic_provider/data/metro_v3_2.yaml`
- Test: `tests/semantic_providers/metro_v32/test_metro_v32_source.py`

**Interfaces:**
- Produces `METRO_V32_SOURCE_SHA256`, `load_raw_machine_source()`, `validate_root_metadata()`, and provider-local errors.

- [ ] **Step 1: Reproduce the source audit**

Run:

```bash
sha256sum '/mnt/data/IFC4.3地铁BIM数据标准_V3.2_构件属性增强合并版.md'
sed -n '3944,4170p' '/mnt/data/IFC4.3地铁BIM数据标准_V3.2_构件属性增强合并版.md'
sed -n '4224,4340p' '/mnt/data/IFC4.3地铁BIM数据标准_V3.2_构件属性增强合并版.md'
```

Expected digest:

```text
596a140612f4d3af49dccfe01c235be28cf76b8280334bfc2920f29fc8ee422b
```

Expected source facts: 37 Chapter 21.1 `PsetProj_*` containers; DEC-01 through DEC-10; Chapter 2.6 prohibits `IfcTrack`, `IfcTunnel`, `IfcTunnelPart`, `IfcSprinkler`, `IfcFanCoilUnit`, `IfcPrecastConcreteElement`. If these do not match, stop before production code.

- [ ] **Step 2: Write RED tests**

```python
from copy import deepcopy
import pytest
from metro_semantic_provider.errors import MetroSourceError
from metro_semantic_provider.source import (
    METRO_V32_SOURCE_SHA256,
    load_raw_machine_source,
    validate_root_metadata,
)

EXPECTED = "596a140612f4d3af49dccfe01c235be28cf76b8280334bfc2920f29fc8ee422b"


def test_source_identity_is_exact():
    payload = load_raw_machine_source()
    assert METRO_V32_SOURCE_SHA256 == EXPECTED
    assert payload["metadata"] == {
        "provider_id": "dsp.metro.semantic",
        "provider_version": "3.2",
        "source_document_title": "IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版",
        "source_document_sha256": EXPECTED,
        "target_ifc_provider_id": "buildingSMART.ifc43",
        "target_ifc_provider_version": "4.3.2.0",
        "target_ifc_schema": "IFC4X3_ADD2",
    }


def test_wrong_source_digest_fails_closed():
    payload = deepcopy(dict(load_raw_machine_source()))
    payload["metadata"] = dict(payload["metadata"])
    payload["metadata"]["source_document_sha256"] = "0" * 64
    with pytest.raises(MetroSourceError, match="source_document_sha256"):
        validate_root_metadata(payload)
```

Run:

```bash
PYTHONPATH=providers/semantics/metro_v32/src:platform/semantic_service/src pytest -q tests/semantic_providers/metro_v32/test_metro_v32_source.py
```

Expected RED: import failure because the package does not exist.

- [ ] **Step 3: Create package metadata**

```toml
[project]
name = "metro-semantic-provider"
version = "3.2"
description = "DSP Metro V3.2 domain Semantic Provider."
requires-python = ">=3.11"
dependencies = [
    "semantic-service>=0.1.0",
    "PyYAML==6.0.3",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]

[tool.setuptools.package-data]
metro_semantic_provider = ["data/*.yaml"]
```

- [ ] **Step 4: Create provider-local errors**

```python
class MetroSemanticProviderError(RuntimeError):
    pass

class MetroSourceError(MetroSemanticProviderError):
    pass

class MetroCatalogBuildError(MetroSemanticProviderError):
    pass

class MetroTermNotFoundError(MetroSemanticProviderError):
    pass

class MetroMappingError(MetroSemanticProviderError):
    pass

class MetroValidationError(MetroSemanticProviderError):
    pass
```

- [ ] **Step 5: Create the minimal YAML root**

```yaml
metadata:
  provider_id: dsp.metro.semantic
  provider_version: "3.2"
  source_document_title: "IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版"
  source_document_sha256: "596a140612f4d3af49dccfe01c235be28cf76b8280334bfc2920f29fc8ee422b"
  target_ifc_provider_id: buildingSMART.ifc43
  target_ifc_provider_version: "4.3.2.0"
  target_ifc_schema: IFC4X3_ADD2
source_coverage:
  chapter21_project_pset_containers: []
  structured_property_rows: 0
  inline_only_project_psets: []
  decision_ids: []
  prohibited_entity_names: []
terms: []
mappings: []
validation_rules: []
decisions: []
```

- [ ] **Step 6: Implement safe packaged YAML loading**

```python
from collections.abc import Mapping
from importlib.resources import files
from types import MappingProxyType
import yaml
from .errors import MetroSourceError

METRO_V32_SOURCE_SHA256 = "596a140612f4d3af49dccfe01c235be28cf76b8280334bfc2920f29fc8ee422b"
_EXPECTED = {
    "provider_id": "dsp.metro.semantic",
    "provider_version": "3.2",
    "source_document_title": "IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版",
    "source_document_sha256": METRO_V32_SOURCE_SHA256,
    "target_ifc_provider_id": "buildingSMART.ifc43",
    "target_ifc_provider_version": "4.3.2.0",
    "target_ifc_schema": "IFC4X3_ADD2",
}


def validate_root_metadata(payload: Mapping[str, object]) -> None:
    metadata = payload.get("metadata")
    if not isinstance(metadata, Mapping):
        raise MetroSourceError("metadata must be a mapping")
    for key, expected in _EXPECTED.items():
        if metadata.get(key) != expected:
            raise MetroSourceError(f"{key} mismatch")


def load_raw_machine_source() -> Mapping[str, object]:
    resource = files("metro_semantic_provider").joinpath("data", "metro_v3_2.yaml")
    try:
        payload = yaml.safe_load(resource.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise MetroSourceError("failed to load Metro V3.2 machine source") from exc
    if not isinstance(payload, Mapping):
        raise MetroSourceError("root must be a mapping")
    validate_root_metadata(payload)
    return MappingProxyType(dict(payload))
```

- [ ] **Step 7: GREEN + commit**

```bash
python -m pip install -e platform/semantic_service -e providers/semantics/metro_v32
pytest -q tests/semantic_providers/metro_v32/test_metro_v32_source.py
git add providers/semantics/metro_v32 tests/semantic_providers/metro_v32/test_metro_v32_source.py
git commit -m "feat(semantic): add Metro V3.2 source gate"
```

---

### Task 2: Reviewed machine source, immutable records, normalization, catalog, and hash

**Files:**
- Modify: `data/metro_v3_2.yaml`
- Create: `model.py`, `hashing.py`, `normalization.py`, `catalog.py`
- Test: `test_metro_v32_catalog.py`, `test_metro_v32_hashing.py`

**Interfaces:**
- `normalize_machine_source(payload) -> MetroNormalizedSource`
- `semantic_content_hash(payload) -> str`
- `build_catalog(payload) -> MetroCatalog`

- [ ] **Step 1: Write coverage/immutability/hash RED tests**

The test must freeze this exact Chapter 21.1 Pset inventory:

```python
EXPECTED_PROJECT_PSETS = {
    "PsetProj_RailwayIdentity", "PsetProj_SpatialPartition",
    "PsetProj_AlignmentDesign", "PsetProj_HorizontalSegmentDesign",
    "PsetProj_Chainage", "PsetProj_TrackGeometry",
    "PsetProj_RailSpecification", "PsetProj_Turnout",
    "PsetProj_StationIdentity", "PsetProj_SpaceFunction",
    "PsetProj_PlatformScreenDoor", "PsetProj_TunnelSegment",
    "PsetProj_SegmentRing", "PsetProj_SegmentBlock",
    "PsetProj_BoreholeInvestigation", "PsetProj_GeotechnicalStratum",
    "PsetProj_ClearanceEnvelope", "PsetProj_AssetCommon",
    "PsetProj_FanPerformance", "PsetProj_PumpPerformance",
    "PsetProj_SignalOccurrence", "PsetProj_GeometryQuality",
    "PsetProj_CoordinateMetadata", "PsetProj_ObjectIdentity",
    "PsetProj_BuildingElementDesign", "PsetProj_WallDesign",
    "PsetProj_SlabDesign", "PsetProj_StructuralElement",
    "PsetProj_PileDesign", "PsetProj_DoorOperation",
    "PsetProj_WindowPerformance", "PsetProj_VerticalCirculation",
    "PsetProj_FinishSpecification", "PsetProj_OpeningCoordination",
    "PsetProj_EmbeddedItem", "PsetProj_TemporarySupport",
    "PsetProj_JointAndWaterproofing",
}


def test_source_coverage_is_explicit():
    coverage = load_raw_machine_source()["source_coverage"]
    assert set(coverage["chapter21_project_pset_containers"]) == EXPECTED_PROJECT_PSETS
    assert len(coverage["chapter21_project_pset_containers"]) == 37
    assert coverage["structured_property_rows"] == 236
    assert set(coverage["decision_ids"]) == {f"DEC-{i:02d}" for i in range(1, 11)}
    assert set(coverage["prohibited_entity_names"]) == {
        "IfcTrack", "IfcTunnel", "IfcTunnelPart",
        "IfcSprinkler", "IfcFanCoilUnit", "IfcPrecastConcreteElement",
    }


def test_all_decisions_are_unfrozen():
    catalog = build_catalog(load_raw_machine_source())
    assert {item.state.value for item in catalog.decisions} == {"UNFROZEN"}


def test_repeated_builds_have_identical_hash():
    assert build_catalog(load_raw_machine_source()).content_hash == build_catalog(load_raw_machine_source()).content_hash
```

Add fail-closed tests for duplicate term/mapping/rule/decision IDs, unknown normative/requirement states, ACTIVE non-IFC target, unknown Metro source term, conflicting ACTIVE mappings, and FROZEN decision without selected option.

Run and confirm RED because these modules and the completed YAML do not exist.

- [ ] **Step 2: Populate the reviewed YAML from V3.2 with explicit coverage rules**

Use these exact transcription rules:

1. Add all 37 Chapter 21.1 Pset containers.
2. Audit exactly 236 structured property table rows under `PsetProj_*` headings.
3. Add inline-only definitions for `PsetProj_StationIdentity`, `PsetProj_WallDesign`, `PsetProj_SlabDesign`, `PsetProj_PileDesign`, `PsetProj_DoorOperation`, `PsetProj_WindowPerformance`, `PsetProj_FinishSpecification`, `PsetProj_JointAndWaterproofing`.
4. Container ID: `metro:ProjectPset.<Stem>`; property ID: `metro:<Stem>.<PropertyName>`; physical `PsetProj_*` remains `carrier_name` metadata.
5. Split rows that name multiple backticked properties into one canonical property term per property while keeping `structured_property_rows=236` as the source-row audit count.
6. Do not infer missing datatype. Explicit multiple datatype alternatives become `datatype_options`; do not choose one.
7. Section 11.15 performance examples do not become field constraints; their Chapter 21 container identities may remain `PROJECT_EXTENSION_DRAFT`.
8. Add all DEC-01..10 as `UNFROZEN` with subjects:

```text
DEC-01 metro:ProjectLengthUnit
DEC-02 metro:TunnelAggregationParent
DEC-03 metro:TrackBed
DEC-04 metro:CrossPassageSpace
DEC-05 metro:ClearanceEnvelope
DEC-06 metro:AlignmentFileStrategy
DEC-07 metro:TypeInstancePropertyOverride
DEC-08 metro:SegmentOpeningGeometryDepth
DEC-09 metro:MepPortRequirement
DEC-10 metro:CustomEnumLanguage
```

9. Add Chapter 2.6 prohibitions and Chapter 18.7 invalid usages (`IfcTrackElement[TURNOUT]`, `IfcReferent[KILOMETERPOINT]`, `IfcElectricDistributionBoard`) as rules, never fake IFC terms.
10. ACTIVE mappings require one legal IFC choice, no `项目映射` marker, no slash alternative, and no Chapter 19 freeze requirement.
11. Reviewed ACTIVE baseline includes:

```text
metro:RailwayFacility -> ifc:IfcRailway
metro:TrackSpace -> ifc:IfcRailwayPart [TRACK]
metro:PlainTrackSection -> ifc:IfcRailwayPart [PLAINTRACK]
metro:TurnoutTrackSection -> ifc:IfcRailwayPart [TURNOUTTRACK]
metro:RunningRail -> ifc:IfcRail [RAIL]
metro:Sleeper -> ifc:IfcTrackElement [SLEEPER]
metro:Frog -> ifc:IfcTrackElement [FROG]
metro:TurnoutAssembly -> ifc:IfcElementAssembly [TURNOUTPANEL]
metro:TrackPanel -> ifc:IfcElementAssembly [TRACKPANEL]
metro:RailFastening -> ifc:IfcMechanicalFastener [RAILFASTENING]
metro:RailJoint -> ifc:IfcMechanicalFastener [RAILJOINT]
metro:Station -> ifc:IfcBuilding
metro:FunctionalSpace -> ifc:IfcSpace
metro:Borehole -> ifc:IfcBorehole
metro:GeotechnicalStratum -> ifc:IfcGeotechnicalStratum
metro:Fan -> ifc:IfcFan
metro:Pump -> ifc:IfcPump
metro:Signal -> ifc:IfcSignal
```

Do not activate `metro:TunnelSegment`, `metro:SegmentRing`, `metro:SegmentBlock`, `metro:TrackBed`, `metro:ClearanceEnvelope`, `metro:FanCoilUnit`.

Representative records:

```yaml
- term_id: metro:TunnelSegment.ConstructionMethod
  kind: PROJECT_PROPERTY
  normative_class: PROJECT_EXTENSION_DRAFT
  requirement_level: P-M
  description: 施工工法
  schema:
    carrier_kind: PROJECT_PSET
    carrier_name: PsetProj_TunnelSegment
    property_name: ConstructionMethod
    datatype: ifc:IfcLabel
    allowed_values: [SHIELD, NATM, CUT_AND_COVER, PIPE_JACKING]
    applicable_entity: ifc:IfcFacilityPartCommon
    applicable_predefined_type: SEGMENT
```

```yaml
- mapping_id: metro:Mapping.RunningRail.ToIfcRail
  source_term_id: metro:RunningRail
  state: ACTIVE
  normative_class: NORMATIVE
  target_term_id: ifc:IfcRail
  constraints:
    - term_id: ifc:IfcRail.PredefinedType
      equals: RAIL
```

- [ ] **Step 3: Add exact record models and canonical hash utility**

Use enums:

```python
class NormativeClass(str, Enum):
    NORMATIVE = "NORMATIVE"
    PROJECT_EXTENSION_DRAFT = "PROJECT_EXTENSION_DRAFT"
    RECOMMENDED = "RECOMMENDED"
    EXAMPLE = "EXAMPLE"
    DECISION_OPTION = "DECISION_OPTION"
    PROHIBITED = "PROHIBITED"

class RequirementLevel(str, Enum):
    IFC_M = "IFC-M"; IFC_O = "IFC-O"; P_M = "P-M"; P_C = "P-C"; P_R = "P-R"; PROHIBITED = "PROHIBITED"

class MappingState(str, Enum):
    ACTIVE = "ACTIVE"; CANDIDATE = "CANDIDATE"; DECISION_OPTION = "DECISION_OPTION"

class DecisionState(str, Enum):
    UNFROZEN = "UNFROZEN"; FROZEN = "FROZEN"
```

Create frozen records `MetroTermRecord`, `MetroConstraint`, `MetroMappingRecord`, `MetroValidationRuleRecord`, `MetroDecisionRecord`, `MetroNormalizedSource`. `MetroNormalizedSource` contains tuples for terms/mappings/rules/decisions plus `hash_payload: Mapping[str, object]`.

Canonical hashing:

```python
def semantic_content_hash(payload: object) -> str:
    encoded = json.dumps(
        _normalize(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
```

`_normalize` recursively sorts mappings, normalizes enums to `.value`, preserves sequence order, sorts sets, and never hashes Python repr/memory addresses.

- [ ] **Step 4: Implement fail-closed normalization and immutable catalog**

`normalize_machine_source(payload) -> MetroNormalizedSource` must enforce all Task 2 RED invariants. Hash payload includes machine schema, normative/requirement class, source coverage, mapping state/constraints, rules, decision state/options/recommendation/selection. It excludes description, source page/line/section, URLs, examples, YAML ordering.

`MetroCatalog` exposes immutable tuples/indexes and:

```python
def get(self, term_id: str) -> MetroTermRecord: ...
def schema_for(self, term_id: str) -> Mapping[str, object]: ...
def build_catalog(payload: Mapping[str, object]) -> MetroCatalog: ...
```

`get()` must also expose mapping IDs as `MAPPING_RULE`, validation-rule IDs as `VALIDATION_RULE`, and `metro:Decision.DEC-xx` as `DECISION` synthetic vocabulary records. Unknown terms raise `MetroTermNotFoundError`.

- [ ] **Step 5: GREEN + commit**

```bash
pytest -q tests/semantic_providers/metro_v32/test_metro_v32_source.py tests/semantic_providers/metro_v32/test_metro_v32_catalog.py tests/semantic_providers/metro_v32/test_metro_v32_hashing.py
git add providers/semantics/metro_v32 tests/semantic_providers/metro_v32
git commit -m "feat(semantic): build Metro V3.2 machine catalog"
```

---

### Task 3: ACTIVE Metro-to-IFC mapping

**Files:** `mapping.py`, `test_metro_v32_mapping.py`

**Produces:**

```python
def find_mappings_for_claim(
    catalog: MetroCatalog,
    source_claim: SemanticClaim,
    provenance: ProviderProvenance,
    target_namespace: str | None = None,
) -> tuple[MappingCandidate, ...]: ...
```

- [ ] **Step 1: RED tests**

```python
def test_running_rail_maps_to_ifc_rail():
    results = find_mappings_for_claim(
        _catalog(), SemanticClaim(subject="rail-1", canonical_term_id="metro:RunningRail"), PROVENANCE, "ifc"
    )
    assert [(x.mapping_id, x.target_term_id) for x in results] == [
        ("metro:Mapping.RunningRail.ToIfcRail", "ifc:IfcRail")
    ]


def test_unfrozen_track_bed_and_clearance_return_no_mapping():
    assert find_mappings_for_claim(_catalog(), SemanticClaim(subject="b", canonical_term_id="metro:TrackBed"), PROVENANCE, "ifc") == ()
    assert find_mappings_for_claim(_catalog(), SemanticClaim(subject="c", canonical_term_id="metro:ClearanceEnvelope"), PROVENANCE, "ifc") == ()


def test_non_metro_or_non_ifc_target_is_not_mapped():
    assert find_mappings_for_claim(_catalog(), SemanticClaim(subject="x", canonical_term_id="ifc:IfcWall"), PROVENANCE, "ifc") == ()
    assert find_mappings_for_claim(_catalog(), SemanticClaim(subject="x", canonical_term_id="metro:RunningRail"), PROVENANCE, "dsp") == ()
```

- [ ] **Step 2: Verify RED, then implement only ACTIVE filtering**

```python
def find_mappings_for_claim(catalog, source_claim, provenance, target_namespace=None):
    source = source_claim.canonical_term_id
    if source is None or not source.startswith("metro:"):
        return ()
    if target_namespace not in (None, "ifc"):
        return ()
    items = []
    for record in catalog.mappings:
        if record.state is not MappingState.ACTIVE or record.source_term_id != source:
            continue
        if not record.target_term_id.startswith("ifc:"):
            continue
        items.append(MappingCandidate(record.mapping_id, record.target_term_id, provenance, ()))
    return tuple(sorted(items, key=lambda item: item.mapping_id))
```

No Host/native classification and no recommendation inference.

- [ ] **Step 3: GREEN + commit**

```bash
pytest -q tests/semantic_providers/metro_v32/test_metro_v32_mapping.py tests/semantic_providers/metro_v32/test_metro_v32_catalog.py
git add providers/semantics/metro_v32/src/metro_semantic_provider/mapping.py tests/semantic_providers/metro_v32/test_metro_v32_mapping.py
git commit -m "feat(semantic): add Metro deterministic mappings"
```

---

### Task 4: Claim-local Metro validation

**Files:** `validation.py`, `test_metro_v32_validation.py`

**Produces:**

```python
def validate_claim_against_metro(
    catalog: MetroCatalog,
    claim: SemanticClaim,
    provenance: ProviderProvenance,
) -> tuple[ValidationFinding, ...]: ...
```

- [ ] **Step 1: RED tests**

Cover exact cases:

```python
def test_construction_method_enum_pass_and_fail():
    good = _validate(SemanticClaim(subject="s", canonical_term_id="metro:TunnelSegment.ConstructionMethod", value="SHIELD"))
    bad = _validate(SemanticClaim(subject="s", canonical_term_id="metro:TunnelSegment.ConstructionMethod", value="MAGIC"))
    assert any(x.rule_id.endswith("AllowedValues") and x.status is ValidationStatus.PASS for x in good)
    assert any(x.rule_id.endswith("AllowedValues") and x.status is ValidationStatus.FAIL for x in bad)


def test_explicit_ifc_tunnel_usage_fails():
    findings = _validate(SemanticClaim(subject="x", canonical_term_id="ifc:IfcTunnel"))
    assert any(x.rule_id == "metro:Rule.ProhibitIfcTunnelEntity" and x.status is ValidationStatus.FAIL for x in findings)


def test_p_m_does_not_invent_missing_sibling_failure():
    findings = _validate(SemanticClaim(subject="e", canonical_term_id="metro:BuildingElementDesign.DesignStatus", value="WORKING"))
    assert all("ElementCode.Missing" not in x.rule_id for x in findings)


def test_measure_with_unit_needs_external_unit_context():
    findings = _validate(SemanticClaim(subject="s", canonical_term_id="metro:TunnelSegment.StartChainage", value=1.0, unit="mm"))
    assert any(x.rule_id == "metro:Rule.UnitContext" and x.status is ValidationStatus.NOT_APPLICABLE for x in findings)
```

- [ ] **Step 2: Implement local datatype checks without IFC imports**

Use local sets for `IfcIdentifier/IfcLabel/IfcText/IfcDate/IfcDateTime/IfcDuration` -> string; `IfcBoolean` -> bool; `IfcInteger` -> int excluding bool; common IFC measures -> int/float excluding bool. Unknown/option-dependent datatype context is `NOT_APPLICABLE`, not guessed.

Algorithm: explicit prohibited IFC usage first; unrelated IFC/dsp claim -> scope `NOT_APPLICABLE`; unknown Metro term -> `TermExists/FAIL`; then datatype and allowed values; never scan for absent P-M siblings; P-C external condition -> `NOT_APPLICABLE`; measure with explicit unit -> `UnitContext/NOT_APPLICABLE`; deterministic sorted findings with exact provenance.

- [ ] **Step 3: GREEN + commit**

```bash
pytest -q tests/semantic_providers/metro_v32/test_metro_v32_validation.py tests/semantic_providers/metro_v32/test_metro_v32_catalog.py
git add providers/semantics/metro_v32/src/metro_semantic_provider/validation.py tests/semantic_providers/metro_v32/test_metro_v32_validation.py
git commit -m "feat(semantic): add Metro claim validation"
```

---

### Task 5: Human-reviewed golden hash + complete provider surface

**Files:** `golden.py`, `provider.py`, `__init__.py`, `test_metro_v32_provider.py`, modify hashing tests.

- [ ] **Step 1: Write provider/manifest RED tests**

Verify exact manifest: DOMAIN 3.2; namespaces sorted to `("ifc", "metro")`; `metro AUTHORITATIVE`, `ifc EXTENSION`; four capabilities; exact IFC dependency; content hash equals catalog. Verify exact/case-sensitive `metro:*` lookup, queryable mapping-rule schema, and direct Metro provider failure for `ifc:IfcWall`.

- [ ] **Step 2: Inspect the complete catalog before freezing hash**

```bash
PYTHONPATH=providers/semantics/metro_v32/src:platform/semantic_service/src python - <<'PY'
from metro_semantic_provider.catalog import build_catalog
from metro_semantic_provider.source import load_raw_machine_source
c = build_catalog(load_raw_machine_source())
print("content_hash", c.content_hash)
print("terms", len(c.terms), "mappings", len(c.mappings), "rules", len(c.validation_rules), "decisions", len(c.decisions))
for term in (
    "metro:RunningRail",
    "metro:TunnelSegment.ConstructionMethod",
    "metro:BuildingElementDesign.DesignStatus",
    "metro:Mapping.RunningRail.ToIfcRail",
    "metro:Rule.ProhibitIfcTunnelEntity",
    "metro:Decision.DEC-05",
):
    print(term, c.schema_for(term))
PY
```

Before freezing, visually confirm: all 37 Pset containers exist; all 10 decisions are UNFROZEN; prohibited pseudo-entities are rules, not IFC vocabulary; RunningRail is ACTIVE to IfcRail/RAIL; TrackBed/Clearance/Tunnel project mappings are inactive; TunnelSegment.ConstructionMethod has P-M, IfcLabel, and four allowed values.

- [ ] **Step 3: Freeze the exact printed SHA once**

Create `golden.py` with one assignment whose RHS is exactly the 64-character lowercase `content_hash` printed in Step 2. This value is derived from the complete reviewed catalog and therefore is intentionally not guessed in this plan. Do not create a generator that rewrites it.

Add a test asserting `build_catalog(load_raw_machine_source()).content_hash == METRO_V32_GOLDEN_CONTENT_HASH`.

- [ ] **Step 4: Implement provider class**

Construct `METRO_V32_CATALOG`; fail with `MetroCatalogBuildError` if it differs from the golden. Manifest:

```python
SemanticProviderManifest(
    provider_id="dsp.metro.semantic",
    provider_type=ProviderType.DOMAIN,
    version="3.2",
    content_hash=catalog.content_hash,
    namespaces=("metro", "ifc"),
    capabilities=frozenset({
        SemanticCapability.VOCABULARY,
        SemanticCapability.MAPPING,
        SemanticCapability.VALIDATION,
        SemanticCapability.PROJECTION,
    }),
    authority=(
        NamespaceAuthority("metro", AuthorityMode.AUTHORITATIVE),
        NamespaceAuthority("ifc", AuthorityMode.EXTENSION),
    ),
    compatibility=(),
    requires=(ProviderRef("buildingSMART.ifc43", "4.3.2.0"),),
)
```

Methods: `resolve_term`, `describe_term`, `get_term_schema`, `find_mappings`, `validate_claim`; mapping/validation delegate to Tasks 3-4. Export `METRO_V32_CATALOG`, `METRO_V32_PROVIDER`, `METRO_V32_GOLDEN_CONTENT_HASH`, provider/error types.

- [ ] **Step 5: GREEN + commit**

```bash
pytest -q tests/semantic_providers/metro_v32
git add providers/semantics/metro_v32 tests/semantic_providers/metro_v32
git commit -m "feat(semantic): expose Metro V3.2 provider"
```

---

### Task 6: Semantic Environment, IFC authority, and reference conformance

**Files:** `test_metro_v32_service_integration.py`

- [ ] **Step 1: Prove exact dependency and authority**

Tests must show Metro-only pin raises `ProviderDependencyError`; IFC+Metro pin succeeds; `ifc:IfcWall` resolves through `buildingSMART.ifc43`; `metro:RunningRail` resolves through Metro; DSP Core+IFC+Metro may share one environment with authoritative owners `{dsp, ifc, metro}`.

- [ ] **Step 2: Prove every machine IFC reference is real IFC**

Recursively collect every string beginning `ifc:` from ACTIVE mapping targets/constraints, term datatype/datatype_options/applicability schema, and decision options. For each canonical IFC ID, call `SemanticService.resolve_term()` in an IFC+Metro environment. If any fails, fix/downgrade the Metro machine record; never weaken IFC or add fake IFC terms.

- [ ] **Step 3: Prove service mapping/validation provenance**

`SemanticService.find_mappings()` for `metro:RunningRail` returns Metro provenance and `ifc:IfcRail`; `validate_claim(ifc:IfcTunnel)` contains Metro `ProhibitIfcTunnelEntity/FAIL` while IFC remains the vocabulary authority.

- [ ] **Step 4: GREEN + commit**

```bash
pytest -q tests/semantic_providers/metro_v32 tests/semantic_providers/ifc43 tests/semantic_providers/dsp_core tests/semantic_service
git add tests/semantic_providers/metro_v32/test_metro_v32_service_integration.py
git commit -m "test(semantic): prove Metro IFC authority boundaries"
```

---

### Task 7: Existing Semantic MCP compatibility, architecture guards, README

**Files:** `test_metro_v32_mcp_integration.py`, `test_metro_v32_architecture.py`, `README.md`

- [ ] **Step 1: Write a real MCP client test**

Use current contract exactly:

```python
mappings = await client.call_tool(
    "semantic.find_mappings",
    {
        "source_claim": {"subject": "rail-1", "canonical_term_id": "metro:RunningRail"},
        "environment_id": environment.environment_id,
        "target_namespace": "ifc",
    },
)
```

Also resolve `metro:TunnelSegment.ConstructionMethod`, schema-query `metro:Mapping.RunningRail.ToIfcRail`, verify protocol version `2026-07-28`, and assert Metro content-hash provenance. No Metro-specific MCP endpoint.

- [ ] **Step 2: Add architecture guards**

Scan Metro production `.py` files and fail on `ifcopenshell`, `ifc43_semantic_provider`, `semantic_runtime`, `semantic_mcp`, `ElementId`, `OST_Walls`, `AutoCAD`, `A-WALL`, `Tekla`. Scan platform production sources and fail on `metro_semantic_provider`. Do not ban `PsetProj_` because it is legitimate Metro carrier data.

- [ ] **Step 3: Write README**

Document provider identity/authority/dependency, source digest, packaged YAML, four capability boundaries, Chapter 21 PsetProj meaning, UNFROZEN DEC policy, claim-local validation limits, no Host/D5/geometry/runtime Markdown/network behavior.

- [ ] **Step 4: GREEN + commit**

```bash
pytest -q tests/semantic_providers/metro_v32 tests/semantic_providers/ifc43 tests/semantic_providers/dsp_core tests/semantic_service tests/semantic_mcp
git add providers/semantics/metro_v32/README.md tests/semantic_providers/metro_v32
git commit -m "test(semantic): verify Metro provider integration"
```

---

### Task 8: Focused CI, full regression, diff boundary, and review gate

**Files:** `.github/workflows/metro-semantic-provider.yml`

- [ ] **Step 1: Add workflow**

Trigger on Metro provider/tests plus IFC/DSP Core/Semantic Service/MCP/Runtime/spec/design/plan changes. Install:

```bash
python -m pip install pytest pytest-asyncio jsonschema
python -m pip install -e contracts/python -e hosts/autocad/sidecar -e platform/semantic_runtime -e platform/semantic_service -e platform/semantic_mcp -e providers/semantics/dsp_core -e providers/semantics/ifc43 -e providers/semantics/metro_v32
```

Run three gates:

```bash
pytest -q tests/semantic_providers/metro_v32
pytest -q tests/semantic_providers/dsp_core tests/semantic_providers/ifc43 tests/semantic_providers/metro_v32 tests/semantic_service tests/semantic_mcp
pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime tests/semantic_service tests/semantic_mcp tests/semantic_providers/dsp_core tests/semantic_providers/ifc43 tests/semantic_providers/metro_v32
```

- [ ] **Step 2: Verify final diff boundary**

```bash
git diff --name-only main...HEAD
```

Allowed implementation scope is only Metro package/tests/workflow plus approved design/plan. There must be no platform/Host/D5-D7 production changes.

- [ ] **Step 3: Commit CI**

```bash
git add .github/workflows/metro-semantic-provider.yml
git commit -m "ci(semantic): verify Metro semantic provider"
```

- [ ] **Step 4: Completion gates before PR #10**

Use `superpowers:verification-before-completion`, then `superpowers:requesting-code-review`. Verify exact head SHA; all focused/full tests; golden hash; all active IFC refs; all DEC-01..10 UNFROZEN; no active TrackBed/Clearance/Tunnel project mapping; architecture guards. External-review limits count as review unavailable, never review passed. Only then open PR #10 against `main`.

## Planned Commit Sequence

```text
1 source gate + package metadata
2 reviewed YAML + immutable catalog/hash
3 ACTIVE metro->ifc mapping
4 claim-local validation
5 golden hash + provider manifest/vocabulary
6 IFC dependency/authority/service conformance
7 MCP + architecture + README
8 CI + full regression + review gate
```

## Phase Boundary After PR #10

After PR #10 merges, Phase D reference providers are complete. The next main-Spec item is Phase E step 18: `NormalizedDesignFact contract`. Do not pull AutoCAD extraction, enterprise `A-WALL` mapping, Host classification, D5 reconstruction, or Phase E projection into this PR.
