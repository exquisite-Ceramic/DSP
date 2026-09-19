# HITL Pause / Resume Compatibility Census

**Date:** 2026-09-19  
**Scope:** approved HITL design §14 / implementation plan Task 1  
**Evidence checkout:** `356241dd63f55528a03923e2bea5196f1c0f5fca`  
**Method:** GitHub Actions 在 exact checkout 上用等价的 repository-wide regex scanner 执行 Task 1 同一组 roots/patterns，并用 AST 枚举结构化 `CapabilityProfile` 与 `WorkflowArtifactStore` shape。随后在 `0f14085bb2f83cff2ca5e627be1bcb0b4739dd9c` 尝试逐字执行计划中的 `rg` 命令，但 hosted runner 未安装 `rg`，第一条命令即以 `FileNotFoundError` 停止；因此本文不把该失败尝试当作扫描证据。临时 diagnostic 最终不保留。

## Six-area census

| area | evidence | finding | decision |
| --- | --- | --- | --- |
| public_exports | `platform/orchestrator/src/design_orchestrator/__init__.py`; `workflow_contracts.py`; equivalent full-root scan 59 matches | 当前公开导出包含 `WorkflowCheckpointView` 与 `WorkflowResumeCommand`; 仓库尚无 `PendingInteractionView`; `WorkflowCheckpointView` 尚无 `pending_interaction`; `WorkflowResumeCommand` 当前字段仅为 `resume_kind` 与 `payload` | additive only: 新增 `PendingInteractionView`; `pending_interaction` 保持 optional; `CANCELLED` 为新增 enum value; 不删除或重定义既有字段、phase、`interaction_ref` |
| runtime_callers | `langgraph_runtime.py`; `workflow_port.py`; constructor scan 6 matches且全部位于 tests | runtime 仍以 `resume(task_id, command=None)` 支持 poll/recheck; 显式 command 仅把既有 `resume_kind` 与 `payload` 送入 LangGraph; 仓库 production/Host 未发现 `WorkflowResumeCommand(...)` 构造点 | preserve `resume_kind` and `payload`; `pause_id` 只能作为 trailing optional field; `command=None` poll 与既有 async completion 语义保持 |
| test_callers | 6 个构造点: `test_langgraph_runtime.py:186`; `test_postgres_checkpoint.py:199`; `test_workflow_contracts.py:108`; `test_workflow_end_to_end.py:414,440,584` | 测试同时覆盖旧 human proposal ACCEPT 与 `ASYNC_OPERATION_COMPLETED`; e2e human caller 当前仍传 `payload={"accepted": True}`，async caller 传 owner-specific `operation_id` | migrate human callers to non-empty `pause_id` and empty ACCEPT/REJECT payload; preserve async callers, async payload, and `pause_id=None` compatibility |
| host_plugin_callers | equivalent scan of Task 1 Host/plugin roots/pattern returned 0; 计划原命令见下方 Command H | `hosts` 与 `contracts` 内没有直接引用 `design_orchestrator` workflow contract/port 的仓库 consumer | record repository fact only; external state unproven; 不据此声称 repo 外 consumer 不存在，后续 repo 外兼容性仍需独立证据 |
| persisted_checkpoints | `checkpoint_postgres.py`; `langgraph_graph.py`; `langgraph_state.py`; `test_workflow_end_to_end.py`; equivalent full-root scan 101 matches | checkpoint owner schema 为 `orchestrator_checkpoint`; 旧 human wait 是 unversioned `AWAIT_OPERATION_PROPOSAL` + `operation_ref` + LangGraph interrupt，尚无 `pending_interaction`; 旧 async wait 通过 `async_operation_ref` 与 completion/poll 继续 | classify old human and old async separately: 只有 design §10 exact legacy human shape 可 migration; async wait 保持现有 completion/poll contract，禁止把 async checkpoint 当 human legacy |
| artifact_store_impls | `default_workflow_services.py:WorkflowArtifactStore`; 两个 test-local `_MemoryArtifactStore`; AST 找到 6 个可实例化 profile shape，见下方 Profile shapes | 当前无 production durable artifact adapter; memory store 只存在于 tests; production `DesignCapabilityProfile` 满足 resolver Protocol 且额外含 `description`, `existence_effects`, `idempotent`; 其余 5 个 test shape 仅含 Protocol 字段 | memory test-only; add durable production adapter without leaking PostgreSQL types; codec must cover observed/hash-relevant Protocol fields and tolerate observed production extra fields according to explicit persistence policy |

