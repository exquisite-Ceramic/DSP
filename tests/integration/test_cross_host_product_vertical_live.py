"""Task 16：Cross-Host Product Vertical 四场景真实双 Host 验收契约。

离线 CI 仅核验工作流与 runbook，并默认跳过 live mutation。
真实执行必须通过显式 live flag、受控 Windows 双 Host、真实模型/MCP/人工决策。
"""

from __future__ import annotations

import importlib
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/cross-host-product-vertical.yml"
RUNBOOK = ROOT / "docs/runbooks/cross-host-product-vertical.md"
SCENARIOS = ("deny", "unavailable", "positive", "partial_commit")
REQUIRED_LIVE_ENV = (
    "DSP_TEST_POSTGRES_DSN",
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
)


def _live_gate() -> None:
    """只有显式 Windows live runner 才能执行真实模型与双 Host I/O。"""

    if os.environ.get("DSP_CROSS_HOST_PRODUCT_LIVE") != "1":
        pytest.skip("set DSP_CROSS_HOST_PRODUCT_LIVE=1 for controlled live acceptance")
    if os.name != "nt":
        pytest.fail("controlled Cross-Host Product live acceptance requires Windows")
    missing = tuple(name for name in REQUIRED_LIVE_ENV if not os.environ.get(name))
    if missing:
        pytest.fail("missing controlled live configuration: " + ", ".join(missing))


def _exact_head() -> str:
    """读取现场实际 checkout 的 exact implementation SHA。"""

    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        text=True,
    ).strip()


def _run_real_case(scenario: str) -> Mapping[str, object]:
    """只允许 test-support 调用生产 MCP/Host adapters，不导入 Phase I 执行 helper。"""

    _live_gate()
    if scenario not in SCENARIOS:
        raise ValueError("unsupported controlled live scenario")
    try:
        support = importlib.import_module(
            "tests.integration.cross_host_product_live_support"
        )
    except ImportError as exc:
        pytest.fail(
            "controlled live harness is unavailable; "
            "no synthetic successful acceptance is permitted: "
            + str(exc)
        )
    config_type = getattr(support, "CrossHostProductLiveConfig", None)
    runner = getattr(support, "run_controlled_case", None)
    if config_type is None or not callable(runner):
        pytest.fail("controlled live harness lacks the required production-backed API")
    config = config_type.from_environment()
    result = runner(config=config, scenario=scenario)
    if not isinstance(result, Mapping):
        pytest.fail("live harness must return a structured evidence manifest")
    if result.get("implementation_head") != _exact_head():
        pytest.fail("live evidence must be pinned to the executed exact HEAD")
    if result.get("scenario") != scenario:
        pytest.fail("live evidence scenario identity mismatch")
    if result.get("model_invocation_kind") != "REAL":
        pytest.fail("a fake model is not a valid controlled-live entry")
    if result.get("entrypoint") != "MCP_PRODUCT_TASK_V2":
        pytest.fail("acceptance must enter through the real V2 MCP ProductTask")
    if result.get("human_decision") != "ACCEPTED":
        pytest.fail("each mandatory live scenario requires explicit human ACCEPT")
    for field_name in (
        "fixture_sha256",
        "autocad_build_identity",
        "revit_build_identity",
        "request_hash",
        "session_binding_hash",
        "topology_snapshot_hash",
        "proposal_subject_hash",
        "pause_id",
        "human_decision_ref",
        "evidence_manifest_path",
    ):
        if not result.get(field_name):
            pytest.fail(f"live evidence is missing required lineage: {field_name}")
    return result


def _host_results(result: Mapping[str, object]) -> Mapping[str, object]:
    """要求两端独立 Host evidence 明确存在，不把 EXECUTE receipt 当验证。"""

    hosts = result.get("hosts")
    assert isinstance(hosts, Mapping)
    assert set(hosts) == {"AUTOCAD", "REVIT"}
    return hosts


def _assert_zero_product_mutation(
    result: Mapping[str, object],
    *,
    require_both_reads: bool = True,
) -> None:
    """双端 mutation 必须为零；离线 Host 允许只有显式缺失原因而无 final READ。"""

    hosts = _host_results(result)
    for host_kind in ("AUTOCAD", "REVIT"):
        host = hosts[host_kind]
        assert isinstance(host, Mapping)
        assert host["product_mutation_count"] == 0
        baseline = host.get("independent_baseline_read")
        observed = host.get("independent_final_read")
        if observed is None and not require_both_reads:
            reason = host.get("evidence_absent_reason")
            assert isinstance(reason, str) and reason.strip(), host_kind
        else:
            assert baseline is not None, host_kind
            assert observed == baseline, host_kind


