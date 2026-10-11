"""Task 16A：生产双 Host 现场 preflight 的纯离线 RED/GREEN 契约。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.integration.cross_host_product_live_support import (
    CrossHostProductLiveConfig,
    _validate_mcp_tool_catalog,
    build_production_host_factories,
    verify_fixture_sha256,
)


def _configured(monkeypatch, tmp_path: Path) -> dict[str, str]:
    """生成仅用于配置测试的路径和值，不连接模型、数据库或 Host。"""

    values = {
        "DSP_TEST_POSTGRES_DSN": "postgresql://localhost/dsp_test",
        "DSP_AUTOCAD_ENDPOINT": "dsp-auto-live",
        "DSP_AUTOCAD_DOCUMENT_REF": str(tmp_path / "sample.dwg"),
        "DSP_AUTOCAD_FIXTURE_PATH": str(tmp_path / "sample.dwg"),
        "DSP_AUTOCAD_NATIVE_ID": "AB12",
        "DSP_AUTOCAD_HOST_INSTANCE_ID": "AUTO-1",
        "DSP_REVIT_LIVE_PIPE": "dsp-revit-live",
        "DSP_REVIT_LIVE_DOCUMENT_REF": str(tmp_path / "sample.rvt"),
        "DSP_REVIT_LIVE_FIXTURE_PATH": str(tmp_path / "sample.rvt"),
        "DSP_REVIT_LIVE_WALL_UNIQUE_ID": "REVIT-WALL-1",
        "DSP_REVIT_LIVE_HOST_INSTANCE_ID": "REVIT-1",
        "DSP_AGENT_INTERPRETER_COMMAND_JSON": json.dumps(
            ["C:/reviewed/model-interpreter.exe", "--model", "reviewed-model"]
        ),
        "DSP_AGENT_MODEL_NAME": "reviewed-model",
        "DSP_CROSS_HOST_PRODUCT_MCP_URL": "http://127.0.0.1:8010/mcp",
        "DSP_AUTOCAD_BUILD_IDENTITY": "2026/live-build",
        "DSP_REVIT_BUILD_IDENTITY": "2027/net10/live-build",
    }
    for name, content in (("sample.dwg", b"dwg-fixture"), ("sample.rvt", b"rvt-fixture")):
        path = tmp_path / name
        path.write_bytes(content)
        key = (
            "DSP_AUTOCAD_FIXTURE_SHA256"
            if name.endswith(".dwg")
            else "DSP_REVIT_LIVE_FIXTURE_SHA256"
        )
        values[key] = hashlib.sha256(content).hexdigest()

    for key, value in values.items():
        monkeypatch.setenv(key, value)
    return values


def test_preflight_config_requires_explicit_model_and_mcp(monkeypatch, tmp_path) -> None:
    """缺少真实模型启动约定或 loopback MCP 不得进入 Host I/O。"""

    values = _configured(monkeypatch, tmp_path)
    monkeypatch.delenv("DSP_AGENT_INTERPRETER_COMMAND_JSON")
    with pytest.raises(ValueError, match="LIVE_ENV_MISSING"):
        CrossHostProductLiveConfig.from_environment()

    monkeypatch.setenv(
        "DSP_AGENT_INTERPRETER_COMMAND_JSON",
        values["DSP_AGENT_INTERPRETER_COMMAND_JSON"],
    )
    monkeypatch.setenv("DSP_CROSS_HOST_PRODUCT_MCP_URL", "https://remote.example/mcp")
    with pytest.raises(ValueError, match="loopback"):
        CrossHostProductLiveConfig.from_environment()


def test_preflight_rejects_shell_string_as_model_command(monkeypatch, tmp_path) -> None:
    """模型命令必须是 JSON argv，禁止 shell 解释和隐式环境继承。"""

    _configured(monkeypatch, tmp_path)
    monkeypatch.setenv("DSP_AGENT_INTERPRETER_COMMAND_JSON", "python model.py")
    with pytest.raises(ValueError, match="LIVE_MODEL_COMMAND_INVALID"):
        CrossHostProductLiveConfig.from_environment()


def test_preflight_rejects_mismatched_reviewed_fixture(monkeypatch, tmp_path) -> None:
    """文件字节漂移必须在模型、网络和 Host I/O 之前停止。"""

    _configured(monkeypatch, tmp_path)
    (tmp_path / "sample.rvt").write_bytes(b"tampered fixture")
    with pytest.raises(ValueError, match="LIVE_FIXTURE_HASH_MISMATCH"):
        CrossHostProductLiveConfig.from_environment()


def test_preflight_validates_model_and_fixture_without_invocation(
    monkeypatch, tmp_path
) -> None:
    """构造配置时不得自动执行模型、MCP 或任何 Host 命令。"""

    _configured(monkeypatch, tmp_path)
    config = CrossHostProductLiveConfig.from_environment()
    assert config.model_command[0].endswith("model-interpreter.exe")
    assert config.mcp_url == "http://127.0.0.1:8010/mcp"
    assert config.autocad_fixture_sha256 == verify_fixture_sha256(
        config.autocad_fixture_path, config.autocad_fixture_sha256
    )
    assert config.revit_fixture_sha256 == verify_fixture_sha256(
        config.revit_fixture_path, config.revit_fixture_sha256
    )


def test_production_transport_factories_reject_cross_bound_locator(
    monkeypatch, tmp_path
) -> None:
    """两个 Host locator 必须 exact match，禁止任意目标或 fake dispatcher。"""

    _configured(monkeypatch, tmp_path)
    config = CrossHostProductLiveConfig.from_environment()
    autocad_factory, revit_factory = build_production_host_factories(config)
    with pytest.raises(ValueError, match="LIVE_HOST_LOCATOR_MISMATCH"):
        autocad_factory("other-pipe")
    with pytest.raises(ValueError, match="LIVE_HOST_LOCATOR_MISMATCH"):
        revit_factory("other-pipe")
    assert callable(autocad_factory)
    assert callable(revit_factory)


def test_real_mcp_catalog_must_be_exact_three_product_tools() -> None:
    """拒绝缺失、旧版或额外 tool catalog，不允许伪造已连接 MCP。"""

    expected = (
        "product.wall_thickness.submit",
        "product.wall_thickness.get",
        "product.wall_thickness.resume_operation_proposal",
    )
    _validate_mcp_tool_catalog(expected)
    with pytest.raises(ValueError, match="LIVE_MCP_CATALOG_INVALID"):
        _validate_mcp_tool_catalog(expected[:-1])
    with pytest.raises(ValueError, match="LIVE_MCP_CATALOG_INVALID"):
        _validate_mcp_tool_catalog((*expected, "synthetic.success"))


def test_live_config_repr_does_not_leak_dsn_or_model_argv(
    monkeypatch, tmp_path
) -> None:
    """即使测试失败打印配置，也不能把数据库凭据或模型命令参数泄漏到日志。"""

    _configured(monkeypatch, tmp_path)
    monkeypatch.setenv(
        "DSP_TEST_POSTGRES_DSN",
        "postgresql://user:live-secret@localhost/dsp_test",
    )
    monkeypatch.setenv(
        "DSP_AGENT_INTERPRETER_COMMAND_JSON",
        json.dumps(["C:/reviewed/model.exe", "--secret", "model-secret"]),
    )
    rendered = repr(CrossHostProductLiveConfig.from_environment())
    assert "live-secret" not in rendered
    assert "model-secret" not in rendered
    assert "model_command" not in rendered


def _preflight_boundaries(monkeypatch, config, failure=None):
    """仅替换外部 I/O，保留生产 factory、dispatcher、fact normalizer 和 Revit READ。"""

    import mcp
    import psycopg
    from autocad_sidecar.ipc import transport as autocad_transport
    from revit_sidecar import named_pipe

    from tests.integration import cross_host_product_live_support as support

    events = []

    class Database:
        """数据库边界只接受预检允许的 SELECT 1。"""

        def __enter__(self):
            events.append("postgres.open")
            if failure == "postgres":
                raise OSError("database unavailable")
            return self

        def execute(self, sql):
            assert sql == "SELECT 1"
            events.append("postgres.read")
            return SimpleNamespace(fetchone=lambda: (1,))

        def __exit__(self, *args):
            events.append("postgres.close")

    class CatalogClient:
        """MCP 边界不提供 submit/resume/tool-call，错误调用会直接失败。"""

        def __init__(self, endpoint):
            assert endpoint == config.mcp_url

        async def __aenter__(self):
            events.append("mcp.open")
            return self

        async def __aexit__(self, *args):
            events.append("mcp.close")

        async def list_tools(self):
            events.append("mcp.catalog")
            names = [
                "product.wall_thickness.submit",
                "product.wall_thickness.get",
                "product.wall_thickness.resume_operation_proposal",
            ]
            if failure == "catalog":
                names.pop()
            return SimpleNamespace(tools=[SimpleNamespace(name=n) for n in names])

    class AutoPipe:
        """在真实 HostAdapter 下记录 wire command 及连接释放，禁止 mutation。"""

        def __init__(self, pipe_name):
            assert pipe_name == config.autocad_endpoint

        async def open(self):
            events.append("autocad.open")
            if failure == "autocad_open":
                raise OSError("pipe unavailable")

        async def close(self):
            events.append("autocad.close")

        async def exchange(self, data, **kwargs):
            envelope = json.loads(data)
            command = envelope["payload"]
            assert command["mode"] == "READ"
            assert command["operation"] == "design.extract_native_snapshot"
            assert command["arguments"] == {"handles": [config.autocad_native_id]}
            events.append("autocad.read")
            if failure == "autocad_read":
                raise OSError("pipe read failed")
            payload = {
                "hostInstanceId": "wrong" if failure == "identity" else "AUTO-1",
                "documentId": config.autocad_document_ref,
                "revision": 7,
                "entities": [{
                    "nativeId": config.autocad_native_id,
                    "nativeKind": "LWPOLYLINE",
                    "layer": "WALL",
                    "properties": {"constantWidth": {
                        "value": 201 if failure == "baseline" else 200,
                        "unit": "mm",
                    }},
                }],
            }
            return json.dumps({
                "request_id": envelope["request_id"],
                "status": "OK",
                "result": {"command_id": command["command_id"],
                           "status": "OK", "payload": payload},
            }).encode()

    class RevitPipe:
        """真实 READ ports 解析此边界的响应；不替换身份及 revision 校验。"""

        def __init__(self, *, pipe_name):
            assert pipe_name == config.revit_pipe

        def request(self, command):
            assert command.mode == "READ"
            assert command.document_id == config.revit_document_ref
            events.append("revit." + command.operation)
            payload = {"document_id": config.revit_document_ref,
                       "host_instance_id": "REVIT-1"}
            if command.operation == "context.current_selection":
                payload.update(document_title="fixture", selected_elements=[
                    {"unique_id": "REVIT-WALL-1", "native_kind": "Wall"}
                ])
            else:
                assert command.operation == "read_wall_thickness_snapshot"
                assert command.target_native_refs[0].native_id == "REVIT-WALL-1"
                payload.update(
                    wall_unique_id="REVIT-WALL-1", wall_type_unique_id="TYPE-1",
                    native_kind="Wall", builtin_category="OST_Walls",
                    wall_thickness_mm=200.0, location_signature="line",
                    relationship_signature="isolated", revision_before=9,
                    revision_after=10 if failure == "revision" else 9,
                )
            return {"status": "OK", "payload": payload, "revision_after": 9}

    monkeypatch.setattr(support, "_require_windows_live", lambda: None)
    monkeypatch.setattr(psycopg, "connect", lambda *a, **kw: Database())
    monkeypatch.setattr(mcp, "Client", CatalogClient)
    monkeypatch.setattr(autocad_transport, "PipeTransport", AutoPipe)
    monkeypatch.setattr(named_pipe, "NamedPipeTransport", RevitPipe)
    return events


@pytest.mark.asyncio
async def test_preflight_reads_production_adapters_and_releases_pipe(monkeypatch, tmp_path):
    """遗漏 close 或误发 mutation 时失败；两个 Host revision 无须相等。"""

    from tests.integration.cross_host_product_live_support import run_read_only_preflight

    _configured(monkeypatch, tmp_path)
    config = CrossHostProductLiveConfig.from_environment()
    events = _preflight_boundaries(monkeypatch, config)
    report = await run_read_only_preflight(config)
    assert report["result"] == "READ_ONLY_READY"
    assert report["autocad_revision"] == 7
    assert report["revit_revision"] == 9
    assert report["autocad_baseline_mm"] == report["revit_baseline_mm"] == 200
    assert events == [
        "postgres.open", "postgres.read", "postgres.close",
        "mcp.open", "mcp.catalog", "mcp.close",
        "autocad.open", "autocad.read", "autocad.close",
        "revit.context.current_selection", "revit.read_wall_thickness_snapshot",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", [
    "postgres", "catalog", "autocad_open", "autocad_read",
    "identity", "baseline", "revision",
])
async def test_preflight_failure_stops_and_releases_pipe(monkeypatch, tmp_path, failure):
    """任一边界失败不得继续后续 Host I/O，已创建的 AutoCAD 资源必须释放。"""

    from tests.integration.cross_host_product_live_support import run_read_only_preflight

    _configured(monkeypatch, tmp_path)
    config = CrossHostProductLiveConfig.from_environment()
    events = _preflight_boundaries(monkeypatch, config, failure)
    with pytest.raises((OSError, ValueError)):
        await run_read_only_preflight(config)
    if failure in {"postgres", "catalog"}:
        assert not any(e.startswith(("autocad.", "revit.")) for e in events)
    else:
        assert events.count("autocad.close") == 1
        if failure != "revision":
            assert not any(e.startswith("revit.") for e in events)
