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
  helpers.py             # deterministic fake providers/factories for tests only
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
    first = _manifest(namespaces=("ifc", "ifc-ext"), compatibility=("z", "a"))
    second = _manifest(namespaces=("ifc-ext", "ifc"), compatibility=("a", "z"))
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

Create these classes in `errors.py` as empty typed subclasses with short docstrings:

```python
class SemanticServiceError(ValueError): pass
class ManifestValidationError(SemanticServiceError): pass
class ProviderRegistrationConflictError(SemanticServiceError): pass
class ProviderNotFoundError(SemanticServiceError): pass
class ProviderCapabilityError(SemanticServiceError): pass
class ProviderDependencyError(SemanticServiceError): pass
class NamespaceAuthorityError(SemanticServiceError): pass
class EnvironmentIntegrityError(SemanticServiceError): pass
class EnvironmentNotFoundError(SemanticServiceError): pass
class TermResolutionError(SemanticServiceError): pass
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

`manifest_hash` payload must contain exactly `provider_id`, `provider_type`, `version`, `content_hash`, sorted `namespaces`, sorted `capabilities`, sorted `authority`, sorted `compatibility`, and sorted exact `requires` records. Labels/descriptions/health/transport data are absent.

- [ ] **Step 5: Export only the Task 1 public types and run GREEN**

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

### Task 2: Provider-neutral semantic DTOs, capability Protocols, and explicit test factories

**Files:**
- Create: `platform/semantic_service/src/semantic_service/providers.py`
- Create: `tests/semantic_service/test_provider_contracts.py`
- Create: `tests/semantic_service/helpers.py`
- Modify: `platform/semantic_service/src/semantic_service/__init__.py`

**Interfaces:**
- Produces `ProviderProvenance`, `ResolvedTerm`, `TermDescription`, `TermSchema`, `SemanticClaim`, `MappingCandidate`, `ValidationStatus`, `ValidationFinding`.
- Produces runtime-checkable `SemanticProvider`, `SemanticVocabularyProvider`, `SemanticMappingProvider`, `SemanticValidationProvider`; `SemanticProjectionProvider` is a marker protocol with no batch method.
- Test-only `helpers.py` produces all fake-provider/factory names used by Tasks 2–7, so later tests have no implicit fixture contract.

- [ ] **Step 1: Write protocol/DTO RED tests**

```python
from semantic_service import (
    SemanticMappingProvider,
    SemanticValidationProvider,
    SemanticVocabularyProvider,
)
from tests.semantic_service.helpers import VocabularyProvider


def test_capability_protocols_are_separate():
    provider = VocabularyProvider()
    assert isinstance(provider, SemanticVocabularyProvider)
    assert not isinstance(provider, SemanticMappingProvider)
    assert not isinstance(provider, SemanticValidationProvider)


def test_projection_phase_does_not_require_batch_api():
    provider = VocabularyProvider(claim_projection=True)
    assert provider.manifest.capabilities
    assert not hasattr(provider, "project_facts")
```

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service/test_provider_contracts.py
```

Expected: import failure for provider DTOs/protocols.

- [ ] **Step 3: Implement immutable DTOs and protocols**

Use these exact provider signatures:

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
    def find_mappings(self, source_claim: SemanticClaim, target_namespace: str | None = None) -> tuple[MappingCandidate, ...]: ...

@runtime_checkable
class SemanticValidationProvider(SemanticProvider, Protocol):
    def validate_claim(self, claim: SemanticClaim) -> tuple[ValidationFinding, ...]: ...

class SemanticProjectionProvider(SemanticProvider, Protocol):
    pass
```

`ProviderProvenance` is exactly `(provider_id, version, content_hash)`. `ValidationStatus` is `PASS`, `FAIL`, `NOT_APPLICABLE`. `SemanticClaim.assurance` is a string token defaulting to `"UNKNOWN"`; do not import D5 `AssuranceLevel`.

- [ ] **Step 4: Implement every later test factory explicitly in `helpers.py`**

Create these classes/functions with the listed return contract:

```python
class VocabularyProvider: ...
class MappingProvider: ...
class ValidationProvider: ...

