from pathlib import Path

p = Path('docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md')
s = p.read_text(encoding='utf-8')


def replace_section(text: str, start_heading: str, next_heading: str, body: str) -> str:
    start = text.index(start_heading)
    end = text.index(next_heading, start)
    return text[:start] + body.rstrip() + '\n\n' + text[end:]


# 1. D4 -> LLM -> D6 -> Phase-B Freshness.
s = replace_section(
    s,
    '## 9.2 两阶段使用 D5',
    '## 9.3 LLM Action Space',
    '''## 9.2 D4 / D6 / Phase-B Freshness 顺序

D4 的 operation eligibility 与 Phase A Context Freshness 位于 LLM planning 之前；**Phase B Operation Freshness 必须在 D6 已完成 target/material argument 绑定之后**。

```text
Orchestrator
  ↓
D5 ContextSnapshot                 # Phase A
  ↓
D4 pre-resolution / schema compile
  ↓
LLM selects canonical operation + fills INTENT slots
  ↓
D6 Parameter Binder
  ├─ CONTEXT
  ├─ CANONICAL_DEFAULT
  ├─ DERIVED
  └─ InteractionSession if required
  ↓
BoundOperationProposal
  ↓
derive OperationFreshnessContract
  ↓
D5 Freshness + Coverage + Assurance barrier   # Phase B
  ↓
PlanningSnapshot / SnapshotSet
  ↓
Impact / ChangeSet
```

D4 MAY 在 Phase B 后再次执行确定性 schema/eligibility validation，但不得在 target/material arguments 尚未确定时声称完整 Operation Freshness 已满足。

若 D6 改变 canonical operation、targets 或任何会改变 freshness/coverage/assurance requirements 的 material argument，MUST 重新派生 Phase B contract。''',
)

# 2. Formal ResolvedOperation and resolver pipelines.
if '## 9.4 ResolvedOperation Contract' not in s:
    anchor = '\n---\n\n# 10. Semantic Service / Semantic MCP Server'
    addition = '''
## 9.4 ResolvedOperation Contract

```text
ResolvedOperation {
  operation_id
  canonical_operation
  title
  description
  llm_input_schema
  canonical_entity_constraints
  context_freshness_requirements
  operation_freshness_requirements
  coverage_requirements
  assurance_requirements
  effects
  policy_decision
  risk
  task_score
  preview_supported
  rollback_supported
  verification_contract
  candidate_provider_ids[]   # internal only
}
```

`candidate_provider_ids[]` 只证明存在候选 implementation，不等于 ProviderBinding，且 MUST NOT 成为 LLM 必填输出。

## 9.5 Operation Resolver / Provider Resolver Pipeline

Operation Resolver：

```text
provider capabilities
→ aggregate by canonical_operation
→ Host availability
→ canonical semantic entity applicability
→ Policy
→ Task rank / Top-K
→ 3~10 ResolvedOperations
```

Provider Resolver 位于 Execution Planning 后，对 immutable `ExecutionUnit` 做 late binding，至少依据：

```text
HostRuntimeRef
provider_native_constraints
Policy / Trust
Provider version / compatibility
Health / availability
License / certification
```

Provider Resolver 只能替换 implementation，MUST NOT 修改 `canonical_operation / targets / arguments / expected_effects / approved scope`。
'''
    assert anchor in s
    s = s.replace(anchor, addition + anchor, 1)

# 3a. Persistent host identity vs runtime host instance.
s = replace_section(
    s,
    '## 19.3 HostBinding',
    '## 19.4 ExternalIdentity',
    '''## 19.3 HostBinding / HostRuntimeRef

`HostBinding` 表达持久的 `SemanticIdentity ↔ Host-native entity` 绑定，不把临时软件会话或 provider implementation 当成长期身份。

```text
HostBinding {
  semantic_id
  host_type
  document_id
  native_id
  native_kind
}
```

```text
HostRuntimeRef {
  host_type
  host_instance_id
  document_id
}
```

```text
SemanticIdentity
  ↓ HostBinding (persistent)
Host document/native entity
  ↓ runtime resolution
HostRuntimeRef
  ↓ ExecutionSlice
  ↓ ProviderBinding
```

- `host_instance_id` MAY 随应用会话变化，因此不属于持久 HostBinding 的必要字段；
- `provider_id/provider_tool` 属于 ProviderBinding，不属于 HostBinding；
- 执行前若不能解析到当前有效 HostRuntimeRef，MUST fail closed。''',
)

