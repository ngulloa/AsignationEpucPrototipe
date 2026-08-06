"""Compatibility repository backed by normalized identity and employment tables."""

from __future__ import annotations

import csv
from datetime import date, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from backend.academic_repository import (
    AcademicRepositoryNotFoundError,
    AcademicRepositorySchemaError,
)
from backend.contracts import AcademicRecord
from backend.rut_validator import canonicalize_rut, is_valid_rut, normalize_rut
from persistence.data_model import TABLE_FIELDS, read_csv
from persistence.paths import ProjectPaths
from persistence.unit_of_work import (
    CsvUnitOfWork,
    DataConcurrencyError,
    DataTransactionError,
)


def _write(path: Path, fields: tuple[str, ...], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


class NormalizedAcademicRepository:
    """Expose the legacy aggregate without duplicating normalized source data."""

    def __init__(self, paths: ProjectPaths) -> None:
        self.paths = paths

    def list_all(self) -> list[AcademicRecord]:
        identities = read_csv(self.paths.academic_path, TABLE_FIELDS["Academic.csv"])
        employments = read_csv(
            self.paths.table_path("academic_employment_history.csv"),
            TABLE_FIELDS["academic_employment_history.csv"],
        )
        return self._join(identities, employments, active_only=False)

    def list_active(self) -> list[AcademicRecord]:
        identities = read_csv(self.paths.academic_path, TABLE_FIELDS["Academic.csv"])
        employments = read_csv(
            self.paths.table_path("academic_employment_history.csv"),
            TABLE_FIELDS["academic_employment_history.csv"],
        )
        return self._join(identities, employments, active_only=True)

    def find_by_rut(self, rut: str) -> AcademicRecord | None:
        try:
            canonical = canonicalize_rut(normalize_rut(rut))
        except TypeError, AttributeError:
            return None
        return next((row for row in self.list_all() if row.rut == canonical), None)

    def add(self, record: AcademicRecord) -> None:
        self._mutate("add", record)

    def update(self, record: AcademicRecord) -> None:
        self._mutate("update", record)

    def delete(self, academic_id: str) -> None:
        try:
            with CsvUnitOfWork(self.paths) as uow:
                assert uow.public_dir is not None
                path = uow.public_dir / "tables" / "academic_employment_history.csv"
                rows = read_csv(path, TABLE_FIELDS[path.name])
                current = [
                    row
                    for row in rows
                    if row["academic_id"] == academic_id and not row["valid_to"]
                ]
                if len(current) != 1:
                    raise AcademicRepositoryNotFoundError(
                        "El académico no existe de forma única."
                    )
                current[0]["valid_to"] = date.today().isoformat()
                current[0]["status_id"] = "academic-status-terminated-v1"
                _write(path, TABLE_FIELDS[path.name], rows)
                uow.commit()
        except (DataConcurrencyError, DataTransactionError) as error:
            raise AcademicRepositorySchemaError(str(error)) from error

    def replace_all(self, records: list[AcademicRecord]) -> None:
        raise AcademicRepositorySchemaError(
            "La sustitución masiva no está disponible en el modelo normalizado."
        )

    def _mutate(self, operation: str, record: AcademicRecord) -> None:
        normalized = normalize_rut(record.rut)
        if (
            not is_valid_rut(normalized)
            or not record.name.strip()
            or not 1 <= record.weekly_hours <= 40
        ):
            raise AcademicRepositorySchemaError("Los datos académicos son inválidos.")
        rut = canonicalize_rut(normalized)
        try:
            with CsvUnitOfWork(self.paths) as uow:
                assert uow.public_dir is not None
                table_dir = uow.public_dir / "tables"
                identities = read_csv(
                    table_dir / "Academic.csv", TABLE_FIELDS["Academic.csv"]
                )
                employment_path = table_dir / "academic_employment_history.csv"
                employments = read_csv(
                    employment_path, TABLE_FIELDS[employment_path.name]
                )
                duplicate = next(
                    (
                        row
                        for row in identities
                        if row["rut"] == rut
                        and row["academic_id"] != record.academic_id
                    ),
                    None,
                )
                if duplicate:
                    raise AcademicRepositorySchemaError(
                        "El RUT académico pertenece a otro registro."
                    )
                now = datetime.now().astimezone().isoformat(timespec="seconds")
                if operation == "add":
                    if any(
                        row["academic_id"] == record.academic_id for row in identities
                    ):
                        raise AcademicRepositorySchemaError(
                            "El identificador académico ya existe."
                        )
                    identities.append(
                        {
                            "academic_id": record.academic_id,
                            "rut": rut,
                            "name": record.name.strip(),
                            "created_at": now,
                            "updated_at": now,
                            "row_version": 1,
                        }
                    )
                else:
                    identity = next(
                        (
                            row
                            for row in identities
                            if row["academic_id"] == record.academic_id
                        ),
                        None,
                    )
                    if identity is None:
                        raise AcademicRepositoryNotFoundError("El académico no existe.")
                    if record.row_version != int(identity["row_version"]):
                        raise AcademicRepositorySchemaError(
                            "El académico fue actualizado por otra instancia."
                        )
                    identity.update(
                        rut=rut,
                        name=record.name.strip(),
                        updated_at=now,
                        row_version=str(int(identity["row_version"]) + 1),
                    )
                profile_id, status_id = self._catalog_ids(
                    uow.public_dir, record.profile, record.status
                )
                existing_employment = next(
                    (
                        row
                        for row in employments
                        if row["academic_id"] == record.academic_id
                        and not row["valid_to"]
                    ),
                    None,
                )
                if (
                    operation == "update"
                    and existing_employment is not None
                    and existing_employment["valid_from"] == date.today().isoformat()
                ):
                    existing_employment.update(
                        profile_id=profile_id,
                        status_id=status_id,
                        weekly_hours=str(record.weekly_hours),
                        recorded_at=now,
                        recorded_by_actor_id="local-session",
                    )
                else:
                    if existing_employment is not None:
                        existing_employment["valid_to"] = (
                            date.today() - timedelta(days=1)
                        ).isoformat()
                    employments.append(
                        {
                            "employment_id": f"employment-{uuid4()}",
                            "academic_id": record.academic_id,
                            "profile_id": profile_id,
                            "status_id": status_id,
                            "weekly_hours": record.weekly_hours,
                            "valid_from": date.today().isoformat(),
                            "valid_to": "",
                            "recorded_at": now,
                            "recorded_by_actor_id": "local-session",
                        }
                    )
                _write(
                    table_dir / "Academic.csv", TABLE_FIELDS["Academic.csv"], identities
                )
                _write(employment_path, TABLE_FIELDS[employment_path.name], employments)
                uow.commit()
        except (DataConcurrencyError, DataTransactionError) as error:
            raise AcademicRepositorySchemaError(str(error)) from error

    def _join(
        self,
        identities: list[dict[str, str]],
        employments: list[dict[str, str]],
        *,
        active_only: bool,
    ) -> list[AcademicRecord]:
        profiles, statuses, plants = self._catalog_maps(self.paths.public_data_dir)
        current = {
            row["academic_id"]: row for row in employments if not row["valid_to"]
        }
        result = []
        for identity in identities:
            employment = current.get(identity["academic_id"])
            if employment is None:
                continue
            status = statuses[employment["status_id"]]
            if active_only and status != "Activo":
                continue
            profile_key, staff_id = profiles[employment["profile_id"]]
            result.append(
                AcademicRecord(
                    identity["academic_id"],
                    identity["rut"],
                    identity["name"],
                    plants[staff_id],
                    profile_key,
                    int(employment["weekly_hours"]),
                    status,
                    int(identity["row_version"]),
                )
            )
        return result

    @staticmethod
    def _catalog_maps(
        public: Path,
    ) -> tuple[dict[str, tuple[str, str]], dict[str, str], dict[str, str]]:
        catalog = public / "catalogs"
        profiles = {
            row["profile_id"]: (row["key"], row["staff_id"])
            for row in read_csv(
                catalog / "academic_profiles.csv",
                (
                    "profile_id",
                    "staff_id",
                    "key",
                    "name",
                    "teaching_percentage",
                    "management_percentage",
                    "research_percentage",
                    "allows_extra_courses",
                    "active",
                ),
            )
        }
        statuses = {
            row["status_id"]: row["name"]
            for row in read_csv(
                catalog / "academic_statuses.csv",
                ("status_id", "status_code", "name", "active"),
            )
        }
        plants = {
            row["staff_id"]: row["key"]
            for row in read_csv(
                catalog / "academic_staff.csv", ("staff_id", "key", "name", "active")
            )
        }
        return profiles, statuses, plants

    @staticmethod
    def _catalog_ids(
        public: Path, profile_key: str, status_name: str
    ) -> tuple[str, str]:
        profiles, statuses, _ = NormalizedAcademicRepository._catalog_maps(public)
        profile_id = next(
            (key for key, value in profiles.items() if value[0] == profile_key), None
        )
        status_id = next(
            (key for key, value in statuses.items() if value == status_name), None
        )
        if profile_id is None or status_id is None:
            raise AcademicRepositorySchemaError("Perfil o estado inexistente.")
        return profile_id, status_id
