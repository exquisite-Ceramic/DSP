# MCP/Agent Front Door Design

Status: DESIGN-REVIEW  
Date: 2026-09-28  
Baseline: `architecture/mcp-agent-front-door` @ `b79e0f051bd3952cb533e288d191a1f332a92451`

## 1. Scope and context

This design extends the existing Revit wall-thickness product vertical upstream to one complete, narrow MCP/Agent front-door capability. It does not replace the existing `ProductTaskRequest`, `WallThicknessProductFlow`, workflow runtime, canonical owner composition, Execution Saga, reconciliation, or Host verification ownership.

The existing product vertical already establishes these downstream facts:

- `ProductTaskRequest.task_id` is the accepted product-task identity;
- the complete immutable request is server-side business input authority;
- `WallThicknessProductFlow.submit()` persists the request before workflow start;
- same `task_id` + same request is replay-safe at the request owner, while same `task_id` + different request fails closed;
- Revit semantic/context capture validates exact document/runtime evidence before using it;
- workflow / Saga owners remain authoritative for mutation and recovery outcome;
- workflow checkpoints already expose stable pending-human-interaction identity through `pending_interaction.pause_id`, `subject_ref`, and `allowed_resume_kinds`.

This phase closes three connected gaps:

1. **reliable submission** — where one logical client submission first receives a stable identity before an Agent/tool call can be replayed, and how that correlation freezes exactly one complete ProductTask request;
2. **session resolution** — how a `session_ref` resolves, after client or composition rebuild, to the same exact Revit project/Host/document binding or fails closed;
3. **usable Product Front Door** — how one minimal reference client takes real natural-language input through Agent interpretation, invokes the Product Front Door over real MCP, surfaces HITL without letting the model manufacture human approval, queries/resumes the task, and returns the verified Revit outcome to the user.

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
9. expose a minimal Product Front Door behavior that maps to existing `submit`, `get`, and human `resume` ownership instead of creating a second product runtime;
10. expose a pending HITL interaction as stable owner-derived data and require an explicit human decision event before human resume;
11. keep exact task query available even when the bound Revit Host is unavailable, because querying authoritative task/Saga state is not Host execution;
12. define an honest local v1 trust boundary without claiming multi-user or remote authorization that does not exist;
13. provide one repository-owned minimal reference client suitable for repeatable acceptance rather than making a third-party Agent UI the capability owner;
14. require the final product acceptance to cross a real MCP transport and a real Revit Host from real natural-language input through HITL and independent verification;
15. avoid a generic Agent shell, generic `ProductIntentIngress`, new query platform, multi-Host execution scheduler, or new network service by default.

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
- automatic acceptance of a model-generated string as proof that a human approved an operation.

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
        │ thin submit / get / human-resume adapter
        ▼
existing ProductTask request owner
        │
        ▼
existing ProductFlow / Workflow / Saga
        │
        ├─ pending_interaction? ──► reference client renders HITL
        │                              │
        │                              ▼
        │                         explicit human decision
        │                              │
        │                              └─ deterministic controller
        │                                 invokes MCP human-resume
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

An arbitrary Agent or MCP tool call is not the logical-submission identity boundary. Model behavior MUST NOT be relied upon to remember or reuse a retry ID. Likewise, model behavior MUST NOT be treated as the human-approval boundary.

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

This admission rule MUST NOT be misapplied to read-only lookup of an already-existing task. `get(task_id)` reads authoritative ProductTask/workflow/Saga state and does not require the old Revit Host to be reachable. Fresh Host validation applies only when the operation will newly depend on live Host state or continue Host-bound work.

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

An unavailable old Host does **not** make an existing task unqueryable. The Product Front Door can still return its durable workflow/Saga projection. Only an operation that must access or continue against the old Host is blocked by Host unavailability or binding invalidity.

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

Required business-level acceptance wording is concrete:

> Concurrent submission of the same task does not create a second effective business lineage and does not duplicate Host mutation; after declared crash windows the original task remains queryable/recoverable.

This design intentionally does not label that guarantee “business effect exactly-once.”

## 12. Decision F — minimal Product Front Door MCP behavior

### 12.1 Thin adapter, not a second runtime

The Product Front Door is a thin MCP adapter over the existing product facade and owner contracts. Exact public tool names are intentionally left to implementation planning, but the v1 logical surface is frozen to three behaviors:

```text
submit complete frozen ProductTaskRequest
    -> WallThicknessProductFlow.submit(request)

get exact task_id
    -> WallThicknessProductFlow.get(task_id)

submit explicit human interaction result
    -> validate current pending interaction
    -> construct exact WorkflowResumeCommand
    -> WallThicknessProductFlow.resume(task_id, command)
```

The MCP adapter MUST NOT:

- interpret natural language;
- allocate `client_submission_ref`;
- decide `task_id` retry identity;
- infer or replace `session_ref`;
- own HITL/approval truth;
- duplicate workflow/Saga outcome state;
- perform broad task enumeration or “latest task” lookup.

The reference client/controller owns natural-language orchestration and reliable-delivery state. Existing server owners remain authoritative for business state.

### 12.2 Submit behavior

Submit receives the exact complete ProductTask request already frozen by the deterministic controller. The MCP adapter validates/decodes the wire request and delegates to the product facade. Same frozen request replay must retain the existing ProductTask idempotency behavior; the MCP layer does not create a new retry identity.

A submit result projects the existing `ProductFlowView` and enough framework-neutral checkpoint information for the caller to continue safely. It may expose stable locators/status such as:

- `task_id`;
- product status;
- workflow phase;
- current `pending_interaction` when present;
- `saga_id` or other already-public stable references when needed for presentation/debugging.

It MUST NOT copy private LangGraph state or create a second authoritative business object.

### 12.3 Query behavior

`get(task_id)` is an exact, read-only lookup. It MUST:

- map to the existing ProductFlow query surface;
- return not-found explicitly when the task does not exist;
- return current durable status/checkpoint projection when it does exist;
- expose current pending HITL identity when present;
- remain usable when Revit, the named pipe, the old `session_ref` target, or other Host-bound dependencies are unavailable;
- avoid fresh Host validation unless a later operation actually needs live Host access;
- never resume, retry, or resend a Host mutation as a side effect of query.

Task lookup is therefore separated from execution eligibility. A user can inspect a failed, completed, recovery-required, or Host-orphaned task without reconnecting Revit first.

### 12.4 Human interaction result / resume behavior

The existing workflow checkpoint is the source of truth for whether a human decision is currently pending. The Product Front Door does not accept a free-form “approved=true” claim.

For a human resume the adapter/controller must first use the exact current `pending_interaction` and enforce:

- exact `task_id`;
- exact current `pause_id`;
- a decision mapped only to one of `allowed_resume_kinds`;
- the current workflow contract’s payload restriction (the existing operation-proposal pause accepts no arbitrary resume payload);
- stale `pause_id`, mismatched action, missing pause, or replay after consumption fails closed.

The final server call constructs the existing `WorkflowResumeCommand`; it does not invent a new approval owner.

Most importantly, the **model is not the human-decision authority**. In the v1 reference path, the model-callable interpretation surface MUST NOT include the controller-only human-resume action. The reference client renders the owner-derived pending interaction to the user; only an explicit local human action causes the deterministic controller to invoke the MCP resume behavior.

This separation is a reference-path enforcement rule, not a claim that MCP itself supplies universal human identity or enterprise authorization.

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
7. render returned status and owner-derived pending HITL;
8. capture an explicit human accept/reject action outside the model and invoke the MCP human-resume behavior directly from the deterministic controller;
9. query the same `task_id` until an authoritative terminal/recovery state is available;
10. present that result to the user without inventing success.

The Agent/model output is a proposal to the deterministic controller, not a durable ProductTask and not a human approval.

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
- the design does not claim isolation from every other local process/user on the same machine;
- any future remote access or multi-user deployment requires an explicit authentication/authorization design rather than extending this trust assumption silently.

Within this v1 trust boundary, the reference client may query/resume tasks that it knows by exact `task_id`. Resume still requires the exact current pending-interaction contract and explicit human event described above.

### 13.4 Mandatory end-to-end product acceptance

The capability is not complete merely because correlation storage, SessionBinding, MCP tool delegation, or direct facade tests pass independently.

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
owner-derived pending HITL
        │
        ▼
reference client shows human the pending decision
        │
        ▼
explicit human accept/reject event
        │
        ▼
deterministic controller invokes Product Front Door human-resume over MCP
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

Because a real Agent/model and real Revit are external live dependencies, this gate may be a controlled/manual live acceptance rather than a canonical offline CI job. The runbook MUST record enough evidence to show the natural-language input, actual MCP path, task identity, pending HITL identity/human action, Revit execution, independent verification, and final authoritative product result. Deterministic offline fixtures do not substitute for this live gate.

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

### 14.2 Server first-submit gate

9. Concurrent first `submit()` of the same `task_id` and same body produces one authoritative ProductTask/business lineage and no duplicate Host mutation.
10. Same `task_id` with different request body fails conflict and never overwrites the original request.
11. Declared server/process crash windows preserve query/recovery of the original task. `OUTCOME_UNKNOWN` / `RECOVERY_REQUIRED` are legal; unknown outcome never authorizes blind mutation resend.

### 14.3 Session binding and lifecycle

