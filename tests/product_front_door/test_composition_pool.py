from __future__ import annotations

from dataclasses import replace

import pytest

from design_changeset import canonical_hash
from design_product_front_door.composition_pool import ExactSessionCompositionPool
from design_product_front_door.contracts import (
    ConfiguredRevitCandidate,
    SessionBinding,
    configured_revit_candidate_hash_body,
    session_binding_hash_body,
)


def _candidate() -> ConfiguredRevitCandidate:
    body = configured_revit_candidate_hash_body(
        candidate_key="primary-revit",
        project_id="project-1",
        transport_locator="revit-pipe",
        document_id=r"C:\\DSP\\fixture.rvt",
        semantic_target_id="WALL-001",
        native_target_unique_id="wall-uid-1",
    )
    return ConfiguredRevitCandidate(
        **body,
        candidate_hash=canonical_hash(body),
    )


def _binding(
    candidate: ConfiguredRevitCandidate,
    *,
    session_ref: str = "session-1",
    host_instance_id: str = "revit-runtime-1",
) -> SessionBinding:
    body = session_binding_hash_body(
        session_ref=session_ref,
        project_id=candidate.project_id,
        host_kind="REVIT",
        candidate_key=candidate.candidate_key,
        candidate_hash=candidate.candidate_hash,
        transport_locator=candidate.transport_locator,
        host_instance_id=host_instance_id,
        document_id=candidate.document_id,
    )
    return SessionBinding(
        **body,
        document_title="fixture.rvt",
        binding_hash=canonical_hash(body),
    )


class _Composition:
    def __init__(self, marker: str) -> None:
        self.marker = marker
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _Factory:
    def __init__(self) -> None:
        self.calls: list[tuple[SessionBinding, ConfiguredRevitCandidate]] = []

    def __call__(
        self,
        *,
        binding: SessionBinding,
        candidate: ConfiguredRevitCandidate,
    ) -> _Composition:
        self.calls.append((binding, candidate))
        return _Composition(marker=binding.session_ref)


def test_same_exact_session_binding_returns_same_live_composition() -> None:
    candidate = _candidate()
    binding = _binding(candidate)
    factory = _Factory()
    pool = ExactSessionCompositionPool(factory=factory)

    first = pool.get_or_create(binding=binding, candidate=candidate)
    second = pool.get_or_create(binding=binding, candidate=candidate)

    assert second is first
    assert factory.calls == [(binding, candidate)]


def test_same_session_ref_with_different_binding_body_fails_closed() -> None:
    candidate = _candidate()
    binding = _binding(candidate)
    changed_body = session_binding_hash_body(
        session_ref=binding.session_ref,
        project_id=binding.project_id,
        host_kind=binding.host_kind,
        candidate_key=binding.candidate_key,
        candidate_hash=binding.candidate_hash,
        transport_locator=binding.transport_locator,
        host_instance_id="revit-runtime-2",
        document_id=binding.document_id,
    )
    changed_binding = replace(
        binding,
        host_instance_id="revit-runtime-2",
        binding_hash=canonical_hash(changed_body),
    )
    factory = _Factory()
    pool = ExactSessionCompositionPool(factory=factory)

    first = pool.get_or_create(binding=binding, candidate=candidate)
    with pytest.raises(ValueError, match="FRONT_DOOR_SESSION_BINDING_CONFLICT"):
        pool.get_or_create(binding=changed_binding, candidate=candidate)

    assert factory.calls == [(binding, candidate)]
    assert first.close_calls == 0


def test_distinct_session_refs_never_reverse_reuse_existing_composition() -> None:
    candidate = _candidate()
    first_binding = _binding(candidate, session_ref="session-1")
    second_binding = _binding(candidate, session_ref="session-2")
    factory = _Factory()
    pool = ExactSessionCompositionPool(factory=factory)

    first = pool.get_or_create(binding=first_binding, candidate=candidate)
    second = pool.get_or_create(binding=second_binding, candidate=candidate)

    assert second is not first
    assert [binding.session_ref for binding, _ in factory.calls] == [
        "session-1",
        "session-2",
    ]


def test_close_releases_each_exact_session_handle_once() -> None:
    candidate = _candidate()
    first_binding = _binding(candidate, session_ref="session-1")
    second_binding = _binding(candidate, session_ref="session-2")
    factory = _Factory()
    pool = ExactSessionCompositionPool(factory=factory)
    first = pool.get_or_create(binding=first_binding, candidate=candidate)
    second = pool.get_or_create(binding=second_binding, candidate=candidate)

    pool.close()
    pool.close()

    assert first.close_calls == 1
    assert second.close_calls == 1
