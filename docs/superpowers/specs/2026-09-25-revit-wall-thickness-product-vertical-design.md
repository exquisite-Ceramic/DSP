# Capability Phase — Revit Wall Thickness Product Vertical Design

**Status:** Draft — Written-Spec Review Gate, review amendment 1 applied
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
提交结构化请求“把这面墙厚度改为 300 mm”
  ↓
immutable ProductTask request
  ↓
现有 workflow：context / operation / binding / planning / approval
  ↓
execution grant / admission
  ↓
real Revit mutation
  ↓
HostCommitted / ActualDelta
  ↓
ScopeComparator
  ↓
independent post-commit Revit READ
  ↓
verification evidence / semantic reconstruction
  ↓
Step33 semantic verification
  ↓
convergence / Saga terminal
  ↓
product task outcome projection
```

这里的目标不是再建设一套 domain stack，而是证明：**同一个 ProductTask、同一条 immutable authority lineage、同一个 durable workflow，能够从真实 Revit 产品输入一直运行到真实执行后的 Step33 结果证明。**

前驱 Real-Owner E2E 已有意把“完整 `semantic -> plan -> approve -> execute -> reconcile` 产品场景”留给 successor。本设计正好承接这一保留项；它不重做前驱 composition，也不把新的产品语义塞回 `CanonicalWorkflowOwnerPorts`。

本 amendment 进一步冻结三点：

1. mandatory post-commit semantic proof 必须进入现有 Step33 / materialized coordinator 成功终态之前，而不是由 product facade 在 Saga terminal 之后再做第二套 verifier；
2. 用户请求中的 `300 mm` 必须由 durable、immutable product-request ownership 进入 ParameterBinder input assembly，不能依赖进程内“当前请求”；
3. canonical operation、provider tool、HostCommand operation 与 native-unit implementation 必须保持现有四层边界，不得混名。

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

3. `WorkflowStartRequest` 已经包含 `request_data`，LangGraph runtime 会把它写入 durable graph state；但是当前 parameter-binding service seam 只显式传递 `operation_ref + context_snapshot_ref`。因此“请求数据被 checkpoint 保存”并不等于“ParameterBinder 能在 restart 后按 exact task request 取回 INTENT 参数”。

4. `DefaultWorkflowServices.bind_parameters()` 当前通过：

   ```text
   load_parameter_binding_inputs(
       operation_space_ref,
       context_snapshot_ref,
   )
   -> OperationProposal + ParameterBindingContext
   ```

   获取 binder 输入。当前 real-owner E2E 的 environment boundary 在测试中直接构造 `300 mm` proposal；这证明真实 ParameterBinder 可工作，但尚未证明产品请求 lineage。

5. `WorkflowServices` / `DefaultWorkflowServices` 已把 framework-neutral orchestration 与 deterministic owners 分离；OperationResolver 与 ParameterBinder 在 service adapter 内使用真实 deterministic implementation，其余 owner 通过 stable ports 访问。

6. `CanonicalWorkflowOwnerPorts` 已经是 production/reference composition seam，并负责把 Impact、ChangeSet、Approval、Execution Planning、Provider Binding、Gateway/Grant、Saga、Reconciliation、Recovery 等真实 authoritative owners 接到 workflow。

7. 前驱 real-owner E2E 已证明上述 composition 可以在 durable workflow / PostgreSQL owner 路径上工作；本阶段不得重新发明 `_ScenarioOwners` 风格的 authoritative aggregate fake 来替代这些 owner。

8. Phase H 已冻结 Revit wall-thickness 的层级：

   | Layer | Frozen value |
   |---|---|
   | canonical operation | `set_wall_thickness.v1` |
   | Revit provider tool | `revit.set_wall_thickness` |
   | `HostCommand.operation` | `set_wall_thickness` |
   | HostCommand thickness unit | `mm` |
   | Revit native implementation | 在 native boundary 转换为 Revit internal length units |

   `revit.set_wall_thickness.v1` **不是**现有 public contract。

9. Phase H 的 native mutation 是：目标 wall 必须使用仅被该 wall 使用的既有 `WallType`；provider 修改这个现有 `WallType` 的 `CompoundStructure`，不复制 WallType，也不把 wall 重新分配到另一个类型。

10. Phase H 已经要求 mutation 内部做 post-commit read-back，并在 Host result 中返回 before/after evidence；但当前 live test 的 semantic reconstruction 仍直接消费 mutation response 的 `payload["width_after_mm"]`。因此当前 live acceptance **不能**被描述为“独立于 command response 的再次读取”。

11. `MaterializedExecutionSagaCoordinator` 当前成功路径的顺序已经是：

   ```text
   Host commit
     -> record HostCommitted / ActualDelta
     -> begin reconciliation
     -> ScopeComparator
     -> evidence_port.build_bundle(...)
     -> verify_semantics(...)
     -> record_verification_result(...)
     -> convergence
     -> Saga terminal
   ```

   因此本产品 vertical 的 mandatory semantic proof 必须接入 `evidence_port` / Step33 verification path；product facade 不再拥有 post-terminal verifier。

12. 当前 Revit plugin 已有内部 `RevitWallSnapshotReader`，并有 `READ/check_wall_thickness_readiness` 路径；但是没有一个专门用于“已提交执行的独立 post-commit semantic proof”的 public READ operation。

这些 baseline observations 是本设计的输入，不意味着具体文件名、store 类名或 table 名自动成为长期架构 contract。

---

## 3. Problem statement

当前仓库已经分别证明两件事：

```text
A. real-owner workflow composition 可以跑通并恢复

