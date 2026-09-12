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
| HYG-001 | P0 | CONSOLIDATE | Historical Step25–37 workflows above carried repository-wide pytest tails in addition to focused Step/domain guards; main CI showed broad-tail drift while representative focused gates remained meaningful. | Add one neutral current repository-wide regression owner; remove only duplicated broad pytest tails after the new gate is proven green/superset. Preserve focused tests, architecture guards, path filters, diff checks and Step36/37 Ruff-delta guards. | `repository-regression` green; structural workflow tests; root importlib + normal pytest green; modified historical focused workflows green. | **RESOLVED.** Canonical owner added in `37d2cf27c2ee816434ae9b6d214dcd244835bd14`; Step25–37 broad tails were removed without deleting focused ownership (Step25 `cd0362d1`, Step26 `df53cd1d`, Step27 `7c928028`, Step28 `dc41c573`, Step29 `5a5c0e94`, Step30 `29cae0a6`, Step31 `96964d5f`, Step32 `5d25323b`, Step33 `9b331801`, Step34 `e37c15ce`, Step36 `853eb4de`, Step37 `7a1482fd`). Ownership-source tests were aligned in `d39011c5` / `ecb3c5c2`; historical branch-only diff guards were scoped in `633ff6c4` / `66225dd2`. On `d9cf55c4`, `Repository regression` run `34675335070` was SUCCESS and all 12 retained historical focused workflows were SUCCESS. Coverage moved; it was not deleted. |
| HYG-002 | P0 | FIX | Reusable test builders were exposed through `conftest.py` and sibling `test_*.py` modules, making collection depend on incidental test-module layout. | Move reusable helpers into explicit `_support.py` modules; leave `conftest.py` for pytest fixture wiring only; production code unchanged. | Affected domains pass in importlib and normal modes; root repository modes remain green. | **RESOLVED.** Shared test support was extracted beginning with `8d29f5d5018b14a815d4fd7b6f35f1d4172e81fc` and `e78c3a38b4c679be7968b5967dd4677df5ecce9e`, then completed across readiness/reconciliation/materialized coordination support (`53f3f923`, `55aa3acd`, `f201009e`, `10825f07`, `43e6a96d`) and normal-mode package/import stabilization (`7886dc55`, `79f758ba`, `83d79717`). Final repository verification on `d9cf55c4` passed both `python -m pytest --import-mode=importlib -q` and `python -m pytest -q`; no production source was edited. |
| HYG-003 | P0 | FIX | `test_phase_i_environment_discovery_script.py` required the obsolete `Get-FileHash` source text while the current discovery contract uses shared-read SHA-256. | Update the stale source-text test only. Do not change `discover_phase_i_live_environment.ps1`. | Targeted contract and repository suites green. | **RESOLVED.** `e30aee2d4a11702cb7ab82a0a0e30c3af92b84a0` updated only the stale test contract to the shared-read SHA-256 path. Subsequent Phase I offline runs and both root repository pytest modes were SUCCESS; discovery production script behavior was unchanged. |
| HYG-004 | P1 | DOCUMENT | Root README described the earlier AutoCAD/M1/v0.5 state rather than the completed Phase I multi-Host baseline. | Refresh current-state entrypoint text and links only. | README/lifecycle checks and repository regression green. | **RESOLVED.** `d9cf55c404414dfb532c9abfaef30280812f13be` refreshed README to state Phase I completed, Engineering Hygiene / Stabilization current, next capability phase `NOT YET DEFINED`, AutoCAD + Revit current Host scope, and v0.6 as current authority. The same head passed `Repository regression` run `34675335070`. |
| HYG-005 | P1 | DOCUMENT | `docs/superpowers/specs/` and `docs/superpowers/plans/` had no complete lifecycle/navigation index. | Add `docs/superpowers/README.md`; index all design/plan records externally without editing historical technical bodies. | Structural lifecycle-index test covers every current design/plan filename. | **RESOLVED.** RED contract `41d82581011814a00cdf2033a311b4032e7d830c` required complete coverage; `d9cf55c404414dfb532c9abfaef30280812f13be` added the lifecycle index covering all 28 Design Specs + 29 Implementation Plans, with v0.6 `CURRENT`, v0.5 `SUPERSEDED`, Phase I latest completed, hygiene current, and next phase undefined. Importlib and normal root suites both passed. Historical Design/Plan bodies were not modified. |
| HYG-006 | P1 | DOCUMENT | `pyproject.toml` pytest comments/marker wording and `tests/__init__.py` rationale were Phase-I/Host-specific although their behavior is repository-wide. | Generalize comments/marker description only; keep `pythonpath` values and package behavior unchanged. | Collection count/parity checks; root pytest modes green. | **RESOLVED.** `592903aa57edb204ee9e07b865de042a69faa6f5` generalized pytest metadata wording and `3aeac5050d88bbf753cb4653f412c74d142ccd3e` generalized the tests-package rationale. Diff review proved the 22 `pythonpath` values unchanged. Fresh canonical run `34674953095` passed both modes with `1453 passed / 17 skipped` (1470 collected), Ruff delta `0`, and Revit Core green. |
| HYG-007 | P1 | FIX | `test_move_idempotency.py` and `test_revision_conflict.py` constructed `HostAdapter()` directly while other basic live AutoCAD tests used the repository discovery/override helper. | Normalize those two tests to `live_autocad_host_adapter()` only; do not change production `HostAdapter` defaults. | Characterization RED then Step34 live-harness and repository regression GREEN; offline skip unchanged. | **RESOLVED.** RED characterization `3242e40817598bd97ae27735eb5e2e5eaa546b57` produced exactly `2 failed / 7 passed` in Step34 live-harness proof. `6e524b944ad1ec0ea2e5e20240a4523b1a3bd9b3` and `87025e8537c63375fb54c30f424fb51e1ea32ae1` switched only the two tests to `live_autocad_host_adapter()`. Step34 then passed all gates, and canonical root suites were `1453 passed / 17 skipped` in both modes. Production `HostAdapter` defaults were untouched. |
| HYG-008 | P1 | DEFER | `*_v2` bridge/compatibility modules are referenced by current public/execution paths; static appearance is not evidence of dead code. | No deletion/refactor in this stage. | Diff proves no V2 production bridge removal. | **DEFERRED.** Current bridge paths are retained. Baseline-to-`d9cf55c4` source-tree diff contains no `platform/**/src/**` production edit, so no V2 runtime bridge was removed or rewritten. |
| HYG-009 | P1 | DOCUMENT | Historical temporary spec-transfer/refinement artifacts were already removed in prior work. No current source-tree removal is required. | Record verified-clean state only. | Current tree contains no reintroduced temporary transfer artifacts. | **VERIFIED CLEAN.** No source edit was required. Final current-tree audit found no reintroduced temporary transfer/refinement artifacts; only the new hygiene Design/Plan and lifecycle/navigation documents were added. |
| HYG-010 | P1 | DEFER | `jsonschema.RefResolver` warning exists, but contract-equivalent migration has not been proven in the frozen hygiene scope. | No runtime validator migration here. | Diff proves validation production path unchanged. | **DEFERRED.** RefResolver migration was not proven contract-equivalent. Baseline-to-`d9cf55c4` diff contains no production validator or contracts/schema edit. |
| HYG-011 | P1 | DEFER | GitHub-hosted jobs report Action/Node runtime maintenance warnings. Upgrading actions is separable infrastructure maintenance and not required for the P0 correctness fixes. | Do not mix action-version upgrades into this cleanup. | Workflow diff shows no unrelated action-version churn. | **DEFERRED.** Action/Node runtime upgrades remain separate maintenance. Workflow edits in this stage were limited to the canonical repository owner, removal of duplicated broad tails, and narrowly scoped historical branch/diff guards; action versions were not churned. |
| HYG-012 | P1 | DOCUMENT | Phase H workflow is focused-only and therefore not evidence for the historical broad-tail consolidation problem. | Retain Phase H workflow structure; document separate focused ownership. | Structural workflow test verifies Phase H focused steps remain; Phase H CI green. | **DOCUMENTED / VERIFIED.** Phase H was explicitly excluded from the 12-file consolidation set and its workflow YAML was retained as focused-only. On `d9cf55c4`, Phase H run `34675335020` completed SUCCESS; the only Phase H code change in this stage was the stale Python source-text assertion repair recorded by HYG-014. |
| HYG-013 | P1 | DOCUMENT | gRPC generator/transport tooling remains referenced by transport conformance/dev workflows; it is not proven dead. | Retain tooling and document KEEP rationale; no removal. | Current workflow/tool references remain present; source-tree diff shows no tooling removal. | **DOCUMENTED / RETAINED.** gRPC generator/transport tooling was not removed or rewritten because current conformance/dev references still require it. Baseline-to-`d9cf55c4` diff contains no removal of the transport generator/tooling surfaces. |
| HYG-014 | P0 | FIX | Phase H on the baseline failed one Revit architecture source-contract assertion: the test expected `revisions.Get(document)` while the handler now reads `revisions.Get(uiDocument.Document)` after the executor boundary moved to `UIDocument`; Revit Core remained green. | Update only the stale Python architecture textual assertion. Do not edit `RevitExternalEventHandler.cs`, `DocumentRevisionTracker.cs`, or Host behavior. | `tests/revit/test_revit_architecture.py` green; Revit Core green; Phase H workflow green. | **RESOLVED.** `bb7f523ff0fe03a065d496d4f017e6c9ebff8724` updated only the stale Python architecture assertion. Revit production files were untouched. On final technical head `d9cf55c4`, Phase H run `34675335020` was SUCCESS and canonical Revit Core job was SUCCESS. |

