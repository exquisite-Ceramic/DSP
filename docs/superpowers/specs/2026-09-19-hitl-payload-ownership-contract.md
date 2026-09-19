# HITL Payload Ownership Contract

本 contract 延续 ADR-010 的 single-authoritative-owner 边界，冻结 Capability Phase 的 HITL pause/resume payload 规则。LangGraph checkpoint 是 Workflow Orchestrator 的 navigation/checkpoint store，不是领域对象的第二 source of truth。

```hitl-ownership
checkpoint_navigation_state=MAY_OWN
stable_refs=MAY_OWN
presentation_metadata=MAY_OWN
changeset_truth=MUST_NOT_OWN
approval_execution_grant_truth=MUST_NOT_OWN
saga_truth=MUST_NOT_OWN
host_truth=MUST_NOT_OWN
semantic_truth=MUST_NOT_OWN
domain_payload_rule=STABLE_REF_OR_EXTERNAL_AUTHORITATIVE_STORE
```

## 允许进入 checkpoint 的内容

- 当前 workflow node、pause/resume cursor、workflow-local retry/re-entry metadata；
- `changeset_id/hash`、approval/grant ref、`saga_id`、snapshot ref、`AsyncOperationRef` 等 stable refs；
- 仅用于 HITL 展示、可由 authoritative owner 重新构造的 presentation metadata。

## 禁止复制的 authoritative truth

Checkpoint 不得持有 ChangeSet、Approval/ExecutionGrant、Execution Saga、Host commit/document/revision、Semantic Snapshot/Projection 的 authoritative copy。恢复后必须通过 stable ref 重新查询原 owner；checkpoint 中的展示缓存不能覆盖 owner 返回的新事实。

任意 HITL payload 若天然携带领域对象，只能拆成 stable ref + workflow-local presentation metadata；若业务确实需要独立持久化完整对象，必须先声明独立 authoritative store 与生命周期，不能为了 LangGraph convenience 写入 checkpoint。

## Capability Phase acceptance

HITL pause/resume 实现必须证明 restart 后 stable refs 仍能重新解析 authoritative owner state，且修改/删除 checkpoint 不会修改外部 owner state。
