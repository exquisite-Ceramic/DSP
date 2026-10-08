"""Task 15.5：Cross-Host production proposal/reference composition contract。"""

from __future__ import annotations

from design_orchestrator.canonical_operations import SET_WALL_THICKNESS_V1
from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
from design_orchestrator.operation_resolver import (
    ClassificationGuarantee,
    OperationResolver,
    ResolutionContext,
    SemanticEligibilityContext,
    SemanticEligibilityEntity,
)
from design_orchestrator.workflow_contracts import StableRef
from design_product_runtime.revit_reference_composition import _ReferenceWallCapabilityProfile

from tests.product_front_door.test_cross_host_gate_a import (
    _accepted_input,
    _binding,
    _observation,
)


class _AcceptedReader:
    """只暴露 server-owned V2 accepted input。"""

    def __init__(self) -> None:
        self.accepted = _accepted_input()

    def get_v2(self, task_id: str):
        """按 exact task 返回 accepted input。"""

        assert task_id == self.accepted.request.task_id
        return self.accepted


class _ArtifactStore:
    """只保存本测试的真实 OperationResolver result。"""

    def __init__(self, operation_ref: StableRef, value) -> None:
        self.operation_ref = operation_ref
        self.value = value

    def get(self, ref: StableRef):
        """proposal builder 只能解析调用方给出的 exact operation ref。"""

        assert ref == self.operation_ref
        return self.value


class _ObservationReader:
    """记录 proposal 阶段两次 fresh READ。"""

    def __init__(self) -> None:
        self.calls = []

    def read(self, *, binding, member, command_id: str):
        """返回与 accepted binding 对齐的 human-visible observation。"""

        self.calls.append((binding, member, command_id))
        return _observation(member.host_kind)


def _resolution():
    """用真实 OperationResolver 生成唯一 set_wall_thickness.v1 action space。"""

    profile = _ReferenceWallCapabilityProfile()
    binding = _binding()
    semantic = SemanticEligibilityContext(
        context_snapshot_id="CTX-TASK155",
        context_snapshot_hash="a" * 64,
        document_ref=binding.member("REVIT").document_id,
        semantic_environment_ref=binding.semantic_environment_id,
        entities=(
            SemanticEligibilityEntity(
                semantic_id=binding.semantic_target_id,
                canonical_classifications=("ifc:IfcWall",),
                classification_guarantee=ClassificationGuarantee(
                    machine_decision_supported=True,
                ),
            ),
        ),
    )
    return OperationResolver((SET_WALL_THICKNESS_V1,)).resolve(
        (profile,),
        ResolutionContext(
            host_provider_servers=frozenset({profile.provider_server}),
            semantic_context=semantic,
        ),
    )


def test_reference_proposal_builder_uses_exact_accepted_input_and_two_fresh_reads() -> None:
    """V2 subject 必须绑定 accepted request/binding 与两端实际展示的 fresh observation。"""

    import design_product_runtime as product_runtime

    builder_type = getattr(
        product_runtime,
        "CrossHostOperationProposalBuilder",
        None,
    )
    assert builder_type is not None, "CrossHostOperationProposalBuilder 尚未实现"

    operation_ref = StableRef("operation-space-task155", "b" * 64)
    observations = _ObservationReader()
    accepted_reader = _AcceptedReader()
    builder = builder_type(
        accepted_input_reader=accepted_reader,
        workflow_artifact_store=_ArtifactStore(operation_ref, _resolution()),
        observation_reader=observations,
    )

    subject = builder.build(
        accepted_reader.accepted.request.task_id,
        operation_ref,
        StableRef("context-task155", "c" * 64),
    )

    binding = _binding()
    request = accepted_reader.accepted.request
    assert subject.request_hash == request.request_hash
    assert subject.session_binding_hash == binding.binding_hash
    assert subject.topology_snapshot_hash == binding.topology_snapshot_hash
    assert subject.semantic_target_id == binding.semantic_target_id
    assert subject.canonical_operation == "set_wall_thickness.v1"
    assert subject.canonical_arguments_body() == {
        "targets": [binding.semantic_target_id],
        "thickness": {"unit": "mm", "value": 300.0},
    }
    assert tuple(item.host_kind for item in subject.observations) == (
        "AUTOCAD",
        "REVIT",
    )
    assert [call[1].host_kind for call in observations.calls] == [
        "AUTOCAD",
        "REVIT",
    ]


class _Noop:
    """Canonical owner constructor 的未使用依赖。"""


def test_canonical_owner_delegates_v2_proposal_subject_only_when_builder_is_injected() -> None:
    """Canonical owner 不生成第二份 subject truth，只委托显式 cross-host builder。"""

    class _Builder:
        def __init__(self) -> None:
            self.calls = []

        def build(self, task_id, operation_ref, context_snapshot_ref):
            self.calls.append((task_id, operation_ref, context_snapshot_ref))
            return "subject-sentinel"

    builder = _Builder()
    noop = _Noop()
    owner = CanonicalWorkflowOwnerPorts(
        snapshot_registry=noop,
        freshness_resolver=noop,
        workflow_artifact_store=noop,
        host_revision_observation=noop,
        canonical_operations=noop,
        impact_analyzer=noop,
        impact_store=noop,
        approval_scope_planner=noop,
        approval_scope_store=noop,
        changeset_builder=noop,
        changeset_store=noop,
        materialization_planner=noop,
        materialization_plan_store=noop,
        topology_registry=noop,
        topology_environment_id="TOPOLOGY",
        topology_revision=1,
        execution_plan_store=noop,
        revision_barrier=noop,
        gateway_authorization=noop,
        gateway_authorization_store=noop,
        coordination_clock=noop,
        provider_binding_store=noop,
        dispatch_intent_store=noop,
        execution_recovery_projection=noop,
        saga_store=noop,
        execution_coordinator=noop,
        reconciliation_service=noop,
        convergence_verifier=noop,
        semantic_reconstruction=noop,
        preview_port=noop,
        approval_admission=noop,
        materialization_routing=noop,
        provider_execution_snapshot=noop,
        cross_host_proposal_builder=builder,
    )
    operation_ref = StableRef("operation-task155", "d" * 64)
    context_ref = StableRef("context-task155", "e" * 64)

    result = owner.build_operation_proposal_subject(
        "task-task155",
        operation_ref,
        context_ref,
    )

    assert result == "subject-sentinel"
    assert builder.calls == [("task-task155", operation_ref, context_ref)]
