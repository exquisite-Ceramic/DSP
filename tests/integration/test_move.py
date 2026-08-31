"""Integration: move.v1 on a live host."""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AGENT_HOST_TEST") != "1",
        reason="requires live AutoCAD host (AGENT_HOST_TEST=1)",
    ),
]

from autocad_live_host import live_autocad_host_adapter  # noqa: E402
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher  # noqa: E402


@pytest.mark.asyncio
async def test_move_selected_entities():
    host = live_autocad_host_adapter()
    try:
        dispatcher = CommandDispatcher(host=host)
        selection = await dispatcher.current_selection()
        assert selection.ok, selection.error

        handles = [r["native_id"] for r in selection.payload.get("entityRefs", [])]
        if not handles:
            pytest.skip("nothing selected in the live drawing")

        result = await dispatcher.move(handles, dx=10.0, dy=0.0)
    finally:
        await host.close()

    assert result.ok, result.error
    assert result.payload.get("moved") == len(handles)
    assert result.verification is not None and result.verification.get("ok") is True
