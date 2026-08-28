# DSP Core Semantic Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `dsp.core@1.0` as the first concrete reference Semantic Provider, exposing the eight Spec v0.6 DSP Core terms through the existing Semantic Service and Semantic MCP contracts without changing either production contract.

**Architecture:** Add an isolated Python package under `providers/semantics/dsp_core` that depends only on `semantic_service`. The package owns an immutable term catalog, deterministic machine-semantic hashing, and a VOCABULARY-only provider. Integration tests compose the provider with existing D5 public enums, Semantic Service pinning/routing, and the real Semantic MCP client strictly at test boundaries.

**Tech Stack:** Python 3.11, dataclasses, `MappingProxyType`, SHA-256 + canonical JSON, existing `semantic-service` package, existing `semantic-mcp` package, pytest/pytest-asyncio, MCP Python SDK already pinned by `semantic-mcp`.

**Spec:** `docs/superpowers/specs/2026-08-28-dsp-core-semantic-provider-design.md`

## Global Constraints

- Provider identity is exactly `dsp.core@1.0`.
- Provider type is exactly `CORE`.
- Namespace set is exactly `("dsp",)` and `dsp` authority is exactly `AUTHORITATIVE`.
- Capability set is exactly `{VOCABULARY}`; do not claim `MAPPING`, `VALIDATION`, or `PROJECTION`.
- Initial vocabulary contains exactly eight terms: `dsp:SemanticIdentity`, `dsp:HostBinding`, `dsp:ExternalIdentity`, `dsp:WallThickness`, `dsp:Freshness`, `dsp:Assurance`, `dsp:Snapshot`, `dsp:ChangeSet`.
- Production provider code may import `semantic_service` contracts but MUST NOT import `semantic_runtime` or `semantic_mcp`.
- Production provider code MUST NOT reference AutoCAD, Revit, Tekla, IFC provider implementations, Metro provider implementations, enterprise mappings, D4/D6/D7, Gateway, or provider-native execution details.
- `label` and `description` are presentation-only and MUST NOT affect provider `content_hash`.
- `term_id`, term `version`, `kind`, `domain`, `range`, `unit`, `allowed_values`, and `constraints` are machine semantics and MUST affect `content_hash` when changed.
- All provider results MUST carry provenance exactly matching the pinned manifest: `provider_id`, `version`, `content_hash`.
- Unknown/case-mismatched term lookup is deterministic and exact; no fuzzy aliasing or namespace correction.
- D5 compatibility is checked only in tests; no production dependency from provider to D5.
- Existing Semantic Service and Semantic MCP production code are not modified in this PR.
- Main-Spec §40.5 `MAPPING` and `VALIDATION` determinism are explicitly N/A for this provider version because those capabilities are unclaimed; tests must prove the absence rather than add fake behavior.

---

## File Structure

Create:

```text
providers/semantics/dsp_core/
  pyproject.toml
  README.md
  src/dsp_core_semantic_provider/
    __init__.py          # curated public API only
    hashing.py           # canonical JSON normalization + SHA-256
    catalog.py           # immutable term definition/catalog + exact 8-term baseline
    provider.py          # DspCoreSemanticProvider and manifest/provenance behavior

tests/semantic_providers/dsp_core/
  test_catalog.py
  test_manifest.py
  test_provider.py
  test_service_integration.py
  test_mcp_integration.py
  test_architecture.py
.github/workflows/dsp-core-semantic-provider.yml
```

Modify no existing production Python module. The only existing files allowed to change after this plan are the design/plan records if closeout evidence must be appended.

---

### Task 1: Immutable DSP Core Catalog and Deterministic Hashing

**Files:**
- Create: `providers/semantics/dsp_core/pyproject.toml`
- Create: `providers/semantics/dsp_core/src/dsp_core_semantic_provider/hashing.py`
- Create: `providers/semantics/dsp_core/src/dsp_core_semantic_provider/catalog.py`
- Create: `tests/semantic_providers/dsp_core/test_catalog.py`

**Interfaces:**
- Consumes: Python standard library only in `hashing.py`/`catalog.py`.
- Produces: `SemanticTermDefinition`, `SemanticTermCatalog`, `DSP_CORE_TERMS`, `DSP_CORE_CATALOG`, `canonical_hash(payload) -> str`.

- [ ] **Step 1: Create package metadata and write the failing catalog/hash tests**

Create `providers/semantics/dsp_core/pyproject.toml`:

```toml
[project]
name = "dsp-core-semantic-provider"
version = "1.0.0"
description = "DSP Core reference Semantic Provider for cross-industry canonical vocabulary."
requires-python = ">=3.11"
dependencies = [
    "semantic-service>=0.1.0",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Create `tests/semantic_providers/dsp_core/test_catalog.py` with tests equivalent to:

```python
from dataclasses import replace

