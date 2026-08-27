# gRPC Loopback Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom Python ↔ C# Named Pipe RPC/framing path with a dual-stack gRPC-over-loopback transport while preserving the existing DSP HostContract JSON wire and keeping Named Pipe as rollback until real AutoCAD validation passes.

**Architecture:** Phase 1 adds a transport-only protobuf IDL with `Ping` and `Dispatch(bytes)`; existing `RequestEnvelope`/`ResponseEnvelope` JSON remains the business wire. A pure .NET transport assembly hosts Kestrel on `127.0.0.1:0`, authenticates a per-instance bearer token, and delegates raw JSON bytes through `IContractDispatchTarget`; Python discovers the instance, connects with `grpc.aio`, and exposes the same bytes-in/bytes-out exchange shape to `HostAdapter`.

**Tech Stack:** Python 3.11+, `grpcio`, `protobuf`, build-only `grpcio-tools`; .NET 8 (`net8.0-windows`), ASP.NET Core/Kestrel, grpc-dotnet, `Grpc.Tools`; pytest, xUnit, GitHub Actions `windows-latest`.

**Spec:** `docs/superpowers/specs/2026-08-27-grpc-loopback-transport-design.md`

## Global Constraints

- Existing DSP HostContract wire JSON remains unchanged in phase 1.
- `contracts/proto/host_transport_v1.proto` is transport-only and does not duplicate `HostCommand`, `HostDelta`, `ErrorShape`, revision, idempotency, or other business fields.
- gRPC binds only IPv4 loopback `127.0.0.1` and requests an OS-assigned dynamic port.
- Each AutoCAD instance has a unique `instance_id`, dynamic port, and random 256-bit bearer token.
- Production discovery records live under `%LOCALAPPDATA%/EnterpriseDesignAgent/hosts/` and are current-user-only; tests may override the discovery directory.
- gRPC status is used only for transport/auth/deadline/cancellation/empty transport request failures. DSP business failures remain `ResponseEnvelope` / `ErrorShape` bytes with gRPC status `OK`.
- Named Pipe remains available and remains the default until real AutoCAD smoke validation passes.
- The new transport assembly must not reference or expose any `Autodesk.*` type.
- Native AutoCAD mutation cancellation is cooperative and only honored at safe points.
- No runtime `protoc` invocation. Generated Python transport modules are checked in/packaged; C# generation occurs at build time through `Grpc.Tools`.
- Install local contracts first: `pip install -e contracts/python`, then install the Sidecar. Do not assume a published `host-contracts` package exists.
- Legacy framing deletion and ADR-002 supersession are separate cleanup work after the real-host gate.

---

## Task 1: Transport-only protobuf IDL and checked-in Python stubs

**Files:**
- Create: `contracts/proto/host_transport_v1.proto`
- Create: `tools/generate_host_transport.py`
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/__init__.py`
- Generate: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/host_transport_v1_pb2.py`
- Generate: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/host_transport_v1_pb2_grpc.py`
- Modify: `hosts/autocad/sidecar/pyproject.toml`
- Create: `tests/contracts/test_transport_proto_shape.py`

**Produces:** `dsp.host.transport.v1.AutoCadHost` with `Ping` and `Dispatch`; `DispatchRequest.contract_json` and `DispatchResponse.contract_json` are the only business-payload carriers.

- [ ] **Step 1: Write the failing proto-shape test**

```python
from autocad_sidecar.ipc.generated import host_transport_v1_pb2 as pb


def test_transport_proto_contains_only_transport_messages():
    request = pb.DispatchRequest(contract_json=b'{"request_id":"r1","payload":{}}')
    assert request.contract_json.startswith(b"{")
    assert set(pb.DESCRIPTOR.message_types_by_name) == {
        "PingRequest",
        "PingResponse",
        "DispatchRequest",
        "DispatchResponse",
    }


def test_transport_proto_does_not_duplicate_business_contracts():
    names = set(pb.DESCRIPTOR.message_types_by_name)
    assert "HostCommand" not in names
    assert "HostDelta" not in names
    assert "ErrorShape" not in names
```

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/contracts/test_transport_proto_shape.py
```

Expected: import failure because the generated package does not exist.

- [ ] **Step 3: Add the exact proto**

