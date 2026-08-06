"""Typed data contracts shared by the application layers."""

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import StrEnum

ACADEMIC_STATUSES = ("Activo", "Inactivo", "Sabático", "Terminado")


@dataclass(frozen=True, slots=True)
class AcademicStaff:
    """Stable reference entry for one type of academic staff."""

    staff_id: str
    name: str
    active: bool = True

    def __post_init__(self) -> None:
        if not self.staff_id or not self.name.strip():
            raise ValueError("La planta académica requiere identificador y nombre.")


def _percentage(value: Decimal | int | str, field_name: str) -> Decimal:
    if isinstance(value, float):
        raise TypeError(f"{field_name} no admite float binario.")
    try:
        result = value if isinstance(value, Decimal) else Decimal(value)
    except (InvalidOperation, TypeError, ValueError) as error:
        raise ValueError(f"{field_name} no es un porcentaje decimal válido.") from error
    if not result.is_finite() or result < 0 or result > 100:
        raise ValueError(f"{field_name} debe estar entre 0 y 100.")
    return result


@dataclass(frozen=True, slots=True)
class AcademicProfile:
    """Versioned workload proportions belonging to exactly one staff entry."""

    profile_id: str
    staff_id: str
    name: str
    teaching_percentage: Decimal
    management_percentage: Decimal
    research_percentage: Decimal
    allows_extra_courses: bool
    active: bool = True

    def __post_init__(self) -> None:
        if not self.profile_id or not self.staff_id or not self.name.strip():
            raise ValueError("El perfil requiere identificadores y nombre.")
        teaching = _percentage(self.teaching_percentage, "teaching_percentage")
        management = _percentage(self.management_percentage, "management_percentage")
        research = _percentage(self.research_percentage, "research_percentage")
        if teaching + management + research != Decimal(100):
            raise ValueError("Los porcentajes del perfil deben sumar 100.")
        object.__setattr__(self, "teaching_percentage", teaching)
        object.__setattr__(self, "management_percentage", management)
        object.__setattr__(self, "research_percentage", research)


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
    """Sole persisted academic entity consumed by the active application."""

    academic_id: str
    rut: str
    name: str
    plant: str
    profile: str
    weekly_hours: int
    status: str
    row_version: int = 1


@dataclass(frozen=True, slots=True)
class AcademicPeriod:
    period_id: str
    year: int
    term_code: str
    start_date: str
    end_date: str
    status_code: str


@dataclass(frozen=True, slots=True)
class Course:
    course_id: str
    course_code: str
    name: str
    level_id: str


@dataclass(frozen=True, slots=True)
class CourseOffering:
    offering_id: str
    course_id: str
    period_id: str
    section_code: str
    nrc: str = ""
    enrollment_count: int | None = None


@dataclass(frozen=True, slots=True)
class CourseAssignmentDraft:
    academic_id: str
    period_id: str
    course_id: str
    classification_code: str
    participation_percentage: Decimal
    offering_id: str | None = None
    section_code: str = ""
    nrc: str = ""
    enrollment_count: int | None = None
    demand_category_code: str | None = None


@dataclass(frozen=True, slots=True)
class AssignmentResult:
    assignment_id: str
    calculated_points: Decimal
    policy_id: str
    policy_status: str


class AcademicErrorCode(StrEnum):
    """Stable machine-readable outcomes for academic operations."""

    INVALID_RUT = "invalid_rut"
    INVALID_PLANT = "invalid_plant"
    INVALID_PROFILE = "invalid_profile"
    INCOMPATIBLE_PLANT_PROFILE = "incompatible_plant_profile"
    INVALID_STATUS = "invalid_status"
    DUPLICATE_RUT = "duplicate_rut"
    STALE_DUPLICATE_CONFIRMATION = "stale_duplicate_confirmation"
    PERSISTENCE_ERROR = "persistence_error"


@dataclass(frozen=True, slots=True)
class DuplicateRutConfirmation:
    """Identity and snapshot the user explicitly agreed to overwrite."""

    academic_id: str
    snapshot_token: str


@dataclass(frozen=True, slots=True)
class SubmissionResult:
    """Result returned by the academic registration use case."""

    success: bool
    message: str
    field_errors: dict[str, str] = field(default_factory=dict)
    error_code: AcademicErrorCode | None = None
    duplicate_confirmation: DuplicateRutConfirmation | None = None


class AcademicListingError(RuntimeError):
    """Application-level error raised when persisted academics cannot be listed."""


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    """Identity held by the process-local session after authentication."""

    username: str


@dataclass(frozen=True, slots=True)
class UpdateResult:
    """Observable result of a requested Academic.csv synchronization."""

    changed: bool
    message: str