import pytest

from dsp_core_semantic_provider.catalog import (
    DSP_CORE_CATALOG,
    DSP_CORE_TERMS,
    SemanticTermCatalog,
)

EXPECTED_IDS = (
    "dsp:Assurance",
    "dsp:ChangeSet",
    "dsp:ExternalIdentity",
    "dsp:Freshness",
    "dsp:HostBinding",
    "dsp:SemanticIdentity",
    "dsp:Snapshot",
    "dsp:WallThickness",
)


def test_catalog_contains_exact_spec_v06_baseline():
    assert tuple(term.term_id for term in DSP_CORE_CATALOG.definitions) == EXPECTED_IDS
    assert len(DSP_CORE_TERMS) == 8


def test_duplicate_term_ids_are_rejected():
    term = DSP_CORE_TERMS[0]
    with pytest.raises(ValueError, match="duplicate term_id"):
        SemanticTermCatalog((term, term))


def test_insertion_order_does_not_change_content_hash():
    forward = SemanticTermCatalog(DSP_CORE_TERMS)
    reverse = SemanticTermCatalog(tuple(reversed(DSP_CORE_TERMS)))
    assert forward.content_hash == reverse.content_hash


def test_presentation_only_changes_do_not_change_content_hash():
    baseline = DSP_CORE_TERMS[0]
    changed = replace(
        baseline,
        label=baseline.label + " presentation",
        description=baseline.description + " presentation",
    )
    original = SemanticTermCatalog((baseline,))
    presentation_only = SemanticTermCatalog((changed,))
    assert original.content_hash == presentation_only.content_hash


def test_machine_semantic_change_changes_content_hash():
    baseline = next(term for term in DSP_CORE_TERMS if term.term_id == "dsp:WallThickness")
    changed = replace(baseline, unit="m")
    assert SemanticTermCatalog((baseline,)).content_hash != SemanticTermCatalog((changed,)).content_hash


def test_catalog_and_constraints_are_immutable():
    term = next(term for term in DSP_CORE_TERMS if term.term_id == "dsp:HostBinding")
    with pytest.raises(TypeError):
        term.constraints["required"] = ("native_id",)
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
python -m pip install -e platform/semantic_service -e providers/semantics/dsp_core
pytest -q tests/semantic_providers/dsp_core/test_catalog.py
```

Expected: collection/import failure because `dsp_core_semantic_provider.catalog` does not exist yet.

- [ ] **Step 3: Implement canonical JSON normalization and hashing**

Create `hashing.py` with this contract:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from hashlib import sha256
import json


def _normalize(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Set) and not isinstance(value, (str, bytes, bytearray)):
        normalized = [_normalize(item) for item in value]
        return sorted(normalized, key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")))
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    return value


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        _normalize(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
```

Do not include labels/descriptions here by accident; callers choose the payload.

- [ ] **Step 4: Implement immutable definitions/catalog and the exact eight terms**

Create `catalog.py` around the following exact public shapes:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from .hashing import canonical_hash


def _freeze(value: object) -> object:
    if isinstance(value, Mapping):
        return MappingProxyType({str(k): _freeze(v) for k, v in value.items()})
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, tuple):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, set):
        return frozenset(_freeze(v) for v in value)
    return value


def _plain(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(v) for v in value]
    if isinstance(value, (set, frozenset)):
        return sorted((_plain(v) for v in value), key=repr)
    return value


@dataclass(frozen=True, slots=True)
class SemanticTermDefinition:
    term_id: str
    version: str
    kind: str
    domain: str
    range: str
    unit: str | None
    allowed_values: tuple[str, ...]
    constraints: Mapping[str, object]
    label: str
    description: str

    def __post_init__(self) -> None:
        for name in ("term_id", "version", "kind", "domain", "range", "label", "description"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} is required")
        if not self.term_id.startswith("dsp:"):
            raise ValueError("DSP Core term_id must use dsp: namespace")
        object.__setattr__(self, "allowed_values", tuple(self.allowed_values))
        object.__setattr__(self, "constraints", _freeze(self.constraints))

    def machine_payload(self) -> dict[str, object]:
        return {
            "term_id": self.term_id,
            "version": self.version,
            "kind": self.kind,
            "domain": self.domain,
            "range": self.range,
            "unit": self.unit,
            "allowed_values": list(self.allowed_values),
            "constraints": _plain(self.constraints),
        }


class SemanticTermCatalog:
    def __init__(self, definitions: tuple[SemanticTermDefinition, ...]):
        ordered = tuple(sorted(definitions, key=lambda item: item.term_id))
        ids = tuple(item.term_id for item in ordered)
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate term_id")
        self._definitions = ordered
        self._by_id = MappingProxyType({item.term_id: item for item in ordered})
        self._content_hash = canonical_hash(
            {"terms": [item.machine_payload() for item in ordered]}
        )

    @property
    def definitions(self) -> tuple[SemanticTermDefinition, ...]:
        return self._definitions

    @property
    def content_hash(self) -> str:
        return self._content_hash

    def get(self, term_id: str) -> SemanticTermDefinition:
        return self._by_id[term_id]
