"""Task 16 driver：人工交接、exact-head 与真实资源生命周期的离线契约。"""

from __future__ import annotations

import importlib
import importlib.util
import json
from dataclasses import replace

import pytest

from tests.integration.cross_host_product_v2_proposal_authority import ReviewedV2Proposal
from tests.integration.test_cross_host_product_v2_proposal_authority import (
    _ArtifactReader,
    _case,
    _CheckpointReader,
    _Mcp,
)


def _driver():
    """缺少接线时以明确 capability assertion RED，不在 collection 隐藏错误。"""

    name = "tests.integration.cross_host_product_live_driver"
    assert importlib.util.find_spec(name) is not None, "controlled driver is missing"
    return importlib.import_module(name)


def _reviewed():
    frozen, view, checkpoint, subject = _case()
    pending = checkpoint.pending_interaction
    return ReviewedV2Proposal(frozen, view, pending.pause_id, pending.subject_ref, subject)


def _human(driver, reviewed, case_id="case-1", head="a" * 40):
    """离线输入模拟人工文件；真正 live 必须由 pytest 外部 controller 提供。"""

    return {
        **driver.human_lineage(reviewed, case_id=case_id, implementation_head=head),
        "decision": "ACCEPT",
        "resume_kind": "OPERATION_PROPOSAL_ACCEPTED",
        "decision_ref": "human-audit-1",
        "operator": "reviewer",
        "recorded_at": "2026-10-09T12:00:00Z",
    }


def test_pending_handoff_publishes_exact_owner_proposal_before_human(tmp_path):
    driver = _driver()
    reviewed = _reviewed()
    driver.publish_pending_proposal(tmp_path, reviewed, case_id="case-1", head="a" * 40)
    pending = json.loads((tmp_path / "pending-proposal.json").read_text())
    assert pending["lineage"] == driver.human_lineage(
        reviewed, case_id="case-1", implementation_head="a" * 40
    )
    assert pending["proposal"]["subject"]["canonical_operation"] == "set_wall_thickness.v1"
    assert pending["proposal"]["subject"]["canonical_arguments"]["thickness"]["value"] == 300
    assert not (tmp_path / "human-decision.json").exists()
    assert not (tmp_path / "resume-attempt.json").exists()


@pytest.mark.parametrize(
    "field",
    [
        "task_id",
        "request_hash",
        "session_binding_hash",
        "pause_id",
        "subject_ref",
        "subject_content_hash",
        "case_id",
        "implementation_head",
        "operator",
        "decision_ref",
    ],
)
def test_human_file_rejects_missing_or_mismatched_exact_authority(tmp_path, field):
    driver = _driver()
    reviewed = _reviewed()
    human = _human(driver, reviewed)
    human[field] = "" if field in {"operator", "decision_ref"} else "other"
    path = tmp_path / "human-decision.json"
    path.write_text(json.dumps(human))
    with pytest.raises(ValueError, match="LIVE_HUMAN"):
        driver.load_human_decision(path, reviewed, case_id="case-1", head="a" * 40)


def test_human_file_cannot_preselect_or_supply_rejection_as_accept(tmp_path):
    driver = _driver()
    reviewed = _reviewed()
    (tmp_path / "human-decision.json").write_text(json.dumps(_human(driver, reviewed)))
    with pytest.raises(ValueError, match="LIVE_HUMAN_PRESELECTED"):
        driver.publish_pending_proposal(tmp_path, reviewed, case_id="case-1", head="a" * 40)
    human = _human(driver, reviewed)
    human["resume_kind"] = "OPERATION_PROPOSAL_REJECTED"
    (tmp_path / "human-decision.json").write_text(json.dumps(human))
    with pytest.raises(ValueError, match="LIVE_HUMAN"):
        driver.load_human_decision(
            tmp_path / "human-decision.json", reviewed, case_id="case-1", head="a" * 40
        )


def test_await_human_timeout_keeps_pending_and_never_creates_accept(tmp_path):
    driver = _driver()
    reviewed = _reviewed()
    driver.publish_pending_proposal(tmp_path, reviewed, case_id="case-1", head="a" * 40)
    with pytest.raises(ValueError, match="LIVE_HUMAN_TIMEOUT"):
        driver.await_human_decision(
            tmp_path,
            reviewed,
            case_id="case-1",
            head="a" * 40,
            timeout_seconds=0.01,
            check_head=lambda: None,
        )
    assert (tmp_path / "pending-proposal.json").is_file()
    assert not (tmp_path / "human-decision.json").exists()


@pytest.mark.asyncio
async def test_resume_attempt_is_durable_before_send_and_ambiguous_get_is_preserved(tmp_path):
    driver = _driver()
    reviewed = _reviewed()
    _, _, checkpoint, subject = _case()
    human = _human(driver, reviewed)
    human_path = tmp_path / "human-decision.json"
    human_path.write_text(json.dumps(human))
    decision = driver.load_human_decision(human_path, reviewed, case_id="case-1", head="a" * 40)

    class AmbiguousMcp(_Mcp):
        async def resume_operation_proposal(self, **kwargs):
            recorded = json.loads((tmp_path / "resume-attempt.json").read_text())
            assert recorded["human_decision"] == human
            self.calls.append(("resume", kwargs))
            raise TimeoutError("ambiguous transport")

    client = AmbiguousMcp(reviewed.view)
    ports = dict(
        mcp_client=client,
        checkpoint_reader=_CheckpointReader(checkpoint),
        artifact_reader=_ArtifactReader(subject),
    )
    with pytest.raises(RuntimeError, match="LIVE_RESUME_AMBIGUOUS"):
        await driver.resume_once(
            tmp_path, reviewed, decision, human_body=human, check_head=lambda: None, **ports
        )
    assert (tmp_path / "ambiguous-exact-task-get.json").is_file()
    assert len([c for c in client.calls if c[0] == "resume"]) == 1
    with pytest.raises(ValueError, match="LIVE_RESUME_ALREADY_ATTEMPTED"):
        await driver.resume_once(
            tmp_path, reviewed, decision, human_body=human, check_head=lambda: None, **ports
        )
    assert len([c for c in client.calls if c[0] == "resume"]) == 1


def test_exact_head_guard_rejects_drift_and_old_case_replay(tmp_path, monkeypatch):
    driver = _driver()
    monkeypatch.setattr(driver, "current_head", lambda: "a" * 40)
    monkeypatch.setattr(driver, "source_tree_clean", lambda: True)
    driver.check_frozen_head("a" * 40)
    with pytest.raises(ValueError, match="LIVE_HEAD_DRIFT"):
        driver.check_frozen_head("b" * 40)
    directory = driver.new_case_directory(tmp_path, scenario="positive", head="a" * 40)
    assert directory.is_dir()
    assert not (directory / "front-door.sqlite3").exists()
    assert json.loads((directory / "case.json").read_text())["implementation_head"] == "a" * 40


@pytest.mark.parametrize("scenario", ["unavailable", "partial_commit"])
def test_phase_two_cases_require_reviewed_stage_config_before_any_driver_io(
    monkeypatch, tmp_path, scenario
):
    from tests.integration import cross_host_product_live_support as support
    from tests.integration.test_cross_host_product_live_preflight import _configured

    _configured(monkeypatch, tmp_path)
    monkeypatch.setattr(support, "_require_windows_live", lambda: None)
    config = support.CrossHostProductLiveConfig.from_environment()
    with pytest.raises(ValueError, match="LIVE_DRIVER_CONFIG_REQUIRED"):
        support.run_controlled_case(config=config, scenario=scenario)


def test_managed_mcp_terminates_on_startup_failure_without_pipe_deadlock(monkeypatch, tmp_path):
    driver = _driver()
    events = []

    class Child:
        pid = 1234

        def poll(self):
            return None

        def terminate(self):
            events.append("terminate")

        def wait(self, timeout):
            events.append("wait")
            return 0

    def spawn(argv, **kwargs):
        assert kwargs["stdout"] == driver.subprocess.DEVNULL
        assert kwargs["stderr"] == driver.subprocess.DEVNULL
        assert kwargs.get("shell", False) is False
        events.append("spawn")
        return Child()

    monkeypatch.setattr(driver.subprocess, "Popen", spawn)
    with pytest.raises(ValueError, match="LIVE_MCP_START_TIMEOUT"):
        with driver.ManagedMcpProcess(
            tmp_path, case_id="case-1", head="a" * 40, timeout_seconds=0.01, check_head=lambda: None
        ):
            raise AssertionError("startup must fail")
    assert events == ["spawn", "terminate", "wait"]


def test_loaded_module_provenance_rejects_wrong_pid_head_or_bytes(tmp_path):
    import hashlib

    driver = _driver()
    dll = tmp_path / "Revit.AgentHost.dll"
    dll.write_bytes(b"loaded-module")
    digest = hashlib.sha256(dll.read_bytes()).hexdigest()
    raw = {
        "pid": 1122,
        "modules": [{"file_name": str(dll), "product_version": "1.0.0+" + "a" * 40}],
    }
    result = driver.validate_loaded_module(
        raw,
        host_kind="REVIT",
        locator="EnterpriseDesignAgent.Revit.MACHINE-1122",
        host_instance_id="revit-abc",
        expected_sha=digest,
        head="a" * 40,
    )
    assert result["sha256"] == digest
    assert result["host_instance_id"] == "revit-abc"
    assert result["inspection"] == raw
    for damage in [
        dict(raw, pid=999),
        dict(raw, modules=[]),
        dict(raw, modules=[dict(raw["modules"][0], product_version="1.0.0+old")]),
    ]:
        with pytest.raises(ValueError, match="LIVE_PLUGIN"):
            driver.validate_loaded_module(
                damage,
                host_kind="REVIT",
                locator="EnterpriseDesignAgent.Revit.MACHINE-1122",
                host_instance_id="revit-abc",
                expected_sha=digest,
                head="a" * 40,
            )
    dll.write_bytes(b"changed-module")
    with pytest.raises(ValueError, match="LIVE_PLUGIN"):
        driver.validate_loaded_module(
            raw,
            host_kind="REVIT",
            locator="EnterpriseDesignAgent.Revit.MACHINE-1122",
            host_instance_id="revit-abc",
            expected_sha=digest,
            head="a" * 40,
        )


