# Workflow Orchestrator v0.6 恢复手册

本文档定义 ADR-010 / Workflow Orchestrator v0.6 的故障恢复与运维边界。目标不是通过修改持久化数据“把流程推过去”，而是在运行时重启、异步 owner 长时间未完成、Execution Saga 已经启动、Host dispatch 结果未知等情况下，重新读取各 authoritative owner 的事实，并通过受支持的 Orchestrator / execution-owner API 恢复同一工作流。

## 1. 三类持久事实必须分开理解

### 1.1 Workflow checkpoint：任务导航事实

**Workflow checkpoint** 回答的是“当前任务导航到哪里、等待什么、后续应该从哪个确定性节点重新查询 owner”。它可以持久化：

- `task_id`；
- `WorkflowPhase`；
- workflow-local request data；
- `StableRef`；
- `AsyncOperationRef`；
- durable `saga_id`；
- 为恢复路由所需的少量 workflow-local 标记。

Checkpoint 不是 ChangeSet、Approval、Execution Saga、Host dispatch 或 SemanticProjection 的 authoritative business state。完整的 `CanonicalChangeSet`、`ApprovalRecord`、`StoredExecutionSagaV2`、`HostDispatchIntent`、`ActualDelta`、`SemanticProjection` 不得复制进 checkpoint 形成第二份事实源。

### 1.2 Execution Saga：执行事实

**Execution Saga** 回答的是“Saga execution 实际发生了什么”。Saga 的状态、revision、active slice 等事实由 execution owner 持有；Workflow Orchestrator 只能通过稳定 read model 查询，不能根据自己的 graph node 历史推导或改写 Saga 状态。

一个 Apply-adjacent checkpoint 只能说明导航已经靠近执行边界，**不能据此推断 Host 尚未 commit**。调用方可能已经启动 Saga 或 Host dispatch，只是还没有来得及观察完成结果就发生进程崩溃。

### 1.3 Host dispatch recovery：Host effect 是否已知

**Host dispatch recovery** 回答的是“当前 Host effect outcome 是否已经确定”。它与 Execution Saga 是两个独立的 authoritative projection。

`OUTCOME_UNKNOWN`、`RECOVERY_REQUIRED`、`SAFE_TO_RETRY` 都属于 Host dispatch recovery 事实，不是新的 Saga terminal status。特别是：

- `OUTCOME_UNKNOWN` **绝不授权** Workflow Orchestrator 发起新的 `begin_execution`；
- `SAFE_TO_RETRY` 表示 execution owner 的恢复流程可以按其自身规则继续，并不意味着 Orchestrator 可以制造新的 Host command identity；
- 原 `dispatch_intent_id`、ExecutionSlice hash、idempotency identity 必须保持稳定，除非 authoritative execution owner 按其契约明确创建了新的业务身份。

### 1.4 ExecutionOwnerView 只是组合读边界

`ExecutionOwnerView` 把 Execution Saga projection 与 Host dispatch recovery projection 放到一个稳定读取边界中，方便 Workflow Orchestrator 一次获得完整 execution-side truth；它**不会合并两者的 ownership**。

因此恢复决策的顺序必须是：

1. 重新查询 `ExecutionOwnerView`；
2. 先检查 active Host dispatch recovery；
3. 再分类最新 Saga status；
4. 只有不存在 durable Saga，或者 authoritative view 明确允许创建第一次执行时，才进入新的 execution start；
5. 已经存在 Saga identity 时，禁止仅根据 checkpoint 位置调用第二次 `begin_execution`。

## 2. PostgreSQL workflow persistence ownership

Workflow Orchestrator 在 PostgreSQL 中拥有两个彼此独立但可通过稳定引用关联的 persistence owner。它们都不是 execution、Gateway、semantic runtime 或 Host dispatch recovery 的 authoritative business state。

### 2.1 Checkpoint owner：navigation / wait

LangGraph checkpoint 表只属于 Workflow Orchestrator，其 PostgreSQL schema 为：

```text
orchestrator_checkpoint
```

该 schema 是 workflow navigation persistence owner。`PostgresSaver.setup()` 只能通过 Orchestrator 提供的 checkpointer factory 初始化，并在受限 `search_path` 下创建/访问 checkpoint 表。