# 3b. One SnapshotSet == one pinned semantic environment.
s = replace_section(
    s,
    '## 20.6 SnapshotSet',
    '## 20.7 Snapshot invariant',
    '''## 20.6 SnapshotSet

所有 ChangeSet Core 统一引用 Planning `SnapshotSet`，即使 MVP 只有一个 Host。

**一个 SnapshotSet MUST 绑定唯一的 `semantic_environment_ref`；所有 PlanningSnapshot member MUST 使用同一 pinned SemanticEnvironment。**

```text
SnapshotSet {
  snapshot_set_id
  kind: PLANNING
  semantic_environment_ref
  members[] {
    document_ref
    snapshot_id
    snapshot_hash
    base_host_revision
    semantic_projection_ref
  }
  hash
}
```

若某 document 必须使用不同 SemanticEnvironment，不得静默加入同一 SnapshotSet；应先统一环境，或未来通过独立 ADR 引入 `SemanticEnvironmentSet`。

```text
PS-CAD-01 ─┐
PS-RVT-01 ─┼→ SnapshotSet PSS-01 @ ENV-01 → ChangeSet
PS-TKL-01 ─┘
```

任一 member revision / snapshot hash / projection hash 或 pinned SemanticEnvironment 变化，都必须改变 SnapshotSet hash 并触发 ChangeSet 重新验证。''',
)

