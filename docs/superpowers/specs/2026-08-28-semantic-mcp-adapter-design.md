# Semantic MCP Adapter Design

**Date:** 2026-08-28  
**Status:** Approved for implementation; aligned with DSP v0.6  
**Target branch:** `feat/semantic-mcp-adapter`  
**Base:** `main` at `c40443cf83a9f2c56de0d854e3cce9960c3f128e`  
**Primary architecture baseline:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

PR #7 adds a thin MCP transport adapter around the Semantic Service Core delivered by PR #6.

The adapter exposes the existing Semantic Service logical API as a stable remote MCP tool surface. It does not own semantic interpretation, provider selection, provider lifecycle, environment construction, domain mappings, Host-specific behavior, workflow orchestration, authorization, or LLM action-space selection.

The design goal is:

```text
DSP Platform / Gateway-side MCP Client
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

This design specializes and refines the Semantic MCP portion of DSP v0.6. If this document and the main v0.6 architecture baseline appear to conflict, the main architecture ownership rules remain authoritative unless this design explicitly identifies a baseline-document synchronization issue.

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

The dependency direction is:

```text
semantic_mcp
  ├─ depends on semantic_service
  └─ depends on official mcp Python SDK

semantic_service
  ├─ MUST NOT import semantic_mcp
  └─ MUST NOT import mcp
```

`semantic_mcp` MUST NOT directly depend on concrete IFC, DSP Core, Metro, Enterprise, AutoCAD, Revit, Tekla, or other Host/domain Provider implementations.

This preserves the v0.6 rule:

```text
MCP = service/discovery/call protocol
Semantic Service/Providers = domain semantic ownership
Gateway = auth/policy/routing/audit ownership
LangGraph/Orchestrator = workflow ownership
```

### 2.1 Framework decision

PR #7 SHALL use the official MCP Python SDK already used by the AutoCAD sidecar, with repository-compatible dependency intent:

```text
mcp >= 2, < 3
```

The server implementation SHALL use the official SDK server abstraction (`MCPServer` in the repository's current SDK line).

The independent FastMCP framework is an explicit non-goal for PR #7. It MAY be reconsidered later if DSP needs framework-level MCP composition, proxying, transform pipelines, authentication orchestration, advanced dependency injection, or similar infrastructure capabilities.

The adapter SHALL isolate MCP-framework-specific code so that a future SDK/framework change does not alter Semantic Service contracts, wire DTOs, semantic error codes, environment semantics, or the seven public tool contracts.

### 2.2 MCP protocol baseline

PR #7 SHALL conform to the DSP v0.6 MCP protocol target baseline:

```text
MCP 2026-07-28
```

The Python package version is an implementation dependency; it is not the DSP protocol/domain contract.

An SDK or MCP protocol upgrade MUST NOT implicitly change:

- Semantic MCP tool names;
- tool input/output business payloads;
- semantic error codes or error meaning;
- pinned Semantic Environment semantics;
- Semantic Service/Provider ownership;
- Gateway/governance ownership;
- LLM-facing action-space rules.

A future protocol upgrade that changes one of these DSP-level contracts requires an explicit architecture decision/spec revision rather than an incidental dependency bump.

## 3. Public MCP v1 tool surface

PR #7 SHALL expose exactly these seven Semantic MCP v1 tools:

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

### 3.1 Semantic MCP surface is not the LLM tool surface

The seven Semantic MCP tools are a platform/Gateway-facing semantic service surface. They MUST NOT be interpreted as the LLM action/tool surface.

The main DSP v0.6 ownership remains:

```text
Semantic MCP
  = semantic definitions / mappings / validation / environment metadata

Gateway / Context Composer / Orchestrator
  = decides what task-scoped semantic information may be exposed onward

LLM-facing surface
  = constrained ResolvedOperations + task-scoped semantic context
