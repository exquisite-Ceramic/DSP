# HITL Pause / Resume Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把现有 LangGraph interrupt/resume 骨架收敛成可观察、可相关、可跨进程恢复且 fail-closed 的 HITL pause/resume capability，并先补齐 checkpoint 所引用 workflow-local artifact 的真实 durability。

**Architecture:** Workflow Orchestrator 继续是唯一 workflow/HITL logical owner；LangGraph 只保留 navigation/checkpoint，完整 workflow-local deterministic artifacts 通过独立 `WorkflowArtifactStore` 持久化到 owner-local `orchestrator_artifact` schema。Human pause 使用 framework-neutral `PendingInteractionView + pause_id`；既有 `AsyncOperationRef` completion/poll 路径保持兼容；legacy Operation Proposal checkpoint 只能经过 exact-shape validation、artifact hash verification 和 v2 migration 后继续。

**Tech Stack:** Python 3.11/3.14、LangGraph 1.2.11、langgraph-checkpoint-postgres 3.1.2、psycopg 3.3.5、PostgreSQL 17、pytest 9.1.1、Ruff 0.16.7、GitHub Actions、.NET 10/Revit Core regression。

**Spec:** `docs/superpowers/specs/2026-09-19-hitl-pause-resume-design.md`

## Global Constraints

- `Workflow Orchestrator` 是 workflow progression/checkpoint/HITL authoritative logical owner；LangGraph 只是 v0.6 reference runtime。
- `orchestrator_checkpoint` 只保存 workflow navigation/checkpoint；新的 `orchestrator_artifact` 只保存 Workflow Orchestrator 自己的 deterministic intermediate artifacts。
- checkpoint 不得保存完整 `ResolutionResult`、`BoundOperationProposal`、ChangeSet、ApprovalRecord、ExecutionGrant、Execution Saga、Host dispatch、SemanticProjection 或 ActualDelta authoritative object。
- `WorkflowArtifactStore` public protocol 保持 `put(kind, value, content_hash) -> StableRef` / `get(ref) -> object`，不得泄漏 PostgreSQL 类型。
- artifact codec 必须显式、versioned、JSON-compatible；禁止 pickle、Python repr、对象地址或任意 object serializer。
- `WorkflowResumeCommand.pause_id` 必须是 trailing optional field；既有 `resume_kind/payload` source compatibility 保持。
- Human Operation Proposal `ACCEPT/REJECT` payload 必须为空；existing async completion payload contract 不重写。
- `checkpoint_contract_version=2` 是 runtime-private；不得进入 `WorkflowCheckpointView` public contract。
- v2 human checkpoint corruption 不得降级成 legacy；legacy human migration 必须要求 exact old shape + real pending interrupt。
- legacy artifact rehydration 必须重新调用真实 `OperationResolver`，并要求 recomputed hash 等于 old `operation_ref.content_hash`。
- `await_operation_proposal` node identity 必须保留；不得通过 bump namespace 遗弃旧 in-flight checkpoint。
- Step26 Interaction Coordinator、Step28/32 Gateway/approval、Execution Saga、Host plugin/sidecar、semantic owner、MCP/Agent front door均不得改变 ownership。
- 任何 restart acceptance 必须使用真实 PostgreSQL artifact store；memory store 只能用于 unit/in-memory tests。
- 最终必须通过 Python 3.11 两种 pytest mode、Python 3.14、Ruff new diagnostics = 0、Workflow Orchestrator PostgreSQL、Durable Persistence PostgreSQL、Revit Core、.NET 10。

## Review Focus

1. **Unversioned async checkpoint compatibility:** 升级后旧 `AsyncOperationRef` wait 仍必须允许现有 `ASYNC_OPERATION_COMPLETED` / poll 语义；不能因 human legacy migration 把它误判为 invalid。
2. **v2 corruption vs legacy:** `checkpoint_contract_version=2 + AWAIT_OPERATION_PROPOSAL + missing pending_interaction` 必须 `WORKFLOW_CHECKPOINT_INVALID`，不能 synthetic legacy pause。
3. **Artifact corruption before resume:** artifact row 缺失、codec/version 错误或 hash mismatch 时 human pause 必须保持未消费，并返回 `WORKFLOW_ARTIFACT_UNAVAILABLE`。
4. **Real continuation after process restart:** 新 runtime/new saver/new artifact store 接管 human pause 后，ACCEPT 必须真实运行 `ParameterBinder`，而不是只让 checkpoint phase 前移。
5. **Legacy memory-only operation artifact:** 只允许用 exact `context_snapshot_ref` 重跑真实 `OperationResolver`；hash mismatch/缺 hash/输入不可得必须 fail closed。

---

### Task 1: Freeze the compatibility census before production code

