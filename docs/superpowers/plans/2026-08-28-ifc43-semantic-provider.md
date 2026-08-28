# IFC4.3 Standard Semantic Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement `buildingSMART.ifc43@4.3.2.0` as DSP's authoritative `ifc:*` reference Semantic Provider, backed by a pinned IFC4X3_ADD2 source, deterministic immutable normalization, claim-level validation, and the existing Semantic Service / Semantic MCP contracts.

**Architecture:** Add an isolated Python package under `providers/semantics/ifc43` that depends on `semantic-service` and exactly `ifcopenshell==0.8.5`. The provider loads the exact IFC4X3_ADD2 schema and official Pset/Qto templates once, normalizes them into provider-owned immutable records, computes a canonical SHA-256 semantic hash with a golden regression lock, and serves VOCABULARY + claim-level VALIDATION while leaving PROJECTION marker-only. Platform core, D5, Semantic MCP, Host adapters, and Metro semantics remain provider-neutral.

**Tech Stack:** Python 3.11, `ifcopenshell==0.8.5`, dataclasses, `MappingProxyType`, canonical JSON + SHA-256, existing `semantic-service`, existing `semantic-mcp`, existing `dsp-core-semantic-provider`, pytest/pytest-asyncio, MCP Python SDK already pinned by `semantic-mcp`.

**Spec:** `docs/superpowers/specs/2026-08-28-ifc43-semantic-provider-design.md`

## Global Constraints

- Provider identity is exactly `buildingSMART.ifc43@4.3.2.0`.
- Provider type is exactly `STANDARD`.
- Namespace set is exactly `("ifc",)` and `ifc` authority is exactly `AUTHORITATIVE`.
- Capability set is exactly `{VOCABULARY, VALIDATION, PROJECTION}`; do not claim `MAPPING`.
- `PROJECTION` remains marker-only; PR #9 MUST NOT add `project_facts()` or a fact-batch payload.
- The authoritative source release is exactly `IFC4X3_ADD2 / (4, 3, 2, 0)`.
- Implementation dependency is exactly `ifcopenshell==0.8.5`; it is an inspection engine, not semantic authority.
- Production provider code may import `semantic_service` and `ifcopenshell`; it MUST NOT import `semantic_runtime`, `semantic_mcp`, DSP Core implementation code, Metro provider code, enterprise provider code, or Host-native packages.
- Existing `platform/semantic_service`, `platform/semantic_runtime`, and `platform/semantic_mcp` production Python modules MUST NOT be modified for PR #9.
- Runtime vocabulary/validation queries MUST NOT perform network I/O.
- Machine-semantic `content_hash` includes normalized schema/Pset/Qto semantics and excludes descriptions, examples, URLs, locale text, source iteration order, object reprs, and the IfcOpenShell package version by itself.
- A golden `content_hash` for the first intentionally reviewed normalized IFC4.3.2.0 catalog MUST be frozen and verified in every focused CI run; CI/tests MUST NOT rewrite the expected value.
- Canonical lookup is exact and case-sensitive. No fuzzy matching, alias repair, or Metro substitution is allowed.
- Top-level term IDs use `ifc:<standard-name>`; direct attributes/Pset properties/Qto quantities/enum literals use owner-qualified IDs such as `ifc:IfcWall.PredefinedType`, `ifc:Pset_WallCommon.FireRating`, and `ifc:IfcWallTypeEnum.SOLIDWALL`.
- Inherited attributes keep the canonical identity of their declaring owner, e.g. `ifc:IfcRoot.Name`; do not manufacture `ifc:IfcWall.Name`.
- Metro V3.2 is a PR #9 conformance/reference corpus only. `PsetProj_*`, `QtoProj_*`, P-M/P-C/P-R, IDS, Metro mapping, and Metro engineering rules remain PR #10 scope.
- Claim-level VALIDATION MUST return deterministic findings and MUST return `NOT_APPLICABLE` rather than guess when complete IFC model/file context is required.
- Complete STEP-file validation, EXPRESS WHERE evaluation, inverse-graph consistency, geometry, Alignment continuity, clearance/clash, IDS, and georeferencing-file validation are non-goals.
- Where the design/plan specifies implementation details not frozen by main Spec v0.6 (for example IfcOpenShell 0.8.5, golden hash mechanics, and member-ID encoding), those are PR #9 implementation decisions and MUST NOT be interpreted as amendments to the main Spec.
- Implementation MUST follow RED -> GREEN TDD and commit each independently reviewable task.

---

## File Structure

Create:

```text
providers/semantics/ifc43/
  pyproject.toml
  README.md
  src/ifc43_semantic_provider/
    __init__.py          # curated public API only
    errors.py            # provider-local fail-closed errors
    source.py            # exact IFC4X3_ADD2 + official Pset/Qto source loader
    model.py             # immutable normalized type/term records
    normalization.py     # IfcOpenShell schema/Pset/Qto -> provider records
    hashing.py           # canonical normalization + SHA-256
    catalog.py           # immutable index, inherited-schema projection, content hash
    golden.py            # intentionally frozen expected catalog hash
    validation.py        # claim-level IFC legality/type/enum validation
    provider.py          # manifest, provenance, vocabulary + validation provider

tests/semantic_providers/ifc43/
  test_source_version.py
  test_normalization.py
  test_pset_qto.py
  test_catalog.py
  test_term_identity.py
  test_provider_manifest.py
  test_validation.py
  test_service_integration.py
  test_mcp_integration.py
  test_metro_reference_cases.py
  test_ifc43_architecture.py
.github/workflows/ifc43-semantic-provider.yml
```

No existing production Python module is modified. The only existing documentation allowed to change is the approved IFC4.3 design/plan record if closeout evidence or clarification is appended.

---

### Task 1: Package Boundary, Provider Errors, and Exact IFC4X3_ADD2 Source Gate

**Files:**
- Create: `providers/semantics/ifc43/pyproject.toml`
- Create: `providers/semantics/ifc43/src/ifc43_semantic_provider/errors.py`
- Create: `providers/semantics/ifc43/src/ifc43_semantic_provider/source.py`
- Create: `tests/semantic_providers/ifc43/test_source_version.py`

**Interfaces:**
- Consumes: `ifcopenshell.file(schema_version=...)`, `ifcopenshell.schema_by_name(schema_version=...)`, `ifcopenshell.util.pset.get_template(schema_identifier)`.
- Produces: `IFC_SCHEMA_IDENTIFIER`, `IFC_SCHEMA_VERSION`, `Ifc43Source`, `load_ifc43_source()`, and provider-local error types.

- [ ] **Step 1: Create package metadata and write the failing exact-source tests**

Create `providers/semantics/ifc43/pyproject.toml`:

```toml
[project]
name = "ifc43-semantic-provider"
version = "4.3.2.0"
description = "buildingSMART IFC4.3.2.0 reference Semantic Provider for DSP."
requires-python = ">=3.11"
dependencies = [
    "semantic-service>=0.1.0",
    "ifcopenshell==0.8.5",
]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
where = ["src"]
```

Create `tests/semantic_providers/ifc43/test_source_version.py`:

```python
from types import SimpleNamespace

import pytest

from ifc43_semantic_provider.errors import Ifc43SourceVersionError
from ifc43_semantic_provider.source import (
    IFC_SCHEMA_IDENTIFIER,
    IFC_SCHEMA_VERSION,
    load_ifc43_source,
)


def test_pinned_ifcopenshell_exposes_exact_ifc4320_source():
    source = load_ifc43_source()
    assert source.schema_identifier == "IFC4X3_ADD2"
    assert source.schema_version == (4, 3, 2, 0)
    assert source.schema.name() == "IFC4X3_ADD2"
    assert source.psets is not None


def test_source_loader_rejects_mismatched_probe_identifier():
    bad_probe = SimpleNamespace(
        schema_identifier="IFC4X3_ADD1",
        schema_version=(4, 3, 1, 0),
    )
    with pytest.raises(Ifc43SourceVersionError, match="IFC4X3_ADD2"):
        load_ifc43_source(
            probe_factory=lambda **_: bad_probe,
            schema_loader=lambda **_: None,
            pset_loader=lambda _: None,
        )


def test_source_loader_rejects_schema_definition_name_drift():
    good_probe = SimpleNamespace(
        schema_identifier=IFC_SCHEMA_IDENTIFIER,
        schema_version=IFC_SCHEMA_VERSION,
    )
    bad_schema = SimpleNamespace(name=lambda: "IFC4X3_ADD1")
    with pytest.raises(Ifc43SourceVersionError, match="schema definition"):
        load_ifc43_source(
            probe_factory=lambda **_: good_probe,
            schema_loader=lambda **_: bad_schema,
            pset_loader=lambda _: object(),
        )


def test_pset_loader_receives_exact_schema_identifier():
    calls = []
    good_probe = SimpleNamespace(
        schema_identifier=IFC_SCHEMA_IDENTIFIER,
        schema_version=IFC_SCHEMA_VERSION,
    )
    good_schema = SimpleNamespace(name=lambda: IFC_SCHEMA_IDENTIFIER)
    load_ifc43_source(
        probe_factory=lambda **_: good_probe,
        schema_loader=lambda **_: good_schema,
        pset_loader=lambda identifier: calls.append(identifier) or object(),
    )
    assert calls == ["IFC4X3_ADD2"]
```

