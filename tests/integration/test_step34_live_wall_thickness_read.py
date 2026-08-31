from __future__ import annotations

import os

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


@pytest.mark.asyncio
async def test_live_lwpolyline_constant_width_is_normalized_as_mm_property() -> None:
    pipe_name = _discover_pipe_name()
    host = HostAdapter(
        pipe_name=pipe_name,
        transport=PipeTransport(pipe_name),
    )

    try:
        dispatcher = CommandDispatcher(host)
        selection = await dispatcher.current_selection()
        assert selection.ok, selection.error

        refs = (selection.payload or {}).get("entityRefs", [])
        assert refs, "select the Step34 LWPOLYLINE fixture in AutoCAD"
        assert any(
            str(ref.get("native_type", "")).upper() in {"POLYLINE", "LWPOLYLINE"}
            for ref in refs
        ), "selected entity must include the Step34 LWPOLYLINE fixture"

        handles = [str(ref["native_id"]) for ref in refs]
        batch = await dispatcher.extract_design_facts(handles)
    finally:
        await host.close()

    width_facts = [
        fact
        for fact in batch.facts
        if fact.fact_kind is FactKind.PROPERTY and fact.predicate == "constant_width"
    ]
    assert len(width_facts) == 1, (
        "expected one ConstantWidth property fact from the selected AutoCAD LWPOLYLINE"
    )

    width_fact = width_facts[0]
    assert width_fact.value == 200.0
    assert width_fact.unit == "mm"
    assert width_fact.source_scheme == "autocad.property"
    assert width_fact.source_code == "LWPOLYLINE.ConstantWidth"
