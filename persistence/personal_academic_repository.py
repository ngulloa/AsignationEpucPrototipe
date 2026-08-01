"""Composition helper for the existing CSV adapter in a user's storage area."""

from __future__ import annotations

from backend.academic_catalog import AcademicCatalogs, get_academic_catalogs
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import DEFAULT_PATHS, ProjectPaths


def build_personal_academic_repository(
    username: str,
    *,
    paths: ProjectPaths = DEFAULT_PATHS,
    catalogs: AcademicCatalogs | None = None,
) -> CsvAcademicRepository:
    """Bind the existing CSV repository to one user's canonical table path."""
    return CsvAcademicRepository(
        paths.personal_academics_path(username),
        appointments_path=paths.personal_academic_appointments_path(username),
        catalogs=catalogs or get_academic_catalogs(paths),
    )
