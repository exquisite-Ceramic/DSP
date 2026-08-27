# gRPC Loopback Transport Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the custom Python ↔ C# Named Pipe RPC/framing path with a dual-stack gRPC-over-loopback transport while preserving the existing DSP HostContract JSON wire and keeping Named Pipe as rollback until real AutoCAD validation passes.

**Architecture:** Phase 1 adds a transport-only protobuf IDL with `Ping` and `Dispatch(bytes)`; the existing `RequestEnvelope`/`ResponseEnvelope` JSON remains the business wire. A pure .NET transport assembly hosts Kestrel on `127.0.0.1:0`, authenticates a per-instance bearer token, and delegates raw JSON bytes through `IContractDispatchTarget`; Python discovers the instance, connects with `grpc.aio`, and exposes the same bytes-in/bytes-out exchange shape to `HostAdapter`.

**Tech Stack:** Python 3.11+, `grpcio`, `protobuf`, build-only `grpcio-tools`; .NET 8 (`net8.0-windows`), ASP.NET Core/Kestrel, grpc-dotnet, `Grpc.Tools`; pytest, xUnit, GitHub Actions `windows-latest`.

**Spec:** `docs/superpowers/specs/2026-08-27-grpc-loopback-transport-design.md`

## Global Constraints

- Existing DSP HostContract wire JSON must remain unchanged in phase 1.
- `contracts/proto/host_transport_v1.proto` is transport-only; it must not duplicate `HostCommand`, `HostDelta`, `ErrorShape`, revision, idempotency, or other business fields.
- gRPC binds only IPv4 loopback `127.0.0.1` and uses an OS-assigned dynamic port; no fixed shared port.
- Each AutoCAD instance has a unique `instance_id`, dynamic port, and random 256-bit bearer token.
- Discovery records live under `%LOCALAPPDATA%/EnterpriseDesignAgent/hosts/` in production and are current-user-only; tests may override the discovery directory explicitly.
- gRPC status is reserved for transport/auth/deadline/cancellation/empty-transport-request failures; DSP business failures remain `ResponseEnvelope` / `ErrorShape` bytes with gRPC status `OK`.
- Named Pipe remains available during migration and remains the default until real AutoCAD smoke validation passes.
- The new transport assembly must not reference any `Autodesk.*` assembly or expose any `Autodesk.*` public type.
- Native AutoCAD mutation cancellation is cooperative and only honored at safe points; no half-applied document mutation is allowed.
- No runtime `protoc` invocation; generated Python transport modules are checked in/packaged, while C# generation is performed at build time by `Grpc.Tools`.
- Legacy framing deletion and ADR-002 supersession are a separate cleanup change after the real-host gate; they are not part of this plan.

---

## File Structure

### Shared transport IDL

- Create `contracts/proto/host_transport_v1.proto` — transport-only `Ping`/`Dispatch` RPC contract.
- Create `tools/generate_host_transport.py` — deterministic development/CI generator for checked-in Python stubs.
- Create `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/__init__.py` — generated package boundary.
- Generate `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/host_transport_v1_pb2.py`.
- Generate `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/host_transport_v1_pb2_grpc.py`.

### Pure .NET gRPC transport

- Create `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj`.
- Create `.../IContractDispatchTarget.cs` — raw JSON dispatch boundary.
- Create `.../TransportIdentity.cs` — instance id/token/version model.
- Create `.../GrpcHostOptions.cs` — loopback/listen/discovery configuration.
- Create `.../GrpcHostServer.cs` — Kestrel/gRPC lifecycle and dynamic port discovery.
- Create `.../Services/AutoCadHostService.cs` — generated service implementation.
- Create `.../Auth/BearerTokenInterceptor.cs` — metadata authentication.
- Create `.../Discovery/HostDiscoveryRecord.cs` — serialized discovery model.
- Create `.../Discovery/DiscoveryPublisher.cs` — atomic current-user-only record publisher.
- Create `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/...` — xUnit tests that run without Autodesk.

### Python transport and discovery

- Create `hosts/autocad/sidecar/src/autocad_sidecar/ipc/base.py` — transport protocol.
- Create `.../discovery.py` — record parsing, PID check, stale handling.
- Create `.../grpc_transport.py` — async gRPC implementation.
- Create `.../transport_selector.py` — explicit `grpc|pipe` construction.
- Modify existing `.../transport.py` — make Named Pipe implementation satisfy the common protocol and honor optional timeout.
- Modify `.../adapter/host_adapter.py` — depend on transport abstraction instead of directly on `PipeClient`.
- Modify `.../main.py` — add transport/instance selection while keeping pipe default.

