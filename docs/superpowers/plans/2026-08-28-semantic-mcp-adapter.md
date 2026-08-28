# Semantic MCP Adapter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement PR #7 as a thin, standards-compatible Semantic MCP transport adapter exposing the seven approved Semantic Service v1 tools without adding semantic, Provider, Gateway, or LLM-planning ownership.

**Architecture:** Add an independent `platform/semantic_mcp` Python package that depends only on `semantic-service` and the official MCP Python SDK. MCP-specific code stays in `semantic_mcp`; `SemanticService` remains MCP-free. The adapter performs deterministic JSON wire conversion, explicit pinned-environment delegation, DSP-v0.6-aligned structured error mapping, loopback-only stateless Streamable HTTP serving, and real MCP client/server conformance tests.

**Tech Stack:** Python 3.11+, `semantic-service>=0.1.0`, official `mcp>=2,<3`, pytest, pytest-asyncio, stdlib JSON/logging/typing.

**Spec:** `docs/superpowers/specs/2026-08-28-semantic-mcp-adapter-design.md`

## Global Constraints

- DSP protocol target baseline is `MCP 2026-07-28`; SDK version is an implementation detail.
- Use the official MCP Python SDK only; independent FastMCP framework adoption is forbidden in PR #7.
- Expose exactly seven tools: `semantic.resolve_term`, `semantic.describe_term`, `semantic.get_term_schema`, `semantic.validate_claim`, `semantic.find_mappings`, `semantic.get_provider_manifest`, `semantic.get_environment`.
- Version-sensitive semantic queries require explicit `environment_id`; no `latest`, default, session-derived, or fallback environment is allowed.
- `semantic_mcp` MUST NOT load/discover/manage concrete Providers and MUST NOT import IFC/Metro/Enterprise/Host Provider modules.
- `semantic_service` production code MUST remain free of `mcp` and `semantic_mcp` imports.
- Semantic MCP is a platform/Gateway-facing service surface, not the LLM action/tool surface.
- Successful tool payloads are JSON-only and MUST NOT leak Python containers or stringify unsupported runtime objects.
- Semantic domain errors use DSP v0.6 `ErrorShape` fields: `error_code`, `category`, `message`, `correlation_ids`, `retryable`, `details`.
- PR #7 uses only main-spec categories `SEMANTIC` and `CONSISTENCY` for semantic tool errors; do not invent `PROVIDER`, `AUTHORITY`, `ENVIRONMENT`, or `INTERNAL` categories.
- All semantic wire errors set `retryable=false`; do not infer transient semantics.
- Raw exception messages, tracebacks, filesystem paths, URLs, credentials, configuration, and Provider arbitrary exception text MUST NOT cross the MCP boundary.
- Built-in HTTP runner is loopback-only (`127.0.0.1`, `localhost`, `::1`) and uses `streamable-http`, `stateless_http=True`, `json_response=True`.
- Production external governance remains an Enterprise MCP Gateway responsibility; PR #7 does not implement auth, policy, routing, audit, quota, TLS, or mTLS.
- No `semantic.project_facts`, projection transport API, Provider federation/proxying, `NormalizedDesignFactBatch` transport, D3/D4/D5/D6/D7 behavior change, or Semantic Service Core behavior change.

---

## File Structure

Create:

```text
platform/semantic_mcp/
  pyproject.toml
  src/semantic_mcp/
    __init__.py        # curated public package surface
    wire.py            # JSON-safe wire DTO conversion + SemanticClaim decoding
    errors.py          # DSP ErrorShape mapping + MCP CallToolResult builders
    server.py          # seven tool registrations + exact SemanticService delegation
    transport.py       # loopback-only Streamable HTTP runner

tests/semantic_mcp/
  __init__.py
  helpers.py           # deterministic fake SemanticService for adapter-only tests
  test_architecture.py
  test_wire.py
  test_errors.py
  test_tool_catalog.py
  test_delegation.py
  test_mcp_integration.py
  test_transport.py

.github/workflows/semantic-mcp.yml
```

Modify:

```text
docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md
  # synchronize section 10.3 illustrative signatures with the merged PR #6 explicit-environment API

docs/superpowers/specs/2026-08-28-semantic-mcp-adapter-design.md
  # status only: mark the already-approved design as Approved
```

Do not modify `platform/semantic_service/src/**` except if a failing regression proves an existing PR #6 defect; any such defect requires a separate review gate before changing Core.

---

### Task 1: Package Boundary, Dependency Direction, and Public Surface

**Files:**
- Create: `platform/semantic_mcp/pyproject.toml`
- Create: `platform/semantic_mcp/src/semantic_mcp/__init__.py`
- Create: `tests/semantic_mcp/__init__.py`
- Create: `tests/semantic_mcp/test_architecture.py`

**Interfaces:**
- Consumes: merged `semantic_service.SemanticService` and Core DTO/error types.
- Produces: importable `semantic_mcp` package; final public exports will be `build_mcp_server` and `run_streamable_http` after later tasks.

- [ ] **Step 1: Write failing architecture tests before creating the package**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_semantic_service_has_no_mcp_dependency():
    service_src = ROOT / "platform/semantic_service/src/semantic_service"
    source = "\n".join(path.read_text() for path in service_src.glob("*.py"))
    assert "import mcp" not in source
    assert "from mcp" not in source
    assert "semantic_mcp" not in source


def test_semantic_mcp_has_no_concrete_provider_or_fastmcp_imports():
    adapter_src = ROOT / "platform/semantic_mcp/src/semantic_mcp"
    source = "\n".join(path.read_text() for path in adapter_src.glob("*.py"))
    forbidden = (
        "Ifc43Provider",
        "MetroProvider",
        "EnterpriseProvider",
        "autocad_sidecar",
        "revit",
        "tekla",
        "fastmcp",
    )
    assert all(token not in source for token in forbidden)


def test_package_dependency_contract():
    pyproject = (ROOT / "platform/semantic_mcp/pyproject.toml").read_text()
    assert '"semantic-service>=0.1.0"' in pyproject
    assert '"mcp>=2,<3"' in pyproject
    assert "fastmcp" not in pyproject.lower()
