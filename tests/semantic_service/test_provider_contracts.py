import pytest

from semantic_service import (
    ProviderProvenance,
    SemanticMappingProvider,
    SemanticValidationProvider,
    SemanticVocabularyProvider,
    TermSchema,
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


def test_term_schema_is_deeply_immutable():
    schema = TermSchema(
        "ifc:IfcWall",
        {
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        ProviderProvenance("buildingSMART.ifc43", "4.3.2.0", "ifc-hash"),
    )

    with pytest.raises(TypeError):
        schema.schema["new"] = {}
    with pytest.raises(TypeError):
        schema.schema["properties"]["name"]["type"] = "number"
    assert schema.schema["required"] == ("name",)
