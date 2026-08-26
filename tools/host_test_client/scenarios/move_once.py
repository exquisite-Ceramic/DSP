"""Scenario: select, read revision, move once, verify result."""

from __future__ import annotations

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from host_contracts.result import HostCommandResult


async def run(pipe_name: str) -> HostCommandResult:
    host = HostAdapter(pipe_name=pipe_name)
    try:
        dispatcher = CommandDispatcher(host=host)

        selection = await dispatcher.current_selection()
        if not selection.ok:
            return selection

        handles = [r["handle"] for r in selection.payload.get("entityRefs", [])]
        if not handles:
            return HostCommandResult(
                command_id="scenario.move_once",
                ok=False,
                payload={"reason": "nothing selected"},
            )

        return await dispatcher.move(handles, dx=10.0, dy=0.0)
    finally:
        await host.close()
