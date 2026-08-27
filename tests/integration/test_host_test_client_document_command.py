from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from host_test_client.main import build_parser


def test_host_test_client_exposes_current_document_command():
    args = build_parser().parse_args(["document"])
    assert args.command == "document"
    assert args.kind == "command"


@pytest.mark.asyncio
async def test_current_document_command_uses_injected_host(monkeypatch):
    module = importlib.import_module("host_test_client.commands.current_document")
    host = object()
    expected = object()
    seen: list[object] = []

    class FakeDispatcher:
        def __init__(self, *, host):
            seen.append(host)

        async def current_document(self):
            return expected

    monkeypatch.setattr(module, "CommandDispatcher", FakeDispatcher)
    assert await module.run(host=host) is expected
    assert seen == [host]
