"""Immutable records for the Metro V3.2 machine catalog."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Mapping


class NormativeClass(str, Enum):
    NORMATIVE = "NORMATIVE"
    PROJECT_EXTENSION_DRAFT = "PROJECT_EXTENSION_DRAFT"
    RECOMMENDED = "RECOMMENDED"
    EXAMPLE = "EXAMPLE"
    DECISION_OPTION = "DECISION_OPTION"
    PROHIBITED = "PROHIBITED"


class RequirementLevel(str, Enum):
    IFC_M = "IFC-M"
    IFC_O = "IFC-O"
    P_M = "P-M"
    P_C = "P-C"
    P_R = "P-R"
    PROHIBITED = "PROHIBITED"


class MappingState(str, Enum):
    ACTIVE = "ACTIVE"
    CANDIDATE = "CANDIDATE"
    DECISION_OPTION = "DECISION_OPTION"


class DecisionState(str, Enum):
    UNFROZEN = "UNFROZEN"
    FROZEN = "FROZEN"


def freeze(value: object) -> object:
    """Recursively freeze JSON/YAML-like values."""
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(freeze(item) for item in value)
    if isinstance(value, (set, frozenset)):
        return tuple(sorted((freeze(item) for item in value), key=repr))
    return value


def plain(value: object) -> object:
    """Return a JSON-serializable representation of frozen values and enums."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [plain(item) for item in value]
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


@dataclass(frozen=True)
class MetroTermRecord:
    term_id: str
    kind: str
    normative_class: NormativeClass
    schema: Mapping[str, object]
    requirement_level: RequirementLevel | None = None
    description: str | None = None
    source_ref: Mapping[str, object] | None = None


@dataclass(frozen=True)
class MetroConstraint:
    term_id: str
    equals: object


@dataclass(frozen=True)
class MetroMappingRecord:
    mapping_id: str
    source_term_id: str
    state: MappingState
    normative_class: NormativeClass
    target_term_id: str
    constraints: tuple[MetroConstraint, ...]


@dataclass(frozen=True)
class MetroValidationRuleRecord:
    rule_id: str
    kind: str
    normative_class: NormativeClass
    operands: Mapping[str, object]


@dataclass(frozen=True)
class MetroDecisionRecord:
    decision_id: str
    subject_term_id: str
    state: DecisionState
    options: tuple[object, ...]
    recommended_option: object | None
    selected_option: object | None


@dataclass(frozen=True)
class MetroNormalizedSource:
    metadata: Mapping[str, object]
    source_coverage: Mapping[str, object]
    terms: tuple[MetroTermRecord, ...]
    mappings: tuple[MetroMappingRecord, ...]
    validation_rules: tuple[MetroValidationRuleRecord, ...]
    decisions: tuple[MetroDecisionRecord, ...]
    hash_payload: Mapping[str, object]
