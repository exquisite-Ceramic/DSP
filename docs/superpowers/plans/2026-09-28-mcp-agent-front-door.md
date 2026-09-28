# MCP / Agent Front Door Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every production-code task is strict TDD RED → GREEN → focused verification → exact-head verification → commit; do not collapse gates.

**Goal:** Deliver one reproducible local MCP / Agent front door for the existing Revit selected-wall thickness product vertical, from real natural language through explicit operation-proposal HITL, configured-policy execution admission, real MCP and real Revit verification.
**Architecture:** Add a source-only front-door application layer around the existing ProductTask / ProductFlow / Workflow / Gateway / Saga owners; keep client delivery state, create-once SessionBinding authority and execution approval evidence separate from existing business truth.
**Tech Stack:** Python 3.11, SQLite 3, PostgreSQL 17 + psycopg 3, LangGraph, MCP SDK 2.2 Streamable HTTP, Revit named-pipe sidecar, pytest, Ruff.
**Spec:** `docs/superpowers/specs/2026-09-28-mcp-agent-front-door-design.md`
**Status:** Written implementation plan — pending review
**Date:** 2026-09-28
**Plan source base:** `architecture/mcp-agent-front-door@41247215ca4dc70d62e17577a68bfadc5fa1ec5c`
**Workflow authority:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`
**Persistence authority:** `docs/adr/ADR-008-durable-state-persistence-ownership.md`
**Delivery/recovery authority:** `docs/adr/ADR-009-cross-owner-delivery-crash-recovery.md`

## Goal

交付第一个可复现的 DSP MCP / Agent 产品前门：用户从真实自然语言开始，经受约束的真实模型解释、durable client submission correlation、不可变 Revit SessionBinding、real MCP submit/get/operation-proposal resume、真实 configured-policy `ApprovalAdmission`、既有 Gateway/Workflow/Saga、真实 Revit mutation 与独立验证，最终以同一 `task_id` 返回 authoritative product outcome。

本计划不建立第二套 workflow、第二套 ProductTask owner、第二套 approval owner，也不把 MCP、LLM、client outbox 或本机配置提升为业务真相。既有 ProductTask request、LangGraph workflow、Gateway V2、Execution Saga、Reconciliation 与 Revit Host evidence 的 owner 关系保持不变。

## Architecture

```text
Repository-owned reference client
  -> local SQLite application database
       client_submission / delivery state      [Submission Controller-owned]
       immutable SessionBinding                 [create-once session authority]
       exact frozen ProductTaskRequest copy     [delivery payload only]
  -> constrained AgentInterpreterPort
       natural language -> normalized proposal only
  -> real MCP client
       product.wall_thickness.submit
       product.wall_thickness.get
       product.wall_thickness.resume_operation_proposal

Product Front Door MCP [thin source-only application adapter]
  -> read-only SessionBindingReadPort
       (never reads/writes client delivery rows)
  -> exact request/session validation
  -> host-independent ProductTask query service
  -> exact-session Revit product composition factory
       -> WallThicknessProductFlow
       -> LangGraphWorkflowRuntime
       -> CanonicalWorkflowOwnerPorts
       -> ConfiguredPolicyApprovalAdmissionPort
            -> exact final ChangeSet + ApprovalScope
            -> durable admission issuance evidence
            -> ApprovalAdmission
       -> GatewayAuthorizationServiceV2
       -> existing execution/reconciliation owners
       -> real Revit Host

Query path:
  ProductTaskRequest owner
  + read-only LangGraph checkpoint reader
  + Saga owner
  -> ProductTaskQueryView
  -> no SessionBinding / Host dependency
  -> no workflow progression
