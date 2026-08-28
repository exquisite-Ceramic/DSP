import pytest

from semantic_service import (
    MappingCandidate,
    ProviderProvenance,
    ProviderRef,
    SemanticClaim,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
    SemanticServiceError,
    ValidationFinding,
    ValidationStatus,
)
from tests.semantic_service.helpers import (
    MappingProvider,
    ValidationProvider,
    mapping_service_fixture,
    validation_service_with_fail_and_pass,
)


def test_mapping_uses_only_selected_providers_and_sorts_results():
    service, environment, selected_a, selected_b, unselected = mapping_service_fixture()
    results = service.find_mappings(SemanticClaim(subject="wall-1"), environment.environment_id)
    assert [item.mapping_id for item in results] == ["map-a", "map-b"]
    assert selected_a.calls == 1
    assert selected_b.calls == 1
    assert unselected.calls == 0


def test_mapping_provider_call_order_is_pinned_provider_order():
    service, environment, selected_a, selected_b, _ = mapping_service_fixture()
    service.find_mappings(SemanticClaim(subject="wall-1"), environment.environment_id)
    assert selected_a.call_log == [
        (selected_a.manifest.provider_id, selected_a.manifest.version),
        (selected_b.manifest.provider_id, selected_b.manifest.version),
    ]


def test_mapping_output_sort_uses_mapping_and_provider_provenance():
    shared = []
    provider_b = MappingProvider(provider_id="b.mapping", call_log=shared)
    provider_a = MappingProvider(provider_id="a.mapping", call_log=shared)
    provider_b.mappings = (
        MappingCandidate(
            "same",
            "ifc:IfcWall",
            ProviderProvenance("b.mapping", "1", provider_b.manifest.content_hash),
        ),
    )
    provider_a.mappings = (
        MappingCandidate(
            "same",
            "ifc:IfcWall",
            ProviderProvenance("a.mapping", "1", provider_a.manifest.content_hash),
        ),
    )
    registry = SemanticProviderRegistry()
    registry.register(provider_b)
    registry.register(provider_a)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (ProviderRef("b.mapping", "1"), ProviderRef("a.mapping", "1")),
        registry,
    )
    results = SemanticService(registry, store).find_mappings(
        SemanticClaim(subject="wall-1"), environment.environment_id
    )
    assert [(item.mapping_id, item.provider_id) for item in results] == [
        ("same", "a.mapping"),
        ("same", "b.mapping"),
    ]


def test_validation_preserves_standard_failure_and_domain_pass():
    service, environment = validation_service_with_fail_and_pass()
    findings = service.validate_claim(SemanticClaim(subject="wall-1"), environment.environment_id)
    assert [item.status for item in findings] == [ValidationStatus.FAIL, ValidationStatus.PASS]


def test_validation_preserves_not_applicable():
    provider = ValidationProvider(provider_id="a.validation")
    provider.findings = (
        ValidationFinding(
            "rule-na",
            ValidationStatus.NOT_APPLICABLE,
            ProviderProvenance("a.validation", "1", provider.manifest.content_hash),
        ),
    )
    registry = SemanticProviderRegistry()
    registry.register(provider)
    store = SemanticEnvironmentStore()
    environment = store.pin((ProviderRef("a.validation", "1"),), registry)
    findings = SemanticService(registry, store).validate_claim(
        SemanticClaim(subject="wall-1"), environment.environment_id
    )
    assert [item.status for item in findings] == [ValidationStatus.NOT_APPLICABLE]


def test_provider_exception_aborts_mapping_instead_of_returning_partial_results():
    good = MappingProvider(provider_id="a.mapping")
    good.mappings = (
        MappingCandidate(
            "map-a",
            "ifc:IfcWall",
            ProviderProvenance("a.mapping", "1", good.manifest.content_hash),
        ),
    )
    bad = MappingProvider(provider_id="b.mapping", fail=True)
    registry = SemanticProviderRegistry()
    registry.register(good)
    registry.register(bad)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (ProviderRef("a.mapping", "1"), ProviderRef("b.mapping", "1")),
        registry,
    )

    with pytest.raises(SemanticServiceError, match=r"b\.mapping@1.*RuntimeError"):
        SemanticService(registry, store).find_mappings(
            SemanticClaim(subject="wall-1"), environment.environment_id
        )
    assert good.calls == 1
    assert bad.calls == 1
