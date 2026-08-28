import pytest
from mcp import Client

from semantic_mcp.server import build_mcp_server
from semantic_service import (
    ProviderRef,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
)
from ifc43_semantic_provider import IFC43_CATALOG, IFC43_PROVIDER


@pytest.mark.asyncio
async def test_real_mcp_client_resolves_ifc43_term_and_schema():
    registry = SemanticProviderRegistry()
    registry.register(IFC43_PROVIDER)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (ProviderRef("buildingSMART.ifc43", "4.3.2.0"),),
        registry,
    )
    service = SemanticService(registry, store)

    async with Client(build_mcp_server(service)) as client:
        assert client.protocol_version == "2026-07-28"
        resolved = await client.call_tool(
            "semantic.resolve_term",
            {"term_id": "ifc:IfcWall", "environment_id": environment.environment_id},
        )
        schema = await client.call_tool(
            "semantic.get_term_schema",
            {"term_id": "ifc:IfcWall", "environment_id": environment.environment_id},
        )

    assert resolved.is_error is False
    assert resolved.structured_content["provenance"]["content_hash"] == IFC43_CATALOG.content_hash
    assert schema.is_error is False
    assert "ifc:IfcRoot.Name" in schema.structured_content["schema"]["inherited_members"]