12. Client/application composition restart resolves the same `session_ref` to the exact same immutable binding body or fails.
13. Attempting to rewrite an existing `session_ref` to another project/Host/document binding is rejected.
14. Reusing the same endpoint while fresh Host runtime identity differs is rejected for Host-bound work; new binding is required for new work.
15. Active-document switch causes Host-bound start/resume validation failure; no automatic document switch occurs.
16. Unsaved title-only documents are rejected for durable v1 binding.
17. Close/reopen handling asserts only what current identity surfaces can prove; same-path same-process reopen is not claimed to be automatically detectable and is outside the continuous-open v1 guarantee.
18. If the target changes between candidate observation and binding issuance / first Host-bound use, fresh identity validation rejects the stale target.
19. An unavailable/restarted old Host does not prevent `get(task_id)` from returning the durable state of an existing task.

### 14.4 Candidate/discovery boundary

20. The v1 configured-candidate path reuses existing native read-only context identity capability where compatible; a new Revit command is not introduced merely to create SessionBinding.
21. Any later dynamic discovery contract exposes reachable instances’ current active documents only; it does not imply all-open-document enumeration or multi-Host execution.
22. Configured endpoint/path constraints are candidate inputs, not identity proof; live runtime/document evidence must still match for Host-bound work.
23. Durable client delivery and session-resolution state survives the declared same-workstation client-process restart scope.

### 14.5 MCP tool behavior and HITL

24. A real MCP client can negotiate/list the Product Front Door surface and invoke submit/get/human-resume behavior through the MCP adapter; direct facade invocation is covered separately and cannot satisfy this gate.
25. Submit receives an already-frozen complete request and does not allocate retry identity or reinterpret natural language.
26. Exact `get(task_id)` is read-only, returns the owner-derived projection, and performs no Host mutation/resume side effect.
27. When `pending_interaction` exists, MCP output preserves the exact owner-derived `pause_id`, subject reference, and allowed resume kinds needed by the client to render the HITL state.
28. Human resume with stale/missing `pause_id`, disallowed resume kind, or arbitrary payload fails closed according to the existing workflow contract.
29. The reference Agent/model is not given authority to invoke the controller-only human-resume action; an explicit human event is required before the deterministic controller sends that MCP resume call.
30. Query of a terminal, failed, or recovery-required task remains available while Revit is offline.
31. Product Front Door is local-only under the v1 trust boundary and exposes no broad task enumeration surface.

### 14.6 Complete live product acceptance

32. A real natural-language request enters the repository-owned reference client and crosses a real Agent/model interpretation boundary rather than being replaced by a prebuilt ProductTask fixture.
33. The resulting supported intent is frozen under one `client_submission_ref`, sent through a real MCP client/transport, and accepted as one authoritative ProductTask.
34. The same live task reaches owner-derived HITL; the reference client renders it and records an explicit human accept/reject event before resume.
35. Positive acceptance resumes through real MCP, performs the real Revit wall-thickness mutation, and obtains independent verification/reconciliation evidence.
36. The reference client queries the same `task_id` through MCP and presents the authoritative final result to the user.
37. The live evidence/runbook records enough lineage to prove that natural-language input, MCP task identity, HITL identity, human decision, Host mutation, verification, and final outcome belong to the same task.

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

### 15.10 Let the model submit human approval

Rejected. Existing workflow pause identity already gives the deterministic client an exact `pause_id` and allowed resume kinds. Human approval remains an explicit client-side human event that the controller maps into the existing resume contract; model text is not approval evidence.

## 16. Final v1 architecture decision

The selected v1 is **A + narrow session resolver + thin Product Front Door MCP + minimal reference client**, with no generalized ingress layer:

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
  + explicit human-event handling

Session binding authority/resolver
  uses configured DSP project/candidate context
  + fresh native Revit identity evidence
  -> issues opaque create-once session_ref only for the winning freeze path
  -> resolves exact immutable binding after rebuild
  -> does not require a new service by design

Product Front Door MCP
  thin real-MCP adapter
  -> submit exact frozen request
  -> get exact task without requiring Host availability
  -> transfer explicit human resume after exact pending-interaction validation
  -> does not interpret natural language or own approval

Existing ProductTask / ProductFlow / Workflow / Saga owners
  remain authoritative for business lineage, HITL navigation,
  execution, recovery, and outcome

Real Revit Host + independent verification
  remain authoritative for actual Host effect/evidence
```

The implementation plan may choose concrete storage, adapter/tool names, model provider, reference-client executable shape, and record types only after repository census. It may not weaken the atomic-freeze invariant, compare duplicate callbacks on independently generated IDs, substitute endpoint equality for Host identity, rebind an existing `session_ref`, require a live Host merely to query an existing task, expose model-generated text as human approval, replace the mandatory real-MCP acceptance with direct facade calls, expand document support beyond the declared v1 boundary, or claim concurrent first-submit correctness without proving the gate.
