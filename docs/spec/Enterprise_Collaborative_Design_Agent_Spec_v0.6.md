# DSP — Enterprise Collaborative Design Agent Specification v0.6

> 状态：Draft / Architecture Baseline Candidate  
> 日期：2026-08-28  
> 取代：`Enterprise_Collaborative_Design_Agent_Spec_v0.5.md` 作为下一版候选规格  
> 适用范围：多 Host 设计协同、Host MCP、Semantic MCP、Canonical Action、D5 Collaboration Kernel、D6 参数绑定、D7 ChangeSet/执行闭环  
> Metro Semantic 基线：`IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版`，目标 Schema 为 `IFC4X3_ADD2 / IFC 4.3.2.0`  
> 本次修订：恢复 v0.5 Runtime/Governance Contract Freeze 内容，并将 Progressive Semantic Modeling 与 v0.6 Semantic MCP/D5 架构统一。

---

## 0. 规范性语言

本文中的 **MUST / SHALL / 必须** 表示强制要求；**SHOULD / 应** 表示推荐要求；**MAY / 可** 表示可选能力。

除非另有说明：

- IFC 标准语义以实际锁定的 `IFC4X3_ADD2 / IFC 4.3.2.0` Schema 与正式文档为权威来源；
- Metro Semantic 中的项目扩展、`PsetProj_*`、`QtoProj_*`、IDS、映射与专项校验属于领域/项目实施语义，不得伪装成 IFC 官方 Schema；
- Host 原生对象类型、API 类型、内部单位和执行参数不得成为 DSP Canonical Semantic Model 的公共契约。

---

# 1. 目标与范围

## 1.1 目标

DSP 是一个面向 CAD/BIM/基础设施设计软件的企业级协同智能体平台。系统目标不是让 LLM 直接操作某个软件，而是建立一条可验证、可审计、可回放、可跨 Host 扩展的设计协同链路：

```text
用户意图
  ↓
Canonical Action
  ↓
Canonical Semantic State
  ↓
Progressive Semantic State
  ↓
Impact / ChangeSet / Approval
  ↓
ExecutionSlice / ExecutionUnit
  ↓
Provider Binding / ExecutionGrant
  ↓
Host Execution
  ↓
Host Delta
  ↓
Semantic Reconstruction
```

系统必须支持：

1. AutoCAD、Revit、Tekla 等不同 Host 通过统一 Host Contract 与平台通信；
2. Host 原生事实通过 Semantic Adapter 转换为稳定的数据契约；
3. IFC4.3 + DSP Core 形成跨 Host Canonical Semantic 基线；
4. Metro Semantic、企业标准、专业规则通过 Semantic Provider 扩展；
5. LLM 仅在受约束的 Canonical Action Space 内选择动作和填写意图槽；
6. 可确定性绑定的参数不交给 LLM；
7. D5 采用 Progressive Semantic Modeling / On-demand Reconstruction，只重建当前任务需要的语义与几何；
8. 任何写操作在执行前绑定 PlanningSnapshot、SnapshotSet、SemanticEnvironment 与审批上下文；
9. 所有模型写操作通过 immutable ChangeSet，并经过 ApprovalScopeBoundary 与授权链；
10. 跨 Host 执行通过 ExecutionSlice / ExecutionUnit / ProviderBinding 分层，不使用 Host-to-Host 硬编码；
11. 执行结果必须由 Host read-back / ActualDelta 形成闭环验证与 scope check；
12. LangGraph、Gateway、Semantic Service、D5、Host Provider 各自保持单一 owner，不形成“全能中枢”。

## 1.2 非目标

v0.6 不要求：

- DSP Core 直接理解所有 Revit/AutoCAD/Tekla 原生对象；
- 把 IFC 文件格式本身作为运行时唯一存储格式；
- 让 LLM 根据自然语言 `description` 推断安全规则；
- 为每个 Host 成对实现 Host↔Host 映射；
- 让 Metro Semantic 覆盖或修改 IFC 官方定义；
- 在没有 Freshness / Coverage / Assurance / Snapshot / Authorization 的情况下执行高风险写操作；
- 要求设计师高频编辑时持续维护全量、实时 IFC/Metro 镜像；
- 通过 XA/2PC 解决跨 Host 分布式事务。

---

# 2. 核心架构原则

## 2.1 Hub-and-Spoke，而不是 Host-to-Host

每个 Host 只需要实现：

```text
Host Native ↔ DSP Contracts / Canonical Semantics
```

不得实现：

```text
AutoCAD ↔ Revit
AutoCAD ↔ Tekla
Revit ↔ Tekla
...
```

平台扩展复杂度应接近 O(N)，而不是 O(N²)。

## 2.2 Core 不得包含 Host 分支

平台核心模块中禁止出现以 Host 产品为领域规则的判断：

```python
if host == "revit": ...
if host == "autocad": ...
```

Core 可以理解：

```text
SemanticId
ifc:IfcWall
Placement
Thickness
Relationship
Freshness
Assurance
```

Core 不应理解：

```text
Revit ElementId
BuiltInCategory.OST_Walls
AutoCAD Handle
A-WALL layer convention
Tekla native class code
```

## 2.3 MCP 是协议，不是领域边界

DSP 中至少存在两类 MCP Server：

```text
Host / Execution MCP
  回答：在这个软件里怎么执行？

Semantic MCP
  回答：这个语义词、规则、映射是什么意思？
```

MCP 只定义服务协议和发现/调用机制，不定义领域权威边界。

除非后续 ADR 显式修订，v0.6 的 MCP 协议目标基线继承 v0.5 的 `MCP 2026-07-28`；协议版本升级不得隐式改变 Host、Semantic、Action 或 Governance 领域契约。

平台模块 SHALL 依赖稳定领域 Contract，不 SHALL 直接依赖某个具体 MCP Server 实现。

## 2.4 固定 Structure + 最小 Canonical Vocabulary + 可扩展 Vocabulary

跨 Host 协作的内部数据必须同时满足：

```text
固定数据结构
+
固定最小 Canonical Vocabulary
+
可版本化扩展 Vocabulary
```

不能只固定 JSON 形状却允许语义词无限漂移。

## 2.5 Description 不是机器约束

所有可暴露给人或 LLM 的 Semantic Term / Canonical Operation SHOULD 提供 `label` / `description`。

但以下内容必须结构化表达：

- 类型；
- domain / range；
- 单位；
- 枚举；
- cardinality；
- entity constraint；
- freshness requirement；
- assurance requirement；
- validation rule；
- slot binding policy。

系统不得依赖自然语言 description 执行约束判断。

---

## 2.6 Progressive by default

DSP 的 semantic runtime MUST 默认采用：

```text
task-scoped
aspect-scoped
coverage-scoped
on-demand reconstruction
```

而不是：

```text
every edit
→ full semantic rebuild
→ full IFC/Metro mirror
```

Progressive 不等于弱约束。进入具体 operation / approval / execution 前，系统仍必须通过 Freshness、Coverage、Assurance、Snapshot 与 Policy barrier。

## 2.7 ChangeSet 与授权是唯一写路径

所有 `MODEL_OPERATION` 必须：

```text
Canonical Action
→ PlanningSnapshot/SnapshotSet
→ Impact
→ immutable ChangeSet
→ Approval/ExecutionGrant
→ ProviderBinding
→ Host mutation
→ Verify/Reconcile
```

LLM、Semantic Provider、Gateway、Host MCP 都不得绕过该链直接完成生产级模型修改。

---

# 3. 分层架构

DSP 至少区分六个逻辑平面：

## 3.1 Source of Truth

| State | Authoritative owner | Consistency model |
|---|---|---|
| Design-time native state | Host Application | 实时编辑事实 |
| Semantic definitions / mappings | Semantic Service + pinned Providers | version/hash pinned |
| Canonical semantic projection | D5 | progressive reconstruction + freshness/coverage barrier |
| Change history | Change Journal | append-only |
| Agent workflow state | LangGraph checkpoint | recoverable/replayable |
| Execution intent | immutable ChangeSet | approval/audit unit |
| Authorization evidence | Gateway | ApprovalRecord / ExecutionGrant |

Host 与 D5 不是双主数据库；D5 是 task-scoped canonical projection，Host 仍是 native realtime source of truth。

## 3.2 Logical planes


```text
Host Plane
Semantic Plane
Action Plane
Collaboration State Plane
Governance Plane
Execution Plane
```

参考拓扑：

```text
                              ┌──────────────────────┐
                              │        User          │
                              └──────────┬───────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │ LangGraph / LLM      │
                              │ Orchestrator         │
                              └───────┬──────┬───────┘
                                      │      │
                         action space │      │ semantic context
                                      ▼      ▼
                         ┌────────────────┐  ┌────────────────────┐
                         │ D4 Resolver    │  │ Context Composer   │
                         │ + Action Catalog│ └──────────┬─────────┘
                         └────────┬───────┘             │
                                  │                     ▼
                                  │          ┌────────────────────┐
                                  │          │ Enterprise Gateway │
                                  │          │ Auth/Policy/Audit  │
                                  │          └───────┬──────┬─────┘
                                  │                  │      │
                                  │                  │      └───────────────┐
                                  │                  ▼                      ▼
                                  │        ┌────────────────────┐   ┌──────────────────┐
                                  │        │ Semantic MCP Server│   │ Host/Execution MCP│
                                  │        │ Semantic Service   │   │ Providers          │
                                  │        └─────────┬──────────┘   └─────────┬────────┘
                                  │                  │                        │
                                  │           SemanticProvider                │
                                  │      ┌───────────┼────────────┐           │
                                  │      ▼           ▼            ▼           │
                                  │   IFC4.3       Metro      Enterprise       │
                                  │   Provider     Semantic    Semantic         │
                                  │
                                  ▼
                         ┌──────────────────────────┐
                         │ D5 Collaboration Kernel  │
                         │ Progressive Projection   │
                         │ Identity / Freshness     │
                         │ Coverage / Assurance     │
                         │ Snapshot / Journal       │
                         └────────────┬─────────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │ D6 Parameter Binder      │
                         │ + Host Interaction       │
                         └────────────┬─────────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │ Impact / Dependency      │
                         │ Constraint / Propagation │
                         └────────────┬─────────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │ D7 ChangeSet / Approval  │
                         │ Slice / Unit / Binding   │
                         └────────────┬─────────────┘
                                      │
                    ┌─────────────────┴──────────────────┐
                    ▼                                    ▼
            ┌────────────────┐                   ┌────────────────┐
            │ AutoCAD MCP    │                   │ Revit MCP      │
            │ Host Provider  │                   │ Host Provider  │
            └───────┬────────┘                   └───────┬────────┘
                    ▼                                    ▼
                AutoCAD                                Revit
```

核心边界：

```text
Host MCP        = 怎么在具体 Host 执行
Semantic MCP    = 标准/领域语义和规则是什么
D4              = 当前允许表达什么 canonical action
D5              = 当前设计已被理解成什么，以及理解到什么程度
D6              = 这次 action 的参数具体是什么
Impact Layer    = 这次修改可能影响什么、什么必须传播/验证
D7              = 准备审批、分片、绑定、执行和验证什么
Gateway         = 谁能调用什么、能否执行、如何审计
LangGraph       = task/workflow/checkpoint/HITL 的最终编排者
```

# 4. 互操作等级与 Progressive Semantic Model

DSP 的语义模型不是“一次性把 Host 转成完整 IFC”，而是按任务所需逐步提升语义深度、几何精度与事实覆盖范围。

## 4.1 四级语义互操作能力

### L0 — Native

只有 Host 原生对象和原生 ID。

```text
AutoCAD Handle A31
Revit ElementId 38912
```

仅支持 Host-local 操作。

### L1 — Normalized

数据结构已统一为 `NormalizedDesignFact`，但 canonical classification 可以未知。

可表达：

- identity；
- native kind / source scheme；
- placement；
- bounds；
- revision；
- basic geometry reference；
- native classification evidence。

### L2 — Canonical

至少具备任务所需的：

```text
SemanticIdentity
IFC4.3 canonical classification
DSP Core properties / relationships
canonical units / coordinates
Freshness
Assurance / Provenance
```

L2 是跨 Host 高层协作的最低语义基础，但不意味着实体所有 aspect 已完整重建。

### L3 — Domain / Enterprise

在 L2 基础上按需增加：

```text
Metro Semantic
Enterprise Semantic
专业 Vocabulary
IDS / domain validation
project-specific mappings
```

领域特定操作 MAY 要求 L3。

## 4.2 Progressive Semantic Modeling

同一个实体可以随任务逐步提升语义：

```text
Host Native
   ↓
Normalized Fact
   ↓
Canonical IFC/DSP semantics
   ↓
Metro / Enterprise / discipline semantics
```

例如 AutoCAD `A31`：

```text
阶段 1：
  native_id = A31
  native_kind = LWPOLYLINE
  layer = A-WALL

阶段 2：
  SemanticId = S-WALL-001
  placement / bounds resolved

阶段 3：
  classification = ifc:IfcWall
  dsp:WallThickness = 200mm

阶段 4：
  metro:WallDesign.DesignThickness = 200mm
  Metro IDS / engineering constraints resolved
```

平台 MUST NOT 因为对象最终可能参与 L3 协作，就在每次 Host 编辑后维护其完整 L3 镜像。

## 4.3 Aspect-level progressive state

Semantic Entity 的不同 aspect 可以处于不同的解析深度与覆盖状态：

