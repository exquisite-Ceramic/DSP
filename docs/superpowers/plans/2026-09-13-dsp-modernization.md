# DSP Technology Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move DSP from the post-Phase-I clean baseline to a supported, reproducible, compatibility-verified technology baseline without intentional product behavior, public-contract, canonical-semantic, or Host-visible behavior changes.

**Architecture:** Execute Technology Modernization as an evidence-gated sequence: `M0 audit → M1 reproducible toolchain → M2 compatibility lanes → M3 dependency/deprecation modernization → M4 protocol/build/Host compatibility → M5 canonical cutover → M6 retirement`. Every executable item is first classified in the modernization ledger; T4 findings leave this plan and enter Architecture Modernization Review. Compatibility changes follow `introduce → dual-run → prove parity → switch → merged-main/Host evidence → retire`.

**Tech Stack:** Python 3.11 current baseline with Python 3.14 candidate lane, `uv`, pytest, Ruff, JSON Schema/jsonschema/referencing, MCP Python SDK v2 line, gRPC/Protobuf, .NET 8 current SDK baseline with .NET 10 candidate compatibility where Host-neutral, Autodesk AutoCAD/Revit SDKs, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-09-13-dsp-modernization-design.md`

## Global Constraints

- Starting clean baseline is `main@e308e9279d17ab61ef0d30c874942ce273a0a3f9`.
- `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md` remains the system-level contract authority.
- Technology Modernization is not a capability phase; the next capability phase remains `NOT YET DEFINED`.
- No task may intentionally change user-visible product behavior, public contract, canonical semantics, Host-visible behavior, or supported capability.
- Any task that requires such a semantic/architectural change is reclassified T4, recorded `DEFER`, and removed from Technology Modernization execution.
- M0 is analysis-only with respect to product/runtime behavior and must finish before M1 implementation starts.
- Python `requires-python >=3.11`, Ruff `target-version = "py311"`, and the canonical Python 3.11 baseline remain unchanged through M1–M4; only M5 may change the canonical floor after parity evidence.
- Native AutoCAD/Revit target frameworks remain Host-defined. A Host-neutral .NET compatibility experiment must not implicitly move native Autodesk projects.
- A T3 Host/runtime support claim requires real AutoCAD/Revit process/runtime evidence. Offline tests and mocks are not substitutes.
- Both canonical Python gates remain protected until a separately approved decision retires one: `python -m pytest --import-mode=importlib -q` and `python -m pytest -q`.
- `.github/workflows/repository-regression.yml` remains the one repository-wide offline truth. Historical/domain workflows remain focused guards.
- The `.proto` and canonical JSON Schema sources remain semantic source-of-truth; generator/runtime upgrades must not redefine wire/schema meaning.
- M0 must refresh time-sensitive external support facts immediately before it approves a runtime, Action major, dependency line, SDK, or Host matrix target.
- For any downstream task whose ledger item is `DEFERRED` or `REJECTED`, do not execute the code/config steps; record the decision and evidence in `modernization-ledger.md`, then continue with the next approved task.
- Each task ends with its own reviewable commit. Do not combine unrelated major upgrades into one commit.

---

## File Structure and Ownership Map

Modernization governance lives under `docs/superpowers/modernization/` and is consumed by structural tests under `tests/architecture/`. Root `pyproject.toml`, member `pyproject.toml` files, and a committed `uv.lock` own Python environment resolution; `global.json` and project `.csproj` files own .NET SDK/TFM/package selection. `contracts/proto/host_transport_v1.proto` remains transport source-of-truth. `.github/workflows/repository-regression.yml` owns canonical offline regression, while `.github/workflows/phase-i-real-cross-host-materialization-saga.yml` continues to own real dual-Host acceptance where hardware/software is required.

M0's `dependency-inventory.md` is an explicit interface to later tasks: it must enumerate every first-party Python manifest and .NET project path before M1 can start. Later tasks may modify a manifest not named in this plan only when that exact path is already recorded in that inventory and the corresponding ledger item is `APPROVED`; this avoids inventing paths before the audit while still making the execution boundary deterministic.

---

### Task 1: M0 — Create modernization governance artifacts and structural guard

**Files:**
- Create: `docs/superpowers/modernization/modernization-ledger.md`
- Create: `docs/superpowers/modernization/runtime-matrix.md`
- Create: `docs/superpowers/modernization/dependency-inventory.md`
- Create: `docs/superpowers/modernization/host-compatibility-matrix.md`
- Create: `docs/superpowers/modernization/modernization-risk-register.md`
- Create: `tests/architecture/test_modernization_governance.py`

**Interfaces:**
- Consumes: seed candidates MOD-001 through MOD-016 from the Design Spec.
- Produces: the authoritative item IDs, risk class, owner, decision (`KEEP / UPGRADE / REPLACE / REMOVE / DEFER`), execution state, evidence links, rollback note, and T0–T4 classification consumed by every later task.

- [ ] **Step 1: Write the failing governance-structure test**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODERNIZATION = ROOT / "docs" / "superpowers" / "modernization"


def test_modernization_governance_files_and_seed_ids_exist() -> None:
    required = {
        "modernization-ledger.md",
        "runtime-matrix.md",
        "dependency-inventory.md",
        "host-compatibility-matrix.md",
        "modernization-risk-register.md",
    }
    assert required <= {path.name for path in MODERNIZATION.glob("*.md")}

    ledger = (MODERNIZATION / "modernization-ledger.md").read_text(encoding="utf-8")
    for number in range(1, 17):
        assert f"MOD-{number:03d}" in ledger
    for token in ("T0", "T1", "T2", "T3", "T4", "DEFER"):
        assert token in ledger
```

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/architecture/test_modernization_governance.py -q`

Expected: FAIL because `docs/superpowers/modernization/` and its five records do not yet exist.

- [ ] **Step 3: Create the five factual records**

Create the five documents with tables whose columns are explicit, not prose-only. The ledger must contain MOD-001…MOD-016 exactly as seeded by the spec and add `Execution state` with initial value `PROPOSED`. The risk register must define T0…T4 and state that T4 cannot be implemented by this plan. The inventory records must state baseline commit `e308e9279d17ab61ef0d30c874942ce273a0a3f9`.

- [ ] **Step 4: Run the focused structural test**

Run: `python -m pytest tests/architecture/test_modernization_governance.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/modernization tests/architecture/test_modernization_governance.py
git commit -m "docs: seed modernization governance records"
```

---

### Task 2: M0 — Inventory runtimes, packages, dependencies, protocol tooling, CI and Host constraints

**Files:**
- Modify: `docs/superpowers/modernization/runtime-matrix.md`
- Modify: `docs/superpowers/modernization/dependency-inventory.md`
- Modify: `docs/superpowers/modernization/host-compatibility-matrix.md`
- Modify: `docs/superpowers/modernization/modernization-risk-register.md`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`
- Modify: `tests/architecture/test_modernization_governance.py`

