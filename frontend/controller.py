"""Injectable frontend contract and deterministic in-memory test adapter."""

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
    AuthenticationResult,
    LoginRequest,
    RegistrationRequest,
    RegistrationResult,
    UiResult,
)


class FrontendController(Protocol):
    """Operations reachable from the product interface."""

    def authenticate(self, request: LoginRequest) -> AuthenticationResult: ...

    def register_user(self, request: RegistrationRequest) -> RegistrationResult: ...

    def logout(self) -> None: ...

    def list_academics(self) -> Sequence[AcademicRecord]: ...

    def academic_catalogs(self) -> AcademicCatalogs: ...

    def submit_academic(
        self,
        data: AcademicFormData,
        overwrite_confirmation: DuplicateRutConfirmation | None = None,
    ) -> SubmissionResult: ...

    def update_academic(
        self,
        academic_id: str,
        data: AcademicFormData,
    ) -> SubmissionResult: ...

    def delete_academic(self, academic_id: str) -> SubmissionResult: ...

    def download_information(self) -> UiResult: ...

    def upload_information(self) -> UiResult: ...


class FakeFrontendController:
    """Deterministic process-local behavior for view and navigation tests."""

    def __init__(self, *, academics: Iterable[AcademicRecord] = ()) -> None:
        self._academics = list(academics)
        self._sequence = len(self._academics)
        self._authenticated_username = ""

    def authenticate(self, request: LoginRequest) -> AuthenticationResult:
        username = request.username.strip().lower()
        if not username or username == "error":
            return AuthenticationResult(False, "Las credenciales no son válidas.")
        self._authenticated_username = username
        return AuthenticationResult(
            True,
            "Sesión iniciada.",
            username=username,
        )

    def register_user(self, request: RegistrationRequest) -> RegistrationResult:
        username = request.username.strip().lower()
        if username == "registrado":
            return RegistrationResult(
                False,
                "El nombre de usuario ya está registrado.",
            )
        if request.password != request.password_confirmation:
            message = "Las contraseñas no coinciden."
            return RegistrationResult(
                False,
                message,
                {"password_confirmation": message},
            )
        if not username:
            return RegistrationResult(False, "El nombre de usuario es obligatorio.")
        self._authenticated_username = username
        return RegistrationResult(
            True,
            "Cuenta registrada. La sesión quedó iniciada.",
            username=username,
        )

    def logout(self) -> None:
        self._authenticated_username = ""

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
            replacement = self._record(duplicate.academic_id, data)
            self._academics[self._academics.index(duplicate)] = replacement
            return SubmissionResult(
                True,
                "Académico sobrescrito.",
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
        self._academics.append(self._record(f"synthetic-{self._sequence}", data))
        return SubmissionResult(True, "Académico agregado.")

    def update_academic(
        self,
        academic_id: str,
        data: AcademicFormData,
    ) -> SubmissionResult:
        duplicate = next(
            (
                record
                for record in self._academics
                if record.academic_id != academic_id
                and normalize_rut(record.rut) == normalize_rut(data.rut)
            ),
            None,
        )
        if duplicate is not None:
            return SubmissionResult(
                False,
                DUPLICATE_RUT_MESSAGE,
                {"rut": DUPLICATE_RUT_MESSAGE},
                error_code=AcademicErrorCode.DUPLICATE_RUT,
            )
        for index, existing in enumerate(self._academics):
            if existing.academic_id == academic_id:
                self._academics[index] = self._record(academic_id, data)
                return SubmissionResult(
                    True,
                    "Académico actualizado.",
                )
        return SubmissionResult(False, "No fue posible actualizar el académico.")

    def delete_academic(self, academic_id: str) -> SubmissionResult:
        for index, existing in enumerate(self._academics):
            if existing.academic_id == academic_id:
                del self._academics[index]
                return SubmissionResult(
                    True,
                    "Académico eliminado correctamente.",
                )
        return SubmissionResult(
            False,
            "El académico que intentó eliminar ya no existe.",
        )

    def download_information(self) -> UiResult:
        return UiResult(True, "Academic.csv se actualizó correctamente.")

    def upload_information(self) -> UiResult:
        return UiResult(True, "Academic.csv se subió correctamente.")

    @staticmethod
    def _record(academic_id: str, data: AcademicFormData) -> AcademicRecord:
        return AcademicRecord(
            academic_id=academic_id,
            name=data.name,
            rut=data.rut,
            plant=data.plant,
            profile=data.profile,
            weekly_hours=data.weekly_hours,
            status=data.status,
        )
