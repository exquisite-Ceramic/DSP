"""High-level typed host client over a transport-neutral bytes exchange."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from host_contracts.command import HostCommand
from host_contracts.envelope import RequestEnvelope, ResponseEnvelope, parse_utc
from host_contracts.result import HostCommandResult
from host_contracts.status import HostStatus

from autocad_sidecar.ipc.base import FrameTransport
from autocad_sidecar.ipc.serializer import (
    bytes_to_response,
    payload_as_result,
    payload_as_status,
    request_to_bytes,
)
from autocad_sidecar.ipc.transport import PipeTransport


class HostAdapter:
    """Typed facade over an injected bytes-in/bytes-out host transport."""

    def __init__(
        self,
        pipe_name: str = "EnterpriseDesignAgent",
        *,
        transport: FrameTransport | None = None,
    ) -> None:
        self.pipe_name = pipe_name
        self._transport: FrameTransport = transport or PipeTransport(pipe_name)
        self._opened = False

    async def _ensure_open(self) -> None:
        if self._opened:
            return
        await self._transport.open()
        self._opened = True

    def _timeout_for(self, envelope: RequestEnvelope) -> float | None:
        remaining_s: float | None = None
        if envelope.deadline_at is not None:
            remaining_s = (
                parse_utc(envelope.deadline_at) - datetime.now(timezone.utc)
            ).total_seconds()
            if remaining_s <= 0:
                raise TimeoutError(
                    f"request deadline has expired: {envelope.deadline_at}"
                )

        transport_max = getattr(self._transport, "max_timeout_s", None)
        candidates = [value for value in (remaining_s, transport_max) if value is not None]
        return min(candidates) if candidates else None

    # ---- raw envelope exchange ----

    async def _exchange(self, envelope: RequestEnvelope) -> ResponseEnvelope:
        # Preflight before even opening the transport so an already-expired
        # business request cannot cause a Ping or other network send.
        self._timeout_for(envelope)
        await self._ensure_open()

        # Opening a transport may itself take time; recompute before Dispatch.
        timeout_s = self._timeout_for(envelope)
        response = await self._transport.exchange(
            request_to_bytes(envelope),
            timeout_s=timeout_s,
        )
        return bytes_to_response(response)

    def _command_envelope(self, command: HostCommand) -> RequestEnvelope:
        return RequestEnvelope(
            request_id=str(uuid.uuid4()),
            deadline_at=command.deadline_at,
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
        await self._transport.close()
        self._opened = False
