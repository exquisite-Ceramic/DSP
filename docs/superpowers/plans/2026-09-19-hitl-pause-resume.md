# HITL Pause / Resume Implementation Plan

**Status:** Proposed — written-plan review pending  
**Date:** 2026-09-19  
**Design:** `docs/superpowers/specs/2026-09-19-hitl-pause-resume-design.md`  

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 LangGraph interrupt/resume 骨架收敛成可观察、可相关、可跨进程恢复且 fail-closed 的 HITL pause/resume capability，并先补齐 checkpoint 所引用 workflow-local artifact 的真实 durability。

**Architecture:** Workflow Orchestrator 继续是唯一 workflow/HITL logical owner；LangGraph 只持久化 navigation/checkpoint，完整 workflow-local deterministic artifacts 通过独立 `WorkflowArtifactStore` 保存到 owner-local `orchestrator_artifact`。Human pause 使用 framework-neutral `PendingInteractionView + pause_id`；既有 `AsyncOperationRef` completion/poll 保持兼容；legacy Operation Proposal checkpoint 只能经过 exact-shape validation、legacy hash verification 和 v2 migration 后继续。

**Tech Stack:** Python 3.11/3.14、LangGraph 1.2.11、langgraph-checkpoint-postgres 3.1.2、psycopg 3.3.5、PostgreSQL 17、pytest 9.1.1、Ruff 0.16.7、GitHub Actions、.NET 10/Revit Core regression。

## Global Constraints

- `Workflow Orchestrator` 是 workflow progression/checkpoint/HITL authoritative logical owner；LangGraph 只是 v0.6 reference runtime。
- `orchestrator_checkpoint` 只保存 workflow navigation/checkpoint；`orchestrator_artifact` 只保存 Workflow Orchestrator 自己的 deterministic intermediate artifacts。
- checkpoint 不得保存完整 `ResolutionResult`、`BoundOperationProposal`、ChangeSet、ApprovalRecord、ExecutionGrant、Execution Saga、Host dispatch、SemanticProjection 或 ActualDelta authoritative object。
- `WorkflowArtifactStore` public protocol 保持 `put(kind, value, content_hash) -> StableRef` / `get(ref) -> object`，不得泄漏 PostgreSQL 类型。
- artifact codec 必须显式、versioned、JSON-compatible；禁止 pickle、Python repr、对象地址或任意 object serializer。
- `WorkflowResumeCommand.pause_id` 必须是 trailing optional field；既有 `resume_kind/payload` source compatibility 保持。
- Human Operation Proposal `ACCEPT/REJECT` payload 必须为空；existing async completion payload contract 不重写。
- `checkpoint_contract_version=2` 是 runtime-private；不得进入 `WorkflowCheckpointView` public contract。
- 新 workflow 从 `LangGraphWorkflowRuntime.start()` initial state 起必须写 version 2；不能等到 human pause 才补版本。
- v2 artifact 缺失/损坏只允许 fail closed；**只有 exact legacy checkpoint** 可以请求 rehydration。
- legacy rehydration 必须调用真实 `OperationResolver`，并用旧 hash 算法要求 recomputed hash 等于 old `operation_ref.content_hash`。
- `await_operation_proposal` node identity 必须保留；不得通过 bump namespace 遗弃旧 in-flight checkpoint。
- Step26 Interaction Coordinator、Step28/32 Gateway/approval、Execution Saga、Host plugin/sidecar、semantic owner、MCP/Agent front door 均不得改变 ownership。
- restart acceptance 必须使用真实 PostgreSQL artifact store；memory store 只能用于 unit/in-memory tests。
- 最终必须通过 Python 3.11 两种 pytest mode、Python 3.14、Ruff new diagnostics = 0、Workflow Orchestrator PostgreSQL、Durable Persistence PostgreSQL、Revit Core、.NET 10。

## Execution Topology

当前 `architecture/capability-hitl-pause-resume-design` 分支是 **artifact-only**：只允许 Design Spec、Implementation Plan、lifecycle/governance 文件与其 architecture test，不得写 production implementation。

书面 Plan review 通过后：

```text
freeze Plan = Approved plan
→ docs/architecture PR: architecture/capability-hitl-pause-resume-design -> main
→ write-access approval + protected-main checks
→ merge exact approved artifact head
→ verify exact merged main SHA
→ create feat/capability-hitl-pause-resume from merged main
→ Tasks 1–9 implementation commits
→ implementation PR -> main
→ approval + exact-head gates
→ merge exact implementation head
→ verify merged implementation main
→ docs-only capability closeout PR from merged main
→ mark HITL COMPLETED / successor real E2E NOT STARTED
→ merge closeout and verify final main
```

如果 Task 1 census 或后续 RED evidence 证明 approved Design Spec 的 owner/compatibility assumption 错误，停止实现并回到 design amendment；不得在 implementation PR 中暗改 contract。

