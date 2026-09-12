# Post-Phase-I Engineering Hygiene Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Restore a trustworthy post-Phase-I clean-main baseline without changing public contracts, runtime semantics, Host behavior, or supported product capability.

**Architecture:** Treat hygiene as an evidence-driven engineering-infrastructure migration. First freeze a findings ledger, then repair test import isolation and the stale Phase I script assertion, establish one neutral repository-wide regression workflow, and only after proving coverage remove broad repository-test tails from historical Step workflows while preserving their focused domain/architecture guards. Finish with low-risk test-harness/documentation cleanup and a full verification pass.

**Tech Stack:** Python 3.11, pytest/pytest-asyncio, Ruff, GitHub Actions, PowerShell contract tests, .NET 8 Revit AgentHost Core tests, Markdown engineering records.

**Spec:** `docs/superpowers/specs/2026-09-12-post-phase-i-engineering-hygiene-design.md`

## Global Constraints

- Baseline is `main@d2d1621b30f87506c62adb2d12f73d387821ef78`; the approved design commit is `849419f3bf986f6099a8b35aee9e3e4d45fe86ab`.
- Zero product behavior change. Do not change schemas, canonical actions, approval semantics, ChangeSet semantics, materialization semantics, provider binding, authorization, reconciliation, convergence, Host execution, or Host readback behavior.
- Production `platform/**/src/**`, Host/plugin runtime, provider runtime, and contract/schema files are prohibited by default. If a cleanup requires those areas, record `DEFER` instead of expanding scope.
- Historical Design Specs and Implementation Plans are engineering records. Do not rewrite their technical bodies. Lifecycle status is expressed through the new index/ledger, not by editing old documents.
- Static non-reference does not prove dead code in this plugin/provider/Host system. Any `REMOVE` candidate needs evidence covering dynamic registration, manifests, reflection/config discovery, CI/scripts, and supported tests.
- Keep Phase H and Phase I workflows as focused capability/acceptance gates. Do not fold real dual-Host execution into the new repository-wide workflow.
- Historical workflow consolidation removes only stale broad repository pytest tails after the new current gate is proven to be a superset. Preserve focused tests, architecture guards, path filters, branch-boundary checks, Ruff guards, and Step36/Step37 “no new repository Ruff diagnostics” checks.
- Expected hardware-gated skips remain skips. Do not fake-pass AutoCAD/Revit live acceptance on GitHub-hosted runners.
- Use TDD/characterization for every test or CI behavior change: observe the current failure, add/adjust the smallest structural test, make the minimum edit, rerun green, then commit.
- New code comments, if any are needed in tests/scripts, must be Chinese.
- Warning count alone is not an exit gate. `jsonschema.RefResolver` and GitHub Action runtime warnings are `DEFER` unless an independently proven behavior-neutral fix is established inside this plan.
- Do not delete remote branches in this work. Branch retention is repository administration, not source-tree hygiene.

---

## File Structure Map

- `docs/superpowers/hygiene/`: new findings ledger; records evidence, classification, permitted action, verification, and final resolution.
- `tests/materialization_planning/_support.py`: reusable Phase I materialization test builders currently living in `conftest.py`.
- `tests/execution_planning/_support.py`: reusable Step30 V2 Phase I execution inputs currently living in a sibling test module.
- `tests/integration/test_phase_i_environment_discovery_script.py`: source-contract test for the read-only Phase I discovery script.
- `.github/workflows/repository-regression.yml`: one neutral current repository-wide regression authority.
- `tests/architecture/`: structural CI tests that prove current-vs-historical workflow responsibilities.
- Historical Step workflows: retain focused gates; remove only broad repository pytest tails after coverage proof.
- `tests/integration/autocad_live_host.py`: canonical dynamic AutoCAD pipe-discovery helper for live tests.
- `pyproject.toml`, `tests/__init__.py`: durable test/tooling metadata only; no Python path behavior change.
- `README.md`: current repository entry point.
- `docs/superpowers/README.md`: lifecycle/navigation index for historical design records.

---

### Task 1: Freeze the hygiene findings ledger before editing behavior-adjacent infrastructure

**Files:**
- Create: `docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md`

- [ ] **Step 1: Capture the current broad-tail workflow evidence**

Run from the repository root:

```powershell
rg -n "full repository|relevant full Python|--import-mode=importlib" .github/workflows
```

Record the historical Step workflows that currently contain broad repository pytest tails. The frozen set is exactly:

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

Explicitly record that `.github/workflows/phase-h-revit-wall-thickness.yml` is focused-only and must remain unchanged by the broad-tail consolidation. Also record that Phase I retains its offline and real dual-Host acceptance responsibilities.

- [ ] **Step 2: Create the ledger with the approved taxonomy**

Use columns:

```text
ID | Priority | Classification | Evidence | Allowed Action | Verification | Resolution
```

Seed at least these findings:

```text
HYG-001 P0 FIX/CONSOLIDATE historical Step workflows carry stale broad repository pytest tails
HYG-002 P0 FIX pytest import isolation depends on conftest/test-module imports
HYG-003 P0 FIX Phase I discovery test still requires Get-FileHash although script uses shared-read SHA256
HYG-004 P1 DOCUMENT README describes obsolete AutoCAD/M1/v0.5 state
HYG-005 P1 DOCUMENT Design/Plan lifecycle index is missing
HYG-006 P1 DOCUMENT pyproject/tests package comments and integration marker are stage/Host-specific
HYG-007 P1 FIX two AutoCAD live tests bypass canonical dynamic pipe discovery
HYG-008 KEEP/DEFER *_v2 migration bridge files are current execution/public paths, not proven dead
HYG-009 VERIFIED CLEAN previously temporary spec-transfer artifacts are already removed
HYG-010 DEFER jsonschema.RefResolver warning until contract-equivalent migration is proven
HYG-011 DEFER GitHub Actions runtime/Node warning upgrade until isolated verification is planned
HYG-012 KEEP Phase H workflow is focused-only and is not a broad-tail consolidation target
HYG-013 KEEP gRPC generator/transport conformance tooling remains referenced by CI
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

Its body must be the existing `_phase_i_inputs()` logic from `test_step30_materialization_v2.py`: build the case, create `MaterializationPlan`, create deterministic runtime routes, construct `MaterializationRoutingEvidence`, and construct `ExecutionPlanningRequestV2`.

Update `test_step30_materialization_v2.py`, `test_step30_materialization_v2_hashing.py`, and `test_step30_materialization_v2_routing.py` to import `build_phase_i_execution_inputs` from `tests.execution_planning._support`. Do not change assertions or production APIs.

- [ ] **Step 4: Prove forbidden test imports are gone**

```powershell
rg -n "from (tests\.materialization_planning\.)?conftest import|from test_step30_materialization_v2 import" tests
```

Expected: no matches.

- [ ] **Step 5: Run both isolation and local-parity suites for the affected domains**

```powershell
python -m pytest --import-mode=importlib tests/materialization_planning tests/execution_planning -q
python -m pytest tests/materialization_planning tests/execution_planning -q
```

Expected: both green.

- [ ] **Step 6: Commit**

```powershell
git add tests/materialization_planning tests/execution_planning
git commit -m "test: isolate shared materialization test support"
```

---

### Task 3: Align the Phase I discovery-script test with the final shared-read hashing contract

**Files:**
- Modify: `tests/integration/test_phase_i_environment_discovery_script.py`
- Do not modify: `tests/integration/discover_phase_i_live_environment.ps1`

- [ ] **Step 1: Reproduce the stale assertion**

```powershell
python -m pytest tests/integration/test_phase_i_environment_discovery_script.py -q -vv
```

Expected: `test_discovery_script_hashes_only_explicit_or_existing_fixture_paths` fails because it asserts `Get-FileHash` is present.

- [ ] **Step 2: Change only the test contract**

Replace the stale source-text requirement with assertions for the actual shared-read implementation:

```python
assert "Get-SharedReadSha256" in text
assert "[System.Security.Cryptography.SHA256]::Create()" in text
assert "[System.IO.FileShare]::ReadWrite" in text
assert "Test-Path" in text
assert "Get-FileHash" not in text
```

Keep the fixture-path/environment-name assertions. Do not reintroduce `Get-FileHash` into the PowerShell script; shared-read hashing is required because controlled fixtures can remain open under AutoCAD/Revit sharing locks.

- [ ] **Step 3: Run targeted GREEN**

```powershell
python -m pytest tests/integration/test_phase_i_environment_discovery_script.py -q -vv
```

- [ ] **Step 4: Prove the repository suites now execute through the previously failing point**

```powershell
python -m pytest --import-mode=importlib -q
python -m pytest -q
```

Expected: both green except intentional live-host skips. If a new unrelated failure appears, add a new ledger finding before editing anything else; do not solve it by touching production code.

- [ ] **Step 5: Commit**

```powershell
git add tests/integration/test_phase_i_environment_discovery_script.py
git commit -m "test: align phase i discovery hash contract"
```

---

### Task 4: Add one neutral current repository-wide regression workflow

**Files:**
- Create: `.github/workflows/repository-regression.yml`
- Create: `tests/architecture/test_repository_regression_workflow.py`

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
ruff check --select E,F,I
Revit.AgentHost.Core.Tests.csproj dotnet test
no self-hosted dual-host runner label
no DSP_PHASE_I_LIVE = 1
```

Run:

```powershell
python -m pytest tests/architecture/test_repository_regression_workflow.py -q -vv
```

Expected: RED because the workflow does not exist.

- [ ] **Step 2: Create `.github/workflows/repository-regression.yml`**

Use neutral name `Repository regression` and no `paths:` filters. The Python job runs on `ubuntu-latest`, Python 3.11, and installs the broad currently proven test stack:

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

The Python verification steps are:

```yaml
- run: ruff check --select E,F,I tests contracts/python/tests
- run: python -m pytest --import-mode=importlib -q
- run: python -m pytest -q
```

The .NET job runs on `ubuntu-latest`, installs .NET 8, and executes:

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

Do not add AutoCAD/Revit live execution. Those remain external/manual gates.

- [ ] **Step 3: Run structural GREEN and the same commands locally**

```powershell
python -m pytest tests/architecture/test_repository_regression_workflow.py -q -vv
ruff check --select E,F,I tests contracts/python/tests
python -m pytest --import-mode=importlib -q
python -m pytest -q
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

- [ ] **Step 4: Record HYG-001 coverage proof in the findings ledger**

Record that root pytest in importlib mode covers all test directories reached by the historical broad-tail commands, while normal mode adds local parity. The Revit Core job preserves the current Revit-free .NET gate. Do not mark historical workflows consolidated yet; that happens only after this workflow is green in CI.

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
- Do not remove or merge the Phase I real dual-Host job.

- [ ] **Step 1: Confirm `repository-regression` is green before deleting any historical broad tail**

On the implementation PR, inspect the current `Repository regression` run. If it is not green, stop this Task and fix only the already-approved test/CI infrastructure defect that caused it. Do not remove historical broad tests to obtain green status.

- [ ] **Step 2: Write RED structural coverage tests**

In `tests/architecture/test_historical_workflow_scope.py`, define the exact 12-file historical set and assert that none contains `--import-mode=importlib` after consolidation. Also assert that Phase H still exists and retains its Revit architecture/sidecar/reconciliation/.NET focused steps.

Run:

```powershell
python -m pytest tests/architecture/test_historical_workflow_scope.py -q -vv
```

Expected: RED because the 12 historical workflows still contain broad-tail pytest commands.

- [ ] **Step 3: Remove only the broad pytest tails**

Delete these steps/lines and nothing else:

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

- [ ] **Step 4: Prove only the current repository workflow owns broad pytest**

```powershell
rg -n "full repository|relevant full Python|--import-mode=importlib" .github/workflows
```

Expected: historical Step25–37 broad-tail matches are gone. Any remaining importlib occurrence must have an explicitly justified current/focused owner; `repository-regression.yml` is the canonical repository-wide owner.

- [ ] **Step 5: Run structural and local regression gates**

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

- [ ] **Step 3: Run helper tests and verify live tests still skip offline**

```powershell
python -m pytest tests/integration/test_autocad_live_host.py -q -vv
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

- [ ] **Step 1: Characterize the current collection before editing metadata**

```powershell
python -m pytest --collect-only -q
```

Save the collected-test count in the findings ledger or implementation notes for before/after comparison.

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

Update `tests/__init__.py` to remove the Phase I-specific rationale while retaining the package-resolution purpose:

```python
"""DSP 测试包。

将仓库内 tests 目录声明为显式 Python 包，避免本机环境中第三方同名
``tests`` 包抢占导入解析，并允许仓库内测试辅助模块稳定复用。
"""
```

- [ ] **Step 3: Verify collection and both test modes are unchanged**

```powershell
python -m pytest --collect-only -q
python -m pytest --import-mode=importlib -q
python -m pytest -q
git diff --check
```

The collected-test count must match the pre-edit characterization, apart from tests deliberately added by this hygiene work.

- [ ] **Step 4: Commit**

```powershell
git add pyproject.toml tests/__init__.py
git commit -m "chore: generalize repository test metadata"
```

---

### Task 8: Refresh README and add lifecycle navigation without rewriting historical records

**Files:**
- Modify: `README.md`
- Create: `docs/superpowers/README.md`

- [ ] **Step 1: Replace stale README project-state claims**

README must state all of the following current truths:

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

- [ ] **Step 2: Create `docs/superpowers/README.md` as an external lifecycle index**

Define status meanings `CURRENT`, `COMPLETED`, `SUPERSEDED`, `ABANDONED`.

Separate authority/version status from stage-history status:

```text
Enterprise_Collaborative_Design_Agent_Spec_v0.6.md = CURRENT
Enterprise_Collaborative_Design_Agent_Spec_v0.5.md = SUPERSEDED
```

Represent the historical design/plan chain chronologically and link to the existing artifacts. Mark implemented stages through Phase I as `COMPLETED`; mark the 2026-09-12 hygiene Design and Plan as `CURRENT` while this work is active. State explicitly:

```text
Phase I = latest completed capability phase
Engineering Hygiene / Stabilization = current engineering activity
Next capability phase = NOT YET DEFINED
```

Do not edit old Design Spec or Plan bodies to inject statuses.

- [ ] **Step 3: Verify core links exist**

```powershell
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

- [ ] **Step 4: Verify historical bodies were not modified and commit**

```powershell
git diff --name-only main...HEAD -- docs/superpowers/specs docs/superpowers/plans
```

Expected additions in the 2026-09-12 hygiene Design/Plan only; no historical file modification.

```powershell
git add README.md docs/superpowers/README.md
git commit -m "docs: refresh current repository lifecycle"
```

---

### Task 9: Run the final clean-baseline verification and close the findings ledger

**Files:**
- Modify: `docs/superpowers/hygiene/2026-09-12-post-phase-i-findings.md`

- [ ] **Step 1: Run the canonical repository Python gates**

```powershell
python -m pytest --import-mode=importlib -q
python -m pytest -q
ruff check --select E,F,I tests contracts/python/tests
```

Expected: green with only intentional hardware-gated skips. Compare skip reasons with the baseline; no new unexplained skip is allowed.

- [ ] **Step 2: Run Revit-free .NET verification**

```powershell
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

Expected: green.

- [ ] **Step 3: Re-run the Phase I offline verification surface**

Use the same offline package/test selections defined by `.github/workflows/phase-i-real-cross-host-materialization-saga.yml`, with `DSP_PHASE_I_LIVE=0` and `DSP_REVIT_LIVE=0`. The goal is to prove the existing Phase I offline acceptance remains green after test/CI hygiene.

No new real dual-Host run is required because this plan does not modify live Host execution or mutation behavior. If implementation unexpectedly touches a live harness or Host execution path beyond the approved test-only adapter-construction change, stop and require the applicable real Host acceptance before claiming completion.

- [ ] **Step 4: Prove historical broad pytest ownership has been removed without deleting focused guards**

```powershell
rg -n "full repository|relevant full Python|--import-mode=importlib" .github/workflows
python -m pytest tests/architecture/test_repository_regression_workflow.py tests/architecture/test_historical_workflow_scope.py -q -vv
```

Expected: the neutral current repository workflow owns repository-wide pytest; the 12 historical Step workflows remain focused and Phase H/Phase I retain their separate purposes.

- [ ] **Step 5: Prove source-tree and historical-record boundaries**

```powershell
git diff --check
git diff --name-only main...HEAD
```

Inspect the changed-file list. There must be no product/runtime changes under `platform/**/src/**`, Host/plugin production runtime, provider runtime, or contracts/schema. There must be no modification to historical `docs/superpowers/specs/*.md` or `docs/superpowers/plans/*.md` bodies; only the new hygiene Design/Plan are allowed additions there.

- [ ] **Step 6: Close every ledger row with evidence**

Set final resolutions:

```text
HYG-001 resolved by canonical repository regression + focused historical workflows
HYG-002 resolved by explicit test-support modules
HYG-003 resolved by shared-read SHA256 test contract
HYG-004 resolved by README refresh
HYG-005 resolved by lifecycle index
HYG-006 resolved by durable test metadata wording
HYG-007 resolved by canonical live AutoCAD discovery helper in all four basic live tests
HYG-008 KEEP/DEFER unchanged
HYG-009 VERIFIED CLEAN unchanged
HYG-010 DEFER RefResolver migration
HYG-011 DEFER Action/Node runtime upgrade
HYG-012 KEEP Phase H focused workflow
HYG-013 KEEP gRPC generator/conformance tooling
```

Include exact verification commands/results and implementation commit SHAs in the Resolution column.

- [ ] **Step 7: Commit final evidence**

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
- [ ] `ruff check --select E,F,I tests contracts/python/tests` is green for the enforced scope.
- [ ] Revit AgentHost Core tests are green.
- [ ] Phase I offline gate remains green.
- [ ] `repository-regression` is green in CI.
- [ ] Modified historical workflows are green on their focused gates.
- [ ] Phase H workflow remains focused-only and unchanged by broad-tail consolidation.
- [ ] Phase I real dual-Host acceptance remains a separate manual/self-hosted gate.
- [ ] Historical Step25–37 workflows no longer define repository-wide pytest truth.
- [ ] README accurately states Phase I completed, hygiene current, and the next capability phase undefined.
- [ ] `docs/superpowers/README.md` provides lifecycle navigation without modifying historical bodies.
- [ ] No public contract, canonical semantic, runtime behavior, or Host behavior changed.
- [ ] `git diff --check` passes.
- [ ] The findings ledger contains a verified resolution or explicit `DEFER`/`KEEP` disposition for every item.
