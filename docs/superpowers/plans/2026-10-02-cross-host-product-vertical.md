# Cross-Host Product Vertical Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现一个由 Revit 发起、由一个 V2 ProductTask 治理、同时对一个受审 Revit Wall 与一个受审 AutoCAD 表达执行 200 mm → 300 mm 墙厚变更的真实双 Host 产品 vertical，并以独立 READ、单 Saga、耐久恢复和 exact-task MCP GET 闭环结果。

**Architecture:** 在现有 Product Front Door、Product Runtime、Workflow Orchestrator、canonical owner、Step28–33、Step37 和真实 Revit/AutoCAD Host adapter 上做显式 V2 扩展，不重写 V1。V2 通过 immutable accepted input、proposal decision owner、两成员 SnapshotSet、workflow-owned binding/grant reference manifests、existing multi-slice coordinator、durable reconciliation evidence 和显式 V2 query view 串联；manifest 只保存 original-owner refs，不成为 authorization owner。

**Tech Stack:** Python 3.11 canonical / Python 3.14 compatibility, PostgreSQL 17, SQLite client state, LangGraph durable checkpointing, MCP 2.x loopback transport, Semantic Runtime, Step28–33 V2 owners, Step37 materialized coordinator, AutoCAD sidecar, Revit 2027 / .NET 10 host plugin.

**Spec:** `docs/superpowers/specs/2026-10-01-cross-host-product-vertical-design.md` — Written Spec APPROVED at exact authority `dc2b20cc4a83ed8b3d9211e24ac00b49a9aa6686`.

**Status:** DRAFT — Written-Plan Review required before production implementation.

## Global Constraints

- V1 `ProductTaskRequest`, V1 request hash meaning, V1 persisted rows, V1 MCP behavior and existing Revit single-Host product vertical remain compatible.
- Missing request version decodes as V1; V2 is explicitly discriminated; unknown versions fail closed.
- V2 initiating Host is exactly `REVIT`; requested action is exactly `SET_BOUND_WALL_THICKNESS`; canonical operation remains `set_wall_thickness.v1`.
- V2 topology contains exactly two REQUIRED members: AutoCAD and Revit; no OPTIONAL downgrade, third Host, dynamic discovery or arbitrary N-Host generalization.
- One V2 ProductTask owns one canonical intent, one ChangeSet, one ApprovalScopeBoundaryV2, one MaterializationPlan, one ExecutionPlanV2 and one Saga.
- Existing `stable_host_type_then_slot.v1` ordering remains authoritative; the controlled pair executes AutoCAD before Revit.
- Human decision, policy approval, planning required-set and Gateway Grant remain distinct authorities.
- Proposal continuity compares stable state, not volatile acquisition metadata such as timestamp, command/evidence id or transport request id.
- Workflow manifests are immutable Workflow Orchestrator artifacts containing original-owner refs; they never copy mutable grant/admission/provider eligibility authority.
- Initial forward execution may run readiness/admission; existing-dispatch recovery and read-only GET must not do so merely because composition was rebuilt.
- Known commit/unknown outcome facts dominate replay convenience; no evidence failure or GET may trigger replacement mutation.
- Every committed materialization is verified by an independent READ at its exact committed revision; EXECUTE response is never verification truth.
- V2 query-required evidence bodies must be durable before Saga publishes their hashes; unreferenced immutable evidence residue is allowed, missing body behind a published hash is not.
- Production code must not import `tests/integration/phase_i_live_host.py` or any other Phase I test helper.
- Automatic compensation, native UNDO orchestration, XA/2PC and parallel Host commit are out of scope.
- Runtime arguments come from immutable ProductTask/planning lineage, never fixture constants.
- New or changed production modules/classes/functions require complete Chinese comments consistent with repository style.
- Any missing public owner contract, need for a new Saga state/transition, or need to weaken exact-revision/authority semantics is a stop-and-amend trigger, not permission to improvise.

## Review Focus

1. **Stable state with changed acquisition metadata:** timestamp/command/evidence ids may differ while runtime/document/native target/semantic target/revision/environment/thickness remain identical; Task 4 and Task 6 must prove this does not falsely stale the proposal.
2. **Transient runtime restart versus stable policy:** a changed `host_instance_id` or locator requires a new SessionBindingV2/ProductTask, but must not require rewriting V2 policy; Task 2 and Task 7 pin this distinction.
3. **Evidence-body crash windows:** body-before-reference may leave an unreferenced body, but a Saga-published V2 hash without a durable body is corruption/recovery-required; Task 13 owns this.
4. **More than one unresolved dispatch:** no successful/committed Slice may hide OUTCOME_UNKNOWN/RECOVERY_REQUIRED/SAFE_TO_RETRY on another required Slice; Task 11 owns this.
5. **Corrupt/partial manifest during GET/restart:** resolution must fail closed without readiness, re-admission, dispatch or mutation; Task 8, Task 9 and Task 14 own this.
6. **Policy replay after config drift:** a durable V2 admission must prove the exact policy snapshot that issued it; replay may not silently authorize topology/required-host dimensions from the current mutable config. Task 7 owns this.
7. **Decision committed before LangGraph consumes it:** ACCEPT/REJECT survives the crash window and is consumed idempotently without rerunning Gate A or issuing a second resume. Task 5 owns this.

---

## File Structure

**Versioned product input and client/server handoff**
- Modify: `platform/product_runtime/src/design_product_runtime/contracts.py` — V2 request and V2 query contracts without changing V1 semantics.
- Create: `platform/product_runtime/src/design_product_runtime/accepted_input.py` — server-owned immutable V2 accepted-input contract.
- Modify: `platform/product_runtime/src/design_product_runtime/postgres_request_store.py` — V1-compatible schema evolution plus atomic V2 request+binding takeover.
- Modify: `platform/product_front_door/src/design_product_front_door/contracts.py` — SessionBindingV2/member contracts.
- Create: `platform/product_front_door/src/design_product_front_door/cross_host_config.py` — reviewed two-Host configuration and stable policy identity.
- Modify: `platform/product_front_door/src/design_product_front_door/sqlite_state.py` — V2 client freeze/replay.
- Modify: `platform/product_front_door/src/design_product_front_door/submission_controller.py` — Revit-entry V2 construction.
- Modify: `platform/product_front_door/src/design_product_front_door/mcp_wire.py`, `mcp_client.py`, `mcp_server.py`, `service.py` — explicit V1/V2 wire dispatch and exact server takeover.

**Human proposal and workflow ownership**
- Create: `platform/orchestrator/src/design_orchestrator/interaction_artifacts.py` — CrossHost proposal subject + stable observations.
- Create: `platform/orchestrator/src/design_orchestrator/proposal_decision.py` — human decision/continuation state contract.
- Create: `platform/orchestrator/src/design_orchestrator/proposal_decision_postgres.py` — owner-local CAS persistence.
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_artifacts.py`, `artifact_postgres.py`, `workflow_services.py`, `default_workflow_services.py`, `langgraph_state.py`, `langgraph_graph.py`, `langgraph_runtime.py` — durable subject refs and safe resume semantics.

**Dual-Host planning, policy and execution collections**
- Create: `platform/product_runtime/src/design_product_runtime/cross_host_planning.py` — independent Revit/AutoCAD planning + Gate B.
- Create: `platform/product_front_door/src/design_product_front_door/approval_policy_v2.py` — stable cross-Host policy.
- Create: `platform/orchestrator/src/design_orchestrator/execution_collection_artifacts.py` — binding/grant reference manifests.
- Create: `platform/orchestrator/src/design_orchestrator/execution_collection_resolution.py` — common exact manifest resolution.
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`, `workflow_services.py`, `recovery.py` — multi-slice binding/grant/execution and recovery projection.
- Create: `platform/product_runtime/src/design_product_runtime/runtime_registry.py` — exact `(host_type, host_instance_id, document_ref)` registry.
- Create: `platform/product_runtime/src/design_product_runtime/cross_host_reference_composition.py` — production/reference V2 composition.