B. Revit wall-thickness Host capability 可以真实改墙，
   并能产生 Host mutation evidence / ActualDelta / Phase H verification inputs
```

但 `A + B` 仍不等于一个真实产品 vertical。

尚未被冻结并验证的是：

```text
同一个 immutable 产品请求
  -> 创建/进入同一个 task_id
  -> 捕获真实 Revit authoritative context
  -> 经过当前真实 workflow owner chain
  -> 在 ParameterBinder 中取回该 task 自己的 300 mm INTENT 参数
  -> 产生并批准 immutable execution authority
  -> 真实执行 canonical set_wall_thickness.v1
  -> provider tool revit.set_wall_thickness
  -> HostCommand operation=set_wall_thickness, unit=mm
  -> Host commit / ActualDelta
  -> 对同一次 commit revision 发起独立 READ
  -> 在 Step33 成功终态之前完成 scope + semantic verification
```

如果只把现有 Real-Owner E2E 测试和 Phase H Revit 测试并排运行，就仍然存在 composition gap：两边可能使用不同 task identity、不同 request parameter、不同 snapshot、不同 scope、不同 operation payload，甚至不同执行证据，而测试仍可能分别 GREEN。

本阶段必须同时消灭：

```text
product request lineage gap
+
post-commit evidence lineage gap
```

---

## 4. Goals

本阶段必须满足以下目标：

1. 建立一条从真实 Revit 产品请求到最终 Step33 结果证明的单一 vertical；
2. 复用现有 LangGraph topology、`WorkflowServices`、`DefaultWorkflowServices` 与 `CanonicalWorkflowOwnerPorts`，不建立第二个 workflow runtime；
3. 产品入口拥有 immutable user-request record；workflow 继续拥有 progression/navigation；二者 ownership 不混写；
4. selected entity identity、Host revision、context facts 必须来自 authoritative Revit/context capture，而不是把 presentation 输入当成事实；
5. 用户请求中的 INTENT 参数必须通过 exact `task_id` 进入 ParameterBinder input assembly，restart 后不允许依赖 process-local “current request”；
6. semantic resolution、parameter binding、impact、ChangeSet、approval、planning、provider binding、grant、Saga、reconciliation 继续由当前 owner 持有；
7. approval 后 pause/restart/resume 必须继续 exact refs / hashes，不允许用用户原话重算已批准 artifact；
8. 真实执行必须保持现有 contract layering：canonical `set_wall_thickness.v1` -> provider `revit.set_wall_thickness` -> HostCommand `set_wall_thickness` with `mm`；
9. `Host success=true` 不能直接产生最终成功；
10. mandatory independent post-commit READ 必须在现有 reconciliation/verification path 内完成，并发生在 Saga `SUCCEEDED` 之前；
11. independent READ 必须绑定 exact host instance、document、native target 与 committed revision；中间 revision 漂移时不得把新状态伪装成本次执行证据；
12. offline product E2E 与 live Revit E2E 必须共享同一 product-flow composition，区别只能位于真实 Host/environment boundary；
13. 保持现有严格 Revit fixture，不为 demo 放宽安全前置条件；
14. 不新增第二份 domain truth。

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
- Revit mutation support-matrix 扩张；
- generic Host read API redesign；
- WallType duplication / reassignment policy；
- 为了产品 demo 放宽 wall isolation、join、hosted insert/opening 或 exclusive WallType 要求。

本阶段**允许且要求**增加一个极窄的 Revit read-only post-commit snapshot boundary，因为当前仓库没有能证明“独立于 mutation response 的再次读取”的 public Host read operation。该 read boundary 只服务本次 wall-thickness verification，不扩张 mutation support matrix，也不建立通用 query platform。

如果实现过程中发现其他非目标事项是硬前置，必须回到 Design amendment；implementation plan 不得把它们作为“顺手修改”吸收进去。

---

## 6. Architectural decision

选择 **Thin product facade over the existing real-owner workflow, with Step33-owned post-commit verification**。

本设计提出一个新的 product/application seam，暂定名：

```text
WallThicknessProductFlow
```

这是**新 proposed symbol**，不是当前仓库既有 API。它的职责只有：

1. 接受结构化 wall-thickness 产品请求；
2. 在启动 workflow 之前创建或读取 immutable ProductTask request；
3. 建立或解析当前 workflow 所需的 `task_id` / host-session linkage；
4. 启动或恢复现有 workflow runtime；
5. 把当前 workflow 的 preview / HITL interrupt 转成产品交互；
6. 读取现有 workflow / reconciliation / Saga 的 authoritative outcome，并把结果投影为产品 surface；
7. 只有当前 product composition 确认执行经过本设计冻结的 independent READ evidence path，且 authoritative Saga/reconciliation 成功收口时，才呈现 product `SUCCEEDED`。

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
- 在 Saga terminal 后再跑一套第二 verifier；
- 自己发明 reconciliation 结果；
- 自己把 wall width 写入一份新的 product truth store。

冻结调用关系：

```text
Revit product ingress
        │
        ▼
