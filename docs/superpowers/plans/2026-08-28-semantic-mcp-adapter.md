# Semantic MCP Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement PR #7 as a thin, standards-compatible MCP transport adapter that exposes the seven approved Semantic Service v1 queries without taking ownership of semantic reasoning, Provider lifecycle, Gateway governance, or LLM action-space construction.

**Architecture:** Add an independent `platform/semantic_mcp` package. MCP input-schema handling and protocol transport stay in that package; all semantic meaning remains in the already-merged `SemanticService`. Results are explicitly encoded to stable JSON, Core failures become DSP-v0.6-aligned `ErrorShape` tool results, unexpected failures are sanitized, and the real official MCP client proves the 2026-07-28 contract.

**Tech Stack:** Python 3.11+, `semantic-service>=0.1.0`, official `mcp>=2,<3`, `pydantic>=2,<3` only for strict MCP input DTO/schema generation, pytest, pytest-asyncio.

**Spec:** `docs/superpowers/specs/2026-08-28-semantic-mcp-adapter-design.md`

## Global Constraints

- Protocol target baseline: exactly `MCP 2026-07-28`; SDK package versions are implementation details.
- MCP framework: official MCP Python SDK only. Independent FastMCP framework is forbidden in PR #7.
- Public surface: exactly seven tools: `semantic.resolve_term`, `semantic.describe_term`, `semantic.get_term_schema`, `semantic.validate_claim`, `semantic.find_mappings`, `semantic.get_provider_manifest`, `semantic.get_environment`.
- Every version-sensitive semantic query requires explicit `environment_id`; no latest/default/session-derived/fallback environment.
- `semantic_service` production code remains free of `mcp` and `semantic_mcp` imports.
- `semantic_mcp` MUST NOT load/discover/manage concrete Providers or import IFC/Metro/Enterprise/Host Provider implementations.
- Semantic MCP is a platform/Gateway-facing service surface, not the LLM action/tool surface.
- Wire values are JSON-only. Unsupported runtime objects are rejected, never stringified.
- Unordered Core collections are serialized deterministically, independent of Python hash/set order.
- Domain errors use DSP v0.6 `ErrorShape`: `error_code`, `category`, `message`, `correlation_ids`, `retryable`, `details`.
- Semantic error categories are only `SEMANTIC` or `CONSISTENCY`; do not invent a parallel category taxonomy.
- `retryable=false` for all PR #7 semantic wire errors.
- Remote errors MUST NOT expose raw exception text, traceback, filesystem paths, credentials, URLs, configuration, or arbitrary Provider messages.
- Built-in HTTP runner is loopback-only and runs `streamable-http`, `stateless_http=True`, `json_response=True`.
- Production auth/policy/routing/quota/audit/TLS/mTLS remain Enterprise Gateway responsibilities.
- No Provider loader, Provider federation/proxy, `semantic.project_facts`, projection transport, `NormalizedDesignFactBatch`, D3/D4/D5/D6/D7 behavior change, or Semantic Service Core behavior change.

---

## File Structure

Create:

```text
platform/semantic_mcp/
  pyproject.toml
  src/semantic_mcp/
    __init__.py
    wire.py
    errors.py
    server.py
    transport.py

tests/semantic_mcp/
  __init__.py
  helpers.py
  test_architecture.py
  test_wire.py
  test_errors.py
  test_tool_catalog.py
  test_delegation.py
  test_transport.py
  test_mcp_integration.py

.github/workflows/semantic-mcp.yml
```

Modify:

```text
docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md
docs/superpowers/specs/2026-08-28-semantic-mcp-adapter-design.md
docs/superpowers/plans/2026-08-28-semantic-mcp-adapter.md  # execution evidence only after implementation
```

Do not modify `platform/semantic_service/src/**` unless a new failing regression proves a pre-existing Core defect; if that happens, stop and review the Core change separately before proceeding.

---

### Task 1: Package Boundary and Architecture Guards

**Files:**
- Create: `platform/semantic_mcp/pyproject.toml`
- Create: `platform/semantic_mcp/src/semantic_mcp/__init__.py`
- Create: `tests/semantic_mcp/__init__.py`
- Create: `tests/semantic_mcp/test_architecture.py`

