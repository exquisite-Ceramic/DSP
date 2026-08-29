from __future__ import annotations

import pytest

from design_interaction import (
    InteractionCoordinator,
    InteractionError,
    InteractionStartRequest,
    InteractionState,
    InteractionType,
)


CREATED = "2026-08-29T08:00:00Z"
EXPIRES = "2026-08-29T08:05:00Z"
POINT_SCHEMA = {
    "type": "array",
    "items": {"type": "number"},
    "minItems": 3,
    "maxItems": 3,
}


def _request(**overrides) -> InteractionStartRequest:
    values = {
        "task_id": "task-26",
        "host_instance_id": "acad-01",
        "document_id": "drawing-01",
        "interaction_type": InteractionType.PICK_POINT,
        "input_constraints": {"prompt": "Pick a point"},
        "result_schema": POINT_SCHEMA,
        "idempotency_key": "task-26:pick-point:point",
        "created_at": CREATED,
        "expires_at": EXPIRES,
    }
    values.update(overrides)
    return InteractionStartRequest(**values)


def test_start_creates_pending_session_and_async_ref() -> None:
    coordinator = InteractionCoordinator()

    session = coordinator.start(_request())
    ref = coordinator.async_ref(session.interaction_id)

    assert session.state is InteractionState.PENDING
    assert session.result is None
    assert session.interaction_type is InteractionType.PICK_POINT
    assert ref.type == "INTERACTION_SESSION"
    assert ref.id == session.interaction_id


def test_same_idempotency_key_and_same_request_returns_same_session() -> None:
    coordinator = InteractionCoordinator()
    request = _request()

    first = coordinator.start(request)
    second = coordinator.start(request)

    assert second == first
    assert second.interaction_id == first.interaction_id


def test_same_idempotency_key_with_different_logical_request_fails_closed() -> None:
    coordinator = InteractionCoordinator()
    coordinator.start(_request())

    with pytest.raises(InteractionError) as exc:
        coordinator.start(_request(document_id="drawing-02"))

    assert exc.value.code == "IDEMPOTENCY_CONFLICT"


def test_second_distinct_pending_interaction_on_same_host_document_is_busy() -> None:
    coordinator = InteractionCoordinator()
    coordinator.start(_request())

    with pytest.raises(InteractionError) as exc:
        coordinator.start(_request(idempotency_key="task-26:pick-point:other"))

    assert exc.value.code == "INTERACTION_BUSY"


def test_complete_from_provider_validates_result_schema_and_terminal_state() -> None:
    coordinator = InteractionCoordinator()
    pending = coordinator.start(_request())

    completed = coordinator.complete_from_provider(
        pending.interaction_id,
        [10.0, 20.0, 0.0],
        now="2026-08-29T08:01:00Z",
    )

    assert completed.state is InteractionState.COMPLETED
    assert completed.result == [10.0, 20.0, 0.0]

    with pytest.raises(InteractionError) as exc:
        coordinator.complete_from_provider(
            pending.interaction_id,
            [30.0, 40.0, 0.0],
            now="2026-08-29T08:02:00Z",
        )
    assert exc.value.code == "INTERACTION_TERMINAL"


def test_invalid_provider_result_fails_closed() -> None:
    coordinator = InteractionCoordinator()
    pending = coordinator.start(_request())

    with pytest.raises(InteractionError) as exc:
        coordinator.complete_from_provider(
            pending.interaction_id,
            [10.0, 20.0],
            now="2026-08-29T08:01:00Z",
        )

    assert exc.value.code == "INTERACTION_RESULT_INVALID"
    assert coordinator.get(
        pending.interaction_id,
        now="2026-08-29T08:01:00Z",
    ).state is InteractionState.PENDING


def test_cancel_transitions_pending_to_cancelled_and_releases_busy_slot() -> None:
    coordinator = InteractionCoordinator()
    pending = coordinator.start(_request())

    cancelled = coordinator.cancel(
        pending.interaction_id,
        now="2026-08-29T08:01:00Z",
    )

    assert cancelled.state is InteractionState.CANCELLED
    assert cancelled.result is None

    replacement = coordinator.start(
        _request(idempotency_key="task-26:pick-point:replacement")
    )
    assert replacement.interaction_id != pending.interaction_id


def test_expiry_is_deterministic_and_terminal() -> None:
    coordinator = InteractionCoordinator()
    pending = coordinator.start(_request())

    expired = coordinator.get(
        pending.interaction_id,
        now="2026-08-29T08:05:00Z",
    )

    assert expired.state is InteractionState.EXPIRED
    assert expired.result is None

    with pytest.raises(InteractionError) as exc:
        coordinator.cancel(
            pending.interaction_id,
            now="2026-08-29T08:06:00Z",
        )
    assert exc.value.code == "INTERACTION_TERMINAL"


def test_unknown_session_fails_with_stable_code() -> None:
    coordinator = InteractionCoordinator()

    with pytest.raises(InteractionError) as exc:
        coordinator.get("missing", now="2026-08-29T08:01:00Z")

    assert exc.value.code == "INTERACTION_NOT_FOUND"


def test_start_request_requires_absolute_utc_and_positive_lifetime() -> None:
    with pytest.raises(ValueError, match="absolute UTC"):
        _request(created_at="2026-08-29T08:00:00")

    with pytest.raises(ValueError, match="expires_at"):
        _request(expires_at=CREATED)


def test_completed_session_is_defensively_copied() -> None:
    coordinator = InteractionCoordinator()
    pending = coordinator.start(_request())
    result = [1.0, 2.0, 3.0]

    completed = coordinator.complete_from_provider(
        pending.interaction_id,
        result,
        now="2026-08-29T08:01:00Z",
    )
    result[0] = 999.0

    assert completed.result == [1.0, 2.0, 3.0]
