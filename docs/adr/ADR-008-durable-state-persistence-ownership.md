# ADR-008: Durable State / Persistence Ownership

- 状态：Accepted
- 日期：2026-09-16
- 关联：ADR-009、ADR-010；`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md` §3.1、§19–21、§25、§28、§31、§34、§43；`docs/superpowers/modernization/architecture-modernization-review-input.md`

## 背景（Context）

DSP v0.6 已经定义了多类需要长期保存、恢复、审计或重放的状态，但此前只冻结了**逻辑 owner 与 durability 语义**，没有冻结统一的物理持久化基线。

主 Spec 已明确以下核心事实；ADR-010 对 workflow ownership 的 framework 表述进一步做了规范化：

- Host Application 是 design-time native state 的实时事实源；D5 不是第二个 Host 主数据库，而是 task-scoped canonical projection。
- `SemanticProjection`、`Snapshot`、`DirtyMap` 由 D5 拥有。
- `ChangeSet` 由 ChangeSet Store 拥有。
- `ApprovalRecord` / `ExecutionGrant` 由 Gateway 拥有。
- `InteractionSession` 由 Interaction Coordinator 拥有。
- workflow checkpoint 由逻辑 `Workflow Orchestrator` 拥有，并要求 recoverable / replayable；LangGraph 是 v0.6 reference workflow runtime。
- Change Journal 与 Audit 要求 append-only。
- D4/D6/D7 不得通过共享 D5 内部数据库获得语义状态。
- DSP 跨 Host 一致性采用 Saga / compensation，而不是 XA/2PC。

Technology Modernization 阶段曾明确禁止在没有独立架构批准的情况下引入数据库。该限制的作用域是“技术现代化不得顺带改变产品/架构”，并不等于 DSP 永久禁止数据库。Architecture Modernization Review 现在负责补齐这一物理持久化决策。

本 ADR 要解决的问题是：

> DSP 的 durable state 应使用什么物理持久化基线，同时如何保证现有 bounded-context ownership、Host source-of-truth、Saga 与 contract boundary 不被“共用数据库”破坏？

## 决策（Decision）

### 1. 冻结逻辑所有权与物理存储分离

DSP 采用以下不变量：

```text
Logical ownership != Physical storage
```

每一种长期状态必须只有一个 authoritative owner。owner 对该状态的：

```text
schema / repository contract
persistence lifecycle
transaction boundary
migration ownership
recovery semantics
```

负责。

其他 bounded context 只能通过稳定 contract / API / immutable ref 使用该状态，不得因为底层物理存储相同而获得直接表访问权。

### 2. 关系型 durable store 作为 v0.6 平台标准持久化类别

DSP v0.6 的平台级 durable state 默认落在**关系型 durable store**。

该决定覆盖需要以下能力的状态：

- crash/restart 后可恢复；
- 可事务性提交单 owner 状态变更；
- 可建立稳定 identity / version / hash / lineage；
- 可执行约束与一致性校验；
- 可进行受控 migration；
- 可支持审计、保留与运维备份。

该决定不要求 Host native model、完整 DWG/RVT、完整精确几何或全量 IFC/Metro 镜像复制进入平台关系库。

### 3. PostgreSQL 是 reference implementation，不是领域契约

PostgreSQL 作为 DSP v0.6 的 reference durable persistence implementation。

Reference topology MAY 在早期共用一个 PostgreSQL deployment：

```text
PostgreSQL
├── semantic_runtime
├── changeset
├── gateway
├── interaction
├── orchestrator_checkpoint
└── audit
```

但这些 namespace 仍然属于不同 owner。

业务 Domain / Service 层 MUST 依赖自己的 repository/store contract，不得把 PostgreSQL client、SQL dialect、JSONB、advisory lock、LISTEN/NOTIFY 等 PostgreSQL-specific API 作为 DSP public/domain contract。

PostgreSQL-specific capability MAY 在 infrastructure adapter 内使用，只要替换 adapter 不改变 canonical semantics、public contract 或 owner boundary。

### 4. 共用 deployment 不等于 shared database ownership

初期允许多个 owner 共用同一个 PostgreSQL cluster/database，以降低运维复杂度，但至少必须保持：

```text
独立 schema/namespace
独立 migration ownership
独立 repository implementation
独立 service credential / 最小权限
```

禁止：

