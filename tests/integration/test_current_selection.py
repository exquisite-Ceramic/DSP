"""Integration: current selection round-trip against a live host.

Requires a running AutoCAD + plugin + sidecar; opt in with:
    AGENT_HOST_TEST=1 pytest -m integration
"""

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
async def test_current_selection_returns_entity_refs():
    host = HostAdapter()
    try:
        dispatcher = CommandDispatcher(host=host)
        result = await dispatcher.current_selection()
    finally:
        await host.close()

    assert result.ok, result.error
    refs = result.payload.get("entityRefs", [])
    for entity_ref in refs:
        assert entity_ref["document_id"]
        assert entity_ref["native_id"]