**Files:**
- Create: `docs/superpowers/reviews/2026-09-19-hitl-pause-resume-compatibility-census.md`
- Create: `tests/architecture/test_hitl_pause_resume_compatibility_census.py`

**Interfaces:**
- Consumes: approved HITL spec §14 and current merged-main public/runtime surfaces.
- Produces: a machine-readable six-area census that later tasks must not contradict.

- [ ] **Step 1: Write the RED architecture test**

Create `tests/architecture/test_hitl_pause_resume_compatibility_census.py`:

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
    text = CENSUS.read_text(encoding="utf-8")
    rows = _rows(text)
    assert {row["area"] for row in rows} == REQUIRED_AREAS
    for row in rows:
        assert row["evidence"]
        assert row["finding"]
        assert row["decision"]
        combined = " ".join(row.values()).upper()
        assert "TBD" not in combined
        assert "TODO" not in combined
        assert "UNKNOWN" not in combined
```

- [ ] **Step 2: Run RED**

Run:

```bash
uv run pytest tests/architecture/test_hitl_pause_resume_compatibility_census.py -q
```

Expected: FAIL because the census document does not exist.

- [ ] **Step 3: Execute the exact repository census**

Run all commands from repository root and copy the exact path/line findings into the census:

```bash
rg -n "WorkflowResumeCommand|WorkflowCheckpointView|PendingInteraction" \
  platform hosts tests contracts

rg -n "WorkflowResumeCommand\(" platform hosts tests

rg -n "WorkflowArtifactStore|_MemoryArtifactStore|artifact_store" \
  platform hosts tests

rg -n "await_operation_proposal|ASYNC_OPERATION_COMPLETED|resume\(.*None" \
  platform hosts tests

rg -n "orchestrator_checkpoint|checkpoint_ns|operation_ref" \
  platform tests docs/runbooks .github/workflows

rg -n "design_orchestrator.*workflow|workflow_contracts|workflow_port" \
  hosts contracts
```

Create exactly one row for each required area. Use concrete file paths/counts or `NONE_IN_REPOSITORY(<exact rg command>)`; do not use guessed external consumers.

- [ ] **Step 4: Freeze compatibility decisions in the census**

The six decisions must encode these rules when supported by the actual census:

```text
public_exports       -> additive only; keep existing names
runtime_callers      -> resume_kind/payload preserved; pause_id trailing optional
 test_callers         -> migrate human callers; preserve async completion callers
host_plugin_callers  -> if none in repository, record NONE_IN_REPOSITORY; do not infer repo-external absence
persisted_checkpoints-> recognize old human and old async shapes separately
artifact_store_impls -> memory remains test-only; production restart requires durable adapter
```

If the census reveals a real Host/plugin/external repository caller that contradicts an additive change, stop this plan before Task 2 and amend the design.

- [ ] **Step 5: Run GREEN and commit**

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
- Test: `tests/orchestrator/test_workflow_artifacts.py`
- Test: `tests/orchestrator/test_default_workflow_services.py`

**Interfaces:**
- Consumes: `ResolutionResult`, `ResolvedOperation`, `CapabilityProfile`, `BoundOperationProposal`, `StableRef`.
- Produces:

```python
WORKFLOW_ARTIFACT_CODEC_VERSION = 1

class WorkflowArtifactCodecError(ValueError): ...

@dataclass(frozen=True, slots=True)
class PersistedCapabilityProfile: ...

def workflow_artifact_content_hash(value: object) -> str: ...
def encode_workflow_artifact(*, kind: str, value: object) -> dict[str, object]: ...
def decode_workflow_artifact(
    *, kind: str, codec_version: int, payload: Mapping[str, object]
) -> object: ...
```

- [ ] **Step 1: Write RED codec round-trip tests**

Create tests that use real resolver/binder output, not hand-written fake payloads:

```python
def test_operation_resolution_codec_round_trips_real_resolution(sample_resolution):
    payload = encode_workflow_artifact(kind="operation_resolution", value=sample_resolution)
    restored = decode_workflow_artifact(
        kind="operation_resolution",
        codec_version=WORKFLOW_ARTIFACT_CODEC_VERSION,
        payload=payload,
    )
    assert isinstance(restored, ResolutionResult)
    assert restored.resolved_operations == sample_resolution.resolved_operations
    assert sorted(restored.provider_candidates) == sorted(sample_resolution.provider_candidates)
    assert workflow_artifact_content_hash(restored) == workflow_artifact_content_hash(
        sample_resolution
    )


def test_bound_operation_proposal_codec_round_trips_real_binding(sample_bound):
    payload = encode_workflow_artifact(
        kind="bound_operation_proposal",
        value=sample_bound,
    )
    restored = decode_workflow_artifact(
        kind="bound_operation_proposal",
        codec_version=WORKFLOW_ARTIFACT_CODEC_VERSION,
        payload=payload,
    )
    assert restored == sample_bound
    assert workflow_artifact_content_hash(restored) == workflow_artifact_content_hash(
        sample_bound
    )
