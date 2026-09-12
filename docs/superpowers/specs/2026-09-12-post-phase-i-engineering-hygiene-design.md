# Post-Phase-I Engineering Hygiene and Stabilization Design

**Status:** CURRENT
**Design baseline:** `main@d2d1621b30f87506c62adb2d12f73d387821ef78`
**Date:** 2026-09-12
**Scope:** repository hygiene and stabilization only; no product capability expansion

## 1. Purpose

Phase I real cross-host materialization saga is complete. Before defining the next capability phase, the repository needs a short engineering-hygiene stage that removes avoidable development noise and establishes a trustworthy clean-main baseline.

This stage is intentionally not a new product phase. It does not add business capability, change canonical semantics, redesign architecture, or change Host runtime behavior. Its purpose is to make the current implementation easier to validate, maintain, and extend without altering what the system does.

The desired end state is:

```text
main@d2d1621
   ↓
repo-wide hygiene audit
   ↓
hygiene findings ledger
   ├─ REMOVE
   ├─ FIX
   ├─ CONSOLIDATE
   ├─ DOCUMENT
   └─ DEFER
   ↓
freeze cleanup scope
   ↓
small-batch cleanup
   ↓
full regression + Host build + architecture guards
   ↓
new clean-main baseline
   ↓
next-stage Design Spec
```

## 2. Non-negotiable invariants

The hygiene stage is governed by strict zero-product-behavior-change rules.

1. **No public contract change.** No schema, canonical action, approval, execution, verification, provider, MCP, or Host-facing public contract may change.
2. **No runtime semantic change.** Canonical interpretation, eligibility, planning, approval, materialization, coordination, reconciliation, or verification semantics must remain unchanged.
3. **No Host behavior change.** AutoCAD and Revit execution/readback behavior must not be broadened, narrowed, reordered, or redefined.
4. **No new product capability.** Hygiene may make existing behavior easier to test or maintain, but may not introduce a new supported operation or workflow.
5. **No architecture redesign disguised as cleanup.** Any finding that requires a new architectural boundary or a change to an existing one is `DEFER`.
6. **No evidence-free deletion.** Absence of a static reference is not enough to prove dead code in a plugin/provider/Host system. Dynamic registration, reflection, manifests, MCP tool registration, configuration discovery, add-in entrypoints, CI scripts, and runtime loading must be considered.
7. **Historical engineering records remain historical records.** Existing Design Specs and Implementation Plans are not rewritten to make them appear as if they were authored under current knowledge.

If a candidate change cannot be proven behavior-neutral, it is not implemented in this stage.

## 3. Historical document policy

Historical Design Specs, Implementation Plans, and execution evidence are treated as engineering records.

Their technical body is frozen. Hygiene may add or repair lifecycle metadata, indexes, navigation, or broken references, but may not rewrite the body to erase design evolution or retroactively align an old document with the current architecture.

The lifecycle vocabulary is:

| Status | Meaning |
|---|---|
| `CURRENT` | The document is part of the currently effective design/contract view. |
| `COMPLETED` | The stage or plan was executed and is retained as a historical record. |
| `SUPERSEDED` | A later design replaced the document as the current authority. |
| `ABANDONED` | The work was explicitly not executed or was intentionally discontinued. |

Documentation cleanup may fix broken links, incorrect file references, stale README statements, duplicate indexes, or temporary evidence documents. It must not rewrite historical technical conclusions.

## 4. Audit scope

The repo-wide audit covers five categories.

### 4.1 Code hygiene

Audit for proven dead code, obsolete compatibility shims, unused APIs, duplicate helpers, stale temporary abstractions, and stale `TODO`/`FIXME` markers.

A code item is removable only when current-main evidence shows that it is not used by normal calls, dynamic discovery, registration, reflection, manifests, scripts, tests that represent supported behavior, or Host/plugin loading paths.

### 4.2 Test hygiene

Audit skipped tests, duplicated tests, test-directory drift, hidden import coupling, reusable helpers living in test modules or `conftest.py`, live-host gates, and flaky-environment risks.

Expected hardware-gated skips are allowed. Accidental skips caused by a broken environment or broken collection are not.

### 4.3 Documentation hygiene

Audit README status, spec/plan lifecycle visibility, phase completion statements, stale “next step” text, design-history navigation, broken references, and temporary evidence artifacts.

### 4.4 Build and CI hygiene

Audit warnings, duplicated repository-wide regressions, stale workflow snapshots, broken scripts, dependency/tooling drift, architecture-guard coverage, and runner/action maintenance warnings.

### 4.5 Repository hygiene

Audit committed temporary files, generated artifacts that should not be tracked, obsolete naming/directory leftovers, and source-tree metadata noise.

Remote branch deletion is explicitly outside this source-tree hygiene scope because it is repository administration and destructive state management.

## 5. Findings taxonomy and evidence standard

Every audit finding must be recorded in a findings ledger and classified as one of the following.

### `REMOVE`

Use only when the item is proven unreachable or obsolete on the current baseline.

Required evidence includes, as applicable:

- no static consumers;
- no dynamic registration or reflection path;
- no manifest/config/add-in entrypoint dependency;
- no CI/script/runtime loading dependency;
- no supported test dependency;
- relevant regression evidence before and after removal.

### `FIX`

Use for a defect in engineering infrastructure, tests, docs, or tooling that can be corrected without changing product semantics.

Examples include broken test imports, stale textual assertions, incorrect README lifecycle statements, or a workflow that accidentally runs a current repository-wide gate from a historical stage workflow.

### `CONSOLIDATE`

Use when duplicate infrastructure can be merged without changing its externally observable semantics.

Consolidation must preserve focused architecture/domain guards and must not reduce test coverage merely to make CI green.

### `DOCUMENT`

Use for current-truth documentation, lifecycle metadata, navigation, indexing, and runbook/reference repairs.

Historical technical bodies remain unchanged.

### `DEFER`

Use whenever:

- product/runtime behavior would change;
- a public contract would change;
- Host semantics would change;
- architecture would change;
- evidence of behavior neutrality is insufficient.

`DEFER` is the correct result for an uncertain finding. Hygiene is not allowed to turn uncertainty into an implementation experiment.

## 6. Known baseline hygiene findings

The following are already confirmed on the `d2d1621` baseline and therefore seed the findings ledger.

### 6.1 P0: pytest import isolation defects

Repository-wide `pytest --import-mode=importlib` exposes test-import coupling that focused tests do not reveal.

Observed patterns include tests importing sibling test modules with bare imports and tests importing reusable symbols directly from `conftest.py`. These patterns make collection dependent on incidental `sys.path` and test-directory ordering.

The long-term test rule is:

```text
Forbidden:
  test A -> import test B
  test -> import conftest as a reusable API
  bare sibling-test import

Allowed:
  test -> tests.<domain>._support
  test -> production public API
  pytest -> conftest fixtures/hooks
```

Reusable builders, fixtures-as-functions, case factories, and other shared test helpers should live in explicit support modules such as `tests/<domain>/_support.py` and be imported with package-qualified paths.

This is a test-organization change only; production code is not modified to solve test isolation.

### 6.2 P0: stale Phase I discovery-script assertion

A repository-wide regression currently reaches hundreds of passing tests and then fails because `tests/integration/test_phase_i_environment_discovery_script.py` still asserts that the discovery script source must contain `Get-FileHash`.

The final Phase I responsibility boundary separates environment discovery from fixture-integrity verification. SHA-256 validation belongs to explicit acceptance preflight/live-harness integrity checks rather than being reintroduced into the discovery script solely to satisfy a stale textual assertion.

The frozen responsibility split is:

```text
Environment discovery
    -> discover / emit environment configuration

Fixture integrity preflight
    -> SHA-256 verification

Live harness
    -> fail-closed integrity check before mutation
```

Implementation must update the stale test contract to the final responsibility boundary, not change runtime/acceptance behavior to satisfy an obsolete assertion.

### 6.3 P1: test/tooling warning cleanup

Current regression output includes a `jsonschema.RefResolver` deprecation warning. It may be cleaned only if the replacement validation path is proven contract-equivalent. Otherwise it is recorded as `DEFER`.

### 6.4 P1: GitHub Actions runtime maintenance warning

Current GitHub-hosted runs report an Action runtime/Node compatibility deprecation warning. Action-version maintenance is allowed only as a separately verified CI infrastructure change and must not be mixed with P0 fixes merely to make the dashboard appear cleaner.

### 6.5 P1: inconsistent AutoCAD live-test connection helpers

Some AutoCAD live tests use the repository’s pipe-discovery/override helper while others instantiate the Host adapter through its default connection path. This is a test-harness consistency candidate.

Any consolidation must characterize current behavior first and must not change production HostAdapter defaults.

## 7. Canonical repository regression

The hygiene stage introduces one current, neutral repository-wide CI authority. The recommended workflow name is:

```text
.github/workflows/repository-regression.yml
```

The name must not contain a historical Step number, Phase name, or “hygiene” because it represents the continuing definition of repository health.

Its responsibilities are:

```text
repository-regression
│
├── Python repository isolation
│   └── pytest --import-mode=importlib
│
├── architecture / contract baseline
│
├── static hygiene
│   └── Ruff E/F/I
│
├── Revit Core regression
│   └── Revit-free .NET tests
│
└── offline Host/integration regression
```

For the cleanup exit evidence, two pytest modes are required:

```text
Canonical isolation gate:
  python -m pytest --import-mode=importlib -q

Local parity gate:
  python -m pytest -q
```

The importlib gate is the canonical CI isolation gate because it exposes hidden path/module coupling. The normal gate remains required during this cleanup to prove that isolation fixes did not break ordinary local execution.

Long-term CI may later rationalize duplication, but this hygiene stage must prove both modes green before declaring the new baseline clean.

## 8. Historical workflow responsibility

Historical Step workflows remain valuable as focused domain and architecture guards. They must not continue to carry accidental snapshots of the whole repository as it existed when that Step was implemented.

The target model is:

```text
Historical Step workflow
    = focused domain regression
    + architecture/invariant guards

Current repository workflow
    = repository-wide regression truth
```

A historical workflow may lose a broad repository-regression tail only after the new canonical workflow proves coverage equal to or greater than the valid broad-gate coverage being removed.

CI must not become green by deleting coverage.

## 9. CI migration order

The migration order is a hard safety constraint:

```text
main@d2d1621
   │
   ├─ 1. fix test import isolation
   ├─ 2. fix stale test contract(s)
   │
   ▼
existing broad suites execute correctly
   │
   ├─ 3. add repository-regression.yml
   │
   ▼
current repo-wide gate is GREEN
   │
   ├─ 4. prove coverage >= valid union of historical broad gates
   ├─ 5. remove broad tails from historical workflows
   │       └─ keep focused guards
   ├─ 6. complete P1 test/tooling hygiene
   ├─ 7. update README + lifecycle index
   │
   ▼
clean baseline
```

The new repository regression must be green before historical broad tails are removed.

## 10. Edit boundary

Normal hygiene implementation is limited to engineering-infrastructure and documentation surfaces.

| Area | Permission in this stage |
|---|---|
| `.github/workflows/**` | `FIX` / `CONSOLIDATE` |
| `tests/**` | `FIX` / test-support restructure |
| `contracts/python/tests/**` | test-only hygiene |
| `README.md` | `DOCUMENT` |
| `docs/superpowers/README.md` | lifecycle/index documentation |
| `pyproject.toml` | only test/tooling configuration needed for the approved hygiene scope; no runtime dependency semantic change |
| historical `docs/superpowers/specs/*.md` bodies | frozen |
| historical `docs/superpowers/plans/*.md` bodies | frozen |
| `platform/**/src/**` | prohibited by default |
| Host/plugin production runtime | prohibited by default |
| provider production runtime | prohibited by default |
| contracts/schema | prohibited |

If a finding requires modifying a prohibited production area to make the cleanup work, it becomes `DEFER` unless a purely non-semantic change can be independently proven and explicitly added to the frozen cleanup scope before implementation.

## 11. Execution strategy

This stage is findings-first, then small-batch cleanup. It is not a big-bang cleanup PR and not “clean as we discover.”

The preferred implementation grouping is:

1. create/freeze findings ledger from current-main evidence;
2. repair P0 test-collection and stale-test-contract defects;
3. establish canonical repository regression;
4. consolidate historical CI only after coverage proof;
5. perform low-risk P1 test/tooling cleanup;
6. update README and lifecycle navigation;
7. run final repo-wide verification and establish the clean baseline.

Each cleanup batch must be independently reviewable and must carry its own evidence that product behavior did not change.

## 12. Verification and exit criteria

The hygiene stage is complete only when all applicable gates below pass.

### Python

- `python -m pytest --import-mode=importlib -q` passes.
- `python -m pytest -q` passes.
- no new non-intentional skips are introduced.
- hardware-gated live tests remain explicit opt-in gates rather than fake passes.

### CI

- `repository-regression` is green.
- Phase I offline gate remains green.
- every modified historical focused workflow is green.
- main no longer fails because a historical workflow carries a stale broad-regression snapshot.

### .NET / Hosts

- Revit AgentHost Core tests pass.
- if no live harness or Host execution path is touched, a new real dual-Host acceptance run is not required solely for documentation/test-import cleanup.
- if a live harness or Host execution path is touched, the applicable real Host acceptance gate must be rerun.

### Static hygiene

- Ruff E/F/I introduces no new diagnostics and the approved baseline is clean for the enforced scope.
- `git diff --check` passes.

### Documentation

- README states the current completed Phase I status accurately.
- current/superseded/completed design lineage is navigable through lifecycle metadata/indexing.
- the next product capability phase is explicitly not yet defined.
- historical Design Spec and Plan technical bodies are not rewritten by hygiene.

### Architecture and behavior

- public contracts are unchanged.
- canonical semantics are unchanged.
- Host behavior is unchanged.
- runtime behavior is unchanged.
- no new product capability is introduced.

Warning count alone is not an exit gate. A warning is fixed only when doing so is demonstrably safer than deferring it.

## 13. Success condition

The stage succeeds when `main` becomes a trustworthy development baseline rather than merely a visually cleaner repository.

The resulting repository must have:

- one current repository-wide regression authority;
- focused historical domain/architecture guards without stale broad tails;
- deterministic pytest import isolation;
- accurate lifecycle/navigation documentation;
- explicit evidence for every removal or consolidation;
- no product semantic change;
- a clean boundary from which the next capability Design Spec can be started.

Only after this design is implemented and the clean-main baseline is established should the project begin the next capability-phase design. That future phase is intentionally not named or specified by this document.
