# Architecture Modernization Phase II — Canonical V2 Convergence & Compatibility Retirement

- 状态：DESIGN FROZEN FOR REVIEW
- 日期：2026-09-19
- 基线：`main@73a48b0576306e6f915cccf01fa9bb80cf23d6e5`
- 设计分支：`architecture/phase-ii-canonical-v2-convergence`
- 上游约束：`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`、ADR-008、ADR-009、ADR-010
- 主要输入：`docs/superpowers/modernization/modernization-ledger.md` 中 MOD-016、`docs/superpowers/modernization/architecture-modernization-review-input.md`、PR #55 review 记录

## 1. 背景与问题定义

Technology Modernization 已完成，M5 明确记录 `NO_CUTOVER`，M6 明确记录 `NO_RETIREMENTS`。因此 Python 3.11 与 root .NET 8 SDK policy 继续是 canonical baseline；Python 3.14 与 Host-neutral .NET 10 只代表 compatibility evidence，不构成 canonical ownership transfer。

同时，MOD-016 被明确留给 Architecture Modernization Review：planning、binding、reconciliation 等主链路中仍存在 V1/V2 compatibility surface。当前仓库也确实存在并行公共 API，例如：

- `design_execution_planning` 同时导出 `ExecutionPlan` / `ExecutionPlanV2`、`ExecutionPlanningRequest` / `ExecutionPlanningRequestV2`；
- `design_provider_binding` 同时导出 `ProviderBindingSet` / `ProviderBindingSetV2`、`ProviderExecutionSnapshot` / `ProviderExecutionSnapshotV2`；
- `design_execution_reconciliation` 同时导出 V1/V2 reconciliation service、Saga definition/state/store/builder/controller 契约；
- `materialization_planning` 已形成 Phase I 的 provider-neutral materialization plan 契约，并成为 V2 路径的重要输入边界。

这些兼容路径横跨未来真实工作流的必经主干：

```text
intent / workflow
    -> planning
    -> provider binding
    -> gateway / execution planning
    -> execution saga
    -> reconciliation / convergence
```

如果在 canonical path 未冻结前继续叠加 HITL、真实 workflow 和 MCP 前门，新能力会成为新的双路径消费者，或把兼容判断焊进产品代码，导致“先实现一次、以后再迁移一次”的双重成本。

因此 Phase II 的核心问题不是“如何删除 V1”，而是：

> 哪些 V2 contract / semantics 已经具备成为唯一 canonical path 的条件；哪些 compatibility bridge 仍然承担真实兼容职责；哪些可以安全 cut over / retire？

## 2. 设计目标

Phase II 的目标是建立一套可证明、可审计、可退出的 canonical convergence 机制，而不是追求 V1 删除数量。

完成后必须做到：

1. 对 planning / binding / execution planning / reconciliation / saga 的 V1/V2 compatibility surface 完成消费者普查。
2. 每个 compatibility item 都有唯一 owner、已知 consumers、事实依据和明确 disposition。
3. 对 `CUTOVER_READY` / `RETIREABLE` 项建立 characterize -> census -> parity -> cutover -> observe -> retire 的证据链。
4. 对 `KEEP` / `ADAPTER_ONLY` / `BLOCKED` 项明确为什么不能退，并冻结边界，禁止后续新业务代码继续扩大旧路径依赖。
5. 将 PR #55 遗留债务映射到明确轨道，不允许继续成为无 owner 的“future work”。
6. 在本 phase 的 exit criteria 中冻结后续 Capability Phase 路线，避免 architecture cleanup 无限延长。

## 3. 非目标

Phase II 明确不做以下事情：

- 不把所有名字含 `V1` 的代码视为待删代码；
- 不因为 `V2` 命名更新就自动认定它是 canonical；
- 不改变 ADR-008/009/010 已冻结的 authoritative ownership；
- 不把 Workflow checkpoint 变成 ChangeSet、Approval、Saga、Host truth 的第二 source of truth；
- 不做 Python 3.14 canonical cutover；
- 不做 repository-wide .NET 10 canonical cutover；
- 不扩展 AutoCAD/Revit Host support matrix；
- 不在本 phase 实现完整 HITL 产品闭环、真实用户 workflow 或 MCP/Agent 前门；
- 不为“看起来更整洁”而删除仍有真实 Host / public contract / runtime consumer 的 bridge。

