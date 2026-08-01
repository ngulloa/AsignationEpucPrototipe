"""Domain, projection and v2 persistence checks for the academic aggregate."""

from __future__ import annotations

import csv
import os
from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from backend.academic_catalog import get_academic_catalogs, load_academic_catalogs
from backend.academic_repository import (
    AcademicRepositoryIOError,
    AcademicRepositorySchemaError,
)
from backend.contracts import (
    Academic,
    AcademicAggregate,
    AcademicAppointment,
    AcademicProfile,
    AcademicRecord,
    AcademicStaff,
    AmbiguousAcademicAppointmentsError,
)
from persistence.csv_academic_repository import CsvAcademicRepository
from persistence.paths import DEFAULT_PATHS


def _academic() -> Academic:
    return Academic("academic-v2", "12.345.678-5", "Persona Sintética", None, "Activo")


def _appointment(
    appointment_id: str = "appointment-current",
    *,
    profile_id: str = "academic-profile-ordinary-mixed-v1",
    start_date: date | None = None,
    end_date: date | None = None,
) -> AcademicAppointment:
    return AcademicAppointment(
        appointment_id,
        "academic-v2",
        profile_id,
        40,
        start_date,
        end_date,
    )


def _record() -> AcademicRecord:
    return AcademicRecord(
        "academic-v2",
        "12345678-5",
        "Persona Sintética",
        "Ordinaria",
        "Mixto",
        40,
        "Activo",
    )


def test_four_domain_entities_are_immutable_and_validate_dates() -> None:
    academic = _academic()
    staff = AcademicStaff("staff-test", "Planta de prueba")
    profile = AcademicProfile(
        "profile-test",
        staff.staff_id,
        "Perfil de prueba",
        Decimal("50"),
        Decimal("10"),
        Decimal("40"),
        True,
    )
    appointment = _appointment()

    with pytest.raises(FrozenInstanceError):
        academic.name = "Otro"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        staff.name = "Otra"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        profile.name = "Otro"  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        appointment.weekly_hours = 20  # type: ignore[misc]
    with pytest.raises(ValueError, match="término"):
        _appointment(start_date=date(2026, 2, 2), end_date=date(2026, 2, 1))


def test_profile_percentages_reject_float_range_and_non_100_sum() -> None:
    with pytest.raises(TypeError, match="float"):
        AcademicProfile("p", "s", "Perfil", 50.0, 10, 40, True)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="sumar 100"):
        AcademicProfile("p", "s", "Perfil", Decimal(50), Decimal(10), Decimal(39), True)
    with pytest.raises(ValueError, match="entre 0 y 100"):
        AcademicProfile(
            "p", "s", "Perfil", Decimal(110), Decimal(-10), Decimal(0), True
        )


def test_initial_catalog_ids_labels_percentages_and_ownership() -> None:
    catalogs = get_academic_catalogs()

    assert [(item.staff_id, item.name) for item in catalogs.staff] == [
        ("academic-staff-ordinary-v1", "Planta Ordinaria"),
        ("academic-staff-special-v1", "Planta Especial"),
    ]
    assert {item.profile_id for item in catalogs.profile_entities} == {
        "academic-profile-ordinary-research-v1",
        "academic-profile-ordinary-mixed-v1",
        "academic-profile-special-standard-v1",
        "academic-profile-special-teaching-v1",
        "academic-profile-special-management-v1",
    }
    for profile in catalogs.profile_entities:
        assert profile.staff_id in {item.staff_id for item in catalogs.staff}
        assert (
            profile.teaching_percentage
            + profile.management_percentage
            + profile.research_percentage
            == Decimal(100)
        )
    researcher = catalogs.profile_by_id("academic-profile-ordinary-research-v1")
    assert researcher is not None
    assert researcher.allows_extra_courses is False
    assert all(
        item.allows_extra_courses
        for item in catalogs.profile_entities
        if item.profile_id != researcher.profile_id
    )


def test_inactive_profile_is_readable_but_not_selectable(tmp_path: Path) -> None:
    staff_path = tmp_path / "staff.csv"
    profile_path = tmp_path / "profiles.csv"
    staff_path.write_bytes(DEFAULT_PATHS.academic_staff_catalog_path.read_bytes())
    rows = list(
        csv.DictReader(
            DEFAULT_PATHS.academic_profiles_catalog_path.read_text(
                encoding="utf-8"
            ).splitlines()
        )
    )
    rows[0]["active"] = "false"
    with profile_path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    catalogs = load_academic_catalogs(staff_path, profile_path)

    assert catalogs.strict_profile_key("Investigador") is None
    assert catalogs.read_profile_key("Investigador") == "Investigador"
    assert catalogs.profile_by_id("academic-profile-ordinary-research-v1") is not None

    repository = CsvAcademicRepository(tmp_path / "academics.csv", catalogs=catalogs)
    inactive = AcademicAggregate(
        _academic(),
        (_appointment(profile_id="academic-profile-ordinary-research-v1"),),
    )
    repository.replace_aggregates([inactive])
    assert repository.list_all()[0].profile == "Investigador"
    with pytest.raises(AcademicRepositorySchemaError, match="inactivo"):
        repository.update(replace(_record(), profile="Investigador"))


def test_projection_supports_history_and_rejects_current_ambiguity() -> None:
    catalogs = get_academic_catalogs()
    yesterday = date.today() - timedelta(days=1)
    history = _appointment("appointment-old", end_date=yesterday)
    current = _appointment("appointment-current", start_date=date.today())
    aggregate = AcademicAggregate(_academic(), (history, current))

    projected = catalogs.project(aggregate)

    assert projected == _record()
    ambiguous = AcademicAggregate(
        _academic(), (_appointment("one"), _appointment("two"))
    )
    with pytest.raises(AmbiguousAcademicAppointmentsError):
        ambiguous.current_appointment()


def test_v2_round_trip_keeps_empty_email_history_and_stable_appointment_id(
    tmp_path: Path,
) -> None:
    repository = CsvAcademicRepository(tmp_path / "academics.csv")
    old = _appointment("appointment-old", end_date=date.today() - timedelta(days=1))
    current = _appointment("appointment-stable", start_date=date.today())
    repository.replace_aggregates([AcademicAggregate(_academic(), (old, current))])

    repository.update(replace(_record(), weekly_hours=22))
    loaded = repository.list_aggregates()[0]

    assert loaded.academic.email is None
    assert [item.appointment_id for item in loaded.appointments] == [
        "appointment-old",
        "appointment-stable",
    ]
    assert loaded.current_appointment() is not None
    assert loaded.current_appointment().weekly_hours == 22  # type: ignore[union-attr]
    assert "plant" not in repository.path.read_text(encoding="utf-8").splitlines()[0]
    assert repository.appointments_path.exists()


def test_new_appointment_identifier_is_uuid4(tmp_path: Path) -> None:
    repository = CsvAcademicRepository(tmp_path / "academics.csv")
    repository.add(_record())

    identifier = repository.list_aggregates()[0].appointments[0].appointment_id

    assert UUID(identifier).version == 4


def test_duplicate_overwrite_keeps_current_appointment_identity(tmp_path: Path) -> None:
    from backend.academic_service import AcademicService
    from backend.contracts import AcademicFormData

    repository = CsvAcademicRepository(
        tmp_path / "academics.csv",
        appointment_id_generator=lambda: "appointment-preserved",
    )
    repository.add(_record())
    service = AcademicService(repository)
    form = AcademicFormData(
        name="Persona Sintética Editada",
        rut="12.345.678-5",
        plant="Especial",
        profile="Docente",
        weekly_hours=22,
        status="Inactivo",
    )

    warning = service.register_academic(form)
    assert warning.duplicate_confirmation is not None
    assert service.register_academic(form, warning.duplicate_confirmation).success

    loaded = repository.list_aggregates()[0]
    assert loaded.academic.academic_id == "academic-v2"
    assert loaded.appointments[0].appointment_id == "appointment-preserved"
    assert loaded.appointments[0].profile_id == ("academic-profile-special-teaching-v1")


def test_missing_profile_reference_is_rejected(tmp_path: Path) -> None:
    repository = CsvAcademicRepository(tmp_path / "academics.csv")
    aggregate = AcademicAggregate(
        _academic(), (_appointment(profile_id="profile-does-not-exist"),)
    )

    with pytest.raises(AcademicRepositorySchemaError, match="perfil inexistente"):
        repository.replace_aggregates([aggregate])


def test_second_file_replace_failure_rolls_back_both_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = CsvAcademicRepository(tmp_path / "academics.csv")
    repository.add(_record())
    academic_before = repository.path.read_bytes()
    appointments_before = repository.appointments_path.read_bytes()
    real_replace = os.replace
    failed = False

    def fail_second(source: object, destination: object) -> None:
        nonlocal failed
        if Path(destination) == repository.appointments_path and not failed:
            failed = True
            raise OSError("fallo sintético del segundo reemplazo")
        real_replace(source, destination)

    monkeypatch.setattr(os, "replace", fail_second)

    with pytest.raises(AcademicRepositoryIOError, match="atómica"):
        repository.update(replace(_record(), weekly_hours=12))

    assert repository.path.read_bytes() == academic_before
    assert repository.appointments_path.read_bytes() == appointments_before
