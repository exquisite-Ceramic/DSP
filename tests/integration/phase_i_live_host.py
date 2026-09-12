"""Phase I 真实 AutoCAD + Revit 双 Host 验收的测试侧组合层。"""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import uuid
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml
from autocad_sidecar.adapter.host_adapter import HostAdapter as AutoCadHostAdapter
from autocad_sidecar.execution.command_dispatcher import (
    CommandDispatcher as AutoCadCommandDispatcher,
)
from autocad_sidecar.execution.readiness import AutoCadWallThicknessReadinessPort
from autocad_sidecar.ipc.transport import PipeTransport as AutoCadPipeTransport
from design_approval_scope import CanonicalAspect
from design_changeset import canonical_hash
from design_convergence import (
    CrossHostConvergenceVerifier,
    build_materialization_canonical_evidence,
)
from design_execution_coordination import (
    CrossHostReadinessBarrier,
    HostCommitted,
    HostFailed,
    MaterializedExecutionSagaCoordinator,
    ReadinessStatus,
)
from design_execution_planning import (
    ExecutionPlanningRequestV2,
    HostRuntimeRef,
    MaterializationRoutingEvidence,
    MaterializationRuntimeRoute,
    compute_materialization_routing_hash,
    plan_materialized_execution,
)
from design_execution_reconciliation import (
    ActualChange,
    ActualChangeKind,
    ActualDelta,
    ExecutionReconciliationServiceV2,
    InMemoryExecutionSagaStoreV2,
    VerificationContractEvidence,
    VerificationEvidenceBundle,
    VerificationSubjectEvidence,
    compute_actual_change_hash,
    compute_actual_delta_hash,
    compute_verification_evidence_bundle_hash,
)
from design_gateway_authorization import (
    AdmittedExecutionAuthority,
    ApprovalAdmission,
    ApprovalConsumptionRequestV2,
    ExecutionGrantRequestV2,
    GatewayAuthorizationServiceV2,
    InMemoryGatewayAuthorizationStoreV2,
    compute_admission_fingerprint,
)
from design_materialization_planning import (
    MaterializationPlanner,
    MaterializationPlanningRequest,
)
from design_orchestrator.canonical_operations import SET_WALL_THICKNESS_V1
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
from revit_sidecar.design_fact_adapter import DesignFactAdapter as RevitDesignFactAdapter
from revit_sidecar.execution_result_adapter import RevitExecutionResultAdapter
from revit_sidecar.model_adapter import RevitHostAdapter
from revit_sidecar.named_pipe import NamedPipeTransport
from revit_sidecar.readiness import RevitWallThicknessReadinessPort
from semantic_runtime import (
    Coverage,
    SemanticEnvironmentRef,
    SemanticProjectionRef,
    SemanticSnapshot,
    SnapshotKind,
)

from tests.materialization_planning.conftest import build_case, slot

ROOT = Path(__file__).resolve().parents[2]
_ENTERPRISE_MAPPING = (
    ROOT
    / "providers/semantics/enterprise_mapping/src/enterprise_mapping_provider/data/enterprise_mappings_v1.yaml"
)
_REQUIRED_ENVIRONMENT = (
    "DSP_AUTOCAD_ENDPOINT",
    "DSP_AUTOCAD_DOCUMENT_REF",
    "DSP_AUTOCAD_FIXTURE_PATH",
    "DSP_AUTOCAD_FIXTURE_SHA256",
    "DSP_AUTOCAD_NATIVE_ID",
    "DSP_AUTOCAD_HOST_INSTANCE_ID",
    "DSP_REVIT_LIVE_PIPE",
    "DSP_REVIT_LIVE_DOCUMENT_REF",
    "DSP_REVIT_LIVE_FIXTURE_PATH",
    "DSP_REVIT_LIVE_FIXTURE_SHA256",
    "DSP_REVIT_LIVE_WALL_UNIQUE_ID",
    "DSP_REVIT_LIVE_HOST_INSTANCE_ID",
    "DSP_REVIT_LIVE_VERSION",
    "DSP_REVIT_LIVE_TFM",
    "DSP_REVIT_LIVE_API_DIR",
    "DSP_PHASE_I_SEMANTIC_ID",
)
_BASELINE_MM = 200.0
_TARGET_MM = 300.0
_RACE_MM = 201.0