## Review Focus

1. **Unversioned async compatibility:** 旧 `AsyncOperationRef` wait 仍允许现有 `ASYNC_OPERATION_COMPLETED` / poll；不能被 human legacy logic 误判。
2. **v2 corruption vs legacy:** version 2 的 human wait 缺 `pending_interaction` 必须 `WORKFLOW_CHECKPOINT_INVALID`。
3. **Artifact corruption before resume:** 新 v2 artifact 缺失/codec/hash 错误必须 `WORKFLOW_ARTIFACT_UNAVAILABLE` 且不消费 pause。
4. **Real restart continuation:** new runtime/new saver/new artifact store 接管后，ACCEPT 必须真实运行 `ParameterBinder`。
5. **Legacy memory-only ref:** 只允许 exact context-bound resolver rehydration；缺 hash/hash mismatch/input unavailable fail closed。

---

### Task 1: Freeze compatibility facts before production code

**Files:**
- Create: `docs/superpowers/reviews/2026-09-19-hitl-pause-resume-compatibility-census.md`
- Create: `tests/architecture/test_hitl_pause_resume_compatibility_census.py`

**Interfaces:** approved HITL spec §14 -> machine-readable six-area census.

- [ ] **Step 1: Write the failing architecture test**

```python
from pathlib import Path

CENSUS = Path(
    "docs/superpowers/reviews/2026-09-19-hitl-pause-resume-compatibility-census.md"
)
REQUIRED_AREAS = {
    "public_exports",
    "runtime_callers",
    "test_callers",
    "host_plugin_callers",
    "persisted_checkpoints",
    "artifact_store_impls",
}


def _rows(text: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for line in text.splitlines():
        if not line.startswith("| ") or "area" in line or "---" in line:
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 4:
            rows.append(
                dict(zip(("area", "evidence", "finding", "decision"), cells, strict=True))
            )
    return rows


def test_hitl_compatibility_census_is_complete_and_closed() -> None:
    rows = _rows(CENSUS.read_text(encoding="utf-8"))
    assert {row["area"] for row in rows} == REQUIRED_AREAS
    for row in rows:
        assert all(row.values())
        combined = " ".join(row.values()).upper()
        assert "TBD" not in combined
        assert "TODO" not in combined
        assert "UNKNOWN" not in combined
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/architecture/test_hitl_pause_resume_compatibility_census.py -q
```

Expected: FAIL because the census file is absent.

- [ ] **Step 3: Execute exact repository census**

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

Create exactly one row per required area. `artifact_store_impls` evidence must also list every repository `CapabilityProfile` implementation/shape that can enter `ResolutionResult.provider_candidates`, because Task 2 codec must preserve observed consumer/hash-relevant fields.

Use concrete paths/counts or `NONE_IN_REPOSITORY(<exact command>)`; do not infer repo-external absence.

- [ ] **Step 4: Freeze decisions**

Evidence-supported decisions must encode:

```text
public_exports        -> additive only
runtime_callers       -> preserve resume_kind/payload; pause_id trailing optional
test_callers          -> migrate human callers; preserve async callers
host_plugin_callers   -> record repository fact only; external state unproven
persisted_checkpoints -> classify old human and old async separately
artifact_store_impls  -> memory test-only; durable production adapter; codec covers observed profiles
```

A real contradiction stops the plan before Task 2 and triggers design amendment.

- [ ] **Step 5: GREEN + commit**

```bash
uv run pytest tests/architecture/test_hitl_pause_resume_compatibility_census.py -q
uv run ruff check tests/architecture/test_hitl_pause_resume_compatibility_census.py

git add docs/superpowers/reviews/2026-09-19-hitl-pause-resume-compatibility-census.md \
  tests/architecture/test_hitl_pause_resume_compatibility_census.py
git commit -m "docs: freeze HITL compatibility census"
```

---

### Task 2: Add explicit versioned workflow-artifact codecs

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/workflow_artifacts.py`
- Modify: `platform/orchestrator/src/design_orchestrator/default_workflow_services.py`
- Create: `tests/orchestrator/test_workflow_artifacts.py`
- Modify: `tests/orchestrator/test_default_workflow_services.py`

**Interfaces:**

```python
WORKFLOW_ARTIFACT_CODEC_VERSION = 1
PERSISTED_CAPABILITY_PROFILE_FIELDS = (...)

class WorkflowArtifactError(ValueError): ...
class WorkflowArtifactCodecError(WorkflowArtifactError): ...
class WorkflowArtifactUnavailableError(WorkflowArtifactError): ...

@dataclass(frozen=True, slots=True)
class PersistedCapabilityProfile: ...