```

In particular, the existence of:

```text
semantic.get_provider_manifest
semantic.get_environment
```

does not authorize arbitrary Provider/runtime metadata exposure to the LLM.

PR #7 MUST NOT introduce Provider-native execution details, Host-native identifiers, credentials, policy decisions, or unrestricted runtime metadata into its semantic tool payloads.

## 4. Environment scoping

Every query whose answer depends on semantic interpretation MUST receive an explicit `environment_id`.

The adapter MUST NOT:

- infer an environment from an MCP session;
- use a global default environment;
- select the newest Provider version;
- silently fall back to another environment;
- mutate an environment during a tool call.

Semantic state is identified by the explicit pinned environment, not by transport state:

```text
MCP session != semantic state
```

`semantic.get_provider_manifest(provider_id, version)` remains exact-version metadata lookup and does not require an environment id because the Core method itself is exact-version and version-addressed.

### 4.1 Main-spec contract synchronization note

DSP v0.6 section 10.3 currently shows abbreviated illustrative SemanticService signatures that omit `environment_id` from some version-sensitive queries. The merged PR #6 Core contract and the stronger v0.6 pinned-provider/environment invariants require explicit environment scoping.

PR #7 SHALL therefore use the actual merged SemanticService contract:

```python
resolve_term(term_id, environment_id)
describe_term(term_id, environment_id, locale=None)
get_term_schema(term_id, environment_id)
validate_claim(claim, environment_id)
find_mappings(source_claim, environment_id, target_namespace=None)
get_provider_manifest(provider_id, version)
get_environment(environment_id)
```

The abbreviated signatures in main spec section 10.3 are a baseline-document synchronization item; they MUST NOT be used to weaken pinned-environment behavior in code.

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

The adapter MUST NOT serialize unknown Python objects by calling `str()`, `repr()`, pickle, or another implementation-specific fallback conversion.

Inbound `SemanticClaim.value` SHALL accept only recursively JSON-safe values:

```text
null
boolean
number
string
array
object with string keys
```

Unsupported runtime-only values SHALL be rejected rather than coerced.

For unordered Core collections serialized as arrays, the wire encoder MUST emit deterministic ordering. Unless a stronger domain key exists for the specific field, canonical ordering SHALL use canonical JSON representation with sorted object keys, compact separators, and stable scalar encoding. The encoder MUST NOT depend on Python hash/set iteration order.

Successful tools SHALL return the business payload directly inside the MCP tool result. The adapter SHALL NOT add a redundant custom `{ "result": ... }` business envelope.

### 5.1 Relationship to the DSP Request/Response Envelope

DSP v0.6 section 29 states that cross-service/process requests SHOULD use a common `RequestEnvelope` / `ResponseEnvelope` carrying governance/runtime context such as:

```text
request_id
task_id
project_id
actor_context
correlation_ids
deadline_at
idempotency_key?
payload
```

The seven tool schemas in this design define the **business payload contract**, not a competing cross-service envelope.

PR #7 SHALL NOT copy governance fields into `SemanticClaim`, term DTOs, Provider manifests, or Semantic Environment records.

The intended layering is:

```text
DSP/Gateway request context or envelope
        ↓
MCP tool invocation
        ↓
Semantic MCP business payload defined here
```

PR #7 does not implement Enterprise Gateway envelope propagation. Where no DSP correlation context is supplied to the thin adapter, it MUST NOT invent request/task/project/correlation identifiers.

This is a deliberate specialization of the main spec's `SHOULD`: the thin Adapter owns semantic tool payloads; Gateway/runtime integration owns the common governance envelope.

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

Core `MappingProxyType`, tuple, and frozenset values SHALL be recursively converted to JSON object/array values without changing semantic content. Unordered collections SHALL follow the canonical wire-ordering rule in section 5.

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

Errors are separated into three layers and SHALL align with the DSP v0.6 structured error vocabulary.

### 7.1 MCP/input protocol errors

Malformed MCP requests and tool input-schema violations are owned by the official MCP SDK. The adapter SHALL rely on the SDK for protocol-level validation rather than reimplement JSON-RPC or MCP schema handling.

Examples include missing required tool arguments, arguments of incompatible JSON types, unknown tools, and malformed MCP requests.

These are protocol-layer errors and are not Semantic Service domain failures.

### 7.2 Semantic domain errors

A valid MCP tool call that reaches Semantic Service but fails deterministically is a tool execution failure, not an MCP protocol failure.

Known `SemanticServiceError` subclasses SHALL be converted to an MCP tool result with `isError = true` and a stable structured semantic error payload.

The structured payload SHALL use the DSP v0.6 `ErrorShape` field vocabulary:

```yaml
error:
  error_code: string
  category: SEMANTIC | CONSISTENCY
  message: string
  correlation_ids: string[]
  retryable: false
  details: array
