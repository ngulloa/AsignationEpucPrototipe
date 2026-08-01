"""Tests for exact-schema and atomic CSV academic persistence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from backend.academic_repository import (
    AcademicRepositoryIOError,
    AcademicRepositorySchemaError,
)
from backend.academic_service import PERSISTENCE_ERROR_MESSAGE, AcademicService
from backend.contracts import AcademicFormData, AcademicRecord
from persistence.csv_academic_repository import (
    ACADEMIC_APPOINTMENT_CSV_FIELDS,
    ACADEMIC_CSV_FIELDS,
    ACADEMIC_V2_CSV_FIELDS,
    CsvAcademicRepository,
    deterministic_legacy_appointment_id,
)


def _record(
    academic_id: str = "academic-1",
    *,
    rut: str = "12345678-5",
    name: str = "Persona de prueba",
    weekly_hours: int = 40,
) -> AcademicRecord:
    return AcademicRecord(
        academic_id=academic_id,
        rut=rut,
        name=name,
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=weekly_hours,
        status="Activo",
    )


def _temporary_files(directory: Path) -> list[Path]:
    return list(directory.glob("*.tmp")) + list(directory.glob(".*.tmp"))


def test_missing_file_and_parent_are_created_with_exact_header(
    tmp_path: Path,
) -> None:
    path = tmp_path / "nested" / "Academic.csv"
    repository = CsvAcademicRepository(path)

    assert repository.list_all() == []
    assert path.exists()
    assert path.read_text(encoding="utf-8").splitlines() == [
        ",".join(ACADEMIC_V2_CSV_FIELDS)
    ]
    assert repository.appointments_path.read_text(encoding="utf-8").splitlines() == [
        ",".join(ACADEMIC_APPOINTMENT_CSV_FIELDS)
    ]


def test_header_only_file_reads_as_empty(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(",".join(ACADEMIC_CSV_FIELDS) + "\n", encoding="utf-8")

    assert CsvAcademicRepository(path).list_all() == []


def test_write_then_read_same_record(tmp_path: Path) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")
    expected = _record()

    repository.add(expected)

    assert repository.list_all() == [expected]


def test_multiple_records_preserve_insertion_order(tmp_path: Path) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")
    records = [
        _record("academic-1"),
        _record("academic-2", rut="40000000-K"),
        _record("academic-3", rut="11000003-0"),
    ]

    for record in records:
        repository.add(record)

    assert repository.list_all() == records


def test_weekly_hours_round_trips_as_integer(tmp_path: Path) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")
    repository.add(_record(weekly_hours=-15))

    loaded = repository.list_all()[0]

    assert loaded.weekly_hours == -15
    assert isinstance(loaded.weekly_hours, int)


def test_missing_header_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_bytes(b"")

    with pytest.raises(AcademicRepositorySchemaError, match="cabecera"):
        CsvAcademicRepository(path).list_all()


def test_incorrect_header_or_order_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(
        "rut,academic_id,name,plant,profile,weekly_hours,status\n",
        encoding="utf-8",
    )

    with pytest.raises(AcademicRepositorySchemaError, match="incorrecta"):
        CsvAcademicRepository(path).list_all()


def test_additional_row_columns_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(
        ",".join(ACADEMIC_CSV_FIELDS)
        + "\nacademic-1,12345678-5,Persona,Ordinaria,Mixto,40,Activo,extra\n",
        encoding="utf-8",
    )

    with pytest.raises(AcademicRepositorySchemaError, match="inesperadas"):
        CsvAcademicRepository(path).list_all()


def test_incomplete_row_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(
        ",".join(ACADEMIC_CSV_FIELDS)
        + "\nacademic-1,12345678-5,Persona,Ordinaria,Mixto\n",
        encoding="utf-8",
    )

    with pytest.raises(AcademicRepositorySchemaError, match="incompleta"):
        CsvAcademicRepository(path).list_all()


def test_invalid_integer_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(
        ",".join(ACADEMIC_CSV_FIELDS)
        + "\nacademic-1,12345678-5,Persona,Ordinaria,Mixto,no-entero,Activo\n",
        encoding="utf-8",
    )

    with pytest.raises(AcademicRepositorySchemaError, match="entero"):
        CsvAcademicRepository(path).list_all()


def test_utf8_content_round_trips(tmp_path: Path) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")
    expected = _record(name="Persona Ñandú de prueba")

    repository.add(expected)

    assert repository.list_all() == [expected]
    assert "Ñandú" in repository.path.read_text(encoding="utf-8")


def test_absolute_path_works_after_cwd_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "storage" / "Academic.csv"
    repository = CsvAcademicRepository(path)
    other_directory = tmp_path / "other"
    other_directory.mkdir()
    monkeypatch.chdir(other_directory)

    repository.add(_record())

    assert repository.list_all() == [_record()]
    assert repository.path == path.resolve()


def test_replace_failure_preserves_original_and_removes_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "Academic.csv"
    repository = CsvAcademicRepository(path)
    repository.add(_record())
    original = path.read_bytes()

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("fallo de reemplazo controlado")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(AcademicRepositoryIOError, match="atómica"):
        repository.add(_record("academic-2", rut="40000000-K"))

    assert path.read_bytes() == original
    assert repository.list_all() == [_record()]
    assert _temporary_files(tmp_path) == []


def test_success_leaves_no_temporary_files(tmp_path: Path) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")

    repository.add(_record())

    assert _temporary_files(tmp_path) == []


def test_duplicate_overwrite_failure_preserves_the_previous_csv_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "Academic.csv"
    repository = CsvAcademicRepository(path)
    existing = _record()
    repository.add(existing)
    service = AcademicService(repository)
    form = AcademicFormData(
        name="Datos sintéticos reemplazados",
        rut=" 12.345.678 - 5 ",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=20,
        status="Inactivo",
    )
    warning = service.register_academic(form)
    assert warning.duplicate_confirmation is not None
    original = path.read_bytes()

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("fallo atómico controlado")

    monkeypatch.setattr(os, "replace", fail_replace)
    result = service.register_academic(form, warning.duplicate_confirmation)

    assert result.message == PERSISTENCE_ERROR_MESSAGE
    assert path.read_bytes() == original
    assert repository.list_all() == [existing]
    assert _temporary_files(tmp_path) == []


def test_find_by_rut_canonicalizes_dots_spaces_and_lowercase_k(
    tmp_path: Path,
) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")
    expected = _record(rut="40000000-K")
    repository.add(expected)

    assert repository.find_by_rut(" 40.000.000-k ") == expected
    assert repository.find_by_rut("sin-estructura") is None


def test_recognizable_legacy_catalog_values_are_normalized_only_on_read(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(
        ",".join(ACADEMIC_CSV_FIELDS)
        + "\nlegacy-1,12345678-5,Persona sintética,Mixta,Estandar,20,Sabatico\n",
        encoding="utf-8",
    )
    original = path.read_bytes()

    loaded = CsvAcademicRepository(path).list_all()[0]

    assert (loaded.plant, loaded.profile, loaded.status) == (
        "Especial",
        "Standard",
        "Sabático",
    )
    assert path.read_bytes() == original


def test_historical_incompatible_combination_remains_readable_and_unchanged(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(
        ",".join(ACADEMIC_CSV_FIELDS)
        + "\nlegacy-2,12345678-5,Persona sintética,Ordinaria,Docente,20,Activo\n",
        encoding="utf-8",
    )
    original = path.read_bytes()

    loaded = CsvAcademicRepository(path).list_all()[0]

    assert (loaded.plant, loaded.profile) == ("Ordinaria", "Docente")
    assert path.read_bytes() == original


def test_historical_incompatible_row_can_be_corrected_before_v2_write(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(
        ",".join(ACADEMIC_CSV_FIELDS)
        + "\nlegacy-2,12345678-5,Persona sintética,Ordinaria,Docente,20,Activo\n",
        encoding="utf-8",
    )
    repository = CsvAcademicRepository(path)
    corrected = _record("legacy-2")

    repository.update(corrected)

    assert repository.dataset_version() == 2
    assert repository.list_all() == [corrected]
    assert repository.list_aggregates()[0].appointments[0].appointment_id == (
        deterministic_legacy_appointment_id("legacy-2")
    )


def test_invalid_utf8_is_reported_as_repository_error(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_bytes(b"\xff")

    with pytest.raises(AcademicRepositoryIOError, match="leer"):
        CsvAcademicRepository(path).list_all()
