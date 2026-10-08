"""Task 16A：生产双 Host 现场 preflight 的纯离线 RED/GREEN 契约。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

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
