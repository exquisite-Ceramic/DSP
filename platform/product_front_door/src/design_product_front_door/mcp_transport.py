"""Product Front Door 的 loopback-only Streamable HTTP transport。"""

from __future__ import annotations

from .mcp_server import build_mcp_server

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_bind_address(host: str, port: int) -> None:
    """没有 Enterprise Gateway auth/mTLS 前，只允许显式 loopback bind。"""

    if not isinstance(host, str) or host.lower() not in _LOOPBACK_HOSTS:
        raise ValueError(
            "Product Front Door MCP bind host must be loopback until Gateway "
            "authentication/mTLS is implemented"
        )
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")


def run_streamable_http(
    service: object,
    *,
    host: str = "127.0.0.1",
    port: int = 8010,
) -> None:
    """通过仓库 MCP 2.x server 运行 stateless JSON Streamable HTTP。"""

    validate_bind_address(host, port)
    server = build_mcp_server(service)
    server.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )


__all__ = ["run_streamable_http", "validate_bind_address"]
