# Post-Phase-I Engineering Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a trustworthy post-Phase-I clean-main baseline without changing public contracts, runtime semantics, Host behavior, or supported product capability.

**Architecture:** Treat hygiene as an evidence-driven engineering-infrastructure migration. First freeze a findings ledger, then repair confirmed stale test contracts/import isolation, establish one neutral repository-wide regression workflow, and only after proving coverage remove broad repository-test tails from historical Step workflows while preserving their focused domain/architecture guards. Finish with low-risk test-harness/documentation cleanup and a full verification pass.

**Tech Stack:** Python 3.11, pytest/pytest-asyncio, Ruff, GitHub Actions, PowerShell contract tests, .NET 8 Revit AgentHost Core tests, Markdown engineering records.

**Spec:** `docs/superpowers/specs/2026-09-12-post-phase-i-engineering-hygiene-design.md`

## Global Constraints

- Baseline is `main@d2d1621b30f87506c62adb2d12f73d387821ef78`; approved Design Spec commit is `849419f3bf986f6099a8b35aee9e3e4d45fe86ab`.
- Zero product behavior change. Do not change schemas, canonical actions, approval semantics, ChangeSet semantics, materialization semantics, provider binding, authorization, reconciliation, convergence, Host execution, or Host readback behavior.
- Production `platform/**/src/**`, Host/plugin runtime, provider runtime, and contract/schema files are prohibited by default. If a cleanup requires those areas, record `DEFER` instead of expanding scope.
- Historical Design Specs and Implementation Plans are engineering records. Do not rewrite their technical bodies. Lifecycle status is expressed through the new index/ledger, not by editing old documents.
- Static non-reference does not prove dead code in this plugin/provider/Host system. Any `REMOVE` candidate needs evidence covering dynamic registration, manifests, reflection/config discovery, CI/scripts, and supported tests.
- Phase H and Phase I workflows remain focused capability/acceptance gates. Phase H workflow YAML is not a broad-tail consolidation target. Its confirmed stale architecture-test assertion is fixed separately as test-only hygiene.
- Historical workflow consolidation removes only stale broad repository pytest tails after the new current gate is proven to be a superset. Preserve focused tests, architecture guards, path filters, branch-boundary checks, Ruff guards, and Step36/Step37 “no new Ruff diagnostics” checks.
- Expected hardware-gated skips remain skips. Do not fake-pass AutoCAD/Revit live acceptance on GitHub-hosted runners.
- Use TDD/characterization for every test or CI behavior change: observe the current failure, add/adjust the smallest structural test, make the minimum edit, rerun green, then commit.
- New code comments, if any are needed in tests/scripts, must be Chinese.
- Ruff hygiene is **baseline-delta**, not a new full-repository formatting project. Existing diagnostics may remain; this work may not add new E/F/I diagnostics. Direct Ruff-clean checks are allowed for files newly created or materially edited by hygiene.
- Warning count alone is not an exit gate. `jsonschema.RefResolver` and GitHub Action runtime warnings remain `DEFER` unless a separately proven behavior-neutral migration is approved.
- Do not delete remote branches in this work. Branch retention is repository administration, not source-tree hygiene.

---

## File Structure Map

- `docs/superpowers/hygiene/`: new findings ledger; records evidence, classification, permitted action, verification, and final resolution.
- `tests/materialization_planning/_support.py`: reusable Phase I materialization test builders currently living in `conftest.py`.
- `tests/execution_planning/_support.py`: reusable Step30 V2 Phase I execution inputs currently living in a sibling test module.
- `tests/integration/test_phase_i_environment_discovery_script.py`: source-contract test for the read-only Phase I discovery script.
- `tests/revit/test_revit_architecture.py`: architecture source-contract test whose revision-read assertion predates the current `UIDocument` execution boundary.
- `.github/workflows/repository-regression.yml`: one neutral current repository-wide regression authority.
- `tests/architecture/`: structural tests for current-vs-historical CI responsibility and documentation lifecycle coverage.
- Historical Step workflows: retain focused gates; remove only broad repository pytest tails after coverage proof.
- `tests/integration/autocad_live_host.py`: canonical dynamic AutoCAD pipe-discovery helper for basic live tests.
- `pyproject.toml`, `tests/__init__.py`: durable test/tooling metadata only; no Python path behavior change.
- `README.md`: current repository entry point.
- `docs/superpowers/README.md`: lifecycle/navigation index for historical design records.

---

### Task 1: Freeze the hygiene findings ledger before editing behavior-adjacent infrastructure

**Files:**
- Create: `docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md`

- [ ] **Step 1: Capture current broad-tail workflow evidence**

Run from the repository root:

```powershell
rg -n "full repository|relevant full Python|--import-mode=importlib" .github/workflows
```

Record the historical Step workflows that contain broad repository pytest tails. The frozen consolidation set is exactly:

```text
.github/workflows/step25-d6-parameter-binder.yml
.github/workflows/step26-interaction-session.yml
.github/workflows/step27-impact-layer.yml
.github/workflows/step28-approval-scope.yml
.github/workflows/step29-immutable-changeset.yml
.github/workflows/step30-execution-partitioning.yml
.github/workflows/step31-provider-binding.yml
.github/workflows/step32-gateway-authorization.yml
.github/workflows/step33-execution-reconciliation.yml
.github/workflows/step34-autocad-wall-thickness.yml
.github/workflows/step36-offset-create-scope-breach.yml
.github/workflows/step37-cross-host-saga-failure-injection.yml
```

Record separately that `.github/workflows/phase-h-revit-wall-thickness.yml` is focused-only and therefore not a consolidation target, while its `tests/revit/test_revit_architecture.py` gate currently has one stale textual assertion. Record that Phase I keeps separate offline and real dual-Host acceptance responsibilities.

- [ ] **Step 2: Create the ledger with only approved classifications**

Use columns:

```text
ID | Priority | Classification | Evidence | Allowed Action | Verification | Resolution
```

Every Classification value must be exactly one of `REMOVE`, `FIX`, `CONSOLIDATE`, `DOCUMENT`, or `DEFER`.

Seed these findings:

```text
HYG-001 P0 CONSOLIDATE historical Step25–37 workflows carry stale broad repository pytest tails
HYG-002 P0 FIX pytest import isolation depends on conftest/test-module imports
HYG-003 P0 FIX Phase I discovery test still requires Get-FileHash although the script uses shared-read SHA256
HYG-004 P1 DOCUMENT README describes obsolete AutoCAD/M1/v0.5 state
HYG-005 P1 DOCUMENT Design/Plan lifecycle index is missing
HYG-006 P1 DOCUMENT pyproject/tests package comments and integration marker are stage/Host-specific
HYG-007 P1 FIX two AutoCAD live tests bypass canonical dynamic pipe discovery
HYG-008 P1 DEFER *_v2 migration bridge files are current execution/public paths and are not proven dead
HYG-009 P1 DOCUMENT previously temporary spec-transfer artifacts are already removed; record as verified clean only
HYG-010 P1 DEFER jsonschema.RefResolver warning until contract-equivalent migration is proven
HYG-011 P1 DEFER GitHub Actions runtime/Node warning upgrade until isolated verification is planned
HYG-012 P1 DOCUMENT Phase H workflow structure is focused-only and is not a broad-tail consolidation target
HYG-013 P1 DOCUMENT gRPC generator/transport conformance tooling remains actively referenced by CI
HYG-014 P0 FIX Phase H Revit architecture test still asserts revisions.Get(document) after the executor boundary moved to UIDocument
```

- [ ] **Step 3: Verify the ledger contains no implied product work**

```powershell
rg -n "platform/.*/src|hosts/.*/plugin|providers/.*/src|contracts/.+schema" docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md
```

Any production-path mention must be evidence/context only, not an allowed edit. If a finding would require a production edit, classify it `DEFER`.

- [ ] **Step 4: Commit**

```powershell
git add docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md
git commit -m "docs: freeze post-phase-i hygiene findings"
```

---

### Task 2: Repair pytest import isolation by extracting explicit test-support modules

**Files:**
- Create: `tests/materialization_planning/_support.py`
- Modify: `tests/materialization_planning/conftest.py`
- Modify: `tests/materialization_planning/test_planner.py`
- Create: `tests/execution_planning/_support.py`
- Modify: `tests/execution_planning/test_step30_materialization_v2.py`
- Modify: `tests/execution_planning/test_step30_materialization_v2_hashing.py`
- Modify: `tests/execution_planning/test_step30_materialization_v2_routing.py`
- Modify: `tests/execution_planning/test_step30_materialization_v2_scope_resolution.py`

- [ ] **Step 1: Reproduce the importlib collection defect**

```powershell
python -m pytest --import-mode=importlib tests/materialization_planning tests/execution_planning -q
```

Expected on the baseline: collection/import failures caused by bare `from conftest import ...`, `from tests.materialization_planning.conftest import ...`, or `from test_step30_materialization_v2 import ...` dependencies.

- [ ] **Step 2: Extract materialization-planning reusable helpers without semantic edits**

