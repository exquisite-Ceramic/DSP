# DSP Modernization Host Compatibility Matrix

**Record state:** M4 Task 13 executable Host support rows frozen for the already-proven AutoCAD 2025 and Revit 2027 baselines; no new Host-version support claim  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Observed:** 2026-09-16

Vendor runtime compatibility and DSP acceptance are separate facts. A vendor-supported runtime/TFM is necessary but not sufficient for DSP to call a Host version supported; native build and real-Host acceptance remain required by the T3 gate. Task 13 does not broaden the Host matrix: it turns already-existing acceptance evidence into explicit support rows and leaves unproven versions `NOT VERIFIED`.

## A6 Host Compatibility

| Host surface | Repository fact | Vendor runtime fact | DSP evidence at M0 | M0 status |
| --- | --- | --- | --- | --- |
| AutoCAD 2025 native plugin | `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj` targets `net8.0-windows`; Autodesk refs are confined to Native | Autodesk compatibility/system requirements: AutoCAD 2025 runs on .NET 8 | Phase I real-host acceptance exists for the previously supported baseline; M0 adds no new Host-version claim | KEEP current baseline; T3 for any matrix expansion |
| AutoCAD 2026 | same codebase has not been retargeted by M0 | Autodesk: AutoCAD 2026 runs on .NET 8 | no new-version DSP real-host evidence recorded by M0 | NOT VERIFIED by DSP M0 |
| AutoCAD 2027 | current plugin still `net8.0-windows` | Autodesk: AutoCAD 2027 uses .NET 10 | no native build / real-host acceptance recorded by M0 | candidate T3 assessment only |
| Revit 2025 native plugin | `hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj` consumes `$(DspRevitTargetFramework)` and Host SDK directory inputs | Autodesk Revit 2025 Developer Guide: Revit API requires .NET 8 | M0 does not create a new Revit 2025 support claim | Host-defined TFM; T3 gate applies |
| Revit Core | `hosts/revit/plugin/Revit.AgentHost.Core/Revit.AgentHost.Core.csproj` defaults to `net8.0` and has an opt-in `net10.0` compatibility target | Host-neutral library; Microsoft .NET support policy applies, but native consumers constrain usable targets | canonical offline Core build/test is existing evidence | current net8 baseline plus verified net10 Host-neutral compatibility |
| Revit 2027 native plugin | native project keeps Host-owned version/TFM/API-dir inputs | Autodesk Revit 2027 uses .NET 10; add-in guidance requires a .NET 10 SDK | Phase H and Phase I later produced native-build and real-host evidence after the M0 inventory | eligible for explicit Task 13 support row without changing the native project |

## Executable DSP support rows

`SUPPORTED` below means the exact Host/runtime combination already has both native-build and real-Host acceptance evidence. It does not imply support for adjacent product versions. Historical T3 evidence is reusable here because Technology Modernization has not changed either native plugin project since the post-Phase-I baseline; the modernization diff changes Host-neutral/tooling/workflow surfaces only. Any later native/Host-visible source change invalidates that reuse and requires fresh acceptance.

