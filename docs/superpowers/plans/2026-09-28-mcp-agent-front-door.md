# MCP / Agent Front Door Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Every production-code task is strict TDD RED → GREEN → focused verification → exact-head verification → commit; do not collapse gates.

**Goal:** Deliver one reproducible local MCP / Agent front door for the existing Revit selected-wall thickness product vertical, from real natural language through explicit operation-proposal HITL, configured-policy execution admission, real MCP and real Revit verification.

**Architecture:** Add a source-only front-door application layer around the existing ProductTask / ProductFlow / Workflow / Gateway / Saga owners. Keep client delivery correlation, immutable SessionBinding, operation-proposal human decision, and final execution admission as separate responsibilities; do not create a second workflow, ProductTask owner, approval owner, or generic Agent framework.

**Tech Stack:** Python 3.11, stdlib SQLite 3, PostgreSQL 17 + psycopg 3, existing LangGraph runtime, existing MCP SDK dependency range `mcp>=2,<3`, Revit named-pipe sidecar, pytest, Ruff.

**Spec:** `docs/superpowers/specs/2026-09-28-mcp-agent-front-door-design.md`

**Status:** Written implementation plan — pending review  
**Date:** 2026-09-28  
**Plan source base:** `architecture/mcp-agent-front-door@41247215ca4dc70d62e17577a68bfadc5fa1ec5c`  
**Workflow authority:** `docs/adr/ADR-010-workflow-orchestrator-runtime-ownership.md`  
**Persistence authority:** `docs/adr/ADR-008-durable-state-persistence-ownership.md`  
**Delivery/recovery authority:** `docs/adr/ADR-009-cross-owner-delivery-crash-recovery.md`

## Global Constraints

- Design baseline is exactly `41247215ca4dc70d62e17577a68bfadc5fa1ec5c`; implementation MUST NOT silently amend the approved design.
- `client_submission_ref` is client delivery/recovery identity only. `ProductTaskRequest.task_id` remains the accepted server business identity.
- One client correlation may freeze at most one complete immutable ProductTask request. Different correlations remain different submissions even when content is identical.
- Generated `task_id`, opaque `session_ref`, request hash, timestamps and delivery counters are never callback-equivalence inputs.
- The original user utterance is persisted with the client correlation before model interpretation. Before freeze it may be re-interpreted after client-process restart; after freeze the exact request is replayed and the model MUST NOT be called again for that correlation.
- A model may return either one supported normalized proposal or `CLARIFICATION_REQUIRED`. Clarification never allocates `task_id`/`session_ref`, never sends MCP submit, and never creates ProductTask truth.
- `NormalizedFreezeProposal` includes a deterministic candidate-configuration/target-constraint hash so configuration drift under the same candidate key cannot be mistaken for an identical callback.
- The frozen `candidate_hash` is also part of immutable `SessionBinding` authority and `binding_hash`. Every Host-bound submit/resume/composition path MUST re-read the current configured candidate by exact key, recompute/validate its canonical hash, and require equality with `SessionBinding.candidate_hash` before workflow progress. The server still never reads client submission/outbox rows.
- Complete frozen request + correlation association MUST be durable before first MCP send.
- Same `session_ref` resolves to the exact immutable SessionBinding body or fails. It is never rebound after Host restart, document change, candidate configuration drift, or composition rebuild.
- Product Front Door may read SessionBinding through a narrow resolver but MUST NOT read/write client delivery/outbox rows.
- Durable v1 SessionBinding supports saved Revit documents only. Unsaved/title-only documents fail before request freeze.
- Endpoint/PID equality is only a locator fact. Every Host-bound submit/resume path fresh-validates runtime/document identity and the configured selected target.
- Exact `get(task_id)` is Host-independent: it MUST NOT resolve SessionBinding, open Revit transport, start/resume/poll workflow, or resend Host mutation.
- `request exists / checkpoint absent` is a first-class query fact. `checkpoint exists / request absent` is lineage corruption only after a stabilization re-read.
- Concurrent first submit is serialized by a durable PostgreSQL task gate around `get_checkpoint() -> possible start()`. No Python lock/singleton may provide correctness.
- Operation-proposal `OPERATION_PROPOSAL_ACCEPTED` only authorizes workflow interpretation to continue. It is not execution approval.
- Final execution admission evaluates the authoritative final ChangeSet + ApprovalScope against real configured policy and defaults to deny for new issuance when policy material is missing/invalid/mismatched.
- The policy for this vertical MUST authorize the real canonical operation ID `set_wall_thickness.v1`; `set_wall_thickness` is not a valid substitute.
- Policy snapshot hashing MUST reuse the repository canonical hash helper (`design_changeset.canonical_hash`); `ApprovalAdmission.admission_fingerprint` MUST use `design_gateway_authorization.compute_admission_fingerprint()`.
- Once an exact configured-policy admission is durably issued, replay returns that immutable admission body. Changing the policy file does not rewrite an already-issued admission.
- Configured policy admission and workflow MUST read the same authoritative ChangeSet/ApprovalScope owner stores. The reference composition creates those stores once, then builds the policy admission port from the exact same instances; no duplicate store graph or private-field reach-through is permitted.
- Gateway remains approval/grant authority. This plan may add idempotent recovery of an already-consumed admission inside the existing Gateway owner lifetime, but it does **not** claim a new cross-process durable Gateway store where none exists today.
- Mandatory reference/live composition MUST NOT use `_ApprovalAdmissionBoundary` or equivalent hard-coded approver/hash/time fixture data.
- Existing SemanticVerifier/Reconciliation/Saga remain effect/outcome authority. Unknown Host outcome never authorizes blind mutation resend.
- The current Revit product vertical still uses an in-memory Semantic Runtime `SnapshotRegistry`. Therefore v1 guarantees **client-process restart**, network/MCP reconnect, request-before-workflow server rebuild, and declared first-start crash windows; it does not newly claim arbitrary Product Front Door server-process restart after a ContextSnapshot has been created. The mandatory submit → operation-proposal resume path keeps the exact-session runtime composition alive in the same server process.
- A process-local exact-session composition pool is permitted only as a handle to that existing in-memory owner. It is keyed by exact immutable `session_ref`, has no `latest` fallback, owns no business truth, and is never used by `get(task_id)`.
- No broad task search, generic Agent shell, generic `ProductIntentIngress`, multi-Host scheduler, background document switching, remote auth, multi-tenant identity, generalized approval inbox, or new generalized network service is added.
- New Python production code and code comments/docstrings MUST use complete Chinese comments consistent with repository style.
- Every task ends with an independent commit. The next task starts only from the previous task’s exact GREEN HEAD.

