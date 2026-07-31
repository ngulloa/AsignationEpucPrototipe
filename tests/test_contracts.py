"""Tests for the shared frontend/backend data contracts."""

from dataclasses import FrozenInstanceError

import pytest

from backend.contracts import AcademicFormData, AcademicRecord, SubmissionResult


def test_academic_form_data_construction() -> None:
    data = AcademicFormData(
        name="Ana Cifuentes",
        rut="12345678-9",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )

    assert data.name == "Ana Cifuentes"
    assert data.rut == "12345678-9"
    assert data.plant == "Ordinaria"
    assert data.profile == "Mixto"
    assert data.status == "Activo"


def test_weekly_hours_remains_an_integer() -> None:
    data = AcademicFormData(
        name="Ana Cifuentes",
        rut="12345678-9",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )

    assert isinstance(data.weekly_hours, int)
    assert data.weekly_hours == 40


def test_persistent_academic_record_has_only_sourced_fields() -> None:
    record = AcademicRecord(
        academic_id="academic-test-id",
        rut="12345678-5",
        name="Persona de prueba",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )

    assert record.academic_id == "academic-test-id"
    assert record.rut == "12345678-5"
    assert isinstance(record.weekly_hours, int)
    assert not hasattr(record, "email")
    assert not hasattr(record, "start_date")
    assert not hasattr(record, "end_date")


def test_successful_submission_result_construction() -> None:
    result = SubmissionResult(success=True, message="Operación aceptada.")

    assert result.success is True
    assert result.message == "Operación aceptada."
    assert result.field_errors == {}


def test_submission_result_with_field_errors() -> None:
    result = SubmissionResult(
        success=False,
        message="Revise los campos.",
        field_errors={"name": "El nombre es obligatorio."},
    )

    assert result.success is False
    assert result.field_errors == {"name": "El nombre es obligatorio."}


def test_default_field_error_dictionaries_are_independent() -> None:
    first = SubmissionResult(success=True, message="Primero.")
    second = SubmissionResult(success=True, message="Segundo.")

    first.field_errors["name"] = "Error local."

    assert first.field_errors == {"name": "Error local."}
    assert second.field_errors == {}
    assert first.field_errors is not second.field_errors


def test_contracts_are_structurally_immutable() -> None:
    result = SubmissionResult(success=True, message="Aceptado.")
    record = AcademicRecord(
        academic_id="academic-test-id",
        rut="12345678-5",
        name="Persona de prueba",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )

    with pytest.raises(FrozenInstanceError):
        result.success = False  # type: ignore[misc]
    with pytest.raises(FrozenInstanceError):
        record.rut = "40000000-K"  # type: ignore[misc]
