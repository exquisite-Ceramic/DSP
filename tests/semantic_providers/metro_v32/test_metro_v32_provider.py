import pytest

from semantic_service import (
    AuthorityMode,
    ProviderRef,
    ProviderType,
    SemanticCapability,
    SemanticProviderRegistry,
)

from metro_semantic_provider import (
    METRO_V32_CATALOG,
    METRO_V32_GOLDEN_CONTENT_HASH,
    METRO_V32_PROVIDER,
)
from metro_semantic_provider.errors import MetroTermNotFoundError


def test_manifest_matches_main_spec_v06_metro_provider_identity():
    manifest = METRO_V32_PROVIDER.manifest
    assert manifest.provider_id == "dsp.metro.semantic"
    assert manifest.provider_type is ProviderType.DOMAIN
    assert manifest.version == "3.2"
    assert manifest.content_hash == METRO_V32_CATALOG.content_hash
    assert manifest.namespaces == ("ifc", "metro")
    assert manifest.capabilities == frozenset(
        {
            SemanticCapability.VOCABULARY,
            SemanticCapability.MAPPING,
            SemanticCapability.VALIDATION,
            SemanticCapability.PROJECTION,
        }
    )
    assert {item.namespace: item.mode for item in manifest.authority} == {
        "metro": AuthorityMode.AUTHORITATIVE,
        "ifc": AuthorityMode.EXTENSION,
    }
    assert manifest.requires == (ProviderRef("buildingSMART.ifc43", "4.3.2.0"),)


def test_golden_hash_is_exactly_the_reviewed_catalog_hash():
    assert len(METRO_V32_GOLDEN_CONTENT_HASH) == 64
    assert METRO_V32_CATALOG.content_hash == METRO_V32_GOLDEN_CONTENT_HASH


def test_vocab_resolution_is_exact_case_sensitive_and_carries_provenance():
    resolved = METRO_V32_PROVIDER.resolve_term("metro:RunningRail")
    assert resolved.term_id == "metro:RunningRail"
    assert resolved.kind == "DOMAIN_CONCEPT"
    assert resolved.provenance.provider_id == "dsp.metro.semantic"
    assert resolved.provenance.version == "3.2"
    assert resolved.provenance.content_hash == METRO_V32_CATALOG.content_hash

    for term_id in ("metro:runningrail", "metro:MissingTerm", "ifc:IfcWall"):
        with pytest.raises(MetroTermNotFoundError):
            METRO_V32_PROVIDER.resolve_term(term_id)


def test_mapping_rule_schema_is_queryable_without_expanding_mapping_candidate():
    schema = METRO_V32_PROVIDER.get_term_schema(
        "metro:Mapping.RunningRail.ToIfcRail"
    ).schema
    assert schema["source_term_id"] == "metro:RunningRail"
    assert schema["state"] == "ACTIVE"
    assert schema["target_term_id"] == "ifc:IfcRail"
    assert schema["constraints"][0]["term_id"] == "ifc:IfcRail.PredefinedType"
    assert schema["constraints"][0]["equals"] == "RAIL"


def test_description_locale_falls_back_without_changing_identity():
    described = METRO_V32_PROVIDER.describe_term("metro:RunningRail", "zh-CN")
    assert described.term_id == "metro:RunningRail"
    assert described.locale is None
    assert described.text


def test_provider_delegates_mapping_and_claim_validation():
    from semantic_service import SemanticClaim, ValidationStatus

    mappings = METRO_V32_PROVIDER.find_mappings(
        SemanticClaim(subject="rail-1", canonical_term_id="metro:RunningRail"),
        "ifc",
    )
    assert [(item.mapping_id, item.target_term_id) for item in mappings] == [
        ("metro:Mapping.RunningRail.ToIfcRail", "ifc:IfcRail")
    ]
    assert all(item.provenance.content_hash == METRO_V32_CATALOG.content_hash for item in mappings)

    findings = METRO_V32_PROVIDER.validate_claim(
        SemanticClaim(subject="x", canonical_term_id="ifc:IfcTunnel")
    )
    assert any(
        item.rule_id == "metro:Rule.ProhibitIfcTunnelEntity"
        and item.status is ValidationStatus.FAIL
        for item in findings
    )


def test_registry_accepts_all_claimed_capabilities():
    registry = SemanticProviderRegistry()
    assert registry.register(METRO_V32_PROVIDER) == METRO_V32_PROVIDER.manifest
