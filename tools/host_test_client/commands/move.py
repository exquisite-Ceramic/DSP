"""Command: move entities by (dx, dy, dz)."""

from __future__ import annotations

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from host_contracts.result import HostCommandResult


async def run(
    host: HostAdapter,
    handles: list[str],
    dx: float,
    dy: float,
    dz: float = 0.0,
    revision: int | None = None,
    idempotency_key: str | None = None,
) -> HostCommandResult:
    dispatcher = CommandDispatcher(host=host)
    return await dispatcher.move(
        handles,
        dx,
        dy,
        dz,
        idempotency_key=idempotency_key,
        revision=revision,
    )
