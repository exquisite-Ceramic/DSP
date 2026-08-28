import pytest
from mcp import Client

from semantic_mcp.server import build_mcp_server
from semantic_service import (
    ProviderRef,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
)

from dsp_core_semantic_provider import DSP_CORE_CATALOG, DSP_CORE_PROVIDER


def build_real_service():
    registry = SemanticProviderRegistry()
    registry.register(DSP_CORE_PROVIDER)
    environments = SemanticEnvironmentStore()
    environment = environments.pin((ProviderRef("dsp.core", "1.0"),), registry)
    return SemanticService(registry, environments), environment


@pytest.mark.asyncio
async def test_real_mcp_client_resolves_dsp_core_term_and_schema():
    service, environment = build_real_service()

    async with Client(build_mcp_server(service)) as client:
        assert client.protocol_version == "2026-07-28"
        resolved = await client.call_tool(
            "semantic.resolve_term",
            {
                "term_id": "dsp:WallThickness",
                "environment_id": environment.environment_id,
            },
        )
        schema = await client.call_tool(
            "semantic.get_term_schema",
            {
                "term_id": "dsp:WallThickness",
                "environment_id": environment.environment_id,
            },
        )

    assert resolved.is_error is False
    assert resolved.structured_content == {
        "term_id": "dsp:WallThickness",
        "kind": "PROPERTY",
        "provenance": {
            "provider_id": "dsp.core",
            "version": "1.0",
            "content_hash": DSP_CORE_CATALOG.content_hash,
        },
    }
    assert schema.is_error is False
    assert schema.structured_content["term_id"] == "dsp:WallThickness"
    assert schema.structured_content["schema"]["unit"] == "mm"
    assert "description" not in schema.structured_content["schema"]
