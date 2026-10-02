"""Task 3：ConfiguredRevitCandidate 与 SessionBinding 的 canonical integrity 契约测试。"""

from __future__ import annotations

import importlib

import pytest
from design_changeset import canonical_hash


def _front_door_module():
    """延迟导入尚未实现的 source-only package，使 RED 聚焦到缺失产品契约。"""

    try:
        return importlib.import_module("design_product_front_door")
    except ModuleNotFoundError as exc:
        pytest.fail(f"design_product_front_door 尚未实现: {exc}")


def _types():
    """取得批准计划冻结的两个 immutable contract 类型。"""

    module = _front_door_module()
    candidate_type = getattr(module, "ConfiguredRevitCandidate", None)
    binding_type = getattr(module, "SessionBinding", None)
    assert candidate_type is not None, "ConfiguredRevitCandidate 尚未实现"
    assert binding_type is not None, "SessionBinding 尚未实现"
    return candidate_type, binding_type


def _candidate_body(**overrides: str) -> dict[str, str]:
    """构造 candidate_hash 的权威配置 body；字段与实施计划冻结接口一一对应。"""

    body = {
        "candidate_key": "primary-revit",
        "project_id": "project-id",
        "transport_locator": "configured-revit-pipe",
        "document_id": r"C:\path\to\fixture.rvt",
        "semantic_target_id": "WALL-001",
        "native_target_unique_id": "reviewed-wall-unique-id",
    }
    body.update(overrides)
    return body


def _binding_body(*, candidate_hash: str, **overrides: str) -> dict[str, str]:
    """构造 binding_hash 的 authority body；document_title 明确不是 identity。"""

    body = {
        "session_ref": "session-opaque-1",
        "project_id": "project-id",
        "host_kind": "REVIT",
        "candidate_key": "primary-revit",
        "candidate_hash": candidate_hash,
        "transport_locator": "configured-revit-pipe",
        "host_instance_id": "revit-runtime-7",
        "document_id": r"C:\path\to\fixture.rvt",
    }
    body.update(overrides)
    return body


def _candidate():
    """使用仓库 canonical_hash 构造一个完整且自洽的 candidate contract。"""

    candidate_type, _ = _types()
    body = _candidate_body()
    return candidate_type(**body, candidate_hash=canonical_hash(body))


def test_candidate_accepts_exact_canonical_authority_hash() -> None:
    """candidate_hash 必须覆盖 project/locator/document/semantic/native 全部配置 authority。"""

    candidate = _candidate()
    assert candidate.candidate_key == "primary-revit"
    assert candidate.candidate_hash == canonical_hash(_candidate_body())


def test_candidate_rejects_changed_body_under_supplied_hash() -> None:
    """配置 body 发生任何 authority 漂移时，旧 candidate_hash 不能继续被接受。"""

    candidate_type, _ = _types()
    original = _candidate_body()
    with pytest.raises(ValueError, match="FRONT_DOOR_CANDIDATE_HASH_INVALID"):
        candidate_type(
            **_candidate_body(semantic_target_id="WALL-CHANGED"),
            candidate_hash=canonical_hash(original),
        )


def test_candidate_rejects_title_only_or_relative_document_identity() -> None:
    """durable v1 只接受稳定 absolute path；Revit title 或相对路径不能成为 document authority。"""

    candidate_type, _ = _types()
    for document_id in ("Fixture.rvt", r"models\Fixture.rvt", "./Fixture.rvt"):
        body = _candidate_body(document_id=document_id)
        with pytest.raises(ValueError, match="FRONT_DOOR_DOCUMENT_ID_INVALID"):
            candidate_type(**body, candidate_hash=canonical_hash(body))


