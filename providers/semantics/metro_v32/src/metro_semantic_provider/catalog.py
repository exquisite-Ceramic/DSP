"""Immutable Metro V3.2 semantic catalog."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .errors import MetroCatalogBuildError, MetroTermNotFoundError
from .hashing import semantic_content_hash
from .model import (
    MetroDecisionRecord,
    MetroMappingRecord,
    MetroTermRecord,
    MetroValidationRuleRecord,
    NormativeClass,
    freeze,
    plain,
)
from .normalization import normalize_machine_source


def _synthetic_mapping_term(record: MetroMappingRecord) -> MetroTermRecord:
    return MetroTermRecord(
        term_id=record.mapping_id,
        kind="MAPPING_RULE",
        normative_class=record.normative_class,
        schema=freeze(
            {
                "source_term_id": record.source_term_id,
                "state": record.state.value,
                "target_term_id": record.target_term_id,
                "constraints": [
                    {"term_id": item.term_id, "equals": plain(item.equals)}
                    for item in record.constraints
                ],
            }
        ),
    )


def _synthetic_validation_term(record: MetroValidationRuleRecord) -> MetroTermRecord:
    return MetroTermRecord(
        term_id=record.rule_id,
        kind="VALIDATION_RULE",
        normative_class=record.normative_class,
        schema=freeze({"rule_kind": record.kind, "operands": plain(record.operands)}),
    )


def _synthetic_decision_term(record: MetroDecisionRecord) -> MetroTermRecord:
    return MetroTermRecord(
        term_id=f"metro:Decision.{record.decision_id}",
        kind="DECISION",
        normative_class=NormativeClass.DECISION_OPTION,
        schema=freeze(
            {
                "decision_id": record.decision_id,
                "subject_term_id": record.subject_term_id,
                "state": record.state.value,
                "options": plain(record.options),
                "recommended_option": plain(record.recommended_option),
                "selected_option": plain(record.selected_option),
            }
        ),
    )


@dataclass(frozen=True)
class MetroCatalog:
    metadata: Mapping[str, object]
    source_coverage: Mapping[str, object]
    terms: tuple[MetroTermRecord, ...]
    mappings: tuple[MetroMappingRecord, ...]
    validation_rules: tuple[MetroValidationRuleRecord, ...]
    decisions: tuple[MetroDecisionRecord, ...]
    content_hash: str
    _index: Mapping[str, MetroTermRecord]

    def get(self, term_id: str) -> MetroTermRecord:
        try:
            return self._index[term_id]
        except KeyError as exc:
            raise MetroTermNotFoundError(term_id) from exc

    def schema_for(self, term_id: str) -> Mapping[str, object]:
        return self.get(term_id).schema


def build_catalog(payload: Mapping[str, object]) -> MetroCatalog:
    normalized = normalize_machine_source(payload)
    index: dict[str, MetroTermRecord] = {record.term_id: record for record in normalized.terms}

    synthetic = [
        *(_synthetic_mapping_term(record) for record in normalized.mappings),
        *(_synthetic_validation_term(record) for record in normalized.validation_rules),
        *(_synthetic_decision_term(record) for record in normalized.decisions),
    ]
    for record in synthetic:
        if record.term_id in index:
            raise MetroCatalogBuildError(f"duplicate synthetic term: {record.term_id}")
        index[record.term_id] = record

    return MetroCatalog(
        metadata=normalized.metadata,
        source_coverage=normalized.source_coverage,
        terms=normalized.terms,
        mappings=normalized.mappings,
        validation_rules=normalized.validation_rules,
        decisions=normalized.decisions,
        content_hash=semantic_content_hash(normalized.hash_payload),
        _index=MappingProxyType(index),
    )
