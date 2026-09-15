# DSP Modernization Runtime Matrix

**Record state:** M0 seed; support facts not yet refreshed  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Modernization execution base:** `2edb734c9aa26a32b414a0eff891260831009a97`

This record is intentionally incomplete until M0 Task 2 refreshes authoritative support facts. Candidate versions below come from the approved Design Spec and are not canonical support claims.

| Runtime area | Current baseline | Candidate/keep direction | MOD | Audit state | Support evidence |
| --- | --- | --- | --- | --- | --- |
| Python | 3.11 canonical | prove Python 3.14 compatibility before any floor change | MOD-001 | DISCOVERED | TO REFRESH IN M0 TASK 2 |
| Revit Host-neutral Core | `net8.0` | prove .NET 10 compatibility where consumer-safe | MOD-009 | DISCOVERED | TO REFRESH IN M0 TASK 2 |
| Revit native plugin | Host-defined `DspRevitTargetFramework` input | preserve Host-defined TFM/runtime matrix | MOD-010 | DISCOVERED | TO REFRESH IN M0 TASK 2 |
| AutoCAD native plugin | `net8.0-windows` for current target | preserve Host-defined runtime matrix | MOD-011 | DISCOVERED | TO REFRESH IN M0 TASK 2 |
| .NET SDK selection | workflow/project-driven | explicit repository SDK governance | MOD-012 | DISCOVERED | TO REFRESH IN M0 TASK 2 |

No candidate becomes canonical from this seed. Python 3.11 remains canonical through M1-M4 unless the approved plan's later cutover gate is satisfied. Native Autodesk runtimes remain constrained by the Host compatibility matrix and real-Host evidence.
