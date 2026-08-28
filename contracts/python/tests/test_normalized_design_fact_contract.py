from __future__ import annotations

import importlib
import importlib.util

import pytest


def _contract_module():
    spec = importlib.util.find_spec("design_fact_contracts")
    assert spec is not None, "Step 18 design_fact_contracts package is missing"
    return importlib.import_module("design_fact_contracts")


def _valid_fact_payload() -> dict:
    return {
        "fact_id": "fact-001",
        "producer": "autocad.semantic-adapter",
        "host_ref": {
            "host_type": "AUTOCAD",
            "host_instance_id": "acad-1",
            "document_id": "doc-1",
        },
        "source_revision": 7,
        "subject_native_ref": {
            "document_id": "doc-1",
            "native_id": "A31",
            "native_kind": "LWPOLYLINE",
        },
        "fact_kind": "CLASSIFICATION",
        "predicate": "layer",
        "value": "A-WALL",
        "value_type": "STRING",
        "unit": None,
        "geometry_ref": None,
        "source_scheme": "autocad.layer",
        "source_code": "A-WALL",
        "provenance": ["host-read:A31@7"],
    }


def test_public_api_round_trips_classification_evidence_without_semantic_identity():
    contract = _contract_module()
    fact = contract.NormalizedDesignFact.from_dict(_valid_fact_payload())

    assert fact.to_dict() == _valid_fact_payload()
    assert "semantic_id" not in fact.to_dict()
    assert fact.source_code == "A-WALL"


def test_rejects_mismatched_document_identity():
    contract = _contract_module()
    payload = _valid_fact_payload()
    payload["subject_native_ref"] = dict(payload["subject_native_ref"], document_id="other-doc")

    with pytest.raises(ValueError, match="document"):
        contract.NormalizedDesignFact.from_dict(payload)


def test_rejects_unpaired_source_classification_evidence():
    contract = _contract_module()
    payload = _valid_fact_payload()
    payload["source_code"] = None

    with pytest.raises(ValueError, match="source_scheme|source_code"):
        contract.NormalizedDesignFact.from_dict(payload)


@pytest.mark.parametrize(
    ("value", "value_type"),
    [
        ("3", "INTEGER"),
        (1, "STRING"),
        (True, "NUMBER"),
        ({"x": 1}, "ARRAY"),
    ],
)
def test_rejects_value_type_mismatch(value, value_type):
    contract = _contract_module()
    payload = _valid_fact_payload()
    payload["value"] = value
    payload["value_type"] = value_type

    with pytest.raises(ValueError, match="value_type|value"):
        contract.NormalizedDesignFact.from_dict(payload)


def test_batch_round_trip_accepts_empty_facts():
    contract = _contract_module()
    batch = contract.NormalizedDesignFactBatch.from_dict({"facts": []})
    assert batch.to_dict() == {"facts": []}
