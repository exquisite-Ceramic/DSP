# DSP Modernization Design

**Status:** DRAFT FOR REVIEW  
**Date:** 2026-09-13  
**Baseline:** `main@e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Contract authority:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md` remains authoritative  
**Latest completed capability phase:** Phase I  
**Current engineering activity:** Modernization Planning  
**Next capability phase:** NOT YET DEFINED

## 1. Purpose

This document defines the modernization program for DSP after Phase I and the post-Phase-I engineering-hygiene work have completed and merged to a clean `main` baseline.

The modernization program is deliberately split into two different concerns:

1. **Technology Modernization** — modernize supported runtimes, dependency resolution, packaging, build tooling, protocol tooling, Host SDK compatibility, CI, and deprecated implementation APIs while preserving existing DSP capability semantics.
2. **Architecture Modernization Review** — only after the technology baseline is stable, evaluate whether architectural simplification is justified, including compatibility bridges, Host/provider boundaries, runtime abstractions, and contract evolution candidates.

Technology Modernization is not a new capability phase and must not be used to smuggle product or architecture changes into maintenance work.

The program follows this invariant:

```text
technology modernization
    may change implementation/runtime/tooling baselines
    but must preserve existing observable DSP behavior

architecture modernization
    may propose semantic or boundary changes
    but only through a separate approved design
```

## 2. Context and current baseline

The modernization program starts only because the repository now has a trusted regression baseline.

At the baseline commit:

- Phase I is complete.
- Post-Phase-I engineering hygiene is complete.
- Repository-wide regression ownership is centralized in `.github/workflows/repository-regression.yml`.
- Historical/domain workflows retain focused ownership rather than duplicated repository-wide pytest tails.
- Both root pytest modes are canonical repository gates.
- Revit Core is part of repository regression.
- Phase I offline acceptance remains separate from manual/self-hosted real dual-Host acceptance.
- Historical Design Specs and Implementation Plans are frozen engineering records.

The current technical facts that motivate modernization include:

- root Python baseline is `requires-python = ">=3.11"` and Ruff targets `py311`;
- canonical repository CI runs Python 3.11;
- canonical repository CI installs the verification stack and first-party packages procedurally with `pip` / editable installs rather than consuming one repository lock;
- `actions/checkout@v4` and `actions/setup-python@v5` remain in the canonical workflow;
- `semantic-mcp` already uses the MCP Python SDK v2 line (`mcp>=2,<3`) and Pydantic v2;
- the AutoCAD sidecar already combines MCP with gRPC/Protobuf, confirming those protocols serve different boundaries rather than being alternatives;
- AutoCAD native plugin currently targets `net8.0-windows` and is constrained by the Autodesk Host runtime;
- Revit native plugin already accepts `DspRevitTargetFramework` as a Host-version-dependent input;
- Revit AgentHost Core currently targets `net8.0`;
- engineering hygiene deferred `jsonschema.RefResolver` migration because equivalence had not yet been characterized;
- engineering hygiene also deferred unrelated GitHub Action/Node runtime upgrades to a dedicated modernization phase.

These facts are inputs to modernization, not permission to change DSP behavior.

## 3. Goals

Technology Modernization has four equal top-level objectives, prioritized by risk and benefit rather than by novelty:

1. **Supported baselines** — move DSP toward maintained runtime and tool versions before existing baselines become operational liabilities.
2. **Reproducibility** — make dependency resolution, environment construction, build inputs, and code generation deterministic enough that the same commit can be reasoned about consistently across machines and CI.
3. **Maintainability** — remove proven deprecated implementation APIs, stale compatibility paths, and maintenance-only duplication when parity is demonstrated.
4. **Developer and CI reliability** — reduce bootstrap ambiguity, dependency drift, fragile install ordering, and false CI ownership without weakening validation.

## 4. Non-goals

Technology Modernization does **not** authorize:

- a new domain contract;
- new canonical actions or changeset semantics;
- new materialization, execution, approval, reconciliation, convergence, identity, or Saga behavior;
- a new Host capability;
- a new provider semantic capability;
- changing the authority of the v0.6 main specification;
- replacing MCP with REST, or gRPC with REST, merely for stack uniformity;
- converting Pydantic implementation models into DSP's cross-language canonical contract;
- a cloud-native rewrite;
- introducing Kubernetes, Kafka, Redis, a database, GraphQL, a service mesh, or a frontend/backend framework without an independently approved product need;
- replacing Python or .NET simply to force one-language stack uniformity;
- enabling free-threaded Python as part of the baseline upgrade without separate evidence;
- rewriting historical Design Specs or Implementation Plans to reflect new lifecycle status;
- naming the next capability phase before a capability Design Spec exists.

Any item that requires one of these changes leaves Technology Modernization and enters the Architecture Modernization Review backlog.

## 5. Program-level design choice

The approved approach is **Conservative Modern Polyglot Modernization**.

DSP keeps the technology boundaries that already match its execution model:

```text
Agent-facing integration
        MCP
         │
         ▼
Python platform / sidecar layers
         │
         │ gRPC + Protobuf where Host transport is required
         ▼
Native Host plugin boundaries
         │
         ▼
AutoCAD / Revit APIs
```

The goal is to modernize this stack, not replace it wholesale.

The rejected alternatives are:

- **Stack unification:** forcing Python-only or .NET-only would increase Host/platform coupling and would fight Autodesk runtime constraints.
- **Cloud-native rewrite:** introduces operational and architectural surface without evidence that DSP's current problem requires it.

## 6. Target technology stack

The following target stack is a design direction. Exact version cutovers are validated by M0/M2 evidence before becoming canonical.

| Area | Current direction | Modernized direction | Decision |
| --- | --- | --- | --- |
| Platform runtime | Python `>=3.11` | Python 3.14 as candidate future canonical baseline after dual-run parity | UPGRADE |
| Python workspace | multiple `pyproject.toml`, procedural install | `uv` workspace with explicit first-party graph | UPGRADE |
| Python lock | no single repository lock | one committed root `uv.lock` | UPGRADE |
| Python build backend | setuptools | retain setuptools unless M0 finds a concrete blocker | KEEP |
| Tests | pytest / pytest-asyncio | retain | KEEP |
| Lint | Ruff | retain; only tighten rules through separate evidence | KEEP |
| Static typing | existing Python typing | optionally evaluate Pyright or mypy as advisory only; no new gate without approval | EVALUATE |
| Canonical schema | JSON Schema | retain JSON Schema | KEEP |
| Python schema resolution | `jsonschema`, deferred `RefResolver` debt | modern `referencing.Registry` path after characterization | UPGRADE |
| Boundary DTOs | Pydantic v2 where already used | retain Pydantic v2 at transport/application boundaries | KEEP |
| Agent protocol | MCP SDK v2 line | retain and keep supported | KEEP / REFRESH |
| Host transport | gRPC + Protobuf | retain | KEEP / REFRESH |
| AutoCAD sidecar | Python + MCP + gRPC | same architecture on modernized locked Python stack | UPGRADE TOOLCHAIN |
| AutoCAD plugin | C# / Host-constrained .NET | Host-version-defined supported TFM | MATRIX |
| Revit plugin | C# / dynamic Host TFM | preserve Host-version-defined TFM | MATRIX |
| Host-neutral .NET Core | .NET 8 | prove .NET 10 compatibility where valid; cut over only when consumers allow | EVALUATE / UPGRADE |
| .NET tests | xUnit | retain | KEEP |
| CI | GitHub Actions | current supported Action majors + reproducible bootstrap | UPGRADE |
| Dependency automation | manual updates | Dependabot for supported ecosystems, governed by compatibility policy | UPGRADE |
| Real Host acceptance | manual/self-hosted Windows | retain as hardware/Host-specific gate | KEEP |

### 6.1 Python 3.14 is a candidate, not an immediate floor change

As of this design date, Python 3.14 is a maintained stable line. DSP may target it as the future canonical runtime, but the change must follow:

```text
3.11 baseline
    ↓
add 3.14 compatibility lane
    ↓
prove repository parity
    ↓
prove dependency compatibility
    ↓
make 3.14 canonical
    ↓
retire 3.11 only after an explicit retirement gate
```

Technology Modernization does not enable free-threaded Python by default.

### 6.2 .NET targets are Host constrained

DSP does not own the runtime requirements of AutoCAD or Revit.

The invariant is:

> A native Host plugin target framework is selected from the Autodesk-supported runtime for that Host version, not from a repository-wide preference for the newest .NET release.

Therefore a future compatibility matrix may contain different active targets at the same time.

Host-neutral libraries may be tested on newer .NET versions where useful, but native plugin cutovers require Host-specific evidence.

### 6.3 MCP and gRPC remain separate boundary technologies

MCP serves agent/application integration. gRPC/Protobuf serves typed Host transport where the current architecture requires it.

Modernization must not collapse these boundaries merely to reduce the number of protocols.

### 6.4 JSON Schema remains canonical

Pydantic is an implementation/boundary technology, not the canonical cross-language DSP contract.

Schema modernization therefore follows:

```text
canonical JSON Schema
        ↓
jsonschema + referencing
        ↓
Python validation/runtime adapters
```

and not:

```text
Pydantic model
        ↓
becomes canonical DSP contract
```

## 7. Modernization workstreams

Technology Modernization is organized into six responsibility workstreams.

| Workstream | Responsibility |
| --- | --- |
| W1 Runtime | Python/.NET execution baselines and compatibility |
| W2 Dependency | deterministic dependency ownership, resolution, and update policy |
| W3 Build & Package | workspace/package graph, build/bootstrap, code generation |
| W4 Protocol & Schema | MCP/gRPC/Protobuf/JSON Schema tooling modernization without semantic drift |
| W5 Host SDK Compatibility | AutoCAD/Revit version, SDK, TFM, runtime, and real-host validation |
| W6 CI & Toolchain | canonical verification, Action/runtime maintenance, locked bootstrap |

