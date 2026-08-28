# Semantic MCP Adapter Design

**Date:** 2026-08-28  
**Status:** Approved design for PR #7  
**Target branch:** `feat/semantic-mcp-adapter`  
**Base:** `main` at `c40443cf83a9f2c56de0d854e3cce9960c3f128e`

## 1. Purpose

PR #7 adds a thin MCP transport adapter around the Semantic Service Core delivered by PR #6.

The adapter exposes the existing Semantic Service logical API as a stable remote MCP tool surface. It does not own semantic interpretation, provider selection, provider lifecycle, environment construction, domain mappings, or Host-specific behavior.

The design goal is:

```text
MCP Client
    ↓
official MCP Python SDK
    ↓
Semantic MCP Adapter
    ↓
SemanticService
    ↓
SemanticProvider Registry / SemanticEnvironmentStore / Providers
```

The adapter is a transport/controller boundary, not a second semantic service layer.

## 2. Architectural boundary

PR #7 SHALL introduce an independent Python package:

```text
platform/semantic_mcp/
  pyproject.toml
  src/semantic_mcp/
    __init__.py
    server.py
    wire.py
    errors.py
    transport.py
```

The intended dependency direction is:

```text
semantic_mcp
  ├─ depends on semantic_service
  └─ depends on official mcp Python SDK

semantic_service
  ├─ MUST NOT import semantic_mcp
  └─ MUST NOT import mcp
```

`semantic_mcp` MUST NOT directly depend on concrete IFC, DSP Core, Metro, Enterprise, AutoCAD, Revit, Tekla, or other Host/domain Provider implementations.

### 2.1 Framework decision

PR #7 SHALL use the official MCP Python SDK already used by the AutoCAD sidecar, with repository-compatible dependency intent:

```text
mcp >= 2, < 3
```

