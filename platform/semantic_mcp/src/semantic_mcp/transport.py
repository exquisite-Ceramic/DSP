"""Safe built-in Streamable HTTP transport for Semantic MCP."""

from __future__ import annotations

from semantic_service import SemanticService

from semantic_mcp.server import build_mcp_server


_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_bind_address(host: str, port: int) -> None:
    """Reject external binding until Enterprise Gateway auth/mTLS is present."""

    if not isinstance(host, str) or host.lower() not in _LOOPBACK_HOSTS:
        raise ValueError(
            "Semantic MCP bind host must be loopback until Gateway authentication/mTLS is implemented"
        )
    if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")


def run_streamable_http(
    service: SemanticService,
    *,
    host: str = "127.0.0.1",
    port: int = 8001,
) -> None:
    """Run the injected Semantic Service over stateless JSON Streamable HTTP."""

    validate_bind_address(host, port)
    server = build_mcp_server(service)
    server.run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )
