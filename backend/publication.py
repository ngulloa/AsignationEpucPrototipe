"""Safe public-table drafts and recoverable, serialized Git publication."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from pathlib import Path

from backend.academic_catalog import AcademicCatalogs
from backend.academic_service import AcademicService
from backend.approval import ApprovalService, AuthorizationError
from backend.contracts import (
    AcademicAggregate,
    AcademicFormData,
    AcademicRecord,
    SubmissionResult,
)
from backend.git_sync import GitPushPendingError, GitSyncService
from backend.system_contracts import (
    PublicationKind,
    PublicationOperation,
    PublicationState,
    SharedTable,
    UpdateResult,
)
from persistence.paths import ProjectPaths
from persistence.publication_operation_repository import (
    PublicationOperationRepository,
)
from persistence.shared_table_repository import JsonSharedTableRepository

_LOCKS_GUARD = threading.Lock()
_PUBLICATION_LOCKS: dict[Path, threading.Lock] = {}


class PublicationBusyError(RuntimeError):
    """Another publication already owns the single-writer lock."""


class ConcurrentDatasetChangeError(RuntimeError):
    """The confirmed public aggregate or its catalogs changed after drafting."""


def _safe_error(error: BaseException, root: Path) -> str:
    message = " ".join(str(error).replace("\r", " ").replace("\n", " ").split())
    root_text = str(root)
    if root_text:
        message = message.replace(root_text, "<repositorio>")
    return (message or "La publicación no pudo completarse de forma segura.")[:500]


class PublicationCoordinator:
    """Own private drafts while public files remain a Git publication concern."""

    def __init__(
        self,
        approvals: ApprovalService,
        shared: JsonSharedTableRepository,
        git: GitSyncService,
        *,
        paths: ProjectPaths,
        catalogs: AcademicCatalogs,
    ) -> None:
        self._approvals = approvals
        self._shared = shared
        self._git = git
        self._paths = paths
        self._catalogs = catalogs

    def prepare_personal(
        self,
        *,
        name: str,
        aggregates: list[AcademicAggregate],
        materialize_locally: bool = True,
    ) -> tuple[SharedTable, PublicationOperation]:
        permissions = self._approvals.require_approved()
        table = self._shared.plan_publication(permissions.username, name)
        if table.table_number is None:
            raise RuntimeError("La tabla preparada no tiene identificador.")
        repository = self._operations(permissions.username)
        previous = repository.pending_personal()
        if previous is not None:
            if previous.state in {
                PublicationState.COMMITTED_LOCAL,
                PublicationState.RETRY_PENDING,
            }:
                raise RuntimeError(
                    "Existe un commit pendiente; debe reintentarlo antes de preparar otro."
                )
            repository.restore_base(previous)
            repository.remove(previous.operation_id)
        authorized = self._authorized_paths(table)
        operation = repository.create(
            kind=PublicationKind.PERSONAL_UPDATE,
            table_number=table.table_number,
            table_name=table.name,
            owner_username=table.owner_username,
            filename=table.path.name,
            authorized_paths=authorized,
            base_fingerprint=self.dataset_fingerprint(table),
            aggregates=list(aggregates),
        )
        repository.capture_base(operation)
        if materialize_locally:
            try:
                table = self._shared.materialize_exact(table, list(aggregates))
            except Exception:
                repository.restore_base(operation)
                repository.remove(operation.operation_id)
                raise
        return table, operation

    def prepare_public_edit(self, table_number: int) -> PublicationOperation:
        permissions = self._approvals.require_approved()
        table = self._require_table(table_number)
        repository = self._operations(permissions.username)
        existing = repository.active_for_table(table_number)
        if existing is not None:
            return existing
        operation = repository.create(
            kind=PublicationKind.PUBLIC_EDIT,
            table_number=table_number,
            table_name=table.name,
            owner_username=table.owner_username,
            filename=table.path.name,
            authorized_paths=self._authorized_paths(table),
            base_fingerprint=self.dataset_fingerprint(table),
            aggregates=self._shared.aggregates_for(table_number),
        )
        repository.capture_base(operation)
        return operation

    def edit_public_academic(
        self,
        table_number: int,
        academic_id: str,
        data: AcademicFormData,
    ) -> SubmissionResult:
        permissions = self._approvals.require_approved()
        operation = self.prepare_public_edit(table_number)
        if operation.state in {
            PublicationState.COMMITTED_LOCAL,
            PublicationState.RETRY_PENDING,
        }:
            return SubmissionResult(
                False,
                "La tabla tiene un commit pendiente y ya no admite más ediciones.",
            )
        repository = self._operations(permissions.username)
        result = AcademicService(
            repository.draft_repository(operation.operation_id),
            catalogs=self._catalogs,
        ).update_academic(academic_id, data)
        if result.success and operation.state is PublicationState.FAILED_BEFORE_COMMIT:
            repository.update_state(operation.operation_id, PublicationState.PREPARED)
        return result

    def replace_public_records(
        self,
        table_number: int,
        records: list[AcademicRecord],
    ) -> None:
        """Compatibility boundary for a validated full-record replacement draft."""
        permissions = self._approvals.require_approved()
        operation = self.prepare_public_edit(table_number)
        if operation.state in {
            PublicationState.COMMITTED_LOCAL,
            PublicationState.RETRY_PENDING,
        }:
            raise RuntimeError(
                "La tabla tiene un commit pendiente y ya no admite más ediciones."
            )
        repository = self._operations(permissions.username)
        repository.draft_repository(operation.operation_id).replace_all(records)
        if operation.state is PublicationState.FAILED_BEFORE_COMMIT:
            repository.update_state(operation.operation_id, PublicationState.PREPARED)

    def effective_records(self, table_number: int) -> tuple[AcademicRecord, ...] | None:
        permissions = self._approvals.require_approved()
        operation = self._operations(permissions.username).active_for_table(
            table_number
        )
        if operation is None or operation.kind is not PublicationKind.PUBLIC_EDIT:
            return None
        return tuple(
            self._operations(permissions.username)
            .draft_repository(operation.operation_id)
            .list_all()
        )

    def cancel_public_edit(self, table_number: int) -> None:
        permissions = self._approvals.require_approved()
        repository = self._operations(permissions.username)
        operation = repository.active_for_table(table_number)
        if operation is None or operation.kind is not PublicationKind.PUBLIC_EDIT:
            return
        repository.remove(operation.operation_id)

    def pending_personal(self) -> PublicationOperation | None:
        permissions = self._approvals.require_approved()
        return self._operations(permissions.username).pending_personal()

    def active_public_edit(self, table_number: int) -> PublicationOperation | None:
        permissions = self._approvals.require_approved()
        operation = self._operations(permissions.username).active_for_table(
            table_number
        )
        if operation is None or operation.kind is not PublicationKind.PUBLIC_EDIT:
            return None
        return operation

    def publish_public_edit(
        self,
        table_number: int,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> UpdateResult:
        permissions = self._approvals.require_approved()
        operation = self._operations(permissions.username).active_for_table(
            table_number
        )
        if operation is None or operation.kind is not PublicationKind.PUBLIC_EDIT:
            raise RuntimeError("No existe un borrador público preparado.")
        return self.publish(operation.operation_id, progress=progress)

    def publish_pending_personal(
        self,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> UpdateResult | None:
        operation = self.pending_personal()
        if operation is None:
            return None
        return self.publish(operation.operation_id, progress=progress)

    def publish(
        self,
        operation_id: str,
        *,
        progress: Callable[[str], None] | None = None,
    ) -> UpdateResult:
        permissions = self._approvals.require_approved()
        repository = self._operations(permissions.username)
        operation = repository.get(operation_id)
        if operation.username != permissions.username:
            raise AuthorizationError("La operación no pertenece a la sesión actual.")
        if (
            operation.kind is PublicationKind.PERSONAL_UPDATE
            and operation.owner_username != permissions.username
        ):
            raise AuthorizationError("Solo el titular puede publicar esta preparación.")
        lock = self._lock()
        if not lock.acquire(blocking=False):
            raise PublicationBusyError("Ya existe una publicación en curso.")
        try:
            return self._publish_locked(repository, operation, progress=progress)
        finally:
            lock.release()

    def dataset_fingerprint(self, table: SharedTable) -> str:
        """Hash both CSVs, the matching index entry and the shared catalog version."""
        digest = hashlib.sha256()
        for label, path in (
            ("academic", table.path),
            ("appointments", self._paths.academic_appointments_path(table.path)),
            ("staff", self._paths.academic_staff_catalog_path),
            ("profiles", self._paths.academic_profiles_catalog_path),
        ):
            digest.update(label.encode("ascii"))
            digest.update(b"\0")
            if path.is_file():
                digest.update(b"present\0")
                digest.update(path.read_bytes())
            else:
                digest.update(b"missing\0")
        entry: object = None
        index_path = self._paths.tables_index_path
        if index_path.is_file():
            document = json.loads(index_path.read_text(encoding="utf-8"))
            tables = document.get("tables", []) if isinstance(document, dict) else []
            if isinstance(tables, list):
                entry = next(
                    (
                        item
                        for item in tables
                        if isinstance(item, dict)
                        and item.get("number") == table.table_number
                    ),
                    None,
                )
        digest.update(b"index-entry\0")
        digest.update(
            json.dumps(
                entry, sort_keys=True, ensure_ascii=False, separators=(",", ":")
            ).encode("utf-8")
        )
        return digest.hexdigest()

    def _publish_locked(
        self,
        repository: PublicationOperationRepository,
        operation: PublicationOperation,
        *,
        progress: Callable[[str], None] | None,
    ) -> UpdateResult:
        if operation.state is PublicationState.PUBLISHED:
            return UpdateResult(False, "La operación ya fue publicada.")
        if operation.state in {
            PublicationState.COMMITTED_LOCAL,
            PublicationState.RETRY_PENDING,
        }:
            if operation.commit is None:
                raise RuntimeError("El estado de reintento no contiene un commit.")
            try:
                result = self._git.retry_publication(
                    commit=operation.commit,
                    progress=progress,
                )
            except GitPushPendingError as error:
                repository.update_state(
                    operation.operation_id,
                    PublicationState.RETRY_PENDING,
                    commit=error.commit,
                    error=_safe_error(error, self._paths.root),
                )
                raise
            repository.update_state(
                operation.operation_id,
                PublicationState.PUBLISHED,
                commit=operation.commit,
            )
            repository.cleanup_published_payload(operation.operation_id)
            return result

        table = self._table_from_operation(operation)
        runtime_snapshot: dict[str, bytes | None] = {}
        prepared_base_restored = False

        def verify_base() -> None:
            current = self.dataset_fingerprint(table)
            if current != operation.base_fingerprint:
                raise ConcurrentDatasetChangeError(
                    "El dataset público o sus catálogos cambiaron; el borrador se conservó."
                )
            # A compatible fast-forward may have changed unrelated index entries.
            # Refresh the private rollback snapshot only after the aggregate check.
            repository.capture_base(operation)

        def materialize() -> None:
            for relative in operation.authorized_paths:
                path = self._paths.root / relative
                runtime_snapshot[relative] = (
                    path.read_bytes() if path.is_file() else None
                )
            aggregates = repository.draft_repository(
                operation.operation_id
            ).list_aggregates()
            self._shared.materialize_exact(table, aggregates)

        def rollback() -> None:
            for relative, content in runtime_snapshot.items():
                path = self._paths.root / relative
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_bytes(content)

        def committed(commit: str) -> None:
            repository.update_state(
                operation.operation_id,
                PublicationState.COMMITTED_LOCAL,
                commit=commit,
            )

        try:

            def restore_prepared_base() -> None:
                nonlocal prepared_base_restored
                if (
                    operation.kind is PublicationKind.PERSONAL_UPDATE
                    and operation.state is PublicationState.PREPARED
                ):
                    repository.restore_base(operation)
                    prepared_base_restored = True

            result, commit = self._git.publish_operation(
                operation_id=operation.operation_id,
                name=operation.table_name,
                username=operation.username,
                paths=operation.authorized_paths,
                restore_prepared_base=restore_prepared_base,
                verify_base=verify_base,
                materialize=materialize,
                rollback_materialization=rollback,
                on_committed=committed,
                progress=progress,
            )
        except GitPushPendingError as error:
            repository.update_state(
                operation.operation_id,
                PublicationState.RETRY_PENDING,
                commit=error.commit,
                error=_safe_error(error, self._paths.root),
            )
            raise
        except Exception as error:
            if (
                operation.kind is PublicationKind.PERSONAL_UPDATE
                and operation.state is PublicationState.PREPARED
                and not prepared_base_restored
            ):
                repository.restore_base(operation)
            repository.update_state(
                operation.operation_id,
                PublicationState.FAILED_BEFORE_COMMIT,
                error=_safe_error(error, self._paths.root),
            )
            raise
        repository.update_state(
            operation.operation_id,
            PublicationState.PUBLISHED,
            commit=commit,
        )
        repository.cleanup_published_payload(operation.operation_id)
        return result

    def _operations(self, username: str) -> PublicationOperationRepository:
        return PublicationOperationRepository(
            username,
            paths=self._paths,
            catalogs=self._catalogs,
        )

    def _require_table(self, table_number: int) -> SharedTable:
        table = self._shared.get_by_number(table_number)
        if table is None:
            raise KeyError("La tabla compartida no existe.")
        return table

    def _authorized_paths(self, table: SharedTable) -> tuple[str, ...]:
        return tuple(
            path.relative_to(self._paths.root).as_posix()
            for path in (
                self._paths.tables_index_path,
                table.path,
                self._paths.academic_appointments_path(table.path),
            )
        )

    def _table_from_operation(self, operation: PublicationOperation) -> SharedTable:
        return SharedTable(
            table_id=str(operation.table_number),
            name=operation.table_name,
            owner_username=operation.owner_username,
            path=self._paths.shared_table_path(operation.filename),
            table_number=operation.table_number,
        )

    def _lock(self) -> threading.Lock:
        root = self._paths.root
        with _LOCKS_GUARD:
            return _PUBLICATION_LOCKS.setdefault(root, threading.Lock())
