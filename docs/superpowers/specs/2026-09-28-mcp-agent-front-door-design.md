# MCP/Agent Front Door Design

Status: DESIGN-REVIEW
Date: 2026-09-28
Baseline: `architecture/mcp-agent-front-door` @ `b79e0f051bd3952cb533e288d191a1f332a92451`

## 1. Scope and context

This design extends the existing Revit wall-thickness product vertical upstream to one complete, narrow MCP/Agent front-door capability. It does not replace the existing `ProductTaskRequest`, `WallThicknessProductFlow`, workflow runtime, canonical owner composition, Execution Saga, reconciliation, Gateway authorization, or Host verification ownership.

The existing product vertical already establishes these downstream facts:

- `ProductTaskRequest.task_id` is the accepted product-task identity;
- the complete immutable request is server-side business input authority;
- `WallThicknessProductFlow.submit()` persists the request before workflow start;
- same `task_id` + same request is replay-safe at the request owner, while same `task_id` + different request fails closed;
- Revit semantic/context capture validates exact document/runtime evidence before using it;
- workflow / Saga owners remain authoritative for mutation and recovery outcome;
- workflow checkpoints already expose stable pending-human-interaction identity through `pending_interaction.pause_id`, `subject_ref`, and `allowed_resume_kinds`;
- the existing pending-human interaction is `OPERATION_PROPOSAL`; accepting it allows workflow interpretation to continue but does not itself create execution authorization;
- execution authorization is a separate boundary: `CanonicalWorkflowOwnerPorts.request_approval()` obtains an `ApprovalAdmission` from `ApprovalAdmissionPort`, then Gateway V2 consumes that admission to produce authoritative approval truth;
- current real-owner/product acceptance compositions use a test `_ApprovalAdmissionBoundary` that constructs fixed admission evidence, so those tests prove the downstream Gateway/execution path but do not prove a real product approval-admission source.

This phase closes four connected gaps:

1. **reliable submission** — where one logical client submission first receives a stable identity before an Agent/tool call can be replayed, and how that correlation freezes exactly one complete ProductTask request;
2. **session resolution** — how a `session_ref` resolves, after client or composition rebuild, to the same exact Revit project/Host/document binding or fails closed;
3. **usable Product Front Door** — how one minimal reference client takes real natural-language input through Agent interpretation, invokes the Product Front Door over real MCP, surfaces operation-proposal HITL without letting the model manufacture human approval, queries/resumes the task, and returns the verified Revit outcome to the user;
4. **real execution admission** — how the final ChangeSet/ApprovalScope obtains real v1 approval-admission evidence before Gateway authorization, without treating operation-proposal acceptance or a test fixture as execution approval.

The capability remains intentionally narrow: the first supported product action is the already-implemented Revit selected-wall thickness vertical. This design does not create a generalized Agent platform or generalized product-intent layer.

This is a design document only. It records no new implementation or test result.

## 2. Goals

The v1 design MUST:

1. survive network reconnect and client-process restart on the same workstation under the same user configuration;
2. distinguish retry of one logical submission from a second intentional submission with identical content;
3. freeze one complete immutable request before first network send;
4. prevent one client correlation from producing two sent ProductTask requests under duplicate callback, concurrent completion, or declared crash windows;
5. keep client durable state limited to delivery/recovery responsibility; server ProductTask ownership remains the business truth;
6. make `session_ref` resolve to one immutable binding, never whichever Host/document happens to be active after rebuild;
7. use fresh Host evidence to validate runtime/document identity; transport endpoint alone is never identity;
8. preserve the current strict Revit context adapter and current workflow/Saga recovery rules;
9. expose a minimal Product Front Door behavior that maps to existing `submit`, exact request/query ownership, and operation-proposal `resume` behavior instead of creating a second product runtime;
10. expose an operation-proposal pending interaction as stable owner-derived data and require an explicit human decision event before that human resume;
11. keep operation-proposal acceptance semantically separate from final execution authorization;
12. obtain final execution admission from a real configured policy boundary over the actual final ChangeSet/ApprovalScope before Gateway authorization, never from the current test fixture;
13. distinguish “no persisted ProductTask” from “persisted request but no workflow checkpoint yet” during exact task query;
14. keep exact task query available even when the bound Revit Host is unavailable, because querying authoritative request/workflow/Saga state is not Host execution;
15. define an honest local v1 trust boundary without claiming multi-user or remote authorization that does not exist;
16. provide one repository-owned minimal reference client suitable for repeatable acceptance rather than making a third-party Agent UI the capability owner;
17. require the final product acceptance to cross a real MCP transport and a real Revit Host from real natural-language input through operation-proposal HITL, real execution admission, and independent verification;
18. avoid a generic Agent shell, generic `ProductIntentIngress`, new query platform, multi-Host execution scheduler, generalized approval inbox, or new network service by default.

## 3. Explicit non-goals

This phase does not promise:

- global or unlimited-fault-model “exactly once” business effects;
- content-based deduplication of user requests;
- automatic Host mutation replay when outcome is unknown;
- all-open-Revit-document enumeration;
- background document switching;
- multi-document or multi-Host execution;
- durable binding for unsaved documents identified only by title;
- automatic detection of every close/reopen case when current Host identity surfaces cannot distinguish document opening incarnations;
- a mandatory content-addressed `session_ref`;
- a mandatory PostgreSQL/session-registry service;
- a generalized `ProductIntentIngress` layer;
- a generalized Agent desktop/chat UI;
- remote or multi-tenant authorization;
- task enumeration/search as a v1 Product Front Door feature;
- automatic acceptance of a model-generated string as proof that a human approved an operation;
- treating operation-proposal acceptance as approval of a later, not-yet-built ChangeSet;
- using the current fixed test `_ApprovalAdmissionBoundary` as product authorization evidence;
- a generalized asynchronous approval inbox/UI in v1.

`OUTCOME_UNKNOWN` / `RECOVERY_REQUIRED` remain legal outcomes. Recovery does not imply automatic Host mutation resend.

