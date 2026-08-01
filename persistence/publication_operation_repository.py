"""Private durable publication drafts, audit state and recovery snapshots."""

from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from uuid import UUID, uuid4

from backend.academic_catalog import AcademicCatalogs
from backend.contracts import AcademicAggregate
from backend.system_contracts import (
    PublicationKind,
    PublicationOperation,
    PublicationState,
    normalize_table_name,
)
from persistence.atomic_json_repository import AtomicJsonRepository, JsonDocument
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username

_SAFE_FILENAME = re.compile(r"^table-[0-9]{6}-[a-z0-9._-]+\.csv$", re.ASCII)
_ALL_STATES = {state.value for state in PublicationState}
_ALL_KINDS = {kind.value for kind in PublicationKind}


def _validate_operation(document: JsonDocument) -> None:
    expected = {
        "schema_version",
        "operation_id",
        "username",
        "kind",
        "table_number",
        "table_name",
        "owner_username",
        "filename",
        "authorized_paths",
        "base_fingerprint",
        "state",
        "commit",
        "error",
        "prepared_at",
    }
    if set(document) != expected or document.get("schema_version") != 1:
        raise ValueError("Estado privado de publicación inválido.")
    operation_id = document.get("operation_id")
    try:
        UUID(str(operation_id))
    except (TypeError, ValueError) as error:
        raise ValueError("Identificador de publicación inválido.") from error
    username = document.get("username")
    owner = document.get("owner_username")
    if not isinstance(username, str) or normalize_username(username) != username:
        raise ValueError("Usuario de publicación inválido.")
    if not isinstance(owner, str) or normalize_username(owner) != owner:
        raise ValueError("Titular de publicación inválido.")
    if document.get("kind") not in _ALL_KINDS:
        raise ValueError("Tipo de publicación inválido.")
    if document.get("state") not in _ALL_STATES:
        raise ValueError("Estado de publicación inválido.")
    number = document.get("table_number")
    if type(number) is not int or number <= 0:
        raise ValueError("Tabla de publicación inválida.")
    name = document.get("table_name")
    if not isinstance(name, str) or normalize_table_name(name) != name:
        raise ValueError("Nombre de publicación inválido.")
    filename = document.get("filename")
    if not isinstance(filename, str) or not _SAFE_FILENAME.fullmatch(filename):
        raise ValueError("Ruta de tabla publicada inválida.")
    authorized = document.get("authorized_paths")
    if not isinstance(authorized, list) or len(authorized) != 3:
        raise ValueError("Allowlist de publicación inválida.")
    if len(set(authorized)) != len(authorized):
        raise ValueError("Allowlist de publicación duplicada.")
    for value in authorized:
        if not isinstance(value, str):
            raise ValueError("Ruta autorizada inválida.")
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts:
            raise ValueError("Ruta autorizada inválida.")
    fingerprint = document.get("base_fingerprint")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise ValueError("Huella base inválida.")
    commit = document.get("commit")
    if commit is not None and (
        not isinstance(commit, str)
        or len(commit) not in {40, 64}
        or any(character not in "0123456789abcdef" for character in commit)
    ):
        raise ValueError("Commit de publicación inválido.")
    error = document.get("error")
    if error is not None and (not isinstance(error, str) or len(error) > 500):
        raise ValueError("Error de publicación inválido.")
    if not isinstance(document.get("prepared_at"), str):
        raise ValueError("Fecha de publicación inválida.")


class PublicationOperationRepository:
    """Store each operation below one authenticated user's private outbox."""

    def __init__(
        self,
        username: str,
        *,
        paths: ProjectPaths = DEFAULT_PATHS,
        catalogs: AcademicCatalogs,
    ) -> None:
        self.username = normalize_username(username)
        self.paths = paths
        self.catalogs = catalogs

    def create(
        self,
        *,
        kind: PublicationKind,
        table_number: int,
        table_name: str,
        owner_username: str,
        filename: str,
        authorized_paths: tuple[str, ...],
        base_fingerprint: str,
        aggregates: list[AcademicAggregate],
    ) -> PublicationOperation:
        operation_id = str(uuid4())
        operation = PublicationOperation(
            operation_id=operation_id,
            username=self.username,
            kind=kind,
            table_number=table_number,
            table_name=normalize_table_name(table_name),
            owner_username=normalize_username(owner_username),
            filename=filename,
            authorized_paths=tuple(sorted(authorized_paths)),
            base_fingerprint=base_fingerprint,
            state=PublicationState.PREPARED,
            commit=None,
            error=None,
            prepared_at=datetime.now(UTC).isoformat(),
        )
        directory = self._directory(operation_id)
        directory.mkdir(parents=True, mode=0o700, exist_ok=False)
        try:
            draft = CsvAcademicRepository(
                directory / "academics.csv",
                appointments_path=directory / "academic_appointments.csv",
                catalogs=self.catalogs,
            )
            draft.replace_aggregates(aggregates)
            document = self._document(operation)
            self._store(operation_id, initial=document).write(document)
            self._chmod_private(directory)
        except Exception:
            shutil.rmtree(directory, ignore_errors=True)
            raise
        return operation

    def get(self, operation_id: str) -> PublicationOperation:
        path = self._directory(operation_id) / "operation.json"
        if not path.is_file():
            raise KeyError("La operación de publicación no existe.")
        document = self._store(operation_id).read()
        return self._from_document(document)

    def list_all(self) -> list[PublicationOperation]:
        root = self.paths.publication_operations_dir(self.username)
        if not root.exists():
            return []
        operations: list[PublicationOperation] = []
        for path in sorted(root.iterdir()):
            if not path.is_dir():
                continue
            try:
                operations.append(self.get(path.name))
            except KeyError, ValueError, OSError:
                continue
        return sorted(operations, key=lambda item: item.prepared_at)

    def active_for_table(self, table_number: int) -> PublicationOperation | None:
        active = {
            PublicationState.PREPARED,
            PublicationState.FAILED_BEFORE_COMMIT,
            PublicationState.COMMITTED_LOCAL,
            PublicationState.RETRY_PENDING,
        }
        return next(
            (
                item
                for item in reversed(self.list_all())
                if item.table_number == table_number and item.state in active
            ),
            None,
        )

    def pending_personal(self) -> PublicationOperation | None:
        return next(
            (
                item
                for item in reversed(self.list_all())
                if item.kind is PublicationKind.PERSONAL_UPDATE
                and item.state is not PublicationState.PUBLISHED
            ),
            None,
        )

    def update_state(
        self,
        operation_id: str,
        state: PublicationState,
        *,
        commit: str | None = None,
        error: str | None = None,
    ) -> PublicationOperation:
        current = self.get(operation_id)
        updated = replace(
            current,
            state=state,
            commit=current.commit if commit is None else commit,
            error=error,
        )
        self._store(operation_id).write(self._document(updated))
        return updated

    def draft_repository(self, operation_id: str) -> CsvAcademicRepository:
        directory = self._directory(operation_id)
        return CsvAcademicRepository(
            directory / "academics.csv",
            appointments_path=directory / "academic_appointments.csv",
            catalogs=self.catalogs,
        )

    def capture_base(self, operation: PublicationOperation) -> None:
        directory = self._directory(operation.operation_id) / "base"
        directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        manifest: list[dict[str, object]] = []
        for index, relative in enumerate(operation.authorized_paths):
            source = self.paths.root / relative
            exists = source.is_file()
            manifest.append({"path": relative, "exists": exists})
            if exists:
                (directory / f"{index:03d}.bin").write_bytes(source.read_bytes())
        manifest_path = directory / "manifest.json"
        manifest_path.write_text(
            json.dumps({"schema_version": 1, "files": manifest}, indent=2) + "\n",
            encoding="utf-8",
        )
        self._chmod_private(directory)

    def restore_base(self, operation: PublicationOperation) -> None:
        directory = self._directory(operation.operation_id) / "base"
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        entries = manifest.get("files")
        if not isinstance(entries, list) or len(entries) != len(
            operation.authorized_paths
        ):
            raise ValueError("Respaldo privado de publicación inválido.")
        for index, entry in enumerate(entries):
            if (
                not isinstance(entry, dict)
                or entry.get("path") != operation.authorized_paths[index]
            ):
                raise ValueError("Respaldo privado de publicación inválido.")
            destination = self.paths.root / operation.authorized_paths[index]
            if entry.get("exists") is True:
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(directory / f"{index:03d}.bin", destination)
                # Keep recovery repeatable after a failed fetch.
                (directory / f"{index:03d}.bin").write_bytes(destination.read_bytes())
            elif entry.get("exists") is False:
                destination.unlink(missing_ok=True)
            else:
                raise ValueError("Respaldo privado de publicación inválido.")

    def remove(self, operation_id: str) -> None:
        operation = self.get(operation_id)
        if operation.state in {
            PublicationState.COMMITTED_LOCAL,
            PublicationState.RETRY_PENDING,
        }:
            raise ValueError("No se puede cancelar una publicación con commit local.")
        shutil.rmtree(self._directory(operation_id))

    def cleanup_published_payload(self, operation_id: str) -> None:
        operation = self.get(operation_id)
        if operation.state is not PublicationState.PUBLISHED:
            raise ValueError("Solo se limpia una publicación confirmada.")
        directory = self._directory(operation_id)
        for name in ("academics.csv", "academic_appointments.csv"):
            (directory / name).unlink(missing_ok=True)
        shutil.rmtree(directory / "base", ignore_errors=True)

    def _store(
        self,
        operation_id: str,
        *,
        initial: JsonDocument | None = None,
    ) -> AtomicJsonRepository:
        placeholder: JsonDocument = {
            "schema_version": 1,
            "operation_id": operation_id,
            "username": self.username,
            "kind": PublicationKind.PUBLIC_EDIT.value,
            "table_number": 1,
            "table_name": "Publicación pendiente",
            "owner_username": self.username,
            "filename": f"table-000001-{self.username}.csv",
            "authorized_paths": [
                "data/public/tables/table-000001-placeholder.appointments.csv",
                "data/public/tables/table-000001-placeholder.csv",
                "data/public/tables_index.json",
            ],
            "base_fingerprint": "0" * 64,
            "state": PublicationState.FAILED_BEFORE_COMMIT.value,
            "commit": None,
            "error": None,
            "prepared_at": "1970-01-01T00:00:00+00:00",
        }
        return AtomicJsonRepository(
            self._directory(operation_id) / "operation.json",
            empty_document=initial or placeholder,
            validator=_validate_operation,
            recover_corrupt=False,
            file_mode=0o600,
        )

    def _directory(self, operation_id: str) -> Path:
        try:
            UUID(operation_id)
        except ValueError as error:
            raise ValueError("Identificador de publicación inválido.") from error
        return self.paths.publication_operation_dir(self.username, operation_id)

    @staticmethod
    def _document(operation: PublicationOperation) -> JsonDocument:
        return {
            "schema_version": 1,
            "operation_id": operation.operation_id,
            "username": operation.username,
            "kind": operation.kind.value,
            "table_number": operation.table_number,
            "table_name": operation.table_name,
            "owner_username": operation.owner_username,
            "filename": operation.filename,
            "authorized_paths": list(operation.authorized_paths),
            "base_fingerprint": operation.base_fingerprint,
            "state": operation.state.value,
            "commit": operation.commit,
            "error": operation.error,
            "prepared_at": operation.prepared_at,
        }

    @staticmethod
    def _from_document(document: JsonDocument) -> PublicationOperation:
        return PublicationOperation(
            operation_id=str(document["operation_id"]),
            username=str(document["username"]),
            kind=PublicationKind(str(document["kind"])),
            table_number=int(document["table_number"]),
            table_name=str(document["table_name"]),
            owner_username=str(document["owner_username"]),
            filename=str(document["filename"]),
            authorized_paths=tuple(str(item) for item in document["authorized_paths"]),
            base_fingerprint=str(document["base_fingerprint"]),
            state=PublicationState(str(document["state"])),
            commit=(str(document["commit"]) if document["commit"] else None),
            error=str(document["error"]) if document["error"] else None,
            prepared_at=str(document["prepared_at"]),
        )

    @staticmethod
    def _chmod_private(directory: Path) -> None:
        try:
            directory.chmod(0o700)
            for path in directory.rglob("*"):
                path.chmod(0o700 if path.is_dir() else 0o600)
        except OSError:
            # ACLs/platform semantics may supersede POSIX modes.
            pass