Move these existing definitions from `tests/materialization_planning/conftest.py` into `tests/materialization_planning/_support.py` with their bodies unchanged:

```text
_bound_evidence
_contract
slot
topology
build_case
```

Leave `conftest.py` as pytest fixture wiring only:

```python
import pytest

from tests.materialization_planning._support import build_case


@pytest.fixture
def phase_i_case():
    return build_case()
```

Update `tests/materialization_planning/test_planner.py` and `tests/execution_planning/test_step30_materialization_v2_scope_resolution.py` to import helpers from `tests.materialization_planning._support`.

- [ ] **Step 3: Extract execution-planning reusable Phase I inputs**

Create `tests/execution_planning/_support.py` with:

```python
def build_phase_i_execution_inputs():
    ...
```

Its body is the existing `_phase_i_inputs()` logic from `test_step30_materialization_v2.py`: build the case, create `MaterializationPlan`, create deterministic runtime routes, construct `MaterializationRoutingEvidence`, and construct `ExecutionPlanningRequestV2`.

Update `test_step30_materialization_v2.py`, `test_step30_materialization_v2_hashing.py`, and `test_step30_materialization_v2_routing.py` to import `build_phase_i_execution_inputs` from `tests.execution_planning._support`. Do not change assertions or production APIs.

- [ ] **Step 4: Prove forbidden test imports are gone**

```powershell
rg -n "from (tests\.materialization_planning\.)?conftest import|from test_step30_materialization_v2 import" tests
```

Expected: no matches.

- [ ] **Step 5: Run affected-domain isolation, local parity, and Ruff checks**

```powershell
python -m pytest --import-mode=importlib tests/materialization_planning tests/execution_planning -q
python -m pytest tests/materialization_planning tests/execution_planning -q
ruff check --select E,F,I tests/materialization_planning tests/execution_planning
```

Expected: green.

- [ ] **Step 6: Commit**

```powershell
git add tests/materialization_planning tests/execution_planning
git commit -m "test: isolate shared materialization test support"
```

---

### Task 3: Align stale Phase I and Phase H textual test contracts with current implementation boundaries

**Files:**
- Modify: `tests/integration/test_phase_i_environment_discovery_script.py`
- Modify: `tests/revit/test_revit_architecture.py`
- Do not modify: `tests/integration/discover_phase_i_live_environment.ps1`
- Do not modify: `hosts/revit/plugin/Revit.AgentHost.Native/**`

- [ ] **Step 1: Reproduce both confirmed stale assertions**

```powershell
python -m pytest tests/integration/test_phase_i_environment_discovery_script.py -q -vv
python -m pytest tests/revit/test_revit_architecture.py -q -vv
```

Expected on the baseline:

```text
Phase I discovery-script test: fails because source does not contain Get-FileHash
Phase H Revit architecture test: 12 passed / 1 failed because handler uses revisions.Get(uiDocument.Document), not revisions.Get(document)
```

- [ ] **Step 2: Change only the Phase I source-text test contract**

Replace the stale `Get-FileHash` requirement with assertions for the implementation that already exists:

```python
assert "Get-SharedReadSha256" in text
assert "[System.Security.Cryptography.SHA256]::Create()" in text
assert "[System.IO.FileShare]::ReadWrite" in text
assert "Test-Path" in text
assert "Get-FileHash" not in text
```

Keep fixture-path/environment-name assertions. Do not reintroduce `Get-FileHash` into the PowerShell script; controlled fixtures can remain open under AutoCAD/Revit sharing locks.

- [ ] **Step 3: Change only the Phase H architecture source assertion**

In `test_document_revision_identity_uses_revit_document_equality_and_cleans_up_on_close`, preserve all assertions about `ConcurrentDictionary<Document, long>`, `Document.Equals/GetHashCode` semantics, `DocumentChanged`, `DocumentClosing`, and `TryRemove(document)`.

Replace the obsolete handler expectation with the current UI/document boundary:

```python
assert "revisions.Get(uiDocument.Document)" in handler_text
assert "() => revisions.Get(uiDocument.Document)" in handler_text
```

Do not edit `RevitExternalEventHandler.cs` or `DocumentRevisionTracker.cs`; the .NET Core regression is already green and this is a stale textual architecture assertion.

- [ ] **Step 4: Run targeted GREEN plus focused Phase H/.NET verification**

```powershell
python -m pytest tests/integration/test_phase_i_environment_discovery_script.py -q -vv
python -m pytest tests/revit/test_revit_architecture.py -q -vv
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
ruff check --select E,F,I tests/integration/test_phase_i_environment_discovery_script.py tests/revit/test_revit_architecture.py
```

