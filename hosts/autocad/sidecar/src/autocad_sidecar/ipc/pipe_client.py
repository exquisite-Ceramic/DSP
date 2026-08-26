"""Named-pipe client (ADR-002)."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

try:
    import win32file
    import win32pipe

    _HAS_PYWIN32 = True
except ImportError:  # pragma: no cover - exercised only on non-Windows
    _HAS_PYWIN32 = False

from autocad_sidecar.ipc.transport import Frame, PipeTransport

MAX_FRAME_BYTES = 1024 * 1024  # must match plugin NamedPipeServer.MaxFrameBytes


class PipeClient:
    """Thin wrapper around the transport for a single pipe connection."""

    def __init__(self, pipe_name: str) -> None:
        self.pipe_name = pipe_name
        self._transport: PipeTransport | None = None

    @property
    def connected(self) -> bool:
        return self._transport is not None

    async def connect(self) -> None:
        if not _HAS_PYWIN32:
            raise RuntimeError("pywin32 is required for named-pipe IPC (pip install pywin32)")
        if self._transport is None:
            self._transport = PipeTransport(self.pipe_name)
            await self._transport.open()
            logger.info("connected to pipe %s", self.pipe_name)

    async def send(self, frame: Frame) -> Frame:
        if self._transport is None:
            raise ConnectionError("not connected")
        return await self._transport.exchange(frame)

    async def close(self) -> None:
        if self._transport is not None:
            await self._transport.close()
            self._transport = None
