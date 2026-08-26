"""Command: move entities by (dx, dy, dz)."""

from __future__ import annotations

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from host_contracts.result import HostCommandResult


async def run(
    pipe_name: str,
    handles: list[str],
    dx: float,
    dy: float,
    dz: float = 0.0,
    revision: int | None = None,
    idempotency_key: str | None = None,
) -> HostCommandResult:
    host = HostAdapter(pipe_name=pipe_name)
    try:
        dispatcher = CommandDispatcher(host=host)
        return await dispatcher.move(
            handles,
            dx,
            dy,
            dz,
            idempotency_key=idempotency_key,
            revision=revision,
        )
    finally:
        await host.close()
