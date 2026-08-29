import pytest

from design_fact_contracts import (
    DesignFactHostRef,
    FactKind,
    NativeSubjectRef,
    NormalizedDesignFact,
    NormalizedDesignFactBatch,
    ValueType,
)
from enterprise_mapping_provider.errors import EnterpriseProjectionError
from enterprise_mapping_provider.model import EnterpriseMappingCatalog, EnterpriseMappingRule, MatchType
from enterprise_mapping_provider.provider import EnterpriseMappingProvider


def make_fact(
    source_code="A-WALL",
    *,
    fact_id="fact-a31",
    native_id="A31",
    host_type="autocad",
    host_instance_id="session/1",
    document_id="C:/models/Station A.dwg",
    fact_kind=FactKind.CLASSIFICATION,
    source_scheme="autocad.layer",
    predicate="layer",
    value=None,
    provenance=("autocad://source",),
):
    if value is None:
        value = source_code if source_code is not None else "misleading-A-WALL"
    if source_scheme is None:
        source_code = None
    return NormalizedDesignFact(
        fact_id=fact_id,
        producer="test.producer",
        host_ref=DesignFactHostRef(host_type, host_instance_id, document_id),
        source_revision=7,
        subject_native_ref=NativeSubjectRef(document_id, native_id, "LWPOLYLINE"),
        fact_kind=fact_kind,
        predicate=predicate,
        value=value,
        value_type=ValueType.STRING,
        source_scheme=source_scheme,
        source_code=source_code,
        provenance=provenance,
    )


def project(*facts, provider=None):
    provider = provider or EnterpriseMappingProvider()
    return provider.project_facts(NormalizedDesignFactBatch(facts))


@pytest.mark.parametrize("source_code", ["A-WALL", "A-WALL-EXT", "A-WALL-INT", "a-wall-ext"])
def test_a_wall_codes_project_to_ifc_wall(source_code):
    claims = project(make_fact(source_code))
    assert len(claims) == 1
    assert claims[0].canonical_term_id == "ifc:IfcWall"


@pytest.mark.parametrize("source_code", ["A-WALLISH", "X-A-WALL", "WALL-A"])
def test_near_miss_codes_do_not_project(source_code):
    assert project(make_fact(source_code)) == ()


def test_non_matching_scheme_missing_evidence_and_non_classification_are_ignored():
    assert project(make_fact("A-WALL", source_scheme="revit.category")) == ()
    assert project(make_fact(None, source_scheme=None)) == ()
    assert project(make_fact("A-WALL", fact_kind=FactKind.IDENTITY)) == ()


def test_projection_uses_structured_source_evidence_not_predicate_value_or_provenance_text():
    fact = make_fact(
        "NOT-WALL",
        predicate="autocad.layer",
        value="A-WALL",
        provenance=("autocad.layer:A-WALL",),
    )
    assert project(fact) == ()


def test_matching_claim_shape_evidence_provenance_and_subject_locator_are_exact():
    fact = make_fact("A-WALL-EXT")
    claim = project(fact)[0]
    assert claim.subject == "native://autocad/session%2F1/C%3A%2Fmodels%2FStation%20A.dwg/A31"
    assert claim.predicate == "classification"
    assert claim.canonical_term_id == "ifc:IfcWall"
    assert claim.value is None
    assert claim.unit is None
    assert claim.assurance == "RULE_DERIVED"
    assert claim.provenance == ("autocad://source",)
    assert claim.evidence == (
        "design-fact:fact-a31",
        "mapping:enterprise.autocad.layer.a-wall-prefix.v1",
    )
    assert claim.provider_id == "dsp.enterprise.mapping"
    assert claim.provider_version == "1.0.0"
    assert "SemanticId" not in claim.subject


def test_projection_is_sorted_by_subject_mapping_id_fact_id_not_input_order():
    facts = (
        make_fact("A-WALL-EXT", fact_id="z", native_id="B20"),
        make_fact("A-WALL", fact_id="a", native_id="A10"),
    )
    claims = project(*facts)
    assert [claim.subject.rsplit("/", 1)[-1] for claim in claims] == ["A10", "B20"]


def synthetic_rule(mapping_id, match_type, pattern, target="ifc:IfcWall", assurance="RULE_DERIVED"):
    return EnterpriseMappingRule(
        mapping_id=mapping_id,
        source_scheme="autocad.layer",
        match_type=match_type,
        pattern=pattern,
        case_sensitive=False,
        target_term_id=target,
        assurance=assurance,
    )


def test_same_semantics_overlapping_rules_keep_separate_mapping_evidence():
    catalog = EnterpriseMappingCatalog(
        metadata={},
        rules=(
            synthetic_rule("prefix", MatchType.PREFIX, "A-"),
            synthetic_rule("exact", MatchType.EXACT, "A-WALL"),
        ),
        content_hash="a" * 64,
    )
    claims = project(make_fact("A-WALL"), provider=EnterpriseMappingProvider(catalog))
    assert [claim.evidence[1] for claim in claims] == ["mapping:exact", "mapping:prefix"]


def test_runtime_conflicting_matches_fail_closed_instead_of_using_rule_order():
    catalog = EnterpriseMappingCatalog(
        metadata={},
        rules=(
            synthetic_rule("wall", MatchType.PREFIX, "A-", target="ifc:IfcWall"),
            synthetic_rule("door", MatchType.EXACT, "A-WALL", target="ifc:IfcDoor"),
        ),
        content_hash="b" * 64,
    )
    with pytest.raises(EnterpriseProjectionError, match="conflicting"):
        project(make_fact("A-WALL"), provider=EnterpriseMappingProvider(catalog))
