# Semantic Service Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the provider-neutral Semantic Service Core for Spec v0.6 Phase C: immutable provider manifests, capability contracts, provider registration, namespace authority, deterministic routing, pinned content-addressed `SemanticEnvironment`s, and logical query APIs without introducing MCP transport or concrete IFC/Metro/Enterprise semantics.

**Architecture:** Add an independent Python 3.11 package at `platform/semantic_service`. `manifest.py` owns immutable provider identity and machine-semantic hashing; `providers.py` owns provider-neutral DTOs and capability protocols; `registry.py` owns immutable provider registration; `environment.py` owns exact-version pinning and immutable environment storage; `service.py` composes registry + environment store and performs deterministic routing/aggregation. `semantic_service` never imports `semantic_runtime`; the only D5 compatibility proof constructs `SemanticEnvironmentRef` from the two stable string values at the test/integration boundary.

**Tech Stack:** Python 3.11, stdlib `dataclasses`, `enum`, `typing.Protocol`, `hashlib`, canonical JSON, pytest, GitHub Actions. No runtime third-party dependency and no MCP SDK in this PR.

**Spec:** `docs/superpowers/specs/2026-08-28-semantic-service-core-design.md`

## Global Constraints

- Python baseline is `>=3.11`.
- `semantic_service` SHALL NOT import `semantic_runtime`.
- `semantic_service` SHALL NOT import MCP/FastMCP, AutoCAD/Revit/Tekla native packages, or concrete IFC/Metro/Enterprise provider implementations.
- MCP remains a later thin adapter; no MCP server/client is implemented in this plan.
- Provider capability contracts are split into VOCABULARY, MAPPING, VALIDATION, and a PROJECTION marker; do not create one giant provider interface.
- `(provider_id, version)` is immutable inside a registry; a later registration never replaces different machine-semantic metadata.
- Environment selection is always exact `provider_id + version`; there is no `latest` planning API.
- One pinned environment may have at most one `AUTHORITATIVE` provider per namespace; `EXTENSION` may coexist but never becomes vocabulary fallback.
- Environment identity is content-addressed: `environment_id == "sem-env:" + content_hash`.
- Environment hashing includes selected provider version, provider `content_hash`, `manifest_hash`, namespaces, capabilities, authority, compatibility, and exact dependencies; caller input order must not affect the hash.
- Mapping and validation fan out only to selected providers in the pinned environment and in deterministic `(provider_id, version)` order.
- Mapping results are returned as candidates with provenance; Semantic Service does not choose a winner.
- Validation results are aggregated with provenance; Semantic Service does not majority-vote failures away.
- Provider exceptions are wrapped in Semantic Service domain errors with provider provenance; the core never invents fallback semantic results.
- `NormalizedDesignFact`, `NormalizedDesignFactBatch`, `project_facts`, concrete IFC4.3/DSP Core/Metro semantics, enterprise A-WALL mapping, D3/D4 changes, and D6/D7 are out of scope.

## Locked File Structure

```text
platform/semantic_service/
  pyproject.toml
  src/semantic_service/
    __init__.py          # curated public surface only
    errors.py            # typed fail-closed domain errors
    manifest.py          # provider identity, authority, exact refs, hashing
    providers.py         # provider-neutral DTOs + capability Protocols
    registry.py          # immutable provider registration/lookup
    environment.py       # pinning, authority/dependency checks, immutable store
    service.py           # environment-scoped routing and aggregation

tests/semantic_service/
  helpers.py             # deterministic fake providers for tests only
  test_manifest.py
  test_provider_contracts.py
  test_registry.py
  test_environment.py
  test_service_vocabulary.py
  test_service_mapping_validation.py
  test_public_surface.py
  test_d5_environment_ref_compatibility.py

.github/workflows/semantic-service.yml
```

---

### Task 1: Package skeleton, typed errors, immutable provider manifest, and deterministic manifest hash

**Files:**
- Create: `platform/semantic_service/pyproject.toml`
- Create: `platform/semantic_service/src/semantic_service/errors.py`
- Create: `platform/semantic_service/src/semantic_service/manifest.py`
- Create: `platform/semantic_service/src/semantic_service/__init__.py`
- Create: `tests/semantic_service/test_manifest.py`

