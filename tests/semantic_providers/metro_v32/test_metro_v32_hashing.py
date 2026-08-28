from copy import deepcopy

from metro_semantic_provider.catalog import build_catalog
from metro_semantic_provider.golden import METRO_V32_GOLDEN_CONTENT_HASH
from metro_semantic_provider.hashing import semantic_content_hash
from metro_semantic_provider.source import load_raw_machine_source


def _mutable_source():
    return deepcopy(dict(load_raw_machine_source()))


def test_repeated_builds_have_identical_hash():
    first = build_catalog(load_raw_machine_source()).content_hash
    second = build_catalog(load_raw_machine_source()).content_hash
    assert first == second
    assert len(first) == 64


def test_reviewed_catalog_matches_golden_hash():
    assert (
        build_catalog(load_raw_machine_source()).content_hash
        == METRO_V32_GOLDEN_CONTENT_HASH
    )


def test_machine_source_record_order_does_not_change_catalog_hash():
    payload = _mutable_source()
    baseline = build_catalog(payload).content_hash
    for key in ("terms", "mappings", "validation_rules", "decisions"):
        payload[key] = list(reversed(payload[key]))
    assert build_catalog(payload).content_hash == baseline


def test_description_and_source_location_do_not_change_catalog_hash():
    payload = _mutable_source()
    baseline = build_catalog(payload).content_hash
    payload["terms"] = list(payload["terms"])
    payload["terms"][0] = deepcopy(payload["terms"][0])
    payload["terms"][0]["description"] = "editorial wording only"
    payload["terms"][0]["source_ref"] = {"section": "moved-section", "line": 999999}
    assert build_catalog(payload).content_hash == baseline


def test_requirement_and_decision_state_change_catalog_hash():
    payload = _mutable_source()
    baseline = build_catalog(payload).content_hash

    requirement_payload = _mutable_source()
    idx = next(i for i, item in enumerate(requirement_payload["terms"]) if item.get("requirement_level") == "P-R")
    requirement_payload["terms"] = list(requirement_payload["terms"])
    requirement_payload["terms"][idx] = deepcopy(requirement_payload["terms"][idx])
    requirement_payload["terms"][idx]["requirement_level"] = "P-M"
    assert build_catalog(requirement_payload).content_hash != baseline

    decision_payload = _mutable_source()
    decision_payload["decisions"] = list(decision_payload["decisions"])
    decision_payload["decisions"][0] = deepcopy(decision_payload["decisions"][0])
    decision_payload["decisions"][0]["state"] = "FROZEN"
    decision_payload["decisions"][0]["selected_option"] = decision_payload["decisions"][0]["options"][0]
    assert build_catalog(decision_payload).content_hash != baseline


def test_canonical_hash_is_mapping_order_independent():
    left = {"b": [2, 1], "a": {"z": 1, "y": 2}}
    right = {"a": {"y": 2, "z": 1}, "b": [2, 1]}
    assert semantic_content_hash(left) == semantic_content_hash(right)
