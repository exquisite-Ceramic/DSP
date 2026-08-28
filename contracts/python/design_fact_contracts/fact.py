from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .refs import DesignFactHostRef, NativeSubjectRef, _require_non_empty


class FactKind(str, Enum):
    PROPERTY = "PROPERTY"
    CLASSIFICATION = "CLASSIFICATION"
    PLACEMENT = "PLACEMENT"
    BOUNDS = "BOUNDS"
    GEOMETRY = "GEOMETRY"
    RELATIONSHIP = "RELATIONSHIP"
    IDENTITY = "IDENTITY"


class ValueType(str, Enum):
    NULL = "NULL"
    STRING = "STRING"
    INTEGER = "INTEGER"
    NUMBER = "NUMBER"
    BOOLEAN = "BOOLEAN"
    OBJECT = "OBJECT"
    ARRAY = "ARRAY"


def _optional_non_empty(value: Any, field_name: str) -> str | None:
    if value is None:
        return None
    return _require_non_empty(value, field_name)


def _freeze_json(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("value must be JSON-compatible; non-finite numbers are forbidden")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, Any] = {}
        for key, nested in value.items():
            if not isinstance(key, str):
                raise ValueError("value OBJECT keys must be strings")
            frozen[key] = _freeze_json(nested)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    raise ValueError(f"value must be JSON-compatible, got {type(value).__name__}")


