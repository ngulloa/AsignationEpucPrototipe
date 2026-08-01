"""Atomic shared-table index and CSV storage using the operational schema."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.academic_catalog import AcademicCatalogs, get_academic_catalogs
from backend.contracts import AcademicAggregate, AcademicRecord
from backend.rut_validator import canonicalize_rut, is_valid_rut, normalize_rut
from backend.system_contracts import SharedTable, normalize_table_name, table_name_key
from persistence.atomic_json_repository import (
    AtomicJsonRepository,
    JsonDocument,
    atomic_write_json,
    create_migration_backup,
    restore_migration_backup,
)
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username

_SAFE_TABLE_FILE = re.compile(r"^table-[0-9]{6}-[a-z0-9._-]+\.csv$", re.ASCII)
TABLES_SCHEMA_VERSION = 2


@dataclass(frozen=True, slots=True)
class SharedTableContent:
    metadata: SharedTable
    academics: tuple[AcademicRecord, ...]


def _validate_tables_document(document: JsonDocument) -> None:
    if set(document) != {"schema_version", "tables"}:
        raise ValueError("El índice de tablas es inválido.")
    if document.get("schema_version") != TABLES_SCHEMA_VERSION:
        raise ValueError("Versión del índice de tablas no soportada.")
    tables = document.get("tables")
    if not isinstance(tables, list):
        raise ValueError("El índice de tablas es inválido.")
    numbers: set[int] = set()
    usernames: set[str] = set()
    filenames: set[str] = set()
    name_keys: set[str] = set()
    for item in tables:
        if not isinstance(item, dict):
            raise ValueError("Una tabla compartida no es un objeto.")
        if set(item) != {"number", "username", "name", "filename", "updated_at"}:
            raise ValueError("Una tabla compartida contiene campos no autorizados.")
        number = item.get("number")
        username = item.get("username")
        name = item.get("name")
        filename = item.get("filename")
        updated_at = item.get("updated_at")
        if type(number) is not int or number <= 0:
            raise ValueError("Número de tabla inválido.")
        if not isinstance(username, str) or normalize_username(username) != username:
            raise ValueError("Usuario de tabla inválido.")
        if not isinstance(name, str) or normalize_table_name(name) != name:
            raise ValueError("Nombre de tabla inválido.")
        normalized_name_key = table_name_key(name)
        if not isinstance(filename, str) or not _SAFE_TABLE_FILE.fullmatch(filename):
            raise ValueError("Archivo de tabla inválido.")
        if not isinstance(updated_at, str) or not updated_at:
            raise ValueError("Fecha de tabla inválida.")
        if (
            number in numbers
            or username in usernames
            or filename in filenames
            or normalized_name_key in name_keys
        ):
            raise ValueError("El índice contiene una tabla duplicada.")
        numbers.add(number)
        usernames.add(username)
        filenames.add(filename)
        name_keys.add(normalized_name_key)


def migrate_tables_index(
    path: Path,
    *,
    backup_directory: Path,
) -> tuple[int, Path | None]:
    """Migrate the existing v1 shape to v2 after collision-safe validation."""
    import json

    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("El índice de tablas no es válido.") from error
    if not isinstance(document, dict):
        raise ValueError("El índice de tablas no es válido.")
    if document.get("schema_version") == TABLES_SCHEMA_VERSION:
        _validate_tables_document(document)
        return 0, None
    if document.get("schema_version") != 1 or set(document) != {
        "schema_version",
        "tables",
    }:
        raise ValueError("El índice de tablas no es v1.")
    tables = document.get("tables")
    if not isinstance(tables, list):
        raise ValueError("El índice de tablas no es válido.")
    migrated_tables: list[JsonDocument] = []
    for table in tables:
        if not isinstance(table, dict):
            raise ValueError("El índice de tablas no es válido.")
        migrated = dict(table)
        migrated["name"] = normalize_table_name(str(table.get("name", "")))
        migrated_tables.append(migrated)
    result: JsonDocument = {
        "schema_version": TABLES_SCHEMA_VERSION,
        "tables": migrated_tables,
    }
    _validate_tables_document(result)
    backup = create_migration_backup(
        path,
        backup_directory,
        filename=f"{path.name}.v1-to-v2.backup.json",
    )
    try:
        atomic_write_json(path, result)
        validated = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(validated, dict):
            raise ValueError("La migración del índice no pudo validarse.")
        _validate_tables_document(validated)
    except Exception:
        restore_migration_backup(backup, path)
        raise
    return len(migrated_tables), backup


class JsonSharedTableRepository:
    """Assign stable numbers and atomically publish one table per user."""

    def __init__(
        self,
        paths: ProjectPaths = DEFAULT_PATHS,
        *,
        catalogs: AcademicCatalogs | None = None,
    ) -> None:
        self.paths = paths
        self._catalogs = catalogs or get_academic_catalogs(paths)
        self._store = AtomicJsonRepository(
            paths.tables_index_path,
            empty_document={"schema_version": TABLES_SCHEMA_VERSION, "tables": []},
            validator=_validate_tables_document,
            recover_corrupt=True,
        )

    @property
    def last_recovery_path(self) -> Path | None:
        return self._store.last_recovery_path

    def list_shared_tables(self) -> list[SharedTable]:
        document = self._store.read()
        tables = document["tables"]
        assert isinstance(tables, list)
        return sorted(
            (self._metadata(item) for item in tables),
            key=lambda table: table_name_key(table.name),
        )

    def list_with_contents(self) -> list[SharedTableContent]:
        result: list[SharedTableContent] = []
        for metadata in self.list_shared_tables():
            records = self._academic_repository(metadata.path).list_all()
            result.append(SharedTableContent(metadata, tuple(records)))
        return result

    def get_by_username(self, username: str) -> SharedTable | None:
        canonical = normalize_username(username)
        return next(
            (
                table
                for table in self.list_shared_tables()
                if table.owner_username == canonical
            ),
            None,
        )

    def get_by_number(self, table_number: int) -> SharedTable | None:
        return next(
            (
                table
                for table in self.list_shared_tables()
                if table.table_number == table_number
            ),
            None,
        )

    def aggregates_for(self, table_number: int) -> list[AcademicAggregate]:
        table = self.get_by_number(table_number)
        if table is None:
            raise KeyError("La tabla compartida no existe.")
        return self._academic_repository(table.path).list_aggregates()

    def plan_publication(self, username: str, name: str) -> SharedTable:
        """Resolve a stable internal path without writing the public dataset."""
        canonical = normalize_username(username)
        clean_name = self.ensure_name_available(name, owner_username=canonical)
        existing = self.get_by_username(canonical)
        if existing is not None:
            return SharedTable(
                table_id=existing.table_id,
                name=clean_name,
                owner_username=canonical,
                path=existing.path,
                table_number=existing.table_number,
                updated_at=existing.updated_at,
            )
        tables = self.list_shared_tables()
        number = max((item.table_number or 0 for item in tables), default=0) + 1
        filename = f"table-{number:06d}-{canonical}.csv"
        return SharedTable(
            table_id=str(number),
            name=clean_name,
            owner_username=canonical,
            path=self.paths.shared_table_path(filename),
            table_number=number,
        )

    def materialize_exact(
        self,
        table: SharedTable,
        aggregates: list[AcademicAggregate],
    ) -> SharedTable:
        """Write one pre-authorized two-CSV dataset and its exact index entry."""
        if table.table_number is None:
            raise ValueError("La tabla preparada no tiene identificador.")
        canonical = normalize_username(table.owner_username)
        clean_name = normalize_table_name(table.name)
        expected_filename = f"table-{table.table_number:06d}-{canonical}.csv"
        if table.path != self.paths.shared_table_path(expected_filename):
            raise ValueError("La ruta interna de la tabla preparada cambió.")
        records = [self._catalogs.project(item) for item in aggregates]
        self._validate_academic_ruts(records)
        document = self._store.read()
        values = document["tables"]
        assert isinstance(values, list)
        existing = next(
            (
                item
                for item in values
                if isinstance(item, dict)
                and (
                    item.get("number") == table.table_number
                    or item.get("username") == canonical
                    or item.get("filename") == expected_filename
                )
            ),
            None,
        )
        if existing is not None and (
            existing.get("number") != table.table_number
            or existing.get("username") != canonical
            or existing.get("filename") != expected_filename
        ):
            raise ValueError(
                "La identidad interna de la tabla fue ocupada remotamente."
            )
        self._ensure_unique_name(values, clean_name, existing=existing)
        self._academic_repository(table.path).replace_aggregates(aggregates)
        updated_at = datetime.now(UTC).isoformat()
        item: JsonDocument = {
            "number": table.table_number,
            "username": canonical,
            "name": clean_name,
            "filename": expected_filename,
            "updated_at": updated_at,
        }
        if existing is None:
            values.append(item)
        else:
            values[values.index(existing)] = item
        self._store.write({"schema_version": TABLES_SCHEMA_VERSION, "tables": values})
        return self._metadata(item)

    def ensure_name_available(
        self,
        name: str,
        *,
        owner_username: str | None = None,
    ) -> str:
        """Backend-facing preflight backed by the repository's canonical key."""
        clean = normalize_table_name(name)
        owner = normalize_username(owner_username) if owner_username else None
        for table in self.list_shared_tables():
            if table.owner_username != owner and table_name_key(
                table.name
            ) == table_name_key(clean):
                raise ValueError("Ya existe una tabla con ese nombre.")
        return clean

    def publish(
        self,
        username: str,
        records: list[AcademicRecord],
        *,
        name: str | None = None,
    ) -> SharedTable:
        canonical = normalize_username(username)
        self._validate_academic_ruts(records)
        clean_name = normalize_table_name(name or canonical)
        document = self._store.read()
        values = document["tables"]
        assert isinstance(values, list)
        existing = next(
            (item for item in values if item.get("username") == canonical), None
        )
        self._ensure_unique_name(values, clean_name, existing=existing)
        if existing is None:
            used = [int(item["number"]) for item in values if isinstance(item, dict)]
            number = max(used, default=0) + 1
            filename = f"table-{number:06d}-{canonical}.csv"
        else:
            number = int(existing["number"])
            filename = str(existing["filename"])

        table_path = self.paths.shared_table_path(filename)
        self._academic_repository(table_path).replace_all(records)
        updated_at = datetime.now(UTC).isoformat()
        new_item: JsonDocument = {
            "number": number,
            "username": canonical,
            "name": clean_name,
            "filename": filename,
            "updated_at": updated_at,
        }
        if existing is None:
            values.append(new_item)
        else:
            values[values.index(existing)] = new_item
        self._store.write({"schema_version": TABLES_SCHEMA_VERSION, "tables": values})
        return self._metadata(new_item)

    def publish_aggregates(
        self,
        username: str,
        aggregates: list[AcademicAggregate],
        *,
        name: str | None = None,
    ) -> SharedTable:
        """Publish the complete appointment histories using the normal index."""
        records = [self._catalogs.project(item) for item in aggregates]
        canonical = normalize_username(username)
        self._validate_academic_ruts(records)
        clean_name = normalize_table_name(name or canonical)
        document = self._store.read()
        values = document["tables"]
        assert isinstance(values, list)
        existing = next(
            (item for item in values if item.get("username") == canonical), None
        )
        self._ensure_unique_name(values, clean_name, existing=existing)
        if existing is None:
            used = [int(item["number"]) for item in values if isinstance(item, dict)]
            number = max(used, default=0) + 1
            filename = f"table-{number:06d}-{canonical}.csv"
        else:
            number = int(existing["number"])
            filename = str(existing["filename"])
        table_path = self.paths.shared_table_path(filename)
        self._academic_repository(table_path).replace_aggregates(aggregates)
        updated_at = datetime.now(UTC).isoformat()
        new_item: JsonDocument = {
            "number": number,
            "username": canonical,
            "name": clean_name,
            "filename": filename,
            "updated_at": updated_at,
        }
        if existing is None:
            values.append(new_item)
        else:
            values[values.index(existing)] = new_item
        self._store.write({"schema_version": TABLES_SCHEMA_VERSION, "tables": values})
        return self._metadata(new_item)

    def update_records(
        self,
        table_number: int,
        records: list[AcademicRecord],
    ) -> SharedTable:
        table = next(
            (
                item
                for item in self.list_shared_tables()
                if item.table_number == table_number
            ),
            None,
        )
        if table is None:
            raise KeyError("La tabla compartida no existe.")
        return self.publish(table.owner_username, records, name=table.name)

    def rename(self, table_number: int, name: str) -> SharedTable:
        clean_name = normalize_table_name(name)
        document = self._store.read()
        tables = document["tables"]
        assert isinstance(tables, list)
        existing = next(
            (
                item
                for item in tables
                if isinstance(item, dict) and item.get("number") == table_number
            ),
            None,
        )
        if existing is None:
            raise KeyError("La tabla compartida no existe.")
        self._ensure_unique_name(tables, clean_name, existing=existing)
        existing["name"] = clean_name
        existing["updated_at"] = datetime.now(UTC).isoformat()
        self._store.write({"schema_version": TABLES_SCHEMA_VERSION, "tables": tables})
        return self._metadata(existing)

    def shared_paths_for(self, table: SharedTable) -> tuple[Path, Path]:
        return self.paths.tables_index_path, table.path

    def publication_paths_for(self, table: SharedTable) -> tuple[Path, ...]:
        """Return every shared registry that may be pending in this update."""
        return (
            self.paths.approved_users_path,
            self.paths.error_notifications_path,
            self.paths.tables_index_path,
            table.path,
            self.paths.academic_appointments_path(table.path),
        )

    def _academic_repository(self, table_path: Path) -> CsvAcademicRepository:
        return CsvAcademicRepository(
            table_path,
            appointments_path=self.paths.academic_appointments_path(table_path),
            catalogs=self._catalogs,
        )

    def _metadata(self, value: object) -> SharedTable:
        assert isinstance(value, dict)
        filename = str(value["filename"])
        number = int(value["number"])
        return SharedTable(
            table_id=str(number),
            name=str(value["name"]),
            owner_username=str(value["username"]),
            path=self.paths.shared_table_path(filename),
            table_number=number,
            updated_at=str(value["updated_at"]),
        )

    @staticmethod
    def _ensure_unique_name(
        values: list[object],
        name: str,
        *,
        existing: object | None,
    ) -> None:
        key = table_name_key(name)
        if any(
            item is not existing
            and isinstance(item, dict)
            and isinstance(item.get("name"), str)
            and table_name_key(str(item["name"])) == key
            for item in values
        ):
            raise ValueError("Ya existe una tabla con ese nombre.")

    @staticmethod
    def _validate_academic_ruts(records: list[AcademicRecord]) -> None:
        seen: set[str] = set()
        for record in records:
            normalized = normalize_rut(record.rut)
            if not is_valid_rut(normalized):
                raise ValueError("El RUT ingresado no es válido.")
            canonical = canonicalize_rut(normalized)
            if canonical in seen:
                raise ValueError("Rut ya registrado.")
            seen.add(canonical)
