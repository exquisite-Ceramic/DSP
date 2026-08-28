from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = ROOT / "contracts" / "schemas"
VECTOR_DIR = ROOT / "contracts" / "test_vectors" / "normalized_design_fact"
FACT_SCHEMA = SCHEMA_DIR / "normalized-design-fact.schema.json"
BATCH_SCHEMA = SCHEMA_DIR / "normalized-design-fact-batch.schema.json"


def _load(path: Path):
    assert path.exists(), f"Step 18 artifact is missing: {path.relative_to(ROOT)}"
    return json.loads(path.read_text(encoding="utf-8"))


def test_step18_schema_and_vector_artifacts_exist():
    required = [
        FACT_SCHEMA,
        BATCH_SCHEMA,
        VECTOR_DIR / "valid_property.json",
        VECTOR_DIR / "valid_classification.json",
        VECTOR_DIR / "valid_object.json",
        VECTOR_DIR / "valid_empty_batch.json",
        VECTOR_DIR / "invalid_source_pair.json",
        VECTOR_DIR / "invalid_document_mismatch.json",
        VECTOR_DIR / "invalid_value_type.json",
    ]
    missing = [str(path.relative_to(ROOT)) for path in required if not path.exists()]
    assert not missing, f"Step 18 artifacts missing: {missing}"


def test_valid_fact_vectors_conform_to_schema():
    schema = _load(FACT_SCHEMA)
    for name in ["valid_property.json", "valid_classification.json", "valid_object.json"]:
        jsonschema.validate(_load(VECTOR_DIR / name), schema)


def test_valid_empty_batch_conforms_to_schema():
    batch_schema = _load(BATCH_SCHEMA)
    fact_schema = _load(FACT_SCHEMA)
    resolver = jsonschema.RefResolver.from_schema(fact_schema)
    # The batch schema is expected to embed/reference the fact definition in a resolvable way.
    jsonschema.validate(_load(VECTOR_DIR / "valid_empty_batch.json"), batch_schema, resolver=resolver)


def test_schema_rejects_unknown_top_level_property():
    schema = _load(FACT_SCHEMA)
    payload = _load(VECTOR_DIR / "valid_property.json")
    payload["semantic_id"] = "must-not-cross-l1"
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(payload, schema)


def test_schema_rejects_unpaired_source_evidence():
    schema = _load(FACT_SCHEMA)
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(_load(VECTOR_DIR / "invalid_source_pair.json"), schema)
