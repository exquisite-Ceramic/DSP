# Capability Phase — Revit Wall Thickness Product Vertical Design

**Status:** Draft — Written-Spec Review Gate  
**Date:** 2026-09-25  
**Base:** `main@1c753e949ada7a2c06ce856a57fa3ced407251e9`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`  
**Workflow authority:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`  
**Persistence authority:** `docs/adr/ADR-008-durable-state-persistence-ownership.md`  
**Delivery authority:** `docs/adr/ADR-009-cross-owner-delivery-crash-recovery.md`  
**Predecessor design:** `docs/superpowers/specs/2026-09-20-real-owner-e2e-workflow-design.md`  
**Host semantic predecessor:** `docs/superpowers/specs/2026-09-01-phase-h-revit-wall-thickness-gap-closure-design.md`

## 1. Purpose

本设计定义 Real-Owner E2E Workflow 之后的下一条 capability increment：把已经存在的 semantic、planning、approval、execution、reconciliation 与 Revit wall-thickness host capability 组合成第一条真实产品 vertical：

```text
用户在 Revit 中选中 exactly one wall
  ↓
请求“把这面墙厚度改为 300 mm”
  ↓
semantic resolution
  ↓
canonical planning
  ↓
preview / approval
  ↓
execution grant / admission
  ↓
real Revit mutation
  ↓
independent read-back
  ↓
ActualDelta / scope comparison
  ↓
semantic reconstruction / semantic verification
  ↓
reconciliation
  ↓
product task SUCCEEDED
```

这里的目标不是再建设一套 domain stack，而是证明：**同一个 ProductTask、同一条 immutable authority lineage、同一个 durable workflow，能够从真实 Revit 产品输入一直运行到真实执行后的独立结果证明。**

前驱 Real-Owner E2E 已有意把“完整 `semantic -> plan -> approve -> execute -> reconcile` 产品场景”留给 successor。本设计正好承接这一保留项；它不重做前驱 composition，也不把新的产品语义塞回 `CanonicalWorkflowOwnerPorts`。

---

## 2. Baseline observations

以下事实以 `main@1c753e949ada7a2c06ce856a57fa3ced407251e9` 为设计基线：

1. `langgraph_graph.py` 已经存在一条真实 workflow topology：

   ```text
   resolve_host_context
     -> ensure_context_freshness
     -> resolve_operations
     -> operation proposal HITL
     -> parameter_binding
     -> ensure_operation_freshness
     -> analyze_impact
     -> build_changeset
     -> preview
     -> policy_approval
     -> execution_planning
     -> revision_barrier
     -> provider_binding
     -> execution_grant
     -> refresh_execution_owner
     -> apply_or_recover
     -> verify_reconcile
   ```

   因此本阶段**不得**新增第二条 semantic/planning workflow。

2. 当前 graph 以 `task_id` 进入 `resolve_host_context`；它不是从一个预先准备好的 `operation_ref` 才开始。`context_snapshot_ref` 与后续 `operation_ref` 都由 workflow 明确携带。

3. `WorkflowServices` / `DefaultWorkflowServices` 已把 framework-neutral orchestration 与 deterministic owners 分离；OperationResolver 与 ParameterBinder 在 service adapter 内使用真实 deterministic implementation，其余 owner 通过 stable ports 访问。

4. `CanonicalWorkflowOwnerPorts` 已经是 production/reference composition seam，并负责把 Impact、ChangeSet、Approval、Execution Planning、Provider Binding、Gateway/Grant、Saga、Reconciliation、Recovery 等真实 authoritative owners 接到 workflow。

5. 前驱 real-owner E2E 已证明上述 composition 可以在 durable workflow / PostgreSQL owner 路径上工作；本阶段不得重新发明 `_ScenarioOwners` 风格的 authoritative aggregate fake 来替代这些 owner。

6. Phase H 已冻结并验证 Revit wall-thickness host semantics：显式 operation intent 为 `revit.set_wall_thickness.v1`；Host 读取当前 WallType width，执行严格 isolation/preflight，再通过独占 WallType 完成厚度变更，并生成 before/after evidence 与 ActualDelta。