def test_controlled_live_collection_workflow_has_strict_host_gate() -> None:
    """离线 RED：专用 workflow 必须隔离 collect/offline 与真实 Windows mutation。"""

    yaml = pytest.importorskip("yaml")
    assert WORKFLOW.is_file(), "Task 16 dedicated workflow is missing"
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    dispatch = workflow["on"]["workflow_dispatch"]
    scenario = dispatch["inputs"]["scenario"]
    assert tuple(scenario["options"]) == SCENARIOS

    offline = workflow["jobs"]["cross-host-product-offline"]
    assert offline["runs-on"] == "ubuntu-latest"
    assert offline["env"]["DSP_CROSS_HOST_PRODUCT_LIVE"] == "0"
    offline_commands = "\n".join(
        item.get("run", "")
        for item in offline["steps"]
        if isinstance(item, dict)
    )
    assert "test_cross_host_product_vertical_live.py" in offline_commands
    assert "--collect-only" in offline_commands
    assert "test_cross_host_product_e2e.py" in offline_commands

    live = workflow["jobs"]["cross-host-product-real"]
    assert live["runs-on"] == [
        "self-hosted",
        "Windows",
        "dsp-cross-host-product",
    ]
    assert live["env"]["DSP_CROSS_HOST_PRODUCT_LIVE"] == "1"
    assert "workflow_dispatch" in live["if"]
    live_commands = "\n".join(
        item.get("run", "")
        for item in live["steps"]
        if isinstance(item, dict)
    )
    assert "test_cross_host_product_vertical_live.py" in live_commands
    assert "DSP_CROSS_HOST_PRODUCT_SCENARIO" in live_commands


def test_controlled_live_runbook_freezes_four_case_evidence() -> None:
    """离线 RED：runbook 必须冻结 fixture/reset/批准/partial-commit 时序。"""

    assert RUNBOOK.is_file(), "Task 16 controlled-live runbook is missing"
    text = RUNBOOK.read_text(encoding="utf-8")
    for marker in (
        "DSP_CROSS_HOST_PRODUCT_LIVE",
        "SHA-256",
        "真实模型",
        "MCP",
        "ACCEPT",
        "REQUIRED",
        "AutoCAD",
        "Revit",
        "200 mm",
        "300 mm",
        "201 mm",
        "REVISION_CONFLICT",
        "BEFORE_COMMIT",
        "PARTIALLY_COMMITTED",
        "CONVERGED",
        "SUCCEEDED",
        "DO NOT SAVE",
        "implementation HEAD",
        "evidence manifest",
    ):
        assert marker in text, f"controlled live runbook missing: {marker}"


def test_cross_host_live_case_policy_deny_has_zero_mutation() -> None:
    """Case 1：真实模型/MCP/ACCEPT 后 V2 policy deny；双端独立读取保持原状态。"""

    result = _run_real_case("deny")
    assert result["policy_status"] == "DENIED"
    assert result["execution_grant_count"] == 0
    _assert_zero_product_mutation(result)


def test_cross_host_live_case_required_host_unavailable_is_atomic_pre_execution() -> None:
    """Case 2：一个 REQUIRED Host 不可用；另一端不得发生 ProductTask mutation。"""

    result = _run_real_case("unavailable")
    assert result["required_host_set"] == ["AUTOCAD", "REVIT"]
    assert result["readiness_status"] == "NOT_READY"
    assert result["required_host_downgraded"] is False
    _assert_zero_product_mutation(result, require_both_reads=False)


def test_cross_host_live_case_positive_two_independent_300mm_reads() -> None:
    """Case 3：一个 task/Saga、两个 REQUIRED Slice、每端一次提交及独立 300mm READ。"""

    result = _run_real_case("positive")
    assert result["task_id"]
    assert result["saga_id"]
    assert result["task_count"] == 1
    assert result["saga_count"] == 1
    assert result["required_host_set"] == ["AUTOCAD", "REVIT"]
    assert result["required_slice_count"] == 2
    assert result["readiness_status"] == "READY"
    assert result["convergence_status"] == "CONVERGED"
    assert result["saga_status"] == "SUCCEEDED"
    assert result["mcp_get_status"] == "SUCCEEDED"

    for host_kind, host in _host_results(result).items():
        assert host["product_mutation_count"] == 1, host_kind
        assert host["committed_revision"] == host["baseline_revision"] + 1
        assert host["independent_final_read"]["value"] == pytest.approx(300.0)
        assert host["independent_final_read"]["unit"] == "mm"
        assert host["verification_source"] == "INDEPENDENT_HOST_READ"
        assert host["verification_revision"] == host["committed_revision"]


