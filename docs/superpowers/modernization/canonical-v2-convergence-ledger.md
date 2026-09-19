# Canonical V2 Convergence Ledger

本 ledger 是 Architecture Modernization Phase II 的事实与处置索引。Stage A 只记录已经验证的 repository facts；不得因为存在 V2 路径而推断 V1 已无 consumer，也不得在本阶段执行 consumer cutover、语义迁移或 legacy retirement。

## Inventory status

```inventory-status
start_date=2026-09-19
working_day_budget=2
task_budget=3
dedicated_inventory_pr=PENDING
tasks_used=1
```

## Compatibility inventory

| item_id | area | v1_contract_or_path | v2_contract_or_path | bridge_or_adapter | producer | consumers | public_exports | runtime_callers | test_callers | host_dependency | authoritative_owner | persistence_owner | semantic_delta | parity_evidence | real_host_evidence | cutover_blocker | disposition | retirement_preconditions | rollback | exact_head_run | merged_main_run | observation_status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

## Stage A rules

- 本文件在 Task 1 只冻结 schema、inventory budget 与 dedicated PR bootstrap identity，不填写未经 census 验证的 consumer 事实。
- 不适用字段在后续 inventory row 中使用 `N/A:<reason>`；不得使用空值、`UNKNOWN` 或 `TBD`。
- `EVIDENCE_MISSING:<具体证据>` 仅允许用于 `BLOCKED` row 的 evidence/blocker 字段，并必须同时记录 owner 与解除条件。
- `dedicated_inventory_pr=PENDING` 只允许存在到 Stage A Draft PR 创建；Task 1 closeout 后必须回填真实 `#<number>`。
