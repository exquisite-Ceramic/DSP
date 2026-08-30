from dataclasses import fields

import design_approval_scope as approval_scope


def test_scope_definition_retains_intent_boundary_witness():
    names = {field.name for field in fields(approval_scope.ApprovalScopeDefinition)}
    assert "intent_boundary" in names


def test_final_boundary_retains_scope_commitment_witness():
    names = {field.name for field in fields(approval_scope.ApprovalScopeBoundary)}
    assert {
        "scope_definition_id",
        "impact_analysis_fingerprint",
        "canonical_effect_evidence",
        "intent_boundary",
        "planning_snapshot_ref",
        "snapshot_set_ref",
        "semantic_environment_ref",
    }.issubset(names)


def test_step28_exports_public_boundary_integrity_validator():
    assert hasattr(approval_scope, "validate_approval_scope_boundary")
