"""Strict-schema and atomicity tests for the monolithic academic register."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from backend.academic_repository import (
    AcademicRepositoryIOError,
    AcademicRepositorySchemaError,
)
from backend.academic_service import PERSISTENCE_ERROR_MESSAGE, AcademicService
from backend.contracts import AcademicFormData, AcademicRecord
from persistence.csv_academic_repository import CsvAcademicRepository

EXACT_HEADER = "academic_id,rut,name,plant,profile,weekly_hours,status\n"


def _record(
    academic_id: str = "synthetic-academic-1",
    *,
    rut: str = "12345678-5",
    name: str = "Persona sintética",
    plant: str = "Ordinaria",
    profile: str = "Mixto",
    weekly_hours: int = 40,
    status: str = "Activo",
) -> AcademicRecord:
    return AcademicRecord(
        academic_id=academic_id,
        rut=rut,
        name=name,
        plant=plant,
        profile=profile,
        weekly_hours=weekly_hours,
        status=status,
    )


def _temporary_files(directory: Path) -> list[Path]:
    return list(directory.glob("*.tmp")) + list(directory.glob(".*.tmp"))


def _write_row(path: Path, values: tuple[str, ...]) -> None:
    path.write_text(EXACT_HEADER + ",".join(values) + "\n", encoding="utf-8")


def test_missing_file_and_parent_create_only_exact_header(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "Academic.csv"
    repository = CsvAcademicRepository(path)

    assert repository.list_all() == []
    assert path.read_bytes() == EXACT_HEADER.encode("utf-8")
    assert [
        item.relative_to(tmp_path) for item in tmp_path.rglob("*") if item.is_file()
    ] == [Path("nested/Academic.csv")]


def test_header_only_file_reads_as_empty_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(EXACT_HEADER, encoding="utf-8")
    before = path.read_bytes()

    assert CsvAcademicRepository(path).list_all() == []
    assert path.read_bytes() == before


def test_write_round_trip_keeps_empty_name_negative_hours_utf8_and_lf(
    tmp_path: Path,
) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")
    expected = _record(name="", weekly_hours=-15)

    repository.add(expected)

    assert repository.list_all() == [expected]
    persisted = repository.path.read_bytes()
    assert b"\r\n" not in persisted
    assert persisted.startswith(EXACT_HEADER.encode("utf-8"))


def test_multiple_records_preserve_insertion_order(tmp_path: Path) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")
    records = [
        _record(),
        _record("synthetic-academic-2", rut="40000000-K"),
        _record("synthetic-academic-3", rut="11000003-0"),
    ]

    repository.replace_all(records)

    assert repository.list_all() == records


@pytest.mark.parametrize(
    "header",
    (
        "",
        "rut,academic_id,name,plant,profile,weekly_hours,status\n",
        "academic_id,rut,name,plant,profile,weekly_hours\n",
        "academic_id,rut,name,plant,profile,weekly_hours,status,extra\n",
    ),
)
def test_header_must_be_exact_and_ordered(tmp_path: Path, header: str) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(header, encoding="utf-8")

    with pytest.raises(AcademicRepositorySchemaError, match="cabecera"):
        CsvAcademicRepository(path).list_all()


def test_additional_row_columns_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    _write_row(
        path,
        (
            "synthetic-academic-1",
            "12345678-5",
            "Persona sintética",
            "Ordinaria",
            "Mixto",
            "40",
            "Activo",
            "extra",
        ),
    )

    with pytest.raises(AcademicRepositorySchemaError, match="inesperadas"):
        CsvAcademicRepository(path).list_all()


def test_incomplete_row_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    _write_row(
        path,
        (
            "synthetic-academic-1",
            "12345678-5",
            "Persona sintética",
            "Ordinaria",
            "Mixto",
        ),
    )

    with pytest.raises(AcademicRepositorySchemaError, match="incompleta"):
        CsvAcademicRepository(path).list_all()


def test_blank_row_is_rejected_as_incomplete(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(EXACT_HEADER + "\n", encoding="utf-8")

    with pytest.raises(AcademicRepositorySchemaError, match="incompleta"):
        CsvAcademicRepository(path).list_all()


@pytest.mark.parametrize(
    "values",
    (
        ("", "12345678-5", "", "Ordinaria", "Mixto", "40", "Activo"),
        (
            "synthetic-academic-1",
            "12345678-4",
            "",
            "Ordinaria",
            "Mixto",
            "40",
            "Activo",
        ),
        (
            "synthetic-academic-1",
            "12345678-5",
            "",
            "Desconocida",
            "Mixto",
            "40",
            "Activo",
        ),
        (
            "synthetic-academic-1",
            "12345678-5",
            "",
            "Ordinaria",
            "Mixto",
            "no-entero",
            "Activo",
        ),
        (
            "synthetic-academic-1",
            "12345678-5",
            "",
            "Ordinaria",
            "Mixto",
            "40",
            "Desconocido",
        ),
    ),
)
def test_invalid_rows_are_rejected(tmp_path: Path, values: tuple[str, ...]) -> None:
    path = tmp_path / "Academic.csv"
    _write_row(path, values)

    with pytest.raises(AcademicRepositorySchemaError, match="inválido|entero"):
        CsvAcademicRepository(path).list_all()


def test_duplicate_ids_and_canonical_ruts_are_rejected(tmp_path: Path) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")
    repository.add(_record())
    before = repository.path.read_bytes()

    with pytest.raises(AcademicRepositorySchemaError, match="identificador"):
        repository.add(_record(rut="40000000-K"))
    assert repository.path.read_bytes() == before

    with pytest.raises(AcademicRepositorySchemaError, match="RUT"):
        repository.add(
            _record(
                "synthetic-academic-2",
                rut=" 12.345.678 - 5 ",
            )
        )
    assert repository.path.read_bytes() == before


def test_persisted_duplicate_canonical_rut_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(
        EXACT_HEADER
        + "synthetic-1,12345678-5,Uno,Ordinaria,Mixto,40,Activo\n"
        + "synthetic-2,12.345.678-5,Dos,Especial,Docente,20,Activo\n",
        encoding="utf-8",
    )

    with pytest.raises(AcademicRepositorySchemaError, match="RUT duplicados"):
        CsvAcademicRepository(path).list_all()


def test_persisted_duplicate_academic_id_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_text(
        EXACT_HEADER
        + "synthetic-1,12345678-5,Uno,Ordinaria,Mixto,40,Activo\n"
        + "synthetic-1,40000000-K,Dos,Especial,Docente,20,Activo\n",
        encoding="utf-8",
    )

    with pytest.raises(AcademicRepositorySchemaError, match="identificadores"):
        CsvAcademicRepository(path).list_all()


def test_find_by_rut_canonicalizes_formatting_and_lowercase_k(
    tmp_path: Path,
) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")
    expected = _record(rut="40000000-K")
    repository.add(expected)

    assert repository.find_by_rut(" 40.000.000-k ") == expected
    assert repository.find_by_rut("sin-estructura") is None


def test_historical_aliases_are_normalized_on_read_without_mutation(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Academic.csv"
    _write_row(
        path,
        (
            "synthetic-historical",
            "12345678-5",
            "Persona sintética",
            "Mixta",
            "Estandar",
            "20",
            "Sabatico",
        ),
    )
    before = path.read_bytes()

    loaded = CsvAcademicRepository(path).list_all()[0]

    assert (loaded.plant, loaded.profile, loaded.status) == (
        "Especial",
        "Standard",
        "Sabático",
    )
    assert path.read_bytes() == before


def test_historical_incompatible_combination_is_readable_and_correctable(
    tmp_path: Path,
) -> None:
    path = tmp_path / "Academic.csv"
    _write_row(
        path,
        (
            "synthetic-historical",
            "12345678-5",
            "Persona sintética",
            "Ordinaria",
            "Docente",
            "20",
            "Activo",
        ),
    )
    before = path.read_bytes()
    repository = CsvAcademicRepository(path)

    loaded = repository.list_all()[0]
    assert (loaded.plant, loaded.profile) == ("Ordinaria", "Docente")
    assert path.read_bytes() == before

    corrected = replace(loaded, profile="Mixto")
    repository.update(corrected)
    assert repository.list_all() == [corrected]


def test_edit_preserves_identifier_and_cannot_take_another_rut(
    tmp_path: Path,
) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")
    first = _record()
    second = _record("synthetic-academic-2", rut="40000000-K")
    repository.replace_all([first, second])

    edited = replace(first, name="Edición sintética", weekly_hours=-8)
    repository.update(edited)
    assert repository.list_all()[0] == edited
    assert repository.list_all()[0].academic_id == first.academic_id

    before = repository.path.read_bytes()
    with pytest.raises(AcademicRepositorySchemaError, match="otro registro"):
        repository.update(replace(edited, rut=second.rut))
    assert repository.path.read_bytes() == before


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
        repository.add(_record("synthetic-academic-2", rut="40000000-K"))

    assert path.read_bytes() == original
    assert repository.list_all() == [_record()]
    assert _temporary_files(tmp_path) == []


def test_failed_first_add_does_not_leave_a_partial_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "Academic.csv"
    repository = CsvAcademicRepository(path)

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("fallo de reemplazo controlado")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(AcademicRepositoryIOError, match="atómica"):
        repository.add(_record())

    assert not path.exists()
    assert _temporary_files(tmp_path) == []


def test_failed_update_of_missing_record_creates_nothing(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    repository = CsvAcademicRepository(path)

    with pytest.raises(AcademicRepositorySchemaError, match="no existe"):
        repository.update(_record())

    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_validation_failure_causes_no_partial_modification(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    repository = CsvAcademicRepository(path)
    repository.add(_record())
    original = path.read_bytes()

    with pytest.raises(AcademicRepositorySchemaError):
        repository.replace_all(
            [_record(), _record("synthetic-academic-2", rut="12345678-5")]
        )

    assert path.read_bytes() == original
    assert _temporary_files(tmp_path) == []


def test_duplicate_overwrite_failure_keeps_previous_record(
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


def test_success_creates_no_sidecars_indices_or_other_files(tmp_path: Path) -> None:
    repository = CsvAcademicRepository(tmp_path / "Academic.csv")

    repository.add(_record())
    repository.update(replace(_record(), name="Edición sintética"))

    assert [path.name for path in tmp_path.iterdir()] == ["Academic.csv"]


def test_invalid_utf8_is_reported_without_mutation(tmp_path: Path) -> None:
    path = tmp_path / "Academic.csv"
    path.write_bytes(b"\xff")
    before = path.read_bytes()

    with pytest.raises(AcademicRepositoryIOError, match="leer"):
        CsvAcademicRepository(path).list_all()

    assert path.read_bytes() == before
