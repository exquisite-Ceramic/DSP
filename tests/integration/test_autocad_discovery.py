import json
import os
from pathlib import Path

import pytest

from autocad_sidecar.ipc.discovery import HostEndpoint, load_instance


def _write_record(directory: Path, instance_id: str, **overrides) -> None:
    record = {
        "instance_id": instance_id,
        "pid": os.getpid(),
        "host": "127.0.0.1",
        "port": 53182,
        "transport": "grpc-h2c",
        "contract_version": "1.0",
        "auth_token": "token-001",
    }
    record.update(overrides)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{instance_id}.json").write_text(json.dumps(record), encoding="utf-8")


def test_load_instance_returns_valid_endpoint(tmp_path):
    instance_id = "instance-001"
    _write_record(tmp_path, instance_id)

    endpoint = load_instance(instance_id, discovery_dir=tmp_path)

    assert endpoint == HostEndpoint(
        instance_id=instance_id,
        pid=os.getpid(),
        host="127.0.0.1",
        port=53182,
        transport="grpc-h2c",
        contract_version="1.0",
        auth_token="token-001",
    )


def test_load_instance_rejects_dead_pid(tmp_path):
    instance_id = "instance-dead"
    _write_record(tmp_path, instance_id, pid=2_147_483_647)

    with pytest.raises(ValueError, match="PID.*not alive|stale"):
        load_instance(instance_id, discovery_dir=tmp_path)


def test_load_instance_rejects_non_loopback_host(tmp_path):
    instance_id = "instance-lan"
    _write_record(tmp_path, instance_id, host="0.0.0.0")

    with pytest.raises(ValueError, match="127\\.0\\.0\\.1|loopback"):
        load_instance(instance_id, discovery_dir=tmp_path)


def test_load_instance_rejects_wrong_transport(tmp_path):
    instance_id = "instance-pipe"
    _write_record(tmp_path, instance_id, transport="pipe")

    with pytest.raises(ValueError, match="grpc-h2c|transport"):
        load_instance(instance_id, discovery_dir=tmp_path)


def test_load_instance_rejects_instance_mismatch(tmp_path):
    instance_id = "instance-file"
    _write_record(tmp_path, instance_id, instance_id="instance-payload")

    with pytest.raises(ValueError, match="instance_id"):
        load_instance(instance_id, discovery_dir=tmp_path)


def test_load_instance_rejects_invalid_port_and_empty_token(tmp_path):
    bad_port_id = "instance-port"
    _write_record(tmp_path, bad_port_id, port=0)
    with pytest.raises(ValueError, match="port"):
        load_instance(bad_port_id, discovery_dir=tmp_path)

    bad_token_id = "instance-token"
    _write_record(tmp_path, bad_token_id, auth_token="")
    with pytest.raises(ValueError, match="auth_token|token"):
        load_instance(bad_token_id, discovery_dir=tmp_path)
