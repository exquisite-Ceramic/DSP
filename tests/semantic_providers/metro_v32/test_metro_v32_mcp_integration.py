import pytest
from mcp import Client

from ifc43_semantic_provider import IFC43_PROVIDER
from metro_semantic_provider import METRO_V32_CATALOG, METRO_V32_PROVIDER
from semantic_mcp.server import build_mcp_server
from semantic_service import (
    ProviderRef,
    SemanticEnvironmentStore,
    SemanticProviderRegistry,
    SemanticService,
)


@pytest.mark.asyncio
async def test_existing_semantic_mcp_surface_serves_metro_provider():
    registry = SemanticProviderRegistry()
    registry.register(IFC43_PROVIDER)
    registry.register(METRO_V32_PROVIDER)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (
            ProviderRef("buildingSMART.ifc43", "4.3.2.0"),
            ProviderRef("dsp.metro.semantic", "3.2"),
        ),
        registry,
    )
    service = SemanticService(registry, store)

    async with Client(build_mcp_server(service)) as client:
        assert client.protocol_version == "2026-07-28"
        tools = await client.list_tools()
        assert not any(tool.name.startswith("metro.") for tool in tools.tools)

        resolved = await client.call_tool(
            "semantic.resolve_term",
            {
                "term_id": "metro:TunnelSegment.ConstructionMethod",
                "environment_id": environment.environment_id,
            },
        )
        schema = await client.call_tool(
            "semantic.get_term_schema",
            {
                "term_id": "metro:Mapping.RunningRail.ToIfcRail",
                "environment_id": environment.environment_id,
            },
        )
        mappings = await client.call_tool(
            "semantic.find_mappings",
            {
                "source_claim": {
                    "subject": "rail-1",
                    "canonical_term_id": "metro:RunningRail",
                },
                "environment_id": environment.environment_id,
                "target_namespace": "ifc",
            },
        )

    assert resolved.is_error is False
    assert resolved.structured_content["provenance"] == {
        "provider_id": "dsp.metro.semantic",
        "version": "3.2",
        "content_hash": METRO_V32_CATALOG.content_hash,
    }
    assert schema.is_error is False
    assert schema.structured_content["schema"]["state"] == "ACTIVE"
    assert schema.structured_content["schema"]["target_term_id"] == "ifc:IfcRail"
    assert mappings.is_error is False
    assert mappings.structured_content["mappings"] == [
        {
            "mapping_id": "metro:Mapping.RunningRail.ToIfcRail",
            "target_term_id": "ifc:IfcRail",
            "provenance": {
                "provider_id": "dsp.metro.semantic",
                "version": "3.2",
                "content_hash": METRO_V32_CATALOG.content_hash,
            },
            "evidence": [],
        }
    ]
