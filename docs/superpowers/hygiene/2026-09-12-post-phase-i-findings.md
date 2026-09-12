# Post-Phase-I Engineering Hygiene Findings

**Baseline:** `main@d2d1621b30f87506c62adb2d12f73d387821ef78`  
**Design:** `docs/superpowers/specs/2026-09-12-post-phase-i-engineering-hygiene-design.md`  
**Plan:** `docs/superpowers/plans/2026-09-12-post-phase-i-engineering-hygiene.md`  
**Date:** 2026-09-12

## Classification contract

Every finding uses exactly one implementation disposition:

- `REMOVE` — proven obsolete/unreachable and safe to delete.
- `FIX` — engineering-infrastructure/test/document defect that can be corrected without changing product semantics.
- `CONSOLIDATE` — duplicated infrastructure can be merged while preserving coverage and focused ownership.
- `DOCUMENT` — current-truth documentation/lifecycle/navigation work only.
- `DEFER` — behavior-neutrality or architectural safety is not sufficiently proven for this hygiene stage.

Historical Design Specs and Implementation Plans are engineering records. Their technical bodies are frozen; this ledger may describe their lifecycle without rewriting them.

## Frozen broad-tail workflow set

The historical workflows targeted only for repository-wide pytest-tail consolidation are:

```text
.github/workflows/step25-d6-parameter-binder.yml
.github/workflows/step26-interaction-session.yml
.github/workflows/step27-impact-layer.yml
.github/workflows/step28-approval-scope.yml
.github/workflows/step29-immutable-changeset.yml
.github/workflows/step30-execution-partitioning.yml
.github/workflows/step31-provider-binding.yml
.github/workflows/step32-gateway-authorization.yml
.github/workflows/step33-execution-reconciliation.yml
.github/workflows/step34-autocad-wall-thickness.yml
.github/workflows/step36-offset-create-scope-breach.yml
.github/workflows/step37-cross-host-saga-failure-injection.yml
```

`.github/workflows/phase-h-revit-wall-thickness.yml` is explicitly **not** in that consolidation set; it is a focused capability gate. Phase I keeps separate offline and real dual-Host acceptance responsibilities.

## Findings ledger

