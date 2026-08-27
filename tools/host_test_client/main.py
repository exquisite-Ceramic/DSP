"""host_test_client: manual and scripted testing of the AutoCAD agent host.

Talks to the sidecar's CommandDispatcher (preferred) or directly to the
named pipe when given --raw.

Usage:
    python tools/host_test_client/main.py selection
    python tools/host_test_client/main.py move --handle 2A1 --dx 10 --dy 5
    python tools/host_test_client/main.py fit
    python tools/host_test_client/main.py scenario move_once
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.ipc.transport_selector import build_transport
from host_test_client.commands import current_selection, fit, move
from host_test_client.scenarios import move_once, move_retry, revision_conflict

COMMANDS = {
    "selection": current_selection.run,
    "move": move.run,
    "fit": fit.run,
}

SCENARIOS = {
    "move_once": move_once.run,
    "move_retry": move_retry.run,
    "revision_conflict": revision_conflict.run,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="host_test_client", description="AutoCAD agent host test client")
    parser.add_argument(
        "--transport",
        choices=["pipe", "grpc"],
        default=os.getenv("DSP_AUTOCAD_TRANSPORT", "pipe"),
        help="host transport (default: pipe; env: DSP_AUTOCAD_TRANSPORT)",
    )
    parser.add_argument("--instance-id", default=None, help="AutoCAD host instance id for gRPC")
    parser.add_argument("--pipe", default="EnterpriseDesignAgent", help="named pipe name")
    sub = parser.add_subparsers(dest="command", required=True)

    p_sel = sub.add_parser("selection", help="read current selection")
    p_sel.set_defaults(kind="command")

    p_move = sub.add_parser("move", help="move entities by (dx, dy[, dz])")
    p_move.add_argument("--handle", action="append", dest="handles", required=True)
    p_move.add_argument("--dx", type=float, required=True)
    p_move.add_argument("--dy", type=float, required=True)
    p_move.add_argument("--dz", type=float, default=0.0)
    p_move.add_argument("--revision", type=int, default=None, help="expected document revision")
    p_move.add_argument("--idempotency-key", default=None)
    p_move.set_defaults(kind="command")

    p_fit = sub.add_parser("fit", help="zoom extents")
    p_fit.add_argument("--handle", action="append", dest="handles", default=None)
    p_fit.set_defaults(kind="command")

    p_sc = sub.add_parser("scenario", help="run a scripted scenario")
    p_sc.add_argument("name", choices=sorted(SCENARIOS))
    p_sc.set_defaults(kind="scenario")
    return parser


def build_host_adapter(args: argparse.Namespace) -> HostAdapter:
    transport = build_transport(
        args.transport,
        pipe_name=args.pipe,
        instance_id=args.instance_id,
    )
    return HostAdapter(pipe_name=args.pipe, transport=transport)


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    kwargs = {
        k: v
        for k, v in vars(args).items()
        if k not in {"command", "kind", "pipe", "transport", "instance_id"}
    }

    if args.kind == "command":
        result = await COMMANDS[args.command](pipe_name=args.pipe, **kwargs)
    else:
        result = await SCENARIOS[args.name](pipe_name=args.pipe)

    print(result)
    return 0 if getattr(result, "ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
