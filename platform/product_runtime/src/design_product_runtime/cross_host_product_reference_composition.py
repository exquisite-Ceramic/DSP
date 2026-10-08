"""Cross-Host Product Vertical 的 production/reference composition seams。

当前模块先提供 proposal subject builder；后续 reference flow resolver 继续在同一模块组合，
但任何业务 authority 仍由 ProductTask、Workflow Artifact 与 Host READ owners 持有。
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from hashlib import sha256
from threading import RLock
from types import MappingProxyType

from design_orchestrator.canonical_owner_ports import CanonicalWorkflowOwnerPorts
from design_orchestrator.interaction_artifacts import CrossHostOperationProposalSubjectV2
from design_orchestrator.operation_resolver import ResolutionResult
from design_orchestrator.workflow_contracts import StableRef

from .accepted_input import AcceptedProductTaskInputV2


@dataclass(frozen=True, slots=True)
class _AcceptedBindingMember:
    """从 server-owned accepted binding body 投影出的 exact Host member read view。"""

    host_kind: str
    role: str
    configured_reference_id: str
    configured_reference_hash: str
    transport_locator: str
    host_instance_id: str
    document_id: str
    native_target_id: str
    host_binding_fingerprint: str


@dataclass(frozen=True, slots=True)
class _AcceptedBinding:
    """proposal builder 只读所需的 V2 binding 结构视图。"""

    session_ref: str
    project_id: str
    semantic_target_id: str
    semantic_environment_id: str
    semantic_environment_hash: str
    topology_environment_id: str
    topology_revision: int
    topology_snapshot_hash: str
    initiating_host_kind: str
    members: tuple[_AcceptedBindingMember, _AcceptedBindingMember]
    binding_hash: str

    def member(self, host_kind: str) -> _AcceptedBindingMember:
        """按 exact Host kind 返回 member；禁止 fuzzy/latest fallback。"""

        matches = tuple(item for item in self.members if item.host_kind == host_kind)
        if len(matches) != 1:
            raise ValueError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: exact Host member is unavailable"
            )
        return matches[0]


def _required_text(value: object, field_name: str) -> str:
    """规范化 accepted-input locator，并区分类型错误与空值错误。"""

    if not isinstance(value, str):
        raise TypeError(
            f"CROSS_HOST_PROPOSAL_LINEAGE_INVALID: {field_name} must be a string"
        )
    if not value.strip():
        raise ValueError(
            f"CROSS_HOST_PROPOSAL_LINEAGE_INVALID: {field_name} must be non-blank"
        )
    return value.strip()


def _binding_from_accepted(accepted: AcceptedProductTaskInputV2) -> _AcceptedBinding:
    """从 ProductTask owner 的 immutable JSON body 重建只读结构，不创建第二份 truth。"""

    payload = accepted.session_binding_payload
    raw_members = payload.get("members")
    if not isinstance(raw_members, list):
        raise TypeError(
            "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted binding members must be a list"
        )
    if len(raw_members) != 2:
        raise ValueError(
            "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted binding requires two members"
        )
    members = []
    for raw in raw_members:
        if not isinstance(raw, Mapping):
            raise TypeError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted member body must be a mapping"
            )
        members.append(
            _AcceptedBindingMember(
                host_kind=_required_text(raw.get("host_kind"), "member.host_kind"),
                role=_required_text(raw.get("role"), "member.role"),
                configured_reference_id=_required_text(
                    raw.get("configured_reference_id"),
                    "member.configured_reference_id",
                ),
                configured_reference_hash=_required_text(
                    raw.get("configured_reference_hash"),
                    "member.configured_reference_hash",
                ),
                transport_locator=_required_text(
                    raw.get("transport_locator"),
                    "member.transport_locator",
                ),
                host_instance_id=_required_text(
                    raw.get("host_instance_id"),
                    "member.host_instance_id",
                ),
                document_id=_required_text(raw.get("document_id"), "member.document_id"),
                native_target_id=_required_text(
                    raw.get("native_target_id"),
                    "member.native_target_id",
                ),
                host_binding_fingerprint=_required_text(
                    raw.get("host_binding_fingerprint"),
                    "member.host_binding_fingerprint",
                ),
            )
        )
    by_kind = {item.host_kind: item for item in members}
    if set(by_kind) != {"AUTOCAD", "REVIT"} or len(by_kind) != 2:
        raise ValueError(
            "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: required Host set is AUTOCAD + REVIT"
        )
    if by_kind["AUTOCAD"].role != "BOUND_REQUIRED" or by_kind["REVIT"].role != "INITIATOR":
        raise ValueError(
            "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted Host roles are invalid"
        )

    binding_hash = _required_text(payload.get("binding_hash"), "binding_hash")
    if binding_hash != accepted.session_binding_hash:
        raise ValueError(
            "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted binding hash mismatch"
        )
    return _AcceptedBinding(
        session_ref=_required_text(payload.get("session_ref"), "session_ref"),
        project_id=_required_text(payload.get("project_id"), "project_id"),
        semantic_target_id=_required_text(
            payload.get("semantic_target_id"),
            "semantic_target_id",
        ),
        semantic_environment_id=_required_text(
            payload.get("semantic_environment_id"),
            "semantic_environment_id",
        ),
        semantic_environment_hash=_required_text(
            payload.get("semantic_environment_hash"),
            "semantic_environment_hash",
        ),
        topology_environment_id=_required_text(
            payload.get("topology_environment_id"),
            "topology_environment_id",
        ),
        topology_revision=payload.get("topology_revision"),
        topology_snapshot_hash=_required_text(
            payload.get("topology_snapshot_hash"),
            "topology_snapshot_hash",
        ),
        initiating_host_kind=_required_text(
            payload.get("initiating_host_kind"),
            "initiating_host_kind",
        ),
        members=(by_kind["AUTOCAD"], by_kind["REVIT"]),
        binding_hash=binding_hash,
    )


class CrossHostOperationProposalBuilder:
    """从 accepted input + OperationResolver result + 两端 fresh READ 构造 immutable subject。"""

    def __init__(
        self,
        *,
        accepted_input_reader: object,
        workflow_artifact_store: object,
        observation_reader: object,
    ) -> None:
        """只保存既有 owner/read seams；构造阶段不访问 Host。"""

        if not callable(getattr(accepted_input_reader, "get_v2", None)):
            raise TypeError("accepted_input_reader must provide get_v2")
        if not callable(getattr(workflow_artifact_store, "get", None)):
            raise TypeError("workflow_artifact_store must provide get")
        if not callable(getattr(observation_reader, "read", None)):
            raise TypeError("observation_reader must provide read")
        self._accepted_input_reader = accepted_input_reader
        self._workflow_artifact_store = workflow_artifact_store
        self._observation_reader = observation_reader

    def build(
        self,
        task_id: str,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> CrossHostOperationProposalSubjectV2:
        """读取 exact accepted task/action-space，并展示两端当前 wall-thickness observation。"""

        normalized_task_id = _required_text(task_id, "task_id")
        if not isinstance(operation_ref, StableRef):
            raise TypeError("operation_ref must be StableRef")
        if not isinstance(context_snapshot_ref, StableRef):
            raise TypeError("context_snapshot_ref must be StableRef")

        accepted = self._accepted_input_reader.get_v2(normalized_task_id)
        if accepted is None:
            raise ValueError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: V2 accepted input is unavailable"
            )
        if not isinstance(accepted, AcceptedProductTaskInputV2):
            raise TypeError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: V2 accepted input has invalid type"
            )
        request = accepted.request
        if request.task_id != normalized_task_id:
            raise ValueError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: accepted task identity mismatch"
            )
        binding = _binding_from_accepted(accepted)
        if (
            request.project_id != binding.project_id
            or request.session_ref != binding.session_ref
            or request.session_binding_hash != binding.binding_hash
            or binding.initiating_host_kind != "REVIT"
        ):
            raise ValueError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: request/binding authority mismatch"
            )

        resolution = self._workflow_artifact_store.get(operation_ref)
        if not isinstance(resolution, ResolutionResult):
            raise TypeError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: operation ref is not ResolutionResult"
            )
        supported = tuple(
            item
            for item in resolution.resolved_operations
            if item.canonical_operation == "set_wall_thickness.v1"
        )
        if len(supported) != 1 or len(resolution.resolved_operations) != 1:
            raise ValueError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: expected one supported wall operation"
            )

        thickness = request.intent_arguments.get("thickness")
        if not isinstance(thickness, Mapping):
            raise TypeError(
                "CROSS_HOST_PROPOSAL_LINEAGE_INVALID: V2 thickness intent must be a mapping"
            )
        arguments = MappingProxyType(
            {
                "targets": (binding.semantic_target_id,),
                "thickness": MappingProxyType(
                    {
                        "unit": thickness.get("unit"),
                        "value": thickness.get("value"),
                    }
                ),
            }
        )

        observations = tuple(
            self._observation_reader.read(
                binding=binding,
                member=member,
                command_id=(
                    f"cross-host-proposal:{normalized_task_id}:{member.host_kind.lower()}"
                ),
            )
            for member in binding.members
        )
        return CrossHostOperationProposalSubjectV2(
            request_hash=request.request_hash,
            session_binding_hash=binding.binding_hash,
            topology_snapshot_hash=binding.topology_snapshot_hash,
            semantic_target_id=binding.semantic_target_id,
            semantic_environment_id=binding.semantic_environment_id,
            semantic_environment_hash=binding.semantic_environment_hash,
            canonical_operation=supported[0].canonical_operation,
            canonical_arguments=arguments,
            observations=observations,
        )


class CrossHostCanonicalWorkflowOwnerPorts(CanonicalWorkflowOwnerPorts):
    """只为 Cross-Host composition 增加 proposal builder，不扩张核心 owner contract。"""

    __slots__ = ("_cross_host_proposal_builder",)

    def __init__(
        self,
        *,
        cross_host_proposal_builder: object,
        **owner_dependencies: object,
    ) -> None:
        """先构造冻结的 canonical owner，再保存 composition-only proposal extension。"""

        if not callable(getattr(cross_host_proposal_builder, "build", None)):
            raise TypeError("cross_host_proposal_builder must provide build")
        super().__init__(**owner_dependencies)
        self._cross_host_proposal_builder = cross_host_proposal_builder

    def build_operation_proposal_subject(
        self,
        task_id: str,
        operation_ref: StableRef,
        context_snapshot_ref: StableRef,
    ) -> CrossHostOperationProposalSubjectV2:
        """把 V2 human subject 构造委托给显式 builder；不保存第二份 owner truth。"""

        return self._cross_host_proposal_builder.build(
            task_id,
            operation_ref,
            context_snapshot_ref,
        )


class CrossHostProductFlowResolver:
    """从 server accepted V2 input 解析 exact task 的可重建 workflow facade。

    缓存只持有进程内 composition handles 和输入指纹，不保存任何可修改的
    ProductTask request、binding、decision 或 checkpoint truth。进程重启后
    factory 必须再次从 authoritative accepted input 安全重建。
    """

    def __init__(
        self,
        flow_factory: Callable[[AcceptedProductTaskInputV2], object],
    ) -> None:
        """保存 lazy factory；构造时不触发 Host I/O 或读取客户端 SQLite。"""

        if not callable(flow_factory):
            raise TypeError("flow_factory must be callable")
        self._flow_factory = flow_factory
        self._lock = RLock()
        self._flows: dict[str, tuple[tuple[str, str, str], object]] = {}

    @staticmethod
    def _fingerprint(
        accepted: AcceptedProductTaskInputV2,
    ) -> tuple[str, str, str]:
        """把 accepted owner body 压缩成缓存校验标识，不创建新 authority。"""

        body = json.dumps(
            dict(accepted.session_binding_payload),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return (
            accepted.request.request_hash,
            accepted.session_binding_hash,
            sha256(body).hexdigest(),
        )

    def get_flow(self, accepted: AcceptedProductTaskInputV2):
        """same task/body 只构造一次；same task/body drift 必须 fail closed。"""

        if not isinstance(accepted, AcceptedProductTaskInputV2):
            raise TypeError("accepted must be AcceptedProductTaskInputV2")
        task_id = accepted.request.task_id
        fingerprint = self._fingerprint(accepted)

        with self._lock:
            cached = self._flows.get(task_id)
            if cached is not None:
                cached_fingerprint, cached_flow = cached
                if cached_fingerprint != fingerprint:
                    raise ValueError(
                        "CROSS_HOST_PRODUCT_FLOW_INPUT_CONFLICT: "
                        "task already owns a different immutable accepted input"
                    )
                return cached_flow

            flow = self._flow_factory(accepted)
            if not callable(getattr(flow, "start_accepted", None)):
                raise TypeError("flow_factory must return a V2 start_accepted facade")
            if not callable(getattr(flow, "resume", None)):
                raise TypeError("flow_factory must return a V2 resume facade")
            self._flows[task_id] = (fingerprint, flow)
            return flow


__all__ = [
    "CrossHostCanonicalWorkflowOwnerPorts",
    "CrossHostProductFlowResolver",
    "CrossHostOperationProposalBuilder",
]