**Interfaces:**
- Consumes: merged `semantic_service` package.
- Produces: importable package boundary; later tasks add `build_mcp_server` and `run_streamable_http` public exports.

- [ ] **Step 1: Write failing architecture tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_semantic_service_remains_mcp_free():
    src = ROOT / "platform/semantic_service/src/semantic_service"
    text = "\n".join(path.read_text() for path in src.glob("*.py"))
    assert "import mcp" not in text
    assert "from mcp" not in text
    assert "semantic_mcp" not in text


def test_semantic_mcp_has_no_forbidden_runtime_dependencies():
    src = ROOT / "platform/semantic_mcp/src/semantic_mcp"
    text = "\n".join(path.read_text() for path in src.glob("*.py"))
    forbidden = (
        "fastmcp",
        "autocad_sidecar",
        "Ifc43Provider",
        "MetroProvider",
        "EnterpriseProvider",
        "project_facts",
    )
    assert all(token not in text for token in forbidden)


def test_semantic_mcp_declares_only_required_runtime_dependencies():
    pyproject = (ROOT / "platform/semantic_mcp/pyproject.toml").read_text()
    assert '"semantic-service>=0.1.0"' in pyproject
    assert '"mcp>=2,<3"' in pyproject
    assert '"pydantic>=2,<3"' in pyproject
    assert "fastmcp" not in pyproject.lower()
