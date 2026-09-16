# DSP Modernization Runtime Matrix

**Record state:** M0 Task 2 factual inventory complete; M2 Tasks 7-8 Python 3.14 and Host-neutral .NET 10 compatibility verified; M5 Task 14 evaluated with no eligible canonical cutover  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Observed:** 2026-09-16

A candidate below is an assessment target only. It is not canonical until the plan's dual-run/cutover gates pass.

## A1 Runtime

| Surface | Frozen baseline | External support fact observed 2026-09-15 | Modernization candidate | M0 interpretation |
| --- | --- | --- | --- | --- |
| Python platform/runtime | root `requires-python = ">=3.11"`; canonical CI = 3.11; Ruff = `py311` | Python 3.14.7 released 2026-08-05 and is the current 3.14 maintenance release | prove 3.14 compatibility beside 3.11 | T2; do not raise floor in M0/M1 |
| .NET repository SDK | `global.json` = 8.0.100, `latestFeature`; canonical CI uses .NET 8.x | .NET 8 LTS is in Maintenance and ends support 2026-11-10; .NET 10 LTS is Active through 2028-11-14 | assess .NET 10 compatibility where consumer-safe | T2; Host constraints override global preference |
| Revit Core | default/canonical `net8.0`; .NET 10 compatibility target is explicit opt-in only | .NET 8 support window above; .NET 10 active | Host-neutral `net10.0` compatibility proven beside default `net8.0`; no canonical/native cutover | T2; compatibility evidence does not broaden native Host support |
| Revit native plugin | `$(DspRevitTargetFramework)` supplied by Host build inputs | Autodesk Revit 2025 API requires .NET 8.0 | preserve Host-defined TFM matrix | T3; vendor + real Host evidence required per supported Revit release |
| AutoCAD native plugin | `net8.0-windows`; project comments/current refs align with AutoCAD 2025 | Autodesk: AutoCAD 2025/2026 use .NET 8; AutoCAD 2027 uses .NET 10 | preserve Host-version runtime matrix | T3; no global .NET 10 rewrite |
| MCP Python SDK | repo declares `mcp>=2,<3` in semantic MCP and AutoCAD sidecar | official MCP Python SDK v2 is current stable line, Python 3.10+ | stay on supported v2 line and lock/audit exact resolution later | T1; no v1→v2 migration exists here |

### Authoritative support evidence

- Python: https://www.python.org/downloads/release/python-3147/ — Python 3.14.7, released 2026-08-05.
- .NET: https://dotnet.microsoft.com/en-us/platform/support/policy — observed 2026-09-15: .NET 10 LTS 10.0.12 Active, EOL 2028-11-14; .NET 8 LTS 8.0.31 Maintenance, EOL 2026-11-10.
- Autodesk AutoCAD: https://help.autodesk.com/cloudhelp/2027/ENU/AutoCAD-Customization/files/GUID-A6C680F2-DE2E-418A-A182-E4884073338A.htm — AutoCAD 2025/2026 .NET 8.0; AutoCAD 2027 .NET 10.0.
- Autodesk Revit 2025 Developer Guide: Autodesk `Development Requirements` states the Revit API requires Microsoft .NET 8.0 and references RevitAPI.dll/RevitAPIUI.dll from the Revit installation.
- MCP Python SDK: https://github.com/modelcontextprotocol/python-sdk — v2 is the current stable release line.

## M2 Task 7 compatibility evidence

- Canonical repository regression run `34987027986` at `b4af4264a35f1d2d799b44d62d5735457a132cd2` expanded the locked Python job into Python 3.11 `canonical` and Python 3.14 `compatibility` lanes while retaining the same committed workspace metadata and `uv.lock`.
- Python 3.11.16 reconstructed the locked workspace and passed both canonical pytest modes with `1475 passed / 17 skipped / 1 warning`; its Ruff baseline gate reported `320 -> 320 / new 0`.
- Python 3.14.7 reconstructed the same committed lock successfully, including the resolved native dependency set, and passed both pytest modes with `1475 passed / 17 skipped / 1 warning`; the Ruff baseline step was skipped by design because 3.14 is not the canonical quality-gate owner.
- Revit Core remained GREEN in the same canonical run.
- Absolute Ruff verifier run `34987662684` at `68a5ee77acd672d766964df5114ddc2a1be736b0` proved the Task 7 workflow/runtime-matrix architecture tests are E/F/I-clean after normalizing the new test's import spacing.
- This evidence proves a non-canonical Python 3.14 compatibility lane only. It does not authorize the later M5 Python-floor/canonical-runtime cutover.

