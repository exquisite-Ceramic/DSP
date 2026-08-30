from __future__ import annotations

import pytest

from design_provider_binding import (
    NativeConstraint,
    NativeConstraintOperator,
    NativeTargetBindingEvidence,
    ProviderBindingAdapterRegistry,
    ProviderBindingError,
    native_constraints_satisfied,
    validate_native_constraints,
)


def _target(digest_fn, semantic_id: str, native_kind: str):
    return NativeTargetBindingEvidence(
        semantic_id,
        "REVIT",
        "DOC-1",
        f"NATIVE-{semantic_id}",
        native_kind,
        digest_fn(f"host-binding-{semantic_id}-{native_kind}"),
    )


def test_native_constraint_eq_and_in_compare_opaque_native_kind(digest_fn):
    wall = _target(digest_fn, "WALL-001", "Wall")
    assert native_constraints_satisfied(
        (NativeConstraint("native_kind", NativeConstraintOperator.EQ, ("Wall",)),),
        (wall,),
    )
    assert native_constraints_satisfied(
        (NativeConstraint("native_kind", NativeConstraintOperator.IN, ("Door", "Wall")),),
        (wall,),
    )
    assert not native_constraints_satisfied(
        (NativeConstraint("native_kind", NativeConstraintOperator.EQ, ("Door",)),),
        (wall,),
    )


def test_every_native_target_must_satisfy_every_constraint(digest_fn):
    wall = _target(digest_fn, "WALL-001", "Wall")
    annotation = _target(digest_fn, "ANNOTATION-002", "Annotation")
    broad = NativeConstraint("native_kind", "IN", ("Wall", "Annotation"))
    wall_only = NativeConstraint("native_kind", "EQ", ("Wall",))
    assert native_constraints_satisfied((broad,), (wall, annotation))
    assert not native_constraints_satisfied((wall_only,), (wall, annotation))


def test_empty_constraint_tuple_passes(digest_fn):
    assert native_constraints_satisfied((), (_target(digest_fn, "WALL-001", "Wall"),))


def test_direct_native_constraint_validation_fails_closed(digest_fn):
    with pytest.raises(ProviderBindingError) as exc:
        validate_native_constraints(
            (NativeConstraint("native_kind", "EQ", ("Door",)),),
            (_target(digest_fn, "WALL-001", "Wall"),),
        )
    assert exc.value.code == "PROVIDER_NATIVE_CONSTRAINT_UNSATISFIED"


def test_registry_same_adapter_registration_is_idempotent(fake_adapter):
    registry = ProviderBindingAdapterRegistry()
    registry.register("provider.revit", fake_adapter)
    registry.register("provider.revit", fake_adapter)
    assert registry.require("provider.revit", "1.0.0") is fake_adapter


def test_registry_conflicting_adapter_fails_closed(fake_adapter):
    registry = ProviderBindingAdapterRegistry()
    registry.register("provider.revit", fake_adapter)
    from conftest import FakeBindingAdapter

    with pytest.raises(ProviderBindingError) as exc:
        registry.register("provider.revit", FakeBindingAdapter())
    assert exc.value.code == "PROVIDER_ADAPTER_CONFLICT"


def test_registry_missing_or_version_mismatch_is_unavailable(fake_adapter):
    registry = ProviderBindingAdapterRegistry()
    registry.register("provider.revit", fake_adapter)
    with pytest.raises(ProviderBindingError) as exc:
        registry.require("provider.missing", "1.0.0")
    assert exc.value.code == "PROVIDER_ADAPTER_UNAVAILABLE"
    with pytest.raises(ProviderBindingError) as exc:
        registry.require("provider.revit", "2.0.0")
    assert exc.value.code == "PROVIDER_ADAPTER_UNAVAILABLE"


def test_registry_rejects_blank_provider_server(fake_adapter):
    registry = ProviderBindingAdapterRegistry()
    with pytest.raises(ProviderBindingError) as exc:
        registry.register("   ", fake_adapter)
    assert exc.value.code == "PROVIDER_BINDING_INPUT_INVALID"


def test_registry_lookup_is_independent_of_registration_order():
    from conftest import FakeBindingAdapter

    first_a = FakeBindingAdapter(adapter_version="1.0.0")
    first_b = FakeBindingAdapter(adapter_version="2.0.0")
    forward = ProviderBindingAdapterRegistry()
    forward.register("provider.a", first_a)
    forward.register("provider.b", first_b)

    second_a = FakeBindingAdapter(adapter_version="1.0.0")
    second_b = FakeBindingAdapter(adapter_version="2.0.0")
    reverse = ProviderBindingAdapterRegistry()
    reverse.register("provider.b", second_b)
    reverse.register("provider.a", second_a)

    assert forward.require("provider.a", "1.0.0") is first_a
    assert forward.require("provider.b", "2.0.0") is first_b
    assert reverse.require("provider.a", "1.0.0") is second_a
    assert reverse.require("provider.b", "2.0.0") is second_b