- [ ] **Step 2: Run the focused test and confirm RED**

Run:

```bash
python -m pip install -e platform/semantic_service -e providers/semantics/ifc43
pytest -q tests/semantic_providers/ifc43/test_source_version.py
```

Expected: import/collection failure because `ifc43_semantic_provider.source` and `errors` do not exist.

- [ ] **Step 3: Implement provider-local errors**

Create `errors.py`:

```python
class Ifc43ProviderError(ValueError):
    """Base error for deterministic IFC4.3 provider failures."""


class Ifc43SourceVersionError(Ifc43ProviderError):
    """The implementation source is not exactly IFC4X3_ADD2 / 4.3.2.0."""


class Ifc43CatalogBuildError(Ifc43ProviderError):
    """The pinned source could not be normalized deterministically."""


class Ifc43TermNotFoundError(Ifc43ProviderError, KeyError):
    """An exact canonical IFC term is not present."""


class Ifc43ValidationError(Ifc43ProviderError):
    """Claim validator execution/configuration failed."""
```

- [ ] **Step 4: Implement the exact source loader**

Create `source.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import ifcopenshell
from ifcopenshell.util.pset import get_template

from .errors import Ifc43SourceVersionError

IFC_SCHEMA_IDENTIFIER = "IFC4X3_ADD2"
IFC_SCHEMA_VERSION = (4, 3, 2, 0)


@dataclass(frozen=True, slots=True)
class Ifc43Source:
    schema_identifier: str
    schema_version: tuple[int, int, int, int]
    schema: object
    psets: object


def load_ifc43_source(
    *,
    probe_factory: Callable[..., object] = ifcopenshell.file,
    schema_loader: Callable[..., object] = ifcopenshell.schema_by_name,
    pset_loader: Callable[[str], object] = get_template,
) -> Ifc43Source:
    probe = probe_factory(schema_version=IFC_SCHEMA_VERSION)
    identifier = getattr(probe, "schema_identifier", None)
    version = getattr(probe, "schema_version", None)
    if identifier != IFC_SCHEMA_IDENTIFIER or version != IFC_SCHEMA_VERSION:
        raise Ifc43SourceVersionError(
            f"expected {IFC_SCHEMA_IDENTIFIER} / {IFC_SCHEMA_VERSION}, "
            f"got {identifier!r} / {version!r}"
        )

    schema = schema_loader(schema_version=IFC_SCHEMA_VERSION)
    schema_name = schema.name()
    if schema_name != IFC_SCHEMA_IDENTIFIER:
        raise Ifc43SourceVersionError(
            f"schema definition must be {IFC_SCHEMA_IDENTIFIER}; got {schema_name!r}"
        )

    psets = pset_loader(IFC_SCHEMA_IDENTIFIER)
    if psets is None:
        raise Ifc43SourceVersionError("official Pset/Qto template source is unavailable")
    return Ifc43Source(identifier, version, schema, psets)
```

Do not fall back to `IFC4X3`, another addendum/corrigendum, a floating latest schema, or a Metro file.

- [ ] **Step 5: Run source tests and confirm GREEN**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_source_version.py
```

Expected: all Task 1 tests pass.

- [ ] **Step 6: Commit Task 1**

```bash
git add providers/semantics/ifc43/pyproject.toml \
        providers/semantics/ifc43/src/ifc43_semantic_provider/errors.py \
        providers/semantics/ifc43/src/ifc43_semantic_provider/source.py \
        tests/semantic_providers/ifc43/test_source_version.py
git commit -m "feat(semantic): gate IFC4.3 provider source"
```

---

### Task 2: Immutable Machine Model, Type Expressions, and Schema Declaration Normalization

**Files:**
- Create: `providers/semantics/ifc43/src/ifc43_semantic_provider/model.py`
- Create: `providers/semantics/ifc43/src/ifc43_semantic_provider/hashing.py`
- Create: `providers/semantics/ifc43/src/ifc43_semantic_provider/normalization.py`
- Create: `tests/semantic_providers/ifc43/test_normalization.py`

**Interfaces:**
- Consumes: `Ifc43Source.schema`, IfcOpenShell declaration/entity/attribute/type reflection APIs.
- Produces: immutable `TypeExpression`, `IfcTermRecord`, `normalize_parameter_type()`, `normalize_schema_declarations()`, `canonical_hash()`.

- [ ] **Step 1: Write failing normalization tests against real IFC4X3_ADD2 declarations**

Create `test_normalization.py`:

```python
from ifc43_semantic_provider.normalization import normalize_schema_declarations
from ifc43_semantic_provider.source import load_ifc43_source


def records_by_id():
    return {
        item.term_id: item
        for item in normalize_schema_declarations(load_ifc43_source().schema)
    }


def test_entity_and_relationship_are_normalized_with_distinct_kinds():
    records = records_by_id()
    assert records["ifc:IfcWall"].kind == "ENTITY"
    assert records["ifc:IfcRelAggregates"].kind == "RELATIONSHIP"
    assert records["ifc:IfcWall"].machine_schema["supertype"] == "ifc:IfcBuildingElement"


def test_direct_attribute_uses_owner_qualified_identity():
    records = records_by_id()
    attr = records["ifc:IfcWall.PredefinedType"]
    assert attr.kind == "ATTRIBUTE"
    assert attr.machine_schema["owner"] == "ifc:IfcWall"
    assert attr.machine_schema["declared_type"]["kind"] == "NAMED"
    assert attr.machine_schema["declared_type"]["name"] == "ifc:IfcWallTypeEnum"


def test_enum_literals_are_owner_qualified_terms():
    records = records_by_id()
    enum = records["ifc:IfcWallTypeEnum"]
    literal = records["ifc:IfcWallTypeEnum.SOLIDWALL"]
    assert enum.kind == "ENUM"
    assert "ifc:IfcWallTypeEnum.SOLIDWALL" in enum.machine_schema["literals"]
    assert literal.kind == "ENUM_LITERAL"
    assert literal.machine_schema == {
        "owner": "ifc:IfcWallTypeEnum",
        "value": "SOLIDWALL",
    }


def test_select_and_defined_type_are_normalized():
    records = records_by_id()
    assert records["ifc:IfcValue"].kind == "SELECT"
    assert records["ifc:IfcLengthMeasure"].kind == "DEFINED_TYPE"
```

- [ ] **Step 2: Run normalization tests and confirm RED**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_normalization.py
```

Expected: import failure because `model`, `hashing`, and `normalization` are missing.

- [ ] **Step 3: Implement canonical hashing**

Create `hashing.py`:

```python
from __future__ import annotations

from collections.abc import Mapping, Sequence, Set
from hashlib import sha256
import json


def _normalize(value: object) -> object:
    if isinstance(value, Mapping):
        return {
            str(key): _normalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Set) and not isinstance(value, (str, bytes, bytearray)):
        values = [_normalize(item) for item in value]
        return sorted(
            values,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [_normalize(item) for item in value]
    return value


def canonical_hash(payload: object) -> str:
    encoded = json.dumps(
        _normalize(payload),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()
```

- [ ] **Step 4: Implement immutable normalized records**

Create `model.py`:

```python
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType


def freeze(item: object) -> object:
    if isinstance(item, Mapping):
        return MappingProxyType({str(k): freeze(v) for k, v in item.items()})
    if isinstance(item, (tuple, list)):
        return tuple(freeze(v) for v in item)
    if isinstance(item, (set, frozenset)):
        return frozenset(freeze(v) for v in item)
    return item


def plain(item: object) -> object:
    if isinstance(item, Mapping):
        return {str(k): plain(v) for k, v in item.items()}
    if isinstance(item, (tuple, list)):
        return [plain(v) for v in item]
    if isinstance(item, (set, frozenset)):
        return sorted((plain(v) for v in item), key=repr)
    return item


@dataclass(frozen=True, slots=True)
class TypeExpression:
    kind: str
    name: str | None = None
    aggregate_kind: str | None = None
    lower: int | None = None
    upper: int | None = None
    element: "TypeExpression | None" = None

    def payload(self) -> dict[str, object]:
        return {
            "kind": self.kind,
            "name": self.name,
            "aggregate_kind": self.aggregate_kind,
            "lower": self.lower,
            "upper": self.upper,
            "element": self.element.payload() if self.element else None,
        }


@dataclass(frozen=True, slots=True)
class IfcTermRecord:
    term_id: str
    kind: str
    machine_schema: Mapping[str, object]
    description: str

    def __post_init__(self) -> None:
        if not self.term_id.startswith("ifc:"):
            raise ValueError("IFC term_id must use ifc: namespace")
        object.__setattr__(self, "machine_schema", freeze(self.machine_schema))

    def machine_payload(self) -> dict[str, object]:
        return {
            "term_id": self.term_id,
            "kind": self.kind,
            "schema": plain(self.machine_schema),
        }
```

Descriptions are presentation-only because `machine_payload()` excludes them.

- [ ] **Step 5: Implement recursive type normalization and declaration expansion**

Create `normalization.py` with:

```python
from __future__ import annotations

from ifcopenshell.ifcopenshell_wrapper import simple_type

from .errors import Ifc43CatalogBuildError
from .model import IfcTermRecord, TypeExpression

_SIMPLE_NAMES = {
    simple_type.binary_type: "BINARY",
    simple_type.boolean_type: "BOOLEAN",
    simple_type.integer_type: "INTEGER",
    simple_type.logical_type: "LOGICAL",
    simple_type.number_type: "NUMBER",
    simple_type.real_type: "REAL",
    simple_type.string_type: "STRING",
}


def normalize_parameter_type(raw: object) -> TypeExpression:
    aggregation = raw.as_aggregation_type()
    if aggregation is not None:
        upper = aggregation.bound2()
        return TypeExpression(
            kind="AGGREGATION",
            aggregate_kind=aggregation.type_of_aggregation_string(),
            lower=aggregation.bound1(),
            upper=None if upper == -1 else upper,
            element=normalize_parameter_type(aggregation.type_of_element()),
        )

    named = raw.as_named_type()
    if named is not None:
        return TypeExpression(kind="NAMED", name=f"ifc:{named.declared_type().name()}")

    primitive = raw.as_simple_type()
    if primitive is not None:
        try:
            name = _SIMPLE_NAMES[primitive.declared_type()]
        except KeyError as exc:
            raise Ifc43CatalogBuildError("unsupported IFC simple type") from exc
        return TypeExpression(kind="SIMPLE", name=name)

    raise Ifc43CatalogBuildError("unsupported IFC parameter type")
```

Implement `normalize_schema_declarations(schema) -> tuple[IfcTermRecord, ...]` with these exact rules:

- iterate `schema.declarations()` sorted by `declaration.name()`;
- entity declarations become `ENTITY`, except names starting with `IfcRel`, which become `RELATIONSHIP`;
- entity machine schema is `{"supertype": canonical-or-None, "abstract": bool, "direct_members": sorted tuple}`;
- pair each direct `entity.attributes()` item with the corresponding `entity.derived()` flag and emit one `ATTRIBUTE` record per direct attribute;
- attribute machine schema is `owner`, normalized `declared_type`, `optional`, and `derived`;
- enumeration declaration emits one `ENUM` record plus one owner-qualified `ENUM_LITERAL` record per `enumeration_items()` value;
- select declaration emits one `SELECT` record whose `members` are sorted canonical declaration IDs from `select_list()`;
- type declaration emits one `DEFINED_TYPE` record with `underlying=normalize_parameter_type(declared_type()).payload()`;
- descriptions are deterministic local strings such as `IFC4X3_ADD2 ENTITY IfcWall.` and never fetched over the network;
- duplicate term IDs are accepted only when machine payloads are identical; conflicting duplicates raise `Ifc43CatalogBuildError`.

For a direct attribute use:

```python
IfcTermRecord(
    term_id=f"ifc:{entity.name()}.{attribute.name()}",
    kind="ATTRIBUTE",
    machine_schema={
        "owner": f"ifc:{entity.name()}",
        "declared_type": normalize_parameter_type(attribute.type_of_attribute()).payload(),
        "optional": attribute.optional(),
        "derived": derived,
    },
    description=f"IFC4X3_ADD2 ATTRIBUTE {entity.name()}.{attribute.name()}.",
)
```

- [ ] **Step 6: Run normalization tests and confirm GREEN**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_normalization.py
```

Expected: all Task 2 tests pass.

- [ ] **Step 7: Commit Task 2**

```bash
git add providers/semantics/ifc43/src/ifc43_semantic_provider/model.py \
        providers/semantics/ifc43/src/ifc43_semantic_provider/hashing.py \
        providers/semantics/ifc43/src/ifc43_semantic_provider/normalization.py \
        tests/semantic_providers/ifc43/test_normalization.py
git commit -m "feat(semantic): normalize IFC4.3 schema declarations"
```

---

### Task 3: Official buildingSMART Pset/Qto Normalization

**Files:**
- Modify: `providers/semantics/ifc43/src/ifc43_semantic_provider/normalization.py`
- Create: `tests/semantic_providers/ifc43/test_pset_qto.py`

**Interfaces:**
- Consumes: `Ifc43Source.psets`, `ifcopenshell.util.pset.get_pset_template_type()`, `parse_applicable_entity()`.
- Produces: `normalize_pset_qto(psets) -> tuple[IfcTermRecord, ...]` with official PSET/QTO/member records only.

- [ ] **Step 1: Write failing official Pset/Qto tests**

Create `test_pset_qto.py`:

```python
from ifc43_semantic_provider.normalization import normalize_pset_qto
from ifc43_semantic_provider.source import load_ifc43_source


def pset_records():
    source = load_ifc43_source()
    return {item.term_id: item for item in normalize_pset_qto(source.psets)}


def test_official_wall_pset_and_qto_exist():
    records = pset_records()
    assert records["ifc:Pset_WallCommon"].kind == "PSET"
    assert records["ifc:Qto_WallBaseQuantities"].kind == "QTO"
    assert "ifc:Pset_WallCommon.FireRating" in records
    assert "ifc:Qto_WallBaseQuantities.Width" in records


def test_project_pset_is_not_part_of_official_ifc_catalog():
    records = pset_records()
    assert "ifc:PsetProj_WallDesign" not in records


def test_pset_member_machine_type_is_preserved():
    records = pset_records()
    load_bearing = records["ifc:Pset_WallCommon.LoadBearing"]
    assert load_bearing.kind == "PSET_PROPERTY"
    assert load_bearing.machine_schema["owner"] == "ifc:Pset_WallCommon"
    assert load_bearing.machine_schema["primary_measure_type"] == "IfcBoolean"
```

- [ ] **Step 2: Run Pset/Qto tests and confirm RED**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_pset_qto.py
```

Expected: import/attribute failure because `normalize_pset_qto()` is missing.

- [ ] **Step 3: Implement deterministic official template traversal**

Add:

```python
from ifcopenshell.util.pset import get_pset_template_type, parse_applicable_entity


def _template_files(psets: object) -> tuple[object, ...]:
    return tuple(getattr(psets, "templates", ()))


def _applicability(template: object) -> tuple[dict[str, object], ...]:
    raw = getattr(template, "ApplicableEntity", None) or ""
    values = []
    for item in parse_applicable_entity(raw):
        values.append(
            {
                "ifc_class": item.ifc_class,
                "predefined_type": item.predefined_type,
                "performance_history": item.performance_history,
            }
        )
    return tuple(sorted(values, key=repr))


def _enum_values(property_template: object) -> tuple[str, ...]:
    enumerators = getattr(property_template, "Enumerators", None)
    if enumerators is None:
        return ()
    values = getattr(enumerators, "EnumerationValues", ()) or ()
    return tuple(sorted(str(getattr(value, "wrappedValue", value)) for value in values))


def _unit_ref(property_template: object) -> dict[str, object] | None:
    unit = getattr(property_template, "PrimaryUnit", None)
    if unit is None:
        return None
    return {
        "ifc_class": unit.is_a(),
        "UnitType": getattr(unit, "UnitType", None),
        "Name": getattr(unit, "Name", None),
        "Prefix": getattr(unit, "Prefix", None),
    }
```

Implement `normalize_pset_qto(psets)` with these rules:

1. iterate every `IfcPropertySetTemplate` in every `psets.templates` file;
2. classify using `get_pset_template_type(template)` and ignore `None`;
3. top-level term ID is `ifc:<Name>`, kind `PSET` or `QTO`, with normalized applicability;
4. iterate `template.HasPropertyTemplates or ()`, sorted by `Name`;
5. member kind is `PSET_PROPERTY` or `QTO_QUANTITY`;
6. member schema is `owner`, `template_type`, string-or-None `primary_measure_type`, `enum_values`, and normalized `unit`;
7. identical duplicate records are deduped; conflicting duplicates raise `Ifc43CatalogBuildError`;
8. records beginning `ifc:PsetProj_` or `ifc:QtoProj_` are rejected from this standard catalog.