def test_cross_host_live_case_partial_commit_preserves_unknown_and_before_commit() -> None:
    """Case 4：ready→AutoCAD commit→独立 Revit 200→201→Revit BEFORE_COMMIT 冲突。"""

    result = _run_real_case("partial_commit")
    assert result["required_host_set"] == ["AUTOCAD", "REVIT"]
    assert result["readiness_status"] == "READY"
    assert result["all_required_readiness_passed"] is True
    assert result["event_order"] == [
        "ALL_REQUIRED_READY",
        "AUTOCAD_PRODUCT_COMMITTED",
        "INDEPENDENT_REVIT_EDIT_201MM",
        "REVIT_PRODUCT_REVISION_CONFLICT",
    ]
    assert result["independent_edit"]["host_kind"] == "REVIT"
    assert result["independent_edit"]["before_mm"] == pytest.approx(200.0)
    assert result["independent_edit"]["after_mm"] == pytest.approx(201.0)
    assert result["revit_failure_ref"] == "REVISION_CONFLICT"
    assert result["revit_failure_phase"] == "BEFORE_COMMIT"
    assert result["revit_product_actual_delta_hash"] is None
    assert result["convergence_status"] is None
    assert result["saga_status"] == "PARTIALLY_COMMITTED"
    assert result["mcp_get_status"] == "PARTIALLY_COMMITTED"
    assert result["automatic_compensation_count"] == 0
    hosts = _host_results(result)
    assert hosts["AUTOCAD"]["product_mutation_count"] == 1
    assert hosts["AUTOCAD"]["independent_final_read"]["value"] == pytest.approx(300.0)
    assert hosts["REVIT"]["product_mutation_count"] == 0


def test_controlled_live_workflow_archives_scenario_evidence() -> None:
    """Task 16 RED：live runner 应持久归档场景证据，不仅打印 manifest path。"""

    yaml = pytest.importorskip("yaml")
    workflow = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    live = workflow["jobs"]["cross-host-product-real"]
    evidence_dir = live["env"]["DSP_CROSS_HOST_PRODUCT_EVIDENCE_DIR"]
    assert evidence_dir == "artifacts/cross-host-product-live"
    uploads = [
        step
        for step in live["steps"]
        if str(step.get("uses", "")).startswith("actions/upload-artifact@")
    ]
    assert len(uploads) == 1
    upload = uploads[0]
    assert "always()" in upload["if"]
    assert upload["with"]["path"] == evidence_dir
    assert upload["with"]["if-no-files-found"] == "error"
    assert "scenario" in upload["with"]["name"]
    assert "github.sha" in upload["with"]["name"]


def test_controlled_live_manifest_requires_file_under_evidence_dir(tmp_path) -> None:
    """Task 16 RED：拒绝未落盘、目录外、identity 不匹配的 evidence manifest。"""

    import json

    from tests.integration.test_cross_host_product_vertical_live import (
        _validate_evidence_manifest,
    )

    evidence_dir = tmp_path / "evidence"
    evidence_dir.mkdir()
    elsewhere = tmp_path / "elsewhere.json"
    expected = {
        "implementation_head": "a" * 40,
        "scenario": "positive",
        "request_hash": "b" * 64,
    }
    elsewhere.write_text(json.dumps(expected), encoding="utf-8")

    with pytest.raises(ValueError, match="LIVE_EVIDENCE_MANIFEST_PATH_INVALID"):
        _validate_evidence_manifest(
            {**expected, "evidence_manifest_path": str(elsewhere)},
            evidence_root=evidence_dir,
        )

    missing = evidence_dir / "missing.json"
    with pytest.raises(ValueError, match="LIVE_EVIDENCE_MANIFEST_MISSING"):
        _validate_evidence_manifest(
            {**expected, "evidence_manifest_path": str(missing)},
            evidence_root=evidence_dir,
        )

    inside = evidence_dir / "evidence.json"
    inside.write_text(
        json.dumps({**expected, "request_hash": "c" * 64}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="LIVE_EVIDENCE_MANIFEST_LINEAGE_INVALID"):
        _validate_evidence_manifest(
            {**expected, "evidence_manifest_path": str(inside)},
            evidence_root=evidence_dir,
        )

    inside.write_text(json.dumps(expected), encoding="utf-8")
    _validate_evidence_manifest(
        {**expected, "evidence_manifest_path": str(inside)},
        evidence_root=evidence_dir,
    )
