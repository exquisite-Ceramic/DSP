"""M3 Task 11 GitHub Actions 与依赖自动化治理契约。"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github/workflows"
DEPENDABOT = ROOT / ".github/dependabot.yml"
PHASE_I = WORKFLOWS / "phase-i-real-cross-host-materialization-saga.yml"
SELF_HOSTED_MARKER = "\n  phase-i-real-dual-host:\n"

APPROVED_ACTION_MAJORS = {
    "actions/checkout": "v7",
    "actions/setup-python": "v7",
    "actions/setup-dotnet": "v6",
}
SELF_HOSTED_COMPATIBILITY = {
    "actions/checkout": "v4",
    "actions/setup-python": "v5",
}
APPROVED_DEPENDABOT_ECOSYSTEMS = {
    "github-actions",
    "uv",
    "nuget",
    "dotnet-sdk",
}


def _workflow_paths() -> list[Path]:
    return sorted((*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")))


def _hosted_text(path: Path) -> str:
    """排除唯一尚未证明 Node 24 runner 版本的 real dual-Host self-hosted job。"""

    text = path.read_text(encoding="utf-8")
    if path == PHASE_I:
        assert SELF_HOSTED_MARKER in text
        return text.split(SELF_HOSTED_MARKER, 1)[0]
    return text


def _action_refs(text: str, action: str) -> list[str]:
    return re.findall(rf"uses:\s*{re.escape(action)}@(v\d+)", text)


def _hosted_offenders(action: str, expected_major: str) -> list[str]:
    offenders: list[str] = []
    for path in _workflow_paths():
        for major in _action_refs(_hosted_text(path), action):
            if major != expected_major:
                offenders.append(f"{path.relative_to(ROOT)}: {action}@{major}")
    return offenders


def test_hosted_checkout_uses_supported_node24_major() -> None:
    assert not _hosted_offenders("actions/checkout", "v7")


def test_hosted_setup_python_uses_supported_node24_major() -> None:
    assert not _hosted_offenders("actions/setup-python", "v7")


def test_hosted_setup_dotnet_uses_supported_node24_major() -> None:
    assert not _hosted_offenders("actions/setup-dotnet", "v6")


def test_real_dual_host_job_is_the_only_deferred_action_compatibility_exception() -> None:
    """未知 self-hosted runner 版本时，只冻结 real dual-Host job 的旧 Node runtime Actions。"""

    text = PHASE_I.read_text(encoding="utf-8")
    _, self_hosted = text.split(SELF_HOSTED_MARKER, 1)
    assert "- self-hosted" in self_hosted
    assert "- Windows" in self_hosted
    for action, expected_major in SELF_HOSTED_COMPATIBILITY.items():
        assert _action_refs(self_hosted, action) == [expected_major]
    assert not _action_refs(self_hosted, "actions/setup-dotnet")


def test_dependabot_is_bounded_to_approved_ecosystems_without_auto_merge() -> None:
    assert DEPENDABOT.exists(), "MOD-014 已批准，但 .github/dependabot.yml 尚不存在"
    text = DEPENDABOT.read_text(encoding="utf-8")
    assert "auto-merge" not in text.lower()
    assert "automerge" not in text.lower()

    config = yaml.safe_load(text)
    assert config["version"] == 2
    updates = config["updates"]
    ecosystems = {entry["package-ecosystem"] for entry in updates}
    assert ecosystems == APPROVED_DEPENDABOT_ECOSYSTEMS

    for entry in updates:
        assert entry["schedule"]["interval"] == "weekly"
        assert 1 <= entry["open-pull-requests-limit"] <= 5