Their logical dependency is:

```text
W1 Runtime
    ↓
W2 Dependency
    ↓
W3 Build & Package
    ↓
 ┌───────────────┐
 ▼               ▼
W4 Protocol     W5 Host SDK
& Schema        Compatibility
 └───────┬───────┘
         ▼
W6 CI & Toolchain
```

W6 begins early as an experimental lane but becomes canonical only after the underlying migrations are proven.

## 8. Universal migration model

Every modernization item uses the same staged migration model unless its risk class requires a stricter one:

```text
introduce
   ↓
dual-run / dual-build where applicable
   ↓
prove parity
   ↓
switch canonical ownership
   ↓
observe stability
   ↓
remove old path
```

The forbidden model is:

```text
upgrade everything
   ↓
fix whatever breaks
```

A compatibility path is not removed in the same step that first introduces its replacement unless equivalence is already independently proven and the risk class permits it.

## 9. Program waves

Technology Modernization is executed through seven ordered waves.

```text
M0 — Modernization Audit
  ↓
M1 — Reproducible Toolchain
  ↓
M2 — Runtime Compatibility
  ↓
M3 — Dependency & Deprecated API Modernization
  ↓
M4 — Protocol / Build / Host SDK Compatibility
  ↓
M5 — Canonical Baseline Cutover
  ↓
M6 — Legacy Baseline Retirement
  ↓
Architecture Modernization Review
```

The waves are sequencing gates, not permission for one giant PR. Implementation plans should split them into independently verifiable tasks and commits.

## 10. Risk classification

Every modernization item is classified before implementation.

| Class | Meaning | Examples | Minimum evidence |
| --- | --- | --- | --- |
| T0 | tooling-only | GitHub Action major, non-runtime build utility | focused structural proof + canonical CI |
| T1 | dependency-compatible | lock refresh, compatible dependency update, resolver implementation migration | unit/contract + repository regression |
| T2 | runtime-compatible | Python 3.14 lane, Host-neutral .NET 10 compatibility, major dependency migration | old/new dual-run + parity |
| T3 | Host-constrained | AutoCAD/Revit SDK/TFM/native runtime | offline + native build + real Host acceptance |
| T4 | semantic/architectural | contract/schema semantics, Saga behavior, Host/provider boundary, compatibility bridge whose removal changes semantics | exits Technology Modernization |

Automatic escalation rule:

```text
if an item requires changing
    public contract
    OR canonical semantics
    OR Host-visible behavior
    OR orchestration semantics
then
    classify T4
    stop Technology Modernization work
    move to Architecture Modernization Review
```

## 11. Evidence package

Each ledger item must retain enough evidence to explain why the old path can be replaced or kept.

```text
before baseline
    ↓
current ownership / dependency
    ↓
risk classification
    ↓
proposed change
    ↓
compatibility evidence
    ↓
repository regression evidence
    ↓
Host evidence when applicable
    ↓
cutover decision
    ↓
retirement evidence when applicable
```

A green CI badge without this relationship is not sufficient evidence for retirement.

## 12. Modernization ledger

M0 creates a living modernization ledger under:

`docs/superpowers/modernization/modernization-ledger.md`

Each entry has:

- ID (`MOD-###`);
- area;
- current implementation/version;
- candidate implementation/version;
- owner;
- dependency/consumer set;
- risk class T0-T4;
- decision;
- status;
- required evidence;
- cutover condition;
- retirement condition;
- final verification references.

Decision values are exactly:

- `KEEP`
- `UPGRADE`
- `REPLACE`
- `REMOVE`
- `DEFER`

Lifecycle status values are exactly:

- `DISCOVERED`
- `ASSESSED`
- `APPROVED`
- `IN_PROGRESS`
- `VERIFIED`
- `DEFERRED`
- `REJECTED`

No approved item may enter M1+ with unknown ownership or unknown risk.

## 13. M0 — Modernization Audit

### 13.1 Purpose

M0 builds the factual inventory required to modernize safely. It is analysis-only with respect to product/runtime behavior.

M0 answers:

```text
what do we use now?
what is supported?
what actually needs to change?
what must stay because a Host or contract constrains it?
```

### 13.2 Audit areas

M0 audits seven areas:

1. **A1 Runtime** — current and candidate Python/.NET/Host runtimes.
2. **A2 Dependency** — Python, NuGet, GitHub Actions, MCP, gRPC, Protobuf and build-tool versions/constraints.
3. **A3 Deprecation** — runtime/library deprecations and warnings.
4. **A4 Build & Packaging** — Python package graph, editable-install ordering, SDK selection, codegen/build inputs.
5. **A5 Protocol & Schema** — JSON Schema, Proto, MCP, generators, validators, resolver ownership.
6. **A6 Host Compatibility** — supported AutoCAD/Revit versions, SDK locations, TFM/runtime requirements, native acceptance.
7. **A7 CI & Toolchain** — Action majors, runner assumptions, Python/.NET matrix, self-hosted requirements, canonical ownership.