def _settings():
    """全部业务身份由审核输入提供，通用 driver 不能复用现场 reference 常量。"""

    return {
        "project_id": "reviewed-project",
        "candidate_key": "reviewed-candidate",
        "semantic_target_id": "reviewed-wall",
        "topology_environment_id": "reviewed-topology",
        "topology_revision": 4,
        "slot_ids": {"AUTOCAD": "auto-slot", "REVIT": "revit-slot"},
        "configured_reference_ids": {"AUTOCAD": "reviewed-dwg", "REVIT": "reviewed-rvt"},
        "policies": {
            scenario: {
                "policy_id": "reviewed-" + scenario,
                "principal": "reviewer:controlled",
                "allowed_canonical_operations": [
                    "set_wall_thickness.v1" if scenario == "positive" else "unapproved.operation.v1"
                ],
                "admission_ttl_seconds": 300,
            }
            for scenario in ("positive", "deny")
        },
        "utterance": "将当前墙和审核绑定墙改为300 mm",
        "human_timeout_seconds": 600,
        "stage_timeout_seconds": 180,
    }


def _composition():
    name = "tests.integration.cross_host_product_live_composition"
    assert importlib.util.find_spec(name) is not None, "production composition is missing"
    return importlib.import_module(name)


def test_reviewed_runtime_inputs_derive_real_semantic_and_exact_required_topology(
    monkeypatch, tmp_path
):
    from tests.integration.cross_host_product_live_support import CrossHostProductLiveConfig
    from tests.integration.test_cross_host_product_live_preflight import _configured

    _configured(monkeypatch, tmp_path)
    config = CrossHostProductLiveConfig.from_environment()
    composition = _composition()
    target, topology, policy = composition.reviewed_runtime_inputs(config, _settings(), "positive")
    assert target.project_id == "reviewed-project"
    assert [member.host_kind for member in target.members] == ["AUTOCAD", "REVIT"]
    assert [member.role for member in target.members] == ["BOUND_REQUIRED", "INITIATOR"]
    assert target.member("AUTOCAD").configured_reference_hash == config.autocad_fixture_sha256
    assert target.member("REVIT").document_id == config.revit_document_ref
    assert topology.topology_revision == 4
    assert all(slot.requirement.value == "REQUIRED" for slot in topology.slots)
    assert policy.reviewed_configuration_hash == target.reviewed_configuration_hash
    assert policy.allowed_topology_snapshot_hashes == (topology.topology_snapshot_hash,)
    assert target.semantic_environment_id and len(target.semantic_environment_hash) == 64


@pytest.mark.asyncio
async def test_audited_production_factory_reads_and_closes_on_actual_io_failure(
    monkeypatch, tmp_path
):
    from tests.integration.cross_host_product_live_support import CrossHostProductLiveConfig
    from tests.integration.test_cross_host_product_live_preflight import (
        _configured,
        _preflight_boundaries,
    )

    _configured(monkeypatch, tmp_path)
    config = CrossHostProductLiveConfig.from_environment()
    events = _preflight_boundaries(monkeypatch, config, failure="autocad_read")
    auto, _ = _composition().audited_host_factories(config, tmp_path, check_head=lambda: None)
    with pytest.raises(OSError, match="pipe read failed"):
        await auto(config.autocad_endpoint).extract_design_facts([config.autocad_native_id])
    assert events == ["autocad.open", "autocad.read", "autocad.close"]
    records = [
        json.loads(line) for line in (tmp_path / "host-commands.jsonl").read_text().splitlines()
    ]
    assert len(records) == 1
    assert records[0]["phase"] == "SEND"
    assert records[0]["command"]["mode"] == "READ"


def test_owner_projection_requires_body_and_rejects_integrity_mismatch():
    from design_execution_reconciliation.evidence_store import encode_reconciliation_evidence

    from tests.execution_reconciliation._support import phase_i_context, signed_delta

    driver = _driver()
    delta = signed_delta(phase_i_context())
    row = {
        "evidence_hash": delta.actual_delta_hash,
        "evidence_kind": "actual_delta",
        "codec_version": 1,
        "body": encode_reconciliation_evidence(delta),
    }
    assert driver.validate_reconciliation_rows([row])[delta.actual_delta_hash] == delta
    for damage in [
        dict(row, evidence_hash="f" * 64),
        dict(row, body={}),
        dict(row, codec_version=99),
        dict(row, evidence_kind="verification_result"),
    ]:
        with pytest.raises(ValueError, match="LIVE_OWNER_EVIDENCE"):
            driver.validate_reconciliation_rows([damage])
    with pytest.raises(ValueError, match="LIVE_OWNER_EVIDENCE"):
        driver.require_evidence_body({}, delta.actual_delta_hash, "actual_delta")


def test_deny_projection_accepts_actual_waiting_policy_phase_and_no_grant():
    driver = _driver()
    assert (
        driver.policy_denied_outcome(
            final_status="WAITING",
            workflow_phase="POLICY_APPROVAL",
            saga_count=0,
            dispatch_count=0,
            grant_count=0,
            policy_attempts=[
                {"status": "DENIED", "error_code": "FRONT_DOOR_APPROVAL_POLICY_DENIED"}
            ],
        )
        == "DENIED"
    )
    for change in [
        dict(grant_count=1),
        dict(workflow_phase="AWAIT_OPERATION_PROPOSAL"),
        dict(policy_attempts=[]),
        dict(saga_count=1),
    ]:
        parameters = dict(
            final_status="WAITING",
            workflow_phase="POLICY_APPROVAL",
            saga_count=0,
            dispatch_count=0,
            grant_count=0,
            policy_attempts=[
                {"status": "DENIED", "error_code": "FRONT_DOOR_APPROVAL_POLICY_DENIED"}
            ],
        )
        with pytest.raises(ValueError, match="LIVE_POLICY_DENY"):
            driver.policy_denied_outcome(**(parameters | change))


def test_public_owner_audit_preserves_result_exception_and_restores_method(tmp_path):
    composition = _composition()
    events = []
    winner = object()
    failure = ValueError("owner failure")

    class Owner:
        def put(self, value):
            events.append(value)
            if value == "bad":
                raise failure
            return winner

    original = Owner.put
    snapshots = []
    with composition.audit_public_method(Owner, "put", lambda value: snapshots.append(value)):
        assert Owner().put("good") is winner
        with pytest.raises(ValueError) as raised:
            Owner().put("bad")
        assert raised.value is failure
    assert Owner.put is original
    assert events == ["good", "bad"]
    assert snapshots == ["good"]


def test_captured_plan_binding_grant_roundtrip_uses_existing_owner_integrity():
    from design_execution_planning import ExecutionPlanV2
    from design_gateway_authorization import ExecutionGrantV2
    from design_provider_binding import ProviderBindingSetV2

    from tests.product_runtime.conftest import build_cross_host_task15_lineage

    driver = _driver()
    ctx = build_cross_host_task15_lineage()
    grant = ctx.gateway_store.get_grant_v2(ctx.authorities[0].grant_hash)
    snapshots = [
        {"kind": kind, "body": driver.plain(value)}
        for kind, value in [
            ("changeset", ctx.case.changeset),
            ("scope", ctx.case.boundary_v2),
            ("materialization_plan", ctx.materialization_plan),
            ("execution_plan", ctx.execution_plan),
            ("binding_set", ctx.binding_sets[0]),
            ("grant", grant),
        ]
    ]
    captured = driver.validate_owner_snapshots(snapshots, ctx.case.topology)
    assert isinstance(captured["execution_plan"][0], ExecutionPlanV2)
    assert isinstance(captured["binding_set"][0], ProviderBindingSetV2)
    assert isinstance(captured["grant"][0], ExecutionGrantV2)
    assert captured["execution_plan"][0] == ctx.execution_plan
    snapshots[-1]["body"]["grant_hash"] = "f" * 64
    with pytest.raises(ValueError, match="LIVE_OWNER_CAPTURE"):
        driver.validate_owner_snapshots(snapshots, ctx.case.topology)


def test_manifest_refs_require_complete_actual_captured_bodies(tmp_path):
    from design_orchestrator.execution_collection_artifacts import (
        ExecutionGrantCollectionManifest,
        ExecutionGrantCollectionMember,
        ProviderBindingCollectionManifest,
        ProviderBindingCollectionMember,
    )
    from design_orchestrator.workflow_contracts import StableRef

    from tests.product_runtime.conftest import build_cross_host_task15_lineage

    driver = _driver()
    ctx = build_cross_host_task15_lineage()
    plan = ctx.execution_plan
    slices = plan.execution_slices
    required_refs = tuple(
        StableRef(item.execution_slice_id, item.execution_slice_hash) for item in slices
    )
    bindings = ProviderBindingCollectionManifest(
        plan.execution_plan_id,
        plan.execution_plan_hash,
        plan.materialization_plan_hash,
        required_refs,
        tuple(
            ProviderBindingCollectionMember(
                item.execution_slice_id,
                item.execution_slice_hash,
                item.materialization_id,
                StableRef(binding.binding_set_id, binding.binding_set_hash),
            )
            for item, binding in zip(slices, ctx.binding_sets, strict=True)
        ),
    )
    grants = tuple(ctx.gateway_store.get_grant_v2(item.grant_hash) for item in ctx.authorities)
    manifest = ExecutionGrantCollectionManifest(
        plan.execution_plan_id,
        plan.execution_plan_hash,
        plan.materialization_plan_hash,
        required_refs,
        tuple(
            ExecutionGrantCollectionMember(
                item.execution_slice_id,
                item.execution_slice_hash,
                item.materialization_id,
                StableRef(grant.grant_id, grant.grant_hash),
            )
            for item, grant in zip(slices, grants, strict=True)
        ),
    )
    driver.validate_collection_capture(plan, bindings, manifest, ctx.binding_sets, grants)
    with pytest.raises(ValueError, match="LIVE_OWNER_CAPTURE"):
        driver.validate_collection_capture(plan, bindings, manifest, ctx.binding_sets[:1], grants)
    with pytest.raises(ValueError, match="LIVE_OWNER_CAPTURE"):
        driver.validate_collection_capture(plan, bindings, manifest, ctx.binding_sets, grants[:1])
    assert not (tmp_path / "evidence-manifest.json").exists()


def test_live_entry_requires_reviewed_settings_before_network(monkeypatch, tmp_path):
    from tests.integration import cross_host_product_live_support as support
    from tests.integration.test_cross_host_product_live_preflight import _configured

    _configured(monkeypatch, tmp_path)
    monkeypatch.delenv("DSP_CROSS_HOST_PRODUCT_DRIVER_CONFIG", raising=False)
    monkeypatch.setattr(support, "_require_windows_live", lambda: None)
    with pytest.raises(ValueError, match="LIVE_DRIVER_CONFIG_REQUIRED"):
        support.run_controlled_case(
            config=support.CrossHostProductLiveConfig.from_environment(), scenario="positive"
        )


