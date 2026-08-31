from __future__ import annotations

import os
import time
from collections.abc import Callable, Iterable

import pytest

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.ipc.transport import PipeTransport

_PIPE_PREFIX = "EnterpriseDesignAgent."
_PIPE_GLOB = rf"\\.\pipe\{_PIPE_PREFIX}*"
_PIPE_PATH_PREFIX = "\\\\.\\pipe\\"
_PIPE_OVERRIDE_ENV = "AGENT_HOST_PIPE"
_PIPE_DISCOVERY_ATTEMPTS = 5
_PIPE_DISCOVERY_DELAY_SECONDS = 0.05


def _bare_pipe_name(value: str) -> str:
    name = value.strip()
    if name.startswith(_PIPE_PATH_PREFIX):
        name = name[len(_PIPE_PATH_PREFIX) :]
    return name


def _candidate_pipe_names(candidates: Iterable[str]) -> list[str]:
    return sorted(
        {
            _bare_pipe_name(candidate)
            for candidate in candidates
            if _bare_pipe_name(candidate).startswith(_PIPE_PREFIX)
        }
    )


def select_autocad_pipe_name(
    candidates: Iterable[str],
    *,
    override: str | None = None,
) -> str:
    if override:
        name = _bare_pipe_name(override)
        if not name.startswith(_PIPE_PREFIX):
            raise AssertionError(
                f"{_PIPE_OVERRIDE_ENV} must name an {_PIPE_PREFIX}* pipe, got {override!r}"
            )
        return name

    names = _candidate_pipe_names(candidates)
    if not names:
        raise AssertionError("no running AutoCAD AgentHost named pipe found")
    if len(names) > 1:
        raise AssertionError(
            "multiple AutoCAD AgentHost named pipes found; set "
            f"{_PIPE_OVERRIDE_ENV} to choose one explicitly: " + ", ".join(names)
        )
    return names[0]


def _select_autocad_pipe_name_with_retry(
    probe: Callable[[], Iterable[str]],
    *,
    attempts: int = _PIPE_DISCOVERY_ATTEMPTS,
    delay_seconds: float = _PIPE_DISCOVERY_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> str:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")

    for attempt in range(attempts):
        names = _candidate_pipe_names(probe())
        if names:
            return select_autocad_pipe_name(names)
        if attempt + 1 < attempts:
            sleep(delay_seconds)

    return select_autocad_pipe_name(())


def discover_autocad_pipe_name() -> str:
    if os.name != "nt":
        pytest.skip("live AutoCAD named-pipe test requires Windows")

    override = os.environ.get(_PIPE_OVERRIDE_ENV)
    if override:
        return select_autocad_pipe_name((), override=override)

    import win32api

    def probe() -> list[str]:
        try:
            entries = win32api.FindFiles(_PIPE_GLOB)
        except Exception as exc:
            if exc.args and exc.args[0] == 18:  # ERROR_NO_MORE_FILES / no matching pipe
                return []
            raise

        return [
            str(entry[8])
            for entry in entries
            if len(entry) > 8
        ]

    return _select_autocad_pipe_name_with_retry(probe)


def live_autocad_host_adapter() -> HostAdapter:
    pipe_name = discover_autocad_pipe_name()
    return HostAdapter(
        pipe_name=pipe_name,
        transport=PipeTransport(pipe_name),
    )
