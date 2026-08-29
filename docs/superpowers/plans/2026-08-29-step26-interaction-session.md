# Step 26 InteractionSession / Host-native Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an explicit InteractionSession lifecycle, deterministic D6 pause/resume for missing required INTENT slots, and one AutoCAD `PICK_POINT` Host Canvas vertical without introducing model mutation or ProviderBinding.

**Architecture:** Create a standalone `platform/interaction` package that owns session state, idempotency, expiry, result validation, and per-Host/document prompt exclusivity. Add a thin `design_orchestrator.interactive_binding` wrapper around the unchanged Step25 `ParameterBinder`; it emits `InteractionRequired`, consumes completed sessions, then reconstructs binding evidence. Add one AutoCAD sidecar/plugin `interaction.pick_point` path whose native AutoCAD point is normalized to a canonical numeric `[x,y,z]` result.

**Tech Stack:** Python 3.11, dataclasses/enums/mapping proxies, `jsonschema>=4.20`, pytest/pytest-asyncio, existing `host_contracts.AsyncOperationRef`, C# net8.0-windows AutoCAD plugin contracts, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-step26-interaction-session-design.md`

## Global Constraints

- Work only on `feat/step26-interaction-session` for production/test changes.
- `InteractionSession` authoritative state belongs to `platform/interaction`, not D6, Host MCP, or LangGraph.
- Do not add an `INTERACTION` `SlotBindingClass`; the five Step23 binding classes remain unchanged.
- Step26 v1 interaction fallback targets only missing required `INTENT` canonical slots with explicit recipes.
- One Host/document may have at most one distinct `PENDING` interaction.
- Same logical `interaction.start` retry uses the same `idempotency_key` and returns the same session.
- `InteractionSession.result` is canonical structured data only; no AutoCAD `Point3d`, Handle, ObjectId, Revit ElementId, provider tool, or internal unit may cross into Core/D6.
- Step25 `ParameterBinder.bind()` remains strict and unchanged in ownership semantics.
- No Impact/Dependency, ApprovalScopeBoundary, ChangeSet, ExecutionUnit, ProviderBinding, ExecutionGrant, or model mutation in Step26.
- Every production behavior must be preceded by a failing test.

---

### Task 1: Freeze Step26 CI boundary

**Files:**
- Create: `.github/workflows/step26-interaction-session.yml`
- Existing spec: `docs/superpowers/specs/2026-08-29-step26-interaction-session-design.md`
- Create: `docs/superpowers/plans/2026-08-29-step26-interaction-session.md`

**Interfaces:**
- Consumes: Step25 `main` baseline and approved Step26 design.
- Produces: branch-scoped exact-diff guard plus focused/regression test entry points.

- [ ] **Step 1: Add workflow paths and branch-scoped diff guard**

Allowed Step26 production/test files are limited to:

```text
.github/workflows/step26-interaction-session.yml
docs/superpowers/plans/2026-08-29-step26-interaction-session.md
platform/interaction/src/design_interaction/{__init__,contracts,coordinator}.py
platform/orchestrator/src/design_orchestrator/{__init__,interactive_binding}.py
hosts/autocad/sidecar/src/autocad_sidecar/{mcp_server.py,adapter/interaction_adapter.py,execution/command_dispatcher.py}
hosts/autocad/plugin/AutoCAD.AgentHost/Commands/{HostCommandHandler.cs,Interaction/PickPointHandler.cs}
hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADInteractionApi.cs
pyproject.toml
tests/interaction/test_step26_interaction_coordinator.py
tests/interaction/test_step26_architecture.py
tests/orchestrator/test_step26_interactive_binding.py
tests/integration/test_step26_autocad_pick_point.py
```

The exact-diff guard MUST run only when `github.head_ref == 'feat/step26-interaction-session'`.

- [ ] **Step 2: Add focused and regression commands**

```bash
pytest -q tests/interaction/test_step26_interaction_coordinator.py
pytest -q tests/interaction/test_step26_architecture.py
pytest -q tests/orchestrator/test_step26_interactive_binding.py
pytest -q tests/integration/test_step26_autocad_pick_point.py
pytest -q tests/orchestrator/test_step25_parameter_binder.py
pytest -q tests/orchestrator/test_step25_architecture.py
pytest -q tests/orchestrator/test_step24_semantic_eligibility.py
pytest -q tests/orchestrator/test_operation_resolver.py
pytest -q --import-mode=importlib contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/interaction tests/semantic_runtime
```