```

Also assert unknown kind/version fail with `WorkflowArtifactCodecError`.

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/orchestrator/test_workflow_artifacts.py -q
```

Expected: FAIL because `workflow_artifacts` does not exist.

- [ ] **Step 3: Implement the deterministic hash in one owner module**

Move the existing normalization semantics out of `default_workflow_services.py` without changing its digest contract:

```python
def workflow_artifact_content_hash(value: object) -> str:
    normalized = _normalize_for_hash(value)
    payload = json.dumps(
        normalized,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return sha256(payload).hexdigest()
```

`DefaultWorkflowServices.resolve_operations()` and `.bind_parameters()` must call this shared function so persisted codec verification and producer hash calculation cannot drift.

- [ ] **Step 4: Implement exact v1 codecs**

`encode_workflow_artifact()` must accept only:

```text
operation_resolution      -> ResolutionResult
bound_operation_proposal  -> BoundOperationProposal
```

For `operation_resolution`, encode every `ResolvedOperation` field plus provider candidates as an explicit `PersistedCapabilityProfile` shape containing:

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

Decode `existence_effects` back to `CanonicalExistenceEffect`, and decode provider candidates into `PersistedCapabilityProfile` instances satisfying the existing `CapabilityProfile` protocol.

For `bound_operation_proposal`, explicitly reconstruct:

```text
CanonicalOperationRef
arguments
SlotBindingEvidence + SlotBindingClass
ContextSnapshotRef
PlanningRequirements
semantic_environment_ref
```

Do not use `pickle`, `repr`, `__dict__` as persisted wire shape, or class-path imports stored in payload.

- [ ] **Step 5: Add deterministic negative tests**

Cover malformed payload keys, wrong nested enum values, wrong Python type for a declared kind, and codec version `2`:

```python
with pytest.raises(WorkflowArtifactCodecError):
    decode_workflow_artifact(
        kind="operation_resolution",
        codec_version=2,
        payload=payload,
    )
```

- [ ] **Step 6: Run GREEN and commit**

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

### Task 3: Add the owner-scoped PostgreSQL WorkflowArtifactStore

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/artifact_postgres.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Create: `tests/orchestrator/test_artifact_postgres.py`

**Interfaces:**
- Consumes: `WorkflowArtifactStore`, Task 2 codec/hash functions.
- Produces:

```python
class PostgresWorkflowArtifactStore(WorkflowArtifactStore):
    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef: ...
    def get(self, ref: StableRef) -> object: ...
    def close(self) -> None: ...


def create_postgres_artifact_store(dsn: str) -> PostgresWorkflowArtifactStore: ...
```

- [ ] **Step 1: Write RED schema/restart tests**

Use `DSP_TEST_POSTGRES_DSN` and a clean `orchestrator_artifact` schema. Assert:

```python
store_a = create_postgres_artifact_store(_dsn())
ref = store_a.put(
    kind="operation_resolution",
    value=resolution,
    content_hash=workflow_artifact_content_hash(resolution),
)
store_a.close()

store_b = create_postgres_artifact_store(_dsn())
assert store_b.get(ref) == resolution
store_b.close()
```

Query `information_schema.tables` and assert artifact tables live in `orchestrator_artifact`, not `public`, `orchestrator_checkpoint`, `execution_saga`, `gateway`, or `semantic_runtime`.

- [ ] **Step 2: Run RED**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/orchestrator/test_artifact_postgres.py -q
```

Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: Implement schema bootstrap and owned connection**

Create a fixed schema constant and one owner table equivalent to:

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

Bootstrap schema with a separate autocommit admin connection, then open the store connection with:

```sql
SET search_path TO orchestrator_artifact
```

The adapter owns and explicitly closes that connection, mirroring `OwnedPostgresSaver` lifecycle discipline.

- [ ] **Step 4: Implement `put()` fail-closed and idempotent**

Before SQL write:

```python
actual_hash = workflow_artifact_content_hash(value)
if actual_hash != content_hash:
    raise WorkflowArtifactCodecError("artifact content_hash does not match value")
