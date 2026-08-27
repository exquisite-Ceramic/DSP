from __future__ import annotations

import json
import os
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from autocad_sidecar.ipc.grpc_transport import GrpcTransport
from autocad_sidecar.ipc.transport import PipeTransport
from host_test_client import main as client_main
from host_test_client.main import build_host_adapter, build_parser


def test_host_test_client_default_transport_remains_pipe(monkeypatch):
    monkeypatch.delenv("DSP_AUTOCAD_TRANSPORT", raising=False)
    args = build_parser().parse_args(["selection"])
    assert args.transport == "pipe"
    assert args.pipe is None


def test_host_test_client_env_can_select_grpc(monkeypatch):
    monkeypatch.setenv("DSP_AUTOCAD_TRANSPORT", "grpc")
    args = build_parser().parse_args(["--instance-id", "inst-1", "selection"])
    assert args.transport == "grpc"
    assert args.instance_id == "inst-1"


def test_host_test_client_auto_discovers_pipe(monkeypatch):
    monkeypatch.delenv("DSP_AUTOCAD_TRANSPORT", raising=False)
    monkeypatch.setattr(
        client_main,
        "discover_pipe_name",
        lambda: "EnterpriseDesignAgent.host-123",
        raising=False,
    )
    args = build_parser().parse_args(["selection"])
    adapter = build_host_adapter(args)
    assert isinstance(adapter._transport, PipeTransport)
    assert adapter.pipe_name == "EnterpriseDesignAgent.host-123"


def test_host_test_client_explicit_pipe_wins_over_discovery(monkeypatch):
    monkeypatch.delenv("DSP_AUTOCAD_TRANSPORT", raising=False)

    def unexpected_discovery() -> str:
        raise AssertionError("explicit --pipe must not trigger discovery")

    monkeypatch.setattr(client_main, "discover_pipe_name", unexpected_discovery, raising=False)
    args = build_parser().parse_args(["--pipe", "EnterpriseDesignAgent.test", "selection"])
    adapter = build_host_adapter(args)
    assert isinstance(adapter._transport, PipeTransport)
    assert adapter.pipe_name == "EnterpriseDesignAgent.test"


def test_host_test_client_builds_grpc_adapter(monkeypatch, tmp_path):
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

    args = build_parser().parse_args(["--transport", "grpc", "--instance-id", "inst-1", "selection"])
    adapter = build_host_adapter(args)
    assert isinstance(adapter._transport, GrpcTransport)
    assert adapter._transport.instance_id == "inst-1"
