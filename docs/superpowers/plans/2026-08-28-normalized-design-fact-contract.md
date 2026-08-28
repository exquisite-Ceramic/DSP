# NormalizedDesignFact Contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Spec v0.6 Phase E Step 18 as an independent, cross-language `NormalizedDesignFact` / `NormalizedDesignFactBatch` transport contract with JSON Schema, Python and .NET parity.

**Architecture:** Add a new `design_fact_contracts` Python package and `DesignFactContracts` .NET namespace under `contracts/`, independent of HostContracts and Semantic Service. Freeze a strict snake_case JSON wire shape, shared golden vectors, fail-closed validation, and architecture guards; do not add extraction or semantic mapping behavior.

**Tech Stack:** JSON Schema Draft 7, Python 3.11 dataclasses/pytest/jsonschema, .NET 8/System.Text.Json/xUnit, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-28-normalized-design-fact-contract-design.md`

## Global Constraints

- Keep every Spec v0.6 §17.2 field in the wire contract: `fact_id`, `producer`, `host_ref`, `source_revision`, `subject_native_ref`, `fact_kind`, `predicate`, `value`, `value_type`, `unit`, `geometry_ref`, `source_scheme`, `source_code`, `provenance`.
- `NormalizedDesignFact` transports evidence; it MUST NOT establish canonical IFC/DSP/Metro meaning.
- No `semantic_id` field in the contract.
- `host_ref` is `{host_type, host_instance_id, document_id}`; `subject_native_ref` is `{document_id, native_id, native_kind?}` and document IDs must match.
- `fact_kind` is closed to `PROPERTY`, `CLASSIFICATION`, `PLACEMENT`, `BOUNDS`, `GEOMETRY`, `RELATIONSHIP`, `IDENTITY`.
- `value_type` is closed to `NULL`, `STRING`, `INTEGER`, `NUMBER`, `BOOLEAN`, `OBJECT`, `ARRAY` and must match `value`.
- `source_scheme` and `source_code` are both present or both absent.
- Wire JSON uses snake_case and rejects unknown top-level properties.
- Python and .NET public types must be value-oriented and preserve JSON-compatible data without Host SDK objects.
- No Step 19+ behavior: no AutoCAD extractor, A-WALL mapping, semantic provider changes, D5 changes, or ingestion endpoint.

---

### Task 1: Contract RED tests and CI harness

**Files:**
- Create: `contracts/python/tests/test_normalized_design_fact_contract.py`
- Create: `contracts/python/tests/test_normalized_design_fact_schema.py`
- Create: `contracts/python/tests/test_design_fact_architecture.py`
- Create: `.github/workflows/normalized-design-fact-contract.yml`

**Interfaces:**
- Consumes: approved design spec only.
- Produces: failing assertions describing required package, schema, vectors, validation behavior, and forbidden dependency leakage.

- [ ] **Step 1: Write failing contract tests**

Write tests that first assert `importlib.util.find_spec("design_fact_contracts") is not None`, schema files exist, golden-vector directory exists, and the .NET project file exists. Once those existence assertions pass, the same tests exercise the public Python API, schemas and golden vectors.

- [ ] **Step 2: Add a targeted PR workflow**

The workflow SHALL run on pull requests touching `contracts/**`, the Step 18 spec/plan, or the workflow itself. It runs:

```bash
python -m pytest contracts/python/tests/test_normalized_design_fact_contract.py \
  contracts/python/tests/test_normalized_design_fact_schema.py \
  contracts/python/tests/test_design_fact_architecture.py -q

dotnet test contracts/dotnet/DesignFactContracts.Tests/DesignFactContracts.Tests.csproj --configuration Release
```

- [ ] **Step 3: Open the PR and verify RED**

Expected failure: at least the package/schema/.NET-project existence assertions fail because Step 18 production files do not yet exist. This proves the tests detect the missing feature.

- [ ] **Step 4: Commit**

Commit message:

```text
test(contracts): define normalized design fact acceptance tests
```

### Task 2: JSON Schema, golden vectors, and Python GREEN

**Files:**
- Create: `contracts/schemas/normalized-design-fact.schema.json`
- Create: `contracts/schemas/normalized-design-fact-batch.schema.json`
- Create: `contracts/test_vectors/normalized_design_fact/valid_property.json`
- Create: `contracts/test_vectors/normalized_design_fact/valid_classification.json`
- Create: `contracts/test_vectors/normalized_design_fact/valid_object.json`
- Create: `contracts/test_vectors/normalized_design_fact/valid_empty_batch.json`
- Create: `contracts/test_vectors/normalized_design_fact/invalid_source_pair.json`
- Create: `contracts/test_vectors/normalized_design_fact/invalid_document_mismatch.json`
- Create: `contracts/test_vectors/normalized_design_fact/invalid_value_type.json`
- Create: `contracts/python/design_fact_contracts/__init__.py`
- Create: `contracts/python/design_fact_contracts/refs.py`
- Create: `contracts/python/design_fact_contracts/fact.py`
- Modify: `contracts/python/pyproject.toml`

**Interfaces:**
- Produces: `DesignFactHostRef`, `NativeSubjectRef`, `FactKind`, `ValueType`, `NormalizedDesignFact`, `NormalizedDesignFactBatch`.
- Public Python DTOs expose `to_dict()` / `from_dict()` and validate on construction/from-wire.

- [ ] **Step 1: Implement strict schemas and shared vectors**

Use Draft 7, snake_case properties and `additionalProperties: false`. Encode cross-field rules with schema `allOf` for source pair presence; enforce document equality in language validators because Draft 7 cannot compare sibling values directly.

- [ ] **Step 2: Implement Python public types**

Use frozen/slots dataclasses and string enums. Validate non-empty strings, revisions, enum values, value/value_type compatibility, document equality, source pair, provenance, and recursively JSON-compatible values. Defensively copy nested object/array values before storing and before returning serialized dictionaries.

- [ ] **Step 3: Update packaging**

Change setuptools package discovery from:

```toml
include = ["host_contracts*"]
```

to:

```toml
include = ["host_contracts*", "design_fact_contracts*"]
```

Do not rename the existing distribution in Step 18.

- [ ] **Step 4: Verify Python GREEN**

Run the three targeted pytest files. Expected: Python/schema/architecture assertions that do not depend on .NET all pass; .NET existence assertion remains RED until Task 3.

- [ ] **Step 5: Commit**

Commit message:

```text
feat(contracts): add normalized design fact python contract
```

### Task 3: .NET parity GREEN

**Files:**
- Create: `contracts/dotnet/DesignFactContracts/DesignFactContracts.csproj`
- Create: `contracts/dotnet/DesignFactContracts/DesignFactHostRef.cs`
- Create: `contracts/dotnet/DesignFactContracts/NativeSubjectRef.cs`
- Create: `contracts/dotnet/DesignFactContracts/NormalizedDesignFact.cs`
- Create: `contracts/dotnet/DesignFactContracts/NormalizedDesignFactBatch.cs`
- Create: `contracts/dotnet/DesignFactContracts.Tests/DesignFactContracts.Tests.csproj`
- Create: `contracts/dotnet/DesignFactContracts.Tests/NormalizedDesignFactTests.cs`

**Interfaces:**
- Produces the .NET equivalents in namespace `DesignFactContracts` with snake_case `JsonPropertyName` annotations and constructor validation equivalent to Python.

- [ ] **Step 1: Write/retain failing .NET conformance assertions before implementation**

The test project reads the shared JSON vectors from `contracts/test_vectors/normalized_design_fact/`, deserializes valid examples and rejects invalid examples. It also checks serialized property names are snake_case and no semantic/provider-specific fields are emitted.

- [ ] **Step 2: Implement minimal .NET value types**

Target `net8.0`; use `System.Text.Json`, records/read-only collections where practical, and explicit validation helpers. Do not reference HostContracts, Autodesk, semantic service, IFC or Metro assemblies.

- [ ] **Step 3: Verify .NET GREEN**

Run:

```bash
dotnet test contracts/dotnet/DesignFactContracts.Tests/DesignFactContracts.Tests.csproj --configuration Release
```

Expected: all shared-vector and serialization tests pass.

- [ ] **Step 4: Commit**

Commit message:

```text
feat(contracts): add normalized design fact dotnet contract
```

### Task 4: Full verification and PR readiness

**Files:**
- Modify only if verification exposes a Step 18 defect; do not expand scope.

**Interfaces:**
- Consumes all Step 18 contract surfaces.
- Produces a PR whose diff is limited to the approved Step 18 boundary.

- [ ] **Step 1: Run targeted Step 18 CI**

Expected: Python/schema/architecture job green and .NET job green.

- [ ] **Step 2: Run relevant regression suites**

At minimum verify existing Host Contract Python/.NET tests and semantic-service tests remain green through existing PR workflows/status checks.

- [ ] **Step 3: Inspect PR diff**

Confirm no AutoCAD extraction, semantic mapping/provider behavior, D5, Host write or transport endpoint changes were introduced.

- [ ] **Step 4: Verify main-spec alignment**

Check every §17.2 field is present and Phase E stops at Step 18.

- [ ] **Step 5: Update PR description with evidence**

Record RED→GREEN evidence, test suites, cross-language parity, explicit non-goals, and readiness status. Do not merge without a separate explicit user request.