## Review Focus

1. **Split-read query race:** a request committed between request/checkpoint reads must not be misreported as checkpoint-without-request corruption. Task 1 owns this.
2. **First-start race/crash:** two submitters, holder death before start, and response loss after first checkpoint persistence must still converge on one workflow lineage. Tasks 2 and 9 own this.
3. **Correlation/configuration replay:** duplicate callbacks, config drift under one candidate key, client restart before/after freeze, and response loss must not create a second request; frozen candidate authority must also reject drift before first submit and before resume. Tasks 3, 4, 7, 8 and 9 own this.
4. **Approval authority/replay:** exact final ChangeSet/scope, shared owner stores, default deny, stable admission identity/time, canonical fingerprint helper, and already-consumed Gateway recovery must stay distinct from operation-proposal HITL. Tasks 5 and 6 own this.
5. **Host/session lifetime:** endpoint reuse, Host restart, active-document switch and unsaved documents block new Host-bound work, while exact task query remains available; submit and later HITL resume must reuse the exact-session composition within the declared v1 server lifetime. Tasks 3, 6, 7, 9 and 10 own this.

## Ruff Gate Policy

The repository contains historical Ruff diagnostics. New-only paths may use absolute Ruff. Any task touching a legacy path MUST use the repository-regression no-new-diagnostics semantics: resolve the merge-base, run the **HEAD Ruff binary** against baseline and head for the same scoped paths, normalize diagnostics to `(filename, code, message)`, and require `head - base == 0`. Final GitHub `Repository regression` on the exact final SHA is authoritative.

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
    """只读 checkpoint adapter；不构造 WorkflowServices，也不编译可执行 graph。"""

    def __init__(self, *, checkpointer) -> None: ...
    def get_checkpoint(self, task_id: str) -> WorkflowCheckpointView | None: ...


class ProductTaskQueryState(str, Enum):
    """Front Door 对 durable task 的最小查询事实。"""

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

**Normative query ordering:**

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

- [ ] **Step 1: Write checkpoint-reader RED.** Prove real persisted checkpoint projection works without `WorkflowServices`; missing task returns `None`; corrupt checkpoint preserves `WORKFLOW_CHECKPOINT_INVALID`.
- [ ] **Step 2: Run RED.** `uv run pytest tests/orchestrator/test_checkpoint_reader.py -q -vv`.
- [ ] **Step 3: Implement `LangGraphWorkflowCheckpointReader`.** Reuse existing `_checkpoint_lookup_config` and `_checkpoint_from_snapshot`; do not duplicate LangGraph private decoding in Product Runtime.
- [ ] **Step 4: Write query RED for all four durable rows plus the split-read race.** Script the first request read as `None`, make checkpoint read observe a concurrently committed request/checkpoint, then return the request on the stabilization read. Assert `WORKFLOW`, not corruption.
- [ ] **Step 5: Implement `ProductTaskQueryService`.** Share existing ProductFlow/Saga projection logic by extracting a helper from `WallThicknessProductFlow`; do not copy terminal/recovery rules.
- [ ] **Step 6: Add PostgreSQL acceptance.** Prove request-only → `ACCEPTED_PRE_WORKFLOW`; request+checkpoint → `WORKFLOW`; isolated corruption fixture with checkpoint but no request → `PRODUCT_TASK_LINEAGE_INVALID` only after the second request read.
- [ ] **Step 7: GREEN.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/orchestrator/test_checkpoint_reader.py \
  tests/product_runtime/test_product_task_query.py \
  tests/product_runtime/test_product_task_query_postgres.py -q -vv
```

- [ ] **Step 8: Ruff delta + commit.** `git commit -m "feat: add race-safe product task query"`.

---

## Task 2: Serialize concurrent first workflow start with a PostgreSQL task gate

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/start_gate.py`
- Create: `platform/product_runtime/src/design_product_runtime/postgres_start_gate.py`
- Modify: `platform/product_runtime/src/design_product_runtime/wall_thickness_flow.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Modify: `tests/product_runtime/test_wall_thickness_flow.py`
- Create: `tests/product_runtime/test_product_task_start_gate_postgres.py`
- Modify all existing product-runtime compositions that construct `WallThicknessProductFlow`.

**Interfaces:**

```python
class ProductTaskStartGate(Protocol):
    """只串行化同一 task 的 checkpoint-missing → start 临界区。"""

    @contextmanager
    def serialize(self, task_id: str) -> Iterator[None]: ...


class PostgresProductTaskStartGate:
    def serialize(self, task_id: str) -> Iterator[None]: ...
    def close(self) -> None: ...
```

Use `product_task.start_gate(task_id TEXT PRIMARY KEY)`. `serialize()` creates/ensures the exact row and holds a PostgreSQL `SELECT ... FOR UPDATE` lock for the full `get_checkpoint() -> possible start()` critical section. `WallThicknessProductFlow.submit()` performs immutable request `create()` before entering the gate, then re-reads the checkpoint **inside** the gate.

- [ ] **Step 1: RED two independent PostgreSQL gate connections.** Both race the same task; only one enters the critical section at a time.
- [ ] **Step 2: Implement the row-lock gate.** No Python lock, singleton, process mutex, or in-memory advisory state.
- [ ] **Step 3: RED two independent `WallThicknessProductFlow` instances.** With the same durable request/checkpoint owners and real gate, concurrent same-request submit yields one effective `start()` and one workflow lineage.
- [ ] **Step 4: RED crash before start.** First holder acquires the gate and disappears before `start()`; second process/connection acquires after transaction rollback and starts the persisted request exactly once.
- [ ] **Step 5: RED response-loss after checkpoint persistence.** Wrap real `start()` so it persists the first checkpoint and then raises to simulate caller loss; a second submit acquires the gate, re-reads the checkpoint, and MUST NOT invoke `start()` again.
- [ ] **Step 6: Implement gate injection and migrate compositions.** Production/reference composition requires a durable gate; non-concurrency unit tests may use a tiny fake gate.
- [ ] **Step 7: GREEN.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_wall_thickness_flow.py \
  tests/product_runtime/test_product_task_start_gate_postgres.py -q -vv
```

- [ ] **Step 8: Ruff delta + commit.** `git commit -m "feat: serialize first product workflow start"`.

---

## Task 3: Add configured Revit candidate discovery and immutable SessionBinding contracts

