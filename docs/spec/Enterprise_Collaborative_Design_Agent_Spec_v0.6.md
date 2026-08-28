# DSP — Enterprise Collaborative Design Agent Specification v0.6

> 状态：Draft / Architecture Baseline Candidate  
> 日期：2026-08-28  
> 取代：`Enterprise_Collaborative_Design_Agent_Spec_v0.5.md` 作为下一版候选规格  
> 适用范围：多 Host 设计协同、Host MCP、Semantic MCP、Canonical Action、D5 Collaboration Kernel、D6 参数绑定、D7 ChangeSet/执行闭环  
> Metro Semantic 基线：`IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版`，目标 Schema 为 `IFC4X3_ADD2 / IFC 4.3.2.0`

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
ChangeSet / Approval
  ↓
Provider Binding
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
7. 任何写操作在执行前绑定 PlanningSnapshot、SemanticEnvironment 与审批上下文；
8. 执行结果必须由 Host read-back / delta 形成闭环验证。

## 1.2 非目标

v0.6 不要求：

- DSP Core 直接理解所有 Revit/AutoCAD/Tekla 原生对象；
- 把 IFC 文件格式本身作为运行时唯一存储格式；
- 让 LLM 根据自然语言 `description` 推断安全规则；
- 为每个 Host 成对实现 Host↔Host 映射；
- 让 Metro Semantic 覆盖或修改 IFC 官方定义；
- 在没有 Freshness / Assurance / Snapshot 的情况下执行高风险写操作。

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

# 3. 分层架构

```text
                              ┌──────────────────────┐
                              │        User          │
                              └──────────┬───────────┘
                                         │
                                         ▼
                              ┌──────────────────────┐
                              │ Orchestrator / LLM   │
                              └───────┬──────┬───────┘
                                      │      │
                         action space │      │ semantic context
                                      ▼      ▼
                         ┌────────────────┐  ┌────────────────────┐
                         │ D4 Resolver    │  │ Semantic MCP Server│
                         │ + Action Catalog│ │ Semantic Service   │
                         └────────┬───────┘  └─────────┬──────────┘
                                  │                    │
                                  │             SemanticProvider
                                  │           ┌────────┼──────────────┐
                                  │           ▼        ▼              ▼
                                  │        IFC4.3   Metro          Enterprise
                                  │        Provider Semantic       Semantic
                                  │
                                  ▼
                         ┌──────────────────────────┐
                         │ D5 Collaboration Kernel  │
                         │ Identity / Projection    │
                         │ Freshness / Assurance    │
                         │ Snapshot / Journal       │
                         └────────────┬─────────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │ D6 Parameter Binder      │
                         └────────────┬─────────────┘
                                      │
                                      ▼
                         ┌──────────────────────────┐
                         │ D7 ChangeSet / Approval  │
                         │ ProviderBinding          │
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

---

# 4. 互操作等级

DSP 定义四级语义互操作能力：

## L0 — Native

只有 Host 原生对象和原生 ID。

```text
AutoCAD Handle A31
Revit ElementId 38912
```

仅支持 Host-local 操作。

## L1 — Normalized

数据结构已统一为 `NormalizedDesignFact`，但分类可能未知。

可用于：

- identity；
- placement；
- bounds；
- revision；
- basic geometry；
- native classification evidence。

## L2 — Canonical

至少具备：

```text
SemanticIdentity
IFC4.3 canonical classification
DSP Core properties / relationships
canonical units / coordinates
Freshness
Assurance / Provenance
```

L2 是跨 Host 高层协作的最低要求。

## L3 — Domain / Enterprise

在 L2 基础上增加：

```text
Metro Semantic
Enterprise Semantic
专业 Vocabulary
IDS / domain validation
project-specific mappings
```

领域特定操作可要求 L3。

---

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

D3 负责发现和标准化 Host/Execution Provider 的“能做什么”。

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
```