### Cross-language conformance harness

- Create `tests/transport/dotnet/ContractTransportTestHost/` — .NET process with fake dispatch targets.
- Create `tests/transport/test_grpc_transport_conformance.py` — TC-RPC01 through TC-RPC07.
- Create `.github/workflows/grpc-transport-conformance.yml` — Windows Python + .NET test job.

### AutoCAD plugin bridge

- Create `hosts/autocad/plugin/AutoCAD.AgentHost/Ipc/GrpcRequestDispatcherTarget.cs` — minimal adapter from current `RequestDispatcher` to `IContractDispatchTarget`.
- Modify `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj` — reference the transport project.
- Modify `hosts/autocad/plugin/AutoCAD.AgentHost/Bootstrap/PluginLifecycle.cs` — start/stop gRPC alongside Named Pipe and publish/remove discovery only after listen succeeds.

### Validation/runbook

- Modify `tools/host_test_client/main.py` — allow explicit `grpc` + `instance_id` selection without removing pipe support.
- Create `docs/runbooks/autocad-grpc-smoke.md` — exact real-host validation sequence and evidence checklist.

---

### Task 1: Add the transport-only protobuf IDL and deterministic Python generation

**Files:**
- Create: `contracts/proto/host_transport_v1.proto`
- Create: `tools/generate_host_transport.py`
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/__init__.py`
- Generate: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/host_transport_v1_pb2.py`
- Generate: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/host_transport_v1_pb2_grpc.py`
- Modify: `hosts/autocad/sidecar/pyproject.toml`
- Create: `tests/contracts/test_transport_proto_shape.py`

**Interfaces:**
- Produces protobuf package `dsp.host.transport.v1` and C# namespace `Dsp.Host.Transport.V1`.
- Produces RPCs `Ping(PingRequest) -> PingResponse` and `Dispatch(DispatchRequest) -> DispatchResponse`.
- `DispatchRequest.contract_json` and `DispatchResponse.contract_json` are `bytes` and are the only business-payload carriers.

- [ ] **Step 1: Write the failing proto-shape test**

```python
from autocad_sidecar.ipc.generated import host_transport_v1_pb2 as pb


def test_transport_proto_is_transport_only():
    req = pb.DispatchRequest(contract_json=b'{"request_id":"r1","payload":{}}')
    assert req.contract_json.startswith(b"{")

    message_names = set(pb.DESCRIPTOR.message_types_by_name)
    assert message_names == {
        "PingRequest",
        "PingResponse",
        "DispatchRequest",
        "DispatchResponse",
    }
    assert "HostCommand" not in message_names
    assert "HostDelta" not in message_names
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
pytest -q tests/contracts/test_transport_proto_shape.py
```

Expected: FAIL during import because the generated transport module does not exist yet.

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

- [ ] **Step 4: Add Python runtime/build dependencies and deterministic generator**

Use the sidecar dependency ranges:

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

`tools/generate_host_transport.py` must invoke `python -m grpc_tools.protoc` with the repository root as the proto include root and write Python outputs directly into `autocad_sidecar/ipc/generated/`. It must exit nonzero if generation fails and must not run from production startup code.

- [ ] **Step 5: Generate and run the test GREEN**

Run:

```bash
pip install -e 'hosts/autocad/sidecar[grpc-build]'
python tools/generate_host_transport.py
pytest -q tests/contracts/test_transport_proto_shape.py
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add contracts/proto tools/generate_host_transport.py hosts/autocad/sidecar tests/contracts/test_transport_proto_shape.py
git commit -m "feat(transport): add gRPC transport IDL"
```

---

### Task 2: Create the Autodesk-free .NET transport project and leak gate

**Files:**
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/IContractDispatchTarget.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/TransportIdentity.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/GrpcHostOptions.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/NativeTypeLeakTests.cs`

**Interfaces:**
- Produces:

```csharp
public interface IContractDispatchTarget
{
    ValueTask<byte[]> DispatchAsync(byte[] contractJson, CancellationToken cancellationToken);
}
```

