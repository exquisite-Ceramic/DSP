# gRPC Loopback Transport Design

## Goal

Replace the custom Python ↔ C# Named Pipe framing/RPC layer with gRPC over HTTP/2 loopback while keeping the existing DSP HostContract business model stable.

The first migration phase must remove transport-specific complexity without simultaneously redefining `RequestEnvelope`, `HostCommand`, `HostCommandResult`, `HostDelta`, `ErrorShape`, revision, idempotency, or contract-version semantics.

## Current State

The repository currently has two independent contract mirrors plus JSON Schema and shared golden vectors. Python and .NET compatibility tests already verify common wire semantics.

The AutoCAD transport currently consists of:

- C#: `hosts/autocad/plugin/AutoCAD.AgentHost/Ipc/NamedPipeServer.cs`
- C#: `hosts/autocad/plugin/AutoCAD.AgentHost/Ipc/ContractSerializer.cs`
- C#: `hosts/autocad/plugin/AutoCAD.AgentHost/Ipc/RequestDispatcher.cs`
- Python: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/transport.py`
- Python: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/pipe_client.py`
- Python: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/serializer.py`

The Named Pipe transport owns framing using a 4-byte little-endian length prefix plus UTF-8 JSON. That framing is transport machinery and should not remain DSP-specific code once gRPC is adopted.

## Architectural Boundary

The design separates three layers:

```text
DSP business contract
RequestEnvelope / HostCommand / HostDelta / ErrorShape / revision / idempotency
                         |
                         v
Existing UTF-8 JSON contract wire representation
                         |
                         v
gRPC transport envelope (protobuf bytes field)
                         |
                         v
