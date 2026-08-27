"""Discovery of local AutoCAD gRPC host instances."""

from __future__ import annotations

import ctypes
import json
import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class HostEndpoint:
    instance_id: str
    pid: int
    host: str
    port: int
    transport: str
    contract_version: str
    auth_token: str


def default_discovery_dir() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise RuntimeError("LOCALAPPDATA is required for AutoCAD host discovery")
    return Path(local_app_data) / "EnterpriseDesignAgent" / "hosts"


def load_instance(instance_id: str, discovery_dir: Path | None = None) -> HostEndpoint:
    _validate_instance_id(instance_id)
    directory = Path(discovery_dir) if discovery_dir is not None else default_discovery_dir()
    path = directory / f"{instance_id}.json"

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"discovery record not found for instance_id {instance_id!r}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid discovery record for instance_id {instance_id!r}") from exc

    if not isinstance(data, dict):
        raise ValueError("discovery record must be a JSON object")

    required = {
        "instance_id",
        "pid",
        "host",
        "port",
        "transport",
        "contract_version",
        "auth_token",
    }
    missing = required - data.keys()
    if missing:
        raise ValueError(f"discovery record missing fields: {', '.join(sorted(missing))}")

    payload_instance_id = data["instance_id"]
    if not isinstance(payload_instance_id, str) or payload_instance_id != instance_id:
        raise ValueError("discovery instance_id does not match requested instance_id")

    pid = data["pid"]
    if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
        raise ValueError("discovery pid must be a positive integer")
    if not _pid_is_alive(pid):
        raise ValueError(f"discovery record is stale: PID {pid} is not alive")

    host = data["host"]
    if host != "127.0.0.1":
        raise ValueError("discovery host must be IPv4 loopback 127.0.0.1")

    port = data["port"]
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise ValueError("discovery port must be an integer in the range 1..65535")

    transport = data["transport"]
    if transport != "grpc-h2c":
        raise ValueError("discovery transport must be grpc-h2c")

    contract_version = data["contract_version"]
    if not isinstance(contract_version, str) or not contract_version.strip():
        raise ValueError("discovery contract_version must be a non-empty string")

    auth_token = data["auth_token"]
    if not isinstance(auth_token, str) or not auth_token:
        raise ValueError("discovery auth_token must be a non-empty string")

    return HostEndpoint(
        instance_id=payload_instance_id,
        pid=pid,
        host=host,
        port=port,
        transport=transport,
        contract_version=contract_version,
        auth_token=auth_token,
    )


def _validate_instance_id(instance_id: str) -> None:
    if not isinstance(instance_id, str) or not instance_id or instance_id in {".", ".."}:
        raise ValueError("instance_id must be a non-empty safe file name")
    if Path(instance_id).name != instance_id or "/" in instance_id or "\\" in instance_id:
        raise ValueError("instance_id must be a safe file name")


def _pid_is_alive(pid: int) -> bool:
    if os.name == "nt":
        return _windows_pid_is_alive(pid)

    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _windows_pid_is_alive(pid: int) -> bool:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    process_query_limited_information = 0x1000
    still_active = 259

    kernel32.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    kernel32.GetExitCodeProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle.restype = ctypes.c_int

    handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
    if not handle:
        return False

    try:
        exit_code = ctypes.c_ulong()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
            return False
        return exit_code.value == still_active
    finally:
        kernel32.CloseHandle(handle)
