from ifc43_semantic_provider.normalization import normalize_pset_qto
from ifc43_semantic_provider.source import load_ifc43_source


def pset_records():
    source = load_ifc43_source()
    return {item.term_id: item for item in normalize_pset_qto(source.psets)}


def test_official_wall_pset_and_qto_exist():
    records = pset_records()
    assert records["ifc:Pset_WallCommon"].kind == "PSET"
    assert records["ifc:Qto_WallBaseQuantities"].kind == "QTO"
    assert "ifc:Pset_WallCommon.FireRating" in records
    assert "ifc:Qto_WallBaseQuantities.Width" in records


def test_project_pset_is_not_part_of_official_ifc_catalog():
    records = pset_records()
    assert "ifc:PsetProj_WallDesign" not in records
    assert not any(term_id.startswith("ifc:PsetProj_") for term_id in records)
    assert not any(term_id.startswith("ifc:QtoProj_") for term_id in records)


def test_pset_member_machine_type_is_preserved():
    records = pset_records()
    load_bearing = records["ifc:Pset_WallCommon.LoadBearing"]
    assert load_bearing.kind == "PSET_PROPERTY"
    assert load_bearing.machine_schema["owner"] == "ifc:Pset_WallCommon"
    assert load_bearing.machine_schema["primary_measure_type"] == "IfcBoolean"