HTTP/2 over 127.0.0.1:<dynamic-port>
```

The protobuf schema introduced by this migration is a transport IDL, not the business-contract source of truth.

This constraint is deliberate: transport migration and business-contract migration are separate architectural changes and must be reviewable independently.

## Transport IDL

Create `contracts/proto/host_transport_v1.proto` with a minimal RPC surface:

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

`Ping` establishes endpoint identity and exposes the current DSP contract version. `Dispatch` transports one existing DSP request-envelope JSON document and returns one existing DSP response-envelope JSON document.

No HostCommand fields are duplicated in protobuf in phase 1.

## .NET Component Design

### Transport assembly

Introduce a transport-focused .NET project that can build and test without Autodesk assemblies. It should depend on HostContracts and gRPC/ASP.NET Core only.

Suggested location:

```text
hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/
```

Responsibilities:

- host Kestrel on IPv4 loopback only;
- request an OS-assigned dynamic port;
- expose `Ping` and `Dispatch`;
- authenticate bearer metadata before dispatch;
- enforce transport input preconditions;
- translate gRPC deadline/cancellation into a `CancellationToken`;
- call a transport-neutral dispatch target supplied by the AutoCAD plugin;
- never reference `Autodesk.*`.

A small interface keeps this project testable without AutoCAD:

```csharp
public interface IContractDispatchTarget
{
    ValueTask<byte[]> DispatchAsync(byte[] contractJson, CancellationToken cancellationToken);
}
```

The existing plugin provides an adapter around `RequestDispatcher`. The adapter is the only bridge between gRPC transport and the current synchronous dispatcher.

### Plugin wiring

The AutoCAD plugin remains responsible for lifecycle and native execution. Bootstrap should:

1. construct the existing `RequestDispatcher`;
2. wrap it in `IContractDispatchTarget`;
3. create a per-instance identity/token;
4. start the gRPC host asynchronously;
5. publish the discovery record only after the server is listening;
6. remove the discovery record and stop the server during plugin shutdown.

The gRPC service must not access Autodesk APIs directly. All native access remains downstream of the existing dispatcher/handler/native boundaries.

## Python Component Design

Keep the sidecar API transport-neutral and add gRPC alongside the existing pipe fallback during migration.

Suggested files:

```text
hosts/autocad/sidecar/src/autocad_sidecar/ipc/discovery.py
hosts/autocad/sidecar/src/autocad_sidecar/ipc/grpc_transport.py
hosts/autocad/sidecar/src/autocad_sidecar/ipc/transport_selector.py
```

Generated Python protobuf/grpc modules should live in a dedicated generated package and must never be generated at runtime in production. Code generation occurs in development/CI and generated files are packaged with the sidecar.

`GrpcTransport.exchange(payload: bytes) -> bytes` preserves the current higher-level exchange shape so sidecar orchestration code does not need to understand protobuf.

During migration:

```text
DSP_AUTOCAD_TRANSPORT=grpc|pipe
```

is the explicit selector. `grpc` becomes the default only after real AutoCAD smoke validation. `pipe` exists only as rollback support and is removed in the later cleanup change.

## Endpoint Discovery

### Record format

Each plugin instance publishes:

```text
%LOCALAPPDATA%/EnterpriseDesignAgent/hosts/<instance_id>.json
```

with:

```json
{
  "instance_id": "7d5027fd-56c3-4bf5-b370-c1aee8f70393",
  "pid": 12345,
  "host": "127.0.0.1",
  "port": 53182,
  "transport": "grpc-h2c",
  "contract_version": "1.0",
  "auth_token": "<base64url-encoded-256-bit-random-token>"
}
```

### Write and cleanup rules

- write to a temporary file in the same directory and atomically rename/replace it;
- apply a current-user-only Windows ACL to the directory/record;
- publish only after the server is listening;
- delete on graceful shutdown;
- Sidecar rejects records whose PID is no longer alive;
- Sidecar performs `Ping(instance_id)` after connecting and rejects identity mismatch;
- failed Ping/connection marks a record stale for that discovery pass.

The Sidecar must not trust a record solely because the filename exists.

## Security Model

The gRPC server binds only to `127.0.0.1`, never `0.0.0.0`, IPv6-any, or a LAN interface in phase 1.

A random 256-bit token is generated independently for every AutoCAD process. The Sidecar sends:

```text
authorization: Bearer <token>
```

on every RPC.

Authentication runs before service dispatch. Missing or invalid tokens return `UNAUTHENTICATED` and cannot reach `RequestDispatcher`.

No TLS is introduced in phase 1 because traffic never leaves loopback and endpoint possession is additionally gated by a current-user discovery record and per-instance token. The threat model is cross-user isolation and accidental local access; a malicious process already running as the same Windows user is outside this phase's protection target.

## Error Semantics

Transport and DSP errors must not be mixed.

### gRPC status errors

- `UNAVAILABLE`: endpoint cannot be reached/server unavailable;
- `UNAUTHENTICATED`: token missing or invalid;
- `DEADLINE_EXCEEDED`: gRPC call deadline expires;
- `CANCELLED`: client cancels the RPC;
- `INVALID_ARGUMENT`: the protobuf request is structurally valid but `contract_json` is empty.

### DSP business errors

Malformed JSON, contract validation failure, unsupported operation, revision conflict, idempotency failures, AutoCAD execution failures, and other DSP application errors remain represented by the existing response envelope/error shape. For these cases the gRPC call completes with status `OK` and carries the DSP error JSON in `DispatchResponse.contract_json`.

This preserves one business error model.

## Deadline and Cancellation Semantics

`RequestEnvelope.deadline_at` remains the authoritative DSP business deadline.

Before invoking gRPC, Sidecar calculates the remaining time until `deadline_at`. The RPC timeout is the earlier of:

- remaining DSP deadline;
- configured transport maximum timeout.

If no business deadline exists, only the configured transport maximum applies.

On the server, cancellation is cooperative. The service checks cancellation before entering the dispatcher and passes the token through the transport interface. Native AutoCAD mutations must not be interrupted in a way that leaves a half-applied document change. Once a handler crosses an atomic native mutation boundary, cancellation is honored only at the next safe point.

Revision guards, idempotency, and business validation remain responsible for application consistency.

## Multi-instance Behavior

Every AutoCAD process has:

- a unique `instance_id`;
- a unique dynamic port;
- a unique auth token;
- a separate discovery record.

The Sidecar must select a concrete instance before creating a channel. No fixed shared port is permitted.

The minimum phase-1 requirement is deterministic instance targeting by `instance_id`. Automatic “pick the active AutoCAD window” heuristics are outside scope.

## Migration Sequence

### Phase 1A — transport infrastructure

Add transport proto, generated stubs, testable .NET gRPC host, Python gRPC transport, discovery/auth primitives, and non-AutoCAD CI tests. Named Pipe remains available.

### Phase 1B — plugin/sidecar wiring

Wire the plugin bootstrap to the gRPC host and wire sidecar transport selection. Existing `RequestDispatcher` and business handlers remain unchanged except for a small adapter boundary.

### Phase 1C — validation and default switch

Run:

- cross-language RPC CI;
- plugin startup/Ping smoke test in real AutoCAD;
- CurrentDocument;
- CurrentSelection;
- MOVE + idempotency;
- revision-conflict path;
- deadline/cancellation behavior;
- two simultaneous AutoCAD processes.

Only after these pass does `grpc` become the default.

### Phase 1D — legacy cleanup

In a separate reviewable change, remove:

- `NamedPipeServer.cs`;
- Python pipe client/framing implementation;
- 4-byte length/partial-read/malformed-frame tests that exist only for the custom transport;
- `pywin32` pipe-only dependency;
- ADR-002 as an active transport decision (retain it as historical/superseded documentation).

Do not mix cleanup with initial gRPC enablement.

## Test Strategy

The migration adds transport tests without weakening existing contract tests.

### Existing tests retained

- Python HostContract unit tests;
- .NET HostContract unit tests;
- JSON Schema conformance;
- shared golden vectors;
- dynamic Python ↔ C# contract compatibility;
- Native type leak checks.

### New transport acceptance tests

#### TC-RPC01 — Python → C# Ping

Start the .NET gRPC transport host with a fake dispatch target, connect with the Python client, authenticate, and assert instance/contract-version identity.

#### TC-RPC02 — Python → C# Dispatch

Python serializes an existing `RequestEnvelope` JSON, sends it through gRPC, fake C# dispatch returns an existing `ResponseEnvelope` JSON, and Python consumes the response unchanged.

#### TC-RPC03 — deadline exceeded

A fake C# dispatch target blocks beyond the client deadline. Python receives `DEADLINE_EXCEEDED`; the request is not reported as a DSP business error.

#### TC-RPC04 — cancellation

Python starts a Dispatch call and cancels it. C# receives cancellation before entering or at a safe point in the fake dispatch target and Python receives `CANCELLED`.

#### TC-RPC05 — malformed DSP contract remains structured DSP error

Send nonconforming/malformed contract JSON through a dispatch target that uses the DSP dispatcher semantics. gRPC completes successfully and response bytes decode to the existing DSP error envelope.

#### TC-RPC06 — auth enforcement

Missing and incorrect bearer tokens return `UNAUTHENTICATED`; the fake dispatch target records zero invocations.

#### TC-RPC07 — multi-instance isolation

Start two transport hosts with dynamic ports/tokens. Assert different ports/tokens, successful matching Ping for each instance, and failure when instance A's token is used against instance B.

### Native AutoCAD smoke tests

CI without Autodesk binaries proves the transport and contract boundaries. Real AutoCAD smoke tests remain required before the default switch because CI cannot prove plugin lifecycle, AutoCAD document threading, or native mutation behavior.

## Dependency Rules

- .NET transport targets `net8.0-windows` compatibility with the current plugin baseline.
- The transport assembly may depend on ASP.NET Core/gRPC/protobuf but not Autodesk assemblies.
- Python sidecar runtime adds gRPC/protobuf runtime dependencies; code generation tooling is development/build-only.
- No runtime protoc invocation.
- Generated transport code is versioned/packaged so deployed Python/C# peers use the same transport IDL revision.

## Rollback

During migration, switching `DSP_AUTOCAD_TRANSPORT=pipe` restores the legacy transport without changing DSP contracts or orchestration semantics.

The Named Pipe implementation is deleted only after the real-host validation gate passes and gRPC becomes the default. If a blocker is found before cleanup, the gRPC branch can be reverted without touching the contract model.

## Non-goals

- protobuf-native `HostCommand`/`HostDelta` business DTOs;
- Python gRPC over Windows Named Pipe;
- remote-machine connectivity;
- TLS/mTLS in phase 1;
- automatic active-window AutoCAD discovery;
- changes to revision/idempotency semantics;
- moving orchestration/platform responsibilities into the plugin.

## Acceptance Criteria

The design is ready for implementation when all of the following are true:

1. existing HostContract wire JSON remains unchanged;
2. protobuf is explicitly transport-only in phase 1;
3. gRPC server is loopback-only and dynamically ported;
4. each instance uses a current-user discovery record plus unique bearer token;
5. transport errors and DSP business errors remain separate;
6. Python and C# can execute Ping and Dispatch in CI without Autodesk binaries;
7. Named Pipe remains a temporary rollback path until real AutoCAD smoke validation;
8. legacy framing is removed only in a later cleanup change.