def _thaw_json(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _thaw_json(nested) for key, nested in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _coerce_enum(enum_type: type[Enum], value: Any, field_name: str) -> Enum:
    if isinstance(value, enum_type):
        return value
    try:
        return enum_type(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field_name}: {value!r}") from exc


def _validate_value_type(value: Any, value_type: ValueType) -> None:
    valid = {
        ValueType.NULL: value is None,
        ValueType.STRING: isinstance(value, str),
        ValueType.INTEGER: isinstance(value, int) and not isinstance(value, bool),
        ValueType.NUMBER: isinstance(value, (int, float)) and not isinstance(value, bool),
        ValueType.BOOLEAN: isinstance(value, bool),
        ValueType.OBJECT: isinstance(value, Mapping),
        ValueType.ARRAY: isinstance(value, tuple),
    }[value_type]
    if not valid:
        raise ValueError(f"value is incompatible with value_type {value_type.value}")


@dataclass(frozen=True, slots=True)
class NormalizedDesignFact:
    fact_id: str
    producer: str
    host_ref: DesignFactHostRef
    source_revision: int
    subject_native_ref: NativeSubjectRef
    fact_kind: FactKind
    value: Any
    value_type: ValueType
    predicate: str | None = None
    unit: str | None = None
    geometry_ref: str | None = None
    source_scheme: str | None = None
    source_code: str | None = None
    provenance: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_non_empty(self.fact_id, "fact_id")
        _require_non_empty(self.producer, "producer")
        if not isinstance(self.host_ref, DesignFactHostRef):
            raise ValueError("host_ref must be a DesignFactHostRef")
        if isinstance(self.source_revision, bool) or not isinstance(self.source_revision, int) or self.source_revision < 0:
            raise ValueError("source_revision must be a non-negative integer")
        if not isinstance(self.subject_native_ref, NativeSubjectRef):
            raise ValueError("subject_native_ref must be a NativeSubjectRef")
        if self.subject_native_ref.document_id != self.host_ref.document_id:
            raise ValueError("host_ref and subject_native_ref document_id must match")

        fact_kind = _coerce_enum(FactKind, self.fact_kind, "fact_kind")
        value_type = _coerce_enum(ValueType, self.value_type, "value_type")
        object.__setattr__(self, "fact_kind", fact_kind)
        object.__setattr__(self, "value_type", value_type)

        object.__setattr__(self, "predicate", _optional_non_empty(self.predicate, "predicate"))
        object.__setattr__(self, "unit", _optional_non_empty(self.unit, "unit"))
        object.__setattr__(self, "geometry_ref", _optional_non_empty(self.geometry_ref, "geometry_ref"))
        object.__setattr__(self, "source_scheme", _optional_non_empty(self.source_scheme, "source_scheme"))
        object.__setattr__(self, "source_code", _optional_non_empty(self.source_code, "source_code"))
        if (self.source_scheme is None) != (self.source_code is None):
            raise ValueError("source_scheme and source_code must be both present or both absent")

        frozen_value = _freeze_json(self.value)
        object.__setattr__(self, "value", frozen_value)
        _validate_value_type(frozen_value, value_type)

        if isinstance(self.provenance, str) or not isinstance(self.provenance, Iterable):
            raise ValueError("provenance must be an iterable of non-empty strings")
        normalized_provenance = tuple(_require_non_empty(item, "provenance item") for item in self.provenance)
        object.__setattr__(self, "provenance", normalized_provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "fact_id": self.fact_id,
            "producer": self.producer,
            "host_ref": self.host_ref.to_dict(),
            "source_revision": self.source_revision,
            "subject_native_ref": self.subject_native_ref.to_dict(),
            "fact_kind": self.fact_kind.value,
            "predicate": self.predicate,
            "value": _thaw_json(self.value),
            "value_type": self.value_type.value,
            "unit": self.unit,
            "geometry_ref": self.geometry_ref,
            "source_scheme": self.source_scheme,
            "source_code": self.source_code,
            "provenance": list(self.provenance),
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NormalizedDesignFact":
        if not isinstance(data, Mapping):
            raise ValueError("NormalizedDesignFact must be an object")
        fields = {
            "fact_id", "producer", "host_ref", "source_revision", "subject_native_ref",
            "fact_kind", "predicate", "value", "value_type", "unit", "geometry_ref",
            "source_scheme", "source_code", "provenance",
        }
        unknown = set(data) - fields
        if unknown:
            raise ValueError(f"NormalizedDesignFact contains unknown fields: {sorted(unknown)}")
        missing = fields - set(data)
        if missing:
            raise ValueError(f"NormalizedDesignFact missing required fields: {sorted(missing)}")
        return cls(
            fact_id=data["fact_id"],
            producer=data["producer"],
            host_ref=DesignFactHostRef.from_dict(data["host_ref"]),
            source_revision=data["source_revision"],
            subject_native_ref=NativeSubjectRef.from_dict(data["subject_native_ref"]),
            fact_kind=data["fact_kind"],
            predicate=data["predicate"],
            value=data["value"],
            value_type=data["value_type"],
            unit=data["unit"],
            geometry_ref=data["geometry_ref"],
            source_scheme=data["source_scheme"],
            source_code=data["source_code"],
            provenance=data["provenance"],
        )


@dataclass(frozen=True, slots=True)
class NormalizedDesignFactBatch:
    facts: tuple[NormalizedDesignFact, ...] = ()

    def __post_init__(self) -> None:
        if isinstance(self.facts, NormalizedDesignFact) or not isinstance(self.facts, Iterable):
            raise ValueError("facts must be an iterable of NormalizedDesignFact")
        normalized = tuple(self.facts)
        if not all(isinstance(fact, NormalizedDesignFact) for fact in normalized):
            raise ValueError("facts must contain only NormalizedDesignFact values")
        object.__setattr__(self, "facts", normalized)

    def to_dict(self) -> dict[str, list[dict[str, Any]]]:
        return {"facts": [fact.to_dict() for fact in self.facts]}

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "NormalizedDesignFactBatch":
        if not isinstance(data, Mapping):
            raise ValueError("NormalizedDesignFactBatch must be an object")
        if set(data) != {"facts"}:
            raise ValueError("NormalizedDesignFactBatch must contain only the facts field")
        facts = data["facts"]
        if not isinstance(facts, list):
            raise ValueError("facts must be an array")
        return cls(tuple(NormalizedDesignFact.from_dict(item) for item in facts))
