from __future__ import annotations

import os
import uuid
from collections.abc import Mapping

import pytest

from autocad_live_host import live_autocad_host_adapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from design_fact_contracts import FactKind, NormalizedDesignFactBatch

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AGENT_HOST_TEST") != "1",
        reason="requires live AutoCAD host (AGENT_HOST_TEST=1)",
    ),
]

_DISTANCE_MM = 300.0


def _one_fact(
    batch: NormalizedDesignFactBatch,
    kind: FactKind,
    predicate: str,
):
    matches = [
        fact
        for fact in batch.facts
        if fact.fact_kind is kind and fact.predicate == predicate
    ]
    assert len(matches) == 1, f"expected exactly one {kind.value}:{predicate} fact"
    return matches[0]


def _bounds(batch: NormalizedDesignFactBatch) -> dict[str, dict[str, float]]:
    raw = _one_fact(batch, FactKind.BOUNDS, "geometric_extents").value
    assert isinstance(raw, Mapping)
    minimum = raw.get("min")
    maximum = raw.get("max")
    assert isinstance(minimum, Mapping)
    assert isinstance(maximum, Mapping)
    return {
        "min": {axis: float(minimum[axis]) for axis in ("x", "y", "z")},
        "max": {axis: float(maximum[axis]) for axis in ("x", "y", "z")},
    }


def _layer(batch: NormalizedDesignFactBatch) -> str:
    return str(_one_fact(batch, FactKind.CLASSIFICATION, "layer").value)


def _native_kind(batch: NormalizedDesignFactBatch) -> str:
    return str(_one_fact(batch, FactKind.IDENTITY, "native_kind").value)


def _side_point(bounds: Mapping[str, Mapping[str, float]]) -> dict[str, float | str]:
    minimum = bounds["min"]
    maximum = bounds["max"]
    width = maximum["x"] - minimum["x"]
    height = maximum["y"] - minimum["y"]
    assert abs(width - height) > 1e-6, "Step36 fixture must be axis-dominant"

    cx = (minimum["x"] + maximum["x"]) / 2.0
    cy = (minimum["y"] + maximum["y"]) / 2.0
    cz = (minimum["z"] + maximum["z"]) / 2.0
    if height > width:
        return {
            "x": maximum["x"] + 4 * _DISTANCE_MM,
            "y": cy,
            "z": cz,
            "unit": "mm",
        }
    return {
        "x": cx,
        "y": maximum["y"] + 4 * _DISTANCE_MM,
        "z": cz,
        "unit": "mm",
    }


@pytest.mark.asyncio
async def test_live_autocad_offset_creates_one_awall_without_mutating_source() -> None:
    host = live_autocad_host_adapter()

    try:
        dispatcher = CommandDispatcher(host)
        document = await dispatcher.current_document()
        assert document.ok, document.error
        revision_before = int((document.payload or {}).get("revision") or 0)

        selection = await dispatcher.current_selection()
        assert selection.ok, selection.error
        refs = (selection.payload or {}).get("entityRefs", [])
        assert len(refs) == 1, "select exactly one Step36 A-WALL Polyline/LWPOLYLINE"
        selected = refs[0]
        selected_type = str(selected.get("native_type", "")).upper()
        assert selected_type in {"POLYLINE", "LWPOLYLINE"}
        source_handle = str(selected["native_id"])

        source_before = await dispatcher.extract_design_facts([source_handle])
        source_layer = _layer(source_before)
        source_native_kind = _native_kind(source_before).upper()
        source_bounds = _bounds(source_before)
        assert source_layer == "A-WALL", "Step36 source fixture must be on layer A-WALL"
        assert source_native_kind in {"POLYLINE", "LWPOLYLINE"}

        width_fact = _one_fact(source_before, FactKind.PROPERTY, "constant_width")
        assert width_fact.unit == "mm", "Step36 fixture requires INSUNITS=4 (millimetres)"
        assert float(width_fact.value) > 0.0

        side_point = _side_point(source_bounds)
        result = await dispatcher.offset(
            [source_handle],
            {"value": _DISTANCE_MM, "unit": "mm"},
            side_point,
            idempotency_key=f"step36-live-offset-{uuid.uuid4()}",
            revision=revision_before,
        )

        # Mandatory Task8 live RED on the current Step34 plugin occurs here:
        # the request reaches Host but offset.v1 is not registered yet.
        assert result.ok, result.error
        assert result.verification is not None
        assert result.verification.get("ok") is True
        assert result.revision_after == revision_before + 1

        payload = result.payload or {}
        created_ref = payload.get("createdEntityRef")
        assert isinstance(created_ref, Mapping), "offset must return exactly one createdEntityRef"
        created_handle = str(created_ref.get("native_id") or "")
        created_type = str(created_ref.get("native_type") or "").upper()
        assert created_handle
        assert created_handle != source_handle
        assert created_type in {"POLYLINE", "LWPOLYLINE"}

        document_after = await dispatcher.current_document()
        assert document_after.ok, document_after.error
        assert int((document_after.payload or {}).get("revision") or 0) == revision_before + 1

        source_after = await dispatcher.extract_design_facts([source_handle])
        created_after = await dispatcher.extract_design_facts([created_handle])
    finally:
        await host.close()

    assert _layer(source_after) == source_layer
    assert _native_kind(source_after).upper() == source_native_kind
    assert _bounds(source_after) == source_bounds

    assert _layer(created_after) == "A-WALL"
    assert _native_kind(created_after).upper() in {"POLYLINE", "LWPOLYLINE"}