def test_driver_config_freezes_settings_and_head_in_current_case(monkeypatch, tmp_path):
    driver = _driver()
    body = {**_settings(), "implementation_head": "a" * 40, "database_name": "reviewed_case_db"}
    path = tmp_path / "reviewed-config.json"
    path.write_text(json.dumps(body))
    monkeypatch.setenv("DSP_CROSS_HOST_PRODUCT_DRIVER_CONFIG", str(path))
    assert driver.load_driver_settings("a" * 40) == body
    with pytest.raises(ValueError, match="LIVE_HEAD_DRIFT"):
        driver.load_driver_settings("b" * 40)


@pytest.mark.parametrize("damage", ["copied_positive", "mixed", "swapped"])
def test_deny_policy_cannot_admit_canonical_operation_before_any_case_io(
    monkeypatch, tmp_path, damage
):
    driver = _driver()
    body = {**_settings(), "implementation_head": "a" * 40, "database_name": "fresh_case_db"}
    if damage == "copied_positive":
        body["policies"]["deny"] = dict(body["policies"]["positive"])
    elif damage == "mixed":
        body["policies"]["deny"]["allowed_canonical_operations"] = [
            "unapproved.operation.v1", "set_wall_thickness.v1"
        ]
    else:
        body["policies"]["positive"], body["policies"]["deny"] = (
            body["policies"]["deny"], body["policies"]["positive"]
        )
    path = tmp_path / "reviewed-config.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    monkeypatch.setenv("DSP_CROSS_HOST_PRODUCT_DRIVER_CONFIG", str(path))
    with pytest.raises(ValueError, match="LIVE_POLICY_SCENARIO_INVALID"):
        driver.load_driver_settings("a" * 40)
    monkeypatch.setattr(driver, "current_head", lambda: "a" * 40)
    monkeypatch.setattr(driver, "audit_imported_product_sources", lambda: {})
    class NoCaseIO:
        def verify_fixtures(self):
            raise AssertionError("fixture/Host/model preparation must not begin")

    with pytest.raises(ValueError, match="LIVE_POLICY_SCENARIO_INVALID"):
        driver.run_phase_one(NoCaseIO(), "deny")


def test_controller_probe_uses_real_read_normalizer_and_baseline_identity(monkeypatch, tmp_path):
    from tests.integration.cross_host_product_live_support import CrossHostProductLiveConfig
    from tests.integration.test_cross_host_product_live_preflight import (
        _configured,
        _preflight_boundaries,
    )

    _configured(monkeypatch, tmp_path)
    config = CrossHostProductLiveConfig.from_environment()
    _preflight_boundaries(monkeypatch, config)
    composition = _composition()
    target, _, _ = composition.reviewed_runtime_inputs(config, _settings(), "positive")
    factories = composition.audited_host_factories(config, tmp_path, check_head=lambda: None)
    probe = composition.production_probe_factory(config, target, factories, tmp_path)
    observed = probe("AUTOCAD", config.autocad_endpoint).discover(
        command_id="independent-auto-baseline", document_id=config.autocad_document_ref
    )
    assert observed.host_instance_id == config.autocad_host_instance_id
    assert observed.native_target_id == config.autocad_native_id
    assert len(observed.host_binding_fingerprint) == 64
    assert (tmp_path / "controller-baseline-autocad.json").is_file()


def test_collect_fails_before_publishing_manifest_when_owner_capture_missing(tmp_path):
    driver = _driver()
    with pytest.raises(ValueError, match="LIVE_OWNER_CAPTURE"):
        driver.publish_validated_evidence(
            tmp_path,
            result={"scenario": "positive"},
            owner_snapshots=[],
            topology=None,
            required_capture_kinds=("execution_plan",),
        )
    assert not (tmp_path / "evidence-manifest.json").exists()


def test_public_production_owner_scope_records_exact_winners_and_restores(tmp_path):
    from design_execution_planning import InMemoryExecutionPlanV2Store

    from tests.product_runtime.conftest import build_cross_host_task15_lineage

    composition = _composition()
    plan = build_cross_host_task15_lineage().execution_plan
    original = InMemoryExecutionPlanV2Store.put
    with composition.audit_runtime_owners(tmp_path, check_head=lambda: None):
        store = InMemoryExecutionPlanV2Store()
        assert store.put(plan) is None
        assert store.get(plan.execution_plan_id) is plan
    assert InMemoryExecutionPlanV2Store.put is original
    captured = [
        json.loads(line) for line in (tmp_path / "owner-captures.jsonl").read_text().splitlines()
    ]
    assert len(captured) == 1
    assert isinstance(captured[0].pop("timestamp"), str)
    assert captured == [
        {
            "kind": "execution_plan",
            "storage_provenance": "AUDITED_IN_MEMORY_OWNER",
            "body": _driver().plain(plan),
        }
    ]


def test_native_module_inspection_passes_only_validated_integer_pid(monkeypatch):
    from types import SimpleNamespace

    driver = _driver()
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        assert kwargs["env"]["DSP_INSPECT_PROCESS_ID"] == "1122"
        assert "1122" not in argv[-1]
        return SimpleNamespace(returncode=0, stdout='{"pid":1122,"modules":[]}')

    monkeypatch.setattr(driver.subprocess, "run", run)
    assert (
        driver.inspect_loaded_module("EnterpriseDesignAgent.Revit.MACHINE-1122", "REVIT")["pid"]
        == 1122
    )
    with pytest.raises(ValueError, match="LIVE_PLUGIN_PIPE_INVALID"):
        driver.inspect_loaded_module("EnterpriseDesignAgent.Revit.MACHINE-1122;exit", "REVIT")
    assert len(calls) == 1


def test_run_controlled_case_connects_reviewed_phase_one_only(monkeypatch, tmp_path):
    from tests.integration import cross_host_product_live_support as support
    from tests.integration.test_cross_host_product_live_preflight import _configured

    _configured(monkeypatch, tmp_path)
    monkeypatch.setattr(support, "_require_windows_live", lambda: None)
    driver = _driver()
    calls = []
    monkeypatch.setattr(
        driver,
        "run_phase_one",
        lambda config, scenario: calls.append(scenario) or {"scenario": scenario},
    )
    for scenario in ("positive", "deny"):
        assert support.run_controlled_case(
            config=support.CrossHostProductLiveConfig.from_environment(), scenario=scenario
        ) == {"scenario": scenario}
    assert calls == ["positive", "deny"]


def _positive_projection_inputs():
    """离线用真正 Step33 evaluator 生成 owner body；这些 helper 不进入 live 路径。"""

    from types import SimpleNamespace

    from design_execution_reconciliation import compute_actual_delta_hash
    from design_execution_reconciliation.evidence_store import evidence_kind_and_hash

    from tests.execution_reconciliation._support import service, signed_bundle, signed_delta
    from tests.product_runtime.conftest import build_cross_host_task15_lineage
    from tests.product_runtime.test_cross_host_product_query import _binding

    ctx = build_cross_host_task15_lineage()
    binding = _binding(ctx)
    materializations, dispatches, commands, evidence = [], [], [], {}
    observations = []
    for index, (member, execution_slice, authority) in enumerate(
        zip(binding.members, ctx.execution_plan.execution_slices, ctx.authorities, strict=True)
    ):
        delta = signed_delta(ctx, index)
        draft = replace(
            delta, revision_before=10 + index, revision_after=11 + index, actual_delta_hash="0" * 64
        )
        delta = replace(draft, actual_delta_hash=compute_actual_delta_hash(draft))
        bundle = signed_bundle(ctx, delta, index)
        verification = service().verify_semantics(
            canonical_changeset=ctx.case.changeset,
            approval_scope_boundary=ctx.case.boundary_v2,
            execution_slice=execution_slice,
            authority=authority,
            actual_delta=delta,
            validation_tasks=ctx.case.changeset.validation_tasks,
            verification_evidence_bundle=bundle,
            verified_at="2026-10-07T07:00:00Z",
        )
        for value in (delta, bundle, verification):
            evidence[evidence_kind_and_hash(value)[1]] = value
        observations.append(
            SimpleNamespace(
                host_kind=member.host_kind, host_revision=10 + index, normalized_thickness_mm=200
            )
        )
        materializations.append(
            SimpleNamespace(
                host_kind=member.host_kind,
                host_instance_id=member.host_instance_id,
                document_id=member.document_id,
                native_target_id=member.native_target_id,
                semantic_target_id=binding.semantic_target_id,
                execution_slice_hash=execution_slice.execution_slice_hash,
                materialization_id=execution_slice.materialization_id,
                status="SUCCEEDED",
                expected_revision=10 + index,
                committed_revision=11 + index,
                observed_revision=11 + index,
                verified_thickness_mm=300,
                actual_delta_hash=delta.actual_delta_hash,
                evidence_bundle_hash=bundle.evidence_bundle_hash,
                verification_hash=verification.verification_hash,
            )
        )
        dispatches.append(
            {
                "saga_id": "saga-1",
                "execution_slice_hash": execution_slice.execution_slice_hash,
                "grant_hash": authority.grant_hash,
                "binding_set_hash": authority.binding_set_hash,
                "host_instance_id": member.host_instance_id,
                "document_ref": member.document_id,
                "expected_host_revision": str(10 + index),
                "status": "HOST_COMMITTED",
                "idempotency_key": "idem-" + str(index),
            }
        )
        execute = {
            "command_id": "execute-" + str(index),
            "mode": "EXECUTE",
            "operation": "set_wall_thickness",
            "idempotency_key": "idem-" + str(index),
            "document_id": member.document_id,
        }
        for phase in ("SEND", "RECEIVE"):
            commands.append(
                {
                    "host_kind": member.host_kind,
                    "phase": phase,
                    "stage": "MCP",
                    "command": execute,
                    "response": {"status": "OK", "revision_after": 11 + index},
                }
            )
        operation = (
            "design.extract_native_snapshot"
            if member.host_kind == "AUTOCAD"
            else "read_wall_thickness_snapshot"
        )
        payload = (
            {
                "hostInstanceId": member.host_instance_id,
                "documentId": member.document_id,
                "revision": 11 + index,
                "entities": [
                    {
                        "nativeId": member.native_target_id,
                        "properties": {"constantWidth": {"value": 300, "unit": "mm"}},
                    }
                ],
            }
            if member.host_kind == "AUTOCAD"
            else {
                "host_instance_id": member.host_instance_id,
                "document_id": member.document_id,
                "wall_unique_id": member.native_target_id,
                "wall_thickness_mm": 300.0,
                "revision_before": 11 + index,
                "revision_after": 11 + index,
            }
        )
        for stage in ("MCP", "INDEPENDENT_FINAL"):
            commands.append(
                {
                    "host_kind": member.host_kind,
                    "phase": "RECEIVE",
                    "stage": stage,
                    "command": {
                        "command_id": stage + str(index),
                        "mode": "READ",
                        "operation": operation,
                    },
                    "response": {"status": "OK", "payload": payload, "revision_after": 11 + index},
                }
            )
    reviewed = SimpleNamespace(
        frozen=SimpleNamespace(session_binding=binding),
        subject=SimpleNamespace(observations=tuple(observations)),
    )
    final = SimpleNamespace(saga_id="saga-1", materializations=tuple(materializations))
    return reviewed, final, dispatches, evidence, commands