class PhaseILiveConfigurationError(ValueError):
    """真实双 Host 验收配置不完整或 fixture 证据不可信时的稳定错误。"""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PhaseILiveConfig:
    """真实双 Host 验收所需的显式环境、身份和 fixture 证据。"""

    autocad_endpoint: str
    autocad_document_ref: str
    autocad_fixture_path: Path
    autocad_fixture_sha256: str
    autocad_native_id: str
    autocad_host_instance_id: str
    revit_pipe: str
    revit_document_ref: str
    revit_fixture_path: Path
    revit_fixture_sha256: str
    revit_wall_unique_id: str
    revit_host_instance_id: str
    revit_version: str
    revit_tfm: str
    revit_api_dir: Path
    semantic_id: str

    @staticmethod
    def required_environment_variables() -> tuple[str, ...]:
        """返回 Task16 冻结的完整环境变量集合。"""
        return _REQUIRED_ENVIRONMENT

    @classmethod
    def from_environment(cls) -> PhaseILiveConfig:
        """从进程环境构造配置，并在任何 Host I/O 前校验 fixture 哈希。"""
        values: dict[str, str] = {}
        missing: list[str] = []
        for name in _REQUIRED_ENVIRONMENT:
            value = os.environ.get(name, "").strip()
            if not value:
                missing.append(name)
            else:
                values[name] = value
        if missing:
            raise PhaseILiveConfigurationError(
                "LIVE_ENV_MISSING",
                "missing Phase I live environment: " + ", ".join(missing),
            )

        config = cls(
            autocad_endpoint=values["DSP_AUTOCAD_ENDPOINT"],
            autocad_document_ref=values["DSP_AUTOCAD_DOCUMENT_REF"],
            autocad_fixture_path=Path(values["DSP_AUTOCAD_FIXTURE_PATH"]).resolve(),
            autocad_fixture_sha256=values["DSP_AUTOCAD_FIXTURE_SHA256"].lower(),
            autocad_native_id=values["DSP_AUTOCAD_NATIVE_ID"],
            autocad_host_instance_id=values["DSP_AUTOCAD_HOST_INSTANCE_ID"],
            revit_pipe=values["DSP_REVIT_LIVE_PIPE"],
            revit_document_ref=values["DSP_REVIT_LIVE_DOCUMENT_REF"],
            revit_fixture_path=Path(values["DSP_REVIT_LIVE_FIXTURE_PATH"]).resolve(),
            revit_fixture_sha256=values["DSP_REVIT_LIVE_FIXTURE_SHA256"].lower(),
            revit_wall_unique_id=values["DSP_REVIT_LIVE_WALL_UNIQUE_ID"],
            revit_host_instance_id=values["DSP_REVIT_LIVE_HOST_INSTANCE_ID"],
            revit_version=values["DSP_REVIT_LIVE_VERSION"],
            revit_tfm=values["DSP_REVIT_LIVE_TFM"],
            revit_api_dir=Path(values["DSP_REVIT_LIVE_API_DIR"]).resolve(),
            semantic_id=values["DSP_PHASE_I_SEMANTIC_ID"],
        )
        verify_fixture_sha256(config.autocad_fixture_path, config.autocad_fixture_sha256)
        verify_fixture_sha256(config.revit_fixture_path, config.revit_fixture_sha256)
        if config.revit_version != "2027" or config.revit_tfm != "net10.0-windows":
            raise PhaseILiveConfigurationError(
                "REVIT_BUILD_IDENTITY_MISMATCH",
                "Task16 requires Revit 2027 and net10.0-windows",
            )
        return config


def verify_fixture_sha256(path: Path, expected_sha256: str) -> str:
    """验证受控 fixture 字节与审核过的 SHA-256 完全一致。"""
    if not path.is_file():
        raise PhaseILiveConfigurationError(
            "FIXTURE_NOT_FOUND",
            f"controlled fixture does not exist: {path}",
        )
    normalized = expected_sha256.strip().lower()
    if len(normalized) != 64 or any(ch not in "0123456789abcdef" for ch in normalized):
        raise PhaseILiveConfigurationError(
            "FIXTURE_HASH_INVALID",
            "expected fixture SHA-256 must be lowercase hexadecimal",
        )
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    actual = digest.hexdigest()
    if actual != normalized:
        raise PhaseILiveConfigurationError(
            "FIXTURE_HASH_MISMATCH",
            f"fixture SHA-256 mismatch: expected {normalized}, got {actual}",
        )
    return actual


def _utc_now() -> str:
    """生成测试证据使用的规范 UTC RFC3339 时间。"""
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _utc_after(seconds: int) -> str:
    """生成相对当前时刻的规范 UTC RFC3339 时间。"""
    return (datetime.now(UTC) + timedelta(seconds=seconds)).isoformat().replace(
        "+00:00", "Z"
    )


def _run_async(awaitable):
    """在同步 coordinator 边界安全执行现有 AutoCAD async sidecar API。"""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(awaitable)
    raise RuntimeError("Task16 synchronous live harness cannot run inside an active event loop")


def _resolve_enterprise_terms(batch) -> dict[str, tuple[Any, str | None]]:
    """把真实 normalized facts 通过审核过的 enterprise mapping 投影成 canonical terms。"""
    catalog = yaml.safe_load(_ENTERPRISE_MAPPING.read_text(encoding="utf-8"))
    resolved: dict[str, tuple[Any, str | None]] = {}
    for fact in batch.facts:
        if fact.source_scheme is None or fact.source_code is None:
            continue
        matches: list[str] = []
        for rule in catalog["rules"]:
            if rule["source_scheme"] != fact.source_scheme:
                continue
            match = rule["match"]
            pattern = match["pattern"]
            candidate = fact.source_code
            if not match["case_sensitive"]:
                pattern = pattern.casefold()
                candidate = candidate.casefold()
            if match["type"] == "EXACT" and candidate == pattern or match["type"] == "PREFIX" and candidate.startswith(pattern):
                matches.append(rule["target_term_id"])
        if matches:
            if len(set(matches)) != 1:
                raise AssertionError("enterprise mapping produced ambiguous canonical term")
            resolved[matches[0]] = (fact.value, fact.unit)
    return resolved


