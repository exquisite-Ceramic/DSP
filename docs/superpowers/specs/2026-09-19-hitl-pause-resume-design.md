# Capability Phase — HITL Pause / Resume Design

**Status:** Approved design  
**Date:** 2026-09-19  
**Base:** `main@32f1f1f1c7982a63bb68be25d7ac6ea208e92457`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`  
**Architecture authority:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`  
**Persistence authority:** `docs/adr/ADR-008-durable-state-persistence-ownership.md`  
**Handoff:** `docs/superpowers/specs/2026-09-19-capability-phase-handoff.md`  
**Ownership contract:** `docs/superpowers/specs/2026-09-19-hitl-payload-ownership-contract.md`

## 1. Purpose

本设计定义 Capability Phase 的第一个能力增量：把 ADR-010 已存在的 LangGraph `interrupt()` / `resume()` 骨架收敛成一个可由调用方稳定观察、可跨进程恢复、可 fail-closed 校验的 **HITL pause/resume contract**。

它解决的不是“如何再加一个 interrupt”，而是五个实际缺口：

1. 调用方必须能从 framework-neutral checkpoint 明确知道 workflow 当前是否在等待人类输入、等待的是哪一种输入，以及该输入关联哪个 stable subject；
2. human resume 必须与当前 durable pause identity 相关联，旧命令、错误命令和发往异步 owner wait 的 human command 都不能推进 graph；
3. 进程重启后，同一个 pause 必须仍以同一个公共 identity 被观察和恢复；
4. HITL checkpoint 必须继续遵守 single-authoritative-owner：只持有 workflow navigation state 和 stable refs，不复制 Operation / ChangeSet / Approval / Saga / Host / Semantic authoritative truth；
5. checkpoint 中的 workflow-local `StableRef` 必须真正跨进程可解析。当前 `operation_ref` 的 backing `WorkflowArtifactStore` 只有 protocol，现有 E2E 使用 process-local memory store；这不足以支持“在 Operation Proposal gate 暂停后重启再继续”。

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

本设计只冻结第一步及其必需的 restart-durability prerequisite，不提前实现后四步。

---

## 2. Existing baseline

当前 merged-main 已具备：

- `Workflow Orchestrator` 是 workflow progression/checkpoint/HITL/retry coordination 的 authoritative logical owner；
- LangGraph 只是 v0.6 reference runtime，framework type 不进入公共 contract；
- `WorkflowOrchestratorPort` 已暴露 `start / resume / get_checkpoint`；
- `WorkflowResumeCommand` 已存在；
- graph 的 `await_operation_proposal` 已调用 `interrupt()`；
- `await_async_operation` 已用同一 LangGraph interrupt primitive 等待外部 `AsyncOperationRef`；
- 现有 PostgreSQL E2E 已使用 `WorkflowResumeCommand(resume_kind="ASYNC_OPERATION_COMPLETED", ...)` 恢复 external async wait；
- `resume(task_id, None)` 的 port contract 继续表示 poll/recheck authoritative owner state；
- PostgreSQL checkpoint 已独占 `orchestrator_checkpoint` owner schema，并已有 restart/recovery acceptance；
- `DefaultWorkflowServices.resolve_operations()` 把真实 `OperationResolver` 结果写入 `WorkflowArtifactStore` 后只向 graph 返回 `StableRef`；
- `DefaultWorkflowServices.bind_parameters()` 必须通过 `WorkflowArtifactStore.get(operation_ref)` 取回 operation-space artifact 后才能做 binding membership validation；
- 当前 reference tests 的 `WorkflowArtifactStore` 是 `_MemoryArtifactStore`，旧 PostgreSQL E2E 的 restart 刻意发生在 parameter binding 之后，因此没有覆盖“pause 后仍需读取 operation artifact”的 crash window。

现状因此存在两个不同层面的缺口：

```text
HITL state gap:
  checkpoint 没有 public pending-human-interaction identity

restart data gap:
  operation_ref 持久化了
  但 ref 指向的 workflow-local artifact 未必持久化
```