```

Encode using codec version `1`. Insert a new opaque UUID `artifact_id`; on `UNIQUE(kind, content_hash)` conflict, select and return the existing row identity. Repeated identical `put()` must return the same `StableRef`.

- [ ] **Step 5: Implement `get()` with full integrity verification**

`get(ref)` must require `ref.content_hash`, load only by opaque `artifact_id`, then verify in order:

```text
row exists
row.content_hash == ref.content_hash
codec kind/version decodes
workflow_artifact_content_hash(decoded) == row.content_hash
```

Any failure raises `WorkflowArtifactCodecError`/`KeyError` internally; callers must not receive corrupted values.

- [ ] **Step 6: Add corruption/idempotency negative tests**

Directly tamper test rows using a separate admin connection and prove:

- payload mutation fails on `get()`;
- `codec_version=999` fails;
- same `kind + hash` put returns same ref;
- same supplied hash with a different value is rejected before SQL write;
- `close()` is idempotent.

- [ ] **Step 7: Run GREEN and commit**

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
- Produces:

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

- [ ] **Step 1: Write RED public-contract tests**

Add tests for nonblank pause ID, unique/nonempty allowed kinds, additive command field order, and wait exclusivity:

```python
def test_resume_command_keeps_existing_field_order_and_adds_pause_id_last() -> None:
    assert [field.name for field in dataclasses.fields(WorkflowResumeCommand)] == [
        "resume_kind",
        "payload",
        "pause_id",
    ]


def test_checkpoint_rejects_human_and_async_wait_at_once() -> None:
    pending = PendingInteractionView(
        pause_id="pause-1",
        kind=PendingInteractionKind.OPERATION_PROPOSAL,
        subject_ref=StableRef("artifact-1", "a" * 64),
        allowed_resume_kinds=(
            "OPERATION_PROPOSAL_ACCEPTED",
            "OPERATION_PROPOSAL_REJECTED",
        ),
    )
    with pytest.raises(ValueError):
        WorkflowCheckpointView(
            task_id="task-1",
            phase=WorkflowPhase.AWAIT_OPERATION_PROPOSAL,
            pending_interaction=pending,
            async_operation_ref=AsyncOperationRef(
                AsyncOperationKind.OTHER, "owner", "op-1"
            ),
        )
```

Also prove existing async construction remains valid:

```python
command = WorkflowResumeCommand(
    resume_kind="ASYNC_OPERATION_COMPLETED",
    payload={"operation_id": "op-1"},
)
assert command.pause_id is None
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/orchestrator/test_workflow_contracts.py -q
```

Expected: FAIL because pending interaction/CANCELLED/pause_id are absent.

- [ ] **Step 3: Implement minimal additive contracts**

Validation rules:

- normalize `pause_id` with existing `_required_text` when present;
- convert `kind` to `PendingInteractionKind`;
- require `subject_ref` is `StableRef`;
- normalize `allowed_resume_kinds` to tuple of nonblank strings, reject empty/duplicates;
- in `WorkflowCheckpointView.__post_init__`, reject `pending_interaction` together with either `async_operation_ref` or `interaction_ref`;
- do **not** globally reject `WorkflowResumeCommand.payload`, because async completion still owns its existing payload schema.

- [ ] **Step 4: Export the new public types**

Update `workflow_contracts.__all__` and package `__init__.py` with `PendingInteractionKind` and `PendingInteractionView`; do not remove or rename old exports.

- [ ] **Step 5: Run GREEN and commit**

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
- Modify: `tests/orchestrator/test_langgraph_graph.py`
- Create: `tests/orchestrator/test_hitl_checkpoint_state.py`

**Interfaces:**
- Consumes: Task 4 `PendingInteractionView`.
- Produces:

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

`WorkflowGraphState` gains `checkpoint_contract_version: int` and `pending_interaction: dict[str, object] | None`.

- [ ] **Step 1: Write RED state-shape tests**

Cover exact pending keys and v2 corruption:

```python
def test_v2_operation_wait_requires_pending_interaction() -> None:
    with pytest.raises(ValueError, match="pending_interaction"):
        graph_state_to_checkpoint_view(
            {
                "checkpoint_contract_version": 2,
                "task_id": "task-1",
                "phase": "AWAIT_OPERATION_PROPOSAL",
                "operation_ref": {"ref_id": "artifact-1", "content_hash": "a" * 64},
            }
        )


def test_pending_interaction_decoder_rejects_extra_keys() -> None:
    value = {
        "pause_id": "pause-1",
        "kind": "OPERATION_PROPOSAL",
        "subject_ref": {"ref_id": "artifact-1", "content_hash": "a" * 64},
        "allowed_resume_kinds": ["OPERATION_PROPOSAL_ACCEPTED"],
        "payload": {"forbidden": True},
    }
    with pytest.raises(ValueError, match="unsupported keys"):
        decode_pending_interaction(value)
