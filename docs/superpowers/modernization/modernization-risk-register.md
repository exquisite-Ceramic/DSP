# DSP Modernization Risk Register

**Record state:** M0 Task 2 factual evidence attached; execution decisions remain PROPOSED  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Modernization execution base:** `2edb734c9aa26a32b414a0eff891260831009a97`

This register defines the Technology Modernization risk boundary. Task 2 adds observed warnings/support evidence only; Task 3 freezes executable decisions and normalizes the final decision vocabulary.

| Class | Meaning | Examples | Minimum evidence |
| --- | --- | --- | --- |
| T0 | tooling-only | GitHub Action major, non-runtime build utility | focused structural proof + canonical CI |
| T1 | dependency-compatible | lock refresh, compatible dependency update, resolver implementation migration | unit/contract + repository regression |
| T2 | runtime-compatible | Python 3.14 lane, Host-neutral .NET 10 compatibility, major dependency migration | old/new dual-run + parity |
| T3 | Host-constrained | AutoCAD/Revit SDK/TFM/native runtime | offline + native build + real Host acceptance |
| T4 | semantic/architectural | contract/schema semantics, Saga behavior, Host/provider boundary, compatibility bridge whose removal changes semantics | exits Technology Modernization |

## Hard escalation rule

If an item requires changing the public contract, canonical semantics, Host-visible behavior, or orchestration semantics, it is T4. T4 **cannot be implemented by the Technology Modernization plan**. It must be deferred to Architecture Modernization Review before any implementation.

## Task 2 baseline warning register

| Warning class | Observed baseline evidence | Owner | MOD | Task 2 disposition |
| --- | --- | --- | --- | --- |
| DEPRECATION | canonical Python regression reports existing `jsonschema.RefResolver` deprecation warning | Schema tooling | MOD-005 | FACT RECORDED; migration decision remains PROPOSED |
| CI_ACTION | Task 2 RED CI surfaced runner/runtime deprecation warning(s) while canonical workflow still uses `actions/checkout@v4` / `actions/setup-python@v5` | Build & Release | MOD-008 | FACT RECORDED; Action upgrade remains PROPOSED |

Other warning classes retained for M1+ evidence: `RUNTIME`, `PACKAGING`, `BUILD`, `HOST_SDK`. Absence of a Task 2 row is not proof that future execution cannot produce such a warning.

## Support pressure recorded by M0

- Python 3.14.7 is an available maintained candidate; Python 3.11 remains the repository floor and canonical lane until cutover.
- Microsoft reports .NET 8 LTS in Maintenance with EOL 2026-11-10 and .NET 10 LTS Active through 2028-11-14.
- Autodesk runtime requirements are Host-version-specific: AutoCAD 2025/2026 use .NET 8, AutoCAD 2027 uses .NET 10; Revit 2025 API requires .NET 8.
- MCP Python SDK v2 is already the repository's declared major line (`mcp>=2,<3`).
- uv's official workspace model supports multiple package-local manifests with one shared lockfile.
- GitHub documents Dependabot ecosystem support for GitHub Actions, uv, .NET SDK and NuGet.

These are evidence inputs, not execution authorization.

## Decision vocabulary at Task 2

The Task 1 seed vocabulary (`KEEP`, `UPGRADE`, `REPLACE`, `REMOVE`, `DEFER`) is preserved until Task 3 deliberately normalizes it to the frozen Design Spec disposition taxonomy. Task 2 must not silently turn factual inventory into a governance decision.

## Lifecycle vocabulary

Design lifecycle states remain `DISCOVERED`, `ASSESSED`, `APPROVED`, `IN_PROGRESS`, `VERIFIED`, `DEFERRED`, and `REJECTED`. Implementation-plan execution authorization is separate and is frozen in Task 3.

No M1+ work may start with unknown ownership/risk/evidence, and no T4 item may be approved for Technology Modernization execution.
