"""Typed data contracts shared by the application layers."""

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum

from backend.rut_validator import canonicalize_rut, is_valid_rut, normalize_rut

ACADEMIC_STATUSES = ("Activo", "Inactivo", "Sabático", "Terminado")


@dataclass(frozen=True, slots=True)
class Academic:
    """Academic identity and personal attributes, independent of appointments."""

    academic_id: str
    rut: str
    name: str
    email: str | None = None
    status: str = ""

    def __post_init__(self) -> None:
        if not self.academic_id:
            raise ValueError("El identificador académico es obligatorio.")
        normalized_rut = normalize_rut(self.rut)
        if not is_valid_rut(normalized_rut):
            raise ValueError("El RUT académico no es válido.")
        object.__setattr__(self, "rut", canonicalize_rut(normalized_rut))
        if self.status not in ACADEMIC_STATUSES:
            raise ValueError("El estado académico no es válido.")
        if self.email == "":
            object.__setattr__(self, "email", None)


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
class AcademicAppointment:
    """Historical academic appointment; it is not an activity assignment."""

    appointment_id: str
    academic_id: str
    profile_id: str
    weekly_hours: int
    start_date: date | None = None
    end_date: date | None = None

    def __post_init__(self) -> None:
        if not self.appointment_id or not self.academic_id or not self.profile_id:
            raise ValueError("El nombramiento requiere todos sus identificadores.")
        if type(self.weekly_hours) is not int:
            raise TypeError("La jornada semanal debe ser un entero.")
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date < self.start_date
        ):
            raise ValueError("La fecha de término no puede anteceder al inicio.")

    def is_current(self, on_date: date | None = None) -> bool:
        """Return whether this appointment is effective on the supplied date."""
        reference = on_date or date.today()
        return (self.start_date is None or self.start_date <= reference) and (
            self.end_date is None or self.end_date >= reference
        )


class AmbiguousAcademicAppointmentsError(ValueError):
    """More than one appointment could feed the current UI projection."""


@dataclass(frozen=True, slots=True)
class AcademicAggregate:
    """Academic identity together with its complete appointment history."""

    academic: Academic
    appointments: tuple[AcademicAppointment, ...]

    def __post_init__(self) -> None:
        identifiers: set[str] = set()
        for appointment in self.appointments:
            if appointment.academic_id != self.academic.academic_id:
                raise ValueError("El nombramiento pertenece a otro académico.")
            if appointment.appointment_id in identifiers:
                raise ValueError("El historial contiene nombramientos duplicados.")
            identifiers.add(appointment.appointment_id)

    def current_appointment(
        self, on_date: date | None = None
    ) -> AcademicAppointment | None:
        current = tuple(
            appointment
            for appointment in self.appointments
            if appointment.is_current(on_date)
        )
        if len(current) > 1:
            raise AmbiguousAcademicAppointmentsError(
                "El académico posee más de un nombramiento vigente."
            )
        return current[0] if current else None


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
    """Flattened compatibility projection consumed by the existing Qt UI."""

    academic_id: str
    rut: str
    name: str
    plant: str
    profile: str
    weekly_hours: int
    status: str


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