```

The new front-door application code is source-only, matching the existing Product Runtime precedent:

```text
platform/product_front_door/src/design_product_front_door/
```

It may import public Product Runtime, orchestrator, Gateway and Revit-sidecar contracts. Generic orchestrator/Gateway packages MUST NOT import `design_product_front_door` or Revit-specific front-door policy/configuration.

## Source Census Decisions Frozen by This Plan

1. `WallThicknessProductFlow.submit()` currently persists the immutable request before `get_checkpoint()` / `start()`. The crash window remains intentional and is closed by replay plus a PostgreSQL first-start serialization gate, not by reversing the order.
2. Current `WallThicknessProductFlow.get()` cannot distinguish no request from persisted-request/no-checkpoint. A new read-only query service will join the immutable request owner and checkpoint owner with a stabilization re-read; the existing `get()` compatibility behavior is not used as the MCP truth surface.
3. Query consistency uses `request read -> checkpoint read -> conditional request re-read`. If the first request read is absent but a checkpoint appears, the request is re-read before declaring corruption. This prevents a concurrent submit between the first two reads from producing a false lineage violation.
4. One local SQLite application database physically holds two different logical responsibilities: `client_submission` is client delivery/recovery state owned by the Submission Controller, while `session_binding` is the create-once application SessionBinding authority. The Product Front Door server receives only a narrow read-only `SessionBindingReadPort`; it never reads or mutates client outbox/delivery rows. Server ProductTask/workflow/Saga truth stays in existing PostgreSQL owners.
5. A SessionBinding is host/document identity evidence, not ProductTask business truth. The configured candidate key and target constraint are deterministic application/environment configuration; they are never generated by the model or copied into the ProductTask body as model facts. Endpoint/pipe name is only a locator.
6. Candidate issuance reuses the existing `context.current_selection` READ. No new Revit native command is added merely for discovery.
7. The mandatory reference execution-approval path is synchronous configured policy. Operation-proposal acceptance never creates `ApprovalAdmission`.
8. Configured policy admission persists the exact first-issued `ApprovalAdmission` body so retry/rebuild returns the same admission identity, policy evidence and times without re-reading the current clock or silently re-evaluating a changed policy.
9. Gateway store semantics remain strict consume-once. A narrow Gateway V2 `consume_or_get_approval()` recovery API may return the already-consumed exact ApprovalRecord only when the `admission_id + admission_fingerprint` lineage matches and the current authoritative ChangeSet/scope still validates; different authority content remains conflict.
10. The reference composition is extracted from reviewed production-owner wiring currently living in product acceptance fixtures. Test-only fixed approval data is not moved into production.
11. Model output may choose only the supported intent value and configured candidate key. `project_id`, `host_kind`, task/session identity, request hash, `pause_id`, human resume action and policy approval are deterministic/controller-owned.
12. The repository-owned reference client uses an external configured model command through a strict JSON stdin/stdout adapter. This avoids making one model vendor SDK an architectural owner while still requiring a real model command for mandatory live acceptance.
13. Product Front Door binds loopback only and performs exact-id lookup only. `task_id` is a locator, not a credential.
14. The final mandatory capability gate is an interactive controlled live run, not ordinary CI: real model, real MCP transport, explicit human operation-proposal decision, real configured policy admission, real Revit mutation and independent verification must all be evidenced on one task lineage.

## Global Constraints

- Design baseline is exactly `41247215ca4dc70d62e17577a68bfadc5fa1ec5c`; do not silently amend the approved Spec during implementation.
- `client_submission_ref` is client delivery identity only; `ProductTaskRequest.task_id` remains the server business identity.
- One correlation can freeze at most one complete request. Same normalized proposal replays the winner; conflicting normalized proposal fails closed.
- Generated `task_id`, `session_ref`, request hash, timestamps and delivery counters are never callback-equivalence inputs.
- Complete frozen request + correlation association must be durable before first MCP send.
- Same `session_ref` resolves to the exact immutable binding body or fails; it is never rebound after Host restart/document change.
- Product Front Door code may read SessionBinding through the narrow resolver but MUST NOT read/write `client_submission` delivery state; the reference client/controller remains the only delivery-state writer.
- Durable v1 SessionBinding supports saved Revit documents only. Unsaved title-only documents fail before freeze.
- Endpoint/PID equality is not Host identity. Every Host-bound submit/resume path performs fresh runtime/document validation against the binding.
- Read-only exact `get(task_id)` must work with Revit offline and must never resolve SessionBinding merely to answer the query, start/resume/poll workflow work or resend Host mutation.
- Request exists / checkpoint absent is a first-class query fact, not not-found.
- Checkpoint exists / request absent is a fail-closed lineage error only after the stabilization re-read.
- Operation-proposal `OPERATION_PROPOSAL_ACCEPTED` authorizes continuation to binding/Impact/ChangeSet only. It never means execution approval.
- Configured policy admission evaluates the final immutable ChangeSet + ApprovalScope and defaults to deny on first issuance when policy material is missing/invalid/mismatched.
- Once an exact `ApprovalAdmission` has been durably issued, replay returns that immutable evidence until it expires or is consumed; changing/removing the local policy file does not rewrite the already-issued body. This is issuance replay, not a new approval lifecycle or revocation system.
- Local configured principal is audit/policy identity inside the same-workstation trust boundary only; it is not enterprise authentication.
- Mandatory reference/live composition must not use `_ApprovalAdmissionBoundary` or equivalent hard-coded approver/hash/time fixture data.
- `compute_admission_fingerprint()` remains the only admission fingerprint algorithm; no front-door copy is permitted.
- Existing Gateway remains approval/grant authority; existing SemanticVerifier/Reconciliation/Saga remain effect/outcome authority.
- Unknown Host outcome never authorizes blind mutation resend.
- No broad task list/search surface, generic Agent shell, generic ProductIntentIngress, multi-Host scheduler, remote auth, multi-tenant identity or generalized approval inbox is added.
- New Python production code and code comments/docstrings must be complete Chinese comments consistent with repository style.
- Every task ends with an independent commit. The next task starts only from the previous task's exact GREEN HEAD.

## Review Focus

1. **Request/checkpoint read race:** a request committed between query reads must not be misreported as checkpoint-without-request corruption. Task 1 owns the stabilization tests.
2. **Duplicate/concurrent freeze:** duplicate callback, concurrent same proposal, concurrent conflicting proposal and crash/reopen must publish one binding/request winner only. Tasks 3–4 own these tests.
3. **Approval replay window:** configured policy replay must return the same admission body; consume-after-consume recovery must resolve the same ApprovalRecord without weakening expiry/conflict semantics. Task 5 owns these tests.
4. **Host identity drift:** endpoint reuse, Host restart, active-document switch and unsaved document must block new Host-bound work while exact task query remains available. Tasks 3, 6, 7, 9 and 10 own these tests.
5. **Authority separation:** model cannot perform human resume or create approval; operation-proposal acceptance without policy admission must produce zero Host mutation. Tasks 7–10 own these tests.

## Ruff Gate Policy

The repository contains historical Ruff diagnostics. Use the repository-regression no-new-diagnostics policy for any pre-existing Python directory. New-only paths may use absolute Ruff.

For legacy paths:

```bash
BASE_SHA="$(git merge-base HEAD origin/main)"
# 使用 HEAD 的 Ruff 同时扫描 BASE/HEAD，并比较规范化 (filename, code, message) multiset。
# 只有 head - base == 0 才算 GREEN；不得借本阶段批量清理历史诊断。
```

Final GitHub `Repository regression` on the exact final SHA is authoritative.

---

# Implementation Tasks

## Task 1: Add host-independent ProductTask query semantics with race stabilization

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_runtime.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Modify: `platform/product_runtime/src/design_product_runtime/contracts.py`
- Create: `platform/product_runtime/src/design_product_runtime/query.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Create: `tests/orchestrator/test_checkpoint_reader.py`
- Create: `tests/product_runtime/test_product_task_query.py`
- Create: `tests/product_runtime/test_product_task_query_postgres.py`

**Interfaces:**

```python
class LangGraphWorkflowCheckpointReader:
    """只读 checkpoint adapter；构造时不需要 WorkflowServices，也不编译可执行 graph。"""

    def __init__(self, *, checkpointer) -> None: ...
    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None: ...


class ProductTaskQueryState(str, Enum):
    """Front Door 需要区分的 durable task 查询事实。"""

    ACCEPTED_PRE_WORKFLOW = "ACCEPTED_PRE_WORKFLOW"
    WORKFLOW = "WORKFLOW"


@dataclass(frozen=True, slots=True)
class ProductTaskQueryView:
    """只组合既有 owner truth，不持久化第二份任务状态。"""

    task_id: str
    request_hash: str
    state: ProductTaskQueryState
    flow: ProductFlowView | None


class ProductTaskQueryService:
    def get(self, task_id: str) -> ProductTaskQueryView | None: ...
```

**Query algorithm is normative:**

```text
request_1 = request_store.get(task_id)
checkpoint = checkpoint_reader.get_checkpoint(task_id)

request_1 absent + checkpoint absent
  -> not-found

request_1 present + checkpoint absent
  -> ACCEPTED_PRE_WORKFLOW

request_1 present + checkpoint present
  -> WORKFLOW projection

request_1 absent + checkpoint present
  -> request_2 = request_store.get(task_id)
     request_2 present -> WORKFLOW projection
     request_2 absent  -> PRODUCT_TASK_LINEAGE_INVALID
```