## 7.2 Semantic constraint 与 Native constraint 分离

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

前者用于 D4 eligibility；后者用于后期 ProviderBinding。

---

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

## 9.2 两阶段使用 D5

推荐流程：

```text
Orchestrator
  ↓
D5 ContextSnapshot
  ↓
D4 pre-resolution / schema compile
  ↓
LLM operation selection + INTENT slots
  ↓
D5 operation-specific freshness / assurance barrier
  ↓
D6
```

D4 不导入 D5 实现；通过稳定 Read Contract 交互。

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

---

# 10. Semantic Service / Semantic MCP Server

## 10.1 定位

Semantic Service 是 DSP 平台统一语义服务层。

其 MCP Server 是对外协议入口，但领域边界由 `SemanticProvider` Contract 定义。

平台组件不得直接依赖：

```text
Ifc43McpServer
MetroMcpServer
AcmeMcpServer
```

而应依赖：

```text
SemanticService
```

## 10.2 Semantic MCP tools

MVP 建议提供：

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
semantic.project_fact
semantic.validate_projection
semantic.query_inheritance
semantic.query_applicability
```

## 10.3 SemanticService Contract

逻辑接口：

```text
resolve_term(term_id, environment)
describe_term(term_id, locale, environment)
get_term_schema(term_id, environment)
validate_claim(claim, environment)
find_mappings(source_claim, target_namespace, environment)
get_environment(environment_id)
```

所有会影响机器解释的调用必须绑定一个明确的 `SemanticEnvironment`。

---

# 11. Semantic Provider

## 11.1 Provider Protocol

Semantic Provider 是领域能力，不是 transport。

推荐拆为 capability-oriented protocols：

```text
SemanticVocabularyProvider
SemanticMappingProvider
SemanticValidationProvider
SemanticProjectionProvider
```

一个 Provider 可以实现一个或多个能力。

## 11.2 Provider Manifest

每个 Provider 必须声明：

```text
provider_id
provider_type
namespaces[]
version
content_hash
capabilities
source/authority
compatible_semantic_contract_version
```

示例：

```yaml
provider_id: buildingSMART.ifc43
provider_type: STANDARD
namespaces:
  - ifc
version: "4.3.2.0"
capabilities:
  vocabulary: true
  validation: true
  projection: true
  mapping: false
authority:
  ifc: authoritative
```

## 11.3 Provider transport adapter

Provider 实现 MAY 是：

```text
InProcessSemanticProvider
McpSemanticProvider
FileSemanticProvider
DatabaseSemanticProvider
```

D5 / D4 不感知具体实现方式。

---

# 12. Semantic Provider 类型

## 12.1 IFC4.3 Provider

IFC Provider 是 `ifc:*` namespace 的标准权威来源。

职责：

- IFC entity/type/property/relationship 定义；
- inheritance；
- Schema validity；
- 官方 Pset/Qto metadata；
- standard descriptions；
- IFC-compatible projection/validation helpers。

DSP 不重新定义 `ifc:IfcWall` 的 canonical meaning。

## 12.2 DSP Core Provider

DSP Core Provider 管理跨行业协作所需但 IFC 不直接定义的平台语义，例如：

```text
dsp:SemanticIdentity
dsp:HostBinding
dsp:Freshness
dsp:Assurance
dsp:SemanticSnapshot
```

如某业务属性可以直接引用 IFC 官方定义，应优先引用标准 term，避免重复造词。

## 12.3 Metro Semantic Provider

Metro Semantic 是地铁领域 Provider，不是 IFC Provider 的替代品。

权威顺序：

```text
IFC Schema
  ↓
IFC official Pset / Qto
  ↓
Metro Semantic usage / project extension
  ↓
PsetProj_* / QtoProj_*
  ↓
