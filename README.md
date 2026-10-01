# Enterprise Collaborative Design Agent

企业级协同设计智能体：以 provider-neutral 的 canonical semantic/change pipeline 连接 Agent、平台治理与真实设计宿主，并通过独立 read-back、reconciliation 与 convergence 证明执行结果。

## 当前状态

- **Latest completed capability phase:** MCP / Agent front door
- **Current engineering activity:** MCP / Agent front door — COMPLETED
- **Next capability phase:** NOT YET DEFINED / NOT YET STARTED
- **Latest product acceptance:** MCP / Agent front door controlled live GREEN；真实模型 → real MCP → explicit human HITL → configured policy → Gateway/Saga → real Revit → independent READ/reconciliation 已在实现 HEAD `c67c7d7475f79218b57f4322e001f85b4e6feee9` 完成，PR #83 合并后 `main@dd3ab785cfabf0d69068d6004a579d5d946b23b5` 的 20 条 fresh push workflows 全部 GREEN
- 当前主规格：[`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`](docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md)
- 已完成 Front Door 设计：[`docs/superpowers/specs/2026-09-28-mcp-agent-front-door-design.md`](docs/superpowers/specs/2026-09-28-mcp-agent-front-door-design.md)
- 已完成 Front Door 实施计划：[`docs/superpowers/plans/2026-09-28-mcp-agent-front-door.md`](docs/superpowers/plans/2026-09-28-mcp-agent-front-door.md)
- 已完成 Revit 产品 vertical 设计：[`docs/superpowers/specs/2026-09-25-revit-wall-thickness-product-vertical-design.md`](docs/superpowers/specs/2026-09-25-revit-wall-thickness-product-vertical-design.md)
- 已完成 Revit 产品 vertical 实施计划：[`docs/superpowers/plans/2026-09-25-revit-wall-thickness-product-vertical.md`](docs/superpowers/plans/2026-09-25-revit-wall-thickness-product-vertical.md)
- 已完成 Technology Modernization Design：[`docs/superpowers/specs/2026-09-13-dsp-modernization-design.md`](docs/superpowers/specs/2026-09-13-dsp-modernization-design.md)
- v0.5 已由 v0.6 取代，保留为历史规格：[`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.5.md`](docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.5.md)

## 系统边界

```text
Agent / semantic / canonical change
        ↓
approval scope / immutable ChangeSet
        ↓
materialization topology / planning
        ↓
execution planning / provider binding / authorization
        ↓
AutoCAD + Revit Hosts
        ↓
ActualDelta / independent read-back / reconciliation / convergence
```

当前已证明的能力包括：

- canonical semantic/change pipeline；
- approval scope 与 immutable ChangeSet；
- materialization topology / planning；
- execution planning 与 provider binding；
- gateway authorization；
- execution reconciliation；
- cross-host coordination / convergence；
- deterministic partial commit；
- 真实 AutoCAD + Revit acceptance；
- durable ProductTask request owner 与 explicit task lineage；
- Revit 当前选择墙体厚度修改为 300 mm 的完整产品 vertical：request → semantic context → canonical operation → approval → planning/binding/admission → Saga → 真实 Revit mutation → 独立 post-commit READ → Step33 verification → convergence → product projection；
- MCP / Agent Front Door：durable client correlation 与 immutable request freeze、exact SessionBinding、真实 loopback MCP submit/get/resume、明确 human operation-proposal decision、configured-policy admission/default deny、Gateway/Saga、真实 Revit mutation、独立 READ/reconciliation/convergence，以及 Host 不可用时的 durable exact task query；
- 同一 ProductTask 首次 workflow start 由 PostgreSQL durable row lock 串行化；同一 exact-session composition 下的并发 submit 也只能进入一个有效 `workflow.start()` lineage；
- Host commit outcome unknown、Windows Named Pipe I/O 与 commit-revision mismatch 的 fail-closed / recovery-required 处理，禁止把未知提交状态误判为可安全重试。

Revit wall-thickness product vertical 的真实 Host acceptance 已证明 revision 按一次提交推进、独立 READ 在 exact committed revision 重新测得 300 mm、Saga 与 Product 均达到 `SUCCEEDED`。MCP / Agent Front Door controlled live 进一步证明真实自然语言模型调用、真实 MCP、显式 human decision、configured policy deny/allow、Gateway/Saga 与真实 Revit mutation 可以在同一产品路径闭环；negative case 保持 200 mm / revision `0 → 0`，positive case 达到 300 mm / revision `0 → 1`，并由独立 READ、Revit UI、verification 与 convergence 共同确认。真实验收仍按受控 Windows/Revit 环境执行；GitHub-hosted CI 只运行 offline matrix 并验证 live test 可 collection/明确 skip。