- [ ] **Step 1: RED the read-only checkpoint adapter.** Test exact checkpoint projection from a real checkpointer without constructing `WorkflowServices`; missing task returns `None`; corrupt checkpoint still fails with existing `WORKFLOW_CHECKPOINT_INVALID`.
- [ ] **Step 2: Run RED.**

```bash
uv run pytest tests/orchestrator/test_checkpoint_reader.py -q -vv
```

- [ ] **Step 3: Implement `LangGraphWorkflowCheckpointReader` by reusing the existing `_checkpoint_lookup_config` / `_checkpoint_from_snapshot` logic.** Do not duplicate checkpoint decoding in Product Runtime.
- [ ] **Step 4: RED the four query rows plus the concurrent-read stabilization case.** Use a scripted request store whose first read returns `None`, checkpoint read commits/observes the request, and second request read returns the exact request. Assert `WORKFLOW`, not lineage failure.
- [ ] **Step 5: Implement `ProductTaskQueryService`.** Share the existing ProductFlow status projection logic rather than copy Saga terminal/recovery rules; extract one public/internal helper if required.
- [ ] **Step 6: Add PostgreSQL query acceptance.** Persist request without workflow and prove `ACCEPTED_PRE_WORKFLOW`; then start workflow and prove `WORKFLOW`; delete/corrupt the request row under an existing checkpoint only inside an isolated integrity-test fixture and prove the stabilized read fails with `PRODUCT_TASK_LINEAGE_INVALID` rather than reconstructing request truth from checkpoint data.
- [ ] **Step 7: GREEN.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/orchestrator/test_checkpoint_reader.py \
  tests/product_runtime/test_product_task_query.py \
  tests/product_runtime/test_product_task_query_postgres.py -q -vv
```

- [ ] **Step 8: Ruff delta + commit.**

```bash
git commit -m "feat: add race-safe product task query"
```

---

## Task 2: Serialize concurrent first workflow start with a PostgreSQL task gate

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/start_gate.py`
- Create: `platform/product_runtime/src/design_product_runtime/postgres_start_gate.py`
- Modify: `platform/product_runtime/src/design_product_runtime/wall_thickness_flow.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Modify: `tests/product_runtime/test_wall_thickness_flow.py`
- Create: `tests/product_runtime/test_product_task_start_gate_postgres.py`
- Update composition fixtures that construct `WallThicknessProductFlow`.

**Interfaces:**

```python
class ProductTaskStartGate(Protocol):
    """只串行化同 task 的 checkpoint-missing -> start 临界区。"""

    @contextmanager
    def serialize(self, task_id: str) -> Iterator[None]: ...


class PostgresProductTaskStartGate:
    def serialize(self, task_id: str) -> Iterator[None]: ...
    def close(self) -> None: ...
```

The owner table is `product_task.start_gate(task_id TEXT PRIMARY KEY)`. `serialize()` must create/ensure the row and hold an exact-task PostgreSQL row lock for the entire `get_checkpoint() -> possible start()` critical section. The implementation uses a database transaction plus `INSERT ... ON CONFLICT DO NOTHING` / `SELECT ... FOR UPDATE`; correctness must not depend on a Python lock. `WallThicknessProductFlow.submit()` enters this gate only after immutable request `create()` succeeds.

- [ ] **Step 1: RED two independent gate instances on separate PostgreSQL connections.** Use a barrier so both callers attempt the same task concurrently; prove only one holder enters the critical section at a time.
- [ ] **Step 2: Implement the row-lock gate.** No Python `Lock`, singleton, process mutex or advisory in-memory state.
- [ ] **Step 3: RED `WallThicknessProductFlow.submit()` with two facade instances sharing the same durable request/checkpoint owners.** Assert one effective `start()` call / workflow lineage and identical returned task identity.
- [ ] **Step 4: Implement gate injection and migrate all product-runtime composition tests.** The gate is required in production/reference composition; tests may use a tiny deterministic fake gate only when they are not proving concurrency.
- [ ] **Step 5: Prove crash release.** Terminate/close one gate connection while holding the DB transaction and prove a fresh gate can acquire the same task and continue from persisted request/checkpoint facts.
- [ ] **Step 6: GREEN + Ruff delta + commit.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_wall_thickness_flow.py \
  tests/product_runtime/test_product_task_start_gate_postgres.py -q -vv
git commit -m "feat: serialize first product workflow start"
```

---

## Task 3: Add configured Revit candidate discovery and immutable SessionBinding contracts

**Files:**
- Modify: `hosts/revit/sidecar/src/revit_sidecar/context.py`
- Modify: `hosts/revit/sidecar/src/revit_sidecar/__init__.py`
- Create: `platform/product_front_door/src/design_product_front_door/__init__.py`
- Create: `platform/product_front_door/src/design_product_front_door/contracts.py`
- Create: `platform/product_front_door/src/design_product_front_door/candidate_config.py`
- Modify: `pyproject.toml` to add `platform/product_front_door/src` to pytest `pythonpath` only; do not make a new workspace distribution in this task.
- Create: `tests/revit_sidecar/test_context_discovery.py`
- Create: `tests/product_front_door/test_contracts.py`
- Create: `tests/product_front_door/test_candidate_config.py`

**Reference candidate configuration:**

```json
{
  "version": "DSP_REVIT_CANDIDATES_V1",
  "candidates": [
    {
      "candidate_key": "primary-revit",
      "project_id": "project-id",
      "transport_locator": "DSP.Revit.AgentHost.<machine>.<pid>",
      "document_id": "C:\\path\\to\\fixture.rvt",
      "semantic_target_id": "WALL-001",
      "native_target_unique_id": "reviewed-wall-unique-id"
    }
  ]
}
```

`semantic_target_id` / `native_target_unique_id` are environment-owned configured target constraints used to validate the authoritative Host selection and seed the existing product composition identity environment. They are not model output and never enter `ProductTaskRequest` as client-authoritative target identity.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ConfiguredRevitCandidate:
    """确定性的本机候选配置；pipe 是 locator，target constraint 不是 ProductTask body。"""

    candidate_key: str
    project_id: str
    transport_locator: str
    document_id: str
    semantic_target_id: str
    native_target_unique_id: str


class ConfiguredRevitCandidateSource(Protocol):
    """按确定性 candidate key 读取本机应用配置。"""

    def get(self, candidate_key: str) -> ConfiguredRevitCandidate | None: ...


class JsonConfiguredRevitCandidateSource:
    def get(self, candidate_key: str) -> ConfiguredRevitCandidate | None: ...


