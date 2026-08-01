"""Shared approval registry and local owner configuration repositories."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from json import JSONDecodeError
from pathlib import Path

from persistence.atomic_json_repository import (
    AtomicJsonRepository,
    JsonDocument,
    atomic_write_json,
    create_migration_backup,
    restore_migration_backup,
)
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username

APPROVAL_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class ApprovalEntry:
    request_id: str
    username: str
    status: str
    requested_at: str
    approved_at: str | None = None
    approved_by: str | None = None
    withdrawn_at: str | None = None
    withdrawn_by: str | None = None


class OwnerConfigurationError(RuntimeError):
    """The required local owner setting is missing or malformed."""


class ApprovalMigrationRequiredError(RuntimeError):
    """A legacy approval register must be migrated without silent rewriting."""


def _validate_utc_timestamp(value: object, *, label: str) -> None:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} inválida.")
    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"{label} inválida.") from error
    if timestamp.utcoffset() != UTC.utcoffset(timestamp):
        raise ValueError(f"{label} debe estar expresada en UTC.")


def _validate_approval_document(document: JsonDocument) -> None:
    if set(document) != {"schema_version", "approved_users"}:
        raise ValueError("Registro de aprobaciones inválido.")
    if document.get("schema_version") != APPROVAL_SCHEMA_VERSION:
        raise ValueError("Versión de aprobaciones no soportada.")
    entries = document.get("approved_users")
    if not isinstance(entries, list):
        raise ValueError("La lista de aprobaciones es inválida.")
    seen_usernames: set[str] = set()
    seen_requests: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("Una aprobación no es un objeto.")
        request_id = entry.get("request_id")
        username = entry.get("username")
        if set(entry) != {
            "request_id",
            "username",
            "status",
            "requested_at",
            "approved_at",
            "approved_by",
            "withdrawn_at",
            "withdrawn_by",
        }:
            raise ValueError("Una aprobación contiene campos no autorizados.")
        status = entry.get("status")
        requested_at = entry.get("requested_at")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("Identificador de aprobación inválido.")
        if not isinstance(username, str) or normalize_username(username) != username:
            raise ValueError("Usuario de aprobación inválido.")
        if status not in {"pending", "approved", "withdrawn"}:
            raise ValueError("Estado de aprobación inválido.")
        _validate_utc_timestamp(requested_at, label="Fecha de solicitud")
        approved_at = entry.get("approved_at")
        approved_by = entry.get("approved_by")
        withdrawn_at = entry.get("withdrawn_at")
        withdrawn_by = entry.get("withdrawn_by")
        if approved_at is not None and not isinstance(approved_at, str):
            raise ValueError("Fecha de aprobación inválida.")
        if approved_at is not None:
            _validate_utc_timestamp(approved_at, label="Fecha de aprobación")
        if approved_by is not None:
            if not isinstance(approved_by, str):
                raise ValueError("Aprobador inválido.")
            normalize_username(approved_by)
        if withdrawn_at is not None and not isinstance(withdrawn_at, str):
            raise ValueError("Fecha de retiro inválida.")
        if withdrawn_at is not None:
            _validate_utc_timestamp(withdrawn_at, label="Fecha de retiro")
        if withdrawn_by is not None:
            if not isinstance(withdrawn_by, str):
                raise ValueError("Autor de retiro inválido.")
            normalize_username(withdrawn_by)
        if status == "pending" and any(
            value is not None
            for value in (approved_at, approved_by, withdrawn_at, withdrawn_by)
        ):
            raise ValueError("Solicitud pendiente con auditoría incompatible.")
        if status == "approved" and (
            approved_at is None
            or approved_by is None
            or withdrawn_at is not None
            or withdrawn_by is not None
        ):
            raise ValueError("Aprobación con auditoría incompatible.")
        if status == "withdrawn" and (
            withdrawn_at is None
            or withdrawn_by != username
            or approved_at is not None
            or approved_by is not None
        ):
            raise ValueError("Retiro con auditoría incompatible.")
        if username in seen_usernames or request_id in seen_requests:
            raise ValueError("Aprobación duplicada.")
        seen_usernames.add(username)
        seen_requests.add(request_id)


def migrate_approvals(
    path: Path,
    *,
    backup_directory: Path,
) -> tuple[int, Path | None]:
    """Back up and atomically migrate v1 approvals to v2 without invented events."""
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, JSONDecodeError) as error:
        raise ValueError("El registro de aprobaciones no es válido.") from error
    if not isinstance(document, dict):
        raise ValueError("El registro de aprobaciones no es válido.")
    version = document.get("schema_version")
    if version == APPROVAL_SCHEMA_VERSION:
        _validate_approval_document(document)
        return 0, None
    if version != 1 or set(document) != {"schema_version", "approved_users"}:
        raise ValueError("El registro de aprobaciones no es v1.")
    entries = document.get("approved_users")
    if not isinstance(entries, list):
        raise ValueError("El registro de aprobaciones no es válido.")
    migrated_entries: list[JsonDocument] = []
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("El registro de aprobaciones no es válido.")
        migrated_entries.append(
            {
                "request_id": entry.get("request_id"),
                "username": entry.get("username"),
                "status": entry.get("status"),
                "requested_at": entry.get("requested_at"),
                "approved_at": entry.get("approved_at"),
                "approved_by": entry.get("approved_by"),
                "withdrawn_at": None,
                "withdrawn_by": None,
            }
        )
    result: JsonDocument = {
        "schema_version": APPROVAL_SCHEMA_VERSION,
        "approved_users": migrated_entries,
    }
    _validate_approval_document(result)
    backup = create_migration_backup(
        path,
        backup_directory,
        filename=f"{path.name}.v1-to-v2.backup.json",
    )
    try:
        atomic_write_json(path, result)
        validated = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(validated, dict):
            raise ValueError("La migración de aprobaciones no pudo validarse.")
        _validate_approval_document(validated)
    except Exception:
        restore_migration_backup(backup, path)
        raise
    return len(migrated_entries), backup


class JsonApprovalRepository:
    """Atomically maintain pending and granted shared approval entries."""

    def __init__(self, paths: ProjectPaths = DEFAULT_PATHS) -> None:
        self.paths = paths
        self._store = AtomicJsonRepository(
            paths.approved_users_path,
            empty_document={
                "schema_version": APPROVAL_SCHEMA_VERSION,
                "approved_users": [],
            },
            validator=_validate_approval_document,
            recover_corrupt=True,
        )

    @property
    def last_recovery_path(self) -> Path | None:
        return self._store.last_recovery_path

    def list_all(self, *, include_withdrawn: bool = False) -> list[ApprovalEntry]:
        document = self._store.read()
        values = document["approved_users"]
        assert isinstance(values, list)
        entries = [self._entry(value) for value in values]
        return (
            entries
            if include_withdrawn
            else [entry for entry in entries if entry.status != "withdrawn"]
        )

    def find_username(self, username: str) -> ApprovalEntry | None:
        canonical = normalize_username(username)
        return next(
            (
                entry
                for entry in self.list_all(include_withdrawn=True)
                if entry.username == canonical
            ),
            None,
        )

    def find_request(self, request_id: str) -> ApprovalEntry | None:
        return next(
            (
                entry
                for entry in self.list_all(include_withdrawn=True)
                if entry.request_id == request_id
            ),
            None,
        )

    def save(self, entry: ApprovalEntry) -> None:
        entries = self.list_all(include_withdrawn=True)
        replaced = False
        for index, existing in enumerate(entries):
            if existing.username == entry.username:
                entries[index] = entry
                replaced = True
                break
        if not replaced:
            entries.append(entry)
        self._store.write(
            {
                "schema_version": APPROVAL_SCHEMA_VERSION,
                "approved_users": [self._document(item) for item in entries],
            }
        )

    @staticmethod
    def _entry(value: object) -> ApprovalEntry:
        assert isinstance(value, dict)
        return ApprovalEntry(
            request_id=str(value["request_id"]),
            username=str(value["username"]),
            status=str(value["status"]),
            requested_at=str(value["requested_at"]),
            approved_at=(
                str(value["approved_at"])
                if value.get("approved_at") is not None
                else None
            ),
            approved_by=(
                str(value["approved_by"])
                if value.get("approved_by") is not None
                else None
            ),
            withdrawn_at=(
                str(value["withdrawn_at"])
                if value.get("withdrawn_at") is not None
                else None
            ),
            withdrawn_by=(
                str(value["withdrawn_by"])
                if value.get("withdrawn_by") is not None
                else None
            ),
        )

    @staticmethod
    def _document(entry: ApprovalEntry) -> JsonDocument:
        return {
            "request_id": entry.request_id,
            "username": entry.username,
            "status": entry.status,
            "requested_at": entry.requested_at,
            "approved_at": entry.approved_at,
            "approved_by": entry.approved_by,
            "withdrawn_at": entry.withdrawn_at,
            "withdrawn_by": entry.withdrawn_by,
        }


def load_owner_username(paths: ProjectPaths = DEFAULT_PATHS) -> str:
    """Load the private owner setting without creating or modifying it."""
    path = paths.owner_local_path
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise OwnerConfigurationError(
            "Configure el propietario en config/owner.local.json."
        ) from error
    except (OSError, UnicodeError, JSONDecodeError) as error:
        raise OwnerConfigurationError(
            "La configuración local del propietario no es válida."
        ) from error
    if not isinstance(parsed, dict) or parsed.get("schema_version") != 1:
        raise OwnerConfigurationError(
            "La configuración local del propietario no es válida."
        )
    username = parsed.get("username")
    if not isinstance(username, str):
        raise OwnerConfigurationError(
            "La configuración local del propietario no contiene un usuario."
        )
    try:
        return normalize_username(username)
    except ValueError as error:
        raise OwnerConfigurationError(
            "El usuario propietario configurado no es seguro."
        ) from error