immutable ProductTask request owner       [new application ownership]
        │ task_id
        ▼
WallThicknessProductFlow                  [new thin application seam]
        │
        ▼
LangGraphWorkflowRuntime                  [existing]
        │
        ▼
DefaultWorkflowServices                   [existing]
        │
        ▼
CanonicalWorkflowOwnerPorts               [existing]
        │
        ├── Context / freshness
        ├── OperationResolver / ParameterBinder
        ├── Impact / ApprovalScope / ChangeSet
        ├── Approval / Gateway / Grant
        ├── Execution Planning / Provider Binding
        └── Execution Saga / Host dispatch recovery
                         │
                         ▼
MaterializedExecutionSagaCoordinator      [existing]
        │
        ├── Host mutation
        ├── ActualDelta
        ├── ScopeComparator
        ├── evidence_port.build_bundle
        │       └── independent Revit post-commit READ   [new narrow read seam]
        │               -> semantic reconstruction
        ├── Step33 verify_semantics
        ├── record_verification_result
        ├── convergence
        └── Saga terminal
                         │
                         ▼
WallThicknessProductFlow outcome projection
```

产品层不再定义“execution truth + product verifier truth”两个彼此独立的成功状态。对于本 vertical，mandatory semantic verification 是 authoritative execution/reconciliation terminalization 的组成部分。

---

## 7. Why not the alternatives

### 7.1 Rejected — second wall-thickness workflow

为 wall thickness 新建一个专用 orchestrator，把 semantic、planning、approval、execution 再串一次，会直接复制 ADR-010 workflow ownership，并制造两套恢复语义。拒绝。

### 7.2 Rejected — put Revit product semantics into `CanonicalWorkflowOwnerPorts`

`CanonicalWorkflowOwnerPorts` 是 generic owner composition adapter。把“exactly one wall”“300 mm”“独占 WallType”等产品/Host 约束塞进去，会让 production composition adapter 变成 Revit-specific domain owner。拒绝。

### 7.3 Rejected — product-side post-terminal verifier

现有 materialized coordinator 已经在 Saga 成功终态之前执行 scope comparison、evidence bundle、semantic verification 与 convergence。若 product facade 在 terminal 后再触发 mandatory verifier，会制造第二套 success authority，并与 Step33 ownership 冲突。拒绝。

终态后的额外 observation 可以作为 diagnostics/monitoring，但它不能替代本次 execution 的 Step33 verification，也不能改变已经持久化的 Saga transition。

### 7.4 Chosen — thin facade + existing workflow + pre-terminal independent evidence

本方案只新增产品 request/composition seam 与一个 narrow Revit READ boundary；mandatory proof 进入现有 `evidence_port -> verify_semantics -> reconciliation` path。

---

## 8. Product request ownership and ingress contract

### 8.1 Structured request, not NLP

本阶段不引入 NLP。产品请求是结构化输入，语义上至少包含：

```text
task_id
host kind = REVIT
active host/session linkage
requested product action = wall thickness change
requested thickness = { value: 300, unit: mm }
```

字段级 Python/C# 类型名由 implementation plan 在 repo census 后确定；本设计只冻结 ownership 与 invariants。

### 8.2 Immutable ProductTask request owner

产品/application 层必须拥有一份 durable、immutable 的 ProductTask request record。概念上至少满足：

```text
primary identity = task_id
request_hash     = canonical hash of immutable request body
create semantics = create-once / same-body idempotent
mutation         = forbidden after workflow start
```

具体 store/class/table 名不在本设计中冻结；implementation plan 必须先 census 是否已有可复用 durable application store，再决定最小实现。

该 request record 是**用户 intent 输入**的 authority，但不是 Host/model facts 的 authority。

它可以记录：

- requested product action；
- requested thickness `300 mm`；
- host kind；
- 用于定位产品 session 的稳定 linkage。

它不得把以下内容当成 client-authoritative model truth：

- selected wall semantic/native identity；
- current wall thickness；
- wall classification；
- WallType identity；
- current Host revision；
- join / hosted insert / opening 状态。

这些事实必须由 `resolve_host_context(task_id)` 及其 authoritative Host/context providers 捕获，并形成当前 workflow 的 `context_snapshot_ref`。

### 8.3 Request-to-binder lineage amendment

当前 graph 已经持有 `task_id`，但 parameter-binding seam 尚未显式携带它。本阶段冻结一个**窄 contract amendment**：

```text
parameter_binding node
  receives state.task_id
  + operation_ref
  + context_snapshot_ref

DefaultWorkflowServices / ExternalOwnerPorts binding-input seam
  must carry task_id explicitly

binding-input assembly
  loads immutable ProductTask request by exact task_id
  + loads exact ContextSnapshot-bound ParameterBindingContext
  -> constructs OperationProposal
  -> constructs ParameterBindingInputs
  -> real ParameterBinder.bind(...)
