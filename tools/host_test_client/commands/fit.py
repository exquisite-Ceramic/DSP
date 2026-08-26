"""Command: zoom extents (fit)."""

from __future__ import annotations

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from host_contracts.result import HostCommandResult


async def run(pipe_name: str, handles: list[str] | None = None) -> HostCommandResult:
    host = HostAdapter(pipe_name=pipe_name)
    try:
        dispatcher = CommandDispatcher(host=host)
        return await dispatcher.fit(handles)
    finally:
        await host.close()
