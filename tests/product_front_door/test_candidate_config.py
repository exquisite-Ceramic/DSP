"""Task 3：configured Revit candidate catalog 的规范化与 fail-closed 契约测试。"""

from __future__ import annotations

import importlib

import pytest
from design_changeset import canonical_hash


def _front_door_module():
    """延迟导入 source-only package，避免尚未实现时把 RED 变成 collection error。"""

    try:
        return importlib.import_module("design_product_front_door")
    except ModuleNotFoundError as exc:
        pytest.fail(f"design_product_front_door 尚未实现: {exc}")


def _catalog_type():
    """取得本 Task 的最小配置 source 实现。"""

    catalog_type = getattr(_front_door_module(), "ConfiguredRevitCandidateCatalog", None)
    assert catalog_type is not None, "ConfiguredRevitCandidateCatalog 尚未实现"
    return catalog_type


def _candidate(**overrides: object) -> dict[str, object]:
    """构造 reference config 中一个完整 candidate mapping。"""

    candidate: dict[str, object] = {
        "candidate_key": "primary-revit",
        "project_id": "project-id",
        "transport_locator": "configured-revit-pipe",
        "document_id": r"C:\path\to\fixture.rvt",
        "semantic_target_id": "WALL-001",
        "native_target_unique_id": "reviewed-wall-unique-id",
    }
    candidate.update(overrides)
    return candidate


def _config(*candidates: dict[str, object], version: str = "DSP_REVIT_CANDIDATES_V1") -> dict:
    """构造顶层 versioned candidate 配置。"""

    return {
        "version": version,
        "candidates": list(candidates or (_candidate(),)),
    }


def test_catalog_loads_reference_config_and_computes_candidate_hash() -> None:
    """配置文件不携带 authority hash；catalog 必须用仓库 canonical_hash 计算并冻结它。"""

    catalog = _catalog_type().from_mapping(_config())

    candidate = catalog.get("primary-revit")
    assert candidate is not None
    expected_body = _candidate()
    assert candidate.candidate_key == "primary-revit"
    assert candidate.project_id == "project-id"
    assert candidate.transport_locator == "configured-revit-pipe"
    assert candidate.document_id == r"C:\path\to\fixture.rvt"
    assert candidate.semantic_target_id == "WALL-001"
    assert candidate.native_target_unique_id == "reviewed-wall-unique-id"
    assert candidate.candidate_hash == canonical_hash(expected_body)
    assert catalog.get("missing") is None


def test_catalog_rejects_unknown_version() -> None:
    """未知配置版本不能按 v1 猜测解析。"""

    with pytest.raises(ValueError, match="FRONT_DOOR_CANDIDATE_CONFIG_VERSION_INVALID"):
        _catalog_type().from_mapping(_config(version="DSP_REVIT_CANDIDATES_V2"))


def test_catalog_rejects_duplicate_candidate_key() -> None:
    """同一个 candidate_key 只能映射一个配置 authority body。"""

    with pytest.raises(ValueError, match="FRONT_DOOR_CANDIDATE_KEY_DUPLICATE"):
        _catalog_type().from_mapping(
            _config(
                _candidate(),
                _candidate(document_id=r"C:\other\fixture.rvt"),
            )
        )


@pytest.mark.parametrize(
    "field_name",
    [
        "candidate_key",
        "project_id",
        "transport_locator",
        "document_id",
        "semantic_target_id",
        "native_target_unique_id",
    ],
)
def test_catalog_rejects_blank_authority_fields(field_name: str) -> None:
    """所有 candidate authority 字段都必须显式非空，不能从其它字段推断。"""

    with pytest.raises(ValueError, match="FRONT_DOOR_CANDIDATE_CONFIG_INVALID"):
        _catalog_type().from_mapping(_config(_candidate(**{field_name: "   "})))


@pytest.mark.parametrize(
    "document_id",
    [
        "Fixture.rvt",
        r"models\Fixture.rvt",
        "./Fixture.rvt",
    ],
)
def test_catalog_rejects_title_only_or_relative_document_id(document_id: str) -> None:
    """v1 durable binding 只接受 saved absolute document path，不接受 title/relative locator。"""

    with pytest.raises(ValueError, match="FRONT_DOOR_DOCUMENT_ID_INVALID"):
        _catalog_type().from_mapping(_config(_candidate(document_id=document_id)))


def test_catalog_accepts_posix_absolute_path_without_inferring_project() -> None:
    """absolute 校验必须按路径语义而非 CI Host OS 猜测；project_id 仍完全来自配置。"""

    catalog = _catalog_type().from_mapping(
        _config(
            _candidate(
                project_id="explicit-project",
                document_id="/srv/revit/fixture.rvt",
            )
        )
    )

    candidate = catalog.get("primary-revit")
    assert candidate is not None
    assert candidate.project_id == "explicit-project"
    assert candidate.document_id == "/srv/revit/fixture.rvt"
