# ADR-009: Cross-owner Delivery & Crash Recovery

- 状态：Proposed
- 日期：2026-09-16
- 关联：ADR-003、ADR-008；`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md` §25、§28、§29、§31、§43；`platform/execution_coordination/`；`platform/execution_reconciliation/`

## 背景（Context）

ADR-008 已冻结：DSP 的长期状态由各 bounded context 单独拥有；关系型 durable store 是 v0.6 平台级持久化类别；PostgreSQL 是 reference implementation；跨 owner 不允许通过共享数据库建立 ACID transaction。

主 Spec 同时要求：

- workflow checkpoint 可恢复、可重放；
- `ChangeSet` / `ApprovalRecord` / `ExecutionGrant` / Saga 等关键状态具有 durable evidence；
- 所有 MODEL_OPERATION 必须具备稳定 idempotency key；
- 跨 Host 一致性使用 Saga / compensation，而不是 XA/2PC；
- Host write 后必须通过 ActualDelta、read-back、Verify / Reconcile / ScopeCheck 收口；
- `PENDING` 必须通过显式 `AsyncOperationRef` 暴露，不得依赖隐式 server session。

当前 Phase I 已存在 `ExecutionSagaStoreV2` 独立持久边界、`saga_revision` + `expected_revision` 的 CAS 状态迁移、Slice admission / Host commit / reconciliation / convergence 状态机；其 reference implementation 仍是 in-memory store。该事实说明 DSP 已经拥有业务 Saga state machine，Architecture Review 需要补齐的是 durable delivery 与 crash-recovery 规则，而不是重新发明第二套业务编排器。

ADR-003 已定义 Host 写命令的 idempotency key，但其现有 Host/Sidecar reference 去重缓存主要面向正常重试窗口，不足以单独承担平台崩溃、响应丢失、Host 重启后的 durable outcome truth。

本 ADR 要解决的问题是：

> 当 `ChangeSet committed → Approval recorded → Execution admitted → Host mutation → Reconcile` 跨越多个 authoritative owner 与 Host 外部副作用时，DSP 如何保证崩溃恢复后不会丢失已提交事实、重复产生业务副作用，或把未知执行结果错误归类为成功/失败？

## 决策（Decision）

### 1. 采用 owner-local ACID + Transactional Outbox

任何 owner 在一次本地业务状态变化需要对其他 owner 可见时，MUST 在**同一个 owner-local database transaction** 中同时提交：

```text
owner domain state
+
outbox record
```

例如：

```text
ChangeSet Store transaction
  ├── persist immutable ChangeSet
  └── append outbox: ChangeSetCommitted
```

若事务回滚，则 domain state 与 outbox record 必须同时不存在；不得先写业务表、再以第二次数据库操作“补发事件”。

Outbox 属于产生该事实的 owner，不属于全局 Event Service。

### 2. 跨 owner 投递语义冻结为 at-least-once

v0.6 不承诺 transport-level exactly-once delivery。

Reference delivery semantics：

```text
owner-local commit
  ↓
outbox
  ↓
dispatch / retry
  ↓
at-least-once delivery
  ↓
idempotent consumer
```

因此同一事件 MAY 被重复投递；consumer MUST 将重复 delivery 视为正常情况，而不是异常数据。

“Exactly-once business effect” 由以下组合保证：

```text
local ACID
+ transactional outbox
+ at-least-once delivery
+ idempotent consumer
+ CAS / revision guards
+ stable idempotency key
+ Host read-back / reconcile
```

不得把 exactly-once transport 作为 DSP 正确性的前置条件。

### 3. Consumer 使用 Inbox / Idempotent Receipt

对于会改变 consumer durable state 的跨 owner message，consumer MUST 具备 durable duplicate detection。

Reference mechanism 是 owner-local inbox / receipt record，至少绑定：

```text
event_id
producer_owner
producer_stream/version or source revision
consumer_owner
processed_at
result_ref/hash when applicable
```

consumer 在同一个本地事务内完成：

```text
check/insert inbox receipt
+
apply consumer domain transition
+
append its own outbox records when needed
```

重复 `event_id` 不得重复产生业务状态迁移。

