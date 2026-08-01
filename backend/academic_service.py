"""Application service for validating, registering and listing academics."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from uuid import uuid4

from backend.academic_catalog import ACADEMIC_CATALOGS, AcademicCatalogs
from backend.academic_repository import (
    AcademicRepository,
    AcademicRepositoryError,
    AcademicRepositoryIOError,
)
from backend.contracts import (
    AcademicErrorCode,
    AcademicFormData,
    AcademicListingError,
    AcademicRecord,
    DuplicateRutConfirmation,
    SubmissionResult,
)
from backend.rut_validator import canonicalize_rut, is_valid_rut, normalize_rut

INVALID_RUT_MESSAGE = "El RUT ingresado no es válido."
INVALID_PLANT_MESSAGE = "Seleccione una planta válida."
INVALID_PROFILE_MESSAGE = "Seleccione un perfil válido."
INCOMPATIBLE_PLANT_PROFILE_MESSAGE = (
    "El perfil no es compatible con la planta seleccionada."
)
INVALID_STATUS_MESSAGE = "Seleccione un estado válido."
DUPLICATE_RUT_MESSAGE = "RUT ya existe. Se sobrescribirán los datos del académico."
STALE_DUPLICATE_CONFIRMATION_MESSAGE = (
    "La confirmación de sobrescritura está obsoleta. Revise nuevamente el RUT."
)
PERSISTENCE_ERROR_MESSAGE = "No fue posible guardar el académico. Intente nuevamente."
LISTING_ERROR_MESSAGE = (
    "No fue posible cargar el listado de académicos. Intente nuevamente."
)
SUCCESS_MESSAGE = "Académico guardado correctamente."

ACADEMIC_ERROR_MESSAGES = {
    AcademicErrorCode.INVALID_RUT: INVALID_RUT_MESSAGE,
    AcademicErrorCode.INVALID_PLANT: INVALID_PLANT_MESSAGE,
    AcademicErrorCode.INVALID_PROFILE: INVALID_PROFILE_MESSAGE,
    AcademicErrorCode.INCOMPATIBLE_PLANT_PROFILE: (INCOMPATIBLE_PLANT_PROFILE_MESSAGE),
    AcademicErrorCode.INVALID_STATUS: INVALID_STATUS_MESSAGE,
    AcademicErrorCode.DUPLICATE_RUT: DUPLICATE_RUT_MESSAGE,
    AcademicErrorCode.STALE_DUPLICATE_CONFIRMATION: (
        STALE_DUPLICATE_CONFIRMATION_MESSAGE
    ),
    AcademicErrorCode.PERSISTENCE_ERROR: PERSISTENCE_ERROR_MESSAGE,
}

ACADEMIC_ERROR_FIELDS = {
    AcademicErrorCode.INVALID_RUT: "rut",
    AcademicErrorCode.INVALID_PLANT: "plant",
    AcademicErrorCode.INVALID_PROFILE: "profile",
    AcademicErrorCode.INCOMPATIBLE_PLANT_PROFILE: "profile",
    AcademicErrorCode.INVALID_STATUS: "status",
    AcademicErrorCode.DUPLICATE_RUT: "rut",
    AcademicErrorCode.STALE_DUPLICATE_CONFIRMATION: "rut",
}

IdentifierGenerator = Callable[[], str]

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _ValidatedAcademicData:
    name: str
    rut: str
    plant: str
    profile: str
    weekly_hours: int
    status: str

    def record(self, academic_id: str) -> AcademicRecord:
        return AcademicRecord(
            academic_id=academic_id,
            rut=self.rut,
            name=self.name,
            plant=self.plant,
            profile=self.profile,
            weekly_hours=self.weekly_hours,
            status=self.status,
        )


def _generate_academic_id() -> str:
    return str(uuid4())


def _failure(
    code: AcademicErrorCode,
    *,
    confirmation: DuplicateRutConfirmation | None = None,
) -> SubmissionResult:
    message = ACADEMIC_ERROR_MESSAGES[code]
    field = ACADEMIC_ERROR_FIELDS.get(code)
    return SubmissionResult(
        success=False,
        message=message,
        field_errors={} if field is None else {field: message},
        error_code=code,
        duplicate_confirmation=confirmation,
    )


def _validate_form_data(
    form_data: AcademicFormData,
    catalogs: AcademicCatalogs = ACADEMIC_CATALOGS,
) -> _ValidatedAcademicData | SubmissionResult:
    normalized_rut = normalize_rut(form_data.rut)
    if not is_valid_rut(normalized_rut):
        return _failure(AcademicErrorCode.INVALID_RUT)

    plant = catalogs.strict_plant_key(form_data.plant)
    if plant is None:
        return _failure(AcademicErrorCode.INVALID_PLANT)
    profile = catalogs.strict_profile_key(form_data.profile)
    if profile is None:
        return _failure(AcademicErrorCode.INVALID_PROFILE)
    if not catalogs.is_compatible(plant, profile):
        return _failure(AcademicErrorCode.INCOMPATIBLE_PLANT_PROFILE)
    status = catalogs.strict_status_key(form_data.status)
    if status is None:
        return _failure(AcademicErrorCode.INVALID_STATUS)

    return _ValidatedAcademicData(
        name=form_data.name,
        rut=canonicalize_rut(normalized_rut),
        plant=plant,
        profile=profile,
        weekly_hours=form_data.weekly_hours,
        status=status,
    )


def validate_academic_form(form_data: AcademicFormData) -> SubmissionResult:
    """Validate a write without touching persistence."""
    validated = _validate_form_data(form_data)
    if isinstance(validated, SubmissionResult):
        return validated
    return SubmissionResult(success=True, message="Datos académicos válidos.")


def canonical_academic_record(
    academic_id: str,
    form_data: AcademicFormData,
    *,
    catalogs: AcademicCatalogs = ACADEMIC_CATALOGS,
) -> AcademicRecord | SubmissionResult:
    """Return a canonical record or a field-addressable validation failure."""
    validated = _validate_form_data(form_data, catalogs)
    if isinstance(validated, SubmissionResult):
        return validated
    return validated.record(academic_id)


def duplicate_snapshot_token(record: AcademicRecord) -> str:
    """Return the opaque snapshot identity used for overwrite confirmation."""
    serialized = json.dumps(
        (
            record.academic_id,
            record.rut,
            record.name,
            record.plant,
            record.profile,
            record.weekly_hours,
            record.status,
        ),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


class AcademicService:
    """Coordinate validation, duplicate detection and atomic persistence."""

    __slots__ = ("_catalogs", "_id_generator", "_repository")

    def __init__(
        self,
        repository: AcademicRepository,
        *,
        id_generator: IdentifierGenerator = _generate_academic_id,
        catalogs: AcademicCatalogs = ACADEMIC_CATALOGS,
    ) -> None:
        self._repository = repository
        self._id_generator = id_generator
        self._catalogs = catalogs

    def register_academic(
        self,
        form_data: AcademicFormData,
        overwrite_confirmation: DuplicateRutConfirmation | None = None,
    ) -> SubmissionResult:
        """Create or explicitly overwrite one duplicate after revalidation."""
        validated = _validate_form_data(form_data, self._catalogs)
        if isinstance(validated, SubmissionResult):
            return validated

        try:
            duplicate = self._repository.find_by_rut(validated.rut)
            if overwrite_confirmation is not None:
                if (
                    duplicate is None
                    or duplicate.academic_id != overwrite_confirmation.academic_id
                    or duplicate_snapshot_token(duplicate)
                    != overwrite_confirmation.snapshot_token
                ):
                    return _failure(AcademicErrorCode.STALE_DUPLICATE_CONFIRMATION)
                self._repository.update(validated.record(duplicate.academic_id))
            elif duplicate is not None:
                confirmation = DuplicateRutConfirmation(
                    academic_id=duplicate.academic_id,
                    snapshot_token=duplicate_snapshot_token(duplicate),
                )
                return _failure(
                    AcademicErrorCode.DUPLICATE_RUT,
                    confirmation=confirmation,
                )
            else:
                self._repository.add(validated.record(self._id_generator()))
        except AcademicRepositoryError:
            LOGGER.exception("Falló la persistencia de un registro académico.")
            return _failure(AcademicErrorCode.PERSISTENCE_ERROR)

        return SubmissionResult(success=True, message=SUCCESS_MESSAGE)

    def update_academic(
        self,
        academic_id: str,
        form_data: AcademicFormData,
    ) -> SubmissionResult:
        """Validate and atomically update a record while preserving its identifier."""
        validated = _validate_form_data(form_data, self._catalogs)
        if isinstance(validated, SubmissionResult):
            return validated
        try:
            duplicate = self._repository.find_by_rut(validated.rut)
            if duplicate is not None and duplicate.academic_id != academic_id:
                return _failure(AcademicErrorCode.DUPLICATE_RUT)
            update = getattr(self._repository, "update", None)
            if update is None:
                raise AcademicRepositoryIOError(
                    "El repositorio no permite actualizar registros."
                )
            update(validated.record(academic_id))
        except AcademicRepositoryError:
            LOGGER.exception("Falló la actualización de un registro académico.")
            return _failure(AcademicErrorCode.PERSISTENCE_ERROR)
        return SubmissionResult(success=True, message=SUCCESS_MESSAGE)

    def list_academics(self) -> list[AcademicRecord]:
        """Return persisted records, preserving the repository insertion order."""
        try:
            return self._repository.list_all()
        except AcademicRepositoryError as error:
            LOGGER.exception("Falló la lectura del listado académico.")
            raise AcademicListingError(LISTING_ERROR_MESSAGE) from error
