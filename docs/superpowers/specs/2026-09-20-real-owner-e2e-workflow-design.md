# Capability Phase — Real-Owner E2E Workflow Design

**Status:** Baseline approved — Amendment A Written-Spec Review Gate  
**Date:** 2026-09-20  
**Base:** `main@c92fe302d22669f5cefea1946281e9b456e0fea7`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`  
**Workflow authority:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`  
**Persistence authority:** `docs/adr/ADR-008-durable-state-persistence-ownership.md`  
**Delivery authority:** `docs/adr/ADR-009-cross-owner-delivery-crash-recovery.md`  
**Capability handoff:** `docs/superpowers/specs/2026-09-19-capability-phase-handoff.md`  
**Predecessor design:** `docs/superpowers/specs/2026-09-19-hitl-pause-resume-design.md`  
**Checkpoint retention:** `docs/superpowers/specs/2026-09-19-checkpoint-retention-contract.md`

## 1. Purpose

本设计定义 Capability Phase 的第二个能力增量：在不改变 ADR-010 ownership、不把 LangGraph 变成领域 owner、也不把测试替身误称为 production composition 的前提下，建立一条 **real-owner E2E workflow** reference composition 与 acceptance path。

这里的 “real-owner” 有严格含义：

> workflow 内部已经存在于仓库中的 authoritative deterministic owners 使用真实实现；只有真正属于外部环境或 presentation boundary 的接口可以保留窄、确定性的测试 port。

它不等于“所有 Host、网络、数据库、UI、MCP 和产品入口都必须真实”。本阶段的任务是把当前 workflow runtime 与真实 owner 主干接起来，证明：

```text
workflow orchestration
  + real repository owners
  + durable workflow state
  + explicit narrow environment boundaries
```

能够形成一条可恢复、可 fail-closed、不会产生第二份领域真相的 E2E acceptance path。

Capability Phase handoff 的 successor 顺序保持不变：

```text
HITL pause/resume
  ↓
real E2E workflow                 <- 本设计
  ↓
semantic -> plan -> approve -> execute -> reconcile
  ↓
MCP/Agent front door
  ↓
real AutoCAD/Revit acceptance
```

本设计只冻结第二步，不提前实现后续三步。

---

## 2. Problem statement

ADR-010 已冻结：

```text
Workflow Orchestrator = authoritative logical workflow owner
LangGraph             = v0.6 reference runtime
Deterministic owners  = authoritative domain semantics
```

现有 workflow graph 已能通过 `WorkflowServices` / `DefaultWorkflowServices` 编排 resolver、HITL、binding、freshness、impact、ChangeSet、approval、planning、provider binding、execution/recovery 与 reconciliation 等阶段。

但当前 workflow E2E 的一个关键缺口是：测试侧可以使用 `_ScenarioOwners` 一类 scenario fake 来满足 external-owner port，因此“graph 能跑通”还不能证明真实 repository owner 可以按同一 contract 被生产式组合起来。

本阶段要消除的是 **composition gap**，而不是重写 workflow topology 或重写 owner semantics：

```text
已有：
LangGraph runtime
  -> DefaultWorkflowServices
     -> test-side scenario composition

缺少：
LangGraph runtime
  -> DefaultWorkflowServices
     -> reusable production/reference owner composition
        -> real canonical/V2 owners
```

因此本阶段必须回答：

1. production/reference composition 放在哪里；
2. 它可以做什么、禁止做什么；
3. 哪些 owner 必须是真实实现；
4. 哪些边界可以继续是窄 fixture；
5. restart 后 StableRef 无法解析时如何收口；
6. 如何证明 checkpoint 没有重新变成领域事实的第二 source of truth；
7. 如何保留现有快速 orchestration regression，而不是为了“真实”删除有价值的 scenario tests。

---

## 3. Baseline observations

以下是 `main@c92fe302d22669f5cefea1946281e9b456e0fea7` 的设计输入；这些是当前实现事实，不是长期 architecture contract：

- ADR-010 已要求 graph 只拥有 workflow progression/navigation、HITL、wait/re-entry、retry/replan coordination，不拥有 ChangeSet、Approval、ExecutionGrant、ProviderBinding、Execution Saga、Host commit 或 reconciliation truth；
- `DefaultWorkflowServices` 已作为 graph 与 deterministic services / external owners 之间的 service layer；
- repository 已具备真实的 Operation Resolver / Parameter Binder，以及 Impact、ChangeSet V2、Gateway V2、Execution Planning V2、Provider Binding V2、Execution Saga V2、Reconciliation V2 等 owner/service 主干；
- Execution Saga 已存在 PostgreSQL durability path，可作为本阶段 restart/recovery acceptance 的真实 durable owner；
- 当前 Gateway V2 baseline 仍存在 process-local/in-memory store 路径，因此不能把“任意 owner ref 在任意进程重启后都必然可解析”当作既成事实；
- HITL predecessor 已建立 durable Workflow Orchestrator checkpoint / workflow-artifact recovery contract；
- checkpoint retention contract 已明确：恢复和审计领域事实时必须通过 stable refs 查询原 authoritative owner，checkpoint GC 不改变外部 owner 的 lifecycle/durability；
- 当前 repository census 没有发现一个应当被本阶段强行提升为 authoritative owner 的通用 `platform/preview`；
- 当前 workflow E2E 中可明确识别的 concrete scenario composition 位于 test side；本设计不把 Python structural protocol 的“显式继承数量”误当作完整实现 census。