```text
S-WALL-001

IDENTITY        resolved
PLACEMENT       resolved
CLASSIFICATION  canonical
PROPERTIES      partial
RELATIONSHIPS   unresolved
GEOMETRY        bounds
METRO           unresolved
```

因此：

```text
entity is L2
```

只能作为粗粒度能力标签，不能替代 aspect-level coverage。

D5 / Snapshot 必须能够表达“哪些 aspect / property / relationship 已被重建”，而不能把局部解析伪装成完整模型。

## 4.4 Geometry Progressive Levels

几何精度独立于 semantic depth：

| Level | 内容 | 典型用途 |
|---|---|---|
| `NONE` | 不读取 geometry | 纯属性/分类任务 |
| `BOUNDS` | AABB/OBB/axis/centroid | 定位、粗过滤、action applicability |
| `APPROXIMATE` | 简化 mesh/curve | broad-phase clash、快速规划 |
| `EXACT` | 精确可计算几何 | 精确碰撞、洞口、几何约束 |
| `NATIVE` | Host 原生 kernel/context | 必须由 Host native API 决定的操作 |

Context Freshness SHOULD 默认限制在 `NONE/BOUNDS`；只有 chosen operation 明确要求时才升级到 `APPROXIMATE/EXACT/NATIVE`。

## 4.5 四个正交维度

DSP 不得把下列概念合并：

```text
Semantic Depth
  NATIVE → NORMALIZED → CANONICAL → DOMAIN

Geometry Fidelity
  NONE → BOUNDS → APPROXIMATE → EXACT → NATIVE

Freshness
  UNKNOWN / DIRTY / RECONSTRUCTING / FRESH / STALE

Assurance
  UNKNOWN / HEURISTIC / RULE_DERIVED / STANDARD_MAPPED / NATIVE_ASSERTED
```

示例：

```yaml
classification:
  depth: CANONICAL
  freshness: FRESH
  assurance: RULE_DERIVED

geometry:
  fidelity: BOUNDS
  freshness: FRESH

metro:
  depth: DOMAIN
  coverage: UNRESOLVED
```

**Freshness 回答“已知事实是否仍与当前 Host revision 对齐”；Coverage/Maturity 回答“系统到底已经理解到了什么”；Assurance 回答“这些理解是如何得到、可信到什么程度”。**

## 4.6 On-demand Semantic Reconstruction

Progressive Model 的默认策略：

```text
Task requirement
   ↓
required semantic aspects / depth / geometry fidelity
   ↓
Freshness + Coverage check
   ↓
selective reconstruction
   ↓
Semantic Providers
   ↓
new/updated SemanticProjection
   ↓
Snapshot
```

系统 MUST 优先重用仍满足 contract 的已有 projection；不相关 aspect 不得因任务无关而被强制重建。

# 5. D1 — Host Contract

## 5.1 职责

Host Contract 是 DSP 与 Host Sidecar/Plugin 之间的数据边界，负责：

- command；
- result；
- delta；
- error；
- status；
- revision；
- idempotency；
- HostEntityRef。

Host Contract SHALL 保持低语义、Host-neutral，不承担 IFC/Metro/企业语义解释。

## 5.2 HostDelta

HostDelta 保持轻量证据模型：

```text
revision_before
revision_after
added[]
modified[]
erased[]
```

其中实体使用 HostEntityRef，包含文档和 native identity。

HostDelta 不应直接要求 Host 生成 `IfcWall`、`IfcDoor` 等分类。

## 5.3 Transport

Host Contract 与传输协议解耦。

AutoCAD reference implementation 当前可支持：

- Named Pipe；
- gRPC loopback migration transport。

Transport 切换不得改变 Host Contract 的语义。

---

# 6. D2 — Host Adapter / Host MCP

## 6.1 职责

每个 Host Provider 负责：

- 触碰 Host Native API；
- Host 状态读取；
- Host command 执行；
- revision / idempotency；
- read-back verification；
- change capture；
- Native Fact extraction；
- 暴露 Host MCP execution tools。

## 6.2 Host MCP

Host MCP tool 的 description 与 inputSchema 属于 **Provider Execution Interface**。

例如 AutoCAD：

```text
cad.move
handles
dx
dy
dz
revision
idempotency_key
```

这些字段不得直接成为 LLM 公共 action schema。

## 6.3 Host Native Fact Extractor

Host Adapter MAY 提供低语义事实：

```text
native_id
native_kind
layer/category
type/family
raw parameters
placement
bounds
geometry reference
host revision
```

低语义 Host（例如依赖图层规范的 CAD）允许由企业插件/Mapping Provider 进一步解释。

高语义 Host（例如 BIM Host）应尽量采用薄转换，保留原生语义证据但不把 Host ontology 带入 Core。

---

# 7. D3 — Design Capability

## 7.1 职责

D3 负责发现和标准化 Host/Execution Provider 的“能做什么”，而不是决定当前用户最终要执行什么。

Design Capability Profile 至少包含：

```text
provider_server
provider_tool
canonical_operation
category
provider_native_constraints
execution_freshness
effects
risk
preview_supported
rollback_supported
idempotent
verification_contract
provider input/output schema
provider version / trust metadata
```

## 7.2 Capability 四类语义

D3 MUST 区分：

| Category | 作用 | 修改模型 | ChangeSet |
|---|---|---:|---:|
| `MODEL_OPERATION` | 修改设计事实 | 是 | 必须 |
| `INTERACTION` | Host-native 用户输入 | 否 | 否 |
| `VIEW` | 改变视图/导航 | 否 | 否 |
| `CONTEXT` | 读取 Host 当前上下文 | 否 | 否 |

VIEW / CONTEXT / INTERACTION 不得因为“也是 MCP Tool”而进入模型事务路径。

## 7.3 Semantic constraint 与 Native constraint 分离

禁止继续使用一个模糊的 `entity_constraints` 同时表达：

```text
ifc:IfcWall
```

和：

```text
LWPOLYLINE
Revit Wall
```

必须拆成：

```text
canonical_entity_constraints
provider_native_constraints
```

- `canonical_entity_constraints`：由 Canonical Action / D4 eligibility 使用；
- `provider_native_constraints`：由 ProviderBinding / execution validation 使用。

Provider Profile MAY 声明 native constraint；平台 Canonical Action Contract 声明 canonical semantic constraint。

## 7.4 Freshness ownership

Provider Profile 的 freshness 默认解释为 **execution / Phase B requirements**。

Context Freshness（Phase A）由平台根据：

```text
operation taxonomy
canonical applicability
task
current selection/context
```

派生最小要求。

第三方 Provider MUST NOT 通过 Profile 强迫平台为了“发现能力”读取无关高成本语义或 EXACT geometry。

## 7.5 Provider 只实现 capability，不拥有 canonical action

多个 Provider MAY 实现同一个：

```text
wall.thickness.set.v1
```

但 Provider 的：

```text
revit.set_parameter
cad.offset_polyline
```

仅属于 execution interface。

LLM MUST NOT 直接选择 provider/server/tool。

# 8. Canonical Action Catalog

## 8.1 定位

Canonical Action Catalog 是 DSP 平台公共动作契约，不属于某个 Host Provider，也不应只是 D4 内部实现状态。

D4、D6、D7 均可消费该 Catalog。

## 8.2 CanonicalOperationDefinition

建议契约：

```text
canonical_operation
title
description
category
input_schema
slot_binding_policy
semantic_entity_constraints
freshness_requirements
assurance_requirements
effects
verification_contract
version
```

## 8.3 Action description

Action `description` 只解释：

> 这个动作对用户意味着什么。

例如：

```text
wall.thickness.set.v1
Set the final canonical thickness of a wall.
```

Host MCP 的：

```text
Move entities in the active AutoCAD document.
```

不得替代 Canonical Action description。

---

# 9. D4 — Operation Resolver

## 9.1 职责

D4 根据：

- D3 provider capability；
- D5 context snapshot；
- canonical semantic entity type；
- policy；
- task relevance；
- freshness / assurance requirement；

筛选并排序当前可用 Canonical Actions。

## 9.2 D4 / D6 / Phase-B Freshness 顺序

D4 的 operation eligibility 与 Phase A Context Freshness 位于 LLM planning 之前；**Phase B Operation Freshness 必须在 D6 已完成 target/material argument 绑定之后**。

```text
Orchestrator
  ↓
D5 ContextSnapshot                 # Phase A
  ↓
D4 pre-resolution / schema compile
  ↓
LLM selects canonical operation + fills INTENT slots
  ↓
D6 Parameter Binder
  ├─ CONTEXT
  ├─ CANONICAL_DEFAULT
  ├─ DERIVED
  └─ InteractionSession if required
  ↓
BoundOperationProposal
  ↓
derive OperationFreshnessContract
  ↓
D5 Freshness + Coverage + Assurance barrier   # Phase B
  ↓
PlanningSnapshot / SnapshotSet
  ↓
Impact / ChangeSet
```

D4 MAY 在 Phase B 后再次执行确定性 schema/eligibility validation，但不得在 target/material arguments 尚未确定时声称完整 Operation Freshness 已满足。

若 D6 改变 canonical operation、targets 或任何会改变 freshness/coverage/assurance requirements 的 material argument，MUST 重新派生 Phase B contract。

## 9.3 LLM Action Space

LLM 只应看到：

```text
canonical_operation
title / description
intent-visible input schema
canonical semantic constraints
必要的 context summary
```

不得看到：

```text
AutoCAD handle
Revit ElementId
internal units
revision guard token
idempotency key
provider tool routing id
```

## 9.4 ResolvedOperation Contract

```text
ResolvedOperation {
  operation_id
  canonical_operation
  title
  description
  llm_input_schema
  canonical_entity_constraints
  context_freshness_requirements
  operation_freshness_requirements
  coverage_requirements
  assurance_requirements
  effects
  policy_decision
  risk
  task_score
  preview_supported
  rollback_supported
  verification_contract
  candidate_provider_ids[]   # internal only
}
```

`candidate_provider_ids[]` 只证明存在候选 implementation，不等于 ProviderBinding，且 MUST NOT 成为 LLM 必填输出。

## 9.5 Operation Resolver / Provider Resolver Pipeline

Operation Resolver：

```text
provider capabilities
→ aggregate by canonical_operation
→ Host availability
→ canonical semantic entity applicability
→ Policy
→ Task rank / Top-K
→ 3~10 ResolvedOperations
```

Provider Resolver 位于 Execution Planning 后，对 immutable `ExecutionUnit` 做 late binding，至少依据：

```text
HostRuntimeRef
provider_native_constraints
Policy / Trust
Provider version / compatibility
Health / availability
License / certification
```

Provider Resolver 只能替换 implementation，MUST NOT 修改 `canonical_operation / targets / arguments / expected_effects / approved scope`。

---

# 10. Semantic Service / Semantic MCP Server

## 10.1 定位

Semantic Service 是 DSP 的统一语义查询、映射、校验和版本路由层。

其对平台的远程协议采用 MCP。

```text
DSP Platform
   ↓ MCP Client
Semantic MCP Server
   ↓ Domain Contract
SemanticProvider Registry
```

D5 / Orchestrator 不 SHALL 直接依赖具体 `Ifc43Provider`、`MetroProvider` 或企业 Provider。

## 10.2 MCP v1 Tool Surface

首版建议暴露：

```text
semantic.resolve_term
semantic.describe_term
semantic.get_term_schema
semantic.validate_claim
semantic.find_mappings
semantic.get_provider_manifest
semantic.get_environment
```

后续 MAY 增加：

```text
semantic.project_facts
semantic.validate_projection
semantic.query_rules
```

但不应在 v1 一次性把复杂批量投影全部远程化。

## 10.3 SemanticService Contract

平台内部逻辑接口建议至少包含：

```python
resolve_term(term_id, environment_id)
describe_term(term_id, environment_id, locale=None)
get_term_schema(term_id, environment_id)
validate_claim(claim, environment_id)
find_mappings(source_claim, environment_id, target_namespace=None)
get_provider_manifest(provider_id, version)
get_environment(environment_id)
```

所有依赖语义版本状态的查询 MUST 使用显式锁定的 Semantic Environment，MUST NOT 使用隐式 latest/default Provider 状态。
## 10.4 SemanticProvider capability interfaces

Provider SHOULD 按能力实现，而不是强迫所有 Provider 实现同一大接口：

```text
SemanticVocabularyProvider
SemanticMappingProvider
SemanticValidationProvider
SemanticProjectionProvider
```

## 10.5 Provider Adapter

Provider 的运行方式与领域接口分离：

```text
InProcessSemanticProvider
McpSemanticProviderAdapter
FileSemanticProvider
DatabaseSemanticProvider
```

D5 无需知道 Provider 实现方式。

---

# 11. SemanticProvider Manifest

每个 Provider 必须声明：

```text
provider_id
provider_type
version
content_hash
namespaces
capabilities
authority
compatibility
```

示例：

```yaml
provider_id: buildingSMART.ifc43
provider_type: STANDARD
version: "4.3.2.0"
namespaces: [ifc]
capabilities:
  vocabulary: true
  validation: true
  mapping: false
  projection: true
authority:
  ifc: authoritative
```

Metro：

```yaml
provider_id: dsp.metro.semantic
provider_type: DOMAIN
version: "3.2"
requires:
  - buildingSMART.ifc43@4.3.2.0
capabilities:
  vocabulary: true
  mapping: true
  validation: true
  projection: true
```

