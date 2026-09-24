from __future__ import annotations

from dataclasses import replace

import pytest
from design_provider_binding import (
    InMemoryProviderBindingSetV2Store,
    ProviderBindingError,
    resolve_provider_bindings_v2,
)

from tests.provider_binding._support import build_phase_i_binding_inputs


def _real_binding_set():
    """使用现有 Phase I builder 生成真实 ProviderBindingSetV2，避免测试自造 owner truth。"""
    _materialization_plan, slices, snapshots = build_phase_i_binding_inputs()
    return resolve_provider_bindings_v2(
        slices["autocad"],
        snapshots["autocad"],
    )


def test_get_by_hash_resolves_exact_full_hash() -> None:
    """完整 64 位 owner hash 必须解析回同一个不可变 binding set。"""
    binding_set = _real_binding_set()
    store = InMemoryProviderBindingSetV2Store()
    store.put(binding_set)

    resolved = store.get_by_hash(binding_set.binding_set_hash)

    assert resolved == binding_set
    assert resolved.binding_set_hash == binding_set.binding_set_hash


def test_get_by_hash_rejects_same_short_id_with_different_full_hash() -> None:
    """相同前 12 位不能替代完整 hash 身份；碰撞必须 fail closed。"""
    original = _real_binding_set()
    stored_hash = "a" * 12 + "2" * 52
    requested_hash = "a" * 12 + "1" * 52
    collision = replace(
        original,
        binding_set_id=f"PBSV2-{stored_hash[:12]}",
        binding_set_hash=stored_hash,
    )
    store = InMemoryProviderBindingSetV2Store()
    store.put(collision)

    with pytest.raises(ProviderBindingError) as exc_info:
        store.get_by_hash(requested_hash)

    assert exc_info.value.code == "PROVIDER_BINDING_INTEGRITY_INVALID"


@pytest.mark.parametrize("value", ["", "A" * 64, "a" * 63, "g" * 64])
def test_get_by_hash_rejects_noncanonical_digest(value: str) -> None:
    """lookup 入口必须拒绝非 canonical lowercase SHA-256，而不是尝试模糊解析。"""
    with pytest.raises(ValueError):
        InMemoryProviderBindingSetV2Store().get_by_hash(value)


def test_get_by_hash_reports_missing_exact_artifact() -> None:
    """合法 hash 没有 owner artifact 时返回稳定的 not-found 机器码。"""
    with pytest.raises(ProviderBindingError) as exc_info:
        InMemoryProviderBindingSetV2Store().get_by_hash("b" * 64)

    assert exc_info.value.code == "PROVIDER_BINDING_SET_REFERENCE_NOT_FOUND"
