import pytest

from semantic_service import (
    MappingCandidate,
    ProviderProvenance,
    ProviderRef,
    ResolvedTerm,
    SemanticClaim,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
    SemanticServiceError,
    ValidationFinding,
    ValidationStatus,
)
from tests.semantic_service.helpers import MappingProvider, ValidationProvider, VocabularyProvider


class ForgedVocabularyProvider(VocabularyProvider):
    def resolve_term(self, term_id: str) -> ResolvedTerm:
        self.resolve_calls.append(term_id)
        return ResolvedTerm(
            term_id,
            "TERM",
            ProviderProvenance("forged.provider", "9", "forged-hash"),
        )


def _service_for(provider):
    registry = SemanticProviderRegistry()
    registry.register(provider)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (ProviderRef(provider.manifest.provider_id, provider.manifest.version),),
        registry,
    )
    return SemanticService(registry, store), environment


def test_vocabulary_result_provenance_must_match_pinned_provider():
    service, environment = _service_for(ForgedVocabularyProvider())

    with pytest.raises(SemanticServiceError, match="provenance mismatch"):
        service.resolve_term("ifc:IfcWall", environment.environment_id)


def test_mapping_result_provenance_must_match_pinned_provider():
    provider = MappingProvider(provider_id="a.mapping")
    provider.mappings = (
        MappingCandidate(
            "map-a",
            "ifc:IfcWall",
            ProviderProvenance("forged.provider", "9", "forged-hash"),
        ),
    )
    service, environment = _service_for(provider)

    with pytest.raises(SemanticServiceError, match="provenance mismatch"):
        service.find_mappings(SemanticClaim(subject="wall-1"), environment.environment_id)


def test_validation_result_provenance_must_match_pinned_provider():
    provider = ValidationProvider(provider_id="a.validation")
    provider.findings = (
        ValidationFinding(
            "rule-a",
            ValidationStatus.PASS,
            ProviderProvenance("forged.provider", "9", "forged-hash"),
        ),
    )
    service, environment = _service_for(provider)

    with pytest.raises(SemanticServiceError, match="provenance mismatch"):
        service.validate_claim(SemanticClaim(subject="wall-1"), environment.environment_id)
