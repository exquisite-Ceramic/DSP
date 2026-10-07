"""Workflow Orchestrator 持有的 execution collection manifests。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from design_execution_planning import ExecutionPlanV2

from .workflow_contracts import StableRef

_DIGEST_RE = re.compile(r"^[0-9a-f]{64}$")
_ERROR = "PROVIDER_BINDING_COLLECTION_INVALID"


def _invalid(message: str) -> ValueError:
    """返回稳定 manifest 校验错误。"""

    return ValueError(f"{_ERROR}: {message}")


def _text(value: object, field_name: str) -> str:
    """规范化 manifest 中不可为空的 identity 文本。"""

    if not isinstance(value, str) or not value.strip():
        raise _invalid(f"{field_name} must be a non-blank string")
    return value.strip()


def _digest(value: object, field_name: str) -> str:
    """只接受 canonical lowercase SHA-256。"""

    normalized = _text(value, field_name)
    if _DIGEST_RE.fullmatch(normalized) is None:
        raise _invalid(f"{field_name} must be lowercase SHA-256")
    return normalized


def _owner_ref(value: object) -> StableRef:
    """成员本身只冻结原 owner ref；完整 content hash 在 manifest 边界统一校验。"""

    if not isinstance(value, StableRef):
        raise _invalid("owner_ref must be a StableRef")
    return value


@dataclass(frozen=True, slots=True)
class ProviderBindingCollectionMember:
    """一个 ExecutionSlice 到原 ProviderBindingSetV2 owner ref 的不可变映射。"""

    execution_slice_id: str
    execution_slice_hash: str
    materialization_id: str
    owner_ref: StableRef

    def __post_init__(self) -> None:
        """冻结 Slice/materialization identity，并拒绝 short owner refs。"""

        object.__setattr__(
            self,
            "execution_slice_id",
            _text(self.execution_slice_id, "execution_slice_id"),
        )
        object.__setattr__(
            self,
            "execution_slice_hash",
            _digest(self.execution_slice_hash, "execution_slice_hash"),
        )
        object.__setattr__(
            self,
            "materialization_id",
            _text(self.materialization_id, "materialization_id"),
        )
        object.__setattr__(self, "owner_ref", _owner_ref(self.owner_ref))


@dataclass(frozen=True, slots=True)
class ProviderBindingCollectionManifest:
    """双 Slice ProviderBinding owner refs 的 workflow-local immutable manifest。

    该对象只解决编排层集合恢复，不复制 provider eligibility、授权或 runtime validity；
    每个成员的真实内容和有效性仍由原 ProviderBinding owner 负责。
    """

    execution_plan_id: str
    execution_plan_hash: str
    materialization_plan_hash: str
    required_slice_refs: tuple[StableRef, ...]
    members: tuple[ProviderBindingCollectionMember, ...]

    def __post_init__(self) -> None:
        """校验 manifest 自身结构与 exact Slice 覆盖，不把它升级成授权来源。"""

        object.__setattr__(
            self,
            "execution_plan_id",
            _text(self.execution_plan_id, "execution_plan_id"),
        )
        object.__setattr__(
            self,
            "execution_plan_hash",
            _digest(self.execution_plan_hash, "execution_plan_hash"),
        )
        object.__setattr__(
            self,
            "materialization_plan_hash",
            _digest(self.materialization_plan_hash, "materialization_plan_hash"),
        )

        refs = tuple(self.required_slice_refs)
        members = tuple(self.members)
        if len(refs) != 2 or len(members) != 2:
            raise _invalid("manifest requires exactly two REQUIRED Slice members")
        if any(
            not isinstance(item, StableRef) or item.content_hash is None
            for item in refs
        ):
            raise _invalid("required_slice_refs must contain hashed StableRef values")
        if any(
            not isinstance(item, ProviderBindingCollectionMember)
            for item in members
        ):
            raise _invalid("members must contain ProviderBindingCollectionMember values")
        if any(item.owner_ref.content_hash is None for item in members):
            raise _invalid("member owner_ref values must include content_hash")

        ref_pairs = tuple((item.ref_id, item.content_hash) for item in refs)
        member_pairs = tuple(
            (item.execution_slice_id, item.execution_slice_hash) for item in members
        )
        if ref_pairs != member_pairs:
            raise _invalid("member Slice identities must equal required_slice_refs in order")
        if len({item.execution_slice_id for item in members}) != len(members):
            raise _invalid("member execution_slice_id values must be unique")
        if len({item.materialization_id for item in members}) != len(members):
            raise _invalid("member materialization_id values must be unique")

        object.__setattr__(self, "required_slice_refs", refs)
        object.__setattr__(self, "members", members)

    @classmethod
    def create(
        cls,
        plan: "ExecutionPlanV2",
        members: Iterable[ProviderBindingCollectionMember],
    ) -> "ProviderBindingCollectionManifest":
        """从 authoritative ExecutionPlanV2 验证 exact coverage 后建立 manifest。"""

        from design_execution_planning import ExecutionPlanV2

        if not isinstance(plan, ExecutionPlanV2):
            raise TypeError("plan must be ExecutionPlanV2")
        slices = tuple(plan.execution_slices)
        supplied = tuple(members)
        if len(slices) != 2 or len(supplied) != 2:
            raise _invalid("two-slice V2 plan requires exactly two manifest members")
        if plan.execution_plan_id != f"XPV2-{plan.execution_plan_hash[:12]}":
            raise _invalid("execution plan id/hash relation is invalid")

        for execution_slice in slices:
            if (
                execution_slice.materialization_plan_hash
                != plan.materialization_plan_hash
            ):
                raise _invalid("Slice materialization plan lineage differs from plan")
            if execution_slice.changeset_hash != plan.changeset_hash:
                raise _invalid("Slice ChangeSet lineage differs from plan")

        for execution_slice, member in zip(slices, supplied, strict=True):
            if not isinstance(member, ProviderBindingCollectionMember):
                raise _invalid("members contain an invalid value")
            if (
                member.execution_slice_id != execution_slice.execution_slice_id
                or member.execution_slice_hash != execution_slice.execution_slice_hash
                or member.materialization_id != execution_slice.materialization_id
            ):
                raise _invalid("manifest member does not match required Slice lineage")

        return cls(
            execution_plan_id=plan.execution_plan_id,
            execution_plan_hash=plan.execution_plan_hash,
            materialization_plan_hash=plan.materialization_plan_hash,
            required_slice_refs=tuple(
                StableRef(
                    execution_slice.execution_slice_id,
                    execution_slice.execution_slice_hash,
                )
                for execution_slice in slices
            ),
            members=supplied,
        )


def _grant_invalid(message: str) -> ValueError:
    """返回稳定 ExecutionGrant manifest 校验错误。"""

    return ValueError(f"EXECUTION_GRANT_COLLECTION_INVALID: {message}")


@dataclass(frozen=True, slots=True)
class ExecutionGrantCollectionMember:
    """一个 ExecutionSlice 到原 Gateway ExecutionGrantV2 ref 的不可变映射。"""

    execution_slice_id: str
    execution_slice_hash: str
    materialization_id: str
    owner_ref: StableRef

    def __post_init__(self) -> None:
        """冻结 Slice/materialization identity；完整 ref 在 manifest 边界校验。"""

        try:
            execution_slice_id = _text(
                self.execution_slice_id,
                "execution_slice_id",
            )
            execution_slice_hash = _digest(
                self.execution_slice_hash,
                "execution_slice_hash",
            )
            materialization_id = _text(
                self.materialization_id,
                "materialization_id",
            )
            owner_ref = _owner_ref(self.owner_ref)
        except ValueError as exc:
            raise _grant_invalid(str(exc)) from exc

        object.__setattr__(self, "execution_slice_id", execution_slice_id)
        object.__setattr__(self, "execution_slice_hash", execution_slice_hash)
        object.__setattr__(self, "materialization_id", materialization_id)
        object.__setattr__(self, "owner_ref", owner_ref)


@dataclass(frozen=True, slots=True)
class ExecutionGrantCollectionManifest:
    """双 Slice Gateway grant refs 的 workflow-local immutable manifest。

    Manifest 只记录原 Gateway owner 的引用，不复制 admission、readiness 或执行状态。
    """

    execution_plan_id: str
    execution_plan_hash: str
    materialization_plan_hash: str
    required_slice_refs: tuple[StableRef, ...]
    members: tuple[ExecutionGrantCollectionMember, ...]

    def __post_init__(self) -> None:
        """验证自身结构与 ordered REQUIRED Slice identity。"""

        try:
            execution_plan_id = _text(self.execution_plan_id, "execution_plan_id")
            execution_plan_hash = _digest(
                self.execution_plan_hash,
                "execution_plan_hash",
            )
            materialization_plan_hash = _digest(
                self.materialization_plan_hash,
                "materialization_plan_hash",
            )
        except ValueError as exc:
            raise _grant_invalid(str(exc)) from exc

        refs = tuple(self.required_slice_refs)
        members = tuple(self.members)
        if len(refs) != 2 or len(members) != 2:
            raise _grant_invalid(
                "manifest requires exactly two REQUIRED Slice members"
            )
        if any(
            not isinstance(item, StableRef) or item.content_hash is None
            for item in refs
        ):
            raise _grant_invalid(
                "required_slice_refs must contain hashed StableRef values"
            )
        if any(
            not isinstance(item, ExecutionGrantCollectionMember)
            for item in members
        ):
            raise _grant_invalid(
                "members must contain ExecutionGrantCollectionMember values"
            )
        if any(item.owner_ref.content_hash is None for item in members):
            raise _grant_invalid(
                "member owner_ref values must include content_hash"
            )

        ref_pairs = tuple((item.ref_id, item.content_hash) for item in refs)
        member_pairs = tuple(
            (item.execution_slice_id, item.execution_slice_hash)
            for item in members
        )
        if ref_pairs != member_pairs:
            raise _grant_invalid(
                "member Slice identities must equal required_slice_refs in order"
            )
        if len({item.execution_slice_id for item in members}) != len(members):
            raise _grant_invalid("member execution_slice_id values must be unique")
        if len({item.materialization_id for item in members}) != len(members):
            raise _grant_invalid("member materialization_id values must be unique")

        object.__setattr__(self, "execution_plan_id", execution_plan_id)
        object.__setattr__(self, "execution_plan_hash", execution_plan_hash)
        object.__setattr__(
            self,
            "materialization_plan_hash",
            materialization_plan_hash,
        )
        object.__setattr__(self, "required_slice_refs", refs)
        object.__setattr__(self, "members", members)

    @classmethod
    def create(
        cls,
        plan: "ExecutionPlanV2",
        members: Iterable[ExecutionGrantCollectionMember],
    ) -> "ExecutionGrantCollectionManifest":
        """从 authoritative ExecutionPlanV2 建立 exact Grant ref manifest。"""

        from design_execution_planning import ExecutionPlanV2

        if not isinstance(plan, ExecutionPlanV2):
            raise TypeError("plan must be ExecutionPlanV2")
        slices = tuple(plan.execution_slices)
        supplied = tuple(members)
        if len(slices) != 2 or len(supplied) != 2:
            raise _grant_invalid(
                "two-slice V2 plan requires exactly two grant members"
            )
        if plan.execution_plan_id != f"XPV2-{plan.execution_plan_hash[:12]}":
            raise _grant_invalid("execution plan id/hash relation is invalid")

        for execution_slice, member in zip(slices, supplied, strict=True):
            if not isinstance(member, ExecutionGrantCollectionMember):
                raise _grant_invalid("members contain an invalid value")
            if (
                execution_slice.materialization_plan_hash
                != plan.materialization_plan_hash
            ):
                raise _grant_invalid(
                    "Slice materialization plan lineage differs from plan"
                )
            if execution_slice.changeset_hash != plan.changeset_hash:
                raise _grant_invalid("Slice ChangeSet lineage differs from plan")
            if (
                member.execution_slice_id != execution_slice.execution_slice_id
                or member.execution_slice_hash
                != execution_slice.execution_slice_hash
                or member.materialization_id != execution_slice.materialization_id
            ):
                raise _grant_invalid(
                    "grant manifest member does not match required Slice lineage"
                )

        return cls(
            execution_plan_id=plan.execution_plan_id,
            execution_plan_hash=plan.execution_plan_hash,
            materialization_plan_hash=plan.materialization_plan_hash,
            required_slice_refs=tuple(
                StableRef(
                    execution_slice.execution_slice_id,
                    execution_slice.execution_slice_hash,
                )
                for execution_slice in slices
            ),
            members=supplied,
        )


__all__ = [
    "ExecutionGrantCollectionManifest",
    "ExecutionGrantCollectionMember",
    "ProviderBindingCollectionManifest",
    "ProviderBindingCollectionMember",
]
