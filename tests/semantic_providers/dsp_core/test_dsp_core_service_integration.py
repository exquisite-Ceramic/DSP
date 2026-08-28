from dataclasses import replace

import pytest

from semantic_runtime import AssuranceLevel, FreshnessState
from semantic_service import (
    AuthorityMode,
    NamespaceAuthority,
    NamespaceAuthorityError,
    ProviderProvenance,
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
    changed_terms = tuple(
        replace(term, unit="m") if term.term_id == "dsp:WallThickness" else term
        for term in DSP_CORE_TERMS
    )
    changed_provider = DspCoreSemanticProvider(SemanticTermCatalog(changed_terms))
    _, _, _, baseline_environment = build_service(DSP_CORE_PROVIDER)
    _, _, _, changed_environment = build_service(changed_provider)
    assert baseline_environment.environment_id != changed_environment.environment_id


class OtherDspAuthority:
    def __init__(self) -> None:
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
        self._provenance = ProviderProvenance("other.dsp", "1.0", "other-content")

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def resolve_term(self, term_id: str) -> ResolvedTerm:
        return ResolvedTerm(term_id, "TYPE", self._provenance)

    def describe_term(self, term_id: str, locale: str | None = None) -> TermDescription:
        return TermDescription(term_id, "other", None, self._provenance)

    def get_term_schema(self, term_id: str) -> TermSchema:
        return TermSchema(term_id, {"term_id": term_id}, self._provenance)


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
