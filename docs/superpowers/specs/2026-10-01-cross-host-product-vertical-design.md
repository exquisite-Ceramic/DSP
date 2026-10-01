# Cross-Host Product Vertical — Design Specification

Status: **FINAL CONSISTENCY REVIEW — not yet approved for implementation**

Date: 2026-10-01

Baseline: `main@1dd35413d4cadb3b3e7f3ba023919c760f5ab42f`

Predecessor: MCP / Agent Front Door, implementation PR #83 and lifecycle closeout PR #84

## 1. Outcome and agreed scope

Prove one user-facing ProductTask can carry one wall-thickness intent through real model interpretation, real MCP, explicit human decision, configured policy, Gateway authorization, two REQUIRED Host materializations, independent verification, durable recovery, and final exact-task query.

The selected product entry point is Revit. The selected Revit wall and one explicitly pre-reviewed AutoCAD representation form the exact two-Host execution topology for this vertical.

One semantic target and one canonical `set_wall_thickness.v1` operation produce exactly two REQUIRED materializations:

- Revit materialization;
- AutoCAD materialization.

The reference request changes both reviewed representations from 200 mm to 300 mm.

Runtime arguments originate from the frozen ProductTask request and authoritative planning lineage. They are never taken from hard-coded fixture values.

Success means:

```text
both REQUIRED Host materializations commit the authorized effect
→ each Host independently READs its exact committed result
→ scope verification succeeds
→ semantic verification succeeds
→ cross-Host convergence = CONVERGED
→ the single durable Saga = SUCCEEDED
→ exact-task MCP GET projects durable per-materialization evidence
```

Non-goals include:

- AutoCAD initiation;
- arbitrary Host count;
- dynamic topology discovery;
- automatic semantic-target matching;
- a third Host;
- multiple semantic targets in one ProductTask;
- parallel Host commits;
- XA/2PC;
- automatic compensation;
- native UNDO orchestration;
- generic Agent-platform redesign;
- general approval inbox;
- full desktop administration UI.

This remains a controlled same-workstation trust boundary. It does not introduce multi-user remote authorization.

## 2. Audit of the baseline

The relevant baseline establishes the following constraints.

| Area | Baseline | Consequence |
| --- | --- | --- |
| Product request | Existing V1 ProductTask is Revit/single-wall specific | Cross-Host behavior requires explicit V2 |
| Client/session binding | Existing binding freezes one Revit candidate/runtime/document | V2 must freeze exact Revit + AutoCAD membership |
| MCP | Strict submit/get/resume DTOs already exist | Extend through explicit versioning, not native command escape hatches |
| Front Door | Resolves one session binding and one selected Revit Wall | V2 needs exact two-Host accepted binding |
| Product request persistence | PostgreSQL request owner is create-once by task identity | Extend immutable payload semantics without rewriting V1 |
| Planning freshness | Current canonical path creates one PlanningSnapshot member | Cross-Host requires two independently authoritative members |
| SnapshotSet | Already supports multiple PlanningSnapshots | Reuse; do not invent another revision ledger |
| RevisionBarrier | Protects PlanningSnapshot revision → execution | Does not protect human observation → planning |
| Provider binding | Canonical adapter currently assumes exactly one ExecutionSlice | Multi-slice orchestration manifest required |
| Execution entry | Existing canonical path supplies one binding/grant | Must resolve complete two-Slice concrete collections before first execution |
| Execution owner view | Current adapter assumes one Saga Slice / one active recovery | Must become multi-slice recovery aware |
| Saga V2 | Already models multiple slice lifecycle and partial commit | Preserve one ProductTask → one Saga |
| AutoCAD | Production dispatcher/fact/readiness infrastructure exists | Product path must use production contracts, not Phase I test helpers |
| Gateway V2 | Final Grant sees execution plan/materialization/topology/binding | Final required-set authority remains at Grant time |
| Policy | Existing product policy primarily covers project/operation | V2 needs stable cross-Host capability policy |
| Candidate hash | V1 candidate hash includes transport locator | Do not treat it as inherently stable policy identity |
| Reconciliation | Saga records hashes but not every queryable evidence body | V2 must durably retain required evidence bodies |
| Workflow artifact store | Durable orchestrator artifact store + StableRef already exist | Reuse for multi-slice reference manifests |
| Concurrency | Existing start gate and checkpoint semantics protect task start/resume | Extend with atomic ACCEPT-vs-stale transition semantics |

The predecessor capability remains complete and unchanged.

This Design does not alter predecessor lifecycle state.

## 3. Approaches considered

### 3.1 Selected: explicit versioned cross-Host ProductTask

Introduce a distinct V2 request/session binding while reusing existing canonical, materialization, authorization, Saga, reconciliation and workflow owners.

The end-to-end identity is:

```text
one ProductTask
→ one semantic intent
→ one canonical operation
→ one ChangeSet
→ one ApprovalScope
→ one MaterializationPlan
→ one ExecutionPlan
→ two REQUIRED ExecutionSlices
→ one Saga
```

### 3.2 Rejected: two independent ProductTasks

One Revit task plus one AutoCAD task would create:

```text
two requests
two approval lineages
two Saga lineages
two recovery authorities
```

A UI aggregation over those two tasks would not establish one governed cross-Host operation.

### 3.3 Deferred: arbitrary N-Host product framework

Dynamic Host discovery, arbitrary N-Host topology and either-Host initiation are deferred.

The present topology is exactly:

```text
Revit entry
→ one semantic target
→ REQUIRED AutoCAD
→ REQUIRED Revit
```

## 4. Product request and immutable binding

### 4.1 ProductTaskRequestV2

Introduce an explicitly discriminated V2 request.

Conceptually:

```text
ProductTaskRequestV2
```

It freezes at minimum:

```text
version
task_id
project_id
initiating_host_kind = REVIT
session_ref
session_binding_hash
requested_action = SET_BOUND_WALL_THICKNESS
normalized thickness intent
request_hash
```

The underlying canonical operation remains `set_wall_thickness.v1`.

The product request does not choose runtime authority, provider identity, execution grant, materialization ordering, or policy credentials.

### 4.2 SessionBindingV2

`SessionBindingV2` contains exactly two REQUIRED entries:

```text
Revit
AutoCAD
```

Each entry freezes the applicable:

```text
role
configured candidate/reference identity
existing candidate hash where applicable
transport locator
host_instance_id
document identity
native target identity
HostBinding fingerprint
```

The common binding freezes:

```text
project_id
semantic_target_id
semantic_environment identity
topology snapshot identity
topology revision
topology snapshot hash
initiating Host = Revit
```

Missing, duplicate or extra members fail closed.

Members are canonically ordered before hashing.

### 4.3 Cross-Host identity authority

The reviewed configuration supplies inputs to existing semantic/topology owners.

The following are insufficient to establish identity:

```text
model output
display title
geometric similarity
enumeration order
similar endpoint names
```

The Revit and AutoCAD representations must independently resolve to the same reviewed semantic target.

Ambiguous document/target identity fails closed.

### 4.4 Client-to-server binding handoff

The selected same-workstation flow is:

```text
client freezes V2 request + SessionBindingV2 in SQLite
        ↓
MCP submit carries ProductTaskRequestV2
        ↓
server resolves exact session_ref through local durable binding reader
        ↓
server validates session_binding_hash
        ↓
server validates reviewed configuration
        ↓
server atomically accepts immutable request + immutable binding body
        ↓
workflow becomes start-eligible
```

`session_binding_hash` is an integrity join. It is not a replacement for the binding body.

After server acceptance, recovery reads the server-owned immutable accepted input and does not depend on client SQLite continuing to exist.

No latest-session or reverse lookup may replace the accepted binding.

### 4.5 Stable policy identity versus runtime identity

V1 hash semantics remain unchanged.

In particular, the existing V1 candidate hash MUST NOT be modified merely to make it suitable as a stable policy identity.

V2 distinguishes:

```text
Policy configuration
    stable reviewed target/capability/topology fields

SessionBindingV2
    exact runtime/session/document/endpoint

ProviderBinding + Gateway Grant
    exact executable runtime/provider authority
```

A long-lived policy cannot require transient `host_instance_id` or transport endpoint solely because those fields are present in SessionBinding.

### 4.6 Compatibility

Mandatory compatibility rules:

- V1 request shape remains unchanged.
- V1 hashing remains unchanged.
- V1 persisted rows remain valid.
- V1 MCP behavior remains valid.
- Missing request version decodes as existing V1.
- V2 requires explicit discrimination.
- Unknown versions fail closed.
- Same task ID with different version/body/binding conflicts.
- Same accepted V2 submission replays to the same immutable input.
- Changed topology/runtime/document/native target requires a new binding and new ProductTask.
- Exact GET dispatches from durable request version.
- V2 GET does not require current client configuration.

## 5. Human decision and execution authorization

Human decision, policy authorization, planning and final execution authority are distinct stages.

The authoritative order is:

```text
Human Proposal
→ parameter binding / freshness / impact / ChangeSet
→ Policy / Approval
→ MaterializationPlan / ExecutionPlan
→ ProviderBinding
→ Gateway Grant
→ execution
```

### 5.1 Cross-Host proposal subject

The human proposal displays at minimum:

```text
both Host/document identities
configured semantic correspondence
native target identities
independently observed wall thicknesses
requested thickness
Host revisions
observation timestamps
```

The server persists an immutable proposal subject containing or referencing:

```text
request_hash
session_binding_hash
topology_snapshot_hash
semantic target
canonical operation + arguments
Revit proposal observation
AutoCAD proposal observation
proposal subject hash
```

The materialization `required_set_hash` does not yet exist and MUST NOT be included.

Existing binding/topology authority is preferred over inventing another equivalent required-host hash.

### 5.2 Stable observation comparison semantics

The original proposal evidence is immutable and auditable.

Later independent reads are NOT required to reproduce the same whole evidence hash.

Legitimate metadata differences may include:

```text
timestamp
command_id
evidence_id
transport request identity
```

Continuity compares stable state.

For each required Host it must establish at minimum:

```text
same applicable runtime/session identity
same document
same native target
same semantic target
same accepted Host revision
same pinned semantic environment
same normalized relevant wall-thickness value
valid lineage to the accepted proposal
```

An existing content hash may be reused only if it covers the required stable comparison fields rather than volatile acquisition metadata.

### 5.3 Gate A — pre-consumption freshness

Before normal consumption of `OPERATION_PROPOSAL_ACCEPTED`, both REQUIRED Hosts are freshly observed.

If either no longer matches the accepted proposal under the stable comparison rules:

```text
do not normally consume ACCEPT
do not normally call flow.resume()
do not fabricate human REJECT
do not transfer ACCEPT to new observations
```

The workflow owner records the proposal as no longer usable.

ProductTask query only projects that owner state.

### 5.4 Gate B — accepted observation to planning continuity

Gate A does not close the window:

```text
Gate A passes
→ ACCEPT commits
→ external edit
→ PlanningSnapshot reconstruction
```

Therefore every independently reconstructed PlanningSnapshot must establish stable-state continuity with the accepted proposal observation.

The proposal observation does not become the PlanningSnapshot.

The PlanningSnapshot is produced independently by the proper semantic/runtime owner.

If continuity fails:

- historical ACCEPT remains accepted history;
- the old task stops further governed progression;
- workflow owner durably records continuity/staleness failure;
- the newer state cannot inherit authorization from the old human decision.

### 5.5 Stale proposal product path

This phase selects:

```text
new submission
→ new ProductTask
```

rather than same-task re-pause.

For Gate A or Gate B failure:

```text
old task becomes non-continuable
→ old subject/history remains immutable
→ new submission
→ new task_id
→ fresh observations
→ new proposal subject
→ new pause
→ new explicit human decision
```

An old ACCEPT can never authorize a new subject.

A stale condition is not human rejection.

### 5.6 Atomic ACCEPT / stale owner transition

For one exact:

```text
task_id
pause_id
proposal subject identity/hash
```

normal ACCEPT and Gate-A proposal invalidation compete against the same expected authoritative workflow state.

Conceptually:

```text
EXPECTED:
    task T
    pause P
    subject S
    state = awaiting decision

COMMAND A:
    accept S

COMMAND B:
    invalidate S because Gate A detected drift
```

Exactly one compatible owner transition may win.

The losing request MUST re-read authoritative owner state. It MUST NOT overwrite or reinterpret the winning transition.

If stale wins:

```text
S → stale/non-continuable
```

a delayed ACCEPT cannot advance planning or recreate the old wait state.

If ACCEPT wins:

```text
S → accepted historical decision
```

a delayed Gate-A invalidation cannot rewrite history to say that ACCEPT was never consumed.

Later drift is handled by Gate B or later freshness/revision protection.

The Design does not prescribe PostgreSQL locks versus CAS. It freezes the observable transition semantics.

Front Door MUST NOT:

```text
consume ACCEPT outside owner
→ return success
→ asynchronously mark stale
```

Front Door may perform fresh observation and request a legal owner transition, but it does not directly mutate checkpoint state or create a competing stale flag.

Concurrent resume therefore guarantees:

```text
at most one ACCEPT consumption
at most one invalidation
no ACCEPT after committed stale transition
no stale transition erasing committed ACCEPT
no stale transition erasing downstream execution facts
```

### 5.7 Policy / Approval authority

Human ACCEPT only authorizes workflow continuation.

Cross-Host execution requires explicit V2-capable configured policy.

Policy authorizes stable dimensions such as:

```text
project
canonical operation
reviewed target/capability configuration
semantic target
allowed topology
required Host roles/types
```

The Approval stage binds authoritative:

```text
CanonicalChangeSet
ApprovalScopeBoundaryV2
semantic environment
available topology/scope lineage
```

An existing V1 single-Host policy does not implicitly authorize V2.

### 5.8 Planning and Gateway Grant authority

The final materialization required-set only exists after planning.

Authority is therefore layered:

```text
Human
    exact intent + observations

Policy / Approval
    final ChangeSet + ApprovalScope

Planning
    MaterializationPlan
    required_set_hash
    ExecutionPlanV2

Gateway Grant
    final plan
    required_set
    topology
    exact Slice
    ProviderBinding
    approval lineage
    exact runtime
```

Existing Gateway V2 required-set/topology validation remains authoritative.

## 6. Semantic planning and execution composition

### 6.1 Independent semantic reconstruction

The canonical operation remains anchored to the selected Revit wall.

Both Host representations are independently:

```text
READ
→ normalized
→ semantically reconstructed
→ mapped to configured semantic target
```

AutoCAD is not an identity-only ping.

It must independently satisfy the required wall/effect semantics.

### 6.2 Two-member SnapshotSet

Operation freshness creates:

```text
Revit PlanningSnapshot
AutoCAD PlanningSnapshot
```

under one pinned SemanticEnvironment.

They may have different Host revisions.

Revit remains the anchor `planning_snapshot_ref`.

The complete SnapshotSet contains exactly the two required documents.

The AutoCAD member must come from independent AutoCAD reconstruction.

It MUST NOT be created by cloning the Revit snapshot and changing `document_ref`.

### 6.3 Proposal-to-planning continuity

Before either PlanningSnapshot enters the authoritative SnapshotSet:

```text
accepted proposal state
    == stable continuity comparison ==
independent PlanningSnapshot base state
```

A new planning read may have different acquisition metadata.

It may not silently adopt newer model state under the previous human decision.

### 6.4 Planning-to-execution freshness

The total chain is:

```text
proposal observations
→ Gate A
→ ACCEPT
→ Gate B
→ SnapshotSet
→ ChangeSet / planning
→ RevisionBarrier
→ native Host revision guard
→ mutation
```

Each gate protects a distinct time window.

### 6.5 One governed multi-materialization lineage

Exactly:

```text
one ProductTask
one canonical operation
one ChangeSet
one ApprovalScopeBoundaryV2
one MaterializationPlan
one ExecutionPlanV2
two REQUIRED ExecutionSliceV2
one Saga
```

Existing deterministic ordering must yield AutoCAD before Revit for the controlled pair.

### 6.6 ProviderBinding collection manifest

Workflow does not gain fields such as:

```text
autocad_binding_ref
revit_binding_ref
```

Instead it stores one immutable collection reference.

Conceptually:

```text
ProviderBindingCollectionRef
```

The body maps:

```text
ExecutionSlice identity
    → original ProviderBinding owner StableRef
```

It is a reference manifest, not authorization.

### 6.7 Gateway Grant collection manifest

Likewise:

```text
ExecutionGrantCollectionRef
```

maps:

```text
ExecutionSlice identity
    → original Gateway Grant StableRef
```

The collection itself grants nothing.

Before first mutation:

```text
ExecutionPlan REQUIRED Slice set
    ==
Binding manifest Slice set
    ==
Grant manifest Slice set
```

No missing, duplicate or extra member is allowed.

Exact materialization/plan lineage must match.

### 6.8 Collection persistence ownership

The two collection manifests are Workflow Orchestrator artifacts.

They use the existing durable workflow artifact ownership model.

The checkpoint stores only their `StableRef`.

Conceptually:

```text
workflow checkpoint
    |
    | StableRef
    v
orchestrator durable artifact store
    |
    +-- ProviderBinding reference manifest
    +-- ExecutionGrant reference manifest
```

Each manifest is:

```text
immutable
content-addressed
codec-versioned
durably recoverable
```

It contains orchestration identity and original-owner refs, including at minimum:

```text
execution_plan identity/hash
materialization_plan identity/hash where applicable
ordered required Slice identities/hashes

per member:
    execution_slice_id
    execution_slice_hash
    materialization_id
    original owner StableRef
```

It does not copy:

```text
grant lifecycle
admission state
expiry
provider eligibility state
mutable authorization state
```

A persisted manifest proves immutable mapping completeness.

It does not prove that referenced authority is currently valid.

### 6.9 Common collection resolution

The canonical owner adapter owns collection resolution.

All uses begin with:

```text
collection StableRef
→ read exact workflow artifact
→ validate codec/hash/manifest identity
→ validate execution/materialization lineage
→ validate exact required Slice coverage
→ resolve original-owner refs as required for the use case
```

This common resolution step is NOT itself:

```text
execution
authorization
re-admission
readiness
redispatch
recovery mutation
```

### 6.10 Initial or owner-authorized forward execution

Only when authoritative execution state permits a new execution attempt does the adapter continue:

```text
resolve every BindingSet from ProviderBinding owner
→ resolve applicable Grant/admitted authority from Gateway owner
→ validate current execution applicability
→ assemble concrete ordered binding + authority collections
→ call existing materialized execution entry
```

Current all-required readiness belongs to this forward-execution path.

A complete manifest does not authorize execution by itself.

### 6.11 Existing-dispatch recovery

If durable Saga or dispatch facts already exist, recovery begins from those facts:

```text
saga_id
→ durable Saga
+ durable per-Slice dispatch intents
+ recovery facts
→ existing recovery/reconciliation path
```

Collection manifests may be resolved to validate historical lineage.

Recovery MUST NOT merely because the manifest was resolved:

```text
call coordinator.execute()
rerun all-required readiness
re-admit historical grants
create a new dispatch intent
issue replacement Host mutation
```

Historical already-admitted binding/grant lineage is distinct from deciding whether a new execution attempt is currently allowed.

Known commit and unknown-outcome facts take precedence over replay convenience.

### 6.12 Read-only GET and reconstruction

GET/restart reconstruction uses durable owner truth.

Manifest resolution for read-only projection MUST NOT:

```text
require Host readiness
require Hosts online
re-admit grants
create dispatch
invoke mutation execution
```

Read-only reconstruction uses as applicable:

```text
accepted ProductTask input
workflow checkpoint
workflow artifacts
Saga
dispatch/recovery state
durable reconciliation evidence
other immutable referenced owner artifacts
```

Host unavailability therefore cannot by itself prevent querying an already durable task.

### 6.13 Coordinator boundary

The materialized execution coordinator does not own or understand workflow collection manifests.

For forward execution:

```text
canonical adapter
    resolves manifest
    resolves/validates original authority
    assembles concrete collections
        ↓
existing coordinator execution boundary
```

For recovery:

```text
Saga / dispatch / reconciliation owner path
```

For read-only GET:

```text
durable query / evidence path
```

Therefore:

```text
collection resolution ≠ execution
collection resolution ≠ re-admission
collection resolution ≠ recovery dispatch
```

Composition rebuild MUST NOT reset execution authority or erase prior execution facts.

### 6.14 Production Host registry and adapters

Production runtime resolution uses exact:

```text
(host_type, host_instance_id, document_ref)
```

identity.

Revit reuses production execution/evidence adapters where appropriate.

AutoCAD product adapters must wrap public production dispatcher, facts, readiness and reconciliation contracts.

Production code cannot import Phase I test helpers.

AutoCAD qualification must cover:

```text
changed-target/effect evidence
revision acknowledgement
BEFORE_COMMIT failure
lost/ambiguous response
independent post-commit READ
```

## 7. Independent verification and outcome ownership

### 7.1 Independent post-commit READ

Each committed materialization independently reads:

```text
its Host
its document
its native target
its committed revision
```

EXECUTE response content is not the verification READ.

A READ that cannot establish exact committed lineage cannot be reported as verification.

### 7.2 Durable V2 evidence bodies

All V2 evidence bodies required for offline product projection are durably owned by the existing reconciliation/persistence domain.

This is an extension of that owner, not a separate evidence microservice.

Frozen invariant:

```text
construct canonical evidence body
→ validate content hash
→ validate complete lineage
→ durably write body
→ only then publish ref/hash in Saga
```

Same hash/body replay is idempotent.

Different immutable body for the same hash is corruption.

### 7.3 Crash invariant

Preferred ordering:

```text
evidence-body-first
→ Saga-reference-second
```

or equivalent owner-local atomicity.

Allowed crash residue:

```text
durable unreferenced immutable evidence body
```

Forbidden accepted state:

```text
Saga publishes required V2 evidence hash
but corresponding body never became durable
```

### 7.4 Query lineage

V2 query follows explicit owner lineage, e.g.:

```text
Saga slice
→ verification_hash
→ verification result
→ evidence_bundle_hash
→ evidence bundle
→ per-Host READ evidence
→ measured thickness / observed revision
```

The query does not infer 300 mm from requested intent.

Terminal Saga state alone does not manufacture measured evidence.

### 7.5 Historical compatibility

New evidence-body requirements apply to V2 records that promise those bodies.

Historical V1 records do not become corrupt merely because they predate this requirement.

Evidence query failure MUST NOT:

```text
redispatch Host mutation
erase known commit truth
rewrite execution history
```

### 7.6 ProductTaskQueryViewV2

V2 query output is explicitly versioned.

Conceptually:

```text
ProductTaskQueryViewV2
```

It contains aggregate task/workflow state plus per-materialization projection.

Where authoritative evidence exists, a materialization projection may contain:

```text
Host identity
document identity
native/semantic target
materialization ref
execution slice ref
status
expected revision
committed revision
observed revision
verified thickness
ActualDelta refs/hashes
verification refs/hashes
convergence refs/hashes
dispatch/recovery disposition
evidence integrity/unavailable reason
```

Do not add a mutable parallel `ProductTaskResult` truth table.

### 7.7 Aggregate outcomes

| Owner truth | Product projection |
| --- | --- |
| Both REQUIRED materializations verified + convergence `CONVERGED` + Saga `SUCCEEDED` | `SUCCEEDED` |
| Human explicitly rejects | existing `CANCELLED` semantics |
| Proposal stale under Gate A or Gate B | stale/non-continuable; not human rejection |
| Policy deny | no mutation |
| Required Host unavailable before execution | fail closed |
| AutoCAD committed + Revit known BEFORE_COMMIT failure | `PARTIALLY_COMMITTED` |
| Any required dispatch outcome unresolved | `RECOVERY_REQUIRED` / recover-or-wait |
| Local effects verify but convergence fails | `DIVERGED` |

Retain:

```text
task absent
ACCEPTED_PRE_WORKFLOW
WORKFLOW
```

as distinct states.

## 8. Persistence, concurrency and recovery

### 8.1 Existing durable owners

Reuse:

```text
ProductTask PostgreSQL request/start gate
LangGraph checkpoint storage
Workflow artifact store
Approval / Admission persistence
MaterializationPlan / ExecutionPlan stores
Gateway persistence
Saga V2
Host dispatch intent store
reconciliation evidence persistence
client SQLite before server acceptance
```

The task input, human decision and invalidation state, workflow manifests, Saga, dispatch truth, and V2 query-required evidence that this phase explicitly requires to survive restart or support offline query MUST NOT rely solely on in-memory state.

Other intermediate artifacts that carry authoritative facts required for restart recovery or offline query MUST have an explicit durable or safe reconstruction path. If an exact artifact cannot be safely reconstructed, §8.7 fail-closed semantics apply rather than silently widening this phase into a blanket migration of every domain store.

### 8.2 One ProductTask, one Saga

One V2 ProductTask has exactly one:

```text
saga_id
```

Both required slices belong to that Saga.

Do not create one Saga per Host.

### 8.3 Multi-slice execution-owner projection

The workflow-facing owner view must represent all unresolved dispatch facts.

Conceptually:

```text
ExecutionOwnerView
    saga
    unresolved_dispatch_recoveries[]
```

Each recovery fact maintains:

```text
dispatch intent identity
execution_slice_hash
recovery disposition
```

### 8.4 Recovery classification

Before interpreting aggregate Saga state:

```text
ANY OUTCOME_UNKNOWN
    → RECOVER_OR_WAIT

ANY RECOVERY_REQUIRED
    → RECOVER_OR_WAIT

ANY unresolved SAFE_TO_RETRY
    → RECOVER_OR_WAIT
```

No successful Slice hides another unresolved required Slice.

Only when no unresolved dispatch recovery remains may aggregate Saga state drive terminal/dispatch eligibility.

### 8.5 Exact recovery Slice set

Recovery validates exact membership and detects:

```text
missing required Slice
duplicate Slice
extra Slice
materialization mismatch
execution-plan mismatch
dispatch not belonging to Saga
```

It must never arbitrarily select one Slice from inconsistent state.

### 8.6 Shared composition and concurrency

Retain:

```text
independent transaction ownership
ProductTask start serialization
composition single-flight
create-once request
idempotent exact-task replay
```

Concurrent submission cannot start two workflows.

Concurrent resume cannot consume one human decision twice.

ACCEPT/stale competition follows §5.6.

A committed Slice cannot be redispatched due to request replay, composition rebuild or evidence-read failure.

### 8.7 Reconstruction

After server acceptance, recovery uses:

```text
server-owned immutable V2 input
+ durable exact owner refs
```

not client SQLite.

If required immutable artifacts cannot be safely reconstructed:

```text
fail closed / recovery required
```

Do not reread a newer model and fabricate old approved evidence.

### 8.8 Unknown outcome

Unknown Host effect is never automatically safe to retry.

GET/restart/reconstruction must not issue another Host command merely to obtain cleaner status.

Automatic compensation remains excluded.

## 9. Acceptance gates

### 9.1 Offline and real-owner gates

Mandatory tests include:

- V1 request/hash/replay compatibility.
- Strict V2 request/query discrimination.
- Client durable binding → server immutable takeover.
- Server restart without client SQLite.
- Same-task conflicting body/version/binding rejection.
- Stable policy configuration versus transient runtime identity.
- Cross-Host immutable proposal subject.
- Gate A stale detection.
- Atomic ACCEPT-versus-stale race in both winner orders.
- Gate B post-ACCEPT planning continuity failure.
- New task required after either stale path.
- Stable comparison rules tolerate changed acquisition metadata.
- Real model/revision changes fail continuity.
- Independent Revit PlanningSnapshot.
- Independent AutoCAD PlanningSnapshot.
- Exact two-member SnapshotSet.
- Missing/extra/duplicate member failures.
- Dual-member RevisionBarrier.
- Explicit V2 policy default deny.
- Materialization required-set created only during planning.
- Exact ProviderBinding manifest coverage.
- Exact Grant manifest coverage.
- Workflow artifact persistence/restart of both manifests.
- Manifest integrity/codec/hash validation.
- Manifest resolution does not itself grant authority.
- Partial manifest cannot execute.
- Original Binding/Gateway owner remains authoritative.
- One ProductTask → one execution plan → one Saga.
- Two-Slice recovery projection.
- Multiple unresolved dispatch classification.
- Recovery after process restart does not rerun current readiness merely to read prior state.
- GET with Hosts offline does not invoke execution/admission/readiness.
- Production AutoCAD/Revit ports only.
- V2 evidence body persisted before Saga reference.
- Evidence lineage corruption detection.
- Historical V1 query remains supported.
- Evidence query failure does not redispatch.
- Offline V2 GET.
- `PARTIALLY_COMMITTED`.
- `DIVERGED`.
- `RECOVERY_REQUIRED`.
- Existing predecessor regressions relevant to changed code.

### 9.2 Mandatory controlled live cases

#### Case 1 — Policy deny

```text
real model invocation
→ MCP
→ human ACCEPT
→ policy deny
```

Required proof:

```text
zero execution authority effect
zero ProductTask Host mutation
both independent READs remain at baseline
```

#### Case 2 — Required Host unavailable before execution

After valid proposal preparation but before governed execution, one REQUIRED Host is unavailable.

Required proof:

```text
fail closed
zero ProductTask mutation on available Host
no silent REQUIRED → OPTIONAL downgrade
```

#### Case 3 — Positive cross-Host execution

Required proof:

```text
one ProductTask
one Saga
two REQUIRED slices
one authorized mutation per Host
each Host advances according to its own revision lineage
independent READ = 300 mm on both
convergence = CONVERGED
exact-task MCP GET = SUCCEEDED
```

#### Case 4 — Controlled partial commit

The timing is fixed:

```text
Human decision valid
→ Gate B continuity valid
→ PlanningSnapshot / ChangeSet / Approval valid
→ all-required readiness succeeds
→ AutoCAD ProductTask mutation commits 300 mm
→ independent legal Revit edit changes bound wall 200 → 201 mm
→ Revit revision advances
→ ProductTask Revit command then attempts execution
→ native revision guard reports REVISION_CONFLICT / BEFORE_COMMIT
→ Saga/ProductTask = PARTIALLY_COMMITTED
```

Required proof:

- AutoCAD committed effect remains known.
- Revit ProductTask mutation did not commit.
- No ProductTask Revit ActualDelta is fabricated.
- No false convergence success is emitted.
- No automatic compensation occurs.
- Independent Revit edit has separate command/evidence identity.

An edit occurring:

```text
before Gate A
during Gate B
before all-required readiness succeeds
```

does not satisfy this partial-commit scenario.

It must instead produce the appropriate stale/fail-closed behavior for that earlier stage.

### 9.3 Stale-decision acceptance

Gate A and Gate B are independently tested.

Gate A:

```text
proposal S pending
→ ACCEPT and stale transition race
→ exactly one owner transition wins
→ stale winner prevents late ACCEPT
→ no planning/execution
→ new task required
```

Also test the inverse:

```text
ACCEPT wins
→ late Gate-A invalidation cannot erase accepted history
→ later drift must be handled by Gate B
```

Gate B:

```text
ACCEPT already committed
→ independent planning reconstruction observes drift
→ continuity fails
→ ACCEPT history remains
→ old task stops before execution authority
→ new task required
```

Neither path becomes human `REJECTED`.

### 9.4 Collection path acceptance

Explicitly prove all three post-resolution paths.

Forward execution:

```text
manifest
→ original owner validation
→ current applicability
→ readiness
→ execute
```

Existing-dispatch recovery:

```text
manifest lineage validation where required
+ Saga/dispatch truth
→ recovery path
→ no unconditional execute()
→ no unconditional readiness
→ no re-admission caused by reconstruction
```

Read-only GET:

```text
durable input/artifacts/Saga/evidence
→ query projection
→ Hosts may be offline
→ zero readiness
→ zero admission
→ zero mutation
```

### 9.5 Evidence archive

Closure evidence pins at minimum:

```text
exact implementation HEAD
AutoCAD/Revit plugin build identities
loaded DLL identities
fixture hashes
real model invocation
V2 request hash
SessionBindingV2 hash
topology hash
task_id
proposal subject hash
pause_id
human decision
stale transition evidence where applicable
PlanningSnapshot refs
SnapshotSet ref
ChangeSet
ApprovalScope
policy / Admission / Approval
MaterializationPlan
required_set_hash
ExecutionPlan
both ExecutionSlices
ProviderBinding manifest
original BindingSet refs
Grant manifest
original Grant refs
single saga_id
per-Slice dispatch/recovery facts
per-Host revisions
ActualDelta evidence
independent READ evidence
verification
convergence
final exact-task MCP GET
```

Acceptance archives must remain secret-free and integrity-manifested.

Mutated live fixtures must not overwrite canonical test fixtures.

## 10. Delivery and review boundary

A subsequent Implementation Plan should sequence approximately:

```text
1. V2 ProductTaskRequest / SessionBinding + V1 compatibility
2. server immutable binding takeover/persistence
3. proposal subject + Gate A
4. atomic ACCEPT/stale owner transition
5. dual-Host planning + Gate B continuity
6. stable V2 policy / Approval composition
7. ProviderBinding workflow manifest
8. Gateway Grant workflow manifest
9. manifest codec/persistence/reconstruction
10. forward-execution manifest resolution
11. multi-slice execution-owner recovery projection
12. recovery/read-only path separation
13. AutoCAD production execution/evidence qualification
14. durable reconciliation evidence bodies
15. ProductTaskQueryViewV2
16. offline/real-owner contract suites
17. controlled live acceptance
18. exact-head CI + independent review
19. PR merge + merged-main observation
20. lifecycle closeout
```

Implementation MUST NOT:

```text
alter V1 hash meaning
turn workflow manifests into authorization owners
make coordinator own workflow manifests
route existing-dispatch recovery through execute() merely because composition restarted
rerun Host readiness for read-only GET
re-admit historical grants for query reconstruction
split one ProductTask into multiple Sagas
adopt newer PlanningSnapshot state under old human decision
turn stale into human REJECT
erase an accepted decision after Gate B failure
redispatch because evidence lookup failed
infer measured success from requested intent
import Phase I test helpers into product production code
```

A missing public owner contract or insufficient production Host evidence is an implementation blocker requiring explicit treatment.

It is not waived as a test limitation.

This Design introduces no product code and does not mark the successor capability implementation as started.

Current gate:

```text
Architecture Direction: PASS

Amendment A: PASS
Amendment B: PASS
Amendment C: PASS

Merged Written Spec:
FINAL CONSISTENCY REVIEW
NOT YET FORMALLY APPROVED
```

The next step is one final Written-Spec consistency review of this merged document.

Only after explicit approval of this complete merged Spec may the project proceed to Implementation Plan authoring and Written-Plan Review.