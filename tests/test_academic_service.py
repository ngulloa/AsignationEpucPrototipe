"""Unit tests for the academic registration and listing use cases."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from backend.academic_repository import AcademicRepositoryIOError
from backend.academic_service import (
    DUPLICATE_RUT_MESSAGE,
    INVALID_RUT_MESSAGE,
    LISTING_ERROR_MESSAGE,
    PERSISTENCE_ERROR_MESSAGE,
    SUCCESS_MESSAGE,
    AcademicService,
)
from backend.contracts import (
    AcademicFormData,
    AcademicListingError,
    AcademicRecord,
)


class MemoryAcademicRepository:
    def __init__(
        self,
        records: list[AcademicRecord] | None = None,
        *,
        fail_on: str | None = None,
    ) -> None:
        self.records = list(records or [])
        self.fail_on = fail_on
        self.find_calls: list[str] = []
        self.add_calls: list[AcademicRecord] = []
        self.list_calls = 0

    def list_all(self) -> list[AcademicRecord]:
        self.list_calls += 1
        if self.fail_on == "list":
            raise AcademicRepositoryIOError("detalle técnico de lectura")
        return list(self.records)

    def find_by_rut(self, rut: str) -> AcademicRecord | None:
        self.find_calls.append(rut)
        if self.fail_on == "find":
            raise AcademicRepositoryIOError("detalle técnico de búsqueda")
        return next((record for record in self.records if record.rut == rut), None)

    def add(self, record: AcademicRecord) -> None:
        self.add_calls.append(record)
        if self.fail_on == "add":
            raise AcademicRepositoryIOError("detalle técnico de escritura")
        self.records.append(record)


@pytest.fixture
def valid_form() -> AcademicFormData:
    return AcademicFormData(
        name="Persona de prueba",
        rut=" 12.345.678 - 5 ",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=40,
        status="Activo",
    )


def _record(
    *,
    academic_id: str = "existing-id",
    rut: str = "12345678-5",
) -> AcademicRecord:
    return AcademicRecord(
        academic_id=academic_id,
        rut=rut,
        name="Registro sintético",
        plant="Mixta",
        profile="Docente",
        weekly_hours=20,
        status="Sabático",
    )


def test_invalid_rut_does_not_access_repository(
    valid_form: AcademicFormData,
) -> None:
    repository = MemoryAcademicRepository()
    service = AcademicService(repository)

    result = service.register_academic(replace(valid_form, rut="12.345.678-4"))

    assert result.success is False
    assert result.message == INVALID_RUT_MESSAGE
    assert result.field_errors == {"rut": INVALID_RUT_MESSAGE}
    assert repository.find_calls == []
    assert repository.add_calls == []


def test_valid_rut_persists_exactly_once(valid_form: AcademicFormData) -> None:
    repository = MemoryAcademicRepository()
    service = AcademicService(repository, id_generator=lambda: "fixed-id")

    result = service.register_academic(valid_form)

    assert result.success is True
    assert result.message == SUCCESS_MESSAGE
    assert len(repository.add_calls) == 1
    assert repository.records == repository.add_calls


def test_default_identifier_is_textual_uuid4(valid_form: AcademicFormData) -> None:
    repository = MemoryAcademicRepository()

    AcademicService(repository).register_academic(valid_form)

    identifier = repository.records[0].academic_id
    parsed = UUID(identifier)
    assert parsed.version == 4
    assert str(parsed) == identifier


def test_identifier_generator_is_injectable(valid_form: AcademicFormData) -> None:
    repository = MemoryAcademicRepository()

    AcademicService(
        repository,
        id_generator=lambda: "deterministic-id",
    ).register_academic(valid_form)

    assert repository.records[0].academic_id == "deterministic-id"


def test_stored_rut_is_canonical_and_form_is_immutable(
    valid_form: AcademicFormData,
) -> None:
    repository = MemoryAcademicRepository()
    original = valid_form

    AcademicService(repository).register_academic(valid_form)

    assert repository.records[0].rut == "12345678-5"
    assert valid_form is original
    assert valid_form.rut == " 12.345.678 - 5 "


def test_exact_duplicate_is_rejected(valid_form: AcademicFormData) -> None:
    repository = MemoryAcademicRepository([_record()])

    result = AcademicService(repository).register_academic(
        replace(valid_form, rut="12345678-5")
    )

    assert result.success is False
    assert result.message == DUPLICATE_RUT_MESSAGE
    assert result.field_errors == {"rut": DUPLICATE_RUT_MESSAGE}


def test_duplicate_with_dots_spaces_and_lowercase_k_is_rejected(
    valid_form: AcademicFormData,
) -> None:
    repository = MemoryAcademicRepository([_record(rut="40000000-K")])

    result = AcademicService(repository).register_academic(
        replace(valid_form, rut=" 40.000.000-k ")
    )

    assert result.success is False
    assert repository.find_calls == ["40000000-K"]


def test_duplicate_never_calls_add(valid_form: AcademicFormData) -> None:
    repository = MemoryAcademicRepository([_record()])

    AcademicService(repository).register_academic(valid_form)

    assert repository.add_calls == []
    assert repository.records == [_record()]


def test_repository_error_returns_controlled_failure_and_logs_technical_detail(
    valid_form: AcademicFormData,
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = MemoryAcademicRepository(fail_on="add")

    result = AcademicService(repository).register_academic(valid_form)

    assert result.success is False
    assert result.message == PERSISTENCE_ERROR_MESSAGE
    assert result.field_errors == {}
    assert repository.records == []
    assert "detalle técnico de escritura" in caplog.text


def test_listing_returns_persisted_order() -> None:
    records = [_record(academic_id="first"), _record(academic_id="second")]
    repository = MemoryAcademicRepository(records)

    result = AcademicService(repository).list_academics()

    assert result == records
    assert result is not repository.records


def test_listing_error_keeps_technical_cause(
    caplog: pytest.LogCaptureFixture,
) -> None:
    repository = MemoryAcademicRepository(fail_on="list")

    with pytest.raises(AcademicListingError, match=LISTING_ERROR_MESSAGE) as captured:
        AcademicService(repository).list_academics()

    assert isinstance(captured.value.__cause__, AcademicRepositoryIOError)
    assert "detalle técnico de lectura" in caplog.text


def test_no_academic_rules_beyond_rut_are_validated() -> None:
    repository = MemoryAcademicRepository()
    form = AcademicFormData(
        name="",
        rut="12.345.678-5",
        plant="",
        profile="",
        weekly_hours=-999,
        status="",
    )

    result = AcademicService(repository).register_academic(form)

    assert result.success is True
    assert repository.records[0].name == ""
    assert repository.records[0].weekly_hours == -999
