import pytest

from semantic_service import (
    AuthorityMode,
    NamespaceAuthority,
    NamespaceAuthorityError,
    ProviderRef,
    ProviderRegistrationConflictError,
    ProviderType,
    SemanticCapability,
    SemanticEnvironmentStore,
    SemanticProviderManifest,
    SemanticProviderRegistry,
    SemanticService,
)
from dsp_core_semantic_provider import DSP_CORE_PROVIDER
from ifc43_semantic_provider import IFC43_PROVIDER

IFC_REF = ProviderRef("buildingSMART.ifc43", "4.3.2.0")
DSP_REF = ProviderRef("dsp.core", "1.0")


def build_service():
    registry = SemanticProviderRegistry()
    registry.register(DSP_CORE_PROVIDER)
    registry.register(IFC43_PROVIDER)
    store = SemanticEnvironmentStore()
    environment = store.pin((DSP_REF, IFC_REF), registry)
    return SemanticService(registry, store), environment, registry, store


def test_service_resolves_ifc_term_through_exact_authoritative_owner():
    service, environment, _, _ = build_service()
    result = service.resolve_term("ifc:IfcWall", environment.environment_id)
    assert result.term_id == "ifc:IfcWall"
    assert result.provenance.provider_id == "buildingSMART.ifc43"


def test_environment_pins_exact_ifc_version_and_repin_is_idempotent():
    _, environment, registry, store = build_service()
    again = store.pin((IFC_REF, DSP_REF), registry)
    assert again == environment
    pinned = next(
        item for item in environment.providers if item.provider_id == "buildingSMART.ifc43"
    )
    assert pinned.version == "4.3.2.0"
    assert pinned.content_hash == IFC43_PROVIDER.manifest.content_hash


class ConflictingIfcOwner:
    manifest = SemanticProviderManifest(
        provider_id="test.conflicting-ifc",
        provider_type=ProviderType.DOMAIN,
        version="1",
        content_hash="conflict",
        namespaces=("ifc",),
        capabilities=frozenset({SemanticCapability.VOCABULARY}),
        authority=(NamespaceAuthority("ifc", AuthorityMode.AUTHORITATIVE),),
        compatibility=(),
        requires=(),
    )

    def resolve_term(self, term_id):
        raise AssertionError("must never route")

    def describe_term(self, term_id, locale=None):
        raise AssertionError("must never route")

    def get_term_schema(self, term_id):
        raise AssertionError("must never route")


def test_second_authoritative_ifc_owner_fails_environment_pinning():
    _, _, registry, store = build_service()
    registry.register(ConflictingIfcOwner())
    with pytest.raises(NamespaceAuthorityError, match="multiple AUTHORITATIVE"):
        store.pin((IFC_REF, ProviderRef("test.conflicting-ifc", "1")), registry)


class ConflictingSameVersion:
    manifest = SemanticProviderManifest(
        provider_id="buildingSMART.ifc43",
        provider_type=ProviderType.STANDARD,
        version="4.3.2.0",
        content_hash="different-machine-semantics",
        namespaces=("ifc",),
        capabilities=frozenset(),
        authority=(),
        compatibility=(),
        requires=(),
    )


def test_same_provider_version_with_different_content_fails_closed():
    registry = SemanticProviderRegistry()
    registry.register(IFC43_PROVIDER)
    with pytest.raises(
        ProviderRegistrationConflictError,
        match="immutable provider version conflict",
    ):
        registry.register(ConflictingSameVersion())