其他 authoritative owner（例如 execution Saga、Gateway、semantic runtime、Host dispatch recovery）不得直接读写 `orchestrator_checkpoint` 表。反过来，Workflow Orchestrator 也不得通过 SQL 修改这些 owner 的业务表来完成恢复。

### 2.2 Artifact owner：deterministic continuation artifact

Operation Proposal、ParameterBinder 等确定性 continuation 所需的 workflow-local artifact 由独立 PostgreSQL schema 持有：

```text
orchestrator_artifact
```

`orchestrator_artifact` 保存的是可由 checkpoint 中 `StableRef` 精确寻址的 **workflow-local deterministic continuation artifact**。它允许进程在 human pause 边界完全退出后，以新的 artifact store 实例重新打开同一 continuation 输入；它不是 ChangeSet、Approval、Execution Saga、Host dispatch 或 SemanticProjection 的第二份 authoritative copy。

v0.6 的恢复与保留规则冻结为：

```text
orchestrator_checkpoint = navigation/wait
orchestrator_artifact   = workflow-local deterministic continuation artifact
active/paused reachable artifact ref => GC forbidden
WORKFLOW_ARTIFACT_UNAVAILABLE => no manual row editing
legacy-only rehydration = authoritative inputs + exact legacy hash equality
```

因此：

- 任何从 active / paused Workflow checkpoint 可达的 artifact `StableRef` 都是 GC root；对应 artifact **GC forbidden**，不能在任务仍可恢复时删除。
- v2 human pause resume 必须命中 pending subject 所指向的 exact durable artifact。artifact 缺失、损坏、来源不再是 durable，或返回引用发生漂移时，runtime 必须以 `WORKFLOW_ARTIFACT_UNAVAILABLE` fail closed，并保持原 pause 可重试。
- `WORKFLOW_ARTIFACT_UNAVAILABLE` 不是修改数据库行的授权。operator 不得手工补写 `orchestrator_artifact`，不得改 checkpoint 的 subject ref，也不得清掉 pending interaction 来绕过 durable authority。
- rehydration 只允许用于明确的 legacy migration；该 **legacy-only rehydration** 必须重新读取 authoritative inputs，并要求 **exact legacy hash equality**。当前 v2 pause 不得因为 artifact 缺失而自动 rehydrate。

### 禁止操作

- **禁止手工修改 checkpoint 行来强制业务成功。**
- 禁止把 `phase` 改成 `COMPLETED` 来绕过真实 owner 状态。
- 禁止删除 `saga_id` 来迫使 Orchestrator 重新调用 `begin_execution`。
- 禁止通过 SQL 把 `AsyncOperationRef` 清空并假装远程 operation 已完成。
- 禁止从 checkpoint 的 Apply 邻近位置推断 Host 没有产生副作用。
- 禁止删除 active / paused checkpoint 仍可达的 artifact row。
- 禁止在 v2 human resume 失败时手工制造“看起来等价”的 artifact row 或替换其 `StableRef`。

需要人工诊断时可以只读检查数据库运行状况，但业务恢复必须走受支持的 runtime/service API。

## 3. Runtime restart 的标准恢复流程

当 Orchestrator 进程退出、容器重启或调用方在 external side effect 完成前断开时：

1. 使用相同 PostgreSQL 数据库重新创建 owner-scoped checkpointer；若 checkpoint 可达 workflow artifact，同时创建新的 owner-scoped artifact store，不能依赖旧进程内存对象；
2. 创建新的 `LangGraphWorkflowRuntime` 与新的 service graph，不要复用旧进程对象作为恢复依据；
3. 使用 `get_checkpoint(task_id)` 读取 durable Workflow checkpoint；
4. 对 human pause，确认恢复出的 `PendingInteraction` 与 pause 前一致，并通过其 subject `StableRef` 从 `orchestrator_artifact` 读取 exact durable artifact；
5. 根据 checkpoint 中其余稳定 ref，从对应 authoritative owner 重新加载最新事实；
6. 若存在 `saga_id`，在任何新的 execution side effect 之前重新查询完整 `ExecutionOwnerView`；
7. owner truth 为 terminal execution state 时进入 verify/reconcile；
8. owner truth 为 active / recovery state 时进入 recover-or-wait；
9. 仅在没有 durable Saga、且正常 topology 到达首次执行边界时，才允许调用 `begin_execution`。