**AutoCAD production path and durable reconciliation evidence**
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/execution/wall_thickness.py` — production materialized mutation adapter.
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/execution/wall_thickness_read.py` — exact-revision independent READ adapter.
- Create: `platform/product_runtime/src/design_product_runtime/autocad_execution.py` — provider snapshot/revision binding boundary.
- Create: `platform/product_runtime/src/design_product_runtime/autocad_evidence.py` — semantic verification evidence composition.
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/evidence_store.py` — evidence owner protocol/codec.
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_evidence.py` — PostgreSQL content-addressed evidence body store.
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/v2.py` and `platform/execution_coordination/src/design_execution_coordination/materialized_coordinator.py` — body-before-reference ordering.

**Query, acceptance and closeout**
- Modify: `platform/product_runtime/src/design_product_runtime/query.py`, `wall_thickness_flow.py` — explicit V2 projection.
- Add focused suites under `tests/product_runtime`, `tests/product_front_door`, `tests/orchestrator`, `tests/execution_reconciliation`, `tests/execution_coordination`.
- Create: `tests/integration/test_cross_host_product_vertical_live.py`.
- Create: `docs/runbooks/cross-host-product-vertical.md`.
- Create: `.github/workflows/cross-host-product-vertical.yml`.
- Modify: `README.md` and `docs/superpowers/README.md` only at lifecycle/closeout gates defined below.

---

### Task 1: Add V2 ProductTaskRequest and SessionBinding contracts without changing V1

**Files:**
- Modify: `platform/product_runtime/src/design_product_runtime/contracts.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Modify: `platform/product_front_door/src/design_product_front_door/contracts.py`
- Modify: `platform/product_front_door/src/design_product_front_door/__init__.py`
- Test: `tests/product_runtime/test_product_task_request.py`
- Create: `tests/product_runtime/test_product_task_request_v2.py`
- Test: `tests/product_front_door/test_contracts.py`

**Interfaces:**
- Produces: `ProductTaskRequestV2.create(...)->ProductTaskRequestV2`.
- Produces: `SessionBindingMemberV2` and `SessionBindingV2.create(...)->SessionBindingV2`.
- V2 request hash body is exactly `version, task_id, project_id, initiating_host_kind, session_ref, session_binding_hash, requested_action, intent_arguments`.
- V2 binding has exactly one `REVIT` member and one `AUTOCAD` member, canonically ordered before hashing.

- [ ] **Step 1: Write V1-preservation and V2 RED tests.**

```python
def test_v1_request_payload_and_hash_contract_remain_unchanged(): ...
def test_v2_request_requires_explicit_version_and_set_bound_wall_thickness(): ...
def test_v2_binding_requires_exact_revit_and_autocad_members(): ...
def test_v2_binding_hash_is_order_independent_but_member_complete(): ...
```

Assert V1 payload keys stay exactly `project_id, host_kind, session_ref, requested_action, intent_arguments`; V2 rejects missing/duplicate/extra members and non-`mm`/non-positive thickness.

- [ ] **Step 2: Run focused RED.**

```bash
uv run pytest tests/product_runtime/test_product_task_request.py tests/product_runtime/test_product_task_request_v2.py tests/product_front_door/test_contracts.py -q -vv
```

Expected: V1 remains GREEN; V2 tests fail because new contracts are absent.

- [ ] **Step 3: Implement the contracts.**

Use exact signatures:

```python
ProductTaskRequestV2.create(
    *,
    task_id: str,
    project_id: str,
    initiating_host_kind: str,
    session_ref: str,
    session_binding_hash: str,
    requested_action: str,
    intent_arguments: Mapping[str, object],
) -> ProductTaskRequestV2

SessionBindingV2.create(
    *,
    session_ref: str,
    project_id: str,
    semantic_target_id: str,
    semantic_environment_id: str,
    semantic_environment_hash: str,
    topology_environment_id: str,
    topology_revision: int,
    topology_snapshot_hash: str,
    initiating_host_kind: str,
    members: Sequence[SessionBindingMemberV2],
) -> SessionBindingV2
```

Do not alter V1 helper/hash bodies.

- [ ] **Step 4: GREEN + Ruff.**

```bash
uv run pytest tests/product_runtime/test_product_task_request.py tests/product_runtime/test_product_task_request_v2.py tests/product_front_door/test_contracts.py -q -vv
uv run ruff check platform/product_runtime/src/design_product_runtime/contracts.py platform/product_front_door/src/design_product_front_door/contracts.py tests/product_runtime/test_product_task_request_v2.py
```

- [ ] **Step 5: Commit** `feat: add versioned cross-host product input contracts`.

---

### Task 2: Freeze reviewed cross-Host configuration and client-side V2 submission durably

**Files:**
- Create: `platform/product_front_door/src/design_product_front_door/cross_host_config.py`
- Modify: `platform/product_front_door/src/design_product_front_door/sqlite_state.py`
- Modify: `platform/product_front_door/src/design_product_front_door/submission_controller.py`
- Modify: `platform/product_front_door/src/design_product_front_door/mcp_wire.py`
- Modify: `platform/product_front_door/src/design_product_front_door/mcp_client.py`
- Modify: `platform/product_front_door/src/design_product_front_door/mcp_server.py`
- Create: `tests/product_front_door/test_cross_host_config.py`
- Modify: `tests/product_front_door/test_sqlite_state.py`, `test_submission_controller.py`, `test_mcp_wire.py`, `test_mcp_client.py`, `test_mcp_server.py`

**Interfaces:**
- Produces: `ConfiguredCrossHostWallThicknessTarget` with a stable `reviewed_configuration_hash` that excludes transient `host_instance_id` and transport endpoints.
- Produces: SQLite `FrozenSubmissionV2` carrying exact `SessionBindingV2 + ProductTaskRequestV2`.
- MCP V2 submit carries the V2 request only; it does not carry the binding body.

- [ ] **Step 1: Write RED for stable config identity, V2 freeze and wire discrimination.**

```python
def test_reviewed_configuration_hash_ignores_transient_runtime_identity(): ...
def test_v2_freeze_atomically_persists_request_and_two_member_binding(): ...
def test_missing_wire_version_decodes_as_v1_and_unknown_version_fails_closed(): ...
def test_v2_mcp_submit_contains_session_binding_hash_but_not_binding_body(): ...
```

Also assert changing runtime/document/native target after freeze requires a different binding and task.

- [ ] **Step 2: Run RED.**

```bash
uv run pytest tests/product_front_door/test_cross_host_config.py tests/product_front_door/test_sqlite_state.py tests/product_front_door/test_submission_controller.py tests/product_front_door/test_mcp_wire.py tests/product_front_door/test_mcp_client.py tests/product_front_door/test_mcp_server.py -q -vv
```

- [ ] **Step 3: Implement exact V2 client freeze and MCP codec.**

Keep the existing V1 tables/readers valid. Add version-aware request JSON and a V2 binding body codec; do not change the existing V1 binding hash.

