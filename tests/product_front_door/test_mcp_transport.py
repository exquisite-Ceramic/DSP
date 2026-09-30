"""Product Front Door MCP transport 的 loopback-only contract。"""

from __future__ import annotations

from inspect import signature

import pytest
from design_product_front_door.mcp_transport import (
    run_streamable_http,
    validate_bind_address,
)


class _FakeServer:
    """记录 MCPServer.run 收到的 transport 参数，避免单元测试真正占用端口。"""

    def __init__(self) -> None:
        """初始化空的运行调用记录。"""

        self.run_calls: list[dict[str, object]] = []

    def run(self, **kwargs: object) -> None:
        """记录一次 server.run 调用。"""

        self.run_calls.append(kwargs)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "LOCALHOST", "::1"])
def test_mcp_transport_accepts_only_declared_loopback_hosts(host: str) -> None:
    """Product Front Door 可绑定的 host 与现有 Semantic MCP 安全边界保持一致。"""

    # 这里仅验证 bind authority，不启动网络服务；真实 Streamable HTTP 会在后续 E2E 覆盖。
    validate_bind_address(host, 8010)


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "192.168.1.10", "10.0.0.8", "example.com", "", "127.0.0.2"],
)
def test_mcp_transport_rejects_non_loopback_bind(host: str) -> None:
    """没有 Enterprise Gateway auth/mTLS 前，外部网卡或任意 hostname 必须 fail closed。"""

    with pytest.raises(ValueError, match="loopback"):
        validate_bind_address(host, 8010)


@pytest.mark.parametrize("port", [0, -1, 65536, True, "8010"])
def test_mcp_transport_rejects_invalid_ports(port: object) -> None:
    """端口必须是 1..65535 的真实整数，不能接受 bool、字符串或越界值。"""

    with pytest.raises(ValueError, match="between 1 and 65535"):
        validate_bind_address("127.0.0.1", port)  # type: ignore[arg-type]


def test_mcp_transport_uses_frozen_default_loopback_endpoint() -> None:
    """transport entrypoint 的默认地址必须冻结为 127.0.0.1:8010，避免意外扩大 trust boundary。"""

    parameters = signature(run_streamable_http).parameters

    assert parameters["host"].default == "127.0.0.1"
    assert parameters["port"].default == 8010


def test_run_streamable_http_uses_repository_mcp_2x_transport(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP runner 必须通过真实 MCPServer builder 启动 stateless JSON Streamable HTTP。"""

    import design_product_front_door.mcp_transport as transport_module

    server = _FakeServer()
    service = object()
    built_with: list[object] = []

    def fake_build_mcp_server(value: object) -> _FakeServer:
        """记录 transport 是否把同一个 application service 交给 MCP server builder。"""

        built_with.append(value)
        return server

    monkeypatch.setattr(transport_module, "build_mcp_server", fake_build_mcp_server)

    result = run_streamable_http(service, host="localhost", port=8123)

    assert result is None
    assert built_with == [service]
    assert server.run_calls == [
        {
            "transport": "streamable-http",
            "host": "localhost",
            "port": 8123,
            "stateless_http": True,
            "json_response": True,
        }
    ]


def test_public_package_exports_mcp_server_and_http_runner() -> None:
    """source-only Product Front Door public API 必须包含 MCP builder/runner，不要求缩减既有导出。"""

    import design_product_front_door

    assert "build_mcp_server" in design_product_front_door.__all__
    assert "run_streamable_http" in design_product_front_door.__all__
    assert callable(design_product_front_door.build_mcp_server)
    assert callable(design_product_front_door.run_streamable_http)
