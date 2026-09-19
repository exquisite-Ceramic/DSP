# Capability Phase Handoff

Architecture Modernization Phase II 在此只冻结 successor 顺序、owner 约束与 entry discipline；本文不是 Capability Phase 的详细 Design Spec 或 Implementation Plan，也不直接授权 production capability implementation、support-matrix 扩张或 legacy retirement。

```capability-phase-handoff
successor=Capability Phase
ordinary_hygiene_blocks_start=NO
non_blocking_debt_blocks_start=NO
hard_prerequisite_policy=EXPLICIT_ONLY
```

## Frozen successor order

1. HITL pause/resume
2. real E2E workflow
3. semantic -> plan -> approve -> execute -> reconcile
4. MCP/Agent front door
5. real AutoCAD/Revit acceptance

## Entry discipline

- HITL pause/resume 必须遵守 `2026-09-19-hitl-payload-ownership-contract.md`：checkpoint 只拥有 workflow-local navigation state、stable refs 与 presentation metadata，领域 authoritative truth 继续由原 owner 持有。
- 当前合法 `BLOCKED` convergence rows 是已知 architecture constraints，不自动构成 Capability Phase 的全局启动 blocker。某个 capability step 若真实依赖其中一项，必须在该 step 的独立 design/plan 中显式声明 owner、release evidence 与 gate。
- `legacy_lane_package_declaration` 属 Engineering Hygiene；普通 hygiene 与其它 non-blocking debt 不得继续无限推迟 Capability Phase。
- CV2-008 的 DIVERGED compensation executor 继续 `BLOCKED`。任何需要自动 compensation execution 的 capability 必须显式以 V2 executor、authorization、Host dispatch、durable Saga/recovery 与相应 Host evidence 为 hard prerequisite；不得把 `DIVERGED` 或 delivery success 当成 authorization/business success。
- checkpoint retention/GC 属 Workflow Orchestrator persistence ops；除非某个 capability step 明确依赖 retention acceptance，否则它不是全局启动 blocker。
- 只有显式 merge-blocking architecture invariant、safety 或 data-integrity prerequisite 才能阻塞或重新排序 successor；发现一般性技术债本身不构成理由。

## Next design gate

Capability Phase 的详细范围、acceptance 与实现任务仍必须经过独立 Superpowers brainstorming → Design Spec → Implementation Plan 流程。Phase II handoff 只提供冻结的顺序与 architecture ownership constraints，不替代后续设计审批。