---

# 12. IFC4.3 Standard Semantic Provider

## 12.1 权威范围

IFC Provider 对以下内容具有权威性：

- IFC entity；
- inheritance；
- attribute；
- enum；
- standard relationship；
- standard Pset/Qto definition；
- IFC data type；
- Schema legality。

## 12.2 Term identity

标准 term 使用稳定 canonical identity，例如：

```text
ifc:IfcWall
ifc:IfcDoor
ifc:IfcAlignment
ifc:IfcRelAggregates
```

`description` 是 presentation metadata；真正 identity 是标准 namespace + term + pinned standard version。

## 12.3 不得承担 DSP Action

IFC Provider 不提供：

```text
wall.thickness.set.v1
wall.move.v1
```

IFC 定义 State Semantics；DSP Canonical Action Catalog 定义 Action Semantics。

---

# 13. Metro Semantic Provider

## 13.1 定位

Metro Semantic 是建立在 IFC4.3 之上的地铁领域语义 Provider。

其基线来源为：

```text
IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版
Schema: IFC4X3_ADD2 / IFC 4.3.2.0
```

Metro Semantic 不是 IFC 官方标准本体，而是：

```text
IFC standard semantics
+
metro domain mapping
+
PsetProj/QtoProj dictionary
+
IDS information requirements
+
field status / cardinality rules
+
metro geometry / engineering validation rules
```

## 13.2 权威层级

Metro Provider 必须遵循以下优先级：

```text
1. IFC4X3_ADD2 Schema legality
2. IFC official entity / Pset / Qto semantics
3. Metro domain mappings and PsetProj/QtoProj
4. Metro IDS requirements
5. Metro project-specific validation rules
```

若 Metro 规则与正式 IFC Schema 冲突，以 IFC Schema 为准。

## 13.3 Metro field status

Metro Provider 应能够表达：

```text
IFC-M
IFC-O
P-M
P-C
P-R
PROHIBITED
```

并可按阶段转换为 IDS 可执行 requirement：

```text
required
optional
prohibited
```

## 13.4 Metro property resolution order

Metro Semantic SHOULD 保留以下读取/解释优先级：

```text
Schema native fields
→ Type object fields
→ official Pset/Qto
→ material and classification relations
→ PsetProj project extension fields
→ IDS / special geometry validation
```

## 13.5 Metro mapping

Metro Provider 负责受控的“地铁业务概念 → 合法 IFC4.3 表达”。

例如，不得产生不存在的 IFC 实体：

```text
IfcTunnel
IfcTunnelPart
IfcTrack
IfcSprinkler
IfcFanCoilUnit
IfcPrecastConcreteElement
```

Metro Provider 可将隧道、限界、PSD、专业设备等映射到合法 IFC entity + project properties / classification。

## 13.6 Metro extensions

Metro-specific term MAY 使用独立 namespace，例如：

```text
metro:WallDesign.DesignThickness
metro:TunnelSegment.ConstructionMethod
metro:ClearanceEnvelope.EnvelopeType
metro:TrackGeometry.DesignSpeed
```

但是对于已经存在的 IFC term，Metro 不得重新定义 canonical identity：

```text
ifc:IfcWall
```

必须仍然由 IFC Provider 权威解释。

## 13.7 Metro description

Metro term 的 description 由 Metro Provider 维护。

IFC term 在 Metro context 下可附加 metro usage note，但不得覆盖 IFC canonical description/meaning。

示例：

```text
ifc:IfcWall
  canonical meaning: IFC Provider
  metro usage note: Metro Provider
```

---

# 14. DSP Core Semantic Provider

DSP Core Provider 仅维护跨行业协同所需、IFC 不直接定义的 DSP 语义，例如：

```text
dsp:SemanticIdentity
dsp:HostBinding
dsp:ExternalIdentity
dsp:WallThickness
dsp:Freshness
dsp:Assurance
dsp:Snapshot
dsp:ChangeSet
```

DSP Core term 必须具有：

```text
stable id
version
kind
domain
range
unit / allowed values
label
description
```

description 的修改不应自动改变 semantic content hash；domain/range/unit/constraint 的改变属于 semantic definition change。

---

# 15. Enterprise Semantic Provider

企业 Provider 可提供：

- 图层/块/族/命名规则映射；
- 企业分类体系；
- 企业 Pset / 属性字典；
- 专业规则；
- 资产规则；
- 自有设计标准；
- Host-native → canonical mappings。

例如：

```text
AutoCAD layer A-WALL-EXT
  ↓
acme:ExteriorWall
  ↓
ifc:IfcWall
```

企业 Provider 不得修改：

```text
ifc:IfcWall 的 canonical meaning
```

企业可定义自己 namespace 下的 term，并通过显式 mapping 与 IFC/DSP/Metro term 建立关系。

---

# 16. Semantic Environment

## 16.1 目的

Semantic Environment 描述某次规划/审批所使用的完整语义解释环境。

```yaml
semantic_environment:
  providers:
    - provider_id: buildingSMART.ifc43
      version: "4.3.2.0"
      content_hash: "..."

    - provider_id: dsp.core
      version: "1.0"
      content_hash: "..."

    - provider_id: dsp.metro.semantic
      version: "3.2"
      content_hash: "..."

    - provider_id: acme.design.standard
      version: "2026.08"
      content_hash: "..."
```

## 16.2 Version pinning

PlanningSnapshot / ChangeSet 必须固定 `SemanticEnvironmentRef`。

禁止在审批之后因为 Provider 自动升级而静默改变已审批语义。

## 16.3 Provider conflict

Provider 不得静默覆盖其他 Provider 的权威 namespace。

冲突必须：

- fail closed；或
- 根据显式配置的 mapping/overlay policy 处理；
- 并记录 provenance。

---

# 17. Semantic Ingest Contract

## 17.1 Pipeline

```text
HostDelta / Host read
  ↓
Native Fact Extractor
  ↓
Semantic Adapter
  ↓
NormalizedDesignFactBatch
  ↓
Semantic Service / Providers
  ↓
Canonical Claims
  ↓
D5 Collaboration Kernel
```

## 17.2 NormalizedDesignFact

建议最小结构：

```text
fact_id
producer
host_ref
source_revision
subject_native_ref
fact_kind
predicate
value
value_type
unit
geometry_ref
source_scheme
source_code
provenance
```

NormalizedDesignFact 解决“数据怎么移动”，不是“最终是什么意思”。

## 17.3 SemanticClaim

Provider 输出统一 claim：

```text
subject
predicate / classification
canonical_term_id
value
unit
assurance
provenance
evidence
provider_id
provider_version
```

---

# 18. Semantic Assurance

## 18.1 Assurance 与 Freshness 分离

Freshness 回答：

> 这个事实在当前 Host revision 下是否仍然新鲜？

Assurance 回答：

> 这个事实是如何得到的、可信程度如何？

## 18.2 Assurance level

建议至少：

```text
NATIVE_ASSERTED
STANDARD_MAPPED
RULE_DERIVED
HEURISTIC
UNKNOWN
```

可附加：

```text
producer
provider_id
mapping_profile
rule_id
evidence
confidence
```

## 18.3 Operation gate

Canonical Operation 可以声明最低 assurance：

```text
target.classification >= RULE_DERIVED
```

AI/LLM 不得自行降低 assurance requirement。

---

# 19. D5 — Collaboration Kernel / Progressive Semantic Runtime

## 19.1 职责

D5 负责回答：

> 当前设计在 canonical collaboration world 中是什么，以及当前任务要求的那部分语义是否足够新鲜、足够完整、足够可信？

D5 不负责：

- Host-native mapping 规则；
- IFC/Metro/企业 Vocabulary 的权威定义；
- LLM action description；
- provider execution schema；
- 最终 Host API 调用。

D5 通过 Semantic Service contract 使用语义 Provider，而不依赖具体 IFC/Metro/Enterprise 实现。

## 19.2 SemanticIdentity

```text
SemanticIdentity
  semantic_id
```

一个 SemanticIdentity 可拥有多个 HostBinding。

## 19.3 HostBinding / HostRuntimeRef

`HostBinding` 表达持久的 `SemanticIdentity ↔ Host-native entity` 绑定，不把临时软件会话或 provider implementation 当成长期身份。

```text
HostBinding {
  semantic_id
  host_type
  document_id
  native_id
  native_kind
}
```

```text
HostRuntimeRef {
  host_type
  host_instance_id
  document_id
}
```

```text
SemanticIdentity
  ↓ HostBinding (persistent)
Host document/native entity
  ↓ runtime resolution
HostRuntimeRef
  ↓ ExecutionSlice
  ↓ ProviderBinding
```

- `host_instance_id` MAY 随应用会话变化，因此不属于持久 HostBinding 的必要字段；
- `provider_id/provider_tool` 属于 ProviderBinding，不属于 HostBinding；
- 执行前若不能解析到当前有效 HostRuntimeRef，MUST fail closed。

## 19.4 ExternalIdentity

D5 不得为 IFC GlobalId 建特殊字段。

```text
ExternalIdentity
  semantic_id
  scheme
  value
```

例如：

```text
scheme = ifc.global_id
value  = 2Ksd...
```

## 19.5 Canonical Semantic Projection

D5 Projection 至少可表达：

```text
semantic_id
classification
canonical_properties
relationships
placement / coordinates
spatial membership
connectivity
constraints
source extensions
assurance / provenance
coverage / maturity metadata
```

实例只存 term id，不复制 Vocabulary description。

```yaml
semantic_id: S-WALL-001
classification:
  term_id: ifc:IfcWall
properties:
  dsp:WallThickness:
    value: 200
    unit: mm
extensions:
  metro:WallDesign.DesignThickness:
    value: 200
    unit: mm
```

## 19.6 SemanticAspect

D5 至少支持：

```text
IDENTITY
CLASSIFICATION
PROPERTIES
PLACEMENT
GEOMETRY
SPATIAL
CONNECTIVITY
RELATIONSHIPS
CONSTRAINTS
```

`CLASSIFICATION` 为一等 aspect。

Domain extensions（如 Metro）可在 coverage 中进一步细分，但不得通过新增 Host-specific aspect 污染 Core。

## 19.7 Progressive Coverage / Maturity

D5 必须区分“事实不存在/尚未解析”和“事实已经解析但 stale”。

建议：

```text
UNRESOLVED
PARTIAL
RESOLVED
```

Coverage 可细到：

```text
entity
aspect
property family
relationship family
domain extension
geometry fidelity
```

例如：

```yaml
coverage:
  identity: RESOLVED
  classification: RESOLVED
  properties:
    dsp:WallThickness: RESOLVED
    fire_rating: UNRESOLVED
  geometry:
    fidelity: BOUNDS
  relationships: PARTIAL
  metro: UNRESOLVED
```

## 19.8 Freshness

D5 保留：

```text
FRESH
STALE
DIRTY
UNKNOWN
RECONSTRUCTING
```

Freshness 与 coverage 正交：

- `UNRESOLVED` 不是 `STALE`；
- `FRESH` 不意味着“所有语义都已解析”；
- `RESOLVED` 不意味着“当前 revision 仍然 fresh”。

## 19.9 Assurance / Provenance

每个关键 claim MAY 带：

```text
assurance_level
producer
provider_id/version
mapping_profile
rule_id
evidence
confidence
source_revision
```

Freshness barrier 与 Assurance barrier 可以分别失败。

## 19.10 Change Journal / DirtyMap

Host delta 经 semantic ingest 后形成：

```text
HostDeltaRecord
  document_id
  host_revision
  semantic_id
  change_type
  affected_aspects
```

Journal append-only；DirtyMap 按：

```text
document + semantic_id + aspect
```

跟踪状态。

## 19.11 Reconstruction Engine

Reconstruction Engine 负责把任务 requirement 转换为 selective reconstruction 工作：

```text
required coverage
+ required freshness
+ required assurance
+ geometry fidelity
      ↓
missing / stale set
      ↓
Native Fact read / Semantic Provider calls
      ↓
Projection update
      ↓
Snapshot
```

Reconstruction MUST 是 task-scoped / coverage-scoped，不得把“需要一项属性”自动扩大为全项目 IFC 重建。

# 20. Semantic Freshness Contract / Snapshot / SnapshotSet

## 20.1 SemanticFreshnessContract

Freshness 必须由显式 contract 驱动，而不是简单 `ensure_fresh=true`。

```text
SemanticFreshnessContract {
  contract_id
  project_id
  contract_type: CONTEXT|OPERATION
  root_entities[]
  requirements[] {
    aspect
    required_state
    minimum_coverage?
    semantic_depth?
    geometry_fidelity?
    minimum_assurance?
  }
  neighborhood {
    depth
    relations[]
  }
}
```

## 20.2 Two-phase Freshness

### Phase A — Context Freshness

Operation Resolution / 初步 LLM planning 前，只重建发现 action space 所需最小事实：

```text
selection
identity
classification/native kind
document revision
lightweight properties
geometry <= BOUNDS by default
```

产出 `ContextSnapshot`。

### Phase B — Operation Freshness

Canonical operation + material arguments/targets 已知后，根据 operation definition 精确生成要求：

```text
OperationProposal
  ↓
OperationFreshnessContract
  ↓
selective reconstruction
  ↓
PlanningSnapshot
```

若 operation、targets 或会改变 required aspects 的关键参数变化，MUST 重新生成 Phase B contract。

## 20.3 ReconstructionResult

