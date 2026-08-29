from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SIDECAR_SRC = ROOT / "hosts" / "autocad" / "sidecar" / "src"
if str(SIDECAR_SRC) not in sys.path:
    sys.path.insert(0, str(SIDECAR_SRC))


MOVE_TOOL = {
    "name": "cad.move",
    "description": "Move entities.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "handles": {"type": "array", "items": {"type": "string"}},
            "dx": {"type": "number"},
            "dy": {"type": "number"},
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
        "com.company.design/preview": False,
        "com.company.design/rollback": False,
        "com.company.design/idempotent": True,
        "com.company.design/verification": {"type": "HOST_READ_BACK"},
    },
}


def _require_module(name: str):
    return importlib.import_module(name)


def test_profile_parser_requires_explicit_structured_metadata() -> None:
    profile_module = _require_module("autocad_sidecar.capability.profile")

    profile = profile_module.parse_design_capability(MOVE_TOOL, provider_server="autocad-local")

    assert profile.canonical_operation == "move.v1"
    assert profile.provider_tool == "cad.move"
    assert profile.category == "MODEL_OPERATION"
    assert profile.entities == ("LINE", "LWPOLYLINE", "ARC")
    assert profile.execution_freshness[0].aspect == "PLACEMENT"
    assert profile.execution_freshness[0].required_state == "FRESH"
    assert profile.preview is False
    assert profile.rollback is False
    assert profile.idempotent is True
    assert profile.verification == {"type": "HOST_READ_BACK"}


def test_profile_parser_does_not_infer_canonical_operation_from_description() -> None:
    profile_module = _require_module("autocad_sidecar.capability.profile")
    invalid = {
        **MOVE_TOOL,
        "_meta": {
            key: value
            for key, value in MOVE_TOOL["_meta"].items()
            if key != "com.company.design/operation"
        },
    }

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
        "interaction.pick_point",
        "cad.move",
    ]

    interaction_tool = next(tool for tool in tools if tool["name"] == "interaction.pick_point")
    assert interaction_tool["_meta"]["com.company.design/operation"] == "interaction.pick_point.v1"
    assert interaction_tool["_meta"]["com.company.design/category"] == "INTERACTION"
    assert interaction_tool["_meta"]["com.company.design/idempotent"] is True

    move_tool = next(tool for tool in tools if tool["name"] == "cad.move")
    assert move_tool["_meta"]["com.company.design/operation"] == "move.v1"
    assert move_tool["_meta"]["com.company.design/category"] == "MODEL_OPERATION"
    assert move_tool["_meta"]["com.company.design/execution_freshness"] == [
        {"aspect": "PLACEMENT", "required_state": "FRESH"}
    ]
    assert move_tool["_meta"]["com.company.design/preview"] is False
    assert move_tool["_meta"]["com.company.design/rollback"] is False


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

        async def pick_point(self, **kwargs):  # pragma: no cover
            raise AssertionError("not called")

        async def move(self, handles, dx, dy, dz=0.0, **kwargs):  # pragma: no cover
            raise AssertionError("not called")

    server = server_module.build_mcp_server(DispatcherStub())
    tools = await server.list_tools()
    interaction = next(tool for tool in tools if tool.name == "interaction.pick_point")
    move = next(tool for tool in tools if tool.name == "cad.move")

    assert interaction.meta["com.company.design/operation"] == "interaction.pick_point.v1"
    assert interaction.meta["com.company.design/category"] == "INTERACTION"
    assert move.meta["com.company.design/operation"] == "move.v1"
    assert move.meta["com.company.design/category"] == "MODEL_OPERATION"


def test_mcp_cli_builds_runnable_sidecar_runtime_without_opening_host_transport() -> None:
    cli_module = _require_module("autocad_sidecar.mcp_main")
    args = cli_module.build_parser().parse_args(
        [
            "--transport",
            "pipe",
            "--pipe",
            "EnterpriseDesignAgent.Test",
            "--host",
            "127.0.0.1",
            "--port",
            "8765",
            "--retries",
            "1",
        ]
    )

    runtime = cli_module.build_runtime(args, validate_transport=False)

    assert runtime.host == "127.0.0.1"
    assert runtime.port == 8765
    assert runtime.transport == "pipe"
    assert runtime.pipe == "EnterpriseDesignAgent.Test"
    assert runtime.retry_attempts == 1
    assert os.environ.get("AUTOCAD_PIPE_NAME") != "EnterpriseDesignAgent.Test"
