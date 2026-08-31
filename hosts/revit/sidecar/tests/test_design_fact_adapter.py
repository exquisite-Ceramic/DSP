from __future__ import annotations

import hashlib

from design_fact_contracts import FactKind, ValueType

from revit_sidecar.design_fact_adapter import DesignFactAdapter


def _expected_fact_id(*, fact_kind: FactKind, predicate: str) -> str:
    canonical = "\n".join(
        [
            "revit-design-fact-v1",
            "DOC-REVIT-001",
            "11",
            "wall-unique-id",
            fact_kind.value,
            predicate,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _snapshot() -> dict:
    return {
        "document_id": "DOC-REVIT-001",
        "host_instance_id": "HOST-REVIT-A",
        "source_revision": 11,
        "native_id": "wall-unique-id",
        "native_kind": "Wall",
        "builtin_category": "OST_Walls",
        "wall_thickness_mm": 300.0,
    }


def test_revit_wall_snapshot_emits_exact_minimum_frozen_fact_set() -> None:
    batch = DesignFactAdapter().normalize_snapshot(_snapshot())

    assert len(batch.facts) == 3
    by_kind = {fact.fact_kind: fact for fact in batch.facts}

    identity = by_kind[FactKind.IDENTITY]
    assert identity.fact_id == _expected_fact_id(
        fact_kind=FactKind.IDENTITY,
        predicate="native_kind",
    )
    assert identity.predicate == "native_kind"
    assert identity.value == "Wall"
    assert identity.value_type is ValueType.STRING
    assert identity.subject_native_ref.document_id == "DOC-REVIT-001"
    assert identity.subject_native_ref.native_id == "wall-unique-id"
    assert identity.subject_native_ref.native_kind == "Wall"

    classification = by_kind[FactKind.CLASSIFICATION]
    assert classification.fact_id == _expected_fact_id(
        fact_kind=FactKind.CLASSIFICATION,
        predicate="builtin_category",
    )
    assert classification.predicate == "builtin_category"
    assert classification.source_scheme == "revit.builtin_category"
    assert classification.source_code == "OST_Walls"
    assert classification.value == "OST_Walls"
    assert classification.value_type is ValueType.STRING

    thickness = by_kind[FactKind.PROPERTY]
    assert thickness.fact_id == _expected_fact_id(
        fact_kind=FactKind.PROPERTY,
        predicate="wall_thickness",
    )
    assert thickness.predicate == "wall_thickness"
    assert thickness.source_scheme == "revit.property"
    assert thickness.source_code == "WallType.CompoundStructure.TotalWidth"
    assert thickness.value == 300.0
    assert thickness.value_type is ValueType.NUMBER
    assert thickness.unit == "mm"

    for fact in batch.facts:
        assert fact.producer == "revit.sidecar.design_fact_adapter.v1"
        assert fact.host_ref.host_type == "revit"
        assert fact.host_ref.host_instance_id == "HOST-REVIT-A"
        assert fact.host_ref.document_id == "DOC-REVIT-001"
        assert fact.source_revision == 11


def test_revit_fact_ids_are_deterministic_for_identical_snapshot() -> None:
    adapter = DesignFactAdapter()

    first = adapter.normalize_snapshot(_snapshot())
    second = adapter.normalize_snapshot(_snapshot())

    assert [fact.fact_id for fact in first.facts] == [fact.fact_id for fact in second.facts]