**Interfaces:**
- Produces `ProviderType`, `SemanticCapability`, `AuthorityMode`, `ProviderRef`, `NamespaceAuthority`, `SemanticProviderManifest`.
- `SemanticProviderManifest.manifest_hash: str` is the deterministic SHA-256 of canonical machine-semantic payload.
- `ProviderRef(provider_id: str, version: str)` is reused later as exact dependency and environment selection.
- Produces error hierarchy rooted at `SemanticServiceError`.

- [ ] **Step 1: Write the failing manifest tests**

Create `tests/semantic_service/test_manifest.py` with concrete RED cases:

```python
from dataclasses import replace

import pytest

from semantic_service import (
    AuthorityMode,
    ManifestValidationError,
    NamespaceAuthority,
    ProviderRef,
    ProviderType,
    SemanticCapability,
    SemanticProviderManifest,
)


def _manifest(**changes):
    base = SemanticProviderManifest(
        provider_id="buildingSMART.ifc43",
        provider_type=ProviderType.STANDARD,
        version="4.3.2.0",
        content_hash="ifc-content-v1",
        namespaces=("ifc",),
        capabilities=frozenset({
            SemanticCapability.VOCABULARY,
            SemanticCapability.VALIDATION,
            SemanticCapability.PROJECTION,
        }),
        authority=(NamespaceAuthority("ifc", AuthorityMode.AUTHORITATIVE),),
        compatibility=("semantic-service.v1",),
        requires=(),
    )
    return replace(base, **changes)


def test_manifest_hash_is_order_independent_for_set_like_fields():
    first = _manifest(
        namespaces=("ifc", "ifc-ext"),
        compatibility=("z", "a"),
    )
    second = _manifest(
        namespaces=("ifc-ext", "ifc"),
        compatibility=("a", "z"),
    )
    assert first.manifest_hash == second.manifest_hash


def test_machine_semantic_change_changes_manifest_hash():
    baseline = _manifest()
    changed = _manifest(capabilities=frozenset({SemanticCapability.VOCABULARY}))
    assert baseline.manifest_hash != changed.manifest_hash


def test_self_dependency_is_rejected():
    with pytest.raises(ManifestValidationError, match="self-dependency"):
        _manifest(requires=(ProviderRef("buildingSMART.ifc43", "4.3.2.0"),))


def test_namespace_token_with_colon_is_rejected():
    with pytest.raises(ManifestValidationError, match="namespace"):
        _manifest(namespaces=("ifc:bad",))
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
PYTHONPATH=platform/semantic_service/src pytest -q tests/semantic_service/test_manifest.py
```

Expected: collection fails with `ModuleNotFoundError: No module named 'semantic_service'`.

- [ ] **Step 3: Add package metadata and the complete error hierarchy**

Create `platform/semantic_service/pyproject.toml` following `platform/semantic_runtime/pyproject.toml`:

```toml
[project]
name = "semantic-service"
version = "0.1.0"
description = "Provider-neutral semantic registry, routing, and environment pinning for DSP."
requires-python = ">=3.11"
dependencies = []

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Create these classes in `errors.py`:

```python
class SemanticServiceError(ValueError): ...
class ManifestValidationError(SemanticServiceError): ...
class ProviderRegistrationConflictError(SemanticServiceError): ...
class ProviderNotFoundError(SemanticServiceError): ...
class ProviderCapabilityError(SemanticServiceError): ...
class ProviderDependencyError(SemanticServiceError): ...
class NamespaceAuthorityError(SemanticServiceError): ...
class EnvironmentIntegrityError(SemanticServiceError): ...
class EnvironmentNotFoundError(SemanticServiceError): ...
class TermResolutionError(SemanticServiceError): ...
```

- [ ] **Step 4: Implement minimal manifest normalization and hashing**

In `manifest.py`, use frozen/slots dataclasses and normalize tuple/set-like fields in `__post_init__`. Namespace tokens must match `^[A-Za-z][A-Za-z0-9_.-]*$`, required strings are trimmed/non-empty, duplicate namespace-authority entries are rejected, every authority namespace must also appear in `namespaces`, and exact self-dependency is rejected.

Canonical hash helper:

```python
def _hash_payload(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
```

`manifest_hash` payload must contain exactly:

```python
{
    "provider_id": self.provider_id,
    "provider_type": self.provider_type.value,
    "version": self.version,
    "content_hash": self.content_hash,
    "namespaces": list(self.namespaces),
    "capabilities": [item.value for item in self.capabilities],
    "authority": [item.payload() for item in self.authority],
    "compatibility": list(self.compatibility),
    "requires": [item.payload() for item in self.requires],
}
```

- [ ] **Step 5: Export only the Task 1 public types and run GREEN**

Run:

```bash
PYTHONPATH=platform/semantic_service/src pytest -q tests/semantic_service/test_manifest.py
```

Expected: all Task 1 tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add platform/semantic_service tests/semantic_service/test_manifest.py
git commit -m "feat(semantic): add provider manifest contracts"
```

---

### Task 2: Provider-neutral semantic DTOs and capability Protocols

**Files:**
- Create: `platform/semantic_service/src/semantic_service/providers.py`
- Create: `tests/semantic_service/test_provider_contracts.py`
- Create: `tests/semantic_service/helpers.py`
- Modify: `platform/semantic_service/src/semantic_service/__init__.py`

**Interfaces:**
- Consumes `SemanticProviderManifest` from Task 1.
- Produces `ProviderProvenance`, `ResolvedTerm`, `TermDescription`, `TermSchema`, `SemanticClaim`, `MappingCandidate`, `ValidationStatus`, `ValidationFinding`.
- Produces runtime-checkable protocols `SemanticProvider`, `SemanticVocabularyProvider`, `SemanticMappingProvider`, `SemanticValidationProvider`, `SemanticProjectionProvider`.
- PROJECTION is intentionally only a marker over `manifest`; no `project_facts()` signature appears in this PR.

- [ ] **Step 1: Write protocol/DTO RED tests**

`test_provider_contracts.py` must prove a vocabulary-only fake satisfies only the vocabulary protocol and that PROJECTION does not require a temporary batch API:

```python
from semantic_service import (
    SemanticMappingProvider,
    SemanticProjectionProvider,
    SemanticValidationProvider,
    SemanticVocabularyProvider,
)
from tests.semantic_service.helpers import VocabularyProvider


def test_capability_protocols_are_separate():
    provider = VocabularyProvider()
    assert isinstance(provider, SemanticVocabularyProvider)
    assert not isinstance(provider, SemanticMappingProvider)
    assert not isinstance(provider, SemanticValidationProvider)


def test_projection_contract_is_marker_only():
    provider = VocabularyProvider(claim_projection=True)
    assert isinstance(provider, SemanticProjectionProvider)
    assert not hasattr(provider, "project_facts")
```

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service/test_provider_contracts.py
```

Expected: import failure for provider DTOs/protocols.

- [ ] **Step 3: Implement immutable DTOs and protocols**

Use these exact method signatures:

```python
@runtime_checkable
class SemanticProvider(Protocol):
    @property
    def manifest(self) -> SemanticProviderManifest: ...

@runtime_checkable
class SemanticVocabularyProvider(SemanticProvider, Protocol):
    def resolve_term(self, term_id: str) -> ResolvedTerm: ...
    def describe_term(self, term_id: str, locale: str | None = None) -> TermDescription: ...
    def get_term_schema(self, term_id: str) -> TermSchema: ...

@runtime_checkable
class SemanticMappingProvider(SemanticProvider, Protocol):
    def find_mappings(
        self,
        source_claim: SemanticClaim,
        target_namespace: str | None = None,
    ) -> tuple[MappingCandidate, ...]: ...

@runtime_checkable
class SemanticValidationProvider(SemanticProvider, Protocol):
    def validate_claim(self, claim: SemanticClaim) -> tuple[ValidationFinding, ...]: ...

@runtime_checkable
class SemanticProjectionProvider(SemanticProvider, Protocol):
    pass
```

`ProviderProvenance` is exactly `(provider_id, version, content_hash)`. `ValidationStatus` is `PASS`, `FAIL`, `NOT_APPLICABLE`. `SemanticClaim.assurance` is a string token and defaults to `"UNKNOWN"`; do not import D5 `AssuranceLevel`.

- [ ] **Step 4: Add deterministic fake providers for later tests**

`helpers.py` supplies `VocabularyProvider`, `MappingProvider`, and `ValidationProvider` that construct valid manifests and return fixed tuples. Keep all IFC/Metro example semantics in tests only.

- [ ] **Step 5: Run Task 1+2 tests GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q \
  tests/semantic_service/test_manifest.py \
  tests/semantic_service/test_provider_contracts.py
```

- [ ] **Step 6: Commit Task 2**

```bash
git add platform/semantic_service/src/semantic_service tests/semantic_service
git commit -m "feat(semantic): define semantic provider capabilities"
```

---

### Task 3: Immutable provider registry and capability conformance

**Files:**
- Create: `platform/semantic_service/src/semantic_service/registry.py`
- Create: `tests/semantic_service/test_registry.py`
- Modify: `platform/semantic_service/src/semantic_service/__init__.py`

**Interfaces:**
- `SemanticProviderRegistry.register(provider: SemanticProvider) -> SemanticProviderManifest`
- `get(provider_id: str, version: str) -> SemanticProvider`
- `get_manifest(provider_id: str, version: str) -> SemanticProviderManifest`
- `versions(provider_id: str) -> tuple[str, ...]`
- `providers_with_capability(capability: SemanticCapability) -> tuple[SemanticProvider, ...]`

- [ ] **Step 1: Write registry RED tests**

Cover idempotency, immutable conflicts, multiple versions, missing provider, and claimed capability mismatch:

```python
def test_identical_registration_is_idempotent():
    registry = SemanticProviderRegistry()
    provider = VocabularyProvider()
    first = registry.register(provider)
    second = registry.register(provider)
    assert first == second
    assert registry.get(first.provider_id, first.version) is provider


def test_same_version_different_machine_manifest_fails_closed():
    registry = SemanticProviderRegistry()
    registry.register(VocabularyProvider(content_hash="hash-a"))
    with pytest.raises(ProviderRegistrationConflictError):
        registry.register(VocabularyProvider(content_hash="hash-b"))


def test_claimed_mapping_without_mapping_protocol_is_rejected():
    registry = SemanticProviderRegistry()
    bad = VocabularyProvider(extra_capabilities={SemanticCapability.MAPPING})
    with pytest.raises(ProviderCapabilityError, match="MAPPING"):
        registry.register(bad)
```

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service/test_registry.py
```

- [ ] **Step 3: Implement registration without replacement semantics**

Use `(provider_id, version)` as the internal key. If an existing manifest equals the incoming manifest, return the existing manifest and retain the originally registered provider object. If the incoming manifest differs in any machine field, raise `ProviderRegistrationConflictError`; never hot-swap the provider behind an occupied immutable version.

- [ ] **Step 4: Enforce claimed capability protocols**

At registration:

```python
checks = {
    SemanticCapability.VOCABULARY: SemanticVocabularyProvider,
    SemanticCapability.MAPPING: SemanticMappingProvider,
    SemanticCapability.VALIDATION: SemanticValidationProvider,
}
```

For each claimed capability above, require `isinstance(provider, protocol)`. `PROJECTION` has no method check beyond `SemanticProvider` because this phase deliberately freezes only the marker.

- [ ] **Step 5: Run registry and prior tests GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service
```

- [ ] **Step 6: Commit Task 3**

```bash
git add platform/semantic_service/src/semantic_service/registry.py \
  platform/semantic_service/src/semantic_service/__init__.py \
  tests/semantic_service/test_registry.py
git commit -m "feat(semantic): add immutable provider registry"
```

---

### Task 4: Exact-version environment pinning, namespace authority, and immutable environment store

**Files:**
- Create: `platform/semantic_service/src/semantic_service/environment.py`
- Create: `tests/semantic_service/test_environment.py`
- Modify: `platform/semantic_service/src/semantic_service/__init__.py`

**Interfaces:**
- `PinnedProvider.from_manifest(manifest) -> PinnedProvider`
- `SemanticEnvironment(providers, environment_id, content_hash)` is immutable.
- `SemanticEnvironmentStore.pin(selections: Iterable[ProviderRef], registry: SemanticProviderRegistry) -> SemanticEnvironment`
- `get(environment_id: str) -> SemanticEnvironment`
- `get_by_hash(content_hash: str) -> SemanticEnvironment`

- [ ] **Step 1: Write environment RED tests**

Required cases:

```python
def test_pin_is_order_independent_and_content_addressed():
    registry = registry_with_ifc_and_enterprise()
    store = SemanticEnvironmentStore()
    first = store.pin((ProviderRef("ifc", "1"), ProviderRef("acme", "2")), registry)
    second = store.pin((ProviderRef("acme", "2"), ProviderRef("ifc", "1")), registry)
    assert first == second
    assert first.environment_id == f"sem-env:{first.content_hash}"


def test_missing_exact_dependency_fails():
    registry = registry_with_metro_requiring_ifc()
    with pytest.raises(ProviderDependencyError, match="buildingSMART.ifc43@4.3.2.0"):
        SemanticEnvironmentStore().pin((ProviderRef("dsp.metro.semantic", "3.2"),), registry)


def test_two_authoritative_ifc_providers_fail():
    registry = registry_with_two_ifc_authorities()
    with pytest.raises(NamespaceAuthorityError, match="ifc"):
        SemanticEnvironmentStore().pin(all_refs(registry), registry)


def test_ifc_extension_can_coexist_with_authority():
    registry = registry_with_ifc_authority_and_metro_extension()
    environment = SemanticEnvironmentStore().pin(all_refs(registry), registry)
    assert len(environment.providers) == 2
```

Also add parameterized tests proving that changing provider version, `content_hash`, authority, capabilities, compatibility, or dependency declaration changes the environment hash.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service/test_environment.py
```

- [ ] **Step 3: Implement `PinnedProvider` and canonical environment hashing**

`PinnedProvider.payload()` contains exactly:

```python
{
    "provider_id": ...,
    "provider_type": ...,
    "version": ...,
    "content_hash": ...,
    "manifest_hash": ...,
    "namespaces": [...],
    "capabilities": [...],
    "authority": [...],
    "compatibility": [...],
    "requires": [...],
}
```

Sort pinned records by `(provider_id, version)` before hashing. Hash canonical JSON with the same SHA-256 helper semantics as Task 1. Build `environment_id` from the full digest, not a truncated digest.

- [ ] **Step 4: Implement exact dependency and namespace authority barriers**

`pin()` must resolve every selection through the registry first. Every declared `requires` ref must occur in the selected exact-ref set. Build an `authorities: dict[str, ProviderRef]`; a second `AUTHORITATIVE` owner for the same namespace raises `NamespaceAuthorityError`. `EXTENSION` entries do not occupy that owner slot.

- [ ] **Step 5: Implement immutable dual-key store**

Store by both `environment_id` and `content_hash`. Re-pinning the identical provider set returns the existing equal environment. If either key is occupied by a non-equal object, raise `EnvironmentIntegrityError`. Unknown lookup raises `EnvironmentNotFoundError`.

- [ ] **Step 6: Run all focused semantic-service tests GREEN and commit**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service

git add platform/semantic_service/src/semantic_service/environment.py \
  platform/semantic_service/src/semantic_service/__init__.py \
  tests/semantic_service/test_environment.py \
  tests/semantic_service/helpers.py
git commit -m "feat(semantic): pin immutable semantic environments"
```

---

### Task 5: SemanticService vocabulary routing on one pinned environment

**Files:**
- Create: `platform/semantic_service/src/semantic_service/service.py`
- Create: `tests/semantic_service/test_service_vocabulary.py`
- Modify: `platform/semantic_service/src/semantic_service/__init__.py`

**Interfaces:**
- `SemanticService(registry: SemanticProviderRegistry, environments: SemanticEnvironmentStore)`
- `resolve_term(term_id: str, environment_id: str) -> ResolvedTerm`
- `describe_term(term_id: str, environment_id: str, locale: str | None = None) -> TermDescription`
- `get_term_schema(term_id: str, environment_id: str) -> TermSchema`
- `get_provider_manifest(provider_id: str, version: str) -> SemanticProviderManifest`
- `get_environment(environment_id: str) -> SemanticEnvironment`

- [ ] **Step 1: Write vocabulary routing RED tests**

Prove: only the pinned `AUTHORITATIVE` provider is called; an `EXTENSION` provider is never fallback; missing authority fails; missing VOCABULARY capability fails; malformed term without `namespace:local` fails; provider exception becomes `TermResolutionError` containing provider id/version.

Example:

```python
def test_resolve_term_calls_only_authoritative_provider():
    service, authoritative, extension, environment = service_with_ifc_authority_and_extension()
    result = service.resolve_term("ifc:IfcWall", environment.environment_id)
    assert result.term_id == "ifc:IfcWall"
    assert authoritative.resolve_calls == ["ifc:IfcWall"]
    assert extension.resolve_calls == []


def test_extension_is_not_fallback_when_authority_missing():
    service, environment = service_with_ifc_extension_only()
    with pytest.raises(NamespaceAuthorityError, match="ifc"):
        service.resolve_term("ifc:IfcWall", environment.environment_id)
```

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service/test_service_vocabulary.py
```

- [ ] **Step 3: Implement namespace parsing and authoritative provider selection**

Private helper behavior:

```text
term_id -> split once on ':' -> namespace
load environment by explicit environment_id
find pinned records whose authority contains namespace/AUTHORITATIVE
require exactly one
require VOCABULARY in pinned capabilities
resolve exact provider object from registry by pinned id/version
```

Do not consult providers outside the selected environment. Do not fall back from failed/missing authority to `EXTENSION`.

- [ ] **Step 4: Implement vocabulary calls and error wrapping**

Call the appropriate protocol method. On provider exception, raise `TermResolutionError` with operation, provider id, provider version, and original exception type in the message; chain with `raise ... from exc`.

- [ ] **Step 5: Run GREEN and commit**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service

git add platform/semantic_service/src/semantic_service/service.py \
  platform/semantic_service/src/semantic_service/__init__.py \
  tests/semantic_service/test_service_vocabulary.py \
  tests/semantic_service/helpers.py
git commit -m "feat(semantic): route pinned vocabulary queries"
```

---

### Task 6: Deterministic mapping/validation fan-out without semantic voting

**Files:**
- Create: `tests/semantic_service/test_service_mapping_validation.py`
- Modify: `platform/semantic_service/src/semantic_service/service.py`
- Modify: `tests/semantic_service/helpers.py`

**Interfaces:**
- `find_mappings(source_claim: SemanticClaim, environment_id: str, target_namespace: str | None = None) -> tuple[MappingCandidate, ...]`
- `validate_claim(claim: SemanticClaim, environment_id: str) -> tuple[ValidationFinding, ...]`

- [ ] **Step 1: Write deterministic fan-out RED tests**

Tests must prove:

```python
def test_mapping_uses_only_selected_providers_and_sorts_results():
    service, environment, selected_a, selected_b, unselected = mapping_service_fixture()
    results = service.find_mappings(SemanticClaim(subject="wall-1"), environment.environment_id)
    assert [item.mapping_id for item in results] == ["map-a", "map-b"]
    assert selected_a.calls == 1
    assert selected_b.calls == 1
    assert unselected.calls == 0


def test_validation_preserves_standard_failure_and_domain_pass():
    service, environment = validation_service_with_fail_and_pass()
    findings = service.validate_claim(SemanticClaim(subject="wall-1"), environment.environment_id)
    assert [item.status for item in findings] == [ValidationStatus.FAIL, ValidationStatus.PASS]
```

Also prove provider call order is `(provider_id, version)`, mapping output sorting is `(mapping_id, provider_id, provider_version)`, validation output sorting is `(provider_id, provider_version, rule_id, status)`, `NOT_APPLICABLE` is preserved, and a provider exception aborts with wrapped `SemanticServiceError` rather than returning partial guessed success.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service/test_service_mapping_validation.py
```

- [ ] **Step 3: Implement selected-provider capability fan-out**

Iterate over `environment.providers` already sorted by id/version. For each pinned provider whose capability set contains MAPPING or VALIDATION, retrieve that exact provider from registry and invoke the matching protocol. Never use `registry.providers_with_capability()` directly for runtime fan-out because that would include unpinned versions/providers.

- [ ] **Step 4: Aggregate without winner selection or voting**

Mapping returns every candidate after deterministic sort. Validation returns every finding, including `NOT_APPLICABLE`; no pass count can erase a failure. Preserve provider-provided provenance fields unchanged.

- [ ] **Step 5: Run GREEN and commit**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service

git add platform/semantic_service/src/semantic_service/service.py \
  tests/semantic_service/test_service_mapping_validation.py \
  tests/semantic_service/helpers.py
git commit -m "feat(semantic): aggregate pinned mapping and validation"
```

---

### Task 7: Public surface, architecture guards, D5 ref compatibility, and dedicated CI

**Files:**
- Create: `tests/semantic_service/test_public_surface.py`
- Create: `tests/semantic_service/test_d5_environment_ref_compatibility.py`
- Create: `.github/workflows/semantic-service.yml`
- Modify: `platform/semantic_service/src/semantic_service/__init__.py`

**Interfaces:**
- Public package exports all stable Task 1–6 contracts and does not export internal hashing/routing helpers.
- Integration proof uses existing D5 `SemanticEnvironmentRef(environment_id, content_hash)` without adding any import from `semantic_service` into D5.

- [ ] **Step 1: Add public-surface and import-boundary RED/guard tests**

`test_public_surface.py`:

```python
import ast
from pathlib import Path

import semantic_service as s


def test_public_surface_contains_phase_c_contracts_only():
    required = (
        "SemanticProviderManifest",
        "SemanticProviderRegistry",
        "SemanticEnvironment",
        "SemanticEnvironmentStore",
        "SemanticService",
        "SemanticVocabularyProvider",
        "SemanticMappingProvider",
        "SemanticValidationProvider",
        "SemanticProjectionProvider",
    )
    assert [name for name in required if not hasattr(s, name)] == []
    assert not hasattr(s, "NormalizedDesignFactBatch")
    assert not hasattr(s, "McpSemanticProviderAdapter")


def test_semantic_service_has_no_d5_mcp_or_host_imports():
    package = Path(s.__file__).resolve().parent
    forbidden_roots = {
        "semantic_runtime", "mcp", "fastmcp", "autodesk", "revit", "tekla"
    }
    found = []
    for path in sorted(package.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".", 1)[0].lower() for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                roots = [node.module.split(".", 1)[0].lower()]
            else:
                continue
            found.extend(root for root in roots if root in forbidden_roots)
    assert found == []
```

- [ ] **Step 2: Add D5 environment-ref compatibility test**

```python
from semantic_runtime import SemanticEnvironmentRef
from semantic_service import ProviderRef, SemanticEnvironmentStore


def test_pinned_environment_values_construct_existing_d5_ref(registry_with_ifc):
    environment = SemanticEnvironmentStore().pin(
        (ProviderRef("buildingSMART.ifc43", "4.3.2.0"),),
        registry_with_ifc,
    )
    ref = SemanticEnvironmentRef(environment.environment_id, environment.content_hash)
    assert ref.payload() == {
        "environment_id": environment.environment_id,
        "content_hash": environment.content_hash,
    }
```

The test may import both packages; production `semantic_service` source may not.

- [ ] **Step 3: Finalize curated `__all__`**

Export stable errors, enums, manifest values, provider DTOs/protocols, registry, environment, and service. Do not export `_hash_payload`, namespace parser, or internal routing helpers.

- [ ] **Step 4: Add dedicated GitHub Actions workflow**

Create `.github/workflows/semantic-service.yml`:

```yaml
name: Semantic service verification

on:
  push:
    branches:
      - 'feat/semantic-service-core'
    paths:
      - 'platform/semantic_service/**'
      - 'tests/semantic_service/**'
      - 'docs/superpowers/specs/2026-08-28-semantic-service-core-design.md'
      - 'docs/superpowers/plans/2026-08-28-semantic-service-core.md'
      - '.github/workflows/semantic-service.yml'
  pull_request:
    paths:
      - 'platform/semantic_service/**'
      - 'tests/semantic_service/**'
      - 'docs/superpowers/specs/2026-08-28-semantic-service-core-design.md'
      - 'docs/superpowers/plans/2026-08-28-semantic-service-core.md'
      - '.github/workflows/semantic-service.yml'
  workflow_dispatch:

jobs:
  semantic-service:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install packages
        run: |
          python -m pip install pytest pytest-asyncio jsonschema
          python -m pip install -e contracts/python -e hosts/autocad/sidecar \
            -e platform/semantic_runtime -e platform/semantic_service
      - name: Run Semantic Service tests
        run: pytest -q tests/semantic_service
      - name: Run full Python regression tests
        run: pytest -q contracts/python/tests tests/contracts tests/integration \
          tests/orchestrator tests/semantic_runtime tests/semantic_service
```

- [ ] **Step 5: Run the complete local verification set**

From a clean environment with the editable packages installed:

```bash
python -m pip install -e contracts/python -e hosts/autocad/sidecar \
  -e platform/semantic_runtime -e platform/semantic_service
pytest -q tests/semantic_service
pytest -q contracts/python/tests tests/contracts tests/integration \
  tests/orchestrator tests/semantic_runtime tests/semantic_service
```

Expected: Semantic Service focused suite passes; full regression has no new failures. Existing live-AutoCAD-gated skips remain skips unless the live host is explicitly enabled.

- [ ] **Step 6: Commit the conformance/CI gate**

```bash
git add platform/semantic_service/src/semantic_service/__init__.py \
  tests/semantic_service/test_public_surface.py \
  tests/semantic_service/test_d5_environment_ref_compatibility.py \
  .github/workflows/semantic-service.yml
git commit -m "test(semantic): enforce Semantic Service boundaries"
```

---

### Task 8: PR #6 implementation closeout and fresh-head verification

**Files:**
- Modify: `docs/superpowers/plans/2026-08-28-semantic-service-core.md` only to record executed commit SHAs and fresh CI evidence after implementation.
- Modify: PR #6 body/status through GitHub metadata; no production code in this task.

**Interfaces:**
- Consumes all Task 1–7 deliverables.
- Produces a reviewable PR whose final head is covered by a fresh successful Semantic Service workflow run.

- [ ] **Step 1: Review architecture invariants before claiming completion**

Verify the production package contains no MCP SDK imports, no `semantic_runtime` import, no Host product branches/mappings, no concrete IFC/Metro provider implementation, no mutable `latest` API, and no `project_facts` payload contract.

- [ ] **Step 2: Verify exact spec coverage**

Map the design requirements to tests: immutable registration; capability split; authority conflict; extension coexistence; exact dependency; environment hash determinism; explicit environment-scoped vocabulary routing; selected-only mapping/validation fan-out; provenance preservation; D5 ref compatibility; architecture import guard.

- [ ] **Step 3: Wait for fresh GitHub Actions at the final head and record evidence**

Only claim completion after the final PR head SHA has a successful `Semantic service verification` run. Record exact focused/full counts and any expected skips in this plan execution record and PR body.

- [ ] **Step 4: Keep PR #6 Draft until implementation review gates pass**

PR #6 is stacked on `feat/semantic-runtime` while PR #5 remains unmerged. After PR #5 merges, retarget PR #6 to `main`, obtain fresh CI on the resulting head/merge ref, and only then mark PR #6 Ready for review. Do not merge automatically.

- [ ] **Step 5: Commit the execution record only after fresh-head verification**

```bash
git add docs/superpowers/plans/2026-08-28-semantic-service-core.md
git commit -m "docs: record Semantic Service core verification"
```

## Implementation Order / Review Gates

Execute Tasks 1 → 8 strictly in order. Each Task 1–7 is a standalone reviewer gate with its own RED → minimal GREEN → focused regression → commit cycle. Do not combine concrete IFC/Metro content or Semantic MCP transport into these commits even if the generic interfaces make those follow-ups easy.

The expected PR evolution is:

```text
Task 1  Manifest + errors                         RED/GREEN
Task 2  Provider DTOs/protocols                  RED/GREEN
Task 3  Immutable Registry                       RED/GREEN
Task 4  Environment pinning/store                RED/GREEN
Task 5  Vocabulary routing                       RED/GREEN
Task 6  Mapping/validation aggregation           RED/GREEN
Task 7  Public surface + architecture + CI       RED/GREEN
Task 8  Fresh-head closeout                      verification only
```
