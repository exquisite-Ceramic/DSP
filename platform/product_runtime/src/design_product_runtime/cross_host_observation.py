"""Cross-Host wall-thickness proposal/planning 的 production READ adapters。"""

from __future__ import annotations

import asyncio
import math
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from design_fact_contracts import FactKind, NormalizedDesignFactBatch
from design_orchestrator.interaction_artifacts import CrossHostProposalObservationV2
from semantic_runtime import ReconstructionResult

from .cross_host_planning import CrossHostPlanningMemberEvidence

if TYPE_CHECKING:
    from design_product_front_door.contracts import (
        SessionBindingMemberV2,
        SessionBindingV2,
    )


def _fail(code: str, detail: str) -> None:
    """用稳定错误码拒绝不能形成 proposal/planning authority 的 READ evidence。"""

    raise ValueError(f"{code}: {detail}")


def _run(awaitable):
    """在同步 product boundary 执行 AutoCAD async fact READ。"""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError(
        "cross-host synchronous observation cannot run inside an active event loop"
    )


def _utc_now() -> str:
    """返回 canonical UTC Z 文本，只作为 acquisition provenance。"""

    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _required_clock_value(clock) -> str:
    """规范化 proposal acquisition timestamp。"""

    value = clock()
    if not isinstance(value, str) or not value.strip():
        raise ValueError("observation clock must return a non-blank string")
    return value.strip()


def _require_exact_member(
    binding: SessionBindingV2,
    member: SessionBindingMemberV2,
) -> None:
    """只接受 accepted binding 中 exact member；运行时保持 Product Runtime→Front Door 单向解耦。"""

    members = getattr(binding, "members", None)
    semantic_target_id = getattr(binding, "semantic_target_id", None)
    if not isinstance(members, tuple) or not isinstance(semantic_target_id, str):
        raise TypeError("binding must expose frozen V2 members and semantic_target_id")

    required_member_fields = (
        "host_kind",
        "transport_locator",
        "host_instance_id",
        "document_id",
        "native_target_id",
    )
    if any(not hasattr(member, field_name) for field_name in required_member_fields):
        raise TypeError("member must expose the frozen V2 Host member identity")
    if member not in members:
        _fail(
            "CROSS_HOST_OBSERVATION_BINDING_MISMATCH",
            "member is not the exact frozen binding member",
        )


class CrossHostWallThicknessObservationReader:
    """把 AutoCAD/Revit production READ 归一为 human-subject observation。"""

    def __init__(
        self,
        *,
        autocad_dispatcher_factory,
        revit_transport_factory,
        clock=None,
    ) -> None:
        """保存 locator→production transport factories；构造阶段不访问 Host。"""

        if not callable(autocad_dispatcher_factory):
            raise TypeError("autocad_dispatcher_factory must be callable")
        if not callable(revit_transport_factory):
            raise TypeError("revit_transport_factory must be callable")
        if clock is not None and not callable(clock):
            raise TypeError("clock must be callable")
        self._autocad_dispatcher_factory = autocad_dispatcher_factory
        self._revit_transport_factory = revit_transport_factory
        self._clock = clock or _utc_now

    def read(
        self,
        *,
        binding: SessionBindingV2,
        member: SessionBindingMemberV2,
        command_id: str,
    ) -> CrossHostProposalObservationV2:
        """fresh-read exact Host runtime/document/native target 并返回稳定比较体。"""

        _require_exact_member(binding, member)
        if not isinstance(command_id, str) or not command_id.strip():
            raise ValueError("command_id must be a non-blank string")
        normalized_command_id = command_id.strip()

        if member.host_kind == "AUTOCAD":
            revision, thickness = self._read_autocad(member)
        elif member.host_kind == "REVIT":
            revision, thickness = self._read_revit(
                member,
                normalized_command_id,
            )
        else:
            _fail(
                "CROSS_HOST_OBSERVATION_BINDING_MISMATCH",
                "unsupported Host kind",
            )

        return CrossHostProposalObservationV2(
            host_kind=member.host_kind,
            host_instance_id=member.host_instance_id,
            document_id=member.document_id,
            native_target_id=member.native_target_id,
            semantic_target_id=binding.semantic_target_id,
            host_revision=revision,
            normalized_thickness_mm=thickness,
            observed_at=_required_clock_value(self._clock),
            command_id=normalized_command_id,
        )

    def _read_autocad(
        self,
        member: SessionBindingMemberV2,
    ) -> tuple[int, float]:
        """复用 AutoCAD normalized-fact extraction，严格关联 exact target。"""

        dispatcher = self._autocad_dispatcher_factory(member.transport_locator)
        extractor = getattr(dispatcher, "extract_design_facts", None)
        if not callable(extractor):
            raise TypeError(
                "AutoCAD dispatcher must provide extract_design_facts"
            )
        try:
            batch = _run(extractor([member.native_target_id]))
        except (ConnectionError, OSError, RuntimeError, TypeError, ValueError) as exc:
            _fail(
                "CROSS_HOST_OBSERVATION_READ_FAILED",
                f"AutoCAD fact extraction failed: {exc}",
            )
        if not isinstance(batch, NormalizedDesignFactBatch):
            _fail(
                "CROSS_HOST_OBSERVATION_READ_FAILED",
                "AutoCAD fact extraction returned an invalid batch",
            )

        width_facts = tuple(
            fact
            for fact in batch.facts
            if fact.fact_kind is FactKind.PROPERTY
            and fact.predicate == "constant_width"
            and fact.unit == "mm"
            and fact.host_ref.host_type == "autocad"
            and fact.host_ref.host_instance_id == member.host_instance_id
            and fact.host_ref.document_id == member.document_id
            and fact.subject_native_ref.document_id == member.document_id
            and fact.subject_native_ref.native_id == member.native_target_id
            and fact.subject_native_ref.native_kind == "LWPOLYLINE"
        )
        if len(width_facts) != 1:
            _fail(
                "CROSS_HOST_OBSERVATION_READ_FAILED",
                "exact AutoCAD constant_width evidence is unavailable",
            )
        fact = width_facts[0]
        value = fact.value
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) <= 0.0
        ):
            _fail(
                "CROSS_HOST_OBSERVATION_READ_FAILED",
                "AutoCAD wall thickness must be finite and positive",
            )
        return fact.source_revision, float(value)

    def _read_revit(
        self,
        member: SessionBindingMemberV2,
        command_id: str,
    ) -> tuple[int, float]:
        """先读取 current context revision，再以同 revision 读取独立 wall snapshot。"""

        from revit_sidecar import RevitContextReadPort, RevitWallThicknessSnapshotReadPort

        transport = self._revit_transport_factory(member.transport_locator)
        if transport is None:
            _fail(
                "CROSS_HOST_OBSERVATION_READ_FAILED",
                "Revit transport locator is unresolved",
            )
        context = RevitContextReadPort(transport).read(
            command_id=f"{command_id}:context",
            document_id=member.document_id,
            host_instance_id=member.host_instance_id,
        )
        if (
            len(context.selected_elements) != 1
            or context.selected_elements[0].native_kind != "Wall"
            or context.selected_elements[0].unique_id != member.native_target_id
        ):
            _fail(
                "CROSS_HOST_OBSERVATION_BINDING_MISMATCH",
                "Revit selected Wall differs from frozen binding",
            )
        snapshot = RevitWallThicknessSnapshotReadPort(transport).read(
            command_id=f"{command_id}:snapshot",
            document_id=member.document_id,
            host_instance_id=member.host_instance_id,
            wall_unique_id=member.native_target_id,
            expected_revision=context.revision,
        )
        return context.revision, snapshot.wall_thickness_mm


class CrossHostPlanningRuntimePort:
    """一个 REQUIRED Host 的 Gate-B current-revision + independent reconstruction port。"""

    def __init__(
        self,
        *,
        binding: SessionBindingV2,
        member: SessionBindingMemberV2,
        observation_reader: CrossHostWallThicknessObservationReader,
        semantic_reconstruction: object,
    ) -> None:
        """冻结 exact member；语义重建仍委托既有 semantic owner。"""

        _require_exact_member(binding, member)
        if not isinstance(
            observation_reader,
            CrossHostWallThicknessObservationReader,
        ):
            raise TypeError(
                "observation_reader must be CrossHostWallThicknessObservationReader"
            )
        if not callable(getattr(semantic_reconstruction, "reconstruct", None)):
            raise TypeError(
                "semantic_reconstruction must provide reconstruct"
            )
        self._binding = binding
        self._member = member
        self._observation_reader = observation_reader
        self._semantic_reconstruction = semantic_reconstruction

    def current_revision(self, document_ref: str) -> str:
        """fresh-read exact document current revision；不缓存 proposal observation。"""

        if document_ref != self._member.document_id:
            _fail(
                "PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED",
                "exact planning document is not configured",
            )
        observation = self._observation_reader.read(
            binding=self._binding,
            member=self._member,
            command_id=(
                f"cross-host-planning-revision:{self._member.host_kind}:"
                f"{self._member.document_id}"
            ),
        )
        return str(observation.host_revision)

    def reconstruct_member(
        self,
        *,
        task_id: str,
        host_kind: str,
        contract,
        accepted_observation: CrossHostProposalObservationV2,
        expected_host_revision: str,
        semantic_environment_ref,
    ) -> CrossHostPlanningMemberEvidence:
        """再次 fresh-read 自身 Host 后交给 semantic owner 独立重建。"""

        if host_kind != self._member.host_kind:
            _fail(
                "PRODUCT_RUNTIME_HOST_RUNTIME_NOT_CONFIGURED",
                "planning Host kind does not match configured member",
            )
        if (
            accepted_observation.host_kind != self._member.host_kind
            or accepted_observation.host_instance_id
            != self._member.host_instance_id
            or accepted_observation.document_id != self._member.document_id
            or accepted_observation.native_target_id
            != self._member.native_target_id
            or accepted_observation.semantic_target_id
            != self._binding.semantic_target_id
        ):
            _fail(
                "CROSS_HOST_OBSERVATION_BINDING_MISMATCH",
                "accepted observation does not match exact planning member",
            )
        if not isinstance(expected_host_revision, str) or not expected_host_revision.strip():
            raise ValueError("expected_host_revision must be non-blank")

        fresh = self._observation_reader.read(
            binding=self._binding,
            member=self._member,
            command_id=f"cross-host-planning:{task_id}:{host_kind}",
        )
        reconstruction = self._semantic_reconstruction.reconstruct(
            task_id=task_id,
            contract=contract,
            observation=fresh,
            semantic_environment_ref=semantic_environment_ref,
        )
        if not isinstance(reconstruction, ReconstructionResult):
            raise TypeError(
                "semantic_reconstruction.reconstruct must return ReconstructionResult"
            )
        return CrossHostPlanningMemberEvidence(
            observation=fresh,
            reconstruction=reconstruction,
        )


__all__ = [
    "CrossHostPlanningRuntimePort",
    "CrossHostWallThicknessObservationReader",
]
