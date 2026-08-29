# Step 23 — Canonical Action Contract Upgrade Design

**Status:** Approved design, implementation not started  
**Date:** 2026-08-29  
**Base:** `main@833503062d516c25baffae644de73f929164f473`  
**Branch:** `feat/step23-canonical-action-contract`  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step 23 upgrades the platform-owned Canonical Action contract so D4, D6, and D7 can consume one stable Host-independent operation definition.

This step exists to freeze **what a canonical action means** before later phases implement:

- Step 24 — D4 semantic eligibility;
- Step 25 — D6 Slot Binder;
- Step 26 — InteractionSession / Host interaction;
- Step 27+ — Impact / ChangeSet / Governance;
- Step 30 — canonical `ExecutionUnit`;
- Step 31 — `ProviderBinding / binding_set_hash`.

Step 23 MUST NOT implement those later responsibilities early.

The architectural result is:

```text
Canonical Action Catalog
  = platform-owned semantic operation contract

Host / Execution Provider Profile
  = provider-owned execution capability claim
```

A Provider MAY implement a canonical action, but it MUST NOT define or mutate the canonical action's public meaning.

---

## 2. Why Step 23 is required now

The current `CanonicalOperationDefinition` on `main` contains only:

```text
canonical_operation
category
input_schema
verification_contract
context_freshness_requirements
operation_freshness_requirements
```

This was sufficient for the Step 22 ownership proof, but it is not yet the complete contract required by v0.6.

The master spec requires Canonical Action metadata covering:

```text
canonical_operation
version
title
description
category
input_schema
slot_binding_policy
canonical semantic constraints
freshness requirements
coverage requirements
assurance requirements
effects
verification contract
```

The current model also exposes the full canonical `input_schema` through D4. For `move.v1`, that schema includes both:

```text
targets
displacement
```

but v0.6 freezes different binding ownership:

```text
targets      = CONTEXT
displacement = INTENT
```

Therefore Step 23 must establish a structured slot-binding contract and a deterministic intent-visible schema projection before Step 25 implements actual parameter binding.

---

## 3. Design classification

This is an **architectural** change because the contract becomes a shared boundary for future D4/D6/D7 work. It is not merely a dataclass field expansion.

A wrong boundary here would cause one or more of the following later:

- Host-native schemas leaking into the LLM action space;
- D6 having to infer slot ownership from names/descriptions;
- Provider profiles redefining canonical effects or semantic requirements;
- D7 receiving provider-specific operation meaning before `ProviderBinding`;
- duplicated or contradictory action metadata across modules.

---

## 4. Chosen approach

### 4.1 Chosen: freeze the full platform Canonical Action contract now

Step 23 will upgrade `CanonicalOperationDefinition` and its validation so the catalog is expressive enough for downstream phases without implementing those phases.

The contract will own:

```text
identity / version
human-facing semantic description
category
canonical input schema
slot binding policy
canonical semantic applicability metadata
progressive semantic requirements
effects
verification contract
```

The implementation remains provider-neutral.

### 4.2 Rejected: minimal string-field patch

Adding only `title` and `description` would leave slot ownership and semantic requirements as loose conventions. D6 would then need to invent a second source of truth.

Rejected because it postpones rather than freezes the action contract.

### 4.3 Rejected: implement ProviderBinding now

The master spec places `ProviderBinding` at Step 31, after canonical `ExecutionSlice` and `ExecutionUnit` are corrected at Step 30.

Current `platform/changeset` is still an early placeholder and is not yet the v0.6 canonical execution model. Implementing `ProviderBinding` now would bind to the wrong execution DTOs and skip Steps 23–30.

---

## 5. Ownership model

### 5.1 Canonical Action Catalog owns semantic operation meaning

The platform-owned `CanonicalOperationDefinition` SHALL own:

- canonical operation identity;
- contract version;
- title and description;
- operation category;
- canonical input shape;
- slot binding classes;
- canonical semantic entity constraints;
- context freshness requirements;
- operation freshness requirements;
- coverage requirements;
- assurance requirements;
- canonical expected effects;
- canonical verification contract.

These fields SHALL NOT be derived at runtime from the set of candidate Host providers.