IDS / 专项规则 / 项目映射
```

Metro Provider 可提供：

- 地铁领域 entity usage rules；
- `PsetProj_*` / `QtoProj_*` 数据字典；
- 字段 required / conditional / recommended / prohibited 状态；
- IDS requirements；
- 地铁对象映射；
- 轨道、车站、隧道、地质、限界、MEP 专项规则；
- 项目几何/数学 validation references。

Metro Provider 不得修改 IFC Schema 的 canonical definition。

## 12.4 Enterprise Semantic Provider

企业 Provider 可以表达：

```text
企业分类
图层标准
族/类型标准
资产编码
专业命名规范
企业自定义属性
```

示例：

```text
AutoCAD layer A-WALL-EXT
  ↓ enterprise mapping
acme:ExteriorWall
  ↓ canonical mapping
ifc:IfcWall
```

新增/删除企业 Mapping Provider 不得要求修改 D5 Core。

---

# 13. Metro Semantic Contract

## 13.1 基线

Metro Semantic reference package 基于：

```text
IFC4.3 地铁 BIM 数据标准 V3.2——构件属性增强合并版
Target Schema: IFC4X3_ADD2 / IFC 4.3.2.0
```

该领域标准明确区分：

```text
IFC-M
IFC-O
P-M
P-C
P-R
禁止
```

Metro Provider 必须保留这些等级的语义，不得全部压缩成一个 Boolean required。

## 13.2 Metro semantic claim 示例

```yaml
term_id: metro:PsetProj_WallDesign.DesignThickness
kind: Property
maps_to_container: PsetProj_WallDesign
applies_to:
  - ifc:IfcWall
range:
  type: IfcLengthMeasure
requirement_level: P-M
source:
  package: metro.ifc43.v3.2
```

## 13.3 官方与项目属性不得混淆

例如墙体：

```text
ifc:IfcWall

IFC official:
  Pset_WallCommon.LoadBearing
  Pset_WallCommon.FireRating
  Qto_WallBaseQuantities.Width

Metro/project:
  PsetProj_WallDesign.WallFunction
  PsetProj_WallDesign.DesignThickness
  PsetProj_WallDesign.WaterproofGrade
```

Semantic Service 的返回结果必须带 `authority/source`，让调用方能够区分标准定义与项目扩展。

## 13.4 Metro validation

Metro Provider 中的校验规则至少分为：

```text
SCHEMA
IDS
DATA_DICTIONARY
RELATIONSHIP
GEOMETRY
MATH
PROJECT_POLICY
```

例如：

```text
DesignThickness
≈ geometry thickness
≈ material layer total thickness
```

这种规则不得伪装成 IFC Schema constraint。

---

# 14. SemanticEnvironment

## 14.1 定义

SemanticEnvironment 是一次确定性语义解释所使用的 Provider 集合：

```yaml
semantic_environment:
  providers:
    - provider_id: buildingSMART.ifc43
      version: "4.3.2.0"
      content_hash: "..."

    - provider_id: dsp.core
      version: "1.0"
      content_hash: "..."

    - provider_id: metro.ifc43
      version: "3.2"
      content_hash: "..."

    - provider_id: acme.design.standard
      version: "2026.08"
      content_hash: "..."
```

## 14.2 Pinning

PlanningSnapshot、ChangeSet 和 Approval 必须 pin SemanticEnvironment。

审批后不得在执行时悄悄切换 Provider 版本。

若 SemanticEnvironment 发生变化：

```text
重新验证 / 重规划 / 重新审批
```

由 policy 决定具体级别。

## 14.3 Hash

机器语义变化必须导致 content hash 变化。

纯 presentation metadata：

```text
label
description
translation
example
```

SHOULD 与 semantic content hash 分离，避免仅修改文案导致 PlanningSnapshot 失效。

---

# 15. Semantic Ingest Contract

## 15.1 目标

在 Host Native Fact 与 D5 之间定义独立、可版本化的固定数据结构。

建议：

```text
SemanticIngestContract v1
NormalizedDesignFactBatch
```

## 15.2 NormalizedDesignFact

最小建议字段：

```text
source
  host/provider
  document_id
  host_revision