7. Phase H 同时冻结：wall thickness 不提升为 universal `SemanticObject` field；其 canonical effect 仍是 `PROPERTIES`；真实成功证据要求独立 post-state reconstruction 与 semantic verification，而不是相信 Host 返回的 `success=true`。

这些 baseline observations 是本设计的输入，不意味着具体文件名、store 类名或 table 名自动成为长期架构 contract。

---

## 3. Problem statement

当前仓库已经分别证明两件事：

```text
A. real-owner workflow composition 可以跑通并恢复

B. Revit wall-thickness host capability 可以真实改墙并完成 Phase H 级验证
```

但 `A + B` 仍不等于一个真实产品 vertical。

尚未被冻结并验证的是：

```text
同一个产品请求
  -> 创建/进入同一个 task_id
  -> 捕获真实 Revit authoritative context
  -> 经过当前真实 workflow owner chain
  -> 产生并批准 immutable execution authority
  -> 真实执行 revit.set_wall_thickness.v1
  -> 对同一次执行做 independent read-back
  -> 用批准过的 authority 验证 ActualDelta 与最终 semantic state
```

如果只把现有 Real-Owner E2E 测试和 Phase H Revit 测试并排运行，就仍然存在 composition gap：两边可能使用不同 task identity、不同 snapshot、不同 scope、不同 operation payload，甚至不同执行证据，而测试仍可能分别 GREEN。

本阶段必须消灭的正是这个 **product lineage gap**。

---

## 4. Goals

本阶段必须满足以下目标：

1. 建立一条从真实 Revit 产品请求到最终结果证明的单一 vertical；
2. 复用现有 LangGraph topology、`WorkflowServices`、`DefaultWorkflowServices` 与 `CanonicalWorkflowOwnerPorts`，不建立第二个 workflow runtime；
3. 产品入口只负责把结构化用户请求与 Host session/document context 变成当前 workflow 可消费的 `task_id`；
4. selected entity identity、Host revision、context facts 必须来自 authoritative Revit/context capture，而不是把 presentation 输入当成事实；
5. semantic resolution、parameter binding、impact、ChangeSet、approval、planning、provider binding、grant、Saga、reconciliation 继续由当前 owner 持有；
6. approval 后 pause/restart/resume 必须继续 exact refs / hashes，不允许用用户原话重算已批准 artifact；
7. 真实执行必须使用 `revit.set_wall_thickness.v1` 的既有 Host contract；
8. `Host success=true` 不能直接产生产品 success；
9. 产品 success 必须要求 independent read-back、ActualDelta scope proof 与 semantic postcondition proof；
10. offline product E2E 与 live Revit E2E 必须共享同一 product-flow composition，区别只能位于真实 Host/environment boundary；
11. 保持现有严格 Revit fixture，不为 demo 放宽安全前置条件；
12. 不新增第二份 domain truth。

---

## 5. Explicit non-goals

本阶段不实现：

- MCP/Agent front door；
- NLP / free-form intent understanding；
- 新的 OperationResolver；
- 新的 ParameterBinder；
- 新的 semantic canonical model；
- 把 wall thickness 加到 universal `SemanticObject` schema；
- 多实体 wall-thickness mutation；
- CREATE / DELETE product scenario；
- AutoCAD product vertical；
- cross-host materialization；
- 新 Execution Saga semantics；
- automatic compensation executor；
- owner-wide persistence redesign；
- checkpoint schema expansion；
- V1 retirement；
- Host support-matrix 扩张；
- 为了产品 demo 放宽 wall isolation、join、hosted insert/opening 或 exclusive WallType 要求。

如果实现过程中发现这些事项是硬前置，必须回到 Design amendment；implementation plan 不得把它们作为“顺手修改”吸收进去。

---

## 6. Architectural decision

选择 **Thin product facade over the existing real-owner workflow**。

本设计提出一个新的 product/application seam，暂定名：

```text
WallThicknessProductFlow
```

