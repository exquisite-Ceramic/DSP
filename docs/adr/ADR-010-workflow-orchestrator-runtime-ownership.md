# ADR-010: Workflow Orchestrator Runtime Ownership

- 状态：Accepted
- 日期：2026-09-16
- 关联：ADR-008、ADR-009；`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md` §3、§28、§29、§43；`platform/orchestrator/`；`platform/execution_reconciliation/`

## 背景（Context）

在本轮 architecture consistency amendment 之前，主 Spec v0.6 曾直接写道：

```text
LangGraph = task/workflow/checkpoint/HITL 的最终编排者
```

同时，Spec 也冻结了一个更高层的不变量：一个长期状态只能有一个 authoritative owner，且 deterministic domain modules 不得把自己的业务规则交给自由形式 LLM 或其他隐藏 agent loop。

当前仓库中的 `platform/orchestrator/` 已经包含 Canonical Operation、Operation Resolver、Parameter Binder、Interaction Binding 等确定性业务模块，但当前实现尚未形成一个真正绑定 LangGraph runtime 的完整 workflow engine；根 `pyproject.toml` 也尚未把 LangGraph 作为 canonical runtime dependency。

与此同时，Phase I 已形成独立的 Execution Saga V2/CAS 状态机，用来承载 execution/reconciliation truth。ADR-008 又冻结了 persistence owner 与物理数据库分离，ADR-009 冻结了 cross-owner delivery、crash recovery 与 unknown-outcome 收口规则。

因此 Architecture Review 需要明确区分：

```text
谁拥有业务 workflow 的逻辑所有权？

和

哪个具体 framework/runtime 在 v0.6 中实现这个 owner？
```

本 ADR 要避免以下两类问题：

1. 把 LangGraph library 本身误当成 DSP canonical domain contract；
2. 在 LangGraph、Temporal、Execution Saga 等多个 durable state machine 之间形成重叠 ownership。

## 决策（Decision）

### 1. Workflow Orchestrator 是 authoritative logical owner

DSP 定义一个逻辑上的：

```text
Workflow Orchestrator
```

作为以下状态的 authoritative owner：

```text
task workflow progression
workflow checkpoint / resume position
HITL wait/resume state
workflow-level retry/replan decision
AsyncOperationRef wait/continue coordination
```

该 logical owner 不等于某个具体 Python library。

架构不变量是：

```text
Workflow owner != workflow framework implementation
```

### 2. LangGraph 是 v0.6 reference workflow runtime

DSP v0.6 采用 LangGraph 作为 `Workflow Orchestrator` 的 reference runtime implementation。

即：

```text
Workflow Orchestrator   = logical owner
LangGraph               = v0.6 reference runtime
```

LangGraph 可以承担：

```text
workflow state transition
checkpoint
pause / resume
HITL coordination
retry / re-entry coordination
routing between deterministic services
```

但 LangGraph library type、checkpoint row shape、graph node implementation detail 不得进入 DSP canonical/public contract。

### 3. Workflow checkpoint 只拥有 workflow navigation state

LangGraph checkpoint MUST NOT 成为以下领域事实的第二 source of truth：

```text
SemanticSnapshot / SemanticProjection
ChangeSet
ApprovalRecord
ExecutionGrant
ProviderBinding
Execution Saga state
Host commit truth
ActualDelta
```

Workflow checkpoint SHOULD 只持有稳定引用，例如：

```text
task_id
snapshot_ref
changeset_id/hash
approval_id/ref
execution_plan_ref
saga_id
AsyncOperationRef
interaction_id
current workflow node / workflow-local metadata
```

恢复后，Orchestrator MUST 重新查询 authoritative owner，而不是把 checkpoint 中缓存的远程状态当作最新事实。

### 4. Deterministic services 继续拥有业务规则

以下模块继续保持 deterministic domain/service ownership：

```text
Operation Resolver
Freshness Resolver / D5 barrier
Parameter Binder
Impact Analyzer
ChangeSet Builder
Approval / Gateway policy
Execution Planner
Provider Resolver
Revision Barrier
Verify / Reconcile
Scope Comparator
Execution Saga
```

LangGraph 只编排调用顺序、等待、重入与异常路径。

LangGraph MUST NOT 重新实现这些模块的 canonical semantics。

### 5. Execution Saga 与 Workflow Orchestrator 是两个不同 owner

DSP 明确区分：