- Produces immutable `TransportIdentity` with `InstanceId`, `AuthToken`, `ContractVersion`.
- Produces `GrpcHostOptions` with production default host `127.0.0.1`, port `0`, and optional discovery directory override for tests.

- [ ] **Step 1: Write the failing assembly leak test**

```csharp
[Fact]
public void TransportAssembly_DoesNotReference_Autodesk()
{
    var refs = typeof(IContractDispatchTarget).Assembly.GetReferencedAssemblies();
    Assert.DoesNotContain(refs, a =>
        a.Name?.StartsWith("Autodesk", StringComparison.OrdinalIgnoreCase) == true);
}
```

Also scan exported public properties, fields, method return types/parameters, constructor parameters, events, arrays, nullable/generic arguments for namespaces beginning with `Autodesk`.

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

Expected: FAIL because the transport project/types do not exist.

- [ ] **Step 3: Create project boundaries**

The production project targets `net8.0-windows`, uses `FrameworkReference Include="Microsoft.AspNetCore.App"`, references `Grpc.AspNetCore` and `Grpc.Tools`, and includes:

```xml
<Protobuf Include="..\..\..\..\contracts\proto\host_transport_v1.proto"
          GrpcServices="Server" />
```

It must not reference the AutoCAD plugin project or any Autodesk DLL. The test project references only the new transport project and xUnit test packages.

- [ ] **Step 4: Add the minimal public types**

```csharp
public sealed record TransportIdentity(
    string InstanceId,
    string AuthToken,
    string ContractVersion);

public sealed record GrpcHostOptions(
    string Host = "127.0.0.1",
    int Port = 0,
    string? DiscoveryDirectory = null);
```

Generate the token with `RandomNumberGenerator.GetBytes(32)` and base64url encoding at the composition layer; do not embed token generation inside the DTO.

- [ ] **Step 5: Run tests GREEN**

Run:

```bash
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

Expected: PASS and no Autodesk references.

- [ ] **Step 6: Commit**

```bash
git add hosts/autocad/transport/dotnet
git commit -m "feat(transport): add Autodesk-free gRPC transport boundary"
```

---

### Task 3: Implement loopback gRPC host, authentication, Ping, Dispatch, deadline and cancellation

**Files:**
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/GrpcHostServer.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/GrpcHostHandle.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/Services/AutoCadHostService.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/Auth/BearerTokenInterceptor.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/GrpcHostServerTests.cs`

**Interfaces:**
- `GrpcHostServer.StartAsync(IContractDispatchTarget, TransportIdentity, GrpcHostOptions, CancellationToken) -> GrpcHostHandle`.
- `GrpcHostHandle.Port` exposes the actual OS-assigned port after Kestrel starts.
- `GrpcHostHandle.DisposeAsync()` stops the host.
- Service passes `ServerCallContext.CancellationToken` to the dispatch target.

- [ ] **Step 1: Write failing .NET host tests**

Cover all of the following in one focused test class:

```csharp
[Fact] public async Task Ping_ReturnsIdentity_WithCorrectToken();
[Fact] public async Task MissingToken_IsUnauthenticated_AndDoesNotDispatch();
[Fact] public async Task WrongToken_IsUnauthenticated_AndDoesNotDispatch();
[Fact] public async Task EmptyContractJson_IsInvalidArgument();
[Fact] public async Task Dispatch_PreservesBytesExactly();
[Fact] public async Task Cancellation_ReachesDispatchTarget();
[Fact] public async Task Host_BindsIpv4Loopback_OnDynamicPort();
```

Use a fake target with `InvocationCount` and a `TaskCompletionSource` to observe cancellation.

- [ ] **Step 2: Run tests and verify RED**

Run:

```bash
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj --filter GrpcHostServerTests
```

Expected: FAIL because host/service/interceptor types are absent.

- [ ] **Step 3: Implement Kestrel host on `IPAddress.Loopback`, port `0`**

The Kestrel endpoint must be configured as HTTP/2 only:

```csharp
options.Listen(IPAddress.Loopback, hostOptions.Port, listen =>
{
    listen.Protocols = HttpProtocols.Http2;
});
```

After `StartAsync`, obtain the bound address from the server features and return the actual port in `GrpcHostHandle`. Assert the parsed host is loopback before returning the handle.

- [ ] **Step 4: Implement bearer auth before service dispatch**

