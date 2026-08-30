# Step33 — Execution Reconciliation Design Refinements

> Status: Approved with the Step33 implementation plan; normative for implementation  
> Date: 2026-08-30  
> Base design: `docs/superpowers/specs/2026-08-30-step33-execution-reconciliation-design.md` at `d8493b0dee8389f1be76bc568526831ac3f94ef5`  
> Implementation plan: `docs/superpowers/plans/2026-08-30-step33-execution-reconciliation.md`  
> Main base: `cef76e111f74d10f063eedfebc7efc0d805caefa`

This addendum is normative together with the approved Step33 base design. It freezes four Step33-only executable contract refinements discovered while decomposing the implementation plan. It does not modify Step28, Step29, Step30, Step31, or Step32 existing contract/hash identity. If wording in the base design is narrower than this addendum on these four points, this addendum governs Step33 implementation.

## 1. Creation source canonical-kind evidence

`ActualChange` adds:

```text
source_canonical_kind?
```

Step33 evaluates a Step28 `CreationRule.source_selector` only from provider-neutral ActualChange evidence:

```text
PredicateField.SEMANTIC_ID      -> ActualChange.source_semantic_id
PredicateField.CANONICAL_KIND   -> ActualChange.source_canonical_kind
PredicateField.SOURCE_ENTITY    -> ActualChange.source_semantic_id
PredicateField.DERIVATION_RULE  -> ActualChange.derivation_rule
```

Missing evidence makes that predicate non-matching. Step33 MUST NOT backfill source selector evidence from Host-native type/category/layer metadata or by querying D5 internals.

## 2. Baseline evidence for DELTA_EQUALS_ARGUMENT

`VerificationEvidenceBundle` adds:

```text
baseline_snapshot_ref?
baseline_projection_ref?
baseline_subject_evidence[]
```

`VerificationSubjectEvidence` adds:

```text
snapshot_id
snapshot_hash
```

When any requested executable verification assertion uses `DELTA_EQUALS_ARGUMENT`:

```text
baseline snapshot/evidence required
→ baseline snapshot identity == CanonicalChangeSet.planning_snapshot_ref
→ baseline and post evidence share the exact SemanticEnvironment
→ required baseline subject/path must be present
otherwise EVIDENCE_INSUFFICIENT / REQUIRED_BASELINE_MISSING
```

The evidence-bundle hash includes baseline snapshot/projection references and baseline subject evidence when present. Step33 performs no unit conversion; canonical operation arguments and semantic evidence must already use canonical semantic units. If a tolerance unit is supplied, explicit observed/expected units must agree or evidence is insufficient.

## 3. SemanticVerifier exact joins

`SemanticVerificationRequest` is refined to include:

```text
SemanticVerificationRequest {
  admitted_execution_authority
  approval_scope_boundary
  canonical_changeset
  actual_delta
  validation_tasks[]
  verification_evidence_bundle
  verified_at
}
```

Rationale:

- Step33 must call the public Step29 `validate_changeset_integrity(changeset, boundary)` rather than reimplementing ChangeSet integrity.
- Post-execution revision verification must join to the authoritative ActualDelta, not merely a caller-supplied delta hash.
- Boundary, ChangeSet, authority, ActualDelta, Slice, evidence bundle, and SemanticEnvironment must join exactly before assertion evaluation.

## 4. Complete ValidationTask-to-Slice assignment

Step29 `ValidationTask`s are ChangeSet-scoped while Step30 has no task-to-Slice field. Step33 therefore derives immutable task ownership during Saga definition construction:

```text
SliceValidationAssignment {
  execution_slice_hash
  validation_task_ids[]
}

ExecutionSagaDefinition {
  ...
  slice_validation_assignments[]
  saga_definition_hash
}
```

Assignment is deterministic and complete:

```text
CANONICAL_OPERATION task
→ resolve exactly one ChangeSet operation by
  canonical_operation_ref + exact subject_semantic_ids
→ assign to the Slice containing that operation's ExecutionUnit

DEPENDENCY_VERIFICATION task
→ resolve exactly one SemanticImpactEvidence by
  dependency_ref + affected subject
→ if affected semantic id is the target of exactly one ChangeSet operation,
  assign to that operation's Slice
→ otherwise assign to the Slice containing the source_semantic_id operation
→ ambiguous or unresolved assignment = SAGA_INTEGRITY_INVALID
```

Every ChangeSet ValidationTask MUST be assigned exactly once. `slice_validation_assignments` are included in `saga_definition_hash` with canonical sorting.

A Slice may enter `SUCCEEDED` only after:

```text
persisted ScopeComparisonResult == WITHIN_SCOPE
+
persisted SemanticVerificationResult covers exactly every ValidationTask
assigned to that Slice by the Saga definition
+
verification aggregate == PASSED
```

Caller omission of an assigned task is invalid and cannot produce Slice success.

## Frozen boundary

These refinements remain provider-neutral and do not authorize any expansion of the Step33 implementation boundary. In particular they do not permit changes to Step28/29/31/32 production code, Host/provider implementations, D5 storage internals, or any existing upstream semantic hash algorithm.