此外，当前名为 `await_operation_proposal` 的 gate 在 graph state 中实际携带的是 `resolve_operations()` 产出的 **operation-space ref**。真正的 `OperationProposal` / `ParameterBindingInputs` 由后续 owner port 在 parameter binding 时提供。本能力不得把 operation-space artifact 谎称为 Approval 或完整 OperationProposal authoritative truth。

---

## 3. Scope

### 3.1 In scope

本能力实现：

- framework-neutral pending-human-interaction contract；
- durable `pause_id` correlation；
- 现有 Operation Proposal gate 的 `ACCEPT / REJECT` v1 HITL；
- human wait 与 external async wait 的公共语义分离；
- restart 后同一 pending interaction 的恢复；
- stale / mismatch / malformed human resume 的 fail-closed 行为；
- 保持既有 async completion/poll contract；
- Workflow Orchestrator 自己的 durable workflow-artifact backing store；
- 旧 in-flight Operation Proposal checkpoint 的受控兼容/rehydration；
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
- Temporal 或第二 workflow runtime；
- 重写现有 `ASYNC_OPERATION_COMPLETED` resume protocol；
- 建立一个可存任意领域对象的通用 blob/database store。

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
checkpoint contract version
```

这些内容决定“这个 task 正在等待哪一个 workflow-local human decision”。

### 4.2 Workflow Orchestrator does not own external domain truth

Pending interaction / checkpoint 不得持有或成为以下内容的 authoritative copy：

```text
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

### 4.3 Workflow-local deterministic artifacts remain Orchestrator-owned

ADR-010 implementation plan 已冻结 `WorkflowArtifactStore`：它只保存 **没有其他 authoritative owner 的 workflow-local deterministic intermediate artifacts**，例如真实 `OperationResolver` 生成的 operation-space artifact、真实 `ParameterBinder` 生成的 bound proposal artifact。

这些 artifact 不属于 LangGraph checkpoint，但属于同一个 logical `Workflow Orchestrator` owner。

因此：

```text
Workflow checkpoint
  = navigation / wait / stable refs

Workflow artifact store
  = ref 指向的 workflow-local deterministic intermediate artifacts
```

二者不能合并成“把完整 artifact 直接塞进 checkpoint”。

### 4.4 Step26 InteractionSession remains a separate owner

Step26 的 `InteractionSession` 继续由 **Interaction Coordinator** 持有，并通过：

```text
AsyncOperationRef(kind=INTERACTION_SESSION, ...)
```

表示 workflow 正在等待 Host-native interaction completion。

它不是 `PendingInteractionView`，也不是 Workflow Artifact。

### 4.5 Operation Proposal gate is not execution approval

现有 gate 的 stable subject 是 operation-space / workflow-local artifact ref。`OPERATION_PROPOSAL_ACCEPTED` 只表示：

```text
允许 workflow 继续到 parameter binding，
随后由既有 owner port 提供/刷新 ParameterBindingInputs，
并由真实 ParameterBinder 按 persisted operation space 校验 proposal。
```

它不表示：

```text
ApprovalRecord 已批准
ExecutionGrant 已签发
该 ChangeSet 已获执行授权
```

Step28/Step32/Gateway authority 保持不变。

---

## 5. Hard prerequisite — durable WorkflowArtifactStore

### 5.1 Why this is merge-blocking

HITL pause 发生在 `resolve_operations()` 之后、`bind_parameters()` 之前。

如果：

```text
operation_ref 已写入 durable checkpoint
但 operation-space artifact 只存在于旧进程 memory store
```

那么新进程即使恢复了 LangGraph checkpoint，也会在 `bind_parameters()` 的 `artifact_store.get(operation_ref)` 失败。

因此“pause identity 可恢复”但“业务 continuation 不可恢复”不算 HITL capability 完成。

这属于 Capability handoff 允许的 **data-integrity hard prerequisite**，不是普通 hygiene。

### 5.2 Reference persistence

v1 reference implementation 新增 Workflow Orchestrator 自己的 PostgreSQL namespace：

```text
orchestrator_artifact
```

与：

```text
orchestrator_checkpoint
```

属于同一个 logical owner，但使用不同 repository/migration namespace：