### 5.2 Host provider owns execution interface

A Host/Execution provider continues to own:

- `provider_server`;
- `provider_tool`;
- provider-native input/output schema;
- provider-native constraints;
- provider execution freshness;
- provider-specific preview/rollback/idempotency claims;
- native conversion and later HostCommand generation.

Provider metadata is a capability claim, not canonical semantic authority.

### 5.3 D4 consumes, but does not own, the catalog

Step 23 SHALL NOT move Canonical Action ownership into `OperationResolver`.

D4 remains a consumer that resolves which canonical operations are currently available.

### 5.4 D6 will consume slot metadata later

Step 23 freezes slot binding classes but SHALL NOT implement `BoundOperationProposal`, deterministic context binding, defaults, derived parameters, or Host interactions.

Those belong to Step 25/26.

### 5.5 D7 will consume the same canonical definition later

Step 23 SHALL NOT create `ExecutionUnit` or `ProviderBinding` production paths.

Later D7 code must be able to use this same canonical operation definition without importing Host provider packages.

---

## 6. CanonicalOperationDefinition contract

The Step 23 production contract SHALL contain the following semantic fields.

```text
CanonicalOperationDefinition {
  canonical_operation
  version
  title
  description
  category
  input_schema
  slot_binding_policy
  canonical_entity_constraints
  context_freshness_requirements
  operation_freshness_requirements
  coverage_requirements
  assurance_requirements
  effects
  verification_contract
}
```

The Python implementation may use immutable tuples/mappings/dataclasses internally, but the semantic meaning above is normative.

### 6.1 `canonical_operation`

Stable platform operation identity.

Example:

```text
move.v1
```

Requirements:

- non-empty;
- whitespace-normalized;
- provider server/tool names are forbidden as substitutes;
- changing meaning incompatibly requires a new operation identity or major contract version according to future version policy.

### 6.2 `version`

Version of the platform-owned action contract.

For the Step 23 MOVE fixture:

```text
1.0.0
```

Step 23 SHALL validate this as a non-empty structured version string. It does not need to implement a package/version resolver.

### 6.3 `title`

Short human-facing operation label.

For MOVE:

```text
Move entities
```

It explains the canonical user operation, not a provider tool.

### 6.4 `description`

Human/LLM-facing explanation of what the canonical operation means.

It MUST NOT contain Host-specific routing instructions or be used as machine-enforced constraint logic.

### 6.5 `category`

Existing categories remain:

```text
MODEL_OPERATION
INTERACTION
VIEW
CONTEXT
```

Step 23 retains strict validation against this set.

### 6.6 `input_schema`

This is the **canonical semantic parameter schema**, not the Host MCP provider schema.

It describes all canonical slots required to represent the action, including slots that are not LLM-visible.

For `move.v1`:

```json
{
  "type": "object",
  "properties": {
    "targets": {
      "type": "array",
      "items": {"type": "string"},
      "minItems": 1
    },
    "displacement": {
      "type": "array",
      "items": {"type": "number"},
      "minItems": 3,
      "maxItems": 3
    }
  },
  "required": ["targets", "displacement"],
  "additionalProperties": false
}
```

Provider-native fields such as these are forbidden from becoming canonical slots solely because a provider needs them:

```text
handles
ElementId
revision token
idempotency key
internal unit
provider tool routing id
```

### 6.7 `slot_binding_policy`

Structured mapping from each canonical top-level input slot to exactly one binding class.

Normative binding classes:

```text
INTENT
CONTEXT
CANONICAL_DEFAULT
DERIVED
PROVIDER
```

Step 23 SHALL introduce a typed representation such as `SlotBindingClass` rather than accepting arbitrary free-form strings throughout the codebase.

The semantic meaning is:

| Binding class | Owner/source | LLM visible in intent schema? |
|---|---|---:|
| `INTENT` | user/LLM intent | yes |
| `CONTEXT` | current canonical/context state | no |
| `CANONICAL_DEFAULT` | platform canonical default | no |
| `DERIVED` | deterministic platform derivation | no |
| `PROVIDER` | post-ProviderBinding native execution value | no |

