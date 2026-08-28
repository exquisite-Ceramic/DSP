import pytest

from semantic_service import ProviderProvenance
from dsp_core_semantic_provider import DSP_CORE_CATALOG, DSP_CORE_PROVIDER


def test_every_baseline_term_resolves_with_exact_manifest_provenance():
    expected = ProviderProvenance("dsp.core", "1.0", DSP_CORE_CATALOG.content_hash)
    for definition in DSP_CORE_CATALOG.definitions:
        resolved = DSP_CORE_PROVIDER.resolve_term(definition.term_id)
        assert resolved.term_id == definition.term_id
        assert resolved.kind == definition.kind
        assert resolved.provenance == expected


def test_wall_thickness_schema_contains_machine_semantics_only():
    schema = DSP_CORE_PROVIDER.get_term_schema("dsp:WallThickness")
    assert dict(schema.schema) == {
        "term_id": "dsp:WallThickness",
        "version": "1.0",
        "kind": "PROPERTY",
        "domain": "WALL_LIKE_DESIGN_ELEMENT",
        "range": "NUMBER",
        "unit": "mm",
        "allowed_values": (),
        "constraints": {"minimum_exclusive": 0},
    }
    assert "label" not in schema.schema
    assert "description" not in schema.schema


def test_description_is_presentation_only_and_locale_falls_back_to_canonical():
    result = DSP_CORE_PROVIDER.describe_term("dsp:WallThickness", "zh-CN")
    assert result.term_id == "dsp:WallThickness"
    assert result.text
    assert result.locale is None


def test_lookup_is_exact_and_case_sensitive():
    with pytest.raises(KeyError):
        DSP_CORE_PROVIDER.resolve_term("dsp:wallthickness")
    with pytest.raises(KeyError):
        DSP_CORE_PROVIDER.resolve_term("WallThickness")