核心原则：**resume 先恢复自己的 durable continuation identity，再重新查询 authoritative truth，最后才 retry / replan；checkpoint 不是外部副作用完成情况的证据。**

## 4. 卡住的 AsyncOperationRef：operator procedure

`AsyncOperationRef` 是 durable continuation identity。它至少包含 owner、operation kind、operation id；runtime restart 后必须仍能看到同一个引用。

当任务长时间停在异步等待时，operator 按以下流程处理：

1. 通过 Orchestrator 的受支持查询入口读取 checkpoint，确认 `task_id`、当前 phase 和完整 `AsyncOperationRef`；不要修改 checkpoint row。
2. 使用 `AsyncOperationRef.owner` 和 `AsyncOperationRef.operation_id` 查询对应 authoritative owner，而不是从 graph history 猜测远程结果。
3. 如果 owner 仍报告 operation active，处理 owner 自身的队列、worker、依赖或外部系统故障，然后继续等待；不要伪造完成 payload。
4. 如果 owner 已 authoritative-complete，使用正常的 `resume` / `WorkflowResumeCommand` 唤醒 pending interrupt；resume value 只表示“允许重新查询”，业务结果仍由 service 从 owner 重新读取。
5. 如果 owner 报告不可恢复失败，按该 owner 的失败/重建/replan 契约处理；不要把 checkpoint 直接改到后续 phase。
6. 唤醒后再次读取 checkpoint，确认 async ref 已按 topology 清理或替换，并确认下一 owner ref 已 durable。

如果同一个 `AsyncOperationRef` 被重复唤醒，仍必须查询同一个 authoritative operation identity；不得因为重复 resume 创建第二份远程工作。

## 5. OUTCOME_UNKNOWN：operator procedure

当 `ExecutionOwnerView.active_dispatch_recovery.state == OUTCOME_UNKNOWN` 时，表示 Host effect 是否发生目前无法确定。此状态必须 fail closed。

操作流程：

1. 从 Workflow checkpoint 获取 durable `saga_id`。
2. 从 execution owner 查询最新 `ExecutionOwnerView`，记录 Saga revision、active ExecutionSlice hash、原 `dispatch_intent_id` 和 recovery state。
3. 确认 Workflow Orchestrator 当前处于 recover-or-wait / `AsyncOperationRef(kind=EXECUTION_JOB)` 路径，且没有第二次 `begin_execution`。
4. 在 execution owner / ADR-009 的受支持恢复接口中处理**同一个** dispatch intent；不要由 Workflow Orchestrator 生成新的 Host command identity 或新的 idempotency key。
5. 如果 recovery owner 仍为 `OUTCOME_UNKNOWN`，继续等待或执行 owner 定义的 read-back/reconciliation；不要把 Saga 人工标成 `SUCCEEDED` 或 `FAILED`。
6. 当 authoritative execution-side truth 发生变化后，再通过受支持的 workflow resume/wake 让 Orchestrator 重新读取 `ExecutionOwnerView`。
7. 若 Saga 已进入 terminal execution state，则由 verify/reconcile owner 收口；若 execution owner 明确仍需恢复，则继续 recovery wait。

`OUTCOME_UNKNOWN` 不是“失败”、也不是“未提交”的同义词；它只意味着当前不能安全证明 Host effect outcome。

## 6. SUCCEEDED / EXECUTING 等 restart 场景

如果 checkpoint 写入后调用方还未看到返回值就崩溃，重启后可能出现：

- Saga 已 `SUCCEEDED`：重新查询 owner 后直接进入 verify/reconcile，不能再次 execution start；
- Saga 仍 `EXECUTING` / `PENDING`：进入 recover-or-wait，不能再次 execution start；
- Saga `EXECUTING` 且 dispatch recovery 为 `OUTCOME_UNKNOWN`：dispatch recovery 优先，保持同一 recovery identity；
- Saga `READY` 且已有 `RECOVERY_REQUIRED` / `SAFE_TO_RETRY`：仍由 execution owner 的 recovery path 处理，Workflow Orchestrator 不自行重发 Host command。