```

Define the exact eight `SemanticTermDefinition` values with `version="1.0"` and these machine fields:

```python
DSP_CORE_TERMS = (
    SemanticTermDefinition(
        "dsp:SemanticIdentity", "1.0", "TYPE", "DSP_COLLABORATION",
        "SEMANTIC_IDENTITY", None, (),
        {"host_bindings": "0..N", "external_identities": "0..N"},
        "Semantic Identity",
        "Stable DSP semantic identity shared across Host bindings.",
    ),
    SemanticTermDefinition(
        "dsp:HostBinding", "1.0", "TYPE", "SEMANTIC_IDENTITY",
        "HOST_NATIVE_IDENTITY_BINDING", None, (),
        {"required": ("host_type", "document_id", "native_id")},
        "Host Binding",
        "Binding from a DSP semantic identity to one Host-native entity identity.",
    ),
    SemanticTermDefinition(
        "dsp:ExternalIdentity", "1.0", "TYPE", "SEMANTIC_IDENTITY",
        "EXTERNAL_IDENTITY_BINDING", None, (),
        {"required": ("scheme", "value")},
        "External Identity",
        "Scheme/value identity supplied by an external semantic or data system.",
    ),
    SemanticTermDefinition(
        "dsp:WallThickness", "1.0", "PROPERTY", "WALL_LIKE_DESIGN_ELEMENT",
        "NUMBER", "mm", (), {"minimum_exclusive": 0},
        "Wall Thickness",
        "Canonical wall-like element thickness expressed in millimetres.",
    ),
    SemanticTermDefinition(
        "dsp:Freshness", "1.0", "STATE", "SEMANTIC_ASPECT", "ENUM", None,
        ("FRESH", "STALE", "DIRTY", "UNKNOWN", "RECONSTRUCTING"), {},
        "Freshness",
        "State describing whether a semantic aspect is current relative to Host revision evidence.",
    ),
    SemanticTermDefinition(
        "dsp:Assurance", "1.0", "STATE", "SEMANTIC_CLAIM", "ORDERED_ENUM", None,
        ("UNKNOWN", "HEURISTIC", "RULE_DERIVED", "STANDARD_MAPPED", "NATIVE_ASSERTED"), {},
        "Assurance",
        "Ordered confidence class describing how strongly a semantic claim is supported.",
    ),
    SemanticTermDefinition(
        "dsp:Snapshot", "1.0", "TYPE", "COLLABORATION_STATE",
        "IMMUTABLE_SEMANTIC_SNAPSHOT", None, (),
        {
            "snapshot_kind": ("CONTEXT", "PLANNING"),
            "planning_requires": ("semantic_projection_ref", "semantic_environment_ref"),
        },
        "Semantic Snapshot",
        "Immutable DSP semantic snapshot bound to reconstruction and semantic-environment evidence.",
    ),
    SemanticTermDefinition(
        "dsp:ChangeSet", "1.0", "TYPE", "MODEL_OPERATION",
        "IMMUTABLE_CANONICAL_LOGICAL_TRANSACTION", None, (),
        {
            "approval_binds": (
                "changeset_hash", "approved_scope_hash", "semantic_environment_ref"
            ),
            "provider_native_payload_forbidden": True,
        },
        "ChangeSet",
        "Immutable canonical logical transaction used as the unit of planning and approval.",
    ),
)

DSP_CORE_CATALOG = SemanticTermCatalog(DSP_CORE_TERMS)
```

- [ ] **Step 5: Run catalog tests and confirm GREEN**

Run:

```bash
pytest -q tests/semantic_providers/dsp_core/test_catalog.py
```

Expected: all Task 1 tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add providers/semantics/dsp_core/pyproject.toml \
        providers/semantics/dsp_core/src/dsp_core_semantic_provider/hashing.py \
        providers/semantics/dsp_core/src/dsp_core_semantic_provider/catalog.py \
        tests/semantic_providers/dsp_core/test_catalog.py
git commit -m "feat(semantic): add DSP Core term catalog"
```

---

### Task 2: VOCABULARY Provider, Manifest, Provenance, and Curated API

**Files:**
- Create: `providers/semantics/dsp_core/src/dsp_core_semantic_provider/provider.py`
- Create: `providers/semantics/dsp_core/src/dsp_core_semantic_provider/__init__.py`
- Create: `tests/semantic_providers/dsp_core/test_manifest.py`
- Create: `tests/semantic_providers/dsp_core/test_provider.py`