```proto
syntax = "proto3";

package dsp.host.transport.v1;
option csharp_namespace = "Dsp.Host.Transport.V1";

service AutoCadHost {
  rpc Ping(PingRequest) returns (PingResponse);
  rpc Dispatch(DispatchRequest) returns (DispatchResponse);
}

message PingRequest {
  string instance_id = 1;
}

message PingResponse {
  string instance_id = 1;
  string contract_version = 2;
}

message DispatchRequest {
  bytes contract_json = 1;
}

message DispatchResponse {
  bytes contract_json = 1;
}
```

- [ ] **Step 4: Add Python dependencies and generator**

Use:

```toml
dependencies = [
    "host-contracts>=0.1.0",
    "grpcio>=1.70,<2",
    "protobuf>=5.29,<7",
]

[project.optional-dependencies]
pipe = ["pywin32>=306"]
grpc-build = ["grpcio-tools>=1.70,<2"]
```

`tools/generate_host_transport.py` must use `contracts/proto` as the include directory, write both generated modules into `autocad_sidecar/ipc/generated`, verify both files exist, and replace the generated sibling import with:

```python
from . import host_transport_v1_pb2 as host__transport__v1__pb2
```

The generator must raise `RuntimeError` if the expected generated import is not found, so a grpc-tools output-format change fails explicitly.

- [ ] **Step 5: Generate and run GREEN**

```bash
pip install -e contracts/python
pip install -e 'hosts/autocad/sidecar[grpc-build]'
python tools/generate_host_transport.py
pytest -q tests/contracts/test_transport_proto_shape.py
```

Expected: 2 tests pass.

- [ ] **Step 6: Commit**

```bash
git add contracts/proto tools/generate_host_transport.py hosts/autocad/sidecar tests/contracts/test_transport_proto_shape.py
git commit -m "feat(transport): add gRPC transport IDL"
```

---

## Task 2: Autodesk-free .NET transport boundary and leak gate

**Files:**
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/IContractDispatchTarget.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/TransportIdentity.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/GrpcHostOptions.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/NativeTypeLeakTests.cs`

**Produces:**

```csharp
public interface IContractDispatchTarget
{
    ValueTask<byte[]> DispatchAsync(byte[] contractJson, CancellationToken cancellationToken);
}
```

- [ ] **Step 1: Write the failing native-leak tests**

```csharp
using System.Reflection;
using Xunit;

namespace AutoCAD.AgentHost.Grpc.Tests;

public sealed class NativeTypeLeakTests
{
    [Fact]
    public void TransportAssembly_DoesNotReference_AutodeskAssemblies()
    {
        var refs = typeof(IContractDispatchTarget).Assembly.GetReferencedAssemblies();
        Assert.DoesNotContain(refs, assembly =>
            assembly.Name?.StartsWith("Autodesk", StringComparison.OrdinalIgnoreCase) == true);
    }

    [Fact]
    public void TransportPublicApi_DoesNotExpose_AutodeskTypes()
    {
        var assembly = typeof(IContractDispatchTarget).Assembly;
        foreach (var type in assembly.GetExportedTypes())
        {
            foreach (var ctor in type.GetConstructors())
                foreach (var parameter in ctor.GetParameters())
                    AssertNotAutodesk(parameter.ParameterType, $"{type.FullName} ctor");

            foreach (var method in type.GetMethods(BindingFlags.Public | BindingFlags.Instance | BindingFlags.Static))
            {
                AssertNotAutodesk(method.ReturnType, $"{type.FullName}.{method.Name} return");
                foreach (var parameter in method.GetParameters())
                    AssertNotAutodesk(parameter.ParameterType, $"{type.FullName}.{method.Name}");
            }

            foreach (var property in type.GetProperties())
                AssertNotAutodesk(property.PropertyType, $"{type.FullName}.{property.Name}");

            foreach (var field in type.GetFields())
                AssertNotAutodesk(field.FieldType, $"{type.FullName}.{field.Name}");

            foreach (var evt in type.GetEvents())
                AssertNotAutodesk(evt.EventHandlerType!, $"{type.FullName}.{evt.Name}");
        }
    }

    private static void AssertNotAutodesk(Type type, string where)
    {
        var current = Nullable.GetUnderlyingType(type) ?? type;
        if (current.IsArray)
            AssertNotAutodesk(current.GetElementType()!, where);
        if (current.IsGenericType)
            foreach (var argument in current.GetGenericArguments())
                AssertNotAutodesk(argument, where);
        Assert.False(current.Namespace?.StartsWith("Autodesk", StringComparison.OrdinalIgnoreCase) == true,
            $"{where} exposes {current.FullName}");
    }
}
```

- [ ] **Step 2: Run RED**

```bash
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

