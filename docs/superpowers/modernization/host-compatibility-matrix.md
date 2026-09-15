# DSP Modernization Host Compatibility Matrix

**Record state:** M0 seed; no new Host support claim  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Modernization execution base:** `2edb734c9aa26a32b414a0eff891260831009a97`

This matrix is created in Task 1 only to establish the authority shape required by the Design Spec. M0 Task 2 must replace unknown values with vendor-supported version/runtime/SDK facts. A row cannot become `SUPPORTED` for a T3 change without native build and real Host acceptance evidence.

| Product/version | Vendor-supported runtime | SDK/API assembly source | DSP project TFM | Build SDK requirement | Offline Core evidence | Native build evidence | Real Host acceptance evidence | MOD | Support status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Revit — exact versions TO INVENTORY | TO REFRESH | TO INVENTORY | Host-defined `DspRevitTargetFramework` | TO INVENTORY | TO INVENTORY | NOT VERIFIED | NOT VERIFIED | MOD-010 | DISCOVERED |
| AutoCAD — exact versions TO INVENTORY | TO REFRESH | `AUTOCAD_ACAD_DIR` / exact install source TO INVENTORY | `net8.0-windows` for current target; version matrix TO VERIFY | TO INVENTORY | TO INVENTORY | NOT VERIFIED | NOT VERIFIED | MOD-011 | DISCOVERED |

Rules:

- Host-neutral .NET compatibility does not automatically change native Autodesk TFMs.
- Offline tests cannot substitute for native plugin loading/execution evidence.
- Missing Autodesk software or SDK evidence means `NOT VERIFIED`, never PASS.
- Any required Host-visible behavior change escalates to T4 and exits Technology Modernization.