**Files:**
- Modify: `hosts/revit/sidecar/src/revit_sidecar/context.py`
- Modify: `hosts/revit/sidecar/src/revit_sidecar/__init__.py`
- Create: `platform/product_front_door/src/design_product_front_door/__init__.py`
- Create: `platform/product_front_door/src/design_product_front_door/contracts.py`
- Create: `platform/product_front_door/src/design_product_front_door/candidate_config.py`
- Modify: root `pyproject.toml` to add `platform/product_front_door/src` to pytest `pythonpath`; keep this source-only unless later census proves a distribution is required.
- Create: `tests/revit_sidecar/test_context_discovery.py`
- Create: `tests/product_front_door/test_contracts.py`
- Create: `tests/product_front_door/test_candidate_config.py`

**Reference candidate shape:**

```json
{
  "version": "DSP_REVIT_CANDIDATES_V1",
  "candidates": [
    {
      "candidate_key": "primary-revit",
      "project_id": "project-id",
      "transport_locator": "configured-revit-pipe",
      "document_id": "C:\\path\\to\\fixture.rvt",
      "semantic_target_id": "WALL-001",
      "native_target_unique_id": "reviewed-wall-unique-id"
    }
  ]
}
```

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class ConfiguredRevitCandidate:
    """确定性的本机候选配置；locator 不是 Host 身份证明。"""

    candidate_key: str
    project_id: str
    transport_locator: str
    document_id: str
    semantic_target_id: str
    native_target_unique_id: str
    candidate_hash: str


class ConfiguredRevitCandidateSource(Protocol):
    def get(self, candidate_key: str) -> ConfiguredRevitCandidate | None: ...


@dataclass(frozen=True, slots=True)
class SessionBinding:
    """一次 create-once 的 Revit runtime/document/candidate authority 绑定。"""

    session_ref: str
    project_id: str
    host_kind: str
    candidate_key: str
    candidate_hash: str
    transport_locator: str
    host_instance_id: str
    document_id: str
    document_title: str
    binding_hash: str


class RevitCurrentContextProbe:
    def discover(self, *, command_id: str, document_id: str) -> RevitContextObservation: ...
```

`candidate_hash` uses `design_changeset.canonical_hash()` over normalized candidate authority/configuration fields, including the configured semantic/native target identity. `SessionBinding.binding_hash` uses the same canonical helper over authority fields (`session_ref`, project, host kind, candidate key, **candidate hash**, locator, runtime id, document id); `document_title` is presentation metadata and does not establish identity. The binding therefore freezes the exact candidate configuration selected at freeze time without expanding `ProductTaskRequest`.

- [ ] **Step 1: RED discovery adapter.** It sends the existing `context.current_selection` READ, requires the configured document id, accepts fresh returned `host_instance_id`, and rejects Host error/document mismatch/malformed identity.
- [ ] **Step 2: Refactor response parsing.** Strict `RevitContextReadPort` and discovery share parser validation; strict expected-host checking remains unchanged for the existing port.
- [ ] **Step 3: RED candidate config and binding.** Reject unknown version, duplicate key, blank fields, changed candidate body under supplied hash, title-only/relative document ids, malformed binding hash, binding/body mismatch, and any binding whose `candidate_hash` is not part of the canonical `binding_hash` body.
- [ ] **Step 4: Implement config/binding canonical hashing with `design_changeset.canonical_hash()`.** Do not infer `project_id` from Revit path and do not treat pipe/PID as identity.
- [ ] **Step 5: GREEN.**

```bash
uv run pytest \
  tests/revit_sidecar/test_context_discovery.py \
  tests/product_front_door/test_contracts.py \
  tests/product_front_door/test_candidate_config.py -q -vv
```

- [ ] **Step 6: Ruff delta/absolute new-path check + commit.** `git commit -m "feat: add immutable Revit session binding"`.

---

## Task 4: Implement durable client correlation, clarification, atomic freeze, SessionBinding authority and outbox

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
class AgentProposal:
    """模型只允许提出受支持的候选与厚度意图。"""

    candidate_key: str
    thickness_value: float
    thickness_unit: str


@dataclass(frozen=True, slots=True)
class AgentClarificationRequired:
    """需要用户补充信息；此结果绝不产生业务任务身份。"""

    question: str


class AgentInterpreterPort(Protocol):
    def interpret(
        self,
        *,
        client_submission_ref: str,
        utterance: str,
    ) -> AgentProposal | AgentClarificationRequired: ...


@dataclass(frozen=True, slots=True)
class NormalizedFreezeProposal:
    """只包含生成 identity 之前存在的确定性输入。"""

    project_id: str
    host_kind: str
    requested_action: str
    intent_arguments: Mapping[str, object]
    candidate_key: str
    candidate_hash: str


class SubmissionState(str, Enum):
    """客户端 correlation 的持久化生命周期；未冻结记录不伪造业务字段。"""

    UNFROZEN = "UNFROZEN"
    FROZEN = "FROZEN"


@dataclass(frozen=True, slots=True)
class FrozenSubmission:
    client_submission_ref: str
    utterance: str
    proposal_hash: str
    session_binding: SessionBinding
    request: ProductTaskRequest
    delivery_state: str


@dataclass(frozen=True, slots=True)
class SubmissionRecord:
    """可表达模型调用前已经落盘但尚未 freeze 的 correlation 记录。"""

    client_submission_ref: str
    utterance: str
    state: SubmissionState
    frozen: FrozenSubmission | None


class SessionBindingReadPort(Protocol):
    def resolve_session(self, session_ref: str) -> SessionBinding | None: ...


class SqliteFrontDoorStateStore:
    def create_submission(self, client_submission_ref: str, utterance: str) -> SubmissionRecord: ...
    def get_submission(self, client_submission_ref: str) -> SubmissionRecord | None: ...
    def get_frozen_submission(self, client_submission_ref: str) -> FrozenSubmission | None: ...
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
    def resolve_session(self, session_ref: str) -> SessionBinding | None: ...
    def close(self) -> None: ...
```

The physical SQLite database has two logical responsibilities: `client_submission` is controller-owned delivery/recovery state; `session_binding` is create-once application binding authority. `SubmissionRecord` is the controller read model for both UNFROZEN and FROZEN correlations; it never invents request/session/proposal fields before freeze. The server gets only `SqliteSessionBindingReader`/`SessionBindingReadPort`.

