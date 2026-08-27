"""Transport-neutral Sidecar IPC interface."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class FrameTransport(Protocol):
    """Bytes-in/bytes-out request transport used by HostAdapter."""

    async def open(self) -> None: ...

    async def exchange(self, payload: bytes, *, timeout_s: float | None = None) -> bytes: ...

    async def close(self) -> None: ...
