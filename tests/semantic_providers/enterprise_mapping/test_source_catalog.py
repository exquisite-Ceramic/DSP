from copy import deepcopy

import pytest

from enterprise_mapping_provider.catalog import build_catalog
from enterprise_mapping_provider.errors import EnterpriseCatalogBuildError, EnterpriseSourceError
from enterprise_mapping_provider.model import MatchType
from enterprise_mapping_provider.source import load_raw_machine_source, validate_root_metadata


EXPECTED_METADATA = {
    "provider_id": "dsp.enterprise.mapping",
    "provider_version": "1.0.0",
    "target_ifc_provider_id": "buildingSMART.ifc43",
    "target_ifc_provider_version": "4.3.2.0",
    "target_ifc_schema": "IFC4X3_ADD2",
}
EXPECTED_RULE_IDS = (
    "enterprise.autocad.layer.a-wall-prefix.v1",
    "enterprise.autocad.layer.a-wall.exact.v1",
)


def mutable_source():
    return deepcopy(dict(load_raw_machine_source()))


def test_packaged_source_metadata_and_rule_ids_are_exact():
    payload = load_raw_machine_source()
    assert dict(payload["metadata"]) == EXPECTED_METADATA
    catalog = build_catalog(payload)
    assert tuple(rule.mapping_id for rule in catalog.rules) == EXPECTED_RULE_IDS
    assert [rule.match_type for rule in catalog.rules] == [MatchType.PREFIX, MatchType.EXACT]


def test_catalog_rules_are_immutable_and_sorted_by_mapping_id():
    catalog = build_catalog(load_raw_machine_source())
    assert tuple(rule.mapping_id for rule in catalog.rules) == tuple(
        sorted(rule.mapping_id for rule in catalog.rules)
    )
    with pytest.raises((AttributeError, TypeError)):
        catalog.rules[0].pattern = "OTHER"


def test_source_metadata_validation_fails_closed():
    payload = mutable_source()
    payload["metadata"] = dict(payload["metadata"])
    payload["metadata"]["target_ifc_schema"] = "IFC2X3"
    with pytest.raises(EnterpriseSourceError, match="target_ifc_schema"):
        validate_root_metadata(payload)


def test_source_validation_allows_description_but_rejects_unknown_root_or_metadata_fields():
    payload = mutable_source()
    payload["metadata"] = dict(payload["metadata"])
    payload["metadata"]["description"] = "human presentation only"
    validate_root_metadata(payload)

    payload["metadata"]["unexpected_semantic_field"] = "ignored-without-this-guard"
    with pytest.raises(EnterpriseSourceError, match="unknown metadata"):
        validate_root_metadata(payload)

    payload = mutable_source()
    payload["unexpected_root_field"] = {}
    with pytest.raises(EnterpriseSourceError, match="unknown root"):
        validate_root_metadata(payload)


@pytest.mark.parametrize(
    ("mutate", "pattern"),
    [
        (lambda p: p["rules"].append(deepcopy(p["rules"][0])), "duplicate mapping_id"),
        (lambda p: p["rules"][0].update(source_scheme=" "), "source_scheme"),
        (lambda p: p["rules"][0]["match"].update(pattern=" "), "pattern"),
        (lambda p: p["rules"][0].update(target_term_id=" "), "target_term_id"),
        (lambda p: p["rules"][0]["match"].update(type="REGEX"), "match type"),
        (lambda p: p["rules"][0]["match"].update(case_sensitive="false"), "case_sensitive"),
        (lambda p: p["rules"][0].update(target_term_id="IfcWall"), "namespace:local"),
        (lambda p: p["rules"][0].update(assurance="CERTAIN"), "assurance"),
    ],
)
def test_catalog_rejects_invalid_machine_rules(mutate, pattern):
    payload = mutable_source()
    mutate(payload)
    with pytest.raises(EnterpriseCatalogBuildError, match=pattern):
        build_catalog(payload)


def synthetic_payload(rules):
    return {"metadata": EXPECTED_METADATA.copy(), "rules": rules}


def rule(mapping_id, match_type, pattern, target="ifc:IfcWall", assurance="RULE_DERIVED", case_sensitive=False):
    return {
        "mapping_id": mapping_id,
        "source_scheme": "autocad.layer",
        "match": {
            "type": match_type,
            "pattern": pattern,
            "case_sensitive": case_sensitive,
        },
        "target_term_id": target,
        "assurance": assurance,
    }


@pytest.mark.parametrize(
    "rules",
    [
        [rule("a", "EXACT", "A-WALL", "ifc:IfcWall"), rule("b", "EXACT", "a-wall", "ifc:IfcDoor")],
        [rule("a", "EXACT", "A-WALL-EXT", "ifc:IfcWall"), rule("b", "PREFIX", "A-WALL-", "ifc:IfcDoor")],
        [rule("a", "PREFIX", "A-WALL-", "ifc:IfcWall"), rule("b", "PREFIX", "A-WALL-EXT", "ifc:IfcDoor")],
    ],
)
def test_overlapping_rules_with_different_semantics_fail_closed(rules):
    with pytest.raises(EnterpriseCatalogBuildError, match="overlapping"):
        build_catalog(synthetic_payload(rules))


def test_overlapping_rules_with_same_semantics_are_allowed_for_evidence_retention():
    catalog = build_catalog(
        synthetic_payload(
            [
                rule("a", "EXACT", "A-WALL", "ifc:IfcWall"),
                rule("b", "PREFIX", "A-", "ifc:IfcWall"),
            ]
        )
    )
    assert tuple(item.mapping_id for item in catalog.rules) == ("a", "b")