### 13.3 M0 artifacts

M0 creates:

```text
docs/superpowers/modernization/
    modernization-ledger.md
    runtime-matrix.md
    dependency-inventory.md
    host-compatibility-matrix.md
    modernization-risk-register.md
```

The documents are factual records, not parallel specifications.

### 13.4 Dependency/ownership graph

M0 records first-party relationships explicitly, including at least:

```text
contracts
   ↓
semantic_runtime
   ↓
semantic_service
   ↓
semantic_mcp

contracts
   ↓
providers
   ↓
materialization / execution layers

contracts/proto
   ↓
Python transport
   ↓
.NET transport
   ↓
Host plugin
```

M0 must distinguish declared package relationships from incidental `PYTHONPATH` or CI install ordering.

### 13.5 Warning baseline

Warnings are captured and classified as:

- `DEPRECATION`
- `RUNTIME`
- `PACKAGING`
- `BUILD`
- `HOST_SDK`
- `CI_ACTION`

A warning is not automatically a defect; each warning gets an owner and decision.

### 13.6 M0 exit gate

M1 may start only when all of the following are true:

1. every relevant runtime has a current and candidate/keep decision;
2. all first-party Python/.NET packages are inventoried;
3. all known deprecations are in the ledger;
4. Host version ↔ SDK ↔ TFM ↔ runtime ownership is explicit;
5. Proto / JSON Schema / MCP tooling ownership is explicit;
6. GitHub Actions and build tooling versions are inventoried;
7. every modernization candidate has T0-T4 classification;
8. every candidate has `KEEP / UPGRADE / REPLACE / REMOVE / DEFER` disposition;
9. T4 items are removed from Technology Modernization execution scope;
10. the starting `main` regression baseline remains green.

Hard gate:

> No M1 implementation begins while an approved modernization item has unknown risk or unknown ownership.

## 14. M1 — Reproducible Toolchain

### 14.1 Purpose

M1 makes the **existing** technology baseline reproducible before changing the baseline.

M1 may change dependency resolution, install/sync mechanics, bootstrap scripts, SDK selection mechanics, and code-generation determinism.

M1 may not change Python minimum version, Host-visible runtime behavior, contract semantics, or supported capability.

### 14.2 Python workspace

DSP adopts a root `uv` workspace if M0 confirms all current first-party Python packages can be represented without changing package identity.

Target structure:

```text
root pyproject.toml
    │
    ├── workspace members
    │      ├── contracts/python
    │      ├── hosts/autocad/sidecar
    │      ├── hosts/revit/sidecar (if package-managed)
    │      ├── platform/* Python packages
    │      └── providers/semantics/*
    │
    └── uv.lock
```

Each member keeps its own `name`, `version`, dependencies, build backend, entry points, and package metadata.

Workspace membership does not merge packages into one distribution.

### 14.3 First-party dependency ownership

A first-party dependency must be expressed through package/workspace metadata where the relationship is real. Canonical CI must not depend on a carefully ordered list of `pip install -e ...` commands to create a hidden dependency graph.

Any package that intentionally is not installable remains explicitly classified rather than being forced into the workspace.

### 14.4 Lock policy

The root `uv.lock` is committed.

Canonical environments consume the committed resolution:

```text
metadata
   ↓
uv lock
   ↓
committed uv.lock
   ↓
CI/developer bootstrap consumes locked graph
```

Dependency-update changes are responsible for updating the lock. Normal verification must not silently drift it.

Use `--locked` or `--frozen` semantics according to whether CI should validate lock freshness or merely consume an already-validated lock. The implementation plan must choose one canonical behavior and test it explicitly.

### 14.5 Python build backend

M1 does not replace setuptools solely because `uv` is introduced. `uv` owns project/workspace environment resolution; package build backend ownership remains separate.

### 14.6 .NET SDK governance

M1 introduces explicit .NET SDK governance, expected to include a repository `global.json` or an equivalent deterministic SDK policy.

It must distinguish:

- SDK used to build/test Host-neutral projects;
- SDK required to compile Host-constrained targets;
- runtime actually loaded by AutoCAD/Revit.

### 14.7 NuGet package governance

`Directory.Packages.props` is not mandatory by ideology.

M0/M1 introduce central package management only when repeated package declarations or observed version drift justify it. Otherwise project-local `PackageReference` remains valid.

### 14.8 Protobuf/code generation

The `.proto` contract remains source-of-truth.

M1 makes generator/runtime versions and generation commands explicit and reproducible.

If generated sources are committed, verification must be able to regenerate and prove no diff. If generated sources are intentionally build-time-only, verification must prove the same source + same toolchain build deterministically enough for repository requirements.

M1 does not change protocol semantics.

### 14.9 Bootstrap entrypoints

Prefer native existing tools over adding another task-runner layer:

```text
uv sync / uv run
pytest
ruff
dotnet build / test
repository scripts only where orchestration is genuinely needed
```

Do not introduce Make, Just, tox, nox, or another runner merely to rename commands.

### 14.10 M1 exit gate

M1 is complete only when:

1. all eligible first-party Python packages have explicit workspace/dependency ownership;
2. one committed `uv.lock` governs the Python workspace;
3. a clean environment can reconstruct the verification environment from declared metadata + lock;
4. canonical tests no longer depend on incidental editable-install ordering;
5. CI consumes the locked graph deterministically;
6. .NET SDK selection is explicit and reproducible;
7. NuGet package-version ownership has no unknowns;
8. Proto/codegen tool versions and ownership are explicit;
9. a clean checkout can reconstruct the verification environment;
10. repository behavior is regression-equivalent to the pre-M1 baseline.

The Python floor remains unchanged during M1.

## 15. M2 — Runtime Compatibility

### 15.1 Purpose

M2 proves new runtime compatibility before any support-floor change.

M2 introduces additional runtime lanes; it does not initially remove existing ones.

### 15.2 Python compatibility lane

The initial candidate matrix is:

```text
Python 3.11 (current canonical)
          │
          ├── same locked dependency graph where markers allow
          ├── same unit/contract suites
          └── same repository regression

Python 3.14 (candidate)
          │
          ├── same declared workspace
          ├── same unit/contract suites
          └── same repository regression
```

Where one universal lock contains platform/Python markers, M2 must prove the graph is intentional for both runtimes rather than assuming identical wheels imply identical support.

Failures are classified as:

- project incompatibility;
- dependency incompatibility;
- changed interpreter semantics;
- test/tool incompatibility;
- unsupported optional platform dependency.

The fix must stay inside Technology Modernization boundaries. Any required semantic change escalates to T4.

### 15.3 Python language/tool settings

`requires-python`, Ruff target version, and canonical CI remain at the old baseline until M5.

New-language syntax or 3.14-only stdlib features must not enter production code while 3.11 remains an active supported lane.

### 15.4 Free-threaded Python

Free-threaded mode is explicitly excluded from M2. It may be evaluated later as a separate performance/runtime experiment with its own concurrency and C-extension evidence.

### 15.5 Host-neutral .NET compatibility

Host-neutral Core/test projects may add .NET 10 build/test compatibility where their consumers and APIs permit it.

The purpose is to determine whether .NET 10 can become a future baseline before .NET 8 support ends, not to force native plugins onto an unsupported Host runtime.

### 15.6 Native Host runtime compatibility

AutoCAD/Revit native projects are not placed in a generic `.NET 8 + .NET 10` matrix unless the corresponding Autodesk Host versions actually support those runtimes.

They follow W5/M4 Host compatibility evidence.

### 15.7 M2 exit gate

M2 completes when:

- Python candidate runtime executes the canonical offline repository suite successfully;
- dependency and build tool compatibility is understood, with no unexplained skips;
- Host-neutral .NET candidate runtime builds/tests successfully where targeted;
- remaining native Host runtime changes are represented in the Host compatibility matrix;
- no product contract or behavior was changed to obtain compatibility.

## 16. M3 — Dependency & Deprecated API Modernization

### 16.1 Purpose

M3 updates implementation dependencies and removes deprecated API debt after environment reproducibility and runtime compatibility exist.

### 16.2 Update policy

Dependency modernization is risk-driven, not "latest at any cost".

Each update is classified by:

- security/support urgency;
- runtime compatibility;
- breaking API surface;
- number of internal consumers;
- Host/runtime coupling;
- ability to characterize behavior before migration.

Patch/minor upgrades may be grouped only when they share a failure domain and remain easy to bisect. Major upgrades should normally be isolated.

### 16.3 `jsonschema.RefResolver` migration

The hygiene-deferred resolver migration becomes a first-class M3 candidate.

Required sequence:

```text
capture current schema/ref behavior
        ↓
add characterization tests
        ↓
introduce referencing.Registry path
        ↓
prove same validation/ref resolution outcomes
        ↓
switch implementation
        ↓
remove deprecated resolver path
```

Canonical schemas do not change as part of this migration.

### 16.4 MCP SDK

DSP already depends on MCP SDK v2. M3 therefore treats MCP primarily as support/refresh work, not a v1→v2 product migration.

M0/M3 must still inventory actual SDK APIs in use and confirm that minor/major refreshes preserve the thin-adapter boundary.

Business/domain logic must not migrate into the MCP transport layer merely because an SDK API makes it convenient.

### 16.5 gRPC and Protobuf

Runtime libraries, generated tooling, and cross-language version compatibility are modernized together with explicit codegen evidence.

M3/M4 may refresh library/tool versions but may not redefine the wire contract under the label of dependency maintenance.