def test_positive_projection_requires_independent_committed_reads_and_preserves_numbers():
    driver = _driver()
    reviewed, final, dispatches, evidence, commands = _positive_projection_inputs()
    hosts = driver.project_positive_hosts(reviewed, final, dispatches, evidence, commands)
    assert set(hosts) == {"AUTOCAD", "REVIT"}
    assert hosts["AUTOCAD"]["committed_revision"] == 11
    assert hosts["REVIT"]["committed_revision"] == 12
    assert type(hosts["AUTOCAD"]["independent_final_read"]["value"]) is int
    assert type(hosts["REVIT"]["independent_final_read"]["value"]) is float
    assert all(host["verification_source"] == "INDEPENDENT_HOST_READ" for host in hosts.values())


@pytest.mark.parametrize(
    "damage", ["missing_body", "extra_execute", "receipt_only", "wrong_revision", "wrong_document"]
)
def test_positive_projection_fails_on_incomplete_or_mismatched_owner_truth(damage):
    driver = _driver()
    reviewed, final, dispatches, evidence, commands = _positive_projection_inputs()
    if damage == "missing_body":
        evidence.pop(final.materializations[0].evidence_bundle_hash)
    elif damage == "extra_execute":
        commands.insert(0, dict(commands[0]))
    elif damage == "receipt_only":
        commands = [item for item in commands if item["command"]["mode"] != "READ"]
    elif damage == "wrong_revision":
        commands[3]["response"]["payload"]["revision"] = 99
    else:
        dispatches[0]["document_ref"] = "other"
    with pytest.raises(ValueError, match="LIVE_(OWNER_EVIDENCE|HOST_EVIDENCE)"):
        driver.project_positive_hosts(reviewed, final, dispatches, evidence, commands)


def test_durable_workflow_artifact_rows_verify_ref_codec_body_hash():
    from design_orchestrator.workflow_artifacts import encode_workflow_artifact

    driver = _driver()
    reviewed = _reviewed()
    row = {
        "artifact_id": reviewed.subject_ref.ref_id,
        "kind": "cross_host_operation_proposal_subject_v2",
        "codec_version": 1,
        "content_hash": reviewed.subject_ref.content_hash,
        "payload": encode_workflow_artifact(
            kind="cross_host_operation_proposal_subject_v2", value=reviewed.subject
        ),
    }
    assert driver.validate_workflow_rows([row])[reviewed.subject_ref.ref_id] == reviewed.subject
    row["content_hash"] = "f" * 64
    with pytest.raises(ValueError, match="LIVE_OWNER_ARTIFACT"):
        driver.validate_workflow_rows([row])


def test_formal_collect_rejects_old_head_before_reading_owner_or_publishing(tmp_path, monkeypatch):
    driver = _driver()
    driver.write_once(
        tmp_path / "case.json",
        {"implementation_head": "b" * 40, "scenario": "positive", "case_id": "old-case"},
    )
    monkeypatch.setattr(driver, "current_head", lambda: "a" * 40)
    with pytest.raises(ValueError, match="LIVE_HEAD_DRIFT"):
        driver.collect_formal_evidence(
            None,
            tmp_path,
            None,
            None,
            None,
            None,
            None,
            None,
            lambda: driver.check_frozen_head("b" * 40),
        )
    assert not (tmp_path / "evidence-manifest.json").exists()


def test_artifact_publication_is_atomic_and_never_overwrites(tmp_path):
    driver = _driver()
    path = tmp_path / "artifact.json"
    with pytest.raises(TypeError):
        driver.write_once(path, {"invalid": object()})
    assert not path.exists()
    driver.write_once(path, {"winner": 300})
    with pytest.raises(FileExistsError):
        driver.write_once(path, {"winner": 200})
    assert json.loads(path.read_text())["winner"] == 300


def test_human_timestamp_cannot_replay_before_published_proposal(tmp_path):
    driver = _driver()
    reviewed = _reviewed()
    driver.publish_pending_proposal(tmp_path, reviewed, case_id="case-1", head="a" * 40)
    human = _human(driver, reviewed)
    human["recorded_at"] = "2020-01-01T00:00:00Z"
    path = tmp_path / "human-decision.json"
    path.write_text(json.dumps(human))
    with pytest.raises(ValueError, match="LIVE_HUMAN_DECISION_STALE"):
        driver.load_human_decision(path, reviewed, case_id="case-1", head="a" * 40)


def test_initial_live_freeze_rejects_dirty_checkout(monkeypatch):
    driver = _driver()
    monkeypatch.setattr(driver, "current_head", lambda: "a" * 40)
    monkeypatch.setattr(driver.subprocess, "check_output", lambda *a, **kw: " M tests/modified.py")
    with pytest.raises(ValueError, match="LIVE_HEAD_DIRTY"):
        driver.freeze_clean_head()


def test_live_boundary_never_logs_unsanitized_adapter_exception(monkeypatch, tmp_path):
    from tests.integration import cross_host_product_live_support as support
    from tests.integration.test_cross_host_product_live_preflight import _configured

    _configured(monkeypatch, tmp_path)
    monkeypatch.setattr(support, "_require_windows_live", lambda: None)

    def failing(*args):
        raise ValueError("raw-adapter-private-credential")

    monkeypatch.setattr(_driver(), "run_phase_one", failing)
    with pytest.raises(RuntimeError, match="LIVE_CASE_FAILED") as raised:
        support.run_controlled_case(
            config=support.CrossHostProductLiveConfig.from_environment(), scenario="positive"
        )
    assert "private-credential" not in str(raised.value)