Reconstruction 不得只返回 freshness guarantee，还必须绑定实际 semantic projection/environment：

```text
ReconstructionResult
  document_ref
  host_revision
  coverage
  guarantees
  semantic_projection_ref
  semantic_environment_ref
```

## 20.4 SemanticProjectionRef

```text
projection_id
projection_hash
normalized_fact_batch_hash
semantic_model_version
provider_set_hash
mapping_profile_set_hash
```

## 20.5 SemanticSnapshot

```text
SemanticSnapshot
  snapshot_id
  kind: CONTEXT|PLANNING
  project_id
  freshness_contract_id/hash
  document_ref
  base_host_revision
  coverage
  aspect_guarantees[]
  semantic_projection_ref
  semantic_environment_ref
  hash
```

`aspect_guarantees` 只能对 contract coverage 声明保证；局部 reconstruction 不得被解释为整个 document fresh。

## 20.6 SnapshotSet

所有 ChangeSet Core 统一引用 Planning `SnapshotSet`，即使 MVP 只有一个 Host。

**一个 SnapshotSet MUST 绑定唯一的 `semantic_environment_ref`；所有 PlanningSnapshot member MUST 使用同一 pinned SemanticEnvironment。**

```text
SnapshotSet {
  snapshot_set_id
  kind: PLANNING
  semantic_environment_ref
  members[] {
    document_ref
    snapshot_id
    snapshot_hash
    base_host_revision
    semantic_projection_ref
  }
  hash
}
```

若某 document 必须使用不同 SemanticEnvironment，不得静默加入同一 SnapshotSet；应先统一环境，或未来通过独立 ADR 引入 `SemanticEnvironmentSet`。

```text
PS-CAD-01 ─┐
PS-RVT-01 ─┼→ SnapshotSet PSS-01 @ ENV-01 → ChangeSet
PS-TKL-01 ─┘
```

任一 member revision / snapshot hash / projection hash 或 pinned SemanticEnvironment 变化，都必须改变 SnapshotSet hash 并触发 ChangeSet 重新验证。

## 20.7 Snapshot invariant

PlanningSnapshot 必须能够证明：

> 审批时看的是哪一个 Host revision、哪一份 semantic projection、哪一个 coverage、哪套 provider/mapping environment，以及哪些 aspect/fidelity/assurance 被保证。

# 21. D5 Read API

建议稳定接口：

```text
SemanticReadService
  get_context_snapshot(task_scope)
  get_entity(semantic_id, snapshot_id)
  query_entities(filter, snapshot_id)
  get_projection(snapshot_id)
  check_freshness(snapshot_id, requirements)
  check_assurance(snapshot_id, requirements)
  resolve_host_bindings(semantic_id)
```

事件：

```text
SemanticSnapshotPublished
SemanticEntityDirty
SemanticIdentityChanged
SemanticProjectionChanged
```

D4/D6/D7 不得直接共享 D5 内部数据库。

---

# 22. Context Composer 与 LLM

## 22.1 Context 来源

LLM task context 由以下内容按需组装：

```text
D5 instance facts
+
Semantic Service descriptions / schemas
+
Canonical Action Catalog descriptions
+
policy / task constraints
```

LLM 不读取完整模型数据库。

## 22.2 Semantic description

例如 LLM 可看到：

```text
S-WALL-001
Classification:
  IfcWall — <IFC provider description>

Domain constraints:
  Metro wall design requirements — <Metro provider summary>

Current thickness:
  200 mm
```

但系统 eligibility 仍由结构化 term/schema/requirements 判断。

---

# 23. D6 — Parameter Binder / Host Interaction

## 23.1 Slot Binding Model

每个 canonical slot 必须声明 binding class：

```text
INTENT
CONTEXT
CANONICAL_DEFAULT
DERIVED
PROVIDER
```

原则：

> 能确定性绑定的槽，绝不交给 LLM。

## 23.2 LLM-visible slots

LLM 主要填写 `INTENT`。

```text
wall.thickness.set.v1

target:
  binding = CONTEXT

thickness:
  binding = INTENT
```

用户：

```text
把这堵墙加厚到 300mm
```

LLM 只需给出 operation + `thickness=300mm`；target 可从 ContextSnapshot 确定性绑定。

## 23.3 Host-native Interaction

当某个参数不能从 intent/context/default/derived 确定性获得，而必须由设计师在 Host canvas 中选择时，D6 发起 Host-native interaction。

首批 interaction：

```text
SELECT_ENTITIES
PICK_POINT
PICK_DIRECTION
INPUT_NUMBER
CONFIRM
CANCEL
```

LLM 不应通过自然语言要求用户手工输入 native id 或坐标来替代可用的 Host interaction。

## 23.4 InteractionSession

长时间用户交互必须显式 session 化：

```text
InteractionSession {
  interaction_id
  task_id
  host_instance_id
  document_id
  interaction_type
  input_constraints
  result_schema
  state: PENDING|COMPLETED|CANCELLED|EXPIRED
  result?
  created_at
  expires_at
}
```

`interaction.start` 属于 side-effecting operation，必须使用稳定 idempotency_key；网络重试不得弹出第二个 Host prompt。

## 23.5 BoundOperationProposal

```text
BoundOperationProposal
  operation
  arguments
  binding_evidence
  context_snapshot_ref
  planning_requirements
  semantic_environment_ref
```

Binding evidence 至少区分：

```text
target ← ContextSnapshot.selection
thickness ← UserIntent
point ← InteractionSession
unit ← CanonicalDefault
```

## 23.6 Provider-bound slot

`PROVIDER` slot 只在 ProviderBinding 以后出现，例如：

```text
Revit ElementId
AutoCAD Handle
internal unit
revision token
idempotency key
```

这些字段不得进入 LLM-visible canonical schema。

## 23.7 Host-native UX / View Navigation

Host 内交互 SHOULD 优先保持 ambient / spatial：

```text
Agent Orb → Peek → Task Card → Host Canvas
```

该 UI 形态不是 Semantic/D5 contract，但主架构必须保持：

- entity selection / point / direction picking 在 Host Canvas 完成；
- VIEW 不产生 ChangeSet；
- CONTEXT 为 read-only；
- INTERACTION 通过 InteractionSession；
- MODEL_OPERATION 才进入 ChangeSet/Approval。

典型 VIEW：

```text
FIT_ENTITIES
FOCUS_ENTITY
RESTORE_VIEW
NEXT_ISSUE
```

# 24. Semantic Dependency / Constraint / Impact / Propagation

## 24.1 五类图不得混淆

| Graph | 生命周期 | 回答的问题 |
|---|---|---|
| Relationship Graph | 长期 | A 与 B 有什么关系？ |
| Dependency Graph | 长期 | A 改了可能影响 B 吗？ |
| Constraint / Invariant Graph | 长期 | 修改后必须/应该满足什么？ |
| Change Impact Graph | task runtime | 这次修改实际预计影响什么？ |
| Change DAG | task runtime | 最终派生修改的因果/执行结构是什么？ |

IFC/Metro relationship 不得自动等价为 dependency。

Semantic Provider 可以提供 relationship、constraint、rule evidence；D5/Dependency layer 决定它们是否参与当前 task impact。

## 24.2 Dependency strength

```text
HARD
SOFT
ADVISORY
```

- HARD：保持系统/工程 invariant；
- SOFT：存在设计选择；
- ADVISORY：只影响检查/提示。

## 24.3 Propagation owner

```text
HOST_NATIVE
SEMANTIC_RUNTIME
AGENT
```

- `HOST_NATIVE`：Host associativity 自己产生副作用，平台 predict + verify；
- `SEMANTIC_RUNTIME`：规则可确定性派生；
- `AGENT`：存在设计自由度，需要 replan / HITL。

## 24.4 Propagation actions

至少：

```text
AUTO_MUTATE
RECOMPUTE
REVALIDATE
MARK_DIRTY
REPLAN
BLOCK
```

Dependency propagation MUST NOT 被实现成“所有相关对象都自动修改”。

## 24.5 Exception-first review

大量派生影响应按：

```text
rule
strategy
discipline
risk
scope
```

分组。

安全、确定性的 propagation 可汇总展示；跨专业、高风险、有设计自由度或超出 intent boundary 的部分进入 `Exception Set`。

## 24.6 Metro Semantic 与 dependency

Metro Provider 可提供：

```text
domain relationships
IDS requirements
engineering constraints
validation rules
mapping provenance
```

但 Metro Provider 不直接拥有 ChangeSet propagation 决策。

其输出作为 evidence 进入 Dependency / Constraint / Impact Analyzer。

# 25. D7 — ChangeSet / Approval / Execution / Verification

## 25.1 生成链路

```text
BoundOperationProposal
   ↓
Operation Freshness → PlanningSnapshot → SnapshotSet
   ↓
Impact Analyzer / Propagation
   ↓
ApprovalScopeBoundary
   ↓
ChangeSetBuilder
   ↓
Immutable ChangeSet
   ↓
Preview
   ↓
ApprovalToken → ApprovalRecord
   ↓
Execution Planner
   ↓
ExecutionSlice[]
   ↓
ExecutionUnit[]
   ↓
RevisionBarrier
   ↓
ProviderBinding[]
   ↓
binding_set_hash
   ↓
ExecutionGrant
   ↓
HostCommand
   ↓
ActualDelta
   ↓
Verify / Scope Check / Reconcile
```

## 25.2 ChangeSet

ChangeSet 是被规划和审批的 **canonical logical transaction**，不是 Host command 集合。

```text
ChangeSet {
  changeset_id
  task_id / project_id
  base_snapshot_set_id/hash
  semantic_environment_ref
  root_operations[]
  derived_operations[]
  preconditions[]
  affected_entities[]
  semantic_impacts[]
  validation_tasks[]
  approval_scope_boundary_ref
  risk
  approval
  verification
  rollback
  hash
  status
}
```

ChangeSet 进入 Preview/Approval 后 SHOULD immutable；任何 canonical operation/target/argument/approved effect scope 变化必须新建 ChangeSet。

## 25.3 ExecutionSlice

ExecutionSlice 是：

```text
Host instance
+
document
+
approved scope
```

边界，不是 provider 边界。

```text
ExecutionSlice {
  execution_slice_id
  changeset_id
  host_instance_id
  document_id
  approved_scope_ref
  execution_units[]
  status
}
```

Cross-host ChangeSet：

```text
ChangeSet
├── XS-CAD-01
├── XS-RVT-01
└── XS-TKL-01
```

## 25.4 ExecutionUnit — 必须保持 canonical

ExecutionUnit 是最小 provider-binding 单位，但本身仍是 provider-neutral canonical object：

```text
ExecutionUnit {
  execution_unit_id
  execution_slice_id
  canonical_operation
  targets[]
  arguments
  preconditions[]
  expected_effects[]
}
```

**ExecutionUnit MUST NOT 包含 `provider_tool`、AutoCAD Handle、Revit ElementId、internal unit 等 native execution payload。**

## 25.5 ProviderBinding

只有 execution planning 后才做：

```text
SemanticId
   ↓
HostBinding
   ↓
provider-native identity
   ↓
provider execution schema
```

```text
ProviderBinding {
  binding_id
  execution_unit_id
  canonical_operation
  provider_server
  provider_tool
  provider_version
  host_instance_id
  input_adapter_version
  native_binding_metadata
  verification_contract
  rollback_contract
  binding_expires_at
}
```

ProviderBinding 不由 LLM 完成，且不得改变 ExecutionUnit 的 canonical semantics。

同一 Slice 的全部 ProviderBinding 按规范化顺序生成：

```text
binding_set_hash
```

## 25.6 ApprovalScopeBoundary

用户批准的是：

```text
ChangeSet hash
+
effect scope
```

不是 Host API 的任意隐式副作用。

ApprovalScopeBoundary 至少支持：

```text
existing_entity_rules
creation_rules
deletion_rules
propagation_bundle_ids
execution_slice_scopes
scope_hash
```

CREATE / COPY / OFFSET / SPLIT / ROUTE 等不能仅靠“旧实体白名单”判断范围。

## 25.7 ApprovalToken / ApprovalRecord / ExecutionGrant

```text
ApprovalToken
  ↓ one-time apply admission
ApprovalRecord
  ↓ durable approval evidence
ExecutionGrant
  ↓ per ExecutionSlice authorization
Provider / Sidecar
```

ApprovalRecord 至少绑定：

```text
changeset_hash
approved_scope_hash
semantic_environment_ref/hash
policy_snapshot_hash
approver
approved_at
```

ExecutionGrant 至少绑定：

```text
approval_id
changeset_hash
execution_slice_id
binding_set_hash
host_instance_id
approved_scope_hash
allowed_operations
expires_at
```

ProviderBinding 改变但 canonical ChangeSet/scope 未改变时：

```text
old binding_set_hash → old grant invalid
new binding_set_hash → reissue grant
```

不必重复用户审批。

## 25.8 HostCommand

最终 native execution payload 才进入：

```text
HostCommand {
  command_id
  task_id / project_id
  document_id
  mode
  provider operation
  target_native_refs[]
  payload
  preconditions[]
  idempotency_key
  deadline_at?
}
```

## 25.9 Verification / Reconcile

```text
Host write
  ↓
Host read-back / ActualDelta
  ↓
Host revision update
  ↓
D5 dirty/reconstruct
  ↓
new SemanticSnapshot
  ↓
expected semantic result comparison
  +
ApprovalScopeBoundary comparison
```

