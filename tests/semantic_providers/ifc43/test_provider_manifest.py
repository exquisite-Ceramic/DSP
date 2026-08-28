from semantic_service import (
    AuthorityMode,
    ProviderType,
    SemanticCapability,
    SemanticProviderRegistry,
)

from ifc43_semantic_provider import IFC43_CATALOG, IFC43_PROVIDER
from ifc43_semantic_provider.errors import Ifc43TermNotFoundError


def test_manifest_matches_main_spec_v06_ifc_provider_identity():
    manifest = IFC43_PROVIDER.manifest
    assert manifest.provider_id == "buildingSMART.ifc43"
    assert manifest.provider_type is ProviderType.STANDARD
    assert manifest.version == "4.3.2.0"
    assert manifest.content_hash == IFC43_CATALOG.content_hash
    assert manifest.namespaces == ("ifc",)
    assert manifest.capabilities == frozenset(
        {
            SemanticCapability.VOCABULARY,
            SemanticCapability.VALIDATION,
            SemanticCapability.PROJECTION,
        }
    )
    assert len(manifest.authority) == 1
    assert manifest.authority[0].namespace == "ifc"
    assert manifest.authority[0].mode is AuthorityMode.AUTHORITATIVE
    assert manifest.requires == ()


def test_vocab_results_carry_exact_pinned_provenance():
    resolved = IFC43_PROVIDER.resolve_term("ifc:IfcWall")
    assert resolved.term_id == "ifc:IfcWall"
    assert resolved.kind == "ENTITY"
    assert resolved.provenance.provider_id == "buildingSMART.ifc43"
    assert resolved.provenance.version == "4.3.2.0"
    assert resolved.provenance.content_hash == IFC43_CATALOG.content_hash


def test_entity_enum_pset_and_qto_schema_shapes_are_exposed():
    wall = IFC43_PROVIDER.get_term_schema("ifc:IfcWall").schema
    enum = IFC43_PROVIDER.get_term_schema("ifc:IfcWallTypeEnum").schema
    pset = IFC43_PROVIDER.get_term_schema("ifc:Pset_WallCommon").schema
    qto = IFC43_PROVIDER.get_term_schema("ifc:Qto_WallBaseQuantities").schema
    assert "ifc:IfcWall.PredefinedType" in wall["direct_members"]
    assert "ifc:IfcRoot.Name" in wall["inherited_members"]
    assert "ifc:IfcWallTypeEnum.SOLIDWALL" in enum["literals"]
    assert "ifc:Pset_WallCommon.FireRating" in pset["members"]
    assert "ifc:Qto_WallBaseQuantities.Width" in qto["members"]


def test_description_locale_falls_back_without_changing_identity():
    described = IFC43_PROVIDER.describe_term("ifc:IfcWall", "zh-CN")
    assert described.term_id == "ifc:IfcWall"
    assert described.locale is None
    assert described.text


def test_provider_does_not_claim_mapping_or_concrete_projection_method():
    assert SemanticCapability.MAPPING not in IFC43_PROVIDER.manifest.capabilities
    assert not hasattr(IFC43_PROVIDER, "find_mappings")
    assert not hasattr(IFC43_PROVIDER, "project_facts")


def test_invalid_case_nonexistent_and_project_terms_fail_exactly():
    for term_id in ("ifc:ifcwall", "ifc:IfcTunnel", "ifc:PsetProj_WallDesign"):
        try:
            IFC43_PROVIDER.resolve_term(term_id)
        except Ifc43TermNotFoundError:
            continue
        raise AssertionError(f"unexpected resolution: {term_id}")


def test_registry_accepts_all_claimed_capabilities_after_validation_exists():
    registry = SemanticProviderRegistry()
    assert registry.register(IFC43_PROVIDER) == IFC43_PROVIDER.manifest
