import importlib

import pytest


class _FakeServer:
    def __init__(self) -> None:
        self.run_calls: list[dict[str, object]] = []

    def run(self, **kwargs) -> None:
        self.run_calls.append(kwargs)


def _transport():
    try:
        return importlib.import_module("semantic_mcp.transport")
    except ModuleNotFoundError:
        pytest.fail("semantic_mcp.transport is not implemented")


@pytest.mark.parametrize("host", ("127.0.0.1", "localhost", "LOCALHOST", "::1"))
@pytest.mark.parametrize("port", (1, 8001, 65535))
def test_validate_bind_address_accepts_only_valid_loopback_pairs(host, port):
    module = _transport()
    module.validate_bind_address(host, port)


@pytest.mark.parametrize(
    "host",
    (
        "0.0.0.0",
        "192.168.1.5",
        "example.com",
        "",
        "127.0.0.2",
    ),
)
def test_validate_bind_address_rejects_non_loopback_host(host):
    module = _transport()
    with pytest.raises(ValueError, match="loopback"):
        module.validate_bind_address(host, 8001)


@pytest.mark.parametrize("port", (0, -1, 65536, 100000))
def test_validate_bind_address_rejects_invalid_port(port):
    module = _transport()
    with pytest.raises(ValueError, match="between 1 and 65535"):
        module.validate_bind_address("127.0.0.1", port)


def test_run_streamable_http_uses_stateless_json_transport(monkeypatch):
    module = _transport()
    server = _FakeServer()
    service = object()
    built_with: list[object] = []

    def fake_build_mcp_server(value):
        built_with.append(value)
        return server

    monkeypatch.setattr(module, "build_mcp_server", fake_build_mcp_server)
    result = module.run_streamable_http(service, host="localhost", port=8123)

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


def test_public_package_exports_only_server_builder_and_http_runner():
    import semantic_mcp

    assert semantic_mcp.__all__ == ["build_mcp_server", "run_streamable_http"]
    assert callable(semantic_mcp.build_mcp_server)
    assert callable(semantic_mcp.run_streamable_http)
