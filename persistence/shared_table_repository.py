"""Atomic shared-table index and CSV storage using the operational schema."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from backend.contracts import AcademicRecord
from backend.rut_validator import canonicalize_rut, is_valid_rut, normalize_rut
from backend.system_contracts import SharedTable
from persistence.atomic_json_repository import AtomicJsonRepository, JsonDocument
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import DEFAULT_PATHS, ProjectPaths, normalize_username

_SAFE_TABLE_FILE = re.compile(r"^table-[0-9]{6}-[a-z0-9._-]+\.csv$", re.ASCII)


@dataclass(frozen=True, slots=True)
class SharedTableContent:
    metadata: SharedTable
    academics: tuple[AcademicRecord, ...]


def _validate_tables_document(document: JsonDocument) -> None:
    if document.get("schema_version") != 1:
        raise ValueError("Versión del índice de tablas no soportada.")
    tables = document.get("tables")
    if not isinstance(tables, list):
        raise ValueError("El índice de tablas es inválido.")
    numbers: set[int] = set()
    usernames: set[str] = set()
    filenames: set[str] = set()
    for item in tables:
        if not isinstance(item, dict):
            raise ValueError("Una tabla compartida no es un objeto.")
        number = item.get("number")
        username = item.get("username")
        name = item.get("name")
        filename = item.get("filename")
        updated_at = item.get("updated_at")
        if type(number) is not int or number <= 0:
            raise ValueError("Número de tabla inválido.")
        if not isinstance(username, str) or normalize_username(username) != username:
            raise ValueError("Usuario de tabla inválido.")
        if not isinstance(name, str) or not name.strip() or len(name) > 80:
            raise ValueError("Nombre de tabla inválido.")
        if not isinstance(filename, str) or not _SAFE_TABLE_FILE.fullmatch(filename):
            raise ValueError("Archivo de tabla inválido.")
        if not isinstance(updated_at, str) or not updated_at:
            raise ValueError("Fecha de tabla inválida.")
        if number in numbers or username in usernames or filename in filenames:
            raise ValueError("El índice contiene una tabla duplicada.")
        numbers.add(number)
        usernames.add(username)
        filenames.add(filename)


class JsonSharedTableRepository:
    """Assign stable numbers and atomically publish one table per user."""

    def __init__(self, paths: ProjectPaths = DEFAULT_PATHS) -> None:
        self.paths = paths
        self._store = AtomicJsonRepository(
            paths.tables_index_path,
            empty_document={"schema_version": 1, "tables": []},
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
        return [self._metadata(item) for item in tables]

    def list_with_contents(self) -> list[SharedTableContent]:
        result: list[SharedTableContent] = []
        for metadata in self.list_shared_tables():
            records = CsvAcademicRepository(metadata.path).list_all()
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

    def publish(
        self,
        username: str,
        records: list[AcademicRecord],
        *,
        name: str | None = None,
    ) -> SharedTable:
        canonical = normalize_username(username)
        self._validate_academic_ruts(records)
        clean_name = self._clean_name(name or canonical)
        document = self._store.read()
        values = document["tables"]
        assert isinstance(values, list)
        existing = next(
            (item for item in values if item.get("username") == canonical), None
        )
        if existing is None:
            used = [int(item["number"]) for item in values if isinstance(item, dict)]
            number = max(used, default=0) + 1
            filename = f"table-{number:06d}-{canonical}.csv"
        else:
            number = int(existing["number"])
            filename = str(existing["filename"])

        table_path = self.paths.shared_table_path(filename)
        # The CSV adapter validates every field and uses same-directory os.replace.
        CsvAcademicRepository(table_path).replace_all(records)
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
        self._store.write({"schema_version": 1, "tables": values})
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

    def shared_paths_for(self, table: SharedTable) -> tuple[Path, Path]:
        return self.paths.tables_index_path, table.path

    def publication_paths_for(self, table: SharedTable) -> tuple[Path, ...]:
        """Return every shared registry that may be pending in this update."""
        return (
            self.paths.approved_users_path,
            self.paths.error_notifications_path,
            self.paths.tables_index_path,
            table.path,
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
    def _clean_name(value: str) -> str:
        clean = " ".join(value.replace("\r", " ").replace("\n", " ").split())
        if not clean or len(clean) > 80:
            raise ValueError(
                "El nombre de la tabla debe tener entre 1 y 80 caracteres."
            )
        return clean

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
