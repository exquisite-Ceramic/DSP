"""Step29 针对 Step28 V2 审批边界的完整性重建。"""

from __future__ import annotations

from design_approval_scope import (
    ApprovalScopeBoundaryV2,
    validate_approval_scope_boundary_v2,
)

from .contracts import CanonicalChangeSet
from .integrity import _validate_changeset_integrity_body


def validate_changeset_integrity_v2(
    changeset: CanonicalChangeSet,
    approval_scope_boundary: ApprovalScopeBoundaryV2,
) -> None:
    """先验证 Step28 V2 owner 边界，再复用原 Step29 语义重建算法。"""
    if not isinstance(changeset, CanonicalChangeSet):
        raise TypeError("changeset must be CanonicalChangeSet")
    if not isinstance(approval_scope_boundary, ApprovalScopeBoundaryV2):
        raise TypeError("approval_scope_boundary must be ApprovalScopeBoundaryV2")

    validate_approval_scope_boundary_v2(approval_scope_boundary)
    _validate_changeset_integrity_body(changeset, approval_scope_boundary)


__all__ = ["validate_changeset_integrity_v2"]
