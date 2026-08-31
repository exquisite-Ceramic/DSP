from __future__ import annotations

from pathlib import Path

import pytest

from autocad_live_host import (
    _select_autocad_pipe_name_with_retry,
    select_autocad_pipe_name,
)


def test_selects_single_dynamic_pipe() -> None:
    assert (
        select_autocad_pipe_name(["EnterpriseDesignAgent.MACHINE-1234"])
        == "EnterpriseDesignAgent.MACHINE-1234"
    )


def test_rejects_zero_dynamic_pipes() -> None:
    with pytest.raises(AssertionError, match="no running AutoCAD AgentHost named pipe"):
        select_autocad_pipe_name([])


def test_rejects_multiple_dynamic_pipes_without_override() -> None:
    with pytest.raises(AssertionError, match="AGENT_HOST_PIPE"):
        select_autocad_pipe_name(
            [
                "EnterpriseDesignAgent.MACHINE-1234",
                "EnterpriseDesignAgent.MACHINE-5678",
            ]
        )


def test_explicit_override_accepts_full_pipe_path() -> None:
    assert (
        select_autocad_pipe_name(
            [
                "EnterpriseDesignAgent.MACHINE-1234",
                "EnterpriseDesignAgent.MACHINE-5678",
            ],
            override=r"\\.\pipe\EnterpriseDesignAgent.MACHINE-5678",
        )
        == "EnterpriseDesignAgent.MACHINE-5678"
    )


def test_retries_transient_zero_pipe_discovery() -> None:
    probes = iter(
        [
            [],
            ["EnterpriseDesignAgent.MACHINE-1234"],
        ]
    )
    sleeps: list[float] = []

    assert (
        _select_autocad_pipe_name_with_retry(
            lambda: next(probes),
            attempts=2,
            delay_seconds=0.01,
            sleep=lambda seconds: sleeps.append(seconds),
        )
        == "EnterpriseDesignAgent.MACHINE-1234"
    )
    assert sleeps == [0.01]


def test_retry_does_not_mask_multiple_pipe_ambiguity() -> None:
    calls = 0

    def probe() -> list[str]:
        nonlocal calls
        calls += 1
        return [
            "EnterpriseDesignAgent.MACHINE-1234",
            "EnterpriseDesignAgent.MACHINE-5678",
        ]

    with pytest.raises(AssertionError, match="AGENT_HOST_PIPE"):
        _select_autocad_pipe_name_with_retry(
            probe,
            attempts=3,
            delay_seconds=0.01,
            sleep=lambda _: None,
        )

    assert calls == 1


def test_single_instance_host_waits_for_client_completion_before_reaccepting() -> None:
    source = (
        Path(__file__).parents[2]
        / "hosts/autocad/plugin/AutoCAD.AgentHost/Ipc/NamedPipeServer.cs"
    ).read_text(encoding="utf-8")

    assert "maxNumberOfServerInstances: 1" in source
    assert "await pipe.WaitForConnectionAsync(ct);" in source
    assert "await HandleClientAsync(pipe, ct);" in source
    assert "_ = Task.Run(() => HandleClientAsync(pipe, ct), ct);" not in source

# CI carrier: collect the new Step36 live scope acceptance under full importlib.