def make_manifest(
    *, provider_id: str, version: str, namespace: str,
    authority: AuthorityMode, capabilities: frozenset[SemanticCapability],
    content_hash: str | None = None, compatibility: tuple[str, ...] = ("semantic-service.v1",),
    requires: tuple[ProviderRef, ...] = (),
) -> SemanticProviderManifest: ...

def register_all(*providers: SemanticProvider) -> SemanticProviderRegistry: ...
def all_refs(registry: SemanticProviderRegistry) -> tuple[ProviderRef, ...]: ...
def registry_with_ifc() -> SemanticProviderRegistry: ...
def registry_with_ifc_and_enterprise() -> SemanticProviderRegistry: ...
def registry_with_metro_requiring_ifc() -> SemanticProviderRegistry: ...
def registry_with_two_ifc_authorities() -> SemanticProviderRegistry: ...
def registry_with_ifc_authority_and_metro_extension() -> SemanticProviderRegistry: ...
def service_with_ifc_authority_and_extension() -> tuple[SemanticService, VocabularyProvider, VocabularyProvider, SemanticEnvironment]: ...
def service_with_ifc_extension_only() -> tuple[SemanticService, SemanticEnvironment]: ...
def mapping_service_fixture() -> tuple[SemanticService, SemanticEnvironment, MappingProvider, MappingProvider, MappingProvider]: ...
def validation_service_with_fail_and_pass() -> tuple[SemanticService, SemanticEnvironment]: ...
```

Task 2 initially defines these helpers against the public names already available; where a later production class (`SemanticProviderRegistry`, `SemanticEnvironment`, `SemanticService`) does not exist yet, add the helper function only in the task that first provides that production class. The names/signatures above are frozen now and MUST NOT be renamed later.

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
- Modify: `tests/semantic_service/helpers.py` to activate registry factories frozen in Task 2.

**Interfaces:**
- `register(provider: SemanticProvider) -> SemanticProviderManifest`
- `get(provider_id: str, version: str) -> SemanticProvider`
- `get_manifest(provider_id: str, version: str) -> SemanticProviderManifest`
- `versions(provider_id: str) -> tuple[str, ...]`
- `providers_with_capability(capability: SemanticCapability) -> tuple[SemanticProvider, ...]`

- [ ] **Step 1: Write registry RED tests**

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

Add tests for `ProviderNotFoundError`, deterministic sorted `versions()`, and coexistence of two versions of one provider.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service/test_registry.py
```

- [ ] **Step 3: Implement registration without replacement semantics**

Use `(provider_id, version)` as the internal key. Equal manifest re-registration returns the existing manifest and retains the originally registered provider object. Any different manifest under the occupied key raises `ProviderRegistrationConflictError`; never hot-swap an immutable version.

- [ ] **Step 4: Enforce claimed capability protocols**

Require VOCABULARY → `SemanticVocabularyProvider`, MAPPING → `SemanticMappingProvider`, VALIDATION → `SemanticValidationProvider`. PROJECTION has no concrete method check in this phase beyond the base `SemanticProvider` manifest contract.

- [ ] **Step 5: Activate registry helper factories and run GREEN**

Implement `register_all`, `all_refs`, `registry_with_ifc`, `registry_with_ifc_and_enterprise`, `registry_with_metro_requiring_ifc`, `registry_with_two_ifc_authorities`, and `registry_with_ifc_authority_and_metro_extension` exactly as frozen in Task 2.

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service
```

- [ ] **Step 6: Commit Task 3**

```bash
git add platform/semantic_service/src/semantic_service/registry.py \
  platform/semantic_service/src/semantic_service/__init__.py \
  tests/semantic_service/test_registry.py tests/semantic_service/helpers.py
