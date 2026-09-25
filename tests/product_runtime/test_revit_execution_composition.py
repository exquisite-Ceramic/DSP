"""Task 6 RED：Revit execution composition 必须把 authoritative planning revision 冻结进 binding hash。"""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import design_product_runtime
import pytest
from design_provider_binding import (
    EligibilityState,
    NativeConstraint,
    NativeConstraintOperator,
    NativeTargetBindingEvidence,
    ProviderBindingMaterial,
    ProviderExecutionCandidate,
    ProviderExecutionSnapshotV2,
    compute_candidate_fingerprint,
    compute_host_binding_fingerprint,
    compute_provider_snapshot_hash_v2,
    resolve_provider_bindings_v2,
)
from semantic_runtime import SnapshotKind

from tests.execution_planning._support import build_phase_i_execution_inputs


class _ChangeSetStore:
    """只暴露 exact ChangeSet lookup；测试不复制 ChangeSet owner 规则。"""

    def __init__(self, changeset) -> None:
        self._changeset = changeset
        self.lookups: list[str] = []

    def get(self, changeset_id: str):
        self.lookups.append(changeset_id)
        assert changeset_id == self._changeset.changeset_id
        return self._changeset


class _SnapshotRegistry:
    """模拟 Semantic Runtime exact refs，允许只改变 authoritative planning revision。"""

    def __init__(self, changeset, *, document_ref: str, revision: str) -> None:
        self._changeset = changeset
        self._document_ref = document_ref
        self._revision = revision
        self.snapshot_set_lookups: list[str] = []
        self.snapshot_lookups: list[str] = []

    def get_snapshot_set(self, snapshot_set_id: str):
        self.snapshot_set_lookups.append(snapshot_set_id)
        ref = self._changeset.snapshot_set_ref
        assert snapshot_set_id == ref.snapshot_set_id
        return SimpleNamespace(
            snapshot_set_id=ref.snapshot_set_id,
            hash=ref.snapshot_set_hash,
            member_snapshot_ids=tuple(ref.member_snapshot_ids),
            semantic_environment_ref=ref.semantic_environment_ref,
        )

    def get_snapshot(self, snapshot_id: str):
        self.snapshot_lookups.append(snapshot_id)
        planning = self._changeset.planning_snapshot_ref
        assert snapshot_id == planning.snapshot_id
        return SimpleNamespace(
            snapshot_id=planning.snapshot_id,
            hash=planning.snapshot_hash,
            kind=SnapshotKind.PLANNING,
            document_ref=self._document_ref,
            base_host_revision=self._revision,
            semantic_environment_ref=planning.semantic_environment_ref,
        )


def _revit_case():
    case, _, _, request = build_phase_i_execution_inputs()
    execution_plan = __import__(
        "design_execution_planning",
        fromlist=["plan_materialized_execution"],
    ).plan_materialized_execution(request)
    execution_slice = next(
        item
        for item in execution_plan.execution_slices
        if item.host_runtime_ref.host_type == "revit"
    )
    return case, execution_slice