Expected: both Python targets green; Revit Core remains green.

- [ ] **Step 5: Prove repository suites now execute beyond the previously failing points**

```powershell
python -m pytest --import-mode=importlib -q
python -m pytest -q
```

Expected: both green except intentional hardware-gated skips. If a new unrelated failure appears, add a new ledger finding before editing anything else; do not solve it by touching production code.

- [ ] **Step 6: Commit**

```powershell
git add tests/integration/test_phase_i_environment_discovery_script.py tests/revit/test_revit_architecture.py
git commit -m "test: align stale phase acceptance assertions"
```

---

### Task 4: Add one neutral current repository-wide regression workflow

**Files:**
- Create: `.github/workflows/repository-regression.yml`
- Create: `tests/architecture/test_repository_regression_workflow.py`
- Modify: `docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md`

- [ ] **Step 1: Write RED structural tests for the new workflow**

`tests/architecture/test_repository_regression_workflow.py` must require:

```text
repository-regression.yml exists
push trigger exists without paths filter
pull_request trigger exists without paths filter
workflow_dispatch exists
AGENT_HOST_TEST = 0
DSP_PHASE_I_LIVE = 0
DSP_REVIT_LIVE = 0
python -m pytest --import-mode=importlib -q
python -m pytest -q
an “Enforce no new repository Ruff diagnostics” baseline-delta step
ruff check --select E,F,I --output-format=json platform hosts/autocad/sidecar tests runs for base and head
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
no self-hosted dual-host runner label
no DSP_PHASE_I_LIVE = 1
```

Run:

```powershell
python -m pytest tests/architecture/test_repository_regression_workflow.py -q -vv
```

Expected: RED because the workflow does not exist.

- [ ] **Step 2: Create `.github/workflows/repository-regression.yml`**

Use neutral name `Repository regression` and no `paths:` filters. The Python job runs on `ubuntu-latest`, Python 3.11, with offline environment:

```yaml
env:
  AGENT_HOST_TEST: "0"
  DSP_PHASE_I_LIVE: "0"
  DSP_REVIT_LIVE: "0"
```

Install the currently proven broad test stack:

```yaml
- run: python -m pip install pytest pytest-asyncio jsonschema PyYAML==6.0.3 ruff
- run: >-
    python -m pip install
    -e contracts/python
    -e hosts/autocad/sidecar
    -e platform/semantic_runtime
    -e platform/semantic_service
    -e platform/semantic_mcp
    -e providers/semantics/dsp_core
    -e providers/semantics/ifc43
    -e providers/semantics/metro_v32
    -e providers/semantics/enterprise_mapping
```

Run both current repository pytest modes:

```yaml
- run: python -m pytest --import-mode=importlib -q
- run: python -m pytest -q
```

Add a Ruff baseline-delta step patterned on the existing Step36/Step37 guard, not a hard historical-zero gate:

1. resolve `BASE_SHA` to the PR base SHA for `pull_request`, `github.event.before` for normal `push`, and `HEAD^` for `workflow_dispatch` or an all-zero push base;
2. `git worktree add /tmp/dsp-base "$BASE_SHA"`;
3. run `ruff check --select E,F,I --output-format=json platform hosts/autocad/sidecar tests` in base and head with `|| true` to collect diagnostics;
4. normalize repository-relative filenames and compare `Counter[(filename, code, message)]` values;
5. fail only when `head - base` contains new diagnostics.

Do not bulk-format or fix historical diagnostics in this Task.

The .NET job runs on `ubuntu-latest`, installs .NET 8, and executes:

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

Do not add AutoCAD/Revit live execution. Those remain external/manual gates.

- [ ] **Step 3: Run structural GREEN and local equivalents**

