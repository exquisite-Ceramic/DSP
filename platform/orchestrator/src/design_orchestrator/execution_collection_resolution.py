"""Execution collection manifests 的只读解析边界。"""

from __future__ import annotations

from design_gateway_authorization import ExecutionGrantV2
from design_provider_binding import ProviderBindingSetV2

from .execution_collection_artifacts import (
    ExecutionGrantCollectionManifest,
    ProviderBindingCollectionManifest,
)
from .workflow_artifacts import workflow_artifact_content_hash
from .workflow_contracts import StableRef

_ERROR = "EXECUTION_COLLECTION_INVALID"


def _invalid(message: str) -> ValueError:
    """返回稳定 collection resolution 错误。"""

    return ValueError(f"{_ERROR}: {message}")


def _load_manifest(
    ref: StableRef,
    execution_plan,
    artifact_store,
    manifest_type,
):
    """先完整验证 workflow manifest，再允许读取任何原领域 owner。"""

    if not isinstance(ref, StableRef) or ref.content_hash is None:
        raise _invalid("collection ref must be a hashed StableRef")
    get_artifact = getattr(artifact_store, "get", None)
    if not callable(get_artifact):
        raise TypeError("artifact_store must provide get")
    try:
        manifest = get_artifact(ref)
    except Exception as exc:
        raise _invalid("collection artifact is unavailable") from exc
    if not isinstance(manifest, manifest_type):
        raise _invalid("collection artifact has an unexpected type")

    try:
        reconstructed = manifest_type.create(execution_plan, manifest.members)
        content_hash = workflow_artifact_content_hash(manifest)
    except (TypeError, ValueError) as exc:
        raise _invalid("collection manifest coverage or lineage is invalid") from exc

    if reconstructed != manifest:
        raise _invalid("collection manifest body differs from authoritative plan")
    if content_hash != ref.content_hash:
        raise _invalid("collection manifest content hash does not match its ref")
    return manifest


def resolve_provider_binding_collection(
    ref: StableRef,
    execution_plan,
    artifact_store,
    binding_store,
) -> tuple[ProviderBindingSetV2, ...]:
    """只读解析完整 ProviderBinding collection；不执行 admission/readiness。"""

    manifest = _load_manifest(
        ref,
        execution_plan,
        artifact_store,
        ProviderBindingCollectionManifest,
    )
    get_binding = getattr(binding_store, "get", None)
    if not callable(get_binding):
        raise TypeError("binding_store must provide get")

    resolved: list[ProviderBindingSetV2] = []
    for execution_slice, member in zip(
        execution_plan.execution_slices,
        manifest.members,
        strict=True,
    ):
        try:
            binding_set = get_binding(member.owner_ref.ref_id)
        except Exception as exc:
            raise _invalid("provider binding owner ref is unresolved") from exc
        if not isinstance(binding_set, ProviderBindingSetV2):
            raise _invalid("provider binding owner returned an invalid object")
        if (
            member.owner_ref.content_hash != binding_set.binding_set_hash
            or binding_set.execution_slice_id != execution_slice.execution_slice_id
            or binding_set.execution_slice_hash
            != execution_slice.execution_slice_hash
            or binding_set.materialization_id != execution_slice.materialization_id
            or binding_set.materialization_plan_hash
            != execution_plan.materialization_plan_hash
        ):
            raise _invalid("provider binding owner lineage does not match manifest")
        resolved.append(binding_set)
    return tuple(resolved)


def resolve_execution_grant_collection(
    ref: StableRef,
    execution_plan,
    artifact_store,
    gateway_store,
) -> tuple[ExecutionGrantV2, ...]:
    """只读解析完整 ExecutionGrant collection；绝不重新 admission。"""

    manifest = _load_manifest(
        ref,
        execution_plan,
        artifact_store,
        ExecutionGrantCollectionManifest,
    )
    get_grant = getattr(gateway_store, "get_grant_v2", None)
    if not callable(get_grant):
        raise TypeError("gateway_store must provide get_grant_v2")

    resolved: list[ExecutionGrantV2] = []
    for execution_slice, member in zip(
        execution_plan.execution_slices,
        manifest.members,
        strict=True,
    ):
        grant_hash = member.owner_ref.content_hash
        if grant_hash is None:
            raise _invalid("grant owner ref requires content_hash")
        try:
            grant = get_grant(grant_hash)
        except Exception as exc:
            raise _invalid("Gateway grant owner ref is unresolved") from exc
        if not isinstance(grant, ExecutionGrantV2):
            raise _invalid("Gateway owner returned an invalid ExecutionGrantV2")
        if (
            grant.grant_id != member.owner_ref.ref_id
            or grant.grant_hash != grant_hash
            or grant.execution_slice_id != execution_slice.execution_slice_id
            or grant.execution_slice_hash != execution_slice.execution_slice_hash
            or grant.materialization_id != execution_slice.materialization_id
            or grant.materialization_plan_hash
            != execution_plan.materialization_plan_hash
            or grant.changeset_hash != execution_plan.changeset_hash
            or grant.approved_scope_hash
            != execution_plan.approval_scope_ref.scope_hash
            or grant.host_instance_id
            != execution_slice.host_runtime_ref.host_instance_id
        ):
            raise _invalid("Gateway grant lineage does not match manifest")
        resolved.append(grant)
    return tuple(resolved)


__all__ = [
    "resolve_execution_grant_collection",
    "resolve_provider_binding_collection",
]
