from semantic_service import SemanticClaim, ValidationStatus

from ifc43_semantic_provider import IFC43_PROVIDER


def finding(rule_id, claim):
    return next(item for item in IFC43_PROVIDER.validate_claim(claim) if item.rule_id == rule_id)


def test_non_ifc_claim_is_not_applicable():
    result = IFC43_PROVIDER.validate_claim(
        SemanticClaim(subject="S1", canonical_term_id="dsp:WallThickness", value=200)
    )
    assert result[0].status is ValidationStatus.NOT_APPLICABLE


def test_unknown_ifc_term_fails_legality_check():
    item = finding(
        "ifc43.term.exists",
        SemanticClaim(subject="S1", canonical_term_id="ifc:IfcTunnel", value=None),
    )
    assert item.status is ValidationStatus.FAIL


def test_valid_enum_value_passes_and_invalid_value_fails():
    valid = finding(
        "ifc43.value.enum",
        SemanticClaim(
            subject="S1",
            canonical_term_id="ifc:IfcRailwayPart.PredefinedType",
            value="TRACK",
        ),
    )
    invalid = finding(
        "ifc43.value.enum",
        SemanticClaim(
            subject="S1",
            canonical_term_id="ifc:IfcRailwayPart.PredefinedType",
            value="STATION",
        ),
    )
    assert valid.status is ValidationStatus.PASS
    assert invalid.status is ValidationStatus.FAIL


def test_boolean_pset_property_rejects_string_value():
    item = finding(
        "ifc43.value.type",
        SemanticClaim(
            subject="S1",
            canonical_term_id="ifc:Pset_WallCommon.LoadBearing",
            value="TRUE",
        ),
    )
    assert item.status is ValidationStatus.FAIL


def test_entity_value_requires_model_context():
    item = finding(
        "ifc43.value.context",
        SemanticClaim(subject="S1", canonical_term_id="ifc:IfcWall", value="reference"),
    )
    assert item.status is ValidationStatus.NOT_APPLICABLE