- [ ] **Step 4: GREEN + V1 wire regression.**

```bash
uv run pytest tests/product_front_door/test_cross_host_config.py tests/product_front_door/test_sqlite_state.py tests/product_front_door/test_submission_controller.py tests/product_front_door/test_mcp_wire.py tests/product_front_door/test_mcp_client.py tests/product_front_door/test_mcp_server.py -q -vv
uv run pytest tests/product_front_door/test_mcp_product_end_to_end.py --collect-only -q
```

- [ ] **Step 5: Commit** `feat: freeze cross-host client submission and wire version`.

---

### Task 3: Atomically transfer V2 request and binding authority to the ProductTask PostgreSQL owner

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/accepted_input.py`
- Modify: `platform/product_runtime/src/design_product_runtime/postgres_request_store.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Modify: `platform/product_front_door/src/design_product_front_door/service.py`
- Create: `tests/product_runtime/test_product_task_accepted_input_v2_postgres.py`
- Modify: `tests/product_runtime/test_product_task_request_postgres.py`
- Modify: `tests/product_front_door/test_service.py`, `test_durable_recovery_postgres.py`

**Interfaces:**
- Produces: `AcceptedProductTaskInputV2(request, session_binding_hash, session_binding_payload)`.
- Adds:
```python
PostgresProductTaskRequestStore.create_v2(
    request: ProductTaskRequestV2,
    *,
    session_binding_hash: str,
    session_binding_payload: Mapping[str, object],
) -> AcceptedProductTaskInputV2

PostgresProductTaskRequestStore.get_v2(task_id: str) -> AcceptedProductTaskInputV2 | None
```
- Schema evolution keeps historical V1 rows readable and uses one task-id conflict domain across V1/V2.

- [ ] **Step 1: Write PostgreSQL RED.**

```python
def test_v2_accept_persists_request_and_binding_in_one_owner_transaction(): ...
def test_same_v2_body_replays_and_different_version_body_or_binding_conflicts(): ...
def test_historical_v1_row_remains_readable_after_v2_schema_upgrade(): ...
def test_server_restart_recovers_v2_binding_without_client_sqlite(): ...
```

- [ ] **Step 2: Run with real PostgreSQL and verify RED.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/product_runtime/test_product_task_accepted_input_v2_postgres.py tests/product_runtime/test_product_task_request_postgres.py tests/product_front_door/test_durable_recovery_postgres.py -q -vv
```

- [ ] **Step 3: Implement owner-local migration/transaction.**

Evolve `product_task.request` with explicit request-version and nullable V2 binding columns, preserving V1 defaults. For V2, durable binding body/hash publication and request publication must commit together.

- [ ] **Step 4: Wire Front Door takeover order.**

V2 submit order is exact local binding read → binding-hash validation → reviewed-config validation → atomic `create_v2` → workflow eligibility. Recovery after acceptance reads `get_v2`, never client SQLite.

- [ ] **Step 5: GREEN + request/start-gate concurrency regression.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/product_runtime/test_product_task_accepted_input_v2_postgres.py tests/product_runtime/test_product_task_request_postgres.py tests/product_front_door/test_durable_recovery_postgres.py tests/product_runtime/test_product_task_shared_start_gate_postgres.py tests/product_runtime/test_request_binding_interleaving.py -q -vv
```

- [ ] **Step 6: Commit** `feat: persist immutable cross-host accepted input`.

---

### Task 4: Persist the exact cross-Host human proposal subject and make HITL subject refs generic

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/interaction_artifacts.py`
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_artifacts.py`
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/default_workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_state.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_runtime.py`
- Create: `tests/orchestrator/test_cross_host_proposal_subject.py`
- Modify: `tests/orchestrator/test_hitl_resume.py`, `test_workflow_artifacts.py`, `test_artifact_postgres.py`

**Interfaces:**
- Produces: `CrossHostProposalObservationV2` and `CrossHostOperationProposalSubjectV2`.
- Adds `InteractionSubjectArtifactResolution(ref: StableRef, source: str)` alongside the existing `OperationArtifactResolution`; do not repurpose the operation-only result type.
- Adds:
```python
WorkflowServices.prepare_operation_proposal_subject(
    task_id: str,
    operation_ref: StableRef,
    context_snapshot_ref: StableRef,
) -> StableRef

WorkflowServices.ensure_interaction_subject_artifact(
    subject_ref: StableRef,
    context_snapshot_ref: StableRef,
    *,
    allow_legacy_rehydrate: bool,
) -> InteractionSubjectArtifactResolution
```
- Keep `ensure_operation_artifact(...)` unchanged for legacy operation-artifact migration. V1 current checkpoints resolve their operation subject through the new generic validator; V2 resolves a durable proposal-subject artifact.
- Private graph state keeps `proposal_subject_ref`; `pending_interaction.subject_ref` equals it and is no longer required to equal `operation_ref`.

- [ ] **Step 1: Write RED for subject content and V1 HITL compatibility.**

```python
def test_v2_subject_hash_binds_request_binding_topology_operation_and_both_observations(): ...
def test_subject_stable_comparison_ignores_timestamp_and_command_id_only(): ...
def test_v1_pending_subject_can_remain_operation_ref(): ...
def test_runtime_preflight_validates_generic_durable_subject_without_rehydrating_v2(): ...
```

- [ ] **Step 2: Run RED.**

```bash
uv run pytest tests/orchestrator/test_cross_host_proposal_subject.py tests/orchestrator/test_hitl_resume.py tests/orchestrator/test_workflow_artifacts.py -q -vv
```

- [ ] **Step 3: Implement proposal subject codec + graph/runtime hook.**

The V2 subject contains exact request hash, binding hash, topology hash, semantic target, canonical operation/arguments and both Host observations. It must not contain `required_set_hash`.

- [ ] **Step 4: Prove PostgreSQL artifact restart.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/orchestrator/test_artifact_postgres.py tests/orchestrator/test_cross_host_proposal_subject.py -q -vv
```

- [ ] **Step 5: Commit** `feat: persist exact cross-host proposal subject`.

---

### Task 5: Add the durable proposal-decision owner and atomic ACCEPT-versus-stale Gate A

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/proposal_decision.py`
- Create: `platform/orchestrator/src/design_orchestrator/proposal_decision_postgres.py`
- Modify: `platform/product_front_door/src/design_product_front_door/service.py`
- Modify: `platform/product_runtime/src/design_product_runtime/query.py`
- Create: `tests/orchestrator/test_proposal_decision_postgres.py`
- Create: `tests/product_front_door/test_cross_host_gate_a.py`

**Interfaces:**
- `HumanDecisionState = AWAITING | ACCEPTED | REJECTED`.
- `ProposalContinuationState = CONTINUABLE | STALE_GATE_A | STALE_GATE_B`.
- Produces:
```python
ProposalDecisionStore.claim_accept(task_id, pause_id, subject_ref) -> ProposalDecisionRecord
ProposalDecisionStore.claim_reject(task_id, pause_id, subject_ref) -> ProposalDecisionRecord
ProposalDecisionStore.invalidate_gate_a(task_id, pause_id, subject_ref, reason) -> ProposalDecisionRecord
ProposalDecisionStore.invalidate_gate_b(task_id, pause_id, subject_ref, reason) -> ProposalDecisionRecord
ProposalDecisionStore.get(task_id, pause_id, subject_ref) -> ProposalDecisionRecord | None
```

- [ ] **Step 1: Write CAS race RED in both winner orders.**

```python
def test_gate_a_stale_wins_then_late_accept_cannot_advance(): ...
def test_accept_wins_then_late_gate_a_invalidation_cannot_erase_accept(): ...
def test_reject_is_human_history_and_is_not_stale(): ...
def test_concurrent_accept_consumes_at_most_once(): ...
```

- [ ] **Step 2: Run PostgreSQL RED.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/orchestrator/test_proposal_decision_postgres.py tests/product_front_door/test_cross_host_gate_a.py -q -vv
```

