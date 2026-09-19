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
- 新 workflow 从 `LangGraphWorkflowRuntime.start()` 的 initial state 起就必须写 `checkpoint_contract_version=2`；不能等到 human pause 才补版本。
- v2 human checkpoint corruption 不得降级成 legacy；legacy human migration 必须要求 exact old shape + real pending interrupt。
- legacy artifact rehydration 必须重新调用真实 `OperationResolver`，并要求 legacy recomputed hash 等于 old `operation_ref.content_hash`。
- `await_operation_proposal` node identity 必须保留；不得通过 bump namespace 遗弃旧 in-flight checkpoint。
- Step26 Interaction Coordinator、Step28/32 Gateway/approval、Execution Saga、Host plugin/sidecar、semantic owner、MCP/Agent front door 均不得改变 ownership。
- 任何 restart acceptance 必须使用真实 PostgreSQL artifact store；memory store 只能用于 unit/in-memory tests。
- 最终必须通过 Python 3.11 两种 pytest mode、Python 3.14、Ruff new diagnostics = 0、Workflow Orchestrator PostgreSQL、Durable Persistence PostgreSQL、Revit Core、.NET 10。

## Execution Topology

本 `architecture/capability-hitl-pause-resume-design` 分支只承载 approved Design Spec、Implementation Plan 与 lifecycle/governance 文档；**不得在本分支实现 production code**。

书面 Plan review 通过后按以下顺序执行：

```text
Design + Plan artifact branch
→ architecture/docs PR to main
→ required write-access approval + protected-main checks
→ merge exact approved artifact head
→ verify exact merged main SHA
→ create feat/capability-hitl-pause-resume from that merged main
→ execute Tasks 1–9 as TDD commits
→ one implementation PR to main
→ required approval/checks
→ merge exact implementation head
→ verify merged main before successor work
```

如果 Task 1 census 或后续 RED evidence 证明 approved Design Spec 的 owner/compatibility assumption 错误，停止 implementation branch，回到 design amendment；不得在实现 PR 中暗改 contract。

## Review Focus

1. **Unversioned async checkpoint compatibility:** 升级后旧 `AsyncOperationRef` wait 仍必须允许现有 `ASYNC_OPERATION_COMPLETED` / poll 语义；不能因 human legacy migration 把它误判为 invalid。
2. **v2 corruption vs legacy:** `checkpoint_contract_version=2 + AWAIT_OPERATION_PROPOSAL + missing pending_interaction` 必须 `WORKFLOW_CHECKPOINT_INVALID`，不能 synthetic legacy pause。
3. **Artifact corruption before resume:** artifact row 缺失、codec/version 错误或 hash mismatch 时 human pause 必须保持未消费，并返回 `WORKFLOW_ARTIFACT_UNAVAILABLE`。
4. **Real continuation after process restart:** 新 runtime/new saver/new artifact store 接管 human pause 后，ACCEPT 必须真实运行 `ParameterBinder`，而不是只让 checkpoint phase 前移。
5. **Legacy memory-only operation artifact:** 只允许用 exact `context_snapshot_ref` 重跑真实 `OperationResolver`；legacy hash mismatch/缺 hash/输入不可得必须 fail closed。

---

### Task 1: Freeze the compatibility census before production code

**Files:**
- Create: `docs/superpowers/reviews/2026-09-19-hitl-pause-resume-compatibility-census.md`
- Create: `tests/architecture/test_hitl_pause_resume_compatibility_census.py`

**Interfaces:**
- Consumes: approved HITL spec §14 and exact merged-main public/runtime surfaces.
- Produces: a machine-readable six-area census that later tasks must not contradict.

- [ ] **Step 1: Write the failing architecture test**

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

- [ ] **Step 2: Run the test and verify RED**

```bash
uv run pytest tests/architecture/test_hitl_pause_resume_compatibility_census.py -q
```

Expected: FAIL because the census document does not exist.

- [ ] **Step 3: Execute the exact repository census**

Run from repository root:

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

Create exactly one row for each required area. `artifact_store_impls` evidence must additionally name every repository `CapabilityProfile` implementation/shape that can enter `ResolutionResult.provider_candidates`, because Task 2 codec must preserve the fields needed by the current artifact hash and consumers.

Use concrete file paths/counts or `NONE_IN_REPOSITORY(<exact rg command>)`; do not infer absence of repo-external callers.