Expected: project/type not found.

- [ ] **Step 3: Create the project and types**

Target `net8.0-windows`, add `FrameworkReference Include="Microsoft.AspNetCore.App"`, reference `Grpc.AspNetCore` and `Grpc.Tools`, and include:

```xml
<Protobuf Include="..\..\..\..\..\contracts\proto\host_transport_v1.proto"
          GrpcServices="Server" />
```

Create:

```csharp
public sealed record TransportIdentity(string InstanceId, string AuthToken, string ContractVersion);

public sealed record GrpcHostOptions(
    string Host = "127.0.0.1",
    int Port = 0,
    string? DiscoveryDirectory = null);
```

The project must not reference the AutoCAD plugin project or Autodesk DLLs.

- [ ] **Step 4: Run GREEN**

```bash
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

Expected: both leak tests pass.

- [ ] **Step 5: Commit**

```bash
git add hosts/autocad/transport/dotnet
git commit -m "feat(transport): add Autodesk-free gRPC boundary"
```

---

## Task 3: Loopback gRPC host, auth, Ping, Dispatch, cancellation

**Files:**
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/GrpcHostServer.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/GrpcHostHandle.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/Services/AutoCadHostService.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/Auth/BearerTokenInterceptor.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/GrpcHostServerTests.cs`

**Produces:** `GrpcHostServer.StartAsync(IContractDispatchTarget, TransportIdentity, GrpcHostOptions, CancellationToken)` and an async-disposable handle exposing the actual bound port.

- [ ] **Step 1: Write failing host tests**

Create a `RecordingTarget` in the test file with `InvocationCount`, `LastPayload`, and a `TaskCompletionSource` that completes when cancellation is observed. Add tests with these exact expectations:

```csharp
[Fact]
public async Task Ping_ReturnsIdentity_WithCorrectToken()
{
    await using var fixture = await GrpcFixture.StartAsync();
    var reply = await fixture.Client.PingAsync(
        new PingRequest { InstanceId = fixture.Identity.InstanceId },
        headers: fixture.AuthHeaders);
    Assert.Equal(fixture.Identity.InstanceId, reply.InstanceId);
    Assert.Equal(fixture.Identity.ContractVersion, reply.ContractVersion);
}

[Fact]
public async Task WrongToken_IsUnauthenticated_AndDoesNotDispatch()
{
    await using var fixture = await GrpcFixture.StartAsync();
    var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        await fixture.Client.DispatchAsync(
            new DispatchRequest { ContractJson = ByteString.CopyFromUtf8("{}") },
            headers: new Metadata { { "authorization", "Bearer wrong" } }));
    Assert.Equal(StatusCode.Unauthenticated, ex.StatusCode);
    Assert.Equal(0, fixture.Target.InvocationCount);
}

[Fact]
public async Task EmptyContractJson_IsInvalidArgument()
{
    await using var fixture = await GrpcFixture.StartAsync();
    var ex = await Assert.ThrowsAsync<RpcException>(async () =>
        await fixture.Client.DispatchAsync(new DispatchRequest(), headers: fixture.AuthHeaders));
    Assert.Equal(StatusCode.InvalidArgument, ex.StatusCode);
}

[Fact]
public async Task Dispatch_PreservesBytesExactly()
{
    await using var fixture = await GrpcFixture.StartAsync(responseBytes: new byte[] { 1, 2, 3 });
    var response = await fixture.Client.DispatchAsync(
        new DispatchRequest { ContractJson = ByteString.CopyFrom(new byte[] { 9, 8, 7 }) },
        headers: fixture.AuthHeaders);
    Assert.Equal(new byte[] { 9, 8, 7 }, fixture.Target.LastPayload);
    Assert.Equal(new byte[] { 1, 2, 3 }, response.ContractJson.ToByteArray());
}
```

Also add a missing-token test, an instance-id mismatch test expecting `FAILED_PRECONDITION`, a cancellation propagation test, and a loopback/dynamic-port test asserting `Port > 0` and the endpoint address is `127.0.0.1`.

- [ ] **Step 2: Run RED**

```bash
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj --filter GrpcHostServerTests
```

Expected: compile failure because host/service/interceptor types do not exist.

- [ ] **Step 3: Implement server and auth**

Kestrel binding:

```csharp
options.Listen(IPAddress.Loopback, hostOptions.Port, listen =>
{
    listen.Protocols = HttpProtocols.Http2;
});
```

Authentication must require exactly `authorization: Bearer <token>` and compare UTF-8 token bytes using `CryptographicOperations.FixedTimeEquals` before service dispatch.