只读、可纯函数重算且不会产生 durable side effect 的 consumer MAY 不持久化 inbox，但必须有可证明的幂等行为。

### 4. v0.6 reference implementation 使用 PostgreSQL outbox polling/claim

在没有吞吐、隔离或组织边界证据前，v0.6 不引入 Kafka、NATS、RabbitMQ 等 broker 作为 correctness dependency。

Reference implementation：

```text
PostgreSQL owner schema
  ├── domain tables
  ├── outbox
  └── inbox/receipts when needed
```

dispatcher MAY 使用 polling、row claim、lease 等 PostgreSQL adapter 机制进行投递，但这些实现细节不得泄漏进入 DSP canonical/public contract。

未来可以替换为 broker/CDC，只要保持：

```text
owner-local atomic publication
at-least-once semantics
consumer idempotency
ordering contract if explicitly declared
single authoritative owner
```

### 5. 不建立全局事件顺序

DSP v0.6 不定义所有事件的 total order。

只有在某个 bounded context 的业务不变量要求顺序时，才允许定义局部 ordering key，例如：

```text
saga_id + saga_revision
changeset_id + version
interaction_id + state_revision
semantic projection lineage
```

Consumer MUST 使用业务 version / CAS / expected revision 检测 stale、duplicate 或 out-of-order transition；不得依赖“消息恰好按网络到达顺序处理”。

### 6. LangGraph 仍是业务 workflow owner，事件投递层不是第二 orchestrator

Outbox dispatcher、inbox consumer、PostgreSQL polling 或未来 broker 都只负责 delivery，不拥有 DSP 业务 workflow。

保持：

```text
LangGraph
= task/workflow/checkpoint/HITL final owner

Execution Saga
= execution/reconciliation durable state owner

Delivery infrastructure
= message movement / retry only
```

Delivery infrastructure MUST NOT 自行决定：

```text
是否重新 PlanningSnapshot
是否重新审批
是否创建新 ChangeSet
是否选择新的 canonical operation
是否进入 compensation
```

这些决定仍由相应业务 owner / Orchestrator 根据 durable evidence 作出。

### 7. Host mutation 使用 Durable Intent，不尝试把 Host 加入数据库事务

Host Application 不属于 PostgreSQL transaction，Host mutation 也不得被伪装成跨系统 ACID commit。

在发送任何生产级 Host mutation 前，execution/reconciliation owner MUST 已经持久化足够的 dispatch intent / admission evidence，使崩溃恢复后能够回答：

```text
准备执行什么？
对哪个 exact Slice / ExecutionUnit？
使用哪个 binding / grant？
目标 Host instance/document 是什么？
稳定 idempotency key 是什么？
基于哪个 revision/precondition？
```

推荐顺序：

```text
1. durable Saga/Execution reservation
2. durable admitted authority / grant evidence
3. persist DISPATCH_INTENT
4. commit local transaction
5. dispatch HostCommand(idempotency_key)
6. observe response / timeout / transport failure
7. persist observation
8. read-back / ActualDelta / reconciliation
9. advance durable Saga state by CAS
```

不得先调用 Host，再尝试补写“我们本来打算执行”的 durable intent。

### 8. Host response 丢失时进入显式 OUTCOME_UNKNOWN

当出现以下窗口：

```text
Host may have committed
+
platform did not durably record the outcome
```

系统 MUST NOT 直接归类为：

```text
FAILED
```

也 MUST NOT 无条件重新执行。

该状态必须进入显式的 unknown-outcome recovery path。实现命名 MAY 不同，但语义至少等价于：

```text
OUTCOME_UNKNOWN
```

Recovery 必须使用：

```text
same stable idempotency key replay when safe
+
Host revision / command result lookup when available
+
Host read-back
+
ActualDelta / semantic verification
+
ApprovalScopeBoundary scope check
```

最终只能收口为有证据的状态，例如：

```text
COMMITTED / SUCCEEDED
NOT_COMMITTED / SAFE_TO_RETRY
PARTIALLY_COMMITTED
DIVERGED
REQUIRES_RECONCILIATION
```

不得仅根据“客户端没收到成功响应”推断 Host 没有写入。

### 9. Host idempotency 是 recovery aid，不是唯一 durable truth