## 4. Frozen responsibility chain

The reliable path begins before the Agent can cause a Product Front Door call and continues until the verified result returns to the user:

```text
Real natural-language user input
        │
        ▼
Repository-owned reference client
        │
        ├─ deterministic Submission Controller
        │    owns durable client_submission_ref
        │
        └─ Agent / LLM interpretation
             interpretation only; no retry identity authority
        │
        ▼
Clarification / deterministic product validation
        │
        ▼
Project context + Revit candidate source
        │
        ▼
Session binding issuance / resolution
        │ session_ref -> one immutable binding
        ▼
Atomic request freeze
        │ client_submission_ref
        │   -> unique task_id
        │   -> complete immutable ProductTaskRequest
        │   -> request_hash
        ▼
Durable client delivery / outbox state
        │ exact frozen request only
        ▼
REAL MCP TRANSPORT
        │
        ▼
Product Front Door MCP
        │ thin submit / get / operation-proposal-human-resume adapter
        ▼
existing ProductTask request owner
        │
        ▼
existing ProductFlow / Workflow / Saga
        │
        ├─ OPERATION_PROPOSAL pending_interaction?
        │        │
        │        └──► reference client renders proposal HITL
        │                 │
        │                 ▼
        │            explicit human accept/reject
        │                 │
        │                 └──► deterministic controller
        │                       invokes MCP human-resume
        │
        ▼
parameter binding / Impact / final ChangeSet + ApprovalScope
        │
        ▼
configured local ApprovalAdmissionPort
        │ evaluates exact final ChangeSet/scope
        │ against immutable configured policy snapshot
        │
        ├─ deny -> fail closed; no Host mutation
        │
        └─ ApprovalAdmission
              │
              ▼
Gateway V2 consume_approval(...)
        │ authoritative ApprovalRecord / approval truth
        ▼
execution planning / provider binding / execution grant
        │
        ▼
real Revit Host execution
        │
        ▼
independent verification / reconciliation
        │
        ▼
Product Front Door get(task_id)
        │
        ▼
user-visible authoritative result
```

An arbitrary Agent or MCP tool call is not the logical-submission identity boundary. Model behavior MUST NOT be relied upon to remember or reuse a retry ID. Likewise, model behavior MUST NOT be treated as the operation-proposal human-decision boundary or as execution approval evidence.

Operation-proposal acceptance and execution authorization are intentionally different decisions. The first permits workflow interpretation to continue. The second evaluates the actual immutable ChangeSet and final ApprovalScope and is the only path that may feed Gateway authorization.

## 5. Decision A — client submission identity and atomic request freeze

### 5.1 `client_submission_ref`

A deterministic client/controller boundary creates or obtains one durable `client_submission_ref` for one explicit logical submit event before Agent interpretation can cause a Product Front Door call.

`client_submission_ref` is client delivery/recovery identity only. It is not a second server ProductTask identity and is not a server business owner. The accepted server identity remains `ProductTaskRequest.task_id`.

Two intentional user submissions MUST receive two different correlations even if all interpreted content is byte-for-byte identical.

### 5.2 Atomic invariant

The transition from “correlation exists but no request has been frozen” to “request is frozen” MUST atomically associate all of the following:

```text
client_submission_ref
    -> exactly one task_id
    -> exactly one complete immutable ProductTaskRequest body
    -> exact request_hash
```

There MUST NOT be an externally recoverable intermediate state in which:

- a correlation owns a task ID but the complete immutable request is missing; or
- a request has been sent but its correlation-to-task/request association was not durably committed.

Implementation may use one transactional record, multiple records under one transaction/constraint, compare-and-set, or an equivalent mechanism. This design does not freeze table shape or storage product.

### 5.3 Replay and callback comparison semantics

Callback handling MUST resolve the correlation before allocating generated identities.

For every Agent/tool callback associated with a `client_submission_ref`, the deterministic controller performs this ordering:

```text
load correlation by client_submission_ref
        │
        ├─ FROZEN_REQUEST exists
        │      -> load winner's exact task_id/session_ref/request/hash
        │      -> compare only normalized freeze input when comparison is needed
        │      -> same normalized input: return/resend winner
        │      -> conflicting normalized input: fail correlation conflict
        │      -> DO NOT allocate another task_id
        │      -> DO NOT issue another authoritative SessionBinding
        │
        └─ no frozen request
               -> normalize callback input
               -> compete to freeze exactly once
               -> winner allocates/publishes generated identities
               -> loser reloads winner and applies the same comparison rule
```

The comparison input for one correlation is the **normalized freeze proposal**, not the complete generated ProductTask body. For v1 it consists of the deterministic user/application inputs that exist before generated identity allocation:

```text
NormalizedFreezeProposal
  project_id
  host_kind
  requested_action
  canonical intent_arguments
  configured candidate key / target constraint
```

`task_id`, opaque `session_ref`, `request_hash`, timestamps, delivery counters, and other generated/operational fields are explicitly excluded from callback equivalence. They become authoritative only through the committed winner.

Therefore:

- a callback arriving after freeze MUST first read the frozen result; it never regenerates identity in order to decide whether the callback is “the same”;
- two concurrent callbacks with the same normalized freeze proposal race for one freeze; the loser reads the winner rather than comparing independently generated UUIDs;
- if an implementation must create tentative local values before the compare-and-set, those values have no authority, MUST NOT participate in conflict comparison, and MUST NOT publish an extra authoritative binding or request when that attempt loses;
- two callbacks for the same correlation with different normalized freeze proposals are conflicting user/application input; at most one may freeze and the other fails closed;
- two different correlations remain two distinct submissions even when their normalized freeze proposals are identical.

After the atomic freeze succeeds:

- Agent/tool replay for the same `client_submission_ref` MUST return or resend the exact frozen request;
- natural language MUST NOT be reinterpreted to rebuild the request;
- the request body, `task_id`, `session_ref`, and hash MUST NOT be rewritten;
- content equality across different correlations is never a retry key.