- [ ] **Step 4: Run Pset/Qto tests and confirm GREEN**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_pset_qto.py
```

Expected: all Task 3 tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add providers/semantics/ifc43/src/ifc43_semantic_provider/normalization.py \
        tests/semantic_providers/ifc43/test_pset_qto.py
git commit -m "feat(semantic): normalize IFC4.3 Pset and Qto semantics"
```

---

### Task 4: Immutable Catalog, Inherited Member Projection, and Golden Semantic Hash

**Files:**
- Create: `providers/semantics/ifc43/src/ifc43_semantic_provider/catalog.py`
- Create: `providers/semantics/ifc43/src/ifc43_semantic_provider/golden.py`
- Create: `tests/semantic_providers/ifc43/test_catalog.py`
- Create: `tests/semantic_providers/ifc43/test_term_identity.py`

**Interfaces:**
- Consumes: `normalize_schema_declarations()`, `normalize_pset_qto()`, `canonical_hash()`.
- Produces: `Ifc43Catalog`, `build_ifc43_catalog()`, `IFC43_CATALOG`, `EXPECTED_IFC43_CONTENT_HASH`.

- [ ] **Step 1: Write failing synthetic hash and real exact-identity tests**

Create `test_catalog.py`:

```python
from dataclasses import replace

from ifc43_semantic_provider.catalog import Ifc43Catalog
from ifc43_semantic_provider.model import IfcTermRecord


def term(term_id, schema, description="presentation"):
    return IfcTermRecord(term_id, "DEFINED_TYPE", schema, description)


def test_record_order_does_not_change_content_hash():
    a = term("ifc:IfcA", {"underlying": "STRING"})
    b = term("ifc:IfcB", {"underlying": "REAL"})
    forward = Ifc43Catalog("IFC4X3_ADD2", (4, 3, 2, 0), (a, b))
    reverse = Ifc43Catalog("IFC4X3_ADD2", (4, 3, 2, 0), (b, a))
    assert forward.content_hash == reverse.content_hash


def test_presentation_change_does_not_change_content_hash():
    a = term("ifc:IfcA", {"underlying": "STRING"})
    changed = replace(a, description="different presentation")
    assert Ifc43Catalog("IFC4X3_ADD2", (4, 3, 2, 0), (a,)).content_hash == Ifc43Catalog(
        "IFC4X3_ADD2", (4, 3, 2, 0), (changed,)
    ).content_hash


def test_machine_change_changes_content_hash():
    a = term("ifc:IfcA", {"underlying": "STRING"})
    changed = term("ifc:IfcA", {"underlying": "REAL"})
    assert Ifc43Catalog("IFC4X3_ADD2", (4, 3, 2, 0), (a,)).content_hash != Ifc43Catalog(
        "IFC4X3_ADD2", (4, 3, 2, 0), (changed,)
    ).content_hash
```

Create `test_term_identity.py`:

```python
from ifc43_semantic_provider.catalog import build_ifc43_catalog
from ifc43_semantic_provider.source import load_ifc43_source


def catalog():
    return build_ifc43_catalog(load_ifc43_source())


def test_inherited_name_keeps_ifcroot_owner_identity():
    current = catalog()
    wall = current.schema_for("ifc:IfcWall")
    assert "ifc:IfcRoot.Name" in wall["inherited_members"]
    assert "ifc:IfcWall.Name" not in current.term_ids


def test_lookup_is_exact_and_case_sensitive():
    current = catalog()
    assert current.get("ifc:IfcWall").term_id == "ifc:IfcWall"
    for invalid in ("ifc:ifcwall", "IFC:IfcWall", "ifc:IfcTunnel"):
        assert invalid not in current.term_ids
```

- [ ] **Step 2: Run catalog/identity tests and confirm RED**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_catalog.py \
          tests/semantic_providers/ifc43/test_term_identity.py
```

Expected: import failure because `catalog.py` does not exist.

- [ ] **Step 3: Implement immutable catalog and inherited-member projection**

Create `catalog.py`:

```python
from __future__ import annotations

from types import MappingProxyType

from .errors import Ifc43CatalogBuildError, Ifc43TermNotFoundError
from .hashing import canonical_hash
from .model import IfcTermRecord, freeze, plain
from .normalization import normalize_pset_qto, normalize_schema_declarations
from .source import Ifc43Source, load_ifc43_source


class Ifc43Catalog:
    def __init__(
        self,
        schema_identifier: str,
        schema_version: tuple[int, int, int, int],
        records: tuple[IfcTermRecord, ...],
    ) -> None:
        ordered = tuple(sorted(records, key=lambda item: item.term_id))
        ids = tuple(item.term_id for item in ordered)
        if len(ids) != len(set(ids)):
            raise Ifc43CatalogBuildError("duplicate IFC term_id")
        self._schema_identifier = schema_identifier
        self._schema_version = schema_version
        self._records = ordered
        self._by_id = MappingProxyType({item.term_id: item for item in ordered})
        self._content_hash = canonical_hash(
            {
                "schema_identifier": schema_identifier,
                "schema_version": list(schema_version),
                "terms": [item.machine_payload() for item in ordered],
            }
        )

    @property
    def term_ids(self) -> tuple[str, ...]:
        return tuple(self._by_id)

    @property
    def content_hash(self) -> str:
        return self._content_hash

    def get(self, term_id: str) -> IfcTermRecord:
        try:
            return self._by_id[term_id]
        except KeyError as exc:
            raise Ifc43TermNotFoundError(term_id) from exc

    def schema_for(self, term_id: str):
        record = self.get(term_id)
        schema = plain(record.machine_schema)
        if record.kind not in {"ENTITY", "RELATIONSHIP"}:
            return freeze(schema)

        inherited = []
        supertype = schema.get("supertype")
        while supertype:
            parent = self.get(supertype)
            parent_schema = plain(parent.machine_schema)
            inherited.extend(parent_schema.get("direct_members", ()))
            supertype = parent_schema.get("supertype")
        schema["inherited_members"] = sorted(set(inherited))
        return freeze(schema)


def build_ifc43_catalog(source: Ifc43Source) -> Ifc43Catalog:
    records = normalize_schema_declarations(source.schema) + normalize_pset_qto(source.psets)
    return Ifc43Catalog(source.schema_identifier, source.schema_version, records)
```

- [ ] **Step 4: Run catalog/identity tests and confirm GREEN before golden lock**

Run the Task 4 pytest command. Expected: all current tests pass.

- [ ] **Step 5: Compute and manually inspect the first normalized catalog hash**

Run:

```bash
python - <<'PY'
from ifc43_semantic_provider.catalog import build_ifc43_catalog
from ifc43_semantic_provider.source import load_ifc43_source

catalog = build_ifc43_catalog(load_ifc43_source())
print("term_count=", len(catalog.term_ids))
print("content_hash=", catalog.content_hash)
for term_id in (
    "ifc:IfcWall",
    "ifc:IfcWall.PredefinedType",
    "ifc:IfcWallTypeEnum.SOLIDWALL",
    "ifc:Pset_WallCommon",
    "ifc:Pset_WallCommon.FireRating",
    "ifc:Qto_WallBaseQuantities.Width",
):
    print(term_id, catalog.get(term_id).kind)
PY
```

Expected: every named reference term resolves and `content_hash` is one lowercase 64-hex value. Review the term count and reference records. If any reference fact is wrong, fix normalization and repeat before freezing the hash.

- [ ] **Step 6: After that explicit review, perform the one-time initial golden freeze**

Run this only after Step 5 has been reviewed:

```bash
HASH="$(python - <<'PY'
from ifc43_semantic_provider.catalog import build_ifc43_catalog
from ifc43_semantic_provider.source import load_ifc43_source
print(build_ifc43_catalog(load_ifc43_source()).content_hash)
PY
)"
test "${#HASH}" -eq 64
printf 'EXPECTED_IFC43_CONTENT_HASH = "%s"\n' "$HASH" \
  > providers/semantics/ifc43/src/ifc43_semantic_provider/golden.py
```

This command is only the initial reviewed freeze. No test, CI job, package import, or future update script may rewrite `golden.py` automatically.

Append to `test_catalog.py`:

```python
from ifc43_semantic_provider.catalog import build_ifc43_catalog
from ifc43_semantic_provider.golden import EXPECTED_IFC43_CONTENT_HASH
from ifc43_semantic_provider.source import load_ifc43_source