ADR-003 的 stable idempotency key 继续有效，但本 ADR 冻结：

```text
idempotency cache hit != semantic verification
```

Host/Sidecar 的本地 idempotency store MAY 因文档关闭、Host 重启、缓存淘汰等原因失去历史，因此平台不得把该缓存当成唯一 durable evidence。

最终写结果仍以：

```text
Host native state
+ revision
+ ActualDelta/read-back
+ semantic verification
+ scope comparison
```

形成闭环。

若未来 Host 支持 durable command receipt，可作为额外证据加入，但不得替代 verify/reconcile invariant。

### 10. ExecutionSagaStoreV2 的 durable adapter 必须保持 CAS 语义

当前 `ExecutionSagaStoreV2` 已定义 `expected_revision` 驱动的严格 CAS transition。

未来 PostgreSQL durable adapter MUST 保持同一可观测语义：

```text
read saga_revision = N
attempt transition expected_revision = N
only one writer may commit revision N+1
stale writer => SAGA_CONFLICT
```

不得因数据库具备行锁或 serializable transaction 就删除领域层可观测的 revision/CAS contract。

数据库锁是 implementation detail；`saga_revision` / conflict semantics 是业务恢复协议的一部分。

### 11. Crash recovery 从 durable owner truth 重建，不从进程内 memory 推断

任一服务重启后，恢复流程 MUST 从该 owner durable store 与其他 owner 的 stable API/ref 重新获取事实。

不得依赖：

```text
Python object identity
in-memory queue
hidden server session
process-local retry counter
unpersisted callback
```

作为恢复正确性的必要条件。

LangGraph checkpoint 恢复后必须重新验证其外部 refs 当前状态，而不是假设 checkpoint 之后所有远程 side effects 都未发生。

### 12. Event / delivery contract 与 domain contract 分离

Outbox event 必须引用已经由 owner 冻结的 domain identity/hash/ref，而不是复制并重新拥有对方领域对象。

典型事件 payload 应优先携带：

```text
event_id
event_type
occurred_at
producer_owner
aggregate/domain ref
version/revision
correlation ids
immutable hashes/refs needed by consumer
```

不得通过事件 payload 创建第二份可独立修改的 `ChangeSet`、`Snapshot`、`ApprovalRecord` 或 Saga truth。

事件是事实通知，不是 shared mutable state。

### 13. Audit 与 outbox 不能互相替代

Outbox 的职责是可靠 delivery；Audit 的职责是 append-only governance evidence。

一个 outbox record 被投递并清理/归档后，不得导致必须保留的审计证据丢失。

同样，Audit log 也不得被当作业务队列来驱动唯一一次状态迁移。

## 崩溃窗口与恢复规则（Crash Windows）

### Window A — domain state 未提交前崩溃

```text
transaction rolled back
```

结果：state 与 outbox 都不存在；安全重试原 owner command。

### Window B — domain state + outbox 已提交，尚未投递即崩溃

结果：重启后的 dispatcher 从 outbox 继续投递；不得要求业务调用方重新制造事件。

### Window C — event 已投递，consumer 提交前崩溃

结果：producer 可重投；consumer 因 inbox/idempotency 不产生重复业务副作用。

### Window D — consumer state 已提交，ack/response 丢失

结果：重投同一 `event_id`；consumer 返回/投影既有结果，不重复迁移。

### Window E — DISPATCH_INTENT 已提交，Host 尚未调用即崩溃

结果：恢复后可依据 durable intent、grant validity、revision barrier 决定是否安全派发；不得生成新的逻辑 command identity。

### Window F — Host 已提交，平台记录结果前崩溃

结果：进入 `OUTCOME_UNKNOWN` 语义路径，通过 stable idempotency key + Host/read-back/ActualDelta/reconcile 收口。

### Window G — 某些 Slice 已提交，后续 Slice 失败/不可恢复

结果：遵循现有 Saga：`PARTIALLY_COMMITTED` / `DIVERGED`，阻止尚未开始 Slice，并通过显式 compensating ChangeSet / reapproval 处理；不得隐藏 undo。

## 结果（Consequences）

### 正面