def test_formal_deny_collect_preserves_actual_waiting_policy_owner_outcome(tmp_path, monkeypatch):
    import hashlib
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from design_orchestrator.interaction_artifacts import (
        CrossHostOperationProposalSubjectV2,
        CrossHostProposalObservationV2,
    )
    from design_orchestrator.proposal_decision import ProposalDecisionRecord
    from design_orchestrator.workflow_artifacts import (
        encode_workflow_artifact,
        workflow_artifact_content_hash,
    )
    from design_orchestrator.workflow_contracts import StableRef, WorkflowCheckpointView
    from design_product_front_door import ConfiguredProductApprovalPolicyV2, FrozenSubmissionV2
    from design_product_runtime import ProductTaskQueryViewV2, ProductTaskRequestV2
    from design_product_runtime.accepted_input import AcceptedProductTaskInputV2

    from tests.product_runtime.conftest import build_cross_host_task15_lineage
    from tests.product_runtime.test_cross_host_product_query import _binding

    driver = _driver()
    ctx = build_cross_host_task15_lineage()
    binding = _binding(ctx)
    request = ProductTaskRequestV2.create(
        task_id=ctx.case.changeset.task_id,
        project_id=binding.project_id,
        initiating_host_kind="REVIT",
        session_ref=binding.session_ref,
        session_binding_hash=binding.binding_hash,
        requested_action="SET_BOUND_WALL_THICKNESS",
        intent_arguments={"thickness": {"value": 300, "unit": "mm"}},
    )
    frozen = FrozenSubmissionV2(
        "submission-1", "真实模型提出300 mm", "9" * 64, "8" * 64, binding, request, "PENDING"
    )
    subject = CrossHostOperationProposalSubjectV2(
        request_hash=request.request_hash,
        session_binding_hash=binding.binding_hash,
        topology_snapshot_hash=binding.topology_snapshot_hash,
        semantic_target_id=binding.semantic_target_id,
        semantic_environment_id=binding.semantic_environment_id,
        semantic_environment_hash=binding.semantic_environment_hash,
        canonical_operation="set_wall_thickness.v1",
        canonical_arguments={
            "targets": [binding.semantic_target_id],
            "thickness": {"value": 300, "unit": "mm"},
        },
        observations=tuple(
            CrossHostProposalObservationV2(
                host_kind=member.host_kind,
                host_instance_id=member.host_instance_id,
                document_id=member.document_id,
                native_target_id=member.native_target_id,
                semantic_target_id=binding.semantic_target_id,
                host_revision=10 + index,
                normalized_thickness_mm=200.0,
                observed_at="2026-10-09T12:00:00Z",
                command_id="baseline-" + member.host_kind,
            )
            for index, member in enumerate(binding.members)
        ),
    )
    ref = StableRef("proposal-1", workflow_artifact_content_hash(subject))
    final = ProductTaskQueryViewV2(
        "V2",
        request.task_id,
        request.request_hash,
        "WORKFLOW",
        "WAITING",
        "ACCEPTED",
        None,
        None,
        (),
    )
    reviewed = ReviewedV2Proposal(frozen, _reviewed().view, "pause-1", ref, subject)
    checkpoint = WorkflowCheckpointView(
        request.task_id,
        "POLICY_APPROVAL",
        changeset_ref=StableRef(ctx.case.changeset.changeset_id, ctx.case.changeset.changeset_hash),
    )
    decision = ProposalDecisionRecord(request.task_id, "pause-1", ref, "ACCEPTED", "CONTINUABLE", 1)
    accepted = AcceptedProductTaskInputV2(request, binding.binding_hash, driver.plain(binding))
    policy = ConfiguredProductApprovalPolicyV2.from_mapping(
        {
            "version": "DSP_PRODUCT_APPROVAL_POLICY_V2",
            "policy_id": "reviewed-deny",
            "principal": "reviewer",
            "project_ids": [binding.project_id],
            "allowed_canonical_operations": ["other.operation.v1"],
            "reviewed_configuration_hash": "8" * 64,
            "semantic_target_ids": [binding.semantic_target_id],
            "allowed_topology_snapshot_hashes": [binding.topology_snapshot_hash],
            "required_host_roles": {"AUTOCAD": "BOUND_REQUIRED", "REVIT": "INITIATOR"},
            "admission_ttl_seconds": 300,
        }
    )
    head = "a" * 40
    driver.write_once(
        tmp_path / "case.json",
        {"case_id": "deny-case-1", "scenario": "deny", "implementation_head": head},
    )
    source_audit = driver.audit_imported_product_sources()
    driver.write_once(tmp_path / "controller-python-sources.json", source_audit)
    driver.write_once(
        tmp_path / "mcp-ready.json",
        {"case_id": "deny-case-1", "implementation_head": head, "python_sources": source_audit},
    )
    driver.publish_pending_proposal(tmp_path, reviewed, case_id="deny-case-1", head=head)
    human = _human(driver, reviewed, "deny-case-1")
    human["recorded_at"] = datetime.now(UTC).isoformat()
    driver.write_once(tmp_path / "human-decision.json", human)
    driver.write_once(tmp_path / "resume-attempt.json", {"human_decision": human})
    from tests.integration.cross_host_product_live_composition import append_audit

    for kind, value in (("changeset", ctx.case.changeset), ("scope", ctx.case.boundary_v2)):
        append_audit(tmp_path / "owner-captures.jsonl", {"kind": kind, "body": driver.plain(value)})
    append_audit(
        tmp_path / "policy-attempts.jsonl",
        {
            "task_id": request.task_id,
            "changeset_ref": driver.plain(checkpoint.changeset_ref),
            "scope_hash": ctx.case.boundary_v2.scope_hash,
            "policy": policy.snapshot_payload(),
            "policy_snapshot_hash": policy.policy_snapshot_hash,
            "status": "DENIED",
            "error_code": "FRONT_DOOR_APPROVAL_POLICY_DENIED",
        },
    )
    model_name = "reviewed-model"
    candidate_key = "reviewed-wall"
    model_source = driver.validate_reviewed_model_command(
        (driver.sys.executable, "-m", driver.MODEL_MODULE)
    )
    driver.write_once(tmp_path / "model-interpreter-source.json", model_source)
    driver.write_once(tmp_path / "driver-settings.json", {"candidate_key": candidate_key})
    proposal = {
        "kind": "PROPOSAL",
        "candidate_key": candidate_key,
        "thickness": {"value": 300, "unit": "mm"},
    }
    raw_response = {
        "id": "msg-deny-1",
        "model": model_name,
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 20},
        "content": [{"type": "text", "text": driver.json.dumps(proposal)}],
    }
    driver.write_once(
        tmp_path / "model-provider-invocation.json",
        {
            "client_submission_ref": "submission-1",
            "model_name": model_name,
            "invocation_id": "msg-deny-1",
            "request_id": None,
            "response_model": model_name,
            "proposal": proposal,
            "raw_response": raw_response,
            "usage": raw_response["usage"],
        },
    )
    append_audit(
        tmp_path / "model-invocations.jsonl",
        {
            "client_submission_ref": "submission-1",
            "invocation_kind": "ANTHROPIC_SDK_PROVIDER_RESPONSE",
            "invocation_id": "msg-deny-1",
            "request_id": None,
            "response_model": model_name,
            "usage": raw_response["usage"],
            "interpreter_source_sha256": model_source["sha256"],
            "controller_authority_env_absent": True,
        },
    )
    _, _, _, _, commands = _positive_projection_inputs()
    final_reads = [row for row in commands if row.get("stage") == "INDEPENDENT_FINAL"]
    for index, row in enumerate(final_reads):
        payload = row["response"]["payload"]
        if index == 0:
            payload["revision"] = 10
            payload["entities"][0]["properties"]["constantWidth"]["value"] = 200
        else:
            payload.update(wall_thickness_mm=200.0, revision_before=11, revision_after=11)
        append_audit(tmp_path / "host-commands.jsonl", row)
    raw = {
        "requests": [{"task_id": request.task_id, "request_hash": request.request_hash}],
        "decisions": [{}],
        "artifacts": [
            {
                "artifact_id": ref.ref_id,
                "kind": "cross_host_operation_proposal_subject_v2",
                "codec_version": 1,
                "content_hash": ref.content_hash,
                "payload": encode_workflow_artifact(
                    kind="cross_host_operation_proposal_subject_v2", value=subject
                ),
            }
        ],
        "sagas": [],
        "dispatches": [],
        "evidence": [],
        "admissions": [],
    }
    monkeypatch.setattr(
        driver, "_read_durable_owners", lambda *args: (raw, accepted, decision, [], [])
    )
    monkeypatch.setattr(driver, "check_frozen_head", lambda _head: None)
    plugins = {}
    for index, member in enumerate(binding.members):
        name = "AutoCAD.AgentHost.dll" if index == 0 else "Revit.AgentHost.dll"
        dll = tmp_path / name
        dll.write_bytes(b"offline-loaded-bytes")
        plugins[member.host_kind] = {
            "host_instance_id": member.host_instance_id,
            "locator": member.transport_locator,
            "sha256": hashlib.sha256(dll.read_bytes()).hexdigest(),
            "inspection": {"pid": 41 + index},
        }
        for stage in ("CONTROLLER", "MCP"):
            append_audit(
                tmp_path / "pipe-server-ownership.jsonl",
                {
                    "host_kind": member.host_kind,
                    "host_instance_id": member.host_instance_id,
                    "locator": member.transport_locator,
                    "server_pid": plugins[member.host_kind]["inspection"]["pid"],
                    "expected_pid": plugins[member.host_kind]["inspection"]["pid"],
                    "stage": stage,
                },
            )
    # 本合同替换 native inspector；PID locator 与真实 bytes validator 有独立合同验证。
    monkeypatch.setattr(driver, "inspect_loaded_module", lambda *args: {})
    monkeypatch.setattr(
        driver, "validate_loaded_module", lambda raw, **kwargs: {"sha256": kwargs["expected_sha"]}
    )
    result = driver.collect_formal_evidence(
            SimpleNamespace(
                autocad_fixture_sha256="a" * 64,
                revit_fixture_sha256="b" * 64,
                model_name=model_name,
                model_command=(driver.sys.executable, "-m", driver.MODEL_MODULE),
            ),
        tmp_path,
        reviewed,
        final,
        SimpleNamespace(get_checkpoint=lambda _: checkpoint),
        ctx.case.topology,
        policy,
        plugins,
        lambda: None,
    )
    assert result["policy_status"] == "DENIED"
    assert result["mcp_get_status"] == "WAITING"
    assert result["workflow_phase"] == "POLICY_APPROVAL"
    assert result["execution_grant_count"] == 0
    assert result["hosts"]["AUTOCAD"]["independent_final_read"]["value"] == 200
    assert result["hosts"]["REVIT"]["product_mutation_count"] == 0
    assert driver.Path(result["evidence_manifest_path"]).is_file()


def test_worktree_pythonpath_replaces_conflicting_controller_paths(monkeypatch, tmp_path):
    driver = _driver()
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "primary-checkout"))
    monkeypatch.setattr(driver.sys, "path", [str(tmp_path / "editable-primary")])
    paths = driver.worktree_source_paths()
    assert str(driver.ROOT) == paths[0]
    assert str(driver.ROOT / "platform/product_runtime/src") in paths
    assert all(
        driver.ROOT in driver.Path(item).parents or driver.Path(item) == driver.ROOT
        for item in paths
    )
    assert not any("editable-primary" in item or "primary-checkout" in item for item in paths)


def test_imported_product_module_audit_rejects_editable_primary_checkout(tmp_path):
    from types import SimpleNamespace

    driver = _driver()
    module_file = tmp_path / "design_product_runtime" / "__init__.py"
    module_file.parent.mkdir()
    module_file.write_text("old code", encoding="utf-8")
    with pytest.raises(ValueError, match="LIVE_PYTHON_PROVENANCE_INVALID"):
        driver.audit_imported_product_sources(
            {"design_product_runtime": SimpleNamespace(__file__=str(module_file))}
        )
    import design_product_runtime

    result = driver.audit_imported_product_sources(
        {"design_product_runtime": design_product_runtime}
    )
    assert result["design_product_runtime"]["path"].startswith("platform/product_runtime/src/")
    assert len(result["design_product_runtime"]["sha256"]) == 64


def test_python_source_manifest_rejects_missing_or_changed_product_module(tmp_path):
    driver = _driver()
    actual = driver.audit_imported_product_sources()
    assert driver.validate_python_source_manifest(actual) == actual
    with pytest.raises(ValueError, match="LIVE_PYTHON_PROVENANCE_INVALID"):
        driver.validate_python_source_manifest({})
    damaged = {key: dict(value) for key, value in actual.items()}
    damaged["design_product_runtime"]["sha256"] = "0" * 64
    with pytest.raises(ValueError, match="LIVE_PYTHON_PROVENANCE_INVALID"):
        driver.validate_python_source_manifest(damaged)


def test_python_source_manifest_rejects_hash_valid_module_path_substitution():
    """模块键必须指向本模块源码，不能借另一份有效源码和 SHA 冒名。"""

    driver = _driver()
    actual = driver.audit_imported_product_sources()
    damaged = {key: dict(value) for key, value in actual.items()}
    damaged["design_product_runtime"] = dict(actual["design_orchestrator"])
    with pytest.raises(ValueError, match="LIVE_PYTHON_PROVENANCE_INVALID"):
        driver.validate_python_source_manifest(damaged)


def test_model_command_requires_committed_in_tree_interpreter():
    """任意 caller argv 不能仅靠 REAL_SUBPROCESS 标签成为真实模型证明。"""

    driver = _driver()
    expected = (
        driver.sys.executable,
        "-m",
        "tests.integration.cross_host_product_model_interpreter",
    )
    assert driver.validate_reviewed_model_command(expected)["sha256"]
    with pytest.raises(ValueError, match="LIVE_MODEL_SOURCE_INVALID"):
        driver.validate_reviewed_model_command((driver.sys.executable, "-c", "print('{}')"))