```

本设计不要求最终方法名一定为：

```text
bind_parameters(task_id, operation_ref, context_snapshot_ref)
load_parameter_binding_inputs(task_id, operation_ref, context_snapshot_ref)
```

但语义必须等价：**task identity 必须显式到达 proposal assembly；禁止通过 context reverse lookup、global “current request”、thread-local、singleton cache 或“最近一次请求”恢复 300 mm。**

对于本 vertical，proposal assembly 必须从该 task 的 immutable request 产生：

```text
OperationProposal(
    canonical_operation = set_wall_thickness.v1,
    intent_arguments = {
        thickness: { value: 300, unit: mm }
    }
)
```

`DefaultWorkflowServices` 仍必须验证 proposal 的 canonical operation 位于 persisted operation space 内；产品 request 不能绕过 OperationResolver。

### 8.4 Restart semantics

在 ParameterBinder 完成之前，如果 workflow 因 operation-proposal HITL 暂停并重启：

```text
task_id
  -> reload exact immutable ProductTask request
  -> exact operation_space_ref
  -> exact context_snapshot_ref
  -> rebuild ParameterBindingInputs
```

只要 request record、operation artifact 或 context artifact 任一 unavailable/mismatch，就 fail closed。

ParameterBinder 成功后，bound operation artifact 已 content-address 用户 INTENT argument 与 exact context lineage；此后 approval/execution recovery 不再依赖重新解释原始 product request。

### 8.5 Existing `request_data`

`WorkflowStartRequest.request_data` 可以继续作为 runtime-local start metadata carrier，但它**不是**本设计用来解决 request authority 的 process-local escape hatch。

本阶段不新增 checkpoint field。若 implementation 选择在现有 `request_data` 中携带一个稳定 product-request locator/hash，该值只能用于引用/校验 immutable request owner；不得复制一份可变 request body 后让 binder 从 checkpoint 与 request store 二选一。

### 8.6 Mandatory interleaving acceptance

必须新增：

```text
Task A: same Host/context, request thickness = 300 mm
Task B: same Host/context, request thickness = 350 mm

start A -> pause before ParameterBinder
start B -> pause before ParameterBinder
rebuild product flow/runtime/adapters
resume B
resume A
```

并证明：

- B 只绑定 350 mm；
- A 只绑定 300 mm；
- 两者 operation/context refs 不发生 request cross-talk；
- 不存在 process-local “current request” 依赖。

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

parameter binding input assembly(
    task_id,
    operation_ref,
    context_snapshot_ref,
)
  -> ProductTask request + exact semantic context
  -> OperationProposal + ParameterBindingContext

real ParameterBinder
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

provider binding / grant / execution / Step33 reconcile
```

对于本产品 vertical，OperationResolver/ParameterBinder 最终必须收敛到 canonical `set_wall_thickness.v1`，而不是由产品 facade 直接绕过 resolver 注入 Host command。

---

## 10. Authority lineage

### 10.1 Pre-binding request lineage

ParameterBinder 完成前：

```text
ProductTask request
(task_id + immutable request_hash)
  ↓
exact task_id
  ↓
context_snapshot_ref
  ↓
operation-space operation_ref
  ↓
ParameterBindingInputs
  ↓
bound operation_ref
```

ProductTask request body 不进入 downstream owner 作为第二份 plan truth。

### 10.2 Workflow-visible lineage

ParameterBinder 成功后，继续保留当前 graph 已显式携带的 exact lineage：

```text
task_id
  ↓
context_snapshot_ref
  ↓
bound operation_ref
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

### 10.3 Owner-internal lineage

ApprovalScope、execution slice、binding set、grant admission 等 owner-internal authority 即使不作为独立 graph field 暴露，也必须由其 owner 在 changeset/planning/grant/reconciliation 路径上精确验证。

本阶段不能为了“看起来 lineage 更完整”而把所有 owner internal refs 复制进 checkpoint。

### 10.4 User request stops being downstream authority

结构化用户请求在 ParameterBinder 之前拥有 INTENT-input authority；一旦 bound operation / ChangeSet / approval / execution artifacts 已冻结：

```text
resume/restart
  != reread user request and recompute an equivalent plan

resume/restart
  = reload exact persisted refs
    + ask authoritative owners for current state
```

尤其 approval 之后，任何无法解析原 exact artifact 的情况都必须 fail closed；不能重新解释“300 mm”并创建一个“语义等价”的新计划继续执行。

---

## 11. HITL / preview / resume semantics

产品层把现有 workflow interrupt 转成 UI interaction，但不拥有 HITL authority。

必须满足：

1. operation proposal pause 继续绑定当前 durable pause identity 与 exact operation-space `operation_ref`；
2. pause/restart 后 ParameterBinder 从 exact `task_id` 对应的 immutable ProductTask request 恢复 INTENT 参数；
3. preview 展示来自当前 `preview_ref` / approved ChangeSet lineage，而不是 product layer 自己重算；
4. approval resume 必须关联原 durable pause / approval identity；
5. restart 后 UI 可以重新渲染当前 pending interaction，但不能创建新的 domain artifact 来“恢复界面”；
6. rejected/cancelled interaction 不能进入 execution；
7. stale context / stale operation 必须返回既有 freshness path，不得由产品层覆盖。

本阶段只允许第 2 项所需的 task/request-lineage seam amendment；不改变现有 human-pause identity contract。

---

## 12. Revit wall-thickness execution contract

### 12.1 Four-layer naming and unit boundary

本产品 vertical 必须复用现有分层：

```text
canonical operation
  = set_wall_thickness.v1

ProviderBinding provider_tool
  = revit.set_wall_thickness