```text
orchestrator_checkpoint
  = LangGraph checkpoint/navigation persistence

orchestrator_artifact
  = workflow-local deterministic artifact persistence
```

它们都不得获得其他 owner schema 的直接读写权。

PostgreSQL/schema/table detail 仍是 infrastructure detail，不进入 canonical/public contract。

### 5.3 WorkflowArtifactStore durability contract

公共 service-side protocol 保持：

```python
class WorkflowArtifactStore(Protocol):
    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef: ...
    def get(self, ref: StableRef) -> object: ...
```

但 production/reference adapter 必须满足：

1. `put` 成功返回的 ref 在 process restart 后可由新的 store instance `get`；
2. `content_hash` 必须是 artifact deterministic normalized representation 的 lowercase SHA-256；
3. read 时必须重新验证 persisted bytes/decoded value 的 content hash；
4. same logical `kind + content_hash` 重复 `put` 必须 idempotent，不得创建语义不同的 artifact；
5. `ref_id` 对 caller 是 opaque，不得要求解析数据库主键或 schema；
6. serializer/codec 必须显式、versioned、JSON-compatible；禁止 pickle、Python repr、进程地址或任意 object serialization；
7. v1 至少为当前 `operation_resolution` 与 `bound_operation_proposal` artifact 提供 round-trip codec；
8. unknown artifact kind/version fail closed。

Unit tests 仍可使用 memory adapter；**任何 restart acceptance 不得使用 memory adapter 证明 durability**。

### 5.4 Write ordering and crash safety

Graph/service 必须先 durable `put` artifact，再把其 ref 返回给 node 并进入 checkpoint。

允许的 crash window：

```text
artifact committed
checkpoint not committed
=> orphan workflow artifact
=> safe; later owner-local GC may reclaim
```

禁止出现：

```text
checkpoint committed with ref
artifact was never durable
```

本能力不要求跨 `orchestrator_artifact` / `orchestrator_checkpoint` 建立数据库 2PC。正确的 write ordering + idempotent artifact put 足够保证 ref 不悬空。

### 5.5 Artifact retention

`orchestrator_artifact` 不受 `Checkpoint Retention Contract` 的 checkpoint-row GC 直接管理，但必须满足最小依赖规则：

```text
artifact ref reachable from active/paused workflow checkpoint
=> artifact GC FORBIDDEN
```

terminal workflow 的 artifact retention 可由后续 Workflow Orchestrator persistence policy 配置，但不能在仍存在合法 checkpoint/audit dependency 时提前删除。

Artifact GC 不得级联删除任何外部 owner state。

---

## 6. Public HITL contracts

### 6.1 PendingInteractionKind

v1 只冻结一个 human-pause kind：

```python
class PendingInteractionKind(str, Enum):
    OPERATION_PROPOSAL = "OPERATION_PROPOSAL"
```

该名称沿用现有 graph gate；其 v1 `subject_ref` 是 durable operation-space artifact ref，不表示 checkpoint 内存在完整 LLM proposal body。

### 6.2 PendingInteractionView

新增 framework-neutral contract：

```python
@dataclass(frozen=True, slots=True)
class PendingInteractionView:
    pause_id: str
    kind: PendingInteractionKind
    subject_ref: StableRef
    allowed_resume_kinds: tuple[str, ...]
```

v1 gate：

```text
kind = OPERATION_PROPOSAL
subject_ref = current durable operation-space ref
allowed_resume_kinds = (
  OPERATION_PROPOSAL_ACCEPTED,
  OPERATION_PROPOSAL_REJECTED,
)
```

规则：

1. `pause_id` 必填、非空；
2. `subject_ref` 必须是 stable ref，不能内嵌 artifact body；
3. `allowed_resume_kinds` 必须非空、无重复；
4. v1 不在公共 pending view 中加入任意 domain `payload`；
5. 后续 front door 若要展示 operation-space/proposal 细节，必须通过 Workflow Orchestrator 的稳定 read boundary 读取 artifact/ref；本能力不把 artifact body 放进 checkpoint。

### 6.3 WorkflowCheckpointView

增加：

