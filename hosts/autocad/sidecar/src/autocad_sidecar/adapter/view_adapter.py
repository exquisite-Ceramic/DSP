"""View commands: zoom / fit."""

from __future__ import annotations

import uuid

from host_contracts.command import HostCommand
from host_contracts.result import HostCommandResult

from autocad_sidecar.adapter.host_adapter import HostAdapter


class ViewAdapter:
    """View-only commands. No model mutation."""

    def __init__(self, host: HostAdapter) -> None:
        self._host = host

    async def fit(self, handles: list[str] | None = None) -> HostCommandResult:
        command = HostCommand(
            command_id=str(uuid.uuid4()),
            mode="VIEW",
            operation="view.fit_entities",
            arguments={"handles": handles or []},
        )
        return await self._host.send_command(command)