```powershell
python -m pytest tests/architecture/test_repository_regression_workflow.py -q -vv
python -m pytest --import-mode=importlib -q
python -m pytest -q
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

For locally edited/new Python files, run direct Ruff:

```powershell
ruff check --select E,F,I tests/materialization_planning tests/execution_planning tests/integration/test_phase_i_environment_discovery_script.py tests/revit/test_revit_architecture.py tests/architecture/test_repository_regression_workflow.py
```

- [ ] **Step 4: Record HYG-001 coverage proof**

Record that root pytest in importlib mode covers the valid union of historical broad-tail pytest scopes and normal mode adds local parity; the Ruff guard preserves the pre-existing diagnostic baseline while prohibiting additions; Revit Core remains an explicit current gate.

Do not mark historical workflows consolidated yet; that happens only after this workflow is green in CI.

- [ ] **Step 5: Commit**

```powershell
git add .github/workflows/repository-regression.yml tests/architecture/test_repository_regression_workflow.py docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md
git commit -m "ci: add canonical repository regression"
```

---

### Task 5: Consolidate historical Step workflows to focused guards only

**Files:**
- Create: `tests/architecture/test_historical_workflow_scope.py`
- Modify the exact 12 Step workflow files listed in Task 1.
- Modify: `docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md`
- Do not modify: `.github/workflows/phase-h-revit-wall-thickness.yml`
- Do not remove or merge: Phase I real dual-Host job.

- [ ] **Step 1: Confirm prerequisite current/focused CI gates are green**

On the implementation PR, require:

```text
Repository regression = green
Phase H Revit wall thickness = green after Task 3 test-only assertion repair
Phase I offline job = green where triggered/applicable
```

If `Repository regression` is not green, stop this Task. Do not remove historical broad tests to obtain green status.

- [ ] **Step 2: Write RED structural coverage tests**

In `tests/architecture/test_historical_workflow_scope.py`, define the exact 12-file historical consolidation set and assert that none contains `--import-mode=importlib` after consolidation. Also assert:

```text
phase-h-revit-wall-thickness.yml still exists
Phase H retains Revit architecture, sidecar, reconciliation, external-live-gate, and .NET focused steps
phase-i-real-cross-host-materialization-saga.yml still contains phase-i-offline and phase-i-real-dual-host jobs
Step36/Step37 no-new-Ruff-diagnostics guards remain present
```

Run:

```powershell
python -m pytest tests/architecture/test_historical_workflow_scope.py -q -vv
```

Expected: RED because the 12 historical workflows still contain broad-tail pytest commands.

- [ ] **Step 3: Remove only the broad pytest tails**

Delete these broad-tail steps/commands and nothing else:

```text
Step25: Run relevant full Python regression
Step26: Run relevant full Python regression
Step27: Run relevant full Python regression
Step28: Run full repository Python test suite
Step29: Run full repository Python test suite
Step30: Run full repository Python test suite
Step31: Run full repository tests
Step32: Run full repository tests
Step33: Run full repository importlib suite
Step33: remove the importlib full-suite command inside its legacy branch-only final verification block
Step34: Run full repository importlib regression
Step36: Run full repository importlib regression
Step37: Run full repository importlib regression
```

Preserve every focused regression and architecture test. Preserve Step36/37 repository Ruff-delta guards, diff/branch-boundary checks, path filters, installs, and focused Step34/36/37 proofs.

- [ ] **Step 4: Prove broad pytest ownership moved rather than disappeared**

```powershell
rg -n "full repository|relevant full Python|--import-mode=importlib" .github/workflows
```

Expected: historical Step25–37 broad-tail matches are gone. The neutral `repository-regression.yml` owns repository-wide importlib pytest. Any other remaining match must be explicitly focused and justified by its workflow role.

- [ ] **Step 5: Run structural and repository regression gates**

```powershell
python -m pytest tests/architecture/test_historical_workflow_scope.py tests/architecture/test_repository_regression_workflow.py -q -vv
python -m pytest --import-mode=importlib -q
python -m pytest -q
```

- [ ] **Step 6: Update HYG-001 resolution and commit**

Record that coverage was moved, not deleted: the new root repository gate is the superset; historical workflows retain focused owners.

```powershell
git add .github/workflows tests/architecture docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md
git commit -m "ci: keep historical workflows focused"
```

---

### Task 6: Normalize AutoCAD live-test pipe discovery without touching HostAdapter production defaults

**Files:**
- Modify: `tests/integration/test_autocad_live_host.py`
- Modify: `tests/integration/test_move_idempotency.py`
- Modify: `tests/integration/test_revision_conflict.py`

- [ ] **Step 1: Add a RED structural test**

Add a parametrized test in `test_autocad_live_host.py` that reads both legacy live-test files and requires:

```python
assert "live_autocad_host_adapter()" in source
assert "HostAdapter()" not in source
```

Run:

```powershell
python -m pytest tests/integration/test_autocad_live_host.py -q -vv
```

Expected: RED for both files on the baseline.

- [ ] **Step 2: Switch only test harness construction**

In `test_move_idempotency.py` and `test_revision_conflict.py`, replace the direct production adapter import/constructor with:

```python
from autocad_live_host import live_autocad_host_adapter  # noqa: E402
...
host = live_autocad_host_adapter()
```

Do not modify `HostAdapter` itself or its default pipe name.

- [ ] **Step 3: Run helper tests, Ruff, and verify live tests still skip offline**

```powershell
python -m pytest tests/integration/test_autocad_live_host.py -q -vv
ruff check --select E,F,I tests/integration/test_autocad_live_host.py tests/integration/test_move_idempotency.py tests/integration/test_revision_conflict.py
$env:AGENT_HOST_TEST = "0"
python -m pytest tests/integration/test_move_idempotency.py tests/integration/test_revision_conflict.py -q -vv
```

Expected: helper unit tests green; live tests skip for the same explicit `AGENT_HOST_TEST=1` reason.

- [ ] **Step 4: Commit**

```powershell
git add tests/integration/test_autocad_live_host.py tests/integration/test_move_idempotency.py tests/integration/test_revision_conflict.py
git commit -m "test: normalize live autocad pipe discovery"
```

---

### Task 7: Generalize durable test/tooling metadata without changing module resolution

**Files:**
- Modify: `pyproject.toml`
- Modify: `tests/__init__.py`

- [ ] **Step 1: Characterize current collection before editing metadata**

```powershell
python -m pytest --collect-only -q
```

Record the collected-test count in the findings ledger or implementation notes for before/after comparison.

- [ ] **Step 2: Update comments/marker descriptions only**

In `pyproject.toml`, keep the `pythonpath` list byte-for-byte unchanged. Replace the Phase-I-specific comment with durable wording:

```toml
# 统一仓库根目录、本地测试与 CI 的 Python 模块解析边界。
# 从仓库根目录执行离线回归时不需要额外手工拼接 PYTHONPATH。
```

Change only the integration marker description to:

```toml
"integration: 需要真实宿主（AutoCAD 和/或 Revit）的测试"
```

Do not add runtime dependencies and do not convert/remove the commented uv workspace block in this Task.

Update `tests/__init__.py` to remove the Phase I-specific rationale while retaining package-resolution purpose:

```python
"""DSP 测试包。

将仓库内 tests 目录声明为显式 Python 包，避免本机环境中第三方同名
``tests`` 包抢占导入解析，并允许仓库内测试辅助模块稳定复用。
"""
```

- [ ] **Step 3: Verify collection and both test modes remain valid**

```powershell
python -m pytest --collect-only -q
python -m pytest --import-mode=importlib -q
python -m pytest -q
git diff --check
```

The collected-test count must equal the pre-edit count plus only the structural tests deliberately added by this hygiene plan.

- [ ] **Step 4: Commit**

```powershell
git add pyproject.toml tests/__init__.py
git commit -m "chore: generalize repository test metadata"
```

---

### Task 8: Refresh README and add complete lifecycle navigation without rewriting historical records

**Files:**
- Create: `tests/architecture/test_document_lifecycle_index.py`
- Modify: `README.md`
- Create: `docs/superpowers/README.md`

- [ ] **Step 1: Write RED lifecycle-index structural tests**

`tests/architecture/test_document_lifecycle_index.py` must:

1. enumerate every `*.md` filename in `docs/superpowers/specs/` and `docs/superpowers/plans/`;
2. require every filename to appear in `docs/superpowers/README.md`;
3. require explicit v0.6 `CURRENT` and v0.5 `SUPERSEDED` entries;
4. require explicit statements equivalent to:

```text
Phase I = latest completed capability phase
Engineering Hygiene / Stabilization = current engineering activity
Next capability phase = NOT YET DEFINED
```

Run:

```powershell
python -m pytest tests/architecture/test_document_lifecycle_index.py -q -vv
```

Expected: RED because `docs/superpowers/README.md` does not exist yet.

- [ ] **Step 2: Replace stale README project-state claims**

README must state these current truths:

```text
Latest completed capability phase: Phase I
Current activity: Engineering Hygiene / Stabilization
Next capability phase: NOT YET DEFINED
Hosts represented in the current proof: AutoCAD + Revit
Current system spec entry: docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md
Historical superseded spec: docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.5.md
Real dual-host runbook: docs/runbooks/phase-i-real-cross-host-wall-thickness.md
Design/plan history index: docs/superpowers/README.md
```

Remove obsolete statements that M1 is current, that `platform/` is a future second-stage placeholder, or that v0.5 is the current specification.

Keep README as an entry point, not a duplicate architecture spec. Its current-capability summary should cover canonical semantic/change pipeline, approval scope, immutable ChangeSet, materialization topology/planning, provider binding, gateway authorization, execution reconciliation, cross-host coordination/convergence, deterministic partial commit, and real AutoCAD + Revit acceptance.

Include verification entry points:

```powershell
python -m pytest --import-mode=importlib -q
python -m pytest -q
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