native_identity
  native_id
  native_kind

identity_hints[]

classification_claims[]
property_claims[]
relationship_claims[]
placement_claims[]
geometry_refs[]

provenance
```

Claim 中的 term 可以是：

```text
ifc:*
metro:*
enterprise namespace
native namespace
```

但进入 L2 Canonical collaboration 之前必须得到可验证 canonical mapping。

## 15.3 Ingest Pipeline

```text
HostDelta
   ↓
Native Fact Extractor
   ↓
NormalizedDesignFactBatch
   ↓
Semantic Service
   ↓
Mapping / Validation / Projection
   ↓
D5 Collaboration Kernel
   ↓
Journal / DirtyMap / SemanticProjection
```

---

# 16. D5 — Collaboration Kernel

## 16.1 定位

D5 是当前设计的 canonical semantic read model / collaboration state center。

D5 不负责：

- Host native conversion knowledge；
- LLM action selection；
- Host command execution；
- 企业 Mapping Pack 逻辑；
- IFC definition authority。

## 16.2 D5 核心职责

```text
Semantic Identity
Host Bindings
External Identities
Canonical Classification
Canonical Properties
Canonical Relationships
Placement / Coordinates
Freshness
Assurance / Provenance
Journal / DirtyMap
Semantic Projection
Semantic Snapshot
Conflict / Revision state
```

---

# 17. Semantic Identity

## 17.1 SemanticIdentity

```text
SemanticIdentity
  semantic_id
```

`semantic_id` 是 DSP collaboration identity，不等于任何 Host native id。

## 17.2 HostBinding

一个 SemanticIdentity 可以有多个 HostBinding：

```text
HostBinding
  semantic_id
  provider_id
  document_id
  native_id
  native_kind
```

例如：

```text
S-WALL-001
├── AutoCAD / drawing-1 / A31
└── Revit / model-2 / 38912
```

## 17.3 ExternalIdentity

不得把 IFC GlobalId 写成 D5 Core 特殊字段。

统一使用：

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

未来外部资产号、CDE ID、其他行业标准 ID 使用同一结构。

---

# 18. Canonical Semantic Projection

## 18.1 SemanticEntity

逻辑结构：

```text
SemanticEntity
  semantic_id
  classification
  properties
  relationships
  placement
  spatial_context
  assurance
  provenance
```

示例：

```yaml
semantic_id: S-WALL-001
classification:
  term_id: ifc:IfcWall
properties:
  metro:PsetProj_WallDesign.DesignThickness:
    value: 200
    unit: mm
```

Instance 不复制 Semantic Term description。

## 18.2 SemanticProjectionRef

Snapshot 不嵌入全部 semantic state，但必须引用 exact projection：

```text
SemanticProjectionRef
  projection_id
  projection_hash
  semantic_contract_version
  normalized_fact_batch_hash
```

## 18.3 SemanticEnvironmentRef

```text
SemanticEnvironmentRef
  environment_id
  environment_hash
```

Projection + Environment 共同确定：

> 当前数据是什么，以及这份数据是按哪套语义解释出来的。

---

# 19. Freshness

## 19.1 SemanticAspect

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

`CLASSIFICATION` 必须是一等 aspect。

## 19.2 两阶段 Freshness

保留：

```text
Context Freshness
Operation Freshness
```

Context 阶段只获取任务需要的低成本上下文。

Operation 阶段在：

```text
canonical operation
target
material arguments
```

确定后执行 exact freshness barrier。

## 19.3 Freshness 与 Assurance 分离

Freshness 回答：

> 这个事实相对于 Host revision 是否仍然新鲜？

Assurance 回答：

> 这个事实是怎么得出的，可信等级是什么？

二者不可合并。

---

# 20. Semantic Assurance / Provenance

建议等级：

```text
NATIVE_ASSERTED
STANDARD_MAPPED
RULE_DERIVED
HEURISTIC
UNKNOWN
```

每个关键 claim SHOULD 能记录：

```text
producer/provider
source fact
mapping profile
rule id
semantic environment
confidence (if heuristic)
```

Canonical Operation 可声明最小 assurance：

```text
target.classification >= STANDARD_MAPPED
```

高风险 operation 不得把 `HEURISTIC` 默认当成等价可靠分类。

---

# 21. Semantic Snapshot

## 21.1 Snapshot 内容

```text
SemanticSnapshot
  snapshot_id
  kind
  project_id
  freshness_contract_id/hash
  document_ref
  base_host_revision
  coverage
  aspect_guarantees
  projection_ref
  semantic_environment_ref
  hash
