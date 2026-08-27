"""Authenticated local gRPC transport for the AutoCAD Sidecar."""

from __future__ import annotations

from pathlib import Path

import grpc

from autocad_sidecar.ipc.discovery import HostEndpoint, load_instance
from autocad_sidecar.ipc.generated import host_transport_v1_pb2 as pb2
from autocad_sidecar.ipc.generated import host_transport_v1_pb2_grpc as pb2_grpc
from autocad_sidecar.ipc.transport import MAX_FRAME_BYTES


class GrpcTransport:
    """Byte-preserving gRPC client bound to one discovered AutoCAD host instance."""

    def __init__(
        self,
        instance_id: str,
        *,
        discovery_dir: Path | None = None,
        max_timeout_s: float = 30.0,
    ) -> None:
        if max_timeout_s <= 0:
            raise ValueError("max_timeout_s must be positive")

        self.instance_id = instance_id
        self.discovery_dir = Path(discovery_dir) if discovery_dir is not None else None
        self.max_timeout_s = max_timeout_s
        self.endpoint: HostEndpoint = load_instance(instance_id, self.discovery_dir)
        self._channel: grpc.aio.Channel | None = None
        self._stub: pb2_grpc.AutoCadHostStub | None = None

    @property
    def target(self) -> str:
        return f"{self.endpoint.host}:{self.endpoint.port}"

    @property
    def _metadata(self) -> tuple[tuple[str, str], ...]:
        return (("authorization", f"Bearer {self.endpoint.auth_token}"),)

    async def open(self) -> None:
        if self._channel is not None:
            return

        channel = grpc.aio.insecure_channel(self.target)
        stub = pb2_grpc.AutoCadHostStub(channel)

        try:
            response = await stub.Ping(
                pb2.PingRequest(instance_id=self.instance_id),
                metadata=self._metadata,
                timeout=self.max_timeout_s,
            )
            if response.instance_id != self.instance_id:
                raise ConnectionError(
                    "gRPC host identity mismatch: "
                    f"expected instance_id {self.instance_id!r}, got {response.instance_id!r}"
                )
            if response.contract_version != self.endpoint.contract_version:
                raise ConnectionError(
                    "gRPC host contract identity mismatch: "
                    f"expected contract_version {self.endpoint.contract_version!r}, "
                    f"got {response.contract_version!r}"
                )
        except BaseException:
            await channel.close()
            raise

        self._channel = channel
        self._stub = stub

    async def exchange(self, payload: bytes, *, timeout_s: float | None = None) -> bytes:
        stub = self._stub
        if stub is None:
            raise ConnectionError("gRPC transport is not open")
        if len(payload) > MAX_FRAME_BYTES:
            raise ValueError(f"frame too large: {len(payload)} bytes")

        chosen_timeout = self.max_timeout_s if timeout_s is None else min(
            timeout_s, self.max_timeout_s
        )
        if chosen_timeout <= 0:
            raise TimeoutError("transport timeout must be positive")

        response = await stub.Dispatch(
            pb2.DispatchRequest(contract_json=payload),
            metadata=self._metadata,
            timeout=chosen_timeout,
        )
        contract_json = bytes(response.contract_json)
        if len(contract_json) > MAX_FRAME_BYTES:
            raise ConnectionError(f"frame too large: {len(contract_json)} bytes")
        return contract_json

    async def close(self) -> None:
        channel = self._channel
        self._stub = None
        self._channel = None
        if channel is not None:
            await channel.close()
