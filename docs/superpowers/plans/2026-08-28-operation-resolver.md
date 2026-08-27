# D4 Operation Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the D4 Operation Resolver so discovered provider capabilities are first aggregated by `canonical_operation`, then filtered in strict Host → Entity → Policy → Task order, producing 3–10 canonical `ResolvedOperation` choices when enough candidates exist plus a provider-free dynamic structured-output schema for the LLM.

**Architecture:** Put D4 in a host-neutral orchestrator package under `platform/orchestrator/src/design_orchestrator`. The resolver consumes provider profiles structurally (no AutoCAD import), keeps provider candidates as internal routing hints only, and emits a canonical LLM projection. Provider selection/binding remains deferred to the later ExecutionUnit → ProviderBinding stage.

**Tech Stack:** Python 3.11, dataclasses, typing Protocol, pytest, GitHub Actions.

**Spec:** `Enterprise_Collaborative_Design_Agent_Spec_v0.5.md` §5.3, §6.1–6.5, Appendix D step 4, Appendix E.1–E.3.

## Global Constraints

- Aggregate provider profiles by `canonical_operation` before any filtering.
- Filtering order is exactly Host → Entity → Policy → Task.
- Host and Entity filters are hard constraints; Policy is governance; Task performs relevance/ranking/top-K.
- LLM Action Space MUST NOT contain `provider_server`, `provider_tool`, AutoCAD ObjectId, command strings, approval tokens, execution grants, or idempotency keys.
- `candidate_provider_ids` are internal routing hints and MUST NOT be emitted by the LLM projection/schema.
- LLM chooses canonical operations only; provider binding/selection does not occur in D4.
- D5 Semantic Runtime, D6 Parameter Binder, and D7 ChangeSet/approval execution are out of scope.
- Existing AutoCAD native APIs remain inside the AutoCAD plugin.
- Python baseline remains 3.11.

---

### Task 1: Add D4 test harness and prove RED

**Files:**
- Create: `tests/orchestrator/test_operation_resolver.py`
- Create: `.github/workflows/operation-resolver.yml`
- Modify: `pyproject.toml`

**Interfaces:**
- Consumes D3-like provider profile attributes: `provider_server`, `provider_tool`, `canonical_operation`, `category`, `entity_constraints`, `execution_freshness`, `effects`, `risk`, `preview_supported`, `rollback_supported`, `verification_contract`, `input_schema`, `output_schema`.
- Produces failing tests importing `design_orchestrator.operation_resolver`.

- [ ] **Step 1: Write failing tests**

Create a structural `Profile` test dataclass and tests asserting: two MOVE providers aggregate to one `move.v1`; Host filtering removes unavailable provider implementations but keeps the canonical operation if another survives; Entity filtering removes unsupported implementations; provider identities remain internal.

- [ ] **Step 2: Configure test import path and CI**

Add `platform/orchestrator/src` to pytest `pythonpath`. Add an `operation-resolver.yml` workflow that installs the existing Python dependencies and runs focused D4 tests plus the full Python regression suite.

- [ ] **Step 3: Run CI and verify RED**

Run: `pytest -q tests/orchestrator/test_operation_resolver.py`

Expected: import/collection failure because `design_orchestrator.operation_resolver` does not exist.

- [ ] **Step 4: Commit RED only**

Commit message: `test(orchestrator): define D4 operation resolver contract`

---

### Task 2: Implement aggregation, Host filter, Entity filter, and canonical ResolvedOperation

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Create: `platform/orchestrator/src/design_orchestrator/operation_resolver.py`
- Test: `tests/orchestrator/test_operation_resolver.py`

**Interfaces:**
- `CapabilityProfile` Protocol: host-neutral structural provider capability contract.
- `ResolutionContext(host_provider_servers, entity_kinds, policy, task)`.
- `ResolvedOperation` fields: `operation_id`, `canonical_operation`, `input_schema`, `entity_constraints`, `context_freshness_requirements`, `operation_freshness_requirements`, `effects`, `policy_decision`, `risk`, `task_score`, `preview_supported`, `rollback_supported`, `verification_contract`, `candidate_provider_ids`.
- `ResolutionResult(resolved_operations, provider_candidates)` where `provider_candidates` maps opaque candidate IDs to provider profiles and is internal/non-LLM-facing.
- `OperationResolver.resolve(profiles, context) -> ResolutionResult`.

