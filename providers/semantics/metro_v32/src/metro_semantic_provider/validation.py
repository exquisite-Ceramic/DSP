"""Claim-local Metro validation without importing concrete IFC implementations."""

from __future__ import annotations

from collections.abc import Mapping

from semantic_service.providers import (
    ProviderProvenance,
    SemanticClaim,
    ValidationFinding,
    ValidationStatus,
)

from .catalog import MetroCatalog
from .errors import MetroTermNotFoundError
from .model import RequirementLevel

_STRING_TYPES = {
    "ifc:IfcIdentifier",
    "ifc:IfcLabel",
    "ifc:IfcText",
    "ifc:IfcDate",
    "ifc:IfcDateTime",
    "ifc:IfcDuration",
}
_INTEGER_TYPES = {"ifc:IfcInteger"}
_BOOLEAN_TYPES = {"ifc:IfcBoolean"}


def _finding(
    rule_id: str,
    status: ValidationStatus,
    provenance: ProviderProvenance,
    message: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(
        rule_id=rule_id,
        status=status,
        provenance=provenance,
        message=message,
    )


def _datatype_status(datatype: str, value: object) -> ValidationStatus | None:
    if datatype in _STRING_TYPES:
        return ValidationStatus.PASS if isinstance(value, str) else ValidationStatus.FAIL
    if datatype in _BOOLEAN_TYPES:
        return ValidationStatus.PASS if isinstance(value, bool) else ValidationStatus.FAIL
    if datatype in _INTEGER_TYPES:
        return (
            ValidationStatus.PASS
            if isinstance(value, int) and not isinstance(value, bool)
            else ValidationStatus.FAIL
        )
    if datatype.startswith("ifc:Ifc") and datatype.endswith("Measure"):
        return (
            ValidationStatus.PASS
            if isinstance(value, (int, float)) and not isinstance(value, bool)
            else ValidationStatus.FAIL
        )
    return None


def _matches_prohibited_token(forbidden: object, claim: SemanticClaim) -> bool:
    if not isinstance(forbidden, str):
        return False
    term_id = claim.canonical_term_id
    if term_id is None or not term_id.startswith("ifc:"):
        return False
    token = term_id.split(":", 1)[1]

    entity, separator, bracketed_value = forbidden.partition("[")
    if not separator:
        return forbidden == token
    if not entity or not bracketed_value.endswith("]"):
        return False

    expected_value = bracketed_value[:-1]
    return (
        token == f"{entity}.PredefinedType"
        and claim.value == expected_value
    )


def _prohibited_findings(
    catalog: MetroCatalog,
    claim: SemanticClaim,
    provenance: ProviderProvenance,
) -> list[ValidationFinding]:
    term_id = claim.canonical_term_id
    if term_id is None or not term_id.startswith("ifc:"):
        return []
    token = term_id.split(":", 1)[1]
    findings: list[ValidationFinding] = []
    for rule in catalog.validation_rules:
        if rule.kind != "PROHIBITED_IFC_USAGE":
            continue
        forbidden = rule.operands.get("forbidden_token")
        if _matches_prohibited_token(forbidden, claim):
            findings.append(
                _finding(
                    rule.rule_id,
                    ValidationStatus.FAIL,
                    provenance,
                    f"{token} is prohibited by the Metro V3.2 profile",
                )
            )
    return findings


def validate_claim_against_metro(
    catalog: MetroCatalog,
    claim: SemanticClaim,
    provenance: ProviderProvenance,
) -> tuple[ValidationFinding, ...]:
    prohibited = _prohibited_findings(catalog, claim, provenance)
    if prohibited:
        return tuple(sorted(prohibited, key=lambda item: item.rule_id))

    term_id = claim.canonical_term_id
    if term_id is None or not term_id.startswith("metro:"):
        return (
            _finding(
                "metro:Rule.Scope",
                ValidationStatus.NOT_APPLICABLE,
                provenance,
                "claim is outside Metro vocabulary scope",
            ),
        )

    try:
        record = catalog.get(term_id)
    except MetroTermNotFoundError:
        return (
            _finding(
                "metro:Rule.TermExists",
                ValidationStatus.FAIL,
                provenance,
                f"unknown Metro term: {term_id}",
            ),
        )

    findings: list[ValidationFinding] = [
        _finding("metro:Rule.TermExists", ValidationStatus.PASS, provenance)
    ]
    schema: Mapping[str, object] = record.schema
    datatype = schema.get("datatype")

    if claim.value is not None:
        if isinstance(datatype, str):
            status = _datatype_status(datatype, claim.value)
            if status is None:
                findings.append(
                    _finding(
                        f"{term_id}.Datatype",
                        ValidationStatus.NOT_APPLICABLE,
                        provenance,
                        f"datatype {datatype} needs external schema context",
                    )
                )
            else:
                findings.append(
                    _finding(
                        f"{term_id}.Datatype",
                        status,
                        provenance,
                        None if status is ValidationStatus.PASS else f"value does not match {datatype}",
                    )
                )
        elif schema.get("unresolved_datatype") is not None or schema.get("datatype_options") is not None:
            findings.append(
                _finding(
                    f"{term_id}.Datatype",
                    ValidationStatus.NOT_APPLICABLE,
                    provenance,
                    "datatype is unresolved or project-option dependent",
                )
            )

        allowed_values = schema.get("allowed_values")
        if isinstance(allowed_values, tuple) and allowed_values:
            status = (
                ValidationStatus.PASS
                if claim.value in allowed_values
                else ValidationStatus.FAIL
            )
            findings.append(
                _finding(
                    f"{term_id}.AllowedValues",
                    status,
                    provenance,
                    None if status is ValidationStatus.PASS else "value is outside the allowed Metro enumeration",
                )
            )

    if record.requirement_level is RequirementLevel.P_C:
        findings.append(
            _finding(
                "metro:Rule.ConditionalContext",
                ValidationStatus.NOT_APPLICABLE,
                provenance,
                "P-C applicability requires entity/project context",
            )
        )

    if claim.unit is not None and isinstance(datatype, str) and datatype.endswith("Measure"):
        findings.append(
            _finding(
                "metro:Rule.UnitContext",
                ValidationStatus.NOT_APPLICABLE,
                provenance,
                "unit compatibility requires the external IFC unit assignment context",
            )
        )

    return tuple(
        sorted(
            findings,
            key=lambda item: (item.rule_id, item.status.value, item.message or ""),
        )
    )
