"""M3 Task 9 JSON Schema reference-resolution migration boundary."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VALIDATION_TEST = ROOT / "contracts/python/tests/test_normalized_design_fact_schema.py"


def test_schema_validation_path_uses_supported_reference_resolution() -> None:
    """The frozen conformance validation path must not retain the deprecated API."""

    source = SCHEMA_VALIDATION_TEST.read_text(encoding="utf-8")
    assert "RefResolver" not in source