`Host success=true` 不等于 semantic verified。

## 25.10 SCOPE_BREACH

若：

```text
ActualDelta ⊄ ApprovalScopeBoundary
```

必须返回：

```text
SCOPE_BREACH
```

并：

```text
stop not-yet-started slices
→ compensate/rollback when safe
→ Exception Set
→ new ChangeSet
→ reapproval
```

不得只记录 warning 后继续。

## 25.11 Cross-host Saga / Compensation

DSP 不实现 XA/2PC。

跨 Host ChangeSet 使用 Saga：

```text
Slice A success
Slice B failure
  ↓
PARTIALLY_COMMITTED
  ↓
Compensation Planner
  ↓
Compensating ChangeSet(s)
```

补偿自身也是 ChangeSet，必须可审计、可验证；不得用隐藏 undo 绕过平台记录。

## 25.12 Optimistic concurrency

设计师持续编辑时不锁住整个 Host。

执行前必须：

```text
RevisionBarrier
```

Host revision / precondition 不匹配返回：

```text
REVISION_CONFLICT
```

然后由 Orchestrator：

```text
reconstruct → revalidate → replan/new ChangeSet
```

# 26. “墙体加厚到 300mm”完整流程

假定设计师当前只要求“把这堵墙加厚到 300mm”。

初始 D5 可能只有：

```text
S-WALL-001
HostBinding = Revit ElementId 38912 / 或 AutoCAD Handle A31
IDENTITY = FRESH
PLACEMENT = FRESH
GEOMETRY = BOUNDS
CLASSIFICATION = unresolved or canonical
PROPERTIES.thickness = unresolved or 200mm
METRO = unresolved
```

流程：

```text
1. User
   “把这堵墙加厚到 300mm”

2. D5 Context Freshness
   只保证 operation discovery 所需：
   identity / selection / classification / lightweight context
   geometry 不升级到 EXACT

3. Progressive reconstruction（如需要）
   AutoCAD:
      layer/fact → Enterprise Provider → ifc:IfcWall
   Revit:
      native semantic evidence → thin mapping → ifc:IfcWall

4. D4
   eligible canonical action:
      wall.thickness.set.v1

5. LLM
   只填写 INTENT：
      thickness = 300mm

6. D6
   target = S-WALL-001       [CONTEXT]
   thickness = 300mm         [INTENT]

7. Operation Freshness Contract
   要求：
      CLASSIFICATION = FRESH
      PROPERTIES.wall_thickness = FRESH
      required coverage = resolved
      assurance >= configured minimum
      geometry fidelity = only if operation/provider verification requires

8. D5 selective reconstruction
   得到 PlanningSnapshot PS-001
   bind SemanticProjectionRef + SemanticEnvironmentRef

9. Impact Analyzer
   检查：
      related openings / connections / annotations / metro constraints
   生成 predicted impact + propagation bundles + Exception Set

10. ChangeSetBuilder
    ChangeSet CS-001:
      before = 200mm
      after  = 300mm
      base SnapshotSet = PSS-001
      ApprovalScopeBoundary = ASB-001

11. Preview / Approval
    user/policy approves:
      CS-001 hash + ASB-001 hash + SemanticEnvironment
    persist ApprovalRecord AR-001

12. Execution Planner
    Revit path:
       ExecutionSlice XS-RVT-01
    or AutoCAD path:
       ExecutionSlice XS-CAD-01

13. Expand canonical ExecutionUnit
    EU-001:
       operation = wall.thickness.set.v1
       target = S-WALL-001
       thickness = 300mm

14. RevisionBarrier
    exact target Host revision still matches planning preconditions

15. ProviderBinding
    Revit:
       S-WALL-001 → ElementId 38912
       300mm → Revit internal unit
       provider tool selected deterministically

    AutoCAD:
       S-WALL-001 → Handle A31
       enterprise/native execution adapter selected

    EU-001 本身不改变。

16. Gateway
    binding_set_hash
      ↓
    ExecutionGrant EG-001

17. Host execution
    HostCommand + idempotency_key

18. Host ActualDelta
    native changes + implicit associativity effects

19. D5
    dirty → selective reconstruction
    publish new SemanticProjection / Snapshot

20. Verify / Scope Check
    intended wall thickness == observed 300mm
    ActualDelta ⊆ ApprovalScopeBoundary

21. Result
    inside scope + verify pass → SUCCEEDED

    outside scope → SCOPE_BREACH
      → stop remaining slices
      → compensate/reapproval
```

关键点：

- Revit 与 AutoCAD 共用同一个 canonical operation / ChangeSet 语义；
- 差异只在 HostBinding / ProviderBinding / HostCommand；
- Progressive Model 只提升当前 operation 需要的语义，不重建无关 Metro/geometry；
- 若 Metro rule 是本次操作的 policy/validation requirement，才将相关 domain coverage 提升到 L3。

# 27. Enterprise MCP Gateway 与 Runtime Surfaces

## 27.1 Gateway 定位

Semantic MCP Server 与 Enterprise MCP Gateway 不是同一个组件。

```text
Agent / Orchestrator
       ↓
Enterprise MCP Gateway
       ├── Semantic MCP
       └── Host / Execution MCP
```

Gateway 负责治理；Semantic MCP 负责语义服务。

## 27.2 Gateway MUST

```text
Authentication / Authorization
Policy enforcement
MCP routing
quota / rate limit
audit / trace
approval admission
ExecutionGrant issuance/enforcement
data egress policy
```

## 27.3 Gateway MUST NOT

```text
BIM/CAD design planning
own LangGraph workflow state
own canonical ChangeSet
modify Host native model
redefine IFC/Metro semantics
perform free-form engineering reasoning
```

## 27.4 三类 Runtime Surface

### LLM-facing

每一步只暴露 3~10 个：

```text
ResolvedOperation
```

以及 task-scoped semantic context。

不得暴露 provider/native details。

### Orchestrator-facing

稳定、少量服务，例如：

```text
context.current_document
context.current_selection
semantic.read
semantic.ensure_context_fresh
semantic.ensure_operation_fresh
operation.resolve
interaction.start/result
impact.analyze
changeset.build/preview/apply/status
execution.plan
provider.resolve
execution.grant
changeset.verify/rollback
```

实现 MAY 使用 MCP/HTTP/internal RPC，但逻辑上不等于 LLM 工具列表。

### Provider-facing MCP

可大量扩张：

```text
cad.move
cad.offset
revit.set_parameter
interaction.pick_point
view.fit
context.current_selection
semantic.resolve_term
semantic.validate_claim
```

新增 Provider Tool SHOULD NOT 要求修改 stable Orchestrator surface。

# 28. LangGraph Orchestration / Module Interaction

## 28.1 Workflow owner

LangGraph 是业务 task/workflow/checkpoint/HITL 的最终编排者。

```text
START
 ↓ ResolveIntent
 ↓ ResolveHostContext
 ↓ EnsureContextFreshness
 ↓ ResolveOperations
 ↓ LLM OperationProposal
 ↓ D6 ParameterBinding / HostInteraction
 ↓ EnsureOperationFreshness
 ↓ AnalyzeImpact / Propagation
 ↓ BuildChangeSet
 ↓ Preview
 ↓ Policy / Approval
 ↓ ExecutionPlanning
 ↓ RevisionBarrier
 ↓ ProviderBinding
 ↓ ExecutionGrant
 ↓ Apply
 ↓ Verify / Reconcile / ScopeCheck
END
```

若当前实现未来替换 LangGraph，替代框架必须保持同一 ownership/invariant，而不能让 Host UI、MCP Server、LLM 各自维护独立最终 agent loop。

## 28.2 Deterministic nodes

以下 SHOULD 是确定性模块/服务：

```text
Operation Resolver
Freshness Resolver
Parameter Binder
Impact Analyzer
ChangeSetBuilder
Execution Planner
Provider Resolver
Policy Engine
Verify/Reconcile
Scope Comparator
```

LangGraph 负责状态迁移、checkpoint、异常恢复，不把这些规则委托给自由形式 LLM。

## 28.3 Async operation

Host interaction、重型 reconstruction、长时间 execution 必须显式返回 typed handle：

```text
AsyncOperationRef
```

LangGraph checkpoint/resume 只能依赖显式 handle，不依赖 server hidden session state。

## 28.4 Human change capture

```text
Designer edits Host
  ↓
native events
  ↓
Host Plugin Change Sensor
  ↓ lightweight HostDelta
Sidecar queue
  ↓
D5 Journal / DirtyMap
```

Host event callback 中 MUST NOT：

```text
call LLM
wait Gateway
run geometry reconstruction
perform cross-service transaction
```

## 28.5 Module ownership

一个长期状态只能有一个 authoritative owner：

- Host native design state → Host；
- SemanticProjection/Snapshot/DirtyMap → D5；
- Semantic definitions/provider versions → Semantic Service/Provider；
- ChangeSet → ChangeSet Store；
- ApprovalRecord/ExecutionGrant → Gateway；
- InteractionSession → Interaction Coordinator；
- workflow checkpoint → LangGraph。

# 29. 通用 Envelope / Idempotency / Structured Error

## 29.1 Request / Response Envelope

所有跨服务/进程请求 SHOULD 使用统一 envelope：

```text
RequestEnvelope {
  request_id
  task_id
  project_id
  actor_context
  correlation_ids
  deadline_at
  idempotency_key?
  payload
}

AsyncOperationRef {
  type: INTERACTION_SESSION|RECONSTRUCTION_JOB|EXECUTION_JOB|OTHER
  id
}

ResponseEnvelope {
  request_id
  status: OK|PENDING|ERROR
  correlation_ids
  snapshot_ref?
  operation_ref?: AsyncOperationRef
  result?
  error?: ErrorShape
}
```

## 29.2 request_id 与 idempotency_key

```text
request_id
= 一次 transport attempt

idempotency_key
= 一个逻辑副作用
```

同一副作用网络重试：

```text
new request_id
same idempotency_key
```

所有 MODEL_OPERATION 与 `interaction.start` 必须具有稳定 idempotency_key。

## 29.3 Deadline

`deadline_at` 必须是 absolute timestamp。

```text
child.deadline_at <= parent.deadline_at
```

转发方 MAY 缩短，不得自行延长。

## 29.4 PENDING

任何：

```text
status = PENDING
```

必须返回 typed `AsyncOperationRef`。

调用方不得依赖自然语言 message 或隐式 server session 来猜后续 job/session。

## 29.5 ErrorShape

```text
ErrorShape {
  error_code
  category
  message
  correlation_ids
  retryable
  details[]
}
```

category：

```text
PROTOCOL
POLICY
SEMANTIC
EXECUTION
CONSISTENCY
```

## 29.6 Core error codes

至少保留/新增：

```text
UNAUTHORIZED
QUOTA_EXCEEDED
SCHEMA_INVALID
APPROVAL_REQUIRED
EXECUTION_GRANT_INVALID
CAPABILITY_FORBIDDEN
PROVIDER_UNAVAILABLE

FRESHNESS_INSUFFICIENT
ASSURANCE_INSUFFICIENT
SEMANTIC_COVERAGE_INSUFFICIENT
SNAPSHOT_STALE
SEMANTIC_PROVIDER_UNAVAILABLE
SEMANTIC_ENVIRONMENT_MISMATCH
SEMANTIC_TERM_CONFLICT
MAPPING_AMBIGUOUS

REVISION_CONFLICT
HOST_LOCK_UNAVAILABLE
HOST_COMMAND_FAILED
INTERACTION_CANCELLED

VERIFY_FAILED
SCOPE_BREACH
SLICE_PARTIAL_FAILED
```

自然语言错误文本不得成为 retry/replan/compensation 的机器决策依据。

# 30. 安全、授权与威胁模型

## 30.1 安全原则

```text
least privilege
default deny
capability as permission boundary
immutable approval evidence
audit cannot be bypassed
```

## 30.2 授权链

```text
User / enterprise IdP
  ↓ OAuth2/OIDC
Agent Runtime
  ↓
Enterprise Gateway
  ↓ policy
ApprovalToken
  ↓ changeset.apply admission
ApprovalRecord
  ↓
ExecutionSlice / ProviderBinding / binding_set_hash
  ↓
ExecutionGrant
  ↓ mTLS/workload identity/delegation
Provider / Sidecar
  ↓
Host Plugin
```

Provider 不得获得用户原始 IdP token，只获得最小 delegation context。

## 30.3 SemanticEnvironment 进入批准证据

Approval / Planning 必须绑定：

```text
ChangeSet hash
ApprovalScopeBoundary hash
SemanticEnvironmentRef/hash
PolicySnapshot hash
```

批准后 Provider/Vocabulary 自动升级不得静默改变已批准语义。

## 30.4 威胁模型

| Threat | 典型向量 | 必须缓解 |
|---|---|---|
| Prompt injection | 图纸文字/属性/第三方文档诱导写操作 | 设计内容视为 data；写路径必须 ChangeSet+Policy+Approval |
| Malicious execution provider | 虚报 low risk/rollback/verification | certification + conformance + policy override |
| Malicious semantic provider | 篡改 mapping/term/rule | namespace authority + version pinning + content hash + provenance |
| Capability escalation | Skill/LLM 诱导越权 | Policy filter before LLM + Gateway enforcement |
| Replay | 重放 approval/apply/command | one-time token + grant + stable idempotency + hashes |
| Data exfiltration | 第三方 MCP 上传模型 | egress policy + DLP + data classification |
| Local privilege escalation | 伪造 Sidecar/IPC | local ACL + workload identity/handshake |
| Semantic drift | Provider 自动升级 | SemanticEnvironment pinning |