## 4. 备选方案与决策

### 方案 A：直接 retirement-first

做法：从 `_v2` / V1/V2 类型名入手，逐步把调用改到 V2，再删除旧 API。

优点：短期代码量下降快。

缺点：无法证明 consumer completeness；很容易把真实 Host compatibility、测试 fixture、外部 public contract 或 recovery path 当成 dead code。对本仓库的 T3/T4 风险不可接受。

结论：拒绝。

### 方案 B：inventory-first canonical convergence（采用）

做法：先冻结 consumer/owner facts，再按 disposition 逐项决定 cutover 与 retirement。

优点：复用 Technology Modernization 已验证的 evidence-driven 方法；可以允许 `KEEP` / `ADAPTER_ONLY` 成为合法终态；不会为了“必须删东西”而制造架构回归。

代价：前期有一段主要产出是 inventory / characterization，而非功能代码。

结论：采用。

### 方案 C：Capability-first，等产品能力完成后再统一

做法：先做 HITL、真实 workflow、MCP 前门，后续再收敛 V1/V2。

优点：短期可见能力更快。

缺点：新能力会成为新的兼容路径 consumer；以后需要再次迁移，扩大 retirement surface；并且并不能产生“V1 还有谁在用”的关键证据。

结论：拒绝作为当前顺序；保留为 Phase II 的声明式继任者。

## 5. Inventory 模型

Phase II 的第一核心产物不是代码，而是一张完整 compatibility disposition ledger。每一个 item 至少记录：

```text
item_id
area
v1_contract_or_path
v2_contract_or_path
bridge_or_adapter
producer
consumers
public_exports
runtime_callers
test_callers
host_dependency
authoritative_owner
persistence_owner
semantic_delta
parity_evidence
real_host_evidence
cutover_blocker
disposition
retirement_preconditions
rollback
```

### 5.1 Inventory scope

必须至少覆盖：

- execution planning
- materialization planning 与 execution planning 的衔接
- provider binding
- gateway / authorization consumers
- execution coordination consumers
- execution reconciliation
- execution Saga V1/V2 contracts、state、store、controller
- convergence / compensation 相关 consumers
- orchestrator 对上述模块的调用与 stable refs
- tests / runbooks / workflow lanes 对 V1/V2 的显式依赖
- AutoCAD / Revit real-host acceptance path 中存在的版本依赖

### 5.2 Consumer 口径

consumer 不只包含 production import。以下全部算 consumer：

- public package export / re-export；
- runtime import / direct call；
- adapter input/output type；
- persisted serialized state 或 hash identity；
- schema / proto / contract binding；
- test fixture 若它冻结 canonical behavior；
- CI / runbook / real-Host gate 若它证明 support claim；
- external Host/plugin compatibility boundary。

仅有“grep 看不到调用”不足以判定 RETIREABLE。

## 6. Disposition 状态机

每个 compatibility item 必须且只能进入以下一个终态：

### `KEEP`

旧路径仍是合法且必要的长期 contract / Host boundary。Phase II 不退役，并补 architecture guard 防止误删。

### `ADAPTER_ONLY`

旧路径可以存在，但只能停留在显式边界 adapter，不允许新的 domain/business code 直接依赖。目标是把兼容成本压缩到一个边界。

### `CUTOVER_READY`

V2 已完成 characterization + consumer census + parity proof，但仍需执行正式 cutover 和 merged-main observation。

### `BLOCKED`

已知希望收敛，但存在明确 blocker，例如真实 Host、public contract、migration、durable-state compatibility 或缺失 parity evidence。必须记录解除条件和 owner。

### `RETIREABLE`

所有 consumer 已 cut over，merged-main observation 已完成，rollback 明确，且不存在 public/Host/persistence compatibility obligation。只有这一状态允许实际删除旧实现。

`RETIREABLE` 是 retirement 的授权条件，不是 inventory 人员的主观判断标签。

## 7. Cutover protocol

所有会改变 canonical ownership 的项目必须遵循：