Read `authorization` metadata, require exactly `Bearer <token>`, compare token bytes with `CryptographicOperations.FixedTimeEquals`, and throw `RpcException(StatusCode.Unauthenticated, ...)` on failure. The fake target invocation count must remain zero for auth failures.

- [ ] **Step 5: Implement Ping and Dispatch**

`Ping` returns `identity.InstanceId` and `identity.ContractVersion`; if a non-empty request `instance_id` differs from the current instance, return `FAILED_PRECONDITION` so stale/mis-targeted discovery is explicit.

`Dispatch` behavior:

```csharp
if (request.ContractJson.IsEmpty)
    throw new RpcException(new Status(StatusCode.InvalidArgument, "contract_json is required"));

var response = await target.DispatchAsync(request.ContractJson.ToByteArray(), context.CancellationToken);
return new DispatchResponse { ContractJson = ByteString.CopyFrom(response) };
```

Do not parse DSP JSON in the gRPC service.

- [ ] **Step 6: Run tests GREEN**

Run:

```bash
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add hosts/autocad/transport/dotnet
git commit -m "feat(transport): host authenticated gRPC on loopback"
```

---

### Task 4: Add discovery record publication and Python discovery validation

**Files:**
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/Discovery/HostDiscoveryRecord.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/Discovery/DiscoveryPublisher.cs`
- Create: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/DiscoveryPublisherTests.cs`
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/discovery.py`
- Create: `tests/integration/test_autocad_discovery.py`

**Interfaces:**
- .NET `DiscoveryPublisher.PublishAsync(record) -> DiscoveryLease`; disposing the lease removes the record if it still belongs to the same instance.
- Python `load_instance(instance_id: str, discovery_dir: Path | None = None) -> HostEndpoint`.
- Python `HostEndpoint` fields: `instance_id`, `pid`, `host`, `port`, `transport`, `contract_version`, `auth_token`.

- [ ] **Step 1: Write failing .NET publisher tests**

Verify:

- file is not visible under its final name before atomic replace;
- final JSON has exactly the required fields;
- production path resolves under `%LOCALAPPDATA%/EnterpriseDesignAgent/hosts`;
- file/directory ACL grants the current user and does not grant broad write access to `Everyone`;
- disposing the lease removes its record.

- [ ] **Step 2: Write failing Python discovery tests**

```python
def test_load_instance_rejects_dead_pid(tmp_path): ...
def test_load_instance_rejects_non_loopback_host(tmp_path): ...
def test_load_instance_rejects_wrong_transport(tmp_path): ...
def test_load_instance_returns_valid_endpoint(tmp_path): ...
```

For Windows PID liveness use `ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, ...)`; do not add `psutil` solely for this check. Tests may use the current pytest PID as the live process.

- [ ] **Step 3: Run both suites and verify RED**

Run on Windows:

```powershell
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj --filter DiscoveryPublisherTests
pytest -q tests/integration/test_autocad_discovery.py
```

Expected: FAIL because publisher/reader are absent.

- [ ] **Step 4: Implement atomic current-user discovery publication**

Write JSON to `<instance_id>.json.<random>.tmp` in the same directory, flush/close, apply current-user ACL, then atomically replace/rename to `<instance_id>.json`. Production records must contain:

```json
{
  "instance_id": "...",
  "pid": 12345,
  "host": "127.0.0.1",
  "port": 53182,
  "transport": "grpc-h2c",
  "contract_version": "1.0",
  "auth_token": "..."
}
```

- [ ] **Step 5: Implement Python record validation**

Reject records with missing fields, dead PID, host other than `127.0.0.1`, port outside `1..65535`, transport other than `grpc-h2c`, empty token, or mismatched `instance_id`.

- [ ] **Step 6: Run both suites GREEN**

Run the two commands from Step 3. Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add hosts/autocad/transport hosts/autocad/sidecar/src/autocad_sidecar/ipc/discovery.py tests/integration/test_autocad_discovery.py
git commit -m "feat(transport): publish and validate host discovery records"
```

---

### Task 5: Add the Python transport abstraction, gRPC transport, timeout calculation, and selector