| Host surface | Product / version | Vendor runtime | SDK / API assembly source | DSP TFM | Build SDK | Offline / Core evidence | Native build evidence | Real Host acceptance evidence | Support status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AutoCAD native plugin | AutoCAD 2025 | .NET 8 | AutoCAD 2025 installation/SDK via `$(AUTOCAD_ACAD_DIR)` resolving `AcCoreMgd.dll`, `AcDbMgd.dll`, `AcMgd.dll` | `net8.0-windows` | .NET SDK 8.x; repository selector remains `global.json` 8.0.100 with `latestFeature` | Task 12 final Repository regression `35035207258` at `ef83246bef7e399174197f98da8edd468ac85efa`; Task 12 focused transport `14/14` .NET gRPC | `docs/runbooks/autocad-grpc-smoke.md`: AutoCAD 2025 SDK build PASS before live gates; latest AutoCAD-specific Gate 11/12 commit `157c54d88fc401ede20944c5d477dbb3e0d95bf6`; no build errors | `docs/runbooks/autocad-grpc-smoke.md`: all 12 AutoCAD 2025 real-host gates PASS; Phase I PR #30 head `502fac1a2ea174f716e30e16b4b8ca5b4e061879` records real positive dual-Host and partial-commit gates PASS | SUPPORTED |
| Revit native plugin | Revit 2027 | .NET 10 | installed Revit 2027 `RevitAPI.dll` and `RevitAPIUI.dll` via `$(DspRevitApiDir)` | `net10.0-windows` | .NET SDK 10; Autodesk add-in guidance names SDK `10.0.100` | Task 12 final Repository regression `35035207258` at `ef83246bef7e399174197f98da8edd468ac85efa`; Revit Core net8/net10 jobs GREEN | `docs/runbooks/revit-wall-thickness-gap-closure.md`: head `c8b652f61d9b0aebc1c8d4c5938679b5855c71c3`, Revit 2027 build `20260716_1515(x64)` / file `27.2.0.39`, native build PASS with 0 errors | same Phase H runbook: real Revit 2027 live pytest PASS with 300 mm mutation, stable precommit failures, replay and reconciliation; Phase I PR #30 head `502fac1a2ea174f716e30e16b4b8ca5b4e061879` records real positive dual-Host and partial-commit gates PASS | SUPPORTED |
| AutoCAD native plugin | AutoCAD 2026 | .NET 8 | AutoCAD 2026 installation/SDK required for a claim | Host-defined; not claimed by Task 13 | matching .NET 8 build SDK required | candidate only | NOT VERIFIED | NOT VERIFIED | NOT VERIFIED |
| AutoCAD native plugin | AutoCAD 2027 | .NET 10 | AutoCAD 2027 installation/SDK required for a claim | current plugin remains `net8.0-windows`; no Task 13 retarget | matching .NET 10 build SDK required | candidate only | NOT VERIFIED | NOT VERIFIED | NOT VERIFIED |
| Revit native plugin | Revit 2025 | .NET 8 | installed Revit 2025 API assemblies required for a claim | Host-defined; no Task 13 support claim | matching .NET 8 build SDK required | candidate only | NOT VERIFIED | NOT VERIFIED | NOT VERIFIED |

### AutoCAD vendor matrix refreshed 2026-09-16

Authoritative Autodesk evidence:

- `System requirements for AutoCAD 2025 including Specialized Toolsets` states AutoCAD 2025 uses .NET 8.
- Autodesk technical support for AutoCAD 2025/2026 states both releases run on .NET 8.
- The Autodesk Managed .NET compatibility guidance remains the authority for any future AutoCAD SDK/runtime row; a vendor-compatible row is still not a DSP support claim without native build and live acceptance.

| AutoCAD release | Vendor runtime used by Task 13 classification |
| --- | --- |
| 2025 | .NET 8 |
| 2026 | .NET 8 |
| 2027 | .NET 10; candidate only until separately built and accepted by DSP |

### Revit vendor evidence refreshed 2026-09-16

Authoritative Autodesk Revit 2027 evidence:

- `System requirements for Revit 2027 products` lists `.NET Platform` as `.NET 10`.
- `Migrating Revit to .NET 10` states Revit 2027 uses the final .NET 10 runtime for Revit and add-ins and instructs add-in developers to install SDK `10.0.100`.
- `Major changes and renovations to the Revit API` likewise identifies the .NET 10 migration and requires a .NET 10 SDK to build fully aligned add-ins.

These facts classify the already-executed Revit 2027 evidence; they do not infer support for another Revit release.

## T3 acceptance rule

A native Host/runtime combination can be called DSP-supported only after all applicable layers are green:

1. offline/core regression;
2. native plugin build against the exact Host SDK/runtime inputs;
3. contract/transport compatibility;
4. real AutoCAD/Revit acceptance on the exact target Host version.

For a `KEEP` baseline, Task 13 may reuse earlier fresh real-Host evidence only when the native project/Host-visible implementation has not changed since that evidence. If a later change touches the affected native or Host-visible path, the corresponding `SUPPORTED` row returns to `NOT VERIFIED` until the real Host gate is rerun.

## Task 13 scope decision

Task 13 makes no native project, TFM, proto, transport, or Host-visible behavior change. AutoCAD 2025 and Revit 2027 are explicit because the repository already contains real acceptance evidence for those exact combinations. AutoCAD 2026, AutoCAD 2027, Revit 2025, and any other release remain outside the supported matrix until their own T3 evidence exists.