The server implementation SHALL use the official SDK server abstraction (`MCPServer` in the repository's current SDK line).

The independent FastMCP framework is an explicit non-goal for PR #7. It MAY be reconsidered later if DSP needs framework-level MCP composition, proxying, transform pipelines, authentication orchestration, advanced dependency injection, or similar infrastructure capabilities.

The adapter SHALL isolate MCP-framework-specific code so that a future framework change does not alter Semantic Service contracts, wire DTOs, semantic error codes, or the seven public tool contracts.

## 3. Public MCP v1 tool surface

PR #7 SHALL expose exactly these seven tools:

```text
semantic.resolve_term
semantic.describe_term
semantic.get_term_schema
semantic.validate_claim
semantic.find_mappings
semantic.get_provider_manifest
semantic.get_environment
```

The following are explicitly excluded from PR #7:

```text
semantic.project_facts
semantic.validate_projection
semantic.query_rules
provider registration/admin tools
provider discovery tools
provider health tools
```

No tool may introduce a mutable `latest` or implicit default Semantic Environment.

## 4. Environment scoping

Every query whose answer depends on semantic interpretation MUST receive an explicit `environment_id`.

The adapter MUST NOT:

- infer an environment from an MCP session;
- use a global default environment;
- select the newest provider version;
- silently fall back to another environment;
- mutate an environment during a tool call.

Semantic state is identified by the explicit pinned environment, not by transport state:

```text
MCP session != semantic state
```

`semantic.get_provider_manifest(provider_id, version)` remains exact-version metadata lookup and does not require an environment id because the Core method itself is exact-version and version-addressed.

## 5. Wire-contract principles

MCP clients SHALL receive only JSON-safe values. Python implementation details MUST NOT cross the MCP boundary.

The adapter SHALL convert Core values such as:

```text
dataclass
Enum
tuple
frozenset
MappingProxyType
```

into stable JSON forms:

```text
object
string
array
array
object
```

The adapter MUST NOT serialize unknown Python objects by calling `str()`, `repr()`, pickle, or other implementation-specific fallback conversion.

Inbound `SemanticClaim.value` SHALL accept only recursively JSON-safe values:

```text
null
boolean
number
string
array
object with string keys
```

Unsupported Python/runtime-only values SHALL be rejected rather than coerced.

Successful tools SHALL return the business payload directly. The adapter SHALL NOT add a redundant custom `{ "result": ... }` envelope because MCP already defines the tool-call result envelope.

## 6. Tool contracts

### 6.1 `semantic.resolve_term`

Input:

```yaml
term_id: string
environment_id: string
```

Output:

```yaml
term_id: string
kind: string | null
provenance:
  provider_id: string
  version: string
  content_hash: string
```

Delegation:

```python
SemanticService.resolve_term(term_id, environment_id)
```

### 6.2 `semantic.describe_term`

Input:

```yaml
term_id: string
environment_id: string
locale: string | null = null
```

Output:

```yaml
term_id: string
text: string
locale: string | null
provenance:
  provider_id: string
  version: string
  content_hash: string
```

Delegation:

```python
SemanticService.describe_term(term_id, environment_id, locale)
```

### 6.3 `semantic.get_term_schema`

Input:

```yaml
term_id: string
environment_id: string
```

Output:

```yaml
term_id: string
schema: object
provenance:
  provider_id: string
  version: string
  content_hash: string
```

Core `MappingProxyType`, tuple, and frozenset values SHALL be recursively converted to JSON object/array values without changing their semantic content.

Delegation:

```python
SemanticService.get_term_schema(term_id, environment_id)
```

### 6.4 `semantic.validate_claim`

Input:

```yaml
environment_id: string
claim:
  subject: string
  predicate: string | null
  canonical_term_id: string | null
  value: JSON value
  unit: string | null
  assurance: string
  provenance: string[]
  evidence: string[]
  provider_id: string | null
  provider_version: string | null
```

Output:

```yaml
findings:
  - rule_id: string
    status: PASS | FAIL | NOT_APPLICABLE
    message: string | null
    provenance:
      provider_id: string
      version: string
      content_hash: string
```

The adapter MUST preserve the Core result set. It MUST NOT collapse findings into one boolean, vote among Providers, overwrite findings, or invent severity semantics.

Delegation:

```python
SemanticService.validate_claim(claim, environment_id)
```

### 6.5 `semantic.find_mappings`

Input:

```yaml
environment_id: string
source_claim:
  subject: string
  predicate: string | null
  canonical_term_id: string | null
  value: JSON value
  unit: string | null
  assurance: string
  provenance: string[]
  evidence: string[]
  provider_id: string | null
  provider_version: string | null
target_namespace: string | null = null
```

Output:

```yaml
mappings:
  - mapping_id: string
    target_term_id: string
    evidence: string[]
    provenance:
      provider_id: string
      version: string
      content_hash: string
```

The adapter MUST preserve deterministic Core ordering and MUST NOT select a mapping winner.

Delegation:

```python
SemanticService.find_mappings(source_claim, environment_id, target_namespace)
```

### 6.6 `semantic.get_provider_manifest`

Input:

```yaml
provider_id: string
version: string
```

Output:

```yaml
provider_id: string
provider_type: STANDARD | CORE | DOMAIN | ENTERPRISE
version: string
content_hash: string
manifest_hash: string
namespaces: string[]
capabilities: string[]
authority:
  - namespace: string
    mode: AUTHORITATIVE | EXTENSION
compatibility: string[]
requires:
  - provider_id: string
    version: string
```

The output is the manifest's machine-semantic record. The adapter SHALL NOT append Provider runtime health, transport configuration, credentials, descriptions, process IDs, or other non-manifest state.

Delegation:

```python
SemanticService.get_provider_manifest(provider_id, version)
```

### 6.7 `semantic.get_environment`

Input:

```yaml
environment_id: string
```

Output:

```yaml
environment_id: string
content_hash: string
providers:
  - provider_id: string
    provider_type: STANDARD | CORE | DOMAIN | ENTERPRISE
    version: string
    content_hash: string
    manifest_hash: string
    namespaces: string[]
    capabilities: string[]
    authority:
      - namespace: string
        mode: AUTHORITATIVE | EXTENSION
    compatibility: string[]
    requires:
      - provider_id: string
        version: string
```

The Provider records SHALL match the Core `PinnedProvider` machine payload. The adapter MUST NOT recompute environment identity independently.

Delegation:

```python
SemanticService.get_environment(environment_id)
```

## 7. Error model

Errors are separated into three layers.

### 7.1 MCP/input protocol errors

Malformed MCP requests and tool input-schema violations are owned by the official MCP SDK. The adapter SHALL rely on the SDK for protocol-level validation rather than reimplementing JSON-RPC or MCP schema handling.

Examples include missing required tool arguments, arguments of incompatible JSON types, unknown tools, and malformed MCP requests.

### 7.2 Semantic domain errors

A valid MCP tool call that reaches Semantic Service but fails deterministically is a tool execution failure, not an MCP protocol failure.

Known `SemanticServiceError` subclasses SHALL be converted to an MCP tool result with `isError = true` and a stable structured semantic error payload.

The structured payload shape is:

```yaml
error:
  code: string
  category: string
  retryable: false
  message: string
```

The text content MAY repeat the safe human-readable `message` for agent readability.

Stable wire error codes SHALL be:

| Core error | Wire code | Category |
| --- | --- | --- |
| `ManifestValidationError` | `SEMANTIC_MANIFEST_INVALID` | `MANIFEST` |
| `ProviderRegistrationConflictError` | `SEMANTIC_PROVIDER_REGISTRATION_CONFLICT` | `PROVIDER` |
| `ProviderNotFoundError` | `SEMANTIC_PROVIDER_NOT_FOUND` | `PROVIDER` |
| `ProviderCapabilityError` | `SEMANTIC_PROVIDER_CAPABILITY` | `PROVIDER` |
| `ProviderDependencyError` | `SEMANTIC_PROVIDER_DEPENDENCY` | `PROVIDER` |
| `NamespaceAuthorityError` | `SEMANTIC_NAMESPACE_AUTHORITY` | `AUTHORITY` |
| `EnvironmentIntegrityError` | `SEMANTIC_ENVIRONMENT_INTEGRITY` | `ENVIRONMENT` |
| `EnvironmentNotFoundError` | `SEMANTIC_ENVIRONMENT_NOT_FOUND` | `ENVIRONMENT` |
| `TermResolutionError` | `SEMANTIC_TERM_RESOLUTION` | `TERM` |
| other `SemanticServiceError` | `SEMANTIC_SERVICE_ERROR` | `SEMANTIC` |

PR #7 SHALL set `retryable = false` for all semantic wire errors. The Adapter MUST NOT guess transient/retry semantics that the Core does not model.

Wire error codes are part of the remote contract and SHOULD remain stable even if internal Python exception class organization changes later.

### 7.3 Unexpected internal errors

Any uncaught non-domain exception SHALL be sanitized to:

```yaml
error:
  code: SEMANTIC_INTERNAL_ERROR
  category: INTERNAL
  retryable: false
  message: Semantic service request failed.
```

The remote result MUST NOT expose:

- traceback text;
- Python module/class paths;
- filesystem paths;
- arbitrary Provider exception strings;
- tokens, credentials, URLs, configuration, or environment variables.

The real exception MAY be logged server-side by the process owner.

The adapter SHALL NOT use MCP protocol errors for ordinary Semantic Service domain failures.

## 8. Server construction and lifecycle

The primary construction API SHALL be:

```python
build_mcp_server(service: SemanticService) -> MCPServer
```

The adapter receives a fully constructed `SemanticService`. It does not construct or discover Providers.

A small transport helper MAY be provided:

```python
run_streamable_http(
    service: SemanticService,
    *,
    host: str = "127.0.0.1",
    port: int = 8001,
) -> None
```

The production transport baseline for PR #7 SHALL be:

```text
transport = streamable-http
stateless_http = true
json_response = true
```

This matches the repository's existing AutoCAD MCP transport pattern.

### 8.1 Stateless transport does not recreate semantic state

MCP stateless mode means requests do not rely on MCP client session state. It does not require rebuilding Semantic Service for every request.

One process MAY share one injected `SemanticService` across multiple stateless calls:

```text
client A ─┐
client B ─┼─ stateless MCP calls → one SemanticService
client C ─┘                         ↓
                              pinned environments
```

Version-sensitive behavior remains controlled by explicit `environment_id`.

### 8.2 Bind-host safety

Until Gateway authentication/mTLS is implemented, the built-in HTTP runner SHALL accept loopback binding only:

```text
127.0.0.1
localhost
::1
```

The helper SHALL reject broad external bindings such as `0.0.0.0`.

This is a transport deployment boundary, not Semantic Service business logic.

### 8.3 Provider lifecycle ownership

Semantic MCP Adapter MUST NOT own Provider lifecycle.

It SHALL NOT implicitly call or invent operations such as:

```text
provider.connect()
provider.close()
provider.refresh()
provider.discover()
provider.load_config()
```

Future Provider runtime resources, remote Provider sessions, file/database handles, caches, or watchers belong to the future composition root/provider runtime layer.

## 9. Composition-root boundary

PR #7 SHALL NOT construct:

```text
SemanticProviderRegistry
SemanticEnvironmentStore
IFC Provider
DSP Core Provider
Metro Provider
Enterprise Provider
```

PR #7 SHALL NOT define a Provider plugin-loader/configuration architecture.

Future bootstrap/deployment code is expected to perform:

```text
construct Providers
    ↓
register Providers
    ↓
pin/load Semantic Environments
    ↓
construct SemanticService
    ↓
build_mcp_server(service)
```

A standalone CLI that starts an empty Semantic MCP Server is intentionally excluded from PR #7 because it would create an apparently runnable service without meaningful Provider/environment content.

## 10. Testing strategy

PR #7 SHALL include five layers of tests.

### 10.1 Wire codec tests

Tests SHALL verify recursive conversion of Core DTOs to JSON-safe payloads and inbound Semantic Claim decoding.

Coverage SHALL include:

```text
dataclass → object
Enum → string
tuple → array
frozenset → deterministic array
MappingProxyType → object
nested schema values → recursive JSON-safe values
```

Unsupported runtime objects MUST fail rather than stringify.

### 10.2 Tool catalog contract tests

Tests SHALL assert the exact seven-tool public surface and their required/optional inputs.

Tests SHALL fail if PR #7 exposes:

```text
semantic.project_facts
provider registration/admin tools
provider discovery tools
implicit environment selection tools
```

### 10.3 Delegation tests

Using a fake/stub Semantic Service, tests SHALL prove each MCP tool delegates exactly once to the corresponding Semantic Service method with unchanged semantic arguments.

The Adapter MUST NOT:

- rewrite term IDs;
- infer an environment;
- choose another Provider;
- reorder business semantics independently;
- select mapping winners;
- aggregate validation findings into one verdict;
- modify assurance/provenance.

### 10.4 Error-boundary tests

Each known Core domain error SHALL map to the stable wire code, `isError = true`, and safe message.

At least one deliberately sensitive unexpected exception SHALL prove traceback and exception text are not exposed remotely.

### 10.5 Real MCP conformance/integration tests

At least one test path SHALL use the real MCP SDK/client/session rather than mocking the SDK.

The suite SHALL exercise:

```text
initialize
tools/list
tools/call
successful structured result
tool execution error
```

The purpose is to prove the package is actually callable as a standards-compatible MCP Server, not merely that Python handler functions pass unit tests.

## 11. Architecture guards

PR #7 SHALL add regression guards proving:

- `semantic_service` production code does not import `mcp` or `semantic_mcp`;
- `semantic_mcp` production code does not import concrete IFC/Metro/Enterprise/Host Provider modules;
- public MCP tool names remain exactly the seven v1 names;
- no `project_facts` transport contract exists in PR #7;
- no Provider loader/discovery subsystem exists in PR #7;
- no default/latest environment selection exists;
- independent FastMCP framework imports are absent.

## 12. Non-goals

PR #7 MUST NOT implement:

- Provider loader/discovery;
- IFC4.3 Provider;
- DSP Core Provider;
- Metro Provider;
- Enterprise Provider;
- `NormalizedDesignFactBatch` transport;
- `semantic.project_facts`;
- projection transport APIs;
- remote Provider federation;
- MCP-to-MCP Provider proxying;
- Gateway authentication;
- TLS/mTLS implementation;
- persistent MCP session semantics;
- Host MCP functions;
- D3/D4/D5/D6/D7 modifications;
- Semantic Service Core behavior changes;
- independent FastMCP framework adoption.

## 13. Expected PR shape

PR #7 should remain small and transport-focused. Expected implementation scope is approximately:

```text
platform/semantic_mcp/
  pyproject.toml
  src/semantic_mcp/
    __init__.py
    server.py
    wire.py
    errors.py
    transport.py

tests/semantic_mcp/
  test_wire.py
  test_tool_catalog.py
  test_delegation.py
  test_errors.py
  test_mcp_integration.py
  test_architecture.py

.github/workflows/semantic-mcp.yml   # if a dedicated path-filtered verification job is used
```

The implementation plan may refine test-file names and grouping, but MUST preserve the architectural and remote-contract requirements in this design.

## 14. Acceptance criteria

PR #7 is complete only when all of the following are true:

1. Exactly seven Semantic MCP v1 tools are exposed.
2. Each tool delegates to the corresponding existing Semantic Service method.
3. Version-sensitive tools require explicit `environment_id`.
4. Successful results are stable JSON-safe payloads with no Python container leakage.
5. Inbound claim values reject non-JSON-safe runtime values rather than coercing them.
6. Known Core domain errors map to stable `isError=true` semantic error payloads.
7. Unexpected exceptions are sanitized and do not leak internal details.
8. No mapping winner selection, validation voting, environment fallback, or Provider selection logic exists in the Adapter.
9. Streamable HTTP runs stateless with JSON responses and loopback-only built-in binding.
10. Provider construction/lifecycle remains external to the Adapter.
11. Real MCP client/server integration tests cover initialize, list, call, success, and tool execution error.
12. Semantic Service Core remains free of MCP dependencies.
13. No Provider loader, concrete Provider, projection API, or `project_facts` scope is introduced.
14. The package uses the official MCP SDK only; independent FastMCP framework adoption remains deferred.