def test_session_binding_accepts_exact_authority_hash_and_excludes_title() -> None:
    """document_title 仅为展示元数据；不同 title 不改变同一 authority binding_hash。"""

    _, binding_type = _types()
    candidate = _candidate()
    body = _binding_body(candidate_hash=candidate.candidate_hash)
    binding_hash = canonical_hash(body)

    first = binding_type(
        **body,
        document_title="Fixture A",
        binding_hash=binding_hash,
    )
    second = binding_type(
        **body,
        document_title="Renamed Presentation Title",
        binding_hash=binding_hash,
    )

    assert first.binding_hash == second.binding_hash == binding_hash
    assert first.document_title != second.document_title


def test_session_binding_rejects_malformed_or_body_mismatched_hash() -> None:
    """binding_hash 必须是 exact authority body 的 canonical hash，不能只满足字符串形状。"""

    _, binding_type = _types()
    candidate = _candidate()
    body = _binding_body(candidate_hash=candidate.candidate_hash)

    with pytest.raises(ValueError, match="FRONT_DOOR_BINDING_HASH_INVALID"):
        binding_type(
            **body,
            document_title="Fixture",
            binding_hash="not-a-sha256",
        )

    original_hash = canonical_hash(body)
    with pytest.raises(ValueError, match="FRONT_DOOR_BINDING_HASH_INVALID"):
        binding_type(
            **_binding_body(
                candidate_hash=candidate.candidate_hash,
                host_instance_id="revit-runtime-changed",
            ),
            document_title="Fixture",
            binding_hash=original_hash,
        )


def test_session_binding_hash_must_include_candidate_hash() -> None:
    """防止回退到未冻结 candidate authority 的旧 hash body。"""

    _, binding_type = _types()
    candidate = _candidate()
    body = _binding_body(candidate_hash=candidate.candidate_hash)
    body_without_candidate_hash = {
        key: value for key, value in body.items() if key != "candidate_hash"
    }

    with pytest.raises(ValueError, match="FRONT_DOOR_BINDING_HASH_INVALID"):
        binding_type(
            **body,
            document_title="Fixture",
            binding_hash=canonical_hash(body_without_candidate_hash),
        )


def test_session_binding_rejects_relative_document_identity() -> None:
    """SessionBinding 本身也必须保护 saved-document absolute identity，不能只依赖 config parser。"""

    _, binding_type = _types()
    candidate = _candidate()
    body = _binding_body(
        candidate_hash=candidate.candidate_hash,
        document_id="Fixture.rvt",
    )

    with pytest.raises(ValueError, match="FRONT_DOOR_DOCUMENT_ID_INVALID"):
        binding_type(
            **body,
            document_title="Fixture",
            binding_hash=canonical_hash(body),
        )


def _v2_member(module, *, host_kind: str):
    """构造一个 exact REQUIRED Host member；哈希字段只表达已冻结 owner refs。"""

    if host_kind == "REVIT":
        return module.SessionBindingMemberV2(
            host_kind="REVIT",
            role="INITIATOR",
            configured_reference_id="primary-revit",
            configured_reference_hash="1" * 64,
            transport_locator="configured-revit-pipe",
            host_instance_id="revit-runtime-7",
            document_id=r"C:\path\to\fixture.rvt",
            native_target_id="reviewed-wall-unique-id",
            host_binding_fingerprint="2" * 64,
        )
    return module.SessionBindingMemberV2(
        host_kind="AUTOCAD",
        role="BOUND_REQUIRED",
        configured_reference_id="primary-autocad",
        configured_reference_hash="3" * 64,
        transport_locator="configured-autocad-pipe",
        host_instance_id="autocad-runtime-3",
        document_id=r"C:\path\to\fixture.dwg",
        native_target_id="reviewed-wall-entity-id",
        host_binding_fingerprint="4" * 64,
    )