@pytest.mark.parametrize(
    "damage", [None, "missing_id", "model", "proposal", "raw_usage", "raw_content"]
)
def test_model_provider_record_must_bind_raw_response_and_frozen_proposal(damage):
    """真实 provider 响应字段、解释结果和冻结身份必须形成同一条链。"""

    from copy import deepcopy
    from types import SimpleNamespace

    driver = _driver()
    proposal = {
        "kind": "PROPOSAL",
        "candidate_key": "reviewed-wall",
        "thickness": {"value": 300, "unit": "mm"},
    }
    response = {
        "id": "msg-provider-1",
        "model": "reviewed-model",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 12, "output_tokens": 20},
        "content": [{"type": "text", "text": driver.json.dumps(proposal)}],
    }
    record = {
        "client_submission_ref": "submission-current",
        "model_name": "reviewed-model",
        "invocation_id": response["id"],
        "request_id": None,
        "response_model": response["model"],
        "proposal": proposal,
        "raw_response": response,
        "usage": response["usage"],
    }
    record = deepcopy(record)
    if damage == "missing_id":
        del record["request_id"]
    elif damage == "model":
        record["response_model"] = "other-model"
    elif damage == "proposal":
        record["proposal"]["thickness"]["value"] = 200
    elif damage == "raw_usage":
        record["usage"] = {"input_tokens": 0, "output_tokens": 0}
    elif damage == "raw_content":
        record["raw_response"]["content"] = []
    result = SimpleNamespace(
        candidate_key="reviewed-wall", thickness_value=300.0, thickness_unit="mm"
    )
    if damage:
        with pytest.raises(ValueError, match="LIVE_MODEL_PROVENANCE_INVALID"):
            driver.validate_model_provider_record(
                record, client_submission_ref="submission-current", model_name="reviewed-model",
                candidate_key="reviewed-wall", result=result,
            )
    else:
        assert driver.validate_model_provider_record(
            record, client_submission_ref="submission-current", model_name="reviewed-model",
            candidate_key="reviewed-wall", result=result,
        ) == record


def test_reviewed_model_cli_uses_sdk_and_archives_response_without_secret(monkeypatch, tmp_path):
    """离线 SDK 假响应只测适配器；真实 live 路径仍调用原 SDK。"""

    from types import SimpleNamespace

    from tests.integration import cross_host_product_model_interpreter as interpreter

    proposal = {
        "kind": "PROPOSAL",
        "candidate_key": "reviewed-wall",
        "thickness": {"value": 300, "unit": "mm"},
    }
    raw = {
        "id": "provider-msg-1",
        "model": "reviewed-model",
        "stop_reason": "end_turn",
        "usage": {"input_tokens": 10, "output_tokens": 15},
        "content": [{"type": "text", "text": interpreter.json.dumps(proposal)}],
    }
    calls = []

    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(
            id=raw["id"], model=raw["model"], _request_id=None,
            usage=SimpleNamespace(model_dump=lambda: raw["usage"]),
            model_dump=lambda: raw,
        )

    monkeypatch.setattr(
        interpreter.anthropic, "Anthropic",
        lambda **kwargs: SimpleNamespace(messages=SimpleNamespace(create=create)),
    )
    evidence = tmp_path / "provider.json"
    environment = {
        "ANTHROPIC_AUTH_TOKEN": "offline-dummy-secret",
        "ANTHROPIC_BASE_URL": "https://provider.example/anthropic",
        "ANTHROPIC_MODEL": "reviewed-model",
        "DSP_MODEL_CANDIDATE_KEY": "reviewed-wall",
        "DSP_MODEL_EVIDENCE_FILE": str(evidence),
    }
    output = interpreter.run_model(
        {"client_submission_ref": "submission-1", "utterance": "Set it to 300 mm"},
        environment,
    )
    assert output == proposal
    assert len(calls) == 1
    assert calls[0]["messages"] == [{"role": "user", "content": "Set it to 300 mm"}]
    assert "offline-dummy-secret" not in evidence.read_text(encoding="utf-8")
    assert _driver().read_json(evidence)["raw_response"] == raw


@pytest.mark.parametrize(
    "damage", [None, "approval", "required_set", "checkpoint_plan", "saga_delta"]
)
def test_positive_authority_joins_reject_hash_valid_cross_owner_substitution(damage):
    from dataclasses import replace
    from types import SimpleNamespace

    from design_orchestrator.workflow_contracts import StableRef

    from tests.product_runtime.conftest import build_cross_host_task15_lineage

    driver = _driver()
    ctx = build_cross_host_task15_lineage()
    _, final, _, _, _ = _positive_projection_inputs()
    grants = [ctx.gateway_store.get_grant_v2(item.grant_hash) for item in ctx.authorities]
    approval = SimpleNamespace(approval_hash=grants[0].approval_hash)
    definition = SimpleNamespace(
        required_set_hash=ctx.materialization_plan.required_set_hash,
        approved_scope_hash=ctx.case.boundary_v2.scope_hash,
    )
    states = tuple(
        SimpleNamespace(
            execution_slice_hash=row.execution_slice_hash,
            materialization_id=row.materialization_id,
            approval_hash=grant.approval_hash,
            grant_hash=grant.grant_hash,
            binding_set_hash=grant.binding_set_hash,
            admitted_host_instance_id=grant.host_instance_id,
            actual_delta_hash=row.actual_delta_hash,
            verification_hash=row.verification_hash,
            status=SimpleNamespace(value="SUCCEEDED"),
        )
        for row, grant in zip(final.materializations, grants, strict=True)
    )
    saga = SimpleNamespace(definition=definition, slice_states=states)
    checkpoint = SimpleNamespace(
        execution_plan_ref=StableRef(
            ctx.execution_plan.execution_plan_id, ctx.execution_plan.execution_plan_hash
        )
    )
    if damage == "approval":
        approval.approval_hash = "0" * 64
    elif damage == "required_set":
        definition.required_set_hash = "0" * 64
    elif damage == "checkpoint_plan":
        checkpoint.execution_plan_ref = replace(
            checkpoint.execution_plan_ref, content_hash="0" * 64
        )
    elif damage == "saga_delta":
        states[0].actual_delta_hash = "0" * 64
    if damage:
        with pytest.raises(ValueError, match="LIVE_OWNER_AUTHORITY_INVALID"):
            driver.validate_positive_owner_lineage(
                ctx.case.changeset,
                ctx.case.boundary_v2,
                ctx.materialization_plan,
                ctx.execution_plan,
                grants,
                approval,
                saga,
                final,
                checkpoint,
            )
    else:
        driver.validate_positive_owner_lineage(
            ctx.case.changeset,
            ctx.case.boundary_v2,
            ctx.materialization_plan,
            ctx.execution_plan,
            grants,
            approval,
            saga,
            final,
            checkpoint,
        )


def test_durable_owner_reader_closes_first_store_when_second_constructor_fails(monkeypatch):
    """后续 owner 构造失败时，已打开的 PostgreSQL store 必须立即关闭。"""

    from types import SimpleNamespace

    import design_orchestrator.proposal_decision_postgres as decisions_module
    import design_product_runtime
    import psycopg

    class Database:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def transaction(self):
            return self

        def execute(self, *_args):
            return SimpleNamespace(fetchall=list)

    closed = []
    monkeypatch.setattr(psycopg, "connect", lambda *args, **kwargs: Database())
    monkeypatch.setattr(
        design_product_runtime,
        "create_postgres_product_task_request_store",
        lambda _dsn: SimpleNamespace(close=lambda: closed.append("requests")),
    )
    monkeypatch.setattr(
        decisions_module,
        "PostgresProposalDecisionStore",
        lambda _dsn: (_ for _ in ()).throw(RuntimeError("second store failed")),
    )
    with pytest.raises(RuntimeError, match="second store failed"):
        _driver()._read_durable_owners(SimpleNamespace(dsn="offline-only"), "task-1")
    assert closed == ["requests"]



@pytest.fixture
def _windows_pipe_contract_modules(monkeypatch):
    """Linux 离线 runner 使用窄 Win32 API 模块替身，实际 handle 路径照常受测。

    真正的 Windows runner 不替换系统模块；这只解决非 Windows 收集缺模块问题，
    绝不模拟成功的生产 Host 状态或绕过 CreateFile/WriteFile 断言。
    """

    import sys
    from types import ModuleType

    if sys.platform == "win32":
        return
    definitions = {
        "win32file": ("CreateFile", "CloseHandle", "WriteFile", "ReadFile"),
        "win32pipe": ("GetNamedPipeServerProcessId",),
        "win32con": (
            "GENERIC_READ", "GENERIC_WRITE", "OPEN_EXISTING", "FILE_ATTRIBUTE_NORMAL"
        ),
        "pywintypes": ("error",),
    }
    for name, attributes in definitions.items():
        module = ModuleType(name)
        for attr in attributes:
            if name == "pywintypes":
                setattr(module, attr, OSError)
            elif name == "win32con":
                setattr(module, attr, 1)
            else:
                setattr(module, attr, lambda *_args, **_kwargs: None)
        monkeypatch.setitem(sys.modules, name, module)


def test_actual_revit_pipe_server_pid_mismatch_closes_handle_before_write(
    monkeypatch, tmp_path, _windows_pipe_contract_modules
):
    """生产 transport 的实际 CreateFile handle 必须证明 OS server PID 后才能写命令。"""

    from types import SimpleNamespace

    import win32file
    import win32pipe
    from revit_sidecar.named_pipe import WindowsNamedPipeEndpoint

    composition = _composition()
    handle = object()
    created, closed, writes = [], [], []
    def original(*args):
        created.append(args)
        return handle
    monkeypatch.setattr(win32file, "CreateFile", original)
    monkeypatch.setattr(win32file, "CloseHandle", lambda value: closed.append(value))
    monkeypatch.setattr(win32file, "WriteFile", lambda *args: writes.append(args))
    monkeypatch.setattr(win32pipe, "GetNamedPipeServerProcessId", lambda value: 99)
    config = SimpleNamespace(
        autocad_endpoint="EnterpriseDesignAgent.wall-41",
        revit_pipe="EnterpriseDesignAgent.Revit.wall-42",
        autocad_host_instance_id="auto-host",
        revit_host_instance_id="revit-host",
    )
    with composition.audited_pipe_ownership(
        config, tmp_path, stage="MCP", check_head=lambda: None
    ), pytest.raises(ValueError, match="LIVE_PLUGIN_PIPE_OWNER_MISMATCH"):
        WindowsNamedPipeEndpoint(config.revit_pipe).exchange(b"never-send")
    assert len(created) == 1
    assert closed == [handle]
    assert writes == []
    assert win32file.CreateFile is original
    audit = _driver()._jsonl(tmp_path / "pipe-server-ownership.jsonl")
    assert audit[0]["server_pid"] == 99
    assert audit[0]["expected_pid"] == 42


