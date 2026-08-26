# ADR-002: Named Pipe IPC

- 状态：Accepted
- 日期：2025-01
- 关联：spec §5；`hosts/autocad/plugin/Ipc/`、`hosts/autocad/sidecar/src/autocad_sidecar/ipc/`

## 背景（Context）

Sidecar（Python 进程）需要与 AutoCAD 进程内的 .NET 插件双向通信：命令下行、结果/变更上行。候选方案：命名管道、TCP/HTTP（localhost）、gRPC、共享内存、文件轮询。

约束：AutoCAD 内插件生命周期与文档事件紧密耦合，服务端必须在插件内；Sidecar 应尽可能零依赖（Windows 上纯 Python 即可用 `pywin32` 或原生管道）。

## 决策（Decision）

1. 使用 **Windows Named Pipe**：插件为服务端（`NamedPipeServer`），Sidecar 为客户端（`pipe_client`）。
2. 管道名：`\\.\pipe\EnterpriseDesignAgent.<HostId>`，HostId 默认 `{machineName}-{processId}`，可在插件启动参数中覆盖。
3. 帧格式：**4 字节小端长度前缀 + UTF-8 JSON（Envelope）**；单帧上限 1 MiB（超限返回 `payload_too_large` 错误）。
4. 可靠性：Sidecar 负责断线重连（指数退避，上限 30 s）；插件每次仅处理一个请求，`RequestDispatcher` 串行化写命令，保证 AutoCAD 文档线程安全。
5. 安全：管道 ACL 仅允许当前用户（默认行为）；不接受跨用户连接。

## 后果（Consequences）

- 正面：零网络配置、低延迟、无需额外依赖（.NET 内置、Python 侧 `win32pipe` 可选，纯 .NET 端已实现）；权限天然按用户隔离。
- 代价：仅限 Windows；进程外调试不便；1 MiB 帧上限需在契约层约定分页/分片策略（v0.5 暂不实现）。
- 迁移路径：若未来需要跨机器，可在 Sidecar 层抽象 `transport` 接口，替换为 TCP/gRPC 而不改契约。

## 备选方案

- TCP localhost：放弃（端口冲突、防火墙提示、多实例管理成本）。
- gRPC：暂缓（依赖、代码生成，见 ADR-001）。
- 共享内存：放弃（生命周期与同步复杂度高）。