- [ ] **Step 1: RED correlation creation.** `create_submission(ref, utterance)` durably records the exact original utterance before model call, returns `SubmissionRecord(state=UNFROZEN, frozen=None)`, and allocates no task/session identity. Same ref + different utterance is `FRONT_DOOR_CORRELATION_CONFLICT`.
- [ ] **Step 2: RED client restart before freeze.** Close/reopen SQLite, `get_submission(ref)` returns the original immutable utterance with `UNFROZEN`; permit re-interpretation because no ProductTask request exists yet. No fake request/session/proposal fields are materialized.
- [ ] **Step 3: RED clarification.** `CLARIFICATION_REQUIRED` returns a user-visible question but creates no SessionBinding, task id, request or MCP delivery. A clarified user submission is a new explicit correlation in v1; do not mutate the old correlation into a different utterance.
- [ ] **Step 4: RED same-correlation replay after freeze.** Controller checks `SubmissionRecord.frozen` before invoking model/probe/ID factories; replay returns the exact winner and never reinterprets natural language.
- [ ] **Step 5: RED concurrent same and conflicting proposals using two SQLite connections.** Same normalized proposal produces one winner; different proposal or changed `candidate_hash` produces one winner + one conflict; no losing binding/request persists.
- [ ] **Step 6: RED crash/reopen after freeze.** New process returns byte-equivalent request/binding and `DELIVERY_PENDING`; read-only session reader resolves the same binding.
- [ ] **Step 7: Implement SQLite transaction.** Use `BEGIN IMMEDIATE`, foreign keys and uniqueness. One successful transaction inserts the winning SessionBinding and exact ProductTask request copy/hash under the correlation and transitions to `FROZEN` + `DELIVERY_PENDING` atomically.
- [ ] **Step 8: Implement `SubmissionController`.** Resolve configured candidate, fresh-probe the configured document, require exactly the configured selected Wall target, create opaque `session_ref` and stable `task_id`, copy the exact candidate hash into `SessionBinding`, build the complete ProductTask request, then compete to freeze once.
- [ ] **Step 9: Implement `SubprocessAgentInterpreter`.** stdin contains only correlation + utterance; stdout must be exactly either `{kind:"PROPOSAL", candidate_key, thickness:{value,unit}}` or `{kind:"CLARIFICATION_REQUIRED", question}`. Reject project/host/task/session/pause/resume/approval fields and unknown keys.
- [ ] **Step 10: GREEN + absolute Ruff + commit.**

```bash
uv run pytest \
  tests/product_front_door/test_sqlite_state.py \
  tests/product_front_door/test_submission_controller.py \
  tests/product_front_door/test_agent.py -q -vv
uv run ruff check platform/product_front_door/src/design_product_front_door tests/product_front_door
git commit -m "feat: freeze durable front door submissions"
```

---

## Task 5: Implement configured-policy ApprovalAdmission with durable issuance replay

**Files:**
- Create: `platform/product_front_door/src/design_product_front_door/approval_policy.py`
- Create: `platform/product_front_door/src/design_product_front_door/postgres_admission_store.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/store_v2.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/v2.py`
- Modify: `platform/gateway_authorization/src/design_gateway_authorization/__init__.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_owner_ports.py`
- Create: `tests/product_front_door/test_approval_policy.py`
- Create: `tests/product_front_door/test_approval_admission_postgres.py`
- Modify/create focused Gateway V2 replay tests.
- Modify: `tests/orchestrator/test_real_owner_workflow_end_to_end.py` only where the new composition-safe Gateway call changes the seam.

**Policy shape:**

```json
{
  "version": "DSP_PRODUCT_APPROVAL_POLICY_V1",
  "policy_id": "local-wall-thickness-v1",
  "principal": "local:operator",
  "project_ids": ["project-id"],
  "allowed_canonical_operations": ["set_wall_thickness.v1"],
  "admission_ttl_seconds": 900
}
```

`policy_snapshot_hash = design_changeset.canonical_hash(normalized_policy_body)`. Missing/malformed policy, blank principal, project mismatch, incomplete canonical-operation set, or non-positive TTL denies **new** issuance.

**Interfaces:**

```python
class ConfiguredPolicyApprovalAdmissionPort:
    """对最终 ChangeSet/Scope 执行真实本机配置策略授权。"""

    def __init__(
        self,
        *,
        changeset_store: object,
        approval_scope_store: object,
        admission_store: PostgresConfiguredPolicyAdmissionStore,
        policy_source: object,
        clock: object,
        id_factory: object,
    ) -> None: ...

    def request_approval(self, changeset_ref: StableRef) -> ApprovalAdmission: ...


class PostgresConfiguredPolicyAdmissionStore:
    def get(
        self,
        *,
        changeset_hash: str,
        approved_scope_hash: str,
    ) -> ApprovalAdmission | None: ...

    def issue_or_get(self, admission: ApprovalAdmission) -> ApprovalAdmission: ...
    def close(self) -> None: ...


class ApprovalAdmissionFactory(Protocol):
    """基于 reference composition 已创建的 authoritative owner stores 构造 admission port。"""

    def build(
        self,
        *,
        changeset_store: object,
        approval_scope_store: object,
    ) -> ApprovalAdmissionPort: ...


class GatewayAuthorizationServiceV2:
    def consume_or_get_approval(
        self,
        request: ApprovalConsumptionRequestV2,
    ) -> ApprovalRecord: ...
```

`product_policy.admission` stores the exact immutable issued admission body/fingerprint and uses exact final `(changeset_hash, approved_scope_hash)` as create-once issuance lineage. It is issuance evidence, not approval lifecycle truth. `ConfiguredPolicyApprovalAdmissionPort` MUST receive the same ChangeSet/ApprovalScope owner-store instances used by the workflow composition; it may not create parallel stores or reach into composition private fields.

**Normative issuance ordering:** exact ChangeSet/scope load + ref/hash validation → existing admission lookup → if present validate/replay exact body → otherwise normalize policy → authorize project/environment/complete canonical operation set → injected clock/id factory → construct Admission → existing `compute_admission_fingerprint()` → PostgreSQL `issue_or_get()` → return durable winner.

**Normative Gateway retry ordering:** validate admission fingerprint and authoritative ChangeSet/scope/least-privilege joins → query existing consumption by exact admission id/fingerprint in the current Gateway store → if found verify stored ApprovalRecord authority hash/lineage and return it without reapplying original admission expiry → otherwise call strict first-consumption path (including expiry validation). This is same-owner retry recovery, not a promise of new durable Gateway persistence across server-process loss.

