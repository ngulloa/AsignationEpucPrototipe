"""Frontend controller contract."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from backend.academic_catalog import AcademicCatalogs
from backend.contracts import (
    AcademicFormData,
    AcademicRecord,
    CourseAssignmentDraft,
    DuplicateRutConfirmation,
    SubmissionResult,
)
from frontend.contracts import (
    AuthenticationResult,
    LoginRequest,
    RegistrationRequest,
    RegistrationResult,
    UiResult,
)


class FrontendController(Protocol):
    """Operations reachable from the product interface."""

    def authenticate(self, request: LoginRequest) -> AuthenticationResult: ...

    def register_user(self, request: RegistrationRequest) -> RegistrationResult: ...

    def logout(self) -> None: ...

    def list_academics(self) -> Sequence[AcademicRecord]: ...

    def academic_catalogs(self) -> AcademicCatalogs: ...

    def submit_academic(
        self,
        data: AcademicFormData,
        overwrite_confirmation: DuplicateRutConfirmation | None = None,
    ) -> SubmissionResult: ...

    def update_academic(
        self,
        academic_id: str,
        data: AcademicFormData,
    ) -> SubmissionResult: ...

    def delete_academic(self, academic_id: str) -> SubmissionResult: ...

    def download_information(self) -> UiResult: ...

    def upload_information(self) -> UiResult: ...

    def list_active_academics(self): ...

    def list_periods(self): ...

    def list_courses(self): ...

    def list_offerings(self, period_id: str, course_id: str): ...

    def calculate_course_assignment(self, draft: CourseAssignmentDraft): ...

    def create_course_assignment(self, draft: CourseAssignmentDraft): ...
