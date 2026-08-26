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
                │ Named Pipe (ADR-002)
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

## 核心文档

| 文档 | 说明 |
| --- | --- |
| [docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.5.md](docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.5.md) | 系统规格 v0.5 |
| [docs/adr/ADR-001-host-contract-boundary.md](docs/adr/ADR-001-host-contract-boundary.md) | 宿主契约边界 |
| [docs/adr/ADR-002-named-pipe-ipc.md](docs/adr/ADR-002-named-pipe-ipc.md) | 命名管道 IPC |
| [docs/adr/ADR-003-idempotency.md](docs/adr/ADR-003-idempotency.md) | 幂等性设计 |

## 快速开始

```bash
# 1. 安装 Python 契约包（开发模式）
pip install -e contracts/python

# 2. 运行契约测试
pytest tests/contracts

# 3. 运行测试客户端（需 sidecar 已连接插件）
python tools/host_test_client/main.py --help
```

## 里程碑

- **M1（当前）**：contracts/ 定稿 + sidecar 骨架 + host_test_client。
- **M2**：AutoCAD 插件命令闭环（selection / move / fit）+ 幂等与版本校验。
- **M3**：platform/ 第二阶段：semantic_runtime、changeset、capability、orchestrator。