这是**新 proposed symbol**，不是当前仓库既有 API。它的职责只有：

1. 接受结构化 wall-thickness 产品请求；
2. 建立或解析当前 workflow 所需的 `task_id` / host-session linkage；
3. 启动或恢复现有 workflow runtime；
4. 把当前 workflow 的 preview / HITL interrupt 转成产品交互；
5. 在 generic workflow execution/reconciliation 到达可验证终态后，触发同一执行 lineage 的 independent result proof；
6. 只在 execution truth 与 result proof 都满足时报告产品 `SUCCEEDED`。

它**不得**：

- 自己执行 eligibility；
- 自己选择 canonical operation；
- 自己绑定 operation parameters；
- 自己计算 impact；
- 自己生成 ApprovalScope / ChangeSet；
- 自己发行 approval / grant；
- 自己解释 provider binding；
- 自己推进 Saga；
- 自己判断 Host-effect recovery；
- 自己发明 reconciliation 结果；
- 自己把 wall width 写入一份新的 product truth store。

冻结调用关系：

```text
Revit product ingress
        │
        ▼
WallThicknessProductFlow        [new thin application seam]
        │
        ▼
LangGraphWorkflowRuntime        [existing]
        │
        ▼
DefaultWorkflowServices         [existing]
        │
        ▼
CanonicalWorkflowOwnerPorts     [existing]
        │
        ├── Context / freshness
        ├── OperationResolver / ParameterBinder path
        ├── Impact / ApprovalScope / ChangeSet
        ├── Approval / Gateway / Grant
        ├── Execution Planning / Provider Binding
        ├── Execution Saga / Host dispatch recovery
        └── Reconciliation

real Revit execution evidence
        │
        ▼
existing Phase H proof chain
        ├── independent read-back
        ├── ActualDelta
        ├── ScopeComparator
        ├── semantic reconstruction
        └── SemanticVerifier
        │
        ▼
WallThicknessProductFlow product outcome
```

---

## 7. Why not the alternatives

### 7.1 Rejected — second wall-thickness workflow

为 wall thickness 新建一个专用 orchestrator，把 semantic、planning、approval、execution 再串一次，会直接复制 ADR-010 workflow ownership，并制造两套恢复语义。拒绝。

### 7.2 Rejected — put Revit product semantics into `CanonicalWorkflowOwnerPorts`

`CanonicalWorkflowOwnerPorts` 是 generic owner composition adapter。把“exactly one wall”“300 mm”“独占 WallType”等产品/Host 约束塞进去，会让 production composition adapter 变成 Revit-specific domain owner。拒绝。

### 7.3 Rejected — declare product success when generic Saga is `SUCCEEDED`

Saga `SUCCEEDED` 证明 execution owner 的状态机已经成功收口；它不自动证明最终 Revit model 的 wall thickness 等于批准目标，也不自动证明 ActualDelta 没有越界。把两者合并会丢失 Phase H 已建立的 independent verification boundary。拒绝。

### 7.4 Chosen — thin facade + existing workflow + independent post-execution proof

该方案最大限度复用现有 authoritative owners，只新增产品 interaction/composition seam，并保持 execution truth 与 product acceptance truth 可区分。

---

## 8. Product ingress contract

本阶段不引入 NLP。产品请求是结构化输入，语义上至少包含：

```text
task identity
host kind = REVIT
active document/session linkage
requested product action = wall thickness change
requested thickness = 300 mm
```

字段级 Python/C# 类型名由 implementation plan 在 repo census 后确定，本设计不提前虚构当前不存在的 public API。

以下内容**不能**直接由 presentation request 作为 authoritative fact 注入后续 owner：

- selected wall entity identity；
- current wall thickness；
- wall classification；
- WallType identity；
- current Host revision；
- join / hosted insert / opening 状态。

这些事实必须由 `resolve_host_context(task_id)` 及其 authoritative Host/context providers 捕获，并形成当前 workflow 的 `context_snapshot_ref`。

因此 ingress 的安全不变量是：

