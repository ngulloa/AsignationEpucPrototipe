"""Productive application API composed from local and shared services."""

from __future__ import annotations

from backend.approval import ApprovalService
from backend.authentication import LocalAuthenticationService
from backend.contracts import AcademicFormData, AcademicRecord, SubmissionResult
from backend.error_notifications import ErrorNotificationService
from backend.git_sync import GitSyncService
from backend.personal_academics import PersonalAcademicService
from backend.system_contracts import (
    AuthenticatedSession,
    ErrorNotification,
    SharedTable,
    TablePublication,
    UpdateResult,
    UserPermissions,
)
from backend.table_publication import TablePublicationService
from persistence.approval_repository import ApprovalEntry
from persistence.error_notification_repository import StoredErrorNotification
from persistence.paths import ProjectPaths
from persistence.shared_table_repository import (
    JsonSharedTableRepository,
    SharedTableContent,
)


class ApplicationService:
    """Enforce backend permissions independently of every frontend control."""

    def __init__(
        self,
        *,
        authentication: LocalAuthenticationService,
        approvals: ApprovalService,
        personal_academics: PersonalAcademicService,
        shared_tables: JsonSharedTableRepository,
        publisher: TablePublicationService,
        notifications: ErrorNotificationService,
        git: GitSyncService,
        paths: ProjectPaths,
    ) -> None:
        self.authentication = authentication
        self.approvals = approvals
        self.personal_academics = personal_academics
        self.shared_tables = shared_tables
        self.publisher = publisher
        self.notifications = notifications
        self.git = git
        self.paths = paths

    def register_user(self, username: str, password: str) -> AuthenticatedSession:
        session = self.authentication.register_user(username, password)
        if not self.approvals.get_permissions().owner:
            self.approvals.request_approval()
        return session

    def authenticate(self, username: str, password: str) -> AuthenticatedSession:
        return self.authentication.authenticate(username, password)

    def logout(self) -> None:
        self.authentication.logout()

    def request_approval(self) -> ApprovalEntry:
        return self.approvals.request_approval()

    def grant_approval(self, username: str) -> ApprovalEntry:
        return self.approvals.grant_approval(username)

    def grant_request(self, request_id: str) -> ApprovalEntry:
        return self.approvals.grant_request(request_id)

    def list_approval_requests(self) -> list[ApprovalEntry]:
        return self.approvals.list_requests()

    def get_permissions(self) -> UserPermissions:
        return self.approvals.get_permissions()

    def list_academics(self) -> list[AcademicRecord]:
        return self.personal_academics.list_academics()

    def save_academic(self, form_data: AcademicFormData) -> SubmissionResult:
        return self.personal_academics.save_academic(form_data)

    def update_academic(
        self, academic_id: str, form_data: AcademicFormData
    ) -> SubmissionResult:
        return self.personal_academics.update_academic(academic_id, form_data)

    def list_shared_tables(self) -> list[SharedTable]:
        self.approvals.require_approved()
        return self.shared_tables.list_shared_tables()

    def list_shared_table_contents(self) -> list[SharedTableContent]:
        self.approvals.require_approved()
        return self.shared_tables.list_with_contents()

    def publish_table(self, publication: TablePublication) -> SharedTable:
        return self.publisher.publish_table(publication)

    def update_shared_table(
        self,
        table_number: int,
        records: list[AcademicRecord],
        *,
        update_name: str,
    ) -> SharedTable:
        return self.publisher.update_shared_table(
            table_number,
            records,
            update_name=update_name,
        )

    def notify_error(self, notification: ErrorNotification) -> StoredErrorNotification:
        return self.notifications.notify_error(notification)

    def list_received_errors(self) -> list[StoredErrorNotification]:
        return self.notifications.list_received()

    def flush_pending_errors(self) -> int:
        return self.notifications.flush_pending()

    def run_update(self) -> UpdateResult:
        self.approvals.require_approved()
        return self.git.run_update()
