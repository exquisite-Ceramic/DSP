"""Step32 V2 materialization-aware grant 的内存参考存储。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .contracts import (
    ApprovalState,
    GatewayAuthorizationError,
    GrantState,
    _utc_timestamp,
)
from .store import InMemoryGatewayAuthorizationStore
from .v2 import AdmittedExecutionAuthorityV2, ExecutionGrantV2


def _parse_utc(value: str) -> datetime:
    """把已规范化 UTC 时间解析为可比较的 datetime。"""
    raw = f"{value[:-1]}+00:00" if value.endswith("Z") else value
    return datetime.fromisoformat(raw)


@dataclass(frozen=True, slots=True)
class _StoredGrantV2:
    """V2 grant 与最小 lifecycle truth 的内部存储行。"""

    grant: ExecutionGrantV2
    state: GrantState
    admitted_at: str | None = None


class InMemoryGatewayAuthorizationStoreV2(InMemoryGatewayAuthorizationStore):
    """复用 V1 approval 存储语义并隔离维护 V2 grant lineage。"""

    def __init__(self) -> None:
        super().__init__()
        self._grants_v2: dict[str, _StoredGrantV2] = {}
        self._lineages_v2: dict[tuple[str, str, str, str], list[str]] = {}

    @staticmethod
    def _lineage_v2(grant: ExecutionGrantV2) -> tuple[str, str, str, str]:
        """冻结 approval + plan + materialization + Slice 的 V2 lineage key。"""
        return (
            grant.approval_hash,
            grant.materialization_plan_hash,
            grant.materialization_id,
            grant.execution_slice_hash,
        )

    def _project_expiry_v2(
        self,
        stored: _StoredGrantV2,
        evaluated_at: str,
    ) -> _StoredGrantV2:
        """在显式评估时间上投影 ACTIVE grant 的 EXPIRED truth。"""
        if (
            stored.state is GrantState.ACTIVE
            and _parse_utc(evaluated_at) >= _parse_utc(stored.grant.expires_at)
        ):
            projected = _StoredGrantV2(stored.grant, GrantState.EXPIRED)
            self._grants_v2[stored.grant.grant_hash] = projected
            return projected
        return stored

    def issue_or_get_grant_v2(self, grant: ExecutionGrantV2) -> ExecutionGrantV2:
        """按 exact V2 lineage 保持与 V1 相同的 active-grant 幂等语义。"""
        if not isinstance(grant, ExecutionGrantV2):
            raise TypeError("grant must be ExecutionGrantV2")
        lineage = self._lineage_v2(grant)
        with self._lock:
            grant_hashes = self._lineages_v2.get(lineage)
            if not grant_hashes:
                existing = self._grants_v2.get(grant.grant_hash)
                if existing is not None:
                    self._lineages_v2[lineage] = [existing.grant.grant_hash]
                    return existing.grant
                self._grants_v2[grant.grant_hash] = _StoredGrantV2(
                    grant,
                    GrantState.ACTIVE,
                )
                self._lineages_v2[lineage] = [grant.grant_hash]
                return grant

            current_hash = grant_hashes[-1]
            current = self._project_expiry_v2(
                self._grants_v2[current_hash],
                grant.issued_at,
            )
            same_binding = current.grant.binding_set_hash == grant.binding_set_hash

            if same_binding:
                if current.state in (GrantState.ACTIVE, GrantState.ADMITTED):
                    return current.grant
                if current.state is GrantState.REVOKED:
                    raise GatewayAuthorizationError(
                        "EXECUTION_GRANT_REVOKED",
                        "execution grant has been revoked",
                    )
                if current.state is GrantState.EXPIRED:
                    raise GatewayAuthorizationError(
                        "EXECUTION_GRANT_EXPIRED",
                        "execution grant has expired",
                    )

            if current.state is GrantState.ADMITTED:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_ALREADY_ADMITTED",
                    "admitted materialization authority cannot switch provider binding",
                )

            if current.state is GrantState.ACTIVE:
                self._grants_v2[current.grant.grant_hash] = _StoredGrantV2(
                    current.grant,
                    GrantState.REVOKED,
                    admitted_at=current.admitted_at,
                )
                self._grants_v2[grant.grant_hash] = _StoredGrantV2(
                    grant,
                    GrantState.ACTIVE,
                )
                grant_hashes.append(grant.grant_hash)
                return grant

            if current.state in (GrantState.REVOKED, GrantState.EXPIRED):
                self._grants_v2[grant.grant_hash] = _StoredGrantV2(
                    grant,
                    GrantState.ACTIVE,
                )
                grant_hashes.append(grant.grant_hash)
                return grant

            raise GatewayAuthorizationError(
                "EXECUTION_GRANT_CONFLICT",
                "unsupported materialization grant lineage state",
            )

    def get_grant_v2(self, grant_hash: str) -> ExecutionGrantV2 | None:
        """读取 V2 grant 的不可变 authority body。"""
        with self._lock:
            stored = self._grants_v2.get(grant_hash)
            return None if stored is None else stored.grant

    @staticmethod
    def _admitted_authority_v2(
        stored: _StoredGrantV2,
    ) -> AdmittedExecutionAuthorityV2:
        """从 authoritative stored grant 构造 admission authority。"""
        if stored.admitted_at is None:
            raise GatewayAuthorizationError(
                "EXECUTION_GRANT_CONFLICT",
                "admitted grant is missing admission evidence",
            )
        grant = stored.grant
        return AdmittedExecutionAuthorityV2(
            approval_hash=grant.approval_hash,
            grant_hash=grant.grant_hash,
            changeset_hash=grant.changeset_hash,
            approved_scope_hash=grant.approved_scope_hash,
            materialization_plan_hash=grant.materialization_plan_hash,
            materialization_id=grant.materialization_id,
            execution_slice_hash=grant.execution_slice_hash,
            binding_set_hash=grant.binding_set_hash,
            host_instance_id=grant.host_instance_id,
            admitted_at=stored.admitted_at,
        )

    def admit_grant_v2(
        self,
        grant_hash: str,
        admitted_at: str,
    ) -> AdmittedExecutionAuthorityV2:
        """原子 admission 一个 V2 grant，并校验父 approval 与 expiry。"""
        normalized_at = _utc_timestamp(admitted_at, "admitted_at")
        with self._lock:
            stored = self._grants_v2.get(grant_hash)
            if stored is None:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_CONFLICT",
                    "execution grant not found",
                )

            parent = self._approvals.get(stored.grant.approval_id)
            if parent is None:
                raise GatewayAuthorizationError(
                    "APPROVAL_RECORD_NOT_FOUND",
                    "parent approval record not found",
                )
            if parent.lifecycle.state is ApprovalState.REVOKED:
                raise GatewayAuthorizationError(
                    "APPROVAL_REVOKED",
                    "parent approval is revoked",
                )

            if stored.state is GrantState.ADMITTED:
                return self._admitted_authority_v2(stored)
            if stored.state is GrantState.REVOKED:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_REVOKED",
                    "execution grant has been revoked",
                )
            if stored.state is GrantState.EXPIRED:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_EXPIRED",
                    "execution grant has expired",
                )

            stored = self._project_expiry_v2(stored, normalized_at)
            if stored.state is GrantState.EXPIRED:
                raise GatewayAuthorizationError(
                    "EXECUTION_GRANT_EXPIRED",
                    "execution grant has expired",
                )

            admitted = _StoredGrantV2(
                stored.grant,
                GrantState.ADMITTED,
                admitted_at=normalized_at,
            )
            self._grants_v2[grant_hash] = admitted
            return self._admitted_authority_v2(admitted)


__all__ = ["InMemoryGatewayAuthorizationStoreV2"]
