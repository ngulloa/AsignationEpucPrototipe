"""Application service for registering and listing academics."""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import uuid4

from backend.academic_repository import (
    AcademicRepository,
    AcademicRepositoryError,
    AcademicRepositoryIOError,
)
from backend.contracts import (
    AcademicFormData,
    AcademicListingError,
    AcademicRecord,
    SubmissionResult,
)
from backend.rut_validator import canonicalize_rut, is_valid_rut, normalize_rut

INVALID_RUT_MESSAGE = "El RUT ingresado no es válido."
DUPLICATE_RUT_MESSAGE = "Rut ya registrado."
PERSISTENCE_ERROR_MESSAGE = "No fue posible guardar el académico. Intente nuevamente."
LISTING_ERROR_MESSAGE = (
    "No fue posible cargar el listado de académicos. Intente nuevamente."
)
SUCCESS_MESSAGE = "Académico guardado correctamente."

IdentifierGenerator = Callable[[], str]

LOGGER = logging.getLogger(__name__)


def _generate_academic_id() -> str:
    return str(uuid4())


class AcademicService:
    """Coordinate RUT validation, duplicate detection and persistence."""

    __slots__ = ("_id_generator", "_repository")

    def __init__(
        self,
        repository: AcademicRepository,
        *,
        id_generator: IdentifierGenerator = _generate_academic_id,
    ) -> None:
        self._repository = repository
        self._id_generator = id_generator

    def register_academic(self, form_data: AcademicFormData) -> SubmissionResult:
        """Validate and persist one academic, returning a presentation-safe result."""
        normalized_rut = normalize_rut(form_data.rut)
        if not is_valid_rut(normalized_rut):
            return SubmissionResult(
                success=False,
                message=INVALID_RUT_MESSAGE,
                field_errors={"rut": INVALID_RUT_MESSAGE},
            )

        canonical_rut = canonicalize_rut(normalized_rut)
        try:
            duplicate = self._repository.find_by_rut(canonical_rut)
            if duplicate is not None:
                return SubmissionResult(
                    success=False,
                    message=DUPLICATE_RUT_MESSAGE,
                    field_errors={"rut": DUPLICATE_RUT_MESSAGE},
                )

            record = AcademicRecord(
                academic_id=self._id_generator(),
                rut=canonical_rut,
                name=form_data.name,
                plant=form_data.plant,
                profile=form_data.profile,
                weekly_hours=form_data.weekly_hours,
                status=form_data.status,
            )
            self._repository.add(record)
        except AcademicRepositoryError:
            LOGGER.exception("Falló la persistencia de un registro académico.")
            return SubmissionResult(
                success=False,
                message=PERSISTENCE_ERROR_MESSAGE,
            )

        return SubmissionResult(success=True, message=SUCCESS_MESSAGE)

    def update_academic(
        self,
        academic_id: str,
        form_data: AcademicFormData,
    ) -> SubmissionResult:
        """Validate and atomically update a record while preserving its identifier."""
        normalized_rut = normalize_rut(form_data.rut)
        if not is_valid_rut(normalized_rut):
            return SubmissionResult(
                success=False,
                message=INVALID_RUT_MESSAGE,
                field_errors={"rut": INVALID_RUT_MESSAGE},
            )
        canonical_rut = canonicalize_rut(normalized_rut)
        try:
            duplicate = self._repository.find_by_rut(canonical_rut)
            if duplicate is not None and duplicate.academic_id != academic_id:
                return SubmissionResult(
                    success=False,
                    message=DUPLICATE_RUT_MESSAGE,
                    field_errors={"rut": DUPLICATE_RUT_MESSAGE},
                )
            record = AcademicRecord(
                academic_id=academic_id,
                rut=canonical_rut,
                name=form_data.name,
                plant=form_data.plant,
                profile=form_data.profile,
                weekly_hours=form_data.weekly_hours,
                status=form_data.status,
            )
            update = getattr(self._repository, "update", None)
            if update is None:
                raise AcademicRepositoryIOError(
                    "El repositorio no permite actualizar registros."
                )
            update(record)
        except AcademicRepositoryError:
            LOGGER.exception("Falló la actualización de un registro académico.")
            return SubmissionResult(success=False, message=PERSISTENCE_ERROR_MESSAGE)
        return SubmissionResult(success=True, message=SUCCESS_MESSAGE)

    def list_academics(self) -> list[AcademicRecord]:
        """Return persisted records, preserving the repository insertion order."""
        try:
            return self._repository.list_all()
        except AcademicRepositoryError as error:
            LOGGER.exception("Falló la lectura del listado académico.")
            raise AcademicListingError(LISTING_ERROR_MESSAGE) from error
