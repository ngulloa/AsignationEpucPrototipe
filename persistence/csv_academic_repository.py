"""Atomic UTF-8 CSV persistence for academic records."""

from __future__ import annotations

import csv
import os
import tempfile
from pathlib import Path

from backend.academic_repository import (
    AcademicRepositoryIOError,
    AcademicRepositorySchemaError,
)
from backend.contracts import AcademicRecord
from backend.rut_validator import canonicalize_rut, normalize_rut

ACADEMIC_CSV_FIELDS = (
    "academic_id",
    "rut",
    "name",
    "plant",
    "profile",
    "weekly_hours",
    "status",
)


class CsvAcademicRepository:
    """Persist academic records in an exact-schema CSV file."""

    __slots__ = ("_path",)

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path).expanduser().resolve(strict=False)

    @property
    def path(self) -> Path:
        """Return the resolved repository path."""
        return self._path

    def list_all(self) -> list[AcademicRecord]:
        """Read and validate all records in insertion order."""
        self._ensure_operational_file()
        return self._read_records(self._path)

    def find_by_rut(self, rut: str) -> AcademicRecord | None:
        """Find a record after canonicalizing the lookup value."""
        try:
            canonical_rut = canonicalize_rut(rut)
        except ValueError:
            return None

        return next(
            (
                record
                for record in self.list_all()
                if self._canonical_persisted_rut(record.rut) == canonical_rut
            ),
            None,
        )

    @staticmethod
    def _canonical_persisted_rut(rut: str) -> str | None:
        try:
            return canonicalize_rut(normalize_rut(rut))
        except ValueError:
            return None

    def add(self, record: AcademicRecord) -> None:
        """Atomically rewrite the complete validated file with one new record."""
        records = self.list_all()
        self._write_records_atomically([*records, record])

    def update(self, record: AcademicRecord) -> None:
        """Atomically replace one record identified by ``academic_id``."""
        records = self.list_all()
        matching = [
            index
            for index, existing in enumerate(records)
            if existing.academic_id == record.academic_id
        ]
        if len(matching) != 1:
            raise AcademicRepositorySchemaError(
                "El académico que se intentó actualizar no existe de forma única."
            )
        records[matching[0]] = record
        self._write_records_atomically(records)

    def replace_all(self, records: list[AcademicRecord]) -> None:
        """Atomically replace the complete table using the operational schema."""
        identifiers = [record.academic_id for record in records]
        if len(identifiers) != len(set(identifiers)):
            raise AcademicRepositorySchemaError(
                "La tabla académica contiene identificadores duplicados."
            )
        self._write_records_atomically(list(records))

    def _ensure_operational_file(self) -> None:
        if self._path.exists():
            return

        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as error:
            raise AcademicRepositoryIOError(
                "No fue posible crear el directorio del CSV académico."
            ) from error

        if not self._path.exists():
            self._write_records_atomically([])

    def _read_records(self, path: Path) -> list[AcademicRecord]:
        try:
            with path.open("r", encoding="utf-8", newline="") as csv_file:
                reader = csv.DictReader(csv_file, strict=True)
                header = reader.fieldnames
                if header is None:
                    raise AcademicRepositorySchemaError(
                        "El CSV académico no contiene una cabecera."
                    )
                if tuple(header) != ACADEMIC_CSV_FIELDS:
                    expected = ",".join(ACADEMIC_CSV_FIELDS)
                    actual = ",".join(header)
                    raise AcademicRepositorySchemaError(
                        "La cabecera del CSV académico es incorrecta. "
                        f"Se esperaba '{expected}' y se encontró '{actual}'."
                    )

                records: list[AcademicRecord] = []
                for line_number, row in enumerate(reader, start=2):
                    if None in row:
                        raise AcademicRepositorySchemaError(
                            "El CSV académico contiene columnas inesperadas "
                            f"en la línea {line_number}."
                        )
                    if any(row[field] is None for field in ACADEMIC_CSV_FIELDS):
                        raise AcademicRepositorySchemaError(
                            "El CSV académico contiene una fila incompleta "
                            f"en la línea {line_number}."
                        )
                    records.append(self._record_from_row(row, line_number))
                return records
        except AcademicRepositorySchemaError:
            raise
        except (OSError, UnicodeError, csv.Error) as error:
            raise AcademicRepositoryIOError(
                "No fue posible leer el CSV académico."
            ) from error

    @staticmethod
    def _record_from_row(
        row: dict[str | None, str | list[str] | None],
        line_number: int,
    ) -> AcademicRecord:
        try:
            weekly_hours = int(str(row["weekly_hours"]))
        except (TypeError, ValueError) as error:
            raise AcademicRepositorySchemaError(
                f"La jornada semanal debe ser un entero en la línea {line_number}."
            ) from error

        return AcademicRecord(
            academic_id=str(row["academic_id"]),
            rut=str(row["rut"]),
            name=str(row["name"]),
            plant=str(row["plant"]),
            profile=str(row["profile"]),
            weekly_hours=weekly_hours,
            status=str(row["status"]),
        )

    def _write_records_atomically(self, records: list[AcademicRecord]) -> None:
        temporary_path: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=self._path.parent,
                prefix=f".{self._path.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                writer = csv.DictWriter(
                    temporary_file,
                    fieldnames=ACADEMIC_CSV_FIELDS,
                    extrasaction="raise",
                )
                writer.writeheader()
                writer.writerows(self._record_to_row(record) for record in records)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())

            self._read_records(temporary_path)
            os.replace(temporary_path, self._path)
            temporary_path = None
        except AcademicRepositorySchemaError:
            raise
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            raise AcademicRepositoryIOError(
                "No fue posible escribir el CSV académico de forma atómica."
            ) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _record_to_row(record: AcademicRecord) -> dict[str, str | int]:
        return {
            "academic_id": record.academic_id,
            "rut": record.rut,
            "name": record.name,
            "plant": record.plant,
            "profile": record.profile,
            "weekly_hours": record.weekly_hours,
            "status": record.status,
        }
