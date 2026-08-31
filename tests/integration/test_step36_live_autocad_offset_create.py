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


def _facts(
    batch: NormalizedDesignFactBatch,
    kind: FactKind,
    predicate: str,
):
    return [
        fact
        for fact in batch.facts
        if fact.fact_kind is kind and fact.predicate == predicate
    ]


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


async def _selected_source(
    dispatcher: CommandDispatcher,
) -> tuple[str, int, NormalizedDesignFactBatch]:
    document = await dispatcher.current_document()
    assert document.ok, document.error
    revision = int((document.payload or {}).get("revision") or 0)

    selection = await dispatcher.current_selection()
    assert selection.ok, selection.error
    refs = (selection.payload or {}).get("entityRefs", [])
    assert len(refs) == 1, "select exactly one Step36 A-WALL Polyline/LWPOLYLINE"
    selected = refs[0]
    selected_type = str(selected.get("native_type", "")).upper()
    assert selected_type in {"POLYLINE", "LWPOLYLINE"}
    source_handle = str(selected["native_id"])

    source = await dispatcher.extract_design_facts([source_handle])
    assert _layer(source) == "A-WALL", "Step36 source fixture must be on layer A-WALL"
    assert _native_kind(source).upper() in {"POLYLINE", "LWPOLYLINE"}
    _bounds(source)
    return source_handle, revision, source


def _assert_mm_fixture(source: NormalizedDesignFactBatch) -> None:
    width_fact = _one_fact(source, FactKind.PROPERTY, "constant_width")
    assert width_fact.unit == "mm", "Step36 fixture requires INSUNITS=4 (millimetres)"
    assert float(width_fact.value) > 0.0


@pytest.mark.asyncio
async def test_live_autocad_offset_creates_one_awall_without_mutating_source() -> None:
    host = live_autocad_host_adapter()

    try:
        dispatcher = CommandDispatcher(host)
        source_handle, revision_before, source_before = await _selected_source(dispatcher)
        source_layer = _layer(source_before)
        source_native_kind = _native_kind(source_before).upper()
        source_bounds = _bounds(source_before)
        _assert_mm_fixture(source_before)

        side_point = _side_point(source_bounds)
        result = await dispatcher.offset(
            [source_handle],
            {"value": _DISTANCE_MM, "unit": "mm"},
            side_point,
            idempotency_key=f"step36-live-offset-{uuid.uuid4()}",
            revision=revision_before,
        )

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


@pytest.mark.asyncio
async def test_live_autocad_offset_replay_returns_same_created_ref_without_second_mutation(
) -> None:
    host = live_autocad_host_adapter()

    try:
        dispatcher = CommandDispatcher(host)
        source_handle, revision_before, source_before = await _selected_source(dispatcher)
        source_bounds = _bounds(source_before)
        _assert_mm_fixture(source_before)
        side_point = _side_point(source_bounds)
        idempotency_key = f"step36-live-offset-replay-{uuid.uuid4()}"

        first = await dispatcher.offset(
            [source_handle],
            {"value": _DISTANCE_MM, "unit": "mm"},
            side_point,
            idempotency_key=idempotency_key,
            revision=revision_before,
        )
        replay = await dispatcher.offset(
            [source_handle],
            {"value": _DISTANCE_MM, "unit": "mm"},
            side_point,
            idempotency_key=idempotency_key,
            revision=revision_before,
        )

        assert first.ok, first.error
        assert first.replayed is False
        assert first.revision_after == revision_before + 1
        assert replay.ok, replay.error
        assert replay.replayed is True
        assert replay.revision_after == first.revision_after
        assert (replay.payload or {}).get("createdEntityRef") == (
            first.payload or {}
        ).get("createdEntityRef")

        document_after = await dispatcher.current_document()
        assert document_after.ok, document_after.error
        assert int((document_after.payload or {}).get("revision") or 0) == revision_before + 1
        source_after = await dispatcher.extract_design_facts([source_handle])
    finally:
        await host.close()

    assert _bounds(source_after) == source_bounds


@pytest.mark.asyncio
async def test_live_autocad_offset_rejects_stale_revision_without_mutation() -> None:
    host = live_autocad_host_adapter()

    try:
        dispatcher = CommandDispatcher(host)
        source_handle, revision_before, source_before = await _selected_source(dispatcher)
        source_bounds = _bounds(source_before)
        _assert_mm_fixture(source_before)

        result = await dispatcher.offset(
            [source_handle],
            {"value": _DISTANCE_MM, "unit": "mm"},
            _side_point(source_bounds),
            idempotency_key=f"step36-live-offset-stale-{uuid.uuid4()}",
            revision=revision_before + 1,
        )
        assert not result.ok
        assert result.error is not None
        assert result.error.error_code == "REVISION_CONFLICT"

        document_after = await dispatcher.current_document()
        assert document_after.ok, document_after.error
        assert int((document_after.payload or {}).get("revision") or 0) == revision_before
        source_after = await dispatcher.extract_design_facts([source_handle])
    finally:
        await host.close()

    assert _bounds(source_after) == source_bounds
    assert _layer(source_after) == _layer(source_before)


@pytest.mark.asyncio
async def test_live_autocad_offset_rejects_non_mm_document_before_mutation() -> None:
    host = live_autocad_host_adapter()

    try:
        dispatcher = CommandDispatcher(host)
        source_handle, revision_before, source_before = await _selected_source(dispatcher)
        source_bounds = _bounds(source_before)
        width_facts = _facts(source_before, FactKind.PROPERTY, "constant_width")
        assert not width_facts, (
            "set INSUNITS to a non-mm value before running this negative live test"
        )

        result = await dispatcher.offset(
            [source_handle],
            {"value": _DISTANCE_MM, "unit": "mm"},
            _side_point(source_bounds),
            idempotency_key=f"step36-live-offset-non-mm-{uuid.uuid4()}",
            revision=revision_before,
        )
        assert not result.ok
        assert result.error is not None
        assert result.error.error_code == "UNSUPPORTED_DOCUMENT_UNITS"

        document_after = await dispatcher.current_document()
        assert document_after.ok, document_after.error
        assert int((document_after.payload or {}).get("revision") or 0) == revision_before
        source_after = await dispatcher.extract_design_facts([source_handle])
    finally:
        await host.close()

    assert _bounds(source_after) == source_bounds
    assert _layer(source_after) == _layer(source_before)