**Files:**
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/base.py`
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/grpc_transport.py`
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/transport_selector.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/transport.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/host_adapter.py`
- Create: `tests/integration/test_transport_selector.py`
- Create: `tests/integration/test_host_adapter_transport.py`

**Interfaces:**

```python
class FrameTransport(Protocol):
    async def open(self) -> None: ...
    async def exchange(self, payload: bytes, *, timeout_s: float | None = None) -> bytes: ...
    async def close(self) -> None: ...
```

- `GrpcTransport(instance_id, discovery_dir=None, max_timeout_s=30.0)` implements `FrameTransport`.
- `build_transport(kind, *, instance_id=None, pipe_name=None, discovery_dir=None) -> FrameTransport` accepts only `grpc` or `pipe`.
- `HostAdapter` accepts a `FrameTransport` instance; it no longer imports `PipeClient` directly.

- [ ] **Step 1: Write failing abstraction/selector tests**

```python
def test_selector_builds_pipe_transport(): ...
def test_selector_requires_instance_id_for_grpc(): ...
def test_selector_rejects_unknown_kind(): ...

@pytest.mark.asyncio
async def test_host_adapter_uses_injected_transport_without_knowing_pipe(): ...
```

Use a fake transport that records the outgoing bytes and returns a valid `ResponseEnvelope` JSON.

- [ ] **Step 2: Write failing gRPC unit tests with a fake generated stub**

Test that `GrpcTransport`:

- loads the endpoint from discovery;
- creates `grpc.aio.insecure_channel("127.0.0.1:<port>")`;
- sends `authorization: Bearer <token>` on Ping and Dispatch;
- performs `Ping(instance_id)` during `open()` and rejects identity mismatch;
- passes `timeout_s` into `stub.Dispatch(..., timeout=timeout_s)`;
- returns `response.contract_json` bytes unchanged.

- [ ] **Step 3: Run tests and verify RED**

Run:

```bash
pytest -q tests/integration/test_transport_selector.py tests/integration/test_host_adapter_transport.py
```

Expected: FAIL because the abstraction and gRPC transport do not exist.

- [ ] **Step 4: Implement `FrameTransport` and adapt Named Pipe without deleting it**

`PipeTransport.exchange(..., timeout_s=None)` keeps existing framing; when timeout is not `None`, wrap the blocking exchange future with `asyncio.wait_for`. Do not change the 4-byte wire in this migration task.

- [ ] **Step 5: Implement deadline-to-timeout calculation in `HostAdapter`**

For each outgoing envelope:

```python
remaining = None
if envelope.deadline_at is not None:
    remaining = max(0.0, parse_utc(envelope.deadline_at) - utc_now())

timeout_s = min_non_none(remaining, transport_max_timeout_s)
```

If remaining time is `<= 0`, fail before sending. Keep this as transport/deadline behavior; do not synthesize a DSP business error.

- [ ] **Step 6: Implement `GrpcTransport` and selector**

Use `grpc.aio.insecure_channel`; attach bearer metadata on every RPC. `open()` must Ping and close the channel if Ping fails or instance identity mismatches. `close()` must be idempotent.

- [ ] **Step 7: Run tests GREEN plus existing sidecar/contract tests**

Run:

```bash
pytest -q tests/integration/test_transport_selector.py tests/integration/test_host_adapter_transport.py
pytest -q contracts/python/tests tests/contracts
```

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add hosts/autocad/sidecar tests/integration
git commit -m "feat(sidecar): add transport-neutral gRPC client"
```

---

### Task 6: Build the cross-language conformance host and implement TC-RPC01 through TC-RPC07

**Files:**
- Create: `tests/transport/dotnet/ContractTransportTestHost/ContractTransportTestHost.csproj`
- Create: `tests/transport/dotnet/ContractTransportTestHost/Program.cs`
- Create: `tests/transport/dotnet/ContractTransportTestHost/FakeDispatchTarget.cs`
- Create: `tests/transport/test_grpc_transport_conformance.py`
- Create: `.github/workflows/grpc-transport-conformance.yml`

**Interfaces:**
- Test host command line:

```text
--instance-id <id>
--token <token>
--discovery-dir <path>
--mode normal|block
--counter-file <path>
```

- On successful start, the host prints exactly one readiness JSON line to stdout containing `instance_id`, `port`, and `pid`; subsequent logs go to stderr.
- `normal` fake target parses only enough JSON to echo `request_id` into a valid DSP `ResponseEnvelope`; malformed DSP JSON returns a valid DSP error response with gRPC status `OK`.
- `block` fake target waits on its cancellation token.

