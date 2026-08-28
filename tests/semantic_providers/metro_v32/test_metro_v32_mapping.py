from metro_semantic_provider.catalog import build_catalog
from metro_semantic_provider.mapping import find_mappings_for_claim
from metro_semantic_provider.source import load_raw_machine_source
from semantic_service.providers import ProviderProvenance, SemanticClaim


PROVENANCE = ProviderProvenance(
    provider_id="dsp.metro.semantic",
    version="3.2",
    content_hash="a" * 64,
)


def _catalog():
    return build_catalog(load_raw_machine_source())


def test_running_rail_maps_to_ifc_rail():
    results = find_mappings_for_claim(
        _catalog(),
        SemanticClaim(subject="rail-1", canonical_term_id="metro:RunningRail"),
        PROVENANCE,
        "ifc",
    )
    assert [(item.mapping_id, item.target_term_id) for item in results] == [
        ("metro:Mapping.RunningRail.ToIfcRail", "ifc:IfcRail")
    ]
    assert results[0].provenance == PROVENANCE


def test_unfrozen_track_bed_and_clearance_return_no_mapping():
    assert find_mappings_for_claim(
        _catalog(),
        SemanticClaim(subject="b", canonical_term_id="metro:TrackBed"),
        PROVENANCE,
        "ifc",
    ) == ()
    assert find_mappings_for_claim(
        _catalog(),
        SemanticClaim(subject="c", canonical_term_id="metro:ClearanceEnvelope"),
        PROVENANCE,
        "ifc",
    ) == ()


def test_non_metro_or_non_ifc_target_is_not_mapped():
    assert find_mappings_for_claim(
        _catalog(),
        SemanticClaim(subject="x", canonical_term_id="ifc:IfcWall"),
        PROVENANCE,
        "ifc",
    ) == ()
    assert find_mappings_for_claim(
        _catalog(),
        SemanticClaim(subject="x", canonical_term_id="metro:RunningRail"),
        PROVENANCE,
        "dsp",
    ) == ()


def test_default_target_namespace_still_returns_only_active_ifc_mapping():
    results = find_mappings_for_claim(
        _catalog(),
        SemanticClaim(subject="station-1", canonical_term_id="metro:Station"),
        PROVENANCE,
    )
    assert [(item.mapping_id, item.target_term_id) for item in results] == [
        ("metro:Mapping.Station.ToIfcBuilding", "ifc:IfcBuilding")
    ]


def test_missing_canonical_term_is_not_mapped():
    assert find_mappings_for_claim(
        _catalog(),
        SemanticClaim(subject="x"),
        PROVENANCE,
        "ifc",
    ) == ()
