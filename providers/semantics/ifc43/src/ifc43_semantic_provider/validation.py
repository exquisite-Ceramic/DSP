from __future__ import annotations

from collections.abc import Mapping

from semantic_service import (
    ProviderProvenance,
    SemanticClaim,
    ValidationFinding,
    ValidationStatus,
)

from .errors import Ifc43TermNotFoundError

IFC_SCOPE_RULE = "ifc43.scope"
TERM_EXISTS_RULE = "ifc43.term.exists"
ENUM_RULE = "ifc43.value.enum"
TYPE_RULE = "ifc43.value.type"
CONTEXT_RULE = "ifc43.value.context"

_QTO_NUMERIC_TYPES = {
    "Q_LENGTH",
    "Q_AREA",
    "Q_VOLUME",
    "Q_WEIGHT",
    "Q_TIME",
    "Q_COUNT",
}


def _finding(
    rule_id: str,
    status: ValidationStatus,
    provenance: ProviderProvenance,
    message: str | None = None,
) -> ValidationFinding:
    return ValidationFinding(rule_id, status, provenance, message)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _python_type_ok(simple_name: object, value: object) -> bool:
    if simple_name in {"REAL", "NUMBER"}:
        return _is_number(value)
    if simple_name == "INTEGER":
        return isinstance(value, int) and not isinstance(value, bool)
    if simple_name == "BOOLEAN":
        return isinstance(value, bool)
    if simple_name == "LOGICAL":
        return value in (True, False, "UNKNOWN")
    if simple_name == "STRING":
        return isinstance(value, str)
    if simple_name == "BINARY":
        return isinstance(value, (bytes, bytearray))
    return False


def _type_target(catalog: object, expression: Mapping[str, object]):
    kind = expression.get("kind")
    if kind == "SIMPLE":
        return ("SIMPLE", expression.get("name"))
    if kind != "NAMED":
        return ("CONTEXT", None)

    term_id = expression.get("name")
    if not isinstance(term_id, str):
        return ("CONTEXT", None)
    record = catalog.get(term_id)
    if record.kind == "ENUM":
        return ("ENUM", term_id)
    if record.kind == "DEFINED_TYPE":
        underlying = record.machine_schema.get("underlying")
        if isinstance(underlying, Mapping):
            return _type_target(catalog, underlying)
    return ("CONTEXT", None)


def _enum_values(catalog: object, enum_term_id: str) -> tuple[object, ...]:
    enum_record = catalog.get(enum_term_id)
    literal_ids = tuple(enum_record.machine_schema.get("literals", ()))
    return tuple(catalog.get(item).machine_schema["value"] for item in literal_ids)


def _value_target(catalog: object, record: object):
    if record.kind == "ATTRIBUTE":
        declared = record.machine_schema.get("declared_type")
        if isinstance(declared, Mapping):
            return _type_target(catalog, declared)
        return ("CONTEXT", None)

    if record.kind == "PSET_PROPERTY":
        enum_values = tuple(record.machine_schema.get("enum_values", ()))
        if enum_values:
            return ("INLINE_ENUM", enum_values)
        measure = record.machine_schema.get("primary_measure_type")
        if isinstance(measure, str) and measure:
            try:
                return _type_target(catalog, {"kind": "NAMED", "name": f"ifc:{measure}"})
            except Ifc43TermNotFoundError:
                return ("CONTEXT", None)
        return ("CONTEXT", None)

    if record.kind == "QTO_QUANTITY":
        template_type = record.machine_schema.get("template_type")
        if template_type in _QTO_NUMERIC_TYPES:
            return ("NUMBER", None)
        return ("CONTEXT", None)

    return ("CONTEXT", None)


def validate_claim_against_ifc43(
    catalog: object,
    claim: SemanticClaim,
    provenance: ProviderProvenance,
) -> tuple[ValidationFinding, ...]:
    target = claim.canonical_term_id or claim.predicate
    if target is None or not target.startswith("ifc:"):
        return (_finding(IFC_SCOPE_RULE, ValidationStatus.NOT_APPLICABLE, provenance),)

    try:
        record = catalog.get(target)
    except Ifc43TermNotFoundError:
        return (_finding(TERM_EXISTS_RULE, ValidationStatus.FAIL, provenance),)

    findings = [_finding(TERM_EXISTS_RULE, ValidationStatus.PASS, provenance)]
    if claim.value is None:
        findings.append(_finding(CONTEXT_RULE, ValidationStatus.NOT_APPLICABLE, provenance))
        return tuple(findings)

    target_kind, target_value = _value_target(catalog, record)
    if target_kind == "ENUM":
        allowed = _enum_values(catalog, target_value)
        status = ValidationStatus.PASS if claim.value in allowed else ValidationStatus.FAIL
        findings.append(_finding(ENUM_RULE, status, provenance))
    elif target_kind == "INLINE_ENUM":
        status = ValidationStatus.PASS if claim.value in target_value else ValidationStatus.FAIL
        findings.append(_finding(ENUM_RULE, status, provenance))
    elif target_kind == "SIMPLE":
        status = (
            ValidationStatus.PASS
            if _python_type_ok(target_value, claim.value)
            else ValidationStatus.FAIL
        )
        findings.append(_finding(TYPE_RULE, status, provenance))
    elif target_kind == "NUMBER":
        status = ValidationStatus.PASS if _is_number(claim.value) else ValidationStatus.FAIL
        findings.append(_finding(TYPE_RULE, status, provenance))
    else:
        findings.append(_finding(CONTEXT_RULE, ValidationStatus.NOT_APPLICABLE, provenance))

    if claim.unit is not None:
        findings.append(
            _finding(
                CONTEXT_RULE,
                ValidationStatus.NOT_APPLICABLE,
                provenance,
                "unit validation requires IFC model unit-assignment context",
            )
        )

    return tuple(findings)