**Interfaces:**
- Consumes: `DSP_CORE_CATALOG`, existing `semantic_service.manifest` and `semantic_service.providers` DTOs/protocols.
- Produces: `DspCoreSemanticProvider`, public `DSP_CORE_PROVIDER`, plus curated exports for catalog values.

- [ ] **Step 1: Write failing manifest/capability tests**

Create `test_manifest.py`:

```python
from semantic_service import (
    AuthorityMode,
    ProviderType,
    SemanticCapability,
    SemanticMappingProvider,
    SemanticValidationProvider,
    SemanticVocabularyProvider,
)

from dsp_core_semantic_provider import DSP_CORE_CATALOG, DSP_CORE_PROVIDER


def test_manifest_is_exact_dsp_core_v1_vocabulary_authority():
    manifest = DSP_CORE_PROVIDER.manifest
    assert manifest.provider_id == "dsp.core"
    assert manifest.provider_type is ProviderType.CORE
    assert manifest.version == "1.0"
    assert manifest.content_hash == DSP_CORE_CATALOG.content_hash
    assert manifest.namespaces == ("dsp",)
    assert manifest.capabilities == frozenset({SemanticCapability.VOCABULARY})
    assert tuple((item.namespace, item.mode) for item in manifest.authority) == (
        ("dsp", AuthorityMode.AUTHORITATIVE),
    )
    assert manifest.compatibility == ()
    assert manifest.requires == ()


def test_unclaimed_mapping_and_validation_capabilities_are_absent_not_stubbed():
    assert isinstance(DSP_CORE_PROVIDER, SemanticVocabularyProvider)
    assert not isinstance(DSP_CORE_PROVIDER, SemanticMappingProvider)
    assert not isinstance(DSP_CORE_PROVIDER, SemanticValidationProvider)
```

- [ ] **Step 2: Write failing vocabulary/provenance tests**

Create `test_provider.py`:

```python
import pytest

from semantic_service import ProviderProvenance
from dsp_core_semantic_provider import DSP_CORE_CATALOG, DSP_CORE_PROVIDER


def test_every_baseline_term_resolves_with_exact_manifest_provenance():
    expected = ProviderProvenance("dsp.core", "1.0", DSP_CORE_CATALOG.content_hash)
    for definition in DSP_CORE_CATALOG.definitions:
        resolved = DSP_CORE_PROVIDER.resolve_term(definition.term_id)
        assert resolved.term_id == definition.term_id
        assert resolved.kind == definition.kind
        assert resolved.provenance == expected


def test_wall_thickness_schema_contains_machine_semantics_only():
    schema = DSP_CORE_PROVIDER.get_term_schema("dsp:WallThickness")
    assert dict(schema.schema) == {
        "term_id": "dsp:WallThickness",
        "version": "1.0",
        "kind": "PROPERTY",
        "domain": "WALL_LIKE_DESIGN_ELEMENT",
        "range": "NUMBER",
        "unit": "mm",
        "allowed_values": (),
        "constraints": {"minimum_exclusive": 0},
    }
    assert "label" not in schema.schema
    assert "description" not in schema.schema


def test_description_is_presentation_only_and_locale_falls_back_to_canonical():
    result = DSP_CORE_PROVIDER.describe_term("dsp:WallThickness", "zh-CN")
    assert result.term_id == "dsp:WallThickness"
    assert result.text
    assert result.locale is None


def test_lookup_is_exact_and_case_sensitive():
    with pytest.raises(KeyError):
        DSP_CORE_PROVIDER.resolve_term("dsp:wallthickness")
    with pytest.raises(KeyError):
        DSP_CORE_PROVIDER.resolve_term("WallThickness")
```

- [ ] **Step 3: Run Task 2 tests and confirm RED**

Run:

```bash
pytest -q tests/semantic_providers/dsp_core/test_manifest.py tests/semantic_providers/dsp_core/test_provider.py
```

Expected: import failure because `provider.py` and curated package exports do not exist.

- [ ] **Step 4: Implement `DspCoreSemanticProvider`**

Create `provider.py` with this structure:

```python
from __future__ import annotations

from semantic_service import (
    AuthorityMode,
    NamespaceAuthority,
    ProviderProvenance,
    ProviderType,
    ResolvedTerm,
    SemanticCapability,
    SemanticProviderManifest,
    TermDescription,
    TermSchema,
)

from .catalog import DSP_CORE_CATALOG, SemanticTermCatalog


class DspCoreSemanticProvider:
    def __init__(self, catalog: SemanticTermCatalog = DSP_CORE_CATALOG) -> None:
        self._catalog = catalog
        self._manifest = SemanticProviderManifest(
            provider_id="dsp.core",
            provider_type=ProviderType.CORE,
            version="1.0",
            content_hash=catalog.content_hash,
            namespaces=("dsp",),
            capabilities=frozenset({SemanticCapability.VOCABULARY}),
            authority=(NamespaceAuthority("dsp", AuthorityMode.AUTHORITATIVE),),
            compatibility=(),
            requires=(),
        )
        self._provenance = ProviderProvenance(
            self._manifest.provider_id,
            self._manifest.version,
            self._manifest.content_hash,
        )

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def resolve_term(self, term_id: str) -> ResolvedTerm:
        definition = self._catalog.get(term_id)
        return ResolvedTerm(definition.term_id, definition.kind, self._provenance)

    def describe_term(self, term_id: str, locale: str | None = None) -> TermDescription:
        definition = self._catalog.get(term_id)
        return TermDescription(
            definition.term_id,
            definition.description,
            None,
            self._provenance,
        )

    def get_term_schema(self, term_id: str) -> TermSchema:
        definition = self._catalog.get(term_id)
        return TermSchema(
            definition.term_id,
            definition.machine_payload(),
            self._provenance,
        )


DSP_CORE_PROVIDER = DspCoreSemanticProvider()
```

Do not add `find_mappings`, `validate_claim`, or projection methods.

- [ ] **Step 5: Create the curated package API**

Create `__init__.py`:

```python
from .catalog import (
    DSP_CORE_CATALOG,
    DSP_CORE_TERMS,
    SemanticTermCatalog,
    SemanticTermDefinition,
)
from .provider import DSP_CORE_PROVIDER, DspCoreSemanticProvider

__all__ = [
    "DSP_CORE_CATALOG",
    "DSP_CORE_PROVIDER",
    "DSP_CORE_TERMS",
    "DspCoreSemanticProvider",
    "SemanticTermCatalog",
    "SemanticTermDefinition",
]
```

- [ ] **Step 6: Run Task 1 + Task 2 tests and confirm GREEN**

Run:

```bash
pytest -q tests/semantic_providers/dsp_core/test_catalog.py \
          tests/semantic_providers/dsp_core/test_manifest.py \
          tests/semantic_providers/dsp_core/test_provider.py
```

Expected: all tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add providers/semantics/dsp_core/src/dsp_core_semantic_provider \
        tests/semantic_providers/dsp_core/test_manifest.py \
        tests/semantic_providers/dsp_core/test_provider.py
git commit -m "feat(semantic): add DSP Core vocabulary provider"
```

---

### Task 3: Semantic Service Pinning, Authority Conflict, Hash Drift, and D5 Compatibility

**Files:**
- Create: `tests/semantic_providers/dsp_core/test_service_integration.py`
- No production files modified.

**Interfaces:**
- Consumes: `DSP_CORE_PROVIDER`, existing `SemanticProviderRegistry`, `SemanticEnvironmentStore.pin(selections, registry)`, `SemanticService`, D5 public enums.
- Produces: integration proof only; no new production API.

- [ ] **Step 1: Write failing Service integration tests**

Create `test_service_integration.py` with helpers and assertions equivalent to:

```python
from dataclasses import replace

import pytest

from semantic_service import (
    AuthorityMode,
    NamespaceAuthority,
    NamespaceAuthorityError,
    ProviderRef,
    ProviderType,
    ResolvedTerm,
    SemanticCapability,
    SemanticEnvironmentStore,
    SemanticProviderManifest,
    SemanticProviderRegistry,
    SemanticService,
    TermDescription,
    TermSchema,
)
from semantic_runtime import AssuranceLevel, FreshnessState

from dsp_core_semantic_provider import (
    DSP_CORE_CATALOG,
    DSP_CORE_PROVIDER,
    DSP_CORE_TERMS,
    DspCoreSemanticProvider,
    SemanticTermCatalog,
)


def build_service(provider=DSP_CORE_PROVIDER):
    registry = SemanticProviderRegistry()
    registry.register(provider)
    environments = SemanticEnvironmentStore()
    environment = environments.pin(
        (ProviderRef(provider.manifest.provider_id, provider.manifest.version),),
        registry,
    )
    return SemanticService(registry, environments), registry, environments, environment


def test_service_resolves_dsp_terms_through_pinned_authority():
    service, _, _, environment = build_service()
    result = service.resolve_term("dsp:WallThickness", environment.environment_id)
    assert result.term_id == "dsp:WallThickness"
    assert result.provenance.content_hash == DSP_CORE_CATALOG.content_hash


def test_d5_freshness_and_assurance_vocabularies_remain_compatible_at_test_boundary():
    freshness = DSP_CORE_PROVIDER.get_term_schema("dsp:Freshness").schema
    assurance = DSP_CORE_PROVIDER.get_term_schema("dsp:Assurance").schema
    assert tuple(freshness["allowed_values"]) == tuple(item.value for item in FreshnessState)
    assert tuple(assurance["allowed_values"]) == tuple(item.name for item in AssuranceLevel)


