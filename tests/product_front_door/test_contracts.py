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
    """document_title 仅为展示元数据；相同 authority body 可在不同 title 下保持同一 binding_hash。"""

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