本设计后续的 architecture rule 不应冻结这些实现偶然性，例如具体 module 文件名、具体 store class、具体 PostgreSQL table name。

---

## 4. Goals

本阶段必须实现以下设计目标：

1. 提供一个可复用的 production/reference composition，使现有 workflow runtime 可以连接真实 repository authoritative owners；
2. 保持 graph topology 与 ADR-010 ownership 不变；
3. 保持 `WorkflowServices` / `DefaultWorkflowServices` 作为 workflow-facing service boundary，不让 LangGraph node 直接依赖 owner internals；
4. 真实 owner 的业务语义继续由其自身 canonical/V2 public API 承载；
5. `_ScenarioOwners` 继续服务快速 orchestration regression，但 real-owner acceptance path 不得使用它；
6. restart/re-entry 继续通过 stable refs 查询 authoritative owner，无法解析时 fail closed；
7. 证明真实 Saga/reconciliation 路径可以完成 `COMPLETED`，并且已有 recovery 语义不会触发第二次外部执行；
8. 证明本阶段没有重新引入 V1 consumer 或建立新的双轨 truth；
9. 把 external/environment/presentation fixtures 明确标记为 boundary doubles，而不是把它们伪装成 domain owners。

---

## 5. Explicit non-goals

本设计不实现：

- real AutoCAD acceptance；
- real Revit acceptance；
- MCP/Agent front door；
- 完整 `semantic -> plan -> approve -> execute -> reconcile` 产品场景；
- owner-wide PostgreSQL migration；
- 为所有 owner 建立 restart durability；
- 新建第二个 workflow runtime；
- 重写现有 LangGraph topology；
- 重写 `WorkflowServices` / `DefaultWorkflowServices` contract；
- automatic `DIVERGED` compensation executor；
- CV2-008 unblock；
- 新 outbox/inbox owner；
- delivery replay protocol redesign；
- owner-wide ADR-009 crash-recovery acceptance 扩张；
- 为 preview 人工创造新的 authoritative domain owner；
- legacy V1 retirement；
- Host support-matrix 扩张。

现有 ADR-009 delivery infrastructure 如果被真实 composition 自然经过，可以继续使用；“非目标”表示本阶段不得借 real E2E 之名扩张 delivery ownership、durability migration 或 replay architecture。

---

## 6. Decision

选择 **Canonical real-owner composition**。

新增 production/reference composition adapter：

```text
CanonicalWorkflowOwnerPorts
```

其职责是满足 workflow 已有的 external-owner port contract，并把 workflow-facing stable-ref/read-model 请求适配到 repository 中的真实 authoritative owner public APIs。

冻结调用栈：

```text
LangGraphWorkflowRuntime
        │
        ▼
DefaultWorkflowServices
        │
        ▼
CanonicalWorkflowOwnerPorts
        │
        ├── Context / freshness boundary
        ├── Impact owner/service
        ├── ChangeSet V2
        ├── Gateway V2
        ├── Execution Planning V2
        ├── Provider Binding V2
        ├── Execution Saga V2 / coordination
        └── Reconciliation V2
```

Operation Resolver 与 Parameter Binder 继续由既有 `DefaultWorkflowServices` ownership/composition 使用，不为了形成这张图而重复包装成新的 owner。

### 6.1 Why this option

它同时满足：

- ADR-010：graph 只编排，不重写 domain semantics；
- 可复用性：不是只在一个大 test fixture 中手工拼装；
- 可审计性：production/reference composition 有明确依赖边界；
- 可测试性：scenario fake 与 real-owner E2E 可以分层存在；
- 后续扩展：下一阶段 semantic/product E2E 与 MCP front door 可以复用同一 reference composition，而不是再次自行组装 owners。

### 6.2 Rejected alternative — fixture-only composition

只在测试 fixture 中手工拼接真实 owners 虽然可以降低初始代码量，但会保留 production composition gap：

```text
E2E fixture knows how to compose
production/reference runtime does not
```

随后 semantic E2E、MCP front door 或其他产品入口仍需重新决定同一组 owner wiring。因此该方案不作为 canonical design。

### 6.3 Rejected alternative — graph imports domain modules directly

LangGraph node 直接 import ChangeSet/Gateway/Saga 等 domain modules 会把 graph 从 orchestration owner 变成 domain-composition/domain-semantics owner，并形成：