**Interfaces:**
- Consumes: repository tree and manifests at the frozen baseline plus refreshed vendor/runtime support documentation.
- Produces: exhaustive first-party manifest/project ownership and the current/candidate/keep facts required for the M0 exit gate.

- [ ] **Step 1: Extend the failing test to require all seven audit areas**

```python

def test_m0_inventory_covers_all_audit_areas() -> None:
    inventory = (MODERNIZATION / "dependency-inventory.md").read_text(encoding="utf-8")
    runtime = (MODERNIZATION / "runtime-matrix.md").read_text(encoding="utf-8")
    host = (MODERNIZATION / "host-compatibility-matrix.md").read_text(encoding="utf-8")
    joined = "\n".join((inventory, runtime, host))
    for marker in (
        "A1 Runtime", "A2 Dependency", "A3 Deprecation", "A4 Build & Packaging",
        "A5 Protocol & Schema", "A6 Host Compatibility", "A7 CI & Toolchain",
    ):
        assert marker in joined
```

Also require exact known roots: `pyproject.toml`, `contracts/python/pyproject.toml`, `hosts/autocad/sidecar/pyproject.toml`, `hosts/revit/sidecar/pyproject.toml`, `global.json`, `contracts/proto/host_transport_v1.proto`, `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj`, `hosts/revit/plugin/Revit.AgentHost.Core/Revit.AgentHost.Core.csproj`, and `hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj`.

- [ ] **Step 2: Run the test and verify RED**

Run: `python -m pytest tests/architecture/test_modernization_governance.py -q`

Expected: FAIL because the records are not yet complete.

- [ ] **Step 3: Populate factual inventories from the repository**

Run these inventory commands from a clean checkout and paste the normalized results into the factual records:

```bash
git ls-files '**/pyproject.toml' 'pyproject.toml'
git ls-files '*.csproj' 'global.json'
git ls-files '.github/workflows/*.yml' '.github/dependabot.yml'
git ls-files '*.proto' '*schema.json'
git grep -nE 'RefResolver|referencing|grpcio|protobuf|mcp>|mcp=|PackageReference|TargetFramework|actions/(checkout|setup-python|setup-dotnet|upload-artifact|download-artifact)@'
```

Record declared first-party edges separately from relationships that exist only because root pytest `pythonpath` or workflow install ordering makes imports happen.

- [ ] **Step 4: Refresh support facts before classification**

Refresh Python, .NET, `uv`, MCP, GitHub Actions/runner, Dependabot ecosystem, AutoCAD and Revit runtime/SDK support facts from authoritative vendor/project documentation. Record the source URL and observation date in the relevant matrix; do not convert a design-time candidate into a canonical version merely because it is newer.

- [ ] **Step 5: Capture warning and baseline evidence**

Run:

```bash
python -m pytest --import-mode=importlib -q
python -m pytest -q
dotnet --version
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

Classify observed warnings under `DEPRECATION`, `RUNTIME`, `PACKAGING`, `BUILD`, `HOST_SDK`, or `CI_ACTION`; every warning gets an owner and decision.

Expected: the two Python gates and Revit Core tests remain green at the starting baseline. Any baseline failure blocks M1 and is recorded rather than normalized away.

- [ ] **Step 6: Run the structural test GREEN**

Run: `python -m pytest tests/architecture/test_modernization_governance.py -q`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add docs/superpowers/modernization tests/architecture/test_modernization_governance.py
git commit -m "docs: complete M0 modernization inventory"
```