- [ ] **Step 3: Implement owner-local CAS semantics.**

Use expected current record revision/state; loser re-reads and returns authoritative winner. Gate A stale leaves human state `AWAITING` and sets continuation `STALE_GATE_A`; ACCEPT winner records `ACCEPTED + CONTINUABLE`.

- [ ] **Step 4: Wire V2 resume and close the decision→checkpoint crash window.**

For an `AWAITING` decision: durable query/pause check → exact accepted input/subject → fresh two-Host READ → stable comparison → CAS ACCEPT/REJECT or Gate-A stale. After the CAS commits, the decision owner is authoritative.

If ACCEPT or REJECT is already durable but the same LangGraph pause is still pending after a process crash, retry consumes that durable decision without rerunning Gate A. If the checkpoint already advanced, retry returns the current durable query without issuing a second resume. `STALE_GATE_A` never calls `flow.resume()`. Gate B remains responsible for drift that occurs after ACCEPT wins. Front Door never edits checkpoint directly.

Add:
```python
def test_accept_committed_before_graph_resume_recovers_without_second_gate_a(): ...
def test_reject_committed_before_graph_resume_recovers_idempotently(): ...
def test_checkpoint_already_advanced_does_not_consume_decision_twice(): ...
```

- [ ] **Step 5: GREEN including delayed/concurrent/crash-window requests.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/orchestrator/test_proposal_decision_postgres.py tests/product_front_door/test_cross_host_gate_a.py tests/product_front_door/test_service_resume.py -q -vv
```

- [ ] **Step 6: Commit** `feat: serialize human accept and proposal staleness`.

---

### Task 6: Build independent dual-Host PlanningSnapshots and Gate B continuity

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/cross_host_planning.py`
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/default_workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Create: `tests/product_runtime/test_cross_host_planning.py`
- Modify: `tests/orchestrator/test_canonical_owner_ports.py` or the repository's existing canonical-owner focused suite.

**Interfaces:**
- Adds:
```python
WorkflowServices.ensure_operation_freshness(
    task_id: str,
    operation_ref: StableRef,
    proposal_subject_ref: StableRef | None,
) -> OperationFreshnessResult | AsyncOperationRef
```
- Produces `CrossHostOperationFreshnessBoundary.ensure(task_id, operation_ref, proposal_subject_ref)`.
- V2 returns Revit anchor `planning_snapshot_ref` plus a `SnapshotSet` with exactly independent Revit and AutoCAD members.

- [ ] **Step 1: Write RED for two independent revisions and Gate B.**

```python
def test_v2_snapshot_set_contains_exact_revit_and_autocad_members(): ...
def test_autocad_snapshot_is_reconstructed_not_cloned_from_revit(): ...
def test_equal_stable_state_with_new_acquisition_metadata_passes_gate_b(): ...
def test_post_accept_revit_or_autocad_drift_marks_stale_gate_b_and_preserves_accept(): ...
```

- [ ] **Step 2: Run RED.**

```bash
uv run pytest tests/product_runtime/test_cross_host_planning.py tests/orchestrator -q -k "operation_freshness or snapshot_set or revision_barrier" -vv
```

- [ ] **Step 3: Implement independent reconstruction.**

Each member must independently READ/normalize/semantically reconstruct under the same pinned SemanticEnvironment, same operation/semantic target lineage and its own document revision. Do not copy Revit snapshot data into AutoCAD.

- [ ] **Step 4: Implement Gate B failure path.**

On continuity failure, atomically preserve `HumanDecisionState.ACCEPTED`, set `STALE_GATE_B`, stop further progression with stable workflow error `OPERATION_PROPOSAL_STALE`, and require a new ProductTask.

- [ ] **Step 5: GREEN + dual-member RevisionBarrier proof.**

```bash
uv run pytest tests/product_runtime/test_cross_host_planning.py tests/semantic_runtime/test_revision_barrier.py tests/orchestrator/test_task7_revision_barrier.py tests/orchestrator/test_canonical_owner_ports.py -q -vv
```

- [ ] **Step 6: Commit** `feat: add dual-host planning continuity`.

---

### Task 7: Add explicit V2 cross-Host approval policy while keeping runtime identity out of policy

**Files:**
- Create: `platform/product_front_door/src/design_product_front_door/approval_policy_v2.py`
- Modify: `platform/product_front_door/src/design_product_front_door/postgres_admission_store.py`
- Modify: `platform/product_front_door/src/design_product_front_door/__init__.py`
- Create: `tests/product_front_door/test_approval_policy_v2.py`
- Modify: `tests/product_front_door/test_approval_policy.py`, `test_approval_admission_postgres.py`

**Interfaces:**
- `ConfiguredProductApprovalPolicyV2` version is exactly `DSP_PRODUCT_APPROVAL_POLICY_V2`.
- Stable authority fields: project, canonical operations, reviewed configuration hash, semantic target id, topology snapshot hash, required Host types/roles, admission TTL.
- Transient `host_instance_id` and transport locator are forbidden policy fields.
- Produces `ConfiguredPolicyApprovalAdmissionPortV2.request_approval(changeset_ref: StableRef)->ApprovalAdmission` without changing the Gateway `ApprovalAdmission` contract.
- Extend the existing `product_policy.admission` owner with nullable V2 policy-version/payload columns so historical V1 rows remain valid. Add:
```python
PostgresConfiguredPolicyAdmissionStore.issue_or_get_v2(
    admission: ApprovalAdmission,
    *,
    policy_version: str,
    policy_snapshot_payload: Mapping[str, object],
) -> StoredConfiguredPolicyAdmissionV2

PostgresConfiguredPolicyAdmissionStore.get_v2(
    *,
    changeset_hash: str,
    approved_scope_hash: str,
) -> StoredConfiguredPolicyAdmissionV2 | None
```
- `StoredConfiguredPolicyAdmissionV2` contains the existing admission plus the canonical V2 policy snapshot body. Its canonical hash MUST equal `admission.policy_snapshot_hash`. V2 replay validates that durable body against the exact ChangeSet/ApprovalScope/topology/required-host lineage and MUST NOT rely on the current mutable config file.

- [ ] **Step 1: Write RED.**

```python
def test_v1_policy_cannot_authorize_v2_cross_host_task(): ...
def test_v2_policy_allows_exact_project_operation_target_topology_and_host_types(): ...
def test_runtime_restart_identity_does_not_change_policy_snapshot_hash(): ...
def test_policy_default_denies_missing_or_extra_required_host(): ...
def test_v2_admission_replay_uses_durable_policy_snapshot_not_current_config(): ...
```

- [ ] **Step 2: Run RED.**

```bash
uv run pytest tests/product_front_door/test_approval_policy.py tests/product_front_door/test_approval_policy_v2.py tests/product_front_door/test_approval_admission_postgres.py -q -vv
```

- [ ] **Step 3: Implement V2 policy/admission without changing V1 parser, V1 row codec or Gateway admission hash.**