| ID | Priority | Classification | Evidence | Allowed Action | Verification | Resolution |
|---|---|---|---|---|---|---|
| HYG-001 | P0 | CONSOLIDATE | Historical Step25–37 workflows above carry repository-wide pytest tails in addition to focused Step/domain guards; main CI shows broad-tail drift while representative focused gates remain meaningful. The new neutral repository-regression owner runs root pytest in importlib mode for the valid repository-wide union, normal mode for local-parity coverage, a repository Ruff baseline-delta guard, and Revit Core as an explicit current gate. | Add one neutral current repository-wide regression owner; remove only duplicated broad pytest tails after the new gate is proven green/superset. Preserve focused tests, architecture guards, path filters, diff checks and Step36/37 Ruff-delta guards. | `repository-regression` green; structural workflow tests; root importlib + normal pytest green; modified historical focused workflows green. | CURRENT GATE ADDED — historical-tail consolidation remains pending until `Repository regression` is green in CI |
| HYG-002 | P0 | FIX | `tests/materialization_planning/conftest.py` exposes reusable builders imported as API; execution-planning tests also import a sibling test module. Importlib collection therefore depends on incidental test module layout. | Move reusable helpers into explicit `_support.py` modules; leave `conftest.py` for pytest fixture wiring only; production code unchanged. | Affected domains pass in importlib and normal modes; forbidden test-module imports absent. | OPEN |
| HYG-003 | P0 | FIX | `tests/integration/test_phase_i_environment_discovery_script.py` still requires `Get-FileHash`, while the current discovery script uses shared-read SHA-256 via `Get-SharedReadSha256` so controlled fixtures can remain open. | Update the stale source-text test only. Do not change `discover_phase_i_live_environment.ps1`. | Targeted test green; repository suites green. | OPEN |
| HYG-004 | P1 | DOCUMENT | Root README still describes the earlier AutoCAD/M1/v0.5 state rather than the completed Phase I multi-Host baseline. | Refresh current-state entrypoint text and links only. | README structural/lifecycle checks and link existence. | OPEN |
| HYG-005 | P1 | DOCUMENT | `docs/superpowers/specs/` and `docs/superpowers/plans/` have no complete lifecycle/navigation index. | Add `docs/superpowers/README.md`; index all design/plan records externally without editing historical technical bodies. | Structural lifecycle-index test covers every current design/plan filename. | OPEN |
| HYG-006 | P1 | DOCUMENT | `pyproject.toml` pytest comments/marker wording and `tests/__init__.py` rationale are Phase-I/Host-specific although their behavior is now repository-wide. | Generalize comments/marker description only; keep `pythonpath` values and package behavior unchanged. | Collection count/parity checks; root pytest modes green. | OPEN |
| HYG-007 | P1 | FIX | `test_move_idempotency.py` and `test_revision_conflict.py` construct `HostAdapter()` directly while other basic live AutoCAD tests use the repository discovery/override helper. | Normalize those two tests to `live_autocad_host_adapter()` only; do not change production `HostAdapter` defaults. | Helper tests green; live tests retain the same explicit offline skip. | OPEN |
| HYG-008 | P1 | DEFER | `*_v2` bridge/compatibility modules are referenced by current public/execution paths; static appearance is not evidence of dead code. | No deletion/refactor in this stage. | Diff proves no V2 production bridge removal. | DEFERRED — current path retained |
| HYG-009 | P1 | DOCUMENT | Historical temporary spec-transfer/refinement artifacts were already removed in prior work. No current source-tree removal is required. | Record verified-clean state only. | Current tree contains no reintroduced temporary transfer artifacts. | VERIFIED CLEAN — no edit required |
| HYG-010 | P1 | DEFER | `jsonschema.RefResolver` warning exists, but contract-equivalent migration has not been proven in the frozen hygiene scope. | No runtime validator migration here. | Diff proves validation production path unchanged. | DEFERRED |
| HYG-011 | P1 | DEFER | GitHub-hosted jobs report Action/Node runtime maintenance warnings. Upgrading actions is separable infrastructure maintenance and not required for the P0 correctness fixes. | Do not mix action-version upgrades into this cleanup. | Workflow diff shows no unrelated action-version churn. | DEFERRED |
| HYG-012 | P1 | DOCUMENT | Phase H workflow is focused-only and therefore not evidence for the historical broad-tail consolidation problem. | Retain Phase H workflow structure; document separate focused ownership. | Structural workflow test verifies Phase H focused steps remain. | OPEN |
| HYG-013 | P1 | DOCUMENT | gRPC generator/transport tooling remains referenced by transport conformance/dev workflows; it is not proven dead. | Retain tooling and document KEEP rationale; no removal. | Current workflow/tool references remain present. | OPEN |
| HYG-014 | P0 | FIX | Phase H run on `main@d2d1621` fails one Revit architecture source-contract assertion: test expects `revisions.Get(document)` but current handler reads `revisions.Get(uiDocument.Document)` after the executor boundary moved to `UIDocument`; Revit Core .NET tests remain green. | Update only the stale Python architecture textual assertion. Do not edit `RevitExternalEventHandler.cs`, `DocumentRevisionTracker.cs`, or Host behavior. | `tests/revit/test_revit_architecture.py` green; Revit Core .NET tests green; Phase H workflow green. | OPEN |

## Edit-boundary check

Production paths such as `platform/**/src/**`, Host/plugin runtime, provider runtime, and contracts/schema may appear in this ledger only as evidence/context. They are not approved hygiene edit targets. Any newly discovered fix that requires those surfaces is `DEFER` unless the frozen scope is explicitly redesigned and re-approved.
