import pytest

from semantic_service import (
    AuthorityMode,
    ProviderProvenance,
    SemanticCapability,
    SemanticMappingProvider,
    SemanticProjectionProvider,
    SemanticValidationProvider,
    SemanticVocabularyProvider,
    TermSchema,
)
from tests.semantic_service.helpers import VocabularyProvider, make_manifest


FACTS_V1 = "dsp.semantic.projection-facts.v1"


class FactsV1ProjectionProvider:
    def __init__(self) -> None:
        self._manifest = make_manifest(
            provider_id="acme.projection",
            version="1",
            namespace="ifc",
            authority=AuthorityMode.EXTENSION,
            capabilities=frozenset({SemanticCapability.PROJECTION}),
            compatibility=(FACTS_V1,),
        )

    @property
    def manifest(self):
        return self._manifest

    def project_facts(self, facts):
        return ()


def test_capability_protocols_are_separate():
    provider = VocabularyProvider()
    assert isinstance(provider, SemanticVocabularyProvider)
    assert not isinstance(provider, SemanticMappingProvider)
    assert not isinstance(provider, SemanticValidationProvider)


def test_projection_marker_without_facts_v1_does_not_require_batch_api():
    provider = VocabularyProvider(claim_projection=True)
    assert SemanticCapability.PROJECTION in provider.manifest.capabilities
    assert FACTS_V1 not in provider.manifest.compatibility
    assert not hasattr(provider, "project_facts")


def test_facts_v1_projection_provider_is_runtime_callable_protocol():
    provider = FactsV1ProjectionProvider()
    assert getattr(SemanticProjectionProvider, "_is_runtime_protocol", False)
    assert isinstance(provider, SemanticProjectionProvider)


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