@dataclass(frozen=True, slots=True)
class SessionBinding:
    """一次 create-once Revit runtime/document binding。"""

    session_ref: str
    project_id: str
    host_kind: str
    candidate_key: str
    transport_locator: str
    host_instance_id: str
    document_id: str
    document_title: str
    binding_hash: str


class RevitCurrentContextProbe:
    def discover(self, *, command_id: str, document_id: str) -> RevitContextObservation: ...
```

`SessionBinding.binding_hash` commits exactly the immutable binding body except the hash itself. Saved-document validation accepts Windows drive/UNC or POSIX absolute path forms and rejects title-only identifiers.

- [ ] **Step 1: RED the new discovery adapter.** Assert it sends existing `context.current_selection`, mode `READ`, validates requested `document_id`, accepts the returned `host_instance_id`, and rejects Host error/document mismatch/malformed identity.
- [ ] **Step 2: Refactor the existing context response parser so strict `RevitContextReadPort` and discovery share validation without weakening the strict expected-host check.**
- [ ] **Step 3: RED candidate config + `SessionBinding`.** Reject unknown config version, duplicate candidate key, blank fields, title-only document, malformed binding hash and hash/body mismatch.
- [ ] **Step 4: Implement `JsonConfiguredRevitCandidateSource`, canonical binding hash and exports.** Config file contents are deterministic application/environment configuration; endpoint/PID is never identity proof.
- [ ] **Step 5: GREEN + Ruff delta + commit.**

```bash
uv run pytest \
  tests/revit_sidecar/test_context_discovery.py \
  tests/product_front_door/test_contracts.py \
  tests/product_front_door/test_candidate_config.py -q -vv
git commit -m "feat: add immutable Revit session binding"
```

---

## Task 4: Implement durable SQLite correlation, atomic freeze, session authority and outbox

**Files:**
- Create: `platform/product_front_door/src/design_product_front_door/sqlite_state.py`
- Create: `platform/product_front_door/src/design_product_front_door/submission_controller.py`
- Create: `platform/product_front_door/src/design_product_front_door/agent.py`
- Modify: `platform/product_front_door/src/design_product_front_door/__init__.py`
- Create: `tests/product_front_door/test_sqlite_state.py`
- Create: `tests/product_front_door/test_submission_controller.py`
- Create: `tests/product_front_door/test_agent.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class NormalizedFreezeProposal:
    """只包含生成 identity 之前就存在的确定性输入。"""

    project_id: str
    host_kind: str
    requested_action: str
    intent_arguments: Mapping[str, object]
    candidate_key: str


@dataclass(frozen=True, slots=True)
class FrozenSubmission:
    client_submission_ref: str
    proposal_hash: str
    session_binding: SessionBinding
    request: ProductTaskRequest
    delivery_state: str


class SessionBindingReadPort(Protocol):
    """服务端只读 session authority；不暴露 client delivery mutation。"""

    def resolve_session(self, session_ref: str) -> SessionBinding | None: ...


class SqliteFrontDoorStateStore:
    def create_correlation(self, client_submission_ref: str) -> None: ...
    def get_submission(self, client_submission_ref: str) -> FrozenSubmission | None: ...
    def freeze_submission(
        self,
        *,
        client_submission_ref: str,
        proposal: NormalizedFreezeProposal,
        binding: SessionBinding,
        request: ProductTaskRequest,
    ) -> FrozenSubmission: ...
    def resolve_session(self, session_ref: str) -> SessionBinding | None: ...
    def mark_delivery(self, client_submission_ref: str, state: str) -> FrozenSubmission: ...
    def close(self) -> None: ...


class SqliteSessionBindingReader:
    """以只读连接实现服务端 SessionBindingReadPort。"""

    def resolve_session(self, session_ref: str) -> SessionBinding | None: ...
    def close(self) -> None: ...


class AgentInterpreterPort(Protocol):
    def interpret(self, *, client_submission_ref: str, utterance: str) -> Mapping[str, object]: ...


class SubprocessAgentInterpreter:
    """真实模型可通过受控外部命令接入；stdout 只能是 proposal JSON。"""

    def interpret(self, *, client_submission_ref: str, utterance: str) -> Mapping[str, object]: ...
```

The same physical SQLite database has two logical tables/owners:

```text
client_submission   # client delivery/recovery state; controller read/write
session_binding     # create-once application session authority; server read-only
```

Use `BEGIN IMMEDIATE`, foreign keys and uniqueness constraints. The successful freeze transaction must insert the winning SessionBinding, persist the exact ProductTask delivery payload/hash under the correlation and transition to `DELIVERY_PENDING` atomically. A losing tentative binding/request is never persisted. `SqliteSessionBindingReader` opens the same committed database read-only and cannot update `client_submission`.

- [ ] **Step 1: RED correlation-before-model and freeze-after-model ordering.** Creating a correlation writes no task/session/request identity.
- [ ] **Step 2: RED same-correlation replay.** After freeze, the controller reloads the winner before invoking candidate probe or ID factories; identical proposal returns the exact winner; conflicting proposal raises `FRONT_DOOR_CORRELATION_CONFLICT`.
- [ ] **Step 3: RED concurrent same proposal and concurrent conflicting proposal with two independent SQLite connections.** Assert exactly one persisted `task_id`, one `session_ref`, one request payload and one binding row.
- [ ] **Step 4: RED crash/reopen.** Close the process immediately after freeze commit; new store instance returns byte-equivalent request/binding and `DELIVERY_PENDING`; separate read-only session reader resolves the same binding.
- [ ] **Step 5: Implement SQLite schema/transactions and deterministic proposal hash.** Generated IDs may be tentative before the transaction, but only the committed winner has authority.
- [ ] **Step 6: Implement `SubmissionController`.** It loads the correlation first, resolves deterministic candidate configuration, calls `RevitCurrentContextProbe`, requires the fresh Host document plus exactly the configured selected Wall target, creates `SessionBinding` + `ProductTaskRequest`, then competes to freeze once.
- [ ] **Step 7: RED/implement strict subprocess Agent adapter.** stdin JSON contains only correlation + natural language; stdout may return only supported thickness/candidate proposal fields. Reject attempts to output `project_id`, `host_kind`, `task_id`, `session_ref`, `pause_id`, resume action, approval/admission fields or unknown keys. The controller derives `project_id/host_kind` from configured candidate/application context.
- [ ] **Step 8: GREEN + absolute Ruff on the new front-door package + commit.**

```bash
uv run pytest \
  tests/product_front_door/test_sqlite_state.py \
  tests/product_front_door/test_submission_controller.py \
  tests/product_front_door/test_agent.py -q -vv
