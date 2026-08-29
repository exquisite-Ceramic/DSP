from semantic_service import (
    AuthorityMode,
    FACT_PROJECTION_COMPATIBILITY,
    ProviderRef,
    ProviderType,
    SemanticCapability,
)

from enterprise_mapping_provider.provider import ENTERPRISE_MAPPING_PROVIDER


def test_enterprise_mapping_provider_manifest_is_exact():
    manifest = ENTERPRISE_MAPPING_PROVIDER.manifest
    assert manifest.provider_id == "dsp.enterprise.mapping"
    assert manifest.provider_type is ProviderType.ENTERPRISE
    assert manifest.version == "1.0.0"
    assert manifest.namespaces == ("ifc",)
    assert manifest.capabilities == frozenset({SemanticCapability.PROJECTION})
    assert manifest.authority == (
        # provider extends mappings involving IFC but never owns IFC vocabulary meaning
        type(manifest.authority[0])("ifc", AuthorityMode.EXTENSION),
    )
    assert manifest.compatibility == (FACT_PROJECTION_COMPATIBILITY,)
    assert manifest.requires == (ProviderRef("buildingSMART.ifc43", "4.3.2.0"),)
    assert len(manifest.content_hash) == 64
