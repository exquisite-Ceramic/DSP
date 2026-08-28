from dataclasses import replace

from ifc43_semantic_provider.catalog import Ifc43Catalog, build_ifc43_catalog
from ifc43_semantic_provider.golden import EXPECTED_IFC43_CONTENT_HASH
from ifc43_semantic_provider.model import IfcTermRecord
from ifc43_semantic_provider.source import load_ifc43_source


def term(term_id, schema, description="presentation"):
    return IfcTermRecord(term_id, "DEFINED_TYPE", schema, description)


def test_record_order_does_not_change_content_hash():
    a = term("ifc:IfcA", {"underlying": "STRING"})
    b = term("ifc:IfcB", {"underlying": "REAL"})
    forward = Ifc43Catalog("IFC4X3_ADD2", (4, 3, 2, 0), (a, b))
    reverse = Ifc43Catalog("IFC4X3_ADD2", (4, 3, 2, 0), (b, a))
    assert forward.content_hash == reverse.content_hash


def test_presentation_change_does_not_change_content_hash():
    a = term("ifc:IfcA", {"underlying": "STRING"})
    changed = replace(a, description="different presentation")
    original = Ifc43Catalog("IFC4X3_ADD2", (4, 3, 2, 0), (a,))
    presentation = Ifc43Catalog("IFC4X3_ADD2", (4, 3, 2, 0), (changed,))
    assert original.content_hash == presentation.content_hash


def test_machine_change_changes_content_hash():
    a = term("ifc:IfcA", {"underlying": "STRING"})
    changed = term("ifc:IfcA", {"underlying": "REAL"})
    original = Ifc43Catalog("IFC4X3_ADD2", (4, 3, 2, 0), (a,))
    machine_changed = Ifc43Catalog("IFC4X3_ADD2", (4, 3, 2, 0), (changed,))
    assert original.content_hash != machine_changed.content_hash


def test_exact_ifc4320_catalog_matches_reviewed_golden_hash():
    actual = build_ifc43_catalog(load_ifc43_source()).content_hash
    assert actual == EXPECTED_IFC43_CONTENT_HASH