## 30.5 Data boundary

进入 LLM context 的设计数据由 Context Composer 白名单构造。

默认不得把：

```text
full model
full exact geometry
credentials
native internal ids not required for context
```

直接进入 prompt。

## 30.6 Offline write

v0.6 默认：

- VIEW / CONTEXT / INTERACTION MAY 在 Gateway degraded 时按本地 policy 继续；
- MODEL_OPERATION MUST NOT 在缺少 Gateway authorization / ApprovalRecord / ExecutionGrant 时执行；
- Semantic Runtime 无法提供所需 PlanningSnapshot 时不得 Apply。

未来 offline write 必须由独立 ADR 引入 signed offline capability lease。

# 31. 可观测性与审计

## 31.1 Correlation model

```text
task_id
 |- interaction_id[]
 '- changeset_id
     |- execution_slice_id[]
         |- execution_unit_id[]
         |   '- command_id[]
         '- execution_id[]
```

全链路 SHOULD 传播 W3C TraceContext。

## 31.2 审计事件

至少：

```text
operation.resolved
semantic.term.resolved
semantic.mapping.applied
semantic.claim.validated
semantic.environment.pinned
semantic.projection.published
freshness.enforced
assurance.checked
impact.analyzed
changeset.built
preview.presented
approval.granted/denied
provider.bound
execution.grant.issued/denied
changeset.applied
verify.completed
scope.checked/breached
compensation.executed
policy.denied
```

审计 MUST append-only，并包含 actor、timestamp、correlation ids 与关键 hash/ref。

## 31.3 Metrics

至少：

```text
resolver_pipeline_latency
semantic_provider_latency
mapping_hit_rate
freshness_barrier_duration
reconstruction_duration
projection_publish_duration
apply_success_rate
revision_conflict_rate
verify_failure_rate
scope_breach_rate
interaction_completion_rate
```

Host native event callback 中不得同步发送重型 telemetry。

# 32. 性能与容量目标

参考初始负载：

```text
单文档 <= 50,000 entities
单 task affected entities <= 500
```

v0.6 初始 p95 目标：

| Metric | Target |
|---|---:|
| CURRENT_SELECTION 等轻量 context | <= 500 ms |
| Operation Resolver（provider <= 200） | <= 300 ms |
| cached resolver path | <= 50 ms |
| Semantic term/description cached lookup | <= 50 ms |
| Semantic mapping/validation single claim cached | <= 100 ms |
| Freshness barrier（geometry <= APPROXIMATE, depth <= 2） | <= 5 s |
| MOVE ChangeSet + Preview ready | <= 2 s |
| Apply → HostDelta（<=100 entities） | <= 3 s |
| Read-back Verify（<=100 entities） | <= 5 s |

上述数值是 baseline candidate，必须通过 reference vertical slice 实测后再冻结 SLO。

预计超时的 reconstruction/execution SHOULD 转为 async job，不得无限阻塞 Host UI。

# 33. 版本化、兼容与弃用

## 33.1 HostContract

HostContract 使用 major.minor。

- major 不兼容 → 拒绝协作；
- minor → 协商兼容版本；
- 新增可选字段属于 minor；
- native API 类型泄漏进公共 contract 属于架构破坏。

## 33.2 Canonical Action

Canonical operation 使用稳定版本 id：

```text
wall.thickness.set.v1
curve.offset.v1
```

语义破坏性变化必须注册新 major operation id，不得原地修改既有含义。

## 33.3 Semantic Provider

Provider version/content hash 进入 `SemanticEnvironment`。

影响机器语义的：

```text
domain/range/unit/constraint/mapping semantics
```

必须改变 content/environment hash。

presentation-only：

```text
label/description/translation/example
```

不应自动改变 semantic content hash。

## 33.4 Protocol compatibility

Semantic MCP / Host MCP 的 transport/protocol upgrade 不得自动改变领域 contract。

Provider Manifest 必须声明：

```text
compatible contract/protocol versions
```

## 33.5 Deprecation

Canonical Action / Provider / Semantic term extension SHOULD 支持：

```text
ANNOUNCED
DOWN_RANKED
REMOVED
```

并保留 successor / migration metadata。

# 34. 部署拓扑与运行环境

## 34.1 推荐部署

| Component | Location |
|---|---|
| Host Plugin | 设计师工作站 in-process |
| Host Sidecar / Host MCP | 设计师工作站本地进程 |
| Enterprise Gateway | 企业私有云/数据中心 |
| Registry / Policy | Gateway 信任域 |
| Semantic MCP Service | 服务端/可本地部署 |
| D5 Semantic Runtime | 服务端集群或项目级服务 |
| Semantic Providers | in-process / service / MCP / database，按 manifest |
| ChangeSet / Approval / Audit Store | 企业服务端 |

## 34.2 网络

```text
Plugin ↔ Sidecar
  local IPC / authenticated loopback

Workstation ↔ Gateway
  HTTPS + mTLS

Gateway ↔ remote Providers
  mTLS + workload identity
```

所有节点要求可靠时钟同步，用于 deadline/audit/grant expiry。

## 34.3 Cache

Semantic Service SHOULD 支持：

```text
immutable provider version cache
pinned SemanticEnvironment cache
approved definition offline read cache
```

缓存不得绕过 authority/version/hash 校验。

## 34.4 Degraded mode

Gateway 不可用：

```text
VIEW / CONTEXT / INTERACTION → MAY
MODEL_OPERATION → MUST NOT
```

Semantic Provider 暂时不可用但 pinned/cache definition 足够完成已批准 read/verify 时 MAY 降级；若 authoritative term/mapping/validation 是当前操作必要条件，则 fail closed。

# 35. Semantic Authority 与冲突规则

## 35.1 Namespace ownership

建议：

```text
ifc:*       → IFC Standard Provider authoritative

dsp:*       → DSP Core authoritative

metro:*     → Metro Semantic authoritative

acme:*      → Enterprise Provider authoritative
```

## 35.2 Mapping 不等于 Identity

```text
acme:PartitionWall maps_to ifc:IfcWall
```

不表示二者的定义完全相同。

Mapping 必须记录：

```text
mapping_type
provider
version
rule/evidence
assurance
```

## 35.3 不能覆盖外部标准

Enterprise/Metro Provider 不得：

```text
override ifc:IfcWall meaning
```

只能：

```text
add usage constraints
add narrower domain terms
add mappings
add validation rules
```

---

# 36. Description / Presentation Metadata

## 36.1 Semantic Term

建议：

```text
SemanticTerm
  term_id
  namespace
  version
  kind
  domain
  range
  unit
  allowed_values
  parent_terms
  equivalent/mapping refs

  presentation:
    label
    description
    examples
    locale
```

## 36.2 Instance 不复制 description

错误：

```text
wall-001.classification.description = "..."
wall-002.classification.description = "..."
```

正确：

```text
wall-001.classification = ifc:IfcWall
wall-002.classification = ifc:IfcWall

ifc:IfcWall
  ↓
Vocabulary lookup
```

## 36.3 Hash policy

仅修改：

```text
label
description
example
translation
```

不应自动改变 semantic content hash。

修改：

```text
domain
range
unit
constraint
mapping semantics
```

必须改变相关 definition/environment hash。

---

# 37. 缓存、可用性与失败策略

## 37.1 Semantic MCP 可用性

D5 runtime 不应因为一次 `describe_term` 远程调用失败就丢失既有 canonical state。

Semantic Service SHOULD 支持：

- provider metadata cache；
- immutable version cache；
- pinned environment cache；
- offline read of already-approved definitions。

## 37.2 Fail closed

以下情况必须 fail closed：

- authoritative term 无法解析；
- Provider version 与 PlanningSnapshot 不一致；
- conflicting authoritative claims；
- operation semantic requirement 未满足；
- classification freshness 不满足；
- minimum assurance 不满足。

非关键 presentation description 不可用时 MAY 降级展示，但不得改变机器判断。

---

# 38. Policy Execution Gates

写操作必须至少经过：

```text
Canonical Operation eligibility
Semantic Coverage/Maturity + Freshness + Assurance
Policy decision
PlanningSnapshot + SnapshotSet + pinned SemanticEnvironment
Impact + ApprovalScopeBoundary
Immutable ChangeSet
ApprovalToken → ApprovalRecord
RevisionBarrier
ProviderBinding + ExecutionGrant
Idempotent Host execution
Host verification + ActualDelta scope check
```

LLM 不得：

- 修改 policy；
- 自行跳过 freshness；
- 自行选择 native id；
- 自行做单位换算作为最终执行依据；
- 自行降低 assurance；
- 直接生成 Host API 调用。

---

# 39. Repository Target Layout

建议目标目录：

```text
contracts/
  host/
  semantic_ingest/
  canonical_actions/
  runtime_envelope/
  changeset/

hosts/
  autocad/
    plugin/
    sidecar/
  revit/
    ...
  tekla/
    ...

platform/
  gateway/                    # auth / policy / audit / grants
  capability/                 # D3
  canonical_actions/          # shared action contracts
  orchestrator/               # LangGraph + D4 workflow integration
  semantic_service/           # Semantic MCP / registry / routing
  semantic_runtime/           # D5 Collaboration Kernel / Progressive Runtime
  dependency/                 # relationship/dependency/constraint/impact
  parameter_binding/          # D6
  interaction/                # InteractionSession / coordinator
  changeset/                  # D7 ChangeSet / scope / slice / unit
  execution/                  # ProviderBinding / grants / verify / saga

providers/
  semantics/
    ifc43/
    dsp_core/
    metro/
    enterprise/

tests/
  contracts/
  gateway/
  semantic_service/
  semantic_runtime/
  dependency/
  operation_resolution/
  parameter_binding/
  interaction/
  changeset/
  execution/
  integration/
  conformance/
  failure_injection/
```

AutoCAD Sidecar 的 Host MCP 保留在 Host 目录，不移动到 Semantic Provider。

Gateway、Semantic MCP、Host MCP 是不同边界，不得因都使用 MCP 而合并实现职责。

# 40. Conformance 与测试

## 40.1 测试分层

| Layer | 验证对象 |
|---|---|
| Host Contract Tests | DTO / schema / IPC / native leakage |
| Execution Provider Conformance | schema / revision / idempotency / transaction / ActualDelta / verify |
| Semantic Provider Conformance | manifest / authority / term / mapping / validation / version |
| D5 Runtime Simulation | progressive coverage / freshness / assurance / snapshot |
| ChangeSet/Governance | scope / approval / grant / binding / saga |
| Failure Injection | timeout / replay / conflicts / partial failure |
| E2E Golden | MOVE / wall thickness / OFFSET / cross-host |

## 40.2 Execution Provider 必测

至少：

```text
input/output schema validation
REVISION_CONFLICT
same idempotency_key retry => no duplicate side effect
transaction abort => no half commit
ActualDelta includes implicit Host associativity
verification independently proves success
provider switch does not change ExecutionUnit/ChangeSet
binding_set_hash change invalidates ExecutionGrant
```

## 40.3 Scope / ChangeSet 必测

```text
CREATE rule inside scope => pass
CREATE kind/count/derivation outside scope => SCOPE_BREACH
DELETE outside scope => SCOPE_BREACH
ActualDelta outside disclosed propagation => stop remaining slices
ChangeSet semantic change => new hash / old approval invalid
```

## 40.4 Snapshot / Progressive Runtime 必测

```text
Context Freshness does not read EXACT geometry unless required
Operation Freshness upgrades fidelity only when chosen operation requires
UNRESOLVED != STALE
partial coverage cannot claim full-document fresh
CLASSIFICATION has independent freshness
PlanningSnapshot binds ProjectionRef + EnvironmentRef
SnapshotSet member revision/hash/environment change invalidates set
```

## 40.5 Semantic Provider Conformance

每个 Provider 必须测试：

```text
manifest validity
namespace ownership
version/content hash stability
term resolution
schema output
mapping determinism
validation determinism
conflict behavior
authority enforcement
environment pinning
```

## 40.6 Metro Semantic Conformance

Metro Provider 至少测试：

- IFC4X3_ADD2 合法实体白名单；
- 禁止 IFC 名称；
- official Pset/Qto 与 `PsetProj_` 区分；
- `IFC-M / IFC-O / P-M / P-C / P-R / PROHIBITED`；
- IDS requirement；
- 墙/板/Alignment/轨道/隧道/MEP reference cases；
- 单位与字段类型；
- mapping provenance；
- Metro rule 不覆盖 `ifc:*` canonical authority。

## 40.7 Failure injection

至少：

```text
Apply committed but response lost => idempotent replay
approval wait during designer edit => RevisionBarrier blocks
second cross-host Slice fails => Saga/partial state
Sidecar restart => explicit recovery/failure
Interaction user cancel => CANCELLED + checkpoint resume
semantic provider unavailable => cached/pinned policy or fail closed
provider semantic version drift => ENVIRONMENT_MISMATCH
ActualDelta outside scope => SCOPE_BREACH
PENDING without AsyncOperationRef => contract failure
```

## 40.8 Extensibility proof

必须有：

```text
A-WALL-* → IfcWall
```

验收测试。

新增/删除 Enterprise Mapping Provider 只能改变 Provider/config，不得修改 D5 Core。

还必须有：

