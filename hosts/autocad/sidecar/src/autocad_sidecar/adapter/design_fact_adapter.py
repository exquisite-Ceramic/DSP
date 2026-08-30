"""Thin AutoCAD-native snapshot to NormalizedDesignFact conversion."""

from __future__ import annotations

import hashlib
import math
from typing import Any, Mapping
from urllib.parse import quote

from design_fact_contracts import (
    DesignFactHostRef,
    FactKind,
    NativeSubjectRef,
    NormalizedDesignFact,
    NormalizedDesignFactBatch,
    ValueType,
)


_BATCH_FIELDS = {"hostInstanceId", "documentId", "revision", "entities"}
_ENTITY_FIELDS = {"nativeId", "nativeKind", "layer", "bounds", "properties"}
_BOUNDS_FIELDS = {"min", "max"}
_POINT_FIELDS = {"x", "y", "z"}
_PROPERTY_FIELDS = {"constantWidth"}
_CONSTANT_WIDTH_FIELDS = {"value", "unit"}


def _require_mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _reject_unknown(mapping: Mapping[str, Any], allowed: set[str], field: str) -> None:
    unknown = set(mapping) - allowed
    if unknown:
        raise ValueError(f"{field} contains unknown fields: {sorted(unknown)}")


def _require_text(mapping: Mapping[str, Any], key: str) -> str:
    value = mapping.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} must be a non-empty string")
    return value


