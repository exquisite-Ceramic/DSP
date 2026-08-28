from dataclasses import replace

import pytest

from dsp_core_semantic_provider.catalog import (
    DSP_CORE_CATALOG,
    DSP_CORE_TERMS,
    SemanticTermCatalog,
)

EXPECTED_IDS = (
    "dsp:Assurance",
    "dsp:ChangeSet",
    "dsp:ExternalIdentity",
    "dsp:Freshness",
    "dsp:HostBinding",
    "dsp:SemanticIdentity",
    "dsp:Snapshot",
    "dsp:WallThickness",
)


def test_catalog_contains_exact_spec_v06_baseline():
    assert tuple(term.term_id for term in DSP_CORE_CATALOG.definitions) == EXPECTED_IDS
    assert len(DSP_CORE_TERMS) == 8


def test_duplicate_term_ids_are_rejected():
    term = DSP_CORE_TERMS[0]
    with pytest.raises(ValueError, match="duplicate term_id"):
        SemanticTermCatalog((term, term))


def test_insertion_order_does_not_change_content_hash():
    forward = SemanticTermCatalog(DSP_CORE_TERMS)
    reverse = SemanticTermCatalog(tuple(reversed(DSP_CORE_TERMS)))
    assert forward.content_hash == reverse.content_hash


def test_presentation_only_changes_do_not_change_content_hash():
    baseline = DSP_CORE_TERMS[0]
    changed = replace(
        baseline,
        label=baseline.label + " presentation",
        description=baseline.description + " presentation",
    )
    original = SemanticTermCatalog((baseline,))
    presentation_only = SemanticTermCatalog((changed,))
    assert original.content_hash == presentation_only.content_hash


def test_machine_semantic_change_changes_content_hash():
    baseline = next(term for term in DSP_CORE_TERMS if term.term_id == "dsp:WallThickness")
    changed = replace(baseline, unit="m")
    assert SemanticTermCatalog((baseline,)).content_hash != SemanticTermCatalog((changed,)).content_hash


def test_catalog_and_constraints_are_immutable():
    term = next(term for term in DSP_CORE_TERMS if term.term_id == "dsp:HostBinding")
    with pytest.raises(TypeError):
        term.constraints["required"] = ("native_id",)
