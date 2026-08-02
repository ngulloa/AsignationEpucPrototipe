"""Productive API for the local demonstration application."""

from __future__ import annotations

from backend.academic_catalog import AcademicCatalogs
from backend.academic_service import AcademicService
from backend.authentication import LocalAuthenticationService
from backend.contracts import (
    AcademicFormData,
    AcademicRecord,
    AuthenticatedSession,
    DuplicateRutConfirmation,
    SubmissionResult,
    UpdateResult,
)
from backend.git_sync import GitSyncService
from backend.session import SessionMemory
from persistence.paths import ProjectPaths


class AuthenticationRequiredError(RuntimeError):
    """An operation requires the current process to hold a session."""


class ApplicationService:
    """Expose authentication and the single global academic register."""

    def __init__(
        self,
        *,
        authentication: LocalAuthenticationService,
        sessions: SessionMemory,
        academics: AcademicService,
        paths: ProjectPaths,
        academic_catalogs: AcademicCatalogs,
        git_sync: GitSyncService,
    ) -> None:
        self.authentication = authentication
        self._sessions = sessions
        self._academics = academics
        self.paths = paths
        self._academic_catalogs = academic_catalogs
        self._git_sync = git_sync

    def register_user(self, username: str, password: str) -> AuthenticatedSession:
        """Register and immediately establish the local process session."""
        return self.authentication.register_user(username, password)

    def authenticate(self, username: str, password: str) -> AuthenticatedSession:
        return self.authentication.authenticate(username, password)

    def logout(self) -> None:
        self.authentication.logout()

    def list_academics(self) -> list[AcademicRecord]:
        self._require_session()
        return self._academics.list_academics()

    def academic_catalogs(self) -> AcademicCatalogs:
        return self._academic_catalogs

    def save_academic(
        self,
        form_data: AcademicFormData,
        overwrite_confirmation: DuplicateRutConfirmation | None = None,
    ) -> SubmissionResult:
        self._require_session()
        return self._academics.register_academic(
            form_data,
            overwrite_confirmation,
        )

    def update_academic(
        self,
        academic_id: str,
        form_data: AcademicFormData,
    ) -> SubmissionResult:
        self._require_session()
        return self._academics.update_academic(academic_id, form_data)

    def download_information(self) -> UpdateResult:
        """Safely fast-forward the one shared academic CSV."""
        self._require_session()
        return self._git_sync.download_information()

    def upload_information(self) -> UpdateResult:
        """Safely commit and publish the one shared academic CSV."""
        self._require_session()
        return self._git_sync.upload_information()

    def _require_session(self) -> AuthenticatedSession:
        session = self._sessions.current_session
        if session is None:
            raise AuthenticationRequiredError("Debe iniciar sesión para continuar.")
        return session
