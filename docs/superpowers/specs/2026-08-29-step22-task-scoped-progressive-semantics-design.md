# Step 22 — Task-Scoped Progressive Semantic Ownership Design

> Status: Approved design baseline  
> Date: 2026-08-29  
> Branch: `feat/step22-task-scoped-progressive-semantics`  
> Base: `main@112864e529e4573b81947b97596d3d05ca4344bd`  
> Master spec: `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step 22 proves and hardens the v0.6 rule that DSP reconstructs only the semantic aspects, coverage, depth, assurance, and geometry fidelity required by the current task.

The key architectural ownership rule is:

```text
Task / Canonical Operation
  decides
D5 semantic reconstruction requirements
```

while:

```text
Bound Host Provider
  decides
provider-specific execution preconditions
```

These are related but not the same contract.

Step 22 must prevent provider-specific execution metadata from inflating D5 semantic reconstruction before late ProviderBinding.

## 2. Master-spec alignment

The v0.6 master spec requires the semantic runtime to be progressive by default:

```text
task-scoped
aspect-scoped
coverage-scoped
on-demand reconstruction
```

It also states that reconstruction must not turn a narrow request into a full IFC/Metro rebuild.

The relevant ownership boundaries are:

- D4 owns the canonical action space.
- D5 owns the task-scoped canonical semantic projection and freshness barrier.
- Host/Execution Providers own Host-specific execution requirements.
- Provider binding happens late, after canonical planning has already been expressed independently of a concrete Host provider.
- Host-native details and provider-specific execution mechanics must not leak into canonical semantic planning.

Step 22 therefore treats semantic reconstruction requirements as part of the canonical operation contract, not as a union of all available provider execution requirements.

## 3. Current state

### 3.1 D5 progressive mechanics are already sufficient

The current `semantic_runtime` already models progressive requirements with independent axes:

```text
AspectRequirement {
  aspect
  geometry_level
  minimum_coverage
  semantic_depth
  minimum_assurance
}
```

The current runtime also already provides the correct lower-level behavior:

1. `build_operation_contract()` binds explicit targets and explicit requirements.
2. `requirements_from_mappings()` parses only explicitly supplied requirement mappings.
3. Duplicate requirements for the same aspect are merged conservatively, axis by axis.
4. `FreshnessResolver` fails closed when coverage, semantic depth, assurance, geometry, or freshness is insufficient.
5. On success, only the aspects present in the operation contract are marked fresh in `DirtyMap`.
6. Unrequested aspects are not automatically marked fresh.

Therefore Step 22 does **not** need a new D5 progressive model, new D5 DTO, or new freshness algorithm.

### 3.2 The ownership leak is upstream of D5

The current D4 `OperationResolver` builds `ResolvedOperation.operation_freshness_requirements` by aggregating every candidate provider's `execution_freshness` metadata.

This is acceptable while only one provider exists and all providers happen to declare identical requirements, but it is not a stable multi-Host ownership model.

For example:

```text
Canonical operation: move.v1

Provider A execution_freshness:
  PLACEMENT / FRESH

Provider B execution_freshness:
  PLACEMENT / FRESH
  GEOMETRY / EXACT
```

If D4 unions both provider declarations before ProviderBinding, D5 is forced to reconstruct `GEOMETRY / EXACT` even when:

- the task itself only needs placement semantics to plan the move;
- Provider A may eventually be selected;
- ProviderBinding has not happened yet;
- the canonical action must remain Host-independent.

That behavior violates the intent of task-scoped progressive semantics.

## 4. Decision

### 4.1 Canonical Operation owns task semantic requirements

`CanonicalOperationDefinition` SHALL gain an explicit field:

```text
operation_freshness_requirements
```

using the already-existing provider-neutral freshness mapping shape.

No new semantic-requirement DTO is introduced in Step 22.

The authoritative D4 -> D5 operation semantic requirements SHALL come from the canonical operation definition.

The flow becomes:

```text
CanonicalOperationDefinition.operation_freshness_requirements
  -> ResolvedOperation.operation_freshness_requirements
  -> requirements_from_mappings(...)
  -> FreshnessContract.requirements
  -> D5 reconstruction barrier
```

### 4.2 Provider execution freshness remains provider-owned

`DesignCapabilityProfile.execution_freshness` remains valid metadata.

It changes semantic role:

```text
Before Step 22 interpretation:
  candidate provider execution_freshness
    -> D4 union
    -> D5 task semantic requirements

