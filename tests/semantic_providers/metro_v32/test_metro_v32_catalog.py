from copy import deepcopy
from types import MappingProxyType

import pytest

from metro_semantic_provider.catalog import build_catalog
from metro_semantic_provider.errors import MetroCatalogBuildError
from metro_semantic_provider.source import load_raw_machine_source


EXPECTED_PROJECT_PSETS = {
    "PsetProj_RailwayIdentity", "PsetProj_SpatialPartition",
    "PsetProj_AlignmentDesign", "PsetProj_HorizontalSegmentDesign",
    "PsetProj_Chainage", "PsetProj_TrackGeometry",
    "PsetProj_RailSpecification", "PsetProj_Turnout",
    "PsetProj_StationIdentity", "PsetProj_SpaceFunction",
    "PsetProj_PlatformScreenDoor", "PsetProj_TunnelSegment",
    "PsetProj_SegmentRing", "PsetProj_SegmentBlock",
    "PsetProj_BoreholeInvestigation", "PsetProj_GeotechnicalStratum",
    "PsetProj_ClearanceEnvelope", "PsetProj_AssetCommon",
    "PsetProj_FanPerformance", "PsetProj_PumpPerformance",
    "PsetProj_SignalOccurrence", "PsetProj_GeometryQuality",
    "PsetProj_CoordinateMetadata", "PsetProj_ObjectIdentity",
    "PsetProj_BuildingElementDesign", "PsetProj_WallDesign",
    "PsetProj_SlabDesign", "PsetProj_StructuralElement",
    "PsetProj_PileDesign", "PsetProj_DoorOperation",
    "PsetProj_WindowPerformance", "PsetProj_VerticalCirculation",
    "PsetProj_FinishSpecification", "PsetProj_OpeningCoordination",
    "PsetProj_EmbeddedItem", "PsetProj_TemporarySupport",
    "PsetProj_JointAndWaterproofing",
}

EXPECTED_INLINE_ONLY = {
    "PsetProj_StationIdentity", "PsetProj_WallDesign", "PsetProj_SlabDesign",
    "PsetProj_PileDesign", "PsetProj_DoorOperation", "PsetProj_WindowPerformance",
    "PsetProj_FinishSpecification", "PsetProj_JointAndWaterproofing",
}


def _mutable_source():
    return deepcopy(dict(load_raw_machine_source()))


def test_source_coverage_is_explicit():
    coverage = load_raw_machine_source()["source_coverage"]
    assert set(coverage["chapter21_project_pset_containers"]) == EXPECTED_PROJECT_PSETS
    assert len(coverage["chapter21_project_pset_containers"]) == 37
    assert coverage["structured_property_rows"] == 236
    assert set(coverage["inline_only_project_psets"]) == EXPECTED_INLINE_ONLY
    assert set(coverage["decision_ids"]) == {f"DEC-{i:02d}" for i in range(1, 11)}
    assert set(coverage["prohibited_entity_names"]) == {
        "IfcTrack", "IfcTunnel", "IfcTunnelPart",
        "IfcSprinkler", "IfcFanCoilUnit", "IfcPrecastConcreteElement",
    }


def test_all_decisions_are_unfrozen_and_queryable():
    catalog = build_catalog(load_raw_machine_source())
    assert {item.state.value for item in catalog.decisions} == {"UNFROZEN"}
    assert {item.decision_id for item in catalog.decisions} == {f"DEC-{i:02d}" for i in range(1, 11)}
    assert catalog.get("metro:Decision.DEC-05").kind == "DECISION"


def test_catalog_records_are_immutable_and_synthetic_rule_terms_are_queryable():
    catalog = build_catalog(load_raw_machine_source())
    assert isinstance(catalog.schema_for("metro:TunnelSegment.ConstructionMethod"), MappingProxyType)
    with pytest.raises(TypeError):
        catalog.schema_for("metro:TunnelSegment.ConstructionMethod")["datatype"] = "ifc:IfcText"
    assert catalog.get("metro:Rule.ProhibitIfcTunnelEntity").kind == "VALIDATION_RULE"


@pytest.mark.parametrize("collection,id_key", [
    ("terms", "term_id"),
    ("mappings", "mapping_id"),
    ("validation_rules", "rule_id"),
    ("decisions", "decision_id"),
])
def test_duplicate_ids_fail_closed(collection, id_key):
    payload = _mutable_source()
    payload[collection] = list(payload[collection])
    payload[collection].append(deepcopy(payload[collection][0]))
    with pytest.raises(MetroCatalogBuildError, match="duplicate"):
        build_catalog(payload)


def test_unknown_normative_class_and_requirement_level_fail_closed():
    payload = _mutable_source()
    payload["terms"] = list(payload["terms"])
    payload["terms"][0] = deepcopy(payload["terms"][0])
    payload["terms"][0]["normative_class"] = "MAGIC"
    with pytest.raises(MetroCatalogBuildError, match="normative"):
        build_catalog(payload)

    payload = _mutable_source()
    index = next(i for i, item in enumerate(payload["terms"]) if item.get("requirement_level"))
    payload["terms"] = list(payload["terms"])
    payload["terms"][index] = deepcopy(payload["terms"][index])
    payload["terms"][index]["requirement_level"] = "MAYBE"
    with pytest.raises(MetroCatalogBuildError, match="requirement"):
        build_catalog(payload)


def test_invalid_active_mapping_and_unknown_source_term_fail_closed():
    payload = _mutable_source()
    payload["mappings"] = list(payload["mappings"])
    payload["mappings"][0] = deepcopy(payload["mappings"][0])
    payload["mappings"][0]["target_term_id"] = "metro:WrongTarget"
    with pytest.raises(MetroCatalogBuildError, match="ACTIVE.*ifc"):
        build_catalog(payload)

    payload = _mutable_source()
    payload["mappings"] = list(payload["mappings"])
    payload["mappings"][0] = deepcopy(payload["mappings"][0])
    payload["mappings"][0]["source_term_id"] = "metro:MissingSource"
    with pytest.raises(MetroCatalogBuildError, match="unknown Metro source"):
        build_catalog(payload)


def test_conflicting_active_mapping_and_invalid_frozen_decision_fail_closed():
    payload = _mutable_source()
    duplicate = deepcopy(payload["mappings"][0])
    duplicate["mapping_id"] = "metro:Mapping.Conflict"
    duplicate["target_term_id"] = "ifc:IfcWall"
    payload["mappings"] = list(payload["mappings"]) + [duplicate]
    with pytest.raises(MetroCatalogBuildError, match="conflicting ACTIVE"):
        build_catalog(payload)

    payload = _mutable_source()
    payload["decisions"] = list(payload["decisions"])
    payload["decisions"][0] = deepcopy(payload["decisions"][0])
    payload["decisions"][0]["state"] = "FROZEN"
    payload["decisions"][0]["selected_option"] = None
    with pytest.raises(MetroCatalogBuildError, match="FROZEN.*selected"):
        build_catalog(payload)