- [ ] **Step 4: Freeze compatibility decisions in the census**

The six decisions must encode these rules when supported by evidence:

```text
public_exports        -> additive only; keep existing names
runtime_callers       -> resume_kind/payload preserved; pause_id trailing optional
test_callers          -> migrate human callers; preserve async completion callers
host_plugin_callers   -> if none in repository, record NONE_IN_REPOSITORY; repo-external state remains unproven
persisted_checkpoints -> recognize old human and old async shapes separately
artifact_store_impls  -> memory remains test-only; production restart requires durable adapter; codec covers observed profile shapes
```

If a real repository Host/plugin caller or persisted shape contradicts the approved additive strategy, stop before Task 2 and amend the design.

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
- Create: `tests/orchestrator/test_workflow_artifacts.py`
- Modify: `tests/orchestrator/test_default_workflow_services.py`

**Interfaces:**
- Consumes: `ResolutionResult`, `ResolvedOperation`, observed `CapabilityProfile` shapes, `BoundOperationProposal`, `StableRef`.
- Produces:

```python
WORKFLOW_ARTIFACT_CODEC_VERSION = 1

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

- [ ] **Step 1: Write RED codec and legacy-hash characterization tests**

Use real resolver/binder output. The operation-resolution round trip compares all consumer-visible fields rather than concrete provider class identity:

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
    for candidate_id, original in sample_resolution.provider_candidates.items():
        restored_profile = restored.provider_candidates[candidate_id]
        for field_name in PERSISTED_CAPABILITY_PROFILE_FIELDS:
            assert getattr(restored_profile, field_name) == getattr(original, field_name)


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
```

Before moving the current generic hash helper, add a characterization fixture with a real `ResolutionResult` and assert `legacy_workflow_artifact_content_hash()` equals the pre-change `_artifact_content_hash()` value. This legacy helper exists only to verify old refs during Task 7 migration.

- [ ] **Step 2: Run the codec tests and verify RED**

```bash
uv run pytest tests/orchestrator/test_workflow_artifacts.py -q
```

Expected: FAIL because `workflow_artifacts` does not exist.

- [ ] **Step 3: Implement explicit canonical payload hashing for new artifacts**

`workflow_artifact_content_hash(value)` must hash the canonical JSON generated by the explicit codec/type dispatch, not arbitrary class identity:

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

Move the existing generic `_normalize_for_hash` algorithm unchanged into `legacy_workflow_artifact_content_hash()` so legacy refs remain verifiable. New `DefaultWorkflowServices.resolve_operations()` / `.bind_parameters()` use `workflow_artifact_content_hash()` only.

- [ ] **Step 4: Implement exact v1 codecs**

`encode_workflow_artifact()` accepts only:

```text
operation_resolution      -> ResolutionResult
bound_operation_proposal  -> BoundOperationProposal
```

For `operation_resolution`, persist every `ResolvedOperation` field plus provider candidates using the Task 1 observed protocol fields. The minimum frozen profile fields are:

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

If Task 1 finds additional fields that current generic legacy hashing/consumer behavior depends on, list and encode them explicitly rather than falling back to `__dict__`.

Reconstruct enum-typed fields such as `CanonicalExistenceEffect` explicitly. Decode provider candidates into `PersistedCapabilityProfile` instances satisfying the existing `CapabilityProfile` protocol.

For `bound_operation_proposal`, explicitly reconstruct:

```text
CanonicalOperationRef
arguments
SlotBindingEvidence + SlotBindingClass
ContextSnapshotRef
PlanningRequirements
semantic_environment_ref
```

Do not persist class-path imports, pickle data, repr strings, or object addresses.

- [ ] **Step 5: Add negative codec tests**

Cover wrong kind/type, missing/extra keys, wrong nested enum values and codec version `2`:

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
- Consumes: `WorkflowArtifactStore`, Task 2 codec/hash/errors.
- Produces:

```python
class PostgresWorkflowArtifactStore(WorkflowArtifactStore):
    def put(self, *, kind: str, value: object, content_hash: str) -> StableRef: ...
    def get(self, ref: StableRef) -> object: ...
    def close(self) -> None: ...


def create_postgres_artifact_store(dsn: str) -> PostgresWorkflowArtifactStore: ...
```

- [ ] **Step 1: Write RED schema/restart tests**

Use `DSP_TEST_POSTGRES_DSN` and a clean `orchestrator_artifact` schema:

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