---

### Task 3: M0 — Freeze executable decisions and enforce the M1 gate

**Files:**
- Modify: `docs/superpowers/modernization/modernization-ledger.md`
- Modify: `docs/superpowers/modernization/modernization-risk-register.md`
- Modify: `tests/architecture/test_modernization_governance.py`

**Interfaces:**
- Consumes: Task 2 inventory and refreshed support facts.
- Produces: executable `APPROVED`, `DEFERRED`, or `REJECTED` state for each modernization candidate. T4 items are never `APPROVED` for Technology Modernization.

- [ ] **Step 1: Add a failing exit-gate test**

Implement a small Markdown-table parser inside `test_modernization_governance.py` that reads MOD rows and asserts every row has non-empty `Owner`, `Risk`, `Decision`, `Execution state`, `Evidence`, and `Rollback` cells, and that no T4 row has `Execution state == "APPROVED"`.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/architecture/test_modernization_governance.py -q`

Expected: FAIL while any seed row still has unknown ownership/risk/evidence or an invalid execution state.

- [ ] **Step 3: Classify all rows**

For each MOD item, choose exactly one execution state: `APPROVED`, `DEFERRED`, or `REJECTED`. Preserve MOD-016 V1/V2 bridges as T4/`DEFERRED`. If any other item requires public-contract, canonical-semantic, Host-visible, or orchestration behavior changes, reclassify it T4/`DEFERRED` and explain why.

- [ ] **Step 4: Re-run M0 gates**

Run:

```bash
python -m pytest tests/architecture/test_modernization_governance.py -q
python -m pytest --import-mode=importlib -q
python -m pytest -q
```

Expected: PASS. M1 may start only after this commit is reviewed.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/modernization tests/architecture/test_modernization_governance.py
git commit -m "docs: freeze M0 modernization decisions"
```

---

### Task 4: M1 — Establish a root `uv` workspace and committed lock without changing the Python floor

**Files:**
- Modify: `pyproject.toml`
- Modify: exact first-party member `pyproject.toml` files listed as package-managed in `docs/superpowers/modernization/dependency-inventory.md`
- Create: `uv.lock`
- Create: `tests/architecture/test_modernization_workspace.py`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`

**Interfaces:**
- Consumes: approved MOD-002/MOD-003 and Task 2's exact package manifest inventory.
- Produces: explicit workspace membership, first-party dependency ownership, and one committed lock while all active packages still support Python 3.11.

- [ ] **Step 1: Write failing workspace tests**

The structural test must parse root `pyproject.toml` with `tomllib`, assert `[tool.uv.workspace]` exists, assert every inventory row marked `workspace-member` is present, assert root `requires-python` remains `>=3.11`, assert Ruff remains `py311`, and assert `uv.lock` exists.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/architecture/test_modernization_workspace.py -q`

Expected: FAIL because no root workspace/lock is present.

- [ ] **Step 3: Add the workspace and real first-party dependencies**

Add only package paths classified as package-managed by M0. Express real first-party dependencies through member metadata rather than relying on root pytest `pythonpath` or editable-install order. Do not merge distributions or rename existing packages/entry points.

- [ ] **Step 4: Generate and validate the lock**

Run:

```bash
uv lock
uv lock --check
uv sync --locked --all-packages
uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
```

Expected: lock check PASS; both canonical pytest modes PASS with unchanged semantics.

- [ ] **Step 5: Update ledger evidence and commit**

Mark MOD-002/MOD-003 `VERIFIED` only after the clean locked environment passes.

```bash
git add pyproject.toml uv.lock docs/superpowers/modernization/modernization-ledger.md tests/architecture/test_modernization_workspace.py
git add $(git ls-files '**/pyproject.toml')
git commit -m "build: establish reproducible Python workspace"
```

---

### Task 5: M1 — Make canonical CI consume the locked Python graph

**Files:**
- Modify: `.github/workflows/repository-regression.yml`
- Modify: `tests/architecture/test_repository_regression_workflow.py`
- Modify: `tests/architecture/test_modernization_workspace.py`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`

**Interfaces:**
- Consumes: Task 4 `uv.lock` and workspace.
- Produces: canonical CI bootstrap that reconstructs Python from metadata + committed lock instead of ordered editable installs.

- [ ] **Step 1: Write failing workflow assertions**

Assert the canonical workflow installs `uv`, executes `uv sync --locked` (or `uv sync --frozen` only if M0 explicitly chose frozen-consumption semantics), and runs both canonical pytest modes through the locked environment. Assert the workflow no longer contains a hidden ordered chain of `pip install -e` commands for first-party workspace members.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/architecture/test_repository_regression_workflow.py tests/architecture/test_modernization_workspace.py -q`

Expected: FAIL against the pre-M1 bootstrap.

- [ ] **Step 3: Change only bootstrap/resolution mechanics**

