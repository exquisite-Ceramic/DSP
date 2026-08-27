from __future__ import annotations

import importlib
import importlib.util

import pytest


MOVE_TOOL = {
    "name": "cad.move",
    "description": "Move entities in the active AutoCAD document.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "handles": {"type": "array", "items": {"type": "string"}},
            "dx": {"type": "number"},
            "dy": {"type": "number"},
            "dz": {"type": "number", "default": 0.0},
        },
        "required": ["handles", "dx", "dy"],
    },
    "_meta": {
        "com.company.design/operation": "move.v1",
        "com.company.design/category": "MODEL_OPERATION",
        "com.company.design/entities": ["LINE", "LWPOLYLINE", "ARC"],
        "com.company.design/execution_freshness": [
            {"aspect": "PLACEMENT", "required_state": "FRESH"}
        ],
        "com.company.design/effects": ["PLACEMENT", "GEOMETRY"],
        "com.company.design/risk": "LOW",
        "com.company.design/preview": True,
        "com.company.design/rollback": True,
        "com.company.design/idempotent": True,
        "com.company.design/verification": {"type": "HOST_READ_BACK"},
    },
}


def _require_module(name: str):
    try:
        spec = importlib.util.find_spec(name)
    except ModuleNotFoundError:
        spec = None
    assert spec is not None, f"{name} must exist for the D3 capability-profile slice"
    return importlib.import_module(name)


def test_profile_parser_keeps_provider_tool_separate_from_canonical_operation() -> None:
    profile_module = _require_module("autocad_sidecar.capability.profile")
    assert hasattr(profile_module, "parse_design_capability")

    profile = profile_module.parse_design_capability(MOVE_TOOL, provider_server="autocad-local")

    assert profile.provider_server == "autocad-local"
    assert profile.provider_tool == "cad.move"
    assert profile.canonical_operation == "move.v1"
    assert profile.category == "MODEL_OPERATION"
    assert profile.execution_freshness == (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    assert profile.effects == ("PLACEMENT", "GEOMETRY")
    assert profile.idempotent is True


def test_profile_parser_rejects_missing_canonical_operation() -> None:
    profile_module = _require_module("autocad_sidecar.capability.profile")
    invalid = {**MOVE_TOOL, "_meta": {**MOVE_TOOL["_meta"]}}
    invalid["_meta"].pop("com.company.design/operation")

    with pytest.raises(ValueError, match="canonical operation"):
        profile_module.parse_design_capability(invalid, provider_server="autocad-local")


def test_registry_groups_provider_implementations_by_canonical_operation() -> None:
    registry_module = _require_module("autocad_sidecar.capability.registry")
    registry = registry_module.RegistryCache()

    second_provider = {**MOVE_TOOL, "name": "vendor.move"}
    registry.replace_provider_tools("autocad-local", [MOVE_TOOL])
    registry.replace_provider_tools("vendor-extension", [second_provider])

    providers = registry.providers_for("move.v1")

    assert [provider.provider_server for provider in providers] == [
        "autocad-local",
        "vendor-extension",
    ]
    assert [provider.provider_tool for provider in providers] == ["cad.move", "vendor.move"]


def test_default_mcp_surface_exposes_existing_host_capabilities_with_profile_metadata() -> None:
    server_module = _require_module("autocad_sidecar.mcp_server")
    tools = server_module.build_tool_definitions()

    assert [tool["name"] for tool in tools] == [
        "context.current_document",
        "context.current_selection",
        "view.fit",
        "cad.move",
    ]

    move_tool = next(tool for tool in tools if tool["name"] == "cad.move")
    assert move_tool["_meta"]["com.company.design/operation"] == "move.v1"
    assert move_tool["_meta"]["com.company.design/category"] == "MODEL_OPERATION"
    assert move_tool["_meta"]["com.company.design/execution_freshness"] == [
        {"aspect": "PLACEMENT", "required_state": "FRESH"}
    ]


@pytest.mark.asyncio
async def test_mcp_server_tools_list_preserves_design_profile_meta() -> None:
    server_module = _require_module("autocad_sidecar.mcp_server")

    class DispatcherStub:
        async def current_document(self):  # pragma: no cover - tools/list never calls handlers
            raise AssertionError("not called")

        async def current_selection(self):  # pragma: no cover
            raise AssertionError("not called")

        async def fit(self, handles=None):  # pragma: no cover
            raise AssertionError("not called")

        async def move(self, handles, dx, dy, dz=0.0, **kwargs):  # pragma: no cover
            raise AssertionError("not called")

    server = server_module.build_mcp_server(DispatcherStub())
    tools = await server.list_tools()
    move = next(tool for tool in tools if tool.name == "cad.move")

    assert move.meta["com.company.design/operation"] == "move.v1"
    assert move.meta["com.company.design/category"] == "MODEL_OPERATION"
