from __future__ import annotations

import pytest

from autocad_sidecar.main import build_parser, validate_transport_args


def test_default_transport_remains_pipe(monkeypatch):
    monkeypatch.delenv("DSP_AUTOCAD_TRANSPORT", raising=False)
    args = build_parser().parse_args([])
    assert args.transport == "pipe"


def test_env_can_select_grpc(monkeypatch):
    monkeypatch.setenv("DSP_AUTOCAD_TRANSPORT", "grpc")
    args = build_parser().parse_args(["--instance-id", "inst-1"])
    assert args.transport == "grpc"
    assert args.instance_id == "inst-1"


def test_pipe_keeps_existing_pipe_option(monkeypatch):
    monkeypatch.delenv("DSP_AUTOCAD_TRANSPORT", raising=False)
    args = build_parser().parse_args(["--pipe", "EnterpriseDesignAgent.test"])
    assert args.transport == "pipe"
    assert args.pipe == "EnterpriseDesignAgent.test"


def test_grpc_requires_instance_id(monkeypatch):
    monkeypatch.delenv("DSP_AUTOCAD_TRANSPORT", raising=False)
    args = build_parser().parse_args(["--transport", "grpc"])
    with pytest.raises(ValueError, match="instance_id"):
        validate_transport_args(args)