```

- [ ] **Step 2: Run RED**

```bash
uv run pytest tests/orchestrator/test_hitl_checkpoint_state.py -q
```

Expected: FAIL because version/pending codecs do not exist.

- [ ] **Step 3: Implement exact JSON-compatible pending codec**

Persist only:

```text
pause_id
kind
subject_ref {ref_id, content_hash}
allowed_resume_kinds [stable strings]
```

No arbitrary metadata/payload field is allowed. Reuse `_encode_stable_ref/_decode_stable_ref`.

- [ ] **Step 4: Add version-aware checkpoint validation**

`graph_state_to_checkpoint_view()` must:

```text
version absent -> preserve existing legacy projection; do not synthesize human pause here
version == 2   -> validate v2 structure
other version  -> ValueError
```

For version `2`, `AWAIT_OPERATION_PROPOSAL` requires pending interaction. `WorkflowCheckpointView` then enforces pending-vs-async/interaction mutual exclusion.

Do not reject recognized unversioned async state here; runtime owns interrupt-aware legacy classification in Task 7.

- [ ] **Step 5: Preserve authoritative-object guards**

Extend negative tests so a pending view containing or adjacent to `changeset_object`, `approval_record_object`, `execution_saga_object`, `semantic_projection_object` remains rejected by existing `FORBIDDEN_AUTHORITATIVE_STATE_KEYS` logic.

- [ ] **Step 6: Run GREEN and commit**

```bash
uv run pytest \
  tests/orchestrator/test_hitl_checkpoint_state.py \
  tests/orchestrator/test_langgraph_graph.py -q
uv run ruff check \
  platform/orchestrator/src/design_orchestrator/langgraph_state.py \
  tests/orchestrator/test_hitl_checkpoint_state.py

git add platform/orchestrator/src/design_orchestrator/langgraph_state.py \
  tests/orchestrator/test_hitl_checkpoint_state.py \
  tests/orchestrator/test_langgraph_graph.py
git commit -m "feat: version HITL checkpoint state"
```

---

### Task 6: Split prepare/interrupt and implement ACCEPT/REJECT graph behavior

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_graph.py`
- Modify: `tests/orchestrator/test_langgraph_graph.py`

**Interfaces:**
- Consumes: Task 5 pending codec/version.
- Produces topology:

```text
resolve_operations
→ prepare_operation_proposal_pause
→ await_operation_proposal
→ parameter_binding | END(CANCELLED)
```

`await_operation_proposal` node name remains unchanged.

- [ ] **Step 1: Write RED topology/pause tests**

Assert `MAIN_PATH` includes `prepare_operation_proposal_pause` directly before `await_operation_proposal`. Start a graph with `InMemorySaver` and verify the paused public/private state has:

```text
checkpoint_contract_version = 2
phase = AWAIT_OPERATION_PROPOSAL
pending_interaction.pause_id = nonblank UUID string
pending_interaction.subject_ref == operation_ref
async_operation_ref = None
```

- [ ] **Step 2: Write RED ACCEPT/REJECT tests**

For ACCEPT, invoke LangGraph with runtime-private payload:

```python
Command(
    resume={
        "pause_id": pause_id,
        "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
        "payload": {},
    }
)
```

Assert graph reaches `parameter_binding` and clears `pending_interaction`.

For REJECT use `OPERATION_PROPOSAL_REJECTED`; assert terminal phase `CANCELLED`, no `bind_parameters` call, and no downstream service call.

- [ ] **Step 3: Run RED**

```bash
uv run pytest tests/orchestrator/test_langgraph_graph.py -q
```

Expected: FAIL because current graph creates no persisted pending interaction and ignores resume kind.

- [ ] **Step 4: Implement `prepare_operation_proposal_pause`**

Use `str(uuid4())` exactly once in the prepare node, construct `PendingInteractionView`, and return its encoded state. The await node must never generate a pause ID.

The interrupt payload is limited to:

```python
{
    "pause_id": pending.pause_id,
    "kind": pending.kind.value,
    "subject_ref": _encode_stable_ref(pending.subject_ref),
}
```

- [ ] **Step 5: Implement defense-in-depth resume parsing in the await node**

The value returned by `interrupt()` must be a mapping with exact keys `pause_id`, `resume_kind`, `payload`. Require matching pause ID, an allowed resume kind, and `{}` payload for both v1 human actions.

Return:

```text
ACCEPT -> pending_interaction=None, phase=PARAMETER_BINDING
REJECT -> pending_interaction=None, phase=CANCELLED
```

Add a conditional edge from `await_operation_proposal` to `parameter_binding` or `END` based only on the resulting phase.

- [ ] **Step 6: Prove existing async topology is unchanged**

Keep `await_async_operation`, `_ASYNC_RESUME_NODES`, existing owner refresh ordering, and `ASYNC_OPERATION` interrupt payload unchanged. Run existing async/recovery graph tests in the same target suite.

- [ ] **Step 7: Run GREEN and commit**

