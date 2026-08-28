"""MCP tool catalog for the DSP Semantic Service."""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from semantic_service import SemanticService

from semantic_mcp.wire import SemanticClaimInput


_NOT_IMPLEMENTED = "Semantic MCP delegation is not implemented yet"


def build_mcp_server(service: SemanticService) -> MCPServer:
    """Build the fixed Semantic MCP v1 catalog around an injected service."""

    server = MCPServer("DSP Semantic Service")

    @server.tool(name="semantic.resolve_term")
    def resolve_term(term_id: str, environment_id: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    @server.tool(name="semantic.describe_term")
    def describe_term(
        term_id: str,
        environment_id: str,
        locale: str | None = None,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    @server.tool(name="semantic.get_term_schema")
    def get_term_schema(term_id: str, environment_id: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    @server.tool(name="semantic.validate_claim")
    def validate_claim(claim: SemanticClaimInput, environment_id: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    @server.tool(name="semantic.find_mappings")
    def find_mappings(
        source_claim: SemanticClaimInput,
        environment_id: str,
        target_namespace: str | None = None,
    ) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    @server.tool(name="semantic.get_provider_manifest")
    def get_provider_manifest(provider_id: str, version: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    @server.tool(name="semantic.get_environment")
    def get_environment(environment_id: str) -> None:
        raise NotImplementedError(_NOT_IMPLEMENTED)

    return server