```text
graph topology
  + owner implementation knowledge
  + domain decision knowledge
```

这违反 ADR-010 的 ownership separation，因此禁止。

---

## 7. Workflow topology remains unchanged

本阶段不以“real E2E”为理由修改业务 progression。既有逻辑顺序保持：

```text
context
  -> resolver
  -> HITL
  -> binder
  -> freshness
  -> impact
  -> changeset
  -> preview
  -> approval
  -> execution planning
  -> revision barrier
  -> provider binding
  -> execution grant
  -> apply/recovery
  -> reconcile
```

架构不变量不是“每个 graph node 必须恰好调用一个方法”，而是：

> graph 拥有 orchestration/navigation；graph 不拥有 domain decision。领域语义继续属于 `WorkflowServices` 与 authoritative owners。

未来 graph node 的内部调用数量可以因可观察性、poll/re-entry 或 presentation 需要变化，只要不跨越 ownership boundary。

---

## 8. `CanonicalWorkflowOwnerPorts` contract

### 8.1 Allowed responsibilities

`CanonicalWorkflowOwnerPorts` 是 composition root / anti-corruption adapter。它只允许承担：

```text
request assembly
StableRef resolution
read-model projection
cross-owner composition / dependency wiring
error translation required by the existing workflow-facing contract
```

其中 “cross-owner composition” 只表示把一个 owner 已公开的 stable ref/read model 作为另一个 owner public API 所需输入来组装请求；它不授予 adapter 解释或改变 owner semantics 的权限。

### 8.2 Forbidden responsibilities

adapter 不得重新实现或复制：

```text
approval scope / approval policy
ChangeSet canonical semantics
execution planning rules
revision barrier semantics
provider eligibility / provider selection policy
ExecutionGrant authorization/signing semantics
Saga transition rules
unknown-outcome rules
reconciliation / ActualDelta semantics
DIVERGED classification semantics
compensation policy
Host commit truth
```

如果 real-owner composition 发现某个 workflow-facing request 需要上述规则才能完成，而 owner public API 没有提供对应能力，应当：

```text
FAIL DESIGN / expose missing owner API
```

而不是把规则塞进 `CanonicalWorkflowOwnerPorts`。

### 8.3 Stable-ref-first boundary

composition 应优先在 owner 边界传递：

```text
StableRef
AsyncOperationRef
canonical ids/hashes
owner-defined request/read-model types
```

不得为了减少一次查询，把完整 external authoritative object 长期复制进 workflow checkpoint 或 adapter-owned cache 并把该副本视作 truth。

---

## 9. Dependency and import boundary

本阶段冻结语义级 dependency rule：

```text
CanonicalWorkflowOwnerPorts
  MAY import owner public canonical/V2 API surfaces

CanonicalWorkflowOwnerPorts
  MUST NOT import legacy V1 consumer surfaces
  MUST NOT import owner-private/internal implementation surfaces
  MUST NOT import test helpers/scenario fakes
  MUST NOT import Host-specific implementation details that bypass owner ports
```

这里的 “public canonical/V2 API surface” 是 architecture concept，不由 `v2.py`、`builder_v2.py` 等文件名定义。

实现阶段应增加 machine-enforced architecture guard，但 guard 必须检查 dependency semantics / approved public surfaces，不得把当前物理 module 文件名永久冻结为架构契约。

---

## 10. Definition of real for this capability

本阶段的 real-owner E2E 定义为：

```text
real LangGraph workflow runtime
+ real durable Workflow Orchestrator checkpoint/artifact persistence
+ real Operation Resolver / Parameter Binder
+ real Impact
+ real ChangeSet V2
+ real Gateway V2
+ real Execution Planning V2
+ real Provider Binding V2
+ real Execution Saga V2
+ real Reconciliation V2
+ only explicit narrow environment/presentation test ports
```

换言之：

```text
repository-internal authoritative domain owners = REAL
true external environment / presentation boundary = MAY BE deterministic test port
```

允许的 boundary double 必须满足：

1. 它替代的对象确实是环境/IO/presentation boundary，而不是 repository 中已有的 domain owner；
2. 它不重写 canonical domain rule；
3. 它行为确定、可观察，能够支持 duplicate-call / recovery assertions；
4. 测试命名与 fixture wiring 明确表明它是 boundary double。

典型允许对象包括 deterministic `HostExecutionPort` 与 preview/presentation boundary。

---

## 11. Preview boundary

当前 baseline 没有要求本阶段建立一个新的 authoritative preview owner。

因此 preview 保持 explicit presentation/environment boundary：

```text
ChangeSet authoritative truth
        │
        ├──> preview presentation/ref
        │
        └──> approval/planning/execution consumers
```

preview 不得：

- 复制并修改一份 ChangeSet 后将其作为第二 truth；
- 自己决定 approval scope；
- 自己生成 execution semantics；
- 为追求“100% real”而被提升为没有既有 architecture authority 的 domain owner。