def _wall_thickness_from_batch(batch) -> dict[str, Any]:
    """只接受映射后的 exact dsp:WallThickness mm canonical fact。"""
    terms = _resolve_enterprise_terms(batch)
    if "ifc:IfcWall" not in terms or "dsp:WallThickness" not in terms:
        raise AssertionError("normalized Host facts do not prove canonical wall thickness")
    value, unit = terms["dsp:WallThickness"]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise AssertionError("canonical wall thickness must be a finite number")
    if unit != "mm":
        raise AssertionError("canonical wall thickness must use mm")
    return {"value": float(value), "unit": "mm"}


def _native_target(execution_slice, *, native_id: str, native_kind: str):
    """构造一个 exact semantic-to-native 绑定证据。"""
    draft = NativeTargetBindingEvidence(
        semantic_id=execution_slice.execution_units[0].targets[0],
        host_type=execution_slice.host_runtime_ref.host_type,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        native_id=native_id,
        native_kind=native_kind,
        host_binding_fingerprint="0" * 64,
    )
    return replace(draft, host_binding_fingerprint=compute_host_binding_fingerprint(draft))


def _provider_snapshot(execution_slice, *, native_id: str, native_kind: str, valid_until: str):
    """用真实 persistent native identity 冻结一个 Step31 V2 provider snapshot。"""
    target = _native_target(execution_slice, native_id=native_id, native_kind=native_kind)
    unit = execution_slice.execution_units[0]
    candidate_draft = ProviderExecutionCandidate(
        provider_server=f"provider.{execution_slice.host_runtime_ref.host_type}.wall.live",
        provider_tool="set_wall_thickness",
        provider_version="1.0.0",
        canonical_operation=unit.canonical_operation,
        compatible_operation_versions=(unit.canonical_operation_version,),
        input_adapter_version="1.0.0",
        provider_native_constraints=(
            NativeConstraint(
                "native_kind",
                NativeConstraintOperator.EQ,
                (native_kind,),
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
        snapshot_id=f"PESV2-LIVE-{execution_slice.host_runtime_ref.host_type}",
        materialization_id=execution_slice.materialization_id,
        materialization_plan_hash=execution_slice.materialization_plan_hash,
        execution_slice_id=execution_slice.execution_slice_id,
        execution_slice_hash=execution_slice.execution_slice_hash,
        host_runtime_ref=execution_slice.host_runtime_ref,
        native_target_bindings=(target,),
        provider_candidates=(candidate,),
        candidate_binding_materials={candidate.candidate_fingerprint: material},
        valid_until=valid_until,
        snapshot_hash="0" * 64,
    )
    return replace(draft, snapshot_hash=compute_provider_snapshot_hash_v2(draft))


class _RecordingReadinessPort:
    """记录 production readiness 回执，不改变其判定。"""

    def __init__(self, delegate, receipts: dict[str, Any]) -> None:
        self._delegate = delegate
        self._receipts = receipts

    def check(self, execution_slice, authority, binding_set):
        receipt = self._delegate.check(execution_slice, authority, binding_set)
        self._receipts[execution_slice.materialization_id] = receipt
        return receipt


class PhaseIRealReadinessRegistry:
    """把 exact runtime ref 路由到两侧 production readiness port。"""

    def __init__(self, autocad_dispatcher, revit_transport) -> None:
        self.receipts: dict[str, Any] = {}
        self._ports = {
            "autocad": _RecordingReadinessPort(
                AutoCadWallThicknessReadinessPort(autocad_dispatcher),
                self.receipts,
            ),
            "revit": _RecordingReadinessPort(
                RevitWallThicknessReadinessPort(revit_transport),
                self.receipts,
            ),
        }

    def resolve(self, runtime_ref):
        """按 lowercase Host type 返回唯一 readiness port。"""
        try:
            return self._ports[runtime_ref.host_type]
        except KeyError as exc:
            raise KeyError(f"unsupported Phase I readiness Host: {runtime_ref.host_type}") from exc


class _ObservationStore:
    """只保存已规范化 canonical post-state 和真实 Host revision 证据。"""

    def __init__(self) -> None:
        self.items: dict[str, dict[str, Any]] = {}
        self.race_wall_thickness: dict[str, Any] | None = None

    def record(self, materialization_id: str, *, host_type: str, thickness, revision: int) -> None:
        self.items[materialization_id] = {
            "host_type": host_type,
            "wall_thickness": dict(thickness),
            "revision": revision,
        }


class AutoCadMaterializedExecutionPort:
    """使用现有 AutoCAD CommandDispatcher 执行 exact wall-thickness Slice。"""

    def __init__(self, dispatcher, receipts: dict[str, Any], observations: _ObservationStore) -> None:
        self._dispatcher = dispatcher
        self._receipts = receipts
        self._observations = observations

    def execute(self, execution_slice, authority, binding_set):
        """以 readiness-time revision 串行提交 AutoCAD 300 mm mutation。"""
        receipt = self._receipts[execution_slice.materialization_id]
        if receipt.status is not ReadinessStatus.READY:
            raise AssertionError("AutoCAD mutation requires a READY receipt")
        target = binding_set.bindings[0].native_targets[0]
        before_batch = _run_async(self._dispatcher.extract_design_facts([target.native_id]))
        before = _wall_thickness_from_batch(before_batch)
        if before != {"value": _BASELINE_MM, "unit": "mm"}:
            raise AssertionError(f"AutoCAD controlled baseline must be {_BASELINE_MM} mm")
        before_revisions = {fact.source_revision for fact in before_batch.facts}
        if before_revisions != {receipt.observed_revision}:
            raise AssertionError("AutoCAD state changed after readiness and before mutation")

        result = _run_async(
            self._dispatcher.set_wall_thickness(
                [target.native_id],
                _TARGET_MM,
                idempotency_key=f"phase-i-autocad-{uuid.uuid4().hex}",
                revision=receipt.observed_revision,
            )
        )
        if not result.ok:
            code = result.error.error_code if result.error is not None else "AUTOCAD_HOST_ERROR"
            raise AssertionError(f"AutoCAD live mutation failed: {code}")
        if not isinstance(result.revision_after, int) or result.revision_after <= receipt.observed_revision:
            raise AssertionError("AutoCAD success requires a strictly newer revision_after")

        after_batch = _run_async(self._dispatcher.extract_design_facts([target.native_id]))
        after = _wall_thickness_from_batch(after_batch)
        if after != {"value": _TARGET_MM, "unit": "mm"}:
            raise AssertionError("AutoCAD post-state is not exact 300 mm")
        self._observations.record(
            execution_slice.materialization_id,
            host_type="autocad",
            thickness=after,
            revision=result.revision_after,
        )
        return HostCommitted(
            actual_delta=_signed_v2_delta(
                execution_slice=execution_slice,
                authority=authority,
                binding_set=binding_set,
                revision_before=receipt.observed_revision,
                revision_after=result.revision_after,
                actual_delta_id=f"AD-LIVE-AUTOCAD-{result.command_id}",
            ),
            committed_at=_utc_now(),
        )


class RevitMaterializedExecutionPort:
    """通过 production Revit command/result adapters 执行 exact wall materialization。"""

    def __init__(
        self,
        transport,
        config: PhaseILiveConfig,
        receipts: dict[str, Any],
        observations: _ObservationStore,
        *,
        inject_external_revision_race: bool,
    ) -> None:
        self._transport = transport
        self._config = config
        self._receipts = receipts
        self._observations = observations
        self._inject_external_revision_race = inject_external_revision_race

    def execute(self, execution_slice, authority, binding_set):
        """使用 readiness revision 执行 Revit；partial 场景先做一条合法外部 201 mm edit。"""
        receipt = self._receipts[execution_slice.materialization_id]
        if receipt.status is not ReadinessStatus.READY:
            raise AssertionError("Revit mutation requires a READY receipt")
        target = binding_set.bindings[0].native_targets[0]
        baseline = self._read_state(
            target.native_id,
            execution_slice.host_runtime_ref.document_ref,
        )
        if baseline["wall_thickness"] != {"value": _BASELINE_MM, "unit": "mm"}:
            raise AssertionError(f"Revit controlled baseline must be {_BASELINE_MM} mm")
        if baseline["revision"] != receipt.observed_revision:
            raise AssertionError("Revit state changed after readiness and before mutation")

        if self._inject_external_revision_race:
            race = self._request_mutation(
                document_ref=execution_slice.host_runtime_ref.document_ref,
                wall_unique_id=target.native_id,
                expected_revision=receipt.observed_revision,
                thickness_mm=_RACE_MM,
                marker="race",
            )
            if race.get("status") != "OK":
                raise AssertionError("external Revit race edit did not commit")
            race_payload = race.get("payload") or {}
            race_value = race_payload.get("width_after_mm")
            if not isinstance(race_value, (int, float)) or isinstance(race_value, bool):
                raise AssertionError("external Revit race lacks truthful width_after_mm")
            self._observations.race_wall_thickness = {
                "value": float(race_value),
                "unit": "mm",
            }

        response = self._request_mutation(
            document_ref=execution_slice.host_runtime_ref.document_ref,
            wall_unique_id=target.native_id,
            expected_revision=receipt.observed_revision,
            thickness_mm=_TARGET_MM,
            marker="saga",
        )
        adapted = RevitExecutionResultAdapter.adapt(
            admitted_authority=_v1_authority_view(authority),
            document_ref=execution_slice.host_runtime_ref.document_ref,
            approved_semantic_wall_id=execution_slice.execution_units[0].targets[0],
            host_result=response,
            occurred_at=_utc_now(),
        )
        if isinstance(adapted, HostFailed):
            return adapted

        committed = _upgrade_revit_commit_to_v2(adapted, execution_slice)
        payload = response.get("payload") or {}
        batch = RevitDesignFactAdapter().normalize_snapshot(
            {
                "document_id": execution_slice.host_runtime_ref.document_ref,
                "host_instance_id": execution_slice.host_runtime_ref.host_instance_id,
                "source_revision": committed.actual_delta.revision_after,
                "native_id": payload.get("wall_unique_id"),
                "native_kind": "Wall",
                "builtin_category": "OST_Walls",
                "wall_thickness_mm": payload.get("width_after_mm"),
            }
        )
        after = _wall_thickness_from_batch(batch)
        if after != {"value": _TARGET_MM, "unit": "mm"}:
            raise AssertionError("Revit post-state is not exact 300 mm")
        self._observations.record(
            execution_slice.materialization_id,
            host_type="revit",
            thickness=after,
            revision=committed.actual_delta.revision_after,
        )
        return committed

    def _read_state(self, wall_unique_id: str, document_ref: str) -> dict[str, Any]:
        """通过现有只读 readiness Host operation 获取当前 Revit 宽度和 revision。"""
        from host_contracts import HostCommand, HostEntityRef

        command = HostCommand(
            command_id=f"READ-PHASE-I-{uuid.uuid4().hex}",
            document_id=document_ref,
            mode="READ",
            operation="check_wall_thickness_readiness",
            target_native_refs=[
                HostEntityRef(
                    document_id=document_ref,
                    native_id=wall_unique_id,
                    native_type="Wall",
                )
            ],
            arguments={"thickness": {"value": _TARGET_MM, "unit": "mm"}},
            preconditions=[],
            idempotency_key=None,
        )
        response = self._transport.request(command)
        if response.get("status") != "OK":
            raise AssertionError("Revit baseline READ failed")
        payload = response.get("payload") or {}
        width = payload.get("current_width") or {}
        revision = response.get("revision_after")
        if width.get("unit") != "mm" or not isinstance(revision, int):
            raise AssertionError("Revit baseline READ lacks canonical mm/revision evidence")
        return {
            "wall_thickness": {"value": float(width["value"]), "unit": "mm"},
            "revision": revision,
        }

    def _request_mutation(
        self,
        *,
        document_ref: str,
        wall_unique_id: str,
        expected_revision: int,
        thickness_mm: float,
        marker: str,
    ) -> dict[str, Any]:
        """构造并发送一条现有 Revit set_wall_thickness HostCommand。"""
        command = RevitHostAdapter.build_set_wall_thickness_command(
            command_id=f"CMD-PHASE-I-{marker}-{uuid.uuid4().hex}",
            document_id=document_ref,
            wall_unique_id=wall_unique_id,
            expected_revision=expected_revision,
            thickness_mm=thickness_mm,
            idempotency_key=f"phase-i-revit-{marker}-{uuid.uuid4().hex}",
        )
        return self._transport.request(command)


def _v1_authority_view(authority) -> AdmittedExecutionAuthority:
    """仅为现有 Revit result adapter 提供共同字段视图，不改变 V2 coordinator authority。"""
    return AdmittedExecutionAuthority(
        approval_hash=authority.approval_hash,
        grant_hash=authority.grant_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        execution_slice_hash=authority.execution_slice_hash,
        binding_set_hash=authority.binding_set_hash,
        host_instance_id=authority.host_instance_id,
        admitted_at=authority.admitted_at,
    )


def _upgrade_revit_commit_to_v2(committed: HostCommitted, execution_slice) -> HostCommitted:
    """把 production Revit normalized delta 补上 V2 source-unit lineage 并重签公共 hash。"""
    unit_hash = execution_slice.execution_units[0].execution_unit_hash
    changes = []
    for change in committed.actual_delta.changes:
        draft = replace(
            change,
            source_execution_unit_hash=unit_hash,
            actual_change_hash="0" * 64,
        )
        changes.append(replace(draft, actual_change_hash=compute_actual_change_hash(draft)))
    delta_draft = replace(
        committed.actual_delta,
        changes=tuple(changes),
        actual_delta_hash="0" * 64,
    )
    delta = replace(
        delta_draft,
        actual_delta_hash=compute_actual_delta_hash(delta_draft),
    )
    return HostCommitted(actual_delta=delta, committed_at=committed.committed_at)


def _signed_v2_delta(
    *,
    execution_slice,
    authority,
    binding_set,
    revision_before: int,
    revision_after: int,
    actual_delta_id: str,
) -> ActualDelta:
    """为 AutoCAD 真实提交构造 provider-neutral V2 ActualDelta。"""
    unit = execution_slice.execution_units[0]
    change_draft = ActualChange(
        change_kind=ActualChangeKind.MODIFY,
        semantic_id=unit.targets[0],
        canonical_kind="ifc:IfcWall",
        changed_aspects=(CanonicalAspect.PROPERTIES,),
        source_execution_unit_hash=unit.execution_unit_hash,
        actual_change_hash="0" * 64,
    )
    change = replace(
        change_draft,
        actual_change_hash=compute_actual_change_hash(change_draft),
    )
    delta_draft = ActualDelta(
        actual_delta_id=actual_delta_id,
        grant_hash=authority.grant_hash,
        binding_set_hash=binding_set.binding_set_hash,
        execution_slice_hash=execution_slice.execution_slice_hash,
        changeset_hash=authority.changeset_hash,
        approved_scope_hash=authority.approved_scope_hash,
        host_instance_id=authority.host_instance_id,
        document_ref=execution_slice.host_runtime_ref.document_ref,
        revision_before=revision_before,
        revision_after=revision_after,
        changes=(change,),
        actual_delta_hash="0" * 64,
    )
    return replace(
        delta_draft,
        actual_delta_hash=compute_actual_delta_hash(delta_draft),
    )


class PhaseIConvergenceEvidencePort:
    """只从真实 Host facts 形成的 provider-neutral VerificationEvidenceBundle 生成 convergence evidence。"""

    def __init__(self, changeset, observations: _ObservationStore) -> None:
        self._changeset = changeset
        self._observations = observations
        self.bundles: dict[str, VerificationEvidenceBundle] = {}
        self.evidence: dict[str, Any] = {}

    def build_bundle(
        self,
        *,
        execution_slice,
        actual_delta,
        canonical_changeset,
        approval_scope_boundary,
    ):
        """把 canonical post-state 封装成 Step33 可验证的真实证据 bundle。"""
        observation = self._observations.items[execution_slice.materialization_id]
        thickness = observation["wall_thickness"]
        marker = execution_slice.host_runtime_ref.host_type
        environment = SemanticEnvironmentRef(
            canonical_changeset.semantic_environment_ref.environment_id,
            canonical_changeset.semantic_environment_ref.content_hash,
        )
        fact_hash = canonical_hash(
            {
                "materialization_id": execution_slice.materialization_id,
                "revision": observation["revision"],
                "dsp:WallThickness": thickness,
            }
        )
        projection = SemanticProjectionRef(
            projection_id=f"PROJ-LIVE-{marker}-{actual_delta.revision_after}",
            projection_hash=canonical_hash({"projection": fact_hash, "host": marker}),
            semantic_model_version="ifc43+phase-i-live",
            provider_set_hash=canonical_hash({"provider": marker, "mode": "live"}),
            mapping_profile_set_hash=canonical_hash(
                {"mapping": "enterprise_mappings_v1", "host": marker}
            ),
            normalized_fact_batch_hash=fact_hash,
        )
        snapshot = SemanticSnapshot(
            snapshot_id=f"PS-LIVE-{marker}-{actual_delta.revision_after}",
            kind=SnapshotKind.PLANNING,
            project_id=canonical_changeset.project_id,
            freshness_contract_id=f"FC-LIVE-{marker}",
            freshness_contract_hash=canonical_hash(
                {"freshness": "post-commit", "revision": actual_delta.revision_after}
            ),
            document_ref=actual_delta.document_ref,
            base_host_revision=str(actual_delta.revision_after),
            coverage=Coverage(actual_delta.document_ref, tuple(execution_slice.execution_units[0].targets)),
            projection_ref=projection,
            semantic_environment_ref=environment,
            aspect_guarantees=(),
            hash=canonical_hash(
                {
                    "snapshot": fact_hash,
                    "delta": actual_delta.actual_delta_hash,
                }
            ),
        )
        subject = VerificationSubjectEvidence(
            semantic_id=execution_slice.execution_units[0].targets[0],
            canonical_kind="ifc:IfcWall",
            properties={"dsp:WallThickness": thickness},
            placement=None,
            geometry_evidence=None,
            relationships=(),
            constraints=(),
            classification=("ifc:IfcWall",),
            evidence_aspects=(CanonicalAspect.PROPERTIES,),
            snapshot_id=snapshot.snapshot_id,
            snapshot_hash=snapshot.hash,
            projection_ref=projection,
        )
        contract = SET_WALL_THICKNESS_V1.verification_contract
        draft = VerificationEvidenceBundle(
            evidence_bundle_id=f"VEB-LIVE-{marker}-{actual_delta.revision_after}",
            changeset_hash=canonical_changeset.changeset_hash,
            execution_slice_hash=execution_slice.execution_slice_hash,
            actual_delta_hash=actual_delta.actual_delta_hash,
            semantic_environment_ref=environment,
            post_execution_snapshot_ref=snapshot,
            post_execution_projection_ref=projection,
            base_host_revision=str(actual_delta.revision_after),
            baseline_snapshot_ref=None,
            baseline_projection_ref=None,
            contract_evidence=(
                VerificationContractEvidence(
                    contract_ref=canonical_hash(contract),
                    contract_body=contract,
                ),
            ),
            subject_evidence=(subject,),
            baseline_subject_evidence=(),
            evidence_bundle_hash="0" * 64,
        )
        bundle = replace(
            draft,
            evidence_bundle_hash=compute_verification_evidence_bundle_hash(draft),
        )
        self.bundles[execution_slice.materialization_id] = bundle
        return bundle

    def build_evidence(
        self,
        *,
        materialization_id,
        execution_slice,
        actual_delta,
        verification_result,
        verification_bundle,
        convergence_profile,
    ):
        """调用 production convergence builder，不读取 Host-native JSON。"""
        evidence = build_materialization_canonical_evidence(
            materialization_id=materialization_id,
            execution_slice=execution_slice,
            actual_delta=actual_delta,
            verification_result=verification_result,
            verification_evidence_bundle=verification_bundle,
            convergence_profile=convergence_profile,
        )
        self.evidence[materialization_id] = evidence
        return evidence


class _HostRegistry:
    """按 frozen Host order 的 runtime ref 解析真实执行 port。"""

    def __init__(self, autocad_port, revit_port) -> None:
        self._ports = {"autocad": autocad_port, "revit": revit_port}

    def resolve(self, runtime_ref):
        return self._ports[runtime_ref.host_type]


class _UtcClock:
    """为 live evidence 提供真实 UTC 审计时间。"""

    def now(self) -> str:
        return _utc_now()


def _build_context(config: PhaseILiveConfig):
    """仅用 Tasks 1–8 公共 V2 API 构造 exact two-materialization authority chain。"""
    topology_slots = (
        slot("MS-AUTOCAD", config.semantic_id, "autocad", config.autocad_document_ref),
        slot("MS-REVIT", config.semantic_id, "revit", config.revit_document_ref),
    )
    case = build_case(targets=(config.semantic_id,), topology_slots=topology_slots)
    materialization_plan = MaterializationPlanner().plan(
        MaterializationPlanningRequest(
            canonical_changeset=case.changeset,
            approval_scope_boundary=case.boundary_v2,
            topology_snapshot=case.topology,
            convergence_profile=case.profile,
        )
    )
    slot_by_id = {item.materialization_slot_id: item for item in case.topology.slots}
    host_ids = {
        "autocad": config.autocad_host_instance_id,
        "revit": config.revit_host_instance_id,
    }
    routes = tuple(
        MaterializationRuntimeRoute(
            materialization_id=intent.materialization_id,
            host_runtime_ref=HostRuntimeRef(
                host_type=intent.required_host_type,
                host_instance_id=host_ids[intent.required_host_type],
                document_ref=slot_by_id[intent.materialization_slot_id].document_ref,
            ),
        )
        for intent in materialization_plan.intents
    )
    routing = MaterializationRoutingEvidence(
        routing_snapshot_id=f"MRS-PHASE-I-LIVE-{uuid.uuid4().hex}",
        routes=routes,
        routing_snapshot_hash=compute_materialization_routing_hash(routes),
    )
    execution_plan = plan_materialized_execution(
        ExecutionPlanningRequestV2(
            canonical_changeset=case.changeset,
            approval_scope_boundary=case.boundary_v2,
            materialization_plan=materialization_plan,
            topology_snapshot=case.topology,
            runtime_routing_evidence=routing,
        )
    )

    store = InMemoryGatewayAuthorizationStoreV2()
    gateway = GatewayAuthorizationServiceV2(store)
    approved_at = _utc_after(-60)
    consumed_at = _utc_now()
    expires_at = _utc_after(7200)
    admission_draft = ApprovalAdmission(
        admission_id=f"ADM-PHASE-I-LIVE-{uuid.uuid4().hex}",
        changeset_hash=case.changeset.changeset_hash,
        approved_scope_hash=case.boundary_v2.scope_hash,
        semantic_environment_ref=case.changeset.semantic_environment_ref,
        approver="user:phase-i-live-operator",
        policy_snapshot_hash=canonical_hash({"policy": "phase-i-live-controlled"}),
        policy_allowed_operations=("set_wall_thickness.v1",),
        approved_at=approved_at,
        expires_at=expires_at,
        admission_fingerprint="0" * 64,
    )
    admission = replace(
        admission_draft,
        admission_fingerprint=compute_admission_fingerprint(admission_draft),
    )
    approval = gateway.consume_approval(
        ApprovalConsumptionRequestV2(
            admission=admission,
            canonical_changeset=case.changeset,
            approval_scope_boundary=case.boundary_v2,
            consumed_at=consumed_at,
        )
    )

    binding_sets = []
    authorities = []
    for execution_slice in execution_plan.execution_slices:
        host_type = execution_slice.host_runtime_ref.host_type
        native_id = (
            config.autocad_native_id
            if host_type == "autocad"
            else config.revit_wall_unique_id
        )
        native_kind = "LWPOLYLINE" if host_type == "autocad" else "Wall"
        snapshot = _provider_snapshot(
            execution_slice,
            native_id=native_id,
            native_kind=native_kind,
            valid_until=expires_at,
        )
        binding_set = resolve_provider_bindings_v2(execution_slice, snapshot)
        grant = gateway.issue_execution_grant(
            ExecutionGrantRequestV2(
                approval_id=approval.approval_id,
                execution_plan=execution_plan,
                execution_slice=execution_slice,
                provider_binding_set=binding_set,
                materialization_plan=materialization_plan,
                topology_snapshot=case.topology,
                approval_scope_boundary=case.boundary_v2,
                issued_at=_utc_now(),
            )
        )
        authority = gateway.admit_execution_grant(grant.grant_hash, _utc_now())
        binding_sets.append(binding_set)
        authorities.append(authority)

    return SimpleNamespace(
        case=case,
        materialization_plan=materialization_plan,
        execution_plan=execution_plan,
        binding_sets=tuple(binding_sets),
        authorities=tuple(authorities),
    )


def _build_harness(config: PhaseILiveConfig, *, inject_external_revision_race: bool):
    """组合真实 readiness、真实 Host mutation、V2 reconciliation 与 convergence。"""
    ctx = _build_context(config)
    autocad_host = AutoCadHostAdapter(
        pipe_name=config.autocad_endpoint,
        transport=AutoCadPipeTransport(config.autocad_endpoint),
    )
    autocad_dispatcher = AutoCadCommandDispatcher(autocad_host)
    revit_transport = NamedPipeTransport(pipe_name=config.revit_pipe)
    readiness_registry = PhaseIRealReadinessRegistry(autocad_dispatcher, revit_transport)
    observations = _ObservationStore()
    host_registry = _HostRegistry(
        AutoCadMaterializedExecutionPort(
            autocad_dispatcher,
            readiness_registry.receipts,
            observations,
        ),
        RevitMaterializedExecutionPort(
            revit_transport,
            config,
            readiness_registry.receipts,
            observations,
            inject_external_revision_race=inject_external_revision_race,
        ),
    )
    reconciliation = ExecutionReconciliationServiceV2(
        store=InMemoryExecutionSagaStoreV2()
    )
    evidence_port = PhaseIConvergenceEvidencePort(ctx.case.changeset, observations)
    coordinator = MaterializedExecutionSagaCoordinator(
        readiness_barrier=CrossHostReadinessBarrier(readiness_registry),
        reconciliation=reconciliation,
        host_registry=host_registry,
        evidence_port=evidence_port,
        convergence_verifier=CrossHostConvergenceVerifier(),
        clock=_UtcClock(),
    )
    return SimpleNamespace(
        ctx=ctx,
        readiness_registry=readiness_registry,
        observations=observations,
        reconciliation=reconciliation,
        evidence_port=evidence_port,
        coordinator=coordinator,
    )


def _execute(harness):
    """调用 materialized coordinator 的冻结七输入入口。"""
    ctx = harness.ctx
    return harness.coordinator.execute(
        ctx.case.changeset,
        ctx.case.boundary_v2,
        ctx.materialization_plan,
        ctx.execution_plan,
        ctx.binding_sets,
        ctx.authorities,
        ctx.case.profile,
    )


def _evidence_record(harness, result) -> dict[str, Any]:
    """从 durable V2 store 与 canonical evidence 生成紧凑、可复制的 live 证据记录。"""
    ctx = harness.ctx
    stored = harness.reconciliation.get_saga(result.saga_id)
    if stored is None:
        raise AssertionError("materialized coordinator did not persist Saga V2")
    slices_by_hash = {
        item.execution_slice_hash: item for item in stored.slice_states
    }
    host_by_slice = {
        item.execution_slice_hash: item.host_runtime_ref.host_type
        for item in ctx.execution_plan.execution_slices
    }
    state_by_host = {
        host_by_slice[slice_hash]: state
        for slice_hash, state in slices_by_hash.items()
    }
    observations_by_host = {
        item["host_type"]: item for item in harness.observations.items.values()
    }
    receipts = tuple(harness.readiness_registry.receipts.values())
    readiness_status = (
        "READY"
        if len(receipts) == 2 and all(item.status is ReadinessStatus.READY for item in receipts)
        else "NOT_READY"
    )
    convergence_status = (
        stored.convergence_outcome.value
        if stored.convergence_outcome is not None
        else None
    )
    record = {
        "required_hosts": [
            intent.required_host_type for intent in ctx.materialization_plan.intents
        ],
        "changeset_hash": ctx.case.changeset.changeset_hash,
        "scope_hash": ctx.case.boundary_v2.scope_hash,
        "topology_hash": ctx.case.topology.topology_snapshot_hash,
        "materialization_plan_hash": ctx.materialization_plan.materialization_plan_hash,
        "required_set_hash": ctx.materialization_plan.required_set_hash,
        "execution_slice_hashes": {
            item.host_runtime_ref.host_type: item.execution_slice_hash
            for item in ctx.execution_plan.execution_slices
        },
        "binding_set_hashes": {
            item.bindings[0].host_runtime_ref.host_type: item.binding_set_hash
            for item in ctx.binding_sets
        },
        "grant_hashes": {
            item.host_instance_id: item.grant_hash for item in ctx.authorities
        },
        "readiness_receipt_hashes": {
            item.host_runtime_ref.host_type: item.receipt_hash for item in receipts
        },
        "readiness_status": readiness_status,
        "autocad_post_wall_thickness": observations_by_host.get("autocad", {}).get(
            "wall_thickness"
        ),
        "revit_post_wall_thickness": observations_by_host.get("revit", {}).get(
            "wall_thickness"
        ),
        "autocad_actual_delta_hash": state_by_host["autocad"].actual_delta_hash,
        "revit_actual_delta_hash": state_by_host["revit"].actual_delta_hash,
        "autocad_verification_hash": state_by_host["autocad"].verification_hash,
        "revit_verification_hash": state_by_host["revit"].verification_hash,
        "autocad_slice_status": state_by_host["autocad"].status.value,
        "revit_slice_status": state_by_host["revit"].status.value,
        "race_wall_thickness": harness.observations.race_wall_thickness,
        "revit_failure_ref": result.failure_ref,
        "revit_failure_phase": (
            "BEFORE_COMMIT"
            if result.failure_ref == "REVISION_CONFLICT"
            else None
        ),
        "convergence_status": convergence_status,
        "convergence_result_hash": stored.convergence_result_hash,
        "saga_status": stored.status.value,
        "materialized_status": result.status.value,
    }
    print(json.dumps(record, ensure_ascii=False, sort_keys=True))
    return record


def run_positive_acceptance(config: PhaseILiveConfig) -> dict[str, Any]:
    """运行真实 200→300 mm 双 Host 正向 acceptance，并返回完整哈希证据。"""
    verify_fixture_sha256(config.autocad_fixture_path, config.autocad_fixture_sha256)
    verify_fixture_sha256(config.revit_fixture_path, config.revit_fixture_sha256)
    harness = _build_harness(config, inject_external_revision_race=False)
    result = _execute(harness)
    return _evidence_record(harness, result)


def run_partial_commit_acceptance(config: PhaseILiveConfig) -> dict[str, Any]:
    """运行 AutoCAD 成功后 Revit 201 mm 外部 revision race 的真实 partial-commit acceptance。"""
    verify_fixture_sha256(config.autocad_fixture_path, config.autocad_fixture_sha256)
    verify_fixture_sha256(config.revit_fixture_path, config.revit_fixture_sha256)
    harness = _build_harness(config, inject_external_revision_race=True)
    result = _execute(harness)
    return _evidence_record(harness, result)


__all__ = [
    "AutoCadMaterializedExecutionPort",
    "PhaseIConvergenceEvidencePort",
    "PhaseILiveConfig",
    "PhaseILiveConfigurationError",
    "PhaseIRealReadinessRegistry",
    "RevitMaterializedExecutionPort",
    "run_partial_commit_acceptance",
    "run_positive_acceptance",
    "verify_fixture_sha256",
]