HostCommand
  mode      = EXECUTE
  operation = set_wall_thickness
  arguments = {
      thickness: {
          value: 300,
          unit: mm
      }
  }

Revit native implementation
  = convert 300 mm to Revit internal length units immediately behind native boundary
```

禁止：

- 使用 `revit.set_wall_thickness.v1` 作为 public contract；
- 把 Revit internal units 直接暴露给 product/canonical/HostCommand transport；
- 让 D4/ParameterBinder 学习 Revit unit API。

### 12.2 Native mutation remains Exclusive Isolated WallType MVP

执行前必须满足 Phase H 已冻结的严格条件：

- exactly one approved target wall；
- target 是可证明的 wall semantic classification；
- current thickness 可读取；
- `WallKind.Basic`；
- target wall 的既有 `WallType` 只被该 approved wall 使用；
- `CompoundStructure` 可用且是支持的单 editable layer shape；
- 不存在本场景支持范围外的 hosted inserts/openings；
- 不存在实际 wall joins；
- native associativity 可证明隔离；
- revision barrier 与 grant/admission lineage 全部有效。

mutation 语义继续是：

```text
read existing target WallType
  -> build modified CompoundStructure
  -> WallType.SetCompoundStructure(modified)
  -> commit
```

不得：

- duplicate WallType；
- reassign target wall to a different WallType；
- 通过扩大 approval scope 来包容原本不安全的 shared WallType。

canonical effect 继续严格为：

```text
PROPERTIES
```

Revit 因现有 WallType/representation regeneration 产生的内部几何刷新不是额外的 `GEOMETRY` authority。若 ActualDelta 观察到审批范围外的 entity/aspect 变化，应作为 scope breach 处理，而不是扩张批准 scope 来适配执行结果。

---

## 13. Mandatory independent verification lives inside Step33

### 13.1 Existing coordinator order is authoritative

本 vertical 不新建 success pipeline。成功路径必须保持：

```text
EXECUTE set_wall_thickness
  ↓
Host result adapter
  ↓
HostCommitted + ActualDelta
  ↓
record_host_commit
  ↓
begin_reconciliation
  ↓
ScopeComparator
  ↓
evidence_port.build_bundle
  ↓
Step33 verify_semantics
  ↓
record_verification_result
  ↓
convergence
  ↓
Saga terminal
```

因此独立 read-back **不是**在 Saga terminal 后由 `WallThicknessProductFlow` 触发。

### 13.2 What current Phase H proof does and does not prove

Phase H mutation 自身已经在 transaction 后读取 native wall width，并把结果放进 mutation response；这对 Host 成功判断仍然有效。

但当前 Phase H live semantic proof 直接使用：

```text
mutation_response.payload["width_after_mm"]
```

构造 post-state semantic facts。

该证据与 mutation response 同源，不能满足本产品 vertical 的“独立于 command response 的再次 Host read”要求。

### 13.3 New narrow Host read boundary

本阶段冻结一个 narrow Revit read-only verification operation，概念 contract 为：

```text
mode      = READ
operation = read_wall_thickness_snapshot

document_id       = exact execution document
host runtime       = exact execution HostRuntimeRef / host_instance_id
target_native_refs = exactly one admitted Wall.UniqueId
arguments          = none or read-only options only
idempotency_key    = forbidden
mutation precondition = forbidden
```

最终 public symbol/class name可在 implementation plan 中按 repository naming census 微调，但 wire-level behavior 必须是专门的 read-only post-commit snapshot，不得复用 EXECUTE response body 伪装成 read。

实现应复用现有 native `RevitWallSnapshotReader` 的读取能力，而不是建立第二套 Wall/WallType semantic reader。

read result 至少必须能证明：

- exact document id；
- exact wall `UniqueId`；
- observed wall thickness in `mm`；
- wall/native identity evidence；
- location/relationship evidence required by current verification contract；
- document revision observed before and after the read。

### 13.4 Exact execution correlation

`evidence_port.build_bundle(...)` 为当前 Revit slice 构建 verification evidence 时，必须把独立 READ 绑定到本次 execution lineage：

```text
execution_slice.host_runtime_ref.host_instance_id
  == host instance used for independent READ

ActualDelta.document_ref
  == READ document_id

ProviderBinding admitted native target Wall.UniqueId
  == READ Wall.UniqueId

ActualDelta.revision_after
  == READ revision_before
  == READ revision_after
```

最后一个等式是本阶段的核心 evidence window：

> independent READ 必须观察到**刚刚提交的那一个 document revision**，且 read 期间 revision 不得再次变化。

如果 commit 与 independent READ 之间有任何其他 Revit document change：

```text
current/read revision != ActualDelta.revision_after
```

则该 snapshot **不能**作为本次执行的 Step33 verification evidence。

不得：

- 接受“更新的 revision 但墙厚仍然是 300 mm”作为等价证据；
- reverse-search 一个历史 snapshot；
- 把 mutation response 的 `width_after_mm` 作为 independent fallback；
- 重新 dispatch mutation 以获得“干净证据”。

### 13.5 Revision mismatch outcome

revision mismatch 发生时，Host commit 已经是 known committed truth，因此它不是：

```text
BEFORE_COMMIT failure
```

也不能改写为新的 dispatch attempt。

verification evidence builder 必须 fail closed，使当前 Step33 verification **不能 PASSED**。具体稳定错误码由 implementation plan 在现有 reconciliation error surface census 后确定；若当前 Step33 API 无法表达“known commit, independent evidence not attributable to committed revision”而不产生语义损失，则必须停止 implementation 并提交 Design amendment，不得私自增加新的 Saga transition。

### 13.6 Semantic verification source

只有满足 13.4 的 independent snapshot 才能进入：

```text
Revit NormalizedDesignFact
  -> semantic reconstruction
  -> VerificationEvidenceBundle
  -> verify_semantics