- [ ] **Step 1: Write all seven failing Python conformance tests**

```python
@pytest.mark.conformance
async def test_rpc01_python_to_csharp_ping(): ...

@pytest.mark.conformance
async def test_rpc02_python_to_csharp_dispatch_preserves_contract(): ...

@pytest.mark.conformance
async def test_rpc03_deadline_exceeded_is_grpc_status(): ...

@pytest.mark.conformance
async def test_rpc04_client_cancellation_reaches_csharp(): ...

@pytest.mark.conformance
async def test_rpc05_malformed_dsp_json_returns_dsp_error_over_grpc_ok(): ...

@pytest.mark.conformance
async def test_rpc06_missing_or_wrong_auth_never_invokes_dispatch(): ...

@pytest.mark.conformance
async def test_rpc07_two_instances_have_distinct_ports_tokens_and_identity(): ...
```

- [ ] **Step 2: Run and verify RED**

Run:

```bash
pytest -q tests/transport/test_grpc_transport_conformance.py
```

Expected: FAIL because the test host does not exist.

- [ ] **Step 3: Implement test host and fake target**

The host must reference the production transport project, not reimplement gRPC. It publishes a discovery record into the supplied temporary directory after listen. The fake target increments the counter file atomically on each invocation.

- [ ] **Step 4: Run TC-RPC01/02/05/06/07 GREEN**

Run:

```bash
pytest -q tests/transport/test_grpc_transport_conformance.py -k 'rpc01 or rpc02 or rpc05 or rpc06 or rpc07'
```

Expected: PASS.

- [ ] **Step 5: Run deadline/cancellation tests GREEN**

Run:

```bash
pytest -q tests/transport/test_grpc_transport_conformance.py -k 'rpc03 or rpc04'
```

Expected: PASS with Python receiving `grpc.StatusCode.DEADLINE_EXCEEDED` and `grpc.StatusCode.CANCELLED` respectively.

- [ ] **Step 6: Add Windows GitHub Actions workflow**

Workflow requirements:

```yaml
runs-on: windows-latest
```

Set up Python 3.11 and .NET 8, install `-e hosts/autocad/sidecar`, run the transport .NET tests, then run the Python conformance file. Do not require Autodesk binaries.

- [ ] **Step 7: Run the full local suite and push to trigger Actions**

Run:

```bash
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
pytest -q tests/transport/test_grpc_transport_conformance.py
```

Expected: all PASS locally. After push, verify the GitHub Actions job reaches conclusion `success` before claiming cross-language transport compatibility.

- [ ] **Step 8: Commit**

```bash
git add tests/transport .github/workflows/grpc-transport-conformance.yml
git commit -m "test(transport): verify Python C# gRPC conformance"
```

---

### Task 7: Bridge the existing AutoCAD `RequestDispatcher` into gRPC and run both transports during migration

**Files:**
- Create: `hosts/autocad/plugin/AutoCAD.AgentHost/Ipc/GrpcRequestDispatcherTarget.cs`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Bootstrap/PluginLifecycle.cs`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Bootstrap/PluginEntry.cs` only if lifecycle exception reporting is required by the existing entry point.

**Interfaces:**
- `GrpcRequestDispatcherTarget : IContractDispatchTarget` wraps the current synchronous `RequestDispatcher`.
- Cancellation is checked before calling `_dispatcher.Dispatch(contractJson)`; once synchronous dispatcher/native execution begins, cancellation is not used to tear through an in-progress AutoCAD mutation.
- Plugin lifecycle owns both `_pipeServer` and `_grpcServer` during migration.

- [ ] **Step 1: Add a failing compile-time bridge check in the transport-free CI surface**

Create `tests/contracts/test_plugin_grpc_wiring_source.py` that parses the two target source files and asserts only stable architectural facts:

```python
def test_plugin_lifecycle_wires_both_transports_during_migration():
    text = Path("hosts/autocad/plugin/AutoCAD.AgentHost/Bootstrap/PluginLifecycle.cs").read_text()
    assert "NamedPipeServer" in text
    assert "GrpcHostServer" in text
    assert "DiscoveryPublisher" in text
```

This source check is not a substitute for the real AutoCAD build; it is a regression guard that the migration remains dual-stack in source-controlled CI where Autodesk SDK binaries are unavailable.

