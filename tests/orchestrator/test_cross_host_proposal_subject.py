"""Cross-Host Product Vertical Task 4：immutable human proposal subject 契约。"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest
from design_orchestrator.interaction_artifacts import (
    CrossHostOperationProposalSubjectV2,
    CrossHostProposalObservationV2,
)
from design_orchestrator.workflow_artifacts import (
    WORKFLOW_ARTIFACT_CODEC_VERSION,
    decode_workflow_artifact,
    encode_workflow_artifact,
    workflow_artifact_content_hash,
)


def _observation(
    host_kind: str,
    *,
    revision: int | None = None,
    thickness_mm: float = 200.0,
    observed_at: str | None = None,
    command_id: str | None = None,
) -> CrossHostProposalObservationV2:
    """构造用户实际看到的一条 Host observation；provenance 与稳定状态字段分开。"""

    if host_kind == "REVIT":
        return CrossHostProposalObservationV2(
            host_kind="REVIT",
            host_instance_id="revit-runtime-7",
            document_id=r"C:\DSP\fixtures\cross-host.rvt",
            native_target_id="revit-wall-001",
            semantic_target_id="WALL-001",
            host_revision=41 if revision is None else revision,
            normalized_thickness_mm=thickness_mm,
            observed_at=observed_at or "2026-10-02T04:00:00Z",
            command_id=command_id or "proposal-read-revit-1",
        )
    return CrossHostProposalObservationV2(
        host_kind="AUTOCAD",
        host_instance_id="autocad-runtime-3",
        document_id=r"C:\DSP\fixtures\cross-host.dwg",
        native_target_id="autocad-wall-001",
        semantic_target_id="WALL-001",
        host_revision=17 if revision is None else revision,
        normalized_thickness_mm=thickness_mm,
        observed_at=observed_at or "2026-10-02T04:00:01Z",
        command_id=command_id or "proposal-read-autocad-1",
    )


def _subject(
    *,
    request_hash: str = "1" * 64,
    session_binding_hash: str = "2" * 64,
    topology_snapshot_hash: str = "3" * 64,
    thickness_mm: float = 300.0,
    observations=None,
) -> CrossHostOperationProposalSubjectV2:
    """构造完整 V2 proposal subject；输入 observation 顺序不应改变 identity。"""

    if observations is None:
        observations = (_observation("REVIT"), _observation("AUTOCAD"))
    return CrossHostOperationProposalSubjectV2(
        request_hash=request_hash,
        session_binding_hash=session_binding_hash,
        topology_snapshot_hash=topology_snapshot_hash,
        semantic_target_id="WALL-001",
        semantic_environment_id="SEM-ENV-1",
        semantic_environment_hash="4" * 64,
        canonical_operation="set_wall_thickness.v1",
        canonical_arguments={
            "thickness": {"value": thickness_mm, "unit": "mm"},
            "targets": ["WALL-001"],
        },
        observations=observations,
    )


def test_v2_subject_hash_binds_request_binding_topology_operation_and_both_observations() -> None:
    """subject content hash 必须绑定用户当时接受的完整 cross-Host 证据。"""

    original = _subject()
    original_hash = workflow_artifact_content_hash(original)

    assert original_hash != workflow_artifact_content_hash(
        _subject(request_hash="5" * 64)
    )
    assert original_hash != workflow_artifact_content_hash(
        _subject(session_binding_hash="6" * 64)
    )
    assert original_hash != workflow_artifact_content_hash(
        _subject(topology_snapshot_hash="7" * 64)
    )
    assert original_hash != workflow_artifact_content_hash(
        _subject(thickness_mm=350.0)
    )
    changed_revit = replace(_observation("REVIT"), host_revision=42)
    assert original_hash != workflow_artifact_content_hash(
        _subject(observations=(changed_revit, _observation("AUTOCAD")))
    )
    changed_autocad = replace(_observation("AUTOCAD"), normalized_thickness_mm=201.0)
    assert original_hash != workflow_artifact_content_hash(
        _subject(observations=(_observation("REVIT"), changed_autocad))
    )

    payload = encode_workflow_artifact(
        kind="cross_host_operation_proposal_subject_v2",
        value=original,
    )
    assert "required_set_hash" not in json.dumps(payload, sort_keys=True)


def test_subject_stable_comparison_ignores_timestamp_and_command_id_only() -> None:
    """独立 READ 可换 provenance，但 runtime/document/target/revision/value 漂移必须可见。"""

    original = _observation("REVIT")
    reacquired = replace(
        original,
        observed_at="2026-10-02T04:05:00Z",
        command_id="proposal-reread-revit-2",
    )

    assert original.stable_state_body() == reacquired.stable_state_body()

    for changed in (
        replace(original, host_instance_id="revit-runtime-8"),
        replace(original, document_id=r"C:\DSP\fixtures\other.rvt"),
        replace(original, native_target_id="revit-wall-other"),
        replace(original, semantic_target_id="WALL-OTHER"),
        replace(original, host_revision=42),
        replace(original, normalized_thickness_mm=201.0),
    ):
        assert original.stable_state_body() != changed.stable_state_body()

    first_subject = _subject(
        observations=(original, _observation("AUTOCAD")),
    )
    reacquired_subject = _subject(
        observations=(reacquired, _observation("AUTOCAD")),
    )
    # Subject audit identity 仍绑定真实 provenance，因此重新采集会形成不同 artifact。
    assert workflow_artifact_content_hash(first_subject) != workflow_artifact_content_hash(
        reacquired_subject
    )


def test_cross_host_subject_codec_round_trips_and_canonicalizes_host_order() -> None:
    """workflow artifact codec 必须完整重建 subject，并把成员顺序规范成 AutoCAD→Revit。"""

    subject = _subject(
        observations=(_observation("REVIT"), _observation("AUTOCAD")),
    )
    payload = encode_workflow_artifact(
        kind="cross_host_operation_proposal_subject_v2",
        value=subject,
    )
    restored = decode_workflow_artifact(
        kind="cross_host_operation_proposal_subject_v2",
        codec_version=WORKFLOW_ARTIFACT_CODEC_VERSION,
        payload=payload,
    )

    assert restored == subject
    assert tuple(item.host_kind for item in restored.observations) == (
        "AUTOCAD",
        "REVIT",
    )


@pytest.mark.parametrize(
    "observations",
    [
        (_observation("REVIT"),),
        (_observation("REVIT"), _observation("REVIT")),
    ],
)
def test_cross_host_subject_requires_exact_revit_and_autocad_observations(
    observations,
) -> None:
    """Proposal subject 本身不能接受缺失、重复或额外 Host observation。"""

    with pytest.raises(ValueError, match="CROSS_HOST_PROPOSAL_SUBJECT_INVALID"):
        _subject(observations=observations)
