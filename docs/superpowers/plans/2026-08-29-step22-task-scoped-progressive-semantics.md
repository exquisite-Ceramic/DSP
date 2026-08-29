# Step 22 — Task-Scoped Progressive Semantics Implementation Plan

> Status: Implementation executed; final PR verification in progress  
> Date: 2026-08-29  
> Branch: `feat/step22-task-scoped-progressive-semantics`  
> Base: `main@112864e529e4573b81947b97596d3d05ca4344bd`  
> Design: `docs/superpowers/specs/2026-08-29-step22-task-scoped-progressive-semantics-design.md`

## 1. Goal

Make canonical operations, not unbound Host providers, own D5 task semantic requirements, then prove that D5 upgrades only the aspects and progressive fidelity explicitly required by the task.

The target ownership chain is:

```text
Canonical task
  -> CanonicalOperationDefinition.operation_freshness_requirements
  -> ResolvedOperation.operation_freshness_requirements
  -> requirements_from_mappings
  -> D5 FreshnessContract
  -> only requested aspects/fidelity reconstructed
  -> only requested aspects marked fresh
```

Provider execution preconditions remain a separate later-stage concern:

```text
DesignCapabilityProfile.execution_freshness
  -> retained on provider candidate
  -> future late ProviderBinding / execution admission
  -X-> pre-binding D5 task requirement source
```

## 2. Frozen architectural constraints

- `CanonicalOperationDefinition` owns canonical operation/task semantic requirements.
- `ResolvedOperation.operation_freshness_requirements` copies canonical requirements.
- Candidate provider `execution_freshness` must not be unioned into D5 requirements before ProviderBinding.
- LLM-facing action space exposes canonical freshness only.
- `MOVE_V1` requires exactly `PLACEMENT / FRESH`.
- MOVE may have `PLACEMENT` and `GEOMETRY` effects without requiring pre-operation geometry reconstruction.
- No new semantic requirement DTO.
- No D5 production API or algorithm change.
- No Host production change.
- No Semantic Service, Semantic MCP, IFC, Metro, Enterprise Mapping, Contract, ChangeSet, approval, execution-grant, or ProviderBinding production change.
- Coverage, depth, assurance, geometry, revision, and freshness remain fail-closed.
- The LLM does not choose safety/quality fidelity axes.
- No merge without explicit user authorization.

## 3. Final approved file boundary

The implementation initially planned seven files. PR-context verification exposed a pre-existing CI dependency-closure defect in `.github/workflows/operation-resolver.yml`: its full regression collects `tests/integration` but did not install `semantic_runtime`. Step21 had already introduced a semantic-runtime-dependent integration test, but that workflow had not been retriggered by Step21 because Step21 changed no orchestrator path.

The final Step22 boundary is therefore **eight files**, with only two production files:

```text
.github/workflows/operation-resolver.yml
.github/workflows/step22-task-scoped-progressive.yml
docs/superpowers/plans/2026-08-29-step22-task-scoped-progressive-semantics.md
docs/superpowers/specs/2026-08-29-step22-task-scoped-progressive-semantics-design.md
platform/orchestrator/src/design_orchestrator/canonical_operations.py
platform/orchestrator/src/design_orchestrator/operation_resolver.py
tests/integration/test_step22_task_scoped_progressive.py
tests/orchestrator/test_operation_resolver.py
```

Production changes remain limited to:

```text
platform/orchestrator/src/design_orchestrator/canonical_operations.py
platform/orchestrator/src/design_orchestrator/operation_resolver.py
```

The extra eighth file is CI-only and does not expand the architectural production scope.

## 4. Task 1 — Establish RED for provider-driven reconstruction inflation

### Files

- `tests/orchestrator/test_operation_resolver.py`
- bootstrap `.github/workflows/step22-task-scoped-progressive.yml`

### Steps

- [x] Bootstrap a branch CI harness that runs the existing D4 resolver suite.
- [x] Verify the pre-change D4 baseline is green.
- [x] Add a multi-provider regression:

```text
Provider A execution_freshness:
  PLACEMENT / FRESH

Provider B execution_freshness:
  PLACEMENT / FRESH
  GEOMETRY / FRESH / EXACT

Canonical MOVE requirement:
  PLACEMENT / FRESH
```