## Task 1 repository scan definitions

以下是 implementation plan 冻结的原始命令。`0f14085b...` 的 exact-command probe 证明 hosted runner 缺少 `rg`，因此没有把该 probe 的失败输出误记成 census 结果。`356241dd...` 的 diagnostic 使用相同 roots 与正则表达式直接扫描文件内容，所得计数与路径构成本文证据。

```bash
rg -n "WorkflowResumeCommand|WorkflowCheckpointView|PendingInteraction" \
  platform hosts tests contracts
rg -n "WorkflowResumeCommand\(" platform hosts tests
rg -n "WorkflowArtifactStore|_MemoryArtifactStore|artifact_store" \
  platform hosts tests
rg -n "CapabilityProfile|provider_candidates|ResolutionResult" \
  platform providers hosts tests
rg -n "await_operation_proposal|ASYNC_OPERATION_COMPLETED|resume\(.*None" \
  platform hosts tests
rg -n "orchestrator_checkpoint|checkpoint_ns|operation_ref" \
  platform tests docs/runbooks .github/workflows
```

### Command H — Host/plugin boundary

```bash
rg -n "design_orchestrator.*workflow|workflow_contracts|workflow_port" \
  hosts contracts
```

Equivalent full-root scan result on `356241dd...`: `NONE_IN_REPOSITORY`. This is a repository-scoped fact only.

## CapabilityProfile shapes that can feed `ResolutionResult.provider_candidates`

`OperationResolver` accepts the structural `CapabilityProfile` Protocol and stores selected profile objects in `ResolutionResult.provider_candidates`. AST inventory found the Protocol plus six concrete/test structural shapes that implement every Protocol field.

- Production: `hosts/autocad/sidecar/src/autocad_sidecar/capability/profile.py:25:DesignCapabilityProfile`; Protocol fields plus `description`, `existence_effects`, `idempotent`.
- Test: `tests/orchestrator/test_default_workflow_services.py:31:_Profile`; Protocol fields only.
- Test: `tests/orchestrator/test_operation_resolver.py:55:Profile`; Protocol fields only.
- Test: `tests/orchestrator/test_step24_semantic_eligibility.py:19:Profile`; Protocol fields only.
- Test: `tests/orchestrator/test_step36_offset_action.py:31:OffsetProfile`; Protocol fields only.
- Test: `tests/orchestrator/test_workflow_end_to_end.py:65:_Profile`; Protocol fields only.
- Structural contract, not an implementation: `platform/orchestrator/src/design_orchestrator/operation_resolver.py:70:CapabilityProfile`.

The persisted/hash-relevant Protocol field set observed at this boundary is:

```text
provider_server
provider_tool
canonical_operation
category
entity_constraints
execution_freshness
effects
risk
preview_supported
rollback_supported
verification_contract
input_schema
output_schema
```

Task 2 codec therefore must round-trip every field in the explicit persisted field set derived from this contract. Concrete Python provider class identity is not a persistence contract. Production-only extras must not be silently serialized by generic object/repr machinery; any persisted subset must be explicit and versioned.

## Compatibility conclusion

The census found no contradiction with the approved design ownership or compatibility assumptions. The implementation may proceed to Task 2 only with the frozen distinctions above: human proposal pause and external async wait are different compatibility lanes; Host/plugin absence is proven only inside this repository; workflow artifacts still lack a production durable implementation.
