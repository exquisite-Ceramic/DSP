from __future__ import annotations

from dataclasses import replace

import pytest
from design_provider_binding import (
    ProviderBindingError,
    resolve_provider_bindings_v2,
    validate_provider_binding_set_v2,
)

from tests.provider_binding._support import build_phase_i_binding_inputs, snapshot

_snapshot = snapshot


def test_v2_binding_preserves_exact_materialization_slice_and_host_lineage() -> None:
    _, slices, snapshots = build_phase_i_binding_inputs()

    for host_type in ("autocad", "revit"):
        execution_slice = slices[host_type]
        provider_snapshot = snapshots[host_type]
        binding_set = resolve_provider_bindings_v2(execution_slice, provider_snapshot)

        assert provider_snapshot.materialization_id == execution_slice.materialization_id
        assert provider_snapshot.materialization_plan_hash == execution_slice.materialization_plan_hash
        assert provider_snapshot.execution_slice_hash == execution_slice.execution_slice_hash
        assert provider_snapshot.host_runtime_ref == execution_slice.host_runtime_ref
        assert binding_set.materialization_id == execution_slice.materialization_id
        assert binding_set.materialization_plan_hash == execution_slice.materialization_plan_hash
        assert binding_set.execution_slice_hash == execution_slice.execution_slice_hash
        assert len(binding_set.bindings) == 1
        binding = binding_set.bindings[0]
        assert binding.materialization_id == execution_slice.materialization_id
        assert binding.materialization_plan_hash == execution_slice.materialization_plan_hash
        assert binding.execution_slice_hash == execution_slice.execution_slice_hash
        assert binding.host_runtime_ref == execution_slice.host_runtime_ref
        assert binding.native_targets == provider_snapshot.native_target_bindings
        validate_provider_binding_set_v2(binding_set, execution_slice)


def test_native_identity_change_changes_snapshot_binding_and_set_hashes() -> None:
    _, slices, _ = build_phase_i_binding_inputs()
    execution_slice = slices["revit"]
    first_snapshot = snapshot(
        execution_slice,
        native_id="REVIT-UNIQUE-ID-001",
        native_kind="Wall",
    )
    second_snapshot = snapshot(
        execution_slice,
        native_id="REVIT-UNIQUE-ID-002",
        native_kind="Wall",
    )

    first = resolve_provider_bindings_v2(execution_slice, first_snapshot)
    second = resolve_provider_bindings_v2(execution_slice, second_snapshot)

    assert first_snapshot.snapshot_hash != second_snapshot.snapshot_hash
    assert first.bindings[0].binding_hash != second.bindings[0].binding_hash
    assert first.binding_set_hash != second.binding_set_hash


def test_changed_revit_unique_id_under_old_host_binding_fingerprint_fails_closed() -> None:
    _, slices, snapshots = build_phase_i_binding_inputs()
    execution_slice = slices["revit"]
    provider_snapshot = snapshots["revit"]
    original = provider_snapshot.native_target_bindings[0]
    tampered_target = replace(original, native_id="REVIT-UNIQUE-ID-CHANGED")
    tampered = replace(provider_snapshot, native_target_bindings=(tampered_target,))

    with pytest.raises(ProviderBindingError) as exc:
        resolve_provider_bindings_v2(execution_slice, tampered)
    assert exc.value.code == "IDENTITY_BINDING_CONFLICT"


def test_snapshot_materialization_or_host_substitution_fails_closed() -> None:
    _, slices, snapshots = build_phase_i_binding_inputs()
    execution_slice = slices["autocad"]
    provider_snapshot = snapshots["autocad"]

    with pytest.raises(ProviderBindingError) as exc:
        resolve_provider_bindings_v2(
            execution_slice,
            replace(provider_snapshot, materialization_id="MAT-SUBSTITUTED"),
        )
    assert exc.value.code == "MATERIALIZATION_BINDING_MISMATCH"