Step 23 freezes classification only. It does not perform the binding.

### 6.8 `canonical_entity_constraints`

Platform semantic applicability constraints only.

Examples may include canonical terms such as:

```text
ifc:IfcWall
```

They MUST NOT contain provider-native kinds such as:

```text
LINE
LWPOLYLINE
ARC
Revit.Wall
AutoCAD.Handle
```

For generic `move.v1` in Step 23:

```text
canonical_entity_constraints = ()
```

because MOVE is not limited to one canonical semantic entity type by the platform contract.

Provider-native entity filtering remains outside the Canonical Action contract and is handled by the provider capability / future Step 24 semantic eligibility split.

### 6.9 `context_freshness_requirements`

Phase-A requirements owned by the platform canonical action contract.

Step 23 does not change Step 22's progressive ownership rule.

### 6.10 `operation_freshness_requirements`

Phase-B task semantic requirements owned by the canonical action.

For `move.v1`:

```text
PLACEMENT / FRESH
```

Provider execution freshness MUST NOT be merged into this field.

### 6.11 `coverage_requirements`

Structured canonical requirements describing minimum semantic coverage/maturity needed by the operation.

For generic MOVE in Step 23, the default fixture MAY be empty because the existing progressive proof only requires placement freshness and does not need a new coverage constraint.

The important invariant is ownership: if a future action needs canonical coverage, it is declared here, not inferred from Host candidates.

### 6.12 `assurance_requirements`

Structured canonical minimum assurance requirements.

For generic MOVE in Step 23, the default fixture MAY be empty.

Again, absence means the canonical operation declares no additional assurance threshold beyond other barriers; it MUST NOT mean providers can inject one into the action contract before binding.

### 6.13 `effects`

Canonical semantic effects expected from the user operation.

For `move.v1`:

```text
PLACEMENT
GEOMETRY
```

This field is platform-owned.

It is distinct from semantic prerequisites:

```text
operation effect GEOMETRY
!=
pre-operation GEOMETRY freshness requirement
```

Step 22 already proved this distinction; Step 23 makes the effect source canonical rather than provider-aggregated.

### 6.14 `verification_contract`

Canonical verification expectation.

For MOVE:

```json
{"type": "HOST_READ_BACK"}
```

A provider must be compatible with the canonical verification expectation, but the provider does not redefine it.

---

## 7. Slot-policy validation rules

Step 23 SHALL fail closed when the canonical action definition is internally inconsistent.

### 7.1 Every top-level canonical property must have a binding class

If `input_schema.properties` contains:

```text
targets
displacement
```

then `slot_binding_policy` MUST classify both.

Missing policy entry is invalid.

### 7.2 Binding policy cannot name an unknown canonical slot

A policy entry for a name absent from `input_schema.properties` is invalid.

### 7.3 Required canonical slots may be non-INTENT

A slot may be required by the canonical operation while still not being LLM-visible.

For MOVE:

```text
targets = required canonical slot
binding = CONTEXT
```

This is valid because D6 will bind it deterministically later.

### 7.4 Binding class must be from the frozen enum

Unknown values fail closed.

### 7.5 `PROVIDER` does not imply provider-native fields belong in canonical input

`PROVIDER` is reserved for a canonical slot whose value is intentionally resolved only after ProviderBinding.

It must not be used to smuggle arbitrary Host command parameters into `input_schema`.

Architecture tests/review SHALL continue to enforce the Host-native boundary.

---

## 8. Intent-visible schema projection

Step 23 SHALL add a deterministic helper on the canonical action contract that returns the schema visible to the LLM for intent filling.

Conceptually:

```text
canonical input schema
+
slot binding policy
  ↓
keep INTENT slots only
  ↓
intent-visible schema
```

For `move.v1`, canonical schema contains:

```text
targets
displacement
```

but intent-visible schema SHALL contain only:

```text
displacement
```

### 8.1 Projection rules

The helper SHALL:

1. copy the canonical schema rather than return internal mutable references;
2. retain only top-level properties whose binding class is `INTENT`;
3. retain in `required` only required properties that remain visible;
4. preserve relevant schema keywords for retained intent properties;
5. preserve `additionalProperties` policy;
6. not invent values for non-INTENT slots;
7. not perform context/default/derived/provider binding.