def test_exact_ifc4320_catalog_matches_reviewed_golden_hash():
    actual = build_ifc43_catalog(load_ifc43_source()).content_hash
    assert actual == EXPECTED_IFC43_CONTENT_HASH
```

Then add to the bottom of `catalog.py`:

```python
from .golden import EXPECTED_IFC43_CONTENT_HASH

IFC43_CATALOG = build_ifc43_catalog(load_ifc43_source())
if IFC43_CATALOG.content_hash != EXPECTED_IFC43_CONTENT_HASH:
    raise Ifc43CatalogBuildError(
        "IFC4.3.2.0 normalized catalog content hash drifted from reviewed golden hash"
    )
```

- [ ] **Step 7: Re-run Task 4 tests and confirm the golden lock is GREEN**

Run the Task 4 pytest command. Expected: all pass including the real-corpus golden check.

- [ ] **Step 8: Commit Task 4**

```bash
git add providers/semantics/ifc43/src/ifc43_semantic_provider/catalog.py \
        providers/semantics/ifc43/src/ifc43_semantic_provider/golden.py \
        tests/semantic_providers/ifc43/test_catalog.py \
        tests/semantic_providers/ifc43/test_term_identity.py
git commit -m "feat(semantic): add immutable IFC4.3 catalog"
```

---

### Task 5: IFC4.3 Provider Manifest, Vocabulary Surface, Provenance, and Curated API

**Files:**
- Create: `providers/semantics/ifc43/src/ifc43_semantic_provider/provider.py`
- Create: `providers/semantics/ifc43/src/ifc43_semantic_provider/__init__.py`
- Create: `tests/semantic_providers/ifc43/test_provider_manifest.py`

**Interfaces:**
- Consumes: existing `semantic_service` manifest/provider DTOs and `IFC43_CATALOG`.
- Produces: `Ifc43SemanticProvider`, `IFC43_PROVIDER`, exact VOCABULARY methods and exact manifest/provenance. Registry acceptance is intentionally tested only after Task 6 adds `validate_claim()`.

- [ ] **Step 1: Write failing direct manifest/vocabulary tests**

Create `test_provider_manifest.py`:

```python
from semantic_service import AuthorityMode, ProviderType, SemanticCapability

from ifc43_semantic_provider import IFC43_CATALOG, IFC43_PROVIDER
from ifc43_semantic_provider.errors import Ifc43TermNotFoundError


def test_manifest_matches_main_spec_v06_ifc_provider_identity():
    manifest = IFC43_PROVIDER.manifest
    assert manifest.provider_id == "buildingSMART.ifc43"
    assert manifest.provider_type is ProviderType.STANDARD
    assert manifest.version == "4.3.2.0"
    assert manifest.content_hash == IFC43_CATALOG.content_hash
    assert manifest.namespaces == ("ifc",)
    assert manifest.capabilities == frozenset(
        {
            SemanticCapability.VOCABULARY,
            SemanticCapability.VALIDATION,
            SemanticCapability.PROJECTION,
        }
    )
    assert len(manifest.authority) == 1
    assert manifest.authority[0].namespace == "ifc"
    assert manifest.authority[0].mode is AuthorityMode.AUTHORITATIVE
    assert manifest.requires == ()


def test_vocab_results_carry_exact_pinned_provenance():
    resolved = IFC43_PROVIDER.resolve_term("ifc:IfcWall")
    assert resolved.term_id == "ifc:IfcWall"
    assert resolved.kind == "ENTITY"
    assert resolved.provenance.provider_id == "buildingSMART.ifc43"
    assert resolved.provenance.version == "4.3.2.0"
    assert resolved.provenance.content_hash == IFC43_CATALOG.content_hash


def test_entity_schema_exposes_direct_and_inherited_members():
    schema = IFC43_PROVIDER.get_term_schema("ifc:IfcWall").schema
    assert "ifc:IfcWall.PredefinedType" in schema["direct_members"]
    assert "ifc:IfcRoot.Name" in schema["inherited_members"]


def test_provider_does_not_claim_mapping_or_concrete_projection_method():
    assert SemanticCapability.MAPPING not in IFC43_PROVIDER.manifest.capabilities
    assert not hasattr(IFC43_PROVIDER, "find_mappings")
    assert not hasattr(IFC43_PROVIDER, "project_facts")


def test_invalid_case_nonexistent_and_project_terms_fail_exactly():
    for term_id in ("ifc:ifcwall", "ifc:IfcTunnel", "ifc:PsetProj_WallDesign"):
        try:
            IFC43_PROVIDER.resolve_term(term_id)
        except Ifc43TermNotFoundError:
            continue
        raise AssertionError(f"unexpected resolution: {term_id}")
```

- [ ] **Step 2: Run direct provider tests and confirm RED**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_provider_manifest.py
```

Expected: import failure because `provider.py` / curated API are absent.

- [ ] **Step 3: Implement manifest, provenance, vocabulary methods, and direct singleton**

Create `provider.py`:

```python
from semantic_service import (
    AuthorityMode,
    NamespaceAuthority,
    ProviderProvenance,
    ProviderType,
    ResolvedTerm,
    SemanticCapability,
    SemanticProviderManifest,
    TermDescription,
    TermSchema,
)

from .catalog import IFC43_CATALOG, Ifc43Catalog


class Ifc43SemanticProvider:
    def __init__(self, catalog: Ifc43Catalog = IFC43_CATALOG) -> None:
        self._catalog = catalog
        self._manifest = SemanticProviderManifest(
            provider_id="buildingSMART.ifc43",
            provider_type=ProviderType.STANDARD,
            version="4.3.2.0",
            content_hash=catalog.content_hash,
            namespaces=("ifc",),
            capabilities=frozenset(
                {
                    SemanticCapability.VOCABULARY,
                    SemanticCapability.VALIDATION,
                    SemanticCapability.PROJECTION,
                }
            ),
            authority=(NamespaceAuthority("ifc", AuthorityMode.AUTHORITATIVE),),
            compatibility=(),
            requires=(),
        )
        self._provenance = ProviderProvenance(
            self._manifest.provider_id,
            self._manifest.version,
            self._manifest.content_hash,
        )

    @property
    def manifest(self) -> SemanticProviderManifest:
        return self._manifest

    def resolve_term(self, term_id: str) -> ResolvedTerm:
        record = self._catalog.get(term_id)
        return ResolvedTerm(record.term_id, record.kind, self._provenance)

    def describe_term(self, term_id: str, locale: str | None = None) -> TermDescription:
        record = self._catalog.get(term_id)
        return TermDescription(record.term_id, record.description, None, self._provenance)

    def get_term_schema(self, term_id: str) -> TermSchema:
        record = self._catalog.get(term_id)
        return TermSchema(record.term_id, self._catalog.schema_for(term_id), self._provenance)


IFC43_PROVIDER = Ifc43SemanticProvider()
```

The manifest intentionally claims VALIDATION before Task 6 implements the method, so Task 5 MUST NOT register the provider with `SemanticProviderRegistry` yet.

- [ ] **Step 4: Create curated package exports**

Create `__init__.py`:

```python
from .catalog import IFC43_CATALOG, Ifc43Catalog
from .errors import (
    Ifc43CatalogBuildError,
    Ifc43ProviderError,
    Ifc43SourceVersionError,
    Ifc43TermNotFoundError,
    Ifc43ValidationError,
)
from .provider import IFC43_PROVIDER, Ifc43SemanticProvider

__all__ = [
    "IFC43_CATALOG",
    "IFC43_PROVIDER",
    "Ifc43Catalog",
    "Ifc43CatalogBuildError",
    "Ifc43ProviderError",
    "Ifc43SemanticProvider",
    "Ifc43SourceVersionError",
    "Ifc43TermNotFoundError",
    "Ifc43ValidationError",
]
```

- [ ] **Step 5: Run direct provider tests and confirm GREEN**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_provider_manifest.py
```

Expected: all direct Task 5 tests pass. Do not add a registry test until Task 6.

- [ ] **Step 6: Commit Task 5**

```bash
git add providers/semantics/ifc43/src/ifc43_semantic_provider/provider.py \
        providers/semantics/ifc43/src/ifc43_semantic_provider/__init__.py \
        tests/semantic_providers/ifc43/test_provider_manifest.py