Service dispatch:

```csharp
if (request.ContractJson.IsEmpty)
    throw new RpcException(new Status(StatusCode.InvalidArgument, "contract_json is required"));

var response = await target.DispatchAsync(
    request.ContractJson.ToByteArray(),
    context.CancellationToken);

return new DispatchResponse { ContractJson = ByteString.CopyFrom(response) };
```

The service must not parse DSP JSON.

- [ ] **Step 4: Run GREEN**

```bash
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

Expected: all transport host tests and native-leak tests pass.

- [ ] **Step 5: Commit**

```bash
git add hosts/autocad/transport/dotnet
git commit -m "feat(transport): host authenticated gRPC on loopback"
```

---

## Task 4: Discovery publication and Python discovery validation

**Files:**
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/Discovery/HostDiscoveryRecord.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/Discovery/DiscoveryPublisher.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/DiscoveryPublisherTests.cs`
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/discovery.py`
- Create: `tests/integration/test_autocad_discovery.py`

**Produces:** .NET `DiscoveryPublisher.PublishAsync` returning an async-disposable lease; Python `load_instance(instance_id, discovery_dir=None)` returning a validated `HostEndpoint` dataclass.

- [ ] **Step 1: Write failing Python discovery tests**

```python
import json
import os
from pathlib import Path

import pytest

from autocad_sidecar.ipc.discovery import load_instance


def write_record(root: Path, *, instance_id: str = "inst-1", pid: int | None = None,
                 host: str = "127.0.0.1", port: int = 53182,
                 transport: str = "grpc-h2c", token: str = "token-1") -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{instance_id}.json").write_text(json.dumps({
        "instance_id": instance_id,
        "pid": os.getpid() if pid is None else pid,
        "host": host,
        "port": port,
        "transport": transport,
        "contract_version": "1.0",
        "auth_token": token,
    }), encoding="utf-8")


def test_load_instance_returns_valid_endpoint(tmp_path):
    write_record(tmp_path)
    endpoint = load_instance("inst-1", tmp_path)
    assert endpoint.host == "127.0.0.1"
    assert endpoint.port == 53182
    assert endpoint.auth_token == "token-1"


def test_load_instance_rejects_non_loopback_host(tmp_path):
    write_record(tmp_path, host="0.0.0.0")
    with pytest.raises(ValueError, match="loopback"):
        load_instance("inst-1", tmp_path)


def test_load_instance_rejects_wrong_transport(tmp_path):
    write_record(tmp_path, transport="pipe")
    with pytest.raises(ValueError, match="grpc-h2c"):
        load_instance("inst-1", tmp_path)


def test_load_instance_rejects_dead_pid(tmp_path):
    write_record(tmp_path, pid=2_147_000_000)
    with pytest.raises(ConnectionError, match="process"):
        load_instance("inst-1", tmp_path)
```

Use `ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)` for Windows PID liveness; do not add `psutil` only for this feature.

- [ ] **Step 2: Write failing .NET publisher tests**

Test exact JSON fields, final-path publication only after atomic rename, production path under LocalAppData, current-user ACL without broad `Everyone` write access, and record removal when the lease is disposed.

- [ ] **Step 3: Run RED on Windows**

```powershell
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj --filter DiscoveryPublisherTests
pytest -q tests/integration/test_autocad_discovery.py
```

Expected: missing publisher/reader failures.

- [ ] **Step 4: Implement discovery**

Record schema:

```json
{
  "instance_id": "7d5027fd-56c3-4bf5-b370-c1aee8f70393",
  "pid": 12345,
  "host": "127.0.0.1",
  "port": 53182,
  "transport": "grpc-h2c",
  "contract_version": "1.0",
  "auth_token": "base64url-256-bit-token"
}
```

Write to a random temp file in the same directory, flush/close, apply current-user ACL, then atomically move/replace to `<instance_id>.json`. Python rejects missing fields, dead PID, non-loopback host, invalid port, wrong transport, empty token, or mismatched instance id.

- [ ] **Step 5: Run GREEN**

Run both Step 3 commands. Expected: pass.

- [ ] **Step 6: Commit**

```bash
git add hosts/autocad/transport hosts/autocad/sidecar/src/autocad_sidecar/ipc/discovery.py tests/integration/test_autocad_discovery.py
git commit -m "feat(transport): publish and validate host discovery"
```

---

## Task 5: Python transport abstraction, gRPC client, deadline, selector

**Files:**
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/base.py`
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/grpc_transport.py`
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/transport_selector.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/transport.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/host_adapter.py`
- Create: `tests/integration/test_transport_selector.py`
- Create: `tests/integration/test_host_adapter_transport.py`