### 8.2 Step 23 does not switch D4 to this helper yet

This is a critical scope boundary.

Step 23 freezes the correct action-contract capability, but **D4 behavior remains unchanged in production** until Step 24 integrates semantic eligibility/action-space behavior deliberately.

Reason:

- Step 23 owns the contract;
- Step 24 owns D4 semantic eligibility and how D4 projects it;
- mixing both in one PR would blur the implementation roadmap and make regression attribution harder.

Tests in Step 23 may directly exercise the contract projection helper.

---

## 9. MOVE_V1 frozen fixture

Step 23 SHALL upgrade the existing platform MOVE definition to the following semantic meaning.

```text
canonical_operation = move.v1
version             = 1.0.0
title               = Move entities
description         = canonical Host-independent move meaning
category            = MODEL_OPERATION

canonical slots:
  targets:
    binding = CONTEXT
  displacement:
    binding = INTENT

canonical_entity_constraints = ()

context freshness = ()
operation freshness:
  PLACEMENT / FRESH

coverage requirements  = ()
assurance requirements = ()

effects:
  PLACEMENT
  GEOMETRY

verification:
  HOST_READ_BACK
```

The exact prose description may be concise, but it MUST remain Host-independent.

---

## 10. Immutability / defensive-copy rules

Canonical action definitions are configuration contracts and must be value-oriented.

Step 23 SHALL preserve defensive copying for mutable inputs and extend it to all newly added structured fields.

After construction, mutation of source dictionaries/lists used to create a definition MUST NOT alter the stored definition.

Likewise, helper methods returning projected schemas MUST return independent data.

This prevents catalog meaning from changing because a caller later mutates a Python dict.

---

## 11. Provider boundary invariants

Step 23 SHALL preserve and strengthen these invariants.

### 11.1 Provider MCP schema is not canonical input schema

AutoCAD `cad.move` currently needs native execution fields such as:

```text
handles
dx
dy
dz
idempotency_key
revision
```

These remain provider execution interface fields.

The canonical MOVE contract remains:

```text
targets
displacement
```

Translation belongs to later `ProviderBinding/input-adapter` work.

### 11.2 Provider execution freshness does not redefine task freshness

Step 22 already established:

```text
Canonical Action operation freshness
!=
provider execution_freshness
```

Step 23 keeps that separation.

### 11.3 Provider effects do not define canonical effects

Step 23 moves the source of canonical expected effects into the platform definition.

Provider effect metadata remains useful as capability/conformance evidence, but D4 must not construct the canonical action meaning by unioning provider effects indefinitely.

Full D4 integration of this rule is Step 24, not Step 23.

### 11.4 Provider native constraints do not become canonical entity constraints

`LINE/LWPOLYLINE/ARC` stay provider-native facts.

Step 23 does not rename or migrate the Host capability parser's existing `entity_constraints` field; that broader D3/D4 compatibility migration belongs with Step 24 semantic eligibility.

---

## 12. Production scope

### 12.1 Expected production files

Step 23 SHOULD be implementable primarily in:

```text
platform/orchestrator/src/design_orchestrator/canonical_operations.py
platform/orchestrator/src/design_orchestrator/__init__.py   # only if public exports are required
```

No other production file is presumed necessary by the design.

If implementation reveals that `operation_resolver.py` must change to make Step 23 tests pass, that is a scope escalation and must be justified against the Step 24 boundary before proceeding.

### 12.2 Explicit production non-goals

Step 23 SHALL NOT modify production code under:

```text
platform/semantic_runtime/
platform/semantic_service/
platform/semantic_mcp/
platform/changeset/
hosts/autocad/
providers/semantics/
contracts/
```

unless a separately identified compatibility defect is discovered and reviewed as such.

### 12.3 No ProviderBinding implementation

No production DTO/function named as Step 31 execution binding is introduced in this step.

### 12.4 No D6 binder implementation

No production target/context/default/derived/provider parameter resolution is implemented.

### 12.5 No Host command generation

No `HostCommand` payload is generated from canonical action slots in this step.

