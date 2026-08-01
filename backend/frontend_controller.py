"""Presentation adapter from productive services to the existing Qt contracts."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

from backend.academic_service import ACADEMIC_ERROR_FIELDS, ACADEMIC_ERROR_MESSAGES
from backend.application_service import ApplicationService
from backend.approval import ApprovalError, AuthorizationError
from backend.authentication import AuthenticationError
from backend.contracts import (
    AcademicListingError,
    DuplicateRutConfirmation,
    SubmissionResult,
)
from backend.git_sync import GitServiceError
from backend.system_contracts import (
    DESCRIPTION_REQUIRED_MESSAGE,
    SENSITIVE_DESCRIPTION_MESSAGE,
    ErrorNotification,
    TablePublication,
)
from frontend.contracts import (
    ApprovalItem,
    AuthenticationResult,
    ErrorNotificationRequest,
    LoginRequest,
    OwnerAlert,
    RegistrationRequest,
    SharedAcademicTable,
    ShareTableRequest,
    UiResult,
    UpdateRequest,
)


def _display_date(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return value
    return parsed.astimezone().strftime("%d-%m-%Y %H:%M")


def _translated_academic_result(result: SubmissionResult) -> SubmissionResult:
    """Translate stable backend codes without interpreting catalog rules."""
    if result.error_code is None:
        return result
    message = ACADEMIC_ERROR_MESSAGES.get(result.error_code, result.message)
    field_errors = dict(result.field_errors)
    field = ACADEMIC_ERROR_FIELDS.get(result.error_code)
    if field is not None:
        field_errors[field] = message
    return replace(result, message=message, field_errors=field_errors)


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

    def academic_catalogs(self):
        return self.application.academic_catalogs()

    def submit_academic(
        self,
        data,
        overwrite_confirmation: DuplicateRutConfirmation | None = None,
    ):
        try:
            result = self.application.save_academic(data, overwrite_confirmation)
        except RuntimeError as error:
            return SubmissionResult(False, str(error))
        return _translated_academic_result(result)

    def update_academic(self, academic_id, data):
        try:
            result = self.application.update_academic(academic_id, data)
        except RuntimeError as error:
            return SubmissionResult(False, str(error))
        return _translated_academic_result(result)

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
            replacement = type(existing)(
                academic_id=existing.academic_id,
                name=data.name,
                rut=data.rut,
                plant=data.plant,
                profile=data.profile,
                weekly_hours=data.weekly_hours,
                status=data.status,
            )
            if replacement == existing:
                return SubmissionResult(False, "No hay cambios para publicar.")
            records[index] = replacement
            self.application.update_shared_table(
                table_number,
                records,
            )
        except (AuthorizationError, RuntimeError, ValueError, KeyError) as error:
            return SubmissionResult(False, str(error))
        return SubmissionResult(
            True,
            "Borrador preparado. Publicar enviará el dataset compartido completo.",
        )

    def list_shared_tables(self):
        contents = self.application.list_shared_table_contents()
        tables: list[SharedAcademicTable] = []
        for item in contents:
            table_number = item.metadata.table_number
            operation = (
                self.application.publications.active_public_edit(table_number)
                if table_number is not None
                else None
            )
            tables.append(
                SharedAcademicTable(
                    username=item.metadata.owner_username,
                    academics=item.academics,
                    table_number=table_number,
                    name=item.metadata.name,
                    publication_state=(
                        operation.state.value if operation is not None else None
                    ),
                )
            )
        return tuple(tables)

    def list_approvals(self):
        permissions = self.application.get_permissions()
        return tuple(
            ApprovalItem(
                request_id=item.request_id,
                username=item.username,
                requested_at=_display_date(item.requested_at),
                status="Aprobado" if item.status == "approved" else "Pendiente",
                can_withdraw=(
                    item.status == "pending" and item.username == permissions.username
                ),
                can_approve=(
                    item.status == "pending"
                    and permissions.approved
                    and item.username != permissions.username
                ),
            )
            for item in self.application.list_approval_requests()
        )

    def approve_user(self, request_id: str) -> UiResult:
        try:
            entry = self.application.grant_request(request_id)
        except (ApprovalError, AuthorizationError, RuntimeError) as error:
            return UiResult(False, str(error))
        return UiResult(True, f"Usuario {entry.username} aprobado.")

    def withdraw_approval(self, request_id: str) -> UiResult:
        try:
            self.application.withdraw_approval_request(request_id)
        except (ApprovalError, AuthorizationError, RuntimeError) as error:
            return UiResult(False, str(error))
        return UiResult(True, "Solicitud retirada correctamente.")

    def pending_update_summary(self) -> str:
        try:
            self.application.approvals.require_approved()
            pending = self.application.publications.pending_personal()
            if pending is not None:
                commit = (
                    f" Commit pendiente: {pending.commit}."
                    if pending.commit is not None
                    else ""
                )
                return (
                    f"Tabla preparada: {pending.table_name}. "
                    f"Estado: {pending.state.value}.{commit}"
                )
            return self.application.git.pending_summary()
        except RuntimeError as error:
            return str(error)

    def run_update(self, request: UpdateRequest) -> UiResult:
        try:
            pending_table = self.application.publications.pending_personal()
            if pending_table is None or not hasattr(
                self.application.git, "publish_operation"
            ):
                self.application.flush_pending_errors()
            self.application.run_update(request.update_name)
        except (AuthorizationError, GitServiceError, RuntimeError, ValueError) as error:
            return UiResult(False, str(error))
        return UiResult(True, "Actualización publicada correctamente.")

    def private_table_name(self) -> str:
        return self.application.private_table_name() or ""

    def share_table(self, request: ShareTableRequest) -> UiResult:
        try:
            permissions = self.application.get_permissions()
            source = self.application.paths.personal_academics_path(
                permissions.username
            )
            self.application.share_table(TablePublication(request.name, source))
        except (AuthorizationError, RuntimeError, ValueError) as error:
            return UiResult(False, str(error), {"name": str(error)})
        return UiResult(
            True,
            "Tabla preparada localmente. Use Actualizar para publicarla al remoto.",
        )

    def rename_public_table(self, table_number: int, name: str) -> UiResult:
        try:
            self.application.rename_public_table(table_number, name)
        except (AuthorizationError, RuntimeError, ValueError, KeyError) as error:
            return UiResult(False, str(error), {"name": str(error)})
        return UiResult(True, "Nombre de tabla actualizado localmente.")

    def publish_shared_table(self, table_number: int) -> UiResult:
        try:
            result = self.application.publish_shared_table(table_number)
        except (AuthorizationError, GitServiceError, RuntimeError, ValueError) as error:
            return UiResult(False, str(error))
        return UiResult(True, result.message)

    def cancel_shared_table_draft(self, table_number: int) -> UiResult:
        try:
            self.application.cancel_shared_table_draft(table_number)
        except (AuthorizationError, RuntimeError, ValueError) as error:
            return UiResult(False, str(error))
        return UiResult(True, "Borrador descartado sin modificar la tabla pública.")

    def notify_error(self, request: ErrorNotificationRequest) -> UiResult:
        try:
            self.application.notify_error(
                ErrorNotification(
                    source_screen=request.source_screen,
                    category=request.category,
                    error_code=request.error_code,
                    description=request.description,
                )
            )
        except ValueError as error:
            message = str(error)
            field_errors = (
                {"description": message}
                if message
                in {
                    DESCRIPTION_REQUIRED_MESSAGE,
                    SENSITIVE_DESCRIPTION_MESSAGE,
                    "La descripción no puede superar 1000 caracteres.",
                }
                else {}
            )
            return UiResult(False, message, field_errors)
        except RuntimeError as error:
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
                description=item.description,
            )
            for item in self.application.list_received_errors()
        )

    def mark_alert_seen(self, alert_id: str) -> UiResult:
        try:
            self.application.mark_error_seen(alert_id)
        except (AuthorizationError, RuntimeError, KeyError) as error:
            return UiResult(False, str(error))
        return UiResult(True, "Alerta marcada como vista.")