对于所有“durable Saga 已存在”的场景，operator 应把 `begin_execution` 次数保持为原业务启动次数；runtime restart 本身不是创建新执行身份的理由。

## 7. HITL 恢复

HITL interrupt 的 continuation data 必须显式通过 `WorkflowResumeCommand` 进入 runtime。不要依赖 Web session、Python object、线程局部变量或其他隐藏进程内存恢复用户决定。

恢复时应确认：

1. `task_id` 指向原 durable workflow；
2. checkpoint 当前确实存在同一个 `PendingInteraction` / `pause_id`；
3. v2 pending subject 的 exact durable artifact 仍可从 `orchestrator_artifact` 读取，且返回的 `StableRef` 与 pending subject 完全一致；
4. resume kind / pause correlation / payload shape 已通过公共校验；
5. ACCEPT 后真实 deterministic continuation（例如 ParameterBinder）从该 durable artifact 继续执行，而不是只手工移动 phase；
6. 后续 deterministic service 仍通过 stable ref 重新读取需要的 authoritative facts。

如果 exact durable artifact 不可用，runtime 返回 `WORKFLOW_ARTIFACT_UNAVAILABLE`，原 pause 保持不变。operator 应修复 artifact owner 的可用性或从备份恢复同一 durable artifact；**禁止手工修改** checkpoint/artifact row 来伪造 continuation。只有 legacy checkpoint migration 可以走 legacy-only rehydration，并且必须满足 authoritative inputs + exact legacy hash equality。

同一个 human ACCEPT 在成功消费后再次提交必须按 stale command 拒绝；如果 workflow 此时已经转入 async wait，也不能把旧 `pause_id` 解释成新的异步 wake identity。

## 8. 故障诊断边界

遇到重复等待或无法推进时，分别问四个问题：

1. **Workflow checkpoint**：任务导航现在在哪里、持有哪些 refs？
2. **Workflow artifact**：active / paused checkpoint 可达的 deterministic continuation artifact 是否仍以 exact `StableRef` 存在？
3. **Execution Saga**：execution owner 认为 Saga 发生了什么？
4. **Host dispatch recovery**：当前 Host effect outcome 是否已知、当前 recovery identity 是什么？

不要把这些问题压成一个“checkpoint 看起来像什么”的判断。`orchestrator_artifact` 也不能替代 execution-side authoritative truth；`ExecutionOwnerView` 的价值仍是让 Orchestrator 获得完整 execution-side read boundary，同时保留两个 execution-side owner projection 的区别。

## 9. v0.6 技术边界

LangGraph + PostgreSQL checkpoint 是 v0.6 的业务 workflow runtime/persistence 组合；`orchestrator_artifact` 是同一版本中独立的 durable deterministic continuation owner。**Temporal 不属于 v0.6 recovery procedure**，本手册不要求也不允许通过新增 Temporal workflow history 来补偿现有 checkpoint/artifact/Saga/dispatch recovery 语义。

如果未来架构 ADR 明确引入新的 workflow engine，必须重新冻结 ownership、history 与 migration 契约；在此之前，operator 只使用本文定义的 LangGraph/owner API 恢复路径。

## 10. 恢复完成判定

只有同时满足以下条件，才可以认为一次故障恢复完成：

- Workflow checkpoint 已通过正常 runtime transition 到达期望 phase；
- active / paused checkpoint 可达的 workflow-local artifact 仍能通过 exact durable `StableRef` 读取；
- 所有被引用 authoritative owner 的状态均可重新读取且彼此一致；
- 已有 Saga 的恢复过程中没有产生未经 owner 授权的第二次 `begin_execution`；
- `OUTCOME_UNKNOWN` 已由 Host dispatch recovery / reconciliation 事实消解，而不是被人工覆盖；
- verify/reconcile 已读取 authoritative execution result；
- 没有通过数据库手工更新制造业务成功。