def workflow_artifact_content_hash(value: object) -> str: ...
def legacy_workflow_artifact_content_hash(value: object) -> str: ...
def encode_workflow_artifact(*, kind: str, value: object) -> dict[str, object]: ...
def decode_workflow_artifact(
    *, kind: str, codec_version: int, payload: Mapping[str, object]
) -> object: ...
```

- [ ] **Step 1: Write RED round-trip + legacy-hash characterization tests**

Use real resolver/binder output. For `ResolutionResult`, compare `resolved_operations` and every field in `PERSISTED_CAPABILITY_PROFILE_FIELDS`, not concrete provider class identity. For `BoundOperationProposal`, require dataclass equality.

Before moving the old generic hash helper, freeze a real fixture proving:

```python
assert legacy_workflow_artifact_content_hash(resolution) == old_artifact_hash
```

where `old_artifact_hash` is produced by the pre-change `_artifact_content_hash()` behavior in the characterization fixture.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/orchestrator/test_workflow_artifacts.py -q
```

Expected: FAIL because `workflow_artifacts` is absent.

- [ ] **Step 3: Implement new explicit canonical hashing + preserved legacy hashing**

New artifacts hash only explicit codec payload:

```python
canonical = _canonical_artifact_payload(value)
payload = json.dumps(
    canonical,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
    allow_nan=False,
).encode("utf-8")
return sha256(payload).hexdigest()
```

Move the old generic normalization algorithm unchanged into `legacy_workflow_artifact_content_hash()` and use it **only** for old-ref verification in Task 7. New producers use `workflow_artifact_content_hash()`.

- [ ] **Step 4: Implement exact codecs**

Supported mapping only:

```text
operation_resolution      -> ResolutionResult
bound_operation_proposal  -> BoundOperationProposal
```

For `operation_resolution`, explicitly encode/reconstruct all `ResolvedOperation` fields and the observed `CapabilityProfile` protocol fields. Minimum fields:

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

If Task 1 proves extra current fields affect legacy hash/consumers, encode them explicitly; never fall back to `__dict__`.

Explicitly reconstruct enum-typed fields including `CanonicalExistenceEffect`. Provider candidates decode to `PersistedCapabilityProfile` satisfying `CapabilityProfile`.

For bound proposals explicitly reconstruct `CanonicalOperationRef`, arguments, `SlotBindingEvidence/SlotBindingClass`, `ContextSnapshotRef`, `PlanningRequirements`, `semantic_environment_ref`.

- [ ] **Step 5: Negative tests**

Reject unsupported kind/type, missing/extra keys, invalid nested enum and unknown codec version with `WorkflowArtifactCodecError`.

- [ ] **Step 6: GREEN + commit**

```bash
uv run pytest \
  tests/orchestrator/test_workflow_artifacts.py \
  tests/orchestrator/test_default_workflow_services.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/workflow_artifacts.py \
  platform/orchestrator/src/design_orchestrator/default_workflow_services.py \
  tests/orchestrator/test_workflow_artifacts.py

git add platform/orchestrator/src/design_orchestrator/workflow_artifacts.py \
  platform/orchestrator/src/design_orchestrator/default_workflow_services.py \
  tests/orchestrator/test_workflow_artifacts.py \
  tests/orchestrator/test_default_workflow_services.py
git commit -m "feat: add workflow artifact codecs"
```

---

### Task 3: Add owner-scoped PostgreSQL WorkflowArtifactStore

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/artifact_postgres.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Create: `tests/orchestrator/test_artifact_postgres.py`

**Interfaces:**

```python
class PostgresWorkflowArtifactStore(WorkflowArtifactStore):
    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef: ...
    def get(self, ref: StableRef) -> object: ...
    def close(self) -> None: ...


def create_postgres_artifact_store(dsn: str) -> PostgresWorkflowArtifactStore: ...
```

- [ ] **Step 1: RED PostgreSQL restart/schema test**

```python
store_a = create_postgres_artifact_store(_dsn())
ref = store_a.put(
    kind="operation_resolution",
    value=resolution,
    content_hash=workflow_artifact_content_hash(resolution),
)
store_a.close()

store_b = create_postgres_artifact_store(_dsn())
restored = store_b.get(ref)
assert restored.resolved_operations == resolution.resolved_operations
store_b.close()
```

Also query `information_schema.tables`: artifact tables exist only in `orchestrator_artifact`, never `public`, `orchestrator_checkpoint`, `execution_saga`, `gateway`, `semantic_runtime`.

