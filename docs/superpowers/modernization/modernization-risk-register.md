# DSP Modernization Risk Register

**Record state:** Technology Modernization closeout: COMPLETED
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Modernization execution base:** `2edb734c9aa26a32b414a0eff891260831009a97`  
**Decision freeze date:** 2026-09-15

This register defines the Technology Modernization risk boundary. Task 2 attached the factual evidence; Task 3 freezes which findings may proceed inside Technology Modernization and which remain deferred.

| Class | Meaning | Examples | Minimum evidence |
| --- | --- | --- | --- |
| T0 | tooling-only | GitHub Action major, non-runtime build utility | focused structural proof + canonical CI |
| T1 | dependency-compatible | lock refresh, compatible dependency update, resolver implementation migration | unit/contract + repository regression |
| T2 | runtime-compatible | Python 3.14 lane, Host-neutral .NET 10 compatibility, major dependency migration | old/new dual-run + parity |
| T3 | Host-constrained | AutoCAD/Revit SDK/TFM/native runtime | offline + native build + real Host acceptance |
| T4 | semantic/architectural | contract/schema semantics, Saga behavior, Host/provider boundary, compatibility bridge whose removal changes semantics | exits Technology Modernization |

## Hard escalation rule

If an item requires changing the public contract, canonical semantics, Host-visible behavior, orchestration semantics, identity/materialization/Saga semantics, or supported capability, it is T4. T4 **cannot be implemented by the Technology Modernization plan**. It is recorded `DEFER_ARCHITECTURE` with execution state `DEFERRED` and moves to Architecture Modernization Review.

## Task 3 operational disposition vocabulary

The executable M0 ledger uses exactly these disposition values:

- `KEEP` — retain the current technology/behavior because no justified modernization change is required.
- `PIN_LOCK` — retain the technology/API role but make resolution/tooling reproducible.
- `UPGRADE` — move the same technology role to a supported newer baseline after the item's validation gates.
- `MIGRATE` — change an implementation/tooling API while preserving contracts and observable behavior.
- `DEFER_ARCHITECTURE` — the change is semantic/architectural or cannot be proven behavior-neutral inside Technology Modernization.

The merged planning documents retain earlier seed wording in places (`REPLACE`, `REMOVE`, `DEFER`). M0 records that as governance-document vocabulary drift rather than rewriting the approved historical planning body. The Task 3 exit-gate test and this ledger define the operational vocabulary used by subsequent execution. This naming normalization changes no product/runtime/public-contract behavior.

Lifecycle/execution states at the M0 gate are `APPROVED`, `DEFERRED`, or `REJECTED`. `APPROVED` authorizes only the future task and validation scope already defined by the implementation plan; it does not mean the candidate has already been implemented or verified.

## Baseline warning ownership

| Warning class | Observed baseline evidence | Owner | MOD | M0 decision |
| --- | --- | --- | --- | --- |
| DEPRECATION | canonical Python regression reports existing `jsonschema.RefResolver` deprecation warning | Schema tooling | MOD-005 | `MIGRATE / APPROVED`; characterization precedes replacement |
| CI_ACTION | canonical CI reports Node 20 deprecation for `actions/checkout@v4` and `actions/setup-python@v5`, forced onto Node 24 | Build & Release | MOD-008 | `UPGRADE / APPROVED`; migrate to supported Action majors with canonical parity |

Other warning classes retained for M1+ evidence are `RUNTIME`, `PACKAGING`, `BUILD`, and `HOST_SDK`. Absence of an M0 warning row is not proof that later execution cannot produce one.

## Support pressure recorded by M0

- Python 3.14.7 is a maintained candidate; Python 3.11 remains the repository floor and canonical lane until M5 cutover.
- Microsoft reports .NET 8 LTS in Maintenance with EOL 2026-11-10 and .NET 10 LTS Active through 2028-11-14.
- Autodesk runtime requirements are Host-version-specific: AutoCAD 2025/2026 use .NET 8, AutoCAD 2027 uses .NET 10; Revit 2025 API requires .NET 8.
- MCP Python SDK v2 is already the repository's declared major line (`mcp>=2,<3`), so no v1-to-v2 migration is authorized.
- uv's workspace model supports multiple package-local manifests with one shared lockfile; M1 must first prove parity with the current pip/editable path.
- Current GitHub Action releases observed during M0 include `actions/checkout@v7`, `actions/setup-python@v7`, and `actions/setup-dotnet` v6. The current runner is Node-24 capable; Action cutover still requires repository regression proof.
- GitHub documents Dependabot ecosystem support relevant to GitHub Actions, uv, .NET SDK, and NuGet; configuration remains governed by MOD-014.

These are evidence inputs and constraints, not proof that a later migration has succeeded.

## M0 frozen risk outcomes

- T0/T1 reproducibility and tooling items may proceed only through their focused tests plus canonical repository regression.
- T2 runtime items are approved only as compatibility/dual-run work until M5; M0 does not raise the Python floor or globally retarget .NET.
- T3 native Host surfaces remain on their accepted Host-defined baselines. Any support-matrix expansion requires vendor evidence, native build, contract/transport proof, and real Host acceptance.
- MOD-015 static typing remains deferred for this modernization program because no canonical tool/gate is required to achieve the supported/reproducible baseline.
- MOD-016 V1/V2 compatibility bridges are T4 and `DEFER_ARCHITECTURE`; Technology Modernization may not remove or redesign them.

No M1+ task may start with unknown ownership/risk/evidence, and no T4 item may be approved for Technology Modernization execution.

## Task 16 closeout and T4 handoff

Technology Modernization closes with no unclassified execution risk and no T4 implementation. The formal T4 row remains MOD-016 (`DEFER_ARCHITECTURE / DEFERRED`). Its evidence, together with adjacent architecture-boundary observations gathered during modernization, is copied into `architecture-modernization-review-input.md` for a separate Architecture Modernization Review.

That handoff is evidence-only: it preserves facts, constraints, and review directions. It does not authorize architecture implementation, does not name a next capability phase, and does not convert a deferred T4 item into an executable Technology Modernization task.