## M2 Task 8 compatibility evidence

- A first implementation made `Revit.AgentHost.Core` and `Revit.AgentHost.Core.Tests` unconditionally target `net8.0;net10.0`; canonical run `34988924018` at `c30d6e1462437da3397cd6df56b20dc86fd335d7` rejected that design because SDK 8.0.425 raised `NETSDK1045` while evaluating the `net10.0` target. The same leakage broke the Revit Core steps in Phase H run `34988924001` and Phase I run `34988923987`.
- The accepted design therefore keeps `net8.0` as the default target set and exposes `net8.0;net10.0` only when `DspEnableNet10Compatibility=true`. The repository `global.json` remains the canonical 8.x selector; the `.NET 10 (Host-neutral compatibility)` job creates and removes an ephemeral `hosts/revit/plugin/global.json` that selects the installed 10.x SDK only inside the Revit plugin subtree.
- Canonical repository regression run `34989313437` at `9edbf7c9b10fb60bb28ddfed80d075622233fb9c` passed Revit Core/Core.Tests on both `net8.0` and opt-in `net10.0`: SDK 8.0.425 produced `54/54` passing tests on net8, and SDK 10.0.401 produced `54/54` passing tests on net10.
- The same run kept both Python lanes green with `1477 passed / 17 skipped / 1 warning` in both pytest modes on Python 3.11.16 and Python 3.14.7; canonical Ruff remained `319 -> 319 / new 0`.
- Phase H run `34989281811` and Phase I run `34989282011` at `8e29fa23ce6495169ccbeb4fa51c4c812880e595` both returned GREEN for their existing Revit Core consumers, proving the opt-in target does not leak into the established .NET 8 workflows.
- Absolute Ruff verifier run `34989606896` at `d491a744c6ee015813176796037b4936ac297696` proved the Task 8 .NET architecture test is E/F/I-clean independently of the baseline-delta mechanism.
- No native Revit or AutoCAD TFM changed. This is Host-neutral Core compatibility evidence only; it does not add an Autodesk Host support row and does not authorize a repository-wide .NET 10 SDK cutover.

## Runtime gate facts

- `>=3.11` remains the public Python floor until an approved canonical cutover; Python 3.14 remains a compatibility lane after Task 14 because MOD-001 is not `VERIFIED`.
- Ruff remains targeted at `py311`, and the Ruff baseline-delta gate remains owned by the Python 3.11 canonical lane.
- Revit Core defaults to `net8.0`; `net10.0` is available only through the explicit `DspEnableNet10Compatibility=true` Host-neutral compatibility gate. The root `global.json` remains on the 8.x policy because MOD-012 is not `VERIFIED`.
- Native AutoCAD/Revit TFMs are Host compatibility facts, not a repo-wide target policy; Task 8 and Task 14 do not change them.
- No prerelease runtime is a modernization baseline; .NET 11 RC is explicitly outside the planned baseline.

## M5 Task 14 canonical cutover decision

M5 evaluates the ledger before changing canonical ownership. Task 14 does **not** promote compatibility evidence into implementation verification on its own: an item must already be `VERIFIED` and approved for cutover before its metadata/SDK/CI baseline can move.

- `MOD-001`: `NO_CUTOVER` — ledger status remains `APPROVED / APPROVED`. Task 7 proves Python 3.14 compatibility, but the ledger explicitly says that evidence is compatibility-only and not an M5 cutover authorization. Canonical Python therefore remains 3.11; root `requires-python` remains `>=3.11`; Ruff remains `py311`; Python 3.14 stays as the compatibility lane.
- `MOD-012`: `NO_CUTOVER` — ledger status remains `APPROVED / APPROVED`. Task 8 proves Host-neutral .NET 10 compatibility, but not repository-wide SDK cutover. Root `global.json` therefore remains `8.0.100` with `latestFeature`; Revit Core remains canonical `net8.0`; the opt-in .NET 10 lane remains compatibility-only.
- Native AutoCAD/Revit targets remain governed by the Task 13 Host matrix and are not candidates for a repository-wide M5 rewrite.

Task 13 final exact-head run `35037786997` at `4adc680a416993643c063de95520f52a6accc925` already kept both Python runtime lanes and both Revit Core runtime lanes GREEN immediately before this M5 decision. Task 14 adds an anti-drift consistency contract so a future branch cannot silently flip any of these canonical owners while MOD-001/MOD-012 remain unverified.

`NO_CUTOVER` is an explicit M5 decision, not a retirement. The old canonical paths stay active; M6 retirement work is not authorized by this result.
