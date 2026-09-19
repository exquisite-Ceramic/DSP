# Capability Phase — HITL Pause / Resume Design

**Status:** Proposed — written-spec review pending  
**Date:** 2026-09-19  
**Base:** `main@32f1f1f1c7982a63bb68be25d7ac6ea208e92457`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`  
**Architecture authority:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`  
**Handoff:** `docs/superpowers/specs/2026-09-19-capability-phase-handoff.md`  
**Ownership contract:** `docs/superpowers/specs/2026-09-19-hitl-payload-ownership-contract.md`

## 1. Purpose

本设计定义 Capability Phase 的第一个能力增量：把 ADR-010 已存在的 LangGraph `interrupt()` / `resume()` 骨架收敛成一个可由调用方稳定观察、可跨进程恢复、可 fail-closed 校验的 **HITL pause/resume contract**。

它解决的不是“如何再加一个 interrupt”，而是下面四个缺口：

1. 调用方必须能从 framework-neutral checkpoint 明确知道 workflow 当前是否在等待人类输入、等待的是哪一种输入，以及该输入关联哪个 stable subject；
2. human resume 必须与当前 durable pause identity 相关联，旧命令、错误命令和发往异步 owner wait 的命令都不能推进 graph；
3. 进程重启后，同一个 pause 必须仍以同一个公共 identity 被观察和恢复；
4. HITL checkpoint 必须继续遵守 single-authoritative-owner：只持有 workflow navigation state 和 stable refs，不复制 Operation / ChangeSet / Approval / Saga / Host / Semantic authoritative truth。

Capability Phase handoff 的后续顺序保持不变：

```text
HITL pause/resume
  ↓
real E2E workflow
  ↓
semantic -> plan -> approve -> execute -> reconcile
  ↓
MCP/Agent front door
  ↓
real AutoCAD/Revit acceptance
```

本设计只冻结第一步，不提前实现后四步。

---

## 2. Existing baseline

当前 merged-main 已经具备以下基础：

- `Workflow Orchestrator` 是 workflow progression/checkpoint/HITL/retry coordination 的 authoritative logical owner；
- LangGraph 只作为 v0.6 reference runtime，framework type 不进入公共 contract；
- `WorkflowOrchestratorPort` 已暴露 `start / resume / get_checkpoint`；
- `WorkflowResumeCommand` 已存在；
- graph 的 `await_operation_proposal` 已调用 `interrupt()`；
- `await_async_operation` 已用同一 LangGraph interrupt primitive 等待外部 `AsyncOperationRef`；
- PostgreSQL checkpoint 已独占 `orchestrator_checkpoint` owner schema，并已有 restart/recovery acceptance；
- `WorkflowCheckpointView` 已只暴露 stable refs / navigation state。

但现状仍不是完整 HITL capability：

```text
current checkpoint
  └─ phase = AWAIT_OPERATION_PROPOSAL
     operation_ref = ...
     # 没有公共 pending-human-interaction identity

current resume(command)
  └─ 只检查 LangGraph snapshot 是否存在 interrupt
     # 不证明 command 对应当前 pause
     # 不证明 resume_kind 与当前 human decision 匹配
```

此外，LangGraph 的 `interrupt()` 同时用于：

- 人类继续输入；
- 外部 owner 异步等待。

这可以作为 runtime implementation detail，但不能继续成为公共语义上的同一种等待状态。

---

## 3. Scope

### 3.1 In scope

本能力只实现：

- framework-neutral pending-human-interaction contract；
- durable `pause_id` correlation；
- Operation Proposal 的 `ACCEPT / REJECT` v1 HITL；
- human wait 与 external async wait 的公共语义分离；
- restart 后同一 pending interaction 的恢复；
- stale / mismatch / malformed resume 的 fail-closed 行为；
- 旧 in-flight Operation Proposal checkpoint 的兼容读取/恢复策略；
- architecture / unit / PostgreSQL restart acceptance。

### 3.2 Explicit non-goals

本设计不实现：

- MCP/Agent/HTTP/WebSocket front door；
- 用户身份认证、RBAC、approver authorization；
- ApprovalRecord / ExecutionGrant 的新 authority；
- Step26 Host-native `InteractionSession` 的替代协议；
- concurrent multi-client resume 的 exactly-once arbitration / command receipt ledger；
- automatic DIVERGED compensation execution；
- 新 Host support matrix；
- real AutoCAD/Revit acceptance；
- legacy V1 retirement；
- Temporal 或第二 workflow runtime。