# 4-6. Normative appendices.
if '# Appendix A. Normative Core DTOs' not in s:
    s = s.rstrip() + r'''

---

# Appendix A. Normative Core DTOs

正文解释职责；本附录冻结跨模块必须一致理解的 contract shape。

## A.1 Identity / Runtime Host

```text
HostBinding { semantic_id, host_type, document_id, native_id, native_kind }
HostRuntimeRef { host_type, host_instance_id, document_id }
ExternalIdentity { semantic_id, scheme, value }
```

## A.2 ResolvedOperation

```text
ResolvedOperation {
  operation_id
  canonical_operation
  title
  description
  llm_input_schema
  canonical_entity_constraints
  context_freshness_requirements
  operation_freshness_requirements
  coverage_requirements
  assurance_requirements
  effects
  policy_decision
  risk
  task_score
  preview_supported
  rollback_supported
  verification_contract
  candidate_provider_ids[]
}
```

## A.3 SemanticFreshnessContract

```text
SemanticFreshnessContract {
  contract_id
  project_id
  contract_type: CONTEXT|OPERATION
  root_entities[]
  requirements[] {
    aspect
    required_state
    minimum_coverage?
    semantic_depth?
    geometry_fidelity?
    minimum_assurance?
  }
  neighborhood { depth, relations[] }
}
```

## A.4 SemanticSnapshot / SnapshotSet

```text
SemanticSnapshot {
  snapshot_id
  kind: CONTEXT|PLANNING
  project_id
  document_ref
  base_host_revision
  freshness_contract_id
  freshness_contract_hash
  coverage
  aspect_guarantees[] {
    aspect
    entity_scope | coverage_ref
    required_state
    geometry_fidelity?
    semantic_depth?
    minimum_assurance?
  }
  semantic_projection_ref
  semantic_environment_ref
  hash
}

SnapshotSet {
  snapshot_set_id
  kind: PLANNING
  semantic_environment_ref
  members[] {
    document_ref
    snapshot_id
    snapshot_hash
    base_host_revision
    semantic_projection_ref
  }
  hash
}
```

所有 members MUST 使用 top-level pinned SemanticEnvironment。

## A.5 ChangeSet / Execution

```text
ChangeSet {
  changeset_id
  task_id / project_id
  base_snapshot_set_id / base_snapshot_set_hash
  semantic_environment_ref
  root_operations[] / derived_operations[]
  preconditions[] / affected_entities[] / semantic_impacts[]
  validation_tasks[]
  approval_scope_boundary_ref
  risk / approval / verification / rollback
  hash / status
}

ExecutionSlice {
  execution_slice_id
  changeset_id
  host_instance_id
  document_id
  approved_scope_ref
  execution_units[]
  status
}

ExecutionUnit {
  execution_unit_id
  execution_slice_id
  canonical_operation
  targets[]
  arguments
  preconditions[]
  expected_effects[]
}

ProviderBinding {
  binding_id
  execution_unit_id
  canonical_operation
  provider_server / provider_tool / provider_version
  host_instance_id
  input_adapter_version
  native_binding_metadata
  verification_contract / rollback_contract
  binding_expires_at
}
```

`ExecutionUnit` MUST 保持 provider-neutral；native payload 只进入 ProviderBinding/HostCommand。

## A.6 ApprovalScopeBoundary / Approval / Grant

```text
ApprovalScopeBoundary {
  scope_id
  changeset_hash
  existing_entity_rules[] { entities[] | predicate, allowed_aspects[] }
  creation_rules[] {
    canonical_operation
    source_entities[] | source_predicate
    entity_kinds[]
    max_count?
    required_derivation?
  }
  deletion_rules[] { entities[] | predicate }
  propagation_bundle_ids[]
  execution_slice_scopes[]
  scope_hash
}

ApprovalRecord {
  approval_id
  changeset_hash
  approved_scope_hash
  semantic_environment_ref / semantic_environment_hash
  approver
  policy_snapshot_hash
  approved_at
  revoked_at?
}

ExecutionGrant {
  grant_id
  approval_id
  changeset_hash
  execution_slice_id
  binding_set_hash
  host_instance_id
  allowed_operations[]
  approved_scope_hash
  issued_at / expires_at / state
}
```

## A.7 Interaction / Envelope / Error

```text
InteractionSession {
  interaction_id / task_id / host_instance_id / document_id
  interaction_type
  input_constraints / result_schema
  state: PENDING|COMPLETED|CANCELLED|EXPIRED
  result? / created_at / expires_at
}

RequestEnvelope {
  request_id / task_id / project_id / actor_context
  correlation_ids
  deadline_at
  idempotency_key?
  payload
}

AsyncOperationRef { type, id }

ResponseEnvelope {
  request_id
  status: OK|PENDING|ERROR
  correlation_ids
  snapshot_ref?
  operation_ref?: AsyncOperationRef
  result?
  error?: ErrorShape
}

ErrorShape { error_code, category, message, correlation_ids, retryable, details[] }
```

同一逻辑副作用重试：new `request_id`, same `idempotency_key`；`PENDING` MUST 带 typed AsyncOperationRef。

---

# Appendix B. Module Interaction Contracts

## B.1 通用规则

跨模块 contract SHALL 明确 `Owner / Caller / Input / Output / Mode / Retry owner / State owner`。长期状态必须有单一 authoritative owner；LLM 不负责 protocol retry、authorization retry 或 provider failover。

## B.2 Interaction Matrix

| Caller | Callee | Contract | Mode | Retry owner | State owner |
|---|---|---|---|---|---|
| LangGraph | Host Context | context → document/selection/view | sync | LangGraph(read) | Host |
| LangGraph | D5 | FreshnessContract → Snapshot | sync/job | freshness client | D5 |
| LangGraph | D4 | ContextSnapshot → ResolvedOperation[] | sync | LangGraph | D4/Registry |
| D6/LangGraph | Interaction Coordinator | request → InteractionSession | async | idempotency owner | Interaction Coordinator |
| LangGraph | Impact Analyzer | BoundProposal+PlanningSnapshot → Impact/Scope | sync/job | LangGraph | task runtime |
| LangGraph | ChangeSetBuilder | Proposal+SnapshotSet → ChangeSet | sync | deterministic caller | ChangeSet Store |
| LangGraph | Gateway | approval admission → ApprovalRecord | HITL/sync | LangGraph | Gateway |
| LangGraph | Execution Planner | ChangeSet → Slice[]/Unit[] | sync | deterministic caller | Execution Planner |
| LangGraph | Provider Resolver | ExecutionUnit → ProviderBinding | sync | Resolver | Registry/Resolver |
| Gateway | Provider | Grant+Slice+Units+Bindings → result | sync/job | idempotency owner | Provider |
| Provider/Sidecar | Host Plugin | HostCommand → Result/ActualDelta | IPC | Sidecar | Host |
| LangGraph | Verify/Reconcile | ActualDelta → verify/scope result | sync/job | Orchestrator | D5/ChangeSet |

## B.3 Two-phase ordering

```text
Phase A ContextSnapshot
→ D4
→ LLM OperationProposal
→ D6 material binding / InteractionSession
→ BoundOperationProposal
→ derive Phase B contract
→ D5 selective reconstruction
→ PlanningSnapshot / SnapshotSet
→ Impact / ChangeSet
```

## B.4 Apply / Verify / Scope

```text
ApprovalRecord + ChangeSet
→ ExecutionSlice[] → ExecutionUnit[]
→ RevisionBarrier
→ ProviderBinding[] / binding_set_hash
→ ExecutionGrant
→ HostCommand
→ ActualDelta
→ D5 reconcile + Verify + Scope Comparator
```

| Condition | Required action |
|---|---|
| fail before commit | native rollback + HOST_COMMAND_FAILED |
| commit + verify pass + scope inside | Slice SUCCEEDED |
| commit + verify fail | VERIFY_FAILED → reconcile/compensating ChangeSet |
| ActualDelta outside scope | SCOPE_BREACH → stop remaining slices → compensate/reapproval |

---

# Appendix C. Reference Vertical Slices

## C.1 MOVE — Runtime / Execution / Governance

```text
AutoCAD selection
→ Context Freshness / CS-001
→ D4 MOVE ResolvedOperation
→ LLM move.v1 + displacement
→ D6 binding
→ Operation Freshness / PS-001
→ SnapshotSet PSS-001
→ Impact + ApprovalScopeBoundary
→ ChangeSet CS-001
→ Preview / ApprovalRecord
→ ExecutionSlice XS-CAD-01
→ canonical ExecutionUnit EU-001
→ RevisionBarrier
→ ProviderBinding PB-001
→ binding_set_hash / ExecutionGrant
→ HostCommand / AutoCAD transaction
→ ActualDelta
→ Verify + Scope Check + D5 reconcile
```

MOVE 验证 execution/governance baseline，不要求先建立丰富 IFC/Metro domain semantics。

## C.2 Wall Thickness — Semantic / Cross-host

正文第 26 章为第二条 reference slice，额外验证 Progressive Semantic、IFC/Enterprise/Metro、SemanticEnvironment pinning 与 same canonical operation / different ProviderBinding。

MOVE 与 Wall Thickness MUST 并存。

---

# Appendix D. Numbered Contract Conformance

## D.1 Runtime / Execution — RC

| ID | Contract |
|---|---|
| RC-001 | schema invalid input must be rejected |
| RC-002 | stale revision returns REVISION_CONFLICT |
| RC-003 | same idempotency_key retry produces no duplicate side effect |
| RC-004 | transaction abort leaves no half commit |
| RC-005 | ActualDelta includes implicit Host associativity |
| RC-006 | verification independently proves success |
| RC-007 | VIEW/CONTEXT with model mutation effect fails conformance |
| RC-008 | provider switch does not alter canonical ChangeSet/ExecutionUnit |
| RC-009 | binding_set_hash change invalidates old ExecutionGrant |
| RC-010 | CREATE outside creation_rule returns SCOPE_BREACH |
| RC-011 | ActualDelta outside scope stops remaining slices |
| RC-012 | ApprovalToken consumption persists ApprovalRecord |
| RC-013 | child deadline_at <= parent deadline_at |
| RC-014 | PENDING without AsyncOperationRef is contract failure |
| RC-015 | interaction retry does not create a second Host prompt |
| RC-016 | second cross-host Slice failure enters Saga/partial state |

## D.2 Progressive Runtime — SR

| ID | Contract |
|---|---|
| SR-001 | Context Freshness does not read EXACT/NATIVE geometry by default |
| SR-002 | Phase B occurs after D6 material binding |
| SR-003 | UNRESOLVED != STALE |
| SR-004 | partial coverage cannot claim full-document fresh |
| SR-005 | CLASSIFICATION has independent freshness/coverage |
| SR-006 | PlanningSnapshot binds ProjectionRef + EnvironmentRef |
| SR-007 | SnapshotSet members share one pinned SemanticEnvironment |
| SR-008 | member revision/snapshot/projection/environment change invalidates set hash |
| SR-009 | insufficient assurance fails closed |
| SR-010 | reconstruction upgrades only task-required aspects/depth/fidelity |

## D.3 Semantic Provider / Metro / Cross-host

| ID | Contract |
|---|---|
| SP-001 | manifest declares id/type/version/hash/namespaces/capabilities/authority |
| SP-002 | non-authoritative provider cannot silently override namespace |
| SP-003 | pinned term/mapping/validation is deterministic |
| SP-004 | machine semantic change changes content/environment hash |
| SP-005 | Enterprise mapping provider changes do not modify D5 Core |
| SP-006 | A-WALL-* → ifc:IfcWall works through Provider/config |
| SP-007 | provider outage follows pinned-cache policy or fails closed |
| MS-001 | Metro output is IFC4X3_ADD2 legal |
| MS-002 | official Pset/Qto separated from PsetProj/QtoProj |
| MS-003 | IFC-M/IFC-O/P-M/P-C/P-R/PROHIBITED map to structured requirements |
| MS-004 | IDS/unit/type/provenance are verifiable |
| MS-005 | Metro cannot redefine ifc:* canonical meaning |
| CH-001 | same SemanticId can have AutoCAD/Revit HostBindings |
| CH-002 | same canonical wall operation can use different ProviderBindings |
| CH-003 | HostBinding must resolve to active HostRuntimeRef before execution |
| CH-004 | ChangeSet Planning SnapshotSet uses one pinned SemanticEnvironment |
| CH-005 | cross-host Saga preserves auditable partial/compensation state |
'''

