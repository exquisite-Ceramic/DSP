"""JSON (de)serialization of contract types on the sidecar (v1.0 envelopes)."""

from __future__ import annotations

import json

from host_contracts.command import HostCommand
from host_contracts.envelope import RequestEnvelope, ResponseEnvelope
from host_contracts.result import HostCommandResult
from host_contracts.status import HostStatus


def request_to_bytes(envelope: RequestEnvelope) -> bytes:
    return json.dumps(envelope.to_dict(), ensure_ascii=False).encode("utf-8")


def bytes_to_response(data: bytes) -> ResponseEnvelope:
    return ResponseEnvelope.from_dict(json.loads(data.decode("utf-8")))


def payload_as_command(envelope: RequestEnvelope) -> HostCommand:
    return HostCommand.from_dict(envelope.payload)


def payload_as_result(envelope: ResponseEnvelope) -> HostCommandResult:
    return HostCommandResult.from_dict(envelope.result or {})


def payload_as_status(envelope: ResponseEnvelope) -> HostStatus:
    return HostStatus.from_dict(envelope.result or {})
