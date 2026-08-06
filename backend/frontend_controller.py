"""Presentation adapter for the active local demonstration services."""

from __future__ import annotations

from dataclasses import replace

from backend.academic_service import ACADEMIC_ERROR_FIELDS, ACADEMIC_ERROR_MESSAGES
from backend.application_service import ApplicationService, AuthenticationRequiredError
from backend.authentication import AuthenticationError
from backend.contracts import (
    AcademicListingError,
    AssignmentListingError,
    DuplicateRutConfirmation,
    SubmissionResult,
)
from backend.git_sync import GitServiceError
from frontend.contracts import (
    AuthenticationResult,
    LoginRequest,
    RegistrationRequest,
    RegistrationResult,
    UiResult,
)


def _translated_academic_result(result: SubmissionResult) -> SubmissionResult:
    """Translate stable backend codes without interpreting catalog rules."""
    if result.error_code is None:
        return result
    message = ACADEMIC_ERROR_MESSAGES.get(result.error_code, result.message)
    field_errors = dict(result.field_errors)
    field = ACADEMIC_ERROR_FIELDS.get(result.error_code)
    if field is not None:
        field_errors[field] = message
    return replace(result, message=message, field_errors=field_errors)


class PersistentFrontendController:
    """Translate backend outcomes to safe contracts consumed by Qt views."""

    def __init__(self, application: ApplicationService) -> None:
        self.application = application

    def authenticate(self, request: LoginRequest) -> AuthenticationResult:
        try:
            session = self.application.authenticate(request.username, request.password)
        except (AuthenticationError, RuntimeError) as error:
            self.application.logout()
            return AuthenticationResult(False, str(error))
        return AuthenticationResult(
            True,
            "Sesión iniciada correctamente.",
            username=session.username,
        )

    def register_user(self, request: RegistrationRequest) -> RegistrationResult:
        if request.password != request.password_confirmation:
            message = "Las contraseñas no coinciden."
            return RegistrationResult(
                False,
                message,
                {"password_confirmation": message},
            )
        try:
            session = self.application.register_user(
                request.username,
                request.password,
            )
        except RuntimeError as error:
            return RegistrationResult(False, str(error))
        return RegistrationResult(
            True,
            "Cuenta registrada. La sesión quedó iniciada.",
            username=session.username,
        )

    def logout(self) -> None:
        self.application.logout()

    def list_academics(self):
        try:
            return tuple(self.application.list_academics())
        except RuntimeError as error:
            raise AcademicListingError(str(error)) from error

    def academic_catalogs(self):
        return self.application.academic_catalogs()

    def submit_academic(
        self,
        data,
        overwrite_confirmation: DuplicateRutConfirmation | None = None,
    ):
        try:
            result = self.application.save_academic(data, overwrite_confirmation)
        except RuntimeError as error:
            return SubmissionResult(False, str(error))
        return _translated_academic_result(result)

    def update_academic(self, academic_id, data):
        try:
            result = self.application.update_academic(academic_id, data)
        except RuntimeError as error:
            return SubmissionResult(False, str(error))
        return _translated_academic_result(result)

    def delete_academic(self, academic_id):
        try:
            return self.application.delete_academic(academic_id)
        except RuntimeError as error:
            return SubmissionResult(False, str(error))

    def list_active_academics(self):
        return tuple(self.application.list_active_academics())

    def list_assignments_by_academic(self, period_id=None):
        try:
            return tuple(self.application.list_assignments_by_academic(period_id))
        except RuntimeError as error:
            raise AssignmentListingError(str(error)) from error

    def list_periods(self):
        return tuple(self.application.list_periods())

    def create_period(self, year, term_code, start_date, end_date):
        return self.application.create_period(year, term_code, start_date, end_date)

    def list_courses(self):
        return tuple(self.application.list_courses())

    def list_offerings(self, period_id, course_id):
        return tuple(self.application.list_offerings(period_id, course_id))

    def calculate_course_assignment(self, draft):
        return self.application.calculate_course_assignment(draft)

    def create_course_assignment(self, draft):
        return self.application.create_course_assignment(draft)

    def authorize_assignment(
        self, assignment_id, approved_points, justification="Aprobación interna"
    ):
        return self.application.authorize_assignment(
            assignment_id, approved_points, justification
        )

    def adjust_assignment_points(self, assignment_id, new_points, reason):
        return self.application.adjust_assignment_points(
            assignment_id, new_points, reason
        )

    def download_information(self) -> UiResult:
        try:
            result = self.application.download_information()
        except (AuthenticationRequiredError, GitServiceError) as error:
            return UiResult(False, str(error))
        return UiResult(True, result.message)

    def upload_information(self) -> UiResult:
        try:
            result = self.application.upload_information()
        except (AuthenticationRequiredError, GitServiceError) as error:
            return UiResult(False, str(error))
        return UiResult(True, result.message)