The Product Policy owner persists the canonical V2 policy snapshot body beside the existing admission. Replayed V2 admission must prove the stored body hash equals `policy_snapshot_hash` and re-check its stable dimensions against final ChangeSet/ApprovalScope/topology/required-host lineage. Runtime/provider authority remains Step31/32 responsibility.

- [ ] **Step 4: GREEN and explicit no-mutation policy-deny/replay tests.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/product_front_door/test_approval_policy.py tests/product_front_door/test_approval_policy_v2.py tests/product_front_door/test_approval_admission_postgres.py -q -vv
```

- [ ] **Step 5: Commit** `feat: authorize stable cross-host product policy`.

---

### Task 8: Persist exact ProviderBinding collection manifests as workflow artifacts

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/execution_collection_artifacts.py`
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_artifacts.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Create: `tests/orchestrator/test_provider_binding_collection_manifest.py`
- Modify: `tests/orchestrator/test_artifact_postgres.py`

**Interfaces:**
- Produces `ProviderBindingCollectionManifest` with execution-plan id/hash, materialization-plan hash, ordered required Slice ids/hashes and member tuples `(execution_slice_id, execution_slice_hash, materialization_id, owner_ref)`.
- `CanonicalWorkflowOwnerPorts.bind_providers(execution_plan_ref)` keeps current single-slice behavior for V1, but for a two-slice V2 plan stores both original `ProviderBindingSetV2` values in their owner and returns the manifest `StableRef`.

- [ ] **Step 1: Write RED for exact coverage and codec integrity.**

```python
def test_binding_manifest_covers_exact_required_slice_set_in_plan_order(): ...
def test_binding_manifest_rejects_missing_duplicate_extra_or_wrong_plan_lineage(): ...
def test_binding_manifest_survives_postgres_artifact_restart(): ...
```

- [ ] **Step 2: Run RED.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/orchestrator/test_provider_binding_collection_manifest.py tests/orchestrator/test_artifact_postgres.py -q -vv
```

- [ ] **Step 3: Implement content-addressed codec and multi-slice binding loop.**

Manifest contains refs only; it must not copy provider eligibility or mutable owner state.

- [ ] **Step 4: GREEN + corrupt codec/hash negative.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/orchestrator/test_provider_binding_collection_manifest.py tests/orchestrator/test_artifact_postgres.py -q -vv
```

- [ ] **Step 5: Commit** `feat: persist provider binding reference manifest`.

---

### Task 9: Persist Grant manifests and add one common collection resolver

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/execution_collection_resolution.py`
- Modify: `platform/orchestrator/src/design_orchestrator/execution_collection_artifacts.py`
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_artifacts.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Create: `tests/orchestrator/test_execution_grant_collection_manifest.py`
- Create: `tests/orchestrator/test_execution_collection_resolution.py`

**Interfaces:**
- Produces `ExecutionGrantCollectionManifest` mirroring the exact Slice set and original Gateway Grant `StableRef` values.
- Produces:
```python
resolve_provider_binding_collection(ref, execution_plan, artifact_store, binding_store) -> tuple[ProviderBindingSetV2, ...]
resolve_execution_grant_collection(ref, execution_plan, artifact_store, gateway_store) -> tuple[object, ...]
```
- Common resolver validates artifact codec/hash, plan/materialization lineage and exact required Slice coverage before resolving original owner refs.

- [ ] **Step 1: Write RED for exact Grant coverage and read-only resolution.**

```python
def test_grant_manifest_exactly_matches_binding_manifest_and_required_slices(): ...
def test_manifest_resolution_does_not_admit_check_readiness_or_execute(): ...
def test_partial_or_corrupt_manifest_fails_before_any_owner_mutation(): ...
```

- [ ] **Step 2: Run RED.**

```bash
uv run pytest tests/orchestrator/test_execution_grant_collection_manifest.py tests/orchestrator/test_execution_collection_resolution.py -q -vv
```

- [ ] **Step 3: Implement multi-slice `issue_execution_grant`.**

For each required Slice resolve its original binding, issue/admit through Gateway using exact Step28/29/MaterializationPlan/topology lineage, then persist only Grant refs in the workflow manifest.

- [ ] **Step 4: GREEN.**

```bash
uv run pytest tests/orchestrator/test_execution_grant_collection_manifest.py tests/orchestrator/test_execution_collection_resolution.py -q -vv
```

- [ ] **Step 5: Commit** `feat: persist execution grant reference manifest`.

---

### Task 10: Resolve manifests only on the forward-execution path and assemble exact Host registries

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/runtime_registry.py`
- Create: `platform/product_runtime/src/design_product_runtime/cross_host_reference_composition.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Create: `tests/product_runtime/test_cross_host_runtime_registry.py`
- Create: `tests/product_runtime/test_cross_host_reference_composition.py`
- Create: `tests/orchestrator/test_cross_host_forward_execution.py`

**Interfaces:**
- Produces exact registry `resolve(runtime_ref)` keyed by `(host_type, host_instance_id, document_ref)`.
- V2 `begin_execution(execution_plan_ref, grant_ref)` resolves binding/grant manifests, validates every original owner object and current applicability, then calls existing coordinator with ordered concrete tuples.
- Coordinator remains unaware of workflow manifests.

- [ ] **Step 1: Write RED for exact registry identity and complete-before-first-mutation behavior.**

```python
def test_registry_rejects_same_host_type_with_wrong_instance_or_document(): ...
def test_forward_execution_resolves_all_bindings_and_grants_before_first_host_execute(): ...
def test_missing_second_grant_causes_zero_host_mutations(): ...
```

- [ ] **Step 2: Run RED.**

```bash
uv run pytest tests/product_runtime/test_cross_host_runtime_registry.py tests/product_runtime/test_cross_host_reference_composition.py tests/orchestrator/test_cross_host_forward_execution.py -q -vv
```

- [ ] **Step 3: Implement resolver path and reference composition seams.**

V1 single-slice `begin_execution` stays valid. V2 does not leak manifest objects into `MaterializedExecutionSagaCoordinator.execute(...)`.

- [ ] **Step 4: GREEN + all-required readiness failure proof.**

```bash
uv run pytest tests/product_runtime/test_cross_host_runtime_registry.py tests/product_runtime/test_cross_host_reference_composition.py tests/orchestrator/test_cross_host_forward_execution.py tests/execution_coordination/test_phase_i_readiness_barrier.py tests/execution_coordination/test_phase_i_materialized_readiness_failed.py -q -vv
```

- [ ] **Step 5: Commit** `feat: execute cross-host plan from exact owner collections`.

---

### Task 11: Make execution-owner recovery projection multi-slice and keep recovery separate from execute

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/recovery.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Create: `tests/orchestrator/test_multi_slice_execution_recovery.py`
- Modify: existing recovery tests under `tests/orchestrator`

**Interfaces:**
- `ExecutionOwnerView` gains `unresolved_dispatch_recoveries: tuple[HostDispatchRecoveryView, ...]`.
- Preserve source compatibility for current single-slice callers through an `active_dispatch_recovery` compatibility projection when exactly one unresolved item exists.
- Classification checks every unresolved required Slice before aggregate Saga status.

- [ ] **Step 1: Write RED for multiple unresolved dispatches.**

```python
def test_outcome_unknown_on_one_slice_masks_no_other_slice_success(): ...
def test_two_unresolved_slices_project_recover_or_wait_without_arbitrary_selection(): ...
def test_restart_with_existing_dispatch_does_not_call_execute_or_readiness(): ...
def test_committed_slice_is_never_redispatched_after_composition_rebuild(): ...
```

- [ ] **Step 2: Run RED.**

```bash
uv run pytest tests/orchestrator/test_multi_slice_execution_recovery.py tests/orchestrator/test_task10_durable_recovery.py tests/execution_coordination/test_task8_execution_recovery_projection.py -q -vv
```

- [ ] **Step 3: Implement exact per-Slice projection.**

Validate Saga membership, no duplicate/extra/missing Slice, plan/materialization lineage, and dispatch intent ownership before returning the tuple.

- [ ] **Step 4: GREEN + predecessor single-slice recovery regression.**

```bash
uv run pytest tests/orchestrator/test_multi_slice_execution_recovery.py tests/orchestrator/test_task10_durable_recovery.py tests/orchestrator/test_workflow_resume_authoritative_truth.py tests/execution_coordination/test_task8_execution_recovery_projection.py tests/execution_coordination/test_unknown_outcome_recovery.py -q -vv
```

- [ ] **Step 5: Commit** `feat: project multi-slice execution recovery truth`.

---

### Task 12: Add production AutoCAD mutation, readiness/provider binding and independent READ evidence adapters

**Files:**
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/execution/wall_thickness.py`
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/execution/wall_thickness_read.py`
- Create: `platform/product_runtime/src/design_product_runtime/autocad_execution.py`
- Create: `platform/product_runtime/src/design_product_runtime/autocad_evidence.py`
- Modify: `platform/product_runtime/src/design_product_runtime/cross_host_reference_composition.py`
- Create: `hosts/autocad/sidecar/tests/test_wall_thickness_product_execution.py`
- Create: `tests/product_runtime/test_autocad_execution_composition.py`
- Create: `tests/product_runtime/test_autocad_verification_evidence.py`

**Interfaces:**
- Host mutation wraps public `CommandDispatcher.set_wall_thickness(..., idempotency_key, revision)`.
- Read path wraps public normalized fact extraction and requires exact host/document/native id and exact committed source revision.
- Provider snapshot boundary freezes expected AutoCAD planning revision into existing Step31 binding metadata.
- Evidence port mirrors `RevitWallThicknessVerificationEvidencePort.build_bundle(...)` and never receives a mutation port.

- [ ] **Step 1: Write RED for the full AutoCAD qualification set.**

```python
def test_autocad_commit_builds_actual_delta_only_for_exact_changed_target_effect(): ...
def test_autocad_revision_conflict_is_before_commit_and_has_no_actual_delta(): ...
def test_autocad_lost_response_is_outcome_unknown_not_safe_retry(): ...
def test_autocad_independent_read_requires_exact_committed_revision(): ...
def test_autocad_verification_uses_semantic_facts_not_execute_response_width(): ...
```

- [ ] **Step 2: Run RED.**

```bash
uv run pytest hosts/autocad/sidecar/tests/test_wall_thickness_product_execution.py tests/product_runtime/test_autocad_execution_composition.py tests/product_runtime/test_autocad_verification_evidence.py -q -vv
```

- [ ] **Step 3: Implement thin production adapters only.**

No production import from `tests/integration/phase_i_live_host.py`; reuse `AutoCadWallThicknessReadinessPort` and sidecar public dispatcher/fact APIs.

- [ ] **Step 4: GREEN + AutoCAD sidecar regression.**

```bash
uv run pytest hosts/autocad/sidecar/tests/test_wall_thickness_product_execution.py tests/product_runtime/test_autocad_execution_composition.py tests/product_runtime/test_autocad_verification_evidence.py -q -vv
```

- [ ] **Step 5: Commit** `feat: add production autocad product materialization adapters`.

---

### Task 13: Persist V2 reconciliation evidence bodies before publishing Saga hashes

**Files:**
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/evidence_store.py`
- Create: `platform/execution_reconciliation/src/design_execution_reconciliation/postgres_evidence.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/v2.py`
- Modify: `platform/execution_reconciliation/src/design_execution_reconciliation/__init__.py`
- Modify: `platform/execution_coordination/src/design_execution_coordination/materialized_coordinator.py`
- Create: `tests/execution_reconciliation/test_postgres_evidence_store.py`
- Create: `tests/execution_coordination/test_evidence_body_ordering.py`

