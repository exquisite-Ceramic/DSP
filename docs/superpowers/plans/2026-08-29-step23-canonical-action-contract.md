# Step 23 — Canonical Action Contract Upgrade Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Freeze the complete platform-owned Canonical Action contract, including typed slot ownership and intent-only schema projection, without implementing Step 24 D4 semantic eligibility, Step 25 D6 binding, or later D7/ProviderBinding behavior.

**Architecture:** `CanonicalOperationDefinition` remains in `design_orchestrator.canonical_operations` as the single platform source of canonical operation meaning. Step 23 adds typed metadata, strict construction-time validation, defensive copying, and an `intent_input_schema()` projection helper; `OperationResolver` remains behaviorally unchanged and continues consuming the canonical definition exactly as before until Step 24 deliberately integrates the new metadata into D4 output.

**Tech Stack:** Python 3.11, frozen dataclasses, `enum.Enum`, `types.MappingProxyType`, `copy.deepcopy`, `re`, pytest, jsonschema, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-08-29-step23-canonical-action-contract-design.md`

## Global Constraints

- Base is `main@833503062d516c25baffae644de73f929164f473`.
- Branch is `feat/step23-canonical-action-contract`.
- Canonical Action Catalog is platform-owned; Host/Execution Provider Profiles remain capability claims only.
- Step 23 MUST NOT modify `platform/orchestrator/src/design_orchestrator/operation_resolver.py` production behavior.
- If `operation_resolver.py` must change to make Step 23 tests pass, stop and treat that as a Step 24 scope escalation rather than silently expanding this PR.
- Step 23 MUST NOT modify production code under `platform/semantic_runtime/`, `platform/semantic_service/`, `platform/semantic_mcp/`, `platform/changeset/`, `hosts/autocad/`, `providers/semantics/`, or `contracts/`.
- Step 23 MUST NOT implement D6 binding, InteractionSession, ChangeSet execution, canonical ExecutionUnit, ProviderBinding, `binding_set_hash`, ExecutionGrant, or HostCommand generation.
- `MOVE_V1` canonical schema remains `targets + displacement`; only slot ownership metadata is added.
- `MOVE_V1.targets = CONTEXT`; `MOVE_V1.displacement = INTENT`.
- `MOVE_V1.operation_freshness_requirements` remains exactly `PLACEMENT / FRESH`.
- `MOVE_V1.effects` is canonically `PLACEMENT + GEOMETRY`; GEOMETRY MUST NOT become a pre-operation freshness requirement.
- `MOVE_V1.canonical_entity_constraints = ()`; AutoCAD/Revit native kinds MUST NOT enter the canonical contract.
- Slot binding classes are exactly `INTENT`, `CONTEXT`, `CANONICAL_DEFAULT`, `DERIVED`, `PROVIDER`.
- Every top-level canonical schema property MUST have exactly one binding class; unknown/missing policy entries fail closed.
- `intent_input_schema()` returns only `INTENT` slots and MUST NOT perform actual binding.
- Structured inputs and returned projections are defensively copied/value-oriented.
- No merge without explicit user authorization.

---

## File Structure / Final Approved Boundary

Step 23 is frozen to exactly these **8 files** unless a separately reviewed compatibility defect is discovered:

```text
.github/workflows/step23-canonical-action-contract.yml
docs/superpowers/plans/2026-08-29-step23-canonical-action-contract.md
docs/superpowers/specs/2026-08-29-step23-canonical-action-contract-design.md
platform/orchestrator/src/design_orchestrator/__init__.py
platform/orchestrator/src/design_orchestrator/canonical_operations.py
tests/orchestrator/test_canonical_operations.py
tests/orchestrator/test_operation_resolver.py
tests/orchestrator/test_step23_architecture.py
```

Production diff is restricted to:

```text
platform/orchestrator/src/design_orchestrator/canonical_operations.py
platform/orchestrator/src/design_orchestrator/__init__.py
```

Responsibilities:

- `canonical_operations.py`: typed Canonical Action DTO, validation, defensive copying, intent schema projection, `MOVE_V1` fixture.
- `__init__.py`: public export of `SlotBindingClass` with existing Canonical Action symbols.
- `test_canonical_operations.py`: contract completeness, validation, projection, immutability, structured requirement tests.
- `test_operation_resolver.py`: compatibility-only updates to test fixtures that construct `CanonicalOperationDefinition`; no new Step24 behavior assertions.
- `test_step23_architecture.py`: source-boundary guard against Host/provider/D7 leakage.
- `step23-canonical-action-contract.yml`: branch/PR verification and exact changed-file gate.

---

### Task 1: Establish RED for the complete Canonical Action contract

**Files:**
- Create: `.github/workflows/step23-canonical-action-contract.yml`
- Create: `tests/orchestrator/test_canonical_operations.py`

**Interfaces:**
- Consumes: current `MOVE_V1` from `design_orchestrator.canonical_operations`.
- Produces: a focused Step23 test entry point and CI runner that exposes the missing contract fields before production changes.

- [ ] **Step 1: Create the initial focused test with one contract-completeness RED**

Create `tests/orchestrator/test_canonical_operations.py` with:

```python
from __future__ import annotations