A crash before the atomic freeze commits may leave no frozen request; replay may then complete one freeze. A crash after commit must reload the exact frozen request.

### 5.4 Outbox ordering

The complete immutable request and its correlation association MUST be durable before first send to Product Front Door MCP. Delivery attempts, acknowledgements, retry counters, and response recovery may change, but the frozen request does not.

Conceptually:

```text
CORRELATED_NO_REQUEST
        │ atomic freeze
        ▼
FROZEN_REQUEST(task_id, full_request, request_hash)
        │
        ▼
DELIVERY_PENDING / SENT / ACKNOWLEDGED / RECOVERY_REQUIRED
```

Delivery state is not business truth.

## 6. Decision B — v1 session binding authority

### 6.1 Required logical contract

The frozen invariant is:

```text
same session_ref
    -> same immutable SessionBinding body
    OR
    -> explicit resolution / validity failure
```

The same `session_ref` MUST NEVER be rebound to another Revit process, project, or document.

Content addressing is not required to obtain this invariant. v1 chooses an **opaque `session_ref` plus a create-once immutable binding record** because that is the smallest contract that separates identity from representation. A content-addressed locator remains a compatible future implementation option.

### 6.2 Logical `SessionBinding`

The minimum v1 binding is conceptually:

```text
SessionBinding
  session_ref
  project_id
  host_kind = REVIT
  transport_locator
  host_instance_id
  document_id
  [document_title: presentation metadata only]
```

`transport_locator` is a connection location. It is not Host identity.

A binding implementation MAY add integrity hash, issuance metadata, version, or validity state. Those fields do not change the invariant that the target body is create-once and immutable.

### 6.3 Who may issue a binding

The binding issuer is a deterministic DSP application/controller authority, not the LLM and not the native Revit identity reader.

For v1, `project_id` comes from deterministic DSP application/project configuration. Revit document path/title does not automatically define the DSP project, and the model does not infer project association.

The Revit Host supplies fresh Host/document evidence. It does not decide the DSP `project_id` or issue the DSP `session_ref`.

### 6.4 Who resolves a binding

Product/application composition uses a narrow session-resolution contract:

```text
resolve(session_ref) -> exact immutable SessionBinding | failure
```

This is a logical application capability, not a requirement for a new network service. Physical backing MAY be durable configuration or a create-once record inside an existing durable application boundary. Implementation planning MUST census existing persistence/configuration surfaces before adding storage.

Composition rebuild MUST reload the same binding body or fail closed. It MUST NOT reconstruct a new target from current active Host state under the old `session_ref`.

### 6.5 Which bindings Product Front Door accepts

A new ProductTask submission is admissible only when:

- `session_ref` resolves through the configured v1 binding authority;
- request `project_id` equals binding `project_id`;
- request `host_kind` equals binding `host_kind`;
- the binding is not invalid/unavailable under the declared v1 lifecycle rules;
- fresh Host validation proves the runtime/document target required by the binding before Host-bound workflow use.

Unknown, mismatched, substituted, or non-recoverable bindings fail closed. The front door does not silently create a replacement binding during task replay.

This admission rule MUST NOT be misapplied to read-only lookup of an already-existing task. `get(task_id)` reads authoritative ProductTask request/workflow/Saga state and does not require the old Revit Host to be reachable. Fresh Host validation applies only when the operation will newly depend on live Host state or continue Host-bound work.

## 7. Decision C — v1 binding source: configured candidate + runtime issuance

A fully static exact binding is insufficient for the first Revit path because the exact Revit runtime identity is process-lifetime evidence and must be read from the live Host. A general dynamic candidate-enumeration platform is also unnecessary for v1.

Therefore the mandatory v1 path is:

1. deterministic application configuration supplies the DSP `project_id` and the intended Revit connection/candidate constraint;
2. a read-only Host identity probe obtains the current actual `host_instance_id` and current active-document identity;
3. the controller verifies that evidence against the configured candidate constraint;
4. only the winning freeze path may publish the opaque `session_ref` and immutable binding used by the ProductTask request;
5. later composition rebuild resolves that exact binding and revalidates it against fresh Host evidence before Host-bound work proceeds.

This is **configured candidate selection plus runtime binding issuance**, not “whichever Revit is active at submit time.”

It also does not require an all-instances discovery subsystem for v1. If product UX later requires runtime enumeration of multiple reachable Revit instances, that is an adapter/application capability layered before binding issuance; it does not change SessionBinding semantics.

## 8. Existing Revit discovery and validation boundary

The repository already has native read-only identity capability: `RevitContextIdentityReader` handles `context.current_selection` and returns the current active document identity, current `host_instance_id`, selection, and revision evidence. Its document identity rule is current path when saved, otherwise title.

The repository also has strict sidecar/application context reading that expects a target `document_id` and `host_instance_id` and verifies the Host response matches them. That strict adapter is validation, not a complete reusable candidate-discovery authority.

Existing live-acceptance code also demonstrates test-side discovery of actual live Host/document identity before building the acceptance composition. Offline fixtures use constants. These are different facts and MUST NOT be conflated.

The accurate gap is therefore:

> native read-only identity capability and test-side discovery usage exist; the production application layer does not yet expose one explicit reusable candidate-discovery/session-binding contract.

For v1, the mandatory configured-candidate path should reuse the existing native read-only identity operation where its command constraints and semantics fit. It MUST NOT add a new Revit command by default and MUST NOT bypass the strict context adapter’s later exact validation.

If dynamic candidate discovery is added later, v1 capability is limited to each reachable Revit instance’s **current active document**. It does not enumerate every open document or switch background documents.

## 9. Endpoint and identity semantics

The named-pipe endpoint is a locator only. The current default name includes machine/process information and can also be customized; neither the pipe name nor PID proves Host identity.

Every binding use that depends on a live Revit runtime MUST validate fresh Host evidence against the binding’s `host_instance_id` and document target. Endpoint reuse, PID reuse, or a custom endpoint name cannot satisfy identity validation by themselves.

Likewise, current Revit `document_id` is not an opening-incarnation identity: it is saved path when present, otherwise title. v1 MUST therefore state a narrower support boundary rather than claiming stronger guarantees than the Host API exposes.

## 10. Decision D — v1 Revit lifecycle support boundary

### 10.1 Saved, controlled documents only

Durable v1 SessionBinding supports saved Revit documents with a stable path under the declared same-workstation / same-user environment. Unsaved documents whose identity is title-only are outside the durable v1 binding guarantee.

### 10.2 Host restart

Revit/AgentHost restart invalidates use of the old process-lifetime binding for new Host-bound work. The old `session_ref` MUST NOT be updated to the new runtime identity.

The new runtime requires a new binding and new `session_ref` before a new ProductTask can target it. Existing ProductTask records remain immutable and enter normal failure/recovery semantics according to workflow/Saga state.

An unavailable old Host does **not** make an existing task unqueryable. The Product Front Door can still return its durable request/workflow/Saga projection. Only an operation that must access or continue against the old Host is blocked by Host unavailability or binding invalidity.

### 10.3 Active document switch

If the active document no longer matches the bound document, fresh validation for Host-bound work fails closed. v1 does not switch the active document automatically.

If the same still-running Host returns to the exact supported bound document and fresh validation again satisfies the binding, a later safe retry may proceed according to the existing workflow stage. This rule does not permit replay of an unknown Host mutation.

Read-only `get(task_id)` remains independent of the active-document state.

### 10.4 Document close/reopen

The v1 durable guarantee assumes the bound document remains continuously open for the lifetime of that binding.

Closing and reopening the document semantically requires a new binding for new work. However, with the current path-based saved-document identity, the system may not be able to distinguish every “same path, same Host process, newly reopened document” case automatically. The Spec therefore does **not** claim automatic invalidation detection for that case.

Where a close/reopen or document-instance change cannot be proven with current identity surfaces, the case is outside the v1 guarantee and requires explicit rebinding. Stronger document-opening-instance identity is deferred.

## 11. Decision E — concurrent first `submit()` remains a verification gate

The current request owner already provides create-once behavior for `task_id`: same request replay is idempotent and a different body conflicts. The current product facade then performs:

```text
request_store.create(request)
-> workflow_runtime.get_checkpoint(task_id)
-> if absent: workflow_runtime.start(...)
```

This design MUST NOT infer from that sequence that concurrent first submit is already serialized. Two callers may race after the same request has been accepted and both observe an absent checkpoint unless the underlying runtime/owner contract proves otherwise.

Implementation planning must therefore preserve a dedicated gate for concurrent first `submit()` and prove the actual owner semantics rather than add a process-local lock as a substitute for durable correctness.

The same ordering deliberately permits a second real crash state: the immutable `ProductTaskRequest` may already exist while the workflow checkpoint does not yet exist. That state is not “task not found”; its exact query semantics are frozen in §12.3.

Required business-level acceptance wording is concrete:

> Concurrent submission of the same task does not create a second effective business lineage and does not duplicate Host mutation; after declared crash windows the original persisted request remains queryable/recoverable.

This design intentionally does not label that guarantee “business effect exactly-once.”

## 12. Decision F — minimal Product Front Door MCP behavior

### 12.1 Thin adapter, not a second runtime

The Product Front Door is a thin MCP adapter over the existing product facade and owner contracts. Exact public tool names are intentionally left to implementation planning, but the v1 logical surface is frozen to three behaviors:

```text
submit complete frozen ProductTaskRequest
    -> WallThicknessProductFlow.submit(request)

get exact task_id
    -> exact ProductTaskRequest owner lookup
    -> if workflow checkpoint exists, existing ProductFlow projection

submit explicit operation-proposal human interaction result
    -> validate current pending interaction
    -> construct exact WorkflowResumeCommand
    -> WallThicknessProductFlow.resume(task_id, command)
```

The MCP adapter MUST NOT:

- interpret natural language;
- allocate `client_submission_ref`;
- decide `task_id` retry identity;
- infer or replace `session_ref`;
- own operation-proposal HITL or execution-approval truth;
- manufacture `ApprovalAdmission` from model text or operation-proposal acceptance;
- duplicate request/workflow/Saga outcome state;
- perform broad task enumeration or “latest task” lookup.

The reference client/controller owns natural-language orchestration and reliable-delivery state. Existing server owners remain authoritative for business state. The existing `ApprovalAdmissionPort` + Gateway boundary remains authoritative for execution admission/authorization semantics.

### 12.2 Submit behavior

Submit receives the exact complete ProductTask request already frozen by the deterministic controller. The MCP adapter validates/decodes the wire request and delegates to the product facade. Same frozen request replay must retain the existing ProductTask idempotency behavior; the MCP layer does not create a new retry identity.

A submit result projects the existing `ProductFlowView` and enough framework-neutral checkpoint information for the caller to continue safely. It may expose stable locators/status such as:

- `task_id`;
- product status;
- workflow phase;
- current `pending_interaction` when present;
- `saga_id` or other already-public stable references when needed for presentation/debugging.

It MUST NOT copy private LangGraph state or create a second authoritative business object.

### 12.3 Exact query behavior and the persisted-request / no-checkpoint state

`get(task_id)` is an exact, read-only lookup. It MUST distinguish request existence from workflow-checkpoint existence because the current submit ordering intentionally persists the request before workflow start.

The logical query matrix is:

| Durable ProductTaskRequest | Workflow checkpoint | Query fact |
| --- | --- | --- |
| absent | absent | no persisted ProductTask exists for this exact `task_id` |
| present | absent | request is durably accepted/persisted, but no queryable workflow checkpoint has been established yet |
| present | present | return the existing workflow/Saga product projection |
| absent | present | invariant violation / corrupted lineage; fail closed rather than report not-found |

Concrete public status names are left to the Implementation Plan. The semantic distinction is not optional.

The middle state MUST be projected from the existing immutable request owner, not guessed from client delivery state. At minimum the query result can prove the exact `task_id` and frozen `request_hash` already accepted by the server while stating that workflow state is not yet available.

The current `WallThicknessProductFlow.get()` only reads the workflow checkpoint, so it cannot by itself distinguish the first two rows. Implementation may either minimally extend the product facade or compose the Product Front Door query from the existing `ProductTaskRequestStore.get(task_id)` plus the existing flow/checkpoint projection. It MUST NOT introduce a second ProductTask owner merely to represent this state.

`get(task_id)` MUST also:

- remain usable when Revit, the named pipe, the old `session_ref` target, or other Host-bound dependencies are unavailable;
- expose current operation-proposal pending-interaction identity when a checkpoint exists and such an interaction is pending;
- avoid fresh Host validation unless a later operation actually needs live Host access;
- never start a missing workflow, resume/poll workflow work, create a new task, or resend a Host mutation as a side effect of query.

Recovery from the persisted-request/no-checkpoint state is a separate write action: the deterministic Submission Controller may replay the **same frozen submit request**. Existing request create-once semantics must make that replay idempotent, after which the server may establish the missing workflow according to the proven concurrent-first-submit contract. Read-only `get()` itself does not perform that recovery.

Task lookup is therefore separated from execution eligibility and recovery progression. A user can inspect a persisted-pre-workflow, failed, completed, recovery-required, or Host-orphaned task without reconnecting Revit first.

### 12.4 Operation-proposal human interaction / resume behavior

The existing workflow checkpoint is the source of truth for whether an operation-proposal human decision is currently pending. The Product Front Door does not accept a free-form “approved=true” claim.

For that human resume the adapter/controller must first use the exact current `pending_interaction` and enforce:

- exact `task_id`;
- exact current `pause_id`;
- a decision mapped only to one of `allowed_resume_kinds`;
- the current workflow contract’s payload restriction (the existing operation-proposal pause accepts no arbitrary resume payload);
- stale `pause_id`, mismatched action, missing pause, or replay after consumption fails closed.

The final server call constructs the existing `WorkflowResumeCommand`; it does not invent a new approval owner.

The semantic meaning of `OPERATION_PROPOSAL_ACCEPTED` is deliberately narrow:

> the user accepts the currently resolved operation proposal as the basis for continuing parameter binding, impact analysis, and final ChangeSet construction.

It does **not** mean:

- the final `CanonicalChangeSet` has already been seen or approved;
- the final ApprovalScope is authorized;
- an `ApprovalAdmission`, `ApprovalRecord`, or `ExecutionGrant` exists;
- Host mutation may proceed without the later execution-admission boundary.

Most importantly, the **model is not the human-decision authority**. In the v1 reference path, the model-callable interpretation surface MUST NOT include the controller-only operation-proposal human-resume action. The reference client renders the owner-derived pending interaction to the user; only an explicit local human action causes the deterministic controller to invoke the MCP resume behavior.

This separation is a reference-path enforcement rule, not a claim that MCP itself supplies universal human identity or enterprise authorization.

### 12.5 Final execution admission and Gateway authorization

Execution approval is a later, separate boundary over the actual immutable ChangeSet.

The existing Step32 contract defines `ApprovalAdmission` as already-authenticated and already-policy-evaluated evidence. `CanonicalWorkflowOwnerPorts.request_approval(changeset_ref)` delegates to the existing `ApprovalAdmissionPort`; only a returned `ApprovalAdmission` is then combined with authoritative ChangeSet/ApprovalScope owner data and consumed by Gateway V2 to create approval truth.

The mandatory v1 reference composition selects a **synchronous configured local policy admission boundary** as the real `ApprovalAdmissionPort` implementation. This avoids conflating operation-proposal acceptance with execution approval and avoids adding a second mandatory human click or generalized approval inbox.

For v1 that boundary MUST:

1. load the exact authoritative final ChangeSet and final ApprovalScope corresponding to the supplied `changeset_ref`;
2. evaluate them against an explicit immutable application/project policy snapshot rather than against model output;
3. bind the resulting admission to the exact `changeset_hash`, `approved_scope_hash`, semantic environment, allowed canonical operations, authorization principal/policy identity, approval time, expiry, and policy snapshot hash required by the existing `ApprovalAdmission` contract;
4. use real configured policy material and an injected/runtime clock/lifetime policy rather than hard-coded test approver, hash, or timestamps;
5. return an `ApprovalAdmission` only when that exact final ChangeSet/scope is authorized; policy absence, mismatch, or denial fails closed before any Host mutation;
6. leave Gateway V2 responsible for consuming the admission and producing authoritative `ApprovalRecord` / downstream execution authority.

The v1 local authorization principal is interpreted only inside the already-declared same-workstation trust boundary. This design does not upgrade it into enterprise authentication or remote identity. Future multi-user/remote use still requires explicit authentication/authorization design.

The existing test `_ApprovalAdmissionBoundary` remains valid as a deterministic test fixture for downstream behavior, but it is **not** a valid implementation for mandatory reference/live capability acceptance. A reference acceptance must prove the configured policy snapshot/admission that actually authorized the live final ChangeSet.

`ApprovalAdmissionPort` remains compatible with returning `AsyncOperationRef`, but asynchronous execution approval is not selected for the mandatory v1 reference path. If a future implementation selects it, the async approval owner must durably own approval-pending/completion state and an explicit approval action or policy event must complete it; workflow may then poll/resume the existing `POLICY_APPROVAL` wait. Read-only Product Front Door `get()` never completes, polls, or advances that async operation on the caller's behalf.

## 13. Decision G — v1 reference client, trust boundary, and complete product path

### 13.1 Reference path selection

v1 selects a **repository-owned minimal reference client** as the mandatory reference path instead of making a third-party mature Agent Host the capability acceptance owner.

The reference client is deliberately small. It exists to prove the architecture and provide a reproducible product path, not to become a general chat application. It has only these responsibilities:

1. accept real user natural-language input for the supported wall-thickness action;
2. create/recover `client_submission_ref` through the deterministic Submission Controller;
3. invoke one real Agent/model interpretation boundary that produces the narrow normalized product intent/candidate proposal;
4. perform clarification/deterministic validation as needed;
5. resolve/issue the session binding and atomically freeze the exact ProductTask request;
6. call the Product Front Door through a real MCP client/transport using only the frozen request;
7. render returned status and owner-derived operation-proposal HITL;
8. capture an explicit human accept/reject action outside the model and invoke the MCP operation-proposal human-resume behavior directly from the deterministic controller;
9. observe the same task as workflow constructs the final ChangeSet and the real configured policy admission boundary either denies or authorizes it through the existing Gateway path;
10. query the same `task_id` until an authoritative terminal/recovery state is available;
11. present that result to the user without inventing success.

The reference client does not create `ApprovalAdmission`. The Agent/model output is a proposal to the deterministic controller, not a durable ProductTask, not an operation-proposal human decision, and not final execution authorization.

### 13.2 Real MCP boundary

The repository already uses MCP SDK server/client contracts and a loopback-only Streamable HTTP pattern for the Semantic MCP adapter. Product Front Door v1 should reuse that proven transport shape unless implementation census identifies an even narrower existing local transport that satisfies the same acceptance needs.

For capability acceptance, “real MCP” means the request crosses the MCP protocol/client-server adapter boundary. Calling `WallThicknessProductFlow` directly from a test or client does not satisfy the final Front Door acceptance even though direct facade tests remain required for lower-level correctness.

The implementation plan may freeze exact executable/module/tool names after repository census. It may not replace the mandatory MCP acceptance with a direct Python function call.

### 13.3 Local v1 trust boundary

v1 is a local workstation capability, not a remote multi-tenant service.

Until a gateway/authentication design exists:

- Product Front Door transport MUST NOT bind to a non-local network interface by default;
- task lookup is exact-ID only; there is no list/search-all-tasks surface;
- `task_id` is a locator, not a security credential;
- loopback/process-local reachability is treated as part of the trusted local workstation boundary, not as strong user authentication;
- the configured local policy admission principal/policy identity is part of this same narrow trust model and must not be described as enterprise user authentication;
- the design does not claim isolation from every other local process/user on the same machine;
- any future remote access or multi-user deployment requires an explicit authentication/authorization design rather than extending this trust assumption silently.

Within this v1 trust boundary, the reference client may query/resume tasks that it knows by exact `task_id`. Operation-proposal resume still requires the exact current pending-interaction contract and explicit human event described above. Final execution admission still requires the separate configured policy evaluation described in §12.5.

### 13.4 Mandatory end-to-end product acceptance

The capability is not complete merely because correlation storage, SessionBinding, MCP tool delegation, operation-proposal resume, configured policy evaluation, or direct facade tests pass independently.

The mandatory live reference path is:

```text
real saved Revit document + supported selected wall
        │
        ▼
real Revit AgentHost / sidecar identity evidence
        │
        ▼
reference client receives real natural-language request
        │
        ▼
real Agent/model interpretation produces supported intent proposal
        │
        ▼
deterministic controller
  -> correlation
  -> session binding
  -> atomic complete request freeze
        │
        ▼
real MCP client/transport
        │
        ▼
Product Front Door submit
        │
        ▼
ProductTask / ProductFlow / Workflow
        │
        ▼
owner-derived OPERATION_PROPOSAL pending interaction
        │
        ▼
reference client shows human the operation proposal
        │
        ▼
explicit human accept/reject event
        │
        ▼
deterministic controller invokes Product Front Door human-resume over MCP
        │
        ▼
parameter binding / Impact / final ChangeSet + ApprovalScope
        │
        ▼
real configured local policy admission boundary
        │
        ├─ denied -> no Host mutation
        │
        └─ ApprovalAdmission
              │
              ▼
Gateway V2 ApprovalRecord / execution authorization
        │
        ▼
real Revit mutation
        │
        ▼
independent verification / reconciliation
        │
        ▼
Product Front Door get(task_id) over MCP
        │
        ▼
user receives authoritative result
```

The positive live acceptance for the current vertical must prove the existing product goal (selected Revit Wall thickness changed to the requested supported value, with independent verification) through this entire path.

Because a real Agent/model and real Revit are external live dependencies, this gate may be a controlled/manual live acceptance rather than a canonical offline CI job. The runbook MUST record enough evidence to show the natural-language input, actual MCP path, task identity, operation-proposal `pause_id`/human decision, final ChangeSet identity, configured policy snapshot/admission identity, Gateway approval identity, Revit execution, independent verification, and final authoritative product result. Deterministic offline fixtures do not substitute for this live gate.

A third-party mature Agent Host may later be added as an interoperability acceptance, but it is not the v1 capability authority and is not required to define the architecture.

## 14. Acceptance gates

### 14.1 Client correlation and request freeze

1. Crash after correlation creation but before freeze: no request was sent; replay can freeze at most one complete request.
2. Crash during freeze: restart observes either no frozen request or one complete frozen request; never a partial correlation/task/request association.
3. A callback for an already-frozen correlation reads the frozen winner before any identity allocation; identical normalized freeze input returns/resends the exact winner without allocating a new `task_id` or authoritative `session_ref`.
4. A callback for an already-frozen correlation with conflicting normalized freeze input fails correlation conflict and does not change the winner.
5. Concurrent completion for the same correlation and same normalized freeze proposal freezes exactly one request; losers reload the winner even if their local execution had prepared different tentative UUID values.
6. Concurrent completion for the same correlation with conflicting normalized freeze proposals allows at most one winner; the other path fails conflict; no second request is sent and no losing authoritative binding is published.
7. Product Front Door accepts a request but the response is lost: client replay sends the exact same task ID and full request.
8. Two distinct correlations with identical normalized freeze proposals create two distinct task IDs and remain separate intentional submissions.