```python
pending_interaction: PendingInteractionView | None = None
```

冻结：

```text
pending_interaction != None
  => async_operation_ref == None
  => interaction_ref == None

async_operation_ref != None or interaction_ref != None
  => pending_interaction == None
```

即公共 checkpoint 不能同时宣称“等人”和“等外部 interaction/owner”。

现有 `interaction_ref` 本能力不删除、不重定义。

### 6.4 WorkflowResumeCommand

保留现有 constructor，并以 additive optional field 增加 human correlation：

```python
@dataclass(frozen=True, slots=True)
class WorkflowResumeCommand:
    resume_kind: str
    payload: Mapping[str, object] = field(default_factory=dict)
    pause_id: str | None = None
```

规则：

```text
human pending interaction
  => pause_id MUST be non-empty

external async wait
  => existing command/poll semantics remain valid
  => pause_id MUST be None
```

v1 human gate：

```text
OPERATION_PROPOSAL_ACCEPTED => payload MUST be empty
OPERATION_PROPOSAL_REJECTED => payload MUST be empty
```

现有 async completion signal 继续允许其既有 owner-specific payload，例如：

```text
resume_kind = ASYNC_OPERATION_COMPLETED
payload.operation_id = <external operation id>
pause_id = None
```

human payload 不得携带 ChangeSet、Approval、完整 OperationProposal 或其他 owner authoritative DTO。

---

## 7. Checkpoint contract version and pause identity

### 7.1 Private checkpoint contract version

新 graph state 增加 runtime-private：

```text
checkpoint_contract_version = 2
```

它不进入 `WorkflowCheckpointView` public contract，只用于 adapter 正确地区分：

```text
legacy unversioned checkpoint
vs
new checkpoint corruption
```

规则：

- 新 workflow 从 initial state 起 MUST 写 `2`；
- version `2` 的 Operation Proposal wait 若缺 `pending_interaction`，必须 `WORKFLOW_CHECKPOINT_INVALID`；
- version 缺失只表示“可能是 legacy”，不能单凭 phase 自动放行；还必须满足 §10 的完整 legacy shape。

### 7.2 `pause_id` is workflow-local

`pause_id`：

- 由 Workflow Orchestrator 创建；
- 只用于 durable pause correlation / stale-command detection；
- 不进入任何领域 owner identity；
- 不是 auth token；
- 不要求调用方解析其内部结构。

新 v2 workflow SHOULD 使用随机 UUID 形式的 opaque identity。

### 7.3 Persist before interrupt

不能在调用 `interrupt()` 的同一个未完成 node 中第一次生成 `pause_id`。

新 topology：

```text
resolve_operations
  # artifact 已 durable put
  ↓
prepare_operation_proposal_pause
  # 创建并 checkpoint PendingInteractionView
  ↓
await_operation_proposal
  # 只读取已持久化 pending interaction
  # 调用 interrupt()
```

prepare node 不产生 external domain side effect。

---

## 8. Runtime resume semantics

### 8.1 Human resume

当 `pending_interaction != None` 时，`resume(task_id, command)` 必须解释为 human resume。

在构造 LangGraph `Command(resume=...)` 之前按顺序验证：

```text
1. task exists
2. checkpoint is structurally valid
3. pending interaction exists
4. command.pause_id is present
5. command.pause_id == pending_interaction.pause_id
6. command.resume_kind is allowed
7. human payload satisfies exact kind schema
8. pending subject artifact is resolvable / valid for continuation
```

失败不得调用 graph，不得消费 human pause。

### 8.2 External async resume remains compatible

当 `async_operation_ref != None` 且 `pending_interaction == None` 时：

```text
resume(task_id, None)
  = existing poll/recheck contract

resume(task_id, WorkflowResumeCommand(..., pause_id=None))
  = existing explicit async completion signal
```

本能力不重新定义 async owner payload schema。

任何 `pause_id != None` 的 human-correlated command 发往 external async wait 必须 fail closed。

### 8.3 Stable errors

新增/冻结：

