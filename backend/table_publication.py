"""Authorized publication and editing of operational-schema shared tables."""

from __future__ import annotations

from pathlib import Path

from backend.approval import ApprovalService, AuthorizationError
from backend.contracts import AcademicRecord
from backend.git_sync import GitSyncService
from backend.system_contracts import SharedTable, TablePublication
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import DEFAULT_PATHS, ProjectPaths
from persistence.shared_table_repository import JsonSharedTableRepository


class TablePublicationService:
    """Publish only the authenticated user's canonical personal CSV."""

    def __init__(
        self,
        approvals: ApprovalService,
        repository: JsonSharedTableRepository,
        *,
        paths: ProjectPaths = DEFAULT_PATHS,
        git_service: GitSyncService | None = None,
    ) -> None:
        self._approvals = approvals
        self._repository = repository
        self._paths = paths
        self._git = git_service

    def publish_table(self, publication: TablePublication) -> SharedTable:
        permissions = self._approvals.require_approved()
        expected = self._paths.personal_academics_path(permissions.username).resolve(
            strict=False
        )
        supplied = Path(publication.source_path).expanduser().resolve(strict=False)
        if supplied != expected:
            raise AuthorizationError(
                "Solo puede publicar la tabla personal del usuario autenticado."
            )
        records = CsvAcademicRepository(expected).list_all()
        table = self._repository.publish(
            permissions.username,
            records,
            name=publication.name,
        )
        if self._git is not None:
            self._git.publish_changes(
                name=publication.name,
                username=permissions.username,
                paths=self._repository.publication_paths_for(table),
            )
        return table

    def update_shared_table(
        self,
        table_number: int,
        records: list[AcademicRecord],
        *,
        update_name: str,
    ) -> SharedTable:
        """Allow any approved user to atomically edit an existing shared table."""
        permissions = self._approvals.require_approved()
        table = self._repository.update_records(table_number, records)
        if self._git is not None:
            self._git.publish_changes(
                name=update_name,
                username=permissions.username,
                paths=self._repository.publication_paths_for(table),
            )
        return table