> 用户可以表达“想做什么”，但不能通过请求 payload 自己声明“当前模型事实是什么”。

---

## 9. Existing workflow remains the semantic/planning authority

当前 graph 已经从 `task_id` 开始执行 semantic/planning 主干，因此 `WallThicknessProductFlow` 不新增以下步骤，只驱动现有 runtime：

```text
resolve_host_context(task_id)
  -> context_snapshot_ref

ensure_context_freshness(context_snapshot_ref)

resolve_operations(context_snapshot_ref)
  -> operation_ref

operation proposal HITL

bind_parameters(operation_ref, context_snapshot_ref)
  -> bound operation_ref

ensure_operation_freshness(operation_ref)
  -> operation_ref
  -> planning_snapshot_ref
  -> snapshot_set_ref

analyze_impact(...)
  -> impact_ref

build_changeset(task_id, operation_ref, impact_ref)
  -> changeset_ref

preview(changeset_ref)
  -> preview_ref

request_approval(changeset_ref)
  -> approval_ref

plan_execution(changeset_ref, approval_ref)
  -> execution_plan_ref

provider binding / grant / execution / reconcile
```

对于本产品 vertical，OperationResolver/ParameterBinder 最终必须收敛到既有 Revit wall-thickness operation contract，而不是由产品 facade 直接绕过 resolver 注入 Host command。

---

## 10. Authority lineage

### 10.1 Workflow-visible lineage

本阶段必须保留当前 graph 已显式携带的 exact lineage：

```text
task_id
  ↓
context_snapshot_ref
  ↓
operation_ref
  ↓
planning_snapshot_ref + snapshot_set_ref
  ↓
impact_ref
  ↓
changeset_ref
  ↓
preview_ref
  ↓
approval_ref
  ↓
execution_plan_ref
  ↓
provider_binding_ref
  ↓
grant_ref
  ↓
saga_id / execution-owner truth
```

所有 `StableRef` 都继续使用其 authoritative identity/content hash 语义。禁止通过 “latest artifact”、reverse lookup、registry scan 或内容近似匹配补齐丢失 lineage。

### 10.2 Owner-internal lineage

ApprovalScope、execution slice、binding set、grant admission 等 owner-internal authority 即使不作为独立 graph field 暴露，也必须由其 owner 在 changeset/planning/grant/reconciliation 路径上精确验证。

本阶段不能为了“看起来 lineage 更完整”而把所有 owner internal refs 复制进 checkpoint。

### 10.3 User request stops being authority

结构化用户请求只用于启动 task 与形成后续 authoritative artifacts。一旦 operation/ChangeSet/approval/execution artifacts 已冻结：

```text
resume/restart
  != reread user sentence and recompute

resume/restart
  = reload exact persisted refs
    + ask authoritative owners for current state
```

尤其 approval 之后，任何无法解析原 exact artifact 的情况都必须 fail closed；不能重新解释“300 mm”并创建一个“语义等价”的新计划继续执行。

---

## 11. HITL / preview / resume semantics

产品层把现有 workflow interrupt 转成 UI interaction，但不拥有 HITL authority。

必须满足：

1. operation proposal pause 继续绑定当前 durable pause identity 与 exact `operation_ref`；
2. preview 展示来自当前 `preview_ref` / approved ChangeSet lineage，而不是 product layer 自己重算；
3. approval resume 必须关联原 durable pause / approval identity；
4. restart 后 UI 可以重新渲染当前 pending interaction，但不能创建新的 domain artifact 来“恢复界面”；
5. rejected/cancelled interaction 不能进入 execution；
6. stale context / stale operation 必须返回既有 freshness path，不得由产品层覆盖。

本阶段不改变现有 HITL contract。

---

## 12. Revit wall-thickness execution contract

本产品 vertical 复用 Phase H 已冻结的 Host operation：

```text
revit.set_wall_thickness.v1
```

产品目标为 300 mm，但 transport/Host 内部继续使用既有 internal-unit contract；产品层不得重新定义 Revit 单位规则。

执行前必须满足现有严格 fixture / preflight：