Query `information_schema.tables` and assert artifact tables live only in `orchestrator_artifact`, not `public`, `orchestrator_checkpoint`, `execution_saga`, `gateway`, or `semantic_runtime`.

- [ ] **Step 2: Run the PostgreSQL test and verify RED**

```bash
DSP_TEST_POSTGRES_DSN="$DSP_TEST_POSTGRES_DSN" \
  uv run pytest tests/orchestrator/test_artifact_postgres.py -q
```

Expected: FAIL because the adapter does not exist.

- [ ] **Step 3: Implement schema bootstrap and owned connection**

Create fixed owner schema/table equivalent to:

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

Bootstrap with a separate autocommit admin connection. Open the store connection with autocommit and:

```sql
SET search_path TO orchestrator_artifact
```

The adapter owns/closes its connection, mirroring `OwnedPostgresSaver` lifecycle discipline.

- [ ] **Step 4: Implement `put()` fail-closed and idempotent**

Before SQL write:

```python
actual_hash = workflow_artifact_content_hash(value)
if actual_hash != content_hash:
    raise WorkflowArtifactCodecError("artifact content_hash does not match value")
```

Encode with codec version `1`; insert opaque UUID `artifact_id`. On `UNIQUE(kind, content_hash)` conflict, select and return the existing row identity. Repeated identical `put()` returns the same `StableRef`.

- [ ] **Step 5: Implement `get()` with integrity verification**

`get(ref)` requires `ref.content_hash`, loads only by opaque `artifact_id`, then checks:

```text
row exists
row.content_hash == ref.content_hash
known kind/version
payload decodes
workflow_artifact_content_hash(decoded) == row.content_hash
```

Missing rows or integrity/codec failures normalize to `WorkflowArtifactUnavailableError` at the store boundary; callers never receive corrupted values.

- [ ] **Step 6: Add corruption/idempotency negative tests**

Using a separate admin connection, prove:

- payload mutation -> `WorkflowArtifactUnavailableError`;
- `codec_version=999` -> `WorkflowArtifactUnavailableError`;
- wrong ref content hash -> `WorkflowArtifactUnavailableError`;
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

Add nonblank pause ID, unique/nonempty allowed kinds, additive field-order, CANCELLED and wait-exclusivity tests:

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

Prove old async construction remains source-compatible:

```python
command = WorkflowResumeCommand(
    resume_kind="ASYNC_OPERATION_COMPLETED",
    payload={"operation_id": "op-1"},
)
assert command.pause_id is None
```

- [ ] **Step 2: Run the tests and verify RED**

```bash
uv run pytest tests/orchestrator/test_workflow_contracts.py -q
```

Expected: FAIL because pending interaction/CANCELLED/pause_id are absent.

- [ ] **Step 3: Implement the additive contracts**

Validation:

- normalize present `pause_id` with existing `_required_text`;
- convert `kind` to `PendingInteractionKind`;
- require `subject_ref` is `StableRef`;
- normalize `allowed_resume_kinds` to nonempty unique tuple of nonblank strings;
- `WorkflowCheckpointView.__post_init__` rejects `pending_interaction` with either `async_operation_ref` or `interaction_ref`;
- do **not** globally reject command payload because async completion keeps owner-specific payload.

- [ ] **Step 4: Export new public types without removing old exports**

Update `workflow_contracts.__all__` and package `__init__.py` with `PendingInteractionKind` and `PendingInteractionView`.

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
- Modify: `platform/orchestrator/src/design_orchestrator/langgraph_runtime.py`
- Create: `tests/orchestrator/test_hitl_checkpoint_state.py`
- Modify: `tests/orchestrator/test_langgraph_runtime.py`
- Modify: `tests/orchestrator/test_langgraph_graph.py`

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

- [ ] **Step 1: Write RED state/version tests**

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

Also add a runtime start test that inspects the persisted graph state and asserts:

```python
assert snapshot.values["checkpoint_contract_version"] == 2
```

- [ ] **Step 2: Run the targeted tests and verify RED**

```bash
uv run pytest \
  tests/orchestrator/test_hitl_checkpoint_state.py \
  tests/orchestrator/test_langgraph_runtime.py -q
```

Expected: FAIL because version/pending codecs are absent and `start()` does not write version 2.

- [ ] **Step 3: Implement the exact JSON-compatible pending codec**

Persist only:

```text
pause_id
kind
subject_ref {ref_id, content_hash}
allowed_resume_kinds [stable strings]
```

Reject arbitrary metadata/payload. Reuse `_encode_stable_ref/_decode_stable_ref`.

- [ ] **Step 4: Add version-aware state validation**

`graph_state_to_checkpoint_view()` behavior:

```text
version absent -> preserve existing unversioned projection; do not synthesize a human pause here
version == 2   -> validate v2 structure
other version  -> ValueError
```

For version `2`, `AWAIT_OPERATION_PROPOSAL` requires pending interaction. Do not reject recognized unversioned async state here; runtime owns interrupt-aware legacy classification in Task 7.

- [ ] **Step 5: Write version 2 from `start()` initial state**

Import `CHECKPOINT_CONTRACT_VERSION` into `langgraph_runtime.py` and add:

```python
initial_state = {
    "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
    ...
}
```

Do not expose this private field through `WorkflowCheckpointView`.

- [ ] **Step 6: Preserve authoritative-object guards**

Extend tests so pending state containing or adjacent to `changeset_object`, `approval_record_object`, `execution_saga_object`, `semantic_projection_object` remains rejected.

- [ ] **Step 7: Run GREEN and commit**

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

Assert `MAIN_PATH` includes `prepare_operation_proposal_pause` directly before `await_operation_proposal`. With `InMemorySaver`, verify paused private/public state contains:

```text
checkpoint_contract_version = 2
phase = AWAIT_OPERATION_PROPOSAL
pending_interaction.pause_id = nonblank UUID
pending_interaction.subject_ref == operation_ref
async_operation_ref = None
```

- [ ] **Step 2: Write RED ACCEPT/REJECT tests**

For ACCEPT:

```python
Command(
    resume={
        "pause_id": pause_id,
        "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
        "payload": {},
    }
)
```

Assert graph reaches parameter binding and clears pending interaction.

For REJECT use `OPERATION_PROPOSAL_REJECTED`; assert terminal `CANCELLED`, no `bind_parameters` call and no downstream service call.

- [ ] **Step 3: Run graph tests and verify RED**

```bash
uv run pytest tests/orchestrator/test_langgraph_graph.py -q
```

Expected: FAIL because current graph has no persisted pending interaction and ignores resume kind.

- [ ] **Step 4: Implement `prepare_operation_proposal_pause`**

Use `str(uuid4())` exactly once in the prepare node, construct `PendingInteractionView`, and return its encoded state. `await_operation_proposal` must never generate a pause ID.

Interrupt payload is limited to:

```python
{
    "pause_id": pending.pause_id,
    "kind": pending.kind.value,
    "subject_ref": _encode_stable_ref(pending.subject_ref),
}
```

- [ ] **Step 5: Implement defense-in-depth resume parsing in the await node**

The value returned by `interrupt()` must be a mapping with exact keys `pause_id`, `resume_kind`, `payload`. Require matching pause ID, allowed kind and `{}` payload.

Return:

```text
ACCEPT -> pending_interaction=None, phase=PARAMETER_BINDING
REJECT -> pending_interaction=None, phase=CANCELLED
```

Add a conditional edge from `await_operation_proposal` to `parameter_binding` or `END` based only on resulting phase.

- [ ] **Step 6: Prove existing async topology remains unchanged**

Keep `await_async_operation`, `_ASYNC_RESUME_NODES`, owner-refresh ordering and the `ASYNC_OPERATION` interrupt contract unchanged; run existing recovery tests in the same cycle.

- [ ] **Step 7: Run GREEN and commit**

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

### Task 7: Validate resume mode, recover artifacts, and migrate exact legacy checkpoints

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
) -> StableRef: ...
```

- [ ] **Step 1: Write RED pure resume-validation tests**

Cover stable codes:

```text
human wait + command=None                        -> WORKFLOW_RESUME_INVALID
human wait + pause_id=None                       -> WORKFLOW_RESUME_INVALID
human wait + wrong pause_id                      -> WORKFLOW_RESUME_STALE
human wait + right pause/wrong resume_kind       -> WORKFLOW_RESUME_MISMATCH
human ACCEPT/REJECT + nonempty payload           -> WORKFLOW_RESUME_INVALID
async wait + command.pause_id != None             -> WORKFLOW_RESUME_STALE
async wait + existing command pause_id=None       -> "async"
async wait + command=None                         -> "poll"
no human pending + previously consumed pause_id   -> WORKFLOW_RESUME_STALE
```

The STALE classification is deliberate: a task that already consumed/superseded a human pause must report stale even if it is now waiting on an async owner.

- [ ] **Step 2: Implement deterministic synthetic legacy identity**

Use compact sorted JSON with explicit `content_hash: null`:

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

Return OPERATION_PROPOSAL pending view with ACCEPT/REJECT.

- [ ] **Step 3: Add `ensure_operation_artifact()` using real resolver semantics**

Algorithm:

```text
try artifact_store.get(operation_ref)
  -> require ResolutionResult
  -> return original ref
