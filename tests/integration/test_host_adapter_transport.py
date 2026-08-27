import json
from datetime import datetime, timedelta, timezone

import pytest

from autocad_sidecar.adapter.host_adapter import HostAdapter
from host_contracts.command import HostCommand


class FakeTransport:
    def __init__(self, *, max_timeout_s: float | None = None):
        self.max_timeout_s = max_timeout_s
        self.open_count = 0
        self.payloads: list[bytes] = []
        self.timeouts: list[float | None] = []
        self.closed = False

    async def open(self) -> None:
        self.open_count += 1

    async def exchange(self, payload: bytes, *, timeout_s: float | None = None) -> bytes:
        self.payloads.append(payload)
        self.timeouts.append(timeout_s)
        request_id = json.loads(payload)["request_id"]
        return json.dumps({
            "request_id": request_id,
            "status": "OK",
            "result": {"command_id": "cmd-1", "status": "OK"},
        }).encode()

    async def close(self) -> None:
        self.closed = True


def _deadline(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) + delta).isoformat().replace("+00:00", "Z")


@pytest.mark.asyncio
async def test_host_adapter_uses_injected_transport():
    transport = FakeTransport()
    adapter = HostAdapter(transport=transport)
    result = await adapter.send_command(HostCommand(
        command_id="cmd-1",
        mode="READ",
        operation="context.current_document",
    ))
    assert result.command_id == "cmd-1"
    assert transport.open_count == 1
    assert len(transport.payloads) == 1
    await adapter.close()
    assert transport.closed


@pytest.mark.asyncio
async def test_host_adapter_caps_timeout_at_transport_maximum():
    transport = FakeTransport(max_timeout_s=3.0)
    adapter = HostAdapter(transport=transport)

    await adapter.send_command(HostCommand(
        command_id="cmd-1",
        mode="READ",
        operation="context.current_document",
        deadline_at=_deadline(timedelta(seconds=30)),
    ))

    assert transport.timeouts == [3.0]


@pytest.mark.asyncio
async def test_host_adapter_uses_remaining_business_deadline_when_earlier():
    transport = FakeTransport(max_timeout_s=30.0)
    adapter = HostAdapter(transport=transport)

    await adapter.send_command(HostCommand(
        command_id="cmd-1",
        mode="READ",
        operation="context.current_document",
        deadline_at=_deadline(timedelta(seconds=2)),
    ))

    assert len(transport.timeouts) == 1
    timeout_s = transport.timeouts[0]
    assert timeout_s is not None
    assert 0 < timeout_s <= 2.0


@pytest.mark.asyncio
async def test_expired_business_deadline_fails_before_transport_open():
    transport = FakeTransport(max_timeout_s=30.0)
    adapter = HostAdapter(transport=transport)

    with pytest.raises(TimeoutError, match="deadline"):
        await adapter.send_command(HostCommand(
            command_id="cmd-1",
            mode="READ",
            operation="context.current_document",
            deadline_at=_deadline(timedelta(seconds=-1)),
        ))

    assert transport.open_count == 0
    assert transport.payloads == []


@pytest.mark.asyncio
async def test_no_business_deadline_uses_transport_maximum():
    transport = FakeTransport(max_timeout_s=7.0)
    adapter = HostAdapter(transport=transport)

    await adapter.send_command(HostCommand(
        command_id="cmd-1",
        mode="READ",
        operation="context.current_document",
    ))

    assert transport.timeouts == [7.0]
