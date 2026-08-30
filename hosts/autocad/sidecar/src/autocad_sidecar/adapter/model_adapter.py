"""Model commands: mutating operations such as move."""

from __future__ import annotations

import uuid

from host_contracts.command import HostCommand
from host_contracts.entity_ref import HostEntityRef
from host_contracts.result import HostCommandResult

from autocad_sidecar.adapter.host_adapter import HostAdapter


class ModelAdapter:
    """Model-mutating commands emitted with the canonical HostCommand wire shape."""

    def __init__(self, host: HostAdapter) -> None:
        self._host = host

    async def move(
        self,
        handles: list[str],
        dx: float,
        dy: float,
        dz: float = 0.0,
        *,
        document_id: str,
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
            document_id=document_id,
            mode="EXECUTE",
            operation="move.v1",
            target_native_refs=[
                HostEntityRef(document_id=document_id, native_id=handle)
                for handle in handles
            ],
            arguments={
                "displacement": {
                    "x": dx,
                    "y": dy,
                    "z": dz,
                }
            },
            preconditions=preconditions,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
        return await self._host.send_command(command)

    async def set_wall_thickness(
        self,
        handles: list[str],
        thickness_mm: float,
        *,
        document_id: str,
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
            document_id=document_id,
            mode="EXECUTE",
            operation="set_wall_thickness.v1",
            target_native_refs=[
                HostEntityRef(document_id=document_id, native_id=handle)
                for handle in handles
            ],
            arguments={
                "thickness": {
                    "value": thickness_mm,
                    "unit": "mm",
                }
            },
            preconditions=preconditions,
            idempotency_key=idempotency_key or str(uuid.uuid4()),
        )
        return await self._host.send_command(command)
