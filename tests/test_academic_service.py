"""Unit tests for the academic registration and listing use cases."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from backend.academic_repository import (
    AcademicRepositoryIOError,
    AcademicRepositoryNotFoundError,
)
from backend.academic_service import (
    DELETE_NOT_FOUND_MESSAGE,
    DELETE_PERSISTENCE_ERROR_MESSAGE,
    DELETE_SUCCESS_MESSAGE,
    DUPLICATE_RUT_MESSAGE,
    INCOMPATIBLE_PLANT_PROFILE_MESSAGE,
    INVALID_RUT_MESSAGE,
    INVALID_STATUS_MESSAGE,
    LISTING_ERROR_MESSAGE,
    PERSISTENCE_ERROR_MESSAGE,
    SUCCESS_MESSAGE,
    AcademicService,
)
from backend.contracts import (
    AcademicErrorCode,
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
        self.update_calls: list[AcademicRecord] = []
        self.delete_calls: list[str] = []
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

    def update(self, record: AcademicRecord) -> None:
        self.update_calls.append(record)
        if self.fail_on == "update":
            raise AcademicRepositoryIOError("detalle técnico de actualización")
        index = next(
            index
            for index, existing in enumerate(self.records)
            if existing.academic_id == record.academic_id
        )
        self.records[index] = record

    def delete(self, academic_id: str) -> None:
        self.delete_calls.append(academic_id)
        if self.fail_on == "delete":
            raise AcademicRepositoryIOError("detalle técnico de eliminación")
        for index, existing in enumerate(self.records):
            if existing.academic_id == academic_id:
                del self.records[index]
                return
        raise AcademicRepositoryNotFoundError("registro inexistente")


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
        plant="Especial",
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


def test_duplicate_confirmation_preserves_existing_identifier(
    valid_form: AcademicFormData,
) -> None:
    existing = _record()
    repository = MemoryAcademicRepository([existing])
    service = AcademicService(repository, id_generator=lambda: "must-not-be-used")

    warning = service.register_academic(valid_form)
    result = service.register_academic(valid_form, warning.duplicate_confirmation)

    assert warning.error_code is AcademicErrorCode.DUPLICATE_RUT
    assert warning.duplicate_confirmation is not None
    assert result.success is True
    assert repository.add_calls == []
    assert [record.academic_id for record in repository.records] == [
        existing.academic_id
    ]
    assert repository.update_calls[0].academic_id == existing.academic_id


def test_duplicate_warning_without_confirmation_performs_no_write(
    valid_form: AcademicFormData,
) -> None:
    existing = _record()
    repository = MemoryAcademicRepository([existing])

    result = AcademicService(repository).register_academic(valid_form)

    assert result.success is False
    assert result.message == DUPLICATE_RUT_MESSAGE
    assert repository.add_calls == []
    assert repository.update_calls == []
    assert repository.records == [existing]


def test_changed_duplicate_makes_confirmation_stale(
    valid_form: AcademicFormData,
) -> None:
    existing = _record()
    repository = MemoryAcademicRepository([existing])
    service = AcademicService(repository)
    warning = service.register_academic(valid_form)
    assert warning.duplicate_confirmation is not None
    repository.records[0] = replace(existing, name="Snapshot cambiado")

    result = service.register_academic(valid_form, warning.duplicate_confirmation)

    assert result.error_code is AcademicErrorCode.STALE_DUPLICATE_CONFIRMATION
    assert repository.update_calls == []
    assert repository.records[0].name == "Snapshot cambiado"


def test_overwrite_persistence_failure_keeps_previous_record(
    valid_form: AcademicFormData,
) -> None:
    existing = _record()
    repository = MemoryAcademicRepository([existing])
    service = AcademicService(repository)
    warning = service.register_academic(valid_form)
    assert warning.duplicate_confirmation is not None
    repository.fail_on = "update"

    result = service.register_academic(valid_form, warning.duplicate_confirmation)

    assert result.message == PERSISTENCE_ERROR_MESSAGE
    assert repository.records == [existing]


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


@pytest.mark.parametrize("status", ["Activo", "Inactivo", "Sabático", "Terminado"])
def test_four_mvp_statuses_are_accepted(
    valid_form: AcademicFormData,
    status: str,
) -> None:
    repository = MemoryAcademicRepository()

    result = AcademicService(repository).register_academic(
        replace(valid_form, status=status)
    )

    assert result.success is True
    assert repository.records[0].status == status


def test_arbitrary_status_is_rejected_by_backend(
    valid_form: AcademicFormData,
) -> None:
    repository = MemoryAcademicRepository()

    result = AcademicService(repository).register_academic(
        replace(valid_form, status="Estado inventado")
    )

    assert result.error_code is AcademicErrorCode.INVALID_STATUS
    assert result.field_errors == {"status": INVALID_STATUS_MESSAGE}
    assert repository.add_calls == []


def test_incompatible_plant_profile_is_rejected_by_backend(
    valid_form: AcademicFormData,
) -> None:
    repository = MemoryAcademicRepository()

    result = AcademicService(repository).register_academic(
        replace(valid_form, plant="Ordinaria", profile="Docente")
    )

    assert result.error_code is AcademicErrorCode.INCOMPATIBLE_PLANT_PROFILE
    assert result.field_errors == {"profile": INCOMPATIBLE_PLANT_PROFILE_MESSAGE}
    assert repository.add_calls == []


@pytest.mark.parametrize(
    ("changes", "code", "field"),
    [
        ({"plant": "Mixta"}, AcademicErrorCode.INVALID_PLANT, "plant"),
        ({"profile": "Estándar"}, AcademicErrorCode.INVALID_PROFILE, "profile"),
    ],
)
def test_historical_or_arbitrary_catalog_keys_are_not_accepted_for_new_writes(
    valid_form: AcademicFormData,
    changes: dict[str, str],
    code: AcademicErrorCode,
    field: str,
) -> None:
    repository = MemoryAcademicRepository()

    result = AcademicService(repository).register_academic(
        replace(valid_form, **changes)
    )

    assert result.error_code is code
    assert tuple(result.field_errors) == (field,)
    assert repository.add_calls == []


def test_normal_edit_keeps_identifier_and_own_rut(
    valid_form: AcademicFormData,
) -> None:
    existing = _record()
    repository = MemoryAcademicRepository([existing])

    result = AcademicService(repository).update_academic(
        existing.academic_id,
        replace(valid_form, name="Edición sintética"),
    )

    assert result.success is True
    assert repository.records[0].academic_id == existing.academic_id
    assert repository.records[0].name == "Edición sintética"


def test_edit_cannot_take_another_records_rut(
    valid_form: AcademicFormData,
) -> None:
    edited = _record(academic_id="edited", rut="40000000-K")
    other = _record(academic_id="other", rut="12345678-5")
    repository = MemoryAcademicRepository([edited, other])

    result = AcademicService(repository).update_academic(
        edited.academic_id,
        valid_form,
    )

    assert result.error_code is AcademicErrorCode.DUPLICATE_RUT
    assert repository.update_calls == []
    assert repository.records == [edited, other]


def test_name_and_hours_policy_remains_out_of_scope() -> None:
    repository = MemoryAcademicRepository()
    form = AcademicFormData(
        name="",
        rut="12.345.678-5",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=-999,
        status="Activo",
    )

    result = AcademicService(repository).register_academic(form)

    assert result.success is True
    assert repository.records[0].name == ""
    assert repository.records[0].weekly_hours == -999


def test_delete_uses_stable_identifier_and_preserves_other_records() -> None:
    first = _record(academic_id="stable-first")
    selected = _record(academic_id="stable-selected", rut="40000000-K")
    repository = MemoryAcademicRepository([first, selected])

    result = AcademicService(repository).delete_academic(selected.academic_id)

    assert result.success is True
    assert result.message == DELETE_SUCCESS_MESSAGE
    assert repository.delete_calls == [selected.academic_id]
    assert repository.records == [first]


def test_delete_missing_record_returns_controlled_failure() -> None:
    repository = MemoryAcademicRepository([_record()])

    result = AcademicService(repository).delete_academic("missing-stable-id")

    assert result.success is False
    assert result.message == DELETE_NOT_FOUND_MESSAGE
    assert repository.records == [_record()]


def test_delete_persistence_error_returns_controlled_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    existing = _record()
    repository = MemoryAcademicRepository([existing], fail_on="delete")

    result = AcademicService(repository).delete_academic(existing.academic_id)

    assert result.success is False
    assert result.message == DELETE_PERSISTENCE_ERROR_MESSAGE
    assert repository.records == [existing]
    assert "detalle técnico de eliminación" in caplog.text