def test_actual_autocad_open_audits_same_handle_before_exchange(
    monkeypatch, tmp_path, _windows_pipe_contract_modules
):
    import asyncio
    from types import SimpleNamespace

    import win32file
    import win32pipe
    from autocad_sidecar.ipc.transport import PipeTransport

    composition = _composition()
    handle = object()
    def original(*_args):
        return handle
    observed, writes, closed = [], [], []
    monkeypatch.setattr(win32file, "CreateFile", original)
    monkeypatch.setattr(win32file, "CloseHandle", lambda value: closed.append(value))
    monkeypatch.setattr(win32file, "WriteFile", lambda *args: writes.append(args))
    monkeypatch.setattr(
        win32pipe, "GetNamedPipeServerProcessId",
        lambda value: (observed.append(value), 41)[1],
    )
    config = SimpleNamespace(
        autocad_endpoint="EnterpriseDesignAgent.wall-41",
        revit_pipe="EnterpriseDesignAgent.Revit.wall-42",
        autocad_host_instance_id="auto-host",
        revit_host_instance_id="revit-host",
    )
    transport = PipeTransport(config.autocad_endpoint)
    with composition.audited_pipe_ownership(
        config, tmp_path, stage="CONTROLLER", check_head=lambda: None
    ):
        asyncio.run(transport.open())
        assert transport._handle is handle
        assert observed == [handle]
        assert writes == []
        asyncio.run(transport.close())
    assert closed == [handle]
    assert win32file.CreateFile is original
    rows = _driver()._jsonl(tmp_path / "pipe-server-ownership.jsonl")
    assert rows[0]["host_kind"] == "AUTOCAD"
    assert rows[0]["server_pid"] == 41


@pytest.mark.parametrize("damage", [None, "missing_mcp", "wrong_pid", "wrong_host"])
def test_pipe_ownership_archive_joins_actual_server_to_loaded_module_and_host(damage):
    """正式证据必须含两进程双 Host 的实际连接 PID 与已加载 DLL 身份。"""

    from types import SimpleNamespace

    driver = _driver()
    members = (
        SimpleNamespace(
            host_kind="AUTOCAD", host_instance_id="auto-host",
            transport_locator="EnterpriseDesignAgent.wall-41",
        ),
        SimpleNamespace(
            host_kind="REVIT", host_instance_id="revit-host",
            transport_locator="EnterpriseDesignAgent.Revit.wall-42",
        ),
    )
    plugins = {
        member.host_kind: {"inspection": {"pid": 41 if member.host_kind == "AUTOCAD" else 42}}
        for member in members
    }
    rows = [
        {
            "host_kind": member.host_kind,
            "host_instance_id": member.host_instance_id,
            "locator": member.transport_locator,
            "server_pid": plugins[member.host_kind]["inspection"]["pid"],
            "expected_pid": plugins[member.host_kind]["inspection"]["pid"],
            "stage": stage,
        }
        for stage in ("CONTROLLER", "MCP") for member in members
    ]
    if damage == "missing_mcp":
        rows = rows[:2]
    elif damage == "wrong_pid":
        rows[2]["server_pid"] = 99
    elif damage == "wrong_host":
        rows[3]["host_instance_id"] = "another-host"
    if damage:
        with pytest.raises(ValueError, match="LIVE_PLUGIN_PIPE_OWNER"):
            driver.validate_pipe_ownership_records(rows, members, plugins)
    else:
        assert driver.validate_pipe_ownership_records(rows, members, plugins) == rows


def _convergence_projection_inputs():
    from design_convergence import (
        CrossHostConvergenceVerifier,
        build_convergence_evidence_set,
        build_materialization_canonical_evidence,
    )

    from tests.product_runtime.conftest import build_cross_host_task15_lineage

    driver = _driver()
    ctx = build_cross_host_task15_lineage()
    _, final, _, evidence, _ = _positive_projection_inputs()
    items = []
    for query, execution_slice in zip(
        final.materializations, ctx.execution_plan.execution_slices, strict=True
    ):
        items.append(
            build_materialization_canonical_evidence(
                materialization_id=query.materialization_id,
                execution_slice=execution_slice,
                actual_delta=evidence[query.actual_delta_hash],
                verification_result=evidence[query.verification_hash],
                verification_evidence_bundle=evidence[query.evidence_bundle_hash],
                convergence_profile=ctx.case.profile,
            )
        )
    evidence_set = build_convergence_evidence_set(
        plan=ctx.materialization_plan, profile=ctx.case.profile, evidence_items=items
    )
    result = CrossHostConvergenceVerifier().verify(
        ctx.materialization_plan, ctx.case.profile, evidence_set
    )
    capture = {
        "plan": driver.plain(ctx.materialization_plan),
        "profile": driver.plain(ctx.case.profile),
        "evidence_set": driver.plain(evidence_set),
        "result": driver.plain(result),
    }
    return ctx, evidence, capture, result


@pytest.mark.parametrize("damage", [None, "missing", "wrong_set", "wrong_numeric"])
def test_convergence_capture_requires_exact_local_evidence_set_and_saga(damage, tmp_path):
    from copy import deepcopy
    from types import SimpleNamespace

    from design_convergence import (
        CrossHostConvergenceVerifier,
        MaterializationCanonicalEvidence,
        build_convergence_evidence_set,
        compute_materialization_canonical_evidence_hash,
    )
    from pydantic import TypeAdapter

    driver = _driver()
    ctx, evidence, capture, result = _convergence_projection_inputs()
    rows = [deepcopy(capture)]
    if damage == "missing":
        rows = []
    elif damage in {"wrong_set", "wrong_numeric"}:
        # Self-consistent, hash-valid competing set/result. The Saga/query can also be forged to
        # match this result; the local Step33 body join must still reject it.
        item = TypeAdapter(MaterializationCanonicalEvidence).validate_python(
            capture["evidence_set"]["evidence_items"][0]
        )
        original_field = item.verified_fields[0]
        altered = replace(
            item,
            verified_fields=(
                replace(
                    original_field,
                    value=(
                        float(original_field.value)
                        if type(original_field.value) is int
                        else int(original_field.value)
                    ) if damage == "wrong_numeric" else 301,
                ),
                *item.verified_fields[1:],
            ),
            evidence_hash="0" * 64,
        )
        # Rebind Any references with the authentic public Step33 bundle types.
        bundle = next(
            value for value in evidence.values() if hasattr(value, "evidence_bundle_hash")
        )
        altered = replace(
            altered,
            semantic_environment_ref=bundle.semantic_environment_ref,
            post_execution_projection_ref=bundle.post_execution_projection_ref,
        )
        altered = replace(
            altered, evidence_hash=compute_materialization_canonical_evidence_hash(altered)
        )
        # The other item is already available in the original object graph via public constructors.
        valid_items = []
        for query, execution_slice in zip(
            _positive_projection_inputs()[1].materializations,
            ctx.execution_plan.execution_slices,
            strict=True,
        ):
            from design_convergence import build_materialization_canonical_evidence
            valid_items.append(build_materialization_canonical_evidence(
                materialization_id=query.materialization_id,
                execution_slice=execution_slice,
                actual_delta=evidence[query.actual_delta_hash],
                verification_result=evidence[query.verification_hash],
                verification_evidence_bundle=evidence[query.evidence_bundle_hash],
                convergence_profile=ctx.case.profile,
            ))
        competing = build_convergence_evidence_set(
            plan=ctx.materialization_plan, profile=ctx.case.profile,
            evidence_items=(altered, valid_items[1]),
        )
        competing_result = CrossHostConvergenceVerifier().verify(
            ctx.materialization_plan, ctx.case.profile, competing
        )
        rows[0]["evidence_set"] = driver.plain(competing)
        rows[0]["result"] = driver.plain(competing_result)
        result = competing_result
    saga = SimpleNamespace(convergence_result_hash=result.convergence_result_hash)
    final = SimpleNamespace(
        convergence_result_hash=result.convergence_result_hash,
        materializations=_positive_projection_inputs()[1].materializations,
    )
    if damage:
        with pytest.raises(ValueError, match="LIVE_CONVERGENCE"):
            driver.validate_positive_convergence_capture(
                rows, ctx.materialization_plan, ctx.execution_plan,
                ctx.case.profile, evidence, saga, final,
            )
    else:
        from tests.integration.cross_host_product_live_composition import append_audit

        append_audit(tmp_path / "convergence-captures.jsonl", capture)
        assert driver._capture_profile(tmp_path, ctx.materialization_plan) == ctx.case.profile
        assert driver.validate_positive_convergence_capture(
            rows, ctx.materialization_plan, ctx.execution_plan,
            ctx.case.profile, evidence, saga, final,
        ) == capture


def test_public_convergence_verifier_decoration_calls_original_once_and_restores(
    monkeypatch, tmp_path
):
    from design_convergence import CrossHostConvergenceVerifier

    composition = _composition()
    calls = []
    result = {"convergence_result_hash": "a" * 64}

    def original(owner, plan, profile, evidence_set):
        calls.append((plan, profile, evidence_set))
        return result

    monkeypatch.setattr(CrossHostConvergenceVerifier, "verify", original)
    plan = {"materialization_plan_hash": "b" * 64}
    profile = {"profile_hash": "c" * 64}
    evidence_set = {"evidence_set_hash": "d" * 64}
    with composition.audit_runtime_owners(tmp_path, check_head=lambda: None):
        assert CrossHostConvergenceVerifier().verify(plan, profile, evidence_set) is result
    assert calls == [(plan, profile, evidence_set)]
    assert CrossHostConvergenceVerifier.verify is original
    rows = _driver()._jsonl(tmp_path / "convergence-captures.jsonl")
    assert len(rows) == 1
    assert rows[0]["result"]["convergence_result_hash"] == "a" * 64


