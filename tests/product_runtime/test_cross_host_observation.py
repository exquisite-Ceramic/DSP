"""Task 15.5 A2：production proposal observation 与 planning member seams。"""

from __future__ import annotations

from dataclasses import replace

import design_product_runtime as product_runtime
import pytest
from autocad_sidecar.adapter.design_fact_adapter import DesignFactAdapter
from design_orchestrator.interaction_artifacts import CrossHostProposalObservationV2
from semantic_runtime import (
    ReconstructionResult,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    build_operation_contract,
)

from tests.product_front_door.test_cross_host_gate_a import _binding


class _AutoCadDispatcher:
    """只提供 production normalized-fact READ surface。"""

    def __init__(self, *, revision: int = 17, width_mm: float = 200.0) -> None:
        self.revision = revision
        self.width_mm = width_mm
        self.calls = 0

    async def extract_design_facts(self, handles):
        """返回 exact LWPOLYLINE constant-width normalized facts。"""

        self.calls += 1
        assert tuple(handles) == ("autocad-wall-1",)
        return DesignFactAdapter().normalize_snapshot(
            {
                "hostInstanceId": "autocad-runtime-1",
                "documentId": r"C:\DSP\fixtures\cross-host.dwg",
                "revision": self.revision,
                "entities": [
                    {
                        "nativeId": "autocad-wall-1",
                        "nativeKind": "LWPOLYLINE",
                        "layer": "A-WALL",
                        "properties": {
                            "constantWidth": {
                                "value": self.width_mm,
                                "unit": "mm",
                            }
                        },
                    }
                ],
            }
        )


class _RevitTransport:
    """复用 context.current_selection + snapshot READ 两条 production HostCommand。"""

    def __init__(self, *, revision: int = 41, width_mm: float = 200.0) -> None:
        self.revision = revision
        self.width_mm = width_mm
        self.operations = []

    def request(self, command):
        """返回 exact runtime/document/target 的当前只读 evidence。"""

        self.operations.append(command.operation)
        assert command.document_id == r"C:\DSP\fixtures\cross-host.rvt"
        if command.operation == "context.current_selection":
            return {
                "status": "OK",
                "revision_after": self.revision,
                "payload": {
                    "document_id": command.document_id,
                    "document_title": "Task 15.5 Revit",
                    "host_instance_id": "revit-runtime-1",
                    "selected_elements": [
                        {
                            "unique_id": "revit-wall-1",
                            "native_kind": "Wall",
                        }
                    ],
                },
            }
        if command.operation == "read_wall_thickness_snapshot":
            assert command.target_native_refs[0].native_id == "revit-wall-1"
            return {
                "status": "OK",
                "revision_after": self.revision,
                "payload": {
                    "document_id": command.document_id,
                    "host_instance_id": "revit-runtime-1",
                    "wall_unique_id": "revit-wall-1",
                    "wall_type_unique_id": "revit-type-1",
                    "native_kind": "Wall",
                    "builtin_category": "OST_Walls",
                    "wall_thickness_mm": self.width_mm,
                    "location_signature": "task15.5-location",
                    "relationship_signature": "task15.5-relationship",
                    "revision_before": self.revision,
                    "revision_after": self.revision,
                },
            }
        raise AssertionError(f"unexpected Revit READ: {command.operation}")


class _Clock:
    """为 proposal provenance 提供可控 acquisition metadata。"""

    def __init__(self) -> None:
        self.sequence = 0

    def __call__(self) -> str:
        self.sequence += 1
        return f"2026-10-07T08:00:0{self.sequence}Z"


def _reader(*, autocad=None, revit=None):
    """构造 wished-for production observation reader。"""

    reader_type = getattr(product_runtime, "CrossHostWallThicknessObservationReader", None)
    assert reader_type is not None, "CrossHostWallThicknessObservationReader 尚未实现"
    autocad = autocad or _AutoCadDispatcher()
    revit = revit or _RevitTransport()
    reader = reader_type(
        autocad_dispatcher_factory=lambda locator: (
            autocad if locator == "autocad-pipe" else None
        ),
        revit_transport_factory=lambda locator: (
            revit if locator == "revit-pipe" else None
        ),
        clock=_Clock(),
    )
    return reader, autocad, revit


def test_autocad_and_revit_proposal_reads_return_exact_stable_state() -> None:
    """两个 Host 都必须通过 production READ/normalization 形成 exact proposal stable state。"""

    binding = _binding()
    reader, autocad, revit = _reader()
    by_host = {item.host_kind: item for item in binding.members}

    auto_observation = reader.read(
        binding=binding,
        member=by_host["AUTOCAD"],
        command_id="proposal-autocad-a2",
    )
    revit_observation = reader.read(
        binding=binding,
        member=by_host["REVIT"],
        command_id="proposal-revit-a2",
    )

    assert auto_observation.stable_state_body() == {
        "host_kind": "AUTOCAD",
        "host_instance_id": "autocad-runtime-1",
        "document_id": r"C:\DSP\fixtures\cross-host.dwg",
        "native_target_id": "autocad-wall-1",
        "semantic_target_id": "WALL-001",
        "host_revision": 17,
        "normalized_thickness_mm": 200.0,
    }
    assert revit_observation.stable_state_body() == {
        "host_kind": "REVIT",
        "host_instance_id": "revit-runtime-1",
        "document_id": r"C:\DSP\fixtures\cross-host.rvt",
        "native_target_id": "revit-wall-1",
        "semantic_target_id": "WALL-001",
        "host_revision": 41,
        "normalized_thickness_mm": 200.0,
    }
    assert autocad.calls == 1
    assert revit.operations == [
        "context.current_selection",
        "read_wall_thickness_snapshot",
    ]


def test_metadata_only_reacquisition_remains_stable_equal() -> None:
    """重新采集 command/timestamp 可变化，但 stable state 不得因此 stale。"""

    binding = _binding()
    reader, _autocad, _revit = _reader()
    member = next(item for item in binding.members if item.host_kind == "REVIT")

    first = reader.read(
        binding=binding,
        member=member,
        command_id="proposal-revit-first",
    )
    second = reader.read(
        binding=binding,
        member=member,
        command_id="proposal-revit-second",
    )

    assert first != second
    assert first.command_id != second.command_id
    assert first.observed_at != second.observed_at
    assert first.stable_state_body() == second.stable_state_body()


class _SemanticReconstruction:
    """只把各 Host fresh observation 投影成独立 ReconstructionResult。"""

    def __init__(self, label: str) -> None:
        self.label = label
        self.calls = []

    def reconstruct(
        self,
        *,
        task_id,
        contract,
        observation,
        semantic_environment_ref,
    ):
        """返回 host-specific projection，证明两端没有互相 clone。"""

        self.calls.append((task_id, observation))
        return ReconstructionResult(
            document_ref=contract.coverage.document_ref,
            host_revision=str(observation.host_revision),
            coverage=contract.coverage,
            guarantees=contract.requirements,
            projection_ref=SemanticProjectionRef(
                projection_id=f"projection-{self.label}",
                projection_hash=("a" if self.label == "autocad" else "b") * 64,
                semantic_model_version="dsp.semantic.projection-facts.v1",
                provider_set_hash=semantic_environment_ref.content_hash,
                mapping_profile_set_hash=("c" if self.label == "autocad" else "d") * 64,
                normalized_fact_batch_hash=("e" if self.label == "autocad" else "f") * 64,
            ),
            semantic_environment_ref=semantic_environment_ref,
        )


def test_planning_members_reconstruct_independently_under_same_environment() -> None:
    """AutoCAD/Revit planning ports 必须各自 fresh-read，再在同一 environment 下独立重建。"""

    port_type = getattr(product_runtime, "CrossHostPlanningRuntimePort", None)
    assert port_type is not None, "CrossHostPlanningRuntimePort 尚未实现"

    binding = _binding()
    reader, _autocad, _revit = _reader()
    environment = SemanticEnvironmentRef("SEM-ENV-1", "1" * 64)
    by_host = {item.host_kind: item for item in binding.members}
    owners = {
        "AUTOCAD": _SemanticReconstruction("autocad"),
        "REVIT": _SemanticReconstruction("revit"),
    }
    ports = {
        host_kind: port_type(
            binding=binding,
            member=member,
            observation_reader=reader,
            semantic_reconstruction=owners[host_kind],
        )
        for host_kind, member in by_host.items()
    }

    results = {}
    for host_kind in ("AUTOCAD", "REVIT"):
        member = by_host[host_kind]
        accepted = reader.read(
            binding=binding,
            member=member,
            command_id=f"accepted-{host_kind.lower()}",
        )
        contract = build_operation_contract(
            project_id=binding.project_id,
            document_ref=member.document_id,
            canonical_operation="set_wall_thickness.v1",
            targets=(binding.semantic_target_id,),
            arguments={
                "thickness": {"value": 300.0, "unit": "mm"},
                "targets": [binding.semantic_target_id],
            },
            requirements=(),
        )
        results[host_kind] = ports[host_kind].reconstruct_member(
            task_id="task-a2-planning",
            host_kind=host_kind,
            contract=contract,
            accepted_observation=accepted,
            expected_host_revision=str(accepted.host_revision),
            semantic_environment_ref=environment,
        )

    assert results["AUTOCAD"].observation.host_kind == "AUTOCAD"
    assert results["REVIT"].observation.host_kind == "REVIT"
    assert (
        results["AUTOCAD"].reconstruction.projection_ref
        != results["REVIT"].reconstruction.projection_ref
    )
    assert results["AUTOCAD"].reconstruction.semantic_environment_ref == environment
    assert results["REVIT"].reconstruction.semantic_environment_ref == environment
    assert len(owners["AUTOCAD"].calls) == 1
    assert len(owners["REVIT"].calls) == 1


@pytest.mark.parametrize(
    ("field", "replacement"),
    (
        ("host_instance_id", "wrong-runtime"),
        ("document_id", r"C:\DSP\fixtures\wrong.dwg"),
        ("native_target_id", "wrong-target"),
    ),
)
def test_unknown_runtime_document_or_native_target_fails_closed(
    field: str,
    replacement: str,
) -> None:
    """reader 只接受 binding 中 exact member；runtime/document/native 任一漂移都失败。"""

    binding = _binding()
    reader, _autocad, _revit = _reader()
    member = next(item for item in binding.members if item.host_kind == "AUTOCAD")
    drifted = replace(member, **{field: replacement})

    with pytest.raises(
        ValueError,
        match="CROSS_HOST_OBSERVATION_BINDING_MISMATCH",
    ):
        reader.read(
            binding=binding,
            member=drifted,
            command_id="proposal-invalid-a2",
        )