- [ ] **Step 1: RED policy normalization/default deny.** Include exact `set_wall_thickness.v1`; prove a policy containing only `set_wall_thickness` is rejected for this ChangeSet.
- [ ] **Step 2: RED first issuance + fresh admission-store rebuild.** First call persists exact admission; reopened PostgreSQL store returns identical id/principal/policy hash/approved time/expiry/fingerprint despite later clock or unavailable/changed policy file.
- [ ] **Step 3: Implement authoritative ChangeSet/scope reads and policy evaluation.** Constructor dependencies are explicit shared owner stores. Validate supplied StableRef hash and final boundary before existing-issuance replay or new evaluation.
- [ ] **Step 4: Use only repository hash helpers.** `design_changeset.canonical_hash()` for policy snapshot; `compute_admission_fingerprint()` for admission. Validate fingerprints again on durable read.
- [ ] **Step 5: RED concurrent issuance.** Two PostgreSQL instances race same ChangeSet/scope; one exact admission wins. If both first-issuance attempts observed different policy authority bodies, loser fails conflict rather than rewriting the winner.
- [ ] **Step 6: RED Gateway same-owner retry.** First `consume_or_get_approval()` consumes; retry with same admission id/fingerprint returns exact stored ApprovalRecord even after admission expiry time; same id/different fingerprint remains conflict. Do not change strict `consume_admission_once()` behavior.
- [ ] **Step 7: Add the narrow V2 store read seam and `consume_or_get_approval()`.** Recompute/compare expected approval authority hash before returning an already-consumed record; preserve original stored `consumed_at`.
- [ ] **Step 8: Switch `CanonicalWorkflowOwnerPorts.request_approval()` to `consume_or_get_approval()`.** It still does not interpret policy or compute authority hashes.
- [ ] **Step 9: Negative acceptance.** Operation proposal accepted + missing/denied/mismatched configured policy ⇒ no approval ref, no execution planning/grant, zero Host mutation.
- [ ] **Step 10: GREEN.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_front_door/test_approval_policy.py \
  tests/product_front_door/test_approval_admission_postgres.py \
  tests/gateway_authorization \
  tests/orchestrator/test_real_owner_workflow_end_to_end.py -q -vv
```

- [ ] **Step 11: Ruff delta + commit.** `git commit -m "feat: add configured policy approval admission"`.

---

## Task 6: Extract a production/reference Revit product composition and exact-session lifetime

**Files:**
- Create: `platform/product_runtime/src/design_product_runtime/revit_reference_composition.py`
- Modify: `platform/product_runtime/src/design_product_runtime/__init__.py`
- Refactor: `tests/product_runtime/conftest.py`
- Refactor: `tests/integration/test_revit_wall_thickness_product_live.py`
- Create: `tests/product_runtime/test_revit_reference_composition.py`
- Modify supporting tests that currently import production-shaped helpers from `tests.orchestrator`.

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class RevitWallThicknessCompositionConfig:
    """一个 exact session 的生产/reference composition 输入。"""

    dsn: str
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
    snapshot_registry: object
    saga_store: object

    def close(self) -> None: ...


def build_revit_wall_thickness_reference_composition(
    *,
    config: RevitWallThicknessCompositionConfig,
    transport: object,
    approval_admission_factory: ApprovalAdmissionFactory,
) -> RevitWallThicknessRuntimeComposition: ...
```

This task does **not** make the in-memory `SnapshotRegistry` durable. One runtime composition must therefore remain alive across the reference submit → operation-proposal human-resume sequence. Query does not depend on it.

The factory itself creates the authoritative ChangeSet and ApprovalScope stores exactly once. It passes those exact instances both into the workflow owner graph and into `approval_admission_factory.build(...)`, then wires the returned `ApprovalAdmissionPort` into `CanonicalWorkflowOwnerPorts`. The caller never constructs a policy port against a second store graph, and no implementation reaches through private composition fields to recover stores after construction.

- [ ] **Step 1: Census production-shaped helpers imported from tests.** Cover topology, capability profile, materialization routing, provider snapshot factory, clocks and any additional helper at Task start. Every helper needed by mandatory reference path moves to product application composition or an existing production API.
- [ ] **Step 2: RED/build factory using only production owners.** Existing Impact/Scope/ChangeSet/Planning/Binding/Gateway/Saga/Reconciliation rules stay in their owners; composition only wires environment identity/topology/provider/runtime dependencies. The RED records the ChangeSet/Scope store object identities seen by workflow and `ApprovalAdmissionFactory` and requires exact identity equality.
- [ ] **Step 3: Require injected `ApprovalAdmissionFactory`, not a prebuilt admission port.** Mandatory reference tests build `ConfiguredPolicyApprovalAdmissionPort` from the stores supplied by the factory; `_ApprovalAdmissionBoundary` remains test-only and is forbidden in reference/live composition.
- [ ] **Step 4: RED authoritative lineage.** With real configured-policy admission, the policy port resolves the exact final ChangeSet/ApprovalScope produced by this workflow and authorizes it. A port wired to a different store instance or a mismatched lineage must fail closed rather than returning approval.
- [ ] **Step 5: RED exact session/runtime/document/target failures.** Wrong session ref, runtime, active document, or configured selected native target fails before Host mutation. Request↔binding project equality is enforced by Front Door Task 7, not duplicated here.
- [ ] **Step 6: Refactor offline/live product tests to consume the factory.** Remove production-shaped imports from `tests.orchestrator` on the mandatory path.
- [ ] **Step 7: Prove two sequential calls on the **same composition instance** can submit to operation-proposal pause and then human-resume successfully using the same in-memory snapshot owner. Do not claim an arbitrary server-process rebuild at this phase.
- [ ] **Step 8: GREEN.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_runtime/test_revit_reference_composition.py \
  tests/product_runtime/test_revit_wall_thickness_product_e2e.py \
  tests/product_runtime/test_revit_wall_thickness_product_authorization_failures.py -q -vv