- [x] Assert both `ResolvedOperation` and LLM-facing action space contain only canonical `PLACEMENT / FRESH`.
- [x] Assert Provider B still retains its stronger provider-specific execution freshness.
- [x] Add a regression proving `effects` do not implicitly become freshness requirements.
- [x] Run the RED test before production modification.

### RED evidence

Commit:

```text
27356342f2409eddc73e49fabd507f984c23bedf
```

Result:

```text
1 failed, 17 passed
```

The failure showed old D4 behavior added Provider B's `GEOMETRY / EXACT` requirement to `ResolvedOperation.operation_freshness_requirements`.

## 5. Task 2 — Move ownership to the canonical operation catalog

### Files

- `platform/orchestrator/src/design_orchestrator/canonical_operations.py`
- `platform/orchestrator/src/design_orchestrator/operation_resolver.py`

### Steps

- [x] Add:

```python
operation_freshness_requirements: tuple[dict[str, Any], ...] = ()
```

- [x] Deep-copy the new field in `CanonicalOperationDefinition.__post_init__`.
- [x] Pin `MOVE_V1` to:

```python
operation_freshness_requirements=(
    {"aspect": "PLACEMENT", "required_state": "FRESH"},
)
```

- [x] Change `_build_resolved_operation()` to copy:

```python
definition.operation_freshness_requirements
```

instead of aggregating candidate provider `execution_freshness`.

- [x] Remove the now-unused provider freshness aggregation helper.
- [x] Leave Host/Entity/Policy/Task filtering, candidate identity, effects, risk, preview, rollback, and verification aggregation unchanged.

### GREEN evidence

After the minimal production change:

```text
18 passed
```

for `tests/orchestrator/test_operation_resolver.py`.

## 6. Task 3 — Prove progressive minimality through existing D5

### File

- `tests/integration/test_step22_task_scoped_progressive.py`

No D5 production helper or interface is introduced.

### Proof A — Real MOVE upgrades placement only

- [x] Use real AutoCAD `cad.move` capability metadata.
- [x] Resolve through real D4 `OperationResolver((MOVE_V1,))`.
- [x] Convert canonical freshness via `requirements_from_mappings()`.
- [x] Assert task requirements are exactly `PLACEMENT`.
- [x] Assert operation effects still include `GEOMETRY`.
- [x] Build one-target operation coverage.
- [x] Mark `PLACEMENT`, `GEOMETRY`, and `CLASSIFICATION` dirty.
- [x] Reconstruct only `PLACEMENT`.
- [x] Assert only `PLACEMENT` becomes fresh.
- [x] Assert `GEOMETRY` and `CLASSIFICATION` remain dirty.

### Proof B — Classification-only task does not upgrade geometry or assurance

- [x] Require `CLASSIFICATION / RESOLVED / CANONICAL / RULE_DERIVED`.
- [x] Use `GeometryLevel.NONE`.
- [x] Reconstruct exactly the requested classification guarantee.
- [x] Assert snapshot contains only the classification guarantee.
- [x] Assert assurance remains `RULE_DERIVED`.
- [x] Assert geometry remains dirty.

### Proof C — Exact geometry is required only when explicit

- [x] Explicitly require `GEOMETRY / EXACT`.
- [x] Prove `BOUNDS` fails with `GEOMETRY.geometry`.
- [x] Prove dirty state remains dirty after failure.
- [x] Prove `EXACT` succeeds.
- [x] Prove unrelated classification remains dirty.

Focused result:

```text
3 passed
```

## 7. Task 4 — Step22 CI and exact boundary

### File

- `.github/workflows/step22-task-scoped-progressive.yml`

### Required stack

The dedicated workflow installs:

```text
contracts/python
hosts/autocad/sidecar
platform/semantic_runtime
platform/semantic_service
platform/semantic_mcp
providers/semantics/dsp_core
providers/semantics/ifc43
providers/semantics/metro_v32
providers/semantics/enterprise_mapping
```

### Required checks

- [x] D4 ownership tests.
- [x] Step22 progressive D5 proof.
- [x] Existing D4 -> D5 freshness bridge.
- [x] Existing progressive semantic-runtime regression.
- [x] Step21 canonical projection + architecture regression.
- [x] Broad relevant Python regression.
- [x] PR-context exact changed-file gate.

The final exact boundary accepts only the eight paths listed in Section 3.

## 8. Task 5 — Existing Operation Resolver CI compatibility closure

### Root cause

The pre-existing workflow:

```text
.github/workflows/operation-resolver.yml
```

runs:

```text
pytest -q contracts/python/tests tests/contracts tests/integration tests/orchestrator
```

but installed only:

```text
contracts/python
hosts/autocad/sidecar
```

Once Step21 existed on `main`, collecting `tests/integration/test_step21_d5_canonical_projection.py` required `semantic_runtime`. The defect remained latent until an orchestrator-changing PR retriggered this workflow.

PR #15 initially reproduced the failure as:

```text
ModuleNotFoundError: No module named 'semantic_runtime'
```

for Step21 and Step22 integration collection.

### Minimal fix

- [x] Add only:

```text
-e platform/semantic_runtime
```

to the existing Operation Resolver workflow install step.

- [x] Do not add Semantic Service/providers to that workflow; Step21's higher-level provider stack remains optional/skipped there as designed.
- [x] Re-run the same PR-context workflow.
- [x] Confirm both focused resolver tests and its full regression succeed.

This is CI dependency closure only; no production ownership changes result from it.

## 9. Verification matrix

At the final PR head, require fresh evidence for all rows:

| Check | Required result |
|---|---|
| Step22 D4 ownership | green |
| Step22 progressive D5 | green |
| D4 -> D5 freshness bridge | green |
| Progressive runtime | green |
| Step21 canonical projection + architecture | green |
| Broad relevant Python regression | zero failures |
| Existing Operation Resolver workflow | green |
| Step22 PR changed-file boundary | exactly 8 approved files |
| D5 production diff | 0 |
| Host production diff | 0 |
| Semantic Service/MCP/provider production diff | 0 |
| Contracts/ChangeSet production diff | 0 |

Known acceptable skips remain the four live AutoCAD integration tests gated by `AGENT_HOST_TEST=1`.

The existing `jsonschema.RefResolver` deprecation warning is not introduced by Step22.

## 10. Final architecture review checklist

Before marking the PR ready, confirm:

- [ ] `CanonicalOperationDefinition` is the owner of task operation freshness.
- [ ] `MOVE_V1` canonical freshness is exactly `PLACEMENT / FRESH`.
- [ ] `ResolvedOperation` copies canonical freshness.
- [ ] LLM-facing action space exposes canonical freshness only.
- [ ] Provider `execution_freshness` remains on provider candidates.
- [ ] No unbound provider freshness union feeds D5.
- [ ] Effects do not create task requirements.
- [ ] MOVE only marks `PLACEMENT` fresh in the Step22 proof.
- [ ] Classification-only proof leaves geometry dirty and assurance unchanged.
- [ ] Explicit `GEOMETRY / EXACT` fails closed on weaker evidence.
- [ ] Coverage remains exactly the explicit target set.
- [ ] D5 production diff is zero.
- [ ] Host production diff is zero.
- [ ] Semantic provider production diff is zero.
- [ ] No Step23 ProviderBinding/execution-admission subsystem is implemented.
- [ ] Both PR-context workflows are green at the exact final head.
- [ ] PR remains draft until final review is clean.

## 11. Pull request

Draft PR:

```text
#15 fix(step22): keep D5 reconstruction task-scoped
```

The PR must remain draft through final code review and fresh PR-context verification.

Do not merge without explicit user authorization.

## 12. Completion criterion

Step 22 is complete only when repository evidence proves:

```text
Task / Canonical Operation
  decides
D5 semantic reconstruction scope and fidelity
```

while also proving:

```text
unbound provider execution requirements
  cannot inflate
pre-binding D5 reconstruction
```

and preserving the future late-binding rule:

```text
selected provider
  MAY require stronger execution evidence
  but only after ProviderBinding
```

The final architectural result is:

> The task determines what D5 must understand. The selected Host provider may later require stronger execution evidence, but unselected providers cannot increase D5 semantic reconstruction scope.
