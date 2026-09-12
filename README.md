# Enterprise Collaborative Design Agent

企业级协同设计智能体：以 provider-neutral 的 canonical semantic/change pipeline 连接 Agent、平台治理与真实设计宿主，并通过独立 read-back、reconciliation 与 convergence 证明执行结果。

## 当前状态

- **Latest completed capability phase:** Phase I
- **Current engineering activity:** Engineering Hygiene / Stabilization
- **Next capability phase:** NOT YET DEFINED
- 当前主规格：[`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`](docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md)
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
ActualDelta / reconciliation / convergence
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
- 真实 AutoCAD + Revit acceptance。

Host-specific API 继续被限制在各 Host 的 native/plugin 边界内；平台层使用 provider-neutral contracts 与 evidence，不把 AutoCAD/Revit 原生类型扩散进 canonical runtime。

## 文档入口

| 文档 | 用途 |
| --- | --- |
| [`docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`](docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md) | 当前系统级 contract authority |
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

`Repository regression` CI 是当前 repository-wide offline truth；历史 Step workflows 只保留各自 focused/domain/architecture guards。

真实 Host 验收需要受支持的 AutoCAD / Revit 环境，按对应 runbook 显式运行，不能用 GitHub-hosted offline PASS 代替。

## 目录概览

- `contracts/` — provider-neutral contracts 与多语言镜像。
- `platform/` — semantic runtime、planning、authorization、reconciliation、convergence 等平台能力。
- `hosts/autocad/` — AutoCAD plugin / sidecar / native integration。
- `hosts/revit/` — Revit plugin / sidecar / native integration。
- `providers/` — semantic / materialization provider 实现。
- `tests/` — architecture、contract、integration、offline/live-host 测试。
- `docs/` — 主规格、ADR、runbook、设计与实施历史。
