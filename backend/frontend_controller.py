"""Presentation adapter from productive services to the existing Qt contracts."""

from __future__ import annotations

from datetime import datetime

from backend.application_service import ApplicationService
from backend.approval import ApprovalError, AuthorizationError
from backend.authentication import AuthenticationError
from backend.contracts import AcademicListingError, SubmissionResult
from backend.git_sync import GitServiceError
from backend.system_contracts import ErrorNotification, TablePublication
from frontend.contracts import (
    ApprovalItem,
    AuthenticationResult,
    ErrorNotificationRequest,
    LoginRequest,
    OwnerAlert,
    RegistrationRequest,
    SharedAcademicTable,
    UiResult,
    UpdateRequest,
)


def _display_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.astimezone().strftime("%d-%m-%Y %H:%M")


class PersistentFrontendController:
    """Translate exceptions to safe UI results while preserving backend checks."""

    def __init__(self, application: ApplicationService) -> None:
        self.application = application

    def authenticate(self, request: LoginRequest) -> AuthenticationResult:
        try:
            session = self.application.authenticate(request.username, request.password)
            permissions = self.application.get_permissions()
        except (AuthenticationError, RuntimeError) as error:
            self.application.logout()
            return AuthenticationResult(False, str(error))
        return AuthenticationResult(
            True,
            "Sesión iniciada correctamente.",
            username=session.username,
            is_owner=permissions.owner,
            is_approved=permissions.approved,
        )

    def register_user(self, request: RegistrationRequest) -> UiResult:
        if request.password != request.password_confirmation:
            message = "Las contraseñas no coinciden."
            return UiResult(False, message, {"password_confirmation": message})
        try:
            self.application.register_user(request.username, request.password)
        except RuntimeError as error:
            return UiResult(False, str(error))
        finally:
            self.application.logout()
        return UiResult(
            True,
            "Usuario registrado. Su solicitud de aprobación quedó registrada.",
        )

    def logout(self) -> None:
        self.application.logout()

    def list_academics(self):
        try:
            return tuple(self.application.list_academics())
        except RuntimeError as error:
            raise AcademicListingError(str(error)) from error

    def submit_academic(self, data):
        try:
            return self.application.save_academic(data)
        except RuntimeError as error:
            return SubmissionResult(False, str(error))

    def update_academic(self, academic_id, data):
        try:
            return self.application.update_academic(academic_id, data)
        except RuntimeError as error:
            return SubmissionResult(False, str(error))

    def update_shared_academic(self, table_number, academic_id, data):
        try:
            contents = self.application.list_shared_table_contents()
            table = next(
                (
                    item
                    for item in contents
                    if item.metadata.table_number == table_number
                ),
                None,
            )
            if table is None:
                return SubmissionResult(False, "La tabla compartida no existe.")
            records = list(table.academics)
            index = next(
                (
                    position
                    for position, record in enumerate(records)
                    if record.academic_id == academic_id
                ),
                None,
            )
            if index is None:
                return SubmissionResult(False, "El académico compartido no existe.")
            existing = records[index]
            records[index] = type(existing)(
                academic_id=existing.academic_id,
                name=data.name,
                rut=data.rut,
                plant=data.plant,
                profile=data.profile,
                weekly_hours=data.weekly_hours,
                status=data.status,
            )
            self.application.update_shared_table(
                table_number,
                records,
                update_name="Edición de tabla compartida",
            )
        except (AuthorizationError, RuntimeError, ValueError, KeyError) as error:
            return SubmissionResult(False, str(error))
        return SubmissionResult(True, "Tabla compartida actualizada correctamente.")

    def list_shared_tables(self):
        contents = self.application.list_shared_table_contents()
        return tuple(
            SharedAcademicTable(
                username=item.metadata.owner_username,
                academics=item.academics,
                table_number=item.metadata.table_number,
            )
            for item in contents
        )

    def list_approvals(self):
        return tuple(
            ApprovalItem(
                request_id=item.request_id,
                username=item.username,
                requested_at=_display_date(item.requested_at),
                status="Aprobado" if item.status == "approved" else "Pendiente",
            )
            for item in self.application.list_approval_requests()
        )

    def approve_user(self, request_id: str) -> UiResult:
        try:
            entry = self.application.grant_request(request_id)
        except (ApprovalError, AuthorizationError, RuntimeError) as error:
            return UiResult(False, str(error))
        return UiResult(True, f"Usuario {entry.username} aprobado.")

    def pending_update_summary(self) -> str:
        try:
            self.application.approvals.require_approved()
            return self.application.git.pending_summary()
        except RuntimeError as error:
            return str(error)

    def run_update(self, request: UpdateRequest) -> UiResult:
        try:
            self.application.run_update()
            self.application.flush_pending_errors()
            source = self.application.paths.personal_academics_path(request.username)
            self.application.publish_table(
                TablePublication(request.update_name, source)
            )
        except (AuthorizationError, GitServiceError, RuntimeError, ValueError) as error:
            return UiResult(False, str(error))
        return UiResult(True, "Actualización publicada correctamente.")

    def notify_error(self, request: ErrorNotificationRequest) -> UiResult:
        try:
            self.application.notify_error(
                ErrorNotification(
                    source_screen=request.source_screen,
                    category=request.category,
                    error_code=request.error_code,
                )
            )
        except (RuntimeError, ValueError) as error:
            return UiResult(False, str(error))
        return UiResult(True, "Notificación enviada al propietario.")

    def list_owner_alerts(self):
        return tuple(
            OwnerAlert(
                alert_id=item.notification_id,
                source_screen=item.source_screen,
                created_at=_display_date(item.created_at),
                category=item.category,
                error_code=item.error_code,
                status=item.status,
            )
            for item in self.application.list_received_errors()
        )