After Step 22 interpretation:
  candidate provider execution_freshness
    -> retained with provider candidate
    -> future late ProviderBinding / execution admission
```

Step 22 SHALL NOT delete provider `execution_freshness` metadata.

Step 22 SHALL NOT implement the full late-binding execution-admission mechanism. That belongs to a later step.

### 4.3 Provider requirements may strengthen execution admission only after binding

A bound provider may legitimately require stronger execution evidence than the canonical task needed for semantic planning.

For example:

```text
Canonical move.v1 semantic requirement:
  PLACEMENT / FRESH

Bound provider execution precondition:
  PLACEMENT / FRESH
  GEOMETRY / EXACT
```

This does not mean D4 should request exact geometry from D5 before binding.

The later execution path MAY construct a provider-bound admission requirement that conservatively strengthens the already-approved canonical requirements.

The future rule is:

```text
effective execution admission
  MUST NOT be weaker than canonical task requirements
  MAY be stronger because of the selected provider
  MUST be computed only after a specific provider is bound
```

Step 22 freezes this ownership rule but does not implement that future admission object.

## 5. Canonical operation contract changes

### 5.1 New field

`CanonicalOperationDefinition` SHALL contain both:

```text
context_freshness_requirements
operation_freshness_requirements
```

The distinction remains:

- `context_freshness_requirements`: semantic state required to expose/consider the operation in context.
- `operation_freshness_requirements`: semantic state required to plan the selected canonical operation.

Both are platform-owned and Host-independent.

### 5.2 MOVE v1 requirement

For the current MVP `MOVE_V1`, the canonical operation requirement SHALL be exactly:

```text
PLACEMENT
required_state = FRESH
```

No geometry requirement is added.

This is intentional even though the provider effect metadata currently includes:

```text
PLACEMENT
GEOMETRY
```

Input semantic requirements and output effects are different concepts.

```text
requirement = what must be understood before planning/execution admission

effect = what the operation may change and therefore what may become dirty / need verification afterward
```

A change to geometry does not imply exact geometry must be reconstructed before every move.

## 6. ResolvedOperation behavior

`ResolvedOperation.operation_freshness_requirements` SHALL be copied from the platform-owned `CanonicalOperationDefinition.operation_freshness_requirements`.

It SHALL NOT be produced by unioning candidate provider `execution_freshness` declarations.

Candidate provider profiles remain available through the existing internal provider-candidate map for later execution-time binding.

The LLM-facing action-space output continues to expose canonical operation freshness requirements only.

Provider-native freshness preconditions SHALL NOT be surfaced as if they were task semantic requirements.

## 7. Progressive semantics invariants

Step 22 freezes the following invariants.

### 7.1 Aspect minimality

If an operation requires only:

```text
PLACEMENT
```

then D5 SHALL NOT automatically require:

```text
GEOMETRY
CLASSIFICATION
PROPERTIES
RELATIONSHIPS
...
```

### 7.2 Geometry minimality

`GeometryLevel` remains meaningful only for the `GEOMETRY` aspect.

A non-geometry operation requirement cannot silently request geometry fidelity.

A task that requires `GEOMETRY / BOUNDS` SHALL NOT be upgraded to `EXACT` or `NATIVE` without an explicit stronger requirement.

### 7.3 Coverage minimality

Operation coverage remains exactly the operation targets and explicit neighborhood scope encoded in the freshness contract.

A task targeting one semantic entity SHALL NOT silently expand to whole-document or whole-project reconstruction.

### 7.4 Semantic-depth minimality

If a canonical operation only requires `NORMALIZED`, D5 SHALL NOT require `CANONICAL` or `DOMAIN` solely because those richer representations are available.

If a canonical operation explicitly requires `CANONICAL` or `DOMAIN`, weaker evidence SHALL fail closed.

### 7.5 Assurance minimality

If an operation requires `RULE_DERIVED`, stronger evidence may satisfy it, but D5 SHALL NOT claim stronger assurance than the actual reconstruction evidence.

If an operation requires `STANDARD_MAPPED`, `RULE_DERIVED` evidence SHALL fail closed.

### 7.6 No freshness by side effect

When a contract succeeds, only requested aspects SHALL become fresh in `DirtyMap`.

Other aspects remain in their previous `DIRTY`, `STALE`, or `UNKNOWN` states until separately reconstructed.

## 8. Required proof scenarios

### 8.1 MOVE only upgrades placement

Use the real current AutoCAD MOVE capability and D4 resolver path.

Expected canonical semantic requirement:

```text
PLACEMENT / FRESH
```

The D5 proof SHALL demonstrate:

- `PLACEMENT` can become fresh;
- `GEOMETRY` is not part of the operation freshness contract;
- `CLASSIFICATION` is not part of the operation freshness contract;
- geometry may still be an operation effect without being a pre-operation semantic requirement;
- unrelated dirty/unknown aspects remain unchanged.

### 8.2 Classification-only task does not request geometry

Use a canonical classification requirement such as:

```text
CLASSIFICATION
minimum_coverage = RESOLVED
semantic_depth = CANONICAL
minimum_assurance = RULE_DERIVED
geometry_level = NONE
```

The proof SHALL demonstrate:

- classification can become fresh;
- geometry remains unrequested;
- the snapshot records only the classification guarantee needed by the contract;
- stronger assurance is not fabricated.

This extends the Step 21 wall-classification proof from “canonical evidence reaches D5” to “only the task-requested aspect is upgraded.”

### 8.3 Stronger task upgrades only when explicitly requested

A second canonical operation/test fixture SHALL explicitly request a stronger progressive axis, for example one of:

```text
GEOMETRY / EXACT
```

or:

```text
CLASSIFICATION / DOMAIN / STANDARD_MAPPED
```

The proof SHALL show:

- a weak contract does not request the stronger axis;
- a strong contract does request it;
- insufficient reconstruction evidence fails closed;
- sufficient stronger evidence passes;
- no unrelated aspect is added.

### 8.4 Multi-provider provider-union regression

Construct two provider profiles for the same canonical operation:

```text
Provider A execution_freshness:
  PLACEMENT