```text
D7 -> SELECT semantic_runtime.*
Gateway -> UPDATE changeset.*
D5 -> JOIN gateway.approval_record
Workflow Orchestrator / LangGraph runtime -> 直接修改其他 owner 的业务表
```

跨 owner 访问必须经过 contract/API/ref。

共享数据库实例不得演化为 shared mutable database architecture。

### 5. Host native design state 不进入平台双主模型

AutoCAD/Revit/Tekla 等 Host Application 继续拥有 native realtime source of truth。

平台持久化 MAY 保存：

```text
HostBinding
revision/ref
SemanticProjection
Snapshot/SnapshotSet
hash / provenance / coverage / freshness metadata
ChangeSet / approval / execution evidence
```

但 MUST NOT 把平台 projection 当成可独立覆盖 Host native model 的第二主状态。

D5 projection 仍然遵循 Progressive Semantic Runtime：task-scoped / aspect-scoped / coverage-scoped / on-demand reconstruction。

### 6. 每个 owner 使用自己的事务边界

关系型数据库提供的 ACID transaction 只允许用于**单 owner 内部**的一致性提交。

不得因为多个 schema 位于同一 PostgreSQL deployment，就建立：

```text
D5 transaction
+ ChangeSet transaction
+ Gateway approval transaction
+ Host execution
```

组成的跨 owner ACID transaction。

跨 owner / 跨 Host 的流程继续遵守现有：

```text
immutable refs
idempotency
revision barrier
Saga
compensation
reconcile / verify
```

原则。

本 ADR 不引入 XA/2PC。

### 7. 不同状态保留不同 durability semantics

不得用一个泛化的全局 `state` 表承载所有 DSP 状态。

各类状态至少保持以下语义差异：

| State | Owner | Required persistence semantics |
| --- | --- | --- |
| Host native design state | Host Application | Host-native durability；平台不双主 |
| SemanticIdentity / HostBinding | D5 | persistent identity/binding |
| SemanticProjection | D5 | versioned / reconstructable / provenance-bound |
| SemanticSnapshot / SnapshotSet | D5 | immutable reference/hash evidence |
| DirtyMap | D5 | mutable operational state |
| ChangeJournal | D5 / Journal | append-only |
| Semantic definitions / Provider versions | Semantic Service / Provider | version/hash pinned |
| ChangeSet | ChangeSet Store | immutable after freeze/approval boundary |
| ApprovalRecord | Gateway | durable approval evidence |
| ExecutionGrant | Gateway | durable, revocable/expiring authorization evidence |
| InteractionSession | Interaction Coordinator | finite-state, resumable session |
| Workflow checkpoint | Workflow Orchestrator | recoverable/replayable workflow state；LangGraph 为 v0.6 reference runtime |
| Audit | Audit subsystem / Gateway trust domain | append-only evidence |

### 8. Workflow Orchestrator 拥有 workflow checkpoint；LangGraph 是 reference runtime

采用 PostgreSQL 作为 reference durable store 不改变 workflow 的逻辑 ownership：

```text
Workflow Orchestrator = task/workflow/checkpoint/HITL authoritative logical owner
LangGraph              = v0.6 reference workflow runtime
```

`orchestrator_checkpoint` 是 Workflow Orchestrator 的物理 persistence namespace。v0.6 MAY 由 LangGraph checkpoint adapter 实现，但该 namespace 不成为第二个 orchestrator，也不获得 ChangeSet、D5、Gateway、Execution Saga 等领域状态的 ownership。

Workflow checkpoint 只保存 workflow-local state 与 stable refs；不得复制并重新拥有其他 authoritative owner 的业务真相。具体 runtime ownership 与替换规则由 ADR-010 冻结。

### 9. Redis / cache 类技术不得成为 system of record

未来 MAY 引入 Redis 或其他 cache/coordination technology，但它们只能承担：

```text
cache
ephemeral coordination
performance optimization
```

任何在进程、节点或缓存故障后必须恢复的 canonical/durable state，都必须能够从 authoritative durable owner 恢复。

Cache 不得成为唯一 ApprovalRecord、ChangeSet、Snapshot、workflow checkpoint 或 audit evidence 的保存位置。

### 10. Persistence implementation 不得泄漏进 canonical contract

以下内容不得成为跨语言 DSP canonical schema 的必要语义：

```text
PostgreSQL table name
schema name
primary-key implementation
JSONB shape
sequence id
advisory-lock id
SQL isolation level name
vendor-specific replication metadata
```

