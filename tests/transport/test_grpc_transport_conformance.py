from __future__ import annotations

import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path

import grpc
import pytest

from autocad_sidecar.ipc.generated import host_transport_v1_pb2 as pb2
from autocad_sidecar.ipc.generated import host_transport_v1_pb2_grpc as pb2_grpc
from autocad_sidecar.ipc.grpc_transport import GrpcTransport


TEST_HOST_PROJECT = Path(
    "tests/transport/dotnet/ContractTransportTestHost/ContractTransportTestHost.csproj"
)


@dataclass(slots=True)
class RunningHost:
    process: asyncio.subprocess.Process
    transport: GrpcTransport
    instance_id: str
    token: str
    port: int
    pid: int
    discovery_dir: Path
    counter_file: Path

    async def close(self) -> None:
        await self.transport.close()
        if self.process.returncode is not None:
            return

        try:
            if self.process.stdin is not None:
                self.process.stdin.write(b"shutdown\n")
                await self.process.stdin.drain()
                self.process.stdin.close()
            await asyncio.wait_for(self.process.wait(), timeout=10.0)
        except (asyncio.TimeoutError, BrokenPipeError, ConnectionResetError):
            if self.process.returncode is None:
                self.process.terminate()
                try:
                    await asyncio.wait_for(self.process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    self.process.kill()
                    await self.process.wait()


async def _start_host(
    root: Path,
    *,
    instance_id: str = "inst-a",
    token: str = "token-a",
    mode: str = "normal",
) -> RunningHost:
    discovery_dir = root / f"discovery-{instance_id}"
    counter_file = root / f"counter-{instance_id}.json"
    env = os.environ.copy()
    env["DOTNET_CLI_TELEMETRY_OPTOUT"] = "1"
    env["DOTNET_NOLOGO"] = "1"

    process = await asyncio.create_subprocess_exec(
        "dotnet",
        "run",
        "--project",
        str(TEST_HOST_PROJECT),
        "--configuration",
        "Release",
        "--no-launch-profile",
        "--verbosity",
        "quiet",
        "--",
        "--instance-id",
        instance_id,
        "--token",
        token,
        "--discovery-dir",
        str(discovery_dir),
        "--mode",
        mode,
        "--counter-file",
        str(counter_file),
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    assert process.stdout is not None
    assert process.stderr is not None
    try:
        line = await asyncio.wait_for(process.stdout.readline(), timeout=60.0)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        stderr = (await process.stderr.read()).decode(errors="replace")
        raise AssertionError(f"C# transport host did not become ready: {stderr}")

    if not line:
        await process.wait()
        stderr = (await process.stderr.read()).decode(errors="replace")
        raise AssertionError(f"C# transport host exited before readiness: {stderr}")

    try:
        readiness = json.loads(line.decode("utf-8"))
    except json.JSONDecodeError as exc:
        process.kill()
        await process.wait()
        stderr = (await process.stderr.read()).decode(errors="replace")
        raise AssertionError(
            f"first host stdout line was not readiness JSON: {line!r}; stderr={stderr}"
        ) from exc

    assert readiness["instance_id"] == instance_id
    assert int(readiness["port"]) > 0
    assert int(readiness["pid"]) > 0

    transport = GrpcTransport(
        instance_id,
        discovery_dir=discovery_dir,
        max_timeout_s=30.0,
    )
    return RunningHost(
        process=process,
        transport=transport,
        instance_id=instance_id,
        token=token,
        port=int(readiness["port"]),
        pid=int(readiness["pid"]),
        discovery_dir=discovery_dir,
        counter_file=counter_file,
    )


def _counter(host: RunningHost) -> dict:
    if not host.counter_file.exists():
        return {"count": 0, "status": None}
    return json.loads(host.counter_file.read_text(encoding="utf-8"))


async def _wait_counter(
    host: RunningHost,
    *,
    count: int | None = None,
    status: str | None = None,
    timeout_s: float = 10.0,
) -> dict:
    deadline = asyncio.get_running_loop().time() + timeout_s
    while True:
        value = _counter(host)
        count_matches = count is None or value.get("count") == count
        status_matches = status is None or value.get("status") == status
        if count_matches and status_matches:
            return value
        if asyncio.get_running_loop().time() >= deadline:
            raise AssertionError(
                f"counter did not reach count={count!r}, status={status!r}; got {value!r}"
            )
        await asyncio.sleep(0.02)


def _auth(token: str) -> tuple[tuple[str, str], ...]:
    return (("authorization", f"Bearer {token}"),)


@pytest.mark.asyncio
@pytest.mark.conformance
async def test_rpc01_python_to_csharp_ping(tmp_path):
    host = await _start_host(tmp_path)
    try:
        await host.transport.open()
        assert host.transport.endpoint.instance_id == "inst-a"
        assert host.transport.endpoint.port == host.port
    finally:
        await host.close()


@pytest.mark.asyncio
@pytest.mark.conformance
async def test_rpc02_python_to_csharp_dispatch_preserves_contract(tmp_path):
    host = await _start_host(tmp_path)
    try:
        await host.transport.open()
        request = b'{"request_id":"req-1","payload":{}}'
        response = await host.transport.exchange(request, timeout_s=5.0)
        parsed = json.loads(response)
        assert parsed["request_id"] == "req-1"
        assert parsed["status"] == "OK"
        assert _counter(host)["count"] == 1
    finally:
        await host.close()


@pytest.mark.asyncio
@pytest.mark.conformance
async def test_rpc03_deadline_exceeded_is_transport_error(tmp_path):
    host = await _start_host(tmp_path, mode="block")
    try:
        await host.transport.open()
        with pytest.raises(grpc.aio.AioRpcError) as caught:
            await host.transport.exchange(
                b'{"request_id":"req-deadline","payload":{}}',
                timeout_s=0.05,
            )
        assert caught.value.code() == grpc.StatusCode.DEADLINE_EXCEEDED
    finally:
        await host.close()


@pytest.mark.asyncio
@pytest.mark.conformance
async def test_rpc04_client_cancellation_reaches_csharp_target(tmp_path):
    host = await _start_host(tmp_path, mode="block")
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{host.port}")
    stub = pb2_grpc.AutoCadHostStub(channel)
    try:
        call = stub.Dispatch(
            pb2.DispatchRequest(
                contract_json=b'{"request_id":"req-cancel","payload":{}}'
            ),
            metadata=_auth(host.token),
        )
        await _wait_counter(host, count=1)
        assert call.cancel()
        with pytest.raises(asyncio.CancelledError):
            await call
        assert await call.code() == grpc.StatusCode.CANCELLED
        await _wait_counter(host, count=1, status="cancelled")
    finally:
        await channel.close()
        await host.close()


@pytest.mark.asyncio
@pytest.mark.conformance
async def test_rpc05_malformed_dsp_contract_remains_dsp_error(tmp_path):
    host = await _start_host(tmp_path)
    try:
        await host.transport.open()
        response = await host.transport.exchange(b"not-json", timeout_s=5.0)
        parsed = json.loads(response)
        assert parsed["status"] == "ERROR"
        assert parsed["error"]["error_code"]
    finally:
        await host.close()


@pytest.mark.asyncio
@pytest.mark.conformance
async def test_rpc06_auth_rejection_never_dispatches(tmp_path):
    host = await _start_host(tmp_path)
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{host.port}")
    stub = pb2_grpc.AutoCadHostStub(channel)
    request = pb2.DispatchRequest(contract_json=b"{}")
    try:
        for metadata in (None, _auth("wrong-token")):
            with pytest.raises(grpc.aio.AioRpcError) as caught:
                await stub.Dispatch(request, metadata=metadata, timeout=5.0)
            assert caught.value.code() == grpc.StatusCode.UNAUTHENTICATED
        assert _counter(host)["count"] == 0
    finally:
        await channel.close()
        await host.close()


@pytest.mark.asyncio
@pytest.mark.conformance
async def test_rpc07_multi_instance_ports_and_tokens_are_isolated(tmp_path):
    host_a = await _start_host(tmp_path, instance_id="inst-a", token="token-a")
    host_b = await _start_host(tmp_path, instance_id="inst-b", token="token-b")
    channel_b = grpc.aio.insecure_channel(f"127.0.0.1:{host_b.port}")
    stub_b = pb2_grpc.AutoCadHostStub(channel_b)
    try:
        assert host_a.port != host_b.port
        assert host_a.token != host_b.token
        await host_a.transport.open()
        await host_b.transport.open()

        with pytest.raises(grpc.aio.AioRpcError) as caught:
            await stub_b.Ping(
                pb2.PingRequest(instance_id="inst-b"),
                metadata=_auth(host_a.token),
                timeout=5.0,
            )
        assert caught.value.code() == grpc.StatusCode.UNAUTHENTICATED
    finally:
        await channel_b.close()
        await host_b.close()
        await host_a.close()
