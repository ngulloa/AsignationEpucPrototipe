"""Side-effect-free factories for the productive backend object graph."""

from __future__ import annotations

from backend.academic_catalog import get_academic_catalogs
from backend.academic_service import AcademicService
from backend.application_service import ApplicationService
from backend.assignment_service import AssignmentService
from backend.authentication import LocalAuthenticationService
from backend.git_sync import GitSyncService
from backend.session import InMemorySession
from persistence.data_model import initialize_empty_dataset
from persistence.normalized_academic_repository import NormalizedAcademicRepository
from persistence.paths import DEFAULT_PATHS, ProjectPaths
from persistence.user_repository import JsonUserRepository


def build_application_service(
    *,
    paths: ProjectPaths = DEFAULT_PATHS,
    git_service: GitSyncService | None = None,
) -> ApplicationService:
    """Build the active services around the one global academic register."""
    initialize_empty_dataset(paths.public_data_dir, DEFAULT_PATHS.public_data_dir)
    sessions = InMemorySession()
    academic_catalogs = get_academic_catalogs(paths)
    authentication = LocalAuthenticationService(
        JsonUserRepository(paths),
        sessions,
    )
    academic_repository = NormalizedAcademicRepository(paths)
    academics = AcademicService(
        academic_repository,
        catalogs=academic_catalogs,
    )
    git_sync = git_service or GitSyncService(paths.root)
    return ApplicationService(
        authentication=authentication,
        sessions=sessions,
        academics=academics,
        paths=paths,
        academic_catalogs=academic_catalogs,
        git_sync=git_sync,
        assignments=AssignmentService(paths),
    )
