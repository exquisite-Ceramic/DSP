import importlib

import pytest
from mcp import Client

from tests.semantic_mcp.helpers import FakeSemanticService


EXPECTED = {
    "semantic.resolve_term",
    "semantic.describe_term",
    "semantic.get_term_schema",
    "semantic.validate_claim",
    "semantic.find_mappings",
    "semantic.get_provider_manifest",
    "semantic.get_environment",
}

EXPECTED_PROPERTIES = {
    "semantic.resolve_term": {"term_id", "environment_id"},
    "semantic.describe_term": {"term_id", "environment_id", "locale"},
    "semantic.get_term_schema": {"term_id", "environment_id"},
    "semantic.validate_claim": {"claim", "environment_id"},
    "semantic.find_mappings": {"source_claim", "environment_id", "target_namespace"},
    "semantic.get_provider_manifest": {"provider_id", "version"},
    "semantic.get_environment": {"environment_id"},
}

EXPECTED_REQUIRED = {
    "semantic.resolve_term": {"term_id", "environment_id"},
    "semantic.describe_term": {"term_id", "environment_id"},
    "semantic.get_term_schema": {"term_id", "environment_id"},
    "semantic.validate_claim": {"claim", "environment_id"},
    "semantic.find_mappings": {"source_claim", "environment_id"},
    "semantic.get_provider_manifest": {"provider_id", "version"},
    "semantic.get_environment": {"environment_id"},
}


def _server_module():
    try:
        return importlib.import_module("semantic_mcp.server")
    except ModuleNotFoundError:
        pytest.fail("semantic_mcp.server is not implemented")


def _resolve_nested_schema(root: dict, property_name: str) -> dict:
    nested = root["properties"][property_name]
    if "$ref" not in nested:
        return nested
    ref = nested["$ref"]
    assert ref.startswith("#/$defs/")
    return root["$defs"][ref.rsplit("/", 1)[-1]]


@pytest.mark.asyncio
async def test_tools_list_is_exact_v1_surface_and_schema_contract():
    server_module = _server_module()
    server = server_module.build_mcp_server(FakeSemanticService())

    async with Client(server) as client:
        listed = await client.list_tools()

    tools = {tool.name: tool for tool in listed.tools}
    assert set(tools) == EXPECTED

    for name, tool in tools.items():
        assert set(tool.input_schema["properties"]) == EXPECTED_PROPERTIES[name]
        assert set(tool.input_schema.get("required", [])) == EXPECTED_REQUIRED[name]

    manifest_schema = tools["semantic.get_provider_manifest"].input_schema
    assert "environment_id" not in manifest_schema["properties"]

    validate_schema = tools["semantic.validate_claim"].input_schema
    claim_schema = _resolve_nested_schema(validate_schema, "claim")
    assert set(claim_schema.get("required", [])) == {"subject"}
    assert claim_schema.get("additionalProperties") is False

    mapping_schema = tools["semantic.find_mappings"].input_schema
    source_claim_schema = _resolve_nested_schema(mapping_schema, "source_claim")
    assert set(source_claim_schema.get("required", [])) == {"subject"}
    assert source_claim_schema.get("additionalProperties") is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "claim",
    (
        {"assurance": "UNKNOWN"},
        {"subject": "S-1", "unknown": 1},
    ),
)
async def test_invalid_nested_claim_is_rejected_before_service_handler(claim):
    server_module = _server_module()
    service = FakeSemanticService()
    server = server_module.build_mcp_server(service)

    async with Client(server) as client:
        result = await client.call_tool(
            "semantic.validate_claim",
            {"environment_id": "sem-env:test", "claim": claim},
        )

    assert result.is_error is True
    assert service.validate_calls == []
