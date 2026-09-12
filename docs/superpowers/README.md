# Engineering Design & Plan Lifecycle Index

本索引是 `docs/superpowers/specs/` 与 `docs/superpowers/plans/` 的生命周期导航。历史 Design Spec / Implementation Plan 的正文保持冻结；这里的状态只描述工程阶段生命周期，不表示某份历史文档仍拥有高于当前主规格的 contract authority。

## 当前仓库状态

- Phase I — latest completed capability phase
- Engineering Hygiene / Stabilization — current engineering activity
- Next capability phase — NOT YET DEFINED

## 主规格 authority

| Document | Authority |
| --- | --- |
| [`Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`](../spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md) | CURRENT |
| [`Enterprise_Collaborative_Design_Agent_Spec_v0.5.md`](../spec/Enterprise_Collaborative_Design_Agent_Spec_v0.5.md) | SUPERSEDED |

生命周期状态：

- `CURRENT`：当前正在执行或维护的工程阶段 artifact。
- `COMPLETED`：该阶段已经实施完成；文档作为历史工程记录保留。
- `SUPERSEDED`：已被更高版本 authority 取代，但仍保留审计历史。
- `ABANDONED`：明确停止且未完成的工程方向；当前索引没有此类 artifact。

## Design Specs

| Design Spec | Lifecycle |
| --- | --- |
| [`2026-08-27-grpc-loopback-transport-design.md`](specs/2026-08-27-grpc-loopback-transport-design.md) | COMPLETED |
| [`2026-08-28-dsp-core-semantic-provider-design.md`](specs/2026-08-28-dsp-core-semantic-provider-design.md) | COMPLETED |
| [`2026-08-28-ifc43-semantic-provider-design.md`](specs/2026-08-28-ifc43-semantic-provider-design.md) | COMPLETED |
| [`2026-08-28-metro-semantic-provider-design.md`](specs/2026-08-28-metro-semantic-provider-design.md) | COMPLETED |
| [`2026-08-28-normalized-design-fact-contract-design.md`](specs/2026-08-28-normalized-design-fact-contract-design.md) | COMPLETED |
| [`2026-08-28-semantic-mcp-adapter-design.md`](specs/2026-08-28-semantic-mcp-adapter-design.md) | COMPLETED |
| [`2026-08-28-semantic-service-core-design.md`](specs/2026-08-28-semantic-service-core-design.md) | COMPLETED |
| [`2026-08-29-autocad-native-fact-extractor-design.md`](specs/2026-08-29-autocad-native-fact-extractor-design.md) | COMPLETED |
| [`2026-08-29-enterprise-a-wall-mapping-provider-design.md`](specs/2026-08-29-enterprise-a-wall-mapping-provider-design.md) | COMPLETED |
| [`2026-08-29-step21-d5-canonical-projection-proof-design.md`](specs/2026-08-29-step21-d5-canonical-projection-proof-design.md) | COMPLETED |
| [`2026-08-29-step22-task-scoped-progressive-semantics-design.md`](specs/2026-08-29-step22-task-scoped-progressive-semantics-design.md) | COMPLETED |
| [`2026-08-29-step23-canonical-action-contract-design.md`](specs/2026-08-29-step23-canonical-action-contract-design.md) | COMPLETED |
| [`2026-08-29-step25-d6-parameter-binder-design.md`](specs/2026-08-29-step25-d6-parameter-binder-design.md) | COMPLETED |
| [`2026-08-29-step26-interaction-session-design.md`](specs/2026-08-29-step26-interaction-session-design.md) | COMPLETED |
| [`2026-08-29-step27-impact-layer-design.md`](specs/2026-08-29-step27-impact-layer-design.md) | COMPLETED |
| [`2026-08-29-step28-approval-scope-boundary-design.md`](specs/2026-08-29-step28-approval-scope-boundary-design.md) | COMPLETED |
| [`2026-08-29-step29-immutable-canonical-changeset-design.md`](specs/2026-08-29-step29-immutable-canonical-changeset-design.md) | COMPLETED |
| [`2026-08-29-step30-execution-partitioning-design.md`](specs/2026-08-29-step30-execution-partitioning-design.md) | COMPLETED |
| [`2026-08-30-step31-provider-binding-design.md`](specs/2026-08-30-step31-provider-binding-design.md) | COMPLETED |
| [`2026-08-30-step32-gateway-authorization-design.md`](specs/2026-08-30-step32-gateway-authorization-design.md) | COMPLETED |
| [`2026-08-30-step33-execution-reconciliation-design.md`](specs/2026-08-30-step33-execution-reconciliation-design.md) | COMPLETED |
| [`2026-08-30-step34-autocad-wall-thickness-design.md`](specs/2026-08-30-step34-autocad-wall-thickness-design.md) | COMPLETED |
| [`2026-08-31-step36-offset-create-scope-breach-design.md`](specs/2026-08-31-step36-offset-create-scope-breach-design.md) | COMPLETED |
| [`2026-08-31-step37-cross-host-saga-failure-injection-design.md`](specs/2026-08-31-step37-cross-host-saga-failure-injection-design.md) | COMPLETED |
| [`2026-09-01-phase-h-revit-wall-thickness-gap-closure-design.md`](specs/2026-09-01-phase-h-revit-wall-thickness-gap-closure-design.md) | COMPLETED |
| [`2026-09-06-phase-h-revit-vertical-homogeneity-amendment.md`](specs/2026-09-06-phase-h-revit-vertical-homogeneity-amendment.md) | COMPLETED |
| [`2026-09-06-phase-i-real-cross-host-materialization-saga-design.md`](specs/2026-09-06-phase-i-real-cross-host-materialization-saga-design.md) | COMPLETED |
| [`2026-09-12-post-phase-i-engineering-hygiene-design.md`](specs/2026-09-12-post-phase-i-engineering-hygiene-design.md) | CURRENT |

