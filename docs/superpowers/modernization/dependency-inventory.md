# DSP Modernization Dependency Inventory

**Record state:** M0 Task 2 factual inventory complete; M1 Task 6 .NET ownership normalized  
**Post-Phase-I clean baseline:** `e308e9279d17ab61ef0d30c874942ce273a0a3f9`  
**Modernization execution base:** `2edb734c9aa26a32b414a0eff891260831009a97`  
**Observed:** 2026-09-15

This record inventories the frozen baseline. It does not authorize an upgrade, migration, removal, or support-floor change. Package-managed first-party distributions are distinguished from source trees that are importable today because root pytest `pythonpath` and workflow install ordering expose them.

## A2 Dependency

### Python manifests confirmed at the frozen baseline

| Path | Role / observed dependency shape | Ownership |
| --- | --- | --- |
| `pyproject.toml` | root project; Python `>=3.11`; `jsonschema>=4.20`; dev pytest/pytest-asyncio/jsonschema; 22 pytest `pythonpath` entries; Ruff `py311` | Platform / repository tooling |
| `contracts/python/pyproject.toml` | first-party Python contracts distribution | Contracts |
| `hosts/autocad/sidecar/pyproject.toml` | `host-contracts`, `grpcio>=1.70,<2`, `protobuf>=5.29,<7`, `mcp>=2,<3`; `grpcio-tools==1.70.0` build extra | AutoCAD Host |
| `hosts/revit/sidecar/pyproject.toml` | Revit Python sidecar distribution | Revit Host |
| `platform/changeset/pyproject.toml` | first-party platform distribution | Platform |
| `platform/convergence/pyproject.toml` | first-party platform distribution | Platform |
| `platform/execution_coordination/pyproject.toml` | first-party platform distribution | Platform |
| `platform/execution_planning/pyproject.toml` | first-party platform distribution | Platform |
| `platform/execution_reconciliation/pyproject.toml` | first-party platform distribution | Platform |
| `platform/gateway_authorization/pyproject.toml` | first-party platform distribution | Platform |
| `platform/materialization_planning/pyproject.toml` | first-party platform distribution | Platform |
| `platform/materialization_topology/pyproject.toml` | first-party platform distribution | Platform |
| `platform/provider_binding/pyproject.toml` | first-party platform distribution | Platform |
| `platform/semantic_mcp/pyproject.toml` | Python `>=3.11`; `semantic-service>=0.1.0`, `mcp>=2,<3`, `pydantic>=2,<3`; setuptools build backend | Semantic transport |
| `platform/semantic_runtime/pyproject.toml` | first-party semantic runtime distribution | Semantic runtime |
| `platform/semantic_service/pyproject.toml` | Python `>=3.11`; `host-contracts>=0.1.0`; setuptools build backend | Semantic service |
| `providers/semantics/dsp_core/pyproject.toml` | semantic-provider distribution | Provider |
| `providers/semantics/enterprise_mapping/pyproject.toml` | semantic-provider distribution | Provider |
| `providers/semantics/ifc43/pyproject.toml` | IFC 4.3 semantic-provider distribution | Provider |
| `providers/semantics/metro_v32/pyproject.toml` | Metro semantic-provider distribution; installed editably by canonical repository regression | Provider |

The frozen Git tree and canonical CI install graph are the authorities for workspace membership in M1. The entries above are the manifests confirmed by the M0 tree/CI evidence; M1 must derive workspace membership from tracked manifests rather than from import success alone.

### Source trees without a package-local manifest in the inspected platform tree

`platform/approval_scope`, `platform/impact`, `platform/interaction`, and `platform/orchestrator` are tracked source trees but no package-local `pyproject.toml` appeared in the frozen platform tree. Their current importability must therefore not be treated as proof of declared package ownership; root pytest `pythonpath` / workflow setup is part of the current exposure mechanism and must be characterized before M1 changes it.

### .NET projects confirmed at the frozen baseline

| Path | Role |
| --- | --- |
| `contracts/dotnet/DesignFactContracts/DesignFactContracts.csproj` | shared design-fact contracts |
| `contracts/dotnet/DesignFactContracts.Tests/DesignFactContracts.Tests.csproj` | contract tests |
| `contracts/dotnet/HostContracts/HostContracts.csproj` | shared Host contracts |
| `contracts/dotnet/HostContracts.Tests/HostContracts.Tests.csproj` | Host contract tests |
| `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj` | AutoCAD native plugin; `net8.0-windows` |
| `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj` | AutoCAD gRPC transport; `net8.0-windows`; Google.Protobuf 3.29.3; Grpc.AspNetCore/Grpc.Tools 2.70.0 |
| `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc.Tests/AutoCAD.AgentHost.Grpc.Tests.csproj` | AutoCAD transport tests |
| `hosts/revit/plugin/Revit.AgentHost.Core/Revit.AgentHost.Core.csproj` | Host-neutral Revit Core; `net8.0` |
| `hosts/revit/plugin/Revit.AgentHost.Core.Tests/Revit.AgentHost.Core.Tests.csproj` | Revit Core tests; `net8.0`; xUnit |
| `hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj` | native Revit plugin; `$(DspRevitTargetFramework)` supplied per Host build |

`global.json` pins SDK `8.0.100`, `rollForward: latestFeature`, `allowPrerelease: false`. This is explicit SDK governance already present; MOD-012 is therefore about assessing whether the governed SDK family must evolve, not creating governance from nothing.

### M1 .NET SDK, NuGet and code-generation ownership

Task 6 does not upgrade the SDK, NuGet packages, generator, proto semantics, or native Host target frameworks. It freezes the already-proven M0 values into machine-verifiable owners so later compatibility work has a deterministic baseline.

