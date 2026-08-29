"""Host-facing MCP server surface for the AutoCAD sidecar."""

from __future__ import annotations

from typing import Any

from mcp.server.mcpserver import MCPServer

from autocad_sidecar.execution.command_dispatcher import CommandDispatcher


def _design_meta(
    *,
    operation: str,
    category: str,
    entities: list[str] | None = None,
    execution_freshness: list[dict[str, Any]] | None = None,
    effects: list[Any] | None = None,
    risk: str = "NONE",
    preview: bool = False,
    rollback: bool = False,
    idempotent: bool = True,
    verification: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "com.company.design/operation": operation,
        "com.company.design/category": category,
        "com.company.design/entities": entities or [],
        "com.company.design/execution_freshness": execution_freshness or [],
        "com.company.design/effects": effects or [],
        "com.company.design/risk": risk,
        "com.company.design/preview": preview,
        "com.company.design/rollback": rollback,
        "com.company.design/idempotent": idempotent,
        "com.company.design/verification": verification or {"type": "NONE"},
    }


def build_tool_definitions() -> list[dict[str, Any]]:
    """Return the deterministic provider catalog exposed through MCP tools/list."""

    return [
        {
            "name": "context.current_document",
            "description": "Read the active AutoCAD document identity and revision.",
            "inputSchema": {"type": "object", "properties": {}},
            "_meta": _design_meta(
                operation="context.current_document.v1",
                category="CONTEXT",
            ),
        },
        {
            "name": "context.current_selection",
            "description": "Read the current AutoCAD selection as host entity references.",
            "inputSchema": {"type": "object", "properties": {}},
            "_meta": _design_meta(
                operation="context.current_selection.v1",
                category="CONTEXT",
            ),
        },
        {
            "name": "view.fit",
            "description": "Fit the AutoCAD view to the supplied entities or current model.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "handles": {
                        "type": ["array", "null"],
                        "items": {"type": "string"},
                    }
                },
            },
            "_meta": _design_meta(
                operation="view.fit_entities.v1",
                category="VIEW",
            ),
        },
        {
            "name": "interaction.pick_point",
            "description": "Ask the designer to pick one point on the AutoCAD canvas.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "idempotency_key": {"type": "string", "minLength": 1},
                    "prompt": {"type": ["string", "null"]},
                },
                "required": ["idempotency_key"],
                "additionalProperties": False,
            },
            "_meta": _design_meta(
                operation="interaction.pick_point.v1",
                category="INTERACTION",
                idempotent=True,
            ),
        },
        {
            "name": "cad.move",
            "description": "Move entities in the active AutoCAD document.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "handles": {"type": "array", "items": {"type": "string"}},
                    "dx": {"type": "number"},
                    "dy": {"type": "number"},
                    "dz": {"type": "number", "default": 0.0},
                    "idempotency_key": {"type": ["string", "null"]},
                    "revision": {"type": ["integer", "null"]},
                },
                "required": ["handles", "dx", "dy"],
            },
            "_meta": _design_meta(
                operation="move.v1",
                category="MODEL_OPERATION",
                entities=["LINE", "LWPOLYLINE", "ARC"],
                execution_freshness=[
                    {"aspect": "PLACEMENT", "required_state": "FRESH"}
                ],
                effects=["PLACEMENT", "GEOMETRY"],
                risk="LOW",
                preview=False,
                rollback=False,
                idempotent=True,
                verification={"type": "HOST_READ_BACK"},
            ),
        },
    ]


def build_mcp_server(
    dispatcher: CommandDispatcher,
    *,
    lifespan: Any | None = None,
) -> MCPServer:
    """Create the stateless-capable MCP server without exposing Host native APIs."""

    definitions = {tool["name"]: tool for tool in build_tool_definitions()}
    server = (
        MCPServer("DSP AutoCAD Sidecar", lifespan=lifespan)
        if lifespan is not None
        else MCPServer("DSP AutoCAD Sidecar")
    )

    @server.tool(
        name="context.current_document",
        description=definitions["context.current_document"]["description"],
        meta=definitions["context.current_document"]["_meta"],
    )
    async def current_document() -> dict[str, Any]:
        return (await dispatcher.current_document()).to_dict()

    @server.tool(
        name="context.current_selection",
        description=definitions["context.current_selection"]["description"],
        meta=definitions["context.current_selection"]["_meta"],
    )
    async def current_selection() -> dict[str, Any]:
        return (await dispatcher.current_selection()).to_dict()

    @server.tool(
        name="view.fit",
        description=definitions["view.fit"]["description"],
        meta=definitions["view.fit"]["_meta"],
    )
    async def fit(handles: list[str] | None = None) -> dict[str, Any]:
        return (await dispatcher.fit(handles)).to_dict()

    @server.tool(
        name="interaction.pick_point",
        description=definitions["interaction.pick_point"]["description"],
        meta=definitions["interaction.pick_point"]["_meta"],
    )
    async def pick_point(
        idempotency_key: str,
        prompt: str | None = None,
    ) -> dict[str, Any]:
        return (
            await dispatcher.pick_point(
                idempotency_key=idempotency_key,
                prompt=prompt,
            )
        ).to_dict()

    @server.tool(
        name="cad.move",
        description=definitions["cad.move"]["description"],
        meta=definitions["cad.move"]["_meta"],
    )
    async def move(
        handles: list[str],
        dx: float,
        dy: float,
        dz: float = 0.0,
        idempotency_key: str | None = None,
        revision: int | None = None,
    ) -> dict[str, Any]:
        result = await dispatcher.move(
            handles,
            dx,
            dy,
            dz,
            idempotency_key=idempotency_key,
            revision=revision,
        )
        return result.to_dict()

    return server


def run_mcp_server(
    dispatcher: CommandDispatcher,
    *,
    host: str = "127.0.0.1",
    port: int = 8000,
) -> None:
    """Run the Sidecar MCP endpoint using the 2026 stateless HTTP model."""

    build_mcp_server(dispatcher).run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )
