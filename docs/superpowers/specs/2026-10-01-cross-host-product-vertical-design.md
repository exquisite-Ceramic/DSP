# Cross-Host Product Vertical — Design Review Draft

Status: DESIGN-REVIEW — not approved for implementation
Date: 2026-10-01
Baseline: `main@1dd35413d4cadb3b3e7f3ba023919c760f5ab42f`
Predecessor: MCP / Agent Front Door, implementation PR #83 and lifecycle closeout PR #84

## 1. Outcome and agreed scope

Prove one user-facing ProductTask can carry one wall-thickness intent through real model interpretation, real MCP, explicit human decision, configured policy, Gateway, two required Host materializations, independent verification and final exact-task query.

The user explicitly selected **Revit selection as the entry point, with both Revit and AutoCAD modified through a pre-reviewed binding**. This draft proposes the detailed contracts and acceptance gates; that scope decision is not approval of those details.

The reference user requests that the selected Revit wall and its explicitly bound AutoCAD representation both become 300 mm. One semantic target and one canonical `set_wall_thickness.v1` operation produce two REQUIRED materializations. Both reviewed fixtures start at 200 mm. Runtime arguments come from the frozen request, never from hard-coded fixture constants.

Success means both Hosts have committed the authorized effect, each independent post-commit READ verifies its own exact committed revision, reconciliation succeeds, cross-Host convergence is CONVERGED, and the original ProductTask queried through MCP returns SUCCEEDED / COMPLETED.

Non-goals: either-Host initiation, automatic identity matching/onboarding, a third Host, multiple targets, parallel commits, transport unification, XA/2PC, automatic compensation or native UNDO, a generic Agent platform, a general approval inbox, and a full desktop management UI. This is still the controlled same-workstation trust boundary, not multi-user remote authorization.

## 2. Audit of the baseline

Paths below are relative to the repository root. Findings were checked against the baseline tree; the prior implementation HEAD `c67c7d7...` has identical production code to this baseline. No new Host run was performed for this design audit.

| Area | Observed baseline | Consequence for this phase |
| --- | --- | --- |
| Product request | `platform/product_runtime/src/design_product_runtime/contracts.py` fixes host kind to REVIT and action to SET_SELECTED_WALL_THICKNESS; six fields determine the request hash | Do not silently turn an old single-Host request into a dual-Host request |
| Client and session | `platform/product_front_door/src/design_product_front_door/contracts.py`, `submission_controller.py`, `sqlite_state.py` freeze one Revit candidate/runtime/document | Add an explicit versioned dual-Host binding while preserving old hashes and replay |
| MCP | `mcp_wire.py`, `mcp_server.py` expose submit/get/operation-proposal resume through strict DTOs | Evolve decoding/version discrimination; do not add a generic native-command tool |
| Service and composition | `service.py` validates one Revit context; `revit_reference_composition.py` has a single-port registry and one-slot topology | Add exact dual-Host composition and identity validation; reuse the runtime and owners |
| Planning freshness | `canonical_owner_ports.py::ensure_operation_freshness` creates a one-member SnapshotSet | Supply both planning snapshots before freezing downstream ChangeSet lineage |
| Existing multi-document primitives | `semantic_runtime/freshness.py::SnapshotSet` supports one planning snapshot per document and one pinned semantic environment; `revision_barrier.py` checks every member | Reuse these primitives; do not invent a second revision ledger |
| Provider revision | `product_runtime/revit_execution.py` requires the anchor planning document to match the Revit slice and binds its revision into provider evidence | Resolve the corresponding planning member for each slice; never copy one Host revision into the other |
| Phase I live harness | `tests/integration/phase_i_live_host.py` imports test builders, directly creates Admission, and uses in-memory Saga/dispatch stores; execution helpers contain fixture constants and test assertions | Historical domain/Host proof is useful, but the harness is not a production product composition |
| AutoCAD | Production dispatcher, design-fact adapter and readiness port exist under `hosts/autocad/sidecar`; the materialized execution/evidence wiring inspected is in the Phase I test helper | Qualify and implement the missing product adapter using public production contracts; do not import the helper |
| Authorization | `approval_policy.py` authorizes project and canonical operations; Admission is stored separately and consumed by Gateway | An old single-Host policy must not implicitly authorize the new dual-Host capability |
| Product outcome | `wall_thickness_flow.py` already projects PARTIALLY_COMMITTED, DIVERGED and RECOVERY_REQUIRED; current query view mainly exposes checkpoint and aggregate state | Preserve those states and add owner-derived per-materialization results |
| Start concurrency | `PostgresProductTaskStartGate` creates an independent connection/transaction for each critical section | Reuse it and retain shared-composition concurrency regression coverage |

Source references: the existing [Front Door design](2026-09-28-mcp-agent-front-door-design.md), [Phase I design](2026-09-06-phase-i-real-cross-host-materialization-saga-design.md), [handoff](2026-09-19-capability-phase-handoff.md), and [Phase I runbook](../../runbooks/phase-i-real-cross-host-wall-thickness.md). Existing lifecycle completion does not establish this new end-to-end product acceptance.

## 3. Approaches considered

1. **Recommended: explicit, versioned cross-Host product composition.** Keep the current Revit entry semantics, add a distinct cross-Host request/binding mode, and compose the existing two-materialization pipeline. It adds bounded product contracts while reusing domain owners.
2. **Rejected: run two existing product tasks from the client.** This creates separate task/approval/Saga lineages and cannot establish one governed cross-Host result. A UI that aggregates their statuses would not satisfy the requirement.
3. **Deferred: general multi-Host product/session platform.** Either-Host initiation, arbitrary topology and automatic discovery broaden identity, authorization and recovery design before the first narrow product path is proven.

No new framework or low-level protocol is proposed. Use the existing MCP SDK and Pydantic boundary models, PostgreSQL/psycopg durable stores and row locking, LangGraph workflow/checkpointer, and existing native sidecar transports. New application contracts/adapters are justified by repository-specific identity and authority composition; generic orchestration frameworks cannot supply that domain truth. Do not introduce another scheduler, transport protocol, hashing algorithm or persistence engine.

## 4. Product request and immutable binding

Introduce an explicitly discriminated cross-Host request version in the existing ProductTask owner, not a second task database. Proposed public names are `ProductTaskRequestV2` and `SessionBindingV2`.

The V2 request freezes: version, task_id, project_id, initiating host_kind=REVIT, session_ref, session_binding_hash, requested_action=SET_BOUND_WALL_THICKNESS, and the normalized thickness intent. The canonical operation remains `set_wall_thickness.v1`; the product action name distinguishes the requested execution scope. Hash the entire versioned body using the existing canonical hashing convention. The model may supply the permitted intent; the trusted controller selects the configured capability and freezes identity before first network send.

The V2 binding freezes exactly two entries, one Revit and one AutoCAD, with role, candidate key/hash, transport locator, runtime identity, document identity, native target identity and the existing HostBinding fingerprint. It also pins project, one semantic target, one semantic environment and the exact topology snapshot identity/revision/hash. Revit is the initiating entry. Both topology slots are REQUIRED. Hash the complete canonical binding body with deterministic entry ordering; reject duplicate, missing or extra Hosts.

Use reviewed configuration as the input to existing IdentityRegistry / MaterializationTopologyRegistry contracts. This manifest does not become another semantic identity owner. Model output, display titles, geometry, native list order and pipe-name similarity cannot establish correspondence. Native document refs must be unambiguous within the binding and SnapshotSet; collisions fail closed rather than gaining synthetic aliases at execution time.

Client SQLite continues to own submission delivery/correlation and immutable local binding, not execution truth. V2 request/binding bodies must survive client restart. The server validates the binding against reviewed configuration, then atomically persists the immutable binding body and V2 request under the existing ProductTask request owner before workflow start. The request's session_binding_hash addresses that exact body; replay compares both, and cannot replace either. This is accepted task input, not another semantic binding registry or execution owner. Checkpoints retain stable refs only. Later config drift must be detectable, never resolved via a latest lookup.

Compatibility rules:

- V1 requests, hashes, persisted rows, MCP inputs and single-Revit behavior remain unchanged.
- V2 uses explicit version decoding. Missing version remains the existing V1 shape; unknown versions fail closed.
- Same task_id with any different version/body/binding is a conflict. Reusing a client submission cannot produce another task or silently convert V1 to V2.
- Changing the required Host set, runtime, document, target or topology requires a fresh binding and new submission; existing lineage is immutable.
- Exact GET dispatches from the durable request version. It never needs the current candidate config, live model or live Host.

## 5. Human decision and execution authorization

The operation proposal must visibly state both target documents/Hosts, the configured semantic correspondence, independently observed current widths and the requested width. Observation revisions/timestamps are shown as observations, not a guarantee that both documents remain unchanged.

The server-owned pending proposal must bind the cross-Host scope. Its stable subject content includes or references the accepted request hash, binding hash, required-set/topology hash and canonical proposal. Extend the existing operation-proposal artifact contract explicitly; do not merely attach UI text to an unchanged single-Host subject. Resume still validates the exact task, current pause, subject and allowed decision. The model cannot accept the proposal or select authority credentials.

Human ACCEPT permits the existing workflow to continue. It is not Gateway authorization. Any change in the frozen target set or proposal invalidates the decision; do not transfer an old ACCEPT to a new lineage.

Add an explicit cross-Host configured-policy version/profile. It authorizes the actual final ChangeSet and ApprovalScope, including the exact allowed topology/binding configuration and required Host set, in addition to project and canonical operation. Old policy V1 cannot issue a new cross-Host admission by default. Policy configuration uses existing strict Pydantic/contract validation and canonical hashing. Existing Admission issuance, create-once persistence and Gateway consumption remain authoritative; do not introduce a second approval status store. An already issued exact admission follows existing replay/expiry semantics rather than being silently reissued under a changed policy.

The same ChangeSet/ApprovalScope stores must be supplied to workflow and policy composition. Assert that the final scope covers both materializations before admission. Policy deny produces zero admission issuance and zero mutation dispatches for that task.

## 6. Semantic planning and execution composition

The semantic operation is still anchored to the selected Revit wall. Independently read and normalize both native representations using the existing Host fact adapters and pinned semantic providers. Both must resolve to the configured semantic target. A binding mismatch or unsupported native form fails before dispatch. Both representations must satisfy the existing direct-wall effect constraints; the AutoCAD member is not only an identity ping. Unsupported extra effects or a target outside the reviewed direct-wall scope block execution rather than being inferred safe from the Revit impact analysis.

For operation freshness, construct one valid PlanningSnapshot per required document, under the same pinned SemanticEnvironment, and form one existing SnapshotSet containing both. The Revit member remains the anchor `planning_snapshot_ref`; the full SnapshotSet is the ChangeSet's freshness boundary. Extend the existing owner seam that currently creates a singleton set; do not mutate SnapshotSet membership after ChangeSet hashing. Single-Host callers retain singleton behavior.

Required membership must equal the two-document topology. Missing or extra members, ambiguous document identity, mismatched semantic environment, and per-Host revision mismatch fail closed. Each provider-binding boundary resolves its own document's member and binds that member's expected revision into its own evidence. `RevisionBarrier` checks the complete set. Readiness validates each exact runtime/document/native target and the binding's expected revision; a later readiness revision must not silently replace the planned revision.

Use one CanonicalChangeSet, one ApprovalScopeBoundaryV2, one MaterializationPlan, one execution plan and one durable Saga. Reuse existing materialization-aware grants and all-required readiness. The existing deterministic execution ordering must result in AutoCAD then Revit for this controlled pair; assert this from the plan rather than add an alternate UI ordering authority. A Host being offline never downgrades REQUIRED to OPTIONAL.

Production composition dispatches through an exact `(host_type, host_instance_id, document_ref)` registry. Each registered port validates its own native target binding. Reuse the existing Revit execution/evidence adapters where their contracts apply. Provide AutoCAD product execution/evidence adapters around its real dispatcher, fact extraction and reconciliation APIs. They accept requested arguments and exact authority; they must not copy Phase I's hard-coded 200/300 constants or test-only `AssertionError` outcomes.

AutoCAD adapter qualification must cover actual changed-target/effect evidence, exact revision acknowledgement, known BEFORE_COMMIT failure and lost/ambiguous response classification. A successful command receipt alone cannot manufacture a verified ActualDelta or full scope compliance. If the current native response cannot support required effect or commit truth, the plan must include the bounded native/adapter change before calling the product path ready. Protocol replacement is not implied.

## 7. Independent verification and outcome ownership

Each committed materialization performs a separate READ against its own target and exact committed revision. Normalize and project that evidence through the existing semantic pipeline, then use Step33 V2 scope/semantic verification and the existing convergence verifier. EXECUTE response values are not an independent READ. Reads that fail, return another identity, or observe a later external edit must not be reported as success at the original committed revision.

Expose per-materialization query results from existing durable Saga/reconciliation evidence: Host/document/target identity, materialization and slice refs, status, expected/committed/observed revisions where available, measured thickness where verified, verification/convergence refs and hashes, and recovery disposition. Missing evidence stays absent with its reason. Do not synthesize 300 mm from intent, or add mutable product-result truth beside the Saga owner.

Aggregate outcomes retain existing ProductFlowStatus semantics:

| Owner evidence | Product result |
| --- | --- |
| Both required materializations verified, convergence CONVERGED, Saga SUCCEEDED | SUCCEEDED |
| Human proposal rejected | CANCELLED under existing workflow rules; no task mutation |
| Policy denies | Existing policy-wait/denial result; no fabricated Saga success or forced new FAILED semantics |
| Required Host unavailable before execution | Fail-closed not-ready/error projection; zero task mutation; never success |
| AutoCAD committed, Revit known to fail BEFORE_COMMIT | PARTIALLY_COMMITTED |
| Dispatch/commit result unresolved | RECOVERY_REQUIRED; retain unknown-outcome evidence |
| Both local materializations verified but cross-Host comparison fails | DIVERGED |

Keep the existing distinction between no persisted task, ACCEPTED_PRE_WORKFLOW and WORKFLOW. A transport error after submission is not evidence that no task exists. GET must remain available with both Hosts offline. Readiness/policy failures may be surfaced through existing stable error/state semantics; the implementation plan must test those exact semantics rather than remap every rejection to FAILED.

## 8. Persistence, concurrency and recovery

Reuse PostgreSQL request/start gate, LangGraph checkpoint and workflow artifact stores, Saga V2, dispatch intents, and admission persistence. Reuse the existing client SQLite delivery role. No in-memory Saga/dispatch owner is permitted in the mandatory product path.

One composition may be shared across MCP workers. Retain independent transaction ownership for start serialization and composition single-flight. Shared registries must not route by whichever Host is active. Replay tests must prove that two same-task submissions cannot start two workflows and cannot dispatch a second copy of a committed slice.

Composition rebuild may use only existing owner contracts and exact pinned configuration. Current transient semantic/domain stores are not assumed durable merely because the request and checkpoint are durable. If the existing reconstruction path cannot reproduce the exact referenced artifacts safely, expose the existing recovery-required/fail-closed outcome; do not reread changed models to fabricate old approved artifacts. This phase does not promise automatic recovery from every crash window or a universal persistence migration.

Unknown Host outcome never means safe-to-retry. Subsequent GET, client reconnection or resume cannot replay a mutation just to obtain cleaner evidence. Automatic compensation remains excluded. Partial commit and divergence remain visible for governed follow-up.

## 9. Acceptance gates

Offline and real-owner gates:

- V1 byte/hash/replay compatibility; strict V2 decoding; immutable binding/topology and same-task conflicts.
- Shared-composition PostgreSQL start serialization, concurrent submission, response loss and duplicate human decision.
- Two-member SnapshotSet freshness: intentionally different Host revision values, missing/wrong member, document collision, planning/readiness drift and exact per-slice revision binding.
- Policy denies cross-Host by default under V1; explicit V2 allow/deny; final scope/topology mismatch; no model-owned acceptance or admission.
- Production AutoCAD/Revit ports, same-task durable query and per-materialization evidence; no product imports from tests.
- Rebuild/reconnect, offline GET, partial commit, DIVERGED, read unavailable and commit outcome unknown. Assert no blind redispatch.
- Existing single-Revit product, Front Door, Phase I, owner/persistence, architecture, Ruff and native core regressions relevant to changed code.

Mandatory controlled live cases, each with fresh lineage and clean reviewed DWG/RVT copies:

| Case | Required proof |
| --- | --- |
| Configured policy deny after a real model invocation, MCP and explicit human ACCEPT | Zero Admission and zero task mutation on both Hosts; independent READ confirms both baselines/revisions unchanged |
| Required Host unavailable after proposal preparation but before execution | Real product attempt fails closed, zero mutation on the other Host; after restoring connectivity, read and lineage evidence confirm no task change |
| Positive after real model invocation, MCP and explicit human ACCEPT | One task and Saga; one authorized mutation per Host; each revision advances once from its own baseline; independent READ gives 300 mm at its own committed revision; CONVERGED; same-task GET succeeds |
| Controlled partial commit | AutoCAD commits 300 mm; a separately recorded legal Revit edit after readiness changes 200 to 201 mm; task's stale Revit command fails REVISION_CONFLICT / BEFORE_COMMIT; PARTIALLY_COMMITTED, no fabricated Revit task ActualDelta, no convergence success, no compensation |

The partial-commit race must use test-only orchestration around production ports, following the Phase I deterministic pattern; no production debug switch and no replacement of real model, human decision, policy or Host. The external 201 mm edit is identified separately from the ProductTask effect. Disconnecting a Host must not leave uncertainty about whether this task already dispatched.

All four live cases are mandatory for this capability's closure. An environment limitation may be recorded truthfully as NOT_RUN_ENVIRONMENT_LIMITATION, but leaves that gate pending. Unknown-response and divergence injections are additionally mandatory offline/real-owner tests; this draft does not require destructive real-machine network fault experiments to reproduce every recovery window.

Evidence pins exact implementation HEAD, both plugin builds/loaded DLL identities, fixture hashes, model invocation, client submission, request/binding/topology hashes, task/pause/subject and actual human decision, final ChangeSet/scope, policy/admission/Gateway, materialization/slice/Saga, per-Host revision/effect/READ, verification/convergence and final MCP GET. Include secret-free archive integrity manifest and tool logs. Independent measurement must not be inferred from command output or UI alone. Never save mutated acceptance copies over canonical fixtures.

## 10. Delivery and review boundary

Implementation order proposed for the later plan: versioned request/binding and compatibility; dual-Host semantic/freshness composition; AutoCAD production execution/evidence qualification; configured policy and human scope binding; durable query/recovery projection; real MCP reference client and acceptance; exact-head CI/live review; PR merge and merged-main observation; lifecycle closeout.

The plan must enumerate migrations and owner seams explicitly, with red-to-green tests for changed behavior. It must not treat an AutoCAD adapter qualification failure or a missing public reconstruction contract as a testing exception. A production contract change needs its focused tests and corresponding native/owner implementation.

This draft adds no production code, changes no lifecycle status and makes no new live-success claim. Written-spec approval is required before writing the implementation plan; written-plan review and execution choice follow before implementation. Keep historical predecessor specs and their acceptance evidence unchanged.
