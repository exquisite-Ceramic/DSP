"""Executable MCP entry point for the AutoCAD Sidecar."""

from __future__ import annotations

import argparse
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from mcp.server.mcpserver import MCPServer

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from autocad_sidecar.execution.idempotency import IdempotencyStore
from autocad_sidecar.execution.retry import RetryPolicy
from autocad_sidecar.ipc.transport_selector import build_transport
from autocad_sidecar.mcp_server import build_mcp_server


@dataclass(slots=True)
class McpRuntime:
    """Resources shared by the MCP process for its full lifetime."""

    adapter: HostAdapter
    dispatcher: CommandDispatcher


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="autocad-sidecar-mcp",
        description="Expose the AutoCAD Sidecar as a Design Capability Profile MCP server.",
    )
    parser.add_argument(
        "--transport",
        choices=["pipe", "grpc"],
        default=os.getenv("DSP_AUTOCAD_TRANSPORT", "pipe"),
        help="AutoCAD host transport (default: pipe; env: DSP_AUTOCAD_TRANSPORT)",
    )
    parser.add_argument("--instance-id", default=None, help="AutoCAD host instance id for gRPC")
    parser.add_argument("--pipe", default="EnterpriseDesignAgent", help="named pipe name")
    parser.add_argument("--retries", type=int, default=3, help="max retries for write commands")
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="MCP Streamable HTTP bind host (default: loopback)",
    )
    parser.add_argument("--port", type=int, default=8000, help="MCP Streamable HTTP port")
    return parser


def validate_args(args: argparse.Namespace) -> None:
    if args.transport == "grpc" and not args.instance_id:
        raise ValueError("instance_id is required for grpc transport")
    if not args.host:
        raise ValueError("host is required")
    if not 1 <= args.port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    if args.retries < 1:
        raise ValueError("retries must be at least 1")


def build_runtime(args: argparse.Namespace) -> McpRuntime:
    """Build Sidecar resources without opening a Host connection eagerly."""

    validate_args(args)
    transport = build_transport(
        args.transport,
        pipe_name=args.pipe,
        instance_id=args.instance_id,
    )
    adapter = HostAdapter(pipe_name=args.pipe, transport=transport)
    dispatcher = CommandDispatcher(
        host=adapter,
        idempotency=IdempotencyStore(),
        retry=RetryPolicy(max_attempts=args.retries),
    )
    return McpRuntime(adapter=adapter, dispatcher=dispatcher)


def build_server(runtime: McpRuntime) -> MCPServer:
    """Bind MCP tool handlers to one Sidecar runtime and close it on shutdown."""

    @asynccontextmanager
    async def lifespan(_server: MCPServer) -> AsyncIterator[dict[str, Any]]:
        try:
            yield {}
        finally:
            await runtime.adapter.close()

    return build_mcp_server(runtime.dispatcher, lifespan=lifespan)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    runtime = build_runtime(args)
    server = build_server(runtime)
    server.run(
        transport="streamable-http",
        host=args.host,
        port=args.port,
        stateless_http=True,
        json_response=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