git commit -m "feat(semantic): add IFC4.3 vocabulary provider"
```

---

### Task 6: Deterministic Claim-Level IFC Validation and Registry Conformance

**Files:**
- Create: `providers/semantics/ifc43/src/ifc43_semantic_provider/validation.py`
- Modify: `providers/semantics/ifc43/src/ifc43_semantic_provider/provider.py`
- Create: `tests/semantic_providers/ifc43/test_validation.py`
- Modify: `tests/semantic_providers/ifc43/test_provider_manifest.py`

**Interfaces:**
- Consumes: `SemanticClaim`, `ValidationFinding`, `ValidationStatus`, catalog term/type metadata.
- Produces: `validate_claim_against_ifc43()`, `Ifc43SemanticProvider.validate_claim()`, and a provider accepted by the existing registry for all claimed capabilities.

- [ ] **Step 1: Write failing validation and registry tests**

Create `test_validation.py`:

```python
from semantic_service import SemanticClaim, ValidationStatus

from ifc43_semantic_provider import IFC43_PROVIDER


def finding(rule_id, claim):
    return next(item for item in IFC43_PROVIDER.validate_claim(claim) if item.rule_id == rule_id)


def test_non_ifc_claim_is_not_applicable():
    result = IFC43_PROVIDER.validate_claim(
        SemanticClaim(subject="S1", canonical_term_id="dsp:WallThickness", value=200)
    )
    assert result[0].status is ValidationStatus.NOT_APPLICABLE


def test_unknown_ifc_term_fails_legality_check():
    item = finding(
        "ifc43.term.exists",
        SemanticClaim(subject="S1", canonical_term_id="ifc:IfcTunnel", value=None),
    )
    assert item.status is ValidationStatus.FAIL


def test_valid_enum_value_passes_and_invalid_value_fails():
    valid = finding(
        "ifc43.value.enum",
        SemanticClaim(
            subject="S1",
            canonical_term_id="ifc:IfcRailwayPart.PredefinedType",
            value="TRACK",
        ),
    )
    invalid = finding(
        "ifc43.value.enum",
        SemanticClaim(
            subject="S1",
            canonical_term_id="ifc:IfcRailwayPart.PredefinedType",
            value="STATION",
        ),
    )
    assert valid.status is ValidationStatus.PASS
    assert invalid.status is ValidationStatus.FAIL


def test_boolean_pset_property_rejects_string_value():
    item = finding(
        "ifc43.value.type",
        SemanticClaim(
            subject="S1",
            canonical_term_id="ifc:Pset_WallCommon.LoadBearing",
            value="TRUE",
        ),
    )
    assert item.status is ValidationStatus.FAIL


def test_entity_value_requires_model_context():
    item = finding(
        "ifc43.value.context",
        SemanticClaim(subject="S1", canonical_term_id="ifc:IfcWall", value="reference"),
    )
    assert item.status is ValidationStatus.NOT_APPLICABLE
```

Append to `test_provider_manifest.py`:

```python
from semantic_service import SemanticProviderRegistry


def test_registry_accepts_all_claimed_capabilities_after_validation_exists():
    registry = SemanticProviderRegistry()
    assert registry.register(IFC43_PROVIDER) == IFC43_PROVIDER.manifest
```

- [ ] **Step 2: Run validation/registry tests and confirm RED**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_validation.py \
          tests/semantic_providers/ifc43/test_provider_manifest.py
```

Expected: `validate_claim` missing and registry reports claimed VALIDATION without protocol implementation.

- [ ] **Step 3: Implement explicit validation helpers with no model-level guessing**

Create `validation.py`:

```python
from __future__ import annotations

from collections.abc import Mapping

from semantic_service import (
    ProviderProvenance,
    SemanticClaim,
    ValidationFinding,
    ValidationStatus,
)

from .errors import Ifc43TermNotFoundError

IFC_SCOPE_RULE = "ifc43.scope"
TERM_EXISTS_RULE = "ifc43.term.exists"
ENUM_RULE = "ifc43.value.enum"
TYPE_RULE = "ifc43.value.type"
CONTEXT_RULE = "ifc43.value.context"

_QTO_NUMERIC_TYPES = {
    "Q_LENGTH",
    "Q_AREA",
    "Q_VOLUME",
    "Q_WEIGHT",
    "Q_TIME",
    "Q_COUNT",
}


def _finding(rule_id, status, provenance, message=None):
    return ValidationFinding(rule_id, status, provenance, message)


def _is_number(value: object) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _python_type_ok(simple_name: str, value: object) -> bool:
    if simple_name in {"REAL", "NUMBER"}:
        return _is_number(value)
    if simple_name == "INTEGER":
        return isinstance(value, int) and not isinstance(value, bool)
    if simple_name == "BOOLEAN":
        return isinstance(value, bool)
    if simple_name == "LOGICAL":
        return value in (True, False, "UNKNOWN")
    if simple_name == "STRING":
        return isinstance(value, str)
    if simple_name == "BINARY":
        return isinstance(value, (bytes, bytearray))
    return False


def _type_target(catalog, expression: Mapping[str, object]):
    kind = expression.get("kind")
    if kind == "SIMPLE":
        return ("SIMPLE", expression.get("name"))
    if kind != "NAMED":
        return ("CONTEXT", None)

    term_id = expression.get("name")
    if not isinstance(term_id, str):
        return ("CONTEXT", None)
    record = catalog.get(term_id)
    if record.kind == "ENUM":
        return ("ENUM", term_id)
    if record.kind == "DEFINED_TYPE":
        underlying = record.machine_schema.get("underlying")
        if isinstance(underlying, Mapping):
            return _type_target(catalog, underlying)
    return ("CONTEXT", None)


def _enum_values(catalog, enum_term_id: str) -> tuple[str, ...]:
    enum_record = catalog.get(enum_term_id)
    literal_ids = tuple(enum_record.machine_schema.get("literals", ()))
    return tuple(catalog.get(item).machine_schema["value"] for item in literal_ids)


def _value_target(catalog, record):
    if record.kind == "ATTRIBUTE":
        declared = record.machine_schema.get("declared_type")
        if isinstance(declared, Mapping):
            return _type_target(catalog, declared)
        return ("CONTEXT", None)

    if record.kind == "PSET_PROPERTY":
        enum_values = tuple(record.machine_schema.get("enum_values", ()))
        if enum_values:
            return ("INLINE_ENUM", enum_values)
        measure = record.machine_schema.get("primary_measure_type")
        if isinstance(measure, str) and measure:
            try:
                return _type_target(catalog, {"kind": "NAMED", "name": f"ifc:{measure}"})
            except Ifc43TermNotFoundError:
                return ("CONTEXT", None)
        return ("CONTEXT", None)

    if record.kind == "QTO_QUANTITY":
        template_type = record.machine_schema.get("template_type")
        if template_type in _QTO_NUMERIC_TYPES:
            return ("NUMBER", None)
        return ("CONTEXT", None)

    return ("CONTEXT", None)


def validate_claim_against_ifc43(catalog, claim: SemanticClaim, provenance: ProviderProvenance):
    target = claim.canonical_term_id or claim.predicate
    if target is None or not target.startswith("ifc:"):
        return (_finding(IFC_SCOPE_RULE, ValidationStatus.NOT_APPLICABLE, provenance),)

    try:
        record = catalog.get(target)
    except Ifc43TermNotFoundError:
        return (_finding(TERM_EXISTS_RULE, ValidationStatus.FAIL, provenance),)

    findings = [_finding(TERM_EXISTS_RULE, ValidationStatus.PASS, provenance)]
    if claim.value is None:
        findings.append(_finding(CONTEXT_RULE, ValidationStatus.NOT_APPLICABLE, provenance))
        return tuple(findings)

    target_kind, target_value = _value_target(catalog, record)
    if target_kind == "ENUM":
        allowed = _enum_values(catalog, target_value)
        status = ValidationStatus.PASS if claim.value in allowed else ValidationStatus.FAIL
        findings.append(_finding(ENUM_RULE, status, provenance))
    elif target_kind == "INLINE_ENUM":
        status = ValidationStatus.PASS if claim.value in target_value else ValidationStatus.FAIL
        findings.append(_finding(ENUM_RULE, status, provenance))
    elif target_kind == "SIMPLE":
        status = ValidationStatus.PASS if _python_type_ok(target_value, claim.value) else ValidationStatus.FAIL
        findings.append(_finding(TYPE_RULE, status, provenance))
    elif target_kind == "NUMBER":
        status = ValidationStatus.PASS if _is_number(claim.value) else ValidationStatus.FAIL
        findings.append(_finding(TYPE_RULE, status, provenance))
    else:
        findings.append(_finding(CONTEXT_RULE, ValidationStatus.NOT_APPLICABLE, provenance))

    if claim.unit is not None:
        findings.append(
            _finding(
                CONTEXT_RULE,
                ValidationStatus.NOT_APPLICABLE,
                provenance,
                "unit validation requires IFC model unit-assignment context",
            )
        )
    return tuple(findings)
```

