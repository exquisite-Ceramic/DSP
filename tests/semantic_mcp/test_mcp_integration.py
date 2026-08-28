import pytest
from mcp import Client
from semantic_service import EnvironmentNotFoundError, ProviderProvenance, ResolvedTerm
from semantic_mcp.server import build_mcp_server

from tests.semantic_mcp.helpers import FakeSemanticService
from tests.semantic_mcp.test_delegation import CLAIM_INPUT
from tests.semantic_mcp.test_tool_catalog import EXPECTED


@pytest.mark.asyncio
async def test_real_client_negotiates_2026_07_28_and_lists_exact_surface():
    server = build_mcp_server(FakeSemanticService())

    async with Client(server) as client:
        assert client.protocol_version == "2026-07-28"
        result = await client.list_tools()

    assert {tool.name for tool in result.tools} == EXPECTED


@pytest.mark.asyncio
async def test_real_client_receives_successful_structured_result():
    service = FakeSemanticService()
    service.resolve_result = ResolvedTerm(
        "ifc:IfcWall",
        "ENTITY",
        ProviderProvenance("buildingSMART.ifc43", "4.3.2.0", "ifc-content"),
    )

    async with Client(build_mcp_server(service)) as client:
        result = await client.call_tool(
            "semantic.resolve_term",
            {"term_id": "ifc:IfcWall", "environment_id": "sem-env:abc"},
        )

    assert result.is_error is False
    assert result.structured_content == {
        "term_id": "ifc:IfcWall",
        "kind": "ENTITY",
        "provenance": {
            "provider_id": "buildingSMART.ifc43",
            "version": "4.3.2.0",
            "content_hash": "ifc-content",
        },
    }


@pytest.mark.asyncio
async def test_real_client_receives_typed_and_sanitized_failures():
    domain_service = FakeSemanticService()
    domain_service.resolve_error = EnvironmentNotFoundError(
        "secret=/srv/acme/environment-token=abc123"
    )
    unexpected_service = FakeSemanticService()
    unexpected_service.resolve_error = RuntimeError(
        "secret-path=/srv/acme/token=abc123 https://internal.example"
    )

    async with Client(build_mcp_server(domain_service)) as client:
        domain = await client.call_tool(
            "semantic.resolve_term",
            {"term_id": "ifc:IfcWall", "environment_id": "sem-env:missing"},
        )

    async with Client(build_mcp_server(unexpected_service)) as client:
        unexpected = await client.call_tool(
            "semantic.resolve_term",
            {"term_id": "ifc:IfcWall", "environment_id": "sem-env:abc"},
        )

    assert domain.is_error is True
    assert domain.structured_content["error"]["error_code"] == "SEMANTIC_ENVIRONMENT_NOT_FOUND"
    assert unexpected.is_error is True
    assert unexpected.structured_content["error"]["error_code"] == "SEMANTIC_INTERNAL_ERROR"

    rendered = f"{domain.model_dump(by_alias=True)} {unexpected.model_dump(by_alias=True)}"
    assert "abc123" not in rendered
    assert "/srv/acme" not in rendered
    assert "internal.example" not in rendered


@pytest.mark.asyncio
async def test_real_client_rejects_bad_nested_claim_before_service_call():
    service = FakeSemanticService()
    invalid_claim = dict(CLAIM_INPUT)
    invalid_claim["unknown"] = 1

    async with Client(build_mcp_server(service)) as client:
        result = await client.call_tool(
            "semantic.validate_claim",
            {"environment_id": "sem-env:abc", "claim": invalid_claim},
        )

    assert result.is_error is True
    assert service.validate_calls == []
