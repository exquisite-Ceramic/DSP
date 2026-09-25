"""Repository Regression Ruff baseline 解析的失败关闭契约。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RESOLVER = ROOT / ".github/scripts/resolve-ruff-baseline.sh"
ZERO_SHA = "0" * 40


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=check,
        text=True,
        capture_output=True,
    )


def _init_repo(path: Path, *, branch: str = "main") -> Path:
    path.mkdir(parents=True)
    _git(path, "init", "-b", branch)
    _git(path, "config", "user.email", "ci@example.invalid")
    _git(path, "config", "user.name", "CI Test")
    return path


def _commit(repo: Path, label: str) -> str:
    marker = repo / "marker.txt"
    marker.write_text(label + "\n", encoding="utf-8")
    _git(repo, "add", "marker.txt")
    _git(repo, "commit", "-m", label)
    return _git(repo, "rev-parse", "HEAD").stdout.strip()


def _init_remote(tmp_path: Path, *, label: str = "base") -> tuple[Path, str]:
    seed = _init_repo(tmp_path / "seed")
    base_sha = _commit(seed, label)
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    _git(seed, "remote", "add", "origin", str(remote))
    _git(seed, "push", "origin", "main")
    return remote, base_sha


def _run_resolver(
    repo: Path,
    *,
    event_name: str,
    pr_base_sha: str = "",
    push_before_sha: str = "",
    default_branch: str = "main",
) -> subprocess.CompletedProcess[str]:
    assert RESOLVER.is_file(), "Ruff baseline resolver 尚未实现"
    env = os.environ.copy()
    env.update(
        DSP_EVENT_NAME=event_name,
        DSP_PR_BASE_SHA=pr_base_sha,
        DSP_PUSH_BEFORE_SHA=push_before_sha,
        DSP_DEFAULT_BRANCH=default_branch,
        DSP_REMOTE_NAME="origin",
    )
    return subprocess.run(
        ["bash", str(RESOLVER)],
        cwd=repo,
        check=False,
        text=True,
        capture_output=True,
        env=env,
    )


def test_pull_request_uses_resolvable_base_sha(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    base_sha = _commit(repo, "base")
    _commit(repo, "head")

    result = _run_resolver(repo, event_name="pull_request", pr_base_sha=base_sha)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == base_sha


def test_pull_request_rejects_unresolvable_base_sha(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "head")

    result = _run_resolver(repo, event_name="pull_request", pr_base_sha="1" * 40)

    assert result.returncode != 0
    assert "pull_request base SHA is not resolvable" in result.stderr


def test_push_uses_resolvable_before_sha(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    before_sha = _commit(repo, "before")
    _commit(repo, "head")

    result = _run_resolver(repo, event_name="push", push_before_sha=before_sha)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == before_sha


def test_push_missing_before_uses_fetched_default_branch_merge_base(tmp_path: Path) -> None:
    remote, base_sha = _init_remote(tmp_path)
    repo = _init_repo(tmp_path / "repo")
    _git(repo, "remote", "add", "origin", str(remote))
    _git(repo, "fetch", "origin", "main")
    _git(repo, "checkout", "-b", "feature", "FETCH_HEAD")
    _commit(repo, "feature")
    _git(repo, "update-ref", "-d", "refs/remotes/origin/main")

    result = _run_resolver(repo, event_name="push", push_before_sha="2" * 40)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == base_sha
    assert _git(repo, "rev-parse", "refs/remotes/origin/main").stdout.strip() == base_sha


def test_push_missing_before_rejects_unrelated_default_branch(tmp_path: Path) -> None:
    remote, _ = _init_remote(tmp_path, label="remote-main")
    repo = _init_repo(tmp_path / "repo", branch="feature")
    _commit(repo, "unrelated-feature")
    _git(repo, "remote", "add", "origin", str(remote))

    result = _run_resolver(repo, event_name="push", push_before_sha="3" * 40)

    assert result.returncode != 0
    assert "no common ancestor" in result.stderr


def test_push_missing_before_rejects_merge_base_equal_to_head(tmp_path: Path) -> None:
    remote, head_sha = _init_remote(tmp_path)
    repo = tmp_path / "repo"
    _git(tmp_path, "clone", str(remote), str(repo))

    result = _run_resolver(repo, event_name="push", push_before_sha="4" * 40)

    assert _git(repo, "rev-parse", "HEAD").stdout.strip() == head_sha
    assert result.returncode != 0
    assert "fallback baseline equals HEAD" in result.stderr


def test_push_missing_before_rejects_fetch_failure(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "head")
    _git(repo, "remote", "add", "origin", str(tmp_path / "missing.git"))

    result = _run_resolver(repo, event_name="push", push_before_sha="5" * 40)

    assert result.returncode != 0
    assert "failed to fetch default branch" in result.stderr


def test_zero_before_push_keeps_head_parent_semantics(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    parent_sha = _commit(repo, "parent")
    _commit(repo, "head")

    result = _run_resolver(repo, event_name="push", push_before_sha=ZERO_SHA)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == parent_sha


def test_workflow_dispatch_keeps_head_parent_semantics(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    parent_sha = _commit(repo, "parent")
    _commit(repo, "head")

    result = _run_resolver(repo, event_name="workflow_dispatch")

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == parent_sha


def test_workflow_dispatch_rejects_root_commit_without_parent(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "repo")
    _commit(repo, "root")

    result = _run_resolver(repo, event_name="workflow_dispatch")

    assert result.returncode != 0
    assert "HEAD has no parent" in result.stderr
