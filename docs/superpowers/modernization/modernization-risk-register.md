# DSP Modernization Risk Register

**Record state:** M0 seed  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Modernization execution base:** `2edb734c9aa26a32b414a0eff891260831009a97`

This register defines the approved Technology Modernization risk boundary. M0 Task 2/3 attaches concrete owners and evidence to individual MOD items; this Task 1 record does not authorize implementation.

| Class | Meaning | Examples | Minimum evidence |
| --- | --- | --- | --- |
| T0 | tooling-only | GitHub Action major, non-runtime build utility | focused structural proof + canonical CI |
| T1 | dependency-compatible | lock refresh, compatible dependency update, resolver implementation migration | unit/contract + repository regression |
| T2 | runtime-compatible | Python 3.14 lane, Host-neutral .NET 10 compatibility, major dependency migration | old/new dual-run + parity |
| T3 | Host-constrained | AutoCAD/Revit SDK/TFM/native runtime | offline + native build + real Host acceptance |
| T4 | semantic/architectural | contract/schema semantics, Saga behavior, Host/provider boundary, compatibility bridge whose removal changes semantics | exits Technology Modernization |

## Hard escalation rule

If an item requires changing the public contract, canonical semantics, Host-visible behavior, or orchestration semantics, it is T4. T4 **cannot be implemented by the Technology Modernization plan**. The item must be recorded as `DEFER`/`DEFERRED` and handed to Architecture Modernization Review before any implementation.

## Decision vocabulary

Only these modernization decisions are valid: `KEEP`, `UPGRADE`, `REPLACE`, `REMOVE`, `DEFER`.

## Lifecycle vocabulary

Only these Design lifecycle states are valid: `DISCOVERED`, `ASSESSED`, `APPROVED`, `IN_PROGRESS`, `VERIFIED`, `DEFERRED`, `REJECTED`.

No M1+ work may start with unknown ownership or unknown risk, and no T4 item may be approved for Technology Modernization execution.
