import pytest

from metro_semantic_provider.catalog import build_catalog
from metro_semantic_provider.source import load_raw_machine_source
from metro_semantic_provider.validation import validate_claim_against_metro
from semantic_service.providers import (
    ProviderProvenance,
    SemanticClaim,
    ValidationStatus,
)


PROVENANCE = ProviderProvenance(
    provider_id="dsp.metro.semantic",
    version="3.2",
    content_hash="b" * 64,
)


def _catalog():
    return build_catalog(load_raw_machine_source())


def _validate(claim: SemanticClaim):
    return validate_claim_against_metro(_catalog(), claim, PROVENANCE)


def test_construction_method_enum_pass_and_fail():
    good = _validate(
        SemanticClaim(
            subject="s",
            canonical_term_id="metro:TunnelSegment.ConstructionMethod",
            value="SHIELD",
        )
    )
    bad = _validate(
        SemanticClaim(
            subject="s",
            canonical_term_id="metro:TunnelSegment.ConstructionMethod",
            value="MAGIC",
        )
    )
    assert any(
        item.rule_id.endswith("AllowedValues") and item.status is ValidationStatus.PASS
        for item in good
    )
    assert any(
        item.rule_id.endswith("AllowedValues") and item.status is ValidationStatus.FAIL
        for item in bad
    )


def test_explicit_ifc_tunnel_usage_fails():
    findings = _validate(SemanticClaim(subject="x", canonical_term_id="ifc:IfcTunnel"))
    assert any(
        item.rule_id == "metro:Rule.ProhibitIfcTunnelEntity"
        and item.status is ValidationStatus.FAIL
        for item in findings
    )


@pytest.mark.parametrize(
    ("term_id", "value", "rule_id"),
    [
        (
            "ifc:IfcTrackElement.PredefinedType",
            "TURNOUT",
            "metro:Rule.ProhibitIfcTrackElementTurnout",
        ),
        (
            "ifc:IfcReferent.PredefinedType",
            "KILOMETERPOINT",
            "metro:Rule.ProhibitIfcReferentKilometerPoint",
        ),
    ],
)
def test_bracketed_ifc_usage_rules_match_claim_local_predefined_type(term_id, value, rule_id):
    findings = _validate(
        SemanticClaim(subject="x", canonical_term_id=term_id, value=value)
    )
    assert any(
        item.rule_id == rule_id and item.status is ValidationStatus.FAIL
        for item in findings
    )


def test_p_m_does_not_invent_missing_sibling_failure():
    findings = _validate(
        SemanticClaim(
            subject="e",
            canonical_term_id="metro:BuildingElementDesign.DesignStatus",
            value="WORKING",
        )
    )
    assert all("ElementCode.Missing" not in item.rule_id for item in findings)


def test_measure_with_unit_needs_external_unit_context():
    findings = _validate(
        SemanticClaim(
            subject="s",
            canonical_term_id="metro:TunnelSegment.StartChainage",
            value=1.0,
            unit="mm",
        )
    )
    assert any(
        item.rule_id == "metro:Rule.UnitContext"
        and item.status is ValidationStatus.NOT_APPLICABLE
        for item in findings
    )


def test_boolean_type_is_claim_local_and_strict():
    findings = _validate(
        SemanticClaim(
            subject="e",
            canonical_term_id="metro:BuildingElementDesign.AssetRequired",
            value="TRUE",
        )
    )
    assert any(
        item.rule_id.endswith("Datatype") and item.status is ValidationStatus.FAIL
        for item in findings
    )


def test_unknown_metro_term_fails_and_unrelated_claim_is_not_applicable():
    unknown = _validate(SemanticClaim(subject="x", canonical_term_id="metro:MissingTerm"))
    unrelated = _validate(SemanticClaim(subject="x", canonical_term_id="dsp:WallThickness"))
    assert any(
        item.rule_id == "metro:Rule.TermExists" and item.status is ValidationStatus.FAIL
        for item in unknown
    )
    assert any(
        item.rule_id == "metro:Rule.Scope" and item.status is ValidationStatus.NOT_APPLICABLE
        for item in unrelated
    )


def test_findings_are_deterministic_and_use_exact_provenance():
    claim = SemanticClaim(
        subject="s",
        canonical_term_id="metro:TunnelSegment.ConstructionMethod",
        value="SHIELD",
    )
    first = _validate(claim)
    second = _validate(claim)
    assert first == second
    assert first
    assert all(item.provenance == PROVENANCE for item in first)
