import pytest

from semantic_service import (
    AuthorityMode,
    EnvironmentNotFoundError,
    NamespaceAuthorityError,
    ProviderDependencyError,
    ProviderRef,
    SemanticEnvironmentStore,
)
from tests.semantic_service.helpers import (
    MappingProvider,
    VocabularyProvider,
    all_refs,
    register_all,
    registry_with_ifc_and_enterprise,
    registry_with_ifc_authority_and_metro_extension,
    registry_with_metro_requiring_ifc,
    registry_with_two_ifc_authorities,
)


def _pin_single(provider):
    registry = register_all(provider)
    return SemanticEnvironmentStore().pin(
        (ProviderRef(provider.manifest.provider_id, provider.manifest.version),),
        registry,
    )


def test_pin_is_order_independent_and_content_addressed():
    registry = registry_with_ifc_and_enterprise()
    refs = all_refs(registry)
    store = SemanticEnvironmentStore()
    first = store.pin(refs, registry)
    second = store.pin(tuple(reversed(refs)), registry)
    assert first == second
    assert first.environment_id == f"sem-env:{first.content_hash}"
    assert store.get(first.environment_id) is first
    assert store.get_by_hash(first.content_hash) is first


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


@pytest.mark.parametrize(
    ("baseline", "changed"),
    [
        (
            VocabularyProvider(version="4.3.2.0"),
            VocabularyProvider(version="4.3.2.1"),
        ),
        (
            VocabularyProvider(content_hash="hash-a"),
            VocabularyProvider(content_hash="hash-b"),
        ),
        (
            VocabularyProvider(authority=AuthorityMode.AUTHORITATIVE),
            VocabularyProvider(authority=AuthorityMode.EXTENSION),
        ),
        (
            VocabularyProvider(claim_projection=False),
            VocabularyProvider(claim_projection=True),
        ),
        (
            VocabularyProvider(compatibility=("semantic-service.v1",)),
            VocabularyProvider(compatibility=("semantic-service.v2",)),
        ),
    ],
)
def test_machine_semantic_manifest_changes_change_environment_hash(baseline, changed):
    assert _pin_single(baseline).content_hash != _pin_single(changed).content_hash


def test_dependency_declaration_changes_environment_hash_when_dependency_is_selected():
    ifc_a = VocabularyProvider()
    metro_a = MappingProvider(
        provider_id="dsp.metro.semantic",
        version="3.2",
        namespace="metro",
        authority=AuthorityMode.AUTHORITATIVE,
    )
    registry_a = register_all(ifc_a, metro_a)
    refs = (
        ProviderRef("buildingSMART.ifc43", "4.3.2.0"),
        ProviderRef("dsp.metro.semantic", "3.2"),
    )
    baseline = SemanticEnvironmentStore().pin(refs, registry_a)

    ifc_b = VocabularyProvider()
    metro_b = MappingProvider(
        provider_id="dsp.metro.semantic",
        version="3.2",
        namespace="metro",
        authority=AuthorityMode.AUTHORITATIVE,
        requires=(ProviderRef("buildingSMART.ifc43", "4.3.2.0"),),
    )
    registry_b = register_all(ifc_b, metro_b)
    changed = SemanticEnvironmentStore().pin(refs, registry_b)

    assert baseline.content_hash != changed.content_hash


def test_unknown_environment_lookup_fails_closed():
    store = SemanticEnvironmentStore()
    with pytest.raises(EnvironmentNotFoundError, match="missing"):
        store.get("missing")