This implementation validates only what the current claim contains. It deliberately does not infer an IFC instance graph, unit assignment, inverse relationship, WHERE-rule context, geometry, IDS, or Metro requirement.

- [ ] **Step 4: Wire validation into the provider**

Modify `provider.py`:

```python
from semantic_service import SemanticClaim, ValidationFinding
from .validation import validate_claim_against_ifc43

    def validate_claim(self, claim: SemanticClaim) -> tuple[ValidationFinding, ...]:
        return validate_claim_against_ifc43(self._catalog, claim, self._provenance)
```

Keep the existing singleton `IFC43_PROVIDER = Ifc43SemanticProvider()` at module bottom.

- [ ] **Step 5: Run validation + registry tests and confirm GREEN**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_validation.py \
          tests/semantic_providers/ifc43/test_provider_manifest.py
```

Expected: all Task 5/6 tests pass and the real registry accepts the provider.

- [ ] **Step 6: Commit Task 6**

```bash
git add providers/semantics/ifc43/src/ifc43_semantic_provider/validation.py \
        providers/semantics/ifc43/src/ifc43_semantic_provider/provider.py \
        tests/semantic_providers/ifc43/test_validation.py \
        tests/semantic_providers/ifc43/test_provider_manifest.py
git commit -m "feat(semantic): validate IFC4.3 semantic claims"
```

---

### Task 7: Semantic Service Authority/Environment Integration, Real MCP, and Metro Reference Corpus

**Files:**
- Create: `tests/semantic_providers/ifc43/test_service_integration.py`
- Create: `tests/semantic_providers/ifc43/test_mcp_integration.py`
- Create: `tests/semantic_providers/ifc43/test_metro_reference_cases.py`

**Interfaces:**
- Consumes: existing `SemanticProviderRegistry`, `SemanticEnvironmentStore`, `SemanticService`, existing `semantic_mcp.server.build_mcp_server`, existing `dsp_core_semantic_provider.DSP_CORE_PROVIDER`.
- Produces: no production API; proves the provider works through existing contracts without platform changes.

- [ ] **Step 1: Write service/environment authority tests**

Create `test_service_integration.py`:

```python
import pytest

from semantic_service import (
    AuthorityMode,
    NamespaceAuthority,
    NamespaceAuthorityError,
    ProviderRef,
    ProviderRegistrationConflictError,
    ProviderType,
    SemanticCapability,
    SemanticEnvironmentStore,
    SemanticProviderManifest,
    SemanticProviderRegistry,
    SemanticService,
)
from dsp_core_semantic_provider import DSP_CORE_PROVIDER
from ifc43_semantic_provider import IFC43_PROVIDER


def build_service():
    registry = SemanticProviderRegistry()
    registry.register(DSP_CORE_PROVIDER)
    registry.register(IFC43_PROVIDER)
    store = SemanticEnvironmentStore()
    environment = store.pin(
        (
            ProviderRef("dsp.core", "1.0"),
            ProviderRef("buildingSMART.ifc43", "4.3.2.0"),
        ),
        registry,
    )
    return SemanticService(registry, store), environment, registry, store


def test_service_resolves_ifc_term_through_exact_authoritative_owner():
    service, environment, _, _ = build_service()
    result = service.resolve_term("ifc:IfcWall", environment.environment_id)
    assert result.term_id == "ifc:IfcWall"
    assert result.provenance.provider_id == "buildingSMART.ifc43"


class ConflictingIfcOwner:
    manifest = SemanticProviderManifest(
        provider_id="test.conflicting-ifc",
        provider_type=ProviderType.DOMAIN,
        version="1",
        content_hash="conflict",
        namespaces=("ifc",),
        capabilities=frozenset({SemanticCapability.VOCABULARY}),
        authority=(NamespaceAuthority("ifc", AuthorityMode.AUTHORITATIVE),),
        compatibility=(),
        requires=(),
    )

    def resolve_term(self, term_id):
        raise AssertionError("must never route")

    def describe_term(self, term_id, locale=None):
        raise AssertionError("must never route")

    def get_term_schema(self, term_id):
        raise AssertionError("must never route")


def test_second_authoritative_ifc_owner_fails_environment_pinning():
    _, _, registry, store = build_service()
    registry.register(ConflictingIfcOwner())
    with pytest.raises(NamespaceAuthorityError, match="multiple AUTHORITATIVE"):
        store.pin(
            (
                ProviderRef("buildingSMART.ifc43", "4.3.2.0"),
                ProviderRef("test.conflicting-ifc", "1"),
            ),
            registry,
        )


class ConflictingSameVersion:
    manifest = SemanticProviderManifest(
        provider_id="buildingSMART.ifc43",
        provider_type=ProviderType.STANDARD,
        version="4.3.2.0",
        content_hash="different-machine-semantics",
        namespaces=("ifc",),
        capabilities=frozenset(),
        authority=(),
        compatibility=(),
        requires=(),
    )


def test_same_provider_version_with_different_content_fails_closed():
    registry = SemanticProviderRegistry()
    registry.register(IFC43_PROVIDER)
    with pytest.raises(ProviderRegistrationConflictError, match="immutable provider version conflict"):
        registry.register(ConflictingSameVersion())
```

- [ ] **Step 2: Add real existing Semantic MCP client coverage**

Create `test_mcp_integration.py`:

```python
import pytest
from mcp import Client

from semantic_mcp.server import build_mcp_server
from semantic_service import ProviderRef, SemanticEnvironmentStore, SemanticProviderRegistry, SemanticService
from ifc43_semantic_provider import IFC43_CATALOG, IFC43_PROVIDER


@pytest.mark.asyncio
async def test_real_mcp_client_resolves_ifc43_term_and_schema():
    registry = SemanticProviderRegistry()
    registry.register(IFC43_PROVIDER)
    store = SemanticEnvironmentStore()
    environment = store.pin((ProviderRef("buildingSMART.ifc43", "4.3.2.0"),), registry)
    service = SemanticService(registry, store)

    async with Client(build_mcp_server(service)) as client:
        assert client.protocol_version == "2026-07-28"
        resolved = await client.call_tool(
            "semantic.resolve_term",
            {"term_id": "ifc:IfcWall", "environment_id": environment.environment_id},
        )
        schema = await client.call_tool(
            "semantic.get_term_schema",
            {"term_id": "ifc:IfcWall", "environment_id": environment.environment_id},
        )

    assert resolved.is_error is False
    assert resolved.structured_content["provenance"]["content_hash"] == IFC43_CATALOG.content_hash
    assert schema.is_error is False
    assert "ifc:IfcRoot.Name" in schema.structured_content["schema"]["inherited_members"]
```

- [ ] **Step 3: Encode Metro V3.2 reference facts as test literals only**

Create `test_metro_reference_cases.py`:

```python
import pytest

from ifc43_semantic_provider import IFC43_CATALOG
from ifc43_semantic_provider.errors import Ifc43TermNotFoundError

POSITIVE = (
    "ifc:IfcRailway",
    "ifc:IfcRailwayPart",
    "ifc:IfcAlignment",
    "ifc:IfcLinearPlacement",
    "ifc:IfcRail",
    "ifc:IfcTrackElement",
    "ifc:IfcMechanicalFastener",
    "ifc:IfcWall",
    "ifc:IfcSlab",
    "ifc:IfcBeam",
    "ifc:IfcColumn",
    "ifc:IfcOpeningElement",
    "ifc:IfcBorehole",
    "ifc:IfcGeomodel",
    "ifc:IfcGeotechnicalStratum",
    "ifc:IfcDistributionSystem",
    "ifc:IfcDistributionPort",
    "ifc:Pset_WallCommon",
    "ifc:Qto_WallBaseQuantities",
    "ifc:Pset_Stationing",
)

NEGATIVE_ENTITIES = (
    "ifc:IfcTunnel",
    "ifc:IfcTunnelPart",
    "ifc:IfcTrack",
    "ifc:IfcSprinkler",
    "ifc:IfcFanCoilUnit",
    "ifc:IfcPrecastConcreteElement",
)


@pytest.mark.parametrize("term_id", POSITIVE)
def test_metro_reference_positive_ifc_terms_are_official(term_id):
    assert IFC43_CATALOG.get(term_id).term_id == term_id


@pytest.mark.parametrize("term_id", NEGATIVE_ENTITIES)
def test_metro_reference_nonexistent_ifc_entities_are_rejected(term_id):
    with pytest.raises(Ifc43TermNotFoundError):
        IFC43_CATALOG.get(term_id)
```

Do not import or parse the Metro Markdown inside production provider code.

- [ ] **Step 4: Run Task 7 integration tests**

Run:

```bash
python -m pip install -e providers/semantics/dsp_core -e platform/semantic_mcp
pytest -q tests/semantic_providers/ifc43/test_service_integration.py \
          tests/semantic_providers/ifc43/test_mcp_integration.py \
          tests/semantic_providers/ifc43/test_metro_reference_cases.py