# Add explicit invariants.
inv = '31. MODEL_OPERATION 在无有效 Gateway authorization/grant 的 degraded mode 下不得执行。'
if inv in s and '32. Phase B Operation Freshness MUST occur after D6 material target/argument binding.' not in s:
    s = s.replace(
        inv,
        inv + '\n32. Phase B Operation Freshness MUST occur after D6 material target/argument binding.\n33. Persistent HostBinding 与 runtime HostRuntimeRef MUST 分离；provider implementation id 不得充当 Host identity。\n34. 一个 SnapshotSet MUST 使用单一 pinned SemanticEnvironment。',
        1,
    )

p.write_text(s, encoding='utf-8')

# Self-review: no commit if any target is missing or old contradictory ordering remains.
s = p.read_text(encoding='utf-8')
required = [
    '## 9.2 D4 / D6 / Phase-B Freshness 顺序',
    '## 9.4 ResolvedOperation Contract',
    '## 19.3 HostBinding / HostRuntimeRef',
    '一个 SnapshotSet MUST 绑定唯一的 `semantic_environment_ref`',
    '# Appendix A. Normative Core DTOs',
    '# Appendix B. Module Interaction Contracts',
    '# Appendix C. Reference Vertical Slices',
    '# Appendix D. Numbered Contract Conformance',
    'RC-016', 'SR-010', 'SP-007', 'MS-005', 'CH-005',
]
missing = [item for item in required if item not in s]
assert not missing, missing
assert 'D5 operation-specific freshness / assurance barrier\n  ↓\nD6' not in s
print('spec refinement self-review passed')
