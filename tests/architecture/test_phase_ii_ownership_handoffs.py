from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HITL = ROOT / "docs/superpowers/specs/2026-09-19-hitl-payload-ownership-contract.md"
COMPENSATION = ROOT / "docs/superpowers/specs/2026-09-19-compensation-execution-ownership.md"
RETENTION = ROOT / "docs/superpowers/specs/2026-09-19-checkpoint-retention-contract.md"


def _contract_block(path: Path, fence: str) -> dict[str, str]:
    """解析 ownership 文档中的稳定 key=value contract block。"""
    text = path.read_text(encoding="utf-8")
    marker = f"```{fence}"
    start = text.index(marker) + len(marker)
    end = text.index("```", start)
    values: dict[str, str] = {}
    for raw in text[start:end].splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def test_hitl_payload_contract_keeps_authoritative_truth_external() -> None:
    """HITL checkpoint 只允许 workflow-local 状态、stable refs 与展示元数据。"""
    assert HITL.is_file()
    contract = _contract_block(HITL, "hitl-ownership")
    assert contract["checkpoint_navigation_state"] == "MAY_OWN"
    assert contract["stable_refs"] == "MAY_OWN"
    assert contract["presentation_metadata"] == "MAY_OWN"
    for key in (
        "changeset_truth",
        "approval_execution_grant_truth",
        "saga_truth",
        "host_truth",
        "semantic_truth",
    ):
        assert contract[key] == "MUST_NOT_OWN"
    assert contract["domain_payload_rule"] == "STABLE_REF_OR_EXTERNAL_AUTHORITATIVE_STORE"


def test_compensation_contract_freezes_all_six_ownership_roles() -> None:
    """DIVERGED compensation 必须把六类 owner 分开，不能让 workflow 或 delivery 隐式接管。"""
    assert COMPENSATION.is_file()
    contract = _contract_block(COMPENSATION, "compensation-ownership")
    assert contract == {
        "decision_owner": "Execution Reconciliation / Execution Saga",
        "proposal_builder": "Execution Reconciliation / ExecutionSagaPlanner",
        "authorization_owner": "Approval / Gateway Authorization",
        "host_dispatcher_executor": "Execution Coordination + Host Adapter",
        "durable_truth_owner": "Execution Reconciliation / Execution Saga",
        "workflow_orchestrator_role": "COORDINATE_BY_STABLE_REF_ONLY",
        "delivery_success_equals_business_success": "NO",
    }


def test_checkpoint_retention_contract_preserves_external_owner_state() -> None:
    """Checkpoint GC 归 Orchestrator ops，且不得删除外部 authoritative state。"""
    assert RETENTION.is_file()
    contract = _contract_block(RETENTION, "checkpoint-retention")
    assert contract["gc_owner"] == "Workflow Orchestrator persistence ops"
    assert contract["active_workflow_gc"] == "FORBIDDEN"
    assert contract["paused_workflow_gc"] == "FORBIDDEN"
    assert contract["terminal_retention"] == "POLICY_CONFIGURED_AFTER_TERMINAL_OBSERVATION"
    assert contract["external_authoritative_state_deletion"] == "FORBIDDEN"
    assert contract["minimum_audit_metadata"] == "REQUIRED"
