# Enterprise Collaborative Design Agent

企业级协同设计智能体：以 provider-neutral 的 canonical semantic/change pipeline 连接 Agent、平台治理与真实设计宿主，并通过独立 read-back、reconciliation 与 convergence 证明执行结果。

## 当前状态

- **Latest completed capability phase:** Revit wall-thickness product vertical
- **Current engineering activity:** MCP / Agent front door — implementation plan review
- **Latest product acceptance:** selected Revit Wall thickness → 300 mm，真实 Revit happy path GREEN；Front Door Written Design Review 已通过，当前仅评审 Implementation Plan，尚未进入产品实现
- 当前主规格：[`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`](docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md)
- 当前 Front Door 设计：[`docs/superpowers/specs/2026-09-28-mcp-agent-front-door-design.md`](docs/superpowers/specs/2026-09-28-mcp-agent-front-door-design.md)
- 当前 Front Door 实施计划：[`docs/superpowers/plans/2026-09-28-mcp-agent-front-door.md`](docs/superpowers/plans/2026-09-28-mcp-agent-front-door.md)
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
- Host commit outcome unknown、Windows Named Pipe I/O 与 commit-revision mismatch 的 fail-closed / recovery-required 处理，禁止把未知提交状态误判为可安全重试。

Revit wall-thickness product vertical 的真实 Host acceptance 已证明 revision 按一次提交推进、独立 READ 在 exact committed revision 重新测得 300 mm、Saga 与 Product 均达到 `SUCCEEDED`。真实验收仍按受控 Windows/Revit 环境执行；GitHub-hosted CI 只运行 offline matrix 并验证 live test 可 collection/明确 skip。

Host-specific API 继续被限制在各 Host 的 native/plugin 边界内；平台层使用 provider-neutral contracts 与 evidence，不把 AutoCAD/Revit 原生类型扩散进 canonical runtime。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`](docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md) | 当前系统级 contract authority |
| [`docs/superpowers/specs/2026-09-28-mcp-agent-front-door-design.md`](docs/superpowers/specs/2026-09-28-mcp-agent-front-door-design.md) | MCP / Agent Front Door 已通过 Written Design Review 的设计基线 |
| [`docs/superpowers/plans/2026-09-28-mcp-agent-front-door.md`](docs/superpowers/plans/2026-09-28-mcp-agent-front-door.md) | 当前待评审 Implementation Plan；尚不授权产品实现 |
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

`Repository regression` CI 是当前 repository-wide offline truth；`Revit wall thickness product vertical` CI 是首个产品 vertical 的 focused offline truth。历史 Step workflows 只保留各自 focused/domain/architecture guards。

真实 Revit 产品验收按 [`docs/runbooks/revit-wall-thickness-product-vertical.md`](docs/runbooks/revit-wall-thickness-product-vertical.md) 显式运行，不能用 GitHub-hosted offline PASS 代替。Revit wall-thickness product vertical 已完成 capability closure；MCP / Agent Front Door 当前仍停在 Implementation Plan review，尚无新增 front-door implementation/live acceptance 证据。

## 目录概览

- `contracts/` — provider-neutral contracts 与多语言镜像。
- `platform/` — semantic runtime、planning、authorization、reconciliation、convergence、product runtime 等平台能力。
- `hosts/autocad/` — AutoCAD plugin / sidecar / native integration。
- `hosts/revit/` — Revit plugin / sidecar / native integration。
- `providers/` — semantic / materialization provider 实现。
- `tests/` — architecture、contract、integration、offline/live-host 测试。
- `docs/` — 主规格、ADR、runbook、设计与实施历史。