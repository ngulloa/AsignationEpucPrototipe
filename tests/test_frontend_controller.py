"""Tests for academic error translation at the productive UI boundary."""

from __future__ import annotations

from backend.academic_service import INVALID_STATUS_MESSAGE
from backend.contracts import (
    AcademicErrorCode,
    AcademicFormData,
    SubmissionResult,
)
from backend.frontend_controller import PersistentFrontendController


def test_controller_translates_backend_academic_code_and_field() -> None:
    class ControlledApplication:
        def save_academic(
            self,
            _data: AcademicFormData,
            _confirmation: object,
        ) -> SubmissionResult:
            return SubmissionResult(
                False,
                "internal-untranslated-message",
                {"status": "internal-untranslated-field"},
                error_code=AcademicErrorCode.INVALID_STATUS,
            )

    form = AcademicFormData(
        name="Persona sintética",
        rut="12345678-5",
        plant="Ordinaria",
        profile="Mixto",
        weekly_hours=20,
        status="Estado inventado",
    )

    result = PersistentFrontendController(ControlledApplication()).submit_academic(form)

    assert result.message == INVALID_STATUS_MESSAGE
    assert result.field_errors == {"status": INVALID_STATUS_MESSAGE}
    assert result.error_code is AcademicErrorCode.INVALID_STATUS