**Produces:**

```python
class FrameTransport(Protocol):
    async def open(self) -> None:
        raise NotImplementedError

    async def exchange(self, payload: bytes, *, timeout_s: float | None = None) -> bytes:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError
```

- [ ] **Step 1: Write failing selector tests**

```python
import pytest

from autocad_sidecar.ipc.transport import PipeTransport
from autocad_sidecar.ipc.transport_selector import build_transport


def test_selector_builds_pipe_transport():
    transport = build_transport("pipe", pipe_name="EnterpriseDesignAgent.test")
    assert isinstance(transport, PipeTransport)


def test_selector_requires_instance_id_for_grpc():
    with pytest.raises(ValueError, match="instance_id"):
        build_transport("grpc")


def test_selector_rejects_unknown_kind():
    with pytest.raises(ValueError, match="unsupported transport"):
        build_transport("udp")
```

- [ ] **Step 2: Write failing HostAdapter injection test**

```python
import json

import pytest

from autocad_sidecar.adapter.host_adapter import HostAdapter
from host_contracts.command import HostCommand


class FakeTransport:
    def __init__(self):
        self.open_count = 0
        self.payloads: list[bytes] = []
        self.closed = False

    async def open(self) -> None:
        self.open_count += 1

    async def exchange(self, payload: bytes, *, timeout_s: float | None = None) -> bytes:
        self.payloads.append(payload)
        request_id = json.loads(payload)["request_id"]
        return json.dumps({
            "request_id": request_id,
            "status": "OK",
            "result": {"command_id": "cmd-1", "status": "OK"},
        }).encode()

    async def close(self) -> None:
        self.closed = True


@pytest.mark.asyncio
async def test_host_adapter_uses_injected_transport():
    transport = FakeTransport()
    adapter = HostAdapter(transport=transport)
    result = await adapter.send_command(HostCommand(
        command_id="cmd-1",
        mode="READ",
        operation="context.current_document",
    ))
    assert result.command_id == "cmd-1"
    assert len(transport.payloads) == 1
    await adapter.close()
    assert transport.closed
```

- [ ] **Step 3: Run RED**

```bash
pytest -q tests/integration/test_transport_selector.py tests/integration/test_host_adapter_transport.py
```

Expected: import/signature failures.

- [ ] **Step 4: Adapt Named Pipe and implement gRPC transport**

`PipeTransport.exchange` accepts `timeout_s`; when set, wrap the executor future with `asyncio.wait_for` without changing framing.

`GrpcTransport(instance_id, discovery_dir=None, max_timeout_s=30.0)` must:
- load and validate discovery;
- create `grpc.aio.insecure_channel(f"127.0.0.1:{port}")`;
- attach `authorization: Bearer <token>` to Ping and Dispatch;
- Ping the expected instance during `open()`;
- close and raise on identity mismatch;
- pass the chosen timeout to `Dispatch`;
- return `response.contract_json` unchanged.

- [ ] **Step 5: Implement business-deadline to transport-timeout calculation**

`HostAdapter` computes remaining seconds from `RequestEnvelope.deadline_at`; the RPC timeout is the smaller non-null value of remaining business deadline and transport maximum. If remaining time is non-positive, fail before network send. Do not synthesize a DSP business error.

- [ ] **Step 6: Run GREEN and regressions**

```bash
pip install -e contracts/python
pip install -e hosts/autocad/sidecar
pytest -q tests/integration/test_transport_selector.py tests/integration/test_host_adapter_transport.py
pytest -q contracts/python/tests tests/contracts
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add hosts/autocad/sidecar tests/integration
git commit -m "feat(sidecar): add transport-neutral gRPC client"
```

---

## Task 6: Dynamic Python ↔ C# gRPC conformance (TC-RPC01 through TC-RPC07)

**Files:**
- Create: `tests/transport/dotnet/ContractTransportTestHost/ContractTransportTestHost.csproj`
- Create: `tests/transport/dotnet/ContractTransportTestHost/Program.cs`
- Create: `tests/transport/dotnet/ContractTransportTestHost/FakeDispatchTarget.cs`
- Create: `tests/transport/test_grpc_transport_conformance.py`
- Create: `.github/workflows/grpc-transport-conformance.yml`

