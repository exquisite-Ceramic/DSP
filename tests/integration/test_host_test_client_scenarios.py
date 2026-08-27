from __future__ import annotations

import pytest

from host_contracts.error import ErrorShape
from host_contracts.result import HostCommandResult
from host_test_client.scenarios import move_retry, revision_conflict


@pytest.mark.asyncio
async def test_move_retry_uses_native_id_and_reports_replay(monkeypatch):
    calls: list[tuple[list[str], str]] = []

    class FakeDispatcher:
        def __init__(self, host):
            self.host = host

        async def current_selection(self):
            return HostCommandResult(
                command_id="selection",
                status="OK",
                payload={
                    "entityRefs": [{"native_id": "2C4", "native_type": "Line"}],
                    "revision": 4,
                },
            )

        async def move(self, handles, dx, dy, dz=0.0, *, idempotency_key=None, revision=None):
            calls.append((list(handles), idempotency_key))
            return HostCommandResult(
                command_id=f"move-{len(calls)}",
                status="OK",
                payload={"moved": 1, "positions": {"2C4": {"x": 1.0, "y": 2.0, "z": 0.0}}},
                revision_after=5,
                replayed=len(calls) == 2,
            )

    monkeypatch.setattr(move_retry, "CommandDispatcher", FakeDispatcher)

    result = await move_retry.run(object())

    assert result.ok
    assert calls[0][0] == ["2C4"]
    assert calls[1][0] == ["2C4"]
    assert calls[0][1] == calls[1][1]
    assert result.payload["second"]["replayed"] is True


@pytest.mark.asyncio
async def test_revision_conflict_uses_native_id_and_uppercase_error_code(monkeypatch):
    moves: list[tuple[list[str], int | None]] = []

    class FakeDispatcher:
        def __init__(self, host):
            self.host = host

        async def current_selection(self):
            return HostCommandResult(
                command_id="selection",
                status="OK",
                payload={
                    "entityRefs": [{"native_id": "2C4", "native_type": "Line"}],
                    "revision": 7,
                },
            )

        async def move(self, handles, dx, dy, dz=0.0, *, idempotency_key=None, revision=None):
            moves.append((list(handles), revision))
            return HostCommandResult(
                command_id="move",
                status="ERROR",
                error=ErrorShape(
                    error_code="REVISION_CONFLICT",
                    category="CONSISTENCY",
                    message="stale revision",
                    retryable="AFTER_RECONSTRUCT",
                ),
            )

    monkeypatch.setattr(revision_conflict, "CommandDispatcher", FakeDispatcher)

    result = await revision_conflict.run(object())

    assert result.ok
    assert moves == [(["2C4"], 6)]
    assert result.payload["expectedCode"] == "REVISION_CONFLICT"
    assert result.payload["actual"]["error"]["error_code"] == "REVISION_CONFLICT"
