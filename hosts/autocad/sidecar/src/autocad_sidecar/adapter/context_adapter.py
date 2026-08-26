"""Context commands: current document and selection."""

from __future__ import annotations

import uuid

from host_contracts.command import HostCommand
from host_contracts.result import HostCommandResult

from autocad_sidecar.adapter.host_adapter import HostAdapter


class ContextAdapter:
    """Read-only context probes (command types: context.current_document,
    context.current_selection)."""

    def __init__(self, host: HostAdapter) -> None:
        self._host = host

    async def current_document(self) -> HostCommandResult:
        command = HostCommand(
            command_id=str(uuid.uuid4()),
            command_type="context.current_document",
        )
        return await self._host.send_command(command)

    async def current_selection(self) -> HostCommandResult:
        command = HostCommand(
            command_id=str(uuid.uuid4()),
            command_type="context.current_selection",
        )
        return await self._host.send_command(command)