```

- [ ] **Step 9: Ruff delta + commit.** `git commit -m "refactor: extract Revit product reference composition"`.

---

## Task 7: Add thin Product Front Door service, exact-session composition pool and MCP server

**Files:**
- Create: `platform/product_front_door/src/design_product_front_door/service.py`
- Create: `platform/product_front_door/src/design_product_front_door/composition_pool.py`
- Create: `platform/product_front_door/src/design_product_front_door/mcp_wire.py`
- Create: `platform/product_front_door/src/design_product_front_door/mcp_server.py`
- Create: `platform/product_front_door/src/design_product_front_door/mcp_transport.py`
- Modify: `platform/product_front_door/src/design_product_front_door/__init__.py`
- Create: `tests/product_front_door/test_service.py`
- Create: `tests/product_front_door/test_composition_pool.py`
- Create: `tests/product_front_door/test_mcp_wire.py`
- Create: `tests/product_front_door/test_mcp_server.py`
- Create: `tests/product_front_door/test_mcp_transport.py`

**Frozen logical tool names:**

```text
product.wall_thickness.submit
product.wall_thickness.get
product.wall_thickness.resume_operation_proposal
```

**Interfaces:**

```python
class ExactSessionCompositionPool:
    """仅缓存 exact session 的 runtime composition handle，不拥有业务真相。"""

    def get_or_create(
        self,
        *,
        binding: SessionBinding,
        candidate: ConfiguredRevitCandidate,
    ) -> RevitWallThicknessRuntimeComposition: ...
    def close(self) -> None: ...


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

The service receives `SessionBindingReadPort`, `ConfiguredRevitCandidateSource`, `RevitCurrentContextProbe`/transport factory, `ProductTaskQueryService`, and `ExactSessionCompositionPool`. It does not receive client outbox mutation APIs.

- [ ] **Step 1: RED exact MCP wire decoding.** Submit accepts only complete frozen ProductTask; get accepts exact task id; resume accepts exact task id + pause id + one allowed operation-proposal resume kind and no arbitrary payload.
- [ ] **Step 2: RED host-independent `get()`.** With broken/unavailable Revit/session resolver, exact get still returns request-only/workflow/terminal/recovery facts and never opens Host transport.
- [ ] **Step 3: RED submit binding validation.** Resolve immutable binding + current candidate; require request project/host kind to match binding, require exact candidate key and `current_candidate.candidate_hash == binding.candidate_hash`, validate binding hash, then fresh-probe bound document/runtime and configured selected target before obtaining the exact-session composition. If the same candidate key was edited after freeze—even under the same Host/document—the submit fails before workflow progress.
- [ ] **Step 4: RED composition-pool invariants.** Same `session_ref + binding_hash` returns the same live composition; same ref with different body fails; no `latest`/reverse fallback; query never touches pool.
- [ ] **Step 5: RED human resume.** Read current request/checkpoint first; require exact pending `OPERATION_PROPOSAL`, exact `pause_id`, and allowed resume kind. Re-read candidate by binding key, require its canonical hash to equal frozen `binding.candidate_hash`, fresh-validate the same binding/Host/selection, reuse the exact-session composition, construct existing `WorkflowResumeCommand`, and delegate. Candidate drift after pause fails before runtime resume.
- [ ] **Step 6: Implement thin service only.** It allocates no correlation/task/session ids, interprets no language, creates no admission, lists no tasks, and synthesizes no product success.
- [ ] **Step 7: Implement loopback-only Streamable HTTP transport.** Mirror Semantic MCP safety; accept only `127.0.0.1`, `localhost`, `::1`; default port `8010`; use the repository MCP 2.x contract.
- [ ] **Step 8: Tool-catalog test proves there is no generic approval/admission tool.** Human-resume is controller-only in reference client architecture; the model interpreter receives no MCP endpoint/catalog.
- [ ] **Step 9: GREEN + absolute Ruff + commit.**

```bash
uv run pytest \
  tests/product_front_door/test_service.py \
  tests/product_front_door/test_composition_pool.py \
  tests/product_front_door/test_mcp_wire.py \
  tests/product_front_door/test_mcp_server.py \
  tests/product_front_door/test_mcp_transport.py -q -vv
uv run ruff check platform/product_front_door/src/design_product_front_door tests/product_front_door
git commit -m "feat: expose product front door over MCP"
```

---

## Task 8: Add real MCP client and minimal repository-owned reference client

**Files:**
- Create: `platform/product_front_door/src/design_product_front_door/mcp_client.py`
- Create: `platform/product_front_door/src/design_product_front_door/reference_client.py`
- Create: `tests/product_front_door/test_mcp_client.py`
- Create: `tests/product_front_door/test_reference_client.py`

**Interfaces:**

```python
class ProductFrontDoorMcpClient:
    """只通过配置的 loopback Streamable HTTP URL 调用 Product Front Door。"""

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


class HumanDecisionPort(Protocol):
    """模型之外的显式人类决定边界。"""

    def decide(self, pending: PendingInteractionView) -> str: ...


class ReferenceClient:
    async def run_submission(
        self,
        *,
        client_submission_ref: str,
        utterance: str | None = None,
    ) -> ProductTaskQueryView | AgentClarificationRequired: ...
```

**Reference ordering:** exact correlation/utterance create-or-load as `SubmissionRecord` → if frozen skip model and reload exact request → otherwise read persisted utterance and model proposal/clarification → candidate/probe/atomic freeze → MCP submit → persist delivery result → render owner pending interaction → explicit `HumanDecisionPort` decision → controller-only MCP resume → exact same task get/presentation.

- [ ] **Step 1: RED real loopback MCP URL client.** Launch Product Front Door HTTP server on an ephemeral loopback port and negotiate/list/call through the installed MCP SDK. Direct Python service calls or in-process MCP object do not satisfy this test.
- [ ] **Step 2: RED response-loss + client-process restart after freeze.** Server accepts submit but client loses response; reopened SQLite/reference client uses the same explicit `client_submission_ref`, loads exact frozen request, does not call model, and resends same `task_id/session_ref/request_hash`.
- [ ] **Step 3: RED restart before freeze.** Existing correlation reloads its `SubmissionRecord(state=UNFROZEN)` and stored original utterance, then may call model again because no ProductTask exists. Same ref with a new utterance is conflict. The recovery path is proven after closing and reopening SQLite and does not require caller to supply utterance again.
- [ ] **Step 4: RED clarification.** Model clarification is shown to user and causes no MCP submit. v1 requires a new explicit `client_submission_ref` for a clarified utterance.
- [ ] **Step 5: RED human/model separation.** Model adapter is never passed MCP endpoint/tool metadata. Only `HumanDecisionPort` receives owner-derived pending interaction; only deterministic client code calls the resume MCP method.
- [ ] **Step 6: Implement CLI/reference entrypoints.** CLI accepts/generates a `client_submission_ref`, prints and flushes it before model/network work, and supports `--submission-ref <ref>` recovery. If an utterance is omitted during recovery, it reads the persisted `SubmissionRecord.utterance`; no synthetic frozen fields are required before freeze. Do not embed model vendor credentials.
- [ ] **Step 7: Implement presentation.** Keep `SUCCEEDED`, `RECOVERY_REQUIRED`, failed, cancelled, partial/diverged and `ACCEPTED_PRE_WORKFLOW` distinct; never infer success from transport completion.
- [ ] **Step 8: GREEN + absolute Ruff + commit.**