```

## 21.2 ContextSnapshot

用于 D4 / LLM 上下文生成。

可以较轻，只要求 task-scoped coverage。

## 21.3 PlanningSnapshot

任何写操作必须基于 PlanningSnapshot。

PlanningSnapshot 必须绑定：

```text
exact Host revision
exact semantic projection
exact semantic environment
freshness guarantees
```

SnapshotSet 仅包含 PlanningSnapshot，并保持每 document 一个 member 的不变量。

---

# 22. D5 Read Contract

建议提供：

```text
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
SemanticProjectionPublished
```

D4/D6/D7 不得直接共享 D5 内部数据库。

---

# 23. LLM Context Compilation

## 23.1 LLM 不读取全模型

Orchestrator / Context Composer 根据 task scope 组装：

```text
D5 instance facts
+
相关 Semantic Term descriptions
+
D4 eligible Canonical Actions
```

不得把全部 IFC ontology、全部 Metro 字典和全部模型实例直接塞进上下文。

## 23.2 Description 来源

```text
ifc:IfcWall
  → IFC Provider

metro:PsetProj_WallDesign.DesignThickness
  → Metro Semantic Provider

dsp:...
  → DSP Core Provider

wall.thickness.set.v1
  → Canonical Action Catalog
```

LLM 无需知道具体 Provider 路由。

---

# 24. D6 — Parameter Binder

## 24.1 Slot Binding Classes

每个 canonical slot 必须声明来源：

```text
INTENT
CONTEXT
DEFAULT
DERIVED
PROVIDER
```

规则：

> 能确定性绑定的 slot，不交给 LLM。

## 24.2 示例

```yaml
operation: wall.thickness.set.v1

slots:
  target:
    semantic_type: SemanticId
    entity_constraint: ifc:IfcWall
    binding: CONTEXT

  thickness:
    semantic_term: metro:PsetProj_WallDesign.DesignThickness
    binding: INTENT
```

用户：

```text
把这堵墙加厚到 300mm
```

LLM 只提取：

```text
thickness = 300mm
```

D6 确定性绑定：

```text
target = ContextSnapshot.selection = S-WALL-001
```

输出：

```text
BoundOperationProposal
  canonical_operation
  arguments
  binding_evidence
  snapshot_ref
```

---

# 25. D7 — ChangeSet / Approval / ProviderBinding

## 25.1 ChangeSet

ChangeSet 表达 canonical change，而不是某 Host command。

```text
ChangeSet
  change_set_id
  planning_snapshot_set
  semantic_environment_ref
  canonical_operations[]
  expected_semantic_effects[]
  risk
  approval_state
```

## 25.2 ProviderBinding

仅在 execution boundary 才转换：

```text
SemanticId
→ HostBinding
→ Provider native id

canonical value
→ provider internal unit/value

PlanningSnapshot revision
→ Host revision guard
```

例如：

```text
S-WALL-001
→ Revit ElementId 38912

300mm
→ Revit internal feet
```

LLM 不负责这些转换。

## 25.3 Verification

执行完成后：

```text
Host read-back / HostDelta
  ↓
Semantic Ingest
  ↓
new SemanticProjection
  ↓