Update `.github/workflows/repository-regression.yml` to consume the committed workspace lock. Keep the workflow's ownership and test suites unchanged. Do not add the Python 3.14 lane yet.

- [ ] **Step 4: Verify locally and structurally**

Run:

```bash
uv sync --locked --all-packages
uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
python -m pytest tests/architecture/test_repository_regression_workflow.py -q
```

Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/repository-regression.yml tests/architecture docs/superpowers/modernization/modernization-ledger.md
git commit -m "ci: consume locked Python workspace"
```

---

### Task 6: M1 — Freeze .NET SDK, NuGet and code-generation ownership

**Files:**
- Modify: `global.json`
- Modify if approved by MOD-013 evidence: `Directory.Packages.props`
- Modify if centralization is rejected: exact `.csproj` files recorded in `dependency-inventory.md` only to document/normalize approved package-version ownership
- Modify: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj`
- Create: `tests/architecture/test_modernization_dotnet_toolchain.py`
- Modify: `docs/superpowers/modernization/dependency-inventory.md`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`

**Interfaces:**
- Consumes: approved MOD-007/MOD-012/MOD-013 findings.
- Produces: deterministic SDK policy and explicit ownership for `Google.Protobuf`, `Grpc.AspNetCore`, `Grpc.Tools`, Host-neutral build dependencies, and proto generation.

- [ ] **Step 1: Write failing structural tests**

Assert `global.json` has the M0-approved SDK version/roll-forward policy; assert every package-version owner from the inventory maps to exactly one declared location; assert `contracts/proto/host_transport_v1.proto` remains referenced by the .NET transport project; assert native Host projects retain their current Host-defined TFM model.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/architecture/test_modernization_dotnet_toolchain.py -q`

Expected: FAIL on whichever ownership/determinism facts M0 approved but the repository does not yet encode.

- [ ] **Step 3: Implement only the approved governance shape**

Keep `Directory.Packages.props` absent when MOD-013 is `KEEP`. Create it only if M0 demonstrated repeated declarations/version drift and marked central package management `APPROVED`. Preserve `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj` as Host-defined `net8.0-windows` at M1 and preserve the dynamic Revit native TFM mechanism.

- [ ] **Step 4: Verify .NET and canonical regression**

Run:

```bash
dotnet --version
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
python -m pytest tests/architecture/test_modernization_dotnet_toolchain.py -q
python -m pytest --import-mode=importlib -q
python -m pytest -q
```

Expected: PASS. Native Autodesk plugin builds are required only where the corresponding SDK is available; absence is recorded, not converted into a support claim.

- [ ] **Step 5: Commit**

```bash
git add global.json hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj tests/architecture docs/superpowers/modernization
git add Directory.Packages.props 2>/dev/null || true
git commit -m "build: make dotnet toolchain ownership explicit"
```

---

### Task 7: M2 — Add Python 3.14 as a non-canonical compatibility lane

**Files:**
- Modify: `.github/workflows/repository-regression.yml`
- Modify: `tests/architecture/test_repository_regression_workflow.py`
- Create: `tests/architecture/test_modernization_runtime_matrix.py`
- Modify: `docs/superpowers/modernization/runtime-matrix.md`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`

**Interfaces:**
- Consumes: approved MOD-001, locked M1 environment.
- Produces: CI evidence that current Python 3.11 remains canonical while candidate Python 3.14 executes the same applicable offline suites.

- [ ] **Step 1: Write failing matrix tests**

Parse the workflow and assert both `3.11` and `3.14` lanes exist, 3.11 remains explicitly canonical, both consume the locked workspace, and the source metadata still says `requires-python >=3.11` / Ruff `py311`.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/architecture/test_modernization_runtime_matrix.py tests/architecture/test_repository_regression_workflow.py -q`

Expected: FAIL because the candidate lane does not yet exist.

- [ ] **Step 3: Add the compatibility lane without changing production syntax/floor**

Use the same locked metadata and same applicable unit/contract/repository-regression commands. Any Python-3.14-only incompatibility must be fixed only when the fix is behavior-neutral; otherwise MOD-001 is `DEFERRED` or escalated T4.

- [ ] **Step 4: Prove both runtimes locally where available**

Run:

```bash
uv run --python 3.11 python -m pytest --import-mode=importlib -q
uv run --python 3.11 python -m pytest -q
uv run --python 3.14 python -m pytest --import-mode=importlib -q
uv run --python 3.14 python -m pytest -q
```

Expected: all applicable suites PASS with no unexplained skips. CI is the authoritative cross-environment evidence.

- [ ] **Step 5: Commit**

```bash
git add .github/workflows/repository-regression.yml tests/architecture docs/superpowers/modernization
git commit -m "ci: prove Python 3.14 compatibility"
```

---

### Task 8: M2 — Prove .NET 10 compatibility only for approved Host-neutral projects

