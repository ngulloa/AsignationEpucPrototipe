"""Administrative migration checks without exposing row content."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from persistence.csv_academic_repository import (
    ACADEMIC_CSV_FIELDS,
    CsvAcademicRepository,
    deterministic_legacy_appointment_id,
)
from persistence.paths import ProjectPaths
from scripts.migrate_academic_datasets import migrate_academic_datasets


def _v1(path: Path, *, profile: str = "Mixto") -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        ",".join(ACADEMIC_CSV_FIELDS)
        + "\nacademic-legacy,12345678-5,Persona Sintética,Ordinaria,"
        + profile
        + ",40,Activo\n"
    ).encode()
    path.write_bytes(content)
    return content


def _public_index(paths: ProjectPaths, filename: str) -> None:
    paths.tables_index_path.parent.mkdir(parents=True, exist_ok=True)
    paths.tables_index_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "tables": [
                    {
                        "number": 1,
                        "username": "synthetic-user",
                        "name": "Tabla sintética",
                        "filename": filename,
                        "updated_at": "2026-01-01T00:00:00+00:00",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )


def test_dry_run_prevalidates_private_and_public_without_writes(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    private = paths.personal_academics_path("synthetic-user")
    public = paths.shared_table_path("table-000001-synthetic-user.csv")
    private_before = _v1(private)
    public_before = _v1(public)
    _public_index(paths, public.name)

    report = migrate_academic_datasets(paths)

    assert (report.discovered, report.migratable, report.migrated) == (2, 2, 0)
    assert private.read_bytes() == private_before
    assert public.read_bytes() == public_before
    assert not paths.personal_academic_appointments_path("synthetic-user").exists()
    assert not paths.academic_appointments_path(public).exists()


def test_apply_backs_up_verifies_and_is_idempotent(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    academic_path = paths.personal_academics_path("synthetic-user")
    original = _v1(academic_path)
    backup = tmp_path / "private-backup"

    first = migrate_academic_datasets(paths, apply=True, backup_dir=backup)
    second = migrate_academic_datasets(paths, apply=True, backup_dir=backup)
    repository = CsvAcademicRepository(
        academic_path,
        appointments_path=paths.personal_academic_appointments_path("synthetic-user"),
    )

    assert first.migrated == 1
    assert second.migrated == 0
    assert repository.dataset_version() == 2
    aggregate = repository.list_aggregates()[0]
    assert aggregate.academic.email is None
    assert aggregate.appointments[0].appointment_id == (
        deterministic_legacy_appointment_id("academic-legacy")
    )
    backup_file = backup / "private-0001.academics.csv"
    assert backup_file.read_bytes() == original
    assert (
        hashlib.sha256(backup_file.read_bytes()).hexdigest()
        == hashlib.sha256(original).hexdigest()
    )
    assert (backup / "manifest.json").is_file()
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["datasets"]) == 1


def test_incompatible_dataset_is_reported_and_unchanged(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path / "project")
    academic_path = paths.personal_academics_path("synthetic-user")
    original = _v1(academic_path, profile="Perfil desconocido")

    report = migrate_academic_datasets(
        paths,
        apply=True,
        backup_dir=tmp_path / "backup",
    )

    assert report.incompatible == 1
    assert report.migrated == 0
    assert academic_path.read_bytes() == original
    assert not paths.personal_academic_appointments_path("synthetic-user").exists()


def test_legacy_appointment_identifier_is_deterministic() -> None:
    assert deterministic_legacy_appointment_id("academic-legacy") == (
        deterministic_legacy_appointment_id("academic-legacy")
    )