```text
Workflow Orchestrator
= “这个用户任务现在进行到哪一步？”

Execution Saga
= “这个已批准执行的 ChangeSet/Slice 当前实际执行到什么状态？”
```

因此：

```text
LangGraph checkpoint
!=
ExecutionSagaStore state
```

Execution Saga 继续拥有：

```text
admission
HOST_COMMITTED
reconciliation
PARTIALLY_COMMITTED
DIVERGED
convergence / compensation-related execution truth
```

Workflow Orchestrator 只能通过 `saga_id` / stable API/ref 使用这些事实。

### 6. Temporal 当前不作为第二 business orchestrator 引入

DSP v0.6 不同时运行：

```text
LangGraph business workflow
+
Temporal business workflow
```

来共同拥有同一 task 的 retry/checkpoint/recovery/Saga 语义。

原因是这会形成多个 durable workflow truth：

```text
LangGraph checkpoint
Temporal workflow history
ExecutionSagaStore
```

从而违反 single authoritative owner 原则，并产生不可接受的状态解释冲突。

因此 Temporal 当前：

```text
NOT ADOPTED as a second business orchestrator
```

### 7. Future Temporal adoption 只能通过替换，不得通过重叠 ownership

未来若有充分证据证明 LangGraph 不满足 durability、timer、worker recovery、scale 或 operational requirements，DSP MAY 通过独立 ADR 把 workflow runtime 从 LangGraph 迁移为 Temporal 或其他 durable workflow engine。

该迁移必须满足：

```text
one authoritative Workflow Orchestrator owner remains
old/new runtime ownership cannot remain dual-active indefinitely
external domain owners remain unchanged
Execution Saga remains independent execution truth
```

迁移模式必须类似：

```text
characterize current workflow contract
→ build alternate runtime adapter
→ dual-run / shadow where safe
→ prove parity
→ cut over workflow ownership
→ retire old runtime
```

不得采用：

```text
LangGraph decides some retries
Temporal decides other retries
both own task completion truth
```

### 8. Runtime abstraction 必须位于 workflow framework 边界

未来实现 SHOULD 形成类似：

```text
WorkflowOrchestratorPort
        │
        ├── LangGraphWorkflowRuntime   # v0.6 reference
        └── OtherWorkflowRuntime       # future ADR only
```

该 abstraction 的目的不是在 v0.6 中同时支持多个 runtime，而是防止领域层直接绑定 framework-specific API。

Domain/service modules MUST NOT import LangGraph-specific state/node/checkpoint types作为其公共接口。

### 9. Workflow state persistence 遵守 ADR-008

LangGraph checkpoint 属于 Workflow Orchestrator owner 的 durable state。

其 v0.6 reference persistence MAY 使用 ADR-008 已批准的 PostgreSQL durable substrate，但：

```text
checkpoint schema
migration
repository/adapter
credential boundary
```

必须属于 Workflow Orchestrator owner。

其他 owner 不得直接读写 checkpoint 表。

### 10. Workflow resume 遵守 ADR-009 crash-recovery 规则

当 LangGraph/Orchestrator 从 checkpoint 恢复时，MUST 假设 checkpoint 之后的外部 side effect 可能已经发生但响应丢失。

因此恢复逻辑至少应：

```text
reload checkpoint
→ resolve stable refs
→ query authoritative owners
→ inspect Saga / Approval / ChangeSet / Host outcome evidence
→ decide resume/retry/replan
```

不得使用：

```text
“checkpoint 停在 Apply 前，所以 Host 一定没执行”
```

这类基于本地 workflow position 推断外部事实的规则。

### 11. AsyncOperationRef 是 Orchestrator 与长任务之间的稳定恢复边界

Host interaction、semantic reconstruction、long-running execution 等长任务继续通过主 Spec 定义的 typed `AsyncOperationRef` 暴露。

Workflow checkpoint MAY 保存 `AsyncOperationRef`，恢复后通过对应 authoritative service 查询状态。

Orchestrator 不得依赖 remote service 的 hidden process/session memory 来恢复任务。

### 12. Orchestrator 不拥有 transport/delivery truth

ADR-009 定义的 outbox/inbox/delivery infrastructure 只负责可靠消息移动。

Workflow Orchestrator MAY 因收到领域事件而继续 workflow，但：

```text
event delivery success
!=
workflow business success
```

同样：

```text
workflow checkpoint success
!=
Host execution success
```

各 owner 的 durable truth 必须保持可区分。

## Reference Ownership Topology