### 16.6 GitHub Actions

Action major upgrades are T0/T1 depending on runtime/setup effects.

M0 records current majors, Node/runtime requirements, and self-hosted runner compatibility. M3 then upgrades one Action family at a time with structural and canonical CI proof.

Current supported majors are candidates, not blindly hard-coded future policy: the repository should follow supported Action lines and compatible runner versions at the time of execution.

### 16.7 Dependabot

Where supported, dependency automation is configured for:

- `uv`;
- NuGet;
- .NET SDK metadata where useful;
- GitHub Actions.

Automation policy must avoid uncontrolled major-version batching. Major updates remain reviewable modernization items rather than automatic acceptance.

### 16.8 M3 exit gate

M3 completes when approved dependency/deprecation items are either:

- `VERIFIED`; or
- explicitly `DEFERRED` with an owner and reason.

No known approved deprecation may remain in an ambiguous state.

## 17. M4 — Protocol, Build and Host SDK Compatibility

### 17.1 Purpose

M4 handles the changes most likely to cross language/runtime boundaries while still preserving DSP semantics.

### 17.2 Protocol tooling

For JSON Schema, MCP, gRPC, and Protobuf, M4 distinguishes:

- protocol/schema source-of-truth;
- runtime library;
- generator/tooling;
- generated artifacts;
- adapters consuming generated/runtime APIs.

Updating one layer must not silently alter another.

### 17.3 Host compatibility matrix

`docs/superpowers/modernization/host-compatibility-matrix.md` is the authority for modernization support decisions and records, per Host version:

- product/version;
- vendor-supported .NET/runtime;
- SDK/API assembly source;
- DSP project TFM;
- build SDK requirement;
- offline Core test applicability;
- native build evidence;
- real Host acceptance evidence;
- support status.

Conceptually:

```text
AutoCAD version
    → Autodesk-supported runtime
    → DSP AutoCAD plugin TFM
    → native build
    → live acceptance

Revit version
    → Autodesk-supported runtime
    → DspRevitTargetFramework
    → native build
    → live acceptance
```

### 17.4 Revit

The existing dynamic `DspRevitTargetFramework` model is preserved unless a later Architecture Modernization Review proves a better boundary.

M4 validates version-specific build inputs rather than replacing the model with one repository-wide TFM.

### 17.5 AutoCAD

AutoCAD plugin TFM remains tied to the supported runtime of the AutoCAD version being targeted. Moving a Host-neutral project to a newer .NET baseline does not automatically move AutoCAD native projects.

### 17.6 Real Host acceptance

T3 changes require real Host evidence before support is declared.

Offline tests may prove contract and orchestration behavior, but they cannot replace Autodesk process/runtime loading evidence.

### 17.7 M4 exit gate

M4 completes when all approved Host/runtime/toolchain targets have explicit build and acceptance evidence and no protocol/schema semantic change has been hidden inside tooling migration.

## 18. M5 — Canonical Baseline Cutover

### 18.1 Purpose

M5 changes what the repository officially treats as its current engineering baseline.

This wave occurs only after M1–M4 evidence exists.

### 18.2 Python cutover

If Python 3.14 parity is proven, M5 may update together as one coordinated baseline change:

- root/member `requires-python` constraints as appropriate;
- Ruff target version;
- canonical CI Python version;
- lock resolution assumptions;
- developer/bootstrap documentation.

The cutover must be atomic enough that the repository never claims a support floor different from what CI actually proves.

### 18.3 .NET cutover

Host-neutral projects may change canonical TFM/SDK only when consumers are compatible.

Native Host projects follow the Host compatibility matrix and may legitimately remain on a different TFM.

### 18.4 CI ownership

Repository regression remains the one repository-wide truth.

During compatibility proving, extra lanes may exist. After cutover, the canonical workflow reflects the approved new baseline while focused historical/domain workflows remain focused.

### 18.5 M5 exit gate

M5 is complete only when:

- documentation, package metadata, lock, lint target, build SDK policy, and CI all describe the same supported baseline;
- canonical repository regression is green on that baseline;
- required Host-specific acceptance is green for Host support claims;
- the old baseline is clearly marked legacy/retirement-candidate rather than silently abandoned.

## 19. M6 — Legacy Baseline Retirement

### 19.1 Purpose

M6 removes compatibility surface that is no longer required after the new baseline has proven stable.

Retirement is evidence-driven, not aesthetic cleanup.

### 19.2 Retirement requirements

An old path can be removed only when the ledger identifies:

- its replacement;
- proof that the replacement owns the same required behavior;
- all known consumers;
- rollback implications;
- required observation window or release evidence;
- final regression/Host evidence.

### 19.3 Examples of possible retirement candidates

Depending on earlier evidence, M6 may retire:

- Python 3.11 compatibility lanes;
- obsolete CI bootstrap/install paths;
- deprecated resolver implementations;
- old Action compatibility assumptions;
- obsolete codegen tooling paths;
- temporary dual-target verification lanes.

