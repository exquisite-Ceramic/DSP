# HITL Pause / Resume Compatibility Census

**Date:** 2026-09-19  
**Scope:** approved HITL design §14 / implementation plan Task 1  
**Evidence checkout:** `356241dd63f55528a03923e2bea5196f1c0f5fca`  
**Method:** 在 GitHub Actions exact checkout 上用 temporary Python diagnostic 对计划指定目录与正则做 recursive scan，并额外用 AST 枚举结构化 `CapabilityProfile` 与 `WorkflowArtifactStore` shape。随后在 `0f14085bb2f83cff2ca5e627be1bcb0b4739dd9c` 尝试逐字执行计划中的 `rg` 查询，hosted runner 明确返回 `FileNotFoundError: rg`；因此本文不把该失败尝试描述成成功执行。临时 diagnostic 已从最终分支删除。

## Six-area census

| area | evidence | finding | decision |
| --- | --- | --- | --- |
| public_exports | `platform/orchestrator/src/design_orchestrator/workflow_contracts.py` 定义 `WorkflowCheckpointView` 与 `WorkflowResumeCommand`; `platform/orchestrator/src/design_orchestrator/__init__.py` 公开导出二者; exact-tree scan 未发现现有 `PendingInteractionView` public export | 当前 public surface 已被 tests 与 runtime 使用; `WorkflowCheckpointView` 尚无 `pending_interaction`; `WorkflowResumeCommand` 当前字段只有 `resume_kind` 与 `payload` | additive only |
| runtime_callers | exact-tree constructor scan 在 production 为 0; `platform/orchestrator/src/design_orchestrator/langgraph_runtime.py` 消费 `WorkflowResumeCommand` 并保留 `resume_kind` 与 `payload`; `resume(task_id, command=None)` 仍承担 poll/recheck; `workflow_port.py` 同样允许 optional command | 当前 runtime compatibility surface 同时包含既有 command shape 与 `None` poll; `pause_id` 当前不存在，新增时不得改变既有 source compatibility | preserve resume_kind/payload; pause_id trailing optional |
| test_callers | 6 个 `WorkflowResumeCommand` 构造点: `test_langgraph_runtime.py:186`; `test_postgres_checkpoint.py:199`; `test_workflow_contracts.py:108`; `test_workflow_end_to_end.py:414`; `:440`; `:584`. 其中 3 个是 operation-proposal human resume，1 个是 constructor/copy contract，1 个是 `ASYNC_OPERATION_COMPLETED`，1 个是 `EXECUTION_OWNER_WAKE` | human proposal callers 需要迁移到 pause identity; generic constructor contract、async completion 与 execution-owner wake 证明旧 non-human command shape 仍是 compatibility obligation | migrate human callers; preserve async callers |
| host_plugin_callers | `NONE_IN_REPOSITORY(exact-tree Python scan of hosts and contracts for design_orchestrator.*workflow, workflow_contracts, workflow_port)`; result 为 0 direct match | repository 只证明当前 `hosts/` 与 `contracts/` 没有 direct orchestrator workflow-contract caller; 不能据此证明 repo-external Host/plugin consumer 不存在 | record repository fact only; external state unproven |
| persisted_checkpoints | `langgraph_graph.py` 的 legacy human wait 为 `AWAIT_OPERATION_PROPOSAL + operation_ref + OPERATION_PROPOSAL interrupt`; legacy async wait 为 `async_operation_ref + ASYNC_OPERATION interrupt`; `langgraph_runtime.py` root checkpoint lookup 使用 `thread_id` 与空 `checkpoint_ns`; PostgreSQL owner schema 为 `orchestrator_checkpoint` | 旧 human checkpoint 没有 `pending_interaction/pause_id/version`; 旧 async checkpoint 具有独立 `async_operation_ref` 和 completion/poll 语义; migration 不得把两者解释为同一种 unversioned wait | classify old human and old async separately |
| artifact_store_impls | `WorkflowArtifactStore` 当前只有 public Protocol; concrete `put/get` store 仅 `tests/orchestrator/test_default_workflow_services.py::_MemoryArtifactStore` 与 `tests/orchestrator/test_workflow_end_to_end.py::_MemoryArtifactStore`. 可进入 orchestrator `ResolutionResult.provider_candidates` 的 concrete profile shapes 为 production `hosts/autocad/sidecar/src/autocad_sidecar/capability/profile.py::DesignCapabilityProfile`，以及 `test_default_workflow_services.py::_Profile`, `test_operation_resolver.py::Profile`, `test_step24_semantic_eligibility.py::Profile`, `test_step36_offset_action.py::OffsetProfile`, `test_workflow_end_to_end.py::_Profile`; `CapabilityProfile` Protocol 冻结 13 个共同字段. production `DesignCapabilityProfile` 额外含 `description`, `existence_effects`, `idempotent`，且 legacy `_artifact_content_hash` 对 dataclass 使用全部 `fields()` | repository 尚无 production durable `WorkflowArtifactStore`; Task 2 codec 必须按结构字段而非 concrete class identity round-trip，并显式处理所有 observed profile shape; production 的 3 个额外字段当前参与 legacy hash，不能在 hash-compatibility characterization 中静默丢弃 | memory test-only; durable production adapter; codec covers observed profiles |