```text
User / LLM intent
      │
      ▼
Workflow Orchestrator
(logical owner)
      │
LangGraph runtime
(v0.6 reference)
      │
      ├─────────────► D5 / Semantic Runtime
      ├─────────────► Operation / Parameter / Impact services
      ├─────────────► ChangeSet Store
      ├─────────────► Gateway / Approval
      └─────────────► Execution Planning
                          │
                          ▼
                    Execution Saga V2
                    execution truth owner
                          │
                          ▼
                         Host
```

Persistent state ownership remains：

```text
Workflow checkpoint   → Workflow Orchestrator
Execution Saga state  → Execution Reconciliation/Saga owner
ChangeSet             → ChangeSet Store
Approval / Grant      → Gateway
Semantic state        → D5
Host native state     → Host Application
```

## 结果（Consequences）

### 正面

- 保留主 Spec “单一 workflow owner” 的设计意图，同时避免把一个 framework library 升格为 domain contract。
- 当前可继续采用 LangGraph，而不会阻塞未来 runtime evolution。
- 防止 LangGraph checkpoint 与 Execution Saga/ChangeSet/Gateway 形成多主状态。
- 与 ADR-008 的 logical ownership / physical implementation 分离保持一致。
- 与 ADR-009 的 durable recovery 规则一致：resume 后重新验证 authoritative facts。
- Temporal 等更强 durable workflow engine 未来仍可通过独立 cutover ADR 引入。

### 代价

- 需要为 Orchestrator 建立清晰的 runtime adapter/port，而不能让所有业务模块直接调用 LangGraph API。
- checkpoint payload 必须严格控制为 workflow-local state + stable refs，不能方便地复制其他 owner 的整个对象图。
- 未来若切换 Temporal，需要明确的 parity/cutover/retirement 过程，不能简单新增一个 engine 并长期双跑。

## 不在本 ADR 范围内（Non-goals）

- 不实现 LangGraph workflow graph、节点、checkpoint adapter 或数据库表。
- 不选择具体 LangGraph checkpoint backend package/version。
- 不引入 Temporal。
- 不定义 Temporal worker/activity/task-queue 架构。
- 不改变 ChangeSet、Gateway、D5、Execution Saga 或 Host 的 authoritative ownership。
- 不重新设计 Canonical Action、Approval、ExecutionGrant、ProviderBinding、Saga compensation 语义。
- 不把 LLM agent loop 变成第二 workflow state machine。

## 被拒绝的方案（Rejected Alternatives）

### A. LangGraph library 本身成为永久 canonical architecture boundary

拒绝。DSP 需要冻结的是 workflow ownership/invariants，而不是第三方 framework 的具体 state/node/checkpoint representation。

### B. Temporal 立即替代 LangGraph

暂不采用。当前尚没有经过 Architecture Review 的 durability/scale/operations evidence 证明必须进行 runtime replacement；同时现有 Spec 已以 LangGraph 为 reference direction。

### C. LangGraph + Temporal 同时拥有业务 workflow

拒绝。会产生重叠 retry/checkpoint/recovery ownership，并与 Execution Saga 一起形成多个 durable state machine truth。

### D. 把所有 workflow/execution 状态都收敛进 LangGraph checkpoint

拒绝。将破坏 D5、ChangeSet、Gateway、Execution Saga、Host 等既有 authoritative owner 边界。

## 架构约束（Architecture Invariants Added by This ADR）

1. `Workflow Orchestrator` 是逻辑 workflow authoritative owner；framework implementation 不是 canonical domain owner。
2. LangGraph 是 v0.6 reference workflow runtime。
3. Workflow checkpoint 只拥有 workflow navigation/HITL/retry coordination state 与 stable refs。
4. Checkpoint 不得复制并重新拥有 ChangeSet、Approval、Saga、Host commit、SemanticProjection 等领域真相。
5. Deterministic domain services 继续拥有自己的业务规则；LangGraph 只负责编排。
6. Execution Saga 是 execution/reconciliation truth owner，与 Workflow Orchestrator 分离。
7. Temporal 当前不得作为第二 business orchestrator 与 LangGraph 并行拥有同一 workflow。
8. Future runtime replacement 必须通过独立 ADR、parity、cutover 与 retirement 完成。
9. Workflow resume 必须重新查询 authoritative owners，不能用 checkpoint position 推断外部 side effects。
10. Workflow framework-specific types 不得进入 DSP canonical/public contract。
