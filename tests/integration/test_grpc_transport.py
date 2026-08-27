import asyncio
import json
import os
from pathlib import Path

import grpc
import pytest

from autocad_sidecar.ipc.base import FrameTransport
from autocad_sidecar.ipc.grpc_transport import GrpcTransport
from autocad_sidecar.ipc.generated import host_transport_v1_pb2 as pb2
from autocad_sidecar.ipc.generated import host_transport_v1_pb2_grpc as pb2_grpc
from autocad_sidecar.ipc.transport import PipeTransport


class _RecordingServicer(pb2_grpc.AutoCadHostServicer):
    def __init__(
        self,
        *,
        instance_id: str = "instance-001",
        contract_version: str = "1.0",
        auth_token: str = "token-001",
    ) -> None:
        self.instance_id = instance_id
        self.contract_version = contract_version
        self.auth_token = auth_token
        self.dispatch_payloads: list[bytes] = []
        self.auth_headers: list[str | None] = []

    def _authorize(self, context: grpc.aio.ServicerContext) -> None:
        metadata = dict(context.invocation_metadata())
        authorization = metadata.get("authorization")
        self.auth_headers.append(authorization)
        if authorization != f"Bearer {self.auth_token}":
            raise _Abort(grpc.StatusCode.UNAUTHENTICATED, "invalid bearer token")

    async def Ping(self, request, context):
        try:
            self._authorize(context)
        except _Abort as exc:
            await context.abort(exc.code, exc.details)
        return pb2.PingResponse(
            instance_id=self.instance_id,
            contract_version=self.contract_version,
        )

    async def Dispatch(self, request, context):
        try:
            self._authorize(context)
        except _Abort as exc:
            await context.abort(exc.code, exc.details)
        payload = bytes(request.contract_json)
        self.dispatch_payloads.append(payload)
        return pb2.DispatchResponse(contract_json=request.contract_json)


class _Abort(Exception):
    def __init__(self, code: grpc.StatusCode, details: str) -> None:
        super().__init__(details)
        self.code = code
        self.details = details


def _write_endpoint(
    directory: Path,
    port: int,
    *,
    instance_id: str = "instance-001",
    contract_version: str = "1.0",
    auth_token: str = "token-001",
) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{instance_id}.json").write_text(
        json.dumps({
            "instance_id": instance_id,
            "pid": os.getpid(),
            "host": "127.0.0.1",
            "port": port,
            "transport": "grpc-h2c",
            "contract_version": contract_version,
            "auth_token": auth_token,
        }),
        encoding="utf-8",
    )


async def _serve(servicer: _RecordingServicer):
    server = grpc.aio.server()
    pb2_grpc.add_AutoCadHostServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    return server, port


def test_pipe_and_grpc_transports_share_transport_protocol(tmp_path):
    _write_endpoint(tmp_path, 53182)
    grpc_transport = GrpcTransport("instance-001", discovery_dir=tmp_path)
    pipe_transport = PipeTransport("dsp-test")

    assert isinstance(grpc_transport, FrameTransport)
    assert isinstance(pipe_transport, FrameTransport)


def test_open_pings_identity_and_sends_bearer_token(tmp_path):
    async def _case():
        servicer = _RecordingServicer()
        server, port = await _serve(servicer)
        _write_endpoint(tmp_path, port)
        transport = GrpcTransport("instance-001", discovery_dir=tmp_path)
        try:
            await transport.open()
            assert servicer.auth_headers == ["Bearer token-001"]
        finally:
            await transport.close()
            await server.stop(None)

    asyncio.run(_case())


def test_open_rejects_ping_identity_mismatch(tmp_path):
    async def _case():
        servicer = _RecordingServicer(instance_id="other-instance")
        server, port = await _serve(servicer)
        _write_endpoint(tmp_path, port)
        transport = GrpcTransport("instance-001", discovery_dir=tmp_path)
        try:
            with pytest.raises(ConnectionError, match="instance_id|identity"):
                await transport.open()
        finally:
            await transport.close()
            await server.stop(None)

    asyncio.run(_case())


def test_exchange_preserves_contract_bytes_exactly(tmp_path):
    async def _case():
        servicer = _RecordingServicer()
        server, port = await _serve(servicer)
        _write_endpoint(tmp_path, port)
        transport = GrpcTransport("instance-001", discovery_dir=tmp_path)
        request = b'{"request_id":"r-1","payload":{"x":500}}'
        try:
            await transport.open()
            response = await transport.exchange(request, timeout_s=5.0)
            assert response == request
            assert servicer.dispatch_payloads == [request]
            assert servicer.auth_headers == ["Bearer token-001", "Bearer token-001"]
        finally:
            await transport.close()
            await server.stop(None)

    asyncio.run(_case())


def test_exchange_before_open_is_rejected(tmp_path):
    _write_endpoint(tmp_path, 53182)

    async def _case():
        transport = GrpcTransport("instance-001", discovery_dir=tmp_path)
        with pytest.raises(ConnectionError, match="not open|not connected"):
            await transport.exchange(b"{}", timeout_s=1.0)

    asyncio.run(_case())