`pause_id` 是 durable correlation token，不是 authentication secret 或 authorization credential。

---

## 4. Ownership boundaries

### 4.1 Workflow Orchestrator owns human-pause navigation state

Workflow Orchestrator 可以拥有：

```text
pause_id
pending interaction kind
allowed resume kinds
subject stable ref
current workflow phase/node
resume cursor / workflow-local re-entry metadata
```

这些内容决定“这个 task 正在等待哪一个 workflow-local human decision”。

### 4.2 Workflow Orchestrator does not own domain truth

Pending interaction / checkpoint 不得持有或成为以下内容的 authoritative copy：

```text
ResolvedOperation body
InteractionSession body/result
ChangeSet body
ApprovalRecord
ExecutionGrant
ProviderBinding
Execution Saga state
Host document/revision/commit truth
SemanticSnapshot / SemanticProjection
ActualDelta
```

恢复后仍必须通过 stable ref 查询原 owner。

### 4.3 Step26 InteractionSession remains a separate owner

Step26 的 `InteractionSession` 继续由 **Interaction Coordinator** 持有，并通过：

```text
AsyncOperationRef(kind=INTERACTION_SESSION, ...)
```

表示 workflow 正在等待 Host-native interaction completion。

它不是 `PendingInteractionView`。

二者语义必须严格区分：

```text
PendingInteractionView
= Workflow Orchestrator 自己的 human decision/navigation wait

AsyncOperationRef(INTERACTION_SESSION)
= 外部 Interaction Coordinator 的 durable async state
```

HITL capability 不得把 Step26 `InteractionSession` 复制进 checkpoint，也不得把 Host Canvas prompt state 迁入 Workflow Orchestrator。

### 4.4 Operation Proposal acceptance is not execution approval

`OPERATION_PROPOSAL_ACCEPTED` 只表示：

```text
允许 workflow 继续使用当前 operation_ref 进入 parameter binding
```

它不表示：

```text
ApprovalRecord 已批准
ExecutionGrant 已签发
该 ChangeSet 已获执行授权
```

Step28/Step32/Gateway 的 approval / authorization authority 保持不变。

---

## 5. Public contracts

### 5.1 PendingInteractionKind

v1 只冻结一个 human-pause kind：

```python
class PendingInteractionKind(str, Enum):
    OPERATION_PROPOSAL = "OPERATION_PROPOSAL"
```

本能力不提前为未来 approval、conflict resolution 或 compensation confirmation 建立枚举值。

### 5.2 PendingInteractionView

新增 framework-neutral contract：

```python
@dataclass(frozen=True, slots=True)
class PendingInteractionView:
    pause_id: str
    kind: PendingInteractionKind
    subject_ref: StableRef
    allowed_resume_kinds: tuple[str, ...]
```

v1 Operation Proposal 必须投影为：

```text
kind = OPERATION_PROPOSAL
subject_ref = current operation_ref
allowed_resume_kinds = (
  OPERATION_PROPOSAL_ACCEPTED,
  OPERATION_PROPOSAL_REJECTED,
)
```

规则：

1. `pause_id` 必填、非空，是 workflow-local durable correlation identity；
2. `subject_ref` 必须是 stable ref，不能内嵌 operation body；
3. `allowed_resume_kinds` 必须非空、无重复并使用稳定字符串；
4. v1 不在公共 pending view 中加入任意 `payload` / domain DTO；
5. UI 所需的丰富展示数据由后续 front door 通过 `subject_ref` 重新查询 owner，或在独立设计中加入明确受限的 presentation metadata；本能力不先引入 generic presentation bag。

### 5.3 WorkflowCheckpointView

`WorkflowCheckpointView` 增加：

```python
pending_interaction: PendingInteractionView | None = None
```

并冻结以下不变量：

```text
pending_interaction != None
  => async_operation_ref == None

async_operation_ref != None
  => pending_interaction == None
```

即一个 checkpoint 在公共边界上不能同时宣称“等人”和“等外部 owner”。

现有 `interaction_ref` 字段本能力不删除、不重定义；任何 legacy cleanup 必须走独立兼容性变更。Step26 external wait 继续以 `AsyncOperationRef` 语义为准。