```text
WORKFLOW_RESUME_INVALID
  malformed human command / wrong wait mode / invalid payload

WORKFLOW_RESUME_STALE
  human pause_id no longer matches current pending interaction

WORKFLOW_RESUME_MISMATCH
  pause_id matches but resume_kind is not allowed

WORKFLOW_ARTIFACT_UNAVAILABLE
  checkpoint ref exists but required workflow-owned artifact cannot be loaded,
  verified, or safely rehydrated
```

现有：

```text
WORKFLOW_NOT_FOUND
WORKFLOW_CHECKPOINT_INVALID
WORKFLOW_SERVICE_FAILURE
```

继续保持。

---

## 9. Graph behavior for the v1 human gate

### 9.1 Subject semantics

`resolve_operations()` 产生的是 persisted operation-space artifact/ref。

因此 v1 human gate 实际语义是：

```text
“允许当前 workflow 基于这个已冻结 operation space 继续取得/校验 ParameterBindingInputs 吗？”
```

它不是：

```text
“checkpoint 已经持有一个完整 LLM OperationProposal body 吗？”
```

后者不成立，本能力禁止通过命名掩盖该事实。

### 9.2 ACCEPT

`OPERATION_PROPOSAL_ACCEPTED`：

```text
clear pending interaction
  ↓
phase = PARAMETER_BINDING
  ↓
DefaultWorkflowServices.bind_parameters(operation_ref)
  ↓
existing owner port supplies current ParameterBindingInputs
  ↓
real ParameterBinder validates proposal against persisted operation space
```

### 9.3 REJECT

新增：

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

`CANCELLED` 只终止 workflow progression，不删除外部 owner state。

本能力不引入“编辑 proposal 后继续”或 replan UX。

---

## 10. Legacy in-flight checkpoint compatibility

### 10.1 Exact legacy shape

只有同时满足以下条件，unversioned checkpoint 才可进入 legacy Operation Proposal migration：

```text
checkpoint_contract_version absent
phase = AWAIT_OPERATION_PROPOSAL
operation_ref is valid StableRef
LangGraph snapshot has a real pending interrupt
pending_interaction absent
async_operation_ref absent
```

其它 unversioned/ambiguous interrupt shape 必须 `WORKFLOW_CHECKPOINT_INVALID`。

### 10.2 Synthetic pause identity

runtime adapter 在持有完整 snapshot 的层级派生：

```text
canonical legacy identity payload = compact UTF-8 JSON with sorted keys:
{
  "contract": "legacy-operation-proposal-pause-v1",
  "task_id": normalized_task_id,
  "operation_ref": {
    "ref_id": operation_ref.ref_id,
    "content_hash": operation_ref.content_hash
  }
}

pause_id = "legacy-op-proposal:" + sha256(canonical_json_bytes).hexdigest()
```

显式保留 `content_hash=null`，禁止无边界字符串拼接。

纯 `graph_state_to_checkpoint_view()` 看不到 LangGraph interrupt presence，因此不得仅凭 `phase` 自行制造 synthetic pause；legacy projection 只能由 runtime adapter 在完整 snapshot validation 后完成。

### 10.3 Legacy artifact recovery

旧 checkpoint 的 `operation_ref` 可能来自已经消失的 process-local artifact store。

human command 被送入 LangGraph 前，runtime/service 必须先保证 operation artifact 可恢复：

```text
A. new durable artifact store can resolve old ref
   -> verify content hash
   -> continue

B. old ref cannot resolve, but context_snapshot_ref + expected content_hash are present
   -> call existing authoritative owner port to reload exact snapshot-bound OperationResolutionInputs
   -> rerun real OperationResolver
   -> compute deterministic artifact hash
   -> require recomputed hash == old operation_ref.content_hash
   -> durable put into orchestrator_artifact
   -> replace workflow-local operation_ref with new durable ref
   -> continue

C. input unavailable / hash absent / hash mismatch / decode failure
   -> WORKFLOW_ARTIFACT_UNAVAILABLE
   -> do not consume human pause
   -> no graph progression
```

Rehydration 使用真实 `OperationResolver`，不得复制 eligibility algorithm 到 runtime adapter。

### 10.4 Legacy human command

