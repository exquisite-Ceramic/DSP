from __future__ import annotations

import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = ROOT / "contracts" / "schemas"
VECTOR_DIR = ROOT / "contracts" / "test_vectors" / "normalized_design_fact"
FACT_SCHEMA = SCHEMA_DIR / "normalized-design-fact.schema.json"
BATCH_SCHEMA = SCHEMA_DIR / "normalized-design-fact-batch.schema.json"


def _load(path: Path):
    assert path.exists(), f"Step 18 artifact is missing: {path.relative_to(ROOT)}"
    return json.loads(path.read_text(encoding="utf-8"))


def _registry_for(schema: dict) -> Registry:
    """Register the existing canonical resource by its declared $id."""

    return Registry().with_resource(schema["$id"], Resource.from_contents(schema))


def _validate_batch_with_registry(payload: dict) -> None:
    batch_schema = _load(BATCH_SCHEMA)
    fact_schema = _load(FACT_SCHEMA)
    jsonschema.validate(
        payload,
        batch_schema,
        registry=_registry_for(fact_schema),
    )


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
    _validate_batch_with_registry(_load(VECTOR_DIR / "valid_empty_batch.json"))


def test_fact_schema_local_ref_success_is_characterized():
    """A valid fact traverses the schema's local host/native reference definitions."""

    jsonschema.validate(_load(VECTOR_DIR / "valid_property.json"), _load(FACT_SCHEMA))


def test_batch_external_then_local_nested_ref_success_is_characterized():
    """Batch -> fact schema -> local definitions must remain resolvable after migration."""

    _validate_batch_with_registry({"facts": [_load(VECTOR_DIR / "valid_property.json")]})


def test_missing_ref_failure_shape_is_characterized():
    """An unresolved local reference fails as resolution, not instance validation."""

    schema = {
        "$schema": "http://json-schema.org/draft-07/schema#",
        "$id": "urn:dsp:task9:missing-ref",
        "definitions": {},
        "$ref": "#/definitions/missing",
    }

    with pytest.raises(Exception) as exc_info:
        jsonschema.validate({}, schema, registry=_registry_for(schema))

    error = exc_info.value
    assert not isinstance(error, (jsonschema.ValidationError, jsonschema.SchemaError))
    assert "definitions/missing" in str(error)


def test_invalid_instance_through_external_ref_keeps_validation_error_shape():
    """Resolver migration must preserve the public ValidationError path/keyword shape."""

    with pytest.raises(jsonschema.ValidationError) as exc_info:
        _validate_batch_with_registry(
            {"facts": [_load(VECTOR_DIR / "invalid_source_pair.json")]}
        )

    error = exc_info.value
    assert list(error.absolute_path)[:2] == ["facts", 0]
    assert error.validator == "type"


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