### 14.2 Server first-submit and persisted-request query gate

9. Concurrent first `submit()` of the same `task_id` and same body produces one authoritative ProductTask/business lineage and no duplicate Host mutation.
10. Same `task_id` with different request body fails conflict and never overwrites the original request.
11. Declared server/process crash windows preserve query/recovery of the original task. `OUTCOME_UNKNOWN` / `RECOVERY_REQUIRED` are legal; unknown outcome never authorizes blind mutation resend.
12. When neither request nor checkpoint exists for an exact `task_id`, Product Front Door returns not-found.
13. When the immutable request exists but no checkpoint exists, Product Front Door returns an explicit persisted-request/pre-workflow fact rather than not-found; `get()` creates or resumes nothing.
14. From that persisted-request/no-checkpoint state, replay of the exact same frozen submit may recover workflow start under the proven first-submit contract; `get()` itself remains side-effect free.
15. When request and checkpoint both exist, Product Front Door returns the existing ProductFlow/workflow/Saga projection.
16. A checkpoint without its authoritative ProductTask request is treated as an invariant violation and fails closed rather than being reported as not-found or reconstructed from checkpoint data.

### 14.3 Session binding and lifecycle

17. Client/application composition restart resolves the same `session_ref` to the exact same immutable binding body or fails.
18. Attempting to rewrite an existing `session_ref` to another project/Host/document binding is rejected.
19. Reusing the same endpoint while fresh Host runtime identity differs is rejected for Host-bound work; new binding is required for new work.
20. Active-document switch causes Host-bound start/resume validation failure; no automatic document switch occurs.
21. Unsaved title-only documents are rejected for durable v1 binding.
22. Close/reopen handling asserts only what current identity surfaces can prove; same-path same-process reopen is not claimed to be automatically detectable and is outside the continuous-open v1 guarantee.
23. If the target changes between candidate observation and binding issuance / first Host-bound use, fresh identity validation rejects the stale target.
24. An unavailable/restarted old Host does not prevent `get(task_id)` from returning the durable request/workflow/Saga facts of an existing task.

### 14.4 Candidate/discovery boundary

25. The v1 configured-candidate path reuses existing native read-only context identity capability where compatible; a new Revit command is not introduced merely to create SessionBinding.
26. Any later dynamic discovery contract exposes reachable instances’ current active documents only; it does not imply all-open-document enumeration or multi-Host execution.
27. Configured endpoint/path constraints are candidate inputs, not identity proof; live runtime/document evidence must still match for Host-bound work.
28. Durable client delivery and session-resolution state survives the declared same-workstation client-process restart scope.

### 14.5 MCP tool behavior and operation-proposal HITL

29. A real MCP client can negotiate/list the Product Front Door surface and invoke submit/get/operation-proposal-human-resume behavior through the MCP adapter; direct facade invocation is covered separately and cannot satisfy this gate.
30. Submit receives an already-frozen complete request and does not allocate retry identity or reinterpret natural language.
31. Exact `get(task_id)` is read-only, distinguishes persisted request from checkpoint existence, and performs no Host mutation/workflow-start/resume side effect.
32. When `pending_interaction` exists, MCP output preserves the exact owner-derived `pause_id`, subject reference, and allowed resume kinds needed by the client to render the operation-proposal HITL state.
33. Operation-proposal human resume with stale/missing `pause_id`, disallowed resume kind, or arbitrary payload fails closed according to the existing workflow contract.
34. The reference Agent/model is not given authority to invoke the controller-only operation-proposal human-resume action; an explicit human event is required before the deterministic controller sends that MCP resume call.
35. Operation-proposal acceptance is proven not to create or imply an `ApprovalAdmission`, `ApprovalRecord`, or Host execution authority.
36. Query of a persisted-pre-workflow, terminal, failed, or recovery-required task remains available while Revit is offline.
37. Product Front Door is local-only under the v1 trust boundary and exposes no broad task enumeration surface.

### 14.6 Execution approval admission

38. After operation-proposal acceptance, the real reference path reaches final ChangeSet/ApprovalScope before execution admission is decided.
39. The mandatory reference composition uses a real configured policy-backed `ApprovalAdmissionPort`; it does not inject the fixed test `_ApprovalAdmissionBoundary` or equivalent hard-coded admission values.
40. The configured policy boundary evaluates the exact final ChangeSet/scope and returns an admission only when the configured policy snapshot explicitly authorizes the required canonical operations and lineage; policy absence/mismatch/denial prevents Host mutation.
41. A successful admission carries real configured policy snapshot/principal evidence plus non-fixture timing/expiry evidence and is consumed by the existing Gateway V2 to produce authoritative approval truth.
42. Operation proposal accepted + execution admission unavailable or denied results in no Host mutation and no bypass to execution planning/grant issuance.
43. If an alternative asynchronous approval implementation is later introduced, it owns durable approval-pending/completion state through an `AsyncOperationRef`; an explicit approval/policy event plus workflow poll/resume advances it, while Product Front Door `get()` remains read-only and cannot serve as the progression mechanism.

### 14.7 Complete live product acceptance

44. A real natural-language request enters the repository-owned reference client and crosses a real Agent/model interpretation boundary rather than being replaced by a prebuilt ProductTask fixture.
45. The resulting supported intent is frozen under one `client_submission_ref`, sent through a real MCP client/transport, and accepted as one authoritative ProductTask.
46. The same live task reaches owner-derived operation-proposal HITL; the reference client renders it and records an explicit human accept/reject event before resume.
47. Positive acceptance resumes through real MCP, constructs the final ChangeSet/scope, obtains a real configured-policy `ApprovalAdmission`, and records the resulting Gateway approval lineage before any Revit mutation.
48. The admitted task performs the real Revit wall-thickness mutation and obtains independent verification/reconciliation evidence.
49. The reference client queries the same `task_id` through MCP and presents the authoritative final result to the user.
50. The live evidence/runbook records enough lineage to prove that natural-language input, MCP task identity, operation-proposal HITL identity/human decision, final ChangeSet, configured policy/admission, Gateway approval, Host mutation, verification, and final outcome belong to the same task.

