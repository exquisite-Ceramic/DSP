"""Host-native interaction commands normalized to provider-neutral results."""

from __future__ import annotations

import uuid

from host_contracts.command import HostCommand
from host_contracts.result import HostCommandResult

from autocad_sidecar.adapter.host_adapter import HostAdapter


class InteractionAdapter:
    """Issue explicit Host Canvas interaction commands without model mutation."""

    def __init__(self, host: HostAdapter) -> None:
        self._host = host

    async def pick_point(
        self,
        *,
        document_id: str,
        idempotency_key: str,
        prompt: str | None = None,
    ) -> HostCommandResult:
        arguments = {"prompt": prompt} if prompt is not None else {}
        command = HostCommand(
            command_id=str(uuid.uuid4()),
            document_id=document_id,
            mode="INTERACTION",
            operation="interaction.pick_point",
            arguments=arguments,
            idempotency_key=idempotency_key,
        )
        return await self._host.send_command(command)