def test_unavailable_exact_task_get_never_queries_or_dispatches_host(tmp_path):
    """真实编排 GET 路径只读取同一 task owner 状态，不允许增加 Host 审计记录。"""

    from dataclasses import dataclass

    from tests.integration.cross_host_product_live_composition import append_audit

    driver = _driver()

    @dataclass(frozen=True)
    class Query:
        """模拟 owner 返回的只读且可序列化 exact Task View。"""

        task_id: str

    class ExactMcp:
        def __init__(self, *, write_host=False, wrong_task=False):
            """仅记录查询身份；模拟异常 Host I/O 来证明 fail-closed。"""

            self.calls = []
            self.write_host = write_host
            self.wrong_task = wrong_task

        async def get(self, task_id):
            """只允许 exact task GET；如被故意注入 Host 请求必须拒绝。"""

            self.calls.append(task_id)
            if self.write_host:
                append_audit(tmp_path / "host-commands.jsonl", {"phase": "SEND"})
            return Query(
                task_id="another-task" if self.wrong_task else task_id
            )

    mcp = ExactMcp()
    result = driver.read_unavailable_exact_task_without_host_io(
        mcp, "task-canonical-1", tmp_path
    )
    assert result.task_id == "task-canonical-1"
    assert mcp.calls == ["task-canonical-1"]
    assert driver.read_json(tmp_path / "host-independent-get.json")["before"] == 0
    assert driver.read_json(tmp_path / "host-independent-get.json")["after"] == 0

    for damage in ("host_io", "wrong_task"):
        location = tmp_path / damage
        location.mkdir()
        client = ExactMcp(
            write_host=damage == "host_io", wrong_task=damage == "wrong_task"
        )
        # 测试替身写入自己隔离 case 的审计路径，避免与前一轮竞争。
        if damage == "host_io":
            original = client.get

            async def recorded(task_id):
                """将本轮额外 Host SEND 写入独立 case 的审计目录。"""

                append_audit(location / "host-commands.jsonl", {"phase": "SEND"})
                return await original(task_id)

            client.write_host = False
            client.get = recorded
        with pytest.raises(ValueError, match="LIVE_GET_HOST_IO_INVALID"):
            driver.read_unavailable_exact_task_without_host_io(
                client, "task-canonical-1", location
            )
        assert client.calls == ["task-canonical-1"]
        assert not (location / "host-independent-get.json").exists()


@pytest.mark.parametrize(
    ("scenario", "native_code", "native_commit_state"),
    [
        ("unavailable", "UNRELATED_ERROR", None),
        ("partial_commit", "REVISION_CONFLICT", "COMMIT_STATE_UNKNOWN"),
    ],
)
def test_collector_rejects_wrong_native_failure_before_projection(
    tmp_path, scenario, native_code, native_commit_state
):
    """进入真实 collector 的原始错误校验，不允许把伪失败投影成 PASS。"""

    from datetime import UTC, datetime

    driver = _driver()
    from tests.integration.cross_host_product_live_stages import stage_hash

    reviewed = _reviewed()
    member = next(
        item for item in reviewed.frozen.session_binding.members
        if item.host_kind == "REVIT"
    )
    case = {
        "case_id": "stage-collector-review",
        "scenario": scenario,
        "implementation_head": "a" * 40,
    }
    driver.write_once(tmp_path / "case.json", case)
    pending = {
        "stage_id": "stage-collector-1",
        "pending_hash": "a" * 64,
        "case_id": case["case_id"],
        "scenario": scenario,
        "implementation_head": case["implementation_head"],
        "task_id": reviewed.frozen.request.task_id,
        "request_hash": reviewed.frozen.request.request_hash,
        "session_binding_hash": reviewed.frozen.session_binding.binding_hash,
        "original_command_id": "revit-product-1",
        "host_instance_id": member.host_instance_id,
        "document_id": member.document_id,
        "native_target_id": member.native_target_id,
        "published_at": datetime.now(UTC).isoformat(),
        "prerequisite_hashes": {"gate": "a" * 64},
        "expected_revision": 0,
    }
    driver.write_once(tmp_path / "pending-stage.json", pending)
    completion = {
        "stage_id": pending["stage_id"],
        "pending_hash": pending["pending_hash"],
        "case_id": pending["case_id"],
        "task_id": pending["task_id"],
        "original_command_id": pending["original_command_id"],
        "operator": "external-human",
        "completed_at": datetime.now(UTC).isoformat(),
    }
    driver.write_once(tmp_path / "stage-controller-completion.json", completion)
    release = {
        "stage_id": pending["stage_id"],
        "pending_hash": pending["pending_hash"],
        "case_id": pending["case_id"],
        "task_id": pending["task_id"],
        "original_command_id": pending["original_command_id"],
        "completion_hash": stage_hash(completion),
        "proof_hash": stage_hash(pending["prerequisite_hashes"]),
    }
    driver.write_once(tmp_path / "stage-release.json", release)
    driver.write_once(tmp_path / "stage-release-consumed.json", release)
    command = {
        "mode": "EXECUTE" if scenario == "partial_commit" else "READ",
        "operation": (
            "set_wall_thickness" if scenario == "partial_commit"
            else "check_wall_thickness_readiness"
        ),
        "command_id": pending["original_command_id"],
    }
    pending["original_command_hash"] = stage_hash(command)
    # 本测试聚焦 native error gate；collector 必须先验原始 RECEIVE，才能解析 Saga。
    driver.write_once(tmp_path / "stage-send-attempt.json", {
        "stage_id": pending["stage_id"],
        "pending_hash": pending["pending_hash"],
        "command_id": pending["original_command_id"],
        "command_hash": stage_hash(command),
    })
    driver.write_once(tmp_path / "pending-stage.json.extra-not-used", {})
    # pending 已作为 immutable 文件存在：必须使用最初实际带有的哈希。
    # 本测试的 negative path 在 native response 之前仍需保留 stage command hash。
    stored_pending = driver.read_json(tmp_path / "pending-stage.json")
    stored_pending["original_command_hash"] = stage_hash(command)
    (tmp_path / "pending-stage.json").write_text(json.dumps(stored_pending))
    response = {"status": "ERROR", "error": {"code": native_code}}
    if native_commit_state is not None:
        response["error"]["commit_state"] = native_commit_state
    if scenario == "unavailable":
        response["revision_after"] = 0
    commands = [
        {"host_kind": "REVIT", "phase": "SEND", "command": command},
        {"host_kind": "REVIT", "phase": "RECEIVE", "command": command, "response": response},
    ]
    with pytest.raises(ValueError, match="LIVE_STAGE_NATIVE_ERROR_INVALID"):
        driver.project_staged_outcome(
            tmp_path, reviewed, None, None, [], {}, {},
            {}, commands
        )


@pytest.mark.parametrize(
    ("damage", "expected"),
    [
        ("not_all_ready", "all-required READY absent"),
        ("missing_autocad_delta", "AutoCAD durable delta absent"),
    ],
)
def test_actual_stage_prerequisites_never_allow_pending_without_ready_and_commit(
    tmp_path, monkeypatch, damage, expected
):
    """执行真实 stage_prerequisites：缺少 READY 或 AutoCAD committed 事实不发布 pending。

    只替身 durable 存储的读取结果，保留真正的校验函数和阶段前置条件。
    """

    from types import SimpleNamespace as NS

    from design_orchestrator.execution_collection_artifacts import (
        ExecutionGrantCollectionManifest,
        ProviderBindingCollectionManifest,
    )

    from tests.integration import cross_host_product_live_composition as composition

    driver = _driver()
    binding = {
        "topology_snapshot_hash": "t" * 64,
        "members": [
            {
                "host_kind": host,
                "host_instance_id": host.lower() + "-host",
                "document_id": host.lower() + ".fixture",
                "native_target_id": host.lower() + "-wall",
            }
            for host in ("AUTOCAD", "REVIT")
        ],
    }
    request = {"task_id": "task-stage-prereq"}
    driver.write_once(
        tmp_path / "frozen-submission.json",
        {"request": request, "session_binding": binding},
    )
    subject = {"observations": [
        {
            "host_kind": member["host_kind"],
            "host_instance_id": member["host_instance_id"],
            "document_id": member["document_id"],
            "native_target_id": member["native_target_id"],
            "host_revision": 0,
            "normalized_thickness_mm": 200,
        }
        for member in binding["members"]
    ]}
    driver.write_once(
        tmp_path / "pending-proposal.json",
        {"proposal": {"frozen": {
            "request": request, "session_binding": binding
        }, "subject": subject}},
    )
    ready_status = NS(value="READY")
    slices = [
        NS(
            host_runtime_ref=NS(host_type=member["host_kind"].lower()),
            execution_slice_hash="slice-" + member["host_kind"],
        )
        for member in binding["members"]
    ]
    plan = NS(
        execution_slices=slices,
        execution_plan_hash="plan-1",
    )
    materialization = NS(
        topology_snapshot_hash=binding["topology_snapshot_hash"],
        materialization_plan_hash="mat-plan-1",
        required_set_hash="required-1",
    )
    grants = [
        NS(
            grant_hash="grant-" + member["host_kind"],
            execution_slice_hash="slice-" + member["host_kind"],
            binding_set_hash="binding-" + member["host_kind"],
        )
        for member in binding["members"]
    ]
    receipts = [
        NS(
            status=ready_status,
            grant_hash=grant.grant_hash,
            execution_slice_hash=grant.execution_slice_hash,
            binding_set_hash=grant.binding_set_hash,
            materialization_plan_hash=materialization.materialization_plan_hash,
            observed_revision=0,
            host_runtime_ref=NS(
                host_type=member["host_kind"].lower(),
                host_instance_id=member["host_instance_id"],
            ),
            receipt_hash="receipt-" + member["host_kind"],
        )
        for grant, member in zip(grants, binding["members"], strict=True)
    ]
    readiness = (
        [] if damage == "not_all_ready"
        else [NS(status=ready_status, receipts=receipts)]
    )
    captures = {
        "execution_plan": [plan],
        "materialization_plan": [materialization],
        "binding_set": [object(), object()],
        "grant": grants,
        "approval": [NS(approval_hash="approval-1")],
        "readiness": readiness,
    }
    monkeypatch.setattr(
        composition,
        "reviewed_runtime_inputs",
        lambda *_args: (None, NS(), None),
    )
    monkeypatch.setattr(driver, "validate_owner_snapshots", lambda *_args: captures)
    monkeypatch.setattr(
        driver,
        "_read_durable_owners",
        lambda *_args: (
            {"artifacts": [], "evidence": [], "dispatches": []},
            NS(request=request, session_binding_payload=binding),
            None, [object()], None,
        ),
    )
    monkeypatch.setattr(
        driver,
        "validate_workflow_rows",
        lambda *_args: {
            "binding": object.__new__(ProviderBindingCollectionManifest),
            "grant": object.__new__(ExecutionGrantCollectionManifest),
        },
    )
    monkeypatch.setattr(driver, "validate_collection_capture", lambda *_args: None)
    command = NS(
        operation="set_wall_thickness",
        preconditions=[{"revision": 0}],
    )
    config = NS(autocad_host_instance_id="autocad-host")
    with pytest.raises(ValueError, match=expected):
        driver.stage_prerequisites(
            config, tmp_path, {"scenario": "partial_commit"},
            command, check_head=lambda: None,
        )
    assert not (tmp_path / "pending-stage.json").exists()
    assert not (tmp_path / "stage-send-attempt.json").exists()
