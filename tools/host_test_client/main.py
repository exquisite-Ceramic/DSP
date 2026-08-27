"""host_test_client: manual and scripted testing of the AutoCAD agent host.

Talks to the sidecar's CommandDispatcher (preferred) through the selected
host transport.

Usage:
    python tools/host_test_client/main.py document
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
from pathlib import Path

# Direct script execution sets sys.path[0] to tools/host_test_client rather
# than the repository source roots. Bootstrap those roots before importing any
# project packages so the manual client works without a caller-managed
# PYTHONPATH.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_ROOTS = (
    _REPO_ROOT / "tools",
    _REPO_ROOT / "contracts" / "python",
    _REPO_ROOT / "hosts" / "autocad" / "sidecar" / "src",
)
for _source_root in reversed(_SOURCE_ROOTS):
    _source = str(_source_root)
    if _source not in sys.path:
        sys.path.insert(0, _source)

from autocad_sidecar.adapter.host_adapter import HostAdapter
from autocad_sidecar.ipc.transport_selector import build_transport
from host_test_client.commands import current_document, current_selection, fit, move
from host_test_client.scenarios import move_once, move_retry, revision_conflict

COMMANDS = {
    "document": current_document.run,
    "selection": current_selection.run,
    "move": move.run,
    "fit": fit.run,
}

SCENARIOS = {
    "move_once": move_once.run,
    "move_retry": move_retry.run,
    "revision_conflict": revision_conflict.run,
}

_PIPE_PREFIX = "EnterpriseDesignAgent."
_PIPE_GLOB = rf"\\.\pipe\{_PIPE_PREFIX}*"


def discover_pipe_name() -> str:
    """Return the one running AutoCAD host pipe, or require disambiguation."""
    if os.name != "nt":
        raise RuntimeError("named pipe auto-discovery is only supported on Windows")

    try:
        import win32api
    except ImportError as exc:
        raise RuntimeError(
            "pywin32 is required for named pipe auto-discovery; install the sidecar pipe extra or pass --pipe"
        ) from exc

    try:
        entries = win32api.FindFiles(_PIPE_GLOB)
    except Exception as exc:
        raise RuntimeError(f"failed to enumerate AutoCAD named pipes: {exc}") from exc

    names = sorted(
        {
            str(entry[8])
            for entry in entries
            if len(entry) > 8 and str(entry[8]).startswith(_PIPE_PREFIX)
        }
    )
    if not names:
        raise RuntimeError(
            "no running AutoCAD agent named pipe found; NETLOAD the plugin or pass --pipe explicitly"
        )
    if len(names) > 1:
        raise RuntimeError(
            "multiple AutoCAD agent named pipes found; pass --pipe explicitly: "
            + ", ".join(names)
        )
    return names[0]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="host_test_client", description="AutoCAD agent host test client")
    parser.add_argument(
        "--transport",
        choices=["pipe", "grpc"],
        default=os.getenv("DSP_AUTOCAD_TRANSPORT", "pipe"),
        help="host transport (default: pipe; env: DSP_AUTOCAD_TRANSPORT)",
    )
    parser.add_argument("--instance-id", default=None, help="AutoCAD host instance id for gRPC")
    parser.add_argument(
        "--pipe",
        default=None,
        help="named pipe name (default: auto-discover the one running AutoCAD host)",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_doc = sub.add_parser("document", help="read current document")
    p_doc.set_defaults(kind="command")

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
    pipe_name = args.pipe
    if args.transport == "pipe" and not pipe_name:
        pipe_name = discover_pipe_name()

    # HostAdapter keeps pipe_name for compatibility even when the injected
    # transport is gRPC, where the value is never used for I/O.
    adapter_pipe_name = pipe_name or "EnterpriseDesignAgent"
    transport = build_transport(
        args.transport,
        pipe_name=adapter_pipe_name,
        instance_id=args.instance_id,
    )
    return HostAdapter(pipe_name=adapter_pipe_name, transport=transport)


async def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    kwargs = {
        k: v
        for k, v in vars(args).items()
        if k not in {"command", "kind", "pipe", "transport", "instance_id", "name"}
    }
    host = build_host_adapter(args)

    try:
        if args.kind == "command":
            result = await COMMANDS[args.command](host=host, **kwargs)
        else:
            result = await SCENARIOS[args.name](host=host)
    finally:
        await host.close()

    print(result)
    return 0 if getattr(result, "ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main(sys.argv[1:])))
