import pytest

from ifc43_semantic_provider import IFC43_CATALOG
from ifc43_semantic_provider.errors import Ifc43TermNotFoundError

POSITIVE = (
    "ifc:IfcRailway",
    "ifc:IfcRailwayPart",
    "ifc:IfcAlignment",
    "ifc:IfcLinearPlacement",
    "ifc:IfcRail",
    "ifc:IfcTrackElement",
    "ifc:IfcMechanicalFastener",
    "ifc:IfcWall",
    "ifc:IfcSlab",
    "ifc:IfcBeam",
    "ifc:IfcColumn",
    "ifc:IfcOpeningElement",
    "ifc:IfcBorehole",
    "ifc:IfcGeomodel",
    "ifc:IfcGeotechnicalStratum",
    "ifc:IfcDistributionSystem",
    "ifc:IfcDistributionPort",
    "ifc:Pset_WallCommon",
    "ifc:Qto_WallBaseQuantities",
    "ifc:Pset_Stationing",
)

NEGATIVE_ENTITIES = (
    "ifc:IfcTunnel",
    "ifc:IfcTunnelPart",
    "ifc:IfcTrack",
    "ifc:IfcSprinkler",
    "ifc:IfcFanCoilUnit",
    "ifc:IfcPrecastConcreteElement",
)


@pytest.mark.parametrize("term_id", POSITIVE)
def test_metro_reference_positive_ifc_terms_are_official(term_id):
    assert IFC43_CATALOG.get(term_id).term_id == term_id


@pytest.mark.parametrize("term_id", NEGATIVE_ENTITIES)
def test_metro_reference_nonexistent_ifc_entities_are_rejected(term_id):
    with pytest.raises(Ifc43TermNotFoundError):
        IFC43_CATALOG.get(term_id)