### 5.4 WorkflowResumeCommand

保留现有 command 的 `resume_kind` / `payload` 概念，并增加明确的 pause correlation：

```python
@dataclass(frozen=True, slots=True)
class WorkflowResumeCommand:
    pause_id: str
    resume_kind: str
    payload: Mapping[str, object] = field(default_factory=dict)
```

v1 Operation Proposal 规则：

```text
OPERATION_PROPOSAL_ACCEPTED => payload MUST be empty
OPERATION_PROPOSAL_REJECTED => payload MUST be empty
```

本能力禁止借 generic `payload` 携带 ResolvedOperation、Approval、ChangeSet 或其他 owner 的 authoritative DTO。未来若某个 human interaction 需要数据输入，必须先在对应 capability design 中冻结该 kind 的 payload schema 与 ownership，再允许非空 payload。

实现计划在修改 constructor 前必须做 caller census。若发现 Host/plugin/external consumer，必须采用 additive compatibility adapter；不得无证据地直接破坏外部 caller。当前 Capability handoff 尚未开放 MCP/Agent front door，因此本设计不把未存在的 front-door compatibility 当成约束。

---

## 6. Pause identity

### 6.1 `pause_id` is workflow-local

`pause_id`：

- 由 Workflow Orchestrator 创建；
- 只用于 durable pause correlation / stale-command detection；
- 不进入任何领域 owner identity；
- 不是 auth token；
- 不要求调用方解析其内部结构。

新 workflow v1 SHOULD 使用随机 UUID 形式的 opaque identity。

### 6.2 Persist before interrupt

不能在调用 `interrupt()` 的同一个未完成 node 中第一次生成 `pause_id`，因为 runtime resume/re-entry 可能重新执行该 node。

新 topology 必须采用两阶段：

```text
resolve_operations
  ↓
prepare_operation_proposal_pause
  # 创建并持久化 PendingInteractionView
  ↓
await_operation_proposal
  # 只读取已经持久化的 pending interaction
  # 调用 interrupt()
```

只有 `prepare_operation_proposal_pause` 成功 checkpoint 后，调用方才可能观察到该 `pause_id`。

如果进程在 prepare node checkpoint 之前崩溃，重新生成新的 pause identity 是允许的，因为旧 identity 从未成为 durable/public state。

---

## 7. Runtime resume semantics

### 7.1 Human resume

`resume(task_id, command)` 只能用于 `pending_interaction != None`。

runtime 在构造 LangGraph `Command(resume=...)` 之前必须按顺序校验：

```text
1. task exists
2. checkpoint has pending_interaction
3. command.pause_id == pending_interaction.pause_id
4. command.resume_kind in pending_interaction.allowed_resume_kinds
5. command payload satisfies the exact kind schema
```

任一失败都不得调用 graph，也不得修改 checkpoint。

### 7.2 External async poll/recheck

`resume(task_id, None)` 只用于：

```text
async_operation_ref != None
```

它表示“重新查询 external authoritative owner 并决定继续/等待”，不是隐式 human acceptance。

如果 checkpoint 正在等待 human interaction，而 command 为 `None`，必须 fail closed；不能把 poll 当作接受。

如果 checkpoint 正在等待 external async owner，而调用方提供 human command，也必须 fail closed；不能把 human input 注入 owner wait。

### 7.3 Stable errors

冻结以下公共错误语义：

```text
WORKFLOW_RESUME_INVALID
  malformed command / wrong resume mode / invalid payload schema

WORKFLOW_RESUME_STALE
  task exists but command.pause_id no longer matches current pending interaction
  including already-consumed / superseded pause

WORKFLOW_RESUME_MISMATCH
  pause_id matches, but resume_kind is not allowed for the current pending kind
```

现有：

```text
WORKFLOW_NOT_FOUND
WORKFLOW_CHECKPOINT_INVALID
WORKFLOW_SERVICE_FAILURE
```

继续保持。

错误消息不得暴露 LangGraph `Command` / `StateSnapshot` / checkpoint internal id。

---

## 8. Graph behavior for Operation Proposal

### 8.1 Prepare node

`prepare_operation_proposal_pause`：

1. 必须读取当前 `operation_ref`；
2. 若不存在则 fail closed；
3. 创建 `PendingInteractionView(OPERATION_PROPOSAL)`；
4. 写入 private graph state 的 JSON-compatible representation；
5. phase 保持/进入 `AWAIT_OPERATION_PROPOSAL`。