## CapabilityProfile shapes and hash relevance

`CapabilityProfile` Protocol 的共同字段为：

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

exact-tree structural inventory 找到以下可实例化 shape：

- Production: `hosts/autocad/sidecar/src/autocad_sidecar/capability/profile.py:25:DesignCapabilityProfile`; 共同字段外另有 `description`, `existence_effects`, `idempotent`。
- Test: `tests/orchestrator/test_default_workflow_services.py:31:_Profile`; 共同字段。
- Test: `tests/orchestrator/test_operation_resolver.py:55:Profile`; 共同字段。
- Test: `tests/orchestrator/test_step24_semantic_eligibility.py:19:Profile`; 共同字段。
- Test: `tests/orchestrator/test_step36_offset_action.py:31:OffsetProfile`; 共同字段，并真实进入 `OperationResolver.resolve()`。
- Test: `tests/orchestrator/test_workflow_end_to_end.py:65:_Profile`; 共同字段。
- Structural contract, not an implementation: `platform/orchestrator/src/design_orchestrator/operation_resolver.py:70:CapabilityProfile`。

`platform/orchestrator/src/design_orchestrator/default_workflow_services.py::_normalize_for_hash()` 对 dataclass 使用 `dataclasses.fields()` 逐字段规范化。因此 production `DesignCapabilityProfile` 的 `description`, `existence_effects`, `idempotent` 在现有 legacy hash 中是 hash-relevant facts。Task 2 可以定义显式 versioned persisted field set，但必须先用 characterization test 证明 legacy hash compatibility，不能仅按 13 个 Protocol 字段假定旧 hash 等价。

## Repository census reproduction queries

以下查询保持 implementation plan Task 1 原文，供具备 `rg` 的开发环境复现。GitHub hosted Python runner 在 evidence run 中没有 `rg` binary，所以本次实际 evidence 使用了同目录、同正则的 Python recursive scan；Host/plugin 查询由该 scan 得到 0 direct match。

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
rg -n "design_orchestrator.*workflow|workflow_contracts|workflow_port" \
  hosts contracts
```

## Compatibility conclusion

Task 1 没有发现要求在进入 Task 2 前修改 approved HITL design ownership 或 compatibility assumptions 的 repository contradiction。冻结边界是：human proposal pause 与 external async wait 属于不同 compatibility lane；Host/plugin absence 只在 repository scope 内成立；workflow artifacts 尚无 production durable implementation；artifact codec 必须保留 observed profile fields 的显式、versioned 语义并对 legacy hash 做真实 parity characterization。