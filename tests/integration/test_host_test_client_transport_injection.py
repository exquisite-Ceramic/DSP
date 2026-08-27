from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

import host_test_client.main as client_main


class FakeHost:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_main_injects_one_adapter_into_command_and_closes_it(monkeypatch):
    host = FakeHost()
    seen: list[object] = []

    async def fake_command(*, host, **kwargs):
        seen.append(host)
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(client_main, "build_host_adapter", lambda args: host)
    monkeypatch.setitem(client_main.COMMANDS, "selection", fake_command)

    assert await client_main.main(["selection"]) == 0
    assert seen == [host]
    assert host.closed


@pytest.mark.asyncio
async def test_main_injects_one_adapter_into_scenario_and_closes_it(monkeypatch):
    host = FakeHost()
    seen: list[object] = []

    async def fake_scenario(*, host):
        seen.append(host)
        return SimpleNamespace(ok=True)

    monkeypatch.setattr(client_main, "build_host_adapter", lambda args: host)
    monkeypatch.setitem(client_main.SCENARIOS, "move_once", fake_scenario)

    assert await client_main.main(["scenario", "move_once"]) == 0
    assert seen == [host]
    assert host.closed


def test_command_and_scenario_modules_do_not_construct_host_adapter_directly():
    paths = [
        "tools/host_test_client/commands/current_selection.py",
        "tools/host_test_client/commands/fit.py",
        "tools/host_test_client/commands/move.py",
        "tools/host_test_client/scenarios/move_once.py",
        "tools/host_test_client/scenarios/move_retry.py",
        "tools/host_test_client/scenarios/revision_conflict.py",
    ]
    for path in paths:
        source = Path(path).read_text(encoding="utf-8")
        assert "HostAdapter(" not in source, path