---

## 13. Test design

Step 23 SHALL use TDD during implementation.

### 13.1 Contract completeness test

Verify `MOVE_V1` exposes all frozen Step 23 contract fields and values.

Expected assertions include:

```text
canonical_operation == move.v1
version == 1.0.0
category == MODEL_OPERATION
slot policy targets == CONTEXT
slot policy displacement == INTENT
canonical constraints == ()
operation freshness == PLACEMENT/FRESH
effects == PLACEMENT + GEOMETRY
verification == HOST_READ_BACK
```

### 13.2 Intent projection test

Verify the intent-visible schema for MOVE exposes:

```text
displacement
```

and does not expose:

```text
targets
handles
revision
idempotency_key
provider routing ids
```

### 13.3 Missing slot policy fails closed

Construct an action with a canonical schema property lacking a binding policy entry.

Expected: validation error.

### 13.4 Unknown policy slot fails closed

Define policy for a slot not present in canonical schema.

Expected: validation error.

### 13.5 Unknown binding class fails closed

Expected: typed binding model rejects unsupported class.

### 13.6 Defensive-copy test

Mutate original input dictionaries/lists after action construction.

Expected: stored contract remains unchanged.

Mutate a returned intent-schema projection.

Expected: subsequent projection and canonical schema remain unchanged.

### 13.7 Provider isolation architecture test

Verify `canonical_operations.py` does not contain known provider-native routing identifiers such as:

```text
cad.move
handles
ElementId
autocad.sidecar
revit
```

This guard should be precise enough to avoid false positives in descriptive comments/docstrings where possible.

### 13.8 Step 22 regression

Existing Step 22 resolver/progressive tests must remain green.

Step 23 must not regress the ownership rule that unbound providers cannot inflate D5 task semantic requirements.

---

## 14. CI strategy

A dedicated Step 23 workflow SHOULD:

1. install the orchestrator package and existing minimal dependencies;
2. run Step 23 canonical-action tests;
3. run existing `tests/orchestrator/test_operation_resolver.py`;
4. run relevant Step 22 integration regression where dependency closure allows;
5. run the relevant broad Python regression used by the existing orchestrator workflow;
6. enforce an exact approved-file boundary for the PR.

The final file allowlist will be frozen in the implementation plan after concrete test/workflow file paths are selected.

---

## 15. Error handling

Step 23 validation errors are construction/configuration errors, not runtime Host errors.

The contract SHALL fail fast and deterministically for:

```text
empty canonical operation
empty version/title/description where required
invalid category
non-object input schema
non-object verification contract
missing slot binding classification
unknown slot binding classification
binding policy referencing an unknown slot
invalid structured requirement collection shapes
```

Step 23 does not add new cross-service `ErrorShape` codes because no new remote/runtime API is introduced.

---

## 16. Compatibility rules

### 16.1 Existing resolver construction

The catalog object must remain straightforward for `OperationResolver` to consume.

Step 23 should avoid gratuitous resolver API churn.

### 16.2 Existing field names

Current Step 22 fields:

```text
context_freshness_requirements
operation_freshness_requirements
```

are retained.

### 16.3 Existing canonical MOVE semantic input

The canonical MOVE schema remains semantically `targets + displacement`; Step 23 changes slot ownership metadata, not the underlying meaning of MOVE.

### 16.4 Host provider profile unchanged

AutoCAD capability parsing and MCP metadata remain unchanged in Step 23.

This ensures provider compatibility regression can isolate Canonical Action contract changes.

---

## 17. Architecture guards

The following should be automated where practical.

1. Canonical Action production code does not import Host sidecar/provider packages.
2. Canonical Action production code does not import concrete semantic providers.
3. `slot_binding_policy` is platform-owned and typed.
4. Every canonical top-level slot has exactly one binding class.
5. LLM intent projection contains only `INTENT` slots.
6. Canonical `effects` are stored on the platform definition.
7. Canonical task freshness remains stored on the platform definition.
8. `MOVE_V1` has no Host-native entity constraints.
9. Step 23 does not add `ProviderBinding`, `HostCommand` generation, or ChangeSet execution logic.
10. Step 22 progressive semantics regressions remain green.