compare expected semantic effects
```

验证的是 canonical semantic effect，而不仅是“Host API 返回 success”。

---

# 26. 墙体加厚到 300mm — Reference Flow

初始状态：

```text
SemanticId = S-WALL-001
classification = ifc:IfcWall
Metro evidence = PsetProj_WallDesign.DesignThickness = 200mm
freshness = FRESH
assurance = STANDARD_MAPPED / RULE_DERIVED
```

流程：

```text
1. 用户
   “把这堵墙加厚到300mm”

2. D5 ContextSnapshot
   selection = S-WALL-001
   classification = ifc:IfcWall

3. Semantic Service
   IFC Provider → IfcWall definition
   Metro Provider → wall domain rules / DesignThickness requirement

4. D4
   eligible action = wall.thickness.set.v1

5. LLM
   thickness = 300mm

6. D6
   target = S-WALL-001       [CONTEXT]
   thickness = 300mm         [INTENT]

7. D5 Operation Freshness / Assurance
   CLASSIFICATION = FRESH
   PROPERTIES = FRESH
   assurance requirement satisfied

8. D7 ChangeSet
   before = 200mm
   after  = 300mm
   bind PlanningSnapshot + SemanticEnvironment

9. ProviderBinding
   Revit:
      S-WALL-001 → ElementId 38912
      300mm → Revit internal unit

   or AutoCAD:
      S-WALL-001 → Handle A31
      enterprise semantic/provider mapping → native execution plan

10. Host execution

11. HostDelta

12. D5 reconstruction
    new canonical thickness = 300mm

13. Verification
    intended semantic effect == observed semantic effect
```

---

# 27. Semantic Authority 与冲突规则

## 27.1 Namespace ownership

建议：

```text
ifc:*       → IFC Standard Provider authoritative

dsp:*       → DSP Core authoritative

metro:*     → Metro Semantic authoritative

acme:*      → Enterprise Provider authoritative
```

## 27.2 Mapping 不等于 Identity

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

## 27.3 不能覆盖外部标准

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

# 28. Description / Presentation Metadata

## 28.1 Semantic Term

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

## 28.2 Instance 不复制 description

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

## 28.3 Hash policy

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

# 29. 缓存、可用性与失败策略

## 29.1 Semantic MCP 可用性

D5 runtime 不应因为一次 `describe_term` 远程调用失败就丢失既有 canonical state。

Semantic Service SHOULD 支持：

- provider metadata cache；
- immutable version cache；
- pinned environment cache；
- offline read of already-approved definitions。

## 29.2 Fail closed

以下情况必须 fail closed：

- authoritative term 无法解析；
- Provider version 与 PlanningSnapshot 不一致；
- conflicting authoritative claims；
- operation semantic requirement 未满足；
- classification freshness 不满足；
- minimum assurance 不满足。

非关键 presentation description 不可用时 MAY 降级展示，但不得改变机器判断。

---

# 30. Policy 与安全边界

写操作必须至少经过：

```text
Canonical Operation eligibility
Semantic Freshness
Semantic Assurance
Policy decision
PlanningSnapshot
ChangeSet
Approval（按 risk/policy）
Revision guard
Idempotency
Host verification
```

LLM 不得：

- 修改 policy；
- 自行跳过 freshness；
- 自行选择 native id；
- 自行做单位换算作为最终执行依据；
- 自行降低 assurance；
- 直接生成 Host API 调用。

---

# 31. Repository Target Layout

建议目标目录：

```text
contracts/
  host/
  semantic_ingest/
  canonical_actions/

hosts/
  autocad/
    plugin/
    sidecar/
  revit/
    ...

platform/
  capability/                 # D3
  canonical_actions/          # shared action contracts
  orchestrator/               # D4 orchestration/resolution
  semantic_service/           # Semantic MCP / registry / routing
  semantic_runtime/           # D5 Collaboration Kernel
  parameter_binding/          # D6
  changeset/                  # D7

