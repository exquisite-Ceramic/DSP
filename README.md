# Enterprise Collaborative Design Agent

企业级协同设计智能体：以 **宿主（Host）** 为核心，让 AI Agent 通过一份**契约（Contract）** 与 AutoCAD 等设计工具安全、可验证地协作。

## 架构总览

```
┌─────────────────────────────────────────────────────────────┐
│  Agent / Orchestrator (platform/)                            │
│   semantic_runtime · changeset · capability · gateway        │
└───────────────┬─────────────────────────────────────────────┘
                │  HostContract (contracts/)  ← 第一优先级
┌───────────────▼─────────────────────────────────────────────┐
│  Sidecar (hosts/<host>/sidecar/)  —— Python 进程（AutoCAD 外）│
│   ipc · adapter · execution · health                         │
└───────────────┬─────────────────────────────────────────────┘
                │ Dual stack during migration
                │ Named Pipe (default, ADR-002)
                │ gRPC over 127.0.0.1 dynamic port (opt-in, ADR-004)
┌───────────────▼─────────────────────────────────────────────┐
│  Plugin (hosts/<host>/plugin/)   —— AutoCAD 进程内 (.NET)    │
│   Bootstrap · Ipc · Commands · Execution · ChangeCapture     │
│   Verification · Native（唯一允许 Autodesk.* 的区域）          │
└─────────────────────────────────────────────────────────────┘
```

- **contracts/** —— 契约单一事实来源（JSON Schema + Python + .NET 三份镜像实现）。
- **hosts/autocad/plugin/** —— AutoCAD 进程内的 .NET 插件，只通过 `Native/` 触碰 `Autodesk.*`。
- **hosts/autocad/sidecar/** —— AutoCAD 外部的 Python 侧车进程，负责命令编排、重试、幂等与健康检查。
- **platform/** —— 第二阶段逐步填充：语义运行时、变更集、能力注册、网关、编排器。
- **tools/host_test_client/** —— 手工 / 脚本化测试客户端（⭐ 非常重要）。
- **tests/** —— 契约单测、sidecar 测试、集成测试、一致性测试（conformance）。

## Transport migration status

Current default transport: Named Pipe
Opt-in migration transport: gRPC over loopback
Default-switch gate: docs/runbooks/autocad-grpc-smoke.md

ADR-004 introduces an authenticated gRPC/HTTP2 loopback transport on `127.0.0.1` with a dynamic
port and per-AutoCAD-instance discovery record. The existing DSP HostContract JSON wire remains
unchanged, and Named Pipe stays available as the default/fallback during the migration.

The default must not switch to gRPC until every real-host gate in
[`docs/runbooks/autocad-grpc-smoke.md`](docs/runbooks/autocad-grpc-smoke.md) passes on a supported
AutoCAD installation. Switching the default and later deleting Named Pipe are separate reviews.

## 核心文档

| 文档 | 说明 |
| --- | --- |
| [docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.5.md](docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.5.md) | 系统规格 v0.5 |
| [docs/adr/ADR-001-host-contract-boundary.md](docs/adr/ADR-001-host-contract-boundary.md) | 宿主契约边界 |
| [docs/adr/ADR-002-named-pipe-ipc.md](docs/adr/ADR-002-named-pipe-ipc.md) | 命名管道 IPC（迁移期默认/回退） |
| [docs/adr/ADR-003-idempotency.md](docs/adr/ADR-003-idempotency.md) | 幂等性设计 |
| [docs/adr/ADR-004-grpc-loopback-ipc.md](docs/adr/ADR-004-grpc-loopback-ipc.md) | gRPC loopback 迁移方案 |
| [docs/runbooks/autocad-grpc-smoke.md](docs/runbooks/autocad-grpc-smoke.md) | AutoCAD gRPC 真实宿主 rollout gate |

## 快速开始

```bash
# 1. 安装 Python 契约包（开发模式）
pip install -e contracts/python

# 2. 运行契约测试
pytest tests/contracts

# 3. 运行测试客户端
python tools/host_test_client/main.py --help
```

Named Pipe remains the default. On Windows, the test client can auto-discover a single running
`EnterpriseDesignAgent.*` pipe when `--pipe` is omitted.

For opt-in gRPC testing, first obtain the live `instance_id` from
`%LOCALAPPDATA%\EnterpriseDesignAgent\hosts\<instance_id>.json`, then run for example:

```powershell
python tools/host_test_client/main.py `
    --transport grpc `
    --instance-id <instance-id> `
    document
```

See the rollout runbook for the AutoCAD 2025 ASP.NET Core runtime prerequisite and the complete
real-host gate.

## 里程碑

- **M1（当前）**：contracts/ 定稿 + sidecar 骨架 + host_test_client。
- **M2**：AutoCAD 插件命令闭环（selection / move / fit）+ 幂等与版本校验。
- **M3**：platform/ 第二阶段：semantic_runtime、changeset、capability、orchestrator。
