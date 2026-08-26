"""Command: read the current selection."""

from __future__ import annotations

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from host_contracts.result import HostCommandResult


async def run(pipe_name: str) -> HostCommandResult:
    host = HostAdapter(pipe_name=pipe_name)
    try:
        dispatcher = CommandDispatcher(host=host)
        return await dispatcher.current_selection()
    finally:
        await host.close()