```bash
uv run pytest \
  tests/orchestrator/test_langgraph_graph.py \
  tests/orchestrator/test_workflow_resume_authoritative_truth.py -q
uv run ruff check platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py

git add platform/orchestrator/src/design_orchestrator/langgraph_graph.py \
  tests/orchestrator/test_langgraph_graph.py
git commit -m "feat: implement correlated HITL graph pause"
```

---

### Task 7: Validate resume mode and migrate exact legacy human checkpoints

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/hitl_resume.py`
- Modify: `platform/orchestrator/src/design_orchestrator/workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/default_workflow_services.py`
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_runtime.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Create: `tests/orchestrator/test_hitl_resume.py`
- Modify: `tests/orchestrator/test_langgraph_runtime.py`

**Interfaces:**
- Produces:

```python
def synthetic_legacy_operation_proposal_pause(
    *, task_id: str, operation_ref: StableRef
) -> PendingInteractionView: ...


def validate_human_resume(
    *, checkpoint: WorkflowCheckpointView, command: WorkflowResumeCommand | None
) -> None: ...
```

Extend `WorkflowServices` with:

```python
def ensure_operation_artifact(
    self,
    operation_ref: StableRef,
    context_snapshot_ref: StableRef,
) -> StableRef: ...
```

- [ ] **Step 1: Write RED pure resume-validation tests**

Cover:

```text
human wait + command=None                        -> WORKFLOW_RESUME_INVALID
human wait + pause_id=None                       -> WORKFLOW_RESUME_INVALID
human wait + wrong pause_id                      -> WORKFLOW_RESUME_STALE
human wait + right pause/wrong resume_kind       -> WORKFLOW_RESUME_MISMATCH
human ACCEPT/REJECT + nonempty payload           -> WORKFLOW_RESUME_INVALID
async wait + pause_id != None                    -> WORKFLOW_RESUME_INVALID
async wait + existing command pause_id=None       -> allowed
async wait + command=None                         -> allowed
```

- [ ] **Step 2: Implement deterministic synthetic legacy identity**

Use compact sorted JSON, preserving `content_hash: null` explicitly:

```python
payload = {
    "contract": "legacy-operation-proposal-pause-v1",
    "task_id": task_id.strip(),
    "operation_ref": {
        "ref_id": operation_ref.ref_id,
        "content_hash": operation_ref.content_hash,
    },
}
canonical = json.dumps(
    payload,
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
).encode("utf-8")
pause_id = "legacy-op-proposal:" + sha256(canonical).hexdigest()
```

Return `PendingInteractionView(OPERATION_PROPOSAL, operation_ref, ACCEPT/REJECT)`.

- [ ] **Step 3: Add `ensure_operation_artifact()` to the deterministic service adapter**

Algorithm:

```text
try artifact_store.get(operation_ref)
  -> require ResolutionResult
  -> return original ref
except missing/corrupt artifact:
  -> require operation_ref.content_hash
  -> external_owners.load_operation_resolution_inputs(context_snapshot_ref)
  -> self._operation_resolver.resolve(inputs.profiles, inputs.context)
  -> recompute workflow_artifact_content_hash
  -> require exact equality with old content_hash
  -> artifact_store.put(kind="operation_resolution", ...)
  -> return new durable ref
```

Do not copy resolver eligibility logic. If inputs/hash are unavailable or mismatch, raise an internal artifact-unavailable exception for runtime normalization.

- [ ] **Step 4: Write RED legacy snapshot classification tests**

Seed an `InMemorySaver`/compiled graph using `update_state` with an old unversioned Operation Proposal state and `as_node="resolve_operations"`, then drive it to a real `await_operation_proposal` interrupt using the old shape fixture.

The runtime must only synthesize a pending human view when all are true:

```text
version absent
phase AWAIT_OPERATION_PROPOSAL
valid operation_ref
real snapshot.interrupts present
pending_interaction absent
async_operation_ref absent
```

Also seed an unversioned `async_operation_ref` wait and prove existing async resume is still recognized, not rejected as an unknown legacy human interrupt.

- [ ] **Step 5: Implement interrupt-aware checkpoint projection in runtime**

Add a private runtime method equivalent to:

```python
def _checkpoint_from_snapshot(
    self, task_id: str, snapshot: Any
) -> WorkflowCheckpointView:
    values = snapshot.values
    checkpoint = graph_state_to_checkpoint_view(values)
    version = values.get("checkpoint_contract_version")
    interrupts = tuple(getattr(snapshot, "interrupts", ()))

    if version == 2:
        return checkpoint
    if _is_exact_legacy_operation_proposal(values, interrupts):
        return dataclasses.replace(
            checkpoint,
            pending_interaction=synthetic_legacy_operation_proposal_pause(
                task_id=task_id,
                operation_ref=checkpoint.operation_ref,
            ),
        )
    if checkpoint.async_operation_ref is not None and interrupts:
        return checkpoint
    if interrupts:
        raise WorkflowStateError(
            "WORKFLOW_CHECKPOINT_INVALID",
            "unrecognized legacy interrupt shape",
        )
    return checkpoint
