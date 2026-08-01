"""Productive application API composed from local and shared services."""

from __future__ import annotations

from backend.academic_catalog import AcademicCatalogs
from backend.academic_service import canonical_academic_record
from backend.approval import ApprovalService
from backend.authentication import LocalAuthenticationService
from backend.contracts import (
    AcademicFormData,
    AcademicRecord,
    DuplicateRutConfirmation,
    SubmissionResult,
)
from backend.error_notifications import ErrorNotificationService
from backend.git_sync import GitSyncService
from backend.personal_academics import PersonalAcademicService
from backend.publication import PublicationCoordinator
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
        academic_catalogs: AcademicCatalogs,
        publications: PublicationCoordinator,
    ) -> None:
        self.authentication = authentication
        self.approvals = approvals
        self.personal_academics = personal_academics
        self.shared_tables = shared_tables
        self.publisher = publisher
        self.notifications = notifications
        self.git = git
        self.paths = paths
        self._academic_catalogs = academic_catalogs
        self.publications = publications

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

    def withdraw_approval_request(self, request_id: str) -> ApprovalEntry:
        return self.approvals.withdraw_request(request_id)

    def get_permissions(self) -> UserPermissions:
        return self.approvals.get_permissions()

    def list_academics(self) -> list[AcademicRecord]:
        return self.personal_academics.list_academics()

    def academic_catalogs(self) -> AcademicCatalogs:
        return self._academic_catalogs

    def save_academic(
        self,
        form_data: AcademicFormData,
        overwrite_confirmation: DuplicateRutConfirmation | None = None,
    ) -> SubmissionResult:
        return self.personal_academics.save_academic(
            form_data,
            overwrite_confirmation,
        )

    def update_academic(
        self, academic_id: str, form_data: AcademicFormData
    ) -> SubmissionResult:
        return self.personal_academics.update_academic(academic_id, form_data)

    def list_shared_tables(self) -> list[SharedTable]:
        self.approvals.require_approved()
        return self.shared_tables.list_shared_tables()

    def list_shared_table_contents(self) -> list[SharedTableContent]:
        self.approvals.require_approved()
        contents = self.shared_tables.list_with_contents()
        result: list[SharedTableContent] = []
        for item in contents:
            table_number = item.metadata.table_number
            draft = (
                self.publications.effective_records(table_number)
                if table_number is not None
                else None
            )
            result.append(
                SharedTableContent(
                    item.metadata,
                    item.academics if draft is None else draft,
                )
            )
        return result

    def publish_table(self, publication: TablePublication) -> SharedTable:
        return self.publisher.publish_table(publication)

    def share_table(self, publication: TablePublication) -> SharedTable:
        """Prepare a complete public dataset and pending intent without Git."""
        return self.publisher.publish_table(publication)

    def private_table_name(self) -> str | None:
        return self.publisher.private_name()

    def rename_public_table(self, table_number: int, name: str) -> SharedTable:
        return self.publisher.rename_public_table(table_number, name)

    def update_shared_table(
        self,
        table_number: int,
        records: list[AcademicRecord],
    ) -> SharedTable:
        validated_records: list[AcademicRecord] = []
        for record in records:
            validation = canonical_academic_record(
                record.academic_id,
                AcademicFormData(
                    name=record.name,
                    rut=record.rut,
                    plant=record.plant,
                    profile=record.profile,
                    weekly_hours=record.weekly_hours,
                    status=record.status,
                ),
                catalogs=self._academic_catalogs,
            )
            if isinstance(validation, SubmissionResult):
                raise ValueError(validation.message)
            validated_records.append(validation)
        return self.publisher.update_shared_table(
            table_number,
            validated_records,
        )

    def notify_error(self, notification: ErrorNotification) -> StoredErrorNotification:
        return self.notifications.notify_error(notification)

    def list_received_errors(self) -> list[StoredErrorNotification]:
        return self.notifications.list_received()

    def mark_error_seen(self, notification_id: str) -> None:
        self.notifications.mark_seen(notification_id)

    def flush_pending_errors(self) -> int:
        return self.notifications.flush_pending()

    def run_update(self, update_name: str) -> UpdateResult:
        permissions = self.approvals.require_approved()
        pending_operation = self.publications.pending_personal()
        if pending_operation is not None and hasattr(self.git, "publish_operation"):
            published = self.publications.publish(pending_operation.operation_id)
            self.publisher.clear_pending_share()
            return published
        pulled = self.git.run_update()
        pending = self.publisher.pending_share()
        if pending is None:
            return pulled
        table = self.shared_tables.get_by_number(pending.table_number)
        if table is None or table.owner_username != permissions.username:
            raise RuntimeError("La preparación pendiente no corresponde al usuario.")
        published = self.git.publish_changes(
            name=update_name,
            username=permissions.username,
            paths=self.shared_tables.publication_paths_for(table),
        )
        self.publisher.clear_pending_share()
        return published

    def publish_shared_table(self, table_number: int) -> UpdateResult:
        """Publish or retry the authenticated user's draft of one public table."""
        self.approvals.require_approved()
        return self.publications.publish_public_edit(table_number)

    def cancel_shared_table_draft(self, table_number: int) -> None:
        self.approvals.require_approved()
        self.publications.cancel_public_edit(table_number)