如果 preview 产生 ref，该 ref 只表示 presentation artifact / presentation result；ChangeSet truth 仍属于 ChangeSet owner。

---

## 12. Restart and StableRef recovery semantics

### 12.1 Architecture rule

restart/re-entry 的长期语义基于 **authoritative StableRef resolvability**，而不是基于某个 store implementation class：

```text
checkpoint refs/navigation
        │
        ▼
resolve authoritative owner state by StableRef
        │
        ├── resolvable + valid for current transition
        │      -> continue
        │
        └── unresolved / invalid / stale-in-a-forbidden-way
               -> FAIL CLOSED
```

因此以下说法不属于 architecture contract：

```text
PostgreSQL => 一定可以继续
InMemory   => 一定失败
```

当前 implementation 可能呈现这种结果，但真正的 contract 是 ref 是否仍能由 authoritative owner 解析并满足当前 transition 的有效性要求。

### 12.2 No reconstruction from checkpoint

当 authoritative ref 无法解析时，workflow 不得从 checkpoint 或 graph position 猜测/重建领域事实。

明确禁止：

```text
recreate ApprovalRecord
re-sign / recreate ExecutionGrant
rebuild ChangeSet from cached fields
rebuild ProviderBinding from graph position
infer Saga success from a later graph node
infer Host commit truth from a checkpoint cursor
```

缺少 authoritative truth 是一个需要 fail-closed 的 data-integrity condition，不是“尽力恢复”的提示。

### 12.3 Current owner durability is an implementation fact

本阶段 acceptance 可以且应该针对当前实现验证不同结果，例如：

- PostgreSQL-backed Execution Saga StableRef 在 fresh process 中仍可解析并继续；
- 当前 process-local owner 的 ref 在 fresh process 中如果不可解析，则 workflow 必须 fail closed；

但这些场景是对当前 implementation consequences 的测试，不得反向把 store 类型写成长期领域语义。

### 12.4 No arbitrary-node restart claim

本阶段不能声称：

```text
workflow 可在任意 node、任意 owner state、任意进程丢失后无条件恢复
```

只有其引用的 authoritative state 具备相应 durability/resolvability 的路径才能继续。其它路径的正确行为可以是明确的 fail closed。

---

## 13. Checkpoint and workflow-artifact ownership

沿用 ADR-010、HITL predecessor 与 checkpoint-retention contract：

```text
Workflow checkpoint
  = workflow navigation / waits / stable refs / workflow-local metadata

WorkflowArtifactStore
  = Workflow Orchestrator 自己拥有、没有其它 authoritative owner 的 deterministic intermediate artifacts

External authoritative owner state
  = remains with original owner
```

real-owner E2E 必须继续证明 checkpoint 没有直接持有或成为以下对象的 authoritative copy：

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

本阶段不得为了减少 fixture wiring，把真实 owner object 序列化进 LangGraph state 并在 resume 时绕过原 owner。

---

## 14. Execution, Saga, reconciliation and `DIVERGED`

real-owner E2E 应使用真实的 Execution Saga V2 / materialized execution coordination 与真实 reconciliation V2 owner/service；Host execution 仍可通过确定性的外部 boundary port 驱动。

ownership 保持：

```text
Workflow Orchestrator
= 用户任务 progression / waits / re-entry

Execution Saga
= 已批准执行的实际 execution state

Reconciliation
= actual-vs-expected observation / convergence truth
```

`DIVERGED` 在本阶段只作为真实 Saga/reconciliation terminal truth 被观察：

```text
DIVERGED != compensation authorization
DIVERGED != automatic compensation execution
```

CV2-008 compensation executor 继续保持 `BLOCKED`。本阶段不得因为 E2E 已能观察 `DIVERGED` 就私自引入 compensation side effect。

---

## 15. ADR-009 delivery boundary

ADR-009 仍是 cross-owner delivery/crash-recovery authority，但本 capability 不扩张它的范围。

明确不新增：

```text
new outbox/inbox owner
new owner-wide transactional delivery migration
new replay protocol
new duplicate-delivery semantics
new owner-wide delivery crash-recovery acceptance matrix
```

如果 production/reference composition 自然调用已有 delivery infrastructure，可以覆盖该调用是否与既有 contract 兼容；但不能把“跑真实 owner”变成一次新的 delivery architecture phase。

这条限制用于防止 scope inflation，不用于禁止正常复用已经存在且已被 ADR-009 授权的 infrastructure。

---

## 16. Test architecture

本阶段建立两层互补的 workflow tests，而不是用一层替换另一层。

### 16.1 Fast orchestration regression

现有 `_ScenarioOwners` / narrow workflow doubles 可以保留，用于：

```text
graph topology regression
routing regression
pause/resume edge cases
service-call sequencing
fast failure-path characterization
```

它们的价值是快速、局部、可精确注入状态。

因此：

```text
DELETE _ScenarioOwners = NOT REQUIRED
```

