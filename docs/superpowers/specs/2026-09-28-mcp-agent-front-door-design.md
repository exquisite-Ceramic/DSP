# MCP/Agent Front Door: Reliable Submission and Session Resolution Design

Status: DESIGN-REVIEW  
Date: 2026-09-28  
Baseline: `architecture/mcp-agent-front-door` @ `b79e0f051bd3952cb533e288d191a1f332a92451`

## 1. Scope and context

This design extends the existing Revit wall-thickness product vertical upstream to an MCP/Agent front door. It does not replace the existing `ProductTaskRequest`, `WallThicknessProductFlow`, workflow runtime, canonical owner composition, Execution Saga, reconciliation, or Host verification ownership.

The existing product vertical already establishes these downstream facts:

- `ProductTaskRequest.task_id` is the accepted product-task identity;
- the complete immutable request is server-side business input authority;
- `WallThicknessProductFlow.submit()` persists the request before workflow start;
- same `task_id` + same request is replay-safe at the request owner, while same `task_id` + different request fails closed;
- Revit semantic/context capture validates exact document/runtime evidence before using it;
- workflow / Saga owners remain authoritative for mutation and recovery outcome.

This phase addresses two upstream gaps only:

1. where one logical client submission first receives a stable identity before an Agent/tool call can be replayed;
2. how a `session_ref` resolves, after client or composition rebuild, to the same exact Revit project/Host/document binding or fails closed.

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
9. support a narrow first Revit path without creating a generic Agent shell, generic `ProductIntentIngress`, new query platform, multi-Host execution scheduler, or new network service by default.

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
- a generalized `ProductIntentIngress` layer.

`OUTCOME_UNKNOWN` / `RECOVERY_REQUIRED` remain legal outcomes. Recovery does not imply automatic Host mutation resend.

## 4. Frozen responsibility chain

The reliable path begins before the Agent tool invocation:

```text
User logical submit event
        │
        ▼
Deterministic Submission Controller
        │ owns durable client_submission_ref
        ▼
Agent / LLM interpretation
        │ interpretation only
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
Product Front Door MCP
        │
        ▼
existing ProductTask request owner
        │
        ▼
existing ProductFlow / Workflow / Saga / Host verification
```

An arbitrary Agent or MCP tool call is not the logical-submission identity boundary. Model behavior MUST NOT be relied upon to remember or reuse a retry ID.

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

### 5.3 Replay semantics

After the atomic freeze succeeds:

- Agent/tool replay for the same `client_submission_ref` MUST return or resend the exact frozen request;
- natural language MUST NOT be reinterpreted to rebuild the request;
- the request body, `task_id`, `session_ref`, and hash MUST NOT be rewritten;
- a later callback proposing a different body for the same correlation MUST fail as a correlation conflict;
- content equality is never the retry key.

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

A ProductTask submission is admissible only when:

- `session_ref` resolves through the configured v1 binding authority;
- request `project_id` equals binding `project_id`;
- request `host_kind` equals binding `host_kind`;
- the binding is not invalid/unavailable under the declared v1 lifecycle rules;
- fresh Host validation proves the runtime/document target required by the binding before Host-bound workflow use.

Unknown, mismatched, substituted, or non-recoverable bindings fail closed. The front door does not silently create a replacement binding during task replay.

## 7. Decision C — v1 binding source: configured candidate + runtime issuance

A fully static exact binding is insufficient for the first Revit path because the exact Revit runtime identity is process-lifetime evidence and must be read from the live Host. A general dynamic candidate-enumeration platform is also unnecessary for v1.

Therefore the mandatory v1 path is:

1. deterministic application configuration supplies the DSP `project_id` and the intended Revit connection/candidate constraint;
2. a read-only Host identity probe obtains the current actual `host_instance_id` and current active-document identity;
3. the controller verifies that evidence against the configured candidate constraint;
4. only then does the binding authority issue an opaque `session_ref` and persist one immutable binding;
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

Revit/AgentHost restart invalidates use of the old process-lifetime binding. The old `session_ref` MUST NOT be updated to the new runtime identity.

The new runtime requires a new binding and new `session_ref` before new Host-bound work. Existing ProductTask records remain immutable and enter normal failure/recovery semantics according to workflow/Saga state.

### 10.3 Active document switch

If the active document no longer matches the bound document, fresh validation fails closed. v1 does not switch the active document automatically.

If the same still-running Host returns to the exact supported bound document and fresh validation again satisfies the binding, a later safe retry may proceed according to the existing workflow stage. This rule does not permit replay of an unknown Host mutation.

### 10.4 Document close/reopen

The v1 durable guarantee assumes the bound document remains continuously open for the lifetime of that binding.

Closing and reopening the document semantically requires a new binding. However, with the current path-based saved-document identity, the system may not be able to distinguish every “same path, same Host process, newly reopened document” case automatically. The Spec therefore does **not** claim automatic invalidation detection for that case.

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

