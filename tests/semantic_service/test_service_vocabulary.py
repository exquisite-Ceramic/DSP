import pytest

from semantic_service import (
    AuthorityMode,
    NamespaceAuthorityError,
    ProviderCapabilityError,
    ProviderRef,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
    TermResolutionError,
)
from tests.semantic_service.helpers import (
    MappingProvider,
    VocabularyProvider,
    service_with_ifc_authority_and_extension,
    service_with_ifc_extension_only,
)


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


def test_authority_without_vocabulary_capability_fails_closed():
    provider = MappingProvider(
        provider_id="acme.ifc.mapping",
        version="1",
        namespace="ifc",
        authority=AuthorityMode.AUTHORITATIVE,
    )
    registry = SemanticProviderRegistry()
    registry.register(provider)
    store = SemanticEnvironmentStore()
    environment = store.pin((ProviderRef("acme.ifc.mapping", "1"),), registry)
    service = SemanticService(registry, store)

    with pytest.raises(ProviderCapabilityError, match="VOCABULARY"):
        service.resolve_term("ifc:IfcWall", environment.environment_id)


def test_malformed_term_id_fails_before_provider_call():
    service, authoritative, _, environment = service_with_ifc_authority_and_extension()
    with pytest.raises(TermResolutionError, match="namespace:local"):
        service.resolve_term("IfcWall", environment.environment_id)
    assert authoritative.resolve_calls == []


def test_provider_exception_is_wrapped_with_provider_provenance():
    provider = VocabularyProvider(fail_resolve=True)
    registry = SemanticProviderRegistry()
    registry.register(provider)
    store = SemanticEnvironmentStore()
    environment = store.pin((ProviderRef("buildingSMART.ifc43", "4.3.2.0"),), registry)
    service = SemanticService(registry, store)

    with pytest.raises(
        TermResolutionError,
        match=r"buildingSMART\.ifc43@4\.3\.2\.0.*RuntimeError",
    ):
        service.resolve_term("ifc:IfcWall", environment.environment_id)


def test_describe_and_schema_use_same_pinned_authority():
    service, authoritative, extension, environment = service_with_ifc_authority_and_extension()
    description = service.describe_term("ifc:IfcWall", environment.environment_id, locale="en")
    schema = service.get_term_schema("ifc:IfcWall", environment.environment_id)
    assert description.term_id == schema.term_id == "ifc:IfcWall"
    assert authoritative.describe_calls == [("ifc:IfcWall", "en")]
    assert authoritative.schema_calls == ["ifc:IfcWall"]
    assert extension.describe_calls == []
    assert extension.schema_calls == []