```

并证明：

1. target entity 与批准 lineage 一致；
2. reconstructed canonical classification 包含 `ifc:IfcWall`；
3. reconstructed `dsp:WallThickness == 300 mm`；
4. ScopeComparator 已证明 ActualDelta 没有未批准 entity/aspect；
5. evidence 不是 mutation response echo。

### 13.7 Product outcome projection

对于绑定了上述 evidence path 的本 vertical：

```text
Saga / materialized coordinator SUCCEEDED
```

已经意味着 scope comparison、mandatory semantic verification 与 convergence 在 authoritative execution path 内通过。

因此 `WallThicknessProductFlow` 只读取并呈现该 authoritative outcome；不再维护第二份“product verification status”。

终态后可以做额外观察用于 diagnostics，但它既不能替代 Step33 verification，也不能反向篡改 Saga terminal truth。

---

## 14. Failure and recovery semantics

以下情况必须 fail closed：

| Condition | Required outcome |
|---|---|
| ProductTask request 与 `task_id` 不存在 / hash invalid | fail closed before binder |
| 同一 `task_id` 被不同 request body 重用 | conflict / fail closed |
| selection 不是 exactly one | `REJECT` before planning/execution |
| 无法证明 canonical wall classification | `REJECT` |
| authoritative context stale | 进入既有 freshness path；不得继续旧 context |
| current thickness 无法读取 | `REJECT` |
| isolation / existing exclusive WallType / join / hosted-object 条件不满足 | `REJECT` before Host mutation |
| operation/context exact lineage mismatch | fail closed |
| task/request 与 ParameterBindingInputs cross-talk | fail closed |
| ChangeSet / approval / plan / binding / grant lineage mismatch | fail closed |
| grant expired / revoked / invalid | fail closed；不得 dispatch |
| Host commit outcome unknown | 进入既有 Host-effect recovery；不得新建第二 command identity |
| restart 后 exact workflow artifact 无法解析 | fail closed；不得通过 latest/recompute 补齐 |
| ActualDelta 含额外 entity/aspect | `SCOPE_BREACH` / authoritative divergence path；不得成功 |
| independent READ host/document/entity mismatch | verification evidence rejected |
| independent READ revision != committed revision | verification evidence rejected；不得使用 newer state |
| independent READ 期间 revision 变化 | verification evidence rejected |
| mutation response says 300 mm, independent READ != 300 mm | Step33 verification must not pass |
| semantic reconstruction 无法证明 postcondition | Step33 verification must not pass |

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

### 15.1 Workflow checkpoint ownership

checkpoint 继续只承担：

- workflow progression / navigation；
- pending interaction identity；
- existing stable refs；
- runtime-safe JSON-compatible state。

ApprovalScope、ActualDelta、semantic reconstruction evidence、Saga、Host dispatch truth 等领域事实继续留在原 authoritative owner。

### 15.2 Product request persistence

用户 INTENT request 由 product/application request owner durable 保存；它不是新的 workflow checkpoint domain blob。

恢复关系：

```text
task_id
  -> immutable ProductTask request owner
  -> exact request body/hash

workflow checkpoint
  -> exact workflow/navigation refs
```

ParameterBinder 前两者通过 exact `task_id` join；ParameterBinder 后 downstream 以 bound operation refs 为 authority。

本设计不要求把完整 ProductTask request 复制进 checkpoint，也不允许通过一份可变 process-local cache 替代 durable request owner。

### 15.3 No new checkpoint field

如果 implementation 需要将 stable request locator 放入已有 `request_data`，可以在不扩张 schema 的前提下做最小引用；但：

- correctness 仍必须由 durable request owner 保证；
- 不允许 raw request body 与 request owner 双写后择一读取；
- 不允许新增完整 ChangeSet、Grant、Saga、ActualDelta 或 semantic post-state checkpoint fields。

如果 implementation census 证明现有 state/read surface 无法在上述约束下恢复，必须提交 Design amendment。

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
- immutable ProductTask request ownership implementation selected by plan；
- context/freshness path；
- Impact；
- ApprovalScope / ChangeSet；
- approval/admission；
- Execution Planning；
- Provider Binding；
- Gateway / Grant；
- MaterializedExecutionSagaCoordinator；
- Saga / recovery；
- reconciliation；
- verification evidence builder / semantic verification path。

### 16.2 May be narrow doubles

Offline E2E 可以替代真正无法在普通 CI 中运行的 Revit process / UI environment，但 double 只能模拟 external Host boundary：

- `EXECUTE/set_wall_thickness` 接受 production execution request；
- command thickness 仍以 `{value, unit=mm}` 表达；
- 返回 mutation Host evidence / ActualDelta input；
- `READ/read_wall_thickness_snapshot` 作为单独调用返回 post-commit snapshot；
- 独立 READ 必须拥有可控 revision，以验证 exact-revision acceptance/rejection；
- double 不自行决定 eligibility、scope、approval、grant、reconciliation 或 semantic success。

禁止重新引入一个“大一统 product fake”来同时扮演 Revit、Gateway、Saga、Reconciliation 和 SemanticVerifier。

---

## 17. Live Revit product E2E

Live acceptance 必须用与 offline E2E **同一个 `WallThicknessProductFlow` + workflow composition + Step33 evidence composition**，只把 external Revit Host double 换成真实 Revit 环境。

fixture 继续沿用 Phase H strict conditions：

```text
exactly one isolated wall
existing WallType used only by that wall
no supported hosted inserts/openings
no actual wall joins
```

live execution 必须证明：

```text
canonical set_wall_thickness.v1
  -> provider revit.set_wall_thickness
  -> Host EXECUTE/set_wall_thickness, 300 mm
  -> known committed revision R
  -> separate Host READ/read_wall_thickness_snapshot
  -> read starts at R
  -> read ends at R
  -> semantic reconstruction from READ result
  -> Step33 verification PASSED
  -> Saga SUCCEEDED