```bash
uv run pytest \
  tests/product_front_door/test_mcp_client.py \
  tests/product_front_door/test_reference_client.py -q -vv
git commit -m "feat: add MCP product reference client"
```

---

## Task 9: Prove durable concurrency, declared rebuild windows, and real-MCP offline product behavior

**Files:**
- Create: `tests/product_front_door/test_durable_recovery_postgres.py`
- Create: `tests/product_front_door/test_mcp_product_end_to_end.py`
- Create: `.github/workflows/product-front-door.yml`

**Mandatory scenarios:**

1. Correlation committed, client rebuilt before freeze → same stored utterance/correlation via `SubmissionRecord`; one eventual request.
2. Freeze committed, client rebuilt → exact request/binding/outbox recovered; no model call.
3. Two SQLite controller instances race same correlation/same proposal → one winner.
4. Same correlation but changed candidate config/target hash or conflicting proposal → one winner + one conflict.
5. Freeze committed, then the same candidate key is changed before the first MCP submit → server compares current canonical candidate hash to frozen `SessionBinding.candidate_hash` and fails before workflow progress.
6. MCP submit accepted but response lost → exact frozen replay; same server ProductTask identity.
7. Two independent ProductFlow/start-gate instances race same task against real PostgreSQL → one effective workflow lineage.
8. First start-gate holder dies before start → second holder continues exact persisted request.
9. First `start()` persists checkpoint then caller loses response → second submit sees checkpoint and does not call `start()` again.
10. Request committed, server composition rebuilt before workflow start → `get()` reports `ACCEPTED_PRE_WORKFLOW`; exact submit replay starts/reuses workflow; get itself does nothing.
11. Query request/checkpoint split-read race does not falsely report corruption.
12. Operation proposal accepted but configured policy denies → no Host mutation.
13. Positive offline path uses real loopback Streamable HTTP client/server, deterministic fake Agent interpreter, explicit fake HumanDecisionPort, real configured-policy code wired to the exact workflow ChangeSet/Scope stores, and only an external Revit transport fake; all platform owners/Gateway/Saga/Reconciliation are production code.
14. A deliberately wrong/parallel ChangeSet or ApprovalScope store graph causes configured-policy lineage resolution to fail closed; no authorization is fabricated.
15. Host unavailable after task creation → exact get still returns durable facts without session/Host access.
16. Submit and human resume are separate MCP calls and reuse the same exact-session composition handle/snapshot owner in the server process.
17. Candidate configuration/target under the same key changes after operation-proposal pause but before resume → frozen binding hash/candidate hash validation fails before workflow resume.
18. Deliberate Product Front Door server restart **after** ContextSnapshot/pause does not receive a fake success guarantee; if existing in-memory snapshot authority cannot reconstruct the task, the test records/returns the existing fail-closed behavior rather than adding process-local fallback or claiming unsupported recovery.

- [ ] **Step 1: Write RED cases with fresh PostgreSQL schemas and fresh SQLite files.** No shared singleton may provide persistence correctness.
- [ ] **Step 2: Use independent connections/process-shaped objects for concurrency and rebuild scenarios.** At least one case closes all old durable connections before replacement.
- [ ] **Step 3: Implement only minimum recovery fixes exposed by these REDs.** Do not add generic scheduler/listing/polling.
- [ ] **Step 4: Add `product-front-door.yml`.** PostgreSQL 17 service; focused front-door tests; ProductTask query/start-gate durability; real loopback MCP offline E2E; absolute Ruff for new paths and no-new diagnostics for legacy paths.
- [ ] **Step 5: GREEN locally and exact-head CI.**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" uv run pytest \
  tests/product_front_door/test_durable_recovery_postgres.py \
  tests/product_front_door/test_mcp_product_end_to_end.py -q -vv
