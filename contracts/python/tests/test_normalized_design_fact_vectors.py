from __future__ import annotations

import json
from pathlib import Path

import pytest

from design_fact_contracts import NormalizedDesignFact


ROOT = Path(__file__).resolve().parents[3]
VECTOR_DIR = ROOT / "contracts" / "test_vectors" / "normalized_design_fact"


def _vector(name: str) -> dict:
    return json.loads((VECTOR_DIR / name).read_text(encoding="utf-8"))


@pytest.mark.parametrize(
    "name",
    ["valid_property.json", "valid_classification.json", "valid_object.json"],
)
def test_shared_valid_vectors_round_trip_through_python_contract(name: str) -> None:
    payload = _vector(name)
    assert NormalizedDesignFact.from_dict(payload).to_dict() == payload


@pytest.mark.parametrize(
    "name",
    ["invalid_source_pair.json", "invalid_document_mismatch.json", "invalid_value_type.json"],
)
def test_shared_invalid_vectors_are_rejected_by_python_contract(name: str) -> None:
    with pytest.raises(ValueError):
        NormalizedDesignFact.from_dict(_vector(name))


def test_provenance_must_be_an_ordered_array_not_an_object() -> None:
    payload = _vector("valid_property.json")
    payload["provenance"] = {"source": "host-read:A31@7"}

    with pytest.raises(ValueError, match="provenance"):
        NormalizedDesignFact.from_dict(payload)