## 15. Rejected / deferred alternatives

### 15.1 Content equality as submission deduplication

Rejected. Two intentional submissions may contain identical content. Retry identity comes from `client_submission_ref`, not content.

### 15.2 Let the Agent/model reuse task identity

Rejected. The reliable boundary must be deterministic and recoverable independently of model behavior.

### 15.3 Compare complete generated ProductTask bodies before choosing a freeze winner

Rejected. `task_id` and opaque `session_ref` are generated identities; generating them independently before callback equivalence would turn an otherwise identical duplicate callback into a false conflict. Same-correlation equivalence is defined on the normalized freeze proposal, while winner-generated identities come from the committed freeze result.

### 15.4 Mandatory content-addressed `session_ref`

Not selected. Content addressing is compatible with the immutable-binding contract but is not necessary to enforce it. v1 uses an opaque reference plus create-once immutable record.

### 15.5 Mandatory new Session Registry service/database

Rejected as an architectural requirement. A narrow resolver/authority is required logically; its physical backing must reuse durable configuration or an existing application persistence boundary when that satisfies v1. A new service requires separate evidence of need.

### 15.6 Pure static exact SessionBinding

Not sufficient for the first Revit path because exact process-lifetime Host identity must be captured from the live runtime. v1 instead uses a configured candidate plus runtime identity capture before binding issuance.

### 15.7 General dynamic Revit discovery platform in v1

Deferred. Existing native read-only capability is sufficient to validate the first configured candidate. A reusable enumeration contract may be added when real UX requires selecting among multiple reachable instances.

### 15.8 Generic `ProductIntentIngress`

Not justified. Current evidence supports deterministic submission state + narrow session resolution + thin MCP adapter over the existing ProductTask/ProductFlow boundary.

### 15.9 Make a third-party mature Agent Host the v1 acceptance owner

Not selected. It would couple architectural acceptance to external Host UX/configuration and make deterministic recovery/HITL gates harder to reproduce. A repository-owned minimal reference client proves the required path; external mature Hosts remain future interoperability targets.

### 15.10 Let the model submit operation-proposal human approval

Rejected. Existing workflow pause identity already gives the deterministic client an exact `pause_id` and allowed resume kinds. Operation-proposal human acceptance remains an explicit client-side human event that the controller maps into the existing resume contract; model text is not approval evidence.

### 15.11 Treat operation-proposal acceptance as final execution approval

Rejected. The final ChangeSet and ApprovalScope do not yet exist at the operation-proposal pause. Accepting a proposal authorizes continuation of analysis/construction only; it cannot authorize an unseen final ChangeSet or satisfy the existing `ApprovalAdmission` / Gateway boundary.

### 15.12 Reuse the fixed test approval-admission boundary in the product reference path

Rejected. The fixture is useful for deterministic downstream tests but its hard-coded approver, policy hash, and timestamps are not proof of a real product authorization source. Mandatory reference/live acceptance uses the configured policy-backed admission boundary.

### 15.13 Select asynchronous execution approval for the mandatory v1 reference path

Not selected. The existing `ApprovalAdmissionPort` and workflow can represent `AsyncOperationRef`, but doing so would require an additional durable approval-completion owner and progression surface. The first reference path can prove the real separation more narrowly with synchronous configured policy evaluation. Async approval remains compatible for a later capability.

## 16. Final v1 architecture decision

The selected v1 is **A + narrow session resolver + thin Product Front Door MCP + minimal reference client + configured policy execution admission**, with no generalized ingress or approval-inbox layer:

```text
Repository-owned reference client
  receives real natural language
  + runs narrow real Agent/model interpretation
  + owns deterministic client controller

Deterministic client controller
  owns client_submission_ref
  + normalized freeze proposal
  + atomic correlation/task/full-request freeze
  + durable outbox delivery state
  + explicit operation-proposal human-event handling

Session binding authority/resolver
  uses configured DSP project/candidate context
  + fresh native Revit identity evidence
  -> issues opaque create-once session_ref only for the winning freeze path
  -> resolves exact immutable binding after rebuild
  -> does not require a new service by design

Product Front Door MCP
  thin real-MCP adapter
  -> submit exact frozen request
  -> get exact task by joining immutable request existence with workflow projection
  -> transfer explicit operation-proposal human resume after exact pending-interaction validation
  -> does not interpret natural language or own approval

Configured local ApprovalAdmissionPort
  -> evaluates exact final ChangeSet + ApprovalScope
     against immutable configured policy material
  -> returns real ApprovalAdmission or denies
  -> does not reuse test fixture admission values

Existing Gateway V2
  -> consumes ApprovalAdmission
  -> owns authoritative ApprovalRecord / execution authorization truth

Existing ProductTask / ProductFlow / Workflow / Saga owners
  remain authoritative for business lineage, operation-proposal HITL navigation,
  execution, recovery, and outcome

Real Revit Host + independent verification
  remain authoritative for actual Host effect/evidence
```

The implementation plan may choose concrete storage, adapter/tool names, configured-policy file/schema location, model provider, reference-client executable shape, and query response type names only after repository census. It may not weaken the atomic-freeze invariant, compare duplicate callbacks on independently generated IDs, substitute endpoint equality for Host identity, rebind an existing `session_ref`, report persisted-request/no-checkpoint as not-found, make read-only `get()` advance recovery/approval, treat operation-proposal acceptance as final execution authorization, reuse fixed test admission data as the mandatory reference approval source, require a live Host merely to query an existing task, expose model-generated text as human approval, replace the mandatory real-MCP acceptance with direct facade calls, expand document support beyond the declared v1 boundary, or claim concurrent first-submit correctness without proving the gate.
