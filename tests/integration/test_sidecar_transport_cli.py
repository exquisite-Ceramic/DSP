from __future__ import annotations

import json
import os

import pytest

from autocad_sidecar.ipc.grpc_transport import GrpcTransport
from autocad_sidecar.ipc.transport import PipeTransport
from autocad_sidecar.main import build_host_adapter, build_parser, validate_transport_args


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


def test_build_host_adapter_injects_pipe_transport(monkeypatch):
    monkeypatch.delenv("DSP_AUTOCAD_TRANSPORT", raising=False)
    args = build_parser().parse_args(["--pipe", "EnterpriseDesignAgent.test"])
    adapter = build_host_adapter(args)
    assert isinstance(adapter._transport, PipeTransport)
    assert adapter.pipe_name == "EnterpriseDesignAgent.test"


def test_build_host_adapter_injects_grpc_transport(monkeypatch, tmp_path):
    monkeypatch.delenv("DSP_AUTOCAD_TRANSPORT", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    discovery_dir = tmp_path / "EnterpriseDesignAgent" / "hosts"
    discovery_dir.mkdir(parents=True)
    (discovery_dir / "inst-1.json").write_text(
        json.dumps(
            {
                "instance_id": "inst-1",
                "pid": os.getpid(),
                "host": "127.0.0.1",
                "port": 50051,
                "transport": "grpc-h2c",
                "contract_version": "1.0",
                "auth_token": "token-1",
            }
        ),
        encoding="utf-8",
    )

    args = build_parser().parse_args(["--transport", "grpc", "--instance-id", "inst-1"])
    adapter = build_host_adapter(args)
    assert isinstance(adapter._transport, GrpcTransport)
    assert adapter._transport.instance_id == "inst-1"
