"""Task 16：只组合现有 production owners，审计真实调用，不替换领域结果。"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from contextlib import AsyncExitStack, ExitStack, contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from functools import wraps
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.parse import urlsplit
from uuid import uuid4

from .cross_host_product_live_driver import (
    audit_imported_product_sources,
    check_frozen_head,
    pipe_pid,
    plain,
    read_json,
    write_once,
)


@contextmanager
def audit_public_method(owner_class, name, capture, *, capture_result=False):
    """只在单场景子进程中装饰公开方法，原调用/返回/异常保持原样并 finally 恢复。"""

    original = getattr(owner_class, name)

    @wraps(original)
    def audited(owner, *args, **kwargs):
        result = original(owner, *args, **kwargs)
        capture(result if capture_result else args[0])
        return result

    with patch.object(owner_class, name, audited):
        yield


@contextmanager
def audit_runtime_owners(directory, *, check_head):
    """只在 dedicated MCP 子进程内审计指定 production public owner 写入。"""

    from design_approval_scope import InMemoryApprovalScopeStore
    from design_changeset import InMemoryChangeSetStore
    from design_convergence import CrossHostConvergenceVerifier
    from design_execution_coordination import CrossHostReadinessBarrier
    from design_execution_planning import InMemoryExecutionPlanV2Store
    from design_gateway_authorization import (
        GatewayAuthorizationServiceV2,
        InMemoryGatewayAuthorizationStoreV2,
    )
    from design_materialization_planning import InMemoryMaterializationPlanStore
    from design_provider_binding import InMemoryProviderBindingSetV2Store

    def capture(kind, value):
        check_head()
        append_audit(
            directory / "owner-captures.jsonl",
            {
                "kind": kind,
                "storage_provenance": "AUDITED_IN_MEMORY_OWNER",
                "timestamp": datetime.now(UTC).isoformat(),
                "body": plain(value),
            },
        )

    methods = (
        (InMemoryChangeSetStore, "put", "changeset", False),
        (InMemoryApprovalScopeStore, "put_boundary", "scope", False),
        (InMemoryMaterializationPlanStore, "put", "materialization_plan", False),
        (InMemoryExecutionPlanV2Store, "put", "execution_plan", False),
        (InMemoryProviderBindingSetV2Store, "put", "binding_set", False),
        (InMemoryGatewayAuthorizationStoreV2, "issue_or_get_grant_v2", "grant", True),
        (GatewayAuthorizationServiceV2, "consume_or_get_approval", "approval", True),
        (CrossHostReadinessBarrier, "check_all", "readiness", True),
    )
    original_verify = CrossHostConvergenceVerifier.verify

    @wraps(original_verify)
    def audited_verify(owner, plan, profile, evidence_set):
        result = original_verify(owner, plan, profile, evidence_set)
        check_head()
        append_audit(
            directory / "convergence-captures.jsonl",
            {
                "plan": plain(plan),
                "profile": plain(profile),
                "evidence_set": plain(evidence_set),
                "result": plain(result),
            },
        )
        return result

    with ExitStack() as stack:
        stack.enter_context(patch.object(CrossHostConvergenceVerifier, "verify", audited_verify))
        for owner, method, kind, from_result in methods:
            stack.enter_context(
                audit_public_method(
                    owner,
                    method,
                    lambda value, kind=kind: capture(kind, value),
                    capture_result=from_result,
                )
            )
        yield


def reviewed_runtime_inputs(config, settings, scenario):
    """从审核身份与实际 fixture 构造既有 target/topology/policy contracts。"""

    from design_materialization_topology import (
        MaterializationRequirement,
        MaterializationSlot,
        MaterializationTopologySnapshot,
        compute_topology_snapshot_hash,
    )
    from design_product_front_door import (
        ConfiguredCrossHostMemberTarget,
        ConfiguredCrossHostWallThicknessTarget,
        ConfiguredProductApprovalPolicyV2,
    )
    from dsp_core_semantic_provider import DSP_CORE_PROVIDER
    from enterprise_mapping_provider import ENTERPRISE_MAPPING_PROVIDER
    from ifc43_semantic_provider import IFC43_PROVIDER
    from semantic_service import ProviderRef, SemanticEnvironmentStore, SemanticProviderRegistry

    # 使用公开 semantic owner pin API；不穿透 reference runtime 私有 environment。
    providers = (IFC43_PROVIDER, DSP_CORE_PROVIDER, ENTERPRISE_MAPPING_PROVIDER)
    registry = SemanticProviderRegistry()
    for provider in providers:
        registry.register(provider)
    environment = SemanticEnvironmentStore().pin(
        tuple(ProviderRef(item.manifest.provider_id, item.manifest.version) for item in providers),
        registry,
    )
    draft = MaterializationTopologySnapshot(
        topology_environment_id=settings["topology_environment_id"],
        topology_revision=settings["topology_revision"],
        slots=tuple(
            MaterializationSlot(
                materialization_slot_id=settings["slot_ids"][kind],
                semantic_target_ref=settings["semantic_target_id"],
                required_host_type=kind.lower(),
                document_ref=(
                    config.autocad_document_ref if kind == "AUTOCAD" else config.revit_document_ref
                ),
                requirement=MaterializationRequirement.REQUIRED,
            )
            for kind in ("AUTOCAD", "REVIT")
        ),
        topology_snapshot_hash="0" * 64,
    )
    topology = replace(draft, topology_snapshot_hash=compute_topology_snapshot_hash(draft))
    target = ConfiguredCrossHostWallThicknessTarget.create(
        candidate_key=settings["candidate_key"],
        project_id=settings["project_id"],
        semantic_target_id=settings["semantic_target_id"],
        semantic_environment_id=environment.environment_id,
        semantic_environment_hash=environment.content_hash,
        topology_environment_id=topology.topology_environment_id,
        topology_revision=topology.topology_revision,
        topology_snapshot_hash=topology.topology_snapshot_hash,
        members=(
            ConfiguredCrossHostMemberTarget(
                host_kind="AUTOCAD",
                role="BOUND_REQUIRED",
                configured_reference_id=settings["configured_reference_ids"]["AUTOCAD"],
                configured_reference_hash=config.autocad_fixture_sha256,
                transport_locator=config.autocad_endpoint,
                document_id=config.autocad_document_ref,
                native_target_id=config.autocad_native_id,
            ),
            ConfiguredCrossHostMemberTarget(
                host_kind="REVIT",
                role="INITIATOR",
                configured_reference_id=settings["configured_reference_ids"]["REVIT"],
                configured_reference_hash=config.revit_fixture_sha256,
                transport_locator=config.revit_pipe,
                document_id=config.revit_document_ref,
                native_target_id=config.revit_wall_unique_id,
            ),
        ),
    )
    policy_name = "deny" if scenario == "deny" else "positive"
    policy = ConfiguredProductApprovalPolicyV2.from_mapping(
        {
            **settings["policies"][policy_name],
            "version": "DSP_PRODUCT_APPROVAL_POLICY_V2",
            "project_ids": [target.project_id],
            "semantic_target_ids": [target.semantic_target_id],
            "reviewed_configuration_hash": target.reviewed_configuration_hash,
            "allowed_topology_snapshot_hashes": [target.topology_snapshot_hash],
            "required_host_roles": {"AUTOCAD": "BOUND_REQUIRED", "REVIT": "INITIATOR"},
        }
    )
    return target, topology, policy


def append_audit(path, body):
    """每个进程独立追加真实命令；不收集 transport 异常文本或环境凭据。"""

    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(plain(body), ensure_ascii=False, allow_nan=False) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def audited_pipe_ownership(config, directory, *, stage, check_head):
    """在生产 CreateFile 返回的同一 handle 上证明真实 server PID，再允许任何 WriteFile。"""

    import win32file
    import win32pipe

    reviewed = {
        rf"\\.\pipe\{locator}".casefold(): (kind, locator, host_id)
        for kind, locator, host_id in (
            ("AUTOCAD", config.autocad_endpoint, config.autocad_host_instance_id),
            ("REVIT", config.revit_pipe, config.revit_host_instance_id),
        )
    }
    original = win32file.CreateFile

    @wraps(original)
    def checked_create_file(path, *args, **kwargs):
        member = reviewed.get(str(path).casefold())
        if member is None:
            return original(path, *args, **kwargs)
        kind, locator, host_id = member
        check_head()
        handle = original(path, *args, **kwargs)
        try:
            server_pid = win32pipe.GetNamedPipeServerProcessId(handle)
            expected_pid = pipe_pid(locator, kind)
            append_audit(
                directory / "pipe-server-ownership.jsonl",
                {
                    "host_kind": kind,
                    "host_instance_id": host_id,
                    "locator": locator,
                    "server_pid": server_pid,
                    "expected_pid": expected_pid,
                    "stage": stage,
                    "observed_at": datetime.now(UTC).isoformat(),
                },
            )
            if server_pid != expected_pid:
                raise ValueError("LIVE_PLUGIN_PIPE_OWNER_MISMATCH: actual pipe server differs")
            check_head()
            return handle
        except BaseException:
            win32file.CloseHandle(handle)
            raise

    with patch.object(win32file, "CreateFile", checked_create_file):
        yield


def audited_host_factories(config, directory, *, check_head, stage="MCP"):
    """生产 adapter 的窄 decorator；AutoCAD 每次公开调用都在 finally 关闭 pipe。"""

    from autocad_sidecar.adapter.host_adapter import HostAdapter
    from autocad_sidecar.execution.command_dispatcher import CommandDispatcher
    from autocad_sidecar.ipc.transport import PipeTransport
    from revit_sidecar import NamedPipeTransport

    def record(kind, phase, command, response=None):
        check_head()
        body = {
            "host_kind": kind,
            "phase": phase,
            "command": command.to_dict(),
            "timestamp": datetime.now(UTC).isoformat(),
            "stage": stage,
        }
        if response is not None:
            body["response"] = (
                response.to_dict() if hasattr(response, "to_dict") else plain(response)
            )
        append_audit(directory / "host-commands.jsonl", body)

    class AuditedAutoCadHost(HostAdapter):
        async def send_command(self, command):
            record("AUTOCAD", "SEND", command)
            result = await super().send_command(command)
            record("AUTOCAD", "RECEIVE", command, result)
            return result

    class AuditedRevitTransport(NamedPipeTransport):
        def request(self, command):
            case = read_json(directory / "case.json")
            send_deadline = None
            if stage == "MCP" and case["scenario"] in {"unavailable", "partial_commit"}:
                from .cross_host_product_live_driver import stage_prerequisites
                from .cross_host_product_live_stages import (
                    stage_hash,
                    stage_identity,
                    stage_deadline_monotonic,
                    require_stage_deadline,
                    wait_for_stage_release,
                )

                if case["scenario"] == "unavailable" and command.mode == "EXECUTE":
                    raise ValueError("LIVE_STAGE_COMMAND_INVALID: execution before readiness")
                staged_operation = (
                    command.operation == "check_wall_thickness_readiness"
                    if case["scenario"] == "unavailable"
                    else command.mode == "EXECUTE"
                )
                if staged_operation:
                    frozen = read_json(directory / "frozen-submission.json")
                    binding = frozen["session_binding"]
                    member = next(
                        item for item in binding["members"] if item["host_kind"] == "REVIT"
                    )
                    prerequisites = stage_prerequisites(
                        config, directory, case, command, check_head=check_head
                    )
                    pending = stage_identity(
                        case,
                        {"task_id": frozen["request"]["task_id"],
                         "request_hash": frozen["request"]["request_hash"],
                         "session_binding_hash": binding["binding_hash"]},
                        member,
                        command,
                        prerequisite_hashes=prerequisites,
                        caller_started_at=read_json(
                            directory / "resume-attempt.json"
                        )["timestamp"],
                    )
                    # 发送侧只计算一次绝对 deadline；后续函数不得续租。
                    send_deadline = stage_deadline_monotonic(pending)
                    if (directory / "stage-controller-completion.json").exists():
                        raise ValueError("LIVE_STAGE_PRESELECTED: early operator action")
                    require_stage_deadline(send_deadline)
                    write_once(directory / "pending-stage.json", pending)
                    print(
                        "LIVE_AWAITING_STAGE: " + str(directory / "pending-stage.json"),
                        flush=True,
                    )
                    wait_for_stage_release(
                        directory, pending, proof_hash=stage_hash(prerequisites),
                        check_head=check_head, deadline=send_deadline,
                    )
                    require_stage_deadline(send_deadline)
                    write_once(
                        directory / "stage-send-attempt.json",
                        {"stage_id": pending["stage_id"], "pending_hash": pending["pending_hash"],
                         "command_id": command.command_id,
                         "command_hash": stage_hash(command.to_dict()),
                         "timestamp": datetime.now(UTC).isoformat()},
                    )
                    require_stage_deadline(send_deadline)
            if send_deadline is not None:
                from .cross_host_product_live_stages import require_stage_deadline

                require_stage_deadline(send_deadline)
            record("REVIT", "SEND", command)
            # AUDIT 写入也可能阻塞；最后一次检查必须紧邻原始 transport delegate。
            if send_deadline is not None:
                require_stage_deadline(send_deadline)
            result = super().request(command)
            record("REVIT", "RECEIVE", command, result)
            return result

    class AutoCadLease:
        async def _call(self, method, *args, **kwargs):
            async with AsyncExitStack() as resources:
                host = AuditedAutoCadHost(transport=PipeTransport(config.autocad_endpoint))
                resources.push_async_callback(host.close)
                dispatcher = CommandDispatcher(host)
                return await getattr(dispatcher, method)(*args, **kwargs)

        async def extract_design_facts(self, *args, **kwargs):
            return await self._call("extract_design_facts", *args, **kwargs)

        async def current_document(self, *args, **kwargs):
            return await self._call("current_document", *args, **kwargs)

        async def set_wall_thickness(self, *args, **kwargs):
            return await self._call("set_wall_thickness", *args, **kwargs)

    def auto(locator):
        if locator != config.autocad_endpoint:
            raise ValueError("LIVE_HOST_LOCATOR_MISMATCH: AUTOCAD")
        return AutoCadLease()

    def revit(locator):
        if locator != config.revit_pipe:
            raise ValueError("LIVE_HOST_LOCATOR_MISMATCH: REVIT")
        return AuditedRevitTransport(pipe_name=locator)

    return auto, revit


def read_host_observation(config, member, *, target, factories, command_id):
    """通过 production observation reader 发起 fresh READ 并核对 exact Host 身份。"""

    from design_product_runtime import CrossHostWallThicknessObservationReader

    reader = CrossHostWallThicknessObservationReader(
        autocad_dispatcher_factory=factories[0],
        revit_transport_factory=factories[1],
    )
    observed = reader.read(binding=target, member=member, command_id=command_id)
    expected = (
        config.autocad_host_instance_id
        if member.host_kind == "AUTOCAD"
        else config.revit_host_instance_id
    )
    if observed.host_instance_id != expected:
        raise ValueError("LIVE_HOST_IDENTITY_MISMATCH: observation differs from reviewed runtime")
    return observed


def production_probe_factory(config, target, factories, directory):
    """为原 SubmissionController 适配实际 native READ，不生成授权或执行计划。"""

    from design_fact_contracts import FactKind
    from design_provider_binding import (
        NativeTargetBindingEvidence,
        compute_host_binding_fingerprint,
    )
    from revit_sidecar import RevitCurrentContextProbe, RevitWallThicknessSnapshotReadPort

    class Probe:
        def __init__(self, kind, locator):
            self.member = target.member(kind)
            if locator != self.member.transport_locator:
                raise ValueError("LIVE_HOST_LOCATOR_MISMATCH: context probe")

        def discover(self, *, command_id, document_id):
            member = self.member
            if document_id != member.document_id:
                raise ValueError("LIVE_HOST_DOCUMENT_MISMATCH: context probe")
            if member.host_kind == "AUTOCAD":
                batch = asyncio.run(
                    factories[0](member.transport_locator).extract_design_facts(
                        [member.native_target_id]
                    )
                )
                facts = [
                    fact
                    for fact in batch.facts
                    if fact.fact_kind is FactKind.PROPERTY
                    and fact.predicate == "constant_width"
                    and fact.unit == "mm"
                    and fact.subject_native_ref.native_id == member.native_target_id
                    and fact.subject_native_ref.document_id == document_id
                    and fact.host_ref.document_id == document_id
                    and fact.subject_native_ref.native_kind == "LWPOLYLINE"
                ]
                if len(facts) != 1 or facts[0].value != 200:
                    raise ValueError("LIVE_AUTOCAD_BASELINE_INVALID: reviewed width missing")
                fact = facts[0]
                native_id, native_kind, host_type = member.native_target_id, "LWPOLYLINE", "autocad"
                host_instance = fact.host_ref.host_instance_id
                raw = batch.to_dict()
            else:
                transport = factories[1](member.transport_locator)
                context = RevitCurrentContextProbe(transport).discover(
                    command_id=command_id, document_id=document_id
                )
                if (
                    len(context.selected_elements) != 1
                    or context.selected_elements[0].unique_id != member.native_target_id
                    or context.selected_elements[0].native_kind != "Wall"
                ):
                    raise ValueError("LIVE_REVIT_SELECTION_INVALID: reviewed Wall missing")
                snapshot = RevitWallThicknessSnapshotReadPort(transport).read(
                    command_id=command_id + ":snapshot",
                    document_id=document_id,
                    host_instance_id=context.host_instance_id,
                    wall_unique_id=member.native_target_id,
                    expected_revision=context.revision,
                )
                if snapshot.wall_thickness_mm != 200:
                    raise ValueError("LIVE_REVIT_BASELINE_INVALID: reviewed width missing")
                native_id, native_kind, host_type = member.native_target_id, "Wall", "revit"
                host_instance = context.host_instance_id
                raw = {"context": plain(context), "snapshot": plain(snapshot)}
            expected = (
                config.autocad_host_instance_id
                if member.host_kind == "AUTOCAD"
                else config.revit_host_instance_id
            )
            if host_instance != expected:
                raise ValueError("LIVE_HOST_IDENTITY_MISMATCH: baseline differs")
            evidence = NativeTargetBindingEvidence(
                semantic_id=target.semantic_target_id,
                host_type=host_type,
                document_ref=document_id,
                native_id=native_id,
                native_kind=native_kind,
                host_binding_fingerprint="0" * 64,
            )
            write_once(
                directory / ("controller-baseline-" + member.host_kind.lower() + ".json"), raw
            )
            return SimpleNamespace(
                document_id=document_id,
                host_instance_id=host_instance,
                native_target_id=native_id,
                host_binding_fingerprint=compute_host_binding_fingerprint(evidence),
            )

    return Probe


def run_managed_mcp(directory):
    """专用进程中装配 production service/runtime；不接收任意外部 MCP authority flags。"""

    from design_product_front_door import (
        ConfiguredPolicyApprovalAdmissionPortV2,
        PostgresConfiguredPolicyAdmissionStore,
        SqliteSessionBindingReader,
        run_streamable_http,
    )
    from design_product_front_door.service import ProductFrontDoorService
    from design_product_runtime import build_cross_host_product_reference_runtime

    from .cross_host_product_live_support import CrossHostProductLiveConfig, _require_windows_live

    _require_windows_live()
    case = read_json(directory / "case.json")
    head = case["implementation_head"]

    def check_head():
        check_frozen_head(head)
        audit_imported_product_sources()

    check_head()
    settings = read_json(directory / "driver-settings.json")
    config = CrossHostProductLiveConfig.from_environment()
    target, topology, policy = reviewed_runtime_inputs(config, settings, case["scenario"])

    class Validator:
        def validate(self, binding):
            for key in (
                "project_id",
                "semantic_target_id",
                "semantic_environment_id",
                "semantic_environment_hash",
                "topology_environment_id",
                "topology_revision",
                "topology_snapshot_hash",
            ):
                if getattr(binding, key) != getattr(target, key):
                    raise ValueError("LIVE_REVIEWED_CONFIGURATION_MISMATCH: frozen target differs")
            if binding.initiating_host_kind != "REVIT" or [
                item.host_kind for item in binding.members
            ] != ["AUTOCAD", "REVIT"]:
                raise ValueError("LIVE_REVIEWED_MEMBERSHIP_MISMATCH: exact required order absent")
            for member in binding.members:
                configured = target.member(member.host_kind)
                for key in (
                    "role",
                    "configured_reference_id",
                    "configured_reference_hash",
                    "transport_locator",
                    "document_id",
                    "native_target_id",
                ):
                    if getattr(member, key) != getattr(configured, key):
                        raise ValueError("LIVE_REVIEWED_TARGET_MISMATCH: configured member differs")
                expected = (
                    config.autocad_host_instance_id
                    if member.host_kind == "AUTOCAD"
                    else config.revit_host_instance_id
                )
                if member.host_instance_id != expected:
                    raise ValueError("LIVE_REVIEWED_HOST_MISMATCH: actual runtime differs")

    class PolicySource:
        def load(self):
            check_head()
            return policy

    class Clock:
        def now(self):
            return datetime.now(UTC)

    with ExitStack() as resources:
        resources.enter_context(
            audited_pipe_ownership(config, directory, stage="MCP", check_head=check_head)
        )
        resources.enter_context(audit_runtime_owners(directory, check_head=check_head))

        class AdmissionFactory:
            def build(self, *, changeset_store, approval_scope_store, accepted_input_reader):
                store = PostgresConfiguredPolicyAdmissionStore(config.dsn)
                resources.callback(store.close)
                port = ConfiguredPolicyApprovalAdmissionPortV2(
                    changeset_store=changeset_store,
                    approval_scope_store=approval_scope_store,
                    accepted_input_reader=accepted_input_reader,
                    admission_store=store,
                    policy_source=PolicySource(),
                    clock=Clock(),
                    id_factory=lambda: "ADM-" + uuid4().hex,
                )

                class AuditedAdmission:
                    def request_approval(self, changeset_ref):
                        check_head()
                        changeset = changeset_store.get(changeset_ref.ref_id)
                        scope = approval_scope_store.get_boundary("SCOPE-" + changeset.changeset_id)
                        body = {
                            "task_id": changeset.task_id,
                            "changeset_ref": plain(changeset_ref),
                            "scope_hash": scope.scope_hash,
                            "policy": policy.snapshot_payload(),
                            "policy_snapshot_hash": policy.policy_snapshot_hash,
                        }
                        try:
                            result = port.request_approval(changeset_ref)
                        except Exception as exc:
                            code = str(exc).split(":", 1)[0]
                            body.update(
                                status="DENIED"
                                if code == "FRONT_DOOR_APPROVAL_POLICY_DENIED"
                                else "FAILED",
                                error_code=code
                                if code == "FRONT_DOOR_APPROVAL_POLICY_DENIED"
                                else "POLICY_CALL_FAILED",
                            )
                            append_audit(directory / "policy-attempts.jsonl", body)
                            raise
                        body.update(status="ADMITTED", admission=plain(result))
                        append_audit(directory / "policy-attempts.jsonl", body)
                        return result

                return AuditedAdmission()

        factories = audited_host_factories(config, directory, check_head=check_head)
        runtime = build_cross_host_product_reference_runtime(
            dsn=config.dsn,
            topology_snapshot=topology,
            autocad_dispatcher_factory=factories[0],
            revit_transport_factory=factories[1],
            approval_admission_factory=AdmissionFactory(),
        )
        resources.callback(runtime.close)
        reader = SqliteSessionBindingReader(str(directory / "front-door.sqlite3"))
        resources.callback(reader.close)
        service = ProductFrontDoorService(
            session_binding_reader=reader,
            candidate_source=None,
            context_probe=None,
            transport_factory=None,
            query_service=runtime.query_service,
            composition_pool=None,
            reviewed_configuration_validator=Validator(),
            accepted_input_store=runtime.request_store,
            proposal_decision_store=runtime.proposal_decision_store,
            decision_consume_gate=runtime.decision_consume_gate,
            interaction_subject_reader=runtime.artifact_store,
            cross_host_observation_reader=runtime.observation_reader,
            v2_flow_resolver=runtime.flow_resolver,
        )
        check_head()
        write_once(
            directory / "mcp-ready.json",
            {
                **case,
                "pid": os.getpid(),
                "topology": plain(topology),
                "target": plain(target),
                "policy": policy.snapshot_payload(),
                "policy_snapshot_hash": policy.policy_snapshot_hash,
                "service": type(service).__module__ + "." + type(service).__name__,
                "runtime_builder": build_cross_host_product_reference_runtime.__module__,
                "python_sources": audit_imported_product_sources(),
            },
        )
        parsed = urlsplit(config.mcp_url)
        run_streamable_http(service, host=parsed.hostname, port=parsed.port or 80)


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("LIVE_MCP_ARGUMENT_INVALID: one case directory required")
        run_managed_mcp(Path(sys.argv[1]).resolve())
    except Exception:
        # 不让底层异常中的 DSN/环境数据进入 workflow log。
        raise SystemExit(
            "LIVE_MCP_COMPOSITION_FAILED: inspect controlled owner artifacts"
        ) from None