它不得调用 domain service 或产生 external side effect。

### 8.2 Await node

`await_operation_proposal`：

1. 只读取已持久化 pending interaction；
2. `interrupt()` 暴露的 runtime-private payload 最多包含 `pause_id`、kind 与 stable subject ref；
3. resume 后对 private resume payload 再做 defense-in-depth validation；
4. 成功处理后清除 `pending_interaction`。

### 8.3 ACCEPT

`OPERATION_PROPOSAL_ACCEPTED`：

```text
clear pending interaction
  ↓
phase = PARAMETER_BINDING
  ↓
continue existing deterministic workflow
```

接受动作本身不修改 operation authoritative truth。

### 8.4 REJECT

新增稳定 terminal workflow phase：

```python
WorkflowPhase.CANCELLED = "CANCELLED"
```

`OPERATION_PROPOSAL_REJECTED`：

```text
clear pending interaction
  ↓
phase = CANCELLED
  ↓
END
```

`CANCELLED` 表示用户终止本次 workflow progression，不表示任何 domain artifact 被删除/撤销。

本能力不引入“编辑 proposal 后继续”；需要修改 intent/operation 时由后续 capability 独立设计 replan/re-entry contract。

---

## 9. Legacy in-flight checkpoint compatibility

Durable runtime 升级不能假设所有旧 checkpoint 都已经结束。

Capability implementation 必须兼容升级前已经停在：

```text
phase = AWAIT_OPERATION_PROPOSAL
operation_ref = <stable ref>
LangGraph pending interrupt exists
pending_interaction field absent
```

的 checkpoint。

### 9.1 Chosen migration strategy: read-time legacy projection

本能力不批量重写历史 checkpoint，也不直接操作 LangGraph checkpoint row。

对于上述精确 legacy shape，adapter 可以在公共投影/validation 时派生一个稳定 synthetic pending interaction：

```text
kind = OPERATION_PROPOSAL
subject_ref = operation_ref
allowed_resume_kinds = ACCEPT / REJECT
pause_id = "legacy-op-proposal:" + sha256(
    normalized task_id
    + operation_ref.ref_id
    + (operation_ref.content_hash or "")
)
```

该 synthetic `pause_id`：

- 对同一 legacy checkpoint 可跨进程稳定重算；
- 不是 auth token；
- 不写回历史 row；
- 只允许这一种已知 legacy Operation Proposal shape；
- 任意其它“缺 pending state 但有 interrupt”的未知 shape 必须 `WORKFLOW_CHECKPOINT_INVALID`，不能猜测。

恢复 legacy pause 后，workflow 进入新 contract，后续 checkpoint 使用真实持久化 `PendingInteractionView`。

### 9.2 Node-name compatibility

实现必须保留能够恢复旧 `await_operation_proposal` checkpoint 的 node identity；若 topology 变更会使旧 checkpoint 无法加载，implementation plan 必须先增加兼容 adapter / migration test，不能通过 bump namespace 静默遗弃 in-flight task。

---

## 10. Restart and crash semantics

### 10.1 Restart while paused

必须证明：

```text
runtime A + saver A
  ↓
start task
  ↓
persist pending interaction P
  ↓
close runtime/saver
  ↓
runtime B + saver B
  ↓
get_checkpoint(task)
  == same pause_id/kind/subject_ref
  ↓
resume(task, command(P))
  ↓
workflow continues or cancels correctly
```

### 10.2 Retry after accepted resume

如果第一次 resume 已经 durable 推进到后续 checkpoint，但 caller 在收到响应前失败，再次提交同一 `pause_id` 必须得到：

```text
WORKFLOW_RESUME_STALE
```

不能第二次应用同一个 human navigation decision。

这只保证 Workflow Orchestrator navigation correlation；它不替代其他 owner 的 side-effect idempotency / crash recovery。

### 10.3 Concurrent resume non-goal

v1 不承诺两个进程同时对同一 `pause_id` 提交 command 时的全局 exactly-once arbitration。

要求仅为：

- 串行/可观察的第二次提交必须 stale；
- 不得新增隐藏 process-local lock 作为 durability guarantee；
- 真正 multi-client command receipt / idempotency ledger 必须在 MCP/Agent front-door capability 中单独设计并落在明确 owner。

---