uv run ruff check platform/product_front_door/src/design_product_front_door tests/product_front_door
git commit -m "feat: freeze durable front door submissions"
```

---

## Task 5: Implement real configured-policy ApprovalAdmission with durable replay identity

**Files:**
- Create: `platform/product_front_door/src/design_product_front_door/approval_policy.py`
- Create: `platform/product_front_door/src/design_product_front_door/postgres_admission_store.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/store.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/v2.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/__init__.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Create: `tests/product_front_door/test_approval_policy.py`
- Create: `tests/product_front_door/test_approval_admission_postgres.py`
- Modify/Create focused Gateway V2 tests for replay recovery.
- Modify: `tests/orchestrator/test_real_owner_workflow_end_to_end.py` only where the new idempotent Gateway composition call changes the seam.

**Policy schema:**

```json
{
  "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
  "policy_id": "local-wall-thickness-v1",
  "principal": "local:operator",
  "project_ids": ["project-id"],
  "allowed_canonical_operations": ["set_wall_thickness"],
  "admission_ttl_seconds": 900
}
```

Missing file, malformed schema, empty principal, project mismatch, unknown canonical operation or non-positive TTL is deny/fail-closed for a **new** admission issuance. `policy_snapshot_hash` is canonical SHA-256 of the normalized policy JSON including `version`; it is audit/policy evidence, not an authentication credential.

`product_policy.admission` is a narrow durable issuance record for the configured `ApprovalAdmissionPort`, not a second approval lifecycle owner. Gateway remains the only owner of consumed `ApprovalRecord` / grant authority. The table stores the exact immutable issued admission body (or a canonical JSON payload sufficient to reconstruct it) plus its fingerprint and uses `(changeset_hash, approved_scope_hash)` as the create-once issuance lineage; `admission_id` is unique.

**Interfaces:**

```python
class ConfiguredPolicyApprovalAdmissionPort:
    def request_approval(self, changeset_ref: StableRef) -> ApprovalAdmission: ...


class PostgresConfiguredPolicyAdmissionStore:
    def get(
        self,
        *,
        changeset_hash: str,
        approved_scope_hash: str,
    ) -> ApprovalAdmission | None: ...

    def issue_or_get(self, admission: ApprovalAdmission) -> ApprovalAdmission: ...


class GatewayAuthorizationServiceV2:
    def consume_or_get_approval(
        self,
        request: ApprovalConsumptionRequestV2,
    ) -> ApprovalRecord: ...
```

New issuance ordering is normative:

```text
load exact final ChangeSet + ApprovalScope
-> validate supplied StableRef/hash lineage
-> read existing product_policy.admission by exact ChangeSet/scope
   -> present: validate fingerprint/lineage and return the exact stored admission
   -> absent: load + normalize configured policy
              evaluate exact project/environment/canonical operations
              obtain injected clock + admission id
              construct ApprovalAdmission
              compute fingerprint with existing helper
              issue_or_get under PostgreSQL create-once constraint
              return the durable winner
```

A concurrent loser may have tentative id/time values but must discard them and return the durable winner. A later process rebuild returns the exact original admission body even if the current clock is later; it does not regenerate approval times. If policy material changed before any admission was issued, the new policy is evaluated normally. Once an admission exists for the exact ChangeSet/scope, policy-file changes do not rewrite it; explicit revocation is outside this local v1 admission issuer and remains Gateway lifecycle territory.

Gateway replay ordering is also normative:

```text
consume_or_get_approval(request)
-> validate request type + admission fingerprint integrity
-> validate authoritative ChangeSet/scope integrity + exact joins + least privilege
-> get prior consumption by exact admission_id + fingerprint
   -> present: compare stored ApprovalRecord authority hash/lineage; return stored record
               without re-applying admission expiry to already-consumed authority
   -> absent: call existing consume_approval(request)
              (including admission expiry at first consumption)
```

This preserves the existing Step32 rule that admission expiry applies before first consumption, while an already-consumed durable ApprovalRecord does not become invalid merely because the original admission later expires.

- [ ] **Step 1: RED policy normalization/default deny.** Prove project and complete canonical-operation set must be explicitly allowed; missing/malformed policy cannot issue a new admission.
- [ ] **Step 2: RED first issuance + replay across fresh PostgreSQL store instance.** Inject clock and ID factory; first call persists exact admission; second process rebuild returns the same `admission_id`, policy evidence, `approved_at`, `expires_at` and fingerprint despite a later clock value or unavailable/changed policy file.
- [ ] **Step 3: Implement admission body using final authoritative ChangeSet + final ApprovalScope owner reads.** Validate the supplied `StableRef` hash and boundary lineage before either returning an existing issuance or evaluating a new policy.
- [ ] **Step 4: Compute `ApprovalAdmission.admission_fingerprint` only with `design_gateway_authorization.compute_admission_fingerprint()`.** No duplicate admission hash body in front-door code. Validate the same helper on durable read.
- [ ] **Step 5: RED concurrent issuance.** Two independent PostgreSQL store/port instances race the same exact ChangeSet/scope; one durable admission body wins. Same lineage with incompatible policy authority content fails conflict rather than rewriting the winner.
- [ ] **Step 6: RED Gateway exact replay recovery.** First `consume_or_get_approval()` consumes. A later retry with the same id/fingerprint and an already-expired wall-clock time returns the stored exact ApprovalRecord; same id with a different fingerprint remains conflict. Underlying `consume_admission_once()` remains strict.
- [ ] **Step 7: Add store read seam `get_consumed_approval(admission_id, admission_fingerprint)` and implement `consume_or_get_approval()` with the normative ordering above.** Replay must preserve original stored `consumed_at` and compare the recomputed approval authority hash/lineage before returning it.
- [ ] **Step 8: Switch `CanonicalWorkflowOwnerPorts.request_approval()` to the composition-safe Gateway method.** The adapter still does not interpret policy or compute approval hashes.
- [ ] **Step 9: Negative acceptance:** operation proposal accepted + no issued admission + policy missing/denied/mismatched ⇒ no approval ref, no execution planning/grant, zero Host mutation.
- [ ] **Step 10: GREEN + Ruff delta + commit.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_front_door/test_approval_policy.py \
  tests/product_front_door/test_approval_admission_postgres.py \
  tests/gateway_authorization \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py -q -vv
