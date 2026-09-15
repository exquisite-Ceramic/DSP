# DSP Modernization Runtime Matrix

**Record state:** M0 Task 2 factual inventory complete; M2 Task 7 Python 3.14 compatibility lane verified  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Observed:** 2026-09-15

A candidate below is an assessment target only. It is not canonical until the plan's dual-run/cutover gates pass.

## A1 Runtime

| Surface | Frozen baseline | External support fact observed 2026-09-15 | Modernization candidate | M0 interpretation |
| --- | --- | --- | --- | --- |
| Python platform/runtime | root `requires-python = ">=3.11"`; canonical CI = 3.11; Ruff = `py311` | Python 3.14.7 released 2026-08-05 and is the current 3.14 maintenance release | prove 3.14 compatibility beside 3.11 | T2; do not raise floor in M0/M1 |
| .NET repository SDK | `global.json` = 8.0.100, `latestFeature`; canonical CI uses .NET 8.x | .NET 8 LTS is in Maintenance and ends support 2026-11-10; .NET 10 LTS is Active through 2028-11-14 | assess .NET 10 compatibility where consumer-safe | T2; Host constraints override global preference |
| Revit Core | `net8.0` | .NET 8 support window above; .NET 10 active | prove `net10.0` compatibility where no Host consumer is broken | T2; no TFM change in M0 |
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

## Runtime gate facts

- `>=3.11` remains the public Python floor until M5 cutover; Python 3.14 is first a compatibility lane.
- Ruff remains targeted at `py311`, and the Ruff baseline-delta gate remains owned by the Python 3.11 canonical lane.
- `net8.0` remains Revit Core's current target until compatibility proof; M0 does not retarget it.
- Native AutoCAD/Revit TFMs are Host compatibility facts, not a repo-wide target policy.
- No prerelease runtime is a modernization baseline; .NET 11 RC is explicitly outside the planned baseline.
