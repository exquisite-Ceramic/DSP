from __future__ import annotations

import copy

import pytest

from design_fact_contracts import FactKind, ValueType
from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter


EMPTY = {
    "hostInstanceId": "acad-session-1",
    "documentId": "C:/models/demo.dwg",
    "revision": 7,
    "entities": [],
}

ONE_ENTITY = {
    "hostInstanceId": "acad-session-1",
    "documentId": "C:/models/demo.dwg",
    "revision": 7,
    "entities": [
        {
            "nativeId": "A31",
            "nativeKind": "LWPOLYLINE",
            "layer": "A-WALL",
            "bounds": {
                "min": {"x": 0.0, "y": 1.0, "z": 0.0},
                "max": {"x": 10.0, "y": 2.0, "z": 3.0},
            },
        }
    ],
}


def test_empty_snapshot_normalizes_to_empty_batch():
    batch = DesignFactAdapter().normalize_snapshot(EMPTY)
    assert batch.facts == ()


def test_entity_emits_identity_classification_and_bounds_in_stable_order():
    batch = DesignFactAdapter().normalize_snapshot(ONE_ENTITY)

    assert [fact.fact_kind for fact in batch.facts] == [
        FactKind.IDENTITY,
        FactKind.CLASSIFICATION,
        FactKind.BOUNDS,
    ]
    assert [fact.predicate for fact in batch.facts] == [
        "native_kind",
        "layer",
        "geometric_extents",
    ]
    assert [fact.source_revision for fact in batch.facts] == [7, 7, 7]
    assert all(fact.host_ref.host_type == "autocad" for fact in batch.facts)
    assert all(fact.host_ref.host_instance_id == "acad-session-1" for fact in batch.facts)
    assert all(fact.host_ref.document_id == "C:/models/demo.dwg" for fact in batch.facts)
    assert all(fact.subject_native_ref.native_id == "A31" for fact in batch.facts)
    assert all(fact.subject_native_ref.native_kind == "LWPOLYLINE" for fact in batch.facts)


def test_layer_is_native_classification_evidence_not_canonical_mapping():
    batch = DesignFactAdapter().normalize_snapshot(ONE_ENTITY)
    classification = batch.facts[1]

    assert classification.fact_kind is FactKind.CLASSIFICATION
    assert classification.value_type is ValueType.STRING
    assert classification.value == "A-WALL"
    assert classification.source_scheme == "autocad.layer"
    assert classification.source_code == "A-WALL"

    wire = batch.to_dict()
    assert "semantic_id" not in str(wire)
    assert "ifc:IfcWall" not in str(wire)


def test_bounds_remain_json_object_evidence():
    bounds = DesignFactAdapter().normalize_snapshot(ONE_ENTITY).facts[2]

    assert bounds.fact_kind is FactKind.BOUNDS
    assert bounds.value_type is ValueType.OBJECT
    assert bounds.to_dict()["value"] == ONE_ENTITY["entities"][0]["bounds"]
    assert bounds.unit is None
    assert bounds.geometry_ref is None


def test_same_snapshot_revision_has_stable_fact_ids_and_revision_change_changes_them():
    adapter = DesignFactAdapter()
    first = adapter.normalize_snapshot(ONE_ENTITY)
    second = adapter.normalize_snapshot(copy.deepcopy(ONE_ENTITY))

    assert [fact.fact_id for fact in first.facts] == [fact.fact_id for fact in second.facts]
    assert all(len(fact.fact_id) == 64 for fact in first.facts)
    assert all(fact.fact_id == fact.fact_id.lower() for fact in first.facts)

    changed = copy.deepcopy(ONE_ENTITY)
    changed["revision"] = 8
    third = adapter.normalize_snapshot(changed)
    assert [fact.fact_id for fact in first.facts] != [fact.fact_id for fact in third.facts]


def test_producer_and_provenance_are_frozen():
    facts = DesignFactAdapter().normalize_snapshot(ONE_ENTITY).facts

    assert all(fact.producer == "autocad.sidecar.design_fact_adapter.v1" for fact in facts)
    assert all(len(fact.provenance) == 1 for fact in facts)
    assert all(fact.provenance[0].startswith("autocad://acad-session-1/") for fact in facts)
    assert all(fact.provenance[0].endswith("/A31@7") for fact in facts)


@pytest.mark.parametrize(
    ("mutate", "field"),
    [
        (lambda p: p.__setitem__("hostInstanceId", " "), "hostInstanceId"),
        (lambda p: p.__setitem__("documentId", ""), "documentId"),
        (lambda p: p.__setitem__("revision", -1), "revision"),
        (lambda p: p.__setitem__("revision", True), "revision"),
        (lambda p: p.__setitem__("revision", 1.5), "revision"),
        (lambda p: p.__setitem__("entities", {}), "entities"),
        (lambda p: p.__setitem__("extra", 1), "unknown"),
        (lambda p: p["entities"][0].__setitem__("nativeId", ""), "nativeId"),
        (lambda p: p["entities"][0].__setitem__("nativeKind", " "), "nativeKind"),
        (lambda p: p["entities"][0].__setitem__("layer", ""), "layer"),
        (lambda p: p["entities"][0].__setitem__("extra", 1), "unknown"),
        (lambda p: p["entities"][0].__setitem__("bounds", {"min": {}, "max": {}}), "bounds"),
        (lambda p: p["entities"][0]["bounds"]["min"].__setitem__("x", float("inf")), "bounds"),
    ],
)
def test_malformed_snapshots_fail_closed(mutate, field):
    payload = copy.deepcopy(ONE_ENTITY)
    mutate(payload)

    with pytest.raises(ValueError, match=field):
        DesignFactAdapter().normalize_snapshot(payload)
