from ifc43_semantic_provider.normalization import normalize_schema_declarations
from ifc43_semantic_provider.source import load_ifc43_source


def records_by_id():
    return {
        item.term_id: item
        for item in normalize_schema_declarations(load_ifc43_source().schema)
    }


def test_entity_and_relationship_are_normalized_with_distinct_kinds():
    records = records_by_id()
    assert records["ifc:IfcWall"].kind == "ENTITY"
    assert records["ifc:IfcRelAggregates"].kind == "RELATIONSHIP"
    assert records["ifc:IfcWall"].machine_schema["supertype"] == "ifc:IfcBuiltElement"


def test_direct_attribute_uses_owner_qualified_identity():
    records = records_by_id()
    attr = records["ifc:IfcWall.PredefinedType"]
    assert attr.kind == "ATTRIBUTE"
    assert attr.machine_schema["owner"] == "ifc:IfcWall"
    assert attr.machine_schema["declared_type"]["kind"] == "NAMED"
    assert attr.machine_schema["declared_type"]["name"] == "ifc:IfcWallTypeEnum"


def test_enum_literals_are_owner_qualified_terms():
    records = records_by_id()
    enum = records["ifc:IfcWallTypeEnum"]
    literal = records["ifc:IfcWallTypeEnum.SOLIDWALL"]
    assert enum.kind == "ENUM"
    assert "ifc:IfcWallTypeEnum.SOLIDWALL" in enum.machine_schema["literals"]
    assert literal.kind == "ENUM_LITERAL"
    assert literal.machine_schema == {
        "owner": "ifc:IfcWallTypeEnum",
        "value": "SOLIDWALL",
    }


def test_select_and_defined_type_are_normalized():
    records = records_by_id()
    assert records["ifc:IfcValue"].kind == "SELECT"
    assert records["ifc:IfcLengthMeasure"].kind == "DEFINED_TYPE"
