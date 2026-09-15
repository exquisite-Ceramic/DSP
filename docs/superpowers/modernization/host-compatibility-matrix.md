# DSP Modernization Host Compatibility Matrix

**Record state:** M0 Task 2 factual inventory complete; no new DSP Host support claim  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Observed:** 2026-09-15

Vendor runtime compatibility and DSP acceptance are separate facts. A vendor-supported TFM is necessary but not sufficient for DSP to claim a Host version supported; native build and real-Host acceptance remain required by the T3 gate.

## A6 Host Compatibility

| Host surface | Repository fact | Vendor runtime fact | DSP evidence at M0 | M0 status |
| --- | --- | --- | --- | --- |
| AutoCAD 2025 native plugin | `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj` targets `net8.0-windows`; Autodesk refs are confined to Native | Autodesk compatibility table: AutoCAD 2025 → .NET 8.0 | Phase I real-host acceptance exists for the previously supported baseline; M0 adds no new Host-version claim | KEEP current baseline; T3 for any matrix expansion |
| AutoCAD 2026 | same codebase has not been retargeted by M0 | Autodesk: AutoCAD 2026 → .NET 8.0; AutoCAD 2025 SDK also listed compatible | no new-version DSP real-host evidence recorded by M0 | NOT VERIFIED by DSP M0 |
| AutoCAD 2027 | current plugin still `net8.0-windows` | Autodesk: AutoCAD 2027 → .NET 10.0 | no native build / real-host acceptance recorded by M0 | candidate T3 assessment only |
| Revit 2025 native plugin | `hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj` consumes `$(DspRevitTargetFramework)` and Host SDK directory inputs | Autodesk Revit 2025 Developer Guide: Revit API requires .NET 8.0 | M0 does not create a new Revit 2025 support claim | Host-defined TFM; T3 gate applies |
| Revit Core | `hosts/revit/plugin/Revit.AgentHost.Core/Revit.AgentHost.Core.csproj` targets `net8.0` and is covered by canonical CI tests | Host-neutral library; Microsoft .NET support policy applies, but native consumers constrain usable targets | canonical offline Core build/test is existing evidence | current net8 baseline; net10 compatibility is T2 candidate |
| Revit future releases | native project already validates `DspRevitVersion`, `DspRevitTargetFramework`, `DspRevitApiDir`; repository comments anticipate a .NET 10 Host lane | M0 has not established a vendor fact for every future Revit release | no matrix expansion can be inferred from repository comments | exact version must be vendor-verified and real-host accepted before SUPPORTED |

### AutoCAD vendor matrix observed 2026-09-15

Source: Autodesk `About Managed .NET Compatibility`, AutoCAD 2027 help.

| AutoCAD release | Vendor-supported .NET |
| --- | --- |
| 2027 | 10.0 |
| 2026 | 8.0 |
| 2025 | 8.0 |
| 2024 and earlier shown in the table | .NET Framework line, not the current DSP native plugin target |

### Revit vendor evidence observed 2026-09-15

Source: Autodesk Revit 2025 Developer Guide, `Development Requirements`.

- Revit 2025 API requires Microsoft .NET 8.0.
- Native add-ins reference `RevitAPI.dll` and `RevitAPIUI.dll` from the installed Revit program directory.
- This evidence does not automatically establish the runtime for later Revit releases; each supported Host version requires an explicit vendor/runtime row before implementation.

## T3 acceptance rule

A new native Host/runtime combination can be called DSP-supported only after all applicable layers are green:

1. offline/core regression;
2. native plugin build against the exact Host SDK/runtime inputs;
3. contract/transport compatibility;
4. real AutoCAD/Revit acceptance on the target Host version.

M0 records constraints only and does not satisfy this acceptance rule for a new Host version.
