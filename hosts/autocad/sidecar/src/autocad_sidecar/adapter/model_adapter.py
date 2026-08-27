"""Model commands: mutating operations such as move."""

from __future__ import annotations

import uuid

from host_contracts.command import HostCommand
from host_contracts.result import HostCommandResult

from autocad_sidecar.adapter.host_adapter import HostAdapter


class ModelAdapter:
    """Model-mutating commands emitted with the current HostCommand fields."""

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
        preconditions = (
            [{"type": "revision", "expected": revision}]
            if revision is not None
            else None
        )
        command = HostCommand(
            command_id=str(uuid.uuid4()),
            mode="EXECUTE",
            operation="move.v1",
            arguments={
                "handles": handles,
                "dx": dx,
                "dy": dy,
                "dz": dz,
            },
            preconditions=preconditions,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
        return await self._host.send_command(command)
