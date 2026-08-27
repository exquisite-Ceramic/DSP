"""Command: read the current document."""

from __future__ import annotations

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from host_contracts.result import HostCommandResult


async def run(host: HostAdapter) -> HostCommandResult:
    dispatcher = CommandDispatcher(host=host)
    return await dispatcher.current_document()