```

`graph_state_to_checkpoint_view()` itself must remain unaware of LangGraph interrupt presence.

- [ ] **Step 6: Migrate legacy human state to a real v2 interrupt before consuming command**

For a legacy human checkpoint, before `Command(resume=...)`:

1. validate incoming command against the synthetic pause;
2. call `ensure_operation_artifact(old_operation_ref, context_snapshot_ref)`;
3. build v2 pending interaction using the **same synthetic pause_id** and the returned durable subject ref;
4. call `graph.update_state(..., as_node="prepare_operation_proposal_pause")` with `checkpoint_contract_version=2`, durable `operation_ref`, and encoded pending interaction;
5. invoke graph with `None` once so `await_operation_proposal` establishes a real v2 interrupt;
6. reload checkpoint and revalidate the same command;
7. only then invoke `Command(resume=...)`.

This sequence preserves correlation and ensures a failed artifact recovery never consumes the old pause.

- [ ] **Step 7: Implement new-v2 runtime validation before graph invocation**

For new human pause:

```text
load snapshot/public checkpoint
validate mode/pause/kind/payload
services.ensure_operation_artifact(subject_ref, context_snapshot_ref)
require returned ref == subject_ref for normal v2 path
construct Command(resume={pause_id,resume_kind,payload})
invoke graph
```

If artifact validation fails, normalize to:

```text
WORKFLOW_ARTIFACT_UNAVAILABLE
```

and prove graph/checkpoint remains unchanged.

For async wait, keep existing `pause_id=None` command/poll path and do not call `ensure_operation_artifact` merely because an interrupt exists.

- [ ] **Step 8: Run GREEN and commit**

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

**Interfaces:** no new public interface; this task provides end-to-end evidence for Tasks 2–7.

- [ ] **Step 1: Replace memory artifact storage in PostgreSQL E2E with the real durable adapter**

For the main restart scenario create:

```python
saver_a = create_postgres_checkpointer(_dsn())
artifact_store_a = create_postgres_artifact_store(_dsn())
runtime_a = LangGraphWorkflowRuntime(
    services=_service(owners_a, store=artifact_store_a),
    checkpointer=saver_a,
)
```

Start workflow and stop at human Operation Proposal pause. Capture `pause_id` and `subject_ref`, then close both saver and artifact store before constructing runtime B.

- [ ] **Step 2: Prove same pause + subject artifact after process reconstruction**

Create new saver/store/service/runtime instances and assert:

```python
reopened = runtime_b.get_checkpoint(task_id)
assert reopened.pending_interaction == proposal_wait.pending_interaction
assert artifact_store_b.get(reopened.pending_interaction.subject_ref)
```

Resume with:

```python
WorkflowResumeCommand(
    resume_kind="OPERATION_PROPOSAL_ACCEPTED",
    payload={},
    pause_id=reopened.pending_interaction.pause_id,
)
```

Assert real ParameterBinder output is produced and workflow reaches the existing async owner path.

- [ ] **Step 3: Preserve existing async completion behavior after the new human resume**

The later async completion command must remain:

```python
WorkflowResumeCommand(
    resume_kind="ASYNC_OPERATION_COMPLETED",
    payload={"operation_id": "reconstruction-task9"},
)
```

Do not add `pause_id`; assert it continues through owner refresh and completes as before.

- [ ] **Step 4: Add stale replay and corruption acceptance cases**

After successful human ACCEPT, resubmitting the original human command must raise `WORKFLOW_RESUME_STALE`.

In a separate PostgreSQL case, corrupt/delete the referenced workflow artifact while paused; resume must raise `WORKFLOW_ARTIFACT_UNAVAILABLE`, checkpoint must still expose the same human `pause_id`, and fake external owner mutation counters must remain zero.

- [ ] **Step 5: Update the recovery runbook**

Add these operator facts without changing external owner procedures:

```text
orchestrator_checkpoint = navigation/wait state
orchestrator_artifact   = workflow-local deterministic continuation artifacts
paused checkpoint with reachable artifact ref => artifact GC forbidden
WORKFLOW_ARTIFACT_UNAVAILABLE => do not edit checkpoint/artifact rows manually
legacy rehydration requires authoritative snapshot inputs + exact hash equality
```

- [ ] **Step 6: Wire the artifact/restart tests into the existing PostgreSQL 17 workflow**

The workflow must run at least:

```bash
DSP_TEST_POSTGRES_DSN='postgresql://postgres:postgres@localhost:5432/dsp_test' \
  uv run python -m pytest \
  tests/orchestrator/test_artifact_postgres.py \
  tests/orchestrator/test_postgres_checkpoint.py \
  tests/orchestrator/test_workflow_end_to_end.py -q