def _create_v2_binding(*, members=None):
    """通过公开 create API 构造 exact 两 Host binding。"""

    module = _front_door_module()
    binding_type = getattr(module, "SessionBindingV2", None)
    member_type = getattr(module, "SessionBindingMemberV2", None)
    assert binding_type is not None, "SessionBindingV2 尚未实现"
    assert member_type is not None, "SessionBindingMemberV2 尚未实现"
    if members is None:
        members = (_v2_member(module, host_kind="REVIT"), _v2_member(module, host_kind="AUTOCAD"))
    return binding_type.create(
        session_ref="session-cross-host-1",
        project_id="project-id",
        semantic_target_id="WALL-001",
        semantic_environment_id="SEM-ENV-1",
        semantic_environment_hash="5" * 64,
        topology_environment_id="TOPOLOGY-1",
        topology_revision=7,
        topology_snapshot_hash="6" * 64,
        initiating_host_kind="REVIT",
        members=members,
    )


def test_v2_binding_requires_exact_revit_and_autocad_members_and_canonical_order() -> None:
    """V2 binding 必须恰好覆盖 REQUIRED AutoCAD+Revit，输入顺序不能改变 binding identity。"""

    module = _front_door_module()
    revit = _v2_member(module, host_kind="REVIT")
    autocad = _v2_member(module, host_kind="AUTOCAD")

    first = _create_v2_binding(members=(revit, autocad))
    second = _create_v2_binding(members=(autocad, revit))

    assert first.binding_hash == second.binding_hash
    assert tuple(member.host_kind for member in first.members) == ("AUTOCAD", "REVIT")
    assert first.members == second.members


@pytest.mark.parametrize("members_kind", ["missing", "duplicate", "extra"])
def test_v2_binding_rejects_missing_duplicate_or_extra_members(members_kind: str) -> None:
    """任一缺失、重复或额外 REQUIRED member 都必须在 binding owner 边界 fail closed。"""

    module = _front_door_module()
    revit = _v2_member(module, host_kind="REVIT")
    autocad = _v2_member(module, host_kind="AUTOCAD")
    if members_kind == "missing":
        members = (revit,)
    elif members_kind == "duplicate":
        members = (revit, revit)
    else:
        members = (
            revit,
            autocad,
            module.SessionBindingMemberV2(
                host_kind="IFC",
                role="BOUND_REQUIRED",
                configured_reference_id="unexpected-ifc",
                configured_reference_hash="7" * 64,
                transport_locator="unexpected-ifc",
                host_instance_id="ifc-runtime",
                document_id="/tmp/unexpected.ifc",
                native_target_id="ifc-wall",
                host_binding_fingerprint="8" * 64,
            ),
        )

    with pytest.raises(ValueError, match="FRONT_DOOR_BINDING_V2_INVALID"):
        _create_v2_binding(members=members)


def test_v2_binding_rejects_wrong_roles_or_initiating_host() -> None:
    """Revit 必须是 INITIATOR，AutoCAD 必须是 BOUND_REQUIRED，且发起 Host 固定为 Revit。"""

    module = _front_door_module()
    bad_revit = module.SessionBindingMemberV2(
        host_kind="REVIT",
        role="BOUND_REQUIRED",
        configured_reference_id="primary-revit",
        configured_reference_hash="1" * 64,
        transport_locator="configured-revit-pipe",
        host_instance_id="revit-runtime-7",
        document_id=r"C:\path\to\fixture.rvt",
        native_target_id="reviewed-wall-unique-id",
        host_binding_fingerprint="2" * 64,
    )
    autocad = _v2_member(module, host_kind="AUTOCAD")

    with pytest.raises(ValueError, match="FRONT_DOOR_BINDING_V2_INVALID"):
        _create_v2_binding(members=(bad_revit, autocad))

    binding_type = getattr(module, "SessionBindingV2")
    with pytest.raises(ValueError, match="FRONT_DOOR_BINDING_V2_INVALID"):
        binding_type.create(
            session_ref="session-cross-host-1",
            project_id="project-id",
            semantic_target_id="WALL-001",
            semantic_environment_id="SEM-ENV-1",
            semantic_environment_hash="5" * 64,
            topology_environment_id="TOPOLOGY-1",
            topology_revision=7,
            topology_snapshot_hash="6" * 64,
            initiating_host_kind="AUTOCAD",
            members=(_v2_member(module, host_kind="REVIT"), autocad),
        )
