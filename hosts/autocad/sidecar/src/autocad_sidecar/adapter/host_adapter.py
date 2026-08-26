"""High-level host client: typed calls over the pipe transport."""

from __future__ import annotations

import uuid

from host_contracts.command import HostCommand
from host_contracts.envelope import RequestEnvelope, ResponseEnvelope
from host_contracts.result import HostCommandResult
from host_contracts.status import HostStatus

from autocad_sidecar.ipc.pipe_client import PipeClient
from autocad_sidecar.ipc.serializer import (
    bytes_to_response,
    payload_as_result,
    payload_as_status,
    request_to_bytes,
)


class HostAdapter:
    """Typed facade over the raw pipe. One instance per sidecar process."""

    def __init__(self, pipe_name: str = "EnterpriseDesignAgent") -> None:
        self.pipe_name = pipe_name
        self._client = PipeClient(pipe_name)

    # ---- raw envelope exchange ----

    async def _exchange(self, envelope: RequestEnvelope) -> ResponseEnvelope:
        await self._client.connect()
        response = await self._client.send(request_to_bytes(envelope))
        return bytes_to_response(response)

    def _command_envelope(self, command: HostCommand) -> RequestEnvelope:
        return RequestEnvelope(
            request_id=str(uuid.uuid4()),
            idempotency_key=command.idempotency_key,
            payload=command.to_dict(),
        )

    # ---- typed operations (used by adapters) ----

    async def send_command(self, command: HostCommand) -> HostCommandResult:
        envelope = self._command_envelope(command)
        response = await self._exchange(envelope)
        if response.status == "ERROR":
            return HostCommandResult(
                command_id=command.command_id,
                status="ERROR",
                error=response.error,
            )
        return payload_as_result(response)

    async def get_status(self) -> HostStatus:
        probe = RequestEnvelope(request_id=str(uuid.uuid4()), payload={})
        response = await self._exchange(probe)
        return payload_as_status(response)

    async def close(self) -> None:
        await self._client.close()
