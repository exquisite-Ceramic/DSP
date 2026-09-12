from __future__ import annotations

from dataclasses import replace

import pytest
from design_provider_binding import (
    ProviderBindingError,
    resolve_provider_bindings_v2,
    validate_cross_materialization_identity,
)

from tests.provider_binding._support import build_phase_i_binding_inputs


def _binding_sets():
    materialization_plan, slices, snapshots = build_phase_i_binding_inputs()
    sets = tuple(
        resolve_provider_bindings_v2(slices[host_type], snapshots[host_type])
        for host_type in ("autocad", "revit")
    )
    return materialization_plan, slices, snapshots, sets


def _assert_code(code: str, operation) -> None:
    with pytest.raises(ProviderBindingError) as exc:
        operation()
    assert exc.value.code == code


def test_exact_cross_materialization_identity_passes_for_required_set() -> None:
    materialization_plan, _, _, sets = _binding_sets()
    validate_cross_materialization_identity(materialization_plan, sets)


def test_missing_or_extra_materialization_fails_closed() -> None:
    materialization_plan, _, _, sets = _binding_sets()

    _assert_code(
        "MATERIALIZATION_BINDING_MISMATCH",
        lambda: validate_cross_materialization_identity(
            materialization_plan,
            sets[:1],
        ),
    )
    extra = replace(
        sets[0],
        materialization_id="MAT-EXTRA",
    )
    _assert_code(
        "MATERIALIZATION_BINDING_MISMATCH",
        lambda: validate_cross_materialization_identity(
            materialization_plan,
            (*sets, extra),
        ),
    )


def test_missing_native_target_fails_identity_binding_unresolved() -> None:
    _, slices, snapshots = build_phase_i_binding_inputs()
    execution_slice = slices["autocad"]
    provider_snapshot = replace(snapshots["autocad"], native_target_bindings=())

    _assert_code(
        "IDENTITY_BINDING_UNRESOLVED",
        lambda: resolve_provider_bindings_v2(execution_slice, provider_snapshot),
    )


def test_duplicate_or_conflicting_native_target_fails_identity_binding_conflict() -> None:
    _, slices, snapshots = build_phase_i_binding_inputs()
    execution_slice = slices["revit"]
    provider_snapshot = snapshots["revit"]
    duplicated = replace(
        provider_snapshot,
        native_target_bindings=(
            provider_snapshot.native_target_bindings[0],
            provider_snapshot.native_target_bindings[0],
        ),
    )

    _assert_code(
        "IDENTITY_BINDING_CONFLICT",
        lambda: resolve_provider_bindings_v2(execution_slice, duplicated),
    )


def test_semantic_host_or_document_mismatch_fails_materialization_binding_mismatch() -> None:
    _, slices, snapshots = build_phase_i_binding_inputs()
    execution_slice = slices["revit"]
    provider_snapshot = snapshots["revit"]
    target = provider_snapshot.native_target_bindings[0]

    for changed in (
        replace(target, semantic_id="WALL-OTHER"),
        replace(target, host_type="autocad"),
        replace(target, document_ref="DOC-OTHER"),
    ):
        _assert_code(
            "MATERIALIZATION_BINDING_MISMATCH",
            lambda changed=changed: resolve_provider_bindings_v2(
                execution_slice,
                replace(provider_snapshot, native_target_bindings=(changed,)),
            ),
        )


def test_cross_materialization_plan_hash_substitution_fails_closed() -> None:
    materialization_plan, _, _, sets = _binding_sets()
    substituted = replace(sets[1], materialization_plan_hash="f" * 64)

    _assert_code(
        "MATERIALIZATION_BINDING_MISMATCH",
        lambda: validate_cross_materialization_identity(
            materialization_plan,
            (sets[0], substituted),
        ),
    )