```

- [ ] **Step 2: Run tests and verify RED because package files do not exist**

Run:

```bash
pytest -q tests/semantic_mcp/test_architecture.py
```

Expected: FAIL with missing `platform/semantic_mcp` paths/`pyproject.toml`.

- [ ] **Step 3: Create the minimal package metadata**

```toml
[project]
name = "semantic-mcp"
version = "0.1.0"
description = "Thin MCP transport adapter for DSP Semantic Service."
requires-python = ">=3.11"
dependencies = [
    "semantic-service>=0.1.0",
    "mcp>=2,<3",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Create `platform/semantic_mcp/src/semantic_mcp/__init__.py` initially as:

```python
"""DSP Semantic MCP adapter public surface."""

__all__: list[str] = []
```

Create empty `tests/semantic_mcp/__init__.py`.

- [ ] **Step 4: Run architecture tests and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_architecture.py
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add platform/semantic_mcp tests/semantic_mcp/test_architecture.py tests/semantic_mcp/__init__.py
git commit -m "feat(semantic): scaffold Semantic MCP adapter"
```

---

### Task 2: Deterministic JSON Wire Codec and SemanticClaim Decoder

**Files:**
- Create: `platform/semantic_mcp/src/semantic_mcp/wire.py`
- Create: `tests/semantic_mcp/test_wire.py`

**Interfaces:**
- Consumes: `ProviderProvenance`, `ResolvedTerm`, `TermDescription`, `TermSchema`, `SemanticClaim`, `MappingCandidate`, `ValidationFinding`, `SemanticProviderManifest`, `SemanticEnvironment`.
- Produces:
  - `to_json_value(value: object) -> JsonValue`
  - `decode_semantic_claim(payload: Mapping[str, object]) -> SemanticClaim`
  - `encode_resolved_term(...) -> dict[str, JsonValue]`
  - `encode_term_description(...) -> dict[str, JsonValue]`
  - `encode_term_schema(...) -> dict[str, JsonValue]`
  - `encode_validation_findings(...) -> dict[str, JsonValue]`
  - `encode_mapping_candidates(...) -> dict[str, JsonValue]`
  - `encode_manifest(...) -> dict[str, JsonValue]`
  - `encode_environment(...) -> dict[str, JsonValue]`

- [ ] **Step 1: Write RED tests for recursive JSON safety and deterministic unordered collections**

```python
import math
from types import MappingProxyType

import pytest

from semantic_mcp.wire import to_json_value


def test_to_json_value_recurses_and_canonicalizes_sets():
    value = MappingProxyType({
        "schema": {"kinds": frozenset({"wall", "door"})},
        "items": (1, True, None),
    })
    assert to_json_value(value) == {
        "schema": {"kinds": ["door", "wall"]},
        "items": [1, True, None],
    }


def test_to_json_value_rejects_unknown_runtime_object():
    with pytest.raises(TypeError, match="not JSON-safe"):
        to_json_value(object())


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_to_json_value_rejects_non_finite_numbers(value):
    with pytest.raises(TypeError, match="finite"):
        to_json_value(value)
```

- [ ] **Step 2: Run focused tests and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_wire.py
```

Expected: import failure because `semantic_mcp.wire` does not exist.

- [ ] **Step 3: Implement `to_json_value` with canonical set ordering**

```python
from collections.abc import Mapping
from enum import Enum
import json
import math
from typing import TypeAlias

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


def _canonical_key(value: JsonValue) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def to_json_value(value: object) -> JsonValue:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("JSON numbers must be finite")
        return value
    if isinstance(value, Enum):
        return to_json_value(value.value)
    if isinstance(value, Mapping):
        result: dict[str, JsonValue] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError("JSON object keys must be strings")
            result[key] = to_json_value(item)
        return result
    if isinstance(value, (list, tuple)):
        return [to_json_value(item) for item in value]
    if isinstance(value, (set, frozenset)):
        encoded = [to_json_value(item) for item in value]
        return sorted(encoded, key=_canonical_key)
    raise TypeError(f"value of type {type(value).__name__} is not JSON-safe")
```

- [ ] **Step 4: Add RED tests for exact Core DTO encoders and inbound claim decoding**

Use real Core objects, including nested immutable schema values and explicit provenance. Assert exact field names and enum strings. Include this inbound claim test:

```python
from semantic_mcp.wire import decode_semantic_claim


def test_decode_semantic_claim_preserves_wire_fields():
    claim = decode_semantic_claim({
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
    assert claim.subject == "S-WALL-001"
    assert claim.value == {"amount": 300, "tags": ["design"]}
    assert claim.provenance == ("host:A31",)
```

Also assert missing `subject`, unknown extra keys, non-string provenance/evidence items, and non-JSON-safe values raise `ValueError`/`TypeError` rather than coercing.

- [ ] **Step 5: Implement explicit encoders and strict claim decoding**

Do not use `dataclasses.asdict()` as a public wire contract. Write field-by-field encoders so later Core field additions do not silently become remote API fields. `decode_semantic_claim` must permit exactly:

```text
subject
predicate
canonical_term_id
value
unit
assurance
provenance
evidence
provider_id
provider_version
```

Required field: `subject`. Defaults must match Core: `predicate=None`, `canonical_term_id=None`, `value=None`, `unit=None`, `assurance="UNKNOWN"`, `provenance=[]`, `evidence=[]`, `provider_id=None`, `provider_version=None`.

- [ ] **Step 6: Run wire tests and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_wire.py
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/wire.py tests/semantic_mcp/test_wire.py
git commit -m "feat(semantic): add Semantic MCP wire codec"
```

---

### Task 3: DSP ErrorShape Mapping and Sanitized MCP Tool Results

**Files:**
- Create: `platform/semantic_mcp/src/semantic_mcp/errors.py`
- Create: `tests/semantic_mcp/test_errors.py`

**Interfaces:**
- Consumes: all `SemanticServiceError` subclasses from `semantic_service`.
- Produces:
  - `semantic_error_result(exc: SemanticServiceError) -> CallToolResult`
  - `internal_error_result() -> CallToolResult`
  - exact stable mapping table required by the approved spec.

- [ ] **Step 1: Write parameterized RED tests for every Core error subclass**

Each case must assert:

```python
result.is_error is True
result.structured_content == {
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

Cover:

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

- [ ] **Step 2: Add a RED anti-leak test**

```python

def test_error_result_never_forwards_raw_exception_text():
    exc = ProviderNotFoundError("secret=/srv/acme/token=abc123")
    result = semantic_error_result(exc)
    rendered = str(result.model_dump(by_alias=True))
    assert "abc123" not in rendered
    assert "/srv/acme" not in rendered
```

Add the same check for `internal_error_result()`.

- [ ] **Step 3: Run tests and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_errors.py
```

- [ ] **Step 4: Implement direct `CallToolResult` builders**

Use:

```python
from mcp.types import CallToolResult, TextContent
```

Build both `content` and `structured_content`; the text block repeats only the stable safe message. Do not interpolate `exc` into remote payloads. `internal_error_result()` returns:

```json
{
  "error": {
    "error_code": "SEMANTIC_INTERNAL_ERROR",
    "category": "SEMANTIC",
    "message": "Semantic service request failed.",
    "correlation_ids": [],
    "retryable": false,
    "details": []
  }
}
```

- [ ] **Step 5: Run tests and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_errors.py
```

- [ ] **Step 6: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/errors.py tests/semantic_mcp/test_errors.py
git commit -m "feat(semantic): add Semantic MCP error boundary"
```

---

### Task 4: Exact Seven-Tool Catalog and Input Schemas

**Files:**
- Create: `platform/semantic_mcp/src/semantic_mcp/server.py`
- Create: `tests/semantic_mcp/helpers.py`
- Create: `tests/semantic_mcp/test_tool_catalog.py`

**Interfaces:**
- Consumes: `SemanticService`, wire decoder/encoders, error-result helpers.
- Produces: `build_mcp_server(service: SemanticService) -> MCPServer`.

- [ ] **Step 1: Create a minimal fake service for adapter tests**

`tests/semantic_mcp/helpers.py` should define `FakeSemanticService` with call logs for all seven methods and configurable return values/exceptions. It is an adapter test double, not a fake Provider registry.

- [ ] **Step 2: Write RED catalog test using real MCP SDK server introspection**

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

Assert required/optional inputs from each `tool.input_schema`; specifically `environment_id` must be required on the five version-sensitive semantic query tools and absent from `semantic.get_provider_manifest`.

- [ ] **Step 3: Run catalog test and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_tool_catalog.py
```

- [ ] **Step 4: Implement `build_mcp_server` with exactly seven `@server.tool()` registrations**

Use the repository SDK line:

```python
from mcp.server.mcpserver import MCPServer
```

Create:

```python
def build_mcp_server(service: SemanticService) -> MCPServer:
    server = MCPServer("DSP Semantic Service")
    ...
    return server
```

Each tool decorator must use the exact external `name=` above. Tool handlers must have explicit Python parameters matching the approved wire contract. `validate_claim` and `find_mappings` accept a structured claim object and call `decode_semantic_claim` before delegation.

Do not register resources, prompts, admin tools, Provider tools, `project_facts`, or projection tools.

- [ ] **Step 5: Run catalog tests and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_tool_catalog.py
```

- [ ] **Step 6: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/server.py tests/semantic_mcp/helpers.py tests/semantic_mcp/test_tool_catalog.py
git commit -m "feat(semantic): expose Semantic MCP v1 tool catalog"
```

---

### Task 5: Exact Delegation, Success Payloads, and No Semantic Reinterpretation

**Files:**
- Modify: `platform/semantic_mcp/src/semantic_mcp/server.py`
- Create: `tests/semantic_mcp/test_delegation.py`

**Interfaces:**
- Consumes: seven Core method signatures exactly as merged in PR #6.
- Produces: one-to-one request delegation and deterministic success `CallToolResult` payloads.

- [ ] **Step 1: Write RED delegation tests for all seven tools**

Call server handlers via `await server.call_tool(name, args)` or the real in-process client. For every tool assert exactly one recorded service call with unchanged semantic arguments.

Required signatures:

```python
resolve_term(term_id, environment_id)
describe_term(term_id, environment_id, locale=None)
get_term_schema(term_id, environment_id)
validate_claim(claim, environment_id)
find_mappings(source_claim, environment_id, target_namespace=None)
get_provider_manifest(provider_id, version)
get_environment(environment_id)
```

For mappings, assert the Adapter preserves Core ordering and does not choose a winner. For validation, assert it returns all findings and does not reduce them to a boolean.

- [ ] **Step 2: Add RED success-wire assertions**

For every tool assert:

```python
result.is_error is False
result.structured_content == expected_exact_payload
```

Also inspect `TextContent` and assert it is a deterministic JSON representation of the same payload; no `repr()` or Python enum/container syntax may appear.

- [ ] **Step 3: Run focused tests and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_delegation.py
```

- [ ] **Step 4: Implement a single success-result helper and seven thin handlers**

Success helper shape:

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
wire decode if needed
-> one SemanticService call
-> explicit wire encode
-> _success_result
```

No Provider selection, environment fallback, term rewriting, mapping winner selection, validation voting, assurance modification, or result resorting is permitted.

- [ ] **Step 5: Run delegation + wire tests and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_wire.py tests/semantic_mcp/test_delegation.py
```

- [ ] **Step 6: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/server.py tests/semantic_mcp/test_delegation.py
git commit -m "feat(semantic): delegate Semantic MCP tools to core"
```

---

### Task 6: Tool Error Boundary for Domain and Unexpected Failures

**Files:**
- Modify: `platform/semantic_mcp/src/semantic_mcp/server.py`
- Modify: `tests/semantic_mcp/helpers.py`
- Modify: `tests/semantic_mcp/test_errors.py`

**Interfaces:**
- Consumes: `semantic_error_result`, `internal_error_result`.
- Produces: tool-originated failures as `CallToolResult(is_error=True)`; MCP protocol/input failures remain SDK-owned.

- [ ] **Step 1: Write RED tests that inject a Core typed error from a fake service**

Example:

```python
@pytest.mark.asyncio
async def test_environment_not_found_is_tool_error_not_protocol_error():
    service = FakeSemanticService()
    service.resolve_term_error = EnvironmentNotFoundError("secret env path")
    server = build_mcp_server(service)
    result = await server.call_tool(
        "semantic.resolve_term",
        {"term_id": "ifc:IfcWall", "environment_id": "sem-env:missing"},
    )
    assert result.is_error is True
    assert result.structured_content["error"]["error_code"] == "SEMANTIC_ENVIRONMENT_NOT_FOUND"
```

- [ ] **Step 2: Write RED unexpected-error sanitization test**

Inject:

```python
RuntimeError("secret-path=/srv/acme/token=abc123")
```

Assert the result contains only `SEMANTIC_INTERNAL_ERROR` and the fixed safe message; no raw exception text appears in `content` or `structured_content`.

- [ ] **Step 3: Run tests and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_errors.py
```

- [ ] **Step 4: Add one private invocation boundary in `server.py`**

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

Do not include tool arguments, claim payloads, credentials, or exception text in remote results. Server-side traceback logging is permitted.

Input-schema failures and unknown tools must still be produced by the MCP SDK; do not catch or remap protocol-level dispatch errors outside the registered handler body.

- [ ] **Step 5: Run error/delegation tests and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_errors.py tests/semantic_mcp/test_delegation.py
```

- [ ] **Step 6: Commit**

```bash
git add platform/semantic_mcp/src/semantic_mcp/server.py tests/semantic_mcp/helpers.py tests/semantic_mcp/test_errors.py
git commit -m "feat(semantic): sanitize Semantic MCP tool failures"
```

---

### Task 7: Loopback-Only Stateless Streamable HTTP Transport and Public API

**Files:**
- Create: `platform/semantic_mcp/src/semantic_mcp/transport.py`
- Modify: `platform/semantic_mcp/src/semantic_mcp/__init__.py`
- Create: `tests/semantic_mcp/test_transport.py`

**Interfaces:**
- Consumes: `build_mcp_server(service)`.
- Produces: `run_streamable_http(service, *, host="127.0.0.1", port=8001) -> None` and public exports.

- [ ] **Step 1: Write RED host/port validation tests**

```python
@pytest.mark.parametrize("host", ["0.0.0.0", "192.168.1.10", "example.com"])
def test_runner_rejects_non_loopback_bindings(host):
    with pytest.raises(ValueError, match="loopback"):
        validate_bind_address(host, 8001)


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_runner_accepts_loopback_bindings(host):
    validate_bind_address(host, 8001)
```

Also test ports `0`, `65536`, and negative values fail.

- [ ] **Step 2: Run transport tests and verify RED**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_transport.py
```

- [ ] **Step 3: Implement transport helper exactly**

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

No CLI, Provider bootstrap, auth, TLS, configuration loader, or lifecycle manager is added.

- [ ] **Step 4: Curate public package exports**

`semantic_mcp/__init__.py` must expose only:

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

### Task 8: Real MCP 2026-07-28 Conformance, Main-Spec Sync, and CI

**Files:**
- Create: `tests/semantic_mcp/test_mcp_integration.py`
- Create: `.github/workflows/semantic-mcp.yml`
- Modify: `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`
- Modify: `docs/superpowers/specs/2026-08-28-semantic-mcp-adapter-design.md`
- Modify: `docs/superpowers/plans/2026-08-28-semantic-mcp-adapter.md` only to append execution evidence after implementation.

**Interfaces:**
- Consumes: complete adapter from Tasks 1-7.
- Produces: standards-level proof, repository CI gate, synchronized architecture documentation, final execution record.

- [ ] **Step 1: Write real in-process MCP client integration tests**

Use the official high-level client, not mocked SDK objects:

```python
from mcp import Client


@pytest.mark.asyncio
async def test_real_mcp_client_negotiates_2026_baseline_and_lists_exact_tools():
    server = build_mcp_server(FakeSemanticService.with_defaults())
    async with Client(server) as client:
        assert client.protocol_version == "2026-07-28"
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == EXPECTED_TOOL_NAMES
```

Add real `client.call_tool(...)` tests for:

```text
successful structured result
typed SemanticService error -> is_error=True + DSP ErrorShape
unexpected exception -> sanitized SEMANTIC_INTERNAL_ERROR
```

Also verify malformed tool arguments are rejected by the SDK path and do not reach the fake service call log.

- [ ] **Step 2: Run the integration tests and verify GREEN**

```bash
PYTHONPATH=platform/semantic_service/src:platform/semantic_mcp/src pytest -q tests/semantic_mcp/test_mcp_integration.py
```

If the negotiated SDK protocol is not `2026-07-28`, stop implementation and treat that as a protocol-baseline blocker; do not weaken the assertion to accept an older revision.

- [ ] **Step 3: Synchronize main spec section 10.3 signatures**

Replace only the abbreviated `SemanticService Contract` pseudocode with:

```python
resolve_term(term_id, environment_id)
describe_term(term_id, environment_id, locale=None)
get_term_schema(term_id, environment_id)
validate_claim(claim, environment_id)
find_mappings(source_claim, environment_id, target_namespace=None)
get_provider_manifest(provider_id, version)
get_environment(environment_id)
```

Add one sentence stating that version-sensitive semantic queries MUST be scoped by the pinned Semantic Environment and MUST NOT use implicit latest/default Provider state.

Do not otherwise rewrite the main architecture spec.

- [ ] **Step 4: Mark the approved design status accurately**

Change the design header status to:

```text
Status: Approved for implementation; aligned with DSP v0.6
```

Do not change its frozen requirements during implementation without a new explicit design decision.

- [ ] **Step 5: Create dedicated Semantic MCP workflow**

Use:

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

- [ ] **Step 6: Run fresh focused and full verification locally/in execution environment**

Focused:

```bash
pytest -q tests/semantic_mcp
```

Full:

```bash
pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime tests/semantic_service tests/semantic_mcp
```

Expected: all Semantic MCP tests pass; the only permitted skips are the pre-existing live-AutoCAD integration gates unless new environment-specific skip reasons are explicitly justified in review.

- [ ] **Step 7: Run architecture grep checks**

```bash
python - <<'PY'
from pathlib import Path
root = Path('platform/semantic_mcp/src/semantic_mcp')
source = '\n'.join(p.read_text() for p in root.glob('*.py'))
for token in ('fastmcp', 'autocad_sidecar', 'Ifc43Provider', 'MetroProvider', 'EnterpriseProvider', 'project_facts'):
    assert token not in source, token
print('architecture guard OK')
PY
```

- [ ] **Step 8: Append execution evidence to this plan only after final code-head verification**

Record:

```text
implementation head SHA
focused test count/result
full regression count/result
skip count/reasons
GitHub Actions run id/job id
review findings fixed during closeout
```

Do not claim completion from stale pre-documentation CI; after the execution-record commit, obtain one final CI run on the resulting head and reference that in the PR body.

- [ ] **Step 9: Commit closeout files**

```bash
git add .github/workflows/semantic-mcp.yml docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md docs/superpowers/specs/2026-08-28-semantic-mcp-adapter-design.md tests/semantic_mcp/test_mcp_integration.py docs/superpowers/plans/2026-08-28-semantic-mcp-adapter.md
git commit -m "test(semantic): verify Semantic MCP adapter"
```

---

## Self-Review Checklist

Before execution starts, verify the plan covers every approved spec requirement:

- [ ] exact seven-tool surface
- [ ] explicit `environment_id` on version-sensitive semantic queries
- [ ] official MCP SDK only; no independent FastMCP framework
- [ ] MCP 2026-07-28 real-client conformance assertion
- [ ] JSON-only wire encoding; no runtime-object stringification
- [ ] deterministic unordered-collection serialization
- [ ] exact SemanticClaim decode contract
- [ ] exact Core delegation; no Provider selection/fallback/reordering semantics
- [ ] mappings preserve candidate set; validation preserves findings
- [ ] DSP v0.6 ErrorShape fields and category vocabulary
- [ ] safe fixed error messages; raw exception strings not forwarded
- [ ] unexpected exception sanitization
- [ ] protocol/input failures remain SDK-owned
- [ ] stateless Streamable HTTP + JSON response mode
- [ ] loopback-only built-in runner
- [ ] Gateway governance remains out of scope
- [ ] Semantic MCP surface not treated as LLM action/tool surface
- [ ] Provider construction/lifecycle remains external
- [ ] no projection/project_facts/Provider loader/federation scope
- [ ] `semantic_service` remains MCP-free
- [ ] main spec 10.3 explicit-environment signature synchronization
- [ ] focused + full CI gate and final-head verification

No implementation task may weaken a requirement in the approved design without returning to the design gate.