## 12. Acceptance gates

### 12.1 Client correlation and request freeze

1. Crash after correlation creation but before freeze: no request was sent; replay can freeze at most one complete request.
2. Crash during freeze: restart observes either no frozen request or one complete frozen request; never a partial correlation/task/request association.
3. Concurrent completion for the same correlation and same body: exactly one `task_id`/request freezes; all replay uses it.
4. Concurrent completion for the same correlation with conflicting bodies: at most one freezes; the other path fails conflict; no second request is sent.
5. Product Front Door accepts a request but the response is lost: client replay sends the exact same task ID and full request.
6. Two distinct correlations with identical content create two distinct task IDs and remain separate intentional submissions.

### 12.2 Server first-submit gate

7. Concurrent first `submit()` of the same `task_id` and same body produces one authoritative ProductTask/business lineage and no duplicate Host mutation.
8. Same `task_id` with different request body fails conflict and never overwrites the original request.
9. Declared server/process crash windows preserve query/recovery of the original task. `OUTCOME_UNKNOWN` / `RECOVERY_REQUIRED` are legal; unknown outcome never authorizes blind mutation resend.

### 12.3 Session binding and lifecycle

10. Client/application composition restart resolves the same `session_ref` to the exact same immutable binding body or fails.
11. Attempting to rewrite an existing `session_ref` to another project/Host/document binding is rejected.
12. Reusing the same endpoint while fresh Host runtime identity differs is rejected; new binding is required.
13. Active-document switch causes Host-bound start/resume validation failure; no automatic document switch occurs.
14. Unsaved title-only documents are rejected for durable v1 binding.
15. Close/reopen handling asserts only what current identity surfaces can prove; same-path same-process reopen is not claimed to be automatically detectable and is outside the continuous-open v1 guarantee.
16. If the target changes between candidate observation and binding issuance / first Host-bound use, fresh identity validation rejects the stale target.

### 12.4 Candidate/discovery boundary

17. The v1 configured-candidate path reuses existing native read-only context identity capability where compatible; a new Revit command is not introduced merely to create SessionBinding.
18. Any later dynamic discovery contract exposes reachable instances’ current active documents only; it does not imply all-open-document enumeration or multi-Host execution.
19. Configured endpoint/path constraints are candidate inputs, not identity proof; live runtime/document evidence must still match.
20. Durable client delivery and session-resolution state survives the declared same-workstation, same-user client-process restart scope.

## 13. Rejected / deferred alternatives

### 13.1 Content equality as submission deduplication

Rejected. Two intentional submissions may contain identical content. Retry identity comes from `client_submission_ref`, not content.

### 13.2 Let the Agent/model reuse task identity

Rejected. The reliable boundary must be deterministic and recoverable independently of model behavior.

### 13.3 Mandatory content-addressed `session_ref`

Not selected. Content addressing is compatible with the immutable-binding contract but is not necessary to enforce it. v1 uses an opaque reference plus create-once immutable record.

### 13.4 Mandatory new Session Registry service/database

Rejected as an architectural requirement. A narrow resolver/authority is required logically; its physical backing must reuse durable configuration or an existing application persistence boundary when that satisfies v1. A new service requires separate evidence of need.

### 13.5 Pure static exact SessionBinding

Not sufficient for the first Revit path because exact process-lifetime Host identity must be captured from the live runtime. v1 instead uses a configured candidate plus runtime identity capture before binding issuance.

### 13.6 General dynamic Revit discovery platform in v1

Deferred. Existing native read-only capability is sufficient to validate the first configured candidate. A reusable enumeration contract may be added when real UX requires selecting among multiple reachable instances.

### 13.7 Generic `ProductIntentIngress`

Not justified. Current evidence supports deterministic submission state + narrow session resolution + thin MCP adapter over the existing ProductTask/ProductFlow boundary.

## 14. Final v1 architecture decision

The selected v1 is **A + narrow session resolver**, with no generalized ingress layer:

```text
Deterministic client controller
  owns client_submission_ref
  + atomic correlation/task/full-request freeze
  + durable outbox delivery state

Agent / MCP Host
  interprets / requests clarification
  but does not own retry identity

Session binding authority/resolver
  uses configured DSP project/candidate context
  + fresh native Revit identity evidence
  -> issues opaque create-once session_ref
  -> resolves exact immutable binding after rebuild
  -> does not require a new service by design

Product Front Door MCP
  admits only exact frozen ProductTask requests
  whose session binding resolves and matches project/host constraints

Existing ProductTask / ProductFlow / Workflow / Saga owners
  remain authoritative for business lineage, execution, and recovery
```

The implementation plan may choose concrete storage, adapter names, and record types only after repository census. It may not weaken the atomic-freeze invariant, substitute endpoint equality for Host identity, rebind an existing `session_ref`, expand document support beyond the declared v1 boundary, or claim concurrent first-submit correctness without proving the gate.