```

Do not create a second independent Orchestrator database workflow unless the existing workflow cannot express this gate.

- [ ] **Step 7: Run PostgreSQL GREEN and commit**

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

### Task 9: Close capability gates and hand off to real E2E workflow

**Files:**
- Modify: `docs/superpowers/README.md`
- Modify: `docs/superpowers/reviews/2026-09-19-hitl-pause-resume-compatibility-census.md` only if implementation evidence changes a previously recorded repository fact.
- No product code unless a gate exposes a real defect in Tasks 2–8.

**Interfaces:** consumes the complete HITL branch; produces exact-head verification evidence and lifecycle closeout.

- [ ] **Step 1: Run targeted orchestrator regression**

```bash
uv run pytest tests/orchestrator -q
uv run pytest tests/architecture/test_hitl_pause_resume_compatibility_census.py -q
```

Expected: all non-live/non-PostgreSQL tests PASS; PostgreSQL-only tests may skip only when DSN is intentionally absent.

- [ ] **Step 2: Run PostgreSQL owner gates locally when DSN is available**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/orchestrator -q

DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/execution_reconciliation -q
```

Expected: PASS with no artifact/checkpoint owner leakage.

- [ ] **Step 3: Run canonical repository regression**

```bash
uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
uv run ruff check --select E,F,I platform hosts/autocad/sidecar tests

dotnet test \
  hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj \
  -f net8.0
```

Ruff acceptance is **new diagnostics = 0** relative to the implementation branch base; do not require unrelated historical diagnostics to disappear.

- [ ] **Step 4: Verify architecture boundaries by source guard**

Add/run an architecture assertion or explicit source audit proving:

```text
no LangGraph type exported from workflow_contracts/workflow_port
no PostgreSQL type exported from WorkflowArtifactStore protocol
no Step26 InteractionSession object stored in pending_interaction
no ApprovalRecord/ExecutionGrant/Saga/Host/Semantic object stored in checkpoint/artifact store
no Temporal dependency
no change under Host plugin/sidecar production contract for this capability
```

If a boundary violation is found, fix the owning earlier task and rerun its RED/GREEN cycle; do not waive it in closeout.

- [ ] **Step 5: Update lifecycle index only after exact-head implementation gates are green**

Change the current repository summary to identify HITL pause/resume as the active/completed first Capability increment according to actual merge state, and keep the next successor explicitly as:

```text
real E2E workflow
```

Do not mark the next capability implemented.

- [ ] **Step 6: Commit closeout and run fresh CI on the exact commit**

```bash
git add docs/superpowers/README.md
git commit -m "docs: close HITL pause resume capability"
git rev-parse HEAD
```

Push the exact head and require fresh successful runs for:

```text
Repository regression
Workflow orchestrator PostgreSQL verification
Durable persistence verification
```

Repository regression must show all four required jobs green:

```text
Python 3.11 (canonical)
Python 3.14 (compatibility)
revit-core
.NET 10 (Host-neutral compatibility)
```

- [ ] **Step 7: Final completion audit**

Before declaring HITL complete, confirm all twelve Design Spec §20 completion criteria with exact commit/workflow evidence. Only then may the project start the successor Design/Implementation work for:

```text
real E2E workflow
```

---

## Plan Self-Review Checklist

Before implementation starts, verify:

- [ ] Task 1 completes all six required census areas before Task 2 production code.
- [ ] Durable artifact codec/store is implemented before HITL restart claims.
- [ ] `WorkflowResumeCommand` keeps `resume_kind/payload` and adds only trailing optional `pause_id`.
- [ ] Human and async waits are distinguished semantically without removing the existing async command/poll path.
- [ ] `checkpoint_contract_version=2` cannot make corrupted v2 state look legacy.
- [ ] Exact legacy human migration requires real interrupt presence and does not misclassify unversioned async waits.
- [ ] Legacy artifact rehydration uses the real resolver and exact hash equality.
- [ ] `await_operation_proposal` node identity remains available for old checkpoints.
- [ ] PostgreSQL restart occurs at the human pause boundary and uses a new artifact-store instance.
- [ ] ACCEPT reaches real ParameterBinder; REJECT reaches `CANCELLED` without downstream service calls.
- [ ] Artifact failure occurs before graph progression and preserves the pending pause.
- [ ] No Host/plugin, Gateway, Saga, Interaction Coordinator, semantic-owner, MCP/front-door ownership expansion exists.
- [ ] Final exact-head CI includes repository + orchestrator PostgreSQL + durable persistence workflows.