def test_machine_semantic_change_changes_environment_identity():
    baseline_term = next(term for term in DSP_CORE_TERMS if term.term_id == "dsp:WallThickness")
    changed_terms = tuple(
        replace(term, unit="m") if term.term_id == baseline_term.term_id else term
        for term in DSP_CORE_TERMS
    )
    changed_provider = DspCoreSemanticProvider(SemanticTermCatalog(changed_terms))
    _, _, _, baseline_environment = build_service(DSP_CORE_PROVIDER)
    _, _, _, changed_environment = build_service(changed_provider)
    assert baseline_environment.environment_id != changed_environment.environment_id


class OtherDspAuthority:
    def __init__(self):
        self._manifest = SemanticProviderManifest(
            provider_id="other.dsp",
            provider_type=ProviderType.ENTERPRISE,
            version="1.0",
            content_hash="other-content",
            namespaces=("dsp",),
            capabilities=frozenset({SemanticCapability.VOCABULARY}),
            authority=(NamespaceAuthority("dsp", AuthorityMode.AUTHORITATIVE),),
            compatibility=(),
            requires=(),
        )

    @property
    def manifest(self):
        return self._manifest

    def resolve_term(self, term_id):
        return ResolvedTerm(term_id, "TYPE", self._provenance())

    def describe_term(self, term_id, locale=None):
        return TermDescription(term_id, "other", None, self._provenance())

    def get_term_schema(self, term_id):
        return TermSchema(term_id, {"term_id": term_id}, self._provenance())

    def _provenance(self):
        from semantic_service import ProviderProvenance
        return ProviderProvenance("other.dsp", "1.0", "other-content")


def test_environment_pin_fails_closed_for_second_authoritative_dsp_owner():
    registry = SemanticProviderRegistry()
    registry.register(DSP_CORE_PROVIDER)
    other = OtherDspAuthority()
    registry.register(other)
    with pytest.raises(NamespaceAuthorityError, match="multiple AUTHORITATIVE providers"):
        SemanticEnvironmentStore().pin(
            (ProviderRef("dsp.core", "1.0"), ProviderRef("other.dsp", "1.0")),
            registry,
        )
