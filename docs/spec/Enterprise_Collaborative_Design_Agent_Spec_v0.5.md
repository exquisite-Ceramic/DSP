# Enterprise Collaborative Design Agent — Specification v0.5

> 状态：Draft（v0.5）
> 范围：宿主契约（Host Contract）、AutoCAD 插件 + Sidecar 通信、命令生命周期、幂等与版本、变更捕获、验证、一致性测试。

## 1. 目的与范围

本规格定义企业级协同设计智能体（Agent）与设计宿主（Host，如 AutoCAD）协作的**契约边界**与**运行时行为**。目标是让 Agent 能以可验证、可回放、幂等的方式对宿主内的设计文档执行命令（读上下文、移动实体、视图缩放等）并接收变更。

范围外：宿主内部的 UI 定制、批处理脚本、多宿主抽象（v0.5 仅覆盖 AutoCAD）。

## 2. 术语

| 术语 | 含义 |
| --- | --- |
| Host | 承载设计文档的进程（如 AutoCAD）。 |
| Plugin | 宿主进程内的 .NET 组件，负责执行命令与感知变更。 |
| Sidecar | 宿主外的 Python 进程，负责编排、重试、幂等与健康检查。 |
| HostContract | 双方交换消息的唯一契约（`contracts/`）。 |
| Envelope | 管道上所有消息的统一外层包装。 |
| EntityRef | 图元在文档内的稳定引用（handle + 上下文）。 |
| Revision | 文档级版本号，用于并发防护（RevisionGuard）。 |
| IdempotencyKey | 命令去重键，保证重放安全。 |
| Delta | 一次变更的最小描述（before/after）。 |

## 3. 架构

```
Agent/Orchestrator ──▶ Sidecar (Python) ──[Named Pipe]──▶ Plugin (.NET) ──▶ AutoCAD
                           │                                      │
                     command_dispatcher                     Commands/* (handler)
                     retry / idempotency                    Execution/* (lock, txn, guard)
                     health / host_status                   ChangeCapture/* (sensor → delta)
```

- Plugin 只通过 `Native/` 触碰 `Autodesk.*`；其余代码仅依赖 `HostContracts` 与 BCL。
- Sidecar 是 Agent 的唯一入口；Agent 永不直接连接管道。

## 4. 宿主契约（Host Contract）

契约单一事实来源：`contracts/schemas/*.json`（JSON Schema），并提供 Python（`contracts/python`）与 .NET（`contracts/dotnet`）镜像实现。任何一处修改必须三处同步，并通过 `tests/conformance/host_contract_v1` 校验。

消息类型（Envelope.messageType）：

| 类型 | 方向 | 说明 |
| --- | --- | --- |
| `command` | Sidecar → Plugin | 宿主命令（读/写）。 |
| `result` | Plugin → Sidecar | 命令结果。 |
| `delta` | Plugin → Sidecar | 异步变更推送。 |
| `error` | 双向 | 错误（含重试标记）。 |
| `status` | 双向 | 健康/状态心跳。 |

## 5. IPC（命名管道）

见 [ADR-002](docs/adr/ADR-002-named-pipe-ipc.md)。

- 管道名：`EnterpriseDesignAgent.<HostId>`（HostId 默认取机器名+进程号）。
- 帧格式：长度前缀（4 字节 LE）+ UTF-8 JSON（Envelope）。
- Plugin 为服务端，Sidecar 为客户端；重连退避由 Sidecar 负责。

## 6. 命令生命周期

1. Sidecar 生成 `HostCommand`（含 `commandId`、`idempotencyKey`、`revision`、`params`），包进 Envelope 发送。
2. Plugin `RequestDispatcher` 反序列化 → `IdempotencyStore` 去重 → `RevisionGuard` 校验 → `DocumentLockManager` 加锁 → `TransactionRunner` 执行对应 Handler → 返回 `HostCommandResult`。
3. 变更被 `ChangeSensor` 捕获，`HostDeltaBuilder` 生成 `HostDelta` 列表，经 `EventQueue` 异步推送。
4. Sidecar 收到 result/delta 后更新本地视图，并向 Agent 回传。

## 7. 幂等与版本

- 每条写命令必须携带 `idempotencyKey`；插件在 `IdempotencyStore` 中按 (documentId, key) 记录已执行命令及其结果，重放时直接返回缓存结果（见 [ADR-003](docs/adr/ADR-003-idempotency.md)）。
- 写命令携带 `revision`（读取时的文档版本）；`RevisionGuard` 在事务提交前比对当前版本，不一致返回 `revision_conflict` 错误。

## 8. 变更捕获（Change Capture）

- `ChangeSensor` 订阅文档事件（添加/修改/擦除/对象修改）。
- 同一事务内的多个事件合并为一个 `HostDelta` 列表，避免中间态泄漏。
- Delta 仅在事务提交后推送，且携带提交后的 revision。

## 9. 验证（Verification）

- 写命令执行后必须回读实体（`EntityReader`）并与期望结果比对（如 `MoveVerifier`）。
- 验证失败返回 `verification_failed` 错误，且计入 `result.verification` 字段供回放审计。

## 10. 错误模型

`HostError`：`code`（机器可读）、`message`、`details`、`retryable`。
常见 code：`revision_conflict`、`idempotency_replay`、`entity_not_found`、`document_locked`、`verification_failed`、`pipe_closed`。

## 11. 测试与一致性

- `tests/contracts/`：契约 Python 实现与 JSON Schema 的互操作。
- `tests/integration/`：真实宿主上的端到端（selection / move / 幂等 / 版本冲突）。
- `tests/conformance/host_contract_v1/`：固定样例（golden files）校验三份实现的字节级一致。
- `tools/host_test_client/`：手工与脚本化场景（move_once / move_retry / revision_conflict）。

## 12. 路线图（Phase 2：platform/）

- `semantic_runtime/`：identity、dirty_map、snapshot、journal。
- `changeset/`：变更集建模与执行切片。
- `capability/`：能力注册与 provider 解析。
- `gateway/`、`orchestrator/langgraph/`：多宿主编排。

## 13. 未决问题

- [ ] v0.5 是否将 `revision` 提升为文档级单调计数器（当前为插件内实现细节）。
- [ ] delta 推送的背压策略（EventQueue 满时是丢弃还是阻塞提交）。
- [ ] conformance 测试 golden 文件格式定稿。