git commit -m "feat(semantic): add immutable provider registry"
```

---

### Task 4: Exact-version environment pinning, namespace authority, and immutable environment store

**Files:**
- Create: `platform/semantic_service/src/semantic_service/environment.py`
- Create: `tests/semantic_service/test_environment.py`
- Modify: `platform/semantic_service/src/semantic_service/__init__.py`
- Modify: `tests/semantic_service/helpers.py` to activate environment-dependent factories.

**Interfaces:**
- `PinnedProvider.from_manifest(manifest) -> PinnedProvider`
- `SemanticEnvironmentStore.pin(selections: Iterable[ProviderRef], registry: SemanticProviderRegistry) -> SemanticEnvironment`
- `get(environment_id: str) -> SemanticEnvironment`
- `get_by_hash(content_hash: str) -> SemanticEnvironment`

- [ ] **Step 1: Write environment RED tests**

```python
def test_pin_is_order_independent_and_content_addressed():
    registry = registry_with_ifc_and_enterprise()
    refs = all_refs(registry)
    store = SemanticEnvironmentStore()
    first = store.pin(refs, registry)
    second = store.pin(tuple(reversed(refs)), registry)
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

Add parameterized tests proving that changing provider version, `content_hash`, authority, capabilities, compatibility, or dependency declaration changes the environment hash.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service/test_environment.py
```

- [ ] **Step 3: Implement `PinnedProvider` and canonical environment hashing**

`PinnedProvider.payload()` contains provider id/type/version/content hash/manifest hash plus namespaces, capabilities, authority, compatibility, and exact requires. Sort records by `(provider_id, version)` before canonical JSON SHA-256. Build `environment_id` from the full digest.

- [ ] **Step 4: Implement exact dependency and namespace authority barriers**

Resolve every selection through registry. Every `requires` ref must occur in the selected exact-ref set. A second `AUTHORITATIVE` owner for the same namespace raises `NamespaceAuthorityError`; `EXTENSION` never occupies that owner slot.

- [ ] **Step 5: Implement immutable dual-key store and activate environment helpers**

Store by `environment_id` and `content_hash`. Equal re-pin is idempotent. Occupied key with non-equal object raises `EnvironmentIntegrityError`; unknown lookup raises `EnvironmentNotFoundError`. Environment helper factories must now return real `SemanticEnvironment` values.

- [ ] **Step 6: Run GREEN and commit**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service

git add platform/semantic_service/src/semantic_service/environment.py \
  platform/semantic_service/src/semantic_service/__init__.py \
  tests/semantic_service/test_environment.py tests/semantic_service/helpers.py
git commit -m "feat(semantic): pin immutable semantic environments"
```

---

### Task 5: SemanticService vocabulary routing on one pinned environment

**Files:**
- Create: `platform/semantic_service/src/semantic_service/service.py`
- Create: `tests/semantic_service/test_service_vocabulary.py`
- Modify: `platform/semantic_service/src/semantic_service/__init__.py`
- Modify: `tests/semantic_service/helpers.py` to activate service factories.

**Interfaces:**
- `SemanticService(registry: SemanticProviderRegistry, environments: SemanticEnvironmentStore)`
- `resolve_term(term_id: str, environment_id: str) -> ResolvedTerm`
- `describe_term(term_id: str, environment_id: str, locale: str | None = None) -> TermDescription`
- `get_term_schema(term_id: str, environment_id: str) -> TermSchema`
- `get_provider_manifest(provider_id: str, version: str) -> SemanticProviderManifest`
- `get_environment(environment_id: str) -> SemanticEnvironment`

- [ ] **Step 1: Write vocabulary routing RED tests**

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

Also test missing VOCABULARY capability, malformed term without `namespace:local`, unknown environment, and provider exception → `TermResolutionError` containing provider id/version.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service/test_service_vocabulary.py
```

- [ ] **Step 3: Implement namespace parsing and authoritative provider selection**

Split once on `:`; load the explicit environment; find exactly one pinned provider declaring `AUTHORITATIVE` for that namespace; require VOCABULARY in its pinned capability set; retrieve exactly that provider id/version from registry. Never consult an unpinned or extension fallback provider.

- [ ] **Step 4: Implement vocabulary calls, error wrapping, and service helper factories**

On provider exception, raise `TermResolutionError` containing operation/provider id/version/original exception type and chain the cause. Activate `service_with_ifc_authority_and_extension()` and `service_with_ifc_extension_only()` in `helpers.py`.

- [ ] **Step 5: Run GREEN and commit**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service

git add platform/semantic_service/src/semantic_service/service.py \
  platform/semantic_service/src/semantic_service/__init__.py \
  tests/semantic_service/test_service_vocabulary.py tests/semantic_service/helpers.py
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

Also prove provider call order `(provider_id, version)`, mapping sort `(mapping_id, provider_id, provider_version)`, validation sort `(provider_id, provider_version, rule_id, status)`, preservation of `NOT_APPLICABLE`, and provider exception abort with wrapped `SemanticServiceError` rather than partial guessed success.

- [ ] **Step 2: Verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service/test_service_mapping_validation.py
```