- [ ] **Step 3: Commit CI/plan boundary**

```bash
git add .github/workflows/step26-interaction-session.yml docs/superpowers/plans/2026-08-29-step26-interaction-session.md
git commit -m "docs(step26): plan InteractionSession implementation"
```

---

### Task 2: RED — freeze InteractionSession / Coordinator behavior

**Files:**
- Create: `tests/interaction/test_step26_interaction_coordinator.py`
- Create: `tests/interaction/test_step26_architecture.py`

**Interfaces:**
- Produces expected `design_interaction` public API:
  - `InteractionType`
  - `InteractionState`
  - `InteractionError`
  - `InteractionStartRequest`
  - `InteractionSession`
  - `InteractionCoordinator`

- [ ] **Step 1: Write lifecycle and validation tests**

Use fixed UTC timestamps:

```python
CREATED = "2026-08-29T08:00:00Z"
EXPIRES = "2026-08-29T08:05:00Z"
POINT_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 3,
    "maxItems": 3,
}
```

Prove `PENDING` creation, `COMPLETED` result requirement/schema validation, `CANCELLED`/`EXPIRED` result absence, and `expires_at > created_at`.

- [ ] **Step 2: Write idempotency tests**

```python
first = coordinator.start(request)
second = coordinator.start(request)
assert first.interaction_id == second.interaction_id
```

Create a second request with the same key but different `document_id` and assert `InteractionError.code == "IDEMPOTENCY_CONFLICT"`.

- [ ] **Step 3: Write Host/document exclusivity test**

Start one pending request, then a distinct key on the same `host_instance_id + document_id`; assert `INTERACTION_BUSY`.

- [ ] **Step 4: Write terminal/expiry tests**

Prove `PENDING -> COMPLETED|CANCELLED|EXPIRED`, terminal state immutability, and deterministic expiry when `now >= expires_at`.

- [ ] **Step 5: Write provider result schema test**

```python
with pytest.raises(InteractionError) as exc:
    coordinator.complete_from_provider(session.interaction_id, [10.0, 20.0], now=...)
assert exc.value.code == "INTERACTION_RESULT_INVALID"
```

- [ ] **Step 6: Write async handle test**

```python
ref = coordinator.async_ref(session.interaction_id)
assert ref.type == "INTERACTION_SESSION"
assert ref.id == session.interaction_id
```

- [ ] **Step 7: Write architecture guard**

Read `platform/interaction/src/design_interaction/*.py` and fail if it imports/mentions product packages such as `autocad_sidecar`, `Autodesk`, `revit`, or `tekla` in executable import statements.

- [ ] **Step 8: Commit RED**

Expected focused run before production code: import failure because `design_interaction` does not exist.

```bash
git add tests/interaction
git commit -m "test(step26): freeze InteractionSession RED contract"
```

---

### Task 3: GREEN — implement standalone Interaction Coordinator

**Files:**
- Create: `platform/interaction/src/design_interaction/contracts.py`
- Create: `platform/interaction/src/design_interaction/coordinator.py`
- Create: `platform/interaction/src/design_interaction/__init__.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: `host_contracts.AsyncOperationRef`, `jsonschema.validate`.
- Produces: Step26 Coordinator API used by Task 5 and later orchestration.

- [ ] **Step 1: Implement enums and typed domain error**

```python
class InteractionType(str, Enum):
    SELECT_ENTITIES = "SELECT_ENTITIES"
    PICK_POINT = "PICK_POINT"
    PICK_DIRECTION = "PICK_DIRECTION"
    INPUT_NUMBER = "INPUT_NUMBER"
    CONFIRM = "CONFIRM"
    CANCEL = "CANCEL"