升级后 caller 必须先读取 checkpoint 获得 synthetic `pause_id`。

没有 `pause_id` 的旧 human command 不得继续绕过 correlation；它必须 `WORKFLOW_RESUME_INVALID`。若 caller census 发现 repo 外 consumer 无法原子升级，implementation plan 必须提供受限 compatibility adapter 与明确退场条件，不能在 core runtime 永久保留 uncorrelated human resume。

### 10.5 Node compatibility

新 graph 必须保留 `await_operation_proposal` node identity，使旧 checkpoint 的 pending task 可被新 graph 识别。

当旧 node 在 resume/re-entry 时发现 unversioned exact legacy state，它只能走 §10.3 的已验证 migration path；成功 transition 后必须写入：

```text
checkpoint_contract_version = 2
```

并进入新 contract。

---

## 11. Restart and crash semantics

### 11.1 New v2 pause restart

必须证明：

```text
runtime A + saver A + artifact_store A
  ↓
resolve operation -> durable artifact ref
  ↓
persist pending interaction P
  ↓
close runtime/saver/artifact store
  ↓
runtime B + saver B + artifact_store B
  ↓
get_checkpoint(task) == same pause_id/kind/subject_ref
  ↓
artifact_store B resolves subject_ref
  ↓
resume(task, human command(P))
  ↓
parameter binding succeeds
```

### 11.2 Retry after accepted resume

如果第一次 human resume 已 durable 推进，但 caller 在收到响应前失败，再交同一 `pause_id` 必须：

```text
WORKFLOW_RESUME_STALE
```

这只保证 Workflow Orchestrator navigation correlation，不替代其他 owner 的 idempotency/recovery。

### 11.3 Concurrent resume non-goal

v1 不承诺两个进程同时提交同一 human `pause_id` 时的全局 exactly-once arbitration。

要求：

- 串行可观察的第二次提交必须 stale；
- 不得用 process-local lock 冒充 durability；
- multi-client command receipt/idempotency ledger 留给 MCP/Agent front-door capability 独立设计。

---

## 12. Checkpoint serialization and validation

private graph state 增加 JSON-compatible：

```text
checkpoint_contract_version = 2
pending_interaction = {
  pause_id,
  kind,
  subject_ref: {ref_id, content_hash},
  allowed_resume_kinds: [...]
}
```

必须显式 encode/decode；禁止 pickle/object identity。

`graph_state_to_checkpoint_view()` 必须：

- 拒绝 `FORBIDDEN_AUTHORITATIVE_STATE_KEYS`；
- exact-key validate pending interaction；
- 校验 enum/resume-kind set；
- 强制 human/external wait mutually exclusive；
- 对 v2 malformed state fail closed；
- 不自行猜测 legacy interrupt presence。

`checkpoint_view_to_graph_state()` 不得把 artifact body 或外部 owner object 放回 checkpoint。

---

## 13. Security and authorization boundary

本能力只提供 state correlation，不提供 caller authorization：

```text
pause_id possession != authorization
```

在 MCP/Agent front door 落地前，`WorkflowOrchestratorPort` 是 trusted internal boundary。

未来 front door 必须独立验证 authenticated principal、task access、action permission 与 audit identity 后才可构造 human command。

`orchestrator_artifact` 也不是用户内容直读数据库；外部 caller 只能通过未来稳定 read contract 获取需要的 presentation/read model。

---

## 14. API and persistence compatibility discipline

Implementation Plan 在第一个 production-code task 前必须完成：

```text
public export census
runtime caller census
test caller census
Host/plugin caller census
persisted checkpoint census
WorkflowArtifactStore implementation census
```

规则：

1. `PendingInteractionView` 为 additive export；
2. `WorkflowCheckpointView.pending_interaction` 为 additive optional field；
3. `WorkflowPhase.CANCELLED` 为 additive enum value；
4. `WorkflowResumeCommand.pause_id` 作为 trailing optional field 增加，保持现有 async constructor source compatibility；
5. 新 human pending 必须要求 non-empty `pause_id`；
6. 既有 async resume/poll contract 不删除、不重命名；
7. `WorkflowArtifactStore` protocol 保持 framework-neutral；PostgreSQL-specific adapter 不泄漏到 service/public contract；
8. 不删除 `interaction_ref`、旧 phase 或其它 legacy contract；
9. repo 外 consumer 若存在，必须单独证明 behavioral compatibility。

