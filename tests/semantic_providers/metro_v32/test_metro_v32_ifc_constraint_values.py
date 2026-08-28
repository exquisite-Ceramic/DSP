from ifc43_semantic_provider import IFC43_PROVIDER
from metro_semantic_provider import METRO_V32_CATALOG
from semantic_service import SemanticClaim, ValidationStatus


def test_every_active_mapping_constraint_value_is_legal_ifc43():
    checked = 0
    for mapping in METRO_V32_CATALOG.mappings:
        if mapping.state.value != "ACTIVE":
            continue
        for constraint in mapping.constraints:
            checked += 1
            findings = IFC43_PROVIDER.validate_claim(
                SemanticClaim(
                    subject=mapping.source_term_id,
                    canonical_term_id=constraint.term_id,
                    value=constraint.equals,
                )
            )
            assert not any(
                item.status is ValidationStatus.FAIL
                for item in findings
            ), (
                f"invalid IFC constraint value: {mapping.mapping_id} "
                f"{constraint.term_id}={constraint.equals!r}"
            )
            assert any(
                item.status is ValidationStatus.PASS
                and item.rule_id in {"ifc43.value.enum", "ifc43.value.type"}
                for item in findings
            ), (
                f"IFC constraint was not value-validated: "
                f"{mapping.mapping_id} {constraint.term_id}"
            )
    assert checked