Existing `*_v2` or compatibility bridges are **not automatically M6 candidates**. If removing one changes public/runtime semantics or architecture, it is T4 and belongs to Architecture Modernization Review.

### 19.4 M6 exit gate

M6 completes when no retired baseline remains as an undocumented active path and all retained compatibility surface has an explicit reason.

## 20. CI and validation architecture

Modernization preserves the existing ownership principle:

```text
one current repository-wide truth
    + focused domain/historical guards
    + manual/self-hosted real Host acceptance where hardware is required
```

The validation levels are:

### L1 — Import / Build

- Python environment resolves from approved metadata/lock;
- Python packages import on the candidate runtime;
- .NET projects build on intended SDK/TFM;
- generators/tools execute deterministically.

### L2 — Unit / Contract

- unit tests;
- JSON Schema validation/conformance;
- Proto/transport conformance;
- MCP adapter behavior;
- Host-neutral .NET tests.

### L3 — Repository Regression

Canonical repository regression proves existing offline DSP behavior remains intact.

Both pytest import modes remain protected until a separately approved change proves one can be retired without losing coverage or local parity.

### L4 — Real Host Acceptance

Required for T3 support claims involving actual AutoCAD/Revit SDK/runtime loading or native execution.

A modernization item is accepted at the highest level relevant to its risk class.

## 21. Skip and failure policy

Modernization must not create silent success through skips.

For every new runtime/Host lane:

- expected environmental skips are explicit and counted;
- new unexpected skips fail review;
- dependency/runtime incompatibility is reported as incompatibility, not converted into a skip;
- live Host tests remain opt-in where hardware/software is unavailable, but support claims require separate successful live evidence.

## 22. Rollback strategy

Every T2/T3 change must preserve a rollback path until canonical cutover evidence exists.

Rollback is implemented through source control and explicit baseline ownership, not permanent runtime feature flags unless the technology genuinely requires one.

General strategy:

```text
old canonical path remains intact
        ↓
new compatibility lane introduced
        ↓
parity proven
        ↓
canonical switches
        ↓
short stabilization/observation
        ↓
old path retired in M6
```

If a candidate runtime or dependency cannot meet parity without semantic changes, it is not forced through; the ledger records `DEFER` or escalates T4.

## 23. Supply-chain and dependency governance

Modernization should improve supply-chain clarity without introducing an unrelated security platform project.

Required principles:

- lock resolved Python transitive dependencies;
- make NuGet version ownership explicit;
- keep GitHub Actions on supported major lines compatible with runners;
- use Dependabot for supported ecosystems where the generated update model is reviewable;
- keep major upgrades isolated enough to diagnose failures;
- do not auto-merge breaking dependency/runtime changes merely because CI is green;
- record exceptions and intentional pins in the ledger.

## 24. Documentation and lifecycle governance

Modernization creates new current engineering artifacts without rewriting historical bodies.

Rules:

- this Design Spec is `CURRENT` only after review/approval;
- once an implementation plan exists, both design and plan are `CURRENT` during execution;
- completed hygiene design/plan move to `COMPLETED` in the lifecycle index;
- historical Design Specs and Plans remain immutable engineering records;
- v0.6 remains the system-level contract authority;
- the next capability phase remains `NOT YET DEFINED` throughout Technology Modernization unless a separate capability design is approved.

## 25. Architecture Modernization Review handoff

Technology Modernization ends with a review, not an automatic architecture rewrite.

The review may evaluate:

- current V1/V2 compatibility bridges;
- legacy runtime abstractions;
- Host abstraction weight;
- provider boundaries;
- package/module boundaries exposed by the new workspace graph;
- canonical contract evolution candidates;
- transport/runtime simplification opportunities;
- whether any compatibility path is now demonstrably obsolete.

Possible outcomes include:

1. **KEEP architecture** — current architecture remains justified;
2. **targeted architectural amendments** — one or more bounded design specs;
3. **larger architecture modernization program** — only if evidence justifies it.

Technology Modernization evidence may inform this review but does not pre-approve any architecture change.

## 26. Program completion criteria

Technology Modernization is complete when all of the following are true:

1. runtime support decisions are explicit and current;
2. Python dependency resolution is reproducible from committed metadata/lock;
3. .NET SDK and NuGet ownership are explicit;
4. approved deprecated implementation APIs are removed or explicitly deferred;
5. protocol/schema tooling is supported and reproducible without changing canonical semantics;
6. Host version ↔ SDK ↔ TFM ↔ runtime compatibility is explicit;
7. canonical CI uses the approved modernized baseline;
8. repository regression is green on the new canonical baseline;
9. required real AutoCAD/Revit acceptance is green for supported T3 changes;
10. retired legacy baselines have been intentionally removed;
11. retained legacy/compatibility paths have explicit ownership/reason;
12. no Technology Modernization task changed public contract, canonical semantics, Host-visible behavior, or supported capability;
13. all T4 findings have been handed to Architecture Modernization Review rather than implemented implicitly.