**Interfaces:**
- Produces:
```python
put_actual_delta(value: ActualDelta) -> str
get_actual_delta(content_hash: str) -> ActualDelta | None
put_verification_bundle(value: VerificationEvidenceBundle) -> str
get_verification_bundle(content_hash: str) -> VerificationEvidenceBundle | None
put_verification_result(value: SemanticVerificationResult) -> str
get_verification_result(content_hash: str) -> SemanticVerificationResult | None
```
- Store is content-addressed, codec-versioned and owned by execution reconciliation persistence.
- Same hash/body replay is idempotent; same hash/different body is corruption.

- [ ] **Step 1: Write PostgreSQL RED including crash windows.**

```python
def test_actual_delta_body_is_durable_before_dispatch_and_saga_commit_hash(): ...
def test_verification_bodies_are_durable_before_saga_verification_hash(): ...
def test_crash_after_body_before_saga_ref_leaves_safe_unreferenced_body(): ...
def test_saga_hash_without_body_is_integrity_failure_and_never_redispatches(): ...
```

- [ ] **Step 2: Run RED with PostgreSQL.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/execution_reconciliation/test_postgres_evidence_store.py tests/execution_coordination/test_evidence_body_ordering.py -q -vv
```

- [ ] **Step 3: Implement codec/store and body-before-reference ordering.**

Persist ActualDelta before `mark_host_committed/record_host_commit`; persist bundle/result before Saga publishes verification refs/hashes.

- [ ] **Step 4: GREEN + historical Saga/V1 regression.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/execution_reconciliation/test_postgres_evidence_store.py tests/execution_reconciliation/test_postgres_saga_store_v2.py tests/execution_reconciliation/test_step33_v2_local_reconciliation.py tests/execution_coordination/test_evidence_body_ordering.py tests/execution_coordination/test_verification_evidence_unavailable.py -q -vv
```

- [ ] **Step 5: Commit** `feat: persist reconciliation evidence bodies`.

---

### Task 14: Add explicit ProductTaskQueryViewV2 and offline exact-task MCP GET

**Files:**
- Modify: `platform/product_runtime/src/design_product_runtime/contracts.py`
- Modify: `platform/product_runtime/src/design_product_runtime/query.py`
- Modify: `platform/product_runtime/src/design_product_runtime/wall_thickness_flow.py`
- Modify: `platform/product_front_door/src/design_product_front_door/mcp_wire.py`
- Modify: `platform/product_front_door/src/design_product_front_door/mcp_client.py`
- Modify: `platform/product_front_door/src/design_product_front_door/mcp_server.py`
- Create: `tests/product_runtime/test_product_task_query_v2.py`
- Create: `tests/product_runtime/test_product_task_query_v2_postgres.py`
- Modify: `tests/product_front_door/test_mcp_product_end_to_end.py`

**Interfaces:**
- Produces `ProductTaskQueryViewV2` with explicit `version="V2"`, aggregate state/status, durable proposal state and ordered `materializations`.
- Each `ProductMaterializationQueryViewV2` may expose Host/document/native+semantic target, materialization/Slice refs, status, expected/committed/observed revisions, verified thickness, ActualDelta/verification/convergence hashes and recovery/evidence-unavailable disposition.
- V1 `ProductTaskQueryView` wire shape remains unchanged.

- [ ] **Step 1: Write RED for offline projection and no-side-effect query.**

