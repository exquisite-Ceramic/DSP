from __future__ import annotations

import json
import struct
from typing import Any

from host_contracts.command import HostCommand

from .models import PipeEndpoint

MAX_FRAME_BYTES = 1024 * 1024
_HEADER = struct.Struct("<I")


class WindowsNamedPipeEndpoint:
    def __init__(self, pipe_name: str) -> None:
        if not pipe_name:
            raise ValueError("pipe_name is required")
        self.pipe_name = pipe_name

    @property
    def full_name(self) -> str:
        return rf"\\.\pipe\{self.pipe_name}"

    def exchange(self, packet: bytes) -> bytes:
        import win32con
        import win32file

        handle = win32file.CreateFile(
            self.full_name,
            win32con.GENERIC_READ | win32con.GENERIC_WRITE,
            0,
            None,
            win32con.OPEN_EXISTING,
            win32con.FILE_ATTRIBUTE_NORMAL,
            None,
        )
        try:
            win32file.WriteFile(handle, packet)
            header = self._read_exact(handle, _HEADER.size, win32file)
            (length,) = _HEADER.unpack(header)
            if length <= 0 or length > MAX_FRAME_BYTES:
                raise ConnectionError(f"invalid frame length: {length}")
            body = self._read_exact(handle, length, win32file)
            return header + body
        finally:
            win32file.CloseHandle(handle)

    @staticmethod
    def _read_exact(handle: object, length: int, win32file: Any) -> bytes:
        body = bytearray()
        while len(body) < length:
            error, chunk = win32file.ReadFile(handle, length - len(body))
            if error:
                raise ConnectionError(f"read failed: {error}")
            if not chunk:
                raise ConnectionError("pipe closed before frame completed")
            body.extend(chunk)
        return bytes(body)


class NamedPipeTransport:
    def __init__(
        self,
        endpoint: PipeEndpoint | None = None,
        *,
        pipe_name: str | None = None,
    ) -> None:
        if endpoint is None:
            if pipe_name is None:
                raise ValueError("endpoint or pipe_name is required")
            endpoint = WindowsNamedPipeEndpoint(pipe_name)
        self._endpoint = endpoint

    def request(self, command: HostCommand) -> dict:
        body = json.dumps(
            command.to_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if not body or len(body) > MAX_FRAME_BYTES:
            raise ValueError(f"invalid request frame size: {len(body)}")

        packet = _HEADER.pack(len(body)) + body
        response_packet = self._endpoint.exchange(packet)
        response_body = self._decode_frame(response_packet)
        response = json.loads(response_body.decode("utf-8"))
        if not isinstance(response, dict):
            raise ConnectionError("response payload must be a JSON object")
        return response

    @staticmethod
    def _decode_frame(packet: bytes) -> bytes:
        if len(packet) < _HEADER.size:
            raise ConnectionError("response frame header is incomplete")
        (length,) = _HEADER.unpack(packet[: _HEADER.size])
        if length <= 0 or length > MAX_FRAME_BYTES:
            raise ConnectionError(f"invalid frame length: {length}")
        body = packet[_HEADER.size :]
        if len(body) != length:
            raise ConnectionError(
                f"response frame length mismatch: expected {length}, got {len(body)}"
            )
        return body
