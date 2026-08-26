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
import sys

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
from autocad_sidecar.execution.idempotency import IdempotencyStore
from autocad_sidecar.execution.retry import RetryPolicy
from autocad_sidecar.health.host_status import StatusMonitor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autocad-sidecar", description="AutoCAD agent sidecar")
    parser.add_argument("--pipe", default="EnterpriseDesignAgent", help="named pipe name")
    parser.add_argument("--retries", type=int, default=3, help="max retries for write commands")
    parser.add_argument("--status-interval", type=float, default=5.0, help="health poll interval (s)")
    parser.add_argument("mode", nargs="?", default="serve", choices=["serve", "status"])
    return parser


async def run_status(adapter: HostAdapter) -> int:
    status = await adapter.get_status()
    print(status.to_dict())
    return 0


async def run_serve(adapter: HostAdapter, status_interval: float) -> int:
    monitor = StatusMonitor(adapter, interval_s=status_interval)
    await monitor.start()
    print(f"sidecar ready (pipe={adapter.pipe_name})", flush=True)
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

    adapter = HostAdapter(pipe_name=args.pipe)
    dispatcher = CommandDispatcher(
        host=adapter,
        idempotency=IdempotencyStore(),
        retry=RetryPolicy(max_attempts=args.retries),
    )

    try:
        if args.mode == "status":
            return await run_status(adapter)
        return await run_serve(adapter, args.status_interval)
    finally:
        await adapter.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
