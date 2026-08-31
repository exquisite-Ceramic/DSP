"""Thin Revit-native snapshot to NormalizedDesignFact conversion."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

from design_fact_contracts import (
    DesignFactHostRef,
    FactKind,
    NativeSubjectRef,
    NormalizedDesignFact,
    NormalizedDesignFactBatch,
    ValueType,
)


_SNAPSHOT_FIELDS = {
    "document_id",
    "host_instance_id",
    "source_revision",
    "native_id",
    "native_kind",
    "builtin_category",
    "wall_thickness_mm",
}


def _require_text(payload: Mapping[str, Any], field: str) -> str:
    value = payload.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _require_revision(payload: Mapping[str, Any]) -> int:
    value = payload.get("source_revision")
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("source_revision must be a non-negative integer")
    return value


def _require_wall_thickness_mm(payload: Mapping[str, Any]) -> int | float:
    value = payload.get("wall_thickness_mm")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("wall_thickness_mm must be numeric")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("wall_thickness_mm must be finite")
    if value <= 0:
        raise ValueError("wall_thickness_mm must be positive")
    return value


def deterministic_fact_id(
    document_id: str,
    source_revision: int,
    native_id: str,
    fact_kind: FactKind,
    predicate: str,
) -> str:
    canonical = "\n".join(
        [
            "revit-design-fact-v1",
            document_id,
            str(source_revision),
            native_id,
            fact_kind.value,
            predicate,
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class DesignFactAdapter:
    """Validate one Revit wall snapshot and emit the frozen Step 18 facts."""

    PRODUCER = "revit.sidecar.design_fact_adapter.v1"
    HOST_TYPE = "revit"

    def normalize_snapshot(self, payload: Mapping[str, Any]) -> NormalizedDesignFactBatch:
        if not isinstance(payload, Mapping):
            raise ValueError("snapshot must be an object")

        unknown = set(payload) - _SNAPSHOT_FIELDS
        if unknown:
            raise ValueError(f"snapshot contains unknown fields: {sorted(unknown)}")
        missing = _SNAPSHOT_FIELDS - set(payload)
        if missing:
            raise ValueError(f"snapshot missing required fields: {sorted(missing)}")

        document_id = _require_text(payload, "document_id")
        host_instance_id = _require_text(payload, "host_instance_id")
        source_revision = _require_revision(payload)
        native_id = _require_text(payload, "native_id")
        native_kind = _require_text(payload, "native_kind")
        builtin_category = _require_text(payload, "builtin_category")
        wall_thickness_mm = _require_wall_thickness_mm(payload)

        host_ref = DesignFactHostRef(
            host_type=self.HOST_TYPE,
            host_instance_id=host_instance_id,
            document_id=document_id,
        )
        subject = NativeSubjectRef(
            document_id=document_id,
            native_id=native_id,
            native_kind=native_kind,
        )
        provenance = (
            f"revit://{host_instance_id}/{quote(document_id, safe='')}/"
            f"{quote(native_id, safe='')}@{source_revision}",
        )

        facts = (
            self._fact(
                host_ref=host_ref,
                subject=subject,
                revision=source_revision,
                fact_kind=FactKind.IDENTITY,
                predicate="native_kind",
                value=native_kind,
                value_type=ValueType.STRING,
                provenance=provenance,
            ),
            self._fact(
                host_ref=host_ref,
                subject=subject,
                revision=source_revision,
                fact_kind=FactKind.CLASSIFICATION,
                predicate="builtin_category",
                value=builtin_category,
                value_type=ValueType.STRING,
                source_scheme="revit.builtin_category",
                source_code=builtin_category,
                provenance=provenance,
            ),
            self._fact(
                host_ref=host_ref,
                subject=subject,
                revision=source_revision,
                fact_kind=FactKind.PROPERTY,
                predicate="wall_thickness",
                value=wall_thickness_mm,
                value_type=ValueType.NUMBER,
                unit="mm",
                source_scheme="revit.property",
                source_code="WallType.CompoundStructure.TotalWidth",
                provenance=provenance,
            ),
        )
        return NormalizedDesignFactBatch(facts)

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