**Test host CLI:** `--instance-id`, `--token`, `--discovery-dir`, `--mode normal|block`, `--counter-file`. On start it prints one readiness JSON line to stdout with `instance_id`, `port`, `pid`; logs go to stderr.

- [ ] **Step 1: Write the Python process fixture and TC-RPC01/02**

The fixture starts:

```text
dotnet run --project tests/transport/dotnet/ContractTransportTestHost/ContractTransportTestHost.csproj -- --instance-id inst-a --token token-a --discovery-dir <temp> --mode normal --counter-file <temp>/count.txt
```

It reads the first stdout line as JSON, constructs `GrpcTransport("inst-a", discovery_dir=temp)`, and always terminates the process in fixture cleanup.

Tests:

```python
@pytest.mark.asyncio
@pytest.mark.conformance
async def test_rpc01_python_to_csharp_ping(running_host):
    transport = running_host.transport
    await transport.open()
    assert transport.endpoint.instance_id == "inst-a"
    assert transport.endpoint.port == running_host.port
    await transport.close()


@pytest.mark.asyncio
@pytest.mark.conformance
async def test_rpc02_python_to_csharp_dispatch_preserves_contract(running_host):
    await running_host.transport.open()
    request = b'{"request_id":"req-1","payload":{}}'
    response = await running_host.transport.exchange(request, timeout_s=5.0)
    parsed = json.loads(response)
    assert parsed["request_id"] == "req-1"
    assert parsed["status"] == "OK"
```

- [ ] **Step 2: Add TC-RPC03 through TC-RPC07 with exact outcomes**

- TC-RPC03 starts `--mode block`, calls `exchange(..., timeout_s=0.05)`, and asserts `grpc.aio.AioRpcError.code() == grpc.StatusCode.DEADLINE_EXCEEDED`.
- TC-RPC04 starts a raw generated `Dispatch` call against block mode, calls `cancel()`, awaits the call expecting `asyncio.CancelledError`, then asserts `await call.code() == grpc.StatusCode.CANCELLED`; the C# fake target writes `cancelled` to its counter/status file after its token is cancelled.
- TC-RPC05 sends malformed DSP JSON and asserts the gRPC call returns normally; returned bytes decode to a DSP response with `status == "ERROR"` and a non-empty `error.error_code`.
- TC-RPC06 uses missing and wrong bearer metadata through a raw generated stub, asserts `UNAUTHENTICATED`, then reads the counter file and asserts dispatch invocation count remains zero.
- TC-RPC07 starts `inst-a/token-a` and `inst-b/token-b`, asserts ports differ, successful matching Ping for each, and asserts using token A against instance B returns `UNAUTHENTICATED`.

- [ ] **Step 3: Run RED**

```bash
pytest -q tests/transport/test_grpc_transport_conformance.py
```

Expected: test-host project missing.

- [ ] **Step 4: Implement the test host**

The host references the production gRPC transport project. `normal` fake dispatch parses request id and returns a valid DSP `ResponseEnvelope` JSON; malformed JSON returns a valid DSP error envelope. `block` waits on the cancellation token. Every dispatch increments the counter file using a file lock/atomic replace so auth tests can prove zero invocations.

- [ ] **Step 5: Run GREEN locally**

```bash
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
pytest -q tests/transport/test_grpc_transport_conformance.py
```

Expected: .NET transport suite passes; TC-RPC01 through TC-RPC07 pass.

- [ ] **Step 6: Add Windows CI**

Workflow uses `windows-latest`, Python 3.11, .NET 8 and installs:

```powershell
pip install -e contracts/python
pip install -e hosts/autocad/sidecar
```

Then run the two Step 5 commands. Push and verify the Actions run concludes `success` before claiming cross-language gRPC compatibility.

- [ ] **Step 7: Commit**

```bash
git add tests/transport .github/workflows/grpc-transport-conformance.yml
git commit -m "test(transport): verify Python C# gRPC conformance"
```

---

## Task 7: AutoCAD plugin bridge and dual-stack lifecycle

**Files:**
- Create: `hosts/autocad/plugin/AutoCAD.AgentHost/Ipc/GrpcRequestDispatcherTarget.cs`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Bootstrap/PluginLifecycle.cs`
- Create: `tests/contracts/test_plugin_grpc_wiring_source.py`

**Produces:** adapter from existing synchronous `RequestDispatcher` to `IContractDispatchTarget`; Plugin starts both pipe and gRPC during migration.

- [ ] **Step 1: Write the failing source-controlled wiring guard**

```python
from pathlib import Path


