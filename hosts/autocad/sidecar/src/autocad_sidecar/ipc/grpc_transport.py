"""Authenticated local gRPC transport for the AutoCAD Sidecar."""

from __future__ import annotations

import grpc

from autocad_sidecar.ipc.discovery import HostEndpoint
from autocad_sidecar.ipc.generated import host_transport_v1_pb2 as pb2
from autocad_sidecar.ipc.generated import host_transport_v1_pb2_grpc as pb2_grpc
from autocad_sidecar.ipc.transport import Frame, MAX_FRAME_BYTES


class GrpcTransport:
    """Byte-preserving gRPC client bound to one discovered AutoCAD host instance."""

    def __init__(self, endpoint: HostEndpoint, *, timeout_seconds: float = 5.0) -> None:
        if endpoint.host != "127.0.0.1":
            raise ValueError("gRPC transport endpoint must use IPv4 loopback 127.0.0.1")
        if endpoint.transport != "grpc-h2c":
            raise ValueError("gRPC transport endpoint must use grpc-h2c")
        if not 1 <= endpoint.port <= 65535:
            raise ValueError("gRPC transport endpoint port must be in the range 1..65535")
        if not endpoint.auth_token:
            raise ValueError("gRPC transport endpoint auth_token must be non-empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")

        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
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

        channel = grpc.aio.insecure_channel(
            self.target,
            options=(
                ("grpc.max_send_message_length", MAX_FRAME_BYTES),
                ("grpc.max_receive_message_length", MAX_FRAME_BYTES),
            ),
        )
        stub = pb2_grpc.AutoCadHostStub(channel)

        try:
            response = await stub.Ping(
                pb2.PingRequest(instance_id=self.endpoint.instance_id),
                metadata=self._metadata,
                timeout=self.timeout_seconds,
            )
            if response.instance_id != self.endpoint.instance_id:
                raise ConnectionError(
                    "gRPC host identity mismatch: "
                    f"expected instance_id {self.endpoint.instance_id!r}, "
                    f"got {response.instance_id!r}"
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

    async def exchange(self, payload: Frame) -> Frame:
        stub = self._stub
        if stub is None:
            raise ConnectionError("gRPC transport is not open")
        if not payload:
            raise ValueError("contract payload must not be empty")
        if len(payload) > MAX_FRAME_BYTES:
            raise ValueError(f"frame too large: {len(payload)} bytes")

        response = await stub.Dispatch(
            pb2.DispatchRequest(contract_json=payload),
            metadata=self._metadata,
            timeout=self.timeout_seconds,
        )
        contract_json = bytes(response.contract_json)
        if not contract_json:
            raise ConnectionError("gRPC host returned an empty contract payload")
        if len(contract_json) > MAX_FRAME_BYTES:
            raise ConnectionError(f"frame too large: {len(contract_json)} bytes")
        return contract_json

    async def close(self) -> None:
        channel = self._channel
        self._stub = None
        self._channel = None
        if channel is not None:
            await channel.close()
