from ifc43_semantic_provider.catalog import build_ifc43_catalog
from ifc43_semantic_provider.source import load_ifc43_source


def catalog():
    return build_ifc43_catalog(load_ifc43_source())


def test_inherited_name_keeps_ifcroot_owner_identity():
    current = catalog()
    wall = current.schema_for("ifc:IfcWall")
    assert "ifc:IfcRoot.Name" in wall["inherited_members"]
    assert "ifc:IfcWall.Name" not in current.term_ids


def test_lookup_is_exact_and_case_sensitive():
    current = catalog()
    assert current.get("ifc:IfcWall").term_id == "ifc:IfcWall"
    for invalid in ("ifc:ifcwall", "IFC:IfcWall", "ifc:IfcTunnel"):
        assert invalid not in current.term_ids