### 16.2 Real-owner E2E acceptance

新增独立 acceptance path：

```text
LangGraphWorkflowRuntime
  -> DefaultWorkflowServices
     -> CanonicalWorkflowOwnerPorts
        -> real authoritative owners
           -> explicit environment/presentation boundary doubles only
```

该路径：

```text
MUST NOT use _ScenarioOwners
MUST NOT import test-side owner semantics into production composition
MUST NOT replace a repository authoritative owner with a scenario fake
```

### 16.3 Boundary observability

允许的 Host/environment double 至少应能记录：

```text
external execution invocation count
idempotency/correlation key or equivalent observable identity
requested operation/slice identity
returned deterministic result
```

从而能够证明 recovery/re-entry 没有造成第二次外部执行。

---

## 17. Required acceptance scenarios

实现计划至少必须覆盖以下 acceptance；任何删减需要回到 design review：

### A. Happy path reaches `COMPLETED`

真实 owners 参与的 reference composition 从 workflow start 运行到真实 Saga/reconciliation terminal success，最终 workflow 可观察为 `COMPLETED`。

### B. HITL pause/resume remains intact

real-owner composition 必须继续经过 predecessor 已冻结的 human pause/resume contract；production owner wiring 不得绕过 HITL gate。

### C. At least one asynchronous wait/re-entry

E2E 必须真实经历一次 workflow async wait/re-entry，而不是所有 owner 都被同步 fake 成一次函数返回。

### D. Missing authoritative ref fails closed

构造一个 checkpoint 中 ref 存在、但 fresh composition 无法从 authoritative owner 解析的场景。预期结果必须是明确失败，不得重建领域对象后继续。

### E. Durable Saga recovery does not execute twice

在已有 Saga durability/recovery contract 覆盖的 crash window 中，用 fresh runtime/composition 恢复；确定性的 external Host boundary 必须证明同一已完成 execution 没有被再次 dispatch。

### F. Checkpoint remains refs/navigation only

architecture/serialization assertion 必须证明 external authoritative domain object body 没有重新进入 workflow checkpoint 成为第二 truth。

### G. No V1 consumer reintroduced

architecture guard 必须证明新的 production/reference composition 没有为了方便 wiring 重新依赖 legacy V1 owner surface。

### H. PostgreSQL and repository regression remain green

至少包括本 capability 的 PostgreSQL acceptance gate，以及 repository 既有 canonical regression suites。精确命令与 CI job 在 Implementation Plan 中根据届时 branch HEAD 冻结，本 Design Spec 不提前猜测命令清单。

---

## 18. Failure semantics

real-owner E2E 的失败必须遵守 owner boundary，不允许 adapter/graph 用“恢复便利性”掩盖数据完整性问题。

### Fail closed conditions include

- stable ref 无法由预期 authoritative owner 解析；
- ref resolves 到与当前 workflow subject/hash/revision 不匹配且 owner contract 不允许继续的对象；
- execution authorization/grant 无法由 Gateway authority 验证；
- provider binding/plan/changeset relation 不满足 owner contract；
- Saga/reconciliation 返回 terminal failure/divergence；
- external operation outcome 仍处于 owner-defined unknown state，且 owner contract 尚未允许安全重试。

### Forbidden fallback

不得通过以下手段把 RED 伪装成 GREEN：

```text
fallback to V1
fallback to _ScenarioOwners inside production composition
recreate missing approval/grant/changeset
assume execution succeeded because graph advanced
skip reconciliation because Host double returned success
```

---

## 19. Design constraints for the future Implementation Plan

本 Spec 批准后，独立 Implementation Plan 必须：

1. 先做 exact-head owner/public-API census，再冻结 `CanonicalWorkflowOwnerPorts` 的 concrete dependency list；
2. 以 TDD 证明 real-owner acceptance 先 RED、再逐步 GREEN；
3. 将 composition adapter 与 architecture guard 分成可审计任务；
4. 保留 scenario regression，不用大 E2E 取代所有小测试；
5. 明确每个 retained test double 对应的真实 boundary；
6. 每个任务以 exact-head CI/evidence 收口；
7. 不在计划执行过程中顺手扩张到 semantic product scenario、MCP 或 real Host acceptance。

本节只冻结计划必须遵循的约束；它不是 Implementation Plan，也不授权产品代码修改。

---

## 20. Exit gate

本 Design Spec 当前停在：

```text
WRITTEN-SPEC REVIEW GATE
```

只有本 Spec 被明确批准后，下一步才是：

```text
Implementation Plan
```

在批准前：

```text
production code changes = FORBIDDEN
implementation task execution = FORBIDDEN
support-matrix expansion = FORBIDDEN
```

本能力完成并 merge 后，Capability Phase 才进入下一 successor：

```text
semantic -> plan -> approve -> execute -> reconcile
```

它不会自动授权 MCP front door 或 real AutoCAD/Revit acceptance。

---