```text
characterize current V1/V2 behavior
    -> census all consumers
    -> prove semantic / identity / persistence parity
    -> freeze cutover candidate
    -> migrate consumers
    -> exact-head verification
    -> merge to main
    -> merged-main observation
    -> mark RETIREABLE
    -> remove old path
    -> final regression / Host evidence where applicable
```

特别禁止：

```text
rename V2 -> canonical
remove V1
fix failures afterward
```

对于涉及 Host-visible semantics、native runtime、materialization identity、Saga transitions 或 recovery 的项目，real-Host / PostgreSQL / crash-recovery evidence 必须按原 owner 的既有 gate 继续执行。

## 8. PR #55 债务映射

PR #55 最终 review 明确记录 4 项非阻塞债务。Phase II 为其建立如下归属：

### 8.1 Legacy lane package declaration

轨道：Engineering Hygiene / CI topology。

Phase II 只登记 consumer 事实，不把它当 canonical convergence 的核心产物。若 lane 声明影响 consumer census 的真实性，则先修声明；否则保持独立 hygiene item。

### 8.2 HITL arbitrary payload ownership

轨道：Capability Phase hard prerequisite。

Phase II 必须冻结 ownership rule，但不实现完整 HITL UI/flow：

- checkpoint 只允许 workflow-local navigation state + stable refs；
- ChangeSet / Approval / Saga / Host / Semantic truth 继续由原 authoritative owner 持有；
- 任意 HITL payload 若包含领域对象，必须拆成 stable ref + workflow-local presentation metadata，或明确交给独立 authoritative store；
- 不允许以 LangGraph checkpoint convenience 为理由复制 authoritative domain object graph。

Phase II exit 前必须形成可被后续 HITL implementation plan 直接引用的 payload ownership contract。

### 8.3 DIVERGED compensation executor ownership

轨道：本 Phase reconciliation/convergence 主线。

必须区分：

- 谁决定 compensation 是否需要；
- 谁构造 compensation proposal；
- 谁授权 compensation execution；
- 谁真正 dispatch / execute Host effect；
- 谁记录 compensation durable truth；
- Workflow Orchestrator 只做协调还是拥有业务决策。

默认约束：不得让 LangGraph checkpoint 成为 compensation truth；不得让 delivery success 等同 compensation business success。最终 owner 需通过本 phase 的 architecture evidence 冻结。

### 8.4 Checkpoint retention / GC

轨道：Operations。

Phase II 必须定义 ownership 与 retention contract，但不要求与 V1/V2 retirement 同步实现所有运维自动化。至少冻结：

- active / paused workflow 不得被 GC；
- completed / terminal workflow 的最小 retention 语义；
- checkpoint deletion 不得删除外部 authoritative owner state；
- GC 必须属于 Workflow Orchestrator owner 的 persistence 运维边界；
- observability / audit 所需的最小保留信息。

实现可以进入独立 ops task，但必须有 owner、precondition 和 acceptance evidence。

## 9. Phase structure

### Stage A — Factual Inventory

只读地建立 V1/V2 compatibility ledger。不得在 inventory 阶段顺手迁移或删除路径。

硬出口：所有发现项都已有 consumer/owner/disposition，不允许存在 `UNKNOWN` owner 或无期限 `TBD`。

### Stage B — Canonical Boundary Freeze

基于 inventory 决定：

- 哪些 V2 是 canonical candidate；
- 哪些 V1 必须长期 KEEP；
- 哪些兼容只能 ADAPTER_ONLY；
- 哪些项 CUTOVER_READY / BLOCKED。

如结论会改变 public contract、authoritative ownership 或 Saga semantics，应形成新的 ADR；否则用 Phase II spec/ledger + architecture tests 冻结。

### Stage C — Parity & Cutover

只处理 `CUTOVER_READY` 项。每个 item 独立 TDD / commit / exact-head verification，禁止大爆炸式统一迁移。

### Stage D — Observation & Retirement

cutover 合并 main 后完成 required observation；满足条件才标记 `RETIREABLE` 并删除旧路径。

### Stage E — Closeout & Capability Handoff

完成 disposition ledger，确认四项 PR #55 债务各有 owner / next action，并冻结继任 Capability Phase。