```

For `AssuranceLevel`, compare enum names rather than numeric values because the provider vocabulary contains semantic tokens, not D5 integer ordinals.

- [ ] **Step 2: Run the integration tests and confirm expected failures, then fix only provider-package defects**

Run:

```bash
python -m pip install -e platform/semantic_runtime -e platform/semantic_service -e providers/semantics/dsp_core
pytest -q tests/semantic_providers/dsp_core/test_service_integration.py
```

Expected first run: any failures should identify mismatches in the provider implementation/catalog. Do not modify Semantic Service or D5 to satisfy the provider. Fix only `providers/semantics/dsp_core/**` if a defect is exposed.

- [ ] **Step 3: Re-run focused provider + Service/D5 tests to GREEN**

Run:

```bash
pytest -q tests/semantic_providers/dsp_core
pytest -q tests/semantic_service tests/semantic_runtime
```

Expected: all focused provider tests and existing Semantic Service/D5 tests pass.

- [ ] **Step 4: Commit Task 3**

```bash
git add tests/semantic_providers/dsp_core/test_service_integration.py providers/semantics/dsp_core
git commit -m "test(semantic): prove DSP Core environment conformance"
```

---

### Task 4: Real Semantic MCP Transport Proof and Architecture Guard

**Files:**
- Create: `tests/semantic_providers/dsp_core/test_mcp_integration.py`
- Create: `tests/semantic_providers/dsp_core/test_architecture.py`
- No production Semantic MCP file modified.

**Interfaces:**
- Consumes: existing `semantic_mcp.server.build_mcp_server(service)`, `mcp.Client`, real `SemanticService` built with `DSP_CORE_PROVIDER`.
- Produces: real-client proof and static dependency/domain guard only.

- [ ] **Step 1: Write the real MCP client integration test**

Create `test_mcp_integration.py`:

```python
import pytest
from mcp import Client

from semantic_mcp.server import build_mcp_server
from semantic_service import ProviderRef, SemanticEnvironmentStore, SemanticProviderRegistry, SemanticService

from dsp_core_semantic_provider import DSP_CORE_CATALOG, DSP_CORE_PROVIDER


def build_real_service():
    registry = SemanticProviderRegistry()
    registry.register(DSP_CORE_PROVIDER)
    environments = SemanticEnvironmentStore()
    environment = environments.pin((ProviderRef("dsp.core", "1.0"),), registry)
    return SemanticService(registry, environments), environment


@pytest.mark.asyncio
async def test_real_mcp_client_resolves_dsp_core_term_and_schema():
    service, environment = build_real_service()
    async with Client(build_mcp_server(service)) as client:
        assert client.protocol_version == "2026-07-28"
        resolved = await client.call_tool(
            "semantic.resolve_term",
            {"term_id": "dsp:WallThickness", "environment_id": environment.environment_id},
        )
        schema = await client.call_tool(
            "semantic.get_term_schema",
            {"term_id": "dsp:WallThickness", "environment_id": environment.environment_id},
        )

    assert resolved.is_error is False
    assert resolved.structured_content == {
        "term_id": "dsp:WallThickness",
        "kind": "PROPERTY",
        "provenance": {
            "provider_id": "dsp.core",
            "version": "1.0",
            "content_hash": DSP_CORE_CATALOG.content_hash,
        },
    }
    assert schema.is_error is False
    assert schema.structured_content["term_id"] == "dsp:WallThickness"
    assert schema.structured_content["schema"]["unit"] == "mm"
    assert "description" not in schema.structured_content["schema"]
```

This test must use the real MCP client, not `FakeSemanticService`.

- [ ] **Step 2: Write the architecture guard**

Create `test_architecture.py`:

```python
import ast
from pathlib import Path

PROVIDER_ROOT = Path("providers/semantics/dsp_core/src/dsp_core_semantic_provider")

FORBIDDEN_IMPORT_ROOTS = {
    "semantic_runtime",
    "semantic_mcp",
    "autocad_sidecar",
    "Autodesk",
    "Revit",
    "Tekla",
}

FORBIDDEN_DOMAIN_TOKENS = (
    "A-WALL",
    "MetroProvider",
    "Ifc43Provider",
    "Revit ElementId",
    "AutoCAD Handle",
)


def test_production_provider_has_no_forbidden_import_dependency():
    for path in PROVIDER_ROOT.glob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = {alias.name.split(".", 1)[0] for alias in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = {node.module.split(".", 1)[0]}
            else:
                continue
            assert roots.isdisjoint(FORBIDDEN_IMPORT_ROOTS), (path, roots)


def test_production_provider_has_no_host_ifc_metro_execution_leakage():
    text = "\n".join(path.read_text() for path in PROVIDER_ROOT.glob("*.py"))
    for token in FORBIDDEN_DOMAIN_TOKENS:
        assert token not in text, token
```

Do not forbid generic words like `provider`, `host`, or `semantic`; the guard is for actual ownership leakage, not prose style.

- [ ] **Step 3: Run real MCP + architecture tests and confirm GREEN without changing MCP production code**

Run:

```bash
python -m pip install -e platform/semantic_service -e platform/semantic_mcp -e providers/semantics/dsp_core
pytest -q tests/semantic_providers/dsp_core/test_mcp_integration.py \
          tests/semantic_providers/dsp_core/test_architecture.py
pytest -q tests/semantic_mcp
```

Expected: provider integration passes and the existing Semantic MCP suite remains green. Any failure in the generic MCP adapter should be investigated as a provider contract mismatch first; do not widen the seven-tool surface.

- [ ] **Step 4: Commit Task 4**

```bash
git add tests/semantic_providers/dsp_core/test_mcp_integration.py \
        tests/semantic_providers/dsp_core/test_architecture.py
git commit -m "test(semantic): prove DSP Core MCP transport boundary"
```

---

### Task 5: README, Dedicated CI, Full Regression, and Closeout Evidence

**Files:**
- Create: `providers/semantics/dsp_core/README.md`
- Create: `.github/workflows/dsp-core-semantic-provider.yml`
- Modify only if required for closeout evidence: `docs/superpowers/plans/2026-08-28-dsp-core-semantic-provider.md`

**Interfaces:**
- Consumes: completed provider package and tests.
- Produces: maintainable usage documentation, path-filtered verification workflow, final evidence.

- [ ] **Step 1: Write the provider README**

Create `README.md` with these exact boundaries:

```markdown
# DSP Core Semantic Provider

`dsp.core@1.0` is the authoritative `dsp:*` VOCABULARY provider for the DSP v0.6 baseline.

It defines exactly these initial terms:

- `dsp:SemanticIdentity`
- `dsp:HostBinding`
- `dsp:ExternalIdentity`
- `dsp:WallThickness`
- `dsp:Freshness`
- `dsp:Assurance`
- `dsp:Snapshot`
- `dsp:ChangeSet`

Production code depends only on `semantic_service` provider contracts. It does not depend on D5, Semantic MCP, Host products, IFC/Metro providers, D4/D6/D7, or Gateway behavior.

Machine-semantic content is content-addressed. Presentation-only label/description edits do not change the provider content hash; machine-semantic edits do.
```

- [ ] **Step 2: Add dedicated path-filtered CI**

Create `.github/workflows/dsp-core-semantic-provider.yml`:

```yaml
name: DSP Core semantic provider verification

on:
  push:
    branches:
      - main
      - 'feat/dsp-core-semantic-provider'
    paths:
      - 'providers/semantics/dsp_core/**'
      - 'tests/semantic_providers/dsp_core/**'
      - 'platform/semantic_service/**'
      - 'platform/semantic_mcp/**'
      - 'platform/semantic_runtime/**'
      - 'docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md'
      - 'docs/superpowers/specs/2026-08-28-dsp-core-semantic-provider-design.md'
      - 'docs/superpowers/plans/2026-08-28-dsp-core-semantic-provider.md'
      - '.github/workflows/dsp-core-semantic-provider.yml'
  pull_request:
    paths:
      - 'providers/semantics/dsp_core/**'
      - 'tests/semantic_providers/dsp_core/**'
      - 'platform/semantic_service/**'
      - 'platform/semantic_mcp/**'
      - 'platform/semantic_runtime/**'
      - 'docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md'
      - 'docs/superpowers/specs/2026-08-28-dsp-core-semantic-provider-design.md'
      - 'docs/superpowers/plans/2026-08-28-dsp-core-semantic-provider.md'
      - '.github/workflows/dsp-core-semantic-provider.yml'
  workflow_dispatch:

jobs:
  dsp-core-provider:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: .
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install packages
        run: |
          python -m pip install pytest pytest-asyncio jsonschema
          python -m pip install -e contracts/python -e hosts/autocad/sidecar -e platform/semantic_runtime -e platform/semantic_service -e platform/semantic_mcp -e providers/semantics/dsp_core
      - name: Run DSP Core provider tests
        run: pytest -q tests/semantic_providers/dsp_core
      - name: Run full Python regression tests
        run: pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime tests/semantic_service tests/semantic_mcp tests/semantic_providers/dsp_core
```

Do not modify the existing Semantic Service or Semantic MCP workflows unless a later review finds a repository-wide CI trigger bug unrelated to this feature.

- [ ] **Step 3: Run final local verification**

Run:

```bash
python -m pip install pytest pytest-asyncio jsonschema
python -m pip install -e contracts/python \
                     -e hosts/autocad/sidecar \
                     -e platform/semantic_runtime \
                     -e platform/semantic_service \
                     -e platform/semantic_mcp \
                     -e providers/semantics/dsp_core
pytest -q tests/semantic_providers/dsp_core
pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime tests/semantic_service tests/semantic_mcp tests/semantic_providers/dsp_core
```

Expected: focused provider suite green; full Python regression green with only the existing live-AutoCAD skips unless an actual new failure is discovered.

- [ ] **Step 4: Verify repository scope and architecture diff**

Run:

```bash
git diff --name-only main...HEAD
```

Expected changed paths are limited to:

```text
providers/semantics/dsp_core/**
tests/semantic_providers/dsp_core/**
.github/workflows/dsp-core-semantic-provider.yml
docs/superpowers/specs/2026-08-28-dsp-core-semantic-provider-design.md
docs/superpowers/plans/2026-08-28-dsp-core-semantic-provider.md
```

If any `platform/semantic_service/**`, `platform/semantic_mcp/**`, `platform/semantic_runtime/**`, Host, D4/D6/D7, Gateway, IFC, Metro, or enterprise production file appears, stop and justify/remove the scope expansion before closeout.

- [ ] **Step 5: Commit CI/docs and record verification evidence**

```bash
git add providers/semantics/dsp_core/README.md \
        .github/workflows/dsp-core-semantic-provider.yml \
        docs/superpowers/plans/2026-08-28-dsp-core-semantic-provider.md
git commit -m "ci(semantic): verify DSP Core reference provider"
```

After GitHub Actions runs on the pushed branch/PR, append only factual final evidence to this plan: verified head SHA, focused test count, full regression count/skips, workflow run/job IDs, and any review fixes. Do not rewrite the approved architecture during closeout.

---

## Plan Self-Review Result

- **Spec coverage:** Provider identity/authority, exact eight-term baseline, hash split, provenance, exact lookup, unclaimed capability N/A handling, D5 compatibility, environment pinning/conflict, real MCP transport, architecture isolation, CI, and scope closeout all map to explicit tasks above.
- **Placeholder scan:** No `TBD`, `TODO`, “implement later”, or unspecified “add tests” steps remain.
- **Type consistency:** `DspCoreSemanticProvider`, `SemanticTermCatalog`, `DSP_CORE_CATALOG`, `DSP_CORE_PROVIDER`, `ProviderRef("dsp.core", "1.0")`, and existing Semantic Service/MCP signatures are used consistently across tasks.
- **YAGNI check:** No mapping, validation, projection, IFC, Metro, ingestion, D4, D6, D7, Gateway, persistence, discovery, or localization implementation is included.