git commit -m "feat: add configured policy approval admission"
```

---

## Task 6: Extract a production reference Revit product composition factory

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/revit_reference_composition.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Refactor: `tests/product_runtime/conftest.py`
- Refactor: `tests/integration/test_revit_wall_thickness_product_live.py`
- Create: `tests/product_runtime/test_revit_reference_composition.py`
- Modify supporting product-runtime tests only where they currently import production-shaped helpers from `tests.orchestrator`.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class RevitWallThicknessCompositionConfig:
    """一个 exact session 的生产/reference composition 输入；target identity 来自环境配置而非 request。"""

    dsn: str
    project_id: str
    session_ref: str
    document_id: str
    host_instance_id: str
    semantic_target_id: str
    native_target_unique_id: str


@dataclass(slots=True)
class RevitWallThicknessRuntimeComposition:
    flow: WallThicknessProductFlow
    runtime: LangGraphWorkflowRuntime
    request_store: PostgresProductTaskRequestStore
    start_gate: PostgresProductTaskStartGate
    checkpointer: object
    saga_store: object
    gateway_store: object

    def close(self) -> None: ...


def build_revit_wall_thickness_reference_composition(
    *,
    config: RevitWallThicknessCompositionConfig,
    transport: object,
    approval_admission: ApprovalAdmissionPort,
) -> RevitWallThicknessRuntimeComposition: ...
```

- [ ] **Step 1: Census and RED every production-shaped helper currently imported from test modules.** Cover `_topology`, capability profile, materialization routing, provider snapshot factory, clocks and any additional helper discovered at the Task 6 starting HEAD. Each helper used by the mandatory reference path must move to product application composition or be replaced by an existing production public API.
- [ ] **Step 2: Implement the factory by moving composition only, not owner rules.** Existing Impact/Scope/ChangeSet/Planning/Binding/Gateway/Saga/Reconciliation services stay authoritative; environment-owned identity/topology/provider wiring may be assembled here because request/model input does not own it.
- [ ] **Step 3: Prove the factory accepts an injected `approval_admission` and mandatory reference tests pass `ConfiguredPolicyApprovalAdmissionPort`, never `_ApprovalAdmissionBoundary`.**
- [ ] **Step 4: Prove exact binding validation.** Wrong `session_ref`, project, Host runtime, document or configured selected native target fails before Host mutation.
- [ ] **Step 5: Refactor existing product/offline/live tests to consume the factory so production composition and acceptance composition cannot drift independently.**
- [ ] **Step 6: GREEN + Ruff delta + commit.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_revit_reference_composition.py \
  tests/product_runtime/test_revit_wall_thickness_product_e2e.py \
  tests/product_runtime/test_revit_wall_thickness_product_authorization_failures.py -q -vv
git commit -m "refactor: extract Revit product reference composition"
```

---

## Task 7: Add the thin Product Front Door MCP server and exact wire contracts

**Files:**
- Create: `platform/product_front_door/src/design_product_front_door/service.py`
- Create: `platform/product_front_door/src/design_product_front_door/mcp_wire.py`
- Create: `platform/product_front_door/src/design_product_front_door/mcp_server.py`
- Create: `platform/product_front_door/src/design_product_front_door/mcp_transport.py`
- Modify: `platform/product_front_door/src/design_product_front_door/__init__.py`
- Create: `tests/product_front_door/test_service.py`
- Create: `tests/product_front_door/test_mcp_wire.py`
- Create: `tests/product_front_door/test_mcp_server.py`
- Create: `tests/product_front_door/test_mcp_transport.py`

**Frozen MCP tool names:**

```text
product.wall_thickness.submit
product.wall_thickness.get
product.wall_thickness.resume_operation_proposal
```

**Service API:**

```python
class ProductFrontDoorService:
    def submit(self, request: ProductTaskRequest) -> ProductTaskQueryView: ...
    def get(self, task_id: str) -> ProductTaskQueryView | None: ...
    def resume_operation_proposal(
        self,
        *,
        task_id: str,
        pause_id: str,
        resume_kind: str,
    ) -> ProductTaskQueryView: ...
```

The service receives a read-only `SessionBindingReadPort`, `ConfiguredRevitCandidateSource`, host transport factory, host-independent `ProductTaskQueryService` and exact-session composition factory. It does not receive `SqliteFrontDoorStateStore` or any client delivery mutation API.

- [ ] **Step 1: RED exact wire decoding.** Submit accepts only the full frozen ProductTask contract; get accepts exact task id; resume accepts exact task id + pause id + one allowed operation-proposal resume kind and no arbitrary payload.
- [ ] **Step 2: RED host-independent get.** Build the service with an unavailable Revit transport/session target and prove `get()` still returns persisted-pre-workflow/workflow/terminal/recovery facts without opening SessionBinding or Host transport.
- [ ] **Step 3: RED submit binding admission.** Service resolves `request.session_ref` through the read-only session authority, resolves the immutable configured candidate by `candidate_key`, validates project/host kind/document/target configuration, fresh-probes exact Host/document/current selection and requires the bound `host_instance_id` plus configured selected target before obtaining an exact-session composition. Unknown/rebound/restarted Host fails closed.
- [ ] **Step 4: RED resume correlation + live binding validation.** Service first reads current request/checkpoint and exact pending interaction; stale/missing pause, non-`OPERATION_PROPOSAL`, disallowed kind or replay after consumption fails before `runtime.resume()`. Before a valid resume that can continue Host-bound work, re-resolve the same SessionBinding and fresh-probe exact Host/document/selected target; Host unavailable/mismatch blocks resume but does not affect `get()`.
- [ ] **Step 5: Implement thin delegation only.** The MCP server must not allocate correlation/task/session IDs, interpret language, create admission, list tasks or synthesize product status.
- [ ] **Step 6: Implement loopback-only Streamable HTTP transport**, mirroring Semantic MCP safety: accept only `127.0.0.1`, `localhost`, `::1`; default port `8010`; stateless JSON response.
- [ ] **Step 7: Tool-catalog test proves there is no generic approval/admission tool.** The operation-proposal resume tool exists on the server for the deterministic controller, but the Agent interpreter receives neither that tool nor the MCP endpoint/tool catalog.
- [ ] **Step 8: GREEN + absolute Ruff + commit.**

```bash
uv run pytest \
  tests/product_front_door/test_service.py \
  tests/product_front_door/test_mcp_wire.py \
  tests/product_front_door/test_mcp_server.py \
  tests/product_front_door/test_mcp_transport.py -q -vv
