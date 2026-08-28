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