Canonical contract 只表达领域 identity、hash/ref、version、status、provenance、authorization 与其他已冻结业务语义。

## 结果（Consequences）

### 正面

- 主 Spec 已存在的 durable / append-only / recoverable 要求获得明确可实施的物理基线。
- 避免把 DSP 做成一个“所有模块共享一套表”的 shared-database monolith。
- 同时避免过早为每个 bounded context 部署独立数据库实例、消息集群或复杂云原生基础设施。
- PostgreSQL 可以为 Snapshot、ChangeSet、Approval、checkpoint、Audit 等提供成熟的事务、约束、索引、备份与 migration 基础。
- owner boundary 与物理部署解耦，未来可按容量、安全或组织边界拆分数据库，而无需改变 public/domain contract。
- 保持 Host/D5 非双主、Progressive Semantic Runtime、Saga、immutable ChangeSet 等现有架构不变量。
- 与 ADR-010 对 `Workflow Orchestrator` logical owner / LangGraph reference runtime 的分层一致。

### 代价

- 即使共用一个 PostgreSQL deployment，也必须维护多个 schema/repository/migration owner。
- 服务间读取不能通过便捷的跨 schema SQL JOIN 完成，需要稳定 API/ref 与显式 read model。
- 数据库级 ACID 不能被误用为跨 owner / 跨 Host 一致性机制。
- Infrastructure adapter 必须防止 PostgreSQL-specific 特性向领域层泄漏。
- 后续仍需分别设计 migration、retention、backup/restore 等运行规则；cross-owner delivery 与 crash recovery 由 ADR-009 冻结。

## 不在本 ADR 范围内（Non-goals）

- 不定义具体表结构、索引、ORM 或 migration framework。
- 不定义 PostgreSQL HA、replication、RPO/RTO、backup frequency 或 disaster-recovery deployment。
- 不选择 Kafka、NATS、RabbitMQ 或其他跨 owner event transport。
- 不重新定义 ADR-009 已冻结的 outbox/inbox、at-least-once delivery 与 crash-recovery 语义。
- 不改变 `Workflow Orchestrator` 的业务 workflow ownership；LangGraph 的 v0.6 reference runtime 身份与 future replacement 由 ADR-010 管理。
- 不引入 Temporal 作为第二个业务 orchestrator。
- 不改变 Host native source-of-truth、Semantic Service authority、ChangeSet、ApprovalRecord 或 ExecutionGrant 的既有领域语义。
- 不把完整 DWG/RVT、完整精确几何或全量实时 IFC/Metro 镜像迁入 PostgreSQL。

## 被拒绝的方案（Rejected Alternatives）

### A. 一个全局 DSP 数据库，所有模块共享表

拒绝。该方案会使物理数据模型取代服务契约，破坏单 owner 原则，并允许 D4/D6/D7 绕过 D5/Gateway/ChangeSet contract。

### B. 每个 bounded context 从第一天开始部署独立数据库实例

暂不采用。逻辑隔离是必须的，但当前没有证据证明必须同时承担多实例数据库的运维复杂度。未来可在不改变领域 contract 的情况下物理拆分。

### C. 所有长期状态只保存为文件

拒绝作为平台默认方案。文件可以继续用于 immutable Provider、配置、导出或特定本地实现，但不足以作为 Approval、ChangeSet、checkpoint、Journal/Audit 等企业级 durable state 的统一 reference persistence baseline。

### D. Redis 作为主状态存储

拒绝。Redis 可作为 cache/ephemeral coordination，但不作为 v0.6 canonical durable state 的 reference system of record。

## 架构约束（Architecture Invariants Added by This ADR）

1. 一个长期状态只能有一个 authoritative owner。
2. 共用 PostgreSQL deployment 不授予跨 owner 表访问权。
3. 每个 owner 独立拥有 schema/repository/migration/credential boundary。
4. Domain/service code 不直接依赖 PostgreSQL-specific API。
5. 跨 owner 不使用数据库 ACID transaction；继续使用 immutable refs、idempotency、Saga 与 reconcile。
6. Host native design state 仍由 Host Application 权威持有。
7. D5 是 progressive canonical projection owner，不是第二 Host master。
8. Durable workflow checkpoint 由 `Workflow Orchestrator` authoritative ownership 管理；LangGraph 仅是 v0.6 reference runtime。
9. Redis/cache 不得成为 canonical durable system of record。
10. Persistence vendor detail 不得进入 DSP canonical/public contract。