```

For PR #7:

- `correlation_ids` SHALL be `[]` unless an explicit correlation context is supplied by a future Gateway/runtime integration;
- `details` SHALL default to `[]` and MUST NOT be used to leak internal exception text;
- the Adapter MUST NOT invent correlation identifiers;
- natural-language `message` MUST NOT be used as the machine decision key.

Stable semantic wire error mappings SHALL be:

| Core error | `error_code` | Main-spec category | Safe message |
| --- | --- | --- | --- |
| `ManifestValidationError` | `SEMANTIC_MANIFEST_INVALID` | `SEMANTIC` | `Semantic provider manifest is invalid.` |
| `ProviderRegistrationConflictError` | `SEMANTIC_PROVIDER_REGISTRATION_CONFLICT` | `CONSISTENCY` | `Semantic provider registration conflicts with an existing immutable version.` |
| `ProviderNotFoundError` | `SEMANTIC_PROVIDER_NOT_FOUND` | `SEMANTIC` | `Semantic provider was not found.` |
| `ProviderCapabilityError` | `SEMANTIC_PROVIDER_CAPABILITY` | `SEMANTIC` | `Semantic provider capability requirements were not satisfied.` |
| `ProviderDependencyError` | `SEMANTIC_PROVIDER_DEPENDENCY` | `SEMANTIC` | `Semantic provider dependency requirements were not satisfied.` |
| `NamespaceAuthorityError` | `SEMANTIC_NAMESPACE_AUTHORITY` | `SEMANTIC` | `Semantic namespace authority requirements were not satisfied.` |
| `EnvironmentIntegrityError` | `SEMANTIC_ENVIRONMENT_INTEGRITY` | `CONSISTENCY` | `Semantic environment integrity check failed.` |
| `EnvironmentNotFoundError` | `SEMANTIC_ENVIRONMENT_NOT_FOUND` | `SEMANTIC` | `Semantic environment was not found.` |
| `TermResolutionError` | `SEMANTIC_TERM_RESOLUTION` | `SEMANTIC` | `Semantic term resolution failed.` |
| other `SemanticServiceError` | `SEMANTIC_SERVICE_ERROR` | `SEMANTIC` | `Semantic service request failed.` |

The Adapter MUST use these stable safe messages for remote results and MUST NOT forward `str(exc)` wholesale. Internal exception text MAY be logged server-side according to deployment logging policy.

PR #7 SHALL set `retryable = false` for all semantic wire errors. The Adapter MUST NOT guess transient/retry semantics that the Core does not model.

Wire error codes are machine contract. Safe messages are stable presentation text; callers MUST NOT branch on the message.

### 7.3 Unexpected internal errors

Any uncaught non-domain exception SHALL be sanitized to:

```yaml
error:
  error_code: SEMANTIC_INTERNAL_ERROR
  category: SEMANTIC
  message: Semantic service request failed.
  correlation_ids: []
  retryable: false
  details: []
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

A small built-in transport helper MAY be provided:

```python
run_streamable_http(
    service: SemanticService,
    *,
    host: str = "127.0.0.1",
    port: int = 8001,
) -> None
```

The transport baseline for PR #7 SHALL be:

```text
transport = streamable-http
stateless_http = true
json_response = true
```

This matches the repository's existing AutoCAD MCP transport pattern and MUST remain compatible with the DSP v0.6 MCP 2026-07-28 baseline.

### 8.1 Stateless transport does not recreate semantic state

MCP stateless mode means requests do not rely on hidden MCP client-session state. It does not require rebuilding Semantic Service for every request.

One process MAY share one injected `SemanticService` across multiple stateless calls:

```text
client A ─┐
client B ─┼─ stateless MCP calls → one SemanticService
client C ─┘                         ↓
                              pinned environments
```

Version-sensitive behavior remains controlled by explicit `environment_id`.

This aligns with the v0.6 rule that recoverable orchestration must rely on explicit identifiers/handles rather than hidden server session state.

### 8.2 Bind-host safety and production exposure

Until Gateway authentication/mTLS is implemented, the built-in HTTP runner SHALL accept loopback binding only:

```text
127.0.0.1
localhost
::1
```

The helper SHALL reject broad external bindings such as `0.0.0.0`.

The built-in runner is an internal/development process surface. Production external exposure is expected to sit behind the Enterprise MCP Gateway, which owns authentication, authorization, routing, quota/rate limiting, audit/trace, and data-egress policy.

PR #7 MUST NOT implement or duplicate those Gateway responsibilities.

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

