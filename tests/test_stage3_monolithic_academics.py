"""End-to-end boundaries for the stage-three global academic register."""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

from backend.application_service import AuthenticationRequiredError
from backend.composition import build_application_service
from backend.contracts import AcademicFormData
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import ProjectPaths


def _form(*, name: str, rut: str = "12.345.678-5") -> AcademicFormData:
    return AcademicFormData(
        name=name,
        rut=rut,
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=-4,
        status="Activo",
    )


def test_composition_shares_one_global_register_between_users(tmp_path: Path) -> None:
    paths = ProjectPaths(tmp_path)
    application = build_application_service(paths=paths)

    application.register_user("synthetic.one", "1234")
    assert application.save_academic(_form(name="Registro sintético")).success
    first = application.list_academics()
    application.logout()

    application.register_user("synthetic.two", "5678")
    assert application.list_academics() == first
    assert len(first) == 1
    assert paths.academic_path.is_file()
    assert [path.name for path in paths.public_tables_dir.iterdir()] == ["Academic.csv"]


def test_productive_flow_creates_only_the_authoritative_academic_file(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    application = build_application_service(paths=paths)
    application.register_user("synthetic.user", "1234")

    assert application.save_academic(_form(name="")).success
    stored = application.list_academics()[0]
    assert application.update_academic(
        stored.academic_id,
        _form(name="Edición sintética"),
    ).success

    csv_paths = sorted(path.relative_to(tmp_path) for path in tmp_path.rglob("*.csv"))
    assert csv_paths == [Path("data/public/tables/Academic.csv")]
    assert not tuple(tmp_path.rglob("academic_appointments.csv"))


def test_productive_add_edit_delete_reload_and_authentication_boundaries(
    tmp_path: Path,
) -> None:
    paths = ProjectPaths(tmp_path)
    application = build_application_service(paths=paths)
    application.register_user("synthetic.crud", "1234")
    assert application.save_academic(_form(name="Primero")).success
    assert application.save_academic(_form(name="Segundo", rut="40.000.000-K")).success
    first, second = application.list_academics()
    assert application.update_academic(
        first.academic_id,
        _form(name="Primero editado"),
    ).success

    assert application.delete_academic(second.academic_id).success
    reloaded = CsvAcademicRepository(paths.academic_path).list_all()

    assert [record.academic_id for record in reloaded] == [first.academic_id]
    assert reloaded[0].name == "Primero editado"
    application.logout()
    with pytest.raises(AuthenticationRequiredError):
        application.delete_academic(first.academic_id)
    assert CsvAcademicRepository(paths.academic_path).list_all() == reloaded


def test_csv_repository_contract_has_no_appointments_parameter() -> None:
    parameters = inspect.signature(CsvAcademicRepository).parameters

    assert tuple(parameters) == ("path", "catalogs")
    assert not hasattr(CsvAcademicRepository, "appointments_path")
    assert not hasattr(CsvAcademicRepository, "list_aggregates")
    assert not hasattr(CsvAcademicRepository, "replace_aggregates")


def test_active_composition_references_the_authoritative_academic_path() -> None:
    source = inspect.getsource(build_application_service)

    assert "paths.academic_path" in source
