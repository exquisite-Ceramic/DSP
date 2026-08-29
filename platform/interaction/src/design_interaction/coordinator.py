"""Authoritative in-memory InteractionSession coordinator for Step26 v1."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import hashlib
import json
import uuid

from host_contracts.envelope import AsyncOperationRef, parse_utc
from jsonschema import SchemaError, ValidationError, validate

from design_interaction.contracts import (
    InteractionError,
    InteractionSession,
    InteractionStartRequest,
    InteractionState,
)


class InteractionCoordinator:
    """Own long-lived interaction lifecycle, idempotency, and prompt exclusivity."""

    def __init__(self) -> None:
        self._sessions: dict[str, InteractionSession] = {}
        self._idempotency: dict[str, tuple[str, str]] = {}
        self._pending_by_scope: dict[tuple[str, str], str] = {}

    @staticmethod
    def _fingerprint(request: InteractionStartRequest) -> str:
        logical = {
            "task_id": request.task_id,
            "host_instance_id": request.host_instance_id,
            "document_id": request.document_id,
            "interaction_type": request.interaction_type.value,
            "input_constraints": dict(request.input_constraints),
            "result_schema": dict(request.result_schema),
            "created_at": request.created_at,
            "expires_at": request.expires_at,
        }
        try:
            encoded = json.dumps(
                logical,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValueError("interaction request must be JSON-serializable") from exc
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _scope(session_or_request: InteractionSession | InteractionStartRequest) -> tuple[str, str]:
        return (session_or_request.host_instance_id, session_or_request.document_id)

    def _require(self, interaction_id: str) -> InteractionSession:
        session = self._sessions.get(interaction_id)
        if session is None:
            raise InteractionError(
                "INTERACTION_NOT_FOUND",
                f"unknown interaction session: {interaction_id}",
            )
        return session

    def _store(self, session: InteractionSession) -> InteractionSession:
        self._sessions[session.interaction_id] = session
        scope = self._scope(session)
        if session.state is InteractionState.PENDING:
            self._pending_by_scope[scope] = session.interaction_id
        elif self._pending_by_scope.get(scope) == session.interaction_id:
            del self._pending_by_scope[scope]
        return session

    def _expire_if_due(self, session: InteractionSession, *, now: str) -> InteractionSession:
        try:
            now_dt = parse_utc(now)
        except ValueError as exc:
            raise ValueError(f"now must be absolute UTC: {exc}") from exc

        if (
            session.state is InteractionState.PENDING
            and now_dt >= parse_utc(session.expires_at)
        ):
            session = replace(session, state=InteractionState.EXPIRED)
            self._store(session)
        return session

    def start(self, request: InteractionStartRequest) -> InteractionSession:
        if not isinstance(request, InteractionStartRequest):
            raise TypeError("request must be an InteractionStartRequest")

        fingerprint = self._fingerprint(request)
        remembered = self._idempotency.get(request.idempotency_key)
        if remembered is not None:
            remembered_fingerprint, interaction_id = remembered
            if remembered_fingerprint != fingerprint:
                raise InteractionError(
                    "IDEMPOTENCY_CONFLICT",
                    "same idempotency_key was used for a different interaction request",
                )
            return self._require(interaction_id)

        scope = self._scope(request)
        existing_id = self._pending_by_scope.get(scope)
        if existing_id is not None:
            existing = self._expire_if_due(
                self._require(existing_id),
                now=request.created_at,
            )
            if existing.state is InteractionState.PENDING:
                raise InteractionError(
                    "INTERACTION_BUSY",
                    "another Host Canvas interaction is already pending for this document",
                )

        interaction_id = str(uuid.uuid4())
        session = InteractionSession(
            interaction_id=interaction_id,
            task_id=request.task_id,
            host_instance_id=request.host_instance_id,
            document_id=request.document_id,
            interaction_type=request.interaction_type,
            input_constraints=request.input_constraints,
            result_schema=request.result_schema,
            state=InteractionState.PENDING,
            created_at=request.created_at,
            expires_at=request.expires_at,
        )
        self._idempotency[request.idempotency_key] = (fingerprint, interaction_id)
        return self._store(session)

    def get(self, interaction_id: str, *, now: str) -> InteractionSession:
        return self._expire_if_due(self._require(interaction_id), now=now)

    def cancel(self, interaction_id: str, *, now: str) -> InteractionSession:
        session = self.get(interaction_id, now=now)
        if session.state is not InteractionState.PENDING:
            raise InteractionError(
                "INTERACTION_TERMINAL",
                f"interaction is already terminal: {session.state.value}",
            )
        return self._store(replace(session, state=InteractionState.CANCELLED))

    def complete_from_provider(
        self,
        interaction_id: str,
        result: object,
        *,
        now: str,
    ) -> InteractionSession:
        session = self.get(interaction_id, now=now)
        if session.state is not InteractionState.PENDING:
            raise InteractionError(
                "INTERACTION_TERMINAL",
                f"interaction is already terminal: {session.state.value}",
            )
        try:
            validate(instance=result, schema=dict(session.result_schema))
        except SchemaError as exc:
            raise ValueError(f"result_schema is invalid: {exc.message}") from exc
        except ValidationError as exc:
            raise InteractionError(
                "INTERACTION_RESULT_INVALID",
                f"interaction result does not match result_schema: {exc.message}",
            ) from exc

        return self._store(
            replace(
                session,
                state=InteractionState.COMPLETED,
                result=deepcopy(result),
            )
        )

    def async_ref(self, interaction_id: str) -> AsyncOperationRef:
        self._require(interaction_id)
        return AsyncOperationRef(type="INTERACTION_SESSION", id=interaction_id)


__all__ = ["InteractionCoordinator"]
