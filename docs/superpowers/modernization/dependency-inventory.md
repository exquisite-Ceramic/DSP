# DSP Modernization Dependency Inventory

**Record state:** M0 seed; exhaustive inventory deferred to Task 2  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Modernization execution base:** `2edb734c9aa26a32b414a0eff891260831009a97`

This file is the seed for M0 dependency/build ownership discovery. It does not yet claim exhaustive manifest or consumer coverage. M0 Task 2 must enumerate every first-party Python manifest, .NET project, workflow, protocol/schema tool, and relevant dependency owner before M1 begins.

| Ecosystem / area | Current ownership shape | Candidate direction | MOD | Audit state |
| --- | --- | --- | --- | --- |
| Python workspace | procedural editable-install ordering plus package-local metadata | explicit root `uv` workspace if inventory proves package identity can be preserved | MOD-002 | DISCOVERED |
| Python resolution | no repository-wide committed lock | one committed root `uv.lock` | MOD-003 | DISCOVERED |
| Python build backend | setuptools package-local backends | retain setuptools absent a concrete blocker | MOD-004 | DISCOVERED |
| JSON Schema resolution | deprecated `jsonschema.RefResolver` path exists | characterize then move implementation to `referencing.Registry` | MOD-005 | DISCOVERED |
| MCP SDK | v2 dependency line | remain on a supported v2 line | MOD-006 | DISCOVERED |
| gRPC / Protobuf | Python and .NET runtime/tooling ownership is distributed | refresh only as one proven compatible toolchain | MOD-007 | DISCOVERED |
| GitHub Actions | workflow-local Action majors | move approved families to supported majors compatible with runners | MOD-008 | DISCOVERED |
| .NET SDK | workflow/project-driven selection | explicit repository SDK governance | MOD-012 | DISCOVERED |
| NuGet | project-local package versions | centralize only if Task 2 proves duplication or drift | MOD-013 | DISCOVERED |
| Dependency automation | manual / partial | bounded Dependabot coverage for approved ecosystems | MOD-014 | DISCOVERED |

## Task 2 inventory contract

Task 2 must replace this seed with exact paths and ownership facts. At minimum it will distinguish declared first-party dependencies from relationships that work only because root `PYTHONPATH`, editable-install ordering, or CI bootstrap order happens to expose packages.

Known roots to verify, not a declaration of completeness:

- `pyproject.toml`
- `contracts/python/pyproject.toml`
- `hosts/autocad/sidecar/pyproject.toml`
- `hosts/revit/sidecar/pyproject.toml`
- `global.json`
- `contracts/proto/host_transport_v1.proto`
- `.github/workflows/`

No dependency or tool version change is authorized by this Task 1 seed.