- 消除“业务状态已提交但通知丢失”的 dual-write gap。
- 不要求引入分布式事务或 exactly-once broker 即可获得可证明的业务幂等。
- 与 ADR-008 的 single-owner / no-cross-owner-ACID 原则一致。
- 复用现有 Execution Saga V2/CAS，而不是增加第二套业务状态机。
- Host 外部副作用拥有明确的 unknown-outcome recovery protocol。
- Kafka/NATS 等未来可作为 transport evolution，而不是当前 correctness dependency。
- LangGraph workflow ownership、Execution Saga ownership 与 delivery responsibility 保持可区分。

### 代价

- 每个需要可靠跨 owner publication 的 owner 都要维护 outbox lifecycle。
- 产生 durable side effect 的 consumer 通常需要 inbox/receipt 或等价幂等机制。
- At-least-once delivery 要求所有 consumer 显式考虑 duplicate / stale / out-of-order message。
- `OUTCOME_UNKNOWN` 增加执行状态与运维可观测性复杂度，但避免了错误地重复写 Host。
- PostgreSQL polling 不是无限扩展方案；未来若吞吐或隔离需求出现，可能需要 broker/CDC ADR。

## 不在本 ADR 范围内（Non-goals）

- 不选择 Kafka、NATS、RabbitMQ 或云消息服务。
- 不定义 PostgreSQL outbox 的最终表结构、ORM、claim SQL、batch size 或 polling interval。
- 不规定所有 DSP 事件的全局顺序。
- 不引入 XA/2PC。
- 不把 Temporal 引入为第二个 workflow owner。
- 不重新设计 Phase I 已冻结的 Saga / `PARTIALLY_COMMITTED` / `DIVERGED` 语义。
- 不改变 ChangeSet、ApprovalRecord、ExecutionGrant、Snapshot、ActualDelta 的 authoritative ownership。
- 不以消息系统替代 Audit Store。
- 不承诺“网络 exactly once”；只冻结可验证的 business-effect correctness。

## 被拒绝的方案（Rejected Alternatives）

### A. 纯同步 RPC + checkpoint，不使用 durable publication

拒绝作为 correctness baseline。该方案存在 owner state 已提交但调用方/下游未获知的 dual-write window，恢复逻辑会依赖查询猜测与隐式时序。

### B. 全局数据库事务覆盖多个 owner

拒绝。违反 ADR-008 single-owner 与 no-cross-owner-ACID，并且仍无法把 AutoCAD/Revit Host mutation 纳入真正的数据库 transaction。

### C. 立即引入 Kafka/NATS 作为平台基础依赖

暂不采用。当前没有容量或隔离证据证明需要增加 broker 的运行与治理复杂度。未来可在保持本 ADR delivery semantics 的前提下替换 PostgreSQL reference transport。

### D. Host timeout 直接视为失败并自动重试新命令

拒绝。timeout 不能证明 Host 未提交；新 command identity 可能产生重复模型修改。必须进入 unknown-outcome recovery 并保留 stable idempotency identity。

## 架构约束（Architecture Invariants Added by This ADR）

1. 跨 owner publication 必须消除 owner-local state / event 的 dual-write gap。
2. v0.6 reference delivery 为 owner-local transactional outbox + at-least-once delivery。
3. Durable consumer side effect 必须具备 inbox/receipt 或等价可证明幂等机制。
4. Exactly-once business effect 不依赖 exactly-once network transport。
5. 不建立 DSP 全局事件 total order；顺序由显式 aggregate revision/CAS 决定。
6. Delivery infrastructure 不成为第二 workflow orchestrator。
7. Host mutation 前必须先持久化足够的 durable dispatch intent / admission evidence。
8. Host outcome 不确定时必须显式进入 unknown-outcome recovery，不得把 timeout 等同于 failure。
9. ADR-003 idempotency 是重试/恢复证据的一部分，但不是 Host semantic success 的唯一事实源。
10. PostgreSQL Saga adapter 必须保持 `ExecutionSagaStoreV2` 的 CAS/revision observable semantics。
11. Crash recovery 必须从 durable owner truth 重建，不依赖 process-local hidden state。
12. Outbox 是 delivery mechanism，Audit 是 governance evidence；二者不得互相替代。
