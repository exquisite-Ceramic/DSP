# DSP Modernization Ledger

**Record state:** M0 seed; not execution authorization  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Modernization execution base:** `2edb734c9aa26a32b414a0eff891260831009a97`  
**Design authority:** `docs/superpowers/specs/2026-09-13-dsp-modernization-design.md`  
**Implementation plan:** `docs/superpowers/plans/2026-09-13-dsp-modernization.md`

This ledger starts M0 discovery. `Status` follows the Design Spec lifecycle vocabulary; `Execution state` is the implementation-plan authorization state. Every seed row is `DISCOVERED` and `PROPOSED` until M0 evidence assigns ownership, consumers, support facts, rollback requirements, and an executable disposition. `PROPOSED` does not authorize implementation.

Decision values are `KEEP`, `UPGRADE`, `REPLACE`, `REMOVE`, and `DEFER`. Design lifecycle values are `DISCOVERED`, `ASSESSED`, `APPROVED`, `IN_PROGRESS`, `VERIFIED`, `DEFERRED`, and `REJECTED`.

| ID | Area | Current | Candidate | Risk | Decision | Owner | Consumers | Status | Execution state | Evidence | Rollback |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MOD-001 | Python runtime | 3.11 canonical | prove Python 3.14 compatibility | T2 | UPGRADE | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-002 | Python workspace | procedural editable installs | root `uv` workspace | T1 | UPGRADE | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-003 | Python resolution | no repository-wide lock | committed `uv.lock` | T1 | UPGRADE | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-004 | Python build backend | setuptools | keep setuptools | T0 | KEEP | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-005 | JSON Schema resolver | deprecated resolver path documented by hygiene | `referencing.Registry` after characterization | T1 | UPGRADE | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-006 | MCP SDK | v2 dependency line | remain on supported v2 line | T1 | KEEP | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-007 | gRPC/Protobuf | current Python/.NET runtime + tooling versions | refresh to a proven compatible supported toolchain | T1/T2 | UPGRADE | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-008 | GitHub Actions | older canonical Action majors | current supported majors compatible with runners | T0 | UPGRADE | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-009 | Revit Core | net8.0 | prove net10 compatibility where consumer-safe | T2 | UPGRADE | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-010 | Revit native plugin | Host-defined TFM input | preserve Host-defined TFM and build version matrix | T3 | KEEP | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-011 | AutoCAD native plugin | net8.0-windows for current target | preserve Host-defined runtime matrix | T3 | KEEP | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-012 | .NET SDK selection | workflow/project-driven | explicit repository SDK governance | T1/T2 | UPGRADE | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-013 | NuGet governance | project-local versions | centralize only if inventory proves duplication/drift | T1 | KEEP | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-014 | Dependency automation | manual / partial | Dependabot for supported ecosystems | T0/T1 | UPGRADE | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-015 | Python typing gate | current typing only | evaluate advisory Pyright/mypy value separately | T0/T1 | DEFER | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; M0 evidence required | not applicable before execution |
| MOD-016 | V1/V2 compatibility bridges | active current paths | architecture review only | T4 | DEFER | UNASSIGNED (M0 Task 2) | TO INVENTORY | DISCOVERED | PROPOSED | seed only; Architecture Modernization Review required | not executable in Technology Modernization |

M0 Task 2 and Task 3 must replace unknown ownership/evidence with factual records and convert each candidate to `APPROVED`, `DEFERRED`, or `REJECTED` before M1+ work begins. Any item requiring public-contract, canonical-semantic, Host-visible, or orchestration-semantic change is T4 and exits this plan.
