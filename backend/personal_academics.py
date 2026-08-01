"""Frontend-facing boundary for a user's personal academic repository."""

from __future__ import annotations

from backend.academic_catalog import AcademicCatalogs, get_academic_catalogs
from backend.academic_service import AcademicService
from backend.approval import AuthorizationError
from backend.contracts import (
    AcademicFormData,
    AcademicRecord,
    DuplicateRutConfirmation,
    SubmissionResult,
)
from backend.session import SessionMemory
from persistence.paths import DEFAULT_PATHS, ProjectPaths
from persistence.personal_academic_repository import (
    build_personal_academic_repository,
)


class PersonalAcademicService:
    """Bind academic operations to the authenticated user's private CSV."""

    def __init__(
        self,
        sessions: SessionMemory,
        *,
        paths: ProjectPaths = DEFAULT_PATHS,
    ) -> None:
        self._sessions = sessions
        self._paths = paths
        self._catalogs: AcademicCatalogs = get_academic_catalogs(paths)

    def list_academics(self) -> list[AcademicRecord]:
        return self._service().list_academics()

    def save_academic(
        self,
        form_data: AcademicFormData,
        overwrite_confirmation: DuplicateRutConfirmation | None = None,
    ) -> SubmissionResult:
        return self._service().register_academic(form_data, overwrite_confirmation)

    def update_academic(
        self,
        academic_id: str,
        form_data: AcademicFormData,
    ) -> SubmissionResult:
        return self._service().update_academic(academic_id, form_data)

    def _service(self) -> AcademicService:
        session = self._sessions.current_session
        if session is None:
            raise AuthorizationError("Debe iniciar sesión para usar la tabla personal.")
        repository = build_personal_academic_repository(
            session.username,
            paths=self._paths,
            catalogs=self._catalogs,
        )
        return AcademicService(repository, catalogs=self._catalogs)