- [ ] **Step 3: Create `docs/superpowers/README.md` as the external lifecycle index**

Define status meanings `CURRENT`, `COMPLETED`, `SUPERSEDED`, `ABANDONED`.

Separate authority/version status from stage-history status:

```text
Enterprise_Collaborative_Design_Agent_Spec_v0.6.md = CURRENT
Enterprise_Collaborative_Design_Agent_Spec_v0.5.md = SUPERSEDED
```

Represent the existing design/plan chain chronologically and link every current filename discovered in `docs/superpowers/specs/` and `docs/superpowers/plans/`. Mark implemented stages through Phase I as `COMPLETED`; mark the 2026-09-12 hygiene Design and Plan as `CURRENT` while this work is active.

Do not edit old Design Spec or Plan bodies to inject statuses.

- [ ] **Step 4: Run lifecycle-index GREEN and verify core link targets exist**

```powershell
python -m pytest tests/architecture/test_document_lifecycle_index.py -q -vv
python - <<'PY'
from pathlib import Path

required = (
    "docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md",
    "docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.5.md",
    "docs/runbooks/phase-i-real-cross-host-wall-thickness.md",
    "docs/superpowers/specs/2026-09-12-post-phase-i-engineering-hygiene-design.md",
    "docs/superpowers/plans/2026-09-12-post-phase-i-engineering-hygiene.md",
)
missing = [path for path in required if not Path(path).is_file()]
if missing:
    raise SystemExit("missing documentation targets:\n" + "\n".join(missing))
PY
```

