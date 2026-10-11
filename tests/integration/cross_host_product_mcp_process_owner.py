"""Windows Managed MCP 进程身份边界。

Windows venv 的 python.exe 可能是启动器，而实际监听 MCP 的解释器是直接子进程。
所有进程归属证据来自操作系统，readiness 里的 PID 只作为待核验的声明。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

_MCP_MODULE = "tests.integration.cross_host_product_live_composition"


@dataclass(frozen=True)
class ManagedMcpOsIdentity:
    """冻结由操作系统核验的启动器与实际 MCP 解释器身份。"""

    launcher_pid: int
    launcher_created_at: str
    server_pid: int
    server_created_at: str
    server_parent_pid: int
    server_command_line: str


def _running_windows() -> bool:
    """隔离平台判断，以便离线测试不改变全局 os.name。"""

    return os.name == "nt"


def _windows_process_info(pid: int) -> dict | None:
    """仅查询 Windows 内核进程清单，不读取 MCP 自报的身份字段。"""

    if not _running_windows() or type(pid) is not int or not 0 < pid <= 2147483647:
        raise ValueError("LIVE_MCP_PROVENANCE_INVALID: Windows process identity unavailable")
    script = """$ErrorActionPreference='Stop'
$p=Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $env:DSP_INSPECT_PROCESS_ID)
if ($null -eq $p) { exit 2 }
@{
 pid=[int]$p.ProcessId
 parent_pid=[int]$p.ParentProcessId
 name=[string]$p.Name
 command_line=[string]$p.CommandLine
 created_at=$p.CreationDate.ToUniversalTime().ToString('o')
} | ConvertTo-Json -Compress
"""
    try:
        completed = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            env={**os.environ, "DSP_INSPECT_PROCESS_ID": str(pid)},
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        if completed.returncode == 2:
            return None
        if completed.returncode != 0:
            raise ValueError("Windows OS process query failed")
        value = json.loads(completed.stdout)
        if not isinstance(value, dict):
            raise ValueError("invalid Windows process record")
        return value
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        raise ValueError("LIVE_MCP_PROVENANCE_INVALID: OS process query failed") from exc


def _checked_record(value: dict | None, pid: int) -> dict:
    """拒绝缺字段、复用 PID 或创建时间无法核验的操作系统记录。"""

    if (
        not isinstance(value, dict)
        or type(value.get("pid")) is not int
        or value["pid"] != pid
        or type(value.get("parent_pid")) is not int
        or not isinstance(value.get("created_at"), str)
        or not isinstance(value.get("command_line"), str)
        or not isinstance(value.get("name"), str)
    ):
        raise ValueError("LIVE_MCP_PROVENANCE_INVALID: incomplete OS process identity")
    try:
        created = datetime.fromisoformat(value["created_at"])
        if created.tzinfo is None:
            raise ValueError("timezone missing")
    except ValueError as exc:
        raise ValueError("LIVE_MCP_PROVENANCE_INVALID: invalid OS creation time") from exc
    return value


def _is_reviewed_mcp_command(command_line: str, directory: Path) -> bool:
    """OS 命令行必须明确运行本次固定 MCP 模块与本次 case 目录。"""

    return bool(
        re.search(
            r"(?:^|\s)-m\s+" + re.escape(_MCP_MODULE) + r"(?=\s|$)",
            command_line,
        )
        and str(Path(directory).resolve()).casefold() in command_line.casefold()
    )


def resolve_managed_mcp_identity(
    launcher_pid: int, claimed_server_pid: int, directory: Path
) -> ManagedMcpOsIdentity:
    """从 OS 证实 MCP 为本次启动器本体或直接子解释器；绝不信任自报 PID。"""

    if type(launcher_pid) is not int or type(claimed_server_pid) is not int:
        raise ValueError("LIVE_MCP_PROVENANCE_INVALID: non-integer process identity")
    launcher = _checked_record(_windows_process_info(launcher_pid), launcher_pid)
    server = _checked_record(_windows_process_info(claimed_server_pid), claimed_server_pid)
    launcher_time = datetime.fromisoformat(launcher["created_at"])
    server_time = datetime.fromisoformat(server["created_at"])
    if (
        server["name"].casefold() != "python.exe"
        or not _is_reviewed_mcp_command(server["command_line"], directory)
        or (
            claimed_server_pid != launcher_pid
            and (
                server["parent_pid"] != launcher_pid or server_time < launcher_time
            )
        )
    ):
        raise ValueError("LIVE_MCP_PROVENANCE_INVALID: server is not reviewed launch")
    return ManagedMcpOsIdentity(
        launcher_pid=launcher_pid,
        launcher_created_at=launcher["created_at"],
        server_pid=claimed_server_pid,
        server_created_at=server["created_at"],
        server_parent_pid=server["parent_pid"],
        server_command_line=server["command_line"],
    )


def assert_managed_mcp_alive(identity: ManagedMcpOsIdentity, directory: Path) -> None:
    """对每次存活检查重新查询 OS，拒绝 PID 复用、进程退出与身份漂移。"""

    current = resolve_managed_mcp_identity(
        identity.launcher_pid, identity.server_pid, directory
    )
    if current != identity:
        raise ValueError("LIVE_MCP_PROVENANCE_INVALID: managed process identity drifted")


def terminate_managed_mcp_tree(
    process: subprocess.Popen, identity: ManagedMcpOsIdentity | None
) -> None:
    """清理本次 launcher 进程树，并在需要时额外清理仍有原始 OS 身份的解释器。"""

    if not _running_windows():
        return

    def taskkill(pid: int, *, tree: bool) -> None:
        """使用 Windows 自带工具终止本次 PID（可选同时终止后代）。"""

        arguments = ["taskkill.exe", "/F", "/PID", str(pid)]
        if tree:
            arguments.append("/T")
        try:
            subprocess.run(
                arguments, capture_output=True, timeout=20, check=False
            )
        except (OSError, subprocess.TimeoutExpired):
            # 后续仍检查子进程状态，并由调用方执行 launcher 的 terminate/kill 兜底。
            pass

    # Popen handle 仍存活才能认为 launcher PID 尚未被 OS 复用。
    if process.poll() is None:
        taskkill(process.pid, tree=True)
    if identity is None:
        return
    # 被启动器留在后台的实际解释器只允许在原始 OS 身份仍精确一致时终止。
    server = _windows_process_info(identity.server_pid)
    if server is not None and (
        server.get("created_at") == identity.server_created_at
        and server.get("parent_pid") == identity.server_parent_pid
        and server.get("command_line") == identity.server_command_line
    ):
        taskkill(identity.server_pid, tree=False)
    remaining = _windows_process_info(identity.server_pid)
    if remaining is not None and remaining.get("created_at") == identity.server_created_at:
        raise RuntimeError("LIVE_MCP_CLEANUP_FAILED: validated interpreter still running")