class InteractionState(str, Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"

class InteractionError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
```

- [ ] **Step 2: Implement immutable `InteractionStartRequest` and `InteractionSession`**

Normalize/copy mappings defensively, validate absolute UTC timestamps, state/result invariants, and JSON Schema for completed results.

- [ ] **Step 3: Implement canonical request fingerprint**

Serialize logical request fields with sorted JSON keys and hash using SHA-256. Exclude any transport attempt `request_id` because it is not part of the logical side effect.

- [ ] **Step 4: Implement Coordinator**

Use in-memory dictionaries for Step26 v1:

```text
interaction_id -> InteractionSession
idempotency_key -> {fingerprint, interaction_id}
(host_instance_id, document_id) -> pending interaction_id
```

`start`, `get`, `cancel`, `complete_from_provider`, and `async_ref` must apply expiry before decisions and fail with the frozen codes.

- [ ] **Step 5: Add interaction source to root pytest path**

Add:

```toml
"platform/interaction/src",
```

to `[tool.pytest.ini_options].pythonpath`.

- [ ] **Step 6: Run focused tests and regressions**

```bash
pytest -q tests/interaction/test_step26_interaction_coordinator.py tests/interaction/test_step26_architecture.py
pytest -q tests/orchestrator/test_step25_parameter_binder.py
```

- [ ] **Step 7: Commit GREEN**

```bash
git add platform/interaction pyproject.toml tests/interaction
git commit -m "feat(step26): add InteractionSession coordinator"
```

---

### Task 4: RED — freeze D6 interaction acquisition/resume

**Files:**
- Create: `tests/orchestrator/test_step26_interactive_binding.py`

**Interfaces:**
- Consumes: Step25 `ParameterBinder`, `OperationProposal`, `ParameterBindingContext`, `BoundOperationProposal`; Step26 `InteractionSession`.
- Produces expected `design_orchestrator.interactive_binding` API:
  - `SlotInteractionRecipe`
  - `OperationInteractionRecipe`
  - `InteractionRequired`
  - `InteractiveParameterResolver`

- [ ] **Step 1: Create a synthetic point operation**

```python
CanonicalOperationDefinition(
    canonical_operation="point.place.v1",
    version="1.0.0",
    title="Place point",
    description="Place a canonical point selected by the user.",
    category="MODEL_OPERATION",
    input_schema={
        "type": "object",
        "properties": {
            "targets": {"type": "array", "items": {"type": "string"}, "minItems": 1},
            "point": {"type": "array", "items": {"type": "number"}, "minItems": 3, "maxItems": 3},
        },
        "required": ["targets", "point"],
        "additionalProperties": False,
    },
    slot_binding_policy={"targets": "CONTEXT", "point": "INTENT"},
    verification_contract={"type": "HOST_READ_BACK"},
)
```

Use a normal Step25 CONTEXT_SELECTION recipe for `targets` and a Step26 PICK_POINT recipe for `point`.

- [ ] **Step 2: Test unresolved required interactive slot**

Call `resolver.resolve(...)` with no `point` and no interaction session. Assert `InteractionRequired(slot="point", interaction_type=PICK_POINT, ...)` instead of a `BindingError`.

- [ ] **Step 3: Test explicit intent bypasses interaction**

Supply `point=[1,2,3]` in `OperationProposal.intent_arguments`; assert a `BoundOperationProposal` and ordinary `OperationProposal.intent_arguments` evidence.

- [ ] **Step 4: Test completed session resume**

Supply a completed `InteractionSession(result=[10,20,0])`; assert final canonical `arguments["point"] == [10,20,0]` and evidence source/ref are `InteractionSession` / session id.

- [ ] **Step 5: Test fail-closed context mismatch**

Wrong `task_id`, `host_instance_id`, `document_id`, interaction type, non-COMPLETED state, or invalid result must fail with `INTERACTION_CONTEXT_MISMATCH` or the relevant interaction error.

- [ ] **Step 6: Test recipe constraints**

Reject recipes for optional slots, non-INTENT slots, unknown slots, and `PROVIDER` slots.

- [ ] **Step 7: Test MOVE regression**

Use `MOVE_V1` with no Step26 recipe and prove Step25 behavior is unchanged: displacement INTENT + context targets binds directly with no interaction.

- [ ] **Step 8: Commit RED**

Expected failure: `design_orchestrator.interactive_binding` does not exist.

```bash
git add tests/orchestrator/test_step26_interactive_binding.py
git commit -m "test(step26): freeze D6 interaction resume RED contract"
```

---

### Task 5: GREEN — implement D6 interactive wrapper

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/interactive_binding.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`

**Interfaces:**
- Consumes: unchanged Step25 binder public contracts and `design_interaction.InteractionSession`.
- Produces: interaction-aware resolve surface without changing canonical SlotBindingClass.

- [ ] **Step 1: Implement immutable interaction recipes**

Validate canonical operation/slot names, interaction type, copied constraints/schema, unique slots, and required-INTENT-only ownership.

- [ ] **Step 2: Implement `InteractionRequired`**

Include:

```text
canonical_operation
slot
interaction_type
input_constraints
result_schema
context_snapshot_ref
```

- [ ] **Step 3: Implement resolver construction validation**

Build operation/recipe maps from the same canonical definitions used by the Step25 binder. Reject unknown operations/slots, optional slots, or non-INTENT targets.

- [ ] **Step 4: Implement `resolve`**

Algorithm:

```text
1. find missing required INTENT slots in canonical schema order
2. if a missing slot has a Step26 recipe and no completed session value, return InteractionRequired for the first one
3. merge valid completed interaction results into a new OperationProposal
4. call unchanged ParameterBinder.bind()
5. clone the BoundOperationProposal with InteractionSession evidence replacing only interaction-supplied slots
```

- [ ] **Step 5: Validate session context before merge**

Require exact task/host/document/type match and `COMPLETED` state. Revalidate the session result against the recipe schema before invoking Step25.

- [ ] **Step 6: Export Step26 symbols**

Add public exports in `design_orchestrator.__init__` without removing Step23–25 exports.

- [ ] **Step 7: Run focused + Step25 regression**

```bash
pytest -q tests/orchestrator/test_step26_interactive_binding.py
pytest -q tests/orchestrator/test_step25_parameter_binder.py tests/orchestrator/test_step25_architecture.py
```

- [ ] **Step 8: Commit GREEN**

```bash
git add platform/orchestrator/src/design_orchestrator tests/orchestrator/test_step26_interactive_binding.py
git commit -m "feat(step26): add D6 interaction pause and resume"
```

---

### Task 6: RED — freeze AutoCAD PICK_POINT provider vertical

**Files:**
- Create: `tests/integration/test_step26_autocad_pick_point.py`

**Interfaces:**
- Consumes: current sidecar `build_tool_definitions`, `CommandDispatcher`, `HostCommand` transport.
- Produces expected `interaction.pick_point` sidecar/provider behavior.

- [ ] **Step 1: Test MCP tool metadata**

Assert the catalog contains:

```text
name = interaction.pick_point
category = INTERACTION
```

and a structured input schema accepting prompt/optional constraints but exposing no model mutation metadata.

- [ ] **Step 2: Test sidecar command shape with a fake HostAdapter**

Call `CommandDispatcher.pick_point(idempotency_key="K", prompt="Pick point")`. Capture the sent command and assert:

```text
mode == INTERACTION
operation == interaction.pick_point
idempotency_key == K
arguments.prompt == "Pick point"
```

- [ ] **Step 3: Test sidecar duplicate retry**

The fake HostAdapter counts sends. Call `pick_point` twice with the same key after a successful first response; assert the second call returns the stored result and send count remains one.

- [ ] **Step 4: Test payload normalization**

Return payload `{"point": [100.0, 200.0, 0.0]}` from fake host and assert the sidecar result preserves the canonical numeric vector without Host-native objects.

- [ ] **Step 5: Add source-level plugin guard**

Read `PickPointHandler.cs` / registry after implementation and assert the command type is `interaction.pick_point`; only files under `Native/` may contain `using Autodesk...` per ADR-001.

- [ ] **Step 6: Commit RED**

Expected failure: tool/method/handler do not exist.

```bash
git add tests/integration/test_step26_autocad_pick_point.py
git commit -m "test(step26): freeze AutoCAD PICK_POINT RED vertical"
```

---

### Task 7: GREEN — implement AutoCAD PICK_POINT vertical

**Files:**
- Create: `hosts/autocad/sidecar/src/autocad_sidecar/adapter/interaction_adapter.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/execution/command_dispatcher.py`
- Modify: `hosts/autocad/sidecar/src/autocad_sidecar/mcp_server.py`
- Create: `hosts/autocad/plugin/AutoCAD.AgentHost/Native/AutoCADInteractionApi.cs`
- Create: `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/Interaction/PickPointHandler.cs`
- Modify: `hosts/autocad/plugin/AutoCAD.AgentHost/Commands/HostCommandHandler.cs`

**Interfaces:**
- Sidecar public MCP tool: `interaction.pick_point`.
- Host command: `mode=INTERACTION`, `operation=interaction.pick_point`.
- Host result payload: `{"point": [x, y, z]}` or normal Host error/cancel representation.

- [ ] **Step 1: Implement sidecar `InteractionAdapter`**

Build a `HostCommand` with mode `INTERACTION`, operation `interaction.pick_point`, stable `idempotency_key`, prompt arguments, and current document id.

- [ ] **Step 2: Add dispatcher method with existing idempotency store**

Mirror `move` retry/idempotency structure but do not treat the interaction as model mutation. Successful results are cached under the logical key so retries do not re-prompt.

- [ ] **Step 3: Expose MCP tool**

Add `interaction.pick_point` to `build_tool_definitions()` with category `INTERACTION`; register an MCP handler that delegates to `dispatcher.pick_point`.

- [ ] **Step 4: Implement Native AutoCAD interaction API**

Keep all Autodesk references in `Native/AutoCADInteractionApi.cs`. Use the active document editor to prompt for a point and return a provider-neutral DTO/tuple containing numeric X/Y/Z plus a cancelled flag/error mapping.

- [ ] **Step 5: Implement `PickPointHandler`**

The handler acquires the document lock as required by the existing Host execution pattern, calls only the Native API, and serializes payload:

```json
{"point":[x,y,z]}
```

User cancellation must return the repository's normal Host error/cancel representation and never fabricate `[0,0,0]`.

- [ ] **Step 6: Register handler**

Add `Register(new Interaction.PickPointHandler());` in `HostCommandHandlerRegistry`.

- [ ] **Step 7: Run focused tests**

```bash
pytest -q tests/integration/test_step26_autocad_pick_point.py
```

If AutoCAD assemblies are unavailable in CI, Python contract/source tests must still verify the vertical boundary; existing live Host tests remain integration-skipped by repository convention.

- [ ] **Step 8: Commit GREEN**

```bash
git add hosts/autocad tests/integration/test_step26_autocad_pick_point.py
git commit -m "feat(step26): add AutoCAD PICK_POINT interaction"
```

---

### Task 8: Final verification and PR closeout

**Files:**
- No new production scope.
- Update PR description only.

**Interfaces:**
- Proves Step26 is merge-ready without entering Step27+.

- [ ] **Step 1: Run Step26 focused suite**

```bash
pytest -q tests/interaction/test_step26_interaction_coordinator.py
pytest -q tests/interaction/test_step26_architecture.py
pytest -q tests/orchestrator/test_step26_interactive_binding.py
pytest -q tests/integration/test_step26_autocad_pick_point.py
```

- [ ] **Step 2: Run Phase F regressions**

```bash
pytest -q tests/orchestrator/test_step25_parameter_binder.py
pytest -q tests/orchestrator/test_step25_architecture.py
pytest -q tests/orchestrator/test_step24_semantic_eligibility.py
pytest -q tests/orchestrator/test_operation_resolver.py
pytest -q tests/semantic_runtime/test_d4_freshness_integration.py
```

- [ ] **Step 3: Run relevant full Python regression**

```bash
pytest -q --import-mode=importlib \
  contracts/python/tests \
  tests/contracts \
  tests/integration \
  tests/orchestrator \
  tests/interaction \
  tests/semantic_runtime
```

- [ ] **Step 4: Verify diff boundary**

Compare branch against its main base and confirm no Step27+ production files changed.

- [ ] **Step 5: Open/update PR**

PR title:

```text
feat(step26): InteractionSession and Host-native interaction
```

Description must include design boundary, RED evidence, GREEN CI, exact changed files, idempotency proof, D6 resume proof, and AutoCAD PICK_POINT proof.

- [ ] **Step 6: Final review**

Check for unresolved review threads, unexpected provider/native leakage into Core, and any regression failure before declaring merge-ready.
