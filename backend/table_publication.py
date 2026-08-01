"""Authorized publication and editing of operational-schema shared tables."""

from __future__ import annotations

from pathlib import Path

from backend.academic_catalog import AcademicCatalogs, get_academic_catalogs
from backend.approval import ApprovalService, AuthorizationError
from backend.contracts import AcademicFormData, AcademicRecord
from backend.publication import PublicationCoordinator
from backend.system_contracts import SharedTable, TablePublication
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import DEFAULT_PATHS, ProjectPaths
from persistence.private_table_metadata_repository import (
    PendingShareIntent,
    PrivateTableMetadataRepository,
)
from persistence.shared_table_repository import JsonSharedTableRepository


class TablePublicationService:
    """Publish only the authenticated user's canonical personal CSV."""

    def __init__(
        self,
        approvals: ApprovalService,
        repository: JsonSharedTableRepository,
        *,
        paths: ProjectPaths = DEFAULT_PATHS,
        catalogs: AcademicCatalogs | None = None,
        coordinator: PublicationCoordinator | None = None,
    ) -> None:
        self._approvals = approvals
        self._repository = repository
        self._paths = paths
        self._catalogs = catalogs or get_academic_catalogs(paths)
        self._coordinator = coordinator

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
        repository = CsvAcademicRepository(
            expected,
            appointments_path=self._paths.personal_academic_appointments_path(
                permissions.username
            ),
            catalogs=self._catalogs,
        )
        aggregates = repository.list_aggregates()
        metadata = PrivateTableMetadataRepository(
            permissions.username,
            paths=self._paths,
        )
        clean_name = self._repository.ensure_name_available(
            publication.name,
            owner_username=permissions.username,
        )
        metadata.save_name(clean_name)
        if self._coordinator is None:
            table = self._repository.publish_aggregates(
                permissions.username,
                aggregates,
                name=clean_name,
            )
        else:
            table, _operation = self._coordinator.prepare_personal(
                name=clean_name,
                aggregates=aggregates,
            )
        if table.table_number is None:
            raise RuntimeError("La tabla preparada no tiene identificador.")
        metadata.prepare_intent(table.table_number, table.name)
        return table

    def update_shared_table(
        self,
        table_number: int,
        records: list[AcademicRecord],
    ) -> SharedTable:
        """Allow any approved user to edit a private draft of a shared table."""
        self._approvals.require_approved()
        table = self._repository.get_by_number(table_number)
        if table is None:
            raise KeyError("La tabla compartida no existe.")
        if self._coordinator is None:
            return self._repository.update_records(table_number, records)
        current_records = self._coordinator.effective_records(table_number)
        if current_records is None:
            current_records = tuple(
                self._catalogs.project(item)
                for item in self._repository.aggregates_for(table_number)
            )
        current_by_id = {item.academic_id: item for item in current_records}
        if set(current_by_id) != {item.academic_id for item in records}:
            self._coordinator.replace_public_records(table_number, records)
            return table
        for record in records:
            if current_by_id.get(record.academic_id) == record:
                continue
            result = self._coordinator.edit_public_academic(
                table_number,
                record.academic_id,
                AcademicFormData(
                    name=record.name,
                    rut=record.rut,
                    plant=record.plant,
                    profile=record.profile,
                    weekly_hours=record.weekly_hours,
                    status=record.status,
                ),
            )
            if not result.success:
                raise ValueError(result.message)
        return table

    def rename_public_table(self, table_number: int, name: str) -> SharedTable:
        permissions = self._approvals.require_approved()
        table = self._repository.get_by_number(table_number)
        if table is None:
            raise KeyError("La tabla compartida no existe.")
        if table.owner_username != permissions.username:
            raise AuthorizationError("Solo el titular puede renombrar esta tabla.")
        if self._coordinator is not None:
            pending_edit = self._coordinator.active_public_edit(table_number)
            if pending_edit is not None:
                raise RuntimeError(
                    "Publique o vuelva a preparar la tabla antes de renombrarla."
                )
        clean = self._repository.ensure_name_available(
            name,
            owner_username=permissions.username,
        )
        renamed = self._repository.rename(table_number, clean)
        metadata = PrivateTableMetadataRepository(
            permissions.username,
            paths=self._paths,
        )
        metadata.save_name(renamed.name)
        metadata.prepare_intent(table_number, renamed.name)
        return renamed

    def private_name(self) -> str | None:
        permissions = self._approvals.get_permissions()
        return PrivateTableMetadataRepository(
            permissions.username,
            paths=self._paths,
        ).name()

    def pending_share(self) -> PendingShareIntent | None:
        permissions = self._approvals.require_approved()
        return PrivateTableMetadataRepository(
            permissions.username,
            paths=self._paths,
        ).pending_intent()

    def clear_pending_share(self) -> None:
        permissions = self._approvals.require_approved()
        PrivateTableMetadataRepository(
            permissions.username,
            paths=self._paths,
        ).clear_intent()
