"""Step29 对 Step28 V1/V2 定义的兼容入口。"""

from __future__ import annotations

from dataclasses import replace

from design_approval_scope import (
    ApprovalScopeDefinition,
    ApprovalScopeDefinitionV2,
    validate_approval_scope_definition_v2,
)

from .builder import ChangeSetBuilder as _V1ChangeSetBuilder
from .contracts import CanonicalChangeSet, ChangeSetBuildRequest


def _v2_scope_view(scope: ApprovalScopeDefinitionV2) -> ApprovalScopeDefinition:
    """创建仅供既有 Step29 构建算法读取的内部语义视图。"""
    validate_approval_scope_definition_v2(scope)
    return ApprovalScopeDefinition(
        scope_definition_id=scope.scope_definition_id,
        impact_analysis_fingerprint=scope.impact_analysis_fingerprint,
        canonical_effect_evidence=scope.canonical_effect_evidence,
        intent_boundary=scope.intent_boundary,
        planning_snapshot_ref=scope.planning_snapshot_ref,
        snapshot_set_ref=scope.snapshot_set_ref,
        semantic_environment_ref=scope.semantic_environment_ref,
        existing_entity_rules=scope.existing_entity_rules,
        creation_rules=scope.creation_rules,
        deletion_rules=scope.deletion_rules,
        propagation_bundle_ids=scope.propagation_bundle_ids,
        execution_slice_scope_rules=scope.execution_slice_scope_rules,
        scope_body_hash=scope.scope_body_hash,
    )


class ChangeSetBuilder:
    """复用既有 Step29 哈希流水线，并允许完整性已验证的 V2 scope。"""

    def __init__(self) -> None:
        self._delegate = _V1ChangeSetBuilder()

    def build(self, request: ChangeSetBuildRequest) -> CanonicalChangeSet:
        if isinstance(request, ChangeSetBuildRequest) and isinstance(
            request.approval_scope_definition,
            ApprovalScopeDefinitionV2,
        ):
            request = replace(
                request,
                approval_scope_definition=_v2_scope_view(
                    request.approval_scope_definition
                ),
            )
        return self._delegate.build(request)


__all__ = ["ChangeSetBuilder"]