- [ ] **Step 5: Verify historical bodies were not modified and commit**

```powershell
git diff --name-only main...HEAD -- docs/superpowers/specs docs/superpowers/plans
```

Expected: only the new 2026-09-12 hygiene Design/Plan appear; no historical file modification.

```powershell
git add README.md docs/superpowers/README.md tests/architecture/test_document_lifecycle_index.py
git commit -m "docs: refresh current repository lifecycle"
```

---

### Task 9: Run final clean-baseline verification and close the findings ledger

**Files:**
- Modify: `docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md`

- [ ] **Step 1: Run canonical repository Python gates**

```powershell
$env:AGENT_HOST_TEST = "0"
$env:DSP_PHASE_I_LIVE = "0"
$env:DSP_REVIT_LIVE = "0"
python -m pytest --import-mode=importlib -q
python -m pytest -q
```

Expected: green with only intentional hardware-gated skips. Compare skip reasons with the baseline; no new unexplained skip is allowed.

Run direct Ruff only on hygiene-created/materially edited Python files:

```powershell
ruff check --select E,F,I tests/materialization_planning tests/execution_planning tests/integration/test_phase_i_environment_discovery_script.py tests/integration/test_autocad_live_host.py tests/integration/test_move_idempotency.py tests/integration/test_revision_conflict.py tests/revit/test_revit_architecture.py tests/architecture
```

Repository-wide Ruff correctness is established by the baseline-delta job in `repository-regression`, not by forcing historical diagnostics to zero.

- [ ] **Step 2: Run Revit focused and Revit-free .NET verification**

```powershell
python -m pytest tests/revit/test_revit_architecture.py -q -vv
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

Expected: green.

- [ ] **Step 3: Re-run the exact Phase I offline verification surface**

Keep live gates disabled:

```powershell
$env:DSP_PHASE_I_LIVE = "0"
$env:DSP_REVIT_LIVE = "0"
```

Run the Phase I live-harness offline-safety checks:

```powershell
python -m compileall tests/integration/phase_i_live_host.py
ruff check tests/integration/phase_i_live_host.py tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py
python -m pytest tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py -q -vv
```

Run isolated Phase I package regressions:

```powershell
python -m pytest tests/materialization_topology -q -vv
python -m pytest tests/materialization_planning -q -vv
python -m pytest tests/convergence -q -vv
python -m pytest tests/approval_scope -q -vv
python -m pytest tests/changeset -q -vv
python -m pytest tests/execution_planning -q -vv
python -m pytest tests/provider_binding -q -vv
python -m pytest tests/gateway_authorization -q -vv
python -m pytest tests/execution_reconciliation -q -vv
python -m pytest tests/execution_coordination -q -vv
```

Run the Phase I integration/legacy Host regression set:

```powershell
python -m pytest `
  tests/integration/test_phase_i_materialization_pipeline.py `
  tests/integration/test_phase_i_convergence_divergence.py `
  tests/integration/test_phase_i_readiness_fail_closed.py `
  tests/integration/test_phase_i_real_cross_host_wall_thickness_live.py `
  tests/integration/test_step34_autocad_wall_thickness_reconciliation.py `
  tests/integration/test_phase_h_revit_wall_thickness_reconciliation.py `
  tests/integration/test_phase_h_revit_wall_thickness_live.py `
  tests/architecture/test_phase_i_materialization_architecture.py `
  -q -vv
```

