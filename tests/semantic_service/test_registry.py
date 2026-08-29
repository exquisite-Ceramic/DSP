from dataclasses import replace

import pytest

from semantic_service import (
    AuthorityMode,
    ProviderCapabilityError,
    ProviderNotFoundError,
    ProviderRegistrationConflictError,
    SemanticCapability,
    SemanticProviderRegistry,
)
from tests.semantic_service.helpers import VocabularyProvider, make_manifest


FACTS_V1 = "dsp.semantic.projection-facts.v1"


class InvalidManifestProvider:
    @property
    def manifest(self):
        return object()


class FactsCompatibilityWithoutProjection:
    def __init__(self) -> None:
        self._manifest = make_manifest(
            provider_id="acme.bad.compatibility",
            version="1",
            namespace="ifc",
            authority=AuthorityMode.EXTENSION,
            capabilities=frozenset(),
            compatibility=(FACTS_V1,),
        )

    @property
    def manifest(self):
        return self._manifest


class FactsV1WithoutMethod:
    def __init__(self) -> None:
        self._manifest = make_manifest(
            provider_id="acme.bad.projection",
            version="1",
            namespace="ifc",
            authority=AuthorityMode.EXTENSION,
            capabilities=frozenset({SemanticCapability.PROJECTION}),
            compatibility=(FACTS_V1,),
        )

    @property
    def manifest(self):
        return self._manifest


class FactsV1ProjectionProvider(FactsV1WithoutMethod):
    def __init__(self) -> None:
        super().__init__()
        self._manifest = replace(
            self._manifest,
            provider_id="acme.good.projection",
        )

    def project_facts(self, facts):
        return ()


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


def test_projection_marker_without_facts_v1_remains_registerable():
    registry = SemanticProviderRegistry()
    provider = VocabularyProvider(claim_projection=True)
    assert registry.register(provider) == provider.manifest


def test_facts_v1_compatibility_requires_projection_capability():
    registry = SemanticProviderRegistry()
    with pytest.raises(ProviderCapabilityError, match="PROJECTION"):
        registry.register(FactsCompatibilityWithoutProjection())


def test_facts_v1_projection_requires_callable_protocol():
    registry = SemanticProviderRegistry()
    with pytest.raises(ProviderCapabilityError, match="PROJECTION"):
        registry.register(FactsV1WithoutMethod())


def test_facts_v1_projection_provider_registers():
    registry = SemanticProviderRegistry()
    provider = FactsV1ProjectionProvider()
    assert registry.register(provider) == provider.manifest


def test_invalid_manifest_object_is_rejected_with_typed_error():
    registry = SemanticProviderRegistry()
    with pytest.raises(ProviderCapabilityError, match="manifest"):
        registry.register(InvalidManifestProvider())


def test_missing_exact_provider_raises_provider_not_found():
    registry = SemanticProviderRegistry()
    with pytest.raises(ProviderNotFoundError, match="missing@1"):
        registry.get("missing", "1")


def test_versions_are_sorted_deterministically():
    registry = SemanticProviderRegistry()
    registry.register(VocabularyProvider(version="2"))
    registry.register(VocabularyProvider(version="1"))
    assert registry.versions("buildingSMART.ifc43") == ("1", "2")


def test_multiple_versions_of_one_provider_coexist():
    registry = SemanticProviderRegistry()
    first = VocabularyProvider(version="1", content_hash="hash-1")
    second = VocabularyProvider(version="2", content_hash="hash-2")
    registry.register(first)
    registry.register(second)
    assert registry.get(first.manifest.provider_id, "1") is first
    assert registry.get(second.manifest.provider_id, "2") is second


def test_registered_manifest_is_frozen_even_if_provider_object_drifts():
    registry = SemanticProviderRegistry()
    provider = VocabularyProvider(content_hash="hash-a")
    frozen = registry.register(provider)
    provider._manifest = replace(provider.manifest, content_hash="hash-b")

    assert registry.get_manifest(frozen.provider_id, frozen.version) == frozen
    with pytest.raises(ProviderRegistrationConflictError, match="drift"):
        registry.get(frozen.provider_id, frozen.version)