```text
AutoCAD wall ↔ Revit wall
same SemanticId
same canonical operation
different ProviderBinding
```

证明 cross-host identity/action 不依赖 Host-specific core branch。

# 41. Migration from v0.5 / current branch

## 41.1 v0.5 Runtime/Governance contracts — 保留并升级

以下不是 legacy，应继续作为 baseline：

```text
Enterprise Gateway boundary
LangGraph workflow ownership
ChangeJournal / DirtyMap
Two-phase Freshness
ContextSnapshot / PlanningSnapshot / SnapshotSet
ExecutionSlice
canonical ExecutionUnit
ProviderBinding
ApprovalToken / ApprovalRecord / ExecutionGrant
ApprovalScopeBoundary / SCOPE_BREACH
InteractionSession
RequestEnvelope / AsyncOperationRef / ErrorShape
ActualDelta reconciliation
Dependency / Constraint / Impact / Propagation
Saga / Compensating ChangeSet
audit / correlation / performance / compatibility / deployment rules
```

## 41.2 D5 当前实现可直接保留

```text
ChangeJournal
DirtyMap
FreshnessState
FreshnessContract
Coverage
AspectRequirement
AspectGuarantee
ContextSnapshot / PlanningSnapshot
SnapshotSet
revision / coverage / guarantee barriers
```

## 41.3 必须修改

### Identity

从：

```text
IdentityBinding
  semantic_id
  document_id
  native_id
  ifc_global_id
```

改为：

```text
SemanticIdentity
HostBinding[]
ExternalIdentity[]
```

### Progressive D5

新增/固化：

```text
CLASSIFICATION
coverage / maturity
semantic depth
geometry fidelity
Assurance / Provenance
SemanticProjectionRef
SemanticEnvironmentRef
```

### D3/D4

拆分：

```text
canonical semantic constraints
provider native constraints
```

Canonical Action 增加：

```text
title
description
slot binding
semantic term refs
freshness / coverage / assurance requirements
effects / verification
```

### D7

早期 v0.6 Draft 中把 `ExecutionUnit` 写成 provider-specific 的表述已废弃；本 baseline 以 canonical ExecutionUnit 为准。

恢复：

```text
ExecutionSlice
  ↓
ExecutionUnit (canonical)
  ↓
ProviderBinding (provider/native)
  ↓
HostCommand
```

## 41.4 新增子系统

```text
Semantic Service / Semantic MCP Server
SemanticProvider Contracts
IFC4.3 Provider
DSP Core Provider
Metro Semantic Provider
Semantic Environment
Semantic Ingest Contract
Assurance
Progressive Coverage/Maturity
```

## 41.5 不恢复的旧设计

不得恢复：

```text
ifc_global_id special field in D5 Core
native+semantic mixed entity_constraints
Host-specific mapping inside semantic_runtime
full realtime IFC mirror requirement
```

# 42. 实施顺序

建议顺序：

```text
Phase A — Architecture Freeze
  1. 本 Spec v0.6 corrected baseline
  2. ADR-005 Semantic Service / Provider Boundary
  3. ADR-006 Progressive Semantic Runtime
  4. ADR-007 ChangeSet Execution / Approval Boundary
  5. Contract naming/version policy

Phase B — D5 Baseline Completion
  6. SemanticIdentity / HostBinding / ExternalIdentity
  7. CLASSIFICATION aspect
  8. Progressive coverage/maturity model
  9. geometry fidelity in FreshnessContract
  10. ProjectionRef / EnvironmentRef / SnapshotSet invariant

Phase C — Semantic Service
  11. SemanticProvider contracts
  12. Semantic Registry / Routing
  13. Semantic MCP Server
  14. environment pinning/cache

Phase D — Reference Providers
  15. DSP Core Provider
  16. IFC4.3 Provider
  17. Metro Semantic Provider

Phase E — Ingestion / Progressive Proof
  18. NormalizedDesignFact contract
  19. AutoCAD native fact extractor
  20. enterprise A-WALL mapping provider
  21. prove A-WALL → IfcWall without D5 changes
  22. prove task only upgrades required aspects/fidelity

Phase F — Action / Interaction
  23. Canonical Action contract upgrade
  24. D4 semantic eligibility
  25. D6 Slot Binder
  26. InteractionSession / Host interaction

Phase G — Impact / ChangeSet / Governance
  27. Dependency/Constraint/Impact contracts
  28. ApprovalScopeBoundary
  29. ChangeSet immutable core
  30. ExecutionSlice + canonical ExecutionUnit
  31. ProviderBinding / binding_set_hash
  32. ApprovalRecord / ExecutionGrant
  33. Verify / ScopeComparator / Saga

Phase H — Full E2E
  34. wall thickness Revit
  35. wall thickness AutoCAD
  36. OFFSET CREATE scope case
  37. cross-host SnapshotSet/Saga failure injection
```

原则：

- D6/D7 不应在 D5/Semantic Service 核心语义边界未冻结前扩大；
- 但 v0.5 已冻结的 D7/治理 contract 应先保留在 Spec 中，避免实现阶段重新发明。

# 43. Architecture Invariants

以下约束应成为自动架构测试或 code review checklist：

1. `semantic_runtime` 不 import AutoCAD/Revit/Tekla native package。
2. `semantic_runtime` 不 hardcode enterprise layer/family/category mapping。
3. `semantic_runtime` 不特殊硬编码 IFC GlobalId 字段。
4. 平台通过 Semantic Service contract 使用语义，不直接依赖具体 Semantic Provider。
5. MCP 是 protocol/transport；Provider Protocol 是 domain contract。
6. `ifc:*` canonical identity 只能由 pinned IFC Provider 权威定义。
7. Metro/Enterprise 只能扩展、映射、约束 IFC，不得重定义 IFC canonical meaning。
8. Progressive Semantic Runtime MUST 是 task/aspect/coverage scoped，不维护无条件全量实时 IFC 镜像。
9. `FRESH` 不等于“语义完整”；coverage/maturity 与 freshness 必须分离。
10. geometry fidelity 与 semantic depth 必须分离。
11. D4 LLM action space 不暴露 provider-native execution schema。
12. D6 可确定性绑定的 slot 不交给 LLM。
13. 所有 MODEL_OPERATION MUST 通过 immutable ChangeSet。
14. `ExecutionSlice` 是 Host/document/approved-scope 边界，不是 provider 边界。
15. `ExecutionUnit` MUST 保持 canonical/provider-neutral。
16. provider tool/native arguments 只能进入 ProviderBinding/HostCommand。
17. Preview/Approval/Execute 必须绑定同一个 ChangeSet hash 与 approved scope。
18. ApprovalRecord 必须绑定 SemanticEnvironment。
19. ProviderBinding 集变化必须改变 binding_set_hash，并使旧 ExecutionGrant 失效。
20. Host ActualDelta 是执行副作用 reconciliation 的权威事实。
21. `ActualDelta ⊄ ApprovalScopeBoundary` 必须 SCOPE_BREACH。
22. Cross-host failure 使用 Saga/Compensating ChangeSet，不使用 XA/2PC。
23. Snapshot 必须绑定 exact Host revision、coverage、semantic projection、SemanticEnvironment。
24. SnapshotSet 任一 member 变化必须改变 set hash。
25. 高风险 operation 在 freshness/coverage/assurance 不满足时 fail closed。
26. Relationship / Dependency / Constraint / Impact / ChangeDAG 不得混淆。
27. `request_id` 与 `idempotency_key` 必须分离。
28. PENDING 响应必须返回 typed AsyncOperationRef。
29. Gateway 不得承担设计规划或 semantic authority。
30. Semantic MCP 不得拥有 DSP Canonical Action。
31. MODEL_OPERATION 在无有效 Gateway authorization/grant 的 degraded mode 下不得执行。
32. Phase B Operation Freshness MUST occur after D6 material target/argument binding.
33. Persistent HostBinding 与 runtime HostRuntimeRef MUST 分离；provider implementation id 不得充当 Host identity。
34. 一个 SnapshotSet MUST 使用单一 pinned SemanticEnvironment。

# 44. 术语表

| 术语 | 定义 |
|---|---|
| Host | 设计软件运行环境，如 AutoCAD、Revit |
| Host Provider | 提供 Host read/write 能力的插件/Sidecar/MCP |
| Host Contract | DSP 与 Host 边界的低语义数据契约 |
| Enterprise Gateway | AuthN/AuthZ、Policy、Routing、Audit、Approval/Grant 的治理边界 |
| Native Fact | 从 Host 读取的原生事实 |
| NormalizedDesignFact | Host-neutral 固定结构的事实传输契约 |
| Progressive Semantic Modeling | 按任务/aspect/coverage 渐进提升语义深度，而非维护全量实时语义镜像 |
| Semantic Depth | NATIVE / NORMALIZED / CANONICAL / DOMAIN 的语义深度 |
| Geometry Fidelity | NONE / BOUNDS / APPROXIMATE / EXACT / NATIVE |
| Semantic Coverage / Maturity | 某 entity/aspect/property/domain 已解析到什么程度 |
| Semantic Provider | 提供 vocabulary/mapping/validation/projection 的领域实现 |
| Semantic MCP Server | DSP 统一语义服务的 MCP 协议入口 |
| IFC4.3 Provider | IFC 标准语义权威 Provider |
| Metro Semantic | IFC4.3 之上的地铁领域语义、PsetProj、IDS、映射和规则 |
| DSP Core Semantic | DSP 跨行业协同需要的自有语义 |
| SemanticEnvironment | 某一时刻被 pin 的 Provider/version/hash 集合 |
| SemanticIdentity | 跨 Host 的 DSP 稳定对象身份 |
| HostBinding | SemanticIdentity 到 Host native entity 的绑定 |
| ExternalIdentity | IFC GlobalId 等外部身份的 scheme/value 绑定 |
| SemanticProjection | 当前设计已经重建出的 canonical semantic state |
| Freshness | 已知 semantic fact 相对于 Host revision 的新鲜状态 |
| Assurance | semantic claim 的来源与可信等级 |
| SemanticFreshnessContract | 指定 coverage/aspect/fidelity/assurance 的阶段性重建契约 |
| ContextSnapshot | Phase A freshness 结果 |
| PlanningSnapshot | Phase B operation freshness 结果 |
| SnapshotSet | 一个或多个 PlanningSnapshot 的不可变跨 document 集合 |
| Canonical Action | Host-independent 的用户/Agent 动作语义 |
| Slot Binding | Canonical Action 参数来源与确定性绑定过程 |
| InteractionSession | Host-native 长时间用户交互的显式 session |
| Dependency Graph | 描述变化可能影响关系，不等同 Relationship Graph |
| Change Impact Graph | 当前 ChangeSet/task 的实际预计影响图 |
| ChangeSet | 被规划/审批的 canonical immutable logical transaction |
| ApprovalScopeBoundary | 被预览/批准的 effect scope predicates |
| ExecutionSlice | Host instance + document + approved scope 的执行分片 |
| ExecutionUnit | Slice 内 provider-neutral canonical 最小执行单元 |
| ProviderBinding | ExecutionUnit 到具体 provider/tool/native binding 的执行期绑定 |
| ApprovalRecord | 持久不可变批准事实 |
| ExecutionGrant | 针对一个 Slice + binding set 的短生命周期执行授权 |
| HostDelta / ActualDelta | Host 实际产生的变更，是 reconciliation 权威依据 |
| SCOPE_BREACH | ActualDelta 超出 ApprovalScopeBoundary 的阻断型一致性错误 |
| Compensating ChangeSet | Saga 场景用于逆向/补偿的可审计 ChangeSet |
| AsyncOperationRef | PENDING 请求的 typed session/job handle |

# 45. v0.6 冻结条件

v0.6 进入 `Accepted / Contract Freeze` 前，至少完成：

1. Host Plane / Semantic Plane / Action Plane / Collaboration Kernel / Governance Plane 职责无重叠；
2. Semantic MCP Server 与 SemanticProvider Protocol 的边界通过 ADR 冻结；
3. IFC4.3 与 Metro Semantic 权威关系冻结；
4. Progressive Semantic Model 的 semantic depth / geometry fidelity / coverage / freshness / assurance 五类概念冻结；
5. `SemanticIdentity : HostBinding = 1:N` 冻结；
6. `ExternalIdentity` 替代 `ifc_global_id` 特例；
7. `CLASSIFICATION` 进入 D5 SemanticAspect；
8. SemanticFreshnessContract 的 two-phase / coverage / geometry fidelity 结构冻结；
9. SemanticSnapshot 绑定 ProjectionRef + EnvironmentRef，SnapshotSet cross-host invariant 冻结；
10. Canonical Action description/slot semantic metadata 模型冻结；
11. D6 binding classes + InteractionSession 冻结；
12. D7 `ChangeSet → ExecutionSlice → ExecutionUnit → ProviderBinding → ExecutionGrant` 链冻结；
13. `ExecutionUnit` 明确保持 provider-neutral；
14. ApprovalScopeBoundary / SCOPE_BREACH / Saga compensation 冻结；
15. RequestEnvelope / ErrorShape / idempotency / AsyncOperationRef 冻结；
16. Enterprise Gateway 的 authorization/governance 边界冻结；
17. Dependency / Constraint / Impact / Propagation 边界冻结；
18. 用“墙体加厚到 300mm”演练通过 Revit 和 AutoCAD 两种 Provider 路径；
19. 用 `A-WALL → IfcWall` 证明 Enterprise Mapping Provider 可插拔且 D5 Core 不改代码；
20. Metro reference case 通过 Schema / PsetProj / IDS / mapping / provenance；
21. 至少一个 cross-host SnapshotSet + Slice/Saga failure-injection 测试通过。

