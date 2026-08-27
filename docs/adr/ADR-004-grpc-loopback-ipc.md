# ADR-004: gRPC over loopback for AutoCAD IPC

- 状态：Proposed
- 日期：2026-08-27
- 关联：ADR-001、ADR-002、ADR-003；`contracts/`、`hosts/autocad/plugin/`、`hosts/autocad/sidecar/`

## 背景（Context）

当前 AutoCAD Plugin 与 Python Sidecar 通过 Windows Named Pipe 通信。ADR-002 规定的帧格式为“4 字节小端长度前缀 + UTF-8 JSON”，因此仓库已经在两端维护自定义 framing、partial read、长度校验、连接生命周期和请求/响应交换逻辑。

HostContract 才是 DSP 的稳定业务边界：`RequestEnvelope`、`HostCommand`、`HostCommandResult`、`HostDelta`、`ErrorShape`、revision、idempotency 等语义不应绑定到某个 IPC transport。现有 `contracts/` 的 JSON Schema + Python + .NET 镜像、golden vectors 与 cross-language compatibility tests 已经形成独立的协议保障。

目标是在不同时重写 HostContract 的前提下，用成熟 RPC transport 替换自研 framing，并保留未来进一步迁移到 protobuf-native business contracts 的选择权。

## 决策（Decision）

### 1. 第一阶段只替换 transport/RPC，不替换 HostContract

新增 gRPC transport IDL；protobuf 只描述 RPC transport envelope，不成为 DSP 业务 Contract 的单一事实来源。

第一阶段的 transport proto 只需要：

```proto
syntax = "proto3";
package dsp.host.transport.v1;

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

`contract_json` 是现有 DSP Contract 的 UTF-8 JSON wire bytes。`RequestEnvelope`/`ResponseEnvelope` 及其业务语义保持现状。

### 2. 使用 gRPC over HTTP/2 loopback，不使用 Python gRPC over Windows Named Pipe

AutoCAD Plugin 内启动一个仅监听 `127.0.0.1` 的 gRPC server，并使用动态端口。Python Sidecar 使用标准 `grpcio` client 连接该 loopback endpoint。

第一阶段不实现 Python gRPC over Windows Named Pipe，也不实现自定义 gRPC transport adapter。

### 3. 动态端口与多实例发现

每个 AutoCAD 进程监听独立的动态端口，并发布 current-user discovery record：

```text
%LOCALAPPDATA%/EnterpriseDesignAgent/hosts/<instance_id>.json
```

记录至少包含：

```json
{
  "instance_id": "<guid>",
  "pid": 12345,
  "host": "127.0.0.1",
  "port": 53182,
  "transport": "grpc-h2c",
  "contract_version": "1.0",
  "auth_token": "<random-256-bit-token>"
}
```

Discovery file 必须以原子方式写入，并限制为当前 Windows 用户可读写。Plugin 正常停止时删除记录；Sidecar 遇到 PID 不存在、连接失败或 Ping 身份不匹配时将记录视为 stale。

### 4. Loopback transport 必须鉴权

仅绑定 loopback 不能代替鉴权。Plugin 启动时为每个 AutoCAD instance 生成随机 256-bit token。Sidecar 从受 current-user ACL 保护的 discovery record 获取 token，并在每次 RPC metadata 中发送：

```text
authorization: Bearer <token>
```

缺失或错误 token 返回 gRPC `UNAUTHENTICATED`，且请求不得进入 `RequestDispatcher`。

第一阶段不引入 TLS；安全边界是 loopback-only bind + current-user discovery ACL + per-instance random token。此设计不防御同一 Windows 用户上下文下的恶意进程，目标是保持与原 Named Pipe current-user 边界相近的威胁模型。

### 5. gRPC 与 DSP 业务错误模型严格分层

以下错误使用 gRPC status：

- 无法连接 / server 不可用：`UNAVAILABLE`
- token 缺失或错误：`UNAUTHENTICATED`
- RPC deadline 到期：`DEADLINE_EXCEEDED`
- client cancellation：`CANCELLED`
- transport request 本身缺少 `contract_json`：`INVALID_ARGUMENT`

以下错误仍通过现有 `ResponseEnvelope` / `ErrorShape` 返回，gRPC status 保持 `OK`：

- malformed/unsupported DSP Contract JSON
- Contract validation failure
- unsupported operation
- revision conflict
- idempotency/business execution error
- AutoCAD command failure

因此不会形成第二套业务错误协议。

### 6. deadline 与 cancellation

Sidecar 根据 `RequestEnvelope.deadline_at` 计算 gRPC timeout；若另有 transport 默认 timeout，则使用两者中的更早者。Plugin service 使用 `ServerCallContext.CancellationToken` 在进入 dispatcher 前进行 cooperative cancellation 检查。

AutoCAD mutation 一旦进入必须保持原子性的 native execution 区段，不允许为了响应 transport cancellation 而中断到半写状态。Cancellation 只在安全点生效；业务层的 deadline/revision/idempotency 规则继续作为最终一致性保护。

### 7. Plugin 保持薄边界

Plugin 中的调用链保持：

```text
GrpcHostServer / AutoCadHostService
        -> RequestDispatcher
        -> HostCommandHandler
        -> Native/
        -> Autodesk API
```

gRPC 层不得引入 Semantic Runtime、LangGraph、数据库、Provider Registry 或其他平台业务组件。Transport 层不得暴露 `Autodesk.*` 类型。

### 8. 迁移期间双栈，稳定后删除 Named Pipe framing

迁移不是一次性删除旧链路：

1. 新增 gRPC transport 与 conformance tests。
2. Sidecar 增加 transport selector，迁移期允许 `grpc` / `pipe`。
3. 完成真实 AutoCAD smoke test 后将默认切换到 `grpc`。
4. 在单独 cleanup change 中删除 `NamedPipeServer.cs`、Python pipe framing、4-byte length/partial-read 专属测试和 `pywin32` pipe dependency。

在 cleanup 完成前，ADR-002 描述的是 legacy fallback；cleanup 完成后，本 ADR supersede ADR-002 的 transport/framing 决策。ADR-001 HostContract boundary 与 ADR-003 idempotency 不受影响。

## 结果（Consequences）

### 正面

- 删除 DSP 自研 framing、partial-read、response correlation transport 维护成本。
- Python 与 C# 都使用成熟 gRPC runtime。
- deadline、cancellation、status、stream evolution 与 code generation 有统一基础。
- 多 AutoCAD instance 通过动态端口和 discovery record 隔离。
- HostContract 业务语义、现有 JSON Schema 和 compatibility tests 不需要同步重写。
- 未来可以独立评估 protobuf-native HostContract，而不影响本次 transport 迁移。

### 代价

- Plugin 增加 ASP.NET Core/gRPC runtime 依赖；Sidecar 增加 `grpcio`/protobuf runtime 依赖。
- 需要管理动态 endpoint discovery 和 stale record 清理。
- loopback 安全从 Named Pipe ACL 转为 loopback bind + discovery ACL + bearer token。
- 迁移窗口内暂时维护 gRPC/Named Pipe 双栈。

## 不在本 ADR 范围内（Non-goals）

- 不把现有 `RequestEnvelope`/`HostCommand`/`HostDelta` 改为 protobuf generated business DTO。
- 不实现 gRPC over Windows Named Pipe for Python。
- 不增加跨机器 RPC。
- 不把 AutoCAD Plugin 变成通用 ASP.NET 应用或平台服务。
- 不改变 revision、idempotency、HostError、Contract version 的业务语义。