## 11. Checkpoint serialization and validation

private graph state 增加 JSON-compatible：

```text
pending_interaction = {
  pause_id,
  kind,
  subject_ref: {ref_id, content_hash},
  allowed_resume_kinds: [...]
}
```

必须提供显式 encode/decode；禁止 pickle/object identity。

`graph_state_to_checkpoint_view()` 必须继续：

- 拒绝 `FORBIDDEN_AUTHORITATIVE_STATE_KEYS`；
- 对 pending interaction exact-key validate；
- 对 enum/action set fail closed；
- 强制 human wait / async wait mutually exclusive；
- 对 malformed legacy pause 失败，不进行 best-effort 猜测。

`checkpoint_view_to_graph_state()` 只用于 framework-neutral state projection，不得把外部 owner object 放回 graph state。

---

## 12. Security and authorization boundary

本能力只提供 **state correlation**，不提供 caller authorization。

因此：

```text
pause_id possession != authorization
```

在 MCP/Agent front door 落地前，`WorkflowOrchestratorPort` 被视为 trusted internal boundary。

未来 front door 必须独立验证：

- authenticated principal；
- task access；
- interaction/action permission；
- audit identity；

然后才可构造 `WorkflowResumeCommand`。

Workflow Orchestrator 不应为了提前解决未来 IAM 而持有用户目录、role model 或 approval authority。

---

## 13. API compatibility discipline

本能力会扩展 framework-neutral public contracts，因此 implementation plan 必须在第一个 production-code task 前完成：

```text
public export census
runtime caller census
test caller census
Host/plugin caller census
persisted checkpoint compatibility census
```

规则：

1. 新 `PendingInteractionView` 为 additive export；
2. `WorkflowCheckpointView.pending_interaction` 为 additive optional field；
3. `WorkflowPhase.CANCELLED` 为 additive enum value；
4. `WorkflowResumeCommand.pause_id` 的 constructor 兼容策略必须由 caller census 决定；
5. 若存在 repo 外 Host/plugin consumer，必须先提供 additive adapter/deprecation path；
6. 不允许为了本能力顺手删除 `interaction_ref`、旧 phase 或其它 legacy contract。

---

## 14. Testing and acceptance

### 14.1 Contract tests

必须覆盖：

- `PendingInteractionView` validation；
- `pause_id` non-empty；
- allowed resume kinds non-empty / unique；
- checkpoint human/async wait mutual exclusion；
- `WorkflowResumeCommand` exact v1 payload rules；
- `CANCELLED` stable projection。

### 14.2 In-memory runtime tests

必须覆盖：

1. start 后停在 Operation Proposal，checkpoint 暴露 pending interaction；
2. correct `pause_id + ACCEPT` 继续到 parameter binding/下一 wait；
3. correct `pause_id + REJECT` 到 `CANCELLED`；
4. wrong `pause_id` => `WORKFLOW_RESUME_STALE` 且 checkpoint 不变；
5. wrong `resume_kind` => `WORKFLOW_RESUME_MISMATCH` 且 checkpoint 不变；
6. `resume(None)` 发给 human wait => fail closed；
7. human command 发给 async wait => fail closed；
8. 重放已消费 pause => stale；
9. LangGraph types 不泄漏到 public return/error。

### 14.3 Legacy checkpoint tests

必须构造升级前 Operation Proposal checkpoint，证明：

- 新 runtime 可投影 deterministic synthetic `pause_id`；
- restart 后 synthetic id 不变化；
- ACCEPT/REJECT 可完成一次迁移；
- 未知 legacy interrupt shape fail closed。

### 14.4 PostgreSQL restart acceptance

PostgreSQL 17 gate 必须证明：

- old runtime instance pause；
- saver/connection 显式关闭；
- new runtime/new saver 读取同一 pending interaction；
- resume 后继续；
- 第二次相同 command stale；
- checkpoint delete/corruption 不会修改 external authoritative owner state。

### 14.5 Repository gates

最终 implementation PR 必须至少通过：

- Python 3.11 canonical 两种 pytest mode；
- Python 3.14 compatibility；
- repository Ruff **new diagnostics = 0**；
- Workflow Orchestrator PostgreSQL verification；
- Durable Persistence / Execution Saga PostgreSQL regression；
- Revit Core；
- .NET 10 Host-neutral compatibility。

