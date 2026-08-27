"""Construct Sidecar IPC transports from explicit configuration."""

from __future__ import annotations

from pathlib import Path

from autocad_sidecar.ipc.base import FrameTransport
from autocad_sidecar.ipc.grpc_transport import GrpcTransport
from autocad_sidecar.ipc.transport import PipeTransport


def build_transport(
    kind: str,
    *,
    pipe_name: str = "EnterpriseDesignAgent",
    instance_id: str | None = None,
    discovery_dir: Path | None = None,
    max_timeout_s: float = 30.0,
) -> FrameTransport:
    normalized = kind.strip().lower()
    if normalized == "pipe":
        if not pipe_name:
            raise ValueError("pipe_name is required for pipe transport")
        return PipeTransport(pipe_name)
    if normalized == "grpc":
        if not instance_id:
            raise ValueError("instance_id is required for grpc transport")
        return GrpcTransport(
            instance_id,
            discovery_dir=discovery_dir,
            max_timeout_s=max_timeout_s,
        )
    raise ValueError(f"unsupported transport: {kind!r}")
