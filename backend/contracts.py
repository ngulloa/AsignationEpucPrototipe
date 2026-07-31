"""Typed data contracts shared by the application layers."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class AcademicFormData:
    """Unvalidated data collected by the academic form."""

    name: str
    rut: str
    plant: str
    profile: str
    weekly_hours: int
    status: str


@dataclass(frozen=True, slots=True)
class AcademicRecord:
    """Validated academic data with its stable persistence identifier."""

    academic_id: str
    rut: str
    name: str
    plant: str
    profile: str
    weekly_hours: int
    status: str


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """Result returned by the academic registration use case."""

    success: bool
    message: str
    field_errors: dict[str, str] = field(default_factory=dict)


class AcademicListingError(RuntimeError):
    """Application-level error raised when persisted academics cannot be listed."""