- [ ] **Step 2: Verify RED**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/orchestrator/test_artifact_postgres.py -q
```

- [ ] **Step 3: Implement owner schema/table + connection lifecycle**

Equivalent schema:

```sql
CREATE TABLE IF NOT EXISTS workflow_artifact (
    artifact_id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    codec_version INTEGER NOT NULL,
    content_hash CHAR(64) NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (kind, content_hash)
)
```

Bootstrap via separate autocommit admin connection. Data connection is owned/closable, autocommit, with `SET search_path TO orchestrator_artifact`.

- [ ] **Step 4: Implement fail-closed idempotent `put()`**

Require supplied hash equals `workflow_artifact_content_hash(value)`. Insert opaque UUID; on `(kind, content_hash)` conflict return existing row/ref. Same semantic artifact -> same `StableRef`.

- [ ] **Step 5: Implement integrity-verifying `get()`**

Require `ref.content_hash`; load by opaque `artifact_id`, then verify row hash, known kind/version, decode, and re-hash decoded value. Missing row/integrity/codec failure -> `WorkflowArtifactUnavailableError`.

- [ ] **Step 6: Corruption/idempotency tests**

Prove payload tamper, codec version tamper and wrong ref hash all fail; duplicate put returns same ref; supplied mismatched hash is rejected before SQL; `close()` is idempotent.

Unit memory stores used by tests must also raise `WorkflowArtifactUnavailableError` for a missing/corrupt ref when they participate in Task 7 service tests, so production/test error semantics match.

- [ ] **Step 7: GREEN + commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest \
  tests/orchestrator/test_artifact_postgres.py \
  tests/orchestrator/test_postgres_checkpoint.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/artifact_postgres.py \
  tests/orchestrator/test_artifact_postgres.py

git add platform/orchestrator/src/design_orchestrator/artifact_postgres.py \
  platform/orchestrator/src/design_orchestrator/__init__.py \
  tests/orchestrator/test_artifact_postgres.py
git commit -m "feat: persist workflow artifacts in postgres"
```

---

### Task 4: Add framework-neutral HITL public contracts

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_contracts.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Modify: `tests/orchestrator/test_workflow_contracts.py`

**Interfaces:**

```python
class PendingInteractionKind(str, Enum):
    OPERATION_PROPOSAL = "OPERATION_PROPOSAL"

@dataclass(frozen=True, slots=True)
class PendingInteractionView:
    pause_id: str
    kind: PendingInteractionKind
    subject_ref: StableRef
    allowed_resume_kinds: tuple[str, ...]

class WorkflowPhase(str, Enum):
    ...
    CANCELLED = "CANCELLED"

@dataclass(frozen=True, slots=True)
class WorkflowResumeCommand:
    resume_kind: str
    payload: Mapping[str, object] = field(default_factory=dict)
    pause_id: str | None = None
```

`WorkflowCheckpointView` gains trailing `pending_interaction: PendingInteractionView | None = None`.

- [ ] **Step 1: RED public-contract tests**

Assert pause ID nonblank, allowed kinds nonempty/unique, CANCELLED projection, command field order exactly `resume_kind,payload,pause_id`, and pending interaction mutually exclusive with `async_operation_ref`/`interaction_ref`.

Also prove existing construction remains valid:

```python
command = WorkflowResumeCommand(
    resume_kind="ASYNC_OPERATION_COMPLETED",
    payload={"operation_id": "op-1"},
)
assert command.pause_id is None
```

- [ ] **Step 2: Verify RED**

```bash
uv run pytest tests/orchestrator/test_workflow_contracts.py -q
```

- [ ] **Step 3: Implement additive validation**

Normalize present pause ID; convert enum; require StableRef; normalize allowed kinds; reject duplicates/empty. `WorkflowCheckpointView` enforces human/external wait exclusivity. Do not globally reject command payload because async completion retains its payload.

- [ ] **Step 4: Export new types without removing old exports**

Update module/package `__all__`.

- [ ] **Step 5: GREEN + commit**

```bash
uv run pytest tests/orchestrator/test_workflow_contracts.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/workflow_contracts.py \
  tests/orchestrator/test_workflow_contracts.py

git add platform/orchestrator/src/design_orchestrator/workflow_contracts.py \
  platform/orchestrator/src/design_orchestrator/__init__.py \
  tests/orchestrator/test_workflow_contracts.py
git commit -m "feat: define HITL pause contracts"
```

---

### Task 5: Version and serialize pending-human checkpoint state

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_state.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_runtime.py`
- Create: `tests/orchestrator/test_hitl_checkpoint_state.py`
- Modify: `tests/orchestrator/test_langgraph_runtime.py`
- Modify: `tests/orchestrator/test_langgraph_graph.py`

**Interfaces:**

```python
CHECKPOINT_CONTRACT_VERSION = 2

def encode_pending_interaction(
    value: PendingInteractionView | None,
) -> dict[str, object] | None: ...

def decode_pending_interaction(
    value: object,
    field_name: str = "pending_interaction",
) -> PendingInteractionView | None: ...
```

`WorkflowGraphState` gains `checkpoint_contract_version: int` and `pending_interaction`.

- [ ] **Step 1: RED state/version tests**

Assert version 2 `AWAIT_OPERATION_PROPOSAL` without pending interaction fails; pending decoder rejects extra keys; runtime `start()` persisted snapshot contains version 2.

- [ ] **Step 2: Verify RED**

```bash
uv run pytest \
  tests/orchestrator/test_hitl_checkpoint_state.py \
  tests/orchestrator/test_langgraph_runtime.py -q