uv run ruff check platform/product_front_door/src/design_product_front_door tests/product_front_door
git commit -m "feat: expose product front door over MCP"
```

---

## Task 8: Add the real MCP client and minimal repository-owned reference client

**Files:**
- Create: `platform/product_front_door/src/design_product_front_door/mcp_client.py`
- Create: `platform/product_front_door/src/design_product_front_door/reference_client.py`
- Create: `tests/product_front_door/test_mcp_client.py`
- Create: `tests/product_front_door/test_reference_client.py`

**Interfaces:**

```python
class ProductFrontDoorMcpClient:
    """只通过配置的 Streamable HTTP URL 调用 Product Front Door。"""

    def __init__(self, endpoint_url: str) -> None: ...
    async def submit(self, request: ProductTaskRequest) -> ProductTaskQueryView: ...
    async def get(self, task_id: str) -> ProductTaskQueryView | None: ...
    async def resume_operation_proposal(
        self,
        *,
        task_id: str,
        pause_id: str,
        resume_kind: str,
    ) -> ProductTaskQueryView: ...


class ReferenceClient:
    async def run(self, utterance: str) -> ProductTaskQueryView: ...
```

Reference client ordering is normative:

```text
create/recover client_submission_ref
-> call AgentInterpreterPort only if no frozen request exists
-> deterministic proposal validation
-> atomic freeze
-> send exact frozen request over MCP
-> persist delivery result
-> render owner-derived operation proposal pause
-> obtain explicit local human accept/reject outside model
-> controller calls MCP resume directly
-> query exact same task id
-> present authoritative result
```

- [ ] **Step 1: RED real Streamable HTTP MCP negotiation/list/call using the existing pinned `mcp` dependency.** Start the Product Front Door on an ephemeral loopback port and connect `ProductFrontDoorMcpClient` by URL; `Client(build_mcp_server(...))` / direct service invocation is useful for lower-level server tests but does not satisfy this client transport assertion.
- [ ] **Step 2: RED response-loss recovery.** Simulate server accepting submit then client losing the HTTP/MCP response. Client marks recoverable delivery state, reloads the exact frozen request after restart, and re-sends the same `task_id/session_ref/request_hash`; no model re-interpretation or new IDs occur.
- [ ] **Step 3: RED explicit human-event separation.** Agent adapter is invoked only for interpretation and is not passed MCP endpoint/tool metadata. A pending `pause_id` is rendered to a `HumanDecisionPort`; only that deterministic local callback can invoke the resume MCP tool.
- [ ] **Step 4: Implement terminal/recovery presentation.** `SUCCEEDED` is shown only from authoritative product projection; `RECOVERY_REQUIRED`, failed, cancelled, partial/diverged and persisted-pre-workflow remain distinct user-visible facts.
- [ ] **Step 5: Implement CLI entry behavior** in `reference_client.py` using environment/config arguments; do not embed API keys or model vendor credentials. `DSP_AGENT_INTERPRETER_COMMAND` is parsed once at startup and executed by `SubprocessAgentInterpreter`.
- [ ] **Step 6: GREEN + absolute Ruff + commit.**

```bash
uv run pytest \
  tests/product_front_door/test_mcp_client.py \
  tests/product_front_door/test_reference_client.py -q -vv
git commit -m "feat: add MCP product reference client"
```

---

## Task 9: Prove durable concurrency, rebuild and real-MCP offline product behavior

**Files:**
- Create: `tests/product_front_door/test_durable_recovery_postgres.py`
- Create: `tests/product_front_door/test_mcp_product_end_to_end.py`
- Create: `.github/workflows/product-front-door.yml`

**Mandatory acceptance scenarios:**

1. SQLite correlation created, process rebuilt before freeze → replay freezes one request.
2. Freeze transaction committed, client process rebuilt → exact request/binding/outbox recovered.
3. Two independent client/controller instances race same correlation + same proposal → one winner.
4. Two instances race same correlation + conflicting proposals → one winner, one conflict, no losing binding/request.
5. Product Front Door accepts submit but response is lost → exact frozen replay; same server ProductTask identity.
6. Two independent `WallThicknessProductFlow` / start-gate instances race the same task against real PostgreSQL → one effective workflow lineage and no duplicate Host mutation.
7. Request committed, process rebuilt before workflow start → `get()` reports `ACCEPTED_PRE_WORKFLOW`; exact submit replay starts/reuses workflow; `get()` itself does nothing.
8. Query request/checkpoint split-read race does not falsely report corruption.
9. Operation proposal accepted but configured policy denies → no Host mutation.
10. Positive offline path launches the loopback Streamable HTTP Product Front Door and reaches authoritative terminal product projection through `ProductFrontDoorMcpClient(endpoint_url)` using only an external Host transport fake; all platform owners/policy/Gateway/Saga/Reconciliation are production code. An in-process MCP server object does not satisfy this scenario.
11. Host unavailable after task creation → exact `get()` still returns durable state without session/Host access.

- [ ] **Step 1: Write RED cases with fresh PostgreSQL schemas and fresh SQLite files per scenario.** No shared in-process singleton is allowed to provide correctness.
- [ ] **Step 2: Use independent connections/composition objects for concurrency and rebuild.** At least one test must close every old connection/runtime before constructing the replacement.
- [ ] **Step 3: Implement only the minimum recovery fixes exposed by these REDs.** Do not add generic scheduler/listing/polling facilities.
- [ ] **Step 4: Add `product-front-door.yml`.** PostgreSQL 17 service; run front-door focused tests, product query/start-gate durable tests, real loopback Streamable HTTP MCP offline E2E, and absolute Ruff for new front-door paths plus no-new diagnostics for touched legacy paths.
- [ ] **Step 5: GREEN locally and on exact-head CI.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_front_door/test_durable_recovery_postgres.py \
  tests/product_front_door/test_mcp_product_end_to_end.py -q -vv
```

- [ ] **Step 6: Commit.**

```bash
git commit -m "test: prove durable MCP product recovery"
```

---

## Task 10: Add controlled real-model + real-MCP + human + policy + Revit acceptance and close the implementation gate

**Files:**
- Create: `docs/runbooks/mcp-agent-front-door.md`
- Create: `tests/integration/test_mcp_agent_front_door_live_support.py` for non-interactive environment/readiness/supporting assertions only.
- Modify: `.github/workflows/product-front-door.yml` to collect/skip live support by default; canonical CI MUST NOT fake the mandatory interactive gate.
- Modify: `docs/superpowers/README.md` only after implementation/live evidence reaches the appropriate lifecycle state.

**Mandatory live inputs:**

```text
DSP_FRONT_DOOR_LIVE=1
DSP_AGENT_INTERPRETER_COMMAND=<real model command>
DSP_AGENT_MODEL_NAME=<recorded provider/model label>
DSP_FRONT_DOOR_CANDIDATES_FILE=<configured Revit candidates JSON>
DSP_FRONT_DOOR_POLICY_FILE=<real configured local policy JSON>
DSP_FRONT_DOOR_STATE_DB=<durable local SQLite application DB>
DSP_FRONT_DOOR_HOST=127.0.0.1
DSP_FRONT_DOOR_PORT=8010
DSP_REVIT_VERSION
DSP_REVIT_TFM
DSP_REVIT_API_DIR
DSP_REVIT_PIPE
DSP_REVIT_FIXTURE
DSP_TEST_POSTGRES_DSN
```

