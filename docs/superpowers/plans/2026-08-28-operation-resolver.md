# D4 Operation Resolver Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the D4 Operation Resolver so discovered provider capabilities are first aggregated by `canonical_operation`, then filtered in strict Host → Entity → Policy → Task order, producing 3–10 canonical `ResolvedOperation` choices when enough candidates exist plus a provider-free dynamic structured-output schema for the LLM.

**Architecture:** Put D4 in a host-neutral orchestrator package under `platform/orchestrator/src/design_orchestrator`. Provider MCP schemas remain provider-facing execution contracts. A platform-owned `CanonicalOperationDefinition` catalog supplies Host-independent LLM argument schemas; later `ProviderBinding.input_adapter_version` is responsible for translating canonical arguments into provider-specific tool inputs. The resolver keeps provider candidates as internal routing hints only and never selects/binds a provider.

**Tech Stack:** Python 3.11, dataclasses, typing Protocol, pytest, jsonschema, GitHub Actions.

**Spec:** `Enterprise_Collaborative_Design_Agent_Spec_v0.5.md` §5.3, §6.1–6.5, §16.2–16.4, Appendix D step 4, Appendix E.1–E.3.

## Global Constraints

- Aggregate provider profiles by `canonical_operation` before any filtering.
- Platform canonical definitions are a contract gate: unknown canonical operations never expand the LLM action space.
- Provider MCP `inputSchema` / `outputSchema` MUST NOT be reused as canonical LLM schemas; provider schemas may legitimately differ for the same canonical operation.
- Filtering order is exactly Host → Entity → Policy → Task after canonical contract gating.
- Host and Entity filters are hard constraints; Policy is governance; Task performs relevance/ranking/top-K.
- LLM Action Space MUST NOT contain `provider_server`, `provider_tool`, AutoCAD ObjectId/handles, command strings, approval tokens, execution grants, idempotency keys, or provider transport revision fields.
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

- [x] **Step 1: Write failing tests**

Cover two MOVE providers aggregating to one `move.v1`, Host filtering, Entity filtering, and provider candidates staying internal.

- [x] **Step 2: Configure test import path and CI**

Add `platform/orchestrator/src` to pytest `pythonpath`; run focused D4 tests and full Python regression in GitHub Actions.

- [x] **Step 3: Verify RED**

Observed expected `ModuleNotFoundError: design_orchestrator` before production code existed.

- [x] **Step 4: Commit RED only**

Commit: `8cb717a test(orchestrator): define D4 operation resolver contract`.

---

### Task 2: Implement aggregation, Host filter, Entity filter, and canonical ResolvedOperation

**Files:**
- Create: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Create: `platform/orchestrator/src/design_orchestrator/operation_resolver.py`
- Test: `tests/orchestrator/test_operation_resolver.py`

**Interfaces:**
- `CapabilityProfile` Protocol: host-neutral structural provider capability contract.
- `ResolutionContext(host_provider_servers, entity_kinds, policy, task)`.
- `ResolvedOperation`: `operation_id`, `canonical_operation`, `input_schema`, entity/freshness/effects/policy/risk/task/lifecycle/verification fields, plus internal `candidate_provider_ids`.
- `ResolutionResult(resolved_operations, provider_candidates)` keeps provider profiles internal.

- [x] **Step 1: Aggregate first**

Group deterministically by `canonical_operation` before Host/Entity/Policy/Task filtering.

- [x] **Step 2: Apply Host filter**

Remove unavailable provider implementations while preserving the canonical operation if at least one implementation survives.

- [x] **Step 3: Apply Entity filter**

Require all current entity kinds to be supported by each candidate provider unless its entity constraint list is unrestricted.

- [x] **Step 4: Build canonical operation without provider binding**

Keep opaque deterministic provider candidate IDs internal. Aggregate provider execution freshness, effects, conservative risk, preview, and rollback claims without ranking/binding a provider.