```python
def test_v2_get_projects_measured_300_from_durable_read_evidence_not_request_intent(): ...
def test_v2_get_with_hosts_offline_calls_zero_readiness_admission_execute_or_host_read(): ...
def test_stale_gate_a_and_gate_b_project_stale_not_cancelled(): ...
def test_partial_commit_and_unresolved_dispatch_project_exact_owner_truth(): ...
def test_missing_published_evidence_body_is_integrity_failure_not_redispatch(): ...
```

- [ ] **Step 2: Run RED.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/product_runtime/test_product_task_query_v2.py tests/product_runtime/test_product_task_query_v2_postgres.py tests/product_front_door/test_mcp_product_end_to_end.py -q -vv
```

- [ ] **Step 3: Implement version dispatch and evidence lineage walk.**

Read order is accepted input → checkpoint/decision → Saga/dispatch → evidence bodies → immutable referenced owner artifacts. Do not create `ProductTaskResult` table.

- [ ] **Step 4: GREEN with client configuration removed and Hosts disabled.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/product_runtime/test_product_task_query_v2.py tests/product_runtime/test_product_task_query_v2_postgres.py tests/product_front_door/test_mcp_product_end_to_end.py -q -vv
```

- [ ] **Step 5: Commit** `feat: project durable cross-host product query`.

---

### Task 15: Prove the complete offline/real-owner Cross-Host Product Vertical matrix

**Files:**
- Create: `tests/product_runtime/test_cross_host_product_e2e.py`
- Create: `tests/product_runtime/test_cross_host_product_stale.py`
- Create: `tests/product_runtime/test_cross_host_product_authorization.py`
- Create: `tests/product_runtime/test_cross_host_product_recovery.py`
- Create: `tests/product_runtime/test_cross_host_product_query.py`
- Modify: `tests/product_runtime/conftest.py`

**Required real owners:** ProductTask PostgreSQL accepted-input/start gate, proposal-decision PostgreSQL owner, LangGraph PostgreSQL checkpointer, PostgreSQL workflow artifact store, real semantic reconstruction/Impact/ChangeSet/Scope/Materialization/Execution Planning/Provider Binding/Gateway, PostgreSQL Saga + dispatch intents + evidence store, real ScopeComparator/SemanticVerifier/convergence and the production/reference V2 composition. Allowed doubles are external Host transport behavior, deterministic clocks/ids and explicit failure injection only.

- [ ] **Step 1: Freeze the scenario matrix in tests before implementation cleanup.**

Mandatory cases:
  - V1 request/hash/replay compatibility and strict V2 discrimination.
  - client binding → server takeover; restart without client SQLite.
  - same-task version/body/binding conflict.
  - immutable proposal subject; Gate A both winner orders; Gate B drift; new task required.
  - metadata-only acquisition changes accepted.
  - two independent PlanningSnapshots; exact two-member SnapshotSet; missing/extra/duplicate failure; dual RevisionBarrier.
  - V2 policy default deny; V1 policy cannot authorize V2.
  - exact binding/grant manifest coverage + durable restart + corrupt/partial manifest fail closed.
  - one ProductTask/plan/Saga with two slices.
  - multiple unresolved dispatch recovery classification; restart never unconditional execute/readiness/re-admission.
  - evidence body-before-reference and offline GET.
  - `PARTIALLY_COMMITTED`, `DIVERGED`, `RECOVERY_REQUIRED`.

- [ ] **Step 2: Add happy-path real-owner test.**

```python
def test_cross_host_product_happy_path_one_task_one_saga_two_reads_300_converged(): ...
```

Assert AutoCAD then Revit ordering, one logical mutation each, independent exact-revision READ on both, Saga `SUCCEEDED`, convergence `CONVERGED`, V2 GET measured 300 mm on both.

- [ ] **Step 3: Add stale/authorization/recovery/query suites** matching the matrix; every pre-execution deny/stale case asserts zero ProductTask Host mutation.

- [ ] **Step 4: Run the full PostgreSQL gate.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest   tests/product_runtime/test_cross_host_product_e2e.py   tests/product_runtime/test_cross_host_product_stale.py   tests/product_runtime/test_cross_host_product_authorization.py   tests/product_runtime/test_cross_host_product_recovery.py   tests/product_runtime/test_cross_host_product_query.py -q -vv
```

- [ ] **Step 5: Run predecessor regressions.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/product_front_door/test_mcp_product_end_to_end.py tests/product_runtime/test_revit_wall_thickness_product_e2e.py tests/orchestrator/test_real_owner_workflow_end_to_end.py tests/orchestrator/test_task10_durable_recovery.py tests/execution_reconciliation/test_step33_v2_local_reconciliation.py tests/execution_coordination/test_phase_i_materialized_success.py tests/execution_coordination/test_phase_i_materialized_partial_commit.py tests/execution_coordination/test_phase_i_materialized_unknown_commit.py -q -vv
```

- [ ] **Step 6: Ruff** — capability-new files absolute clean; touched legacy directories no-new-diagnostics relative to the Task starting SHA.

```bash
uv run ruff check platform/product_runtime platform/product_front_door platform/orchestrator platform/execution_reconciliation platform/execution_coordination hosts/autocad/sidecar tests/product_runtime tests/product_front_door tests/orchestrator tests/execution_reconciliation tests/execution_coordination
```

- [ ] **Step 7: Commit** `test: prove cross-host product vertical offline`.

---

### Task 16: Add all four mandatory controlled live cases, runbook and dedicated CI collection gate

**Files:**
- Create: `tests/integration/test_cross_host_product_vertical_live.py`
- Create: `docs/runbooks/cross-host-product-vertical.md`
- Create: `.github/workflows/cross-host-product-vertical.yml`

**Interfaces:**
- Live entry goes through real model invocation → MCP → ProductTask → explicit human ACCEPT.
- Production adapters are used for both Hosts; Phase I test helper execution classes are not imported.
- Controlled fixture identities/hashes, plugin build identities and loaded DLL identities are recorded secret-free.

- [ ] **Step 1: Implement live Case 1 — policy deny.**

Real proposal + human ACCEPT → V2 policy deny; assert zero execution authority effect, zero ProductTask Host mutation and independent reads still baseline.

- [ ] **Step 2: Implement live Case 2 — one required Host unavailable before execution.**

Make one REQUIRED Host unavailable after proposal preparation and before governed execution; assert zero mutation on the available Host and no REQUIRED→OPTIONAL downgrade.

- [ ] **Step 3: Implement live Case 3 — positive cross-Host execution.**

Assert one task, one Saga, two required slices, one authorized mutation per Host, each Host advances on its own revision lineage, independent READ 300 mm on both, `CONVERGED`, exact-task MCP GET `SUCCEEDED`.

- [ ] **Step 4: Implement live Case 4 — controlled partial commit with the frozen timing.**

After all-required readiness and AutoCAD ProductTask commit 300 mm, perform a separately identified legal Revit edit 200→201 mm; then ProductTask Revit execution must fail `REVISION_CONFLICT/BEFORE_COMMIT`. Assert `PARTIALLY_COMMITTED`, no Revit ProductTask ActualDelta, no convergence success and no compensation.

- [ ] **Step 5: Write runbook and evidence manifest instructions.**

Record reset procedure, fixture SHA-256, AutoCAD/Revit plugin/build identities, exact implementation HEAD, request/binding/topology hashes, proposal/pause/decision, planning/ChangeSet/scope/policy/Grant/manifests, saga/dispatch revisions/evidence and final MCP GET.