```

- [ ] **Step 2: Run and verify RED**

```bash
pytest -q tests/semantic_mcp/test_architecture.py
```

Expected: FAIL because `platform/semantic_mcp/pyproject.toml` does not exist.

- [ ] **Step 3: Create package metadata and empty public surface**

```toml
[project]
name = "semantic-mcp"
version = "0.1.0"
description = "Thin MCP transport adapter for DSP Semantic Service."
requires-python = ">=3.11"
dependencies = [
    "semantic-service>=0.1.0",
    "mcp>=2,<3",
    "pydantic>=2,<3",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

`semantic_mcp/__init__.py`:

```python
"""DSP Semantic MCP adapter public surface."""

__all__: list[str] = []
```

- [ ] **Step 4: Run and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_architecture.py
```

- [ ] **Step 5: Commit**

```bash
git add platform/semantic_mcp tests/semantic_mcp
git commit -m "feat(semantic): scaffold Semantic MCP adapter"
```

---

### Task 2: Strict MCP Claim Input DTO and Deterministic Wire Codec

**Files:**
- Create: `platform/semantic_mcp/src/semantic_mcp/wire.py`
- Create: `tests/semantic_mcp/test_wire.py`

**Interfaces:**
- Consumes Core DTOs from `semantic_service`.
- Produces:
  - `SemanticClaimInput(BaseModel)` with strict schema and `extra="forbid"`.
  - `to_json_value(value: object) -> JsonValue`.
  - `decode_semantic_claim(payload: SemanticClaimInput) -> SemanticClaim`.
  - explicit encoders for the seven Core result families.

- [ ] **Step 1: Write RED JSON-safety tests**

```python
import math
from types import MappingProxyType

import pytest
from semantic_mcp.wire import to_json_value


def test_json_codec_recurses_and_canonicalizes_unordered_values():
    value = MappingProxyType({
        "kinds": frozenset({"wall", "door"}),
        "values": (1, True, None),
    })
    assert to_json_value(value) == {
        "kinds": ["door", "wall"],
        "values": [1, True, None],
    }


def test_json_codec_rejects_runtime_object():
    with pytest.raises(TypeError, match="not JSON-safe"):
        to_json_value(object())


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_json_codec_rejects_non_finite_number(value):
    with pytest.raises(TypeError, match="finite"):
        to_json_value(value)
```

- [ ] **Step 2: Write RED strict claim-input tests**

```python
import pytest
from pydantic import ValidationError
from semantic_mcp.wire import SemanticClaimInput, decode_semantic_claim


def test_claim_input_builds_core_claim_without_coercion():
    model = SemanticClaimInput.model_validate({
        "subject": "S-WALL-001",
        "predicate": "dsp:WallThickness",
        "canonical_term_id": "ifc:IfcWall",
        "value": {"amount": 300, "tags": ["design"]},
        "unit": "mm",
        "assurance": "RULE_DERIVED",
        "provenance": ["host:A31"],
        "evidence": ["layer:A-WALL"],
        "provider_id": "acme.semantic",
        "provider_version": "1",
    })
    claim = decode_semantic_claim(model)
    assert claim.subject == "S-WALL-001"
    assert claim.value == {"amount": 300, "tags": ["design"]}
    assert claim.provenance == ("host:A31",)


def test_claim_input_rejects_unknown_field():
    with pytest.raises(ValidationError):
        SemanticClaimInput.model_validate({"subject": "S-1", "unknown": 1})


def test_claim_input_rejects_missing_subject():
    with pytest.raises(ValidationError):
        SemanticClaimInput.model_validate({"assurance": "UNKNOWN"})
```

Also add cases proving integer/string coercion does not occur for string fields and that `value` accepts only recursively JSON-safe data.

- [ ] **Step 3: Run and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_wire.py
```

- [ ] **Step 4: Implement strict input DTO and codec**

Use Pydantic only at the MCP boundary:

```python
from pydantic import BaseModel, ConfigDict, JsonValue


class SemanticClaimInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    subject: str
    predicate: str | None = None
    canonical_term_id: str | None = None
    value: JsonValue = None
    unit: str | None = None
    assurance: str = "UNKNOWN"
    provenance: list[str] = []
    evidence: list[str] = []
    provider_id: str | None = None
    provider_version: str | None = None
```

Use `Field(default_factory=list)` rather than mutable literal defaults in the actual implementation for `provenance` and `evidence`.

Implement `to_json_value` with these exact rules:

```text
None/bool/int/finite-float/str -> unchanged
Enum -> encode .value recursively
Mapping with string keys -> object recursively
list/tuple -> array preserving order
set/frozenset -> recursively encode then sort by canonical JSON string
anything else -> TypeError
```

- [ ] **Step 5: Implement explicit result encoders**

Write field-by-field functions; do not use `asdict()` as the public wire contract:

```python
encode_resolved_term(value)
encode_term_description(value)
encode_term_schema(value)
encode_validation_findings(values)
encode_mapping_candidates(values)
encode_manifest(value)
encode_environment(value)
```

The encoders must preserve Core ordering for mappings/findings and only canonicalize genuinely unordered nested containers.

- [ ] **Step 6: Add exact DTO-shape tests and verify GREEN**

Use real Core objects and assert exact keys/enums/provenance. Then run:

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_wire.py
```

- [ ] **Step 7: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/wire.py tests/semantic_mcp/test_wire.py
git commit -m "feat(semantic): add Semantic MCP wire contract"
```

---

### Task 3: DSP-v0.6 ErrorShape and Sanitization

**Files:**
- Create: `platform/semantic_mcp/src/semantic_mcp/errors.py`
- Create: `tests/semantic_mcp/test_errors.py`

**Interfaces:**
- Produces `semantic_error_result(exc: SemanticServiceError) -> CallToolResult` and `internal_error_result() -> CallToolResult`.

- [ ] **Step 1: Write parameterized RED mapping tests**

Assert exact mappings:

```text
ManifestValidationError -> SEMANTIC_MANIFEST_INVALID / SEMANTIC
ProviderRegistrationConflictError -> SEMANTIC_PROVIDER_REGISTRATION_CONFLICT / CONSISTENCY
ProviderNotFoundError -> SEMANTIC_PROVIDER_NOT_FOUND / SEMANTIC
ProviderCapabilityError -> SEMANTIC_PROVIDER_CAPABILITY / SEMANTIC
ProviderDependencyError -> SEMANTIC_PROVIDER_DEPENDENCY / SEMANTIC
NamespaceAuthorityError -> SEMANTIC_NAMESPACE_AUTHORITY / SEMANTIC
EnvironmentIntegrityError -> SEMANTIC_ENVIRONMENT_INTEGRITY / CONSISTENCY
EnvironmentNotFoundError -> SEMANTIC_ENVIRONMENT_NOT_FOUND / SEMANTIC
TermResolutionError -> SEMANTIC_TERM_RESOLUTION / SEMANTIC
other SemanticServiceError -> SEMANTIC_SERVICE_ERROR / SEMANTIC
```

Every structured payload is exactly:

```python
{
    "error": {
        "error_code": expected_code,
        "category": expected_category,
        "message": expected_safe_message,
        "correlation_ids": [],
        "retryable": False,
        "details": [],
    }
}
```

- [ ] **Step 2: Add anti-leak RED tests**

```python
def test_known_error_never_forwards_raw_exception_text():
    exc = ProviderNotFoundError("secret=/srv/acme/token=abc123")
    result = semantic_error_result(exc)
    rendered = str(result.model_dump(by_alias=True))
    assert "abc123" not in rendered
    assert "/srv/acme" not in rendered
```

Do the same for `internal_error_result()`.

- [ ] **Step 3: Run and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_errors.py
```

- [ ] **Step 4: Implement direct MCP tool-error results**

Use:

```python
from mcp.types import CallToolResult, TextContent
```

Both known and unexpected failures return `CallToolResult(is_error=True)` with a safe text block and matching `structured_content`. Never interpolate `str(exc)` into the remote result.

Unexpected failures use:

```text
error_code = SEMANTIC_INTERNAL_ERROR
category = SEMANTIC
message = Semantic service request failed.
correlation_ids = []
retryable = false
details = []
```

- [ ] **Step 5: Run and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_errors.py
```

- [ ] **Step 6: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/errors.py tests/semantic_mcp/test_errors.py
git commit -m "feat(semantic): add Semantic MCP error boundary"
```

---

### Task 4: Exact Seven-Tool Catalog and SDK-Owned Input Validation

**Files:**
- Create: `platform/semantic_mcp/src/semantic_mcp/server.py`
- Create: `tests/semantic_mcp/helpers.py`
- Create: `tests/semantic_mcp/test_tool_catalog.py`

**Interfaces:**
- Consumes `SemanticClaimInput`, encoders, and error-result helpers.
- Produces `build_mcp_server(service: SemanticService) -> MCPServer`.

- [ ] **Step 1: Create `FakeSemanticService` with call logs and configurable returns/errors**

It must implement all seven Core method signatures exactly:

```python
resolve_term(term_id, environment_id)
describe_term(term_id, environment_id, locale=None)
get_term_schema(term_id, environment_id)
validate_claim(claim, environment_id)
find_mappings(source_claim, environment_id, target_namespace=None)
get_provider_manifest(provider_id, version)
get_environment(environment_id)
```

- [ ] **Step 2: Write RED exact-catalog test**

```python
EXPECTED = {
    "semantic.resolve_term",
    "semantic.describe_term",
    "semantic.get_term_schema",
    "semantic.validate_claim",
    "semantic.find_mappings",
    "semantic.get_provider_manifest",
    "semantic.get_environment",
}


@pytest.mark.asyncio
async def test_tools_list_is_exact_v1_surface():
    server = build_mcp_server(FakeSemanticService())
    tools = await server.list_tools()
    assert {tool.name for tool in tools} == EXPECTED
```

Inspect `tool.input_schema` and assert:

```text
resolve/describe/get_term_schema/validate_claim/find_mappings -> environment_id required
get_environment -> environment_id required
get_provider_manifest -> provider_id + version required, no environment_id
validate_claim.claim -> nested schema generated from SemanticClaimInput
find_mappings.source_claim -> nested schema generated from SemanticClaimInput
```

- [ ] **Step 3: Write RED malformed-input test proving handler is not reached**

With the real server call path, call `semantic.validate_claim` with a missing `subject` or extra claim field. Assert `FakeSemanticService.validate_calls == []`.

- [ ] **Step 4: Run and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_tool_catalog.py
```

- [ ] **Step 5: Implement exactly seven `@server.tool()` handlers**

Use:

```python
from mcp.server.mcpserver import MCPServer


def build_mcp_server(service: SemanticService) -> MCPServer:
    server = MCPServer("DSP Semantic Service")
    ...
    return server
```

`validate_claim` signature must include `claim: SemanticClaimInput`; `find_mappings` must include `source_claim: SemanticClaimInput`. The SDK therefore owns structural input validation before handler execution.

Do not register resources, prompts, admin tools, Provider tools, `project_facts`, or projection tools.

- [ ] **Step 6: Run and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_tool_catalog.py
```

- [ ] **Step 7: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/server.py tests/semantic_mcp/helpers.py tests/semantic_mcp/test_tool_catalog.py
git commit -m "feat(semantic): expose Semantic MCP v1 catalog"
```

---

### Task 5: Exact Core Delegation and Success Results

**Files:**
- Modify: `platform/semantic_mcp/src/semantic_mcp/server.py`
- Create: `tests/semantic_mcp/test_delegation.py`

**Interfaces:**
- Produces one-to-one Core delegation and deterministic success `CallToolResult` values.

- [ ] **Step 1: Write RED delegation tests for all seven tools**

For each tool assert exactly one fake-service call and exact unchanged semantic arguments. Specifically verify:

```text
no environment inference
no term rewriting
no Provider selection
no mapping winner selection
no validation voting/reduction
no assurance/provenance modification
no adapter re-sorting of Core result tuples
```

- [ ] **Step 2: Write RED exact success-wire tests**

For every tool assert:

```python
result.is_error is False
result.structured_content == expected_payload
```

The text content must be deterministic JSON for the same payload and must not contain Python `Enum`, tuple, frozenset, `mappingproxy`, or `repr()` syntax.

- [ ] **Step 3: Run and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_delegation.py
```

- [ ] **Step 4: Implement one success helper and thin handlers**

```python
def _success_result(payload: dict[str, JsonValue]) -> CallToolResult:
    text = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return CallToolResult(
        content=[TextContent(type="text", text=text)],
        structured_content=payload,
        is_error=False,
    )
```

Each handler does only:

```text
Pydantic input already validated by SDK
-> decode SemanticClaimInput if applicable
-> exactly one SemanticService method call
-> explicit wire encoder
-> _success_result
```

- [ ] **Step 5: Run wire + delegation tests and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_wire.py tests/semantic_mcp/test_delegation.py
```

- [ ] **Step 6: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/server.py tests/semantic_mcp/test_delegation.py
git commit -m "feat(semantic): delegate Semantic MCP tools to core"
```

---

### Task 6: Domain/Unexpected Error Handling Inside Tool Execution

**Files:**
- Modify: `platform/semantic_mcp/src/semantic_mcp/server.py`
- Modify: `tests/semantic_mcp/helpers.py`
- Modify: `tests/semantic_mcp/test_errors.py`

**Interfaces:**
- Known Core failures -> `semantic_error_result`.
- Unexpected handler/Core failure -> logged server-side + `internal_error_result`.
- SDK dispatch/schema failures remain SDK-owned.

- [ ] **Step 1: Write RED typed-domain-error tool test**

Inject `EnvironmentNotFoundError("secret")` from fake `resolve_term`. Assert the call returns `is_error=True` and `SEMANTIC_ENVIRONMENT_NOT_FOUND` rather than raising a protocol error.

- [ ] **Step 2: Write RED unexpected-failure sanitization test**

Inject:

```python
RuntimeError("secret-path=/srv/acme/token=abc123")
```

Assert neither text content nor structured content contains `abc123`, `/srv/acme`, or the raw message.

- [ ] **Step 3: Run and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_errors.py
```

- [ ] **Step 4: Implement one private invocation boundary**

```python
def _invoke(call: Callable[[], dict[str, JsonValue]]) -> CallToolResult:
    try:
        return _success_result(call())
    except SemanticServiceError as exc:
        return semantic_error_result(exc)
    except Exception:
        logger.exception("Unexpected Semantic MCP tool failure")
        return internal_error_result()
```

Do not wrap SDK tool lookup or SDK input-schema validation with `_invoke`; it belongs only inside registered tool bodies.

- [ ] **Step 5: Run error + catalog + delegation tests and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_errors.py tests/semantic_mcp/test_tool_catalog.py tests/semantic_mcp/test_delegation.py
```

- [ ] **Step 6: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/server.py tests/semantic_mcp/helpers.py tests/semantic_mcp/test_errors.py
git commit -m "feat(semantic): sanitize Semantic MCP failures"
```

---

### Task 7: Loopback Stateless Streamable HTTP Runner and Public API

**Files:**
- Create: `platform/semantic_mcp/src/semantic_mcp/transport.py`
- Modify: `platform/semantic_mcp/src/semantic_mcp/__init__.py`
- Create: `tests/semantic_mcp/test_transport.py`

**Interfaces:**
- Produces `run_streamable_http(service, *, host="127.0.0.1", port=8001) -> None`.

- [ ] **Step 1: Write RED bind validation tests**

Reject `0.0.0.0`, external IPs/domains, port 0, negative ports, and >65535. Accept only `127.0.0.1`, `localhost`, `::1`.

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_transport.py
```

- [ ] **Step 3: Implement transport exactly**

```python
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def validate_bind_address(host: str, port: int) -> None:
    if host.lower() not in _LOOPBACK_HOSTS:
        raise ValueError("Semantic MCP bind host must be loopback until Gateway auth/mTLS exists")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")


def run_streamable_http(service: SemanticService, *, host: str = "127.0.0.1", port: int = 8001) -> None:
    validate_bind_address(host, port)
    build_mcp_server(service).run(
        transport="streamable-http",
        host=host,
        port=port,
        stateless_http=True,
        json_response=True,
    )
```

No CLI, Provider bootstrap, config loader, auth, or lifecycle manager.

- [ ] **Step 4: Curate public exports**

```python
from semantic_mcp.server import build_mcp_server
from semantic_mcp.transport import run_streamable_http

__all__ = ["build_mcp_server", "run_streamable_http"]
```

- [ ] **Step 5: Run transport + architecture tests and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_transport.py tests/semantic_mcp/test_architecture.py
```

- [ ] **Step 6: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/transport.py platform/semantic_mcp/src/semantic_mcp/__init__.py tests/semantic_mcp/test_transport.py
git commit -m "feat(semantic): add Semantic MCP HTTP transport"
```

---

### Task 8: Real MCP 2026-07-28 Conformance, Main-Spec Sync, CI, and Closeout

**Files:**
- Create: `tests/semantic_mcp/test_mcp_integration.py`
- Create: `.github/workflows/semantic-mcp.yml`
- Modify: `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`
- Modify: `docs/superpowers/specs/2026-08-28-semantic-mcp-adapter-design.md`
- Modify: `docs/superpowers/plans/2026-08-28-semantic-mcp-adapter.md` after code verification to append execution evidence.

**Interfaces:**
- Produces real-client protocol proof and final repository verification gate.

- [ ] **Step 1: Write real MCP client conformance test**

```python
from mcp import Client


@pytest.mark.asyncio
async def test_real_client_negotiates_2026_07_28_and_lists_exact_surface():
    server = build_mcp_server(FakeSemanticService.with_defaults())
    async with Client(server) as client:
        assert client.protocol_version == "2026-07-28"
        result = await client.list_tools()
        assert {tool.name for tool in result.tools} == EXPECTED_TOOL_NAMES
```

Add real `client.call_tool(...)` tests for:

```text
successful structured result
typed SemanticService failure -> is_error=True + DSP ErrorShape
unexpected failure -> sanitized SEMANTIC_INTERNAL_ERROR
bad nested claim input -> rejected before FakeSemanticService is called
```

- [ ] **Step 2: Run real MCP integration and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_mcp_integration.py
```

If `client.protocol_version` is not exactly `2026-07-28`, stop: that is a protocol-baseline blocker. Do not relax the assertion to an older revision.

- [ ] **Step 3: Synchronize main spec section 10.3 only**

Replace the stale illustrative signatures with:

```python
resolve_term(term_id, environment_id)
describe_term(term_id, environment_id, locale=None)
get_term_schema(term_id, environment_id)
validate_claim(claim, environment_id)
find_mappings(source_claim, environment_id, target_namespace=None)
get_provider_manifest(provider_id, version)
get_environment(environment_id)
```

Add one sentence that version-sensitive semantic queries MUST use the pinned Semantic Environment and MUST NOT use implicit latest/default Provider state. Do not otherwise rewrite the main spec.

- [ ] **Step 4: Mark design status**

Set design header status to:

```text
Approved for implementation; aligned with DSP v0.6
```

- [ ] **Step 5: Add Semantic MCP CI workflow**

```yaml
name: Semantic MCP verification

on:
  push:
    branches:
      - main
      - 'feat/semantic-mcp-adapter'
    paths:
      - 'platform/semantic_mcp/**'
      - 'platform/semantic_service/**'
      - 'tests/semantic_mcp/**'
      - 'tests/semantic_service/**'
      - 'docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md'
      - 'docs/superpowers/specs/2026-08-28-semantic-mcp-adapter-design.md'
      - 'docs/superpowers/plans/2026-08-28-semantic-mcp-adapter.md'
      - '.github/workflows/semantic-mcp.yml'
  pull_request:
    paths:
      - 'platform/semantic_mcp/**'
      - 'platform/semantic_service/**'
      - 'tests/semantic_mcp/**'
      - 'tests/semantic_service/**'
      - 'docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md'
      - 'docs/superpowers/specs/2026-08-28-semantic-mcp-adapter-design.md'
      - 'docs/superpowers/plans/2026-08-28-semantic-mcp-adapter.md'
      - '.github/workflows/semantic-mcp.yml'
  workflow_dispatch:

jobs:
  semantic-mcp:
    runs-on: ubuntu-latest
    env:
      PYTHONPATH: .
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - name: Install packages
        run: |
          python -m pip install pytest pytest-asyncio jsonschema
          python -m pip install -e contracts/python -e hosts/autocad/sidecar -e platform/semantic_runtime -e platform/semantic_service -e platform/semantic_mcp
      - name: Run Semantic MCP tests
        run: pytest -q tests/semantic_mcp
      - name: Run full Python regression tests
        run: pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime tests/semantic_service tests/semantic_mcp
```

- [ ] **Step 6: Run fresh focused and full verification**

```bash
pytest -q tests/semantic_mcp
pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime tests/semantic_service tests/semantic_mcp
```

Only the existing live-AutoCAD integration gates may remain skipped unless a new skip is explicitly justified during review.

- [ ] **Step 7: Run architecture guard again**

```bash
python - <<'PY'
from pathlib import Path
root = Path('platform/semantic_mcp/src/semantic_mcp')
text = '\n'.join(path.read_text() for path in root.glob('*.py'))
for token in ('fastmcp', 'autocad_sidecar', 'Ifc43Provider', 'MetroProvider', 'EnterpriseProvider', 'project_facts'):
    assert token not in text, token
print('architecture guard OK')
PY
```

- [ ] **Step 8: Perform closeout review before claiming completion**

Review exact diff for:

```text
Provider/Gateway/LLM ownership leakage
implicit environment selection
wire-contract drift
raw exception leakage
SDK-specific assumptions outside server/transport boundary
new public tools
```

Fix blockers using RED -> GREEN before closeout.

- [ ] **Step 9: Append execution evidence after the final code head is verified**

Append a factual execution record containing:

```text
implementation head SHA
focused result/count
full result/count
skip count and exact reasons
GitHub Actions run id/job id
closeout-review findings and fixes
```

After the execution-record commit changes the head, obtain one final CI run on that head. Update PR metadata with that final-head evidence; metadata updates must not create another git head.

- [ ] **Step 10: Commit closeout artifacts**

```bash
git add .github/workflows/semantic-mcp.yml docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md docs/superpowers/specs/2026-08-28-semantic-mcp-adapter-design.md tests/semantic_mcp/test_mcp_integration.py docs/superpowers/plans/2026-08-28-semantic-mcp-adapter.md
git commit -m "test(semantic): verify Semantic MCP adapter"
```

---

## Self-Review Result

This plan has been checked against the approved design for:

- exact seven-tool coverage;
- explicit environment pinning;
- official MCP SDK / no independent FastMCP;
- explicit real-client `MCP 2026-07-28` assertion;
- strict nested `SemanticClaimInput` schema validation before handler execution;
- deterministic JSON conversion and unsupported-object rejection;
- exact Core delegation with no semantic reinterpretation;
- DSP `ErrorShape` fields/categories and fixed safe messages;
- unexpected exception sanitization;
- SDK-owned protocol/input errors;
- stateless Streamable HTTP and loopback-only runner;
- Gateway/LLM/Provider ownership exclusions;
- main-spec 10.3 signature synchronization;
- focused/full/final-head CI evidence.

Placeholder scan: no `TBD`, `TODO`, `implement later`, or `Similar to Task N` instructions remain. Type/signature scan: all seven method signatures match the merged PR #6 `SemanticService` contract, and `SemanticClaimInput` is explicitly the MCP input type consumed by the two claim-bearing tools.
