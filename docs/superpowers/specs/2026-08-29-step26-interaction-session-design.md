# Step 26 — InteractionSession / Host-native Interaction Design

**Status:** Approved design  
**Date:** 2026-08-29  
**Base:** `main` after PR #18 / Step25  
**Master spec:** `docs/spec/Enterprise_Collaborative_Design_Agent_Spec_v0.6.md`

## 1. Purpose

Step26 completes Phase F by adding explicit, resumable Host-native interaction for canonical action parameters that cannot be materialized from ordinary D6 deterministic sources.

The frozen flow is:

```text
ContextSnapshot
  ↓
D4 ResolvedOperation
  ↓
LLM OperationProposal                  # canonical operation + INTENT only
  ↓
D6 interactive resolution
  ├─ deterministic Step25 binding succeeds
  │      ↓
  │   BoundOperationProposal
  │
  └─ required interactive INTENT slot missing
         ↓
      InteractionRequired
         ↓
      Interaction Coordinator
         ↓
      InteractionSession(PENDING)
         ↓
      AsyncOperationRef(INTERACTION_SESSION)
         ↓
      Host interaction provider
         ↓
      Host Canvas
         ↓
      InteractionSession(COMPLETED)
         ↓
      D6 resume
         ↓
      BoundOperationProposal
         ↓
      Phase-B Operation Freshness
```

Step26 does not introduce model mutation, ChangeSet, approval, ExecutionUnit, ProviderBinding, or ExecutionGrant.

## 2. Architectural boundary

### 2.1 Interaction is not a sixth SlotBindingClass

The canonical slot binding model remains exactly:

```text
INTENT
CONTEXT
CANONICAL_DEFAULT
DERIVED
PROVIDER
```

`INTERACTION` is a value-acquisition process, not a new canonical ownership class.

Step26 v1 permits Host interaction only as a fallback for a missing **required INTENT slot** that has an explicit interaction recipe. This keeps the canonical contract stable and avoids turning Host UI mechanics into semantic ownership metadata.

### 2.2 Long-lived state owner

`InteractionSession` state is owned only by the **Interaction Coordinator**.

D6/LangGraph may start, inspect, cancel, and consume interaction results, but MUST NOT keep hidden authoritative Host prompt state.

### 2.3 Host boundary

Host-specific APIs such as AutoCAD `Editor.GetPoint`, Revit selection APIs, native identifiers, and internal coordinate objects stay behind Host adapters/providers.

The Coordinator and D6 only exchange structured, schema-valid canonical results.

## 3. Interaction types

The Step26 contract freezes the initial vocabulary:

```text
SELECT_ENTITIES
PICK_POINT
PICK_DIRECTION
INPUT_NUMBER
CONFIRM
CANCEL
```

Only `PICK_POINT` is required to be connected end-to-end in Step26 v1. The remaining interaction types are contract-visible for later provider implementations.

## 4. InteractionSession contract

```text
InteractionSession {
  interaction_id
  task_id
  host_instance_id
  document_id
  interaction_type
  input_constraints
  result_schema
  state: PENDING | COMPLETED | CANCELLED | EXPIRED
  result?
  created_at
  expires_at
}
```

Rules:

1. All identity fields are required and non-empty.
2. `created_at` and `expires_at` are absolute UTC timestamps.
3. `expires_at > created_at`.
4. `PENDING` has no result.
5. `COMPLETED` requires a result that validates against `result_schema`.
6. `CANCELLED` and `EXPIRED` have no result.
7. Terminal states are immutable.
8. Expiration is evaluated by the Coordinator before get/complete/cancel/start admission decisions.

## 5. Interaction start request

The Coordinator consumes an explicit request:

```text
InteractionStartRequest {
  task_id
  host_instance_id
  document_id
  interaction_type
  input_constraints
  result_schema
  idempotency_key
  created_at
  expires_at
}
```

`interaction.start` is side-effecting because it can display a Host prompt. Therefore `idempotency_key` is mandatory.

The request fingerprint is a canonical hash over all logical request fields except transport-attempt identifiers. Same key + same fingerprint returns the same session. Same key + different fingerprint fails closed with `IDEMPOTENCY_CONFLICT`.

## 6. Coordinator API and state machine

