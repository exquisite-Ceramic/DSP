# Compensation Execution Ownership

本 contract 冻结 `DIVERGED` / partial-commit 后 compensation 的 owner 边界。现有 `ExecutionSagaPlanner` 只能从 durable Saga evidence 构造可审计 `CompensationProposal`，不会推导 inverse Host command；因此 proposal、authorization、dispatch/execution 与 durable business truth 必须保持分离。

```compensation-ownership
decision_owner=Execution Reconciliation / Execution Saga
proposal_builder=Execution Reconciliation / ExecutionSagaPlanner
authorization_owner=Approval / Gateway Authorization
host_dispatcher_executor=Execution Coordination + Host Adapter
durable_truth_owner=Execution Reconciliation / Execution Saga
workflow_orchestrator_role=COORDINATE_BY_STABLE_REF_ONLY
delivery_success_equals_business_success=NO
```

## Decision 与 proposal

是否需要进入 compensation 路径必须基于 Execution Reconciliation / Execution Saga 持有的 authoritative execution/reconciliation evidence。Workflow Orchestrator 可以观察状态并协调后续步骤，但不能把 checkpoint 或 graph branch 变成 compensation business decision truth。

`ExecutionSagaPlanner` 负责从 durable `StoredExecutionSaga` 证据构造 `CompensationProposal`。它封装 proposal evidence，不自动推导或执行 Host inverse command。

## Authorization 与 Host effect

Compensation 产生新的 Host effect 时，必须经过 Approval / Gateway Authorization 所有的授权边界；`DIVERGED`、`PARTIALLY_COMMITTED`、proposal 存在或 delivery success 都不能隐式充当授权。

Execution Coordination 负责已授权 effect 的跨 Host sequencing/dispatch；真正 native effect 仍由对应 Host Adapter/plugin 执行。平台协调层不得直接拥有 native document truth。

## Durable truth 与 delivery

Compensation proposal/execution result、相关 Saga transition 与最终 reconciliation outcome 的 durable business truth 归 Execution Reconciliation / Execution Saga owner。Transport/outbox/inbox 的 delivery success 只证明消息交付，不证明 compensation business success。

Workflow Orchestrator 只通过 stable refs / `saga_id` 协调等待、重入和用户交互，不复制 compensation durable state 到 checkpoint 作为第二事实源。

## 尚未授权的实现

本 contract 只冻结 owner，不声称 V2 compensation executor 已存在。CV2-008 在 executor、authorization/dispatch implementation 与相应 PostgreSQL/Host evidence 完成前继续保持 `BLOCKED`。
