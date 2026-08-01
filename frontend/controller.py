"""Injectable frontend contract and deterministic in-memory demonstration adapter."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Protocol

from backend.academic_catalog import AcademicCatalogs, get_academic_catalogs
from backend.academic_service import (
    DUPLICATE_RUT_MESSAGE,
    STALE_DUPLICATE_CONFIRMATION_MESSAGE,
    duplicate_snapshot_token,
)
from backend.contracts import (
    AcademicErrorCode,
    AcademicFormData,
    AcademicRecord,
    DuplicateRutConfirmation,
    SubmissionResult,
)
from backend.rut_validator import normalize_rut
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


class FrontendController(Protocol):
    """Operations the UI may request without knowing implementation details."""

    def authenticate(self, request: LoginRequest) -> AuthenticationResult: ...

    def register_user(self, request: RegistrationRequest) -> UiResult: ...

    def logout(self) -> None: ...

    def list_academics(self) -> Sequence[AcademicRecord]: ...

    def academic_catalogs(self) -> AcademicCatalogs: ...

    def submit_academic(
        self,
        data: AcademicFormData,
        overwrite_confirmation: DuplicateRutConfirmation | None = None,
    ) -> SubmissionResult: ...

    def update_academic(
        self, academic_id: str, data: AcademicFormData
    ) -> SubmissionResult: ...

    def update_shared_academic(
        self,
        table_number: int,
        academic_id: str,
        data: AcademicFormData,
    ) -> SubmissionResult: ...

    def list_shared_tables(self) -> Sequence[SharedAcademicTable]: ...

    def private_table_name(self) -> str: ...

    def share_table(self, request: ShareTableRequest) -> UiResult: ...

    def rename_public_table(self, table_number: int, name: str) -> UiResult: ...

    def publish_shared_table(self, table_number: int) -> UiResult: ...

    def cancel_shared_table_draft(self, table_number: int) -> UiResult: ...

    def list_approvals(self) -> Sequence[ApprovalItem]: ...

    def approve_user(self, request_id: str) -> UiResult: ...

    def withdraw_approval(self, request_id: str) -> UiResult: ...

    def pending_update_summary(self) -> str: ...

    def run_update(self, request: UpdateRequest) -> UiResult: ...

    def notify_error(self, request: ErrorNotificationRequest) -> UiResult: ...

    def list_owner_alerts(self) -> Sequence[OwnerAlert]: ...

    def mark_alert_seen(self, alert_id: str) -> UiResult: ...


def _sample_record(
    academic_id: str,
    name: str,
    rut: str,
    *,
    plant: str = "Ordinaria",
    profile: str = "Mixto",
    weekly_hours: int = 40,
    status: str = "Activo",
) -> AcademicRecord:
    return AcademicRecord(
        academic_id=academic_id,
        name=name,
        rut=rut,
        plant=plant,
        profile=profile,
        weekly_hours=weekly_hours,
        status=status,
    )


class FakeFrontendController:
    """Deterministic, process-local states for navigation and presentation tests.

    It deliberately performs no authentication, persistence, file access, CSV
    parsing, RUT validation or update command. Special visible inputs only choose
    a prepared demo outcome so each error presentation can be exercised.
    """

    def __init__(
        self,
        *,
        academics: Iterable[AcademicRecord] = (),
        shared_tables: Iterable[SharedAcademicTable] | None = None,
        approvals: Iterable[ApprovalItem] | None = None,
        alerts: Iterable[OwnerAlert] | None = None,
    ) -> None:
        self._academics = list(academics)
        self._shared_tables = tuple(
            shared_tables
            if shared_tables is not None
            else (
                SharedAcademicTable(
                    username="maria.soto",
                    table_number=1,
                    academics=(
                        _sample_record(
                            "shared-1",
                            "Persona Demo Uno",
                            "12345678-5",
                        ),
                    ),
                ),
                SharedAcademicTable(
                    username="pedro.perez",
                    table_number=2,
                    academics=(
                        _sample_record(
                            "shared-2",
                            "Persona Demo Dos",
                            "40000000-K",
                            plant="Mixta",
                            profile="Docente",
                            status="Sabático",
                        ),
                    ),
                ),
            )
        )
        self._approvals = list(
            approvals
            if approvals is not None
            else (
                ApprovalItem(
                    request_id="request-1",
                    username="maria.soto",
                    requested_at="30-07-2026 09:15",
                    status="Pendiente",
                ),
                ApprovalItem(
                    request_id="request-2",
                    username="pedro.perez",
                    requested_at="30-07-2026 11:40",
                    status="Pendiente",
                ),
            )
        )
        self._alerts = tuple(
            alerts
            if alerts is not None
            else (
                OwnerAlert(
                    alert_id="alert-1",
                    source_screen="academic_form",
                    created_at="30-07-2026 12:10",
                    category="persistence",
                    error_code="SAVE_ERROR",
                    status="new",
                    description="Descripción ficticia de una falla al guardar.",
                ),
                OwnerAlert(
                    alert_id="alert-2",
                    source_screen="update",
                    created_at="30-07-2026 13:25",
                    category="synchronization",
                    error_code="UPDATE_ERROR",
                    status="new",
                    description="Descripción ficticia de una falla de actualización.",
                ),
            )
        )
        self._sequence = len(self._academics)
        self._authenticated_username = ""
        self._approved = False
        self._private_table_name = ""

    def authenticate(self, request: LoginRequest) -> AuthenticationResult:
        if request.username.strip().lower() == "error":
            return AuthenticationResult(False, "Error de autenticación.")
        username = request.username.strip() or "usuario.demo"
        self._authenticated_username = username
        self._approved = username.lower() in {"propietario", "owner"}
        return AuthenticationResult(
            True,
            "Sesión de demostración iniciada.",
            username=username,
            is_owner=username.lower() in {"propietario", "owner"},
            is_approved=self._approved,
        )

    def register_user(self, request: RegistrationRequest) -> UiResult:
        if request.username.strip().lower() == "registrado":
            return UiResult(False, "El nombre de usuario ya está registrado.")
        if request.password != request.password_confirmation:
            return UiResult(
                False,
                "Las contraseñas no coinciden.",
                {"password_confirmation": "Las contraseñas no coinciden."},
            )
        return UiResult(True, "Solicitud de registro preparada para aprobación.")

    def logout(self) -> None:
        self._authenticated_username = ""
        self._approved = False
        return None

    def list_academics(self) -> Sequence[AcademicRecord]:
        return tuple(self._academics)

    def academic_catalogs(self) -> AcademicCatalogs:
        return get_academic_catalogs()

    def submit_academic(
        self,
        data: AcademicFormData,
        overwrite_confirmation: DuplicateRutConfirmation | None = None,
    ) -> SubmissionResult:
        prepared_errors = {
            "11111111-1": DUPLICATE_RUT_MESSAGE,
            "00000000-0": "Rut inválido.",
            "guardar-error": "Error al guardar.",
        }
        message = prepared_errors.get(data.rut.strip())
        if message is not None:
            return SubmissionResult(False, message, {"rut": message})

        duplicate = next(
            (
                record
                for record in self._academics
                if normalize_rut(record.rut) == normalize_rut(data.rut)
            ),
            None,
        )
        if overwrite_confirmation is not None:
            if (
                duplicate is None
                or duplicate.academic_id != overwrite_confirmation.academic_id
                or duplicate_snapshot_token(duplicate)
                != overwrite_confirmation.snapshot_token
            ):
                return SubmissionResult(
                    False,
                    STALE_DUPLICATE_CONFIRMATION_MESSAGE,
                    {"rut": STALE_DUPLICATE_CONFIRMATION_MESSAGE},
                    error_code=AcademicErrorCode.STALE_DUPLICATE_CONFIRMATION,
                )
            replacement = AcademicRecord(
                academic_id=duplicate.academic_id,
                name=data.name,
                rut=data.rut,
                plant=data.plant,
                profile=data.profile,
                weekly_hours=data.weekly_hours,
                status=data.status,
            )
            self._academics[self._academics.index(duplicate)] = replacement
            return SubmissionResult(
                True,
                "Académico sobrescrito en la demostración.",
            )
        if duplicate is not None:
            confirmation = DuplicateRutConfirmation(
                academic_id=duplicate.academic_id,
                snapshot_token=duplicate_snapshot_token(duplicate),
            )
            return SubmissionResult(
                False,
                DUPLICATE_RUT_MESSAGE,
                {"rut": DUPLICATE_RUT_MESSAGE},
                error_code=AcademicErrorCode.DUPLICATE_RUT,
                duplicate_confirmation=confirmation,
            )

        self._sequence += 1
        self._academics.append(
            AcademicRecord(
                academic_id=f"demo-{self._sequence}",
                name=data.name,
                rut=data.rut,
                plant=data.plant,
                profile=data.profile,
                weekly_hours=data.weekly_hours,
                status=data.status,
            )
        )
        return SubmissionResult(True, "Académico agregado en la demostración.")

    def update_academic(
        self,
        academic_id: str,
        data: AcademicFormData,
    ) -> SubmissionResult:
        for index, existing in enumerate(self._academics):
            if existing.academic_id != academic_id:
                continue
            self._academics[index] = AcademicRecord(
                academic_id=academic_id,
                name=data.name,
                rut=data.rut,
                plant=data.plant,
                profile=data.profile,
                weekly_hours=data.weekly_hours,
                status=data.status,
            )
            return SubmissionResult(True, "Académico actualizado en la demostración.")
        return SubmissionResult(False, "No fue posible actualizar el académico.")

    def list_shared_tables(self) -> Sequence[SharedAcademicTable]:
        return self._shared_tables

    def private_table_name(self) -> str:
        return self._private_table_name

    def share_table(self, request: ShareTableRequest) -> UiResult:
        name = " ".join(request.name.split())
        if not name:
            return UiResult(False, "Ingrese un nombre para la tabla.")
        self._private_table_name = name
        return UiResult(
            True,
            "Tabla preparada localmente. Use Actualizar para publicarla al remoto.",
        )

    def rename_public_table(self, table_number: int, name: str) -> UiResult:
        updated = list(self._shared_tables)
        for index, table in enumerate(updated):
            if table.table_number != table_number:
                continue
            if table.username != self._authenticated_username:
                return UiResult(False, "Solo el titular puede renombrar esta tabla.")
            clean = " ".join(name.split())
            if not clean:
                return UiResult(False, "Ingrese un nombre para la tabla.")
            updated[index] = SharedAcademicTable(
                username=table.username,
                academics=table.academics,
                table_number=table.table_number,
                name=clean,
            )
            self._shared_tables = tuple(updated)
            return UiResult(True, "Nombre de tabla actualizado localmente.")
        return UiResult(False, "La tabla compartida no existe.")

    def publish_shared_table(self, table_number: int) -> UiResult:
        if not self._approved:
            return UiResult(False, "Se requiere una cuenta aprobada.")
        self._shared_tables = tuple(
            SharedAcademicTable(
                username=table.username,
                academics=table.academics,
                table_number=table.table_number,
                name=table.name,
            )
            if table.table_number == table_number
            else table
            for table in self._shared_tables
        )
        return UiResult(True, "Borrador público publicado en la demostración.")

    def cancel_shared_table_draft(self, table_number: int) -> UiResult:
        if not self._approved:
            return UiResult(False, "Se requiere una cuenta aprobada.")
        return UiResult(True, "Borrador público cancelado.")

    def update_shared_academic(
        self,
        table_number: int,
        academic_id: str,
        data: AcademicFormData,
    ) -> SubmissionResult:
        if not self._approved:
            return SubmissionResult(False, "Acceso denegado para editar esta tabla.")
        updated_tables = list(self._shared_tables)
        for table_index, table in enumerate(updated_tables):
            if table.table_number != table_number:
                continue
            records = list(table.academics)
            for record_index, record in enumerate(records):
                if record.academic_id != academic_id:
                    continue
                records[record_index] = AcademicRecord(
                    academic_id=academic_id,
                    name=data.name,
                    rut=data.rut,
                    plant=data.plant,
                    profile=data.profile,
                    weekly_hours=data.weekly_hours,
                    status=data.status,
                )
                updated_tables[table_index] = SharedAcademicTable(
                    username=table.username,
                    academics=tuple(records),
                    table_number=table.table_number,
                    name=table.name,
                    publication_state="prepared",
                )
                self._shared_tables = tuple(updated_tables)
                return SubmissionResult(True, "Tabla compartida actualizada.")
        return SubmissionResult(False, "No fue posible actualizar la tabla compartida.")

    def list_approvals(self) -> Sequence[ApprovalItem]:
        return tuple(self._approvals)

    def approve_user(self, request_id: str) -> UiResult:
        for index, item in enumerate(self._approvals):
            if item.request_id == request_id:
                self._approvals[index] = ApprovalItem(
                    item.request_id,
                    item.username,
                    item.requested_at,
                    "Aprobado",
                )
                return UiResult(True, f"Usuario {item.username} aprobado.")
        return UiResult(False, "No fue posible aprobar la solicitud.")

    def withdraw_approval(self, request_id: str) -> UiResult:
        for index, item in enumerate(self._approvals):
            if item.request_id == request_id and item.status == "Pendiente":
                del self._approvals[index]
                return UiResult(True, "Solicitud retirada correctamente.")
        return UiResult(False, "No fue posible retirar la solicitud.")

    def pending_update_summary(self) -> str:
        return (
            "Interfaz y recursos locales listos para sincronizar. "
            "No se ejecutarán comandos Git en este prototipo."
        )

    def run_update(self, request: UpdateRequest) -> UiResult:
        if request.update_name.strip().lower() == "error":
            return UiResult(False, "Error de actualización.")
        return UiResult(
            True,
            "Actualización simulada correctamente; no se ejecutaron comandos.",
        )

    def notify_error(self, request: ErrorNotificationRequest) -> UiResult:
        if request.error_code == "OTHER_ERROR":
            return UiResult(False, "No fue posible preparar la notificación.")
        return UiResult(True, "Notificación preparada para el propietario.")

    def list_owner_alerts(self) -> Sequence[OwnerAlert]:
        return self._alerts

    def mark_alert_seen(self, alert_id: str) -> UiResult:
        updated: list[OwnerAlert] = []
        found = False
        for alert in self._alerts:
            if alert.alert_id == alert_id:
                alert = OwnerAlert(
                    alert_id=alert.alert_id,
                    source_screen=alert.source_screen,
                    created_at=alert.created_at,
                    category=alert.category,
                    error_code=alert.error_code,
                    status="seen",
                    description=alert.description,
                )
                found = True
            updated.append(alert)
        if not found:
            return UiResult(False, "La alerta no existe.")
        self._alerts = tuple(updated)
        return UiResult(True, "Alerta marcada como vista.")