**Files:**
- Modify only if MOD-009 is `APPROVED`: `hosts/revit/plugin/Revit.AgentHost.Core/Revit.AgentHost.Core.csproj`
- Modify only if MOD-009 is `APPROVED`: `hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj`
- Modify: `.github/workflows/repository-regression.yml`
- Modify: `tests/architecture/test_modernization_dotnet_toolchain.py`
- Modify: `docs/superpowers/modernization/runtime-matrix.md`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`

**Interfaces:**
- Consumes: approved MOD-009 and current Revit Core `net8.0` baseline.
- Produces: net8/net10 compatibility evidence for Host-neutral Core only; no native Revit/AutoCAD support claim.

- [ ] **Step 1: Write failing boundary tests**

Assert that a candidate .NET 10 lane, when approved, targets only Host-neutral Core/test paths and that `hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj` plus `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj` are not mechanically rewritten to net10.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/architecture/test_modernization_dotnet_toolchain.py -q`

Expected: FAIL because no approved candidate lane exists yet.

- [ ] **Step 3: Add the minimum compatibility mechanism**

If consumer analysis permits multi-targeting, change only Revit Core/Core.Tests to `TargetFrameworks` containing `net8.0;net10.0`; otherwise leave project TFM unchanged and use the M0-approved SDK compatibility method. Do not alter native plugin TFM inputs.

- [ ] **Step 4: Verify**

For multi-targeting, run:

```bash
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj -f net8.0
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj -f net10.0
python -m pytest tests/architecture/test_modernization_dotnet_toolchain.py -q
```

Expected: both Host-neutral lanes PASS. If .NET 10 requires semantic changes, revert the candidate and mark MOD-009 deferred/T4 rather than changing behavior.

- [ ] **Step 5: Commit**

```bash
git add hosts/revit/plugin/Revit.AgentHost.Core hosts/revit/plugin/Revit.AgentHost.Core.Tests .github/workflows/repository-regression.yml tests/architecture docs/superpowers/modernization
git commit -m "build: prove host-neutral dotnet 10 compatibility"
```

---

### Task 9: M3 — Characterize and replace deprecated `jsonschema.RefResolver` usage

**Files:**
- Modify: exact resolver implementation file(s) identified by M0 `git grep -n RefResolver` and recorded under MOD-005 in `dependency-inventory.md`
- Modify/Create: the nearest existing schema-validation test module(s) recorded by MOD-005; known contract coverage includes `contracts/python/tests/test_normalized_design_fact_schema.py`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`

**Interfaces:**
- Consumes: approved MOD-005 and unchanged canonical schemas under `contracts/schemas/`.
- Produces: `referencing.Registry`-based resolution with identical success/failure outcomes and no schema edits.

- [ ] **Step 1: Add characterization tests before touching resolver code**

Cover at minimum: local `$ref` success, nested ref success, missing ref failure, invalid instance failure, and the exact canonical contract vectors currently validated. Assert exception/result shape at the public validator boundary rather than implementation class names.

- [ ] **Step 2: Run characterization tests GREEN on the old resolver**

Run the exact MOD-005 focused test module(s), including:

`python -m pytest contracts/python/tests/test_normalized_design_fact_schema.py -q`

Expected: PASS before migration.

- [ ] **Step 3: Add a failing implementation guard**

Add an architecture assertion that production code no longer imports/mentions `RefResolver` once the migration is switched. Run it now and verify RED.

- [ ] **Step 4: Replace only the resolver implementation**

Build a `referencing.Registry` from the same canonical schema resources and pass it to the supported `jsonschema` validator path. Do not edit files in `contracts/schemas/` except if a test proves an existing repository defect unrelated to the migration; such a semantic schema change is T4 and must instead stop this task.

- [ ] **Step 5: Run focused and canonical regression**

```bash
python -m pytest contracts/python/tests/test_normalized_design_fact_schema.py -q
python -m pytest --import-mode=importlib -q
python -m pytest -q
```

Expected: PASS; no `RefResolver` production usage remains; outcomes match characterization tests.

- [ ] **Step 6: Commit**

```bash
git add contracts/python tests/architecture docs/superpowers/modernization
git add $(git grep -l RefResolver -- ':!docs/**' || true)
git commit -m "refactor: migrate schema reference resolution"
```

---

### Task 10: M3 — Upgrade approved Python/.NET dependency families one failure domain at a time

**Files:**
- Modify: exact `pyproject.toml`/`.csproj` paths mapped to each `APPROVED` M3 item in `dependency-inventory.md`
- Modify: `uv.lock`
- Modify: focused tests for the affected package/transport only when characterization is needed
- Modify: `docs/superpowers/modernization/modernization-ledger.md`

**Interfaces:**
- Consumes: M0-approved dependency rows such as MCP v2 support refresh and gRPC/Protobuf runtime/tooling refresh.
- Produces: separately bisectable dependency-family commits with locked versions and preserved behavior.

- [ ] **Step 1: For each approved family, capture pre-upgrade focused evidence**

Run the smallest existing suite owning that family. For AutoCAD gRPC this includes:

```bash
python -m pytest tests -q -k 'grpc or transport'
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

For MCP, run the existing semantic-MCP/sidecar focused tests named in the M0 inventory.

- [ ] **Step 2: Change exactly one dependency family**

Update only that family's declared constraints/package references and run `uv lock` when Python resolution changes. Do not group unrelated major upgrades.

- [ ] **Step 3: Run focused GREEN then full GREEN**

