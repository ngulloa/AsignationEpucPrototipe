"""Compatible v1 reader and transactional v2 academic dataset persistence."""

from __future__ import annotations

import csv
import os
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import date
from pathlib import Path
from uuid import UUID, uuid4, uuid5

from backend.academic_catalog import AcademicCatalogs, get_academic_catalogs
from backend.academic_repository import (
    AcademicMigrationRequiredError,
    AcademicRepositoryIOError,
    AcademicRepositorySchemaError,
)
from backend.contracts import (
    Academic,
    AcademicAggregate,
    AcademicAppointment,
    AcademicRecord,
)
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
ACADEMIC_V2_CSV_FIELDS = ("academic_id", "rut", "name", "email", "status")
ACADEMIC_APPOINTMENT_CSV_FIELDS = (
    "appointment_id",
    "academic_id",
    "profile_id",
    "weekly_hours",
    "start_date",
    "end_date",
)

_LEGACY_APPOINTMENT_NAMESPACE = UUID("b6276fc7-7569-4e84-ae4b-ea8b1f6230ca")
IdentifierGenerator = Callable[[], str]


def deterministic_legacy_appointment_id(academic_id: str) -> str:
    """Return the stable appointment identity used for every v1 conversion."""
    return str(uuid5(_LEGACY_APPOINTMENT_NAMESPACE, f"academic-v1:{academic_id}"))


def _new_appointment_id() -> str:
    return str(uuid4())


