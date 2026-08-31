from __future__ import annotations

import os
import uuid

import pytest

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from autocad_sidecar.ipc.transport import PipeTransport
from design_fact_contracts import FactKind

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AGENT_HOST_TEST") != "1",
        reason="requires live AutoCAD host (AGENT_HOST_TEST=1)",
    ),
]

_PIPE_PREFIX = "EnterpriseDesignAgent."
_PIPE_GLOB = rf"\\.\pipe\{_PIPE_PREFIX}*"


def _discover_pipe_name() -> str:
    if os.name != "nt":
        pytest.skip("live AutoCAD named-pipe test requires Windows")

    import win32api

    entries = win32api.FindFiles(_PIPE_GLOB)
    names = sorted(
        {
            str(entry[8])
            for entry in entries
            if len(entry) > 8 and str(entry[8]).startswith(_PIPE_PREFIX)
        }
    )
    if not names:
        raise AssertionError("no running AutoCAD AgentHost named pipe found")
    if len(names) > 1:
        raise AssertionError(
            "multiple AutoCAD AgentHost named pipes found: " + ", ".join(names)
        )
    return names[0]


async def _selected_fixture(dispatcher: CommandDispatcher) -> tuple[list[str], int]:
    document = await dispatcher.current_document()
    assert document.ok, document.error
    revision = int((document.payload or {}).get("revision") or 0)

    selection = await dispatcher.current_selection()
    assert selection.ok, selection.error
    refs = (selection.payload or {}).get("entityRefs", [])
    assert len(refs) == 1, "select exactly one Step34 A-WALL LWPOLYLINE fixture"
    assert str(refs[0].get("native_type", "")).upper() in {"POLYLINE", "LWPOLYLINE"}

    handles = [str(refs[0]["native_id"])]
    batch = await dispatcher.extract_design_facts(handles)

    layers = [
        fact
        for fact in batch.facts
        if fact.fact_kind is FactKind.CLASSIFICATION and fact.predicate == "layer"
    ]
    assert len(layers) == 1
    assert layers[0].value == "A-WALL", "Step34 fixture must be on layer A-WALL"

    widths = [
        fact
        for fact in batch.facts
        if fact.fact_kind is FactKind.PROPERTY and fact.predicate == "constant_width"
    ]
    assert len(widths) == 1
    assert widths[0].value == 200.0, "reset Step34 fixture Global Width to 200 before this test"
    assert widths[0].unit == "mm"
    return handles, revision


async def _selected_current_mm_fixture(
    dispatcher: CommandDispatcher,
) -> tuple[list[str], int, float]:
    document = await dispatcher.current_document()
    assert document.ok, document.error
    revision = int((document.payload or {}).get("revision") or 0)

    selection = await dispatcher.current_selection()
    assert selection.ok, selection.error
    refs = (selection.payload or {}).get("entityRefs", [])
    assert len(refs) == 1, "select exactly one Step34 A-WALL LWPOLYLINE fixture"
    assert str(refs[0].get("native_type", "")).upper() in {"POLYLINE", "LWPOLYLINE"}

    handles = [str(refs[0]["native_id"])]
    batch = await dispatcher.extract_design_facts(handles)
    layers = [
        fact
        for fact in batch.facts
        if fact.fact_kind is FactKind.CLASSIFICATION and fact.predicate == "layer"
    ]
    assert len(layers) == 1
    assert layers[0].value == "A-WALL", "Step34 fixture must be on layer A-WALL"

    widths = [
        fact
        for fact in batch.facts
        if fact.fact_kind is FactKind.PROPERTY and fact.predicate == "constant_width"
    ]
    assert len(widths) == 1, "Step34 negative fixture requires INSUNITS=4 (millimetres)"
    assert widths[0].unit == "mm"
    return handles, revision, float(widths[0].value)