```

- [ ] **Step 6: Commit.** `git commit -m "test: prove durable MCP product recovery"`.

---

## Task 10: Controlled real-model + real-MCP + human + policy + Revit acceptance and closeout

**Files:**
- Create: `docs/runbooks/mcp-agent-front-door.md`
- Create: `tests/integration/test_mcp_agent_front_door_live_support.py` for non-interactive readiness/supporting assertions only.
- Modify: `.github/workflows/product-front-door.yml` to collect/skip live support by default; GitHub-hosted CI MUST NOT fake the mandatory interactive gate.
- Update lifecycle metadata only at the appropriate branch/merged-main closeout point.

**Mandatory live inputs:**

```text
DSP_FRONT_DOOR_LIVE=1
DSP_AGENT_INTERPRETER_COMMAND=<real model command>
DSP_AGENT_MODEL_NAME=<recorded provider/model label>
DSP_FRONT_DOOR_CANDIDATES_FILE=<configured Revit candidates JSON>
DSP_FRONT_DOOR_POLICY_FILE=<real configured local policy JSON>
DSP_FRONT_DOOR_STATE_DB=<durable local SQLite DB>
DSP_FRONT_DOOR_HOST=127.0.0.1
DSP_FRONT_DOOR_PORT=8010
DSP_REVIT_VERSION
DSP_REVIT_TFM
DSP_REVIT_API_DIR
DSP_REVIT_PIPE
DSP_REVIT_FIXTURE
DSP_TEST_POSTGRES_DSN
```

**One exact lineage must be recorded:** natural-language utterance → `client_submission_ref` → model label/invocation evidence → proposal hash + frozen candidate hash/key → `session_ref`/binding hash/real host+document → ProductTask task id/request hash → real MCP submit → operation-proposal pause id/subject → explicit human decision → final ChangeSet/scope from the same owner stores read by configured policy → configured policy id/principal/policy hash → ApprovalAdmission id/fingerprint/times → Gateway ApprovalRecord id/hash → real Revit effect → independent read/verification/reconciliation → final same-task MCP get result.

- [ ] **Step 1: Add support-only live test.** It may validate environment, real Revit context and loopback MCP readiness; it MUST NOT auto-accept human HITL and MUST NOT be reported as the mandatory product acceptance.
- [ ] **Step 2: Write interactive runbook.** Start real Revit fixture, Product Front Door server and reference client; enter natural language; inspect constrained model proposal; explicitly accept/reject owner-derived operation proposal; observe configured policy admission; independently read back Revit.
- [ ] **Step 3: Negative controlled live case.** New task/ChangeSet with denying/mismatched policy and no prior durable admission: operation proposal may be accepted, but Host mutation count remains zero.
- [ ] **Step 4: Positive controlled live case.** Real model + real MCP + explicit human accept + configured policy admission + real Revit mutation + independent verification all share one task lineage.
- [ ] **Step 5: Record evidence without secrets.** Never record keys, tokens, DSNs or hidden model credentials; only the user-visible test utterance and non-secret lineage/evidence identifiers.
- [ ] **Step 6: Fresh exact-head branch verification.** Run both canonical pytest modes, Product Front Door workflow, Repository Regression, Workflow Orchestrator PostgreSQL and Durable Persistence. Require Ruff delta = 0 new diagnostics and unchanged exact HEAD after evidence capture.
- [ ] **Step 7: Open/review/merge only after offline and controlled live gates are GREEN.** Do not mark capability `COMPLETED` merely because feature-branch CI is green.
- [ ] **Step 8: Observe merged-main required workflows on the merge SHA.** Only after merged-main observation succeeds, perform the minimal lifecycle closeout that marks Front Door design/plan/capability completed. If merged-main is RED, lifecycle remains open.

---

# Cross-Task Verification Matrix

| Requirement | Owning task(s) |
| --- | --- |
| request/no-checkpoint query | 1, 9 |
| split-read query race | 1, 9 |
| concurrent first start + crash windows | 2, 9 |
| candidate/runtime discovery | 3, 4 |
| immutable SessionBinding + frozen candidate authority | 3, 4, 7, 9 |
| correlation utterance/restart identity | 4, 8, 9 |
| unfrozen correlation readable without synthetic request/session fields | 4, 8, 9 |
| duplicate/conflicting freeze + config drift | 4, 7, 9 |
| clarification before ProductTask | 4, 8 |
| configured policy default deny | 5 |
| exact `set_wall_thickness.v1` authorization | 5 |
| configured policy/workflow shared ChangeSet+Scope stores | 5, 6, 9 |
| durable admission identity/time replay | 5, 9 |
| same-owner Gateway consumed-admission retry | 5 |
| production reference composition | 6 |
| exact-session composition lifetime across MCP calls | 6, 7, 9 |
| Host-offline exact query | 1, 7, 9 |
| exact operation-proposal pause correlation | 7, 8 |
| model cannot human-resume/approve | 4, 7, 8, 10 |
| real Streamable HTTP MCP boundary | 7, 8, 9, 10 |
| client response-loss recovery | 4, 8, 9 |
| real model interpretation | 8, 10 |
| explicit human event | 8, 10 |
| no Host mutation before final admission | 5, 9, 10 |
| real Revit + independent verification | 10 |
| merged-main closure | 10 |

# Plan Self-Review

## Spec coverage

- Reliable submission/correlation, including restart before/after freeze: Tasks 4, 8, 9.
- Clarification before acceptance: Tasks 4 and 8.
- Session resolution and exact frozen candidate binding: Tasks 3, 4, 7.
- Product Front Door submit/get/resume: Tasks 1 and 7.
- Human/model authority separation: Tasks 7, 8, 10.
- Separate final execution admission with exact shared ChangeSet/Scope owners: Tasks 5, 6 and 10.
- Persisted request/no checkpoint query and race stabilization: Tasks 1 and 9.
- Concurrent first submit + crash/replay gate: Tasks 2 and 9.
- Real MCP + real model + real Revit acceptance: Tasks 8–10.
- Local-only trust boundary/no broad enumeration: Task 7.
- Existing in-memory semantic snapshot owner lifetime is explicitly bounded rather than misrepresented as new server-restart durability: Tasks 6, 7, 9.

No approved Spec requirement is intentionally deferred. The plan also avoids claiming a stronger arbitrary server-process restart guarantee than the approved Spec requires.

## Type/interface consistency

- `ProductTaskQueryService` is the sole new read composition; MCP `get()` consumes `ProductTaskQueryView` and never requires Host/session state.
- `SessionBinding` is create-once application identity evidence and carries frozen `candidate_hash`; server receives read-only `SessionBindingReadPort` only and compares current candidate authority to the frozen hash before Host-bound work.
- `ConfiguredRevitCandidateSource` owns deterministic project/target constraints; model output selects only a candidate key and supported thickness intent.
- `SubmissionRecord` represents both UNFROZEN and FROZEN correlation states; freeze-only fields exist only under `frozen` and are never synthesized before freeze.
- `NormalizedFreezeProposal` commits candidate configuration through `candidate_hash`, preventing config drift from appearing equivalent at freeze competition; `SessionBinding.candidate_hash` extends that authority to later server submit/resume.
- `ConfiguredPolicyApprovalAdmissionPort` implements existing `ApprovalAdmissionPort`; PostgreSQL admission storage preserves issuance evidence only; Gateway remains approval lifecycle authority.
- `ApprovalAdmissionFactory` receives the exact ChangeSet/ApprovalScope stores created by reference composition, preventing parallel store graphs or private-field coupling.
- Gateway strict first consumption remains intact; `consume_or_get_approval()` only recovers same-owner exact replay and does not claim new cross-process Gateway durability.
- Exact-session composition pool is a process-local handle to the existing in-memory snapshot owner, not business truth; `get()` does not depend on it.
- Agent output is either proposal or clarification. Human resume is a separate deterministic callback and is never model output.

## Proportion / YAGNI

The plan does not add remote authentication, user accounts, task search, general multi-Revit discovery, background document switching, multi-Host scheduling, async approval inbox, generic LLM tool orchestration, a generic ProductIntentIngress layer, or a new generalized network service. SQLite is limited to same-workstation client delivery plus create-once SessionBinding; PostgreSQL remains the server durable substrate already used by ProductTask/workflow/Saga plus one narrow policy-admission issuance table.

# Execution Handoff Gate

Implementation MUST NOT start merely because this file exists. Review this plan against design baseline `41247215ca4dc70d62e17577a68bfadc5fa1ec5c`. Pay special attention to Tasks 1, 2, 4, 5, 6, 7 and 10: read consistency, first-start serialization, pre-freeze correlation recovery, frozen candidate authority, shared owner-store construction, approval replay, composition lifetime, and final live authority separation are the highest-risk seams.