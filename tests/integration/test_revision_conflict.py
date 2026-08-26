"""Integration: stale revision is rejected with revision_conflict."""

import os

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.environ.get("AGENT_HOST_TEST") != "1",
        reason="requires live AutoCAD host (AGENT_HOST_TEST=1)",
    ),
]

from autocad_sidecar.adapter.host_adapter import HostAdapter  # noqa: E402
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher  # noqa: E402


@pytest.mark.asyncio
async def test_stale_revision_rejected():
    host = HostAdapter()
    try:
        dispatcher = CommandDispatcher(host=host)
        selection = await dispatcher.current_selection()
        assert selection.ok, selection.error

        handles = [r["handle"] for r in selection.payload.get("entityRefs", [])]
        if not handles:
            pytest.skip("nothing selected in the live drawing")

        stale = (selection.payload.get("revision") or 0) - 1
        result = await dispatcher.move(handles, 1.0, 0.0, revision=stale)
    finally:
        await host.close()

    assert not result.ok
    assert result.error is not None
    assert result.error.code == "revision_conflict"