- [ ] **Step 3: Implement selected-provider capability fan-out**

Iterate only `environment.providers`; for selected MAPPING/VALIDATION capability records, retrieve the exact provider from registry and invoke it. Never use global `providers_with_capability()` for runtime fan-out because that includes unpinned registrations.

- [ ] **Step 4: Aggregate without winner selection or voting and activate remaining helpers**

Return every mapping candidate after deterministic sort. Return every validation finding including `NOT_APPLICABLE`; no pass count erases failure. Preserve provider provenance. Activate `mapping_service_fixture()` and `validation_service_with_fail_and_pass()`.

- [ ] **Step 5: Run GREEN and commit**

```bash
PYTHONPATH=platform/semantic_service/src:. pytest -q tests/semantic_service

git add platform/semantic_service/src/semantic_service/service.py \
  tests/semantic_service/test_service_mapping_validation.py tests/semantic_service/helpers.py
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
- Public package exports stable Task 1–6 contracts, not internal hashing/routing helpers.
- Integration proof uses existing D5 `SemanticEnvironmentRef(environment_id, content_hash)` without adding a production dependency in either direction.

- [ ] **Step 1: Add public-surface and import-boundary guard tests**

```python
import ast
from pathlib import Path

import semantic_service as s


def test_public_surface_contains_phase_c_contracts_only():
    required = (
        "SemanticProviderManifest", "SemanticProviderRegistry",
        "SemanticEnvironment", "SemanticEnvironmentStore", "SemanticService",
        "SemanticVocabularyProvider", "SemanticMappingProvider",
        "SemanticValidationProvider", "SemanticProjectionProvider",
    )
    assert [name for name in required if not hasattr(s, name)] == []
    assert not hasattr(s, "NormalizedDesignFactBatch")
    assert not hasattr(s, "McpSemanticProviderAdapter")


def test_semantic_service_has_no_d5_mcp_or_host_imports():
    package = Path(s.__file__).resolve().parent
    forbidden_roots = {"semantic_runtime", "mcp", "fastmcp", "autodesk", "revit", "tekla"}
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

- [ ] **Step 2: Add D5 environment-ref compatibility test with an explicit factory call**

```python
from semantic_runtime import SemanticEnvironmentRef
from semantic_service import ProviderRef, SemanticEnvironmentStore
from tests.semantic_service.helpers import registry_with_ifc


def test_pinned_environment_values_construct_existing_d5_ref():
    registry = registry_with_ifc()
    environment = SemanticEnvironmentStore().pin(
        (ProviderRef("buildingSMART.ifc43", "4.3.2.0"),), registry
    )
    ref = SemanticEnvironmentRef(environment.environment_id, environment.content_hash)
    assert ref.payload() == {
        "environment_id": environment.environment_id,
        "content_hash": environment.content_hash,
    }
```

The test imports both packages; production `semantic_service` does not import D5.

- [ ] **Step 3: Finalize curated `__all__`**

Export stable errors, enums, manifest values, provider DTOs/protocols, registry, environment, and service. Do not export `_hash_payload`, namespace parser, or internal routing helpers.

- [ ] **Step 4: Add dedicated GitHub Actions workflow**

```yaml
name: Semantic service verification

on:
  push:
    branches: ['feat/semantic-service-core']
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

```bash
python -m pip install -e contracts/python -e hosts/autocad/sidecar \
  -e platform/semantic_runtime -e platform/semantic_service
pytest -q tests/semantic_service
pytest -q contracts/python/tests tests/contracts tests/integration \
  tests/orchestrator tests/semantic_runtime tests/semantic_service