# 46. 一句话系统边界

```text
Host MCP         = 在具体 Host 里怎么做
Semantic MCP     = 标准/领域语义与规则是什么
Gateway          = 谁能调用什么、是否允许执行、如何审计
D4               = 当前允许表达什么 Canonical Action
D5               = 当前设计已经被理解成什么、理解到什么程度、是否新鲜/可信
D6               = 这次 Action 的参数具体是什么，缺失参数如何从 Host 交互获得
Impact Layer     = 这次修改会影响什么、哪些必须传播/验证
D7 ChangeSet     = 准备审批什么 canonical change
ExecutionSlice   = 在哪个 Host/document/approved scope 执行
ExecutionUnit    = Slice 内最小 canonical 执行单位
ProviderBinding  = 这次由哪个 provider/native implementation 执行
LLM              = 在受约束空间中理解意图，不拥有系统真相、权限或执行权
```

---

# Appendix A. Normative Core DTOs

正文解释职责；本附录冻结跨模块必须一致理解的 contract shape。

## A.1 Identity / Runtime Host

```text
HostBinding { semantic_id, host_type, document_id, native_id, native_kind }
HostRuntimeRef { host_type, host_instance_id, document_id }
ExternalIdentity { semantic_id, scheme, value }
```

## A.2 ResolvedOperation

```text
ResolvedOperation {
  operation_id
  canonical_operation
  title
  description
  llm_input_schema
  canonical_entity_constraints
  context_freshness_requirements
  operation_freshness_requirements
  coverage_requirements
  assurance_requirements
  effects
  policy_decision
  risk
  task_score
  preview_supported
  rollback_supported
  verification_contract
  candidate_provider_ids[]
}
```

## A.3 SemanticFreshnessContract

```text
SemanticFreshnessContract {
  contract_id
  project_id
  contract_type: CONTEXT|OPERATION
  root_entities[]
  requirements[] {
    aspect
    required_state
    minimum_coverage?
    semantic_depth?
    geometry_fidelity?
    minimum_assurance?
  }
  neighborhood { depth, relations[] }
}
```

## A.4 SemanticSnapshot / SnapshotSet

```text
SemanticSnapshot {
  snapshot_id
  kind: CONTEXT|PLANNING
  project_id
  document_ref
  base_host_revision
  freshness_contract_id
  freshness_contract_hash
  coverage
  aspect_guarantees[] {
    aspect
    entity_scope | coverage_ref
    required_state
    geometry_fidelity?
    semantic_depth?
    minimum_assurance?
  }
  semantic_projection_ref
  semantic_environment_ref
  hash
}

SnapshotSet {
  snapshot_set_id
  kind: PLANNING
  semantic_environment_ref
  members[] {
    document_ref
    snapshot_id
    snapshot_hash
    base_host_revision
    semantic_projection_ref
  }
  hash
}
```

所有 members MUST 使用 top-level pinned SemanticEnvironment。

## A.5 ChangeSet / Execution

```text
ChangeSet {
  changeset_id
  task_id / project_id
  base_snapshot_set_id / base_snapshot_set_hash
  semantic_environment_ref
  root_operations[] / derived_operations[]
  preconditions[] / affected_entities[] / semantic_impacts[]
  validation_tasks[]
  approval_scope_boundary_ref
  risk / approval / verification / rollback
  hash / status
}

ExecutionSlice {
  execution_slice_id
  changeset_id
  host_instance_id
  document_id
  approved_scope_ref
  execution_units[]
  status
}

ExecutionUnit {
  execution_unit_id
  execution_slice_id
  canonical_operation
  targets[]
  arguments
  preconditions[]
  expected_effects[]
}

ProviderBinding {
  binding_id
  execution_unit_id
  canonical_operation
  provider_server / provider_tool / provider_version
  host_instance_id
  input_adapter_version
  native_binding_metadata
  verification_contract / rollback_contract
  binding_expires_at
}
```

`ExecutionUnit` MUST 保持 provider-neutral；native payload 只进入 ProviderBinding/HostCommand。

## A.6 ApprovalScopeBoundary / Approval / Grant

```text
ApprovalScopeBoundary {
  scope_id
  changeset_hash
  existing_entity_rules[] { entities[] | predicate, allowed_aspects[] }
  creation_rules[] {
    canonical_operation
    source_entities[] | source_predicate
    entity_kinds[]
    max_count?
    required_derivation?
  }
  deletion_rules[] { entities[] | predicate }
  propagation_bundle_ids[]
  execution_slice_scopes[]
  scope_hash
}

ApprovalRecord {
  approval_id
  changeset_hash
  approved_scope_hash
  semantic_environment_ref / semantic_environment_hash
  approver
  policy_snapshot_hash
  approved_at
  revoked_at?
}

ExecutionGrant {
  grant_id
  approval_id
  changeset_hash
  execution_slice_id
  binding_set_hash
  host_instance_id
  allowed_operations[]
  approved_scope_hash
  issued_at / expires_at / state
}
```

## A.7 Interaction / Envelope / Error

```text
InteractionSession {
  interaction_id / task_id / host_instance_id / document_id
  interaction_type
  input_constraints / result_schema
  state: PENDING|COMPLETED|CANCELLED|EXPIRED
  result? / created_at / expires_at
}

RequestEnvelope {
  request_id / task_id / project_id / actor_context
  correlation_ids
  deadline_at
  idempotency_key?
  payload
}

AsyncOperationRef { type, id }

ResponseEnvelope {
  request_id
  status: OK|PENDING|ERROR
  correlation_ids
  snapshot_ref?
  operation_ref?: AsyncOperationRef
  result?
  error?: ErrorShape
}

ErrorShape { error_code, category, message, correlation_ids, retryable, details[] }
```

同一逻辑副作用重试：new `request_id`, same `idempotency_key`；`PENDING` MUST 带 typed AsyncOperationRef。

---

# Appendix B. Module Interaction Contracts

## B.1 通用规则

跨模块 contract SHALL 明确 `Owner / Caller / Input / Output / Mode / Retry owner / State owner`。长期状态必须有单一 authoritative owner；LLM 不负责 protocol retry、authorization retry 或 provider failover。

## B.2 Interaction Matrix

| Caller | Callee | Contract | Mode | Retry owner | State owner |
|---|---|---|---|---|---|
| LangGraph | Host Context | context → document/selection/view | sync | LangGraph(read) | Host |
| LangGraph | D5 | FreshnessContract → Snapshot | sync/job | freshness client | D5 |
| LangGraph | D4 | ContextSnapshot → ResolvedOperation[] | sync | LangGraph | D4/Registry |
| D6/LangGraph | Interaction Coordinator | request → InteractionSession | async | idempotency owner | Interaction Coordinator |
| LangGraph | Impact Analyzer | BoundProposal+PlanningSnapshot → Impact/Scope | sync/job | LangGraph | task runtime |
| LangGraph | ChangeSetBuilder | Proposal+SnapshotSet → ChangeSet | sync | deterministic caller | ChangeSet Store |
| LangGraph | Gateway | approval admission → ApprovalRecord | HITL/sync | LangGraph | Gateway |
| LangGraph | Execution Planner | ChangeSet → Slice[]/Unit[] | sync | deterministic caller | Execution Planner |
| LangGraph | Provider Resolver | ExecutionUnit → ProviderBinding | sync | Resolver | Registry/Resolver |
| Gateway | Provider | Grant+Slice+Units+Bindings → result | sync/job | idempotency owner | Provider |
| Provider/Sidecar | Host Plugin | HostCommand → Result/ActualDelta | IPC | Sidecar | Host |
| LangGraph | Verify/Reconcile | ActualDelta → verify/scope result | sync/job | Orchestrator | D5/ChangeSet |

## B.3 Two-phase ordering

```text
Phase A ContextSnapshot
→ D4
→ LLM OperationProposal
→ D6 material binding / InteractionSession
→ BoundOperationProposal
→ derive Phase B contract
→ D5 selective reconstruction
→ PlanningSnapshot / SnapshotSet
→ Impact / ChangeSet
```

## B.4 Apply / Verify / Scope

```text
ApprovalRecord + ChangeSet
→ ExecutionSlice[] → ExecutionUnit[]
→ RevisionBarrier
→ ProviderBinding[] / binding_set_hash
→ ExecutionGrant
→ HostCommand
→ ActualDelta
→ D5 reconcile + Verify + Scope Comparator
```

| Condition | Required action |
|---|---|
| fail before commit | native rollback + HOST_COMMAND_FAILED |
| commit + verify pass + scope inside | Slice SUCCEEDED |
| commit + verify fail | VERIFY_FAILED → reconcile/compensating ChangeSet |
| ActualDelta outside scope | SCOPE_BREACH → stop remaining slices → compensate/reapproval |

---

# Appendix C. Reference Vertical Slices

## C.1 MOVE — Runtime / Execution / Governance

```text
AutoCAD selection
→ Context Freshness / CS-001
→ D4 MOVE ResolvedOperation
→ LLM move.v1 + displacement
→ D6 binding
→ Operation Freshness / PS-001
→ SnapshotSet PSS-001
→ Impact + ApprovalScopeBoundary
→ ChangeSet CS-001
→ Preview / ApprovalRecord
→ ExecutionSlice XS-CAD-01
→ canonical ExecutionUnit EU-001
→ RevisionBarrier
→ ProviderBinding PB-001
→ binding_set_hash / ExecutionGrant
→ HostCommand / AutoCAD transaction
→ ActualDelta
→ Verify + Scope Check + D5 reconcile
```

MOVE 验证 execution/governance baseline，不要求先建立丰富 IFC/Metro domain semantics。

## C.2 Wall Thickness — Semantic / Cross-host

正文第 26 章为第二条 reference slice，额外验证 Progressive Semantic、IFC/Enterprise/Metro、SemanticEnvironment pinning 与 same canonical operation / different ProviderBinding。

MOVE 与 Wall Thickness MUST 并存。

---

# Appendix D. Numbered Contract Conformance

## D.1 Runtime / Execution — RC

| ID | Contract |
|---|---|
| RC-001 | schema invalid input must be rejected |
| RC-002 | stale revision returns REVISION_CONFLICT |
| RC-003 | same idempotency_key retry produces no duplicate side effect |
| RC-004 | transaction abort leaves no half commit |
| RC-005 | ActualDelta includes implicit Host associativity |
| RC-006 | verification independently proves success |
| RC-007 | VIEW/CONTEXT with model mutation effect fails conformance |
| RC-008 | provider switch does not alter canonical ChangeSet/ExecutionUnit |
| RC-009 | binding_set_hash change invalidates old ExecutionGrant |
| RC-010 | CREATE outside creation_rule returns SCOPE_BREACH |
| RC-011 | ActualDelta outside scope stops remaining slices |
| RC-012 | ApprovalToken consumption persists ApprovalRecord |
| RC-013 | child deadline_at <= parent deadline_at |
| RC-014 | PENDING without AsyncOperationRef is contract failure |
| RC-015 | interaction retry does not create a second Host prompt |
| RC-016 | second cross-host Slice failure enters Saga/partial state |

## D.2 Progressive Runtime — SR

| ID | Contract |
|---|---|
| SR-001 | Context Freshness does not read EXACT/NATIVE geometry by default |
| SR-002 | Phase B occurs after D6 material binding |
| SR-003 | UNRESOLVED != STALE |
| SR-004 | partial coverage cannot claim full-document fresh |
| SR-005 | CLASSIFICATION has independent freshness/coverage |
| SR-006 | PlanningSnapshot binds ProjectionRef + EnvironmentRef |
| SR-007 | SnapshotSet members share one pinned SemanticEnvironment |
| SR-008 | member revision/snapshot/projection/environment change invalidates set hash |
| SR-009 | insufficient assurance fails closed |
| SR-010 | reconstruction upgrades only task-required aspects/depth/fidelity |

## D.3 Semantic Provider / Metro / Cross-host

| ID | Contract |
|---|---|
| SP-001 | manifest declares id/type/version/hash/namespaces/capabilities/authority |
| SP-002 | non-authoritative provider cannot silently override namespace |
| SP-003 | pinned term/mapping/validation is deterministic |
| SP-004 | machine semantic change changes content/environment hash |
| SP-005 | Enterprise mapping provider changes do not modify D5 Core |
| SP-006 | A-WALL-* → ifc:IfcWall works through Provider/config |
| SP-007 | provider outage follows pinned-cache policy or fails closed |
| MS-001 | Metro output is IFC4X3_ADD2 legal |
| MS-002 | official Pset/Qto separated from PsetProj/QtoProj |
| MS-003 | IFC-M/IFC-O/P-M/P-C/P-R/PROHIBITED map to structured requirements |
| MS-004 | IDS/unit/type/provenance are verifiable |
| MS-005 | Metro cannot redefine ifc:* canonical meaning |
| CH-001 | same SemanticId can have AutoCAD/Revit HostBindings |
| CH-002 | same canonical wall operation can use different ProviderBindings |
| CH-003 | HostBinding must resolve to active HostRuntimeRef before execution |
| CH-004 | ChangeSet Planning SnapshotSet uses one pinned SemanticEnvironment |
| CH-005 | cross-host Saga preserves auditable partial/compensation state |
