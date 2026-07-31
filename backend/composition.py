"""Side-effect-free factories for the productive backend object graph."""

from __future__ import annotations

from backend.application_service import ApplicationService
from backend.approval import ApprovalService
from backend.authentication import LocalAuthenticationService
from backend.error_notifications import ErrorNotificationService
from backend.git_sync import GitSyncService
from backend.personal_academics import PersonalAcademicService
from backend.session import InMemorySession
from backend.table_publication import TablePublicationService
from persistence.approval_repository import JsonApprovalRepository
from persistence.error_notification_repository import (
    JsonErrorNotificationRepository,
)
from persistence.paths import DEFAULT_PATHS, ProjectPaths
from persistence.shared_table_repository import JsonSharedTableRepository
from persistence.user_repository import JsonUserRepository


def build_application_service(
    *,
    paths: ProjectPaths = DEFAULT_PATHS,
    git_service: GitSyncService | None = None,
) -> ApplicationService:
    """Build services without reading, writing or invoking Git until called."""
    sessions = InMemorySession()
    users = JsonUserRepository(paths)
    authentication = LocalAuthenticationService(users, sessions)
    approval_repository = JsonApprovalRepository(paths)
    approvals = ApprovalService(sessions, users, approval_repository, paths=paths)
    personal = PersonalAcademicService(sessions, paths=paths)
    shared = JsonSharedTableRepository(paths)
    git = git_service or GitSyncService(paths.root)
    publisher = TablePublicationService(
        approvals,
        shared,
        paths=paths,
        git_service=git,
    )
    notifications = ErrorNotificationService(
        sessions,
        approvals,
        JsonErrorNotificationRepository(paths),
    )
    return ApplicationService(
        authentication=authentication,
        approvals=approvals,
        personal_academics=personal,
        shared_tables=shared,
        publisher=publisher,
        notifications=notifications,
        git=git,
        paths=paths,
    )
