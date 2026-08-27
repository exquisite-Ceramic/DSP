# D4 Operation Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the D4 Operation Resolver so provider capabilities are aggregated and filtered in strict Host → Entity → Policy → Task order while the LLM-facing action space contains only canonical `ResolvedOperation` objects.

**Architecture:** Put D4 in a host-neutral orchestrator package under `platform/orchestrator/src/design_orchestrator`. The resolver consumes provider profiles structurally (no import of AutoCAD-native code), keeps eligible provider candidates in an internal result map for later ExecutionUnit binding, and emits a separate canonical projection for the LLM. Provider selection/binding is explicitly deferred.

**Tech Stack:** Python 3.11, dataclasses, typing Protocol, pytest, GitHub Actions.

**Spec:** `Enterprise_Collaborative_Design_Agent_Spec_v0.5.md` Appendix D step 4 and Appendix E action-space/provider-binding boundaries.

## Global Constraints

- LLM sees only canonical `ResolvedOperation`, never provider-specific MCP tool names.
- Provider aggregation precedes filtering.
- Filtering order is exactly Host → Entity → Policy → Task.
- Provider binding/selection does not occur in D4; it remains an ExecutionUnit responsibility.
- D5 Semantic Runtime, D6 Parameter Binder, and D7 ChangeSet/approval execution are out of scope.
- Existing AutoCAD native APIs remain inside the AutoCAD plugin.
- Python baseline remains 3.11.

---

### Task 1: Add D4 package/test harness and prove RED

**Files:**
- Create: `tests/orchestrator/test_operation_resolver.py`
- Create: `.github/workflows/operation-resolver.yml`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes: D3 profile objects with attributes `provider_server`, `provider_tool`, `canonical_operation`, `category`, `entity_constraints`, `input_schema`, `output_schema`, and `description`.
- Produces: failing tests importing `design_orchestrator.operation_resolver`.

- [ ] **Step 1: Write failing tests**

Use a small `Profile` test dataclass matching the structural fields above. Add tests asserting two providers for `move.v1` collapse to one canonical operation, provider names are absent from the LLM projection, and host/entity mismatches remove only the ineligible provider candidates.

- [ ] **Step 2: Run CI and verify RED**

Run: `pytest -q tests/orchestrator/test_operation_resolver.py`

Expected: collection/import failure because `design_orchestrator.operation_resolver` does not exist.

- [ ] **Step 3: Commit RED only**

Commit message: `test(orchestrator): define D4 operation resolver contract`

---

### Task 2: Implement provider aggregation plus Host and Entity filters

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Create: `platform/orchestrator/src/design_orchestrator/operation_resolver.py`
- Test: `tests/orchestrator/test_operation_resolver.py`

**Interfaces:**
- `CapabilityProfile` Protocol: structural provider profile contract.
- `ResolutionContext(host_provider_servers, entity_kinds, policy, task)`.
- `ResolvedOperation(canonical_operation, category, input_schema, output_schema, description)`.
- `ResolutionResult(resolved_operations, provider_candidates)` where provider candidates remain internal/non-LLM-facing.
- `OperationResolver.resolve(profiles, context) -> ResolutionResult`.

- [ ] **Step 1: Implement the minimal domain types and resolver**

`resolve` sorts provider profiles deterministically, applies host membership first, then entity compatibility. Empty profile entity constraints mean unrestricted; otherwise all selected entity kinds must be supported. Surviving profiles are grouped by `canonical_operation`.

- [ ] **Step 2: Canonicalize without provider binding**

For each canonical group, emit exactly one `ResolvedOperation`. Keep all surviving providers in `provider_candidates[canonical_operation]`; do not rank or choose one provider.

- [ ] **Step 3: Verify GREEN**

Run: `pytest -q tests/orchestrator/test_operation_resolver.py`

Expected: Task 2 tests pass.

- [ ] **Step 4: Commit**

Commit message: `feat(orchestrator): aggregate and filter operation providers`

---

### Task 3: Add Policy and Task filters plus LLM projection boundary

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/operation_resolver.py`
- Modify: `tests/orchestrator/test_operation_resolver.py`

**Interfaces:**
- `OperationPolicy(denied_operations=frozenset(), allowed_categories=None)`.
- `TaskConstraints(allowed_operations=None, required_category=None)`.
- `ResolutionResult.llm_action_space() -> tuple[dict[str, object], ...]` serializes canonical operation data only.

- [ ] **Step 1: Add failing tests**

Add independent tests for policy deny, policy category restriction, task operation restriction, task category restriction, deterministic ordering, and serialization that recursively contains neither `provider_server` nor `provider_tool` values.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/orchestrator/test_operation_resolver.py`

Expected: new policy/task/projection assertions fail while Task 2 cases remain green.

- [ ] **Step 3: Implement Policy then Task filters in strict order**

Apply policy to canonical groups after host/entity provider filtering, then task constraints. Do not collapse provider candidates beyond eligibility filtering.

- [ ] **Step 4: Fail closed on conflicting canonical contracts**

If surviving providers for the same canonical operation disagree on category/input/output schema, raise `CapabilityConflictError` rather than selecting one provider's contract.

- [ ] **Step 5: Verify focused and full regression suites**

Run:
- `pytest -q tests/orchestrator/test_operation_resolver.py`
- `pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator`

Expected: D4 focused suite green; existing D3 and Python regression remain green except existing live-AutoCAD skips.

- [ ] **Step 6: Commit**

Commit message: `feat(orchestrator): enforce canonical D4 action-space filtering`

---

### Task 4: Review and PR

**Files:**
- Review all D4 diff files.
- Create a stacked PR with base `feat/design-capability-profile` while PR #3 remains open.

**Interfaces:**
- PR must state that D4 depends on D3 and must later be retargeted/rebased onto `main` after PR #3 merges.

- [ ] **Step 1: Review boundary invariants**

Confirm no LLM-facing serialization includes provider server/tool identity, no provider ranking/binding exists, and no D5-D7 concepts were introduced.

- [ ] **Step 2: Verify final CI at the PR head SHA**

Only claim completion from fresh successful GitHub Actions output.

- [ ] **Step 3: Open stacked PR**

Title: `feat(orchestrator): add D4 operation resolver`