---

## 15. Testing and acceptance

### 15.1 Durable artifact tests

PostgreSQL reference tests必须证明：

- artifact tables 只存在于 `orchestrator_artifact`；
- `orchestrator_checkpoint` / `orchestrator_artifact` 不读写其他 owner schema；
- `operation_resolution` 与 `bound_operation_proposal` codec round-trip；
- new store instance 可读取旧 store instance 写入的 ref；
- content-hash mismatch/corruption fail closed；
- duplicate `kind + hash` put idempotent；
- unknown codec version fail closed。

### 15.2 Contract tests

覆盖：

- `PendingInteractionView` validation；
- `pause_id` non-empty；
- allowed resume kinds non-empty/unique；
- checkpoint contract version validation；
- human/external wait mutual exclusion；
- human `WorkflowResumeCommand` v1 payload rules；
- existing async command with `pause_id=None` remains valid；
- `CANCELLED` projection。

### 15.3 In-memory runtime tests

覆盖：

1. start 后 checkpoint 暴露 pending interaction；
2. correct `pause_id + ACCEPT` 继续；
3. correct `pause_id + REJECT` 到 `CANCELLED`；
4. wrong pause => stale 且 checkpoint 不变；
5. wrong kind => mismatch 且 checkpoint 不变；
6. `resume(None)` 发给 human wait fail closed；
7. human-correlated command 发给 async wait fail closed；
8. existing `ASYNC_OPERATION_COMPLETED` + `pause_id=None` 继续合法；
9. consumed human pause replay => stale；
10. v2 checkpoint missing pending state => checkpoint invalid；
11. LangGraph types 不泄漏。

### 15.4 Legacy migration tests

构造真实旧 shape，证明：

- synthetic pause id deterministic across new runtime instances；
- old artifact ref 可直接读取时正常继续；
- old memory-only ref 丢失时可从 exact snapshot inputs 重新跑真实 resolver；
- rehydrated hash 必须等于旧 ref hash；
- mismatch => `WORKFLOW_ARTIFACT_UNAVAILABLE` 且 pause 未消费；
- unknown legacy interrupt => checkpoint invalid；
- successful legacy continuation upgrades contract version to 2。

### 15.5 PostgreSQL restart acceptance

必须把 restart 移到 **human pause** 上，而不是只在 parameter binding 后重启：

```text
resolve operation
→ durable workflow artifact
→ human pause
→ close runtime/checkpointer/artifact store
→ new runtime/new stores
→ same pending interaction
→ subject artifact resolves
→ ACCEPT
→ real ParameterBinder runs
→ existing AsyncOperationRef path
→ existing async completion/recovery
→ complete
```

同时证明 checkpoint/artifact deletion/corruption 不会修改外部 authoritative owner state。

### 15.6 Repository gates

最终 implementation PR 至少通过：

- Python 3.11 canonical 两种 pytest mode；
- Python 3.14 compatibility；
- Ruff new diagnostics = 0；
- Workflow Orchestrator PostgreSQL verification；
- Durable Persistence / Execution Saga PostgreSQL regression；
- Revit Core；
- .NET 10 Host-neutral compatibility。

本能力不修改 Host-visible contract，因此不在此阶段要求 real AutoCAD/Revit gate；后续 real E2E / real Host capability 仍必须执行 live acceptance。

---

## 16. Failure handling

Human resume fail closed：

```text
bad/missing pause correlation
wrong human action
wrong wait mode
malformed v2 checkpoint
unknown legacy interrupt
unresolvable/corrupt workflow artifact
legacy rehydration hash mismatch
    => no human pause consumption
    => no graph progression
    => no external domain side effect
    => stable WorkflowStateError
```

existing async command/poll path 继续按现有 owner/recovery validation 运行。

Artifact `put` 成功但 checkpoint 失败只产生 owner-local orphan artifact，不得影响外部 owner state。