## 21. Amendment A — Operation Freshness Exact Lineage

**Amendment date:** 2026-09-23  
**Trigger:** Task 6 rereview during real-owner implementation exposed an exact-lineage contradiction between the frozen workflow-facing seam and the requirement that Impact consume the exact PlanningSnapshot/SnapshotSet produced by the successful operation-freshness transition.  
**Status:** Written-Spec Review Gate

本 Amendment 是一个窄 architecture correction。它不改变 §7 的业务 progression、不建立新的 authoritative owner，也不授权 Task 7 Step 3 继续实现。它只修正 operation freshness → Impact 之间缺失的显式 lineage。

### 21.1 Supersession scope

本节只在以下范围内覆盖 baseline Spec 的旧表述：

1. §5 中“不得重写 `WorkflowServices` / `DefaultWorkflowServices` contract”的 non-goal，对本节明确列出的两个 method seam 例外；其它 workflow-facing contract 继续冻结。
2. §7 中“workflow topology remains unchanged”继续指 **节点顺序与 ownership 不变**；它不再被解释为“节点之间不得新增 checkpoint-safe StableRef 导航字段”。
3. §20 的 baseline Written-Spec Review Gate 已在此前实现启动前完成；当前 gate 只针对 Amendment A。Amendment A 未批准、且对应 Implementation Plan amendment 未冻结前，不得修改本 amendment 涉及的产品代码。

除以上三点外，baseline Spec 继续有效。

### 21.2 Root cause

当前 operation-freshness owner 可以在同一个 canonical operation / freshness contract 上，于不同 Host revision 产生多个合法 immutable PlanningSnapshot：

```text
same operation / same freshness contract
        │
        ├── Host revision 42 -> PlanningSnapshot PS-42 -> SnapshotSet PSS-42
        └── Host revision 43 -> PlanningSnapshot PS-43 -> SnapshotSet PSS-43
```

这些历史对象都可以同时保持 authoritative、immutable、可解析。

但 baseline workflow-facing seam 只有：

```text
ensure_operation_freshness(operation_ref) -> StableRef | AsyncOperationRef
analyze_impact(operation_ref) -> StableRef
```

当成功 freshness 仍只把 `operation_ref` 传给下一阶段时，Impact 无法知道本次 workflow 成功绑定的是 PS-42/PSS-42 还是 PS-43/PSS-43。使用以下任一恢复方式都会破坏 correctness：

```text
latest/current snapshot lookup
freshness-contract reverse lookup
operation_ref -> snapshot process-local map
adapter-local hidden lineage
```

因此 exact lineage 必须成为显式 workflow navigation data。

### 21.3 Decision — explicit workflow-local freshness lineage envelope

新增一个 workflow-facing、非 authoritative 的 typed result：

```text
OperationFreshnessResult
  operation_ref: StableRef
  planning_snapshot_ref: StableRef
  snapshot_set_ref: StableRef
```

三个字段全部是 owner-issued StableRef。`OperationFreshnessResult` 只是 Workflow Orchestrator 的导航 envelope：

```text
it owns no semantic truth
it owns no freshness rule
it owns no snapshot body
it owns no mutable current/latest binding
```

真实 truth 继续属于原 owners：

```text
BoundOperationProposal / operation artifact -> existing workflow/operation owner
PlanningSnapshot / SnapshotSet              -> Semantic Runtime
Impact                                      -> Impact owner/service
```

不得为这个 amendment 新建“FreshnessResult authoritative owner”或第二份 snapshot store。

### 21.4 Approved seam change

本 Amendment 只批准以下 workflow-facing contract change：

```text
ensure_operation_freshness(operation_ref)
  -> OperationFreshnessResult | AsyncOperationRef

analyze_impact(
  operation_ref,
  planning_snapshot_ref,
  snapshot_set_ref,
)
  -> StableRef
```

`WorkflowServices`、`DefaultWorkflowServices` 与 `ExternalOwnerPorts` 只在这两个 method seam 上同步变化；其它 method signatures 不因本 amendment 扩张。

异步 freshness 语义保持：

```text
AsyncOperationRef
  -> wait/re-entry
  -> owner re-query
  -> successful OperationFreshnessResult
```

在 owner 尚未成功产生 exact refs 前，graph 不得合成或猜测 lineage。

### 21.5 Graph/checkpoint data flow

`ensure_operation_freshness` graph node 在成功结果后只持久化导航 refs：

```text
operation_ref
planning_snapshot_ref
snapshot_set_ref
```

这三个 refs 是一个不可拆分的成功结果：**必须在同一次 graph state update 中写入**。graph 不得先写入其中一部分、在后续 node 再补齐剩余 refs；任何 partial tuple 都不得被视作可进入 Impact 的合法状态。

异步 freshness 的 wait/re-entry 也遵守同一规则：

```text
AsyncOperationRef
  -> wait/re-entry
  -> owner re-query
  -> successful OperationFreshnessResult
  -> one atomic graph-state update of all three refs
```

