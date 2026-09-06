from __future__ import annotations

import struct
import sys
import types

import pytest

from revit_sidecar.named_pipe import WindowsNamedPipeEndpoint


class _FakeWin32Error(Exception):
    def __init__(self, winerror: int) -> None:
        super().__init__(winerror, "fake win32 error")
        self.winerror = winerror


class _FakeWin32FileModule:
    def __init__(
        self,
        *,
        create_failures: list[int] | None = None,
        write_failure: int | None = None,
    ) -> None:
        self.create_failures = list(create_failures or [])
        self.write_failure = write_failure
        self.create_calls = 0
        self.writes: list[bytes] = []
        self.close_calls = 0
        response_body = b"{}"
        self.read_chunks = [struct.pack("<I", len(response_body)), response_body]

    def CreateFile(self, *_args):
        self.create_calls += 1
        if self.create_failures:
            raise _FakeWin32Error(self.create_failures.pop(0))
        return object()

    def WriteFile(self, _handle, packet: bytes):
        if self.write_failure is not None:
            raise _FakeWin32Error(self.write_failure)
        self.writes.append(packet)
        return 0, len(packet)

    def ReadFile(self, _handle, _length: int):
        return 0, self.read_chunks.pop(0)

    def CloseHandle(self, _handle) -> None:
        self.close_calls += 1


def _install_fake_pywin32(monkeypatch, win32file: _FakeWin32FileModule) -> None:
    # 单元测试只模拟 Windows Named Pipe 边界，不依赖 CI 机器安装 pywin32。
    monkeypatch.setitem(
        sys.modules,
        "win32con",
        types.SimpleNamespace(
            GENERIC_READ=1,
            GENERIC_WRITE=2,
            OPEN_EXISTING=3,
            FILE_ATTRIBUTE_NORMAL=4,
        ),
    )
    monkeypatch.setitem(sys.modules, "win32file", win32file)
    monkeypatch.setitem(
        sys.modules,
        "pywintypes",
        types.SimpleNamespace(error=_FakeWin32Error),
    )


@pytest.mark.parametrize("transient_error", [2, 231])
def test_windows_named_pipe_endpoint_retries_transient_createfile_without_resending(
    monkeypatch,
    transient_error: int,
) -> None:
    win32file = _FakeWin32FileModule(create_failures=[transient_error])
    _install_fake_pywin32(monkeypatch, win32file)
    monkeypatch.setattr("time.sleep", lambda _seconds: None)

    packet = b"request-packet"
    response = WindowsNamedPipeEndpoint("DSP-Test").exchange(packet)

    assert response == struct.pack("<I", 2) + b"{}"
    assert win32file.create_calls == 2
    assert win32file.writes == [packet]
    assert win32file.close_calls == 1


def test_windows_named_pipe_endpoint_never_retries_after_request_write_begins(
    monkeypatch,
) -> None:
    win32file = _FakeWin32FileModule(write_failure=109)
    _install_fake_pywin32(monkeypatch, win32file)

    with pytest.raises(_FakeWin32Error):
        WindowsNamedPipeEndpoint("DSP-Test").exchange(b"request-packet")

    assert win32file.create_calls == 1
    assert win32file.writes == []
    assert win32file.close_calls == 1