except WorkflowArtifactUnavailableError:
  -> require operation_ref.content_hash
  -> external_owners.load_operation_resolution_inputs(context_snapshot_ref)
  -> self._operation_resolver.resolve(inputs.profiles, inputs.context)
  -> legacy_workflow_artifact_content_hash(resolution)
  -> require exact equality with old operation_ref.content_hash
  -> artifact_store.put(
         kind="operation_resolution",
         value=resolution,
         content_hash=workflow_artifact_content_hash(resolution),
     )
  -> return new durable ref
```

Do not copy resolver eligibility logic. Missing inputs/hash or legacy hash mismatch raises `WorkflowArtifactUnavailableError`.

For **new v2** refs, normal `artifact_store.get(subject_ref)` must succeed; rehydration is a legacy path, not a way to silently repair corrupted v2 durable artifacts.

- [ ] **Step 4: Build real legacy interrupt fixtures instead of using the new graph**

In `tests/orchestrator/test_hitl_resume.py`, define a tiny test-only legacy graph builder whose node identity and old payload match pre-HITL behavior:

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

Invoke this fixture once with an **unversioned** old state to create a real pending interrupt in the shared checkpointer. Then construct the **new** `LangGraphWorkflowRuntime` with that same checkpointer and verify migration.

Create a separate tiny old `await_async_operation` fixture with unversioned `async_operation_ref` and a real interrupt to prove old async waits remain valid.

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

    if version == CHECKPOINT_CONTRACT_VERSION:
        return checkpoint
    if _is_exact_legacy_operation_proposal(values, interrupts):
        assert checkpoint.operation_ref is not None
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

`graph_state_to_checkpoint_view()` stays unaware of LangGraph interrupt presence.

- [ ] **Step 6: Migrate a legacy human state to a real v2 interrupt before consuming the command**

For exact legacy human checkpoint:

1. validate incoming command against synthetic pause;
2. call `ensure_operation_artifact(old_operation_ref, context_snapshot_ref)`;
3. build v2 pending interaction using the **same synthetic pause_id** and returned durable subject ref;
4. call:

```python
migrated_config = self._graph.update_state(
    _checkpoint_lookup_config(task_id),
    {
        "checkpoint_contract_version": CHECKPOINT_CONTRACT_VERSION,
        "operation_ref": _encode_stable_ref(durable_ref),
        "pending_interaction": encode_pending_interaction(migrated_pending),
        "async_operation_ref": None,
        "phase": WorkflowPhase.AWAIT_OPERATION_PROPOSAL.value,
    },
    as_node="prepare_operation_proposal_pause",
)
self._graph.invoke(None, migrated_config)
```

5. reload root snapshot and require a real v2 `await_operation_proposal` interrupt;
6. revalidate the same command against the reloaded pending view;
7. only then invoke `Command(resume=...)`.

A failed artifact recovery happens before `update_state` and therefore cannot consume/replace the old pause.

- [ ] **Step 7: Implement new-v2 runtime validation before graph invocation**

For human pause:

```text
load snapshot/public checkpoint
validate pause/mode/kind/payload
artifact_store-backed service validates subject artifact
construct Command(resume={pause_id,resume_kind,payload})
invoke graph
```

For new v2, `ensure_operation_artifact()` must return the same `StableRef`; a changed/new ref would indicate hidden repair and must be rejected.

Normalize any artifact availability/integrity failure to `WorkflowStateError("WORKFLOW_ARTIFACT_UNAVAILABLE", ...)`, preserving the original cause. Checkpoint must remain unchanged.

For async wait, keep existing `pause_id=None` command/poll path and never call operation-artifact recovery merely because LangGraph has an interrupt.

- [ ] **Step 8: Add non-sensitive structured observability**

Use a module logger and structured `extra` fields. At human/async/poll resume boundaries record only:

```text
task_id
pause_id                 # human only
pending_kind             # human only
resume_kind
resume_mode               # human | async | poll
artifact_ref
artifact_content_hash
artifact_source           # durable | rehydrated
checkpoint_contract_version
result                    # accepted | rejected | stale | mismatch | invalid | unavailable | continued
```

Add `caplog` tests that inspect record attributes and assert command payload/domain bodies are not serialized into log messages/fields.

- [ ] **Step 9: Run GREEN and commit**

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

- [ ] **Step 1: Use the real durable artifact adapter in PostgreSQL E2E**

Change the E2E helper annotation from memory-specific to the protocol:

```python
def _service(
    owners: _ScenarioOwners,
    *,
    store: WorkflowArtifactStore | None = None,
) -> DefaultWorkflowServices: ...
```

For the main restart scenario:

```python
saver_a = create_postgres_checkpointer(_dsn())
artifact_store_a = create_postgres_artifact_store(_dsn())
runtime_a = LangGraphWorkflowRuntime(
    services=_service(owners_a, store=artifact_store_a),
    checkpointer=saver_a,
)
```

Start and stop at human Operation Proposal pause. Capture `pause_id`/`subject_ref`, then close both saver and artifact store before runtime B.

- [ ] **Step 2: Prove same pause + subject artifact after process reconstruction**

Create new saver/store/service/runtime instances:

```python
reopened = runtime_b.get_checkpoint(task_id)
assert reopened.pending_interaction == proposal_wait.pending_interaction
assert reopened.pending_interaction is not None
restored_artifact = artifact_store_b.get(reopened.pending_interaction.subject_ref)
assert isinstance(restored_artifact, ResolutionResult)
```

Resume with empty human payload and the exact pause ID. Assert real `ParameterBinder` output is produced and workflow reaches the existing async owner path.

- [ ] **Step 3: Preserve existing async completion behavior after human resume**

The later async completion remains:

```python
WorkflowResumeCommand(
    resume_kind="ASYNC_OPERATION_COMPLETED",
    payload={"operation_id": "reconstruction-task9"},
)
```

No pause ID. Assert existing owner refresh/recovery behavior and final completion remain unchanged.

- [ ] **Step 4: Add stale replay and corruption acceptance cases**

After successful human ACCEPT, resubmit the original human command and require `WORKFLOW_RESUME_STALE` even if the workflow is now in async wait.

In a separate PostgreSQL case, corrupt/delete the referenced workflow artifact while paused; resume must raise `WORKFLOW_ARTIFACT_UNAVAILABLE`, checkpoint still exposes the same `pause_id`, and fake external-owner mutation counters remain zero.

- [ ] **Step 5: Update the recovery runbook**

Add:

```text
orchestrator_checkpoint = navigation/wait state
orchestrator_artifact   = workflow-local deterministic continuation artifacts
paused checkpoint with reachable artifact ref => artifact GC forbidden
WORKFLOW_ARTIFACT_UNAVAILABLE => do not edit checkpoint/artifact rows manually
legacy rehydration requires authoritative snapshot inputs + exact legacy hash equality
```

Do not change execution-owner/Host recovery ownership.

- [ ] **Step 6: Wire artifact/restart tests into the existing PostgreSQL 17 workflow**

The existing workflow must run at least:

```bash
DSP_TEST_POSTGRES_DSN='postgresql://postgres:postgres@localhost:5432/dsp_test' \
  uv run python -m pytest \
  tests/orchestrator/test_artifact_postgres.py \
  tests/orchestrator/test_postgres_checkpoint.py \
  tests/orchestrator/test_workflow_end_to_end.py -q