def test_plugin_lifecycle_keeps_pipe_and_adds_grpc_during_migration():
    lifecycle = Path(
        "hosts/autocad/plugin/AutoCAD.AgentHost/Bootstrap/PluginLifecycle.cs"
    ).read_text(encoding="utf-8")
    assert "NamedPipeServer" in lifecycle
    assert "GrpcHostServer" in lifecycle
    assert "DiscoveryPublisher" in lifecycle


def test_plugin_project_references_transport_project():
    project = Path(
        "hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj"
    ).read_text(encoding="utf-8")
    assert "AutoCAD.AgentHost.Grpc.csproj" in project
```

This guard does not replace the Autodesk-enabled build; it only prevents source-level loss of dual-stack wiring in CI.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/contracts/test_plugin_grpc_wiring_source.py
```

Expected: gRPC strings/reference absent.

- [ ] **Step 3: Implement the bridge**

```csharp
public sealed class GrpcRequestDispatcherTarget : IContractDispatchTarget
{
    private readonly RequestDispatcher _dispatcher;

    public GrpcRequestDispatcherTarget(RequestDispatcher dispatcher) => _dispatcher = dispatcher;

    public ValueTask<byte[]> DispatchAsync(byte[] contractJson, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        return ValueTask.FromResult(_dispatcher.Dispatch(contractJson));
    }
}
```

Plugin startup order: construct dispatcher; start existing pipe; create `instance_id` and 32 random token bytes encoded base64url; start gRPC on port 0; publish discovery only after listen; attach ChangeSensor. Shutdown order: detach sensor; dispose discovery lease; dispose gRPC host; stop pipe.

If gRPC startup fails, log and retain pipe fallback. Do not publish a broken discovery record.

- [ ] **Step 4: Run source guard GREEN and real plugin build where Autodesk is available**

```bash
pytest -q tests/contracts/test_plugin_grpc_wiring_source.py
```

On the AutoCAD developer machine:

```powershell
$env:AUTOCAD_ACAD_DIR='C:\Program Files\Autodesk\AutoCAD 2025\Acad'
dotnet build hosts/autocad/plugin/AutoCAD.AgentHost.sln -c Release
```

Do not claim plugin build success without this Autodesk-enabled command reaching exit code 0.

- [ ] **Step 5: Commit**

```bash
git add hosts/autocad/plugin tests/contracts/test_plugin_grpc_wiring_source.py
git commit -m "feat(autocad): bridge dispatcher to gRPC transport"
```

---

## Task 8: Sidecar CLI and HostAdapter transport selection, pipe still default

**Files:**
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/main.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/host_adapter.py`
- Modify: `tools/host_test_client/main.py`
- Create: `tests/integration/test_sidecar_transport_cli.py`

**Produces:** `--transport {pipe,grpc}`, `--instance-id`, existing `--pipe`; environment `DSP_AUTOCAD_TRANSPORT` may select transport, otherwise default is `pipe`.

- [ ] **Step 1: Write failing CLI tests**

```python
from autocad_sidecar.main import build_parser


def test_default_transport_remains_pipe(monkeypatch):
    monkeypatch.delenv("DSP_AUTOCAD_TRANSPORT", raising=False)
    args = build_parser().parse_args([])
    assert args.transport == "pipe"


def test_env_can_select_grpc(monkeypatch):
    monkeypatch.setenv("DSP_AUTOCAD_TRANSPORT", "grpc")
    args = build_parser().parse_args(["--instance-id", "inst-1"])
    assert args.transport == "grpc"
    assert args.instance_id == "inst-1"


def test_pipe_keeps_existing_pipe_option(monkeypatch):
    monkeypatch.delenv("DSP_AUTOCAD_TRANSPORT", raising=False)
    args = build_parser().parse_args(["--pipe", "EnterpriseDesignAgent.test"])
    assert args.transport == "pipe"
    assert args.pipe == "EnterpriseDesignAgent.test"
```

Also test the configuration-validation function with `transport="grpc"` and `instance_id=None`, asserting a `ValueError` containing `instance_id`.

- [ ] **Step 2: Run RED**

```bash
pytest -q tests/integration/test_sidecar_transport_cli.py
```

Expected: parser has no transport/instance fields.

- [ ] **Step 3: Implement selection and injection**

Create the transport via `build_transport`, inject it into `HostAdapter`, and remove direct `PipeClient` construction from `HostAdapter`. Keep Named Pipe implementation intact.

Readiness output is transport-neutral:

```text
sidecar ready (transport=grpc, instance_id=inst-1)
```

or:

```text
sidecar ready (transport=pipe, pipe=EnterpriseDesignAgent.test)
```

Update `tools/host_test_client/main.py` to pass the same transport selection into `HostAdapter` rather than touching framing directly.

- [ ] **Step 4: Run GREEN and regressions**

```bash
pip install -e contracts/python
pip install -e hosts/autocad/sidecar
pytest -q tests/integration/test_sidecar_transport_cli.py
pytest -q contracts/python/tests tests/contracts tests/integration
```

Expected: all pass; pipe remains default.

- [ ] **Step 5: Commit**

```bash
git add hosts/autocad/sidecar tools/host_test_client tests/integration/test_sidecar_transport_cli.py
git commit -m "feat(sidecar): select gRPC or pipe transport"
```

---

## Task 9: Real AutoCAD smoke gate and rollout documentation

**Files:**
- Create: `docs/runbooks/autocad-grpc-smoke.md`
- Modify: `README.md`

- [ ] **Step 1: Write the exact smoke sequence**

The runbook records AutoCAD version, .NET runtime, `instance_id`, dynamic port and pass/fail evidence for:

1. Plugin load and discovery record creation only after gRPC listen.
2. Sidecar Ping/status using the exact instance id.
3. CurrentDocument.
4. CurrentSelection.
5. MOVE once with recorded revision before/after.
6. Replay same idempotency key with no second mutation and correct replay semantics.
7. Stale revision returning DSP `REVISION_CONFLICT`, not gRPC error.
8. Expired/short deadline returning `DEADLINE_EXCEEDED` at a safe point.
9. Two simultaneous AutoCAD processes with distinct instance ids, ports and tokens.
10. Token A against instance B rejected.
11. AutoCAD exit/unload removes discovery record.

The runbook uses:

```powershell
$env:DSP_AUTOCAD_TRANSPORT='grpc'
python -m autocad_sidecar.main --transport grpc --instance-id 7d5027fd-56c3-4bf5-b370-c1aee8f70393 status
```

and the corresponding updated `tools/host_test_client` commands for CurrentDocument, CurrentSelection and MOVE.

- [ ] **Step 2: State the default-switch gate explicitly**

The runbook states: Named Pipe remains default until every smoke item above passes on a supported AutoCAD installation and evidence is attached to the review. Any failed item blocks default switching but does not require reverting the opt-in gRPC implementation.

- [ ] **Step 3: Update README without overstating status**

README must say exactly:

```text
Current default transport: Named Pipe
Opt-in migration transport: gRPC over loopback
Default-switch gate: docs/runbooks/autocad-grpc-smoke.md
```

- [ ] **Step 4: Verify all non-Autodesk tests and CI**

```bash
pip install -e contracts/python
pip install -e hosts/autocad/sidecar
pytest -q contracts/python/tests tests/contracts tests/integration tests/transport
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

Expected: all pass. Separately verify GitHub Actions `grpc-transport-conformance` conclusion is `success`.

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/autocad-grpc-smoke.md README.md
git commit -m "docs(transport): add AutoCAD gRPC rollout gate"
```

---

## Post-Implementation Gates

This plan does not change the default to gRPC and does not delete Named Pipe.

After Task 9 real-host evidence passes, create a separate review for the default switch. That review changes only selection defaults/configuration and documentation.

After the gRPC default has operated successfully through the agreed validation window, create another separately approved cleanup review that deletes `NamedPipeServer.cs`, Python pipe framing/client code, pipe-only malformed-frame/partial-read tests, the pipe-only `pywin32` dependency, and marks ADR-002 historical/superseded by ADR-004.

## Self-Review Result

- Every spec acceptance criterion maps to a task.
- HostContract JSON wire remains unchanged.
- Proto is transport-only.
- Auth-before-dispatch has a zero-invocation proof.
- Dynamic port and two-instance isolation are automated.
- DSP business errors remain JSON bytes over gRPC `OK`.
- Deadline and cancellation have .NET and cross-language coverage.
- The transport assembly has an Autodesk leak gate.
- Plugin remains dual-stack and pipe remains default.
- Local/CI Python install order installs `contracts/python` first.
- Generated Python gRPC sibling import is package-relative.
- C# proto path uses five parent segments from the transport project to repository-root `contracts/proto`.
- Real AutoCAD evidence is required before default switching.
- Named Pipe cleanup is outside this plan.