- [ ] **Step 2: Run the source check and verify RED**

Run:

```bash
pytest -q tests/contracts/test_plugin_grpc_wiring_source.py
```

Expected: FAIL because `GrpcHostServer`/`DiscoveryPublisher` are not wired yet.

- [ ] **Step 3: Add the transport project reference and adapter**

`GrpcRequestDispatcherTarget.DispatchAsync`:

```csharp
public ValueTask<byte[]> DispatchAsync(byte[] contractJson, CancellationToken cancellationToken)
{
    cancellationToken.ThrowIfCancellationRequested();
    return ValueTask.FromResult(_dispatcher.Dispatch(contractJson));
}
```

Do not move dispatcher/business logic into the gRPC service.

- [ ] **Step 4: Update plugin lifecycle to start both transports**

Startup order:

1. create existing `RequestDispatcher`;
2. start existing `NamedPipeServer` unchanged;
3. generate `instance_id` and random 32-byte token;
4. start `GrpcHostServer` on loopback port `0`;
5. publish discovery only after the actual port is known/listening;
6. attach `ChangeSensor`.

Shutdown order:

1. detach sensor;
2. dispose discovery lease;
3. stop/dispose gRPC server;
4. stop Named Pipe server.

If gRPC startup fails during migration, log the failure and keep the already-started pipe fallback available; do not publish a broken discovery record.

- [ ] **Step 5: Run source guard GREEN and build on an Autodesk-enabled machine**

CI command:

```bash
pytest -q tests/contracts/test_plugin_grpc_wiring_source.py
```

Real build command on the AutoCAD developer machine:

```powershell
$env:AUTOCAD_ACAD_DIR='C:\Program Files\Autodesk\AutoCAD 2025\Acad'
dotnet build hosts/autocad/plugin/AutoCAD.AgentHost.sln -c Release
```

Expected: source guard PASS; real build exit code 0. Do not claim the plugin build passed unless the Autodesk-enabled build command was actually executed.

- [ ] **Step 6: Commit**

```bash
git add hosts/autocad/plugin tests/contracts/test_plugin_grpc_wiring_source.py
git commit -m "feat(autocad): bridge dispatcher to gRPC transport"
```

---

### Task 8: Wire Sidecar CLI and `HostAdapter` selection while keeping Named Pipe as default

