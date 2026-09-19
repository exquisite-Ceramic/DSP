# Checkpoint Retention Contract

本 contract 冻结 Workflow Orchestrator checkpoint 的 retention / GC ownership。它只管理 `orchestrator_checkpoint` owner schema 中的 workflow navigation/checkpoint data；外部领域 owner 的 durable state 不属于 checkpoint GC 的删除权限。

```checkpoint-retention
gc_owner=Workflow Orchestrator persistence ops
active_workflow_gc=FORBIDDEN
paused_workflow_gc=FORBIDDEN
terminal_retention=POLICY_CONFIGURED_AFTER_TERMINAL_OBSERVATION
external_authoritative_state_deletion=FORBIDDEN
minimum_audit_metadata=REQUIRED
```

## Active / paused

处于 active 或 HITL-paused 状态、仍可能 resume/re-enter 的 workflow 不得被 GC。GC 判断不能只依赖最后更新时间；必须先确认 Workflow Orchestrator 已把 workflow 识别为 terminal，且不存在仍需 checkpoint 的 resume dependency。

## Terminal retention

Terminal workflow 的具体保留时长属于 Workflow Orchestrator persistence operations policy，不在 Phase II 猜测固定天数。只有完成 terminal observation 后，才允许按已配置 retention policy 回收 checkpoint payload。

无论 retention policy 如何配置，GC 至少保留满足 audit/observability 所需的最小 metadata，例如 workflow identity、terminal outcome/status、完成/删除审计信息以及定位外部 evidence 所需的 stable refs；具体物理形态可由后续 ops implementation 决定。

## External owner isolation

Checkpoint deletion 只允许删除 Workflow Orchestrator 自己的 checkpoint rows/metadata。它不得级联删除或通过 convenience cleanup 删除 ChangeSet、Approval/ExecutionGrant、Execution Saga、Host、Semantic 等外部 authoritative owner state。

恢复或审计需要领域事实时，仍通过 stable refs 查询原 owner；checkpoint GC 不改变这些 owner 的 retention、durability 或业务生命周期。