Host-specific API 继续被限制在各 Host 的 native/plugin 边界内；平台层使用 provider-neutral contracts 与 evidence，不把 AutoCAD/Revit 原生类型扩散进 canonical runtime。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`](docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md) | 当前系统级 contract authority |
| [`docs/superpowers/specs/2026-09-28-mcp-agent-front-door-design.md`](docs/superpowers/specs/2026-09-28-mcp-agent-front-door-design.md) | 已完成的 MCP / Agent Front Door 设计基线与历史工程记录 |
| [`docs/superpowers/plans/2026-09-28-mcp-agent-front-door.md`](docs/superpowers/plans/2026-09-28-mcp-agent-front-door.md) | 已完成的 MCP / Agent Front Door implementation / closeout gate |
| [`docs/runbooks/mcp-agent-front-door.md`](docs/runbooks/mcp-agent-front-door.md) | MCP / Agent Front Door controlled live acceptance |
| [`docs/superpowers/specs/2026-09-25-revit-wall-thickness-product-vertical-design.md`](docs/superpowers/specs/2026-09-25-revit-wall-thickness-product-vertical-design.md) | 已完成的首个真实 Revit 产品 vertical 设计边界 |
| [`docs/superpowers/plans/2026-09-25-revit-wall-thickness-product-vertical.md`](docs/superpowers/plans/2026-09-25-revit-wall-thickness-product-vertical.md) | 已完成的产品 vertical implementation / closeout gate |
| [`docs/runbooks/revit-wall-thickness-product-vertical.md`](docs/runbooks/revit-wall-thickness-product-vertical.md) | 真实 Revit 产品 vertical live acceptance |
| [`docs/superpowers/specs/2026-09-13-dsp-modernization-design.md`](docs/superpowers/specs/2026-09-13-dsp-modernization-design.md) | 已完成 Technology Modernization Design / evidence record |
| [`docs/superpowers/modernization/architecture-modernization-review-input.md`](docs/superpowers/modernization/architecture-modernization-review-input.md) | Technology Modernization 的 evidence-only 架构评审输入，不授权实现 |
| [`docs/superpowers/README.md`](docs/superpowers/README.md) | Design Spec / Implementation Plan 生命周期与历史导航 |
| [`docs/runbooks/phase-i-real-cross-host-wall-thickness.md`](docs/runbooks/phase-i-real-cross-host-wall-thickness.md) | Phase I 真实 AutoCAD + Revit 双 Host 验收 |
| [`docs/runbooks/autocad-grpc-smoke.md`](docs/runbooks/autocad-grpc-smoke.md) | AutoCAD gRPC rollout / real-host gate |
| [`docs/adr/`](docs/adr/) | 架构决策记录 |

历史 Design Spec / Implementation Plan 保留用于设计演进和审计，不应被当作当前项目状态页；当前 lifecycle 以 `docs/superpowers/README.md` 为入口。

## 当前验证入口

从仓库根目录运行：

```bash
python -m pytest --import-mode=importlib -q
python -m pytest -q
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

`Repository regression` CI 是当前 repository-wide offline truth；`Product Front Door verification` 是 MCP / Agent Front Door 的 focused PostgreSQL/MCP/authority truth；`Revit wall thickness product vertical` CI 保留产品 vertical 的 focused offline truth。历史 Step workflows 继续保留各自 focused/domain/architecture guards。

MCP / Agent Front Door implementation 已通过 PR #83 合并到 `main@dd3ab785cfabf0d69068d6004a579d5d946b23b5`，该 merge SHA 的 20 条 fresh push workflows 全部成功；最终 controlled live 绑定实现 HEAD `c67c7d7475f79218b57f4322e001f85b4e6feee9` 并通过 negative + positive 两组真实 Windows/Revit 验收。Front Door capability 已满足 implementation merge 与 merged-main observation 的 lifecycle closeout 前提；successor 尚未定义，也尚未开始，后续工作必须重新经过独立 Design Spec / Implementation Plan gate。

## 目录概览

- `contracts/` — provider-neutral contracts 与多语言镜像。
- `platform/` — semantic runtime、planning、authorization、reconciliation、convergence、product runtime 等平台能力。
- `hosts/autocad/` — AutoCAD plugin / sidecar / native integration。
- `hosts/revit/` — Revit plugin / sidecar / native integration。
- `providers/` — semantic / materialization provider 实现。
- `tests/` — architecture、contract、integration、offline/live-host 测试。
- `docs/` — 主规格、ADR、runbook、设计与实施历史。