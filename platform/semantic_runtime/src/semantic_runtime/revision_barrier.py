"""Semantic Runtime 拥有的 Host revision barrier。"""

from __future__ import annotations

from typing import Protocol

from semantic_runtime.freshness import RevisionChangedError, SnapshotSet


class HostRevisionObservationPort(Protocol):
    """只读取 Host 当前 revision；不得在环境边界中实现 barrier 判定。"""

    def current_revision(self, document_ref: str) -> str:
        """返回指定 Host document 当前的 authoritative revision。"""
        ...


class RevisionBarrier:
    """用 PlanningSnapshot 冻结的 Host revision 做执行前 fail-closed 校验。"""

    def __init__(self, revisions: HostRevisionObservationPort) -> None:
        self._revisions = revisions

    def check(self, snapshot_set: SnapshotSet) -> None:
        """逐个校验 planning snapshot；任何缺失或变更都阻止后续执行。"""
        for snapshot in snapshot_set.members:
            try:
                observed_revision = self._revisions.current_revision(snapshot.document_ref)
            except KeyError as exc:
                raise RevisionChangedError(
                    f"host revision observation unavailable for {snapshot.document_ref!r}"
                ) from exc

            if not isinstance(observed_revision, str) or not observed_revision.strip():
                raise RevisionChangedError(
                    f"host revision observation unavailable for {snapshot.document_ref!r}"
                )

            current_revision = observed_revision.strip()
            if current_revision != snapshot.base_host_revision:
                raise RevisionChangedError(
                    "host revision changed from "
                    f"{snapshot.base_host_revision!r} to {current_revision!r} "
                    f"for {snapshot.document_ref!r}"
                )