```bash
uv lock --check
python -m pytest --import-mode=importlib -q
python -m pytest -q
```

Also run the affected .NET suite for NuGet/gRPC changes.

- [ ] **Step 4: Record evidence and commit before the next family**

Use a family-specific commit such as `build: refresh MCP SDK support line` or `build: refresh gRPC protobuf toolchain`. Repeat Steps 1–4 only for the next `APPROVED` family.

---

### Task 11: M3 — Upgrade GitHub Action families and add bounded dependency automation

**Files:**
- Modify: `.github/workflows/repository-regression.yml`
- Modify: other `.github/workflows/*.yml` only for the Action family currently being upgraded
- Create/Modify: `.github/dependabot.yml`
- Create: `tests/architecture/test_modernization_actions.py`
- Modify: `docs/superpowers/modernization/dependency-inventory.md`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`

**Interfaces:**
- Consumes: approved MOD-008/MOD-014 plus refreshed Action runner requirements.
- Produces: supported Action majors compatible with repository/self-hosted runners and reviewable update automation for supported ecosystems.

- [ ] **Step 1: Write failing Action-governance tests**

Parse workflow YAML as text and assert no M0-classified unsupported Action major remains after its family is migrated. Assert Dependabot contains only the M0-approved ecosystems (`uv`, NuGet, .NET SDK metadata when supported/useful, GitHub Actions) and does not auto-merge majors.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/architecture/test_modernization_actions.py -q`

Expected: FAIL on the first approved outdated family / missing automation entry.

- [ ] **Step 3: Upgrade one Action family at a time**

For example, update all approved `actions/checkout` uses as one family, verify, commit; then `setup-python`, verify, commit; then `setup-dotnet`, etc. Preserve self-hosted workflow compatibility; if the required Node/runtime is unsupported by a required runner, defer that family instead of silently dropping the runner.

- [ ] **Step 4: Verify structural and canonical workflow behavior**

```bash
python -m pytest tests/architecture/test_modernization_actions.py tests/architecture/test_repository_regression_workflow.py tests/architecture/test_historical_workflow_scope.py -q
python -m pytest --import-mode=importlib -q
python -m pytest -q
```

Expected: PASS.

- [ ] **Step 5: Commit Dependabot separately from major Action families**

```bash
git add .github/dependabot.yml tests/architecture docs/superpowers/modernization
git commit -m "ci: add bounded dependency update automation"
```

---

### Task 12: M4 — Make Protobuf/gRPC generation reproducible and prove wire-contract parity

**Files:**
- Keep semantic source unchanged: `contracts/proto/host_transport_v1.proto`
- Modify as approved: `hosts/autocad/sidecar/pyproject.toml`
- Modify as approved: `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj`
- Modify/regenerate only when deterministic policy says committed output: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/host_transport_v1_pb2.py`
- Modify/regenerate only when deterministic policy says committed output: `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/host_transport_v1_pb2_grpc.py`
- Create: `tests/architecture/test_proto_codegen_reproducibility.py`
- Modify: `docs/superpowers/modernization/dependency-inventory.md`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`

**Interfaces:**
- Consumes: approved MOD-007 and locked generator/runtime versions.
- Produces: deterministic generation evidence plus unchanged cross-language wire shape.

- [ ] **Step 1: Write failing reproducibility guard**

The test must assert the proto path remains the only source-of-truth, Python generator versions are declared/locked, .NET `Grpc.Tools` ownership is explicit, and the documented regeneration command targets the existing generated package.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/architecture/test_proto_codegen_reproducibility.py -q`

Expected: FAIL until generator ownership/commands are encoded.

- [ ] **Step 3: Regenerate in a temporary tree and diff**

Use the locked Python generator version to generate from `contracts/proto/host_transport_v1.proto` into a temporary directory, normalize only generator-known non-semantic headers if the repository policy explicitly allows it, and diff message/service descriptors against committed output. Do not edit the `.proto` to make generated code easier to upgrade.

- [ ] **Step 4: Run transport conformance**

```bash
python -m pytest -q -k 'grpc or transport'
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
python -m pytest tests/architecture/test_proto_codegen_reproducibility.py -q
```

Expected: PASS; wire/service semantics unchanged.

- [ ] **Step 5: Commit**

```bash
git add hosts/autocad/sidecar/pyproject.toml hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated tests/architecture docs/superpowers/modernization
git commit -m "build: make protobuf generation reproducible"
```

---

### Task 13: M4 — Validate Host version ↔ SDK ↔ TFM ↔ runtime compatibility and real-Host evidence

**Files:**
- Modify: `docs/superpowers/modernization/host-compatibility-matrix.md`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`
- Modify only when an approved Host build target requires it: `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj`
- Modify only when an approved Host build target requires it: `hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj`
- Modify when acceptance coverage needs baseline-only wiring: `.github/workflows/phase-i-real-cross-host-materialization-saga.yml`
- Create: `tests/architecture/test_modernization_host_matrix.py`

**Interfaces:**
- Consumes: MOD-010/MOD-011 plus vendor-supported Host/runtime facts.
- Produces: explicit per-Host support rows and real acceptance evidence for every T3 support claim.

