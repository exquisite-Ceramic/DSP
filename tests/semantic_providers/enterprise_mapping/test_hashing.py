from copy import deepcopy

from enterprise_mapping_provider.catalog import build_catalog
from enterprise_mapping_provider.source import load_raw_machine_source


def mutable_source():
    return deepcopy(dict(load_raw_machine_source()))


def test_rule_input_order_does_not_change_content_hash():
    payload = mutable_source()
    expected = build_catalog(payload).content_hash
    payload["rules"] = list(reversed(payload["rules"]))
    assert build_catalog(payload).content_hash == expected


def test_machine_semantic_change_changes_content_hash():
    payload = mutable_source()
    expected = build_catalog(payload).content_hash
    payload["rules"][0]["assurance"] = "STANDARD_MAPPED"
    assert build_catalog(payload).content_hash != expected


def test_optional_descriptions_do_not_change_content_hash():
    payload = mutable_source()
    expected = build_catalog(payload).content_hash
    payload["metadata"]["description"] = "human presentation only"
    payload["rules"][0]["description"] = "another human explanation"
    assert build_catalog(payload).content_hash == expected


def test_content_hash_is_lowercase_sha256_hex():
    value = build_catalog(load_raw_machine_source()).content_hash
    assert len(value) == 64
    assert value == value.lower()
    int(value, 16)