Provider B execution_freshness:
  PLACEMENT
  GEOMETRY / EXACT
```

The canonical operation definition remains:

```text
PLACEMENT
```

Expected D4 result:

```text
ResolvedOperation.operation_freshness_requirements
  == canonical operation requirement
  == PLACEMENT only
```

The provider-specific `GEOMETRY / EXACT` requirement SHALL remain attached only to Provider B's profile/candidate metadata.

This is the central Step 22 regression against semantic-reconstruction inflation.

## 9. Data-flow after Step 22

```text
Task intent
  ↓
D4 Canonical Operation
  ├─ canonical context freshness
  └─ canonical operation freshness
          ↓
requirements_from_mappings
          ↓
D5 FreshnessContract
          ↓
task-scoped reconstruction
          ↓
PlanningSnapshot
          ↓
Impact / ChangeSet / Execution Planning
          ↓
late ProviderBinding
          ↓
bound provider execution_freshness
          ↓
future provider-specific execution admission
          ↓
Host execution
```

The important non-flow is:

```text
all candidate providers
  -X-> union execution_freshness
  -X-> inflate D5 task reconstruction
```

## 10. Ownership matrix

| Concern | Owner after Step 22 |
|---|---|
| Canonical action identity | D4 canonical operation catalog |
| Context semantic requirements | Canonical operation definition |
| Operation/task semantic requirements | Canonical operation definition |
| Progressive requirement parsing | D5 `requirements_from_mappings()` boundary adapter |
| Freshness/coverage/depth/assurance enforcement | D5 `FreshnessResolver` |
| Task coverage | D5 freshness contract |
| Host execution mechanics | Host Provider |
| Provider execution preconditions | `DesignCapabilityProfile.execution_freshness` |
| Provider selection | future late ProviderBinding / Provider Resolver |
| Post-operation effects | capability/effect metadata + later impact/verification path |

## 11. Production-code boundary

Step 22 SHOULD make the smallest production change needed to correct ownership.

Expected production files are limited to:

```text
platform/orchestrator/src/design_orchestrator/canonical_operations.py
platform/orchestrator/src/design_orchestrator/operation_resolver.py
```

Tests and CI may be added or updated under:

```text
tests/orchestrator/
tests/semantic_runtime/
tests/integration/
.github/workflows/
```

Step 22 SHOULD NOT require production changes under:

```text
platform/semantic_runtime/
platform/semantic_service/
platform/semantic_mcp/
providers/semantics/
contracts/
hosts/autocad/
platform/changeset/
```

If implementation reveals that one of these paths must change to satisfy the approved behavior, the design must be revisited before expanding scope.

## 12. Compatibility

### 12.1 Existing provider metadata remains valid

No Host capability schema key is removed.

Existing:

```text
com.company.design/execution_freshness
```

continues to parse into `DesignCapabilityProfile.execution_freshness`.

### 12.2 Existing D5 public API remains valid

No changes are planned to:

```text
AspectRequirement
AspectGuarantee
FreshnessContract
ReconstructionResult
FreshnessResolver
SemanticSnapshot
DirtyMap
requirements_from_mappings
```

### 12.3 Existing MOVE provider remains valid

AutoCAD `cad.move` may continue declaring provider execution freshness:

```text
PLACEMENT / FRESH
```

The canonical `MOVE_V1` definition independently declares the same task semantic requirement.

The apparent duplication is intentional because the two declarations have different owners and may diverge for another Host/provider.

## 13. Fail-closed rules

Step 22 must preserve all existing fail-closed behavior.

- Unknown semantic aspect: reject.
- Unknown progressive enum: reject.
- Unsupported required state: reject.
- Insufficient coverage: reject.
- Insufficient semantic depth: reject.
- Insufficient assurance: reject.
- Insufficient geometry level: reject.
- Revision change during reconstruction: reject.
- Coverage mismatch between request and reconstruction: reject.

Separating canonical requirements from provider execution preconditions must not weaken any barrier.

## 14. Architecture guards

Step 22 should add guards proving:

1. `ResolvedOperation.operation_freshness_requirements` comes from canonical operation definition, not candidate provider aggregation.
2. Provider `execution_freshness` remains present in provider candidate metadata.
3. Candidate-provider differences cannot change the D5 task requirement before binding.
4. `effects` cannot implicitly create freshness requirements.
5. D5 production source remains unchanged by Step 22.
6. Host production source remains unchanged by Step 22.
7. Semantic providers remain unchanged by Step 22.

## 15. CI expectations

The Step 22 PR should run at minimum:

```text
1. Step 22 focused D4 ownership tests
2. Step 22 progressive D5 behavior tests
3. Existing D4 freshness integration tests
4. Existing semantic-runtime progressive/freshness tests
5. Existing Orchestrator regression
6. Relevant integration regression
7. Step 21 canonical projection regression
```

A changed-file boundary check should enforce the approved production scope plus Step 22 docs/tests/workflow artifacts.

## 16. Non-goals

Step 22 does not:

- implement a complete ProviderBinding subsystem;
- implement provider-specific execution admission after binding;
- add Revit/Tekla providers;
- change AutoCAD MCP metadata;
- add a new Semantic MCP endpoint;
- change Enterprise/Metro/IFC mappings;
- introduce a new semantic-requirement DTO;
- change semantic claim storage;
- add full geometry reconstruction;
- change ChangeSet, approval, or execution-grant contracts;
- make the LLM choose freshness, coverage, assurance, semantic depth, or geometry fidelity;
- infer semantic requirements from natural-language descriptions;
- infer semantic requirements from operation effects.

## 17. Rejected alternatives

### 17.1 Test-only proof with no ownership correction

Rejected because it would prove only the current single-provider case.

As soon as multiple providers advertise different `execution_freshness`, candidate union can inflate task reconstruction. A Step 22 proof that ignores this would not protect the architecture.

### 17.2 Candidate-provider union as conservative safety

Rejected for the D4 -> D5 task semantic boundary.

It is conservative in the wrong phase. Safety requirements from a provider are meaningful only after that provider is selected. Applying the maximum of all possible providers before binding destroys progressive semantics and couples canonical planning to Host implementation details.

### 17.3 Let the LLM choose semantic fidelity

Rejected because semantic depth, coverage, assurance, and geometry fidelity are machine-enforced safety/quality constraints.

They must come from structured canonical contracts and policy, not from free-form model judgment.

## 18. Completion criterion

Step 22 is complete only when the repository proves:

```text
Canonical task
  -> CanonicalOperationDefinition requirements
  -> ResolvedOperation requirements
  -> D5 FreshnessContract
  -> only requested aspects/fidelity reconstructed
  -> only requested aspects marked fresh
```

while also proving:

```text
candidate provider execution_freshness
  != D5 task semantic requirement source
```

and:

```text
provider-specific stronger preconditions
  remain available for future late-bound execution admission
  but do not inflate pre-binding task reconstruction
```

The architectural result is:

> The task determines what D5 must understand. The selected Host provider may later require stronger execution evidence, but unselected providers cannot increase D5 semantic reconstruction scope.
