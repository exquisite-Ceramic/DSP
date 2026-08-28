from semantic_service import (
    AuthorityMode,
    ProviderType,
    SemanticCapability,
    SemanticMappingProvider,
    SemanticValidationProvider,
    SemanticVocabularyProvider,
)

from dsp_core_semantic_provider import DSP_CORE_CATALOG, DSP_CORE_PROVIDER


def test_manifest_is_exact_dsp_core_v1_vocabulary_authority():
    manifest = DSP_CORE_PROVIDER.manifest
    assert manifest.provider_id == "dsp.core"
    assert manifest.provider_type is ProviderType.CORE
    assert manifest.version == "1.0"
    assert manifest.content_hash == DSP_CORE_CATALOG.content_hash
    assert manifest.namespaces == ("dsp",)
    assert manifest.capabilities == frozenset({SemanticCapability.VOCABULARY})
    assert tuple((item.namespace, item.mode) for item in manifest.authority) == (
        ("dsp", AuthorityMode.AUTHORITATIVE),
    )
    assert manifest.compatibility == ()
    assert manifest.requires == ()


def test_unclaimed_mapping_and_validation_capabilities_are_absent_not_stubbed():
    assert isinstance(DSP_CORE_PROVIDER, SemanticVocabularyProvider)
    assert not isinstance(DSP_CORE_PROVIDER, SemanticMappingProvider)
    assert not isinstance(DSP_CORE_PROVIDER, SemanticValidationProvider)