等待期间不得消费旧的 `planning_snapshot_ref` / `snapshot_set_ref`。如果 resume 后得到新的 successful freshness result，Impact 只能消费该结果同一次 state update 写入的 exact pair；不得把 wait 前遗留 pair 与 wait 后的新结果拼接。

然后 `analyze_impact` node 把这三个 exact refs 传入 service boundary。

允许新增的 private graph state 字段必须满足现有 checkpoint rules：

```text
JSON-compatible StableRef encoding only
no SemanticSnapshot object
no SnapshotSet object
no SemanticProjection object
no freshness contract body
no Impact object
```

`planning_snapshot_ref` / `snapshot_set_ref` 是 §13 所允许的“stable refs / navigation”，不是 external authoritative object 的复制。

### 21.6 CanonicalWorkflowOwnerPorts behavior

`CanonicalWorkflowOwnerPorts.analyze_impact(...)` 只能做：

```text
resolve exact operation_ref from its authoritative owner
resolve exact planning_snapshot_ref from Semantic Runtime owner
resolve exact snapshot_set_ref from Semantic Runtime owner
assemble the real Impact owner request
validate/refuse the frozen exact-lineage invariants through owner public surfaces
translate owner failures into the existing workflow error boundary
```

进入真实 Impact owner/service 之前，至少必须验证以下关联；单个 ref 各自合法不能替代三者关系校验：

1. **StableRef identity/hash integrity**：`operation_ref`、`planning_snapshot_ref`、`snapshot_set_ref` 的 `ref_id` / `content_hash` 必须与各自 owner 实际解析到的 authoritative artifact identity/hash 一致。
2. **SnapshotSet membership**：解析到的 `SnapshotSet` 必须包含由 `planning_snapshot_ref` 指定的 exact PlanningSnapshot；不得用“同 contract 的另一个 snapshot”替代。
3. **Document/environment consistency**：PlanningSnapshot 与 SnapshotSet 的 document scope、SemanticEnvironment identity/hash 必须相互一致，并与当前 bound operation 所针对的 authoritative subject/environment 不冲突。
4. **Freshness-contract ↔ bound-operation match**：PlanningSnapshot 所记录的 freshness contract identity/hash 必须对应当前 `operation_ref` 的 bound operation 按现有 canonical freshness-contract construction/public validation 所得到的 operation contract；不得只因为 snapshot 本身有效就接受与当前 operation 无关的 contract。

这些检查只能复用 owner 已公开的 identity、hash、membership、contract/read-model 校验能力，或调用既有 canonical helper；它们不授权 adapter 复制 freshness/Impact 领域规则。

上述任一关系错配都必须 **在调用真实 Impact analyzer/service 之前 fail closed**，并进入既有 workflow error boundary。实现与测试必须能够观察到 mismatch case 中 Impact owner 未被调用。

它不得：

```text
search the latest PlanningSnapshot
select a SnapshotSet by freshness-contract reverse lookup
select a SnapshotSet by operation_ref
maintain operation_ref -> snapshot/process-local lineage maps
compare revisions and choose a winner
reimplement freshness or Impact semantics
```

如果 owner public API 不能通过 exact refs 重建或验证 Impact 所需输入，应按 §8.2 `FAIL DESIGN / expose missing owner API` 处理，而不是回退到 reverse lookup。

### 21.7 Multi-revision invariant

本 amendment 冻结以下必须成立的不变量：

```text
workflow A:
  same operation
  freshness succeeds at revision 42
  -> PS-42 / PSS-42
  -> Impact must consume PS-42 / PSS-42

workflow B:
  same operation
  freshness succeeds at revision 43
  -> PS-43 / PSS-43
  -> Impact must consume PS-43 / PSS-43
```

即使 PS-42、PSS-42、PS-43、PSS-43 同时存在于 owner store，两个 workflow 也不得因为“当前值”“最近值”或 reverse lookup 而交叉绑定。

### 21.8 Restart/rebuilt-adapter invariant

这里必须区分 **rebuilt-adapter proof** 与 **cross-process recovery proof**：

- 销毁旧 `CanonicalWorkflowOwnerPorts`、创建新的 composition instance，并复用同一 owner stores，只能证明 correctness 不依赖 adapter-private/process-local lineage map；如果这些 owner stores 本身仍是进程内对象，该证据不得表述为跨进程 durability/recovery 已被验证。
- 真正的 fresh-process recovery claim 继续受 §12 约束：只有 checkpoint refs 指向的 authoritative owner state 在新进程中仍可解析时，workflow 才允许继续；若 owner store 是 process-local 且 ref 无法解析，正确结果仍是 fail closed。

在 owner state 对当前恢复环境确实可解析的前提下，只要实际序列化 checkpoint 中的三个 StableRef 仍然存在：

```text
operation_ref
planning_snapshot_ref
snapshot_set_ref
```