- [ ] **Step 1: Write failing matrix-completeness tests**

For each row marked `SUPPORTED`, require non-empty values for product/version, vendor runtime, SDK/API assembly source, DSP TFM, build SDK, offline Core evidence, native build evidence, real Host acceptance evidence, and support status. Assert a T3 `SUPPORTED` row cannot contain `N/A` for real Host evidence.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/architecture/test_modernization_host_matrix.py -q`

Expected: FAIL until support rows are complete.

- [ ] **Step 3: Build against the exact SDK/Host targets that are being claimed**

AutoCAD build uses the matrix-owned `AUTOCAD_ACAD_DIR`. Revit build uses the existing `DspRevitTargetFramework`/SDK input model. Do not replace those Host boundaries merely to create one repository-wide TFM.

- [ ] **Step 4: Run real Host acceptance for T3 changes**

Use the existing manual/self-hosted real Host workflow and acceptance runbook. Required evidence must show the tested commit SHA, AutoCAD/Revit versions, runtime/TFM, native plugin load/build, positive path, and required Phase I cross-Host acceptance. A missing Autodesk installation means `NOT VERIFIED`, not PASS.

- [ ] **Step 5: Run structural + offline regression**

```bash
python -m pytest tests/architecture/test_modernization_host_matrix.py -q
python -m pytest --import-mode=importlib -q
python -m pytest -q
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

Expected: PASS. Mark T3 items `VERIFIED` only after separate real-Host evidence is linked.

- [ ] **Step 6: Commit**

```bash
git add docs/superpowers/modernization tests/architecture .github/workflows/phase-i-real-cross-host-materialization-saga.yml hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj
git commit -m "docs: verify modernization host compatibility"
```

---

### Task 14: M5 — Cut over the canonical baseline atomically after parity evidence

**Files:**
- Modify: `pyproject.toml`
- Modify: approved member `pyproject.toml` files from `dependency-inventory.md`
- Modify: `uv.lock`
- Modify: `global.json` if the approved canonical .NET SDK changes
- Modify: approved Host-neutral `.csproj` files only
- Modify: `.github/workflows/repository-regression.yml`
- Modify: `README.md`
- Modify: `docs/superpowers/README.md`
- Modify: `docs/superpowers/modernization/runtime-matrix.md`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`
- Modify: `tests/architecture/test_modernization_runtime_matrix.py`

**Interfaces:**
- Consumes: VERIFIED M1–M4 parity evidence.
- Produces: one repository-wide canonical technology baseline whose metadata, lock, lint target, SDK policy, CI and documentation agree.

- [ ] **Step 1: Add a failing canonical-consistency test**

Read root/member Python metadata, Ruff target, `global.json`, canonical workflow and modernization runtime matrix. Assert they all name the same approved canonical Python/.NET baseline and that no candidate can be canonical unless its ledger state is `VERIFIED`.

- [ ] **Step 2: Run RED before cutover**

Run: `python -m pytest tests/architecture/test_modernization_runtime_matrix.py -q`

Expected: FAIL because the repository still intentionally describes the old canonical baseline.

- [ ] **Step 3: Perform the coordinated cutover**

If MOD-001 is VERIFIED and approved for cutover, update Python `requires-python`, Ruff target, canonical CI version, lock assumptions and developer docs together. If it is not VERIFIED, leave Python 3.11 canonical. Apply the same evidence rule to Host-neutral .NET SDK/TFM cutover. Native Host projects remain governed by the Host matrix and may legitimately stay on different TFMs.

- [ ] **Step 4: Regenerate/validate the lock and run all offline gates**

```bash
uv lock
uv lock --check
uv sync --locked --all-packages
uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
python -m pytest tests/architecture -q
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

Expected: PASS.

- [ ] **Step 5: Require real Host re-acceptance when the cutover touches a T3 support claim**