## Implementation Plans

| Implementation Plan | Lifecycle |
| --- | --- |
| [`2026-08-27-grpc-loopback-transport.md`](plans/2026-08-27-grpc-loopback-transport.md) | COMPLETED |
| [`2026-08-28-dsp-core-semantic-provider.md`](plans/2026-08-28-dsp-core-semantic-provider.md) | COMPLETED |
| [`2026-08-28-ifc43-semantic-provider.md`](plans/2026-08-28-ifc43-semantic-provider.md) | COMPLETED |
| [`2026-08-28-metro-semantic-provider.md`](plans/2026-08-28-metro-semantic-provider.md) | COMPLETED |
| [`2026-08-28-normalized-design-fact-contract.md`](plans/2026-08-28-normalized-design-fact-contract.md) | COMPLETED |
| [`2026-08-28-operation-resolver.md`](plans/2026-08-28-operation-resolver.md) | COMPLETED |
| [`2026-08-28-semantic-mcp-adapter.md`](plans/2026-08-28-semantic-mcp-adapter.md) | COMPLETED |
| [`2026-08-28-semantic-runtime.md`](plans/2026-08-28-semantic-runtime.md) | COMPLETED |
| [`2026-08-28-semantic-service-core.md`](plans/2026-08-28-semantic-service-core.md) | COMPLETED |
| [`2026-08-29-autocad-native-fact-extractor.md`](plans/2026-08-29-autocad-native-fact-extractor.md) | COMPLETED |
| [`2026-08-29-enterprise-a-wall-mapping-provider.md`](plans/2026-08-29-enterprise-a-wall-mapping-provider.md) | COMPLETED |
| [`2026-08-29-step21-d5-canonical-projection-proof.md`](plans/2026-08-29-step21-d5-canonical-projection-proof.md) | COMPLETED |
| [`2026-08-29-step22-task-scoped-progressive-semantics.md`](plans/2026-08-29-step22-task-scoped-progressive-semantics.md) | COMPLETED |
| [`2026-08-29-step23-canonical-action-contract.md`](plans/2026-08-29-step23-canonical-action-contract.md) | COMPLETED |
| [`2026-08-29-step25-d6-parameter-binder.md`](plans/2026-08-29-step25-d6-parameter-binder.md) | COMPLETED |
| [`2026-08-29-step26-interaction-session.md`](plans/2026-08-29-step26-interaction-session.md) | COMPLETED |
| [`2026-08-29-step27-impact-layer.md`](plans/2026-08-29-step27-impact-layer.md) | COMPLETED |
| [`2026-08-29-step28-approval-scope-boundary.md`](plans/2026-08-29-step28-approval-scope-boundary.md) | COMPLETED |
| [`2026-08-29-step29-immutable-canonical-changeset.md`](plans/2026-08-29-step29-immutable-canonical-changeset.md) | COMPLETED |
| [`2026-08-30-step30-execution-partitioning.md`](plans/2026-08-30-step30-execution-partitioning.md) | COMPLETED |
| [`2026-08-30-step31-provider-binding.md`](plans/2026-08-30-step31-provider-binding.md) | COMPLETED |
| [`2026-08-30-step32-gateway-authorization.md`](plans/2026-08-30-step32-gateway-authorization.md) | COMPLETED |
| [`2026-08-30-step33-execution-reconciliation.md`](plans/2026-08-30-step33-execution-reconciliation.md) | COMPLETED |
| [`2026-08-30-step34-autocad-wall-thickness.md`](plans/2026-08-30-step34-autocad-wall-thickness.md) | COMPLETED |
| [`2026-08-31-step36-offset-create-scope-breach.md`](plans/2026-08-31-step36-offset-create-scope-breach.md) | COMPLETED |
| [`2026-08-31-step37-cross-host-saga-failure-injection.md`](plans/2026-08-31-step37-cross-host-saga-failure-injection.md) | COMPLETED |
| [`2026-09-01-phase-h-revit-wall-thickness-gap-closure.md`](plans/2026-09-01-phase-h-revit-wall-thickness-gap-closure.md) | COMPLETED |
| [`2026-09-06-phase-i-real-cross-host-materialization-saga.md`](plans/2026-09-06-phase-i-real-cross-host-materialization-saga.md) | COMPLETED |
| [`2026-09-12-post-phase-i-engineering-hygiene.md`](plans/2026-09-12-post-phase-i-engineering-hygiene.md) | CURRENT |

## 使用规则

- 当前系统级 contract 以 v0.6 主规格为 authority；历史阶段文档用于解释设计演进与实现证据。
- 不通过改写历史正文来表达当前状态；生命周期变化只更新本索引或其他显式状态元数据。
- 新能力阶段只有在其 Design Spec 正式冻结后才命名；当前下一能力阶段保持 `NOT YET DEFINED`。