```

Expected: focused Semantic Service suite passes; full regression has no new failures. Existing live-AutoCAD-gated skips remain skips unless explicitly enabled.

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

Verify no MCP SDK import, no `semantic_runtime` production import, no Host product branch/mapping, no concrete IFC/Metro provider implementation, no mutable `latest` API, and no `project_facts` payload contract.

- [ ] **Step 2: Verify exact spec coverage**

Map design requirements to tests: immutable registration; capability split; authority conflict; extension coexistence; exact dependency; environment hash determinism; explicit environment-scoped vocabulary routing; selected-only mapping/validation fan-out; provenance preservation; D5 ref compatibility; architecture guard.

- [ ] **Step 3: Obtain fresh GitHub Actions at the final head and record evidence**

Only claim completion after the final PR head SHA has a successful `Semantic service verification` run. Record exact focused/full counts and expected skips in the plan execution record and PR body.

- [ ] **Step 4: Keep PR #6 Draft until implementation review gates pass**

PR #6 remains stacked on `feat/semantic-runtime` while PR #5 is unmerged. After PR #5 merges, retarget PR #6 to `main`, obtain fresh CI on the resulting head/merge ref, and only then mark Ready for review. Do not merge automatically.

- [ ] **Step 5: Commit the execution record after fresh-head verification**

```bash
git add docs/superpowers/plans/2026-08-28-semantic-service-core.md
git commit -m "docs: record Semantic Service core verification"
```

## Implementation Order / Review Gates

Execute Tasks 1 → 8 strictly in order. Tasks 1–7 each use RED → minimal GREEN → focused regression → commit. Do not combine concrete IFC/Metro content or Semantic MCP transport into these commits.

```text
Task 1  Manifest + errors                         RED/GREEN
Task 2  Provider DTOs/protocols + helper API     RED/GREEN
Task 3  Immutable Registry                       RED/GREEN
Task 4  Environment pinning/store                RED/GREEN
Task 5  Vocabulary routing                       RED/GREEN
Task 6  Mapping/validation aggregation           RED/GREEN
Task 7  Public surface + architecture + CI       RED/GREEN
Task 8  Fresh-head closeout                      verification only
```

## Implementation Execution Record

### Execution scope and commit range

Tasks 1–7 were executed inline against `feat/semantic-service-core` after the approved plan head `733cad83968eee9b54864fd052cffb39732b6a1d` and through the code-verification head `9f906a4b3d9e54d3367aa8697267de588cbfebec`.

Because this ChatGPT session wrote repository files through GitHub's Contents API, a logical Task could require multiple file-level commits instead of the plan's ideal one-Task/one-commit shape. This execution record therefore treats `733cad83968eee9b54864fd052cffb39732b6a1d..9f906a4b3d9e54d3367aa8697267de588cbfebec` as the authoritative implementation range rather than inventing synthetic per-Task commit boundaries.

Design/plan anchor commits:

- `d0b2e5472c61122a5ced746076bca5d8401c8b68` — initial Semantic Service Core design.
- `4954fd85ad6e90b8ed6a9c253c3740391e9d10c2` — clarified Registry/EnvironmentStore ownership and pinned-record semantics.
- `47e12955e3d37c13427369ff3d7842355c62498d` — initial implementation plan.
- `733cad83968eee9b54864fd052cffb39732b6a1d` — reviewed/tightened implementation plan and execution baseline.

### Executed gates

| Task | Executed result |
| --- | --- |
| 1 | Package, typed errors, immutable provider manifest and deterministic manifest hash implemented with RED → GREEN verification. |
| 2 | Provider-neutral DTOs, split capability Protocols and explicit test helpers implemented with RED → GREEN verification. |
| 3 | Immutable exact-version Provider Registry and capability conformance implemented with RED → GREEN verification. |
| 4 | Exact-version SemanticEnvironment pinning/store, dependency barrier, namespace authority and content addressing implemented with RED → GREEN verification. |
| 5 | Explicit-environment, AUTHORITATIVE-only vocabulary routing implemented with RED → GREEN verification. |
| 6 | Selected-only deterministic mapping/validation fan-out with provenance preservation and fail-closed provider exceptions implemented with RED → GREEN verification. |
| 7 | Curated public surface, architecture guards, D5 ref compatibility proof and dedicated Semantic Service CI implemented and verified. |
| 8 | Architecture/spec review performed; execution record committed; final document-head CI is intentionally recorded in PR metadata after this commit to avoid a self-referential head change. |

### Closeout findings and fixes

CI and closeout review found four issues before the code-verification head was accepted:

1. The dedicated workflow did not initially put the repository root on the test import path. `PYTHONPATH=.` was added to make `tests.semantic_service.helpers` portable in CI.
2. A YAML/shell continuation made the full-regression path resolve incorrectly. Verification commands were made shell-safe.
3. `tests/semantic_runtime/test_public_surface.py` and the new Semantic Service test initially had the same import basename under the full pytest run. The Semantic Service test was renamed to `test_semantic_service_public_surface.py` without changing its assertions.
4. Closeout architecture review found a real immutable-registration gap: an in-process provider object could mutate `.manifest` after registration and silently drift the meaning of one `(provider_id, version)`. The Registry now stores a frozen registration manifest independently and fails closed if the live provider manifest drifts. A regression test was added before accepting the final code-verification head.

No concrete IFC4.3, DSP Core, Metro or Enterprise semantic implementation was added while fixing these issues.

### Architecture and spec coverage review

Verified at the code-verification head:

- no MCP/FastMCP import in `semantic_service` production code;
- no production import from `semantic_service` to `semantic_runtime`;
- no AutoCAD/Revit/Tekla native branch or enterprise Host mapping in Semantic Service Core;
- no concrete IFC4.3/Metro/Enterprise Provider implementation;
- no mutable `latest` planning API;
- no `NormalizedDesignFactBatch` or `project_facts` payload contract;
- immutable `(provider_id, version)` registration, including post-registration manifest-drift detection;
- split VOCABULARY/MAPPING/VALIDATION/PROJECTION capability contracts;
- fail-closed namespace authority conflicts and allowed EXTENSION coexistence;
- exact provider dependency checks;
- order-independent content-addressed SemanticEnvironment hashing over pinned machine-semantic records;
- explicit `environment_id` vocabulary queries with AUTHORITATIVE-only routing and no EXTENSION fallback;
- mapping/validation fan-out only to providers selected in the pinned environment;
- deterministic candidate/finding ordering with provider provenance preserved;
- no mapping winner selection and no validation majority vote;
- existing D5 `SemanticEnvironmentRef(environment_id, content_hash)` compatibility at the test boundary;
- public-surface and source-import architecture guards.

### Code-verification evidence before the execution-record commit

Code-verification head:

`9f906a4b3d9e54d3367aa8697267de588cbfebec`

PR merge ref checked by GitHub Actions:

`9404373e7b8d1280df14e6c6b82f092679f6be0b`

GitHub Actions evidence:

- workflow: `Semantic service verification`;
- PR run: `33151620198` (run #14);
- job: `98784691279`;
- focused command: `pytest -q tests/semantic_service` → **40 passed**;
- full command: `pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime tests/semantic_service` → **223 passed, 4 skipped**;
- skipped tests are the existing live-AutoCAD gates requiring `AGENT_HOST_TEST=1`: `test_current_selection.py`, `test_move.py`, `test_move_idempotency.py`, and `test_revision_conflict.py`;
- new failures: **0**.

The GitHub Actions Node 20 deprecation warning remains non-failing infrastructure noise and is outside Semantic Service Core scope.

### Final-head recording rule

This document commit necessarily creates a new branch head after the code-verification head above. To avoid an infinite self-reference loop, the exact execution-record commit SHA and its fresh successful `Semantic service verification` run are recorded in PR #6 metadata after this document commit, not by making another document commit.

PR #6 remains Draft and stacked on `feat/semantic-runtime` while PR #5 is unmerged. After PR #5 merges, PR #6 must be retargeted to `main`, receive fresh CI on the resulting head/merge ref, and only then be marked Ready for review. It must not be merged automatically.