def _require_revision(mapping: Mapping[str, Any]) -> int:
    value = mapping.get("revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("revision must be a non-negative integer")
    return value


def _require_entities(mapping: Mapping[str, Any]) -> list[Any]:
    value = mapping.get("entities")
    if not isinstance(value, list):
        raise ValueError("entities must be an array")
    return value


def _require_number(mapping: Mapping[str, Any], key: str, field: str) -> int | float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must contain numeric x/y/z coordinates")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"{field} must contain finite numeric coordinates")
    return value


def _validate_point(value: Any, field: str) -> dict[str, int | float]:
    point = _require_mapping(value, field)
    _reject_unknown(point, _POINT_FIELDS, field)
    if set(point) != _POINT_FIELDS:
        raise ValueError(f"{field} must contain x, y, and z")
    return {
        "x": _require_number(point, "x", field),
        "y": _require_number(point, "y", field),
        "z": _require_number(point, "z", field),
    }


def _validate_bounds(value: Any) -> dict[str, dict[str, int | float]]:
    bounds = _require_mapping(value, "bounds")
    _reject_unknown(bounds, _BOUNDS_FIELDS, "bounds")
    if set(bounds) != _BOUNDS_FIELDS:
        raise ValueError("bounds must contain min and max")
    return {
        "min": _validate_point(bounds["min"], "bounds.min"),
        "max": _validate_point(bounds["max"], "bounds.max"),
    }


def _read_constant_width(value: Any) -> tuple[int | float, str]:
    measurement = _require_mapping(value, "properties.constantWidth")
    _reject_unknown(
        measurement,
        _CONSTANT_WIDTH_FIELDS,
        "properties.constantWidth",
    )
    if set(measurement) != _CONSTANT_WIDTH_FIELDS:
        raise ValueError("properties.constantWidth must contain value and unit")

    width = measurement["value"]
    if isinstance(width, bool) or not isinstance(width, (int, float)):
        raise ValueError("properties.constantWidth.value must be numeric")
    if isinstance(width, float) and not math.isfinite(width):
        raise ValueError("properties.constantWidth.value must be finite")
    if width <= 0:
        raise ValueError("properties.constantWidth.value must be positive")

    unit = measurement["unit"]
    if unit != "mm":
        raise ValueError("properties.constantWidth.unit must be mm")
    return width, unit


def deterministic_fact_id(
    document_id: str,
    source_revision: int,
    native_id: str,
    fact_kind: FactKind,
    predicate: str,
) -> str:
    canonical = "\n".join(
        [
            "autocad-design-fact-v1",
            document_id,
            str(source_revision),
            native_id,
            fact_kind.value,
            predicate,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DesignFactAdapter:
    """Validate Host-local AutoCAD snapshots and emit frozen Step 18 facts."""

    PRODUCER = "autocad.sidecar.design_fact_adapter.v1"
    HOST_TYPE = "autocad"

    def normalize_snapshot(self, payload: Mapping[str, Any]) -> NormalizedDesignFactBatch:
        batch = _require_mapping(payload, "snapshot")
        _reject_unknown(batch, _BATCH_FIELDS, "snapshot")
        missing = _BATCH_FIELDS - set(batch)
        if missing:
            raise ValueError(f"snapshot missing required fields: {sorted(missing)}")

        host_instance_id = _require_text(batch, "hostInstanceId")
        document_id = _require_text(batch, "documentId")
        revision = _require_revision(batch)
        entities = _require_entities(batch)

        host_ref = DesignFactHostRef(
            host_type=self.HOST_TYPE,
            host_instance_id=host_instance_id,
            document_id=document_id,
        )

        facts: list[NormalizedDesignFact] = []
        for raw_entity in entities:
            entity = _require_mapping(raw_entity, "entity")
            _reject_unknown(entity, _ENTITY_FIELDS, "entity")
            required = {"nativeId", "nativeKind", "layer"}
            missing_entity = required - set(entity)
            if missing_entity:
                raise ValueError(f"entity missing required fields: {sorted(missing_entity)}")

            native_id = _require_text(entity, "nativeId")
            native_kind = _require_text(entity, "nativeKind")
            layer = _require_text(entity, "layer")
            bounds = _validate_bounds(entity["bounds"]) if "bounds" in entity else None
            properties = (
                _require_mapping(entity["properties"], "properties")
                if "properties" in entity
                else None
            )
            if properties is not None:
                _reject_unknown(properties, _PROPERTY_FIELDS, "properties")
            constant_width = (
                _read_constant_width(properties["constantWidth"])
                if properties is not None and "constantWidth" in properties
                else None
            )

            subject = NativeSubjectRef(
                document_id=document_id,
                native_id=native_id,
                native_kind=native_kind,
            )
            provenance = (
                f"autocad://{host_instance_id}/{quote(document_id, safe='')}/{native_id}@{revision}",
            )

            facts.append(
                self._fact(
                    host_ref=host_ref,
                    subject=subject,
                    revision=revision,
                    fact_kind=FactKind.IDENTITY,
                    predicate="native_kind",
                    value=native_kind,
                    value_type=ValueType.STRING,
                    provenance=provenance,
                )
            )
            facts.append(
                self._fact(
                    host_ref=host_ref,
                    subject=subject,
                    revision=revision,
                    fact_kind=FactKind.CLASSIFICATION,
                    predicate="layer",
                    value=layer,
                    value_type=ValueType.STRING,
                    source_scheme="autocad.layer",
                    source_code=layer,
                    provenance=provenance,
                )
            )
            if bounds is not None:
                facts.append(
                    self._fact(
                        host_ref=host_ref,
                        subject=subject,
                        revision=revision,
                        fact_kind=FactKind.BOUNDS,
                        predicate="geometric_extents",
                        value=bounds,
                        value_type=ValueType.OBJECT,
                        provenance=provenance,
                    )
                )
            if constant_width is not None:
                width, unit = constant_width
                facts.append(
                    self._fact(
                        host_ref=host_ref,
                        subject=subject,
                        revision=revision,
                        fact_kind=FactKind.PROPERTY,
                        predicate="constant_width",
                        value=width,
                        value_type=ValueType.NUMBER,
                        unit=unit,
                        source_scheme="autocad.property",
                        source_code="LWPOLYLINE.ConstantWidth",
                        provenance=provenance,
                    )
                )

        return NormalizedDesignFactBatch(tuple(facts))

    def _fact(
        self,
        *,
        host_ref: DesignFactHostRef,
        subject: NativeSubjectRef,
        revision: int,
        fact_kind: FactKind,
        predicate: str,
        value: Any,
        value_type: ValueType,
        provenance: tuple[str, ...],
        unit: str | None = None,
        source_scheme: str | None = None,
        source_code: str | None = None,
    ) -> NormalizedDesignFact:
        return NormalizedDesignFact(
            fact_id=deterministic_fact_id(
                host_ref.document_id,
                revision,
                subject.native_id,
                fact_kind,
                predicate,
            ),
            producer=self.PRODUCER,
            host_ref=host_ref,
            source_revision=revision,
            subject_native_ref=subject,
            fact_kind=fact_kind,
            predicate=predicate,
            value=value,
            value_type=value_type,
            unit=unit,
            geometry_ref=None,
            source_scheme=source_scheme,
            source_code=source_code,
            provenance=provenance,
        )