def _base_provider_snapshot(execution_slice) -> ProviderExecutionSnapshotV2:
    """发布 environment-owned Revit provider/native evidence，但不携带 planning revision。"""

    unit = execution_slice.execution_units[0]
    target_draft = NativeTargetBindingEvidence(
        semantic_id=unit.targets[0],
        host_type="revit",
        document_ref=execution_slice.host_runtime_ref.document_ref,
        native_id="REVIT-UNIQUE-ID-001",
        native_kind="Wall",
        host_binding_fingerprint="0" * 64,
    )
    target = replace(
        target_draft,
        host_binding_fingerprint=compute_host_binding_fingerprint(target_draft),
    )
    candidate_draft = ProviderExecutionCandidate(
        provider_server="provider.revit.wall",
        provider_tool="revit.set_wall_thickness",
        provider_version="1.0.0",
        canonical_operation=unit.canonical_operation,
        compatible_operation_versions=(unit.canonical_operation_version,),
        input_adapter_version="1.0.0",
        provider_native_constraints=(
            NativeConstraint(
                "native_kind",
                NativeConstraintOperator.EQ,
                ("Wall",),
            ),
        ),
        provider_input_schema={
            "type": "object",
            "properties": {
                "native_ids": {"type": "array", "items": {"type": "string"}},
                "canonical_arguments": {"type": "object"},
            },
            "required": ["native_ids", "canonical_arguments"],
            "additionalProperties": False,
        },
        verification_contract={"read_back": "required"},
        rollback_contract={"mode": "compensating_changeset"},
        trust_state=EligibilityState.SATISFIED,
        compatibility_state=EligibilityState.SATISFIED,
        health_state=EligibilityState.SATISFIED,
        license_state=EligibilityState.SATISFIED,
        certification_state=EligibilityState.SATISFIED,
        policy_priority=10,
        candidate_fingerprint="0" * 64,
    )
    candidate = replace(
        candidate_draft,
        candidate_fingerprint=compute_candidate_fingerprint(candidate_draft),
    )
    material = ProviderBindingMaterial(
        native_targets=(target,),
        provider_arguments={
            "native_ids": [target.native_id],
            "canonical_arguments": dict(unit.arguments),
        },
        provider_preconditions=(),
        native_binding_metadata={"identity_source": "persistent_host_binding"},
    )
    draft = ProviderExecutionSnapshotV2(
        snapshot_id="PESV2-REVIT-PRODUCT",
        materialization_id=execution_slice.materialization_id,
        materialization_plan_hash=execution_slice.materialization_plan_hash,
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        host_runtime_ref=execution_slice.host_runtime_ref,
        native_target_bindings=(target,),
        provider_candidates=(candidate,),
        candidate_binding_materials={candidate.candidate_fingerprint: material},
        valid_until="2026-09-25T23:00:00Z",
        snapshot_hash="0" * 64,
    )
    return replace(draft, snapshot_hash=compute_provider_snapshot_hash_v2(draft))


def _boundary_type():
    boundary = getattr(
        design_product_runtime,
        "RevitWallThicknessProviderExecutionSnapshotBoundary",
        None,
    )
    assert boundary is not None, (
        "RevitWallThicknessProviderExecutionSnapshotBoundary is not implemented"
    )
    return boundary


def _bound_snapshot(*, revision: str):
    case, execution_slice = _revit_case()
    registry = _SnapshotRegistry(
        case.changeset,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision=revision,
    )
    boundary = _boundary_type()(
        changeset_store=_ChangeSetStore(case.changeset),
        snapshot_registry=registry,
        provider_snapshot_factory=_base_provider_snapshot,
    )
    return execution_slice, boundary(execution_slice)


def test_planning_revision_is_frozen_into_hash_bound_provider_metadata() -> None:
    """PlanningSnapshot base revision 必须进入 material、snapshot 和最终 binding hash。"""

    execution_slice, snapshot = _bound_snapshot(revision="31")

    assert snapshot.provider_candidates[0].provider_tool == "revit.set_wall_thickness"
    material = next(iter(snapshot.candidate_binding_materials.values()))
    assert material.native_binding_metadata == {
        "identity_source": "persistent_host_binding",
        "expected_revision": 31,
    }

    binding_set = resolve_provider_bindings_v2(execution_slice, snapshot)
    assert binding_set.bindings[0].native_binding_metadata["expected_revision"] == 31


def test_changing_only_expected_revision_changes_snapshot_and_binding_hashes() -> None:
    """expected revision 是 binding authority，不允许是 execution-time 临时参数。"""

    execution_slice_31, snapshot_31 = _bound_snapshot(revision="31")
    execution_slice_32, snapshot_32 = _bound_snapshot(revision="32")
    assert execution_slice_31 == execution_slice_32

    binding_31 = resolve_provider_bindings_v2(execution_slice_31, snapshot_31)
    binding_32 = resolve_provider_bindings_v2(execution_slice_32, snapshot_32)

    assert snapshot_31.snapshot_hash != snapshot_32.snapshot_hash
    assert binding_31.binding_set_hash != binding_32.binding_set_hash
    assert binding_31.bindings[0].binding_hash != binding_32.bindings[0].binding_hash


@pytest.mark.parametrize("revision", ("-1", "031", "not-a-revision"))
def test_noncanonical_planning_revision_fails_closed_before_binding(revision: str) -> None:
    """只有 canonical non-negative planning revision 可进入 provider binding authority。"""

    with pytest.raises(ValueError, match="revision"):
        _bound_snapshot(revision=revision)