```

- [ ] **Step 3: Implement exact pending codec**

Persist only `pause_id`, `kind`, `subject_ref {ref_id,content_hash}`, `allowed_resume_kinds`.

- [ ] **Step 4: Implement version-aware state validation**

```text
version absent -> unversioned projection only; no synthetic pause here
version == 2   -> strict v2 validation
other version  -> ValueError
```

Recognized unversioned async state remains projectable; interrupt-aware classification belongs to Task 7 runtime.

- [ ] **Step 5: Write version 2 from `start()`**

`initial_state["checkpoint_contract_version"] = CHECKPOINT_CONTRACT_VERSION` before first graph invocation. Keep it private from `WorkflowCheckpointView`.

- [ ] **Step 6: Preserve authoritative-object guards**

Negative tests keep all existing forbidden object keys fail-closed.

- [ ] **Step 7: GREEN + commit**

```bash
uv run pytest \
  tests/orchestrator/test_hitl_checkpoint_state.py \
  tests/orchestrator/test_langgraph_runtime.py \
  tests/orchestrator/test_langgraph_graph.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/langgraph_state.py \
  platform/orchestrator/src/design_orchestrator/langgraph_runtime.py \
  tests/orchestrator/test_hitl_checkpoint_state.py

git add platform/orchestrator/src/design_orchestrator/langgraph_state.py \
  platform/orchestrator/src/design_orchestrator/langgraph_runtime.py \
  tests/orchestrator/test_hitl_checkpoint_state.py \
  tests/orchestrator/test_langgraph_runtime.py \
  tests/orchestrator/test_langgraph_graph.py
git commit -m "feat: version HITL checkpoint state"
```

---

### Task 6: Split prepare/interrupt and implement ACCEPT/REJECT

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify: `tests/orchestrator/test_langgraph_graph.py`

**Topology:**

```text
resolve_operations
→ prepare_operation_proposal_pause
→ await_operation_proposal
→ parameter_binding | END(CANCELLED)
```

`await_operation_proposal` name remains unchanged.

- [ ] **Step 1: RED topology/pause tests**

Assert prepare node precedes await node and paused state contains version 2, UUID pause, subject_ref==operation_ref, no async ref.

- [ ] **Step 2: RED ACCEPT/REJECT tests**

ACCEPT runtime-private resume shape:

```python
{
    "pause_id": pause_id,
    "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
    "payload": {},
}
```

Assert ACCEPT clears pending and reaches binding. REJECT reaches CANCELLED/END with no binder/downstream service call.

- [ ] **Step 3: Verify RED**

```bash
uv run pytest tests/orchestrator/test_langgraph_graph.py -q
```

- [ ] **Step 4: Implement prepare node**

Generate `str(uuid4())` only here; return encoded `PendingInteractionView`. Await node never creates identity. Interrupt exposes only pause_id/kind/stable subject ref.

- [ ] **Step 5: Defense-in-depth parsing in await node**

Require exact resume keys, matching pause ID, allowed resume kind and empty human payload. Conditional edge routes ACCEPT to parameter binding, REJECT to END.

- [ ] **Step 6: Prove async topology unchanged**

Keep `await_async_operation`, `_ASYNC_RESUME_NODES`, owner-refresh ordering and `ASYNC_OPERATION` interrupt behavior unchanged; run existing recovery tests.

- [ ] **Step 7: GREEN + commit**

```bash
uv run pytest \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_workflow_resume_authoritative_truth.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py

git add platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py
git commit -m "feat: implement correlated HITL graph pause"
```

---

### Task 7: Validate resume mode, recover artifacts, migrate exact legacy checkpoints

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/hitl_resume.py`
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/default_workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_runtime.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Create: `tests/orchestrator/test_hitl_resume.py`
- Modify: `tests/orchestrator/test_langgraph_runtime.py`

**Interfaces:**

```python
@dataclass(frozen=True, slots=True)
class OperationArtifactResolution:
    ref: StableRef
    source: str  # "durable" | "rehydrated"


def synthetic_legacy_operation_proposal_pause(
    *, task_id: str, operation_ref: StableRef
) -> PendingInteractionView: ...


def validate_resume_mode(
    *, checkpoint: WorkflowCheckpointView, command: WorkflowResumeCommand | None
) -> str: ...  # "human" | "async" | "poll"
```

Extend `WorkflowServices`:

```python
def ensure_operation_artifact(
    self,
    operation_ref: StableRef,
    context_snapshot_ref: StableRef,
    *,
    allow_legacy_rehydrate: bool,
) -> OperationArtifactResolution: ...
```

- [ ] **Step 1: RED resume-validation tests**

Stable behavior:

```text
human + command=None                  -> WORKFLOW_RESUME_INVALID
human + pause_id=None                 -> WORKFLOW_RESUME_INVALID
human + wrong pause                   -> WORKFLOW_RESUME_STALE
human + right pause/wrong kind        -> WORKFLOW_RESUME_MISMATCH
human + nonempty payload              -> WORKFLOW_RESUME_INVALID
async/no-human + pause_id != None     -> WORKFLOW_RESUME_STALE
async + old command pause_id=None     -> async
async + command=None                  -> poll
consumed/superseded human pause replay-> WORKFLOW_RESUME_STALE
```

- [ ] **Step 2: Implement synthetic legacy pause identity**

Canonical compact sorted JSON includes contract string, normalized task_id, operation_ref.ref_id and explicit nullable content_hash; SHA-256 prefix is `legacy-op-proposal:`.

- [ ] **Step 3: Implement artifact availability with explicit legacy permission**

First try `artifact_store.get(operation_ref)` and require `ResolutionResult`; success returns:

```python
OperationArtifactResolution(ref=operation_ref, source="durable")
```

If unavailable and `allow_legacy_rehydrate is False`, immediately re-raise `WorkflowArtifactUnavailableError` — **no rehydration for v2 corruption**.

If unavailable and `allow_legacy_rehydrate is True`:

```text
require old content_hash
load exact OperationResolutionInputs from context_snapshot_ref
run real OperationResolver
compute legacy_workflow_artifact_content_hash(resolution)
require exact equality with old hash
put new artifact using NEW workflow_artifact_content_hash(resolution)
return OperationArtifactResolution(new_ref, "rehydrated")
```

Missing inputs/hash/mismatch -> `WorkflowArtifactUnavailableError`.

- [ ] **Step 4: Build real old-graph interrupt fixtures**

Do **not** seed legacy state through new topology. Define test-only old graphs with exact old node names/payloads:

```python
def _build_legacy_operation_proposal_graph(checkpointer):
    builder = StateGraph(WorkflowGraphState)

    def await_operation_proposal(state: WorkflowGraphState) -> dict[str, object]:
        operation_ref = _decode_stable_ref(state["operation_ref"], "operation_ref")
        assert operation_ref is not None
        interrupt(
            {
                "kind": "OPERATION_PROPOSAL",
                "operation_ref": _encode_stable_ref(operation_ref),
            }
        )
        return {"phase": WorkflowPhase.PARAMETER_BINDING.value}

    builder.add_node("await_operation_proposal", await_operation_proposal)
    builder.add_edge(START, "await_operation_proposal")
    builder.add_edge("await_operation_proposal", END)
    return builder.compile(checkpointer=checkpointer)
```

Invoke it with unversioned old state to create a real pending interrupt, then open the same checkpointer with new runtime. Create a separate old `await_async_operation` fixture to prove old async wait compatibility.

- [ ] **Step 5: Implement interrupt-aware checkpoint projection**

Runtime sees both `snapshot.values` and `snapshot.interrupts`:

```text
version == 2 -> strict public checkpoint
unversioned exact Operation Proposal + real interrupt -> synthetic pending view
unversioned async_operation_ref + real interrupt -> old async checkpoint
other interrupt-bearing unversioned shape -> WORKFLOW_CHECKPOINT_INVALID
```

`graph_state_to_checkpoint_view()` never guesses interrupt presence.

- [ ] **Step 6: Migrate exact legacy human state before consuming command**

1. validate command vs synthetic pause;
2. `ensure_operation_artifact(... allow_legacy_rehydrate=True)`;
3. build v2 pending with **same synthetic pause_id** + returned durable ref;
4. call:

```python
migrated_config = self._graph.update_state(
    _checkpoint_lookup_config(task_id),
    {
        "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
        "operation_ref": _encode_stable_ref(resolution.ref),
        "pending_interaction": encode_pending_interaction(migrated_pending),
        "async_operation_ref": None,
        "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
    },
    as_node="prepare_operation_proposal_pause",
)
self._graph.invoke(None, migrated_config)
```

5. reload root snapshot; require real v2 `await_operation_proposal` interrupt;
6. revalidate same command;
7. then `Command(resume=...)`.

Artifact recovery failure occurs before `update_state`, preserving old pause.

- [ ] **Step 7: Validate new v2 human resume before graph invocation**

For v2 human:

```python
resolution = services.ensure_operation_artifact(
    pending.subject_ref,
    checkpoint.context_snapshot_ref,
    allow_legacy_rehydrate=False,
)
assert resolution.source == "durable"
assert resolution.ref == pending.subject_ref
```

Then construct runtime-private `Command(resume={pause_id,resume_kind,payload})`. Artifact failure normalizes to stable `WORKFLOW_ARTIFACT_UNAVAILABLE`, preserving original cause and unchanged checkpoint.

Async wait keeps old `pause_id=None` command/poll and never invokes operation-artifact recovery merely because there is a LangGraph interrupt.