Do not mark M5 complete until the exact cutover commit has the required AutoCAD/Revit evidence for affected T3 rows.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock global.json .github/workflows/repository-regression.yml README.md docs/superpowers tests/architecture
git add $(git ls-files '**/pyproject.toml' '*.csproj')
git commit -m "build: cut over canonical modernization baseline"
```

---

### Task 15: M6 — Retire only proven legacy technology paths

**Files:**
- Modify: `.github/workflows/repository-regression.yml`
- Modify/Delete: obsolete bootstrap or compatibility-lane files explicitly listed as `RETIRE` candidates in `modernization-ledger.md`
- Modify: `docs/superpowers/modernization/modernization-ledger.md`
- Modify: `docs/superpowers/modernization/modernization-risk-register.md`
- Modify: `tests/architecture/test_modernization_runtime_matrix.py`
- Modify: `tests/architecture/test_modernization_workspace.py`

**Interfaces:**
- Consumes: merged-main/Host observation evidence after M5.
- Produces: removal of only obsolete technology-baseline paths; retained compatibility surfaces have explicit reasons.

- [ ] **Step 1: Write a failing retirement guard for each approved retirement item**

Examples: old Python compatibility lane, procedural editable-install bootstrap, deprecated resolver path, obsolete Action/runtime assumption, stale codegen path. The test must name the concrete path/token being retired and its replacement MOD item.

- [ ] **Step 2: Run RED**

Run the focused architecture test and confirm it fails because the old path still exists.

- [ ] **Step 3: Remove one proven old path**

Remove only when the ledger includes replacement, consumers, parity evidence, rollback implications and observation evidence. Do **not** remove `*_v2`, V1/V2 bridges, Host/provider abstractions, or contract compatibility paths under M6 merely because they look old; those remain MOD-016/T4 Architecture Modernization inputs.

- [ ] **Step 4: Run full verification after every retirement commit**

```bash
python -m pytest tests/architecture -q
python -m pytest --import-mode=importlib -q
python -m pytest -q
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
```

Expected: PASS.

- [ ] **Step 5: Commit each retirement independently**

Use commit messages naming the retired path, for example `ci: retire Python 3.11 compatibility lane` only when the ledger proves that retirement.

---

### Task 16: Close Technology Modernization and hand T4 findings to Architecture Modernization Review

**Files:**
- Modify: `docs/superpowers/modernization/modernization-ledger.md`
- Modify: `docs/superpowers/modernization/modernization-risk-register.md`
- Create: `docs/superpowers/modernization/architecture-modernization-review-input.md`
- Modify: `docs/superpowers/README.md`
- Modify: `README.md`
- Modify: `tests/architecture/test_modernization_governance.py`

**Interfaces:**
- Consumes: final M0–M6 ledger and verification evidence.
- Produces: completed Technology Modernization record plus evidence-only handoff for a separate architecture brainstorming/design process. It does not authorize architecture implementation.

- [ ] **Step 1: Write failing completion tests**

Assert no `APPROVED` Technology Modernization row remains in an ambiguous/non-terminal state; every T4 row is present in `architecture-modernization-review-input.md`; current docs still state `Next capability phase: NOT YET DEFINED`; and no Architecture Modernization change is marked implemented by this plan.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/architecture/test_modernization_governance.py -q`

Expected: FAIL until the final ledger and handoff are complete.

- [ ] **Step 3: Produce the architecture review input**

Record evidence for V1/V2 compatibility bridges, Host/provider boundaries, runtime abstractions, package/module boundaries, contract evolution candidates and any T4 findings discovered during modernization. Allowed recommendation states are evidence-oriented (`KEEP`, `ASSESS TARGETED CHANGE`, `ASSESS LARGER PROGRAM`); do not write an implementation plan for architecture changes here.

- [ ] **Step 4: Run final repository verification**

```bash
uv lock --check
uv sync --locked --all-packages
uv run python -m pytest --import-mode=importlib -q
uv run python -m pytest -q
python -m pytest tests/architecture -q
dotnet test hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj
dotnet test hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj
```

Also require successful merged-main `Repository regression` and all real Host evidence required by surviving T3 support claims.

Expected: all applicable gates PASS; no unexpected skip is used to manufacture success.

- [ ] **Step 5: Update lifecycle wording and commit**

Update the lifecycle index/README to describe Technology Modernization as completed only after the merged-result evidence exists. Do not invent the next capability phase.

```bash
git add docs/superpowers/modernization docs/superpowers/README.md README.md tests/architecture/test_modernization_governance.py
git commit -m "docs: close technology modernization program"
```

---

## Cutover and Rollback Checkpoints

Before M5, T2/T3 candidates retain the old canonical path. Rollback is source-control-based: revert the candidate/cutover commit and restore the previously verified lock/workflow/SDK policy; do not add permanent product feature flags merely for modernization. After M5 merged-main verification and required Host evidence, M6 may remove the old technology path. Once a data/protocol/build-format change is classified T4, this plan never attempts a forward/backward semantic migration; it exits to Architecture Modernization Review.

## Required Evidence at Wave Boundaries

- **M0 → M1:** all items have owner/risk/decision/evidence; no T4 item is approved; starting regression is green.
- **M1 → M2:** clean checkout reconstructs Python/.NET/tooling deterministically; Python floor remains 3.11.
- **M2 → M3:** candidate runtimes pass applicable parity suites without unexplained skips or semantic fixes.
- **M3 → M4:** approved dependency/deprecation items are VERIFIED or explicitly DEFERRED/REJECTED.
- **M4 → M5:** protocol/tooling parity is green; every T3 support claim has real Host evidence.
- **M5 → M6:** canonical metadata, lock, CI, docs and SDK policies agree; merged-main regression is green; affected Host acceptance is green.
- **M6 → Architecture Review:** retired technology paths have replacement/evidence; retained compatibility paths have reasons; all T4 findings are handed off, not implemented.

## Final Self-Review Checklist for the Executor

Before claiming this plan complete, compare the final repository against every Design Spec section from Target Technology Stack through Program Completion Criteria. Search the implementation diff for `*_v2`/bridge deletions, contract/schema semantic edits, Host-visible behavior edits, unsupported skip additions, and accidental capability-phase naming. Any such change without a separate approved architecture/capability design is a plan violation and must be reverted or reclassified T4.