- [x] **Step 5: Verify GREEN**

Focused D4 and full Python regression passed before the Policy/Task slice.

- [x] **Step 6: Commit**

Commit: `d87cd5b feat(orchestrator): aggregate and filter operation providers`.

---

### Task 3: Add Policy filter, Task ranking/top-K, and provider-free LLM schema

- [x] **Step 1: Add failing tests**

Cover Policy `DENY` / `APPROVAL_REQUIRED`, task allowlist, score ordering, deterministic ties, top-K 3–10, provider identity absence, and valid dynamic JSON Schema.

- [x] **Step 2: Verify RED**

Observed expected import failure for `OperationPolicy` before implementation.

- [x] **Step 3: Implement Policy then Task filters**

Policy follows Host/Entity. Task allowlist/scoring is last; rank by descending task score with canonical-operation tie-break and take `top_k`. Return all survivors when fewer than three exist rather than inventing actions.

- [x] **Step 4: Implement LLM projection and dynamic schema**

`llm_action_space()` omits candidate/provider identity. `structured_output_schema()` constrains the LLM to canonical operation names and canonical arguments.

- [x] **Step 5: Verify GREEN**

Initial slice: 14 focused tests and full regression passed.

- [x] **Step 6: Commit**

Commit: `70c87c7 feat(orchestrator): enforce canonical D4 action-space filtering`.

---

### Task 3A: Review fix — separate canonical schemas from provider MCP schemas

**Finding:** The first implementation incorrectly treated each provider's MCP `inputSchema` as `ResolvedOperation.input_schema`. Real `cad.move` uses provider execution arguments `handles`, `dx`, `dy`, `dz`, `idempotency_key`, and `revision`, which would violate Appendix E if exposed to the LLM.

- [x] **Step 1: Add review RED tests before fixing**

Use the real D3 `build_tool_definitions()` + `parse_design_capability()` path. Assert `cad.move` keeps provider execution arguments internally while the LLM sees only canonical `move.v1(targets, displacement)`. Also prove two providers with different provider schemas can aggregate to the same canonical operation and unknown platform operations stay hidden.

- [x] **Step 2: Verify RED**

Observed expected `ModuleNotFoundError: design_orchestrator.canonical_operations`.

- [x] **Step 3: Add platform canonical operation catalog**

Create `CanonicalOperationDefinition` and MVP `MOVE_V1`. `OperationResolver` requires explicit canonical definitions, gates provider claims by canonical category/verification contract, and never uses provider `input_schema` / `output_schema` for the LLM surface.

- [x] **Step 4: Preserve late binding boundary**

Provider-specific MCP schemas remain in internal `provider_candidates`; argument translation is explicitly deferred to later `ProviderBinding.input_adapter_version`.

- [x] **Step 5: Verify GREEN with real D3 integration**

Run `33107846458`: focused D4 **16 passed**; full Python regression **141 passed, 4 skipped** (all four are existing live-AutoCAD gated tests).

- [x] **Step 6: Commit**

Commits: `b4af51f test(orchestrator): separate canonical and provider schemas` and `025b403 fix(orchestrator): separate canonical and provider schemas`.

---

### Task 4: Review and stacked PR

- [x] **Step 1: Review architecture invariants**

Confirm aggregation precedes the four filters; Host→Entity→Policy→Task ordering is preserved; provider MCP schemas stay internal; no LLM-facing serialization includes provider identity/host arguments; no provider ranking/binding exists; no D5–D7 concepts were introduced.

- [ ] **Step 2: Verify final CI at the final PR head SHA**

Only claim completion from fresh successful GitHub Actions output at the final head.

- [ ] **Step 3: Open stacked PR**

Base: `feat/design-capability-profile` while PR #3 remains open. Title: `feat(orchestrator): add D4 operation resolver`. State dependency on D3 and retarget/rebase to `main` after PR #3 merges.