The completion definition is **not** "every dependency is latest".

It is:

> DSP runs on a supported, reproducible and maintainable technology baseline, and existing capability semantics are demonstrably preserved.

## 27. Initial M0 candidate ledger seed

The following rows seed M0 discovery. They are not implementation authorization and exact target versions must be verified when M0 executes.

| ID | Area | Current | Candidate direction | Risk | Initial disposition |
| --- | --- | --- | --- | --- | --- |
| MOD-001 | Python runtime | 3.11 canonical | prove Python 3.14 compatibility | T2 | UPGRADE |
| MOD-002 | Python workspace | procedural editable installs | root `uv` workspace | T1 | UPGRADE |
| MOD-003 | Python resolution | no repository-wide lock | committed `uv.lock` | T1 | UPGRADE |
| MOD-004 | Python build backend | setuptools | setuptools | T0 | KEEP |
| MOD-005 | JSON Schema resolver | deprecated resolver path documented by hygiene | `referencing.Registry` after characterization | T1 | UPGRADE |
| MOD-006 | MCP SDK | v2 dependency line | supported v2 line | T1 | KEEP / REFRESH |
| MOD-007 | gRPC/Protobuf | current Python/.NET runtime + tooling versions | supported compatible toolchain | T1/T2 | REFRESH / EVALUATE |
| MOD-008 | GitHub Actions | older canonical Action majors | current supported majors compatible with runners | T0 | UPGRADE |
| MOD-009 | Revit Core | net8.0 | prove net10 compatibility where consumer-safe | T2 | EVALUATE |
| MOD-010 | Revit native plugin | Host-defined TFM input | Host version matrix | T3 | KEEP / MATRIX |
| MOD-011 | AutoCAD native plugin | net8.0-windows for current target | Host version matrix | T3 | KEEP / MATRIX |
| MOD-012 | .NET SDK selection | workflow/project-driven | explicit repository SDK governance | T1/T2 | UPGRADE |
| MOD-013 | NuGet governance | project-local versions | centralize only where duplication/drift justifies it | T1 | EVALUATE |
| MOD-014 | Dependency automation | manual / partial | Dependabot for supported ecosystems | T0/T1 | UPGRADE |
| MOD-015 | Python typing gate | current typing only | evaluate advisory Pyright/mypy value | T0/T1 | EVALUATE |
| MOD-016 | V1/V2 compatibility bridges | active current paths | architecture review only | T4 | DEFER |

## 28. External support facts recorded at design time

These facts justify audit priority but are not permanent version pins:

- Python 3.14.7 was released on 2026-08-05 as the seventh Python 3.14 maintenance release: <https://www.python.org/downloads/release/python-3147/>.
- Microsoft's support policy, updated 2026-09-08, lists .NET 8 support ending 2026-11-10 and .NET 10 LTS support ending 2028-11-14: <https://dotnet.microsoft.com/en-us/platform/support/policy>.
- uv workspaces manage multiple packages with individual `pyproject.toml` files and a shared lockfile: <https://docs.astral.sh/uv/concepts/projects/workspaces/>.
- uv documents `uv.lock` as a committed cross-platform lock for reproducible project environments: <https://docs.astral.sh/uv/concepts/projects/layout/>.
- MCP Python SDK v2 is the current stable release line and supports the 2026-07-28 protocol revision plus earlier revisions: <https://github.com/modelcontextprotocol/python-sdk>.
- Current `actions/setup-python` documentation uses `setup-python@v7` and `checkout@v7`; v6 moved the Action runtime to Node 24 and requires a sufficiently recent runner: <https://github.com/actions/setup-python>.
- GitHub documents Dependabot ecosystem support for `uv`, NuGet, .NET SDK, and GitHub Actions: <https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories>.

M0 must refresh these facts before implementation because supported versions and maintenance status are time-dependent.

## 29. Implementation-planning constraints

After this Design Spec is approved, the implementation plan must:

- start with M0 rather than jumping directly to runtime/package upgrades;
- define small TDD/characterization-driven tasks;
- preserve the `introduce → dual-run → prove parity → switch → retire` model;
- state exact files and verification commands per task;
- separate T0/T1 changes from T2/T3 changes where failure domains differ;
- never mix a T4 architecture change into Technology Modernization;
- preserve the canonical repository-regression ownership model;
- include explicit rollback and cutover checkpoints;
- leave real Host acceptance manual/self-hosted where required rather than replacing it with mocks;
- update the modernization ledger continuously as evidence is produced.

## 30. Review decision

Approval of this Design Spec means approval of the **program architecture and boundaries**, not blanket approval to apply every candidate upgrade in the seed ledger.

M0 remains responsible for validating current facts and converting candidate rows into executable `APPROVED`, `DEFERRED`, or `REJECTED` items. Any finding that crosses into T4 returns to design review before implementation.
