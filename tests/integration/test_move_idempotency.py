"""Integration: idempotent move (same key twice -> replay)."""

import os
import uuid

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
async def test_move_is_idempotent_with_same_key():
    host = HostAdapter()
    try:
        dispatcher = CommandDispatcher(host=host)
        selection = await dispatcher.current_selection()
        assert selection.ok, selection.error

        handles = [r["native_id"] for r in selection.payload.get("entityRefs", [])]
        if not handles:
            pytest.skip("nothing selected in the live drawing")

        key = str(uuid.uuid4())
        first = await dispatcher.move(handles, 5.0, 0.0, idempotency_key=key)
        second = await dispatcher.move(handles, 5.0, 0.0, idempotency_key=key)
    finally:
        await host.close()

    assert first.ok, first.error
    assert second.ok, second.error
    assert second.replayed is True, "second call with the same key must be a replay"
    assert first.payload.get("moved") == second.payload.get("moved")
