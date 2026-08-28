"""Normalize and validate the checked-in Metro V3.2 machine source."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .errors import MetroCatalogBuildError
from .model import (
    DecisionState,
    MappingState,
    MetroConstraint,
    MetroDecisionRecord,
    MetroMappingRecord,
    MetroNormalizedSource,
    MetroTermRecord,
    MetroValidationRuleRecord,
    NormativeClass,
    RequirementLevel,
    freeze,
    plain,
)

_PRESENTATION_KEYS = {"description", "source_ref", "source_document_title", "source_document_sha256"}


def _mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise MetroCatalogBuildError(f"{label} must be a mapping")
    return value


def _sequence(value: object, label: str) -> Sequence[object]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise MetroCatalogBuildError(f"{label} must be a sequence")
    return value


def _text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise MetroCatalogBuildError(f"{label} must be a non-empty string")
    return value


def _enum(enum_type, value: object, label: str):
    try:
        return enum_type(_text(value, label))
    except ValueError as exc:
        noun = "normative" if enum_type is NormativeClass else label
        raise MetroCatalogBuildError(f"unknown {noun} value: {value}") from exc


def _unique(records: Sequence[object], key_name: str, collection: str) -> None:
    seen: set[str] = set()
    for raw in records:
        item = _mapping(raw, collection)
        key = _text(item.get(key_name), f"{collection}.{key_name}")
        if key in seen:
            raise MetroCatalogBuildError(f"duplicate {key_name}: {key}")
        seen.add(key)


def _machine_metadata(metadata: Mapping[str, object]) -> Mapping[str, object]:
    return {
        str(key): value
        for key, value in metadata.items()
        if str(key) not in _PRESENTATION_KEYS
    }


def _term_hash_record(record: MetroTermRecord) -> Mapping[str, object]:
    return {
        "term_id": record.term_id,
        "kind": record.kind,
        "normative_class": record.normative_class.value,
        "requirement_level": record.requirement_level.value if record.requirement_level else None,
        "schema": plain(record.schema),
    }


def _mapping_hash_record(record: MetroMappingRecord) -> Mapping[str, object]:
    return {
        "mapping_id": record.mapping_id,
        "source_term_id": record.source_term_id,
        "state": record.state.value,
        "normative_class": record.normative_class.value,
        "target_term_id": record.target_term_id,
        "constraints": [
            {"term_id": item.term_id, "equals": plain(item.equals)}
            for item in record.constraints
        ],
    }


def _rule_hash_record(record: MetroValidationRuleRecord) -> Mapping[str, object]:
    return {
        "rule_id": record.rule_id,
        "kind": record.kind,
        "normative_class": record.normative_class.value,
        "operands": plain(record.operands),
    }


def _decision_hash_record(record: MetroDecisionRecord) -> Mapping[str, object]:
    return {
        "decision_id": record.decision_id,
        "subject_term_id": record.subject_term_id,
        "state": record.state.value,
        "options": plain(record.options),
        "recommended_option": plain(record.recommended_option),
        "selected_option": plain(record.selected_option),
    }


def normalize_machine_source(payload: Mapping[str, object]) -> MetroNormalizedSource:
    metadata = _mapping(payload.get("metadata"), "metadata")
    source_coverage = _mapping(payload.get("source_coverage"), "source_coverage")
    raw_terms = _sequence(payload.get("terms"), "terms")
    raw_mappings = _sequence(payload.get("mappings"), "mappings")
    raw_rules = _sequence(payload.get("validation_rules"), "validation_rules")
    raw_decisions = _sequence(payload.get("decisions"), "decisions")

    _unique(raw_terms, "term_id", "terms")
    _unique(raw_mappings, "mapping_id", "mappings")
    _unique(raw_rules, "rule_id", "validation_rules")
    _unique(raw_decisions, "decision_id", "decisions")

    terms: list[MetroTermRecord] = []
    for raw in raw_terms:
        item = _mapping(raw, "term")
        normative = _enum(NormativeClass, item.get("normative_class"), "normative_class")
        if normative is NormativeClass.EXAMPLE:
            continue
        requirement_raw = item.get("requirement_level")
        requirement = None
        if requirement_raw is not None:
            requirement = _enum(RequirementLevel, requirement_raw, "requirement")
        schema = _mapping(item.get("schema", {}), "term.schema")
        source_ref_raw = item.get("source_ref")
        source_ref = None if source_ref_raw is None else freeze(_mapping(source_ref_raw, "term.source_ref"))
        terms.append(
            MetroTermRecord(
                term_id=_text(item.get("term_id"), "term_id"),
                kind=_text(item.get("kind"), "term.kind"),
                normative_class=normative,
                requirement_level=requirement,
                schema=freeze(schema),
                description=item.get("description") if isinstance(item.get("description"), str) else None,
                source_ref=source_ref,
            )
        )

    term_ids = {record.term_id for record in terms}

    mappings: list[MetroMappingRecord] = []
    active_by_source: dict[str, MetroMappingRecord] = {}
    for raw in raw_mappings:
        item = _mapping(raw, "mapping")
        normative = _enum(NormativeClass, item.get("normative_class"), "normative_class")
        if normative is NormativeClass.EXAMPLE:
            continue
        state = _enum(MappingState, item.get("state"), "mapping state")
        source_term_id = _text(item.get("source_term_id"), "mapping.source_term_id")
        target_term_id = _text(item.get("target_term_id"), "mapping.target_term_id")
        if source_term_id not in term_ids:
            raise MetroCatalogBuildError(f"unknown Metro source term: {source_term_id}")
        if state is MappingState.ACTIVE and not target_term_id.startswith("ifc:"):
            raise MetroCatalogBuildError("ACTIVE mapping target must use ifc namespace")
        constraints: list[MetroConstraint] = []
        for constraint_raw in _sequence(item.get("constraints", []), "mapping.constraints"):
            constraint = _mapping(constraint_raw, "mapping.constraint")
            term_id = _text(constraint.get("term_id"), "constraint.term_id")
            if state is MappingState.ACTIVE and not term_id.startswith("ifc:"):
                raise MetroCatalogBuildError("ACTIVE mapping constraints must target ifc terms")
            constraints.append(MetroConstraint(term_id=term_id, equals=freeze(constraint.get("equals"))))
        record = MetroMappingRecord(
            mapping_id=_text(item.get("mapping_id"), "mapping_id"),
            source_term_id=source_term_id,
            state=state,
            normative_class=normative,
            target_term_id=target_term_id,
            constraints=tuple(constraints),
        )
        if state is MappingState.ACTIVE:
            previous = active_by_source.get(source_term_id)
            if previous is not None and (
                previous.target_term_id != record.target_term_id
                or previous.constraints != record.constraints
            ):
                raise MetroCatalogBuildError(f"conflicting ACTIVE mapping for {source_term_id}")
            active_by_source[source_term_id] = record
        mappings.append(record)

    rules: list[MetroValidationRuleRecord] = []
    for raw in raw_rules:
        item = _mapping(raw, "validation rule")
        normative = _enum(NormativeClass, item.get("normative_class"), "normative_class")
        if normative is NormativeClass.EXAMPLE:
            continue
        rules.append(
            MetroValidationRuleRecord(
                rule_id=_text(item.get("rule_id"), "rule_id"),
                kind=_text(item.get("kind"), "validation rule kind"),
                normative_class=normative,
                operands=freeze(_mapping(item.get("operands", {}), "validation rule operands")),
            )
        )

    decisions: list[MetroDecisionRecord] = []
    for raw in raw_decisions:
        item = _mapping(raw, "decision")
        state = _enum(DecisionState, item.get("state"), "decision state")
        options = tuple(freeze(value) for value in _sequence(item.get("options", []), "decision.options"))
        if not options:
            raise MetroCatalogBuildError("decision options must not be empty")
        selected = freeze(item.get("selected_option"))
        if state is DecisionState.FROZEN and selected is None:
            raise MetroCatalogBuildError("FROZEN decision requires selected option")
        if selected is not None and selected not in options:
            raise MetroCatalogBuildError("selected decision option must be declared")
        if state is DecisionState.UNFROZEN and selected is not None:
            raise MetroCatalogBuildError("UNFROZEN decision cannot have selected option")
        decisions.append(
            MetroDecisionRecord(
                decision_id=_text(item.get("decision_id"), "decision_id"),
                subject_term_id=_text(item.get("subject_term_id"), "decision.subject_term_id"),
                state=state,
                options=options,
                recommended_option=freeze(item.get("recommended_option")),
                selected_option=selected,
            )
        )

    terms.sort(key=lambda item: item.term_id)
    mappings.sort(key=lambda item: item.mapping_id)
    rules.sort(key=lambda item: item.rule_id)
    decisions.sort(key=lambda item: item.decision_id)

    hash_payload = freeze(
        {
            "metadata": _machine_metadata(metadata),
            "source_coverage": plain(freeze(source_coverage)),
            "terms": [_term_hash_record(record) for record in terms],
            "mappings": [_mapping_hash_record(record) for record in mappings],
            "validation_rules": [_rule_hash_record(record) for record in rules],
            "decisions": [_decision_hash_record(record) for record in decisions],
        }
    )

    return MetroNormalizedSource(
        metadata=freeze(metadata),
        source_coverage=freeze(source_coverage),
        terms=tuple(terms),
        mappings=tuple(mappings),
        validation_rules=tuple(rules),
        decisions=tuple(decisions),
        hash_payload=hash_payload,
    )
