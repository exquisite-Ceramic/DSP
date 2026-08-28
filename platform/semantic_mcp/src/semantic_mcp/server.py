"""MCP tool catalog and thin delegation for the DSP Semantic Service."""

from __future__ import annotations

from collections.abc import Callable
import json
import logging

from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, TextContent
from pydantic import JsonValue
from semantic_service import SemanticService, SemanticServiceError

from semantic_mcp.errors import internal_error_result, semantic_error_result
from semantic_mcp.wire import (
    SemanticClaimInput,
    decode_semantic_claim,
    encode_environment,
    encode_manifest,
    encode_mapping_candidates,
    encode_resolved_term,
    encode_term_description,
    encode_term_schema,
    encode_validation_findings,
)


logger = logging.getLogger(__name__)


def _success_result(payload: dict[str, JsonValue]) -> CallToolResult:
    text = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
        is_error=False,
    )


def _invoke(call: Callable[[], dict[str, JsonValue]]) -> CallToolResult:
    """Execute one already-schema-validated tool body behind the safe error boundary."""

    try:
        return _success_result(call())
    except SemanticServiceError as exc:
        return semantic_error_result(exc)
    except Exception:
        logger.exception("Unexpected Semantic MCP tool failure")
        return internal_error_result()


def build_mcp_server(service: SemanticService) -> MCPServer:
    """Build the fixed Semantic MCP v1 catalog around an injected service."""

    server = MCPServer("DSP Semantic Service")

    @server.tool(name="semantic.resolve_term")
    def resolve_term(term_id: str, environment_id: str) -> CallToolResult:
        return _invoke(
            lambda: encode_resolved_term(service.resolve_term(term_id, environment_id))
        )

    @server.tool(name="semantic.describe_term")
    def describe_term(
        term_id: str,
        environment_id: str,
        locale: str | None = None,
    ) -> CallToolResult:
        return _invoke(
            lambda: encode_term_description(
                service.describe_term(term_id, environment_id, locale)
            )
        )

    @server.tool(name="semantic.get_term_schema")
    def get_term_schema(term_id: str, environment_id: str) -> CallToolResult:
        return _invoke(
            lambda: encode_term_schema(service.get_term_schema(term_id, environment_id))
        )

    @server.tool(name="semantic.validate_claim")
    def validate_claim(
        claim: SemanticClaimInput,
        environment_id: str,
    ) -> CallToolResult:
        return _invoke(
            lambda: encode_validation_findings(
                service.validate_claim(
                    decode_semantic_claim(claim),
                    environment_id,
                )
            )
        )

    @server.tool(name="semantic.find_mappings")
    def find_mappings(
        source_claim: SemanticClaimInput,
        environment_id: str,
        target_namespace: str | None = None,
    ) -> CallToolResult:
        return _invoke(
            lambda: encode_mapping_candidates(
                service.find_mappings(
                    decode_semantic_claim(source_claim),
                    environment_id,
                    target_namespace,
                )
            )
        )

    @server.tool(name="semantic.get_provider_manifest")
    def get_provider_manifest(provider_id: str, version: str) -> CallToolResult:
        return _invoke(
            lambda: encode_manifest(service.get_provider_manifest(provider_id, version))
        )

    @server.tool(name="semantic.get_environment")
    def get_environment(environment_id: str) -> CallToolResult:
        return _invoke(lambda: encode_environment(service.get_environment(environment_id)))

    return server