- exactly one target wall；
- target 是可证明的 wall semantic classification；
- current thickness 可读取；
- WallType 为本场景可安全隔离/独占的类型条件；
- 不存在本场景支持范围外的 hosted inserts/openings；
- 不存在实际 wall joins；
- revision barrier 与 grant/admission lineage 全部有效。

canonical effect 继续严格为：

```text
PROPERTIES
```

Revit 因 WallType reassignment / regeneration 产生的内部几何刷新不是额外的 `GEOMETRY` authority。若 ActualDelta 观察到审批范围外的 entity/aspect 变化，应作为 scope breach 处理，而不是扩张批准 scope 来适配执行结果。

---

## 13. Product success is a two-part proof

产品 `SUCCEEDED` 必须同时满足两部分：

### 13.1 Execution/reconciliation truth

现有 execution owners 必须已经安全收口。Host dispatch recovery 仍优先于 Saga 状态解释；`OUTCOME_UNKNOWN`、`RECOVERY_REQUIRED` 等状态不能被产品层跳过。

### 13.2 Independent result proof

同一次执行必须完成：

```text
independent Revit read-back
  ↓
post-state snapshot
  ↓
ActualDelta
  ↓
ScopeComparator
  ↓
semantic reconstruction
  ↓
SemanticVerifier
```

并证明：

1. target entity 与批准 lineage 一致；
2. ActualDelta 不包含未批准 entity/aspect；
3. reconstructed semantic state 仍能证明目标是 wall；
4. reconstructed wall thickness 等于批准目标 300 mm，按既有 live tolerance 判断；
5. evidence 来自 post-execution read-back，而不是 Host command response echo。

只有 13.1 和 13.2 都通过，`WallThicknessProductFlow` 才能向产品 surface 报告 `SUCCEEDED`。

重要区分：如果 generic execution Saga 已经 `SUCCEEDED`，但 independent semantic proof 失败，产品 task **不得**报告 `SUCCEEDED`。产品层也不得伪造 Saga 回退 transition；它应保留 execution truth，并以 verification failure / authoritative reconciliation result 明确收口。

---

## 14. Failure and recovery semantics

以下情况必须 fail closed：

| Condition | Required outcome |
|---|---|
| selection 不是 exactly one | `REJECT` before planning/execution |
| 无法证明 canonical wall classification | `REJECT` |
| authoritative context stale | 进入既有 freshness path；不得继续旧 context |
| current thickness 无法读取 | `REJECT` |
| isolation / WallType / join / hosted-object 条件不满足 | `REJECT` before Host mutation |
| operation/context exact lineage mismatch | fail closed |
| ChangeSet / approval / plan / binding / grant lineage mismatch | fail closed |
| grant expired / revoked / invalid | fail closed；不得 dispatch |
| Host commit outcome unknown | 进入既有 Host-effect recovery；不得新建第二 command identity |
| restart 后 exact workflow artifact 无法解析 | fail closed；不得通过 latest/recompute 补齐 |
| ActualDelta 含额外 entity/aspect | `SCOPE_BREACH` / authoritative divergence path；不得 product success |
| Host reports success but read-back != 300 mm | verification failure；不得 product success |
| semantic reconstruction 无法证明 postcondition | verification failure；不得 product success |

恢复顺序继续遵守 ADR-010/ADR-009：

```text
先读取 Host-effect recovery truth
  ↓
再解释 Saga truth
  ↓
最后决定 may-dispatch / recover-or-wait / terminal
```

产品层不得从 checkpoint node 位置推断“Host 应该还没执行”。

---

## 15. Persistence and checkpoint contract

本阶段冻结：**不扩张 `WorkflowCheckpoint` schema。**

理由：

- 当前 graph state 已经显式携带 semantic/planning/execution 所需 refs；
- checkpoint 应继续只承担 workflow progression / navigation / pending interaction / stable-reference retention；
- ApprovalScope、ActualDelta、semantic reconstruction evidence 等领域事实应留在原 authoritative owner；
- 把完整 product proof 数据复制进 checkpoint 会重新制造第二份 truth。