```

Do not add a second Orchestrator database workflow unless the existing gate cannot express this requirement.

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

### Task 9: Close capability gates and merge from an exact verified head

**Files:**
- Modify: `docs/superpowers/README.md`
- Modify: `docs/superpowers/reviews/2026-09-19-hitl-pause-resume-compatibility-census.md` only if implementation evidence changes a recorded repository fact.
- No product code unless a gate exposes a real defect owned by Tasks 2–8.

**Interfaces:** consumes complete HITL implementation branch; produces exact-head verification, implementation PR and merged-main closeout.

- [ ] **Step 1: Run targeted orchestrator regression**

```bash
uv run pytest tests/orchestrator -q
uv run pytest tests/architecture/test_hitl_pause_resume_compatibility_census.py -q
```

Expected: all non-live/non-PostgreSQL tests PASS; PostgreSQL-only tests may skip only when DSN is intentionally absent.

- [ ] **Step 2: Run PostgreSQL owner gates when DSN is available**

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

Ruff acceptance is **new diagnostics = 0** relative to implementation branch base; unrelated historical diagnostics need not disappear.

- [ ] **Step 4: Verify architecture boundaries by source guard**

Add/run an architecture assertion or explicit source audit proving:

```text
no LangGraph type exported from workflow_contracts/workflow_port
no PostgreSQL type exported from WorkflowArtifactStore protocol
no Step26 InteractionSession object stored in pending_interaction
no ApprovalRecord/ExecutionGrant/Saga/Host/Semantic authoritative object stored in checkpoint/artifact store
no Temporal dependency
no Host plugin/sidecar production-contract change for this capability
```

A violation must be fixed in the owning earlier task and re-verified; do not waive it at closeout.

- [ ] **Step 5: Update lifecycle index after implementation gates are green**

On the implementation branch set the durable pre-merge state to:

```text
Capability Phase — HITL pause/resume CURRENT; implementation exact-head verified
Capability Phase successor after HITL — real E2E workflow, NOT YET STARTED
```

Mark `2026-09-19-hitl-pause-resume.md` `COMPLETED` only after Tasks 1–8 and all exact-head gates are green. Do not mark real E2E implemented/started.

- [ ] **Step 6: Commit closeout and push exact head**

```bash
git add docs/superpowers/README.md
git commit -m "docs: close HITL pause resume capability"
git rev-parse HEAD
```

Require fresh successful exact-head runs for:

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

- [ ] **Step 7: Open and review the implementation PR**

PR topology:

```text
base = main
head = feat/capability-hitl-pause-resume
scope = Tasks 1–9 only
```

The PR body must name the approved spec, exact implementation head, targeted/PostgreSQL/repository verification evidence, and explicitly state that MCP/front-door/real Host work is not included.

Require protected-main write-access approval and all required checks. Do not bypass main rules.

- [ ] **Step 8: Merge exact implementation head and verify merged main**

Merge only if the PR head still equals the verified exact SHA. After merge:

```bash
git fetch origin main
git rev-parse origin/main
```

Verify merged main contains the HITL commits and no unreviewed delta. If merge-main workflows trigger, require them green before declaring the capability closed.

- [ ] **Step 9: Final completion audit**

Confirm all twelve Design Spec §20 completion criteria with exact commit/workflow evidence. Only after merged-main verification may the project begin successor work:

```text
real E2E workflow
```

---

## Plan Self-Review Checklist

Before implementation starts, verify:

- [ ] Task 1 completes all six required census areas before Task 2 production code.
- [ ] Artifact codec/store is implemented before any HITL restart durability claim.
- [ ] New artifact hash semantics are explicit; old generic hash is retained only for legacy verification.
- [ ] `WorkflowResumeCommand` keeps `resume_kind/payload` and adds only trailing optional `pause_id`.
- [ ] Human and async waits are separated without removing existing async command/poll behavior.
- [ ] `checkpoint_contract_version=2` is written from initial start state and cannot make corrupted v2 state look legacy.
- [ ] Legacy human tests create a **real old interrupt with an old graph fixture**, not with the new topology.
- [ ] Exact legacy human migration requires real interrupt presence and does not misclassify unversioned async waits.
- [ ] Legacy artifact rehydration uses the real resolver and exact legacy hash equality.
- [ ] `await_operation_proposal` node identity remains available for old checkpoints.
- [ ] PostgreSQL restart occurs at the human pause boundary with a new artifact-store instance.
- [ ] ACCEPT reaches real ParameterBinder; REJECT reaches `CANCELLED` without downstream service calls.
- [ ] Artifact failure occurs before graph progression and preserves the pending pause.
- [ ] A replayed consumed human pause is `WORKFLOW_RESUME_STALE`, including after routing to async wait.
- [ ] Observability records only workflow-local metadata and does not serialize command/domain payload bodies.
- [ ] No Host/plugin, Gateway, Saga, Interaction Coordinator, semantic-owner, MCP/front-door ownership expansion exists.
- [ ] Artifact-only design/plan branch is merged before implementation branch creation.
- [ ] Final exact-head CI includes repository + Orchestrator PostgreSQL + durable persistence workflows, followed by merged-main verification.
