"""Product Front Door MCP transport 的 loopback-only RED contract。"""

from __future__ import annotations

from inspect import signature

import pytest

from design_product_front_door.mcp_transport import (
    run_streamable_http,
    validate_bind_address,
)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_mcp_transport_accepts_only_declared_loopback_hosts(host: str) -> None:
    """Product Front Door 可绑定的 host 与现有 Semantic MCP 安全边界保持一致。"""

    # 这里仅验证 bind authority，不启动网络服务；真实 Streamable HTTP 会在后续 GREEN/E2E 覆盖。
    validate_bind_address(host, 8010)


@pytest.mark.parametrize(
    "host",
    ["0.0.0.0", "192.168.1.10", "10.0.0.8", "example.com", ""],
)
def test_mcp_transport_rejects_non_loopback_bind(host: str) -> None:
    """没有 Enterprise Gateway auth/mTLS 前，外部网卡或任意 hostname 必须 fail closed。"""

    with pytest.raises(ValueError):
        validate_bind_address(host, 8010)


@pytest.mark.parametrize("port", [0, -1, 65536, True, "8010"])
def test_mcp_transport_rejects_invalid_ports(port: object) -> None:
    """端口必须是 1..65535 的真实整数，不能接受 bool、字符串或越界值。"""

    with pytest.raises(ValueError):
        validate_bind_address("127.0.0.1", port)  # type: ignore[arg-type]


def test_mcp_transport_uses_frozen_default_loopback_endpoint() -> None:
    """transport entrypoint 的默认地址必须冻结为 127.0.0.1:8010，避免意外扩大 trust boundary。"""

    parameters = signature(run_streamable_http).parameters

    assert parameters["host"].default == "127.0.0.1"
    assert parameters["port"].default == 8010