`WallThicknessProductFlow` 如果需要恢复产品 UI，只能通过：

```text
product task identity
  + existing workflow runtime/checkpoint view
  + exact authoritative owner refs/read models
```

恢复，不允许把完整 ChangeSet、Grant、Saga 或 semantic post-state 嵌入新的 product checkpoint blob。

如果 implementation census 证明现有 read surface 无法在不复制事实的情况下完成 product resume，必须提交 Design amendment；不得直接添加 checkpoint 字段。

---

## 16. Offline product E2E

必须新增一条真正的 product E2E，但其测试替身边界严格受限。

### 16.1 Must be real

至少以下必须使用 repository production implementations：

- current LangGraph workflow topology/runtime；
- `DefaultWorkflowServices`；
- `CanonicalWorkflowOwnerPorts`；
- OperationResolver；
- ParameterBinder；
- context/freshness path；
- Impact；
- ApprovalScope / ChangeSet；
- approval/admission；
- Execution Planning；
- Provider Binding；
- Gateway / Grant；
- Saga / recovery；
- reconciliation；
- wall-thickness result proof components that already exist in repository.

### 16.2 May be narrow doubles

Offline E2E 可以替代真正无法在普通 CI 中运行的 Revit process / UI environment，但 double 只能模拟 external Host boundary：

- 接受 production execution request；
- 按 `revit.set_wall_thickness.v1` contract 返回 execution effect；
- 暴露 independent read-back 所需 post-state；
- 不自行决定 eligibility、scope、approval、grant、reconciliation 或 semantic success。

禁止重新引入一个“大一统 product fake”来同时扮演 Revit、Gateway、Saga、Reconciliation 和 SemanticVerifier。

---

## 17. Live Revit product E2E

Live acceptance 必须用与 offline E2E **同一个 `WallThicknessProductFlow` + workflow composition**，只把 external Revit Host double 换成真实 Revit 环境。

fixture 继续沿用 Phase H strict conditions：

```text
exactly one isolated wall
exclusive WallType
no supported hosted inserts/openings
no actual wall joins
```

测试必须记录并能关联：

- product task id；
- context snapshot identity/hash；
- operation identity/hash；
- changeset identity/hash；
- approval identity；
- execution plan / binding / grant identity；
- Saga / Host dispatch identity；
- ActualDelta identity/hash；
- semantic verification result；
- final product outcome。

它必须证明这些证据来自**同一条 lineage**，而不是多个独立测试拼接出来的类似值。

---

## 18. Acceptance matrix

本阶段最小 acceptance matrix：

| Scenario | Offline E2E | Live Revit | Expected |
|---|---:|---:|---|
| happy path: one wall -> 300 mm | required | required | product `SUCCEEDED` |
| operation proposal reject | required | optional | cancelled, no execution |
| stale context | required | optional | freshness/re-acquire path, no stale execution |
| parameter/context lineage mismatch | required | optional | fail closed |
| approval/grant mismatch | required | optional | fail closed before Host mutation |
| grant revoked/expired | required | optional | fail closed before dispatch |
| Host outcome unknown | required | optional | recover/wait, no duplicate dispatch |
| scope extra entity/aspect | required | required where deterministic fixture permits | no product success |
| Host success + read-back wrong thickness | required | required where injectable | verification failure |
| restart at HITL | required | optional | exact refs restored; no recompute |
| restart after dispatch | required | optional | owner truth/recovery determines route |
| exact final semantic thickness 300 mm | required | required | independent semantic proof GREEN |

Live test 的“required where injectable”不能通过修改 production Host 逻辑制造假状态；允许使用既有 deterministic test fixture/failure injection seam。若当前 live harness 不具备该 seam，保持 offline mandatory，并在 implementation plan 中把 live-negative coverage 标成明确 evidence limitation，而不是伪造测试能力。

---

## 19. Observability and audit evidence

本阶段需要的是 lineage evidence，不是新增 observability platform。

每次 product run 的审计输出必须能回答：