---

## 18. Relationship to Step 24

Step 24 will deliberately integrate canonical semantic applicability into D4.

Expected Step 24 questions include:

- how `canonical_entity_constraints` are evaluated against D5 canonical classification;
- how provider-native constraints are separated from canonical constraints in D3/D4;
- how D4's LLM action space uses the intent-visible schema;
- how canonical effects replace provider-aggregated effects in `ResolvedOperation`;
- how availability still depends on at least one compatible provider without allowing providers to redefine semantic meaning.

Step 23 does not answer those by modifying D4 behavior early.

---

## 19. Relationship to Step 25

Step 25 will implement D6 Slot Binder using the binding metadata frozen here.

For MOVE, Step 25 should eventually produce evidence conceptually like:

```text
targets      <- ContextSnapshot.selection
displacement <- UserIntent
```

Step 23 only makes that ownership machine-readable.

---

## 20. Relationship to Step 30/31

The master spec requires:

```text
ExecutionSlice
  ↓
ExecutionUnit (canonical)
  ↓
ProviderBinding (provider/native)
  ↓
HostCommand
```

The Canonical Action contract from Step 23 is upstream semantic input to that chain.

It MUST NOT contain:

```text
provider_tool
AutoCAD Handle
Revit ElementId
internal unit
revision token
idempotency key
```

Those enter only at later execution binding/command stages.

---

## 21. Acceptance criteria

Step 23 implementation is complete only when all of the following are true.

1. `CanonicalOperationDefinition` represents the full Step 23 contract shape.
2. Slot binding classes are typed and frozen to the five v0.6 values.
3. Every top-level canonical input slot is classified exactly once.
4. Invalid/missing slot policies fail closed.
5. An intent-visible schema projection exists and returns only `INTENT` slots.
6. `MOVE_V1.targets` is `CONTEXT`.
7. `MOVE_V1.displacement` is `INTENT`.
8. `MOVE_V1.operation_freshness_requirements` remains exactly `PLACEMENT/FRESH`.
9. `MOVE_V1.effects` is canonically `PLACEMENT + GEOMETRY` without making GEOMETRY a pre-operation freshness requirement.
10. `MOVE_V1.canonical_entity_constraints` contains no AutoCAD/Revit native kinds.
11. Coverage and assurance requirement fields exist as platform-owned metadata even when empty for MOVE.
12. Contract inputs and projections are defensively copied/value-oriented.
13. No Host, D5, Semantic Service, semantic provider, ChangeSet, ProviderBinding, or D6 production logic is added.
14. Existing Step 22 regressions remain green.
15. CI proves the approved Step 23 file boundary and relevant broad regression.

---

## 22. Non-goals

Step 23 does not attempt to:

- implement D4 semantic classification eligibility;
- split/migrate the Host capability parser's native constraint DTO in production;
- implement D6 parameter resolution;
- start Host interaction sessions;
- build immutable v0.6 ChangeSets;
- redesign current placeholder `platform/changeset` DTOs;
- implement canonical `ExecutionUnit`;
- implement `ProviderBinding`;
- compute `binding_set_hash`;
- issue `ExecutionGrant`;
- generate native HostCommand payloads;
- implement wall-thickness domain action yet;
- change IFC/Metro/Enterprise semantic providers.

---

## 23. Final system boundary after Step 23

After Step 23, the project should have this clean separation:

```text
Canonical Action Catalog
  knows:
    operation meaning
    canonical slots
    who owns each slot class
    canonical semantic applicability metadata
    task semantic requirements
    canonical effects
    verification expectation

D4
  still knows:
    which actions are currently resolvable
    candidate providers internally

Provider Profile
  knows:
    native capability/interface claims

D5
  knows:
    semantic state / freshness / coverage / assurance

D6 (future)
  will know:
    concrete canonical argument binding

D7 (future)
  will know:
    approved canonical transaction and execution planning

ProviderBinding (future Step 31)
  will know:
    concrete provider/tool/native execution binding
```

The invariant to preserve is:

> **Canonical Action defines what the operation means. A Provider only defines how one implementation can execute it.**