The v1 service boundary is:

```text
InteractionCoordinator.start(request) -> InteractionSession
InteractionCoordinator.get(interaction_id, now) -> InteractionSession
InteractionCoordinator.cancel(interaction_id, now) -> InteractionSession
InteractionCoordinator.complete_from_provider(interaction_id, result, now) -> InteractionSession
InteractionCoordinator.async_ref(interaction_id) -> AsyncOperationRef
```

State machine:

```text
              ┌→ COMPLETED
PENDING ──────┼→ CANCELLED
              └→ EXPIRED
```

No transition is allowed out of a terminal state.

### 6.1 Host/document exclusivity

Step26 v1 allows at most one `PENDING` session for a given:

```text
host_instance_id + document_id
```

A second distinct logical interaction fails with `INTERACTION_BUSY`.

This avoids competing modal Host Canvas prompts and is intentionally stricter than a general multi-session UI framework.

## 7. AsyncOperationRef

Step26 reuses the existing common contract:

```text
AsyncOperationRef {
  type = INTERACTION_SESSION
  id = interaction_id
}
```

No second async-handle type is introduced.

LangGraph/checkpoint code is expected to persist only the typed handle and task state, not hidden server prompt objects.

## 8. D6 interactive resolution

Step25 `ParameterBinder.bind()` remains the strict deterministic binder and keeps failing when a required INTENT slot is missing.

Step26 adds a thin orchestration layer around it rather than weakening Step25 semantics.

### 8.1 Interaction recipe

```text
SlotInteractionRecipe {
  slot
  interaction_type
  input_constraints
  result_schema
}

OperationInteractionRecipe {
  canonical_operation
  slots[]
}
```

Rules:

1. A Step26 interaction recipe may reference only a canonical slot that exists.
2. v1 interactive recipes may target only `INTENT` slots.
3. The slot must be required by the canonical input schema.
4. `result_schema` must be structurally compatible with the canonical slot schema; the final value is always revalidated through the full canonical operation input schema by the Step25 binder.
5. A recipe must never target a `PROVIDER` slot.

### 8.2 Resolve result

The interactive D6 resolver returns one of:

```text
BoundOperationProposal
```

or:

```text
InteractionRequired {
  canonical_operation
  slot
  interaction_type
  input_constraints
  result_schema
  context_snapshot_ref
}
```

v1 resolves at most one missing interactive slot at a time, using canonical input-schema order. After the resulting session completes, the caller invokes resolution again with the completed session supplied for that slot.

### 8.3 Resume validation

Before using a completed session result, D6 MUST verify:

```text
session.state == COMPLETED
session.task_id matches current task binding context
session.host_instance_id matches requested Host
session.document_id matches requested document
session.interaction_type matches recipe
session.result validates result_schema
```

The canonical value is then added to INTENT arguments and passed through the unchanged Step25 `ParameterBinder`.

### 8.4 Binding evidence

If a slot value came from Host interaction, the final evidence must be:

```text
SlotBindingEvidence {
  slot = <slot>
  binding_class = INTENT
  source = "InteractionSession"
  source_ref = <interaction_id>
}
```

This replaces the default `OperationProposal.intent_arguments` evidence only for the interaction-supplied slot.

## 9. Provider-neutral result requirement

`InteractionSession.result` contains canonical structured data only.

For `PICK_POINT`, Step26 freezes this result schema:

```json
{
  "type": "array",
  "items": {"type": "number"},
  "minItems": 3,
  "maxItems": 3
}
```

D6 therefore receives a value such as:

```text
[1000.0, 2000.0, 0.0]
```

It MUST NOT receive AutoCAD `Point3d`, Revit XYZ objects, ObjectId, Handle, ElementId, or provider tool metadata.

## 10. AutoCAD PICK_POINT vertical

Step26 v1 adds one Host provider surface:

```text
interaction.pick_point
category = INTERACTION
```

The intended chain is:

```text
Interaction Coordinator / caller
  ↓
AutoCAD Sidecar interaction.pick_point
  ↓
HostCommand {
  mode = INTERACTION
  operation = interaction.pick_point
  idempotency_key = stable logical interaction key
}
  ↓
AutoCAD AgentHost PickPoint handler
  ↓
Editor.GetPoint(...)
  ↓
structured [x, y, z]
  ↓
Coordinator.complete_from_provider(...)
```