The runbook must record one exact lineage:

```text
natural-language utterance
client_submission_ref
model provider/model label + invocation evidence
normalized proposal hash
candidate configuration version/key
session_ref + binding_hash + real host_instance_id/document_id
ProductTask task_id + request_hash
real MCP endpoint + submit response
operation-proposal pause_id + subject_ref
explicit human ACCEPT/REJECT event
final changeset id/hash + approval scope hash
configured policy id/principal/policy_snapshot_hash
ApprovalAdmission id/fingerprint/approved_at/expires_at
Gateway ApprovalRecord id/hash
real Revit command/effect evidence
independent post-commit READ / verification / reconciliation
final same-task Product Front Door get result
```

- [ ] **Step 1: Add supporting live test for environment/transport facts only.** It may discover the real Revit context and verify loopback MCP availability but MUST NOT auto-click human approval and MUST NOT be presented as the mandatory acceptance itself.
- [ ] **Step 2: Write the interactive runbook.** Operator starts real Revit fixture, Product Front Door Streamable HTTP server and reference client; enters natural language; verifies the model output is only a proposal; explicitly accepts/rejects the owner-rendered operation proposal; observes configured policy admission; then independently verifies the Revit wall thickness using the existing strict READ path.
- [ ] **Step 3: Negative controlled live case.** Use a denying/mismatched policy with no prior durable admission for that new task/ChangeSet; prove operation proposal may be accepted but Revit mutation count remains zero.
- [ ] **Step 4: Positive controlled live case.** Real model + real loopback MCP transport + explicit human accept + real configured policy admission + real Revit mutation + independent verification all belong to the same task lineage.
- [ ] **Step 5: Record evidence in the runbook without secrets.** Do not record API keys, DSNs, tokens or full sensitive model prompts beyond the user-visible test utterance.
- [ ] **Step 6: Fresh exact-head verification before any completion claim:**

```bash
uv run pytest --import-mode=importlib -q
uv run pytest -q
# plus product-front-door PostgreSQL workflow and Repository Regression on the exact final SHA
```

Required final evidence:

```text
Repository Regression: success
Workflow Orchestrator PostgreSQL: success
Durable Persistence: success
Product Front Door: success
Ruff delta: 0 new diagnostics
controlled live gate: PASS with recorded lineage evidence
branch exact HEAD unchanged after evidence capture
```

- [ ] **Step 7: Only after all gates are real GREEN, update lifecycle metadata and commit the runbook/closeout docs.** Do not mark capability `COMPLETED` from offline CI alone.

```bash
git commit -m "docs: record MCP front door live acceptance"
```

---

# Cross-Task Verification Matrix

| Requirement | Owning task(s) |
| --- | --- |
| Persisted request / no checkpoint query | 1, 9 |
| Split-read race stabilization | 1, 9 |
| Concurrent first submit | 2, 9 |
| Immutable SessionBinding | 3, 4 |
| Read-only server SessionBinding resolution | 4, 7 |
| Duplicate/conflicting callback freeze | 4, 9 |
| Client restart / response loss | 4, 8, 9 |
| Saved-document / Host identity validation | 3, 6, 7, 10 |
| Operation proposal exact pause correlation | 7, 8 |
| Model cannot human-resume | 4, 7, 8, 10 |
| Configured policy default deny | 5 |
| Admission stable replay identity | 5, 9 |
| Gateway already-consumed exact recovery | 5 |
| No Host mutation before final admission | 5, 9, 10 |
| Real MCP Streamable HTTP boundary | 7, 8, 9, 10 |
| Real model interpretation | 8, 10 |
| Explicit human operation-proposal event | 8, 10 |
| Real Revit + independent verification | 10 |
| Host-offline read-only query | 1, 7, 9 |

# Plan Self-Review

## Spec coverage

- Reliable submission/correlation: Tasks 4, 8, 9.
- Session resolution/identity: Tasks 3, 4, 6, 7.
- Product Front Door submit/get/resume: Tasks 1, 7.
- Human/model authority separation: Tasks 7, 8, 10.
- Separate final execution admission: Task 5 and Task 10.
- Persisted-request/no-checkpoint query: Tasks 1 and 9.
- Concurrent first submit gate: Tasks 2 and 9.
- Real MCP + real model + real Revit acceptance: Tasks 8–10.
- Local-only trust boundary/no broad enumeration: Task 7.
- No new generic ingress/approval/scheduler platform: enforced in Global Constraints and every composition task.

No approved Spec requirement is intentionally deferred by this plan.

## Type/interface consistency

- `ProductTaskQueryService` is the sole new read composition; MCP `get()` consumes its `ProductTaskQueryView` and does not touch SessionBinding/Host state.
- `SessionBinding` is create-once application identity evidence in the local SQLite database; the server receives only `SessionBindingReadPort`, never client delivery mutation APIs.
- `ConfiguredRevitCandidateSource` provides deterministic project/target constraints; model output selects only its key.
- Exact Revit product composition receives scalar environment/session evidence and does not import front-door persistence.
- `ConfiguredPolicyApprovalAdmissionPort` implements the existing orchestrator `ApprovalAdmissionPort` seam; `product_policy.admission` only preserves immutable issuance evidence, while Gateway remains approval lifecycle/authorization truth.
- Gateway strict consume-once store semantics are preserved; idempotent replay lives in the V2 service composition method and does not re-expire already-consumed authority.
- Reference client Agent interface produces proposal fields only; human resume remains a separate deterministic controller call.

## Proportion / YAGNI

This plan deliberately does not add remote authentication, user accounts, task search, general multi-Host discovery, background document switching, async approval inbox, generic LLM tool orchestration or a new network service. SQLite is used only for same-workstation submission delivery plus create-once SessionBinding authority; PostgreSQL remains the server durable substrate already used by ProductTask/workflow/Saga, with one narrow configured-policy admission issuance table required for replay safety.

# Execution Handoff Gate

Implementation MUST NOT start merely because this file exists. Review this plan first against the approved design baseline `41247215ca4dc70d62e17577a68bfadc5fa1ec5c`, especially Tasks 1, 2, 5 and 10 where read consistency, cross-process serialization, approval replay and live authority separation are easiest to weaken accidentally.
