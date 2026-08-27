"""Generate checked-in Python stubs for the AutoCAD host transport proto."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTO_DIR = ROOT / "contracts" / "proto"
PROTO = PROTO_DIR / "host_transport_v1.proto"
OUT_DIR = ROOT / "hosts" / "autocad" / "sidecar" / "src" / "autocad_sidecar" / "ipc" / "generated"
PB2 = OUT_DIR / "host_transport_v1_pb2.py"
PB2_GRPC = OUT_DIR / "host_transport_v1_pb2_grpc.py"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            sys.executable,
            "-m",
            "grpc_tools.protoc",
            f"-I{PROTO_DIR}",
            f"--python_out={OUT_DIR}",
            f"--grpc_python_out={OUT_DIR}",
            str(PROTO),
        ],
        cwd=ROOT,
        check=True,
    )

    missing = [str(path) for path in (PB2, PB2_GRPC) if not path.exists()]
    if missing:
        raise SystemExit(f"grpc_tools.protoc did not generate expected files: {', '.join(missing)}")

    text = PB2_GRPC.read_text(encoding="utf-8")
    needle = "import host_transport_v1_pb2 as host__transport__v1__pb2"
    replacement = "from . import host_transport_v1_pb2 as host__transport__v1__pb2"
    if needle not in text:
        raise SystemExit("generated gRPC module did not contain expected sibling pb2 import")
    PB2_GRPC.write_text(text.replace(needle, replacement, 1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