Future Provider runtime resources, remote Provider sessions, file/database handles, caches, or watchers belong to the future composition-root/provider-runtime layer.

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
frozenset → canonical deterministic array
MappingProxyType → object
nested schema values → recursive JSON-safe values
```

Unsupported runtime objects MUST fail rather than stringify. Tests for unordered collections MUST prove repeatable output independent of insertion/hash iteration order.

### 10.2 Tool catalog and protocol contract tests

Tests SHALL assert:

- the exact seven-tool public surface;
- required/optional inputs;
- no default/latest environment selector;
- no `project_facts` or admin/discovery tools;
- the adapter is exercised against the repository's MCP SDK in a way consistent with the MCP 2026-07-28 target baseline.

A dependency upgrade MUST fail review/tests if it changes the frozen DSP tool/wire contract without an explicit spec decision.

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

Each known Core domain error SHALL map to:

```text
stable error_code
main-spec category (SEMANTIC or CONSISTENCY)
stable safe message
correlation_ids = [] unless explicitly supplied
details = []
retryable = false
isError = true
```

Tests MUST prove raw `str(exc)` content is not forwarded for known errors.

At least one deliberately sensitive unexpected exception SHALL prove traceback and exception text are not exposed remotely.

Tests SHALL also prove the adapter does not create its own incompatible error-category taxonomy such as `PROVIDER`, `AUTHORITY`, `ENVIRONMENT`, or `INTERNAL` at the DSP `ErrorShape.category` level.

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
- independent FastMCP framework imports are absent;
- no Gateway auth/policy implementation is added to `semantic_mcp`;
- no LLM action/tool-space logic is added to `semantic_mcp`;
- semantic error `category` remains within the main-spec vocabulary;
- no Host-native/provider-native execution detail becomes part of the semantic wire contract.

## 12. Explicit non-goals

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
- Gateway authentication/authorization/policy;
- Gateway routing/quota/audit implementation;
- TLS/mTLS implementation;
- persistent/hidden MCP session semantics;
- LLM action-space construction;
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

## 14. Main-spec alignment matrix

| DSP v0.6 requirement | PR #7 design treatment | Status |
| --- | --- | --- |
| MCP is protocol, not domain ownership | Thin adapter delegates to `SemanticService`; Core has no MCP dependency | Aligned |
| MCP target baseline `2026-07-28` | Explicit protocol baseline in section 2.2 | Aligned |
| Seven Semantic MCP v1 tools | Exact seven-tool catalog in section 3 | Aligned |
| Complex projection APIs deferred | `project_facts` / projection tools are non-goals | Aligned |
| Pinned Provider/environment semantics | Explicit `environment_id`; no latest/default fallback | Aligned |
| Gateway owns auth/policy/routing/audit | Built-in runner stays loopback/internal; Gateway responsibilities excluded | Aligned |
| LLM sees constrained action/context surface | Semantic MCP surface explicitly not equal to LLM tool surface | Aligned |
| Common structured `ErrorShape` | Uses `error_code`, main categories, correlation IDs, retryable, details | Aligned |
| Common Request/Response Envelope SHOULD | Tool schema defined as business payload; Gateway/runtime envelope remains external | Aligned by explicit specialization |
| Provider runtime independent of domain interface | Adapter does not load/manage concrete Providers | Aligned |
| No hidden session state for orchestration | Stateless MCP; semantic version/state explicit via IDs | Aligned |
| Section 10.3 abbreviated Core signatures | Uses actual merged PR #6 explicit-environment API | Main-spec document sync required |

## 15. Acceptance criteria

PR #7 is complete only when all of the following are true:

1. Exactly seven Semantic MCP v1 tools are exposed.
2. Each tool delegates to the corresponding existing Semantic Service method.
3. Version-sensitive tools require explicit `environment_id`.
4. MCP integration remains consistent with the DSP v0.6 `MCP 2026-07-28` target baseline.
5. Successful results are stable JSON-safe payloads with no Python container leakage.
6. Unordered Core collections use deterministic wire ordering independent of Python set/hash iteration order.
7. Inbound claim values reject non-JSON-safe runtime values rather than coercing them.
8. Known Core domain errors map to the DSP `ErrorShape` field vocabulary with stable `error_code`, `SEMANTIC`/`CONSISTENCY` category, safe message, empty-or-supplied correlation IDs, `retryable=false`, and safe details.
9. Unexpected exceptions are sanitized and do not leak internal details.
10. No mapping winner selection, validation voting, environment fallback, or Provider selection logic exists in the Adapter.
11. Semantic MCP tools are not treated as the LLM action/tool surface.
12. Streamable HTTP runs stateless with JSON responses and loopback-only built-in binding.
13. Production governance remains an Enterprise Gateway responsibility; PR #7 does not duplicate Gateway auth/policy/routing/audit logic.
14. Provider construction/lifecycle remains external to the Adapter.
15. Real MCP client/server integration tests cover initialize, list, call, success, and tool execution error.
16. Semantic Service Core remains free of MCP dependencies.
17. No Provider loader, concrete Provider, projection API, or `project_facts` scope is introduced.
18. The package uses the official MCP SDK only; independent FastMCP framework adoption remains deferred.
19. Tool business payloads remain separate from the DSP governance envelope; semantic DTOs are not polluted with request/task/actor fields.
20. The implementation plan explicitly treats the main-spec section 10.3 signature mismatch as documentation synchronization, not permission to remove environment pinning.