- [ ] **Step 6: Dedicated workflow.**

The workflow must collect the live test with live flags off, run the complete Task 15 PostgreSQL matrix, relevant sidecar/unit suites and repository Ruff delta semantics. Actual controlled live execution remains an explicit environment gate.

```bash
uv run pytest tests/integration/test_cross_host_product_vertical_live.py --collect-only -q
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/product_runtime/test_cross_host_product_e2e.py tests/product_runtime/test_cross_host_product_stale.py tests/product_runtime/test_cross_host_product_authorization.py tests/product_runtime/test_cross_host_product_recovery.py tests/product_runtime/test_cross_host_product_query.py -q -vv
```

- [ ] **Step 7: Execute the controlled live gate from the runbook.**

```bash
DSP_CROSS_HOST_PRODUCT_LIVE=1 uv run pytest tests/integration/test_cross_host_product_vertical_live.py -q -vv
```

Expected: all four controlled cases pass on the same implementation SHA and emit the required secret-free evidence manifest.

- [ ] **Step 8: Commit** `test: add controlled cross-host product acceptance`.

---

### Task 17: Exact-head verification, independent review, merge and lifecycle closeout

**Files:**
- Modify: `README.md` only after Task 15 offline and Task 16 four-case live evidence are GREEN.
- Modify: `docs/superpowers/README.md` only after merged-main verification when closing lifecycle.
- No production file changes are allowed after final implementation evidence is pinned without restarting the exact-head gate.

- [ ] **Step 1: Scope audit before final implementation commit.**

Confirm no V1 hash rewrite, new Saga state/transition, manifest-as-authorization, coordinator manifest knowledge, recovery-through-unconditional-`execute()`, GET readiness/admission/mutation, newer-revision evidence acceptance, automatic compensation or production import of Phase I helpers.

- [ ] **Step 2: Create and push FINAL_SHA.**

Record exact branch SHA after the final implementation/README commit and verify the remote branch points to the same SHA.

- [ ] **Step 3: Run exact-head local gates on FINAL_SHA.**

```bash
uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest tests/product_runtime/test_cross_host_product_e2e.py tests/product_runtime/test_cross_host_product_stale.py tests/product_runtime/test_cross_host_product_authorization.py tests/product_runtime/test_cross_host_product_recovery.py tests/product_runtime/test_cross_host_product_query.py -q -vv
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
uv run pytest hosts/autocad/sidecar -q
uv run ruff check platform hosts/autocad/sidecar hosts/revit/sidecar tests
```

Also run the Task 16 controlled live command from the runbook against the same FINAL_SHA.

- [ ] **Step 4: Require exact-head GitHub Actions GREEN.**

Require `cross-host-product-vertical.yml`, Repository Regression, Durable Persistence and Workflow Orchestrator PostgreSQL on the same FINAL_SHA. Record run IDs/URLs outside the branch; do not commit generated evidence back after pinning.

- [ ] **Step 5: Independent whole-branch review.**

Reviewer checks the approved Spec authority `dc2b20cc…`, this approved plan, scope diff, all stop-and-amend triggers, exact-head CI and four controlled live cases. Any P1/P2 finding reopens implementation before merge.

- [ ] **Step 6: Open/merge PR through normal policy and observe merged-main.**

Merge only the reviewed FINAL_SHA. Then require the relevant workflows on the merge commit to complete successfully.

- [ ] **Step 7: Lifecycle closeout.**

Only after merged-main GREEN update `docs/superpowers/README.md` so Cross-Host Product Vertical moves from CURRENT to COMPLETED and the repository summary names the next state truthfully. Closeout itself is docs-only and gets its own merged-main observation.

---

## Acceptance Matrix

| Proof | Required evidence |
| --- | --- |
| V1 compatibility | unchanged V1 request/hash/persisted-row/MCP/single-Revit behavior |
| V2 input | explicit version, exact Revit initiator, exact binding hash/action/intent |
| Client freeze | SQLite atomically stores V2 request + exact two-member binding |
| Server takeover | PostgreSQL atomically owns request + binding before workflow start |
| Restart | server resumes without client SQLite and without latest/reverse lookup |
| Proposal | durable subject binds exact request/binding/topology/op/args/two observations |
| Gate A | stale/ACCEPT race has one winner; stale is not REJECT |
| Gate B | ACCEPT history preserved; later drift makes old task non-continuable |
| Stable comparison | metadata-only acquisition differences do not stale stable state |
| Planning | independent Revit + AutoCAD snapshots in exact two-member SnapshotSet |
| Revision | dual-member barrier plus native Host guards |
| Policy | explicit V2 stable config; transient runtime identity excluded; replay uses durable policy snapshot body |
| Binding manifest | exact required Slice coverage; original binding refs only |
| Grant manifest | exact required Slice coverage; original Grant refs only |
| Forward execution | complete collections resolved/validated before first mutation |
| Recovery | Saga/dispatch truth first; no unconditional readiness/re-admission/execute |
| Multi unresolved | any unresolved required Slice forces recover-or-wait |
| AutoCAD | production dispatcher/readiness/fact/read path; no test-helper dependency |
| Verification | independent exact-revision READ on each committed Host |
| Evidence durability | body-before-reference; same hash replay; corruption detected |
| Query | explicit V2 view, durable measured values, Hosts may be offline |
| Partial commit | AutoCAD committed; Revit BEFORE_COMMIT after controlled external edit |
| Convergence | only verified local effects may produce CONVERGED/SUCCEEDED |
| Live deny | policy deny after ACCEPT causes zero ProductTask mutations |
| Live unavailable | required Host unavailable before execution causes zero mutation elsewhere |
| Live success | one task/Saga, two mutations, two 300 mm reads, CONVERGED, GET SUCCEEDED |
| Live partial | exact frozen timing, PARTIALLY_COMMITTED, no fake Revit delta/compensation |
| Closeout | exact implementation HEAD → review/CI/live → merge → merged-main GREEN → lifecycle |

## Stop-and-Amend Triggers

Implementation stops and returns to Written Spec / Plan review if any of the following becomes necessary:

1. adding a Saga state/transition to represent evidence unavailability or multi-slice recovery;
2. putting mutable Host/native/revision authority into the ProductTask request instead of accepted binding/planning owners;
3. accepting a newer Host revision or mutation response as verification evidence;
4. moving workflow manifests into Gateway/provider/coordinator ownership or treating manifests as authorization;
5. issuing readiness, re-admission or mutation from read-only GET/reconstruction;
6. replaying an existing dispatch through normal forward `execute()` merely because composition restarted;
7. changing V1 request/hash/wire semantics to make V2 easier;
8. importing Phase I test helpers into production AutoCAD/Revit product code;
9. weakening exact two-member required topology or introducing arbitrary N-Host behavior;
10. requiring client SQLite after server accepted-input takeover.

---

## Written-Plan Review Gate

This document authorizes no production implementation by itself. Before Task 1 starts, Written-Plan Review must confirm:

- every approved Spec §1–§10 requirement maps to a Task above;
- the proposed new public interfaces are sufficient and do not create duplicate authority;
- V1 compatibility and lifecycle semantics remain explicit;
- the four controlled live cases remain mandatory;
- no Task silently expands into generic N-Host/platform redesign;
- the execution method is explicitly selected.

After approval, implementation starts from an isolated worktree created with `superpowers:using-git-worktrees`, then uses `superpowers:subagent-driven-development` or `superpowers:executing-plans` as selected.
