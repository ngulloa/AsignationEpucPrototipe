"""Side-effect-free factories for the productive backend object graph."""

from __future__ import annotations

from backend.academic_catalog import get_academic_catalogs
from backend.academic_service import AcademicService
from backend.application_service import ApplicationService
from backend.authentication import LocalAuthenticationService
from backend.git_sync import GitSyncService
from backend.session import InMemorySession
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import DEFAULT_PATHS, ProjectPaths
from persistence.user_repository import JsonUserRepository


def build_application_service(
    *,
    paths: ProjectPaths = DEFAULT_PATHS,
    git_service: GitSyncService | None = None,
) -> ApplicationService:
    """Build the active services around the one global academic register."""
    sessions = InMemorySession()
    academic_catalogs = get_academic_catalogs(paths)
    authentication = LocalAuthenticationService(
        JsonUserRepository(paths),
        sessions,
    )
    academic_repository = CsvAcademicRepository(
        paths.academic_path,
        catalogs=academic_catalogs,
    )
    academics = AcademicService(
        academic_repository,
        catalogs=academic_catalogs,
    )
    git_sync = git_service or GitSyncService(
        paths.root,
        csv_validator=lambda path: CsvAcademicRepository(
            path,
            catalogs=academic_catalogs,
        ).list_all(),
    )
    return ApplicationService(
        authentication=authentication,
        sessions=sessions,
        academics=academics,
        paths=paths,
        academic_catalogs=academic_catalogs,
        git_sync=git_sync,
    )