```

测试必须记录并能关联：

- product `task_id` + request hash；
- context snapshot identity/hash；
- operation-space / bound operation identity/hash；
- changeset identity/hash；
- approval identity；
- execution plan / binding / grant identity；
- exact Revit host instance；
- Saga / Host dispatch identity；
- ActualDelta identity/hash + committed revision；
- independent READ command identity + observed revision；
- semantic verification result；
- final product outcome。

它必须证明这些证据来自**同一条 lineage**，而不是多个独立测试拼接出来的类似值。

当前 Phase H live 测试仅用 mutation response `width_after_mm` 做 semantic reconstruction，因此不能直接作为本条 acceptance 的最终 GREEN；它是前驱 evidence，必须新增真正的 separate READ path。

---

## 18. Acceptance matrix

本阶段最小 acceptance matrix：

| Scenario | Offline E2E | Live Revit | Expected |
|---|---:|---:|---|
| happy path: one wall -> 300 mm | required | required | Step33 verification + Saga/product `SUCCEEDED` |
| operation proposal reject | required | optional | cancelled, no execution |
| stale context | required | optional | freshness/re-acquire path, no stale execution |
| parameter/context lineage mismatch | required | optional | fail closed |
| two interleaved requests, same Host/context, 300 vs 350 | required | optional | each binds its own immutable request after rebuild |
| request store unavailable/hash mismatch before binding | required | optional | fail closed; no fallback to “current request” |
| approval/grant mismatch | required | optional | fail closed before Host mutation |
| grant revoked/expired | required | optional | fail closed before dispatch |
| Host outcome unknown | required | optional | recover/wait, no duplicate dispatch |
| scope extra entity/aspect | required | required where deterministic fixture permits | Step33 no success |
| mutation says 300, independent READ says other value | required | optional/injectable | Step33 verification not passed |
| independent READ wrong host/document/entity | required | optional | evidence rejected |
| independent READ revision newer than commit | required | required where deterministic change injection permits | evidence rejected; no “newer is good enough” |
| revision changes during independent READ | required | optional/injectable | evidence rejected |
| restart at operation proposal HITL | required | optional | exact task request + refs restored; no cross-talk/recompute |
| restart after dispatch | required | optional | owner truth/recovery determines route |
| exact final semantic thickness 300 mm at committed revision | required | required | independent Step33 semantic proof GREEN |

Live test 的“required where deterministic change injection permits”不能通过修改 production Host 逻辑制造假状态；允许使用既有 deterministic fixture/failure injection seam。若当前 live harness 不具备该 seam，保持 offline mandatory，并在 implementation plan 中把 live-negative coverage 标成明确 evidence limitation，而不是伪造测试能力。

---

## 19. Observability and audit evidence

本阶段需要的是 lineage evidence，不是新增 observability platform。

每次 product run 的审计输出必须能回答：

1. 哪个 immutable ProductTask request / `task_id` 发起；
2. 哪个 exact context snapshot 被使用；
3. 哪个 operation proposal 被人接受；
4. 哪个 bound operation / impact / ChangeSet 被批准；
5. 哪个 execution plan / provider binding / grant 被执行；
6. 哪个 exact Revit host instance / Host dispatch identity 代表真实 side effect；
7. 哪个 ActualDelta 与 committed revision 代表 Host commit；
8. 哪个独立 READ command 观察了相同 document/entity/revision；
9. 哪个 verification result / convergence result 让 Saga 进入最终终态；
10. 最终产品 outcome 为什么是成功、拒绝、恢复等待、scope breach 或 verification failure。

日志/测试证据只能引用 owner identities/hashes 与必要低基数 correlation metadata；不得复制大型 domain payload 作为新的事实存档。

---

## 20. Design invariants

实现与 review 必须保持以下不变量：

1. **One workflow:** 不新增第二个 wall-thickness orchestrator。
2. **One owner per truth:** 每类 domain truth 继续只有现有 authoritative owner。
3. **Immutable request:** `task_id` 对应 product request create-once；ParameterBinder 前可恢复，不能依赖 process-local current request。
4. **Explicit binder lineage:** task identity 必须显式进入 proposal/binding-input assembly。
5. **Exact lineage:** 不允许 latest/reverse-lookup/approximate equivalence fallback。
6. **No reinterpret-on-resume:** bound operation/approval 之后绝不根据用户请求重建“等价计划”。
7. **No checkpoint domain duplication:** 不扩张 checkpoint 保存领域真相。
8. **No universal wall-thickness field:** 继续使用 operation/host semantic contract。
9. **Operation layering is exact:** `set_wall_thickness.v1` -> `revit.set_wall_thickness` -> `set_wall_thickness` -> native internal units。
10. **Transport stays mm:** internal units 不越过 Revit native boundary。
11. **Existing WallType only:** 不 duplicate / reassign WallType。
12. **PROPERTIES only:** Revit regeneration 不扩大 canonical authority。
13. **Host mutation success is insufficient:** Step33 必须使用 separate post-commit READ evidence。
14. **Verification before terminal:** mandatory semantic proof 必须发生在 Saga `SUCCEEDED` 之前。
15. **Exact revision evidence:** independent READ 的 host/document/entity/revision 必须与本次 commit 精确一致。
16. **No newer-state substitution:** intervening document change 后的 snapshot 不能替代本次 execution evidence。
17. **No second product verifier:** product facade 只呈现 authoritative reconciliation/Saga outcome。
18. **Real owners in acceptance:** `_ScenarioOwners` 类 aggregate fake 不得进入产品 acceptance path。
19. **Same composition offline/live:** 只替换真实 external Revit boundary。
20. **Strict fixture remains strict:** 不为 GREEN 放宽 Phase H preflight。

---

## 21. Implementation boundary for the next gate

本 Design Spec 获得 Written-Spec Review 通过后，implementation plan 才可以展开。

计划阶段应按以下顺序做 repository-grounded census 与 TDD task decomposition：

```text
ProductTask request ownership/store census
  -> task_id-to-binder seam census
  -> product ingress
  -> existing task/context bridge
  -> current semantic workflow closure
  -> product preview/HITL adapter
  -> exact canonical/provider/HostCommand mapping
  -> Revit READ-only post-commit snapshot boundary
  -> evidence_port / Step33 verification wiring
  -> offline product E2E
  -> live Revit product E2E
  -> exact-head CI
  -> merge
  -> merged-main observation
