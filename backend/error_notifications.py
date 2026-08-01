"""Structured error notifications with bounded, defensively screened details."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from backend.approval import ApprovalService, AuthorizationError
from backend.session import SessionMemory
from backend.system_contracts import ErrorNotification
from persistence.error_notification_repository import (
    ALLOWED_CATEGORIES,
    ALLOWED_ERROR_CODES,
    ALLOWED_SOURCE_SCREENS,
    ERROR_CATEGORY_BY_CODE,
    JsonErrorNotificationRepository,
    StoredErrorNotification,
)


class ErrorNotificationService:
    """Accept and persist only an allowlisted error classification."""

    def __init__(
        self,
        sessions: SessionMemory,
        approvals: ApprovalService,
        repository: JsonErrorNotificationRepository,
    ) -> None:
        self._sessions = sessions
        self._approvals = approvals
        self._repository = repository

    def notify_error(self, notification: ErrorNotification) -> StoredErrorNotification:
        session = self._sessions.current_session
        if session is None:
            raise AuthorizationError("Debe iniciar sesión para notificar un error.")
        if notification.source_screen not in ALLOWED_SOURCE_SCREENS:
            raise ValueError("Pantalla de origen no autorizada.")
        if notification.category not in ALLOWED_CATEGORIES:
            raise ValueError("Categoría de notificación no autorizada.")
        if notification.error_code not in ALLOWED_ERROR_CODES:
            raise ValueError("Código de error no autorizado.")
        if ERROR_CATEGORY_BY_CODE[notification.error_code] != notification.category:
            raise ValueError("La categoría no corresponde al código de error.")

        stored = StoredErrorNotification(
            notification_id=str(uuid4()),
            created_at=datetime.now(UTC).isoformat(),
            source_screen=notification.source_screen,
            category=notification.category,
            error_code=notification.error_code,
            status="new",
            description=notification.description,
        )
        self._repository.enqueue_and_record(session.username, stored)
        return stored

    def list_received(self) -> list[StoredErrorNotification]:
        self._approvals.require_owner()
        return self._repository.list_all()

    def flush_pending(self) -> int:
        session = self._sessions.current_session
        if session is None:
            raise AuthorizationError(
                "Debe iniciar sesión para incorporar notificaciones pendientes."
            )
        return self._repository.flush_pending(session.username)

    def mark_seen(self, notification_id: str) -> None:
        owner = self._approvals.require_owner()
        self._repository.mark_seen(owner.username, notification_id)