from design_orchestrator.canonical_operations import MOVE_V1


def test_move_v1_exposes_complete_step23_contract() -> None:
    assert MOVE_V1.canonical_operation == "move.v1"
    assert MOVE_V1.version == "1.0.0"
    assert MOVE_V1.title == "Move entities"
    assert MOVE_V1.description
    assert MOVE_V1.category == "MODEL_OPERATION"
    assert MOVE_V1.canonical_entity_constraints == ()
    assert MOVE_V1.coverage_requirements == ()
    assert MOVE_V1.assurance_requirements == ()
    assert MOVE_V1.operation_freshness_requirements == (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    assert MOVE_V1.effects == ("PLACEMENT", "GEOMETRY")
    assert MOVE_V1.verification_contract == {"type": "HOST_READ_BACK"}
```

Do not import or reference a not-yet-existing enum in the first RED. The expected failure must occur during test execution on the missing `version` field, not during Python collection.

- [ ] **Step 2: Create a minimal Step23 workflow capable of running the RED on branch pushes**

Create `.github/workflows/step23-canonical-action-contract.yml` initially as:

```yaml
name: Step23 canonical action contract

on:
  push:
    paths:
      - "platform/orchestrator/src/design_orchestrator/**"
      - "tests/orchestrator/**"
      - ".github/workflows/step23-canonical-action-contract.yml"
  pull_request:
    paths:
      - "platform/orchestrator/src/design_orchestrator/**"
      - "tests/orchestrator/**"
      - "docs/superpowers/specs/2026-08-29-step23-canonical-action-contract-design.md"
      - "docs/superpowers/plans/2026-08-29-step23-canonical-action-contract.md"
      - ".github/workflows/step23-canonical-action-contract.yml"
  workflow_dispatch:

jobs:
  step23-canonical-action-contract:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install focused test dependencies
        run: python -m pip install pytest jsonschema
      - name: Run Step23 canonical action tests
        run: pytest -q tests/orchestrator/test_canonical_operations.py
```

The root `pyproject.toml` already places `platform/orchestrator/src` on pytest `pythonpath`; do not create an orchestrator package build file in Step23.

- [ ] **Step 3: Commit the RED test and workflow together**

```bash
git add \
  .github/workflows/step23-canonical-action-contract.yml \
  tests/orchestrator/test_canonical_operations.py
git commit -m "test(step23): define canonical action contract red"
```

- [ ] **Step 4: Run the branch workflow and verify the intended RED**

Expected focused result:

```text
FAIL tests/orchestrator/test_canonical_operations.py::test_move_v1_exposes_complete_step23_contract
AttributeError: 'CanonicalOperationDefinition' object has no attribute 'version'
```

The RED is valid only if test collection succeeds and the failure is caused by the missing Step23 contract field. Dependency/import failures do not count.

---

### Task 2: Add typed contract fields and freeze `MOVE_V1`

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_operations.py`
- Modify: `platform/orchestrator/src/design_orchestrator/__init__.py`
- Modify: `tests/orchestrator/test_canonical_operations.py`
- Modify: `tests/orchestrator/test_operation_resolver.py`

**Interfaces:**
- Consumes: existing `CanonicalOperationDefinition`, `MOVE_V1`, and `OperationResolver` tests.
- Produces: `SlotBindingClass`, expanded `CanonicalOperationDefinition`, frozen Step23 metadata on `MOVE_V1`, public enum export, and resolver-test fixture compatibility.

- [ ] **Step 1: Extend the focused test to assert typed slot ownership**

Update imports and the completeness test:

```python
from design_orchestrator.canonical_operations import MOVE_V1, SlotBindingClass


def test_move_v1_exposes_complete_step23_contract() -> None:
    assert MOVE_V1.canonical_operation == "move.v1"
    assert MOVE_V1.version == "1.0.0"
    assert MOVE_V1.title == "Move entities"
    assert MOVE_V1.description
    assert MOVE_V1.category == "MODEL_OPERATION"
    assert MOVE_V1.slot_binding_policy["targets"] is SlotBindingClass.CONTEXT
    assert MOVE_V1.slot_binding_policy["displacement"] is SlotBindingClass.INTENT
    assert MOVE_V1.canonical_entity_constraints == ()
    assert MOVE_V1.context_freshness_requirements == ()
    assert MOVE_V1.operation_freshness_requirements == (
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    )
    assert MOVE_V1.coverage_requirements == ()
    assert MOVE_V1.assurance_requirements == ()
    assert MOVE_V1.effects == ("PLACEMENT", "GEOMETRY")
    assert MOVE_V1.verification_contract == {"type": "HOST_READ_BACK"}
```

Expected RED before implementation: import/attribute failure for `SlotBindingClass` or the new fields.

- [ ] **Step 2: Add the five frozen slot binding classes**

In `canonical_operations.py`, add:

```python
from enum import Enum


class SlotBindingClass(str, Enum):
    INTENT = "INTENT"
    CONTEXT = "CONTEXT"
    CANONICAL_DEFAULT = "CANONICAL_DEFAULT"
    DERIVED = "DERIVED"
    PROVIDER = "PROVIDER"
```

Do not add Host-specific subclasses or provider-specific binding values.

- [ ] **Step 3: Expand `CanonicalOperationDefinition` with the approved Step23 fields**

Use this field shape:

```python
@dataclass(frozen=True, slots=True)
class CanonicalOperationDefinition:
    canonical_operation: str
    version: str
    title: str
    description: str
    category: str
    input_schema: dict[str, Any]
    slot_binding_policy: Mapping[str, SlotBindingClass | str]
    verification_contract: dict[str, Any]
    canonical_entity_constraints: tuple[str, ...] = ()
    context_freshness_requirements: tuple[dict[str, Any], ...] = ()
    operation_freshness_requirements: tuple[dict[str, Any], ...] = ()
    coverage_requirements: tuple[dict[str, Any], ...] = ()
    assurance_requirements: tuple[dict[str, Any], ...] = ()
    effects: tuple[Any, ...] = ()
```

Also import:

```python
from collections.abc import Mapping
from types import MappingProxyType
```

At this task, normalize/copy the new values minimally; strict policy validation is Task 3.

- [ ] **Step 4: Freeze the exact Step23 MOVE metadata**

Update `MOVE_V1` to include:

```python
MOVE_V1 = CanonicalOperationDefinition(
    canonical_operation="move.v1",
    version="1.0.0",
    title="Move entities",
    description="Move the selected canonical design entities by a displacement vector.",
    category="MODEL_OPERATION",
    input_schema={
        "type": "object",
        "properties": {
            "targets": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 1,
            },
            "displacement": {
                "type": "array",
                "items": {"type": "number"},
                "minItems": 3,
                "maxItems": 3,
            },
        },
        "required": ["targets", "displacement"],
        "additionalProperties": False,
    },
    slot_binding_policy={
        "targets": SlotBindingClass.CONTEXT,
        "displacement": SlotBindingClass.INTENT,
    },
    canonical_entity_constraints=(),
    operation_freshness_requirements=(
        {"aspect": "PLACEMENT", "required_state": "FRESH"},
    ),
    coverage_requirements=(),
    assurance_requirements=(),
    effects=("PLACEMENT", "GEOMETRY"),
    verification_contract={"type": "HOST_READ_BACK"},
)
```

The description is deliberately Host-independent; do not mention AutoCAD, Revit, handles, ElementIds, provider tools, revisions, or idempotency keys.

- [ ] **Step 5: Normalize slot policy values to a read-only typed mapping**

In `__post_init__`, build:

```python
normalized_slot_policy = MappingProxyType(
    {
        str(slot): (
            value if isinstance(value, SlotBindingClass) else SlotBindingClass(str(value))
        )
        for slot, value in self.slot_binding_policy.items()
    }
)
object.__setattr__(self, "slot_binding_policy", normalized_slot_policy)
```

Do not add fallback values for invalid enum strings; `SlotBindingClass(...)` must raise `ValueError`.

- [ ] **Step 6: Defensive-copy all structured metadata fields**

Add a small private helper:

```python
def _copy_mapping_sequence(
    value: tuple[dict[str, Any], ...],
    *,
    field_name: str,
) -> tuple[dict[str, Any], ...]:
    copied: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field_name} entries must be objects")
        copied.append(deepcopy(dict(item)))
    return tuple(copied)
```

Use it for:

```text
context_freshness_requirements
operation_freshness_requirements
coverage_requirements
assurance_requirements
```

Copy `effects` with:

```python
object.__setattr__(self, "effects", tuple(deepcopy(item) for item in self.effects))
```

Keep existing defensive copies for `input_schema` and `verification_contract`.

- [ ] **Step 7: Export `SlotBindingClass` from the package root**

Modify `platform/orchestrator/src/design_orchestrator/__init__.py`:

```python
from design_orchestrator.canonical_operations import (
    CanonicalOperationDefinition,
    MOVE_V1,
    MVP_CANONICAL_OPERATIONS,
    SlotBindingClass,
)
```

and add:

```python
"SlotBindingClass",
```

to `__all__`.

- [ ] **Step 8: Update resolver test constructors for the expanded required contract**

In `tests/orchestrator/test_operation_resolver.py`, import `SlotBindingClass` and update `definition_for()` for non-MOVE operations:

```python
return CanonicalOperationDefinition(
    canonical_operation=canonical_operation,
    version="1.0.0",
    title=canonical_operation,
    description=f"Canonical test operation {canonical_operation}",
    category="MODEL_OPERATION",
    input_schema=json.loads(json.dumps(GENERIC_CANONICAL_SCHEMA)),
    slot_binding_policy={"targets": SlotBindingClass.INTENT},
    verification_contract={"type": "HOST_READ_BACK"},
)
```

Update the duplicate-definition fixture similarly:

```python
duplicate = CanonicalOperationDefinition(
    canonical_operation="move.v1",
    version="1.0.0",
    title="Duplicate move",
    description="Duplicate test definition.",
    category="MODEL_OPERATION",
    input_schema={"type": "object", "properties": {}},
    slot_binding_policy={},
    verification_contract={"type": "NONE"},
)
```

This is test-fixture compatibility only. Do not change existing D4 expected behavior yet: the resolver still exposes the full canonical input schema and still aggregates provider effects until Step24.

- [ ] **Step 9: Run focused and D4 regression tests**

Run:

```bash
pytest -q tests/orchestrator/test_canonical_operations.py
pytest -q tests/orchestrator/test_operation_resolver.py
```

Expected: the completeness test passes and all existing resolver tests remain green.

- [ ] **Step 10: Commit the typed contract foundation**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/canonical_operations.py \
  platform/orchestrator/src/design_orchestrator/__init__.py \
  tests/orchestrator/test_canonical_operations.py \
  tests/orchestrator/test_operation_resolver.py
git commit -m "feat(step23): freeze canonical action contract fields"
```

---

### Task 3: Add strict validation and intent-only schema projection

**Files:**
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_operations.py`
- Modify: `tests/orchestrator/test_canonical_operations.py`

**Interfaces:**
- Consumes: expanded `CanonicalOperationDefinition` and `SlotBindingClass` from Task 2.
- Produces: fail-closed construction rules and `CanonicalOperationDefinition.intent_input_schema() -> dict[str, Any]`.

- [ ] **Step 1: Write RED tests for required identity/description/version fields**

Add:

```python
import pytest

from design_orchestrator.canonical_operations import (
    CanonicalOperationDefinition,
    MOVE_V1,
    SlotBindingClass,
)


def make_definition(**overrides):
    values = {
        "canonical_operation": "test.op.v1",
        "version": "1.0.0",
        "title": "Test operation",
        "description": "A Host-independent test operation.",
        "category": "MODEL_OPERATION",
        "input_schema": {
            "type": "object",
            "properties": {"value": {"type": "number"}},
            "required": ["value"],
            "additionalProperties": False,
        },
        "slot_binding_policy": {"value": SlotBindingClass.INTENT},
        "verification_contract": {"type": "NONE"},
    }
    values.update(overrides)
    return CanonicalOperationDefinition(**values)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("canonical_operation", "  "),
        ("version", ""),
        ("title", ""),
        ("description", ""),
    ],
)
def test_required_text_fields_fail_closed(field_name: str, value: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_definition(**{field_name: value})


@pytest.mark.parametrize("version", ["1", "1.0", "v1.0.0", "1.0.x"])
def test_contract_version_requires_numeric_major_minor_patch(version: str) -> None:
    with pytest.raises(ValueError, match="version"):
        make_definition(version=version)
```

Step23 uses the intentionally small version grammar `MAJOR.MINOR.PATCH` with numeric components only (`^[0-9]+\.[0-9]+\.[0-9]+$`). Prerelease/build metadata routing is outside this step.

- [ ] **Step 2: Write RED tests for slot-policy exactness**

Add:

```python
def test_missing_slot_policy_fails_closed() -> None:
    with pytest.raises(ValueError, match="missing slot binding policy"):
        make_definition(slot_binding_policy={})


def test_unknown_policy_slot_fails_closed() -> None:
    with pytest.raises(ValueError, match="unknown canonical slot"):
        make_definition(
            slot_binding_policy={
                "value": SlotBindingClass.INTENT,
                "ghost": SlotBindingClass.CONTEXT,
            }
        )


def test_unknown_binding_class_fails_closed() -> None:
    with pytest.raises(ValueError):
        make_definition(slot_binding_policy={"value": "MAGIC"})
```

- [ ] **Step 3: Write RED tests for schema shape and structured requirement collections**

Add:

```python
def test_input_schema_properties_must_be_an_object() -> None:
    with pytest.raises(ValueError, match="properties"):
        make_definition(input_schema={"type": "object", "properties": []})


def test_required_must_reference_known_properties() -> None:
    with pytest.raises(ValueError, match="required"):
        make_definition(
            input_schema={
                "type": "object",
                "properties": {"value": {"type": "number"}},
                "required": ["missing"],
                "additionalProperties": False,
            }
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "context_freshness_requirements",
        "operation_freshness_requirements",
        "coverage_requirements",
        "assurance_requirements",
    ],
)
def test_requirement_entries_must_be_objects(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        make_definition(**{field_name: ("not-an-object",)})
```

- [ ] **Step 4: Write the intent projection RED**

Add:

```python
def test_move_intent_schema_exposes_only_displacement() -> None:
    projected = MOVE_V1.intent_input_schema()

    assert projected["type"] == "object"
    assert list(projected["properties"]) == ["displacement"]
    assert projected["required"] == ["displacement"]
    assert projected["additionalProperties"] is False
    assert "targets" not in projected["properties"]
```

Also validate the schema:

```python
from jsonschema import Draft202012Validator

Draft202012Validator.check_schema(projected)
Draft202012Validator(projected).validate({"displacement": [1, 2, 3]})
```

Expected RED before implementation: `AttributeError` for `intent_input_schema` plus validation tests failing because inconsistent definitions are currently accepted.

- [ ] **Step 5: Implement strict text/category/schema validation**

In `canonical_operations.py`, add:

```python
import re

_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _required_text(value: str, field_name: str) -> str:
    normalized = str(value).strip()
    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized
```

In `__post_init__`:

```python
canonical_operation = _required_text(self.canonical_operation, "canonical_operation")
version = _required_text(self.version, "version")
title = _required_text(self.title, "title")
description = _required_text(self.description, "description")
if _VERSION_RE.fullmatch(version) is None:
    raise ValueError("version must use numeric MAJOR.MINOR.PATCH")
if self.category not in _VALID_CATEGORIES:
    raise ValueError(f"invalid canonical operation category: {self.category!r}")
if not isinstance(self.input_schema, dict):
    raise ValueError("canonical input_schema must be an object")
if not isinstance(self.verification_contract, dict):
    raise ValueError("canonical verification_contract must be an object")
```

Store normalized text values via `object.__setattr__`.

- [ ] **Step 6: Validate top-level schema properties and slot-policy exactness**

Use:

```python
properties = self.input_schema.get("properties", {})
if not isinstance(properties, Mapping):
    raise ValueError("canonical input_schema properties must be an object")
property_names = {str(name) for name in properties}

required = self.input_schema.get("required", [])
if not isinstance(required, list) or any(not isinstance(item, str) for item in required):
    raise ValueError("canonical input_schema required must be an array of strings")
unknown_required = sorted(set(required) - property_names)
if unknown_required:
    raise ValueError(f"canonical input_schema required references unknown slots: {unknown_required}")

policy_names = set(normalized_slot_policy)
missing = sorted(property_names - policy_names)
unknown = sorted(policy_names - property_names)
if missing:
    raise ValueError(f"missing slot binding policy for canonical slots: {missing}")
if unknown:
    raise ValueError(f"slot binding policy references unknown canonical slot: {unknown}")
```

This validation is generic. Do not add an AutoCAD/Revit/native-name denylist in production code.

- [ ] **Step 7: Implement `intent_input_schema()`**

Add:

```python
def intent_input_schema(self) -> dict[str, Any]:
    schema = deepcopy(self.input_schema)
    properties = schema.get("properties", {})
    visible_names = [
        name
        for name in properties
        if self.slot_binding_policy[name] is SlotBindingClass.INTENT
    ]
    schema["properties"] = {
        name: deepcopy(properties[name])
        for name in visible_names
    }
    if "required" in schema:
        schema["required"] = [
            name
            for name in schema["required"]
            if name in schema["properties"]
        ]
    return schema
```

The helper does not bind `CONTEXT`, defaults, derived values, or provider values. It only projects schema visibility.

- [ ] **Step 8: Run the focused Step23 tests**

```bash
pytest -q tests/orchestrator/test_canonical_operations.py
```

Expected: all contract, validation, and projection tests pass.

- [ ] **Step 9: Run the existing D4 resolver suite**

```bash
pytest -q tests/orchestrator/test_operation_resolver.py
```

Expected: all existing tests pass without modifying `operation_resolver.py`.

- [ ] **Step 10: Commit strict validation and projection**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/canonical_operations.py \
  tests/orchestrator/test_canonical_operations.py
git commit -m "feat(step23): validate canonical slot ownership"
```

---

### Task 4: Prove defensive copying and architecture isolation

**Files:**
- Modify: `tests/orchestrator/test_canonical_operations.py`
- Create: `tests/orchestrator/test_step23_architecture.py`
- Modify: `platform/orchestrator/src/design_orchestrator/canonical_operations.py` only if a defensive-copy RED exposes a real gap.

**Interfaces:**
- Consumes: finalized Step23 contract from Task 3.
- Produces: immutability evidence and automated boundary guards proving Step23 did not pull Host/D5/D7/provider concerns into the Canonical Action module.

- [ ] **Step 1: Write defensive-copy tests**

Add:

```python
def test_contract_defensively_copies_source_metadata() -> None:
    input_schema = {
        "type": "object",
        "properties": {"value": {"type": "number"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    policy = {"value": SlotBindingClass.INTENT}
    freshness = [{"aspect": "PROPERTIES", "required_state": "FRESH"}]
    effects = [{"aspect": "PROPERTIES"}]

    definition = make_definition(
        input_schema=input_schema,
        slot_binding_policy=policy,
        operation_freshness_requirements=tuple(freshness),
        effects=tuple(effects),
    )

    input_schema["properties"]["value"]["type"] = "string"
    policy["value"] = SlotBindingClass.CONTEXT
    freshness[0]["required_state"] = "STALE"
    effects[0]["aspect"] = "GEOMETRY"

    assert definition.input_schema["properties"]["value"]["type"] == "number"
    assert definition.slot_binding_policy["value"] is SlotBindingClass.INTENT
    assert definition.operation_freshness_requirements[0]["required_state"] == "FRESH"
    assert definition.effects[0]["aspect"] == "PROPERTIES"
```

- [ ] **Step 2: Write projection independence test**

```python
def test_intent_projection_is_independent_from_canonical_schema() -> None:
    first = MOVE_V1.intent_input_schema()
    first["properties"]["displacement"]["maxItems"] = 99
    first["required"].clear()

    second = MOVE_V1.intent_input_schema()

    assert second["properties"]["displacement"]["maxItems"] == 3
    assert second["required"] == ["displacement"]
    assert MOVE_V1.input_schema["properties"]["displacement"]["maxItems"] == 3
```

- [ ] **Step 3: Create Step23 architecture source guards**

Create `tests/orchestrator/test_step23_architecture.py`:

```python
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CANONICAL = ROOT / "platform/orchestrator/src/design_orchestrator/canonical_operations.py"
ORCHESTRATOR_PRODUCTION = ROOT / "platform/orchestrator/src/design_orchestrator"


def test_canonical_action_module_has_no_host_or_provider_specific_routing() -> None:
    text = CANONICAL.read_text(encoding="utf-8").lower()
    for forbidden in (
        "cad.move",
        "handles",
        "elementid",
        "autocad.sidecar",
        "autocad_sidecar",
        "revit",
    ):
        assert forbidden not in text


def test_canonical_action_module_does_not_import_host_or_semantic_provider_packages() -> None:
    text = CANONICAL.read_text(encoding="utf-8")
    for forbidden in (
        "autocad_sidecar",
        "semantic_service",
        "ifc43_provider",
        "metro_v32_provider",
        "enterprise_mapping_provider",
    ):
        assert forbidden not in text


def test_step23_does_not_add_execution_binding_production_modules() -> None:
    production_files = tuple(ORCHESTRATOR_PRODUCTION.glob("*.py"))
    names = {path.name for path in production_files}
    assert "provider_binding.py" not in names
    assert "host_command_builder.py" not in names
    assert "slot_binder.py" not in names
```

The first guard checks only the production module, not design/plan/test prose, so the approved documentation may still discuss AutoCAD/Revit as boundary examples.

- [ ] **Step 4: Run the new tests and fix only defensive-copy defects**

```bash
pytest -q \
  tests/orchestrator/test_canonical_operations.py \
  tests/orchestrator/test_step23_architecture.py
```

If a defensive-copy test fails, fix the copy behavior inside `canonical_operations.py`. If an architecture test fails because the implementation requires Host/provider/D7 code, stop and reassess scope instead of weakening the guard.

- [ ] **Step 5: Run Step22 regression proofs**

```bash
pytest -q tests/orchestrator/test_operation_resolver.py
pytest -q tests/integration/test_step22_task_scoped_progressive.py
```

Expected invariants:

```text
canonical operation freshness remains PLACEMENT/FRESH
provider execution_freshness remains provider-local
MOVE effects do not imply GEOMETRY pre-operation freshness
progressive D5 only upgrades requested aspects/fidelity
```

- [ ] **Step 6: Commit defensive-copy and architecture evidence**

```bash
git add \
  platform/orchestrator/src/design_orchestrator/canonical_operations.py \
  tests/orchestrator/test_canonical_operations.py \
  tests/orchestrator/test_step23_architecture.py
git commit -m "test(step23): guard canonical action boundaries"
```

If no production copy fix was needed, omit `canonical_operations.py` from this commit.

---

### Task 5: Finalize Step23 CI and exact PR boundary

**Files:**
- Modify: `.github/workflows/step23-canonical-action-contract.yml`

**Interfaces:**
- Consumes: all Step23 tests and existing Step22 regression suites.
- Produces: PR-context exact-file gate plus broad regression evidence for the final head.

- [ ] **Step 1: Expand the workflow dependency closure to match relevant regressions**

Replace the install step with:

```yaml
      - name: Install Step23 verification stack
        run: |
          python -m pip install pytest pytest-asyncio jsonschema PyYAML==6.0.3
          python -m pip install \
            -e contracts/python \
            -e hosts/autocad/sidecar \
            -e platform/semantic_runtime \
            -e platform/semantic_service \
            -e platform/semantic_mcp \
            -e providers/semantics/dsp_core \
            -e providers/semantics/ifc43 \
            -e providers/semantics/metro_v32 \
            -e providers/semantics/enterprise_mapping
```

This mirrors the already-proven Step22 broad regression closure and avoids a new dependency model.

- [ ] **Step 2: Add exact eight-file PR diff gate**

Add:

```yaml
      - name: Verify Step23 PR diff boundary
        if: github.event_name == 'pull_request'
        env:
          BASE_SHA: ${{ github.event.pull_request.base.sha }}
          HEAD_SHA: ${{ github.event.pull_request.head.sha }}
        run: |
          changed="$(git diff --name-only "$BASE_SHA...$HEAD_SHA")"
          printf '%s\n' "$changed"
          bad="$(printf '%s\n' "$changed" | grep -Ev '^(\.github/workflows/step23-canonical-action-contract\.yml|docs/superpowers/(specs/2026-08-29-step23-canonical-action-contract-design\.md|plans/2026-08-29-step23-canonical-action-contract\.md)|platform/orchestrator/src/design_orchestrator/(__init__|canonical_operations)\.py|tests/orchestrator/(test_canonical_operations|test_operation_resolver|test_step23_architecture)\.py)$' || true)"
          if [ -n "$bad" ]; then
            echo "Step23 changed files outside approved boundary:"
            printf '%s\n' "$bad"
            exit 1
          fi
          count="$(printf '%s\n' "$changed" | sed '/^$/d' | wc -l)"
          if [ "$count" -ne 8 ]; then
            echo "Step23 expected exactly 8 changed files, got $count"
            exit 1
          fi
```

Do not weaken this gate merely because implementation accidentally touches an additional production file.

- [ ] **Step 3: Add focused Step23 and D4 regression commands**

```yaml
      - name: Run Step23 canonical action tests
        run: pytest -q tests/orchestrator/test_canonical_operations.py
      - name: Run Step23 architecture guards
        run: pytest -q tests/orchestrator/test_step23_architecture.py
      - name: Run existing D4 operation resolver regression
        run: pytest -q tests/orchestrator/test_operation_resolver.py
      - name: Run Step22 progressive regression
        run: pytest -q tests/integration/test_step22_task_scoped_progressive.py
```

- [ ] **Step 4: Add Step21/22 semantic regression and broad Python suite**

Use:

```yaml
      - name: Run existing D4 to D5 freshness bridge
        run: pytest -q tests/semantic_runtime/test_d4_freshness_integration.py
      - name: Run progressive semantic runtime regression
        run: pytest -q tests/semantic_runtime/test_progressive_requirements.py
      - name: Run Step21 canonical projection regression
        run: |
          pytest -q \
            tests/integration/test_step21_d5_canonical_projection.py \
            tests/semantic_runtime/test_step21_architecture.py
      - name: Run relevant full Python regression
        run: |
          pytest -q --import-mode=importlib \
            contracts/python/tests \
            tests/contracts \
            tests/integration \
            tests/orchestrator \
            tests/semantic_runtime \
            tests/semantic_service \
            tests/semantic_mcp \
            tests/semantic_providers/dsp_core \
            tests/semantic_providers/ifc43 \
            tests/semantic_providers/metro_v32 \
            tests/semantic_providers/enterprise_mapping
```

- [ ] **Step 5: Run the final branch workflow and record exact counts**

For the final head, record the actual output counts for:

```text
Step23 canonical action tests
Step23 architecture guards
D4 operation resolver regression
Step22 progressive regression
D4→D5 freshness bridge
progressive semantic runtime regression
Step21 canonical projection regression
broad relevant Python regression
```

Do not copy expected counts from Step22; report only fresh Step23 workflow output.

- [ ] **Step 6: Commit the final CI gate**

```bash
git add .github/workflows/step23-canonical-action-contract.yml
git commit -m "ci(step23): verify canonical action contract"
```

---

### Task 6: Final verification, diff review, and Draft PR

**Files:**
- No new file paths beyond the frozen eight-file boundary.
- Update `docs/superpowers/plans/2026-08-29-step23-canonical-action-contract.md` only if execution evidence reveals a real plan correction that must be recorded.

**Interfaces:**
- Consumes: final Step23 branch head.
- Produces: reviewed Draft PR with current-head verification evidence; no merge.

- [ ] **Step 1: Compare the final branch against the exact base**

Run the repository compare equivalent of:

```bash
git diff --name-only 833503062d516c25baffae644de73f929164f473...HEAD
```

Expected exact set:

```text
.github/workflows/step23-canonical-action-contract.yml
docs/superpowers/plans/2026-08-29-step23-canonical-action-contract.md
docs/superpowers/specs/2026-08-29-step23-canonical-action-contract-design.md
platform/orchestrator/src/design_orchestrator/__init__.py
platform/orchestrator/src/design_orchestrator/canonical_operations.py
tests/orchestrator/test_canonical_operations.py
tests/orchestrator/test_operation_resolver.py
tests/orchestrator/test_step23_architecture.py
```

Expected production diff: exactly two orchestrator files and no `operation_resolver.py` modification.

- [ ] **Step 2: Review the production patch against the acceptance criteria**

Verify manually from the patch:

```text
CanonicalOperationDefinition has all frozen fields
SlotBindingClass has exactly five values
MOVE targets=CONTEXT
MOVE displacement=INTENT
MOVE canonical constraints empty
MOVE freshness exactly PLACEMENT/FRESH
MOVE effects PLACEMENT+GEOMETRY
coverage/assurance fields present
intent_input_schema only projects INTENT
no Host/provider imports or native routing identifiers
no D4 behavior change
no D6/D7/ProviderBinding/HostCommand code
```

- [ ] **Step 3: Run/confirm the final current-head CI**

Required current-head workflows/checks:

```text
Step23 canonical action contract = success
Operation resolver verification = success when triggered by the PR paths
```

If the existing Operation Resolver workflow exposes a new dependency-closure defect, debug the root cause first. Do not classify a workflow installation failure as a Step23 business-logic failure.

- [ ] **Step 4: Create a Draft PR**

Title:

```text
feat(step23): freeze canonical action contract
```

Body must state:

```text
Goal: platform-owned Canonical Action contract with typed slot ownership.
Production diff: canonical_operations.py + __init__.py only.
D4 production behavior unchanged; Step24 integration intentionally deferred.
MOVE: targets=CONTEXT, displacement=INTENT, PLACEMENT/FRESH, effects PLACEMENT+GEOMETRY.
No Host/D5/Semantic/ChangeSet/D6/ProviderBinding production changes.
TDD RED/GREEN evidence and final current-head CI counts.
Exact 8-file PR boundary.
```

Create it as Draft; do not mark Ready automatically if review evidence is still pending.

- [ ] **Step 5: Inspect PR-context CI and review feedback**

Confirm:

```text
head SHA matches the reviewed final commit
changed_files == 8
Step23 exact diff gate passes on pull_request context
all required current-head workflows are completed/success
no actionable review thread remains unresolved
```

- [ ] **Step 6: Stop before merge**

Completion of Step23 implementation means the PR is ready for review/merge decision. Merge requires a separate explicit user instruction such as:

```text
合并 PR #<n> 到 main
```

Do not merge under Inline Execution without that explicit authorization.

---

## Self-Review Checklist

Before implementation starts, verify this plan against the approved spec:

- Contract completeness: Tasks 2–3.
- Five typed slot classes: Task 2.
- Every top-level slot exactly classified: Task 3.
- Missing/unknown policy fail closed: Task 3.
- Intent-only projection: Task 3.
- MOVE frozen fixture: Task 2.
- Coverage/assurance metadata: Task 2.
- Defensive copying: Tasks 2 and 4.
- Provider isolation: Task 4.
- Step22 regression: Tasks 4–5.
- No D4 production integration: global constraint + Tasks 2/6.
- No D6/D7/ProviderBinding: global constraint + architecture guard.
- Exact approved file boundary: Task 5/6.
- Current-head broad regression: Task 5/6.

No implementation task may add `operation_resolver.py` production changes, Host production changes, Semantic production changes, ChangeSet changes, or ProviderBinding code without stopping for scope review.