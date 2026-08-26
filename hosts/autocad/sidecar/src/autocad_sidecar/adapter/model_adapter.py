"""Model commands: mutating operations such as move."""

from __future__ import annotations

import uuid

from host_contracts.command import HostCommand
from host_contracts.result import HostCommandResult

from autocad_sidecar.adapter.host_adapter import HostAdapter


class ModelAdapter:
    """Model-mutating commands (command type: model.move).

    Callers must pass an idempotency key and the revision observed when the
    selection was read (ADR-003 / spec §7).
    """

    def __init__(self, host: HostAdapter) -> None:
        self._host = host

    async def move(
        self,
        handles: list[str],
        dx: float,
        dy: float,
        dz: float = 0.0,
        *,
        idempotency_key: str | None = None,
        revision: int | None = None,
    ) -> HostCommandResult:
        command = HostCommand(
            command_id=str(uuid.uuid4()),
            command_type="model.move",
            idempotency_key=idempotency_key or str(uuid.uuid4()),
            revision=revision,
            params={
                "handles": handles,
                "dx": dx,
                "dy": dy,
                "dz": dz,
            },
        )
        return await self._host.send_command(command)
