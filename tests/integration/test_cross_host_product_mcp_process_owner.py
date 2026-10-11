"""Windows MCP venv launcher→真实解释器 PID 的 OS 归属与失败清理回归。"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.integration.cross_host_product_mcp_process_owner import (
    _windows_process_info,
    assert_managed_mcp_alive,
    resolve_managed_mcp_identity,
    terminate_managed_mcp_tree,
)


def _records(directory: Path) -> dict:
    """用 Windows OS 记录模拟真实 launcher 21272 → 解释器 28884。"""

    command = (
        '"C:\\Python311\\python.exe" -m '
        'tests.integration.cross_host_product_live_composition '
        f'"{directory}"'
    )
    return {
        21272: {
            "pid": 21272,
            "parent_pid": 99,
            "name": "python.exe",
            "command_line": '"E:\\venv\\Scripts\\python.exe" -m '
            'tests.integration.cross_host_product_live_composition '
            f'"{directory}"',
            "created_at": "2026-10-11T06:31:00.0000000Z",
        },
        28884: {
            "pid": 28884,
            "parent_pid": 21272,
            "name": "python.exe",
            "command_line": command,
            "created_at": "2026-10-11T06:31:01.0000000Z",
        },
        9090: {
            "pid": 9090,
            "parent_pid": 12345,
            "name": "python.exe",
            "command_line": command,
            "created_at": "2026-10-11T06:31:02.0000000Z",
        },
    }


def test_launcher_pid_differs_from_real_interpreter_and_liveness_is_os_bound(
    monkeypatch, tmp_path
):
    """合法子解释器通过；相同 PID 被另一进程复用时存活校验必须失败。"""

    from tests.integration import cross_host_product_mcp_process_owner as owner

    rows = _records(tmp_path)
    monkeypatch.setattr(owner, "_windows_process_info", rows.get)
    identity = resolve_managed_mcp_identity(21272, 28884, tmp_path)
    assert identity.launcher_pid == 21272
    assert identity.server_pid == 28884
    assert_managed_mcp_alive(identity, tmp_path)

    # 即使数值 PID 不变，Windows 创建时间不同也不能复用旧授权。
    rows[28884] = dict(rows[28884], created_at="2026-10-11T06:33:00.0000000Z")
    with pytest.raises(ValueError, match="LIVE_MCP_PROVENANCE_INVALID"):
        assert_managed_mcp_alive(identity, tmp_path)


@pytest.mark.parametrize(
    "case", ["unrelated", "grandchild", "wrong_module", "wrong_case", "older", "missing"]
)
def test_unrelated_or_forged_ready_pid_is_rejected(monkeypatch, tmp_path, case):
    """无关进程、孙进程、错误模块/case、旧创建时间及缺失 PID 一律拒绝。"""

    from tests.integration import cross_host_product_mcp_process_owner as owner

    rows = _records(tmp_path)
    if case == "unrelated":
        claimed = 9090
    else:
        claimed = 28884
        if case == "grandchild":
            rows[claimed] = dict(rows[claimed], parent_pid=10000)
        elif case == "wrong_module":
            rows[claimed] = dict(rows[claimed], command_line="python.exe -m unrelated.module")
        elif case == "wrong_case":
            rows[claimed] = dict(
                rows[claimed],
                command_line=(
                    "python.exe -m "
                    "tests.integration.cross_host_product_live_composition OTHER-CASE"
                ),
            )
        elif case == "older":
            rows[claimed] = dict(
                rows[claimed], created_at="2026-10-11T06:29:00.0000000Z"
            )
        elif case == "missing":
            rows.pop(claimed)
    monkeypatch.setattr(owner, "_windows_process_info", rows.get)
    with pytest.raises(ValueError, match="LIVE_MCP_PROVENANCE_INVALID"):
        resolve_managed_mcp_identity(21272, claimed, tmp_path)


def test_interpreter_without_launcher_is_also_supported(monkeypatch, tmp_path):
    """实际解释器本身就是 Popen PID 时，不要求另行创建子进程。"""

    from tests.integration import cross_host_product_mcp_process_owner as owner

    rows = _records(tmp_path)
    monkeypatch.setattr(owner, "_windows_process_info", rows.get)
    identity = resolve_managed_mcp_identity(21272, 21272, tmp_path)
    assert identity.server_pid == identity.launcher_pid


def test_process_query_reads_windows_os_not_ready_file(monkeypatch):
    """必须使用 Win32_Process 查询 OS PID/parent/command/creation，不信自报文件。"""

    from tests.integration import cross_host_product_mcp_process_owner as owner

    monkeypatch.setattr(owner, "_running_windows", lambda: True)
    seen = []

    def run(argv, **kwargs):
        """记录系统命令，返回模拟的 Win32_Process 原始事实。"""

        seen.append((argv, kwargs))
        return SimpleNamespace(
            returncode=0,
            stdout=json.dumps(_records(Path("C:/case"))[28884]),
        )

    monkeypatch.setattr(owner.subprocess, "run", run)
    assert _windows_process_info(28884)["parent_pid"] == 21272
    assert "Get-CimInstance Win32_Process" in seen[0][0][-1]
    assert seen[0][1]["env"]["DSP_INSPECT_PROCESS_ID"] == "28884"
    with pytest.raises(ValueError, match="LIVE_MCP_PROVENANCE_INVALID"):
        _windows_process_info(-1)
    assert len(seen) == 1


def test_cleanup_kills_launcher_tree_then_orphaned_validated_interpreter(
    monkeypatch, tmp_path
):
    """launcher 进程树清理遗漏子进程时，按原 OS 身份补杀实际解释器。"""

    from tests.integration import cross_host_product_mcp_process_owner as owner

    rows = _records(tmp_path)
    monkeypatch.setattr(owner, "_windows_process_info", rows.get)
    verified = resolve_managed_mcp_identity(21272, 28884, tmp_path)
    monkeypatch.setattr(owner, "_running_windows", lambda: True)
    killed = []

    def run(argv, **_kwargs):
        """模拟 Windows taskkill：第一步仅杀 launcher，第二步才清走孤儿进程。"""

        killed.append(argv)
        if argv[3] == "28884":
            rows.pop(28884)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(owner.subprocess, "run", run)
    terminate_managed_mcp_tree(
        SimpleNamespace(pid=21272, poll=lambda: None), verified
    )
    assert killed == [
        ["taskkill.exe", "/F", "/PID", "21272", "/T"],
        ["taskkill.exe", "/F", "/PID", "28884"],
    ]


def test_cleanup_never_kills_reused_unrelated_interpreter_pid(monkeypatch, tmp_path):
    """身份漂移后只能清理本次 launcher，不能杀死复用 PID 的外部解释器。"""

    from tests.integration import cross_host_product_mcp_process_owner as owner

    rows = _records(tmp_path)
    monkeypatch.setattr(owner, "_windows_process_info", rows.get)
    verified = resolve_managed_mcp_identity(21272, 28884, tmp_path)
    rows[28884] = dict(rows[28884], created_at="2026-10-11T06:35:00.0000000Z")
    monkeypatch.setattr(owner, "_running_windows", lambda: True)
    killed = []

    def run(argv, **_kwargs):
        """保留实际执行 PID 以审计清理不能越界。"""

        killed.append(argv)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(owner.subprocess, "run", run)
    terminate_managed_mcp_tree(
        SimpleNamespace(pid=21272, poll=lambda: None), verified
    )
    assert killed == [["taskkill.exe", "/F", "/PID", "21272", "/T"]]


def test_managed_driver_uses_child_pid_for_readiness_listener_and_exit(
    monkeypatch, tmp_path
):
    """driver 的 readiness、监听端口、存活检查及退出都使用真实解释器 PID。"""

    from tests.integration import cross_host_product_live_driver as driver
    from tests.integration import cross_host_product_live_support as support
    from tests.integration.cross_host_product_mcp_process_owner import (
        ManagedMcpOsIdentity,
    )

    ready = {
        "case_id": "case-1",
        "implementation_head": "a" * 40,
        "pid": 28884,
        "python_sources": {},
    }
    (tmp_path / "mcp-ready.json").write_text(json.dumps(ready), encoding="utf-8")
    events = []

    class Launcher:
        """模拟由 Popen 控制、PID 为 21272 的 venv 启动器。"""

        pid = 21272
        stopped = False

        def poll(self):
            """保留受控启动器的模拟存活状态。"""

            return 0 if self.stopped else None

        def terminate(self):
            """记录启动器兜底停止动作。"""

            self.stopped = True
            events.append("terminate_launcher")

        def wait(self, timeout):
            """记录清理过程已回收 launcher。"""

            events.append("wait_launcher")
            return 0

    launcher = Launcher()
    identity = ManagedMcpOsIdentity(
        launcher_pid=21272,
        launcher_created_at="2026-10-11T06:31:00Z",
        server_pid=28884,
        server_created_at="2026-10-11T06:31:01Z",
        server_parent_pid=21272,
        server_command_line="python.exe -m reviewed.module",
    )
    monkeypatch.setattr(driver.subprocess, "Popen", lambda *args, **kwargs: launcher)
    monkeypatch.setattr(driver, "validate_python_source_manifest", lambda _: None)
    monkeypatch.setattr(
        driver,
        "resolve_managed_mcp_identity",
        lambda launcher_pid, ready_pid, directory: (
            events.append(("resolve", launcher_pid, ready_pid)) or identity
        ),
    )
    monkeypatch.setattr(
        driver,
        "assert_managed_mcp_alive",
        lambda identity, directory: events.append(("live", identity.server_pid)),
    )
    monkeypatch.setattr(
        driver,
        "terminate_managed_mcp_tree",
        lambda process, identity: events.append(("cleanup", identity.server_pid)),
    )
    monkeypatch.setattr(
        driver,
        "_verify_listener_pid",
        lambda url, pid: events.append(("listener", pid)) or pid == 28884,
    )
    monkeypatch.setattr(
        support,
        "_validate_mcp_tool_catalog",
        lambda tools: events.append(("catalog", tools)),
    )
    import mcp

    class Client:
        """纯离线 MCP tool catalog，用于验证 PID 放行后的调用顺序。"""

        async def __aenter__(self):
            """创建独立测试会话。"""

            return self

        async def __aexit__(self, *args):
            """正常关闭测试会话。"""

            return None

        async def list_tools(self):
            """返回窄测试工具集合，不建立真实 MCP 连接。"""

            return SimpleNamespace(
                tools=[SimpleNamespace(name="product.wall_thickness.get")]
            )

    monkeypatch.setattr(mcp, "Client", lambda url: Client())
    with driver.ManagedMcpProcess(
        tmp_path, case_id="case-1", head="a" * 40, check_head=lambda: None
    ) as managed:
        driver._wait_managed_catalog(
            SimpleNamespace(mcp_url="http://127.0.0.1:8016/mcp"),
            managed,
            lambda: None,
        )
        assert managed.server_identity.server_pid == 28884
    assert ("resolve", 21272, 28884) in events
    assert events.count(("listener", 28884)) == 2
    assert ("cleanup", 28884) in events
    assert ("listener", 21272) not in events


def test_managed_driver_rejects_unrelated_ready_and_cleans_up(
    monkeypatch, tmp_path
):
    """case/head 全部正确也不得放行无关 readiness PID，失败必须进入清理。"""

    from tests.integration import cross_host_product_live_driver as driver

    (tmp_path / "mcp-ready.json").write_text(
        json.dumps(
            {
                "case_id": "case-1",
                "implementation_head": "a" * 40,
                "pid": 9090,
                "python_sources": {},
            }
        ),
        encoding="utf-8",
    )
    events = []

    class Launcher:
        """拒绝后仍能被 driver 正常终止的假启动器。"""

        pid = 21272

        def poll(self):
            """模拟仍存活的 launcher。"""

            return None

        def terminate(self):
            """记录兜底终止。"""

            events.append("terminate")

        def wait(self, timeout):
            """记录子进程已回收。"""

            events.append("wait")
            return 0

    monkeypatch.setattr(driver.subprocess, "Popen", lambda *args, **kwargs: Launcher())

    def reject_os_identity(*args):
        """模拟 Windows OS 查询证明 ready PID 与本次 launcher 无关。"""

        raise ValueError("LIVE_MCP_PROVENANCE_INVALID")

    monkeypatch.setattr(driver, "resolve_managed_mcp_identity", reject_os_identity)
    monkeypatch.setattr(
        driver,
        "terminate_managed_mcp_tree",
        lambda process, identity: events.append("cleanup_tree"),
    )
    with pytest.raises(ValueError, match="LIVE_MCP_PROVENANCE_INVALID"):
        with driver.ManagedMcpProcess(
            tmp_path, case_id="case-1", head="a" * 40, check_head=lambda: None
        ):
            raise AssertionError("伪造 readiness 不得进入 MCP 交互")
    assert events == ["cleanup_tree", "terminate", "wait"]