- [ ] **Step 1: Aggregate first**

Sort profiles deterministically and group by `canonical_operation` before filters. Candidate IDs are deterministic opaque IDs used only inside the result.

- [ ] **Step 2: Apply Host filter**

Within each canonical group keep only profiles whose `provider_server` is in `context.host_provider_servers`. Remove the canonical group only if no provider implementation survives.

- [ ] **Step 3: Apply Entity filter**

For each remaining provider, empty `entity_constraints` means unrestricted. Otherwise all current `entity_kinds` must be supported by that provider. Remove the group if no provider survives.

- [ ] **Step 4: Build canonical operation without provider binding**

Require surviving providers for the same canonical operation to agree on canonical contract fields that must not vary by provider: category, input schema, output schema, and verification contract. Raise `CapabilityConflictError` on disagreement. Aggregate entity constraints/effects deterministically, use conservative maximum risk, conservative `all(...)` for preview/rollback claims, and union operation freshness requirements. `context_freshness_requirements` remains empty in D4 because D5 supplies semantic freshness facts later.

- [ ] **Step 5: Verify GREEN**

Run: `pytest -q tests/orchestrator/test_operation_resolver.py`

Expected: Task 2 cases pass.

- [ ] **Step 6: Commit**

Commit message: `feat(orchestrator): aggregate and filter operation providers`

---

### Task 3: Add Policy filter, Task ranking/top-K, and provider-free LLM schema

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/operation_resolver.py`
- Modify: `tests/orchestrator/test_operation_resolver.py`

**Interfaces:**
- `OperationPolicy(decisions)` where decisions are `ALLOW`, `APPROVAL_REQUIRED`, or `DENY`; `DENY` removes the operation and `APPROVAL_REQUIRED` keeps it with that `policy_decision`.
- `TaskConstraints(allowed_operations=None, scores={}, top_k=10)` where `top_k` is constrained to 3–10.
- `ResolutionResult.llm_action_space() -> tuple[dict[str, object], ...]` omits `candidate_provider_ids` and all provider-level identity.
- `ResolutionResult.structured_output_schema() -> dict[str, object]` emits a constrained canonical operation schema using only canonical names and each operation's canonical input schema.

- [ ] **Step 1: Add failing tests**

Add tests for policy DENY, policy APPROVAL_REQUIRED retention, task allowlist, score ordering, deterministic tie-breaks, top-K, conflicting canonical contracts, and recursive provider-identity absence from both `llm_action_space()` and `structured_output_schema()`.

- [ ] **Step 2: Verify RED**

Run: `pytest -q tests/orchestrator/test_operation_resolver.py`

Expected: new policy/task/schema assertions fail while Task 2 cases remain green.

- [ ] **Step 3: Implement Policy then Task filters in strict order**

Policy is applied after Host/Entity. Task allowlist/scoring is applied last. Sort by descending task score and canonical operation as deterministic tie-break, then take `top_k`; if fewer than three operations survive, return all survivors rather than inventing operations.

- [ ] **Step 4: Implement LLM projection and dynamic schema**

Expose canonical `ResolvedOperation` fields needed for planning, but omit `candidate_provider_ids`. Structured output uses canonical operation IDs and canonical arguments only.

- [ ] **Step 5: Verify focused and full regression suites**

Run:
- `pytest -q tests/orchestrator/test_operation_resolver.py`
- `pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator`

Expected: focused D4 suite green; existing D3/full Python suite remains green except existing live-AutoCAD skips.

- [ ] **Step 6: Commit**

Commit message: `feat(orchestrator): enforce canonical D4 action-space filtering`

---

### Task 4: Review and stacked PR

**Files:**
- Review all D4 diff files.
- Create a stacked PR with base `feat/design-capability-profile` while PR #3 remains open.

**Interfaces:**
- PR states D4 depends on D3 and should be retargeted/rebased onto `main` after PR #3 merges.

- [ ] **Step 1: Review architecture invariants**

Confirm aggregation happens before filtering, filter order is Host→Entity→Policy→Task, no LLM-facing serialization includes provider identity, no provider ranking/binding exists, and no D5–D7 concepts were introduced.

- [ ] **Step 2: Verify final CI at PR head SHA**

Only claim completion from fresh successful GitHub Actions output.

- [ ] **Step 3: Open stacked PR**

Title: `feat(orchestrator): add D4 operation resolver`
