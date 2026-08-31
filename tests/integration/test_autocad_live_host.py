from __future__ import annotations

import pytest

from autocad_live_host import select_autocad_pipe_name


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


# Task10 CI carrier: no runtime behavior; removed after offline collection.