## 10. Inventory 硬时限与硬出口

为避免 architecture archaeology 无限膨胀，Stage A 不以“把所有历史读完”为完成条件，而以产物完整度为条件。

Stage A 结束必须满足：

1. scope 内每一个 V1/V2 surface 都有 ledger row；
2. 每 row 至少有 producer、consumer、owner、persistence/Host 影响、disposition；
3. 不存在 `UNKNOWN` / `TBD` disposition；不确定项必须明确为 `BLOCKED` 并记录缺失证据；
4. inventory 阶段不因“顺便能删”而执行 retirement；
5. 产出 reviewable summary：按 KEEP / ADAPTER_ONLY / CUTOVER_READY / BLOCKED / RETIREABLE 聚合。

因此“多数项目最终是 KEEP / ADAPTER_ONLY”仍然是成功结果。

## 11. 测试与证据原则

Phase II 延续当前 exact-head discipline。

### Inventory / boundary 阶段

- architecture tests 冻结 ledger schema、public export census、禁止新增未经登记的 V1 consumer；
- characterization tests 记录当前 V1/V2 semantics，不因目标是退休 V1 就改写旧行为；
- repository regression 必须保持 canonical green。

### Cutover 阶段

按 item 风险选择：

- focused unit / contract tests；
- Python 3.11 canonical + Python 3.14 compatibility；
- Revit Core / Host-neutral .NET 10；
- PostgreSQL durable persistence / restart / crash recovery；
- gRPC transport conformance；
- real AutoCAD/Revit acceptance（仅 Host-visible T3/T4 item）；
- Ruff new diagnostics = 0。

### Retirement 阶段

必须证明：

- old path 无剩余合法 consumer；
- public exports 已按批准方案处理；
- persisted state / migration compatibility 已完成；
- merged-main observation 通过；
- rollback strategy 在删除前已经冻结。

## 12. Phase II exit criteria

Phase II 只有同时满足以下条件才 CLOSED：

1. compatibility disposition ledger 完整并 review 通过；
2. 所有 scope item 都是 `KEEP / ADAPTER_ONLY / CUTOVER_READY / BLOCKED / RETIREABLE` 中之一，无未知项；
3. 已批准的 cutover/retirement item 完成其所需 exact-head + merged-main evidence；
4. `KEEP` / `ADAPTER_ONLY` / `BLOCKED` 项有 architecture guard，防止无意识扩大旧路径；
5. HITL payload ownership contract 已冻结；
6. DIVERGED compensation executor ownership 已冻结，或被明确 BLOCKED 到独立 ADR 且 owner/解除条件已记录；
7. checkpoint GC/retention 已有 ops owner、contract 和后续 acceptance 路径；
8. legacy lane package declaration 已归入 hygiene owner，不再作为无主债务；
9. Capability Phase 继任路线已冻结；
10. main 保持可回归，且没有为了“完成 Phase II”强制删除必要 compatibility bridge。

## 13. 声明式继任者：Capability Phase

Phase II 完成后，下一阶段默认进入 Capability Phase，而不是继续无限 architecture cleanup。

冻结的能力顺序为：

```text
HITL ownership + pause/resume closure
    -> real end-to-end user workflow
    -> orchestrator drives semantic -> plan -> approve -> execute -> reconcile
    -> MCP / Agent front door
    -> real AutoCAD/Revit acceptance for supported capability
```

该 Capability Phase 的详细 design/plan 仍需独立 Superpowers brainstorming/spec/plan 流程，但 Phase II 不得以发现一般性技术债为由无限推迟它。只有新的 merge-blocking architecture invariant / safety / data-integrity blocker 才能重新排序。

## 14. 成功定义

Phase II 的成功不是“删除了多少行 V1”。

成功定义是：

> DSP 对 planning -> binding -> execution -> reconciliation 主干中的每一条 compatibility path 都知道它为什么存在、谁在使用、谁拥有、何时能切、何时不能切，并且未来的新能力有一条明确、稳定、可恢复的 canonical 主干可依赖。

如果最终大量 bridge 被证明为承重墙并进入 `KEEP` / `ADAPTER_ONLY`，只要事实、边界和责任被冻结，本 phase 仍然成功。