The Host side may use native point/coordinate types internally, but must serialize only the canonical numeric vector result.

## 11. Idempotency

`interaction.start` and the Host prompt command share the same logical idempotency key.

Required behavior:

```text
attempt 1: request_id=A, idempotency_key=K → IS-001 / one Host prompt
network retry
attempt 2: request_id=B, idempotency_key=K → IS-001 / no second Host prompt
```

The Coordinator owns logical session idempotency. The AutoCAD sidecar/Host path must also avoid duplicate prompt dispatch for repeated calls with the same key.

## 12. Cancellation and expiration

Cancellation is explicit and non-mutating to the design model.

```text
PENDING → CANCELLED
```

Expiration is deterministic when `now >= expires_at`:

```text
PENDING → EXPIRED
```

Completing or cancelling an expired/terminal session fails closed.

Host-user cancellation of `PICK_POINT` must be mapped to a cancelled interaction outcome rather than a fake coordinate value.

## 13. Failure codes

Step26 freezes these coordinator/domain failures:

```text
INTERACTION_NOT_FOUND
INTERACTION_BUSY
IDEMPOTENCY_CONFLICT
INTERACTION_TERMINAL
INTERACTION_RESULT_INVALID
INTERACTION_CONTEXT_MISMATCH
```

Production code may represent these as typed exceptions internally, but their stable code strings must be inspectable for gateway/orchestrator mapping later.

## 14. Testing requirements

Step26 must prove:

1. legal session state construction;
2. terminal state immutability;
3. deterministic expiration;
4. same idempotency key + same request returns the same session;
5. same key + different request fails `IDEMPOTENCY_CONFLICT`;
6. second pending prompt on same Host/document fails `INTERACTION_BUSY`;
7. async ref type is `INTERACTION_SESSION`;
8. invalid provider result fails schema validation;
9. D6 missing interactive required INTENT returns `InteractionRequired`;
10. completed interaction resumes D6 and emits `InteractionSession` evidence;
11. wrong task/host/document/session type is rejected;
12. `MOVE_V1` behavior remains unchanged and never requires interaction;
13. `PROVIDER` slots cannot acquire values through Step26;
14. interaction core imports no AutoCAD/Revit/Tekla package;
15. AutoCAD provider exposes `interaction.pick_point` as `INTERACTION`;
16. Host command uses `mode=INTERACTION` and stable idempotency key;
17. repeated prompt dispatch with the same key does not trigger a second native prompt;
18. existing Step23–25 regressions remain green.

## 15. File/module boundary

Preferred production ownership:

```text
platform/interaction/src/design_interaction/
  contracts.py        # InteractionSession/request/types/errors
  coordinator.py      # authoritative lifecycle + idempotency + exclusivity
  __init__.py

platform/orchestrator/src/design_orchestrator/
  interactive_binding.py   # D6 recipe / InteractionRequired / resume wrapper

hosts/autocad/sidecar/src/autocad_sidecar/
  adapter/interaction_adapter.py
  execution/command_dispatcher.py
  mcp_server.py

hosts/autocad/plugin/AutoCAD.AgentHost/Commands/Interaction/
  PickPointHandler.cs
```

The Step26 core modules must not import Host product packages.

## 16. Explicit non-goals

Step26 does not implement:

```text
Impact / Dependency / Constraint             # Step27
ApprovalScopeBoundary                        # Step28
immutable ChangeSet                          # Step29
canonical ExecutionUnit                      # Step30
ProviderBinding / binding_set_hash           # Step31
ExecutionGrant
model mutation
cross-Host interaction federation
multi-step wizard/form engine
parallel prompts in one Host document
provider-native identity binding
```

## 17. Phase F completion

After Step26 the Action/Interaction phase is:

```text
Step23  Canonical Action Contract
  ↓
Step24  Canonical Semantic Eligibility
  ↓
Step25  Deterministic D6 Slot Binding
  ↓
Step26  Explicit Host-native Interaction / resume
```

Only after this boundary is stable should the roadmap enter Step27 Dependency / Constraint / Impact contracts.