```

Expected: all pass without editing Semantic Service or Semantic MCP production code. If an actual pre-existing contract defect appears, surface it instead of widening PR #9 silently.

- [ ] **Step 5: Commit Task 7**

```bash
git add tests/semantic_providers/ifc43/test_service_integration.py \
        tests/semantic_providers/ifc43/test_mcp_integration.py \
        tests/semantic_providers/ifc43/test_metro_reference_cases.py
git commit -m "test(semantic): integrate IFC4.3 provider"
```

---

### Task 8: Architecture Guards, README, Focused CI, and Full Regression Verification

**Files:**
- Create: `tests/semantic_providers/ifc43/test_ifc43_architecture.py`
- Create: `providers/semantics/ifc43/README.md`
- Create: `.github/workflows/ifc43-semantic-provider.yml`

**Interfaces:**
- Consumes: repository source tree and all Task 1-7 behavior.
- Produces: enforceable dependency/non-goal guards, operator-facing package notes, focused CI, and final verification evidence.

- [ ] **Step 1: Write architecture guards**

Create `test_ifc43_architecture.py`:

```python
import ast
from pathlib import Path

PROVIDER_ROOT = Path("providers/semantics/ifc43/src/ifc43_semantic_provider")
PLATFORM_ROOTS = (
    Path("platform/semantic_service/src"),
    Path("platform/semantic_runtime/src"),
    Path("platform/semantic_mcp/src"),
)

FORBIDDEN_PROVIDER_IMPORTS = {
    "semantic_runtime",
    "semantic_mcp",
    "dsp_core_semantic_provider",
    "autocad_sidecar",
    "Autodesk",
    "Revit",
    "Tekla",
    "requests",
    "httpx",
    "aiohttp",
    "urllib",
}

FORBIDDEN_PROVIDER_TOKENS = (
    "A-WALL",
    "metro:",
    "PsetProj_",
    "QtoProj_",
    "wall.thickness.set.v1",
    "ElementId",
    "project_facts",
    "find_mappings",
)


def import_roots(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            roots.add(node.module.split(".", 1)[0])
    return roots


def test_provider_has_no_platform_host_metro_or_network_import_leakage():
    for path in PROVIDER_ROOT.glob("*.py"):
        assert import_roots(path).isdisjoint(FORBIDDEN_PROVIDER_IMPORTS), path


def test_platform_core_does_not_import_ifcopenshell_or_concrete_ifc_provider():
    forbidden = {"ifcopenshell", "ifc43_semantic_provider"}
    for root in PLATFORM_ROOTS:
        for path in root.rglob("*.py"):
            assert import_roots(path).isdisjoint(forbidden), path


def test_provider_contains_no_host_metro_action_or_projection_ownership_tokens():
    text = "\n".join(path.read_text() for path in PROVIDER_ROOT.glob("*.py"))
    for token in FORBIDDEN_PROVIDER_TOKENS:
        assert token not in text, token
```

- [ ] **Step 2: Run architecture tests and make them GREEN without weakening guards**

Run:

```bash
pytest -q tests/semantic_providers/ifc43/test_ifc43_architecture.py
```

Expected: pass. Fix dependency leakage in production provider code; do not remove a guard to make CI green.

- [ ] **Step 3: Write package README**

Create `providers/semantics/ifc43/README.md` covering:

```text
provider: buildingSMART.ifc43@4.3.2.0
schema: IFC4X3_ADD2
source engine: ifcopenshell==0.8.5
capabilities: VOCABULARY + claim-level VALIDATION + marker-only PROJECTION
MAPPING: not claimed
lookup: exact/case-sensitive
member identity: owner-qualified attributes/Pset/Qto/enum literals
hashing: normalized machine semantics + reviewed golden hash
Metro V3.2: reference-only in PR #9
not provided: complete IFC file, geometry, IDS, Host, or Metro validation/mapping
```

Do not copy buildingSMART or Metro standard text into the README.

- [ ] **Step 4: Add focused GitHub Actions verification**

Create `.github/workflows/ifc43-semantic-provider.yml`:

```yaml
name: IFC4.3 semantic provider verification

on:
  push:
    branches:
      - main
      - 'feat/ifc43-semantic-provider'
    paths:
      - 'providers/semantics/ifc43/**'
      - 'tests/semantic_providers/ifc43/**'
      - 'providers/semantics/dsp_core/**'
      - 'platform/semantic_service/**'
      - 'platform/semantic_mcp/**'
      - 'platform/semantic_runtime/**'
      - 'docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md'
      - 'docs/superpowers/specs/2026-08-28-ifc43-semantic-provider-design.md'
      - 'docs/superpowers/plans/2026-08-28-ifc43-semantic-provider.md'
      - '.github/workflows/ifc43-semantic-provider.yml'
  pull_request:
    paths:
      - 'providers/semantics/ifc43/**'
      - 'tests/semantic_providers/ifc43/**'
      - 'providers/semantics/dsp_core/**'
      - 'platform/semantic_service/**'
      - 'platform/semantic_mcp/**'
      - 'platform/semantic_runtime/**'
      - 'docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md'
      - 'docs/superpowers/specs/2026-08-28-ifc43-semantic-provider-design.md'
      - 'docs/superpowers/plans/2026-08-28-ifc43-semantic-provider.md'
      - '.github/workflows/ifc43-semantic-provider.yml'
  workflow_dispatch:

jobs:
  ifc43-provider:
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
          python -m pip install -e contracts/python -e hosts/autocad/sidecar -e platform/semantic_runtime -e platform/semantic_service -e platform/semantic_mcp -e providers/semantics/dsp_core -e providers/semantics/ifc43
      - name: Run IFC4.3 provider tests
        run: pytest -q tests/semantic_providers/ifc43
      - name: Run full Python regression tests
        run: pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator tests/semantic_runtime tests/semantic_service tests/semantic_mcp tests/semantic_providers/dsp_core tests/semantic_providers/ifc43
```

- [ ] **Step 5: Run focused provider suite**

Run:

```bash
pytest -q tests/semantic_providers/ifc43
```

Expected: all IFC4.3 provider tests pass, including source gate, normalization, official Pset/Qto, golden hash, validation, service/MCP, Metro reference cases, and architecture guards.

- [ ] **Step 6: Run full relevant repository regression suite**

Run:

```bash
pytest -q contracts/python/tests \
          tests/contracts \
          tests/integration \
          tests/orchestrator \
          tests/semantic_runtime \
          tests/semantic_service \
          tests/semantic_mcp \
          tests/semantic_providers/dsp_core \
          tests/semantic_providers/ifc43
```

Expected: all non-live tests pass. Existing live AutoCAD tests may remain skipped only under their current explicit environment guard; PR #9 adds no IFC-specific skip.

- [ ] **Step 7: Verify the branch did not change existing production platform/Host code**

Run:

```bash
git diff --name-only main...HEAD
```

Expected production changes are limited to the new `providers/semantics/ifc43/**` package plus tests/workflow/docs. No file under `platform/semantic_service/src`, `platform/semantic_runtime/src`, `platform/semantic_mcp/src`, Host production code, D4/D5/D6/D7, or Gateway is modified.

- [ ] **Step 8: Commit Task 8**

```bash
git add providers/semantics/ifc43/README.md \
        tests/semantic_providers/ifc43/test_ifc43_architecture.py \
        .github/workflows/ifc43-semantic-provider.yml
git commit -m "test(semantic): verify IFC4.3 provider boundaries"
```

---

## Plan Self-Review Checklist

Before execution starts, re-read the approved design and verify these mappings:

- Source-of-truth / exact version -> Task 1.
- Schema entity/inheritance/attribute/enum/select/datatype/relationship normalization -> Task 2.
- Official Pset/Qto semantics -> Task 3.
- Stable member IDs, inherited identity, immutable catalog, machine hash, golden drift lock -> Task 4.
- Exact STANDARD manifest, `ifc` authority, VOCABULARY, marker PROJECTION, no MAPPING -> Task 5.
- Narrow claim-level VALIDATION with `NOT_APPLICABLE` for missing context -> Task 6.
- Semantic Service pinning/authority, real MCP, immutable version conflict, Metro reference corpus -> Task 7.
- Core isolation, no Host/Metro/network leakage, focused CI, full regression -> Task 8.

No implementation task may add `NormalizedDesignFact`, Host mapping, Metro `PsetProj_*`, IDS, complete IFC file validation, geometry, new Semantic MCP tools, or platform-core IfcOpenShell dependencies.