## Final verification evidence

- Canonical repository owner: `Repository regression` run `34675335070` on `d9cf55c404414dfb532c9abfaef30280812f13be` — SUCCESS for importlib root pytest, normal-mode root pytest, Ruff E/F/I baseline-delta, and Revit Core.
- Phase H: run `34675335020` on the same head — SUCCESS.
- Phase I: run `34675335023` on the same head — SUCCESS for the offline job; the real dual-Host job remains a separate manual/self-hosted gate and is not substituted by offline CI.
- Modified historical focused workflows Step25–34/36/37 on the same head — all SUCCESS.
- Source-tree boundary: `main@d2d1621b30f87506c62adb2d12f73d387821ef78...d9cf55c4` contains no product/runtime changes under `platform/**/src/**`, Host/plugin production runtime, provider runtime, or contracts/schema.
- Historical-record boundary: no pre-existing `docs/superpowers/specs/*.md` or `docs/superpowers/plans/*.md` body was modified; only the 2026-09-12 hygiene Design/Plan were added.
- Scope-external legacy workflows (`Operation resolver`, `Semantic MCP`, `Semantic service`, `IFC4.3 semantic provider`) may still report their own historical broad-tail environment failures; they are outside the frozen 12-workflow consolidation set and were not widened into this hygiene stage.

## Edit-boundary check

Production paths such as `platform/**/src/**`, Host/plugin runtime, provider runtime, and contracts/schema may appear in this ledger only as evidence/context. They were not modified by this hygiene implementation. Any newly discovered fix that requires those surfaces remains `DEFER` unless the scope is explicitly redesigned and re-approved.