| Concern | Authoritative owner | Frozen value / role |
| --- | --- | --- |
| .NET SDK selection | `global.json` | SDK `8.0.100`; `latestFeature`; `allowPrerelease: false` |
| Google.Protobuf | `hosts/autocad/transport/dotnet/AutoCAD.AgentHost.Grpc/AutoCAD.AgentHost.Grpc.csproj` → `DspGoogleProtobufVersion` | `3.29.3` |
| Grpc.AspNetCore | same transport project → `DspGrpcAspNetCoreVersion` | `2.70.0` |
| Grpc.Tools | same transport project → `DspGrpcToolsVersion` | `2.70.0`; `PrivateAssets="All"` |
| System.IO.FileSystem.AccessControl | same transport project → `DspSystemIOFileSystemAccessControlVersion` | `5.0.0` |
| Host transport proto / .NET code generation | same transport project → `DspHostTransportProto` | resolves to canonical `contracts/proto/host_transport_v1.proto`; `GrpcServices="Server"` |
| AutoCAD native TFM | `hosts/autocad/plugin/AutoCAD.AgentHost/AutoCAD.AgentHost.csproj` | remains Host-defined baseline `net8.0-windows` |
| Revit native TFM | `hosts/revit/plugin/Revit.AgentHost/Revit.AgentHost.csproj` | remains dynamic `$(DspRevitTargetFramework)` |

`Directory.Packages.props` remains absent because MOD-013 is `KEEP`: package-version ownership stays project-local unless later evidence separately approves central package management.

## A3 Deprecation

| Class | Observation | Owner / MOD | Current action |
| --- | --- | --- | --- |
| DEPRECATION | canonical Python regression emits the existing `jsonschema.RefResolver` deprecation warning | Schema tooling / MOD-005 | characterize resolver behavior before any `referencing.Registry` migration |
| CI_ACTION | current canonical workflow uses older Action majors (`actions/checkout@v4`, `actions/setup-python@v5`) and M0 CI surfaced runner/runtime deprecation warning(s) | Build & Release / MOD-008 | record only in M0; no Action upgrade in Task 2 |

No warning is normalized away by M0. A warning becomes an execution item only after Task 3 disposition.

## A4 Build & Packaging

- Python packaging is PEP 621 where manifests exist; setuptools remains the observed build backend for the inspected packaged components.
- The root has no repository-wide Python lock at the frozen baseline.
- Canonical CI installs tooling and multiple first-party packages procedurally/editably; install order and root pytest `pythonpath` therefore participate in the current effective dependency graph.
- Canonical CI directly confirms editable installation of `contracts/python`, `hosts/autocad/sidecar`, `platform/semantic_runtime`, `platform/semantic_service`, `platform/semantic_mcp`, and provider packages `dsp_core`, `ifc43`, `metro_v32`, and `enterprise_mapping`.
- `global.json` is the repository .NET SDK selection source: SDK `8.0.100` with `latestFeature` roll-forward.
- NuGet versions remain project-local at the inspected baseline; M0 has not established that central package management is required.

## A5 Protocol & Schema

| Source / generated path | Role | Ownership |
| --- | --- | --- |
| `contracts/proto/host_transport_v1.proto` | canonical Host transport proto source | Contracts / Host transport |
| `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/host_transport_v1_pb2.py` | committed Python generated transport artifact | AutoCAD Host transport |
| `hosts/autocad/sidecar/src/autocad_sidecar/ipc/generated/host_transport_v1_pb2_grpc.py` | committed Python gRPC generated artifact | AutoCAD Host transport |
| AutoCAD `.csproj` Protobuf item | .NET server code generation from the same proto | AutoCAD Host transport |
| root `jsonschema>=4.20` + resolver usage | JSON Schema validation implementation | Schema tooling / MOD-005 |
| `platform/semantic_mcp/pyproject.toml` and AutoCAD sidecar manifest | MCP v2 dependency line (`mcp>=2,<3`) | Semantic transport / AutoCAD sidecar |

M0 freezes the proto/schema semantics. Generator/runtime changes are implementation-tooling candidates only; source-of-truth contract semantics are not modernization targets.

## A7 CI & Toolchain

Canonical repository truth is `.github/workflows/repository-regression.yml`: Python 3.11, `actions/checkout@v4`, `actions/setup-python@v5`, ad-hoc Python tool installation + editable first-party installs, both canonical pytest modes, Ruff no-new-diagnostics, `actions/setup-dotnet@v4`, .NET 8.x and Revit Core tests. Historical/domain workflows remain focused guards; real AutoCAD/Revit acceptance remains separate from Linux/offline canonical regression.

Official facts observed 2026-09-15:
- uv workspaces keep package-local `pyproject.toml` files while sharing one `uv.lock`; `uv lock`, `uv sync` and `uv run` operate on the workspace (Astral uv documentation).
- MCP Python SDK v2 is the current stable line and requires Python 3.10+; the repo already declares `mcp>=2,<3`, so M0 records this as an existing modern line rather than a v1→v2 migration.
- GitHub Dependabot documents support for `github-actions`, `uv`, `.NET SDK`, and NuGet ecosystems; adoption remains a later governance decision.
- GitHub's current setup-python examples use `actions/checkout@v7` and `actions/setup-python@v7`; this is evidence for MOD-008 assessment, not a Task 2 upgrade authorization.

## Relationship classification

M1 must preserve this distinction:

1. **Declared first-party edge** — present in a package/project manifest (for example `semantic-mcp → semantic-service`, `semantic-service → host-contracts`).
2. **Procedural/exposure edge** — import succeeds because root pytest `pythonpath`, editable-install ordering, or workflow setup exposes source.

The modernization program may convert procedural edges into explicit workspace/package relationships only after parity evidence; Task 2 does not change either graph.