providers/
  semantics/
    ifc43/
    dsp_core/
    metro/
    enterprise/

tests/
  contracts/
  semantic_service/
  semantic_runtime/
  operation_resolution/
  parameter_binding/
  changeset/
  integration/
  conformance/
```

AutoCAD Sidecar 的 Host MCP 保留在 Host 目录，不移动到 Semantic Provider。

---

# 32. Conformance 与测试

## 32.1 Host Contract

保持：

- JSON Schema；
- Python/.NET mirror；
- golden files；
- real Host smoke test。

## 32.2 Semantic Provider Conformance

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
```

## 32.3 Metro Semantic Conformance

Metro Provider 至少测试：

- IFC4X3_ADD2 合法实体白名单；
- 禁止 IFC 名称；
- official Pset/Qto 与 `PsetProj_` 区分；
- `IFC-M / IFC-O / P-M / P-C / P-R / 禁止` 转换；
- IDS requirement；
- 墙/板/Alignment/轨道/隧道/MEP reference cases；
- 单位与字段类型；
- mapping provenance。

## 32.4 Acceptance proof

必须有一个“新增 Enterprise Mapping Provider 不修改 D5 Core”的验收测试：

```text
A-WALL-* → IfcWall
```

安装/移除 mapping pack 仅改变 Provider/config，不改变 Collaboration Kernel 源码。

---

# 33. Migration from v0.5 / current branch

## 33.1 可直接保留

当前 D5 中以下概念继续有效：

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

## 33.2 必须修改

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

### SemanticAspect

新增：

```text
CLASSIFICATION
```

### Snapshot

增加：

```text
SemanticProjectionRef
SemanticEnvironmentRef
```

### D3/D4

拆分：

```text
canonical semantic constraints
provider native constraints
```

### Canonical Action

补充：

```text
title
description
slot binding
semantic term refs
freshness/assurance requirements
```

## 33.3 新增子系统

```text
Semantic Service / Semantic MCP Server
SemanticProvider Contracts
IFC4.3 Provider
DSP Core Provider
Metro Semantic Provider
Semantic Environment
Semantic Ingest Contract
Assurance
```

---

# 34. 实施顺序

建议顺序：

```text
Phase A — Architecture Freeze
  1. 本 Spec v0.6
  2. ADR-005 Semantic Service / Provider Boundary
  3. Contract naming/version policy

Phase B — D5 Baseline Completion
  4. SemanticIdentity / HostBinding / ExternalIdentity
  5. CLASSIFICATION aspect
  6. ProjectionRef / EnvironmentRef

Phase C — Semantic Service
  7. SemanticProvider contracts
  8. Semantic Registry / Routing
  9. Semantic MCP Server
  10. environment pinning/cache

Phase D — Reference Providers
  11. DSP Core Provider
  12. IFC4.3 Provider
  13. Metro Semantic Provider

Phase E — Ingestion Proof
  14. NormalizedDesignFact contract
  15. AutoCAD native fact extractor
  16. fake enterprise A-WALL mapping provider
  17. prove A-WALL → IfcWall without D5 changes

Phase F — Action / Binding / ChangeSet
  18. Canonical Action contract upgrade
  19. D4 semantic eligibility
  20. D6 Slot Binder
  21. D7 ChangeSet / ProviderBinding / verification
```

D6/D7 不应在 Phase B–E 的语义边界未冻结前继续扩大实现。

---

# 35. Architecture Invariants

以下约束应作为自动架构测试或 code review checklist：