@pytest.mark.asyncio
async def test_live_wall_thickness_mutates_200_to_300_and_advances_revision() -> None:
    pipe_name = _discover_pipe_name()
    host = HostAdapter(pipe_name=pipe_name, transport=PipeTransport(pipe_name))

    try:
        dispatcher = CommandDispatcher(host)
        handles, revision_before = await _selected_fixture(dispatcher)

        result = await dispatcher.set_wall_thickness(
            handles,
            300.0,
            idempotency_key=f"step34-live-wall-thickness-{uuid.uuid4()}",
            revision=revision_before,
        )
        assert result.ok, result.error
        assert result.verification is not None
        assert result.verification.get("ok") is True
        assert result.revision_after == revision_before + 1

        post = await dispatcher.extract_design_facts(handles)
    finally:
        await host.close()

    widths = [
        fact
        for fact in post.facts
        if fact.fact_kind is FactKind.PROPERTY and fact.predicate == "constant_width"
    ]
    assert len(widths) == 1
    assert widths[0].value == 300.0
    assert widths[0].unit == "mm"


@pytest.mark.asyncio
async def test_live_wall_thickness_rejects_stale_revision_without_mutation() -> None:
    pipe_name = _discover_pipe_name()
    host = HostAdapter(pipe_name=pipe_name, transport=PipeTransport(pipe_name))

    try:
        dispatcher = CommandDispatcher(host)
        handles, revision_before, width_before = await _selected_current_mm_fixture(dispatcher)

        result = await dispatcher.set_wall_thickness(
            handles,
            width_before + 25.0,
            idempotency_key=f"step34-live-stale-{uuid.uuid4()}",
            revision=revision_before + 1,
        )
        assert not result.ok
        assert result.error is not None
        assert result.error.error_code == "REVISION_CONFLICT"

        document_after = await dispatcher.current_document()
        assert document_after.ok, document_after.error
        assert int((document_after.payload or {}).get("revision") or 0) == revision_before

        post = await dispatcher.extract_design_facts(handles)
    finally:
        await host.close()

    widths = [
        fact
        for fact in post.facts
        if fact.fact_kind is FactKind.PROPERTY and fact.predicate == "constant_width"
    ]
    assert len(widths) == 1
    assert widths[0].value == width_before
    assert widths[0].unit == "mm"


@pytest.mark.asyncio
async def test_live_wall_thickness_rejects_unsupported_document_units_before_mutation() -> None:
    pipe_name = _discover_pipe_name()
    host = HostAdapter(pipe_name=pipe_name, transport=PipeTransport(pipe_name))

    try:
        dispatcher = CommandDispatcher(host)
        document = await dispatcher.current_document()
        assert document.ok, document.error
        revision_before = int((document.payload or {}).get("revision") or 0)

        selection = await dispatcher.current_selection()
        assert selection.ok, selection.error
        refs = (selection.payload or {}).get("entityRefs", [])
        assert len(refs) == 1, "select exactly one Step34 A-WALL LWPOLYLINE fixture"
        assert str(refs[0].get("native_type", "")).upper() in {"POLYLINE", "LWPOLYLINE"}
        handles = [str(refs[0]["native_id"])]

        before = await dispatcher.extract_design_facts(handles)
        layers = [
            fact
            for fact in before.facts
            if fact.fact_kind is FactKind.CLASSIFICATION and fact.predicate == "layer"
        ]
        assert len(layers) == 1
        assert layers[0].value == "A-WALL", "Step34 fixture must be on layer A-WALL"

        widths = [
            fact
            for fact in before.facts
            if fact.fact_kind is FactKind.PROPERTY and fact.predicate == "constant_width"
        ]
        assert not widths, "set INSUNITS to a non-mm value before running this negative live test"

        bounds_before = [
            fact.value
            for fact in before.facts
            if fact.fact_kind is FactKind.BOUNDS and fact.predicate == "geometric_extents"
        ]
        assert len(bounds_before) == 1

        result = await dispatcher.set_wall_thickness(
            handles,
            350.0,
            idempotency_key=f"step34-live-unsupported-units-{uuid.uuid4()}",
            revision=revision_before,
        )
        assert not result.ok
        assert result.error is not None
        assert result.error.error_code == "UNSUPPORTED_DOCUMENT_UNITS"

        document_after = await dispatcher.current_document()
        assert document_after.ok, document_after.error
        assert int((document_after.payload or {}).get("revision") or 0) == revision_before

        after = await dispatcher.extract_design_facts(handles)
    finally:
        await host.close()

    bounds_after = [
        fact.value
        for fact in after.facts
        if fact.fact_kind is FactKind.BOUNDS and fact.predicate == "geometric_extents"
    ]
    assert bounds_after == bounds_before
