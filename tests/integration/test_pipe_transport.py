from __future__ import annotations

import asyncio
import sys
from types import SimpleNamespace

from autocad_sidecar.ipc.transport import PipeTransport


def test_pipe_open_keeps_byte_mode(monkeypatch):
    handle = object()
    state_calls: list[tuple[object, int, object, object]] = []

    monkeypatch.setitem(
        sys.modules,
        "win32con",
        SimpleNamespace(
            GENERIC_READ=0x80000000,
            GENERIC_WRITE=0x40000000,
            OPEN_EXISTING=3,
            FILE_ATTRIBUTE_NORMAL=0x80,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32file",
        SimpleNamespace(CreateFile=lambda *args: handle),
    )
    monkeypatch.setitem(
        sys.modules,
        "win32pipe",
        SimpleNamespace(
            PIPE_READMODE_MESSAGE=0x2,
            PIPE_WAIT=0x0,
            SetNamedPipeHandleState=lambda *args: state_calls.append(args),
        ),
    )

    transport = PipeTransport("EnterpriseDesignAgent.test")
    asyncio.run(transport.open())

    assert transport._handle is handle
    assert state_calls == []