1. `semantic_runtime` 不 import AutoCAD/Revit/Tekla native package。
2. `semantic_runtime` 不 hardcode enterprise layer/family/category mapping。
3. `semantic_runtime` 不特殊硬编码 IFC GlobalId 字段。
4. 平台组件通过 Semantic Service contract 使用语义，不直接调用具体 Provider 实现。
5. MCP 是 protocol/transport；Provider Protocol 是 domain contract。
6. `ifc:*` canonical identity 只能由 pinned IFC Provider 权威定义。
7. Metro/Enterprise 只能扩展、映射和约束 IFC，不得重定义 IFC canonical meaning。
8. D4 LLM action space 不暴露 provider-native execution schema。
9. D6 可确定性绑定的 slot 不交给 LLM。
10. D7 写操作必须绑定 PlanningSnapshot + SemanticEnvironment。
11. Snapshot 必须能追溯 exact Host revision、semantic projection 与 provider/mapping set。
12. 高风险 operation 在 freshness / assurance 不满足时 fail closed。

---

# 36. 术语表

| 术语 | 定义 |
|---|---|
| Host | 设计软件运行环境，如 AutoCAD、Revit |
| Host Provider | 提供 Host read/write 能力的插件/Sidecar/MCP |
| Host Contract | DSP 与 Host 边界的低语义数据契约 |
| Native Fact | 从 Host 读取的原生事实 |
| NormalizedDesignFact | Host-neutral 固定结构的事实传输契约 |
| Semantic Provider | 提供 vocabulary/mapping/validation/projection 的领域实现 |
| Semantic MCP Server | DSP 统一语义服务的 MCP 协议入口 |
| IFC4.3 Provider | IFC 标准语义权威 Provider |
| Metro Semantic | IFC4.3 之上的地铁领域语义、PsetProj、IDS、映射和规则 |
| DSP Core Semantic | DSP 跨行业协同需要的自有语义 |
| SemanticEnvironment | 某一时刻被 pin 的完整 Provider/version/hash 集合 |
| SemanticIdentity | 跨 Host 的 DSP 稳定对象身份 |
| HostBinding | SemanticIdentity 到 Host native entity 的绑定 |
| ExternalIdentity | IFC GlobalId 等外部身份的 scheme/value 绑定 |
| SemanticProjection | 当前设计的 canonical semantic state |
| Freshness | semantic fact 相对于 Host revision 的新鲜状态 |
| Assurance | semantic claim 的来源与可信等级 |
| Canonical Action | Host-independent 的用户/Agent 动作语义 |
| Slot Binding | Canonical Action 参数的来源分类与绑定过程 |
| ChangeSet | 被规划/审批的 canonical change 集合 |
| ProviderBinding | Canonical target/argument 到 Host provider-native 输入的确定性转换 |

---

# 37. v0.6 冻结条件

v0.6 进入 `Accepted` 前，至少完成：

1. Host Plane / Semantic Plane / Action Plane / Collaboration Kernel 的职责无重叠；
2. Semantic MCP Server 与 SemanticProvider Protocol 的边界通过 ADR 冻结；
3. IFC4.3 与 Metro Semantic 权威关系冻结；
4. `SemanticIdentity : HostBinding = 1:N` 冻结；
5. `ExternalIdentity` 替代 `ifc_global_id` 特例；
6. `CLASSIFICATION` 进入 D5 SemanticAspect；
7. SemanticSnapshot 绑定 ProjectionRef + EnvironmentRef；
8. Canonical Action description/slot semantic metadata 模型冻结；
9. D6 binding classes 冻结；
10. 用“墙体加厚到 300mm”演练通过 Revit 和 AutoCAD 两种 Provider 路径；
11. 用 `A-WALL → IfcWall` 证明企业 Mapping Provider 可插拔且 D5 Core 不改代码；
12. Metro reference case 通过 Schema / PsetProj / IDS / mapping / provenance 全链路验证。

---

# 38. 一句话系统边界

```text
Host MCP        = 怎么做
Semantic MCP    = 是什么 / 规则是什么
D5              = 当前设计是什么
Canonical Action= 允许表达什么动作
D6              = 这次动作的参数具体是什么
D7              = 准备执行、审批、绑定和验证什么
LLM             = 在受约束空间中理解意图，不拥有系统真相和执行权
```