```

implementation plan 不得预设：

- 新 checkpoint field；
- generic semantic schema；
- 新 Saga transition；
- WallType duplication/reassignment；
- 通用 Host query platform；
- 第二套 product verification state machine。

ProductTask request 的 concrete class/store 名、binder seam 的最终方法签名、read-operation 的代码 symbol 名，都必须先通过 repo census；但本设计冻结的 ownership、wire behavior、exact task lineage 与 exact revision evidence 不能在 plan 阶段弱化。

---

## 22. Written-spec review checklist

在进入 implementation planning 前，本设计必须逐项通过：

- [ ] successor scope 与 Real-Owner E2E predecessor 不重叠；
- [ ] 当前 graph 已有 semantic/planning stages 被明确复用；
- [ ] `WallThicknessProductFlow` 被明确标记为新 thin application seam，而非 domain owner；
- [ ] immutable ProductTask request ownership 已明确；
- [ ] `300 mm` 如何从 exact task request 进入 `OperationProposal` / ParameterBinder 已明确；
- [ ] operation-proposal pause/restart 后 request 恢复不依赖 process-local current request；
- [ ] 两个 interleaved task 不会发生 parameter cross-talk；
- [ ] product ingress 不把 selection/model facts 当作 client authority；
- [ ] operation/context exact lineage 被保留；
- [ ] ApprovalScope 等 owner-internal authority 没有为了方便被复制到 checkpoint；
- [ ] approval/restart 不允许 reinterpret/recompute；
- [ ] canonical `set_wall_thickness.v1`、provider `revit.set_wall_thickness`、HostCommand `set_wall_thickness` 三层命名已区分；
- [ ] HostCommand thickness unit 明确保持 `mm`；native internal units 不上浮；
- [ ] Revit mutation 明确修改独占的 existing WallType，不 duplicate / reassign；
- [ ] wall thickness 没有提升成 universal canonical field；
- [ ] canonical effect 保持 `PROPERTIES`；
- [ ] 当前 Phase H mutation-response semantic proof 没有被误称为 independent read；
- [ ] separate `READ/read_wall_thickness_snapshot` behavior 已冻结；
- [ ] independent READ 绑定 exact host instance / document / Wall.UniqueId / committed revision；
- [ ] intervening revision change 会拒绝证据，而不是接受 newer state；
- [ ] independent read-back / semantic reconstruction / Step33 verification 是 Saga success 前 mandatory gate；
- [ ] product facade 不再拥有 post-terminal mandatory verifier；
- [ ] offline/live acceptance 使用同一 product + Step33 evidence composition；
- [ ] live Revit strict fixture 没有放宽；
- [ ] MCP/Agent、multi-entity、cross-host、new Saga semantics、V1 retirement 均保持非目标；
- [ ] 本设计没有要求扩张 `WorkflowCheckpoint` schema。

只有这份 Written-Spec Review 被明确批准后，下一步才是 implementation plan；在此之前不得修改产品代码。
