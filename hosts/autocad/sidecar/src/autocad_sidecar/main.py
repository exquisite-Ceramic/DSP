"""Sidecar entry point.

Usage:
    python -m autocad_sidecar.main --pipe EnterpriseDesignAgent.HOST-1234
    python -m autocad_sidecar.main status            # one-shot status probe

For scripting use tools/host_test_client which talks to this sidecar's
command dispatcher (or to the pipe directly).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from autocad_sidecar.execution.idempotency import IdempotencyStore
from autocad_sidecar.execution.retry import RetryPolicy
from autocad_sidecar.health.host_status import StatusMonitor
from autocad_sidecar.ipc.transport_selector import build_transport


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autocad-sidecar", description="AutoCAD agent sidecar")
    parser.add_argument(
        "--transport",
        choices=["pipe", "grpc"],
        default=os.getenv("DSP_AUTOCAD_TRANSPORT", "pipe"),
        help="host transport (default: pipe; env: DSP_AUTOCAD_TRANSPORT)",
    )
    parser.add_argument("--instance-id", default=None, help="AutoCAD host instance id for gRPC")
    parser.add_argument("--pipe", default="EnterpriseDesignAgent", help="named pipe name")
    parser.add_argument("--retries", type=int, default=3, help="max retries for write commands")
    parser.add_argument("--status-interval", type=float, default=5.0, help="health poll interval (s)")
    parser.add_argument("mode", nargs="?", default="serve", choices=["serve", "status"])
    return parser


def validate_transport_args(args: argparse.Namespace) -> None:
    if args.transport == "grpc" and not args.instance_id:
        raise ValueError("instance_id is required for grpc transport")


def build_host_adapter(args: argparse.Namespace) -> HostAdapter:
    validate_transport_args(args)
    transport = build_transport(
        args.transport,
        pipe_name=args.pipe,
        instance_id=args.instance_id,
    )
    return HostAdapter(pipe_name=args.pipe, transport=transport)


def readiness_message(args: argparse.Namespace) -> str:
    if args.transport == "grpc":
        validate_transport_args(args)
        return f"sidecar ready (transport=grpc, instance_id={args.instance_id})"
    return f"sidecar ready (transport=pipe, pipe={args.pipe})"


async def run_status(adapter: HostAdapter) -> int:
    status = await adapter.get_status()
    print(status.to_dict())
    return 0 if status.state in {"ready", "busy"} else 1


async def run_serve(adapter: HostAdapter, status_interval: float, readiness: str) -> int:
    monitor = StatusMonitor(adapter, interval_s=status_interval)
    await monitor.start()
    print(readiness, flush=True)
    try:
        # Block until interrupted; the monitor keeps health fresh.
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        pass
    finally:
        await monitor.stop()
    return 0


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    adapter = build_host_adapter(args)
    dispatcher = CommandDispatcher(
        host=adapter,
        idempotency=IdempotencyStore(),
        retry=RetryPolicy(max_attempts=args.retries),
    )

    try:
        if args.mode == "status":
            return await run_status(adapter)
        return await run_serve(adapter, args.status_interval, readiness_message(args))
    finally:
        await adapter.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
