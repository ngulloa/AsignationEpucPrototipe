"""Strict, atomic persistence for the single global academic register."""

from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Iterable
from pathlib import Path

from backend.academic_catalog import AcademicCatalogs, get_academic_catalogs
from backend.academic_repository import (
    AcademicRepositoryIOError,
    AcademicRepositoryNotFoundError,
    AcademicRepositorySchemaError,
)
from backend.contracts import AcademicRecord
from backend.rut_validator import canonicalize_rut, is_valid_rut, normalize_rut

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
    """Persist ``AcademicRecord`` values in exactly one UTF-8 CSV file."""

    __slots__ = ("_catalogs", "_path")

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        catalogs: AcademicCatalogs | None = None,
    ) -> None:
        self._path = Path(path).expanduser().resolve(strict=False)
        self._catalogs = catalogs or get_academic_catalogs()

    @property
    def path(self) -> Path:
        return self._path

    def list_all(self) -> list[AcademicRecord]:
        """Return all records in insertion order, creating only an empty CSV."""
        if not self._path.exists():
            self._write_atomically([])
        return self._read_records(self._path)

    def find_by_rut(self, rut: str) -> AcademicRecord | None:
        try:
            normalized_rut = normalize_rut(rut)
        except AttributeError, TypeError:
            return None
        if not is_valid_rut(normalized_rut):
            return None
        canonical_rut = canonicalize_rut(normalized_rut)
        if not self._path.exists():
            return None
        return next(
            (
                record
                for record in self._read_records(self._path)
                if record.rut == canonical_rut
            ),
            None,
        )

    def add(self, record: AcademicRecord) -> None:
        candidate = self._validate_record(record, require_current_catalog=True)
        records = self._read_records(self._path) if self._path.exists() else []
        if any(item.academic_id == candidate.academic_id for item in records):
            raise AcademicRepositorySchemaError("El identificador académico ya existe.")
        if any(item.rut == candidate.rut for item in records):
            raise AcademicRepositorySchemaError("El RUT académico ya existe.")
        records.append(candidate)
        self._write_atomically(records)

    def update(self, record: AcademicRecord) -> None:
        candidate = self._validate_record(record, require_current_catalog=True)
        if not self._path.exists():
            raise AcademicRepositorySchemaError(
                "El académico que se intentó actualizar no existe."
            )
        records = self._read_records(self._path)
        matching = [
            index
            for index, existing in enumerate(records)
            if existing.academic_id == candidate.academic_id
        ]
        if len(matching) != 1:
            raise AcademicRepositorySchemaError(
                "El académico que se intentó actualizar no existe de forma única."
            )
        if any(
            existing.rut == candidate.rut
            and existing.academic_id != candidate.academic_id
            for existing in records
        ):
            raise AcademicRepositorySchemaError(
                "El RUT académico pertenece a otro registro."
            )
        records[matching[0]] = candidate
        self._write_atomically(records)

    def delete(self, academic_id: str) -> None:
        if not isinstance(academic_id, str) or not academic_id.strip():
            raise AcademicRepositoryNotFoundError(
                "El académico que se intentó eliminar no existe."
            )
        if not self._path.exists():
            raise AcademicRepositoryNotFoundError(
                "El académico que se intentó eliminar no existe."
            )
        records = self._read_records(self._path)
        matching = [
            index
            for index, existing in enumerate(records)
            if existing.academic_id == academic_id
        ]
        if len(matching) != 1:
            raise AcademicRepositoryNotFoundError(
                "El académico que se intentó eliminar no existe de forma única."
            )
        del records[matching[0]]
        self._write_atomically(records)

    def replace_all(self, records: list[AcademicRecord]) -> None:
        """Validate a complete current dataset before one atomic replacement."""
        validated = [
            self._validate_record(record, require_current_catalog=True)
            for record in records
        ]
        self._validate_uniqueness(validated)
        self._write_atomically(validated)

    def _read_records(self, path: Path) -> list[AcademicRecord]:
        rows = self._read_exact_rows(path)
        records: list[AcademicRecord] = []
        for line_number, row in rows:
            try:
                weekly_hours = int(row["weekly_hours"])
            except ValueError as error:
                raise AcademicRepositorySchemaError(
                    f"La jornada semanal debe ser un entero en la línea {line_number}."
                ) from error
            record = AcademicRecord(
                academic_id=row["academic_id"],
                rut=row["rut"],
                name=row["name"],
                plant=row["plant"],
                profile=row["profile"],
                weekly_hours=weekly_hours,
                status=row["status"],
            )
            try:
                records.append(
                    self._validate_record(record, require_current_catalog=False)
                )
            except AcademicRepositorySchemaError as error:
                raise AcademicRepositorySchemaError(
                    f"El registro académico de la línea {line_number} es inválido."
                ) from error
        self._validate_uniqueness(records)
        return records

    @staticmethod
    def _read_exact_rows(path: Path) -> list[tuple[int, dict[str, str]]]:
        try:
            with path.open("r", encoding="utf-8", newline="") as csv_file:
                reader = csv.reader(csv_file, strict=True)
                header = tuple(next(reader, ()))
                if header != ACADEMIC_CSV_FIELDS:
                    raise AcademicRepositorySchemaError(
                        "La cabecera del CSV académico es incorrecta."
                    )
                rows: list[tuple[int, dict[str, str]]] = []
                for row in reader:
                    line_number = reader.line_num
                    if len(row) > len(ACADEMIC_CSV_FIELDS):
                        raise AcademicRepositorySchemaError(
                            "El CSV académico contiene columnas inesperadas "
                            f"en la línea {line_number}."
                        )
                    if len(row) < len(ACADEMIC_CSV_FIELDS):
                        raise AcademicRepositorySchemaError(
                            "El CSV académico contiene una fila incompleta "
                            f"en la línea {line_number}."
                        )
                    rows.append(
                        (
                            line_number,
                            dict(zip(ACADEMIC_CSV_FIELDS, row, strict=True)),
                        )
                    )
                return rows
        except AcademicRepositorySchemaError:
            raise
        except (OSError, UnicodeError, csv.Error) as error:
            raise AcademicRepositoryIOError(
                "No fue posible leer el CSV académico."
            ) from error

    def _validate_record(
        self,
        record: AcademicRecord,
        *,
        require_current_catalog: bool,
    ) -> AcademicRecord:
        if not isinstance(record.academic_id, str) or not record.academic_id.strip():
            raise AcademicRepositorySchemaError(
                "El identificador académico es obligatorio."
            )
        if not isinstance(record.name, str):
            raise AcademicRepositorySchemaError("El nombre académico no es texto.")
        if type(record.weekly_hours) is not int:
            raise AcademicRepositorySchemaError(
                "La jornada semanal debe ser un entero."
            )
        if not isinstance(record.rut, str):
            raise AcademicRepositorySchemaError("El RUT académico no es texto.")
        try:
            normalized_rut = normalize_rut(record.rut)
        except (AttributeError, TypeError) as error:
            raise AcademicRepositorySchemaError(
                "El RUT académico no es válido."
            ) from error
        if not is_valid_rut(normalized_rut):
            raise AcademicRepositorySchemaError("El RUT académico no es válido.")
        rut = canonicalize_rut(normalized_rut)

        if require_current_catalog:
            plant = self._catalogs.strict_plant_key(record.plant)
            profile = self._catalogs.strict_profile_key(record.profile)
            status = self._catalogs.strict_status_key(record.status)
            if plant is None or profile is None:
                raise AcademicRepositorySchemaError(
                    "La escritura referencia una planta o perfil inexistente."
                )
            if not self._catalogs.is_compatible(plant, profile):
                raise AcademicRepositorySchemaError(
                    "La escritura referencia una combinación planta-perfil "
                    "incompatible."
                )
            if status is None:
                raise AcademicRepositorySchemaError(
                    "La escritura referencia un estado inexistente."
                )
        else:
            plant = self._catalogs.read_plant_key(record.plant)
            profile = self._catalogs.read_profile_key(record.profile)
            status = self._catalogs.read_status_key(record.status)
            if plant is None or profile is None or status is None:
                raise AcademicRepositorySchemaError(
                    "El registro referencia valores académicos desconocidos."
                )

        return AcademicRecord(
            academic_id=record.academic_id,
            rut=rut,
            name=record.name,
            plant=plant,
            profile=profile,
            weekly_hours=record.weekly_hours,
            status=status,
        )

    @staticmethod
    def _validate_uniqueness(records: Iterable[AcademicRecord]) -> None:
        academic_ids: set[str] = set()
        ruts: set[str] = set()
        for record in records:
            if record.academic_id in academic_ids:
                raise AcademicRepositorySchemaError(
                    "La tabla académica contiene identificadores duplicados."
                )
            if record.rut in ruts:
                raise AcademicRepositorySchemaError(
                    "La tabla académica contiene RUT duplicados."
                )
            academic_ids.add(record.academic_id)
            ruts.add(record.rut)

    def _write_atomically(self, records: list[AcademicRecord]) -> None:
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
                    lineterminator="\n",
                )
                writer.writeheader()
                writer.writerows(self._row(record) for record in records)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            if self._read_records(temporary_path) != records:
                raise AcademicRepositorySchemaError(
                    "La verificación del CSV académico temporal no coincide."
                )
            os.replace(temporary_path, self._path)
            temporary_path = None
            self._fsync_directory(self._path.parent)
        except AcademicRepositorySchemaError, AcademicRepositoryIOError:
            raise
        except (OSError, UnicodeError, csv.Error, TypeError, ValueError) as error:
            raise AcademicRepositoryIOError(
                "No fue posible completar la escritura atómica del CSV académico."
            ) from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    @staticmethod
    def _row(record: AcademicRecord) -> dict[str, str | int]:
        return {
            "academic_id": record.academic_id,
            "rut": record.rut,
            "name": record.name,
            "plant": record.plant,
            "profile": record.profile,
            "weekly_hours": record.weekly_hours,
            "status": record.status,
        }

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        try:
            descriptor = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            os.close(descriptor)