本能力不修改 Host-visible production contract，不要求在此阶段重跑真实 AutoCAD/Revit acceptance。后续 real E2E / real Host capability 仍必须执行其独立 live gates。

---

## 15. Failure handling

HITL resume 的原则是 fail closed：

```text
bad/missing pause correlation
wrong action
wrong wait mode
malformed checkpoint
unknown legacy interrupt
    => no graph progression
    => no domain side effect
    => stable WorkflowStateError
```

runtime 在 validation 通过前不得调用 LangGraph `Command(resume=...)`。

如果 validation 通过后 deterministic/domain service 失败，继续使用现有 `WORKFLOW_SERVICE_FAILURE` 归一化并保留原始 cause；本能力不改变 service owner 的业务错误语义。

---

## 16. Observability

本能力只要求 workflow-local、非敏感 observability：

```text
task_id
pause_id
pending kind
resume_kind
result = accepted | rejected | stale | mismatch | invalid
checkpoint/restart path
```

日志不得序列化完整 domain payload，也不得把 `pause_id` 当 secret 输出策略的替代品。

具体 tracing/metrics backend 不在本设计范围。

---

## 17. Rejected alternatives

### 17.1 Keep current generic `interrupt()` only

拒绝。调用方无法稳定识别 pending human state，旧 command 无 correlation，human/async wait 公共语义混合。

### 17.2 Make Step26 InteractionSession own all HITL

拒绝。Step26 拥有 Host-native value acquisition session，不应成为所有 workflow human decisions 的通用 truth；这会把 operation proposal / future workflow decisions错误地耦合到 Host interaction owner。

### 17.3 Add a new authoritative Human Interaction Service now

拒绝。第一步只需要 workflow-local decision/navigation state；引入新的 durable service、DB owner 和 delivery protocol超出当前需求。若未来 multi-client inbox、audit workflow 或 long-lived delegated approval确实要求独立 owner，再通过独立 design 引入。

### 17.4 Treat `pause_id` as an authorization token

拒绝。Correlation 与 authorization 是不同责任；front door 尚未进入当前 capability step。

### 17.5 Bump checkpoint namespace and abandon old in-flight tasks

拒绝。ADR-010 已把 checkpoint 作为 durable owner state；runtime upgrade 不能静默使合法旧 task 不可恢复。

### 17.6 Put proposal body into checkpoint for UI convenience

拒绝。违反 HITL Payload Ownership Contract 与 single-authoritative-owner；UI 必须通过 stable ref 重新查询 authoritative owner。

---

## 18. Implementation boundaries

预计实现只应触及：

```text
platform/orchestrator/src/design_orchestrator/
  workflow_contracts.py
  workflow_port.py                 # 仅在签名/文档需要时
  langgraph_state.py
  langgraph_graph.py
  langgraph_runtime.py
  __init__.py

tests/orchestrator/
tests/architecture/                # ownership/framework boundary guard if needed
.github/workflows/                  # 仅在现有 PostgreSQL gate 无法覆盖新 acceptance 时
```

不应修改：

```text
Step26 Interaction Coordinator ownership
Step28/32 approval/gateway authority
Execution Saga state machine
Host plugin/sidecar contract
semantic owner contract
MCP/Agent front door
```

若实现阶段发现必须改上述 owner boundary，必须停止并回到 design review，不得把 hidden scope expansion 混入 HITL PR。

---

## 19. Completion criteria

Capability Phase HITL pause/resume 只有同时满足以下条件才算完成：

1. `PendingInteractionView` 成为稳定 framework-neutral contract；
2. Operation Proposal pause 在 checkpoint 中拥有 durable `pause_id`；
3. ACCEPT / REJECT 均有明确 graph terminal/continuation semantics；
4. human wait 与 external async wait 对公共 caller 明确分离；
5. stale/mismatch/invalid resume 全部 fail closed，且失败前不推进 graph；
6. process restart 后同一 pending interaction 可恢复；
7. 合法 legacy Operation Proposal checkpoint 可一次性迁移；未知 legacy shape fail closed；
8. checkpoint 仍不拥有任何外部 domain authoritative truth；
9. PostgreSQL restart acceptance 与 repository regression 全绿；
10. 没有借本能力提前实现 MCP front door、approval authority、compensation executor 或 Host-visible behavior。

满足以上条件后，handoff 才允许进入下一能力：

```text
real E2E workflow
```