Then run:

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

No new real dual-Host run is required because this plan does not modify live Host execution or mutation behavior. If implementation unexpectedly touches a live harness or Host execution path beyond the approved test-only adapter-construction change, stop and require the applicable real Host acceptance before claiming completion.

- [ ] **Step 4: Prove historical broad pytest ownership is removed without deleting focused guards**

```powershell
rg -n "full repository|relevant full Python|--import-mode=importlib" .github/workflows
python -m pytest tests/architecture/test_repository_regression_workflow.py tests/architecture/test_historical_workflow_scope.py -q -vv
```

Expected: the neutral current repository workflow owns repository-wide pytest; the 12 historical Step workflows remain focused; Phase H and Phase I retain separate purposes.

- [ ] **Step 5: Prove source-tree and historical-record boundaries**

```powershell
git diff --check
git diff --name-only main...HEAD
```

Inspect the changed-file list. There must be no product/runtime changes under `platform/**/src/**`, Host/plugin production runtime, provider runtime, or contracts/schema. There must be no modification to historical `docs/superpowers/specs/*.md` or `docs/superpowers/plans/*.md` bodies; only the new hygiene Design/Plan are allowed additions there.

- [ ] **Step 6: Require CI evidence before completion**

On the implementation PR verify:

```text
Repository regression = green
Phase H Revit wall thickness = green
Phase I offline = green when triggered/applicable
Every modified historical Step workflow = green on its retained focused gates
```

Do not claim clean-main status from local tests alone.

- [ ] **Step 7: Close every ledger row with evidence**

Use only approved classifications; Resolution may describe `resolved`, `retained`, `verified clean`, or `deferred`.

Record at minimum:

```text
HYG-001 resolved by canonical repository regression + focused historical workflows
HYG-002 resolved by explicit test-support modules
HYG-003 resolved by shared-read SHA256 test contract
HYG-004 resolved by README refresh
HYG-005 resolved by complete lifecycle index
HYG-006 resolved by durable test metadata wording
HYG-007 resolved by canonical live AutoCAD discovery helper in all four basic live tests
HYG-008 deferred; current V2 bridge paths retained
HYG-009 verified clean; no source edit required
HYG-010 deferred; RefResolver migration not proven contract-equivalent in this scope
HYG-011 deferred; Action/Node runtime upgrade isolated from this scope
HYG-012 documented; Phase H workflow retained as focused-only
HYG-013 documented; gRPC generator/conformance tooling retained
HYG-014 resolved by updating only the stale Revit architecture textual assertion
```

Include exact verification commands/results and implementation commit SHAs in the Resolution column.

- [ ] **Step 8: Commit final evidence**

```powershell
git add docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md
git commit -m "docs: close engineering hygiene findings"
```

---

## Final Completion Checklist

Before claiming the hygiene stage complete, verify all of the following:

- [ ] `python -m pytest --import-mode=importlib -q` is green.
- [ ] `python -m pytest -q` is green.
- [ ] No new non-intentional skip exists.
- [ ] Hygiene-created/materially edited Python files are Ruff-clean for E/F/I.
- [ ] `repository-regression` proves no new repository Ruff E/F/I diagnostics relative to its base revision.
- [ ] Revit architecture tests and Revit AgentHost Core tests are green.
- [ ] Phase I offline verification surface remains green.
- [ ] `repository-regression` is green in CI.
- [ ] Modified historical workflows are green on their focused gates.
- [ ] Phase H workflow YAML remains focused-only; its stale architecture assertion is repaired in tests only.
- [ ] Phase I real dual-Host acceptance remains a separate manual/self-hosted gate.
- [ ] Historical Step25–37 workflows no longer define repository-wide pytest truth.
- [ ] README accurately states Phase I completed, hygiene current, and the next capability phase undefined.
- [ ] `docs/superpowers/README.md` indexes every Design Spec and Plan without modifying historical bodies.
- [ ] No public contract, canonical semantic, runtime behavior, or Host behavior changed.
- [ ] `git diff --check` passes.
- [ ] The findings ledger contains a verified resolution or explicit `DEFER`/`DOCUMENT` disposition for every item.