- [ ] **Step 8: Add non-sensitive structured observability**

Use module logger + `extra` fields:

```text
task_id
pause_id                # human only
pending_kind            # human only
resume_kind
resume_mode              # human | async | poll
artifact_ref
artifact_content_hash
artifact_source          # durable | rehydrated
checkpoint_contract_version
result                   # accepted | rejected | stale | mismatch | invalid | unavailable | continued
```

`caplog` tests inspect attributes and prove command payload/domain bodies are not logged.

- [ ] **Step 9: GREEN + commit**

```bash
uv run pytest \
  tests/orchestrator/test_hitl_resume.py \
  tests/orchestrator/test_langgraph_runtime.py \
  tests/orchestrator/test_workflow_resume_authoritative_truth.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/hitl_resume.py \
  platform/orchestrator/src/design_orchestrator/langgraph_runtime.py \
  platform/orchestrator/src/design_orchestrator/default_workflow_services.py \
  tests/orchestrator/test_hitl_resume.py

git add platform/orchestrator/src/design_orchestrator/hitl_resume.py \
  platform/orchestrator/src/design_orchestrator/workflow_services.py \
  platform/orchestrator/src/design_orchestrator/default_workflow_services.py \
  platform/orchestrator/src/design_orchestrator/langgraph_runtime.py \
  platform/orchestrator/src/design_orchestrator/__init__.py \
  tests/orchestrator/test_hitl_resume.py \
  tests/orchestrator/test_langgraph_runtime.py
git commit -m "feat: validate and migrate HITL resume"
```

---

### Task 8: Move PostgreSQL restart acceptance to the human pause boundary

**Files:**
- Modify: `tests/orchestrator/test_workflow_end_to_end.py`
- Modify: `tests/orchestrator/test_postgres_checkpoint.py`
- Modify: `.github/workflows/workflow-orchestrator.yml`
- Modify: `docs/runbooks/workflow-orchestrator-recovery.md`

- [ ] **Step 1: Use real durable artifact adapter in E2E**

Change helper annotation to `WorkflowArtifactStore | None`. Runtime A uses new PostgreSQL saver + new PostgreSQL artifact store and stops at Operation Proposal human pause. Capture pause/subject then explicitly close both stores.

- [ ] **Step 2: Reconstruct all process-owned objects**

Runtime B uses new saver/store/service/runtime. Require same pending interaction and `artifact_store_b.get(subject_ref)` returns `ResolutionResult`.

ACCEPT with empty payload + exact pause ID must execute real `ParameterBinder` and reach existing async path.

- [ ] **Step 3: Preserve async completion behavior**

Later command remains:

```python
WorkflowResumeCommand(
    resume_kind="ASYNC_OPERATION_COMPLETED",
    payload={"operation_id": "reconstruction-task9"},
)
```

No pause ID. Existing execution-owner recovery/final completion remains green.

- [ ] **Step 4: Stale replay + v2 corruption acceptance**

After ACCEPT, re-submit original human command -> `WORKFLOW_RESUME_STALE`, even if current wait is async.

Separate case: delete/corrupt v2 subject artifact while paused. Resume -> `WORKFLOW_ARTIFACT_UNAVAILABLE`; same pause remains; external-owner mutation counters stay zero; no rehydration occurs.

- [ ] **Step 5: Update recovery runbook**

Document:

```text
orchestrator_checkpoint = navigation/wait
orchestrator_artifact   = workflow-local deterministic continuation artifact
active/paused reachable artifact ref => GC forbidden
WORKFLOW_ARTIFACT_UNAVAILABLE => no manual row editing
legacy-only rehydration = authoritative inputs + exact legacy hash equality
```

Do not change execution-owner/Host recovery ownership.

- [ ] **Step 6: Existing PostgreSQL 17 workflow must execute new gates**

```bash
DSP_TEST_POSTGRES_DSN='postgresql://postgres:postgres@localhost:5432/dsp_test' \
  uv run python -m pytest \
  tests/orchestrator/test_artifact_postgres.py \
  tests/orchestrator/test_postgres_checkpoint.py \
  tests/orchestrator/test_workflow_end_to_end.py -q
```

- [ ] **Step 7: GREEN + commit**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest \
  tests/orchestrator/test_artifact_postgres.py \
  tests/orchestrator/test_postgres_checkpoint.py \
  tests/orchestrator/test_workflow_end_to_end.py -q

git add tests/orchestrator/test_workflow_end_to_end.py \
  tests/orchestrator/test_postgres_checkpoint.py \
  .github/workflows/workflow-orchestrator.yml \
  docs/runbooks/workflow-orchestrator-recovery.md
