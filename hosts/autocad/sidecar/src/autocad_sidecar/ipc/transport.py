"""Framed named-pipe transport.

Frame format (matches the plugin side):
    4-byte little-endian length prefix + UTF-8 JSON body (Envelope).
"""

from __future__ import annotations

import asyncio
import struct
from typing import TypeAlias

Frame: TypeAlias = bytes  # one complete envelope JSON payload

MAX_FRAME_BYTES = 1024 * 1024

_HEADER = struct.Struct("<I")


class PipeTransport:
    """Length-prefixed JSON exchange over a Windows named pipe (client side)."""

    max_timeout_s: None = None

    def __init__(self, pipe_name: str) -> None:
        self.pipe_name = pipe_name
        self._handle = None
        self._lock = asyncio.Lock()

    @property
    def full_name(self) -> str:
        # Plugin listens as \\.\pipe\<name>.
        return rf"\\.\pipe\{self.pipe_name}"

    async def open(self) -> None:
        # Executed on the default executor: win32file.CreateFile blocks.
        import win32con
        import win32file
        import win32pipe

        def _connect() -> object:
            handle = win32file.CreateFile(
                self.full_name,
                win32con.GENERIC_READ | win32con.GENERIC_WRITE,
                0,  # exclusive
                None,
                win32con.OPEN_EXISTING,
                win32con.FILE_ATTRIBUTE_NORMAL,
                None,
            )
            win32pipe.SetNamedPipeHandleState(
                handle, win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_WAIT, None, None
            )
            return handle

        self._handle = await asyncio.get_running_loop().run_in_executor(None, _connect)

    async def exchange(self, payload: Frame, *, timeout_s: float | None = None) -> Frame:
        """Send one frame and await the response frame."""
        if timeout_s is not None and timeout_s <= 0:
            raise TimeoutError("transport timeout must be positive")

        async def _exchange() -> Frame:
            async with self._lock:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, self._write_frame, payload)
                return await loop.run_in_executor(None, self._read_frame)

        if timeout_s is None:
            return await _exchange()
        return await asyncio.wait_for(_exchange(), timeout=timeout_s)

    def _write_frame(self, payload: Frame) -> None:
        import win32file

        if len(payload) > MAX_FRAME_BYTES:
            raise ValueError(f"frame too large: {len(payload)} bytes")
        header = _HEADER.pack(len(payload))
        win32file.WriteFile(self._handle, header + payload)

    def _read_frame(self) -> Frame:
        import win32file

        err, header = win32file.ReadFile(self._handle, 4)
        if err:
            raise ConnectionError(f"read failed: {err}")
        (length,) = _HEADER.unpack(header)
        if length <= 0 or length > MAX_FRAME_BYTES:
            raise ConnectionError(f"invalid frame length: {length}")

        body = bytearray()
        while len(body) < length:
            err, chunk = win32file.ReadFile(self._handle, length - len(body))
            if err:
                raise ConnectionError(f"read failed: {err}")
            body.extend(chunk)

        return bytes(body)

    async def close(self) -> None:
        if self._handle is not None:
            import win32file

            win32file.CloseHandle(self._handle)
            self._handle = None