1. 哪个 `task_id` 发起；
2. 哪个 exact context snapshot 被使用；
3. 哪个 operation proposal 被人接受；
4. 哪个 bound operation / impact / ChangeSet 被批准；
5. 哪个 execution plan / provider binding / grant 被执行；
6. 哪个 Saga 与 Host dispatch identity 代表真实 side effect；
7. 哪个 ActualDelta 与 post-state reconstruction 证明最终状态；
8. 最终产品 outcome 为什么是成功、拒绝、恢复等待、scope breach 或 verification failure。

日志/测试证据只能引用 owner identities/hashes；不得复制大型 domain payload 作为新的事实存档。

---

## 20. Design invariants

实现与 review 必须保持以下不变量：

1. **One workflow:** 不新增第二个 wall-thickness orchestrator。
2. **One owner per truth:** 每类 domain truth 继续只有现有 authoritative owner。
3. **Exact lineage:** 不允许 latest/reverse-lookup/approximate equivalence fallback。
4. **No reinterpret-on-resume:** approval 后绝不根据用户请求重建“等价计划”。
5. **No checkpoint domain duplication:** 不扩张 checkpoint 保存领域真相。
6. **No universal wall-thickness field:** 继续使用 operation/host semantic contract。
7. **PROPERTIES only:** Revit regeneration 不扩大 canonical authority。
8. **Host success is insufficient:** 必须 independent proof。
9. **Product success is stricter than execution success:** execution truth 与 product acceptance truth 不混写。
10. **Real owners in acceptance:** `_ScenarioOwners` 类 aggregate fake 不得进入产品 acceptance path。
11. **Same composition offline/live:** 只替换真实 external Revit boundary。
12. **Strict fixture remains strict:** 不为 GREEN 放宽 Phase H preflight。

---

## 21. Implementation boundary for the next gate

本 Design Spec 获得 Written-Spec Review 通过后，implementation plan 才可以展开。

计划阶段应按以下顺序做 repository-grounded census 与 TDD task decomposition：

```text
product ingress
  -> existing task/context bridge
  -> current semantic workflow closure
  -> product preview/HITL adapter
  -> Revit execution wiring
  -> independent result proof wiring
  -> offline product E2E
  -> live Revit product E2E
  -> exact-head CI
  -> merge
  -> merged-main observation
```

implementation plan 不得预设新的 store、checkpoint field、generic semantic schema 或 Saga transition；只有 repo census 证明存在真实缺口，且仍符合本设计 ownership 时才可提出最小实现。

---

## 22. Written-spec review checklist

在进入 implementation planning 前，本设计必须逐项通过：

- [ ] successor scope 与 Real-Owner E2E predecessor 不重叠；
- [ ] 当前 graph 已有 semantic/planning stages 被明确复用；
- [ ] `WallThicknessProductFlow` 被明确标记为新 thin application seam，而非 domain owner；
- [ ] 没有虚构当前不存在的 authoritative owner API；
- [ ] product ingress 不把 selection/model facts 当作 client authority；
- [ ] operation/context exact lineage 被保留；
- [ ] ApprovalScope 等 owner-internal authority 没有为了方便被复制到 checkpoint；
- [ ] approval/restart 不允许 reinterpret/recompute；
- [ ] wall thickness 没有提升成 universal canonical field；
- [ ] canonical effect 保持 `PROPERTIES`；
- [ ] Host `success=true` 没有被视为 product success；
- [ ] independent read-back / ActualDelta / semantic verification 是 mandatory success gate；
- [ ] execution Saga truth 与 product verification outcome 被区分；
- [ ] offline/live acceptance 使用同一 product composition；
- [ ] live Revit strict fixture 没有放宽；
- [ ] MCP/Agent、multi-entity、cross-host、new Saga semantics、V1 retirement 均保持非目标；
- [ ] 本设计没有要求扩张 `WorkflowCheckpoint` schema。

只有这份 Written-Spec Review 被明确批准后，下一步才是 implementation plan；在此之前不得修改产品代码。