git commit -m "test: prove HITL restart durability"
```

---

### Task 9: Verify exact implementation head, merge, then close lifecycle truth

**Files before implementation merge:**
- No lifecycle completion claim yet; `docs/superpowers/README.md` remains HITL CURRENT / successor not started.

**Files after implementation merge:**
- Modify on a docs-only closeout branch: `docs/superpowers/README.md`
- Optionally update compatibility census only if merged-main evidence changes a recorded fact.

- [ ] **Step 1: Targeted orchestrator regression**

```bash
uv run pytest tests/orchestrator -q
uv run pytest tests/architecture/test_hitl_pause_resume_compatibility_census.py -q
```

- [ ] **Step 2: PostgreSQL owner gates when DSN is available**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/orchestrator -q
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/execution_reconciliation -q
```

- [ ] **Step 3: Canonical repository regression**

```bash
uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
uv run ruff check --select E,F,I platform hosts/autocad/sidecar tests

dotnet test \
  hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj \
  -f net8.0
```

Ruff acceptance = new diagnostics 0 relative to implementation branch base.

- [ ] **Step 4: Architecture/source boundary audit**

Prove no LangGraph type leaks from public workflow contracts, no PostgreSQL type leaks from `WorkflowArtifactStore`, no Step26 InteractionSession/Approval/Saga/Host/Semantic authoritative object is persisted as Orchestrator state, no Temporal dependency, and no Host plugin/sidecar production-contract change.

- [ ] **Step 5: Push exact implementation head and require fresh CI**

```bash
git rev-parse HEAD
```

Fresh successful runs:

```text
Repository regression
  Python 3.11 (canonical)
  Python 3.14 (compatibility)
  revit-core
  .NET 10 (Host-neutral compatibility)
Workflow orchestrator PostgreSQL verification
Durable persistence verification
```

- [ ] **Step 6: Open implementation PR**

```text
base = main
head = feat/capability-hitl-pause-resume
scope = Tasks 1–8 + verification evidence only
```

PR body names approved spec, exact head, tests/workflows and non-goals. Require protected-main write-access approval and all required checks; no bypass.

- [ ] **Step 7: Merge exact implementation head and verify merged main**

Merge only if PR head still equals verified SHA. Verify resulting `main` contains exact implementation ancestry and no unreviewed delta. If merge-main workflows trigger, require green.

- [ ] **Step 8: Create docs-only lifecycle closeout from merged implementation main**

Update README truth to:

```text
Capability Phase — HITL pause/resume COMPLETED
Capability Phase successor — real E2E workflow, NOT YET STARTED
```

Mark `2026-09-19-hitl-pause-resume.md` `COMPLETED` only here, after implementation exists on main. Update the lifecycle architecture test accordingly.

Commit:

```bash
git add docs/superpowers/README.md tests/architecture/test_document_lifecycle_index.py
git commit -m "docs: close HITL pause resume capability"
```

- [ ] **Step 9: Closeout PR + final main verification**

Open docs-only closeout PR to main, obtain required approval/checks, merge exact closeout head, verify final main and any triggered workflows. Only then declare HITL capability closed.

- [ ] **Step 10: Completion audit**

Confirm all twelve Design Spec §20 criteria with exact implementation/closeout commit and workflow evidence. Successor work may start only after this final merged-main verification:

```text
real E2E workflow
```

---

## Plan Self-Review Checklist

- [ ] Task 1 completes all six census areas before production code.
- [ ] Durable artifact codec/store precedes HITL restart claims.
- [ ] New explicit artifact hash and preserved legacy hash have separate purposes.
- [ ] `WorkflowResumeCommand` preserves `resume_kind/payload`; `pause_id` is trailing optional.
- [ ] Existing async command/poll path remains supported.
- [ ] Version 2 is written from initial start state and corrupted v2 cannot masquerade as legacy.
- [ ] Legacy human tests create a real old interrupt using an old graph fixture.
- [ ] Unversioned async wait is separately tested and remains supported.
- [ ] `allow_legacy_rehydrate=False` makes new-v2 artifact corruption fail closed.
- [ ] Legacy rehydration uses real resolver + exact old hash, then writes a new-hash durable artifact.
- [ ] `await_operation_proposal` node identity remains compatible.
- [ ] PostgreSQL restart occurs at human pause with new saver/store/service/runtime.
- [ ] ACCEPT reaches real ParameterBinder; REJECT reaches CANCELLED without downstream calls.
- [ ] Artifact failure occurs before graph progression and preserves pending pause.
- [ ] Replayed consumed human pause returns STALE even after routing to async wait.
- [ ] Observability contains only workflow-local metadata, never command/domain payload bodies.
- [ ] No Host/Gateway/Saga/Interaction/Semantic/MCP ownership expansion exists.
- [ ] Design+Plan artifact PR is merged before implementation branch creation.
- [ ] Implementation exact-head CI is green before implementation PR merge.
- [ ] Lifecycle says COMPLETED only in a docs-only closeout created from merged implementation main.
- [ ] Final main is verified before starting real E2E workflow.