**Files:**
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/main.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/host_adapter.py`
- Modify: `tools/host_test_client/main.py`
- Create: `tests/integration/test_sidecar_transport_cli.py`

**Interfaces:**
- CLI adds `--transport {pipe,grpc}`; default is `DSP_AUTOCAD_TRANSPORT` if set, otherwise `pipe`.
- CLI adds `--instance-id` for gRPC targeting.
- Existing `--pipe` remains for legacy fallback.
- `grpc` without `--instance-id` fails fast with a clear parser/configuration error.

- [ ] **Step 1: Write failing CLI tests**

```python
def test_default_transport_remains_pipe(monkeypatch): ...
def test_env_can_select_grpc(monkeypatch): ...
def test_grpc_requires_instance_id(): ...
def test_pipe_keeps_existing_pipe_name_option(): ...
```

- [ ] **Step 2: Run tests RED**

Run:

```bash
pytest -q tests/integration/test_sidecar_transport_cli.py
```

Expected: FAIL because the CLI has no transport selector.

- [ ] **Step 3: Implement explicit selection**

Construct the transport first with `build_transport`, then inject it into `HostAdapter`. Remove the hard-coded `PipeClient` construction path from `HostAdapter`; do not remove pipe implementation.

Change readiness output from a pipe-specific message to transport-neutral output, for example:

```text
sidecar ready (transport=grpc, instance_id=<id>)
```

or

```text
sidecar ready (transport=pipe, pipe=<name>)
```

- [ ] **Step 4: Update host test client arguments**

The test client must pass the same `transport/instance_id/pipe` choices into `HostAdapter` rather than talking directly to framing code.

- [ ] **Step 5: Run tests GREEN plus regression suites**

Run:

```bash
pytest -q tests/integration/test_sidecar_transport_cli.py
pytest -q contracts/python/tests tests/contracts tests/integration
```

Expected: PASS; pipe remains the default.

- [ ] **Step 6: Commit**

```bash
git add hosts/autocad/sidecar tools/host_test_client tests/integration/test_sidecar_transport_cli.py
git commit -m "feat(sidecar): select gRPC or pipe transport explicitly"
```

---

### Task 9: Add the real AutoCAD smoke gate and document evidence required before changing the default

**Files:**
- Create: `docs/runbooks/autocad-grpc-smoke.md`
- Modify: `README.md` only to link the runbook and mark gRPC as migration/opt-in; do not state it is the default.

**Interfaces:**
- Smoke run uses a concrete discovery `instance_id` and `--transport grpc`.
- The runbook records AutoCAD version, .NET runtime, instance id, port, and pass/fail evidence for each scenario.

- [ ] **Step 1: Write the runbook with exact commands**

The runbook must include this order:

1. build/load Plugin with the gRPC branch;
2. verify one discovery record appears only after Plugin startup;
3. run Sidecar status/Ping against that exact `instance_id`;
4. `CurrentDocument`;
5. `CurrentSelection`;
6. MOVE once and record `revision_before/revision_after`;
7. replay same idempotency key and verify no second mutation plus replay semantics;
8. run stale revision and verify DSP `REVISION_CONFLICT`, not a gRPC error;
9. run an expired/short deadline and record gRPC `DEADLINE_EXCEEDED` at a safe point;
10. launch two AutoCAD processes and verify distinct `instance_id`, port and token records;
11. use instance A token/record against B and verify authentication/identity failure;
12. unload/exit AutoCAD and verify discovery cleanup.

Include the exact sidecar invocation pattern:

```powershell
$env:DSP_AUTOCAD_TRANSPORT='grpc'
python -m autocad_sidecar.main --transport grpc --instance-id <INSTANCE_ID> status
```

and the corresponding `tools/host_test_client` commands already supported by that tool after Task 8.

- [ ] **Step 2: Add a default-switch gate section**

The runbook must state: `pipe` remains default until every smoke item passes on a supported AutoCAD installation and the evidence is attached to the review/PR. Any failed item blocks the default switch but does not require deleting the gRPC implementation.

- [ ] **Step 3: Update README without overstating completion**

README should describe:

```text
Current default: Named Pipe
Opt-in migration transport: gRPC loopback
Default switch gate: docs/runbooks/autocad-grpc-smoke.md
```

- [ ] **Step 4: Verify docs and full non-Autodesk CI**

Run:

```bash
pytest -q contracts/python/tests tests/contracts tests/integration tests/transport

dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

Expected: PASS. Separately confirm the GitHub Actions `grpc-transport-conformance` run concludes `success`.

- [ ] **Step 5: Commit**

```bash
git add docs/runbooks/autocad-grpc-smoke.md README.md
git commit -m "docs(transport): add AutoCAD gRPC rollout gate"
```

---

## Post-Plan Gate: Default Switch and Legacy Cleanup Are Separate Changes

Do **not** delete Named Pipe code in the implementation branch described above.

After the real AutoCAD smoke run has evidence for every item in Task 9, create a separate review for the default switch. That change should only change configuration/default selection and documentation; it should not simultaneously delete the rollback path.

After the gRPC default has operated successfully through the agreed validation window, create a second cleanup review that deletes:

- `hosts/autocad/plugin/AutoCAD.AgentHost/Ipc/NamedPipeServer.cs`;
- Python `PipeClient`/4-byte framing implementation;
- malformed-frame/partial-read tests that exist only for the legacy transport;
- pipe-only `pywin32` dependency;
- active ADR-002 transport status, marking it historical/superseded by ADR-004.

That cleanup requires its own design/approval because it removes the rollback mechanism.

---

## Plan Self-Review Checklist

Before execution begins, verify:

- Every acceptance criterion in the spec maps to a task above.
- No task changes HostContract business DTOs or JSON wire shape.
- No protobuf business messages were introduced.
- Auth executes before dispatch and has a zero-invocation test.
- Dynamic port and two-instance isolation have automated coverage.
- DSP business errors remain JSON response bytes with gRPC status `OK`.
- Deadline/cancellation have both .NET-level and Python↔C# coverage.
- The transport project has a Native/Autodesk leak gate.
- Plugin wiring remains dual-stack and pipe remains default.
- Real AutoCAD evidence is required before any default switch claim.
- Named Pipe cleanup is explicitly outside this plan.