---

## 17. Observability

至少记录 workflow-local 非敏感字段：

```text
task_id
pause_id (human only)
pending kind
resume_kind
resume_mode = human | async | poll
artifact_ref/content_hash
artifact_source = durable | rehydrated
checkpoint_contract_version
result = accepted | rejected | stale | mismatch | invalid | unavailable | continued
```

不得记录完整 domain payload，也不得把 `pause_id` 当 auth secret。

---

## 18. Rejected alternatives

### 18.1 Keep generic `interrupt()` only

拒绝：没有稳定 human pending identity/correlation。

### 18.2 Put operation/proposal body into checkpoint

拒绝：违反 ADR-010 / HITL ownership；checkpoint 不是 artifact/domain store。

### 18.3 Continue using process-local WorkflowArtifactStore for paused workflows

拒绝：会产生“checkpoint 可恢复但 ref backing data 丢失”的伪 durability。

### 18.4 Make Step26 InteractionSession own all HITL

拒绝：Host-native value acquisition 与 workflow-local human decision 是不同 owner/state。

### 18.5 Add a new generic Human Interaction Service now

拒绝：当前只需要 workflow-local decision；独立 durable human inbox 等需求留给 front-door capability。

### 18.6 Treat `pause_id` as authorization

拒绝：correlation 与 authorization 分离。

### 18.7 Bump checkpoint namespace and abandon old tasks

拒绝：durable owner upgrade 不得静默遗弃合法 in-flight task；无法安全恢复时必须显式 error/replan，而不是“task 不存在”。

### 18.8 Rewrite existing async completion protocol

拒绝：当前 PostgreSQL E2E 已验证该路径；HITL capability 没有理由顺带替换。

### 18.9 Put workflow artifacts in another domain owner schema

拒绝：`ResolutionResult`/`BoundOperationProposal` 在当前 ADR-010 adapter 中是 Workflow Orchestrator 自己的 deterministic intermediate artifacts；跨 owner 共享表会破坏 ADR-008。

---

## 19. Implementation boundaries

预计实现会触及：

```text
platform/orchestrator/src/design_orchestrator/
  workflow_contracts.py
  workflow_services.py              # 仅增加必要 recovery/read contract 时
  default_workflow_services.py
  workflow_port.py                  # 仅签名/文档需要时
  langgraph_state.py
  langgraph_graph.py
  langgraph_runtime.py
  artifact_postgres.py              # reference durable artifact adapter
  __init__.py

tests/orchestrator/
tests/architecture/
.github/workflows/workflow-orchestrator.yml  # 把 artifact restart acceptance 放进现有 owner gate
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

若实现发现必须改变这些 owner boundary，必须停止并回到 design review。

---

## 20. Completion criteria

Capability Phase HITL pause/resume 只有同时满足以下条件才算完成：

1. `PendingInteractionView` 是稳定 framework-neutral contract；
2. Operation Proposal gate 在 checkpoint 中拥有 durable `pause_id`；
3. `checkpoint_contract_version=2` 能区分 legacy 与新 checkpoint corruption；
4. checkpoint 引用的 workflow-local operation artifact 在新进程可解析，reference implementation 使用 owner-local durable `orchestrator_artifact`；
5. ACCEPT / REJECT 有明确 continuation/terminal semantics；
6. human wait 与 external async wait 对公共 caller 分离，同时既有 async completion/poll contract 保持可用；
7. stale/mismatch/invalid/unavailable human resume 全部 fail closed，失败前不推进 graph；
8. new v2 process restart 后同一 pending interaction + subject artifact 都可恢复；
9. exact legacy Operation Proposal checkpoint 可直接恢复或 hash-verified rehydrate；无法安全恢复时显式 fail closed；
10. checkpoint/artifact store 均不复制其他 owner authoritative truth；
11. PostgreSQL restart acceptance 与 repository regression 全绿；
12. 没有借本能力提前实现 MCP front door、approval authority、compensation executor 或 Host-visible behavior。

满足以上条件后，Capability handoff 才允许进入：

```text
real E2E workflow
```