class CsvAcademicRepository:
    """Use the same aggregate contract for private and public CSV path pairs.

    The transaction protocol assumes a single writer. Both complete temporaries
    are validated before replacement; if the second replacement fails, the first
    file is restored from a same-directory rollback snapshot.
    """

    __slots__ = (
        "_appointment_id_generator",
        "_appointments_path",
        "_catalogs",
        "_path",
    )

    def __init__(
        self,
        path: str | os.PathLike[str],
        *,
        appointments_path: str | os.PathLike[str] | None = None,
        catalogs: AcademicCatalogs | None = None,
        appointment_id_generator: IdentifierGenerator = _new_appointment_id,
    ) -> None:
        self._path = Path(path).expanduser().resolve(strict=False)
        self._appointments_path = (
            Path(appointments_path).expanduser().resolve(strict=False)
            if appointments_path is not None
            else self._derive_appointments_path(self._path)
        )
        if self._appointments_path.parent != self._path.parent:
            raise ValueError("Los dos archivos académicos deben compartir directorio.")
        self._catalogs = catalogs or get_academic_catalogs()
        self._appointment_id_generator = appointment_id_generator

    @staticmethod
    def _derive_appointments_path(path: Path) -> Path:
        if path.name == "academics.csv":
            return path.with_name("academic_appointments.csv")
        return path.with_name(f"{path.stem}.appointments.csv")

    @property
    def path(self) -> Path:
        return self._path

    @property
    def appointments_path(self) -> Path:
        return self._appointments_path

    def dataset_version(self) -> int | None:
        """Return 1, 2 or ``None`` for a dataset that does not exist yet."""
        if not self._path.exists():
            return None
        header = self._read_header(self._path)
        if header == ACADEMIC_CSV_FIELDS:
            return 1
        if header == ACADEMIC_V2_CSV_FIELDS:
            return 2
        raise AcademicRepositorySchemaError(
            "La cabecera del CSV académico es incorrecta; no corresponde a v1 ni v2."
        )

    def list_all(self) -> list[AcademicRecord]:
        """Return the flattened UI projection without rewriting legacy input."""
        self._ensure_operational_files()
        if self.dataset_version() == 1:
            return self._read_v1_records(self._path)
        return [self._project(item) for item in self._read_v2_pair()]

    def list_aggregates(self) -> list[AcademicAggregate]:
        """Return a validated aggregate dataset, converting compatible v1 in memory."""
        self._ensure_operational_files()
        if self.dataset_version() == 1:
            return self._v1_aggregates(self._read_v1_records(self._path))
        return self._read_v2_pair()

    def find_by_rut(self, rut: str) -> AcademicRecord | None:
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
        aggregates = self.list_aggregates()
        if any(item.academic.academic_id == record.academic_id for item in aggregates):
            raise AcademicRepositorySchemaError("El identificador académico ya existe.")
        aggregates.append(self._new_aggregate(record))
        self.replace_aggregates(aggregates)

    def update(self, record: AcademicRecord) -> None:
        if self._path.exists() and self.dataset_version() == 1:
            records = self._read_v1_records(self._path)
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
            self.replace_aggregates(self._v1_aggregates(records))
            return
        aggregates = self.list_aggregates()
        matching = [
            index
            for index, item in enumerate(aggregates)
            if item.academic.academic_id == record.academic_id
        ]
        if len(matching) != 1:
            raise AcademicRepositorySchemaError(
                "El académico que se intentó actualizar no existe de forma única."
            )
        index = matching[0]
        aggregates[index] = self._updated_aggregate(aggregates[index], record)
        self.replace_aggregates(aggregates)

    def replace_all(self, records: list[AcademicRecord]) -> None:
        """Replace projections while preserving matching histories and identities."""
        identifiers = [record.academic_id for record in records]
        if len(identifiers) != len(set(identifiers)):
            raise AcademicRepositorySchemaError(
                "La tabla académica contiene identificadores duplicados."
            )
        if self._path.exists() and self.dataset_version() == 1:
            self.replace_aggregates(self._v1_aggregates(records))
            return
        existing = {
            item.academic.academic_id: item
            for item in (self.list_aggregates() if self._path.exists() else [])
        }
        aggregates = [
            self._updated_aggregate(existing[record.academic_id], record)
            if record.academic_id in existing
            else self._new_aggregate(record)
            for record in records
        ]
        self.replace_aggregates(aggregates)

    def replace_aggregates(self, aggregates: list[AcademicAggregate]) -> None:
        """Validate and transactionally replace both v2 files."""
        copied = list(aggregates)
        self._validate_dataset(copied, require_projection=True)
        self._write_pair_transactionally(copied)

    def migrate_to_v2(self) -> bool:
        """Convert a compatible v1 dataset; return false when already v2."""
        self._ensure_operational_files()
        if self.dataset_version() == 2:
            self._validate_dataset(self._read_v2_pair(), require_projection=True)
            return False
        aggregates = self._v1_aggregates(self._read_v1_records(self._path))
        self.replace_aggregates(aggregates)
        return True

    def _ensure_operational_files(self) -> None:
        if self._path.exists():
            if self.dataset_version() == 2 and not self._appointments_path.exists():
                raise AcademicRepositorySchemaError(
                    "El dataset v2 no contiene el archivo de nombramientos."
                )
            return
        if self._appointments_path.exists():
            raise AcademicRepositorySchemaError(
                "Existe un archivo de nombramientos sin su tabla académica."
            )
        self.replace_aggregates([])

    @staticmethod
    def _read_header(path: Path) -> tuple[str, ...]:
        try:
            with path.open("r", encoding="utf-8", newline="") as csv_file:
                reader = csv.reader(csv_file, strict=True)
                return tuple(next(reader))
        except StopIteration as error:
            raise AcademicRepositorySchemaError(
                "El CSV académico no contiene una cabecera."
            ) from error
        except (OSError, UnicodeError, csv.Error) as error:
            raise AcademicRepositoryIOError(
                "No fue posible leer el CSV académico."
            ) from error

    def _read_v1_records(self, path: Path) -> list[AcademicRecord]:
        rows = self._read_exact_rows(path, ACADEMIC_CSV_FIELDS, "académico v1")
        records: list[AcademicRecord] = []
        for line_number, row in rows:
            try:
                weekly_hours = int(row["weekly_hours"])
            except ValueError as error:
                raise AcademicRepositorySchemaError(
                    f"La jornada semanal debe ser un entero en la línea {line_number}."
                ) from error
            records.append(
                AcademicRecord(
                    academic_id=row["academic_id"],
                    rut=row["rut"],
                    name=row["name"],
                    plant=self._catalogs.normalize_plant_for_read(row["plant"]),
                    profile=self._catalogs.normalize_profile_for_read(row["profile"]),
                    weekly_hours=weekly_hours,
                    status=self._catalogs.normalize_status_for_read(row["status"]),
                )
            )
        return records

    def _v1_aggregates(self, records: list[AcademicRecord]) -> list[AcademicAggregate]:
        aggregates: list[AcademicAggregate] = []
        identifiers: set[str] = set()
        for record in records:
            if not record.academic_id or record.academic_id in identifiers:
                raise AcademicMigrationRequiredError(
                    "El dataset v1 contiene una identidad académica ambigua."
                )
            profile_id = self._catalogs.profile_id_for_legacy(
                record.plant, record.profile
            )
            if profile_id is None:
                raise AcademicMigrationRequiredError(
                    "El dataset v1 contiene una planta, perfil o combinación "
                    "que requiere corrección antes de migrar."
                )
            status = self._catalogs.read_status_key(record.status)
            if status is None:
                raise AcademicMigrationRequiredError(
                    "El dataset v1 contiene un estado que requiere corrección."
                )
            try:
                academic = Academic(
                    academic_id=record.academic_id,
                    rut=record.rut,
                    name=record.name,
                    email=None,
                    status=status,
                )
                appointment = AcademicAppointment(
                    appointment_id=deterministic_legacy_appointment_id(
                        record.academic_id
                    ),
                    academic_id=record.academic_id,
                    profile_id=profile_id,
                    weekly_hours=record.weekly_hours,
                )
            except (TypeError, ValueError) as error:
                raise AcademicMigrationRequiredError(
                    "El dataset v1 contiene un registro que requiere corrección."
                ) from error
            aggregates.append(AcademicAggregate(academic, (appointment,)))
            identifiers.add(record.academic_id)
        self._validate_dataset(aggregates, require_projection=True)
        return aggregates

    def _read_v2_pair(
        self,
        academic_path: Path | None = None,
        appointments_path: Path | None = None,
    ) -> list[AcademicAggregate]:
        academic_source = academic_path or self._path
        appointment_source = appointments_path or self._appointments_path
        academic_rows = self._read_exact_rows(
            academic_source, ACADEMIC_V2_CSV_FIELDS, "académico v2"
        )
        appointment_rows = self._read_exact_rows(
            appointment_source,
            ACADEMIC_APPOINTMENT_CSV_FIELDS,
            "nombramientos",
        )
        academics: list[Academic] = []
        appointments_by_academic: dict[str, list[AcademicAppointment]] = {}
        try:
            for _line_number, row in academic_rows:
                academics.append(
                    Academic(
                        academic_id=row["academic_id"],
                        rut=row["rut"],
                        name=row["name"],
                        email=row["email"] or None,
                        status=row["status"],
                    )
                )
            for line_number, row in appointment_rows:
                try:
                    weekly_hours = int(row["weekly_hours"])
                    start_date = self._optional_date(row["start_date"])
                    end_date = self._optional_date(row["end_date"])
                except ValueError as error:
                    raise AcademicRepositorySchemaError(
                        f"El nombramiento de la línea {line_number} es inválido."
                    ) from error
                appointment = AcademicAppointment(
                    appointment_id=row["appointment_id"],
                    academic_id=row["academic_id"],
                    profile_id=row["profile_id"],
                    weekly_hours=weekly_hours,
                    start_date=start_date,
                    end_date=end_date,
                )
                appointments_by_academic.setdefault(appointment.academic_id, []).append(
                    appointment
                )
        except AcademicRepositorySchemaError:
            raise
        except (TypeError, ValueError) as error:
            raise AcademicRepositorySchemaError(
                "El dataset académico v2 contiene datos inválidos."
            ) from error
        aggregates = [
            AcademicAggregate(
                academic,
                tuple(appointments_by_academic.pop(academic.academic_id, [])),
            )
            for academic in academics
        ]
        if appointments_by_academic:
            raise AcademicRepositorySchemaError(
                "Un nombramiento referencia un académico inexistente."
            )
        self._validate_dataset(aggregates, require_projection=False)
        return aggregates

    @staticmethod
    def _optional_date(value: str) -> date | None:
        return date.fromisoformat(value) if value else None

    @staticmethod
    def _read_exact_rows(
        path: Path,
        fields: tuple[str, ...],
        label: str,
    ) -> list[tuple[int, dict[str, str]]]:
        try:
            with path.open("r", encoding="utf-8", newline="") as csv_file:
                reader = csv.DictReader(csv_file, strict=True)
                if tuple(reader.fieldnames or ()) != fields:
                    raise AcademicRepositorySchemaError(
                        f"La cabecera del CSV {label} es incorrecta."
                    )
                rows: list[tuple[int, dict[str, str]]] = []
                for line_number, row in enumerate(reader, start=2):
                    if None in row:
                        raise AcademicRepositorySchemaError(
                            f"El CSV {label} contiene columnas inesperadas "
                            f"en la línea {line_number}."
                        )
                    if any(row[field] is None for field in fields):
                        raise AcademicRepositorySchemaError(
                            f"El CSV {label} contiene una fila incompleta "
                            f"en la línea {line_number}."
                        )
                    rows.append(
                        (line_number, {field: str(row[field]) for field in fields})
                    )
                return rows
        except AcademicRepositorySchemaError:
            raise
        except (OSError, UnicodeError, csv.Error) as error:
            raise AcademicRepositoryIOError(
                f"No fue posible leer el CSV {label}."
            ) from error

    def _new_aggregate(self, record: AcademicRecord) -> AcademicAggregate:
        profile_id = self._active_profile_id(record)
        try:
            return AcademicAggregate(
                Academic(
                    academic_id=record.academic_id,
                    rut=record.rut,
                    name=record.name,
                    email=None,
                    status=record.status,
                ),
                (
                    AcademicAppointment(
                        appointment_id=self._appointment_id_generator(),
                        academic_id=record.academic_id,
                        profile_id=profile_id,
                        weekly_hours=record.weekly_hours,
                    ),
                ),
            )
        except (TypeError, ValueError) as error:
            raise AcademicRepositorySchemaError(
                "El registro académico no es válido para persistencia v2."
            ) from error

    def _updated_aggregate(
        self, aggregate: AcademicAggregate, record: AcademicRecord
    ) -> AcademicAggregate:
        profile_id = self._active_profile_id(record)
        try:
            current = aggregate.current_appointment()
        except ValueError as error:
            raise AcademicRepositorySchemaError(str(error)) from error
        if current is None:
            raise AcademicRepositorySchemaError(
                "El académico no posee un nombramiento vigente editable."
            )
        appointments = tuple(
            replace(
                item,
                profile_id=profile_id,
                weekly_hours=record.weekly_hours,
            )
            if item.appointment_id == current.appointment_id
            else item
            for item in aggregate.appointments
        )
        try:
            academic = Academic(
                academic_id=aggregate.academic.academic_id,
                rut=record.rut,
                name=record.name,
                email=aggregate.academic.email,
                status=record.status,
            )
            return AcademicAggregate(academic, appointments)
        except (TypeError, ValueError) as error:
            raise AcademicRepositorySchemaError(
                "La actualización académica no es válida para persistencia v2."
            ) from error

    def _active_profile_id(self, record: AcademicRecord) -> str:
        plant_key = self._catalogs.strict_plant_key(record.plant)
        profile_key = self._catalogs.strict_profile_key(record.profile)
        if plant_key is None or profile_key is None:
            raise AcademicRepositorySchemaError(
                "La escritura referencia una planta o perfil inactivo o inexistente."
            )
        profile_id = self._catalogs.profile_id_for_keys(plant_key, profile_key)
        if profile_id is None:
            raise AcademicRepositorySchemaError(
                "La escritura referencia una combinación planta-perfil incompatible."
            )
        return profile_id

    def _project(self, aggregate: AcademicAggregate) -> AcademicRecord:
        try:
            return self._catalogs.project(aggregate)
        except ValueError as error:
            raise AcademicRepositorySchemaError(str(error)) from error

    def _validate_dataset(
        self,
        aggregates: Iterable[AcademicAggregate],
        *,
        require_projection: bool,
    ) -> None:
        academic_ids: set[str] = set()
        appointment_ids: set[str] = set()
        ruts: set[str] = set()
        for aggregate in aggregates:
            academic_id = aggregate.academic.academic_id
            if academic_id in academic_ids:
                raise AcademicRepositorySchemaError(
                    "El dataset contiene identificadores académicos duplicados."
                )
            academic_ids.add(academic_id)
            if aggregate.academic.rut in ruts:
                raise AcademicRepositorySchemaError(
                    "El dataset contiene RUT académicos duplicados."
                )
            ruts.add(aggregate.academic.rut)
            for appointment in aggregate.appointments:
                if appointment.appointment_id in appointment_ids:
                    raise AcademicRepositorySchemaError(
                        "El dataset contiene identificadores de nombramiento duplicados."
                    )
                appointment_ids.add(appointment.appointment_id)
                if self._catalogs.profile_by_id(appointment.profile_id) is None:
                    raise AcademicRepositorySchemaError(
                        "Un nombramiento referencia un perfil inexistente."
                    )
            if require_projection:
                self._project(aggregate)

    def _write_pair_transactionally(self, aggregates: list[AcademicAggregate]) -> None:
        temporary_paths: list[Path] = []
        rollback_paths: dict[Path, Path | None] = {}
        replaced: list[Path] = []
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            academic_temporary = self._write_temporary_csv(
                self._path,
                ACADEMIC_V2_CSV_FIELDS,
                (self._academic_row(item.academic) for item in aggregates),
            )
            appointment_temporary = self._write_temporary_csv(
                self._appointments_path,
                ACADEMIC_APPOINTMENT_CSV_FIELDS,
                (
                    self._appointment_row(appointment)
                    for aggregate in aggregates
                    for appointment in aggregate.appointments
                ),
            )
            temporary_paths.extend((academic_temporary, appointment_temporary))
            self._read_v2_pair(academic_temporary, appointment_temporary)
            for destination in (self._path, self._appointments_path):
                rollback_paths[destination] = self._snapshot(destination)
            for temporary, destination in (
                (academic_temporary, self._path),
                (appointment_temporary, self._appointments_path),
            ):
                os.replace(temporary, destination)
                temporary_paths.remove(temporary)
                replaced.append(destination)
            self._fsync_directory(self._path.parent)
        except AcademicRepositorySchemaError, AcademicRepositoryIOError:
            self._rollback(replaced, rollback_paths)
            raise
        except (OSError, UnicodeError, csv.Error, ValueError) as error:
            try:
                self._rollback(replaced, rollback_paths)
            except OSError as rollback_error:
                raise AcademicRepositoryIOError(
                    "Falló la escritura multifichero y su recuperación automática."
                ) from rollback_error
            raise AcademicRepositoryIOError(
                "No fue posible completar la escritura atómica multifichero."
            ) from error
        finally:
            for temporary in temporary_paths:
                self._safe_unlink(temporary)
            for snapshot in rollback_paths.values():
                if snapshot is not None:
                    self._safe_unlink(snapshot)

    @staticmethod
    def _write_temporary_csv(
        destination: Path,
        fields: tuple[str, ...],
        rows: Iterable[dict[str, str | int]],
    ) -> Path:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="",
                dir=destination.parent,
                prefix=f".{destination.name}.",
                suffix=".tmp",
                delete=False,
            ) as temporary_file:
                temporary_path = Path(temporary_file.name)
                writer = csv.DictWriter(
                    temporary_file, fieldnames=fields, extrasaction="raise"
                )
                writer.writeheader()
                writer.writerows(rows)
                temporary_file.flush()
                os.fsync(temporary_file.fileno())
            return temporary_path
        except BaseException:
            if temporary_path is not None:
                CsvAcademicRepository._safe_unlink(temporary_path)
            raise

    @staticmethod
    def _snapshot(path: Path) -> Path | None:
        if not path.exists():
            return None
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".rollback",
            delete=False,
        ) as snapshot:
            snapshot.write(path.read_bytes())
            snapshot.flush()
            os.fsync(snapshot.fileno())
            return Path(snapshot.name)

    @staticmethod
    def _rollback(
        replaced: list[Path], rollback_paths: dict[Path, Path | None]
    ) -> None:
        for destination in reversed(replaced):
            snapshot = rollback_paths[destination]
            if snapshot is None:
                destination.unlink(missing_ok=True)
            else:
                os.replace(snapshot, destination)

    @staticmethod
    def _safe_unlink(path: Path) -> None:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        descriptor = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _academic_row(academic: Academic) -> dict[str, str]:
        return {
            "academic_id": academic.academic_id,
            "rut": academic.rut,
            "name": academic.name,
            "email": academic.email or "",
            "status": academic.status,
        }

    @staticmethod
    def _appointment_row(
        appointment: AcademicAppointment,
    ) -> dict[str, str | int]:
        return {
            "appointment_id": appointment.appointment_id,
            "academic_id": appointment.academic_id,
            "profile_id": appointment.profile_id,
            "weekly_hours": appointment.weekly_hours,
            "start_date": (
                appointment.start_date.isoformat() if appointment.start_date else ""
            ),
            "end_date": appointment.end_date.isoformat()
            if appointment.end_date
            else "",
        }