新的 `CanonicalWorkflowOwnerPorts` 必须能够从这些 refs 重新组装同一 exact Impact request，而不得依赖旧 adapter 实例中的任何 Python object identity 或隐藏 lineage。

反之，任何一个 required ref 无法解析、hash/integrity 不匹配、或 exact pair 不满足 §21.6 的 lineage invariant 时必须 fail closed，不得重新运行 freshness、选择 latest 或从 graph position 推断。

### 21.9 Rejected alternatives

#### A. Reuse one operation-like StableRef as a hidden wrapper

把 freshness outcome 包装成另一个“operation ref”可以保持 `analyze_impact(operation_ref)` 的表面形状，但会使同一字段同时表示 BoundOperationProposal 与 freshness wrapper，破坏 ref kind 语义并迫使后续节点做隐式二次解析。因此拒绝。

#### B. Mutable `operation -> current freshness` owner binding

即使把 map 从 adapter 移到 Semantic Runtime，只要语义仍是 `current/latest`，revision 43 就可能覆盖 revision 42 的恢复目标。存储位置变化不能修复 lineage ambiguity，因此拒绝。

#### C. Freshness-contract reverse lookup

同一 freshness contract 可以在不同 revision 上产生多个合法 snapshot。遇到多个结果后 fail closed 虽然比任意选一个安全，但它仍意味着 workflow 没有携带本来就已经知道的 exact result identity；因此它不能作为 canonical success path。

### 21.10 Required amendment acceptance

对应 Implementation Plan amendment 至少必须增加以下 TDD evidence：

1. **Interleaved two-revision RED/GREEN**：同一 operation / freshness contract 依次执行 `freshness@42 -> freshness@43 -> Impact@42 -> Impact@43`。PS-42/PSS-42 与 PS-43/PSS-43 必须同时保留，两个 Impact 调用必须分别消费各自 exact pair，证明后一次 freshness 不会把前一次 workflow 绑定到 current/latest 值。
2. **Exact-lineage mismatch negatives**：至少覆盖 §21.6 冻结的四类关系：ref/hash 错配、SnapshotSet 不包含指定 snapshot、document/environment 错配、freshness contract 与当前 bound operation 不匹配。每个 case 都必须在真实 Impact owner/service 被调用前 fail closed。
3. **Atomic graph-state update / stale-pair negative**：成功 freshness 的 `operation_ref + planning_snapshot_ref + snapshot_set_ref` 必须由同一次 graph node update 写入；异步 wait/re-entry 场景必须证明旧 pair 不会与新的 successful freshness result 混用，partial/stale tuple 不能进入 Impact。
4. **Serialized-checkpoint round-trip RED/GREEN**：不能只把测试局部变量中的 refs 直接喂给 rebuilt adapter。测试必须经过真实 checkpoint serializer/graph-state encoding 路径，把成功 freshness 后的 state 序列化，再从序列化结果恢复三个 StableRef，并据此重新执行 exact-lineage Impact 组装。
5. **Rebuilt-adapter RED/GREEN**：销毁旧 adapter，使用新的 composition instance 与同一 owner stores，以上 serializer round-trip 恢复出的 StableRefs 仍可重新组装相同 Impact request。该测试只证明“不依赖 adapter 私有状态”；除非 owner stores 本身具备并实际经过跨进程 durability，否则不得将其命名或表述为 cross-process recovery proof。
6. **No reverse-lookup success path**：production/reference composition 的该路径不得依赖 `get_snapshot_for_freshness_contract`、`get_snapshot_set_for_member` 或等价 latest/current/reverse lookup。
7. **Checkpoint refs-only regression**：新增 graph state 字段只能包含 StableRef 编码，不得把 PlanningSnapshot/SnapshotSet body 写入 checkpoint。
8. **Existing Task 7 compatibility**：Task 7 Step 1/2 已完成能力不得因 seam amendment 回退；所有受影响快速 scenario regression 必须显式迁移到新 shape。
9. **Exact-head closure**：Task 6 repair 的 focused tests、architecture guard、Ruff 与 repository exact-head gates 全部通过后，才能恢复 Task 7 Step 3。

### 21.11 Implementation sequencing gate

Amendment A 的执行顺序冻结为：

```text
Amendment A written-spec approval
  -> Implementation Plan amendment
  -> Task 6 interleaved two-revision RED
  -> exact-lineage mismatch REDs
  -> exact-lineage GREEN
  -> atomic graph-state / stale-pair proof
  -> serialized-checkpoint round-trip proof
  -> rebuilt-adapter no-private-state proof
  -> architecture / checkpoint regression
  -> exact-head verification
  -> Task 6 repair CLOSED
  -> resume Task 7 Step 3
```

在 Task 6 repair 正式 CLOSED 之前：

```text
Task 7 Step 3 product implementation = FORBIDDEN
provider-binding/grant follow-on expansion = FORBIDDEN
latest/current/reverse-lookup workaround = FORBIDDEN